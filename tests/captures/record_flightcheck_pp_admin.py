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

import sys

from _common import (
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
    get_dataverse_url,
)


def main() -> None:
    announce("flightcheck_pp_admin")

    env_url = get_dataverse_url()
    confirm_or_exit()

    # Kit's auth.py / pp_admin_client.py use relative paths.
    chdir_kit_root()

    import auth
    from urllib.parse import urlparse
    from flightcheck.pp_admin_client import PPAdminClient

    tenant_id = auth.discover_tenant(env_url)

    client = PPAdminClient(tenant_id=tenant_id)
    client.authenticate()

    with build_cassette("flightcheck_pp_admin"):
        envs = client.get_environments()
        print(f"  /environments: {len(envs)} envs")

        # NOTE: bypassing flightcheck.pp_admin_client.derive_environment_id
        # here because it has a known bug — it assumes the BAP environment
        # ID equals the Dataverse OrganizationId from WhoAmI(), which is
        # NOT true in practice (verified by 404 from BAP when called with
        # OrganizationId). The correct approach, used here and by the older
        # PVAClient code in PR #63, is to list environments and match by
        # properties.linkedEnvironmentMetadata.instanceUrl.
        # TODO: file an issue / fix derive_environment_id to use this logic.
        target_host = (urlparse(env_url).hostname or "").lower()
        env_id = None
        for e in envs:
            instance_url = (
                e.get("properties", {})
                .get("linkedEnvironmentMetadata", {})
                .get("instanceUrl", "")
            )
            host = (urlparse(instance_url).hostname or "").lower()
            if host == target_host:
                env_id = e.get("name")
                break
        if not env_id:
            print(f"ERROR: no BAP environment matched Dataverse host {target_host!r}.")
            sys.exit(1)
        print(f"  Resolved env_id by instanceUrl match")

        # Each subsequent call is best-effort — if any individual endpoint
        # 404s or 5xx's we want to keep capturing the others rather than
        # tank the whole cassette. The kit's _get / _get_all only handle
        # 401/403 specially; 404s and 5xx's bubble up as HTTPError. (That's
        # itself worth flagging as a robustness gap in the kit — a real
        # customer whose tenant returns 404 for an endpoint we don't expect
        # would see FlightCheck crash mid-run instead of reporting WARNING.)

        def _try(label: str, fn):
            try:
                result = fn()
                count = len(result) if isinstance(result, (list, dict)) else "?"
                print(f"  {label}: {count}")
            except Exception as exc:
                print(f"  {label}: SKIPPED — {type(exc).__name__}: {exc!s}")

        _try("/environments/{id}", lambda: client.get_environment(env_id))
        _try("/flows", lambda: client.get_flows(env_id))
        _try("/connections", lambda: client.get_connections(env_id))
        _try("/apiPolicies (DLP)", lambda: client.get_dlp_policies())

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_pp_admin.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
