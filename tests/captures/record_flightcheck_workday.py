#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering FlightCheck's Workday SOAP workflow tests.

Iterates the 17 ESS workflows defined in
solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py:WORKFLOWS,
sends each SOAP request to the configured Workday tenant, and records the
request/response pairs.

Output: tests/fixtures/cassettes/flightcheck_workday.yaml

⚠️ This wrapper is the most likely to need per-tenant tweaks — Workday
ISU credentials, tenant subdomain, employee ID under test all vary. Set:

    $env:WORKDAY_TENANT_HOST = "https://wd2-impl-services1.workday.com"
    $env:WORKDAY_TENANT_NAME = "yourtenant"
    $env:WORKDAY_ISU_USER    = "ISU_ESS@yourtenant"
    $env:WORKDAY_ISU_PASS    = "..."   # use a secret manager, not a literal
    $env:WORKDAY_TEST_EMP_ID = "21001" # an employee ID known to exist

before running. The wrapper exits with a clear error message if any
required env var is missing.

WS-Security passwords are scrubbed by the inline redactor in _common.py
before the cassette hits disk.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from _common import announce, build_cassette, confirm_or_exit

REQUIRED_ENV = (
    "WORKDAY_TENANT_HOST",
    "WORKDAY_TENANT_NAME",
    "WORKDAY_ISU_USER",
    "WORKDAY_ISU_PASS",
    "WORKDAY_TEST_EMP_ID",
)


def _check_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("ERROR: missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        print()
        print("Set them and re-run. See the docstring at the top of this file.")
        sys.exit(1)
    return {name: os.environ[name] for name in REQUIRED_ENV}


def _build_envelope(workflow: dict, env: dict[str, str]) -> str:
    """Build a single SOAP envelope for one workflow definition.

    The exact envelope shape mirrors what
    flightcheck.checks.workday._test_workflow uses. Keep this in sync with
    that module if the workflow definitions change.
    """
    user = xml_escape(f"{env['WORKDAY_ISU_USER']}@{env['WORKDAY_TENANT_NAME']}")
    pwd = xml_escape(env["WORKDAY_ISU_PASS"])
    emp_id = xml_escape(env["WORKDAY_TEST_EMP_ID"])
    response_group = workflow.get("response_group", "")

    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:bsvc="urn:com.workday/bsvc">
  <soapenv:Header>
    <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
      <wsse:UsernameToken>
        <wsse:Username>{user}</wsse:Username>
        <wsse:Password>{pwd}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    <bsvc:Get_Workers_Request bsvc:version="v40.0">
      <bsvc:Request_References>
        <bsvc:Worker_Reference>
          <bsvc:ID bsvc:type="Employee_ID">{emp_id}</bsvc:ID>
        </bsvc:Worker_Reference>
      </bsvc:Request_References>
      <bsvc:Response_Group>{response_group}</bsvc:Response_Group>
    </bsvc:Get_Workers_Request>
  </soapenv:Body>
</soapenv:Envelope>"""


def main() -> None:
    announce("flightcheck_workday")
    env = _check_env()
    confirm_or_exit()

    import requests
    from flightcheck.checks.workday import WORKFLOWS

    base_url = (
        f"{env['WORKDAY_TENANT_HOST'].rstrip('/')}/ccx/service/"
        f"{env['WORKDAY_TENANT_NAME']}"
    )

    with build_cassette("flightcheck_workday"):
        # Cap to the first 3 workflows by default; flip this to len(WORKFLOWS)
        # once you've verified the recording works end-to-end.
        limit = int(os.environ.get("WORKDAY_RECORD_LIMIT", "3"))
        for wf in WORKFLOWS[:limit]:
            url = f"{base_url}/{wf['service']}/v40.0"
            envelope = _build_envelope(wf, env)
            try:
                r = requests.post(
                    url,
                    data=envelope.encode("utf-8"),
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    timeout=60,
                )
                print(f"  {wf['name']:30s} → {r.status_code}")
            except requests.RequestException as exc:
                print(f"  {wf['name']:30s} → ERROR ({exc!s})")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_workday.yaml")
    print("CAREFULLY for any leftover ISU credentials, employee names, or worker IDs")
    print("before committing. Workday SOAP responses can include nested PII even on")
    print("simple worker lookups.")


if __name__ == "__main__":
    main()
