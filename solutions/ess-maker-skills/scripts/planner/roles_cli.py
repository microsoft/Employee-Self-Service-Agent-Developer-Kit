# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Roles CLI.

The deterministic surface the ``/roles`` skill calls to manage **people and
roles** on a plan, decoupled from the planner (which only *grounds* a role onto
a task). Everything here is WeveNova-backed (the ``weve-plan`` MCP server):

    python scripts/planner/roles_cli.py find-users --name "<display name>"
    python scripts/planner/roles_cli.py roles [--live]
    python scripts/planner/roles_cli.py attest --person <oid> --role WorkdayAdmin
    python scripts/planner/roles_cli.py assignments [--person <oid>] [--role <id>]
    python scripts/planner/roles_cli.py revoke --assignment <id>
    python scripts/planner/roles_cli.py caller-tasks --caller <oid>

A *task* is grounded on a **role** by the planner; an **attestation** binds a
named **person** (their Entra object id) to that role, scoped to the plan, so the
platform can later show that person the role's tasks (``caller-tasks``, Flow 2).

The current caller's token profile and OID come from the kit's ``.env``. To
assign a role to a *different* named person, ``find-users`` resolves their display
name to an ``aadId`` via WeveNova's ``find_users_by_name`` tool — a temporary
stand-in for Work IQ people search — that ``attest --person`` then binds.

Role strings are validated locally against the registry
(:data:`planner.roles.DEFAULT_REGISTRY`) and again by WeveNova (ordinal,
case-sensitive), so emit the exact wire id (run ``roles`` to see them).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure scripts/ is on the path so ``import planner...`` resolves when this
# file is run directly (mirrors scripts/planner/cli.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _attest_client(args: argparse.Namespace):
    """Build the role-attestation client (WeveNova only). Resolves the
    project/plan/tenant binding from args, env, or discovery."""
    from planner.attest import AttestationClient
    from planner.mcp_client import McpError, client_from_config
    from planner.plan_store import PlanStoreError, resolve_plan_binding

    try:
        client = client_from_config(
            getattr(args, "mcp_server", "weve-plan"),
            getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json")),
        )
        pid, plid, tid = resolve_plan_binding(
            client,
            project_id=getattr(args, "project_id", None),
            plan_id=getattr(args, "plan_id", None),
        )
    except (McpError, PlanStoreError) as exc:
        raise SystemExit(f"cannot reach the WeveNova plan: {exc}")
    return AttestationClient(client, plan_id=plid, tenant_id=tid, project_id=pid)


def _weve_client(args: argparse.Namespace):
    """Build a bare WeveNova MCP client for **people lookup** — no plan binding
    is needed (``find_users_by_name`` is directory-scoped, not plan-scoped), so
    this works even before a plan exists."""
    from planner.mcp_client import McpError, client_from_config

    try:
        return client_from_config(
            getattr(args, "mcp_server", "weve-plan"),
            getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json")),
        )
    except McpError as exc:
        raise SystemExit(f"cannot reach the WeveNova MCP server: {exc}")


def _users_from_payload(payload) -> list[dict]:
    """The user records out of a ``find_users_by_name`` payload, tolerating the
    documented ``{"users": [...]}`` shape, an OData ``{"value": [...]}`` envelope,
    or a bare list."""
    if isinstance(payload, dict):
        items = payload.get("users")
        if items is None:
            items = payload.get("value", payload.get("Value", []))
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [u for u in (items or []) if isinstance(u, dict)]


def _user_aad_id(user: dict) -> str:
    """The person's Entra object id (``aadId``) from a directory record."""
    return user.get("aadId") or user.get("AadId") or user.get("id") or user.get("Id") or ""


def _user_display_name(user: dict) -> str:
    return user.get("displayName") or user.get("DisplayName") or user.get("name") or ""


def _resolve_caller_id(args: argparse.Namespace) -> str | None:
    """The caller's own Entra object id for the caller-scoped task query.

    Precedence: explicit ``--caller`` → ``PLANNER_MCP_CALLER_ID`` env → the kit
    ``.env`` aadId. This must be the authenticated caller because WeveNova expands
    role-pooled tasks for the caller's own OID only."""
    caller = getattr(args, "caller", None)
    if caller and caller.strip():
        return caller.strip()
    env = os.environ.get("PLANNER_MCP_CALLER_ID")
    if env and env.strip():
        return env.strip()
    from planner.mcp_client import load_adk_identity

    _user_name, aad_id = load_adk_identity(
        getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json"))
    )
    return aad_id


def cmd_find_users(args: argparse.Namespace) -> int:
    """Resolve a person's **Entra object id (``aadId``) from a display name** via
    the WeveNova people directory (the ``find_users_by_name`` tool on the same
    ``weve-plan`` MCP the plan lives on), needing no separate sign-in. Turns
    "assign <role> to <name>" into the ``aadId`` that ``attest --person`` wants.
    Read-only. A **temporary stand-in for Work IQ** people search — same seam, same
    ``aadId`` result once Work IQ replaces it."""
    from planner.mcp_client import McpError

    client = _weve_client(args)
    try:
        payload = client.call_tool("find_users_by_name", {"name": args.name})
    except McpError as exc:
        print(f"cannot search the WeveNova people directory: {exc}", file=sys.stderr)
        return 1

    users = _users_from_payload(payload)
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0
    if not users:
        print(f"No one in the WeveNova directory matched {args.name!r}.")
        return 0
    print(f"{len(users)} match(es) for {args.name!r}:\n")
    for u in users:
        src = u.get("source")
        tag = f"  ({src})" if src else ""
        print(f"    {_user_display_name(u) or '?'}   <{_user_aad_id(u) or '?'}>{tag}")
    print("\nAttest with the aadId: "
          "`roles attest --person <aadId> --role <role>`.")
    return 0


def cmd_roles(args: argparse.Namespace) -> int:
    """List the valid WeveNova roles (the exact wire ids a task/attestation must
    use). Offline from the static catalogue by default; ``--live`` refreshes from
    the server."""
    from planner.roles import DEFAULT_REGISTRY, RoleRegistry

    registry = DEFAULT_REGISTRY
    if getattr(args, "live", False):
        from planner.mcp_client import McpError, client_from_config

        try:
            client = client_from_config(
                getattr(args, "mcp_server", "weve-plan"),
                getattr(args, "mcp_config", os.path.join(".vscode", "mcp.json")),
            )
            registry = RoleRegistry.from_mcp(client)
        except McpError as exc:
            print(f"warning: could not refresh roles from the server ({exc}); using the static catalogue", file=sys.stderr)

    if args.json:
        print(json.dumps(
            [
                {
                    "role": r.role,
                    "provider": r.provider,
                    "displayName": r.display_name,
                    "attestable": r.attestable,
                }
                for r in registry._by_id.values()  # noqa: SLF001 — CLI dump
            ],
            indent=2,
        ))
        return 0
    print("Task-groundable roles (use the exact id verbatim):\n")
    for r in registry._by_id.values():  # noqa: SLF001 — CLI dump
        tag = "  [attestable]" if r.attestable else ""
        label = r.role if r.display_name == r.role else f"{r.role}  ({r.display_name})"
        print(f"    {label}   <{r.provider}>{tag}")
    print("\nAttestable roles can be bound to a person with `roles attest`.")
    return 0


def cmd_attest(args: argparse.Namespace) -> int:
    """Attest a person (their Entra object id) to an attestable role on the plan."""
    from planner.attest import AttestationError

    client = _attest_client(args)
    try:
        rec = client.attest(
            args.person,
            args.role,
            provider=args.provider,
            idempotency_key=args.idempotency_key,
            etag=args.etag,
        )
    except AttestationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        aid = rec.get("AssignmentId") or rec.get("Id") or "?"
        print(f"Attested {args.person} to {rec.get('Role', args.role)} (assignment {aid}).")

    # A person attested to a role should also *own* that role's waiting work, so
    # its open pool doesn't sit unclaimed. Hand them the role's still-pooled tasks
    # (role grounding retained). This never displaces a task already owned by
    # someone. Assignment trouble is a soft warning — the attestation itself stood.
    if getattr(args, "assign_tasks", True):
        role_id = rec.get("Role", args.role)
        try:
            assigned = client.assign_role_pool_to_subject(args.person, role_id)
        except AttestationError as exc:
            print(f"note: {exc}", file=sys.stderr)
        else:
            if not args.json:
                if assigned:
                    print(f"Assigned {len(assigned)} pooled {role_id} task(s) to them:")
                    for t in assigned:
                        print(f"    - {t.get('Title') or t.get('TaskId')}")
                else:
                    print(f"No open {role_id} tasks were waiting in the pool to assign.")
    return 0


def cmd_assignments(args: argparse.Namespace) -> int:
    """List the plan's role assignments (who is attested to which role)."""
    from planner.attest import AttestationError

    client = _attest_client(args)
    try:
        items = client.list_assignments(
            subject_id=args.person, role=args.role, status=args.status
        )
    except AttestationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(items, indent=2))
        return 0
    if not items:
        print("No role assignments on this plan.")
        return 0
    print(f"{len(items)} role assignment(s):\n")
    for a in items:
        aid = a.get("AssignmentId") or a.get("Id") or "?"
        print(f"    {a.get('Role', '?')}  ->  {a.get('SubjectId', '?')}  "
              f"[{a.get('Status', '?')}]  ({aid})")
    return 0


def cmd_revoke(args: argparse.Namespace) -> int:
    """Revoke a role assignment on the plan."""
    from planner.attest import AttestationError

    client = _attest_client(args)
    try:
        client.revoke(args.assignment, etag=args.etag)
    except AttestationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Revoked assignment {args.assignment}.")
    return 0


def cmd_caller_tasks(args: argparse.Namespace) -> int:
    """Show the tasks a logged-in person sees on the plan: their directly-assigned
    tasks **plus** the pooled tasks for the roles they are attested to (Flow 2,
    server-resolved via WeveNova).

    Caller-scoped and **self-only**: the caller id must be the *authenticated*
    identity (the tunnel-signed-in user), resolved from ``--caller``,
    ``PLANNER_MCP_CALLER_ID``, or the kit ``.env`` aadId. WeveNova only
    expands role-pooled tasks for the caller's own OID."""
    from planner.attest import AttestationError, is_oid

    caller = _resolve_caller_id(args)
    if not caller:
        print(
            "could not resolve your caller id — set .env aadId, pass --caller, or "
            "set PLANNER_MCP_CALLER_ID. It must be YOUR authenticated identity "
            "(self-only).",
            file=sys.stderr,
        )
        return 2
    if not is_oid(caller):
        print(
            f"caller id must be an Entra object id (a GUID), got {caller!r}. "
            "This is the caller's own authenticated OID, not a display name.",
            file=sys.stderr,
        )
        return 2

    client = _attest_client(args)
    try:
        tasks = client.tasks_for_caller(caller, odata_filter=getattr(args, "filter", None))
    except AttestationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # Surface producers before the tasks that consume what they produce, so the
    # list reads in the order the work can be done (Learn order breaks ties).
    from planner.plan_model import order_tasks_by_dependency

    tasks = order_tasks_by_dependency(tasks)
    if args.json:
        print(json.dumps(tasks, indent=2))
        return 0
    if not tasks:
        print("No tasks are waiting on you right now.")
        return 0
    print(f"{len(tasks)} task(s) visible to you:\n")
    for t in tasks:
        tid = t.get("TaskId") or t.get("Id") or "?"
        print(f"    - {tid}  {t.get('Title', '')}  [{t.get('State', '?')}]")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roles", description="ESS Maker Kit roles CLI (people ↔ roles on a plan)")
    parser.add_argument("--mcp-server", dest="mcp_server", default="weve-plan", help="MCP server name in .vscode/mcp.json")
    parser.add_argument("--mcp-config", dest="mcp_config", default=os.path.join(".vscode", "mcp.json"), help="path to the MCP config")
    parser.add_argument("--project-id", dest="project_id", default=None, help="WeveNova project id; else PLANNER_MCP_PROJECT_ID or discovery")
    parser.add_argument("--plan-id", dest="plan_id", default=None, help="WeveNova plan id; else PLANNER_MCP_PLAN_ID or discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("find-users", help="resolve a person's Entra object id (aadId) from a display name via WeveNova (temporary Work IQ stand-in)")
    p.add_argument("--name", required=True, help="full or partial display name to search for (e.g. \"primary\")")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_find_users)

    p = sub.add_parser("roles", help="list the valid WeveNova roles (exact wire ids for tasks/attestations)")
    p.add_argument("--live", action="store_true", help="refresh the catalogue from the weve-plan server (else static)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_roles)

    p = sub.add_parser("attest", help="attest a person to an attestable role on the plan")
    p.add_argument("--person", required=True, help="the person's Entra object id (a GUID); for a *named* person resolve it first with `find-users`, else the caller's own .env aadId")
    p.add_argument("--role", required=True, help="an attestable role (id or display name; see `roles`)")
    p.add_argument("--provider", help="the role's owner (External/Entra/PowerPlatform); derived when omitted")
    p.add_argument("--idempotency-key", dest="idempotency_key", help="optional idempotency key for replay-safe attest")
    p.add_argument(
        "--no-assign-tasks",
        dest="assign_tasks",
        action="store_false",
        help="attest only; do NOT hand the role's open pooled tasks to the person "
             "(by default a successful attest also claims them for that person)",
    )
    p.add_argument(
        "--etag",
        help="existing role assignment's strong ETag only; omit for first attestation",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_attest)

    p = sub.add_parser("assignments", help="list the plan's role assignments")
    p.add_argument("--person", help="filter by subject (person) oid")
    p.add_argument("--role", help="filter by role (id or display name)")
    p.add_argument("--status", choices=["Active", "Revoked"], help="filter by status")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_assignments)

    p = sub.add_parser("revoke", help="revoke a role assignment on the plan")
    p.add_argument("--assignment", required=True, help="the assignment id to revoke")
    p.add_argument(
        "--etag",
        help="current assignment ETag; when omitted the assignment is read first",
    )
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("caller-tasks", help="show YOUR tasks: direct + pooled-for-your-roles (Flow 2, self-only)")
    p.add_argument(
        "--caller",
        help="YOUR own authenticated Entra object id (a GUID); defaults to "
        "PLANNER_MCP_CALLER_ID, then .env aadId. Must be the "
        "tunnel-authenticated caller because role expansion is self-only",
    )
    p.add_argument(
        "--filter",
        dest="filter",
        help="optional extra OData $filter; the caller scope is applied "
        "automatically, so don't repeat an assignedToId predicate",
    )
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_caller_tasks)

    return parser


def _configure_io() -> None:
    """Best-effort UTF-8 stdout/stderr so labels (em-dashes, etc.) print on
    Windows consoles without crashing on cp1252."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_io()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
