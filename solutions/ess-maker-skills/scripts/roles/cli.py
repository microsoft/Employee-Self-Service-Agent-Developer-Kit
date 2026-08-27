# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Roles resolver CLI.

The ``/roles`` attestation skill needs one thing the shared planner service
cannot do for it: turn a *person's name* into the Entra (AAD) object id that
the planner's role-attestation tools take as ``subjectId``. WeveNova stores
role assignments by object id, so a maker saying "make Priya the ServiceNow
admin" has to be resolved to Priya's directory object first.

This CLI owns exactly that Graph hop and nothing else. It reuses the kit's
existing Graph integration (``flightcheck.graph_client.GraphClient`` — same
MSAL app and shared token cache as FlightCheck) but asks for only the
least-privilege, user-consentable ``User.ReadBasic.All`` scope, signs the
maker in if needed, runs a directory ``$search``, and prints the candidate
list as JSON for the skill to disambiguate. Every role read/write itself
(``list_attestable_roles``, ``attest_plan_role``, ...) is a planner tool call
the skill makes directly — those never pass through here.

Usage (run from the kit root):

    python scripts/roles/cli.py resolve-person --name "Priya Sharma"
    python scripts/roles/cli.py resolve-person --name priya@contoso.com --top 5

Network: this command signs in and calls Microsoft Graph. Unlike the planner
CLI (deliberately network-free), person resolution is inherently a live
directory lookup. It requests only the least-privilege, USER-consentable
``User.ReadBasic.All`` delegated scope (not the broader admin-gated set
FlightCheck uses), so in a normal tenant a maker can grant it themselves with
no directory admin. Where a tenant blocks user consent for the Graph CLI app
outright (e.g. Microsoft corp), sign-in is refused, this CLI reports
``auth_required``, and the ``/roles`` skill falls back to the WorkIQ MCP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure scripts/ is on the path so ``import flightcheck...`` / ``import auth``
# resolve when this file is run directly (mirrors scripts/planner/cli.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import discover_tenant
from flightcheck.graph_client import GraphClient, PERSON_RESOLUTION_SCOPES

CONFIG_PATH = os.path.join(".local", "config.json")


def _load_env_url() -> str:
    """Best-effort read of the Dataverse endpoint from ``.local/config.json``.

    Used only to discover the maker's home tenant for sign-in. A missing or
    malformed config is fine — we fall back to the multi-tenant
    ``organizations`` authority so role attestation can run before ``/setup``
    has recorded an environment.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        return ""
    if isinstance(config, dict):
        return config.get("dataverseEndpoint", "") or ""
    return ""


def _shape_candidate(user: dict) -> dict:
    """Project a Graph user object down to the fields the skill needs.

    ``oid`` is the ``subjectId`` the planner's ``attest_plan_role`` tool takes;
    the rest are for the maker to disambiguate between namesakes.
    """
    return {
        "oid": user.get("id", ""),
        "displayName": user.get("displayName", ""),
        "userPrincipalName": user.get("userPrincipalName", ""),
        "mail": user.get("mail", ""),
        "jobTitle": user.get("jobTitle", ""),
    }


def resolve_person(
    name: str,
    *,
    top: int = 10,
    env_url: str | None = None,
) -> dict:
    """Resolve a person's name / email / UPN to directory candidates.

    Returns a JSON-serializable envelope::

        {"query", "status", "count", "candidates": [{oid, displayName, ...}]}

    where ``status`` is one of:

    * ``"ok"`` — one or more candidates (the skill disambiguates if >1),
    * ``"no_match"`` — the directory returned nobody for the query,
    * ``"auth_required"`` — sign-in failed, was declined, OR sign-in succeeded
      but Graph still refused the directory read with a 401/403 (the tenant
      blocks user consent for the Graph CLI app, e.g. Microsoft corp). These are
      not cleanly distinguishable, so the ``/roles`` skill gives the maker one
      chance to sign in / grant access and, if that still fails, falls back to
      the WorkIQ MCP.

    Never raises for the expected failure modes; the skill branches on
    ``status`` rather than catching exceptions.
    """
    query = (name or "").strip()
    if not query:
        return {"query": "", "status": "no_match", "count": 0, "candidates": []}

    resolved_url = env_url if env_url is not None else _load_env_url()
    tenant_id = discover_tenant(resolved_url) if resolved_url else "organizations"

    # Least-privilege, user-consentable scope — not FlightCheck's admin-gated
    # set — so resolving a name never forces the maker through an admin prompt.
    client = GraphClient(tenant_id, scopes=PERSON_RESOLUTION_SCOPES)
    try:
        client.authenticate()
    except Exception:
        # Don't surface the raw MSAL error (it can carry tenant ids / flow
        # detail — CWE-209). The skill just needs to know sign-in is required.
        return {
            "query": query,
            "status": "auth_required",
            "count": 0,
            "candidates": [],
        }

    try:
        raw = client.search_users(query, top=top)
    except PermissionError:
        # Sign-in succeeded, but the tenant won't grant even the least-privilege
        # User.ReadBasic.All to the Graph CLI app (e.g. Microsoft corp). Treat it
        # exactly like a declined sign-in so the /roles skill falls back to the
        # WorkIQ MCP instead of reporting a misleading "no match".
        return {
            "query": query,
            "status": "auth_required",
            "count": 0,
            "candidates": [],
        }

    candidates = [_shape_candidate(u) for u in raw]
    return {
        "query": query,
        "status": "ok" if candidates else "no_match",
        "count": len(candidates),
        "candidates": candidates,
    }


def _cmd_resolve_person(args: argparse.Namespace) -> int:
    result = resolve_person(args.name, top=args.top, env_url=args.env_url)
    print(json.dumps(result, indent=2))
    # Exit non-zero only when sign-in is required, so a caller can branch on it.
    # ``no_match`` is a valid, successful lookup that simply found nobody.
    return 1 if result["status"] == "auth_required" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roles",
        description="Resolve people to directory object ids for role attestation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser(
        "resolve-person",
        help="Look up a person by name / email / UPN and print candidates.",
    )
    resolve.add_argument(
        "--name",
        required=True,
        help="Person's display name, user principal name, or email.",
    )
    resolve.add_argument(
        "--top",
        type=int,
        default=10,
        help="Maximum number of candidates to return (default: 10).",
    )
    resolve.add_argument(
        "--env-url",
        default=None,
        help=(
            "Dataverse endpoint used only to discover the sign-in tenant "
            "(defaults to dataverseEndpoint in .local/config.json)."
        ),
    )
    resolve.set_defaults(func=_cmd_resolve_person)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
