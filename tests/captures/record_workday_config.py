#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the Workday SOAP admin queries that future
FlightCheck *configuration validation* checks would consume.

Distinct from tests/captures/record_flightcheck_workday.py, which
captures the Workday SOAP *runtime* queries (Get_Workers and friends —
what topics call at runtime to fetch employee data).

This wrapper captures the admin queries needed to validate that the
configuration steps in the MS Learn Workday integration docs were
performed correctly:

  - https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday-simplified-setup
  - https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday  (legacy)

Endpoints captured (simplified setup, always on):
  - Workday SOAP Get_API_Clients_Request (Identity_Management/v40.0)
       → validates Task 4 (Register API Client) — confirms client
         exists with the right Common v1 (REST) + SOAP scopes
  - Workday SOAP Get_Authentication_Policies_Request (Identity_Management/v40.0)
       → validates Task 3 (Manage authentication policies) — confirms
         SAML auth is enabled for the OAuth client / ISU users

Endpoints captured (legacy setup, opt-in via WORKDAY_RECORD_LEGACY=1):
  - Workday SOAP Get_Integration_System_Users_Request (Human_Resources/v40.0)
       → validates Task 3 (Create ISU) — confirms ISU_WQL_COPILOT and
         ISU_Generic_COPILOT exist
  - Workday SOAP Get_Integration_System_Security_Groups_Request
       → validates Task 3 — confirms ISSG security groups exist
  - Workday SOAP Get_Domain_Security_Policies_Request
       → validates Task 6 — confirms domain permissions on each ISSG

Out of scope for this wrapper (capture separately):
  - Workday REST GET /ccx/api/v1/{tenant}/workers/me — requires OAuth
    token from a signed-in user, not basic auth. Future capture
    wrapper needs a different auth flow.
  - Workday RaaS GET /ccx/service/customreport2/{tenant}/{user}/{report}
    — RaaS uses HTTP Basic auth but report URL needs a real report name.

Usage:
    $env:WORKDAY_TENANT_HOST = "https://wd2-impl-services1.workday.com"
    $env:WORKDAY_TENANT_NAME = "microsoft_dpt6"
    $env:WORKDAY_ISU_USER    = "<admin-user>"
    $env:WORKDAY_ISU_PASS    = "<password>"
    # Optional — also capture legacy ISU/RaaS validation calls:
    # $env:WORKDAY_RECORD_LEGACY = "1"
    python tests\\captures\\record_workday_config.py

Output: tests/fixtures/cassettes/workday_config.yaml

Most calls require admin-level Workday domain permissions (Integration
Build, Workday Accounts, etc.). The admin account used for the runtime
capture should also work for these.
"""

from __future__ import annotations

import os
import re
import sys
from xml.sax.saxutils import escape as xml_escape

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit

REQUIRED_ENV = ("WORKDAY_TENANT_HOST", "WORKDAY_TENANT_NAME", "WORKDAY_ISU_USER", "WORKDAY_ISU_PASS")


def _check_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("ERROR: missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    return {name: os.environ[name] for name in REQUIRED_ENV}


def _build_envelope(body: str, env: dict[str, str]) -> str:
    """Wrap a body fragment in a Workday SOAP envelope with WS-Security
    UsernameToken header. Mirrors the convention in
    record_flightcheck_workday.py."""
    isu = env["WORKDAY_ISU_USER"]
    tenant_suffix = "@" + env["WORKDAY_TENANT_NAME"]
    if not isu.endswith(tenant_suffix):
        isu = isu + tenant_suffix
    user = xml_escape(isu)
    pwd = xml_escape(env["WORKDAY_ISU_PASS"])

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
  <soapenv:Body>{body}</soapenv:Body>
</soapenv:Envelope>"""


# Each entry: (label, candidates, body_fragment, "simplified"|"legacy")
# `candidates` is a list of (service, version) pairs to try in order.
# Workday operation → service mapping is not always intuitive; web docs
# disagree with each other. Trying multiple candidates per operation
# lets the wrapper succeed even when our first guess is wrong, and
# reports which combination actually worked so we can pin it.
ADMIN_QUERIES: list[tuple[str, list[tuple[str, str]], str, str]] = [
    # ────────── Simplified setup config validation ──────────
    (
        "Get_API_Clients",
        [
            # Per Workday community docs Get_API_Clients lives in
            # Integration_System; some references claim Identity_Management.
            ("Integration_System", "v40.0"),
            ("Identity_Management", "v40.0"),
            ("Integration_System", "v44.0"),
            ("Integration_System", "v36.0"),
        ],
        '<bsvc:Get_API_Clients_Request bsvc:version="{version}">'
        '<bsvc:Response_Filter><bsvc:Page>1</bsvc:Page><bsvc:Count>20</bsvc:Count></bsvc:Response_Filter>'
        '</bsvc:Get_API_Clients_Request>',
        "simplified",
    ),
    (
        "Get_Authentication_Policies",
        [
            # Identity_Management is the documented home but version
            # availability varies per tenant.
            ("Identity_Management", "v40.0"),
            ("Identity_Management", "v44.0"),
            ("Identity_Management", "v36.0"),
        ],
        '<bsvc:Get_Authentication_Policies_Request bsvc:version="{version}">'
        '<bsvc:Response_Filter><bsvc:Page>1</bsvc:Page><bsvc:Count>20</bsvc:Count></bsvc:Response_Filter>'
        '</bsvc:Get_Authentication_Policies_Request>',
        "simplified",
    ),
    # ────────── Legacy ISU/RaaS setup config validation ──────────
    (
        "Get_Integration_System_Users",
        [
            # Human_Resources is the kit's known-working SOAP service.
            ("Human_Resources", "v40.0"),
            ("Integration_System", "v40.0"),
        ],
        '<bsvc:Get_Integration_System_Users_Request bsvc:version="{version}">'
        '<bsvc:Response_Filter><bsvc:Page>1</bsvc:Page><bsvc:Count>20</bsvc:Count></bsvc:Response_Filter>'
        '</bsvc:Get_Integration_System_Users_Request>',
        "legacy",
    ),
    (
        "Get_Integration_System_Security_Groups",
        [
            ("Identity_Management", "v40.0"),
            ("Security", "v40.0"),
            ("Human_Resources", "v40.0"),
        ],
        '<bsvc:Get_Integration_System_Security_Groups_Request bsvc:version="{version}">'
        '<bsvc:Response_Filter><bsvc:Page>1</bsvc:Page><bsvc:Count>20</bsvc:Count></bsvc:Response_Filter>'
        '</bsvc:Get_Integration_System_Security_Groups_Request>',
        "legacy",
    ),
    (
        "Get_Domain_Security_Policies",
        [
            ("Security", "v40.0"),
            ("Identity_Management", "v40.0"),
        ],
        '<bsvc:Get_Domain_Security_Policies_Request bsvc:version="{version}">'
        '<bsvc:Response_Filter><bsvc:Page>1</bsvc:Page><bsvc:Count>20</bsvc:Count></bsvc:Response_Filter>'
        '</bsvc:Get_Domain_Security_Policies_Request>',
        "legacy",
    ),
]


def main() -> None:
    announce("workday_config")
    env = _check_env()
    include_legacy = os.environ.get("WORKDAY_RECORD_LEGACY") == "1"

    # Auto-rewrite known web hosts to SOAP cluster equivalents (same
    # logic as the runtime wrapper).
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
    print(f"  Including legacy queries: {include_legacy} (set WORKDAY_RECORD_LEGACY=1 to enable)")
    print()

    confirm_or_exit()
    chdir_kit_root()

    import requests

    queries = [q for q in ADMIN_QUERIES if q[3] == "simplified" or include_legacy]

    with build_cassette("workday_config"):
        for label, candidates, body_template, category in queries:
            tag = "[simplified]" if category == "simplified" else "[legacy]   "
            success = False
            last_fault = ""

            for service, version in candidates:
                url = f"{base_url}/{service}/{version}"
                body_frag = body_template.replace("{version}", version)
                envelope = _build_envelope(body_frag, env)
                try:
                    r = requests.post(
                        url,
                        data=envelope.encode("utf-8"),
                        headers={"Content-Type": "text/xml; charset=utf-8"},
                        timeout=60,
                    )
                except requests.RequestException as exc:
                    last_fault = f"network error: {exc!s}"
                    continue

                if r.status_code == 200:
                    print(f"  {tag} {label:42s} -> 200  ({service}/{version})")
                    success = True
                    break

                # Surface the fault for diagnostic purposes; capture it
                # too so we have real fault shapes for negative-path tests.
                m = re.search(r"<faultstring[^>]*>(.*?)</faultstring>", r.text, re.DOTALL)
                last_fault = m.group(1).strip()[:200] if m else r.text[:200]

                # If it's "task not authorized" the operation IS at this
                # service+version — we just lack permission. Stop trying
                # other candidates for this operation since we've found
                # the right combo.
                if "not authorized" in last_fault.lower():
                    print(f"  {tag} {label:42s} -> {r.status_code} ({service}/{version})")
                    print(f"    fault: {last_fault}")
                    success = True  # we've captured useful data
                    break

            if not success:
                print(f"  {tag} {label:42s} -> FAIL on all {len(candidates)} candidates")
                print(f"    last fault: {last_fault}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/workday_config.yaml")
    print("CAREFULLY for any leftover real names, ISU usernames, real org role IDs,")
    print("or other tenant identifiers before committing. The PII redactor catches")
    print("most things automatically; eyeball is the safety net.")


if __name__ == "__main__":
    main()
