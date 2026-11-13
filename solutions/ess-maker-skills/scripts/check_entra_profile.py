# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read standard Entra profile attributes and report presence, never their values."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import UUID

import requests

from flightcheck.graph_client import GraphClient, GraphPermissionError
from flightcheck.entra_profile import ATTRIBUTES, SCOPES, check_attributes, permission_unavailable_report


def _tenant(value: str) -> str:
    if value == "organizations":
        return value
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a tenant GUID or organizations.") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=SCOPES, default="me", help="Default: current profile only.")
    parser.add_argument("--tenant-id", type=_tenant, default="organizations")
    parser.add_argument("--preferred-username", help="Require this signed-in account; never stored in the report.")
    parser.add_argument("--attributes", nargs="+", choices=ATTRIBUTES, default=list(ATTRIBUTES))
    parser.add_argument("--output", type=Path, help="Optional aggregate-only JSON report.")
    args = parser.parse_args(argv)
    try:
        client = GraphClient(args.tenant_id, strict_reads=True)
        with redirect_stdout(sys.stderr):
            client.authenticate(
                preferred_username=args.preferred_username,
                scopes=SCOPES[args.scope],
                **({"require_existing_consent": True} if args.scope == "tenant" else {}),
            )
        if args.preferred_username and (
            not client.signed_in_username
            or client.signed_in_username.casefold() != args.preferred_username.casefold()
        ):
            raise ValueError("Authentication selected a different or unverifiable account; no profile was read.")
        client.verify_identity(args.preferred_username)
        report = check_attributes(client, args.scope, args.attributes)
        code = int(report["status"] == "Warning")
    except GraphPermissionError:
        if args.scope == "tenant":
            report, code = permission_unavailable_report(), 1
        else:
            report = {"status": "Error", "scope": args.scope, "error": "The Graph profile read was denied; User.Read is required."}
            code = 2
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else "unavailable"
        report = {"status": "Error", "scope": args.scope, "error": f"Graph request failed ({type(exc).__name__}; HTTP {status})."}
        code = 2
    except (OSError, RuntimeError, ValueError) as exc:
        report = {"status": "Error", "scope": args.scope, "error": str(exc)}
        code = 2
    report["schemaVersion"] = "entra-profile-check.v1"
    report["checkedAt"] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: Cannot write the report ({type(exc).__name__}).", file=sys.stderr)
            return 2
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
