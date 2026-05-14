#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering FlightCheck's Microsoft Graph queries.

Exercises:
- /v1.0/organization                          (get_organization)
- /v1.0/users?$top=10                         (get_users_sample)
- /v1.0/directoryRoles                        (get_directory_roles)
- /v1.0/identity/conditionalAccess/policies   (best-effort; may 403 in some tenants)
- /v1.0/subscribedSkus                        (license inventory)
- /v1.0/servicePrincipals                     (service principal inventory)
- /v1.0/external/connections                  (M365 Copilot Connectors — ServiceNow Knowledge etc.)
- /v1.0/external/connections/{id}             (per-connector detail with state)
- /v1.0/external/connections/{id}/schema      (published schema)
- /v1.0/external/connections/{id}/operations  (recent crawl operations)
- /v1.0/external/connections/{id}/items?$top=1 (proof of indexed content)

The /external/connections* drilldowns only run if at least one connector
exists in the tenant. If none exist, the empty-list shape is captured —
which is itself a useful state for a future check that detects "Copilot
Connector not registered yet."

The /external/connections* calls require the `ExternalConnection.Read.All`
delegated permission. Most M365 admins (Global Admin, Search Administrator)
have it. If the calling account doesn't, GraphClient.get returns a 403
shape — also captured in the cassette as a valid state.

Output: tests/fixtures/cassettes/flightcheck_graph.yaml
"""

from __future__ import annotations

import sys

from _common import (
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
    get_dataverse_url,
)


def main() -> None:
    announce("flightcheck_graph")

    # Tenant ID is derivable from the Dataverse env URL via
    # auth.discover_tenant.
    env_url = get_dataverse_url()

    confirm_or_exit()

    # The kit's auth.py uses relative paths (.local/...) — switch cwd
    # before importing or calling production code.
    chdir_kit_root()

    import auth
    from flightcheck.graph_client import GraphClient

    tenant_id = auth.discover_tenant(env_url)
    client = GraphClient(tenant_id=tenant_id)
    client.authenticate()  # populates token cache for the cassette session

    with build_cassette("flightcheck_graph"):
        org = client.get_organization()
        print(f"  /organization: {len(org)} fields")

        users = client.get_users_sample(top=10)
        print(f"  /users?$top=10: {len(users)} users")

        roles = client.get_directory_roles()
        print(f"  /directoryRoles: {len(roles)} roles")

        cap = client.get_conditional_access_policies()
        print(f"  /identity/conditionalAccess/policies: {len(cap)} policies (may be empty if 403)")

        # Pre-capture endpoints likely future checks will need (license
        # validation, app-registration validation). The kit doesn't read
        # these yet but pre-capturing avoids a cassette-cycle the next
        # time someone adds a check that does.
        try:
            skus = client.get_subscribed_skus()
            print(f"  /subscribedSkus: {len(skus)} SKUs")
        except Exception as exc:
            print(f"  /subscribedSkus: SKIPPED — {exc!s}")

        try:
            # $top=10 keeps the cassette small; we only need the response
            # shape, not the full SP inventory (some tenants have 1000s).
            # $select trims each record to fields a check would actually
            # consume (id / appId / displayName / appOwnerOrganizationId).
            sps_response = client.get(
                "/servicePrincipals"
                "?$top=10"
                "&$select=id,appId,displayName,appOwnerOrganizationId"
            )
            sps = sps_response.get("value", []) if isinstance(sps_response, dict) else []
            print(f"  /servicePrincipals?$top=10: {len(sps)} service principals")
        except Exception as exc:
            print(f"  /servicePrincipals: SKIPPED — {exc!s}")

        # Microsoft 365 Copilot Connectors (/external/connections).
        # Backs a future "is the customer's external connector registered
        # and healthy" check — the Microsoft side of the ServiceNow
        # Knowledge Connector setup that flightcheck_servicenow.yaml
        # already validates the ServiceNow side of.
        #
        # Requires `ExternalConnection.Read.All` delegated permission.
        # GraphClient.get / get_all returns a {"_error": ..., "_status": 403}
        # shape on insufficient permissions, which we capture as well.
        try:
            conns = client.get_all("/external/connections")
            print(f"  /external/connections: {len(conns)} connector(s)")

            # Drill into the FIRST connector only. We only need the
            # response SHAPE for future checks; iterating all of them
            # bloats the cassette with no extra information.
            for c in conns[:1]:
                cid = c.get("id")
                if not cid:
                    continue
                detail = client.get(f"/external/connections/{cid}")
                if isinstance(detail, dict) and detail.get("_error"):
                    print(f"    [{cid}] detail: {detail['_error']} (status={detail.get('_status')})")
                else:
                    print(
                        f"    [{cid}] state={detail.get('state')!r}, "
                        f"name={detail.get('name')!r}"
                    )

                schema = client.get(f"/external/connections/{cid}/schema")
                if isinstance(schema, dict) and not schema.get("_error"):
                    props = schema.get("properties", []) or []
                    print(f"    [{cid}] schema: {len(props)} properties")

                ops = client.get_all(
                    f"/external/connections/{cid}/operations"
                    "?$top=5&$orderby=startTime desc"
                )
                print(f"    [{cid}] recent operations: {len(ops)}")
                if ops:
                    print(
                        f"      latest: status={ops[0].get('status')!r}, "
                        f"type={ops[0].get('type')!r}"
                    )

                # $top=1 keeps the cassette small; we just need the
                # presence-or-absence + item shape.
                items = client.get(f"/external/connections/{cid}/items?$top=1")
                if isinstance(items, dict) and items.get("_error"):
                    print(f"    [{cid}] items: {items['_error']}")
                else:
                    val = items.get("value", []) if isinstance(items, dict) else []
                    print(f"    [{cid}] items (top 1): {len(val)}")
        except Exception as exc:
            print(f"  /external/connections: SKIPPED — {exc!s}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_graph.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
