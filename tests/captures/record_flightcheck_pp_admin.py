#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering FlightCheck's Power Platform Admin (BAP +
PowerApps) queries.

Exercises:
- BAP /environments                         (get_environments)
- BAP /environments/{id}                    (get_environment for the configured env)
- PowerApps /flows                          (get_flows)
- PowerApps /connections                    (get_connections)
- BAP /apiPolicies (DLP)                    (get_dlp_policies)

Output: tests/fixtures/cassettes/flightcheck_pp_admin.yaml
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import REPO_ROOT, announce, build_cassette, confirm_or_exit


def main() -> None:
    announce("flightcheck_pp_admin")

    config_path = REPO_ROOT / "solutions" / "ess-maker-skills" / ".local" / "config.json"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found. Run /setup first.")
        sys.exit(1)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    env_url = cfg.get("dataverseEndpoint")
    if not env_url:
        print("ERROR: config.json missing dataverseEndpoint.")
        sys.exit(1)

    confirm_or_exit()

    import auth
    from flightcheck.pp_admin_client import PPAdminClient, derive_environment_id

    tenant_id = auth.discover_tenant(env_url)
    dv_token = auth.authenticate(env_url)

    client = PPAdminClient(tenant_id=tenant_id)
    client.authenticate()
    env_id = derive_environment_id(env_url, dv_token)
    if not env_id:
        print("ERROR: could not derive Power Platform env id from Dataverse env.")
        sys.exit(1)

    with build_cassette("flightcheck_pp_admin"):
        envs = client.get_environments()
        print(f"  /environments: {len(envs)} envs")

        env = client.get_environment(env_id)
        print(f"  /environments/{{id}}: {len(env)} fields")

        flows = client.get_flows(env_id)
        print(f"  /flows: {len(flows)} flows")

        conns = client.get_connections(env_id)
        print(f"  /connections: {len(conns)} connections")

        try:
            dlp = client.get_dlp_policies()
            print(f"  /apiPolicies (DLP): {len(dlp)} policies")
        except Exception as e:
            print(f"  /apiPolicies (DLP): skipped ({e!s})")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_pp_admin.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
