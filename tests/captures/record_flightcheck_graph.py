#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering FlightCheck's Microsoft Graph queries.

Exercises:
- /v1.0/organization                  (get_organization)
- /v1.0/users?$top=10                  (get_users_sample)
- /v1.0/directoryRoles                 (get_directory_roles)
- /v1.0/identity/conditionalAccess/policies (best-effort; may 403 in some tenants)

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
            sps = client.get_service_principals()
            print(f"  /servicePrincipals: {len(sps)} service principals")
        except Exception as exc:
            print(f"  /servicePrincipals: SKIPPED — {exc!s}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_graph.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
