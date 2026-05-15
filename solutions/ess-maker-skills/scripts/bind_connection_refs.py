# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Bind Connection References to Connections

PATCHes Dataverse connectionreference rows to point at connections created
by create_connection.py. Required after every ISV solution install so flows
can use the connections at runtime.

Usage:
    python scripts/bind_connection_refs.py \\
        --env-id <guid> --env-url <url> \\
        --workday-connection <guid> --dataverse-connection <guid>

    python scripts/bind_connection_refs.py --env-id <guid> --env-url <url> \\
        --mapping bindings.json   # {"workday": "<guid>", "dataverse": "<guid>"}

Exit codes: 0 success, 1 auth, 2 PATCH failed, 3 unexpected.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("ERROR: requests required. Run: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(3)

from auth import authenticate, query_all


# Purpose key -> connector unique names (exact match on last path segment
# of connectorid, e.g. "/providers/Microsoft.PowerApps/apis/shared_workdaysoap").
CONNECTOR_UNIQUE_NAMES = {
    "workday": {"shared_workdaysoap"},
    "dataverse": {"shared_commondataserviceforapps", "shared_commondataservice"},
    "servicenow": {"shared_service-now", "shared_servicenowhrservicedelivery"},
    "successfactors": {"shared_sapsuccessfactors"},
}


def _connector_unique_name(connectorid):
    """Extract the trailing unique name from a connectorid URL or raw name."""
    if not connectorid:
        return ""
    return connectorid.rstrip("/").rsplit("/", 1)[-1].lower()


def classify_connection_refs(refs):
    """Group connection refs by purpose key via exact connector unique-name match."""
    grouped = {}
    for ref in refs:
        unique_name = _connector_unique_name(ref.get("connectorid"))
        for key, names in CONNECTOR_UNIQUE_NAMES.items():
            if unique_name in names:
                grouped.setdefault(key, []).append(ref)
                break
    return grouped


def patch_connection_ref(env_url, token, ref_id, connection_id):
    """PATCH a connectionreference to bind it to a connection."""
    url = f"{env_url.rstrip('/')}/api/data/v9.2/connectionreferences({ref_id})"
    body = {"connectionid": connection_id}
    resp = requests.patch(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "If-Match": "*",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        },
        json=body,
        timeout=30,
    )
    return resp


def main():
    parser = argparse.ArgumentParser(description="Bind connection references to existing connections in a Power Platform env")
    parser.add_argument("--env-id", required=True, help="Env GUID (recorded in output JSON for downstream correlation)")
    parser.add_argument("--env-url", required=True, help="Dataverse env URL, e.g. https://orgxyz.crm.dynamics.com")
    parser.add_argument("--workday-connection", help="Workday connection GUID")
    parser.add_argument("--dataverse-connection", help="Dataverse connection GUID")
    parser.add_argument("--mapping", help="JSON file with {purpose-key: connection-guid} mapping (overrides --*-connection flags)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing connection binding without asking. Default is to skip refs that are already bound to a different connection.")
    args = parser.parse_args()

    # Build the connection mapping.
    mapping = {}
    if args.mapping:
        with open(args.mapping, "r", encoding="utf-8") as f:
            mapping = json.load(f)
    else:
        if args.workday_connection:
            mapping["workday"] = args.workday_connection
        if args.dataverse_connection:
            mapping["dataverse"] = args.dataverse_connection

    if not mapping:
        print("ERROR: no connection bindings specified. Use --workday-connection / --dataverse-connection or --mapping.", file=sys.stderr)
        sys.exit(2)

    token = authenticate(args.env_url)

    # Query ESS / Workday ISV connection refs only (by logical name prefix).
    ess_filter = (
        "startswith(connectionreferencelogicalname,'msdyn_ess') "
        "or startswith(connectionreferencelogicalname,'msdyn_copilotforemployeeselfservice') "
        "or startswith(connectionreferencelogicalname,'new_sharedworkdaysoap') "
        "or startswith(connectionreferencelogicalname,'msviess_shared')"
    )
    refs = query_all(
        args.env_url,
        token,
        "connectionreferences",
        "connectionreferenceid,connectionreferencelogicalname,connectionreferencedisplayname,connectorid,statuscode,connectionid",
        ess_filter,
    )
    print(f"Discovered {len(refs)} connection references in env", file=sys.stderr)

    grouped = classify_connection_refs(refs)

    results = []
    failures = []

    for purpose_key, connection_id in mapping.items():
        candidate_refs = grouped.get(purpose_key, [])
        if not candidate_refs:
            # Expected for some ISVs (e.g. Workday has no Dataverse ref).
            results.append({
                "purpose": purpose_key,
                "connectionId": connection_id,
                "status": "no-refs-in-solution",
                "reason": f"no connection refs found matching connector(s): {CONNECTOR_UNIQUE_NAMES.get(purpose_key, {purpose_key})}",
            })
            continue

        for ref in candidate_refs:
            ref_id = ref.get("connectionreferenceid")
            ref_name = ref.get("connectionreferencelogicalname", "")
            existing = ref.get("connectionid")

            # Idempotency: skip if already bound to the target; require --force for different.
            if existing:
                existing_lower = str(existing).replace("-", "").lower()
                target_lower = str(connection_id).replace("-", "").lower()
                if existing_lower == target_lower:
                    print(f"Skipping {ref_name}: already bound to target connection.", file=sys.stderr)
                    results.append({
                        "purpose": purpose_key,
                        "refId": ref_id,
                        "refLogicalName": ref_name,
                        "connectionId": connection_id,
                        "status": "already-bound",
                    })
                    continue
                if not args.force:
                    print(f"Skipping {ref_name}: already bound to a different connection ({existing}). Use --force to overwrite.", file=sys.stderr)
                    results.append({
                        "purpose": purpose_key,
                        "refId": ref_id,
                        "refLogicalName": ref_name,
                        "connectionId": connection_id,
                        "currentConnectionId": existing,
                        "status": "skipped-already-bound",
                    })
                    continue

            print(f"Binding {ref_name} -> connection {connection_id}", file=sys.stderr)
            resp = patch_connection_ref(args.env_url, token, ref_id, connection_id)

            if resp.status_code in (200, 204):
                results.append({
                    "purpose": purpose_key,
                    "refId": ref_id,
                    "refLogicalName": ref_name,
                    "connectionId": connection_id,
                    "status": "bound",
                })
            else:
                results.append({
                    "purpose": purpose_key,
                    "refId": ref_id,
                    "refLogicalName": ref_name,
                    "connectionId": connection_id,
                    "status": f"failed: {resp.status_code}",
                    "body": resp.text[:400],
                })
                failures.append({
                    "purpose": purpose_key,
                    "refId": ref_id,
                    "refLogicalName": ref_name,
                    "connectionId": connection_id,
                    "reason": f"PATCH returned {resp.status_code}: {resp.text[:200]}",
                })

    output = {
        "envId": args.env_id,
        "envUrl": args.env_url,
        "totalRefsInEnv": len(refs),
        "bindings": results,
        "failures": failures,
    }
    print(json.dumps(output, indent=2))

    # "already-bound" to target is OK; "skipped-already-bound" to a different
    # connection means the caller's intent was not fulfilled.
    incomplete = [r for r in results if r.get("status") == "skipped-already-bound"]
    sys.exit(0 if not failures and not incomplete else 2)


if __name__ == "__main__":
    main()
