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

import json
import sys
from pathlib import Path

from _common import REPO_ROOT, announce, build_cassette, confirm_or_exit


def main() -> None:
    announce("flightcheck_graph")

    config_path = REPO_ROOT / "solutions" / "ess-maker-skills" / ".local" / "config.json"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found. Run /setup first.")
        sys.exit(1)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))

    # Tenant ID is derivable from the env URL via auth.discover_tenant.
    env_url = cfg.get("dataverseEndpoint")
    if not env_url:
        print("ERROR: config.json missing dataverseEndpoint.")
        sys.exit(1)

    confirm_or_exit()

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

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_graph.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
