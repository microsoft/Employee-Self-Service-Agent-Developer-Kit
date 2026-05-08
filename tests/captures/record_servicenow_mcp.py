#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the ServiceNow MCP server's Table API queries.

Exercises a representative slice of the ServiceNow client:
- search_incidents (last 5)
- search_hr_cases (last 5)
- query_table('cmdb_ci', limit=5)
- get_record on whatever the first incident is

⚠️ Requires a ServiceNow developer instance and credentials. Set:

    $env:SERVICENOW_INSTANCE = "https://devNNNNN.service-now.com"
    $env:SERVICENOW_USER     = "admin"
    $env:SERVICENOW_PASS     = "..."   # use a secret manager, not a literal

Output: tests/fixtures/cassettes/servicenow_mcp.yaml
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _common import announce, build_cassette, confirm_or_exit

REQUIRED_ENV = ("SERVICENOW_INSTANCE", "SERVICENOW_USER", "SERVICENOW_PASS")


def main() -> None:
    announce("servicenow_mcp")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("ERROR: missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    confirm_or_exit()

    # The MCP server's client uses httpx, which vcrpy also intercepts.
    # We import here so the pythonpath wiring in _common is in effect.
    from client import ServiceNowClient  # src/mcp/servicenow/client.py

    sn = ServiceNowClient()  # reads SERVICENOW_* from env

    with build_cassette("servicenow_mcp"):
        try:
            incidents = sn.search_incidents(limit=5)
            print(f"  search_incidents: {len(incidents.get('result', []))} records")
        except Exception as e:
            print(f"  search_incidents: ERROR {e!s}")

        try:
            cases = sn.search_hr_cases(limit=5)
            print(f"  search_hr_cases: {len(cases.get('result', []))} records")
        except Exception as e:
            print(f"  search_hr_cases: ERROR {e!s}")

        try:
            cmdb = sn.query_table("cmdb_ci", limit=5)
            print(f"  query_table(cmdb_ci): {len(cmdb.get('result', []))} records")
        except Exception as e:
            print(f"  query_table(cmdb_ci): ERROR {e!s}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/servicenow_mcp.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
