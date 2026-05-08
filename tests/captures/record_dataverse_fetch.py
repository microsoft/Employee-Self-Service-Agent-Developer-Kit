#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the Dataverse calls fetch_and_setup.py makes.

Exercises:
- WhoAmI()
- bot definition retrieval (msdyn_copilots / msdyn_copilotcomponents)
- a few EntityDefinitions queries
- the per-component download loop (a small slice — first N components only)

Usage:
    python tests/captures/record_dataverse_fetch.py

Output: tests/fixtures/cassettes/dataverse_fetch.yaml
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import REPO_ROOT, announce, build_cassette, confirm_or_exit


def main() -> None:
    announce("dataverse_fetch")

    config_path = REPO_ROOT / "solutions" / "ess-maker-skills" / ".local" / "config.json"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found. Run /setup first.")
        sys.exit(1)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    env_url = cfg.get("dataverseEndpoint")
    bot_id = cfg.get("agent", {}).get("botId")
    if not env_url or not bot_id:
        print("ERROR: config.json missing dataverseEndpoint or agent.botId.")
        sys.exit(1)

    confirm_or_exit()

    import auth
    import requests

    token = auth.authenticate(env_url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }

    with build_cassette("dataverse_fetch"):
        # 1. WhoAmI
        r = requests.get(f"{env_url}/api/data/v9.2/WhoAmI()", headers=headers, timeout=30)
        r.raise_for_status()
        print(f"  WhoAmI: {r.status_code}")

        # 2. Bot record
        r = requests.get(
            f"{env_url}/api/data/v9.2/bots({bot_id})",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        print(f"  bots({{bot_id}}): {r.status_code}")

        # 3. Bot components — just the first page, no need to capture every component
        r = requests.get(
            f"{env_url}/api/data/v9.2/botcomponents",
            headers=headers,
            params={
                "$select": "botcomponentid,name,componenttype,schemaname",
                "$filter": f"_parentbotid_value eq {bot_id}",
                "$top": "10",
            },
            timeout=30,
        )
        r.raise_for_status()
        print(f"  botcomponents (first page): {r.status_code}")

        # 4. EntityDefinitions for environment variable definitions
        r = requests.get(
            f"{env_url}/api/data/v9.2/EntityDefinitions(LogicalName='environmentvariabledefinition')",
            headers=headers,
            params={"$select": "LogicalName,SchemaName"},
            timeout=30,
        )
        r.raise_for_status()
        print(f"  EntityDefinitions: {r.status_code}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/dataverse_fetch.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
