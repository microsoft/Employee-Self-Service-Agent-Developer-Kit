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
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit

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
    # Don't double-append @tenant if the user already included it in
    # WORKDAY_ISU_USER. Workday SSO accounts are usually written
    # alias@contoso.com@tenantname; ISU service accounts are usually
    # bare ISU_NAME (no @). Either way, append the tenant suffix only
    # if it's not already there.
    isu = env["WORKDAY_ISU_USER"]
    tenant_suffix = "@" + env["WORKDAY_TENANT_NAME"]
    if not isu.endswith(tenant_suffix):
        isu = isu + tenant_suffix
    user = xml_escape(isu)
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

    # Production code uses relative paths — switch cwd before invoking it.
    chdir_kit_root()

    import requests
    from flightcheck.checks.workday import WORKFLOWS

    # Auto-convert known web hosts to their SOAP equivalents. Workday's
    # web URL (the one in your browser address bar) is NOT the same as
    # the SOAP service URL — the SOAP cluster has "-services1" inserted
    # before the .workday.com / .myworkday.com part. People intuitively
    # set WORKDAY_TENANT_HOST to the URL they see in the browser; this
    # fixes that for the known mappings rather than failing with
    # confusing HTML 404 errors.
    raw_host = env["WORKDAY_TENANT_HOST"].rstrip("/")
    web_to_soap = {
        "https://impl.workday.com": "https://wd2-impl-services1.workday.com",
        "https://wd5.myworkday.com": "https://wd5-services1.myworkday.com",
        "https://wd3.myworkday.com": "https://wd3-services1.myworkday.com",
        "https://wd2.myworkday.com": "https://wd2-services1.myworkday.com",
    }
    soap_host = web_to_soap.get(raw_host, raw_host)
    if soap_host != raw_host:
        print(f"  Note: rewrote web host {raw_host} -> SOAP host {soap_host}")

    base_url = f"{soap_host}/ccx/service/{env['WORKDAY_TENANT_NAME']}"
    print(f"  Will POST to: {base_url}/<service>/v40.0")
    print()

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
                # On non-200, surface the SOAP fault message inline so the
                # operator can diagnose without opening the cassette. The
                # full response is in the cassette either way.
                if r.status_code != 200:
                    snippet = r.text[:400].replace("\n", " ")
                    # Try to extract just the faultstring for cleaner output.
                    m = re.search(r"<faultstring[^>]*>(.*?)</faultstring>", r.text, re.DOTALL)
                    if m:
                        print(f"    fault: {m.group(1).strip()[:200]}")
                    else:
                        print(f"    body[:200]: {snippet[:200]}")
            except requests.RequestException as exc:
                print(f"  {wf['name']:30s} → ERROR ({exc!s})")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_workday.yaml")
    print("CAREFULLY for any leftover ISU credentials, employee names, or worker IDs")
    print("before committing. Workday SOAP responses can include nested PII even on")
    print("simple worker lookups.")


if __name__ == "__main__":
    main()
