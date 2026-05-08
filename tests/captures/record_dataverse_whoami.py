#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a Dataverse WhoAmI() cassette.

Smallest possible recording — a single GET to WhoAmI(). Useful as a smoke
test that the recording pipeline works end-to-end before running the
heavier wrappers.

Pre-reqs: .local/config.json must be set up (run /setup once) and a valid
token must already be in .local/.token_cache.bin (run any kit script that
authenticates and you'll have one).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import REPO_ROOT, announce, build_cassette, confirm_or_exit


def main() -> None:
    announce("dataverse_whoami")

    # Read the real env URL from config so we hit the right tenant.
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

    # Import the production code AFTER pyproject pythonpath wiring has been
    # applied by _common.
    import auth  # solutions/ess-maker-skills/scripts/auth.py
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
