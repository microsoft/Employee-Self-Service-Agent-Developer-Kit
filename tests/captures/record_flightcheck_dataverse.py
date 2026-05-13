#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the Dataverse Web API queries any future
FlightCheck check is likely to consume beyond just WhoAmI.

Pre-captures the API surface so agents adding new Dataverse-backed
checks (CONFIG-* checks reading bot/component metadata, future
integration variable checks for SAP/SuccessFactors, etc.) can promote
the dataverse mock builders without a fresh capture cycle.

Endpoints captured:
- GET /api/data/v9.2/WhoAmI()
- GET /api/data/v9.2/environmentvariabledefinitions?$select=...    (used by WD-ENV-* checks)
- GET /api/data/v9.2/environmentvariablevalues?$select=...         (used by WD-ENV-* checks)
- GET /api/data/v9.2/solutions?$select=uniquename,friendlyname,version,ismanaged
                                                                   (likely future: solution-installed checks)
- GET /api/data/v9.2/connectionreferences?$select=connectionreferencedisplayname,connectorid,connectionid
                                                                   (likely future: connection reference validation)

Usage:
    $env:ESS_DATAVERSE_URL = "https://orgb78b4a3b.crm.dynamics.com"
    python tests\\captures\\record_flightcheck_dataverse.py

Output: tests/fixtures/cassettes/flightcheck_dataverse.yaml
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
    announce("flightcheck_dataverse")
    env_url = get_dataverse_url()
    confirm_or_exit()

    chdir_kit_root()

    import auth
    import requests

    token = auth.authenticate(env_url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }

    def _try(label: str, path: str, params: dict | None = None) -> None:
        try:
            r = requests.get(
                f"{env_url}/api/data/v9.2/{path}",
                headers=headers,
                params=params,
                timeout=60,
            )
            count = "?"
            if r.status_code == 200:
                try:
                    body = r.json()
                    count = (
                        len(body.get("value", []))
                        if isinstance(body, dict) and "value" in body
                        else "(single record)"
                    )
                except ValueError:
                    pass
            print(f"  {label}: {r.status_code} ({count} rows)")
        except requests.RequestException as exc:
            print(f"  {label}: ERROR — {exc!s}")

    with build_cassette("flightcheck_dataverse"):
        _try("WhoAmI",                            "WhoAmI()")

        # Environment variable defs + values — exact selects the kit uses
        # in workday.py:_check_env_vars (cassette validates query_all
        # pagination shape).
        _try(
            "environmentvariabledefinitions",
            "environmentvariabledefinitions",
            params={
                "$select": "displayname,schemaname,environmentvariabledefinitionid",
                "$top": "20",
            },
        )
        _try(
            "environmentvariablevalues",
            "environmentvariablevalues",
            params={
                "$select": "value,schemaname,_environmentvariabledefinitionid_value",
                "$top": "20",
            },
        )

        # Solutions — likely future checks for "is the X extension pack installed?"
        _try(
            "solutions",
            "solutions",
            params={
                "$select": "uniquename,friendlyname,version,ismanaged,installedon",
                "$top": "20",
            },
        )

        # Connection references — likely future checks for connection-ref
        # name -> connection id wiring.
        _try(
            "connectionreferences",
            "connectionreferences",
            params={
                "$select": (
                    "connectionreferencedisplayname,connectionreferencelogicalname,"
                    "connectorid,connectionid"
                ),
                "$top": "20",
            },
        )

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_dataverse.yaml")
    print("for any leftover tenant-specific data before committing.")


if __name__ == "__main__":
    main()
