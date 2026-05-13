#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a Dataverse WhoAmI() cassette.

Smallest possible recording — a single GET to WhoAmI(). Useful as a smoke
test that the recording pipeline works end-to-end before running the
heavier wrappers.

In FlightCheck scope because pp_admin_client.derive_environment_id()
(called during FlightCheck startup to translate the Dataverse env URL
into a Power Platform environment ID) hits WhoAmI as its first step.

Usage:
    $env:ESS_DATAVERSE_URL = "https://orgb78b4a3b.crm.dynamics.com"
    python tests\\captures\\record_dataverse_whoami.py

A browser pops on first run for MSAL interactive auth; subsequent runs
read the silent token from solutions/ess-maker-skills/.local/.token_cache.bin
(created on demand). No /setup required.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import (
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
    get_dataverse_url,
)


def main() -> None:
    announce("dataverse_whoami")

    env_url = get_dataverse_url()
    confirm_or_exit()

    # The kit's auth.py uses relative paths (.local/.token_cache.bin) and
    # assumes cwd is the kit root, not the repo root. Switch before any
    # production-code import or call.
    chdir_kit_root()

    import auth
    import requests

    token = auth.authenticate(env_url)

    with build_cassette("dataverse_whoami"):
        resp = requests.get(
            f"{env_url}/api/data/v9.2/WhoAmI()",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        print(f"WhoAmI returned {resp.status_code}")
        print(f"  keys: {sorted(resp.json().keys())}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/dataverse_whoami.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
