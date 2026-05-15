# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for Workday SOAP APIs.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "placeholder"
#
# ⚠️ These builders are SCHEMA-GROUNDED, not cassette-validated. They
# were constructed by reading
# solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py and
# the public Workday SOAP API documentation. The exact namespace
# prefixes, element ordering, and fault-envelope details that real
# Workday tenants emit may differ.
#
# DO NOT use these mocks in FlightCheck integration tests under
# tests/flightcheck/checks/ until a cassette has been captured and
# this module has been updated to MOCK_STATUS = "validated".
#
# See tests/AGENTS.md for the workflow.
#
# To capture: set the WORKDAY_* env vars and run
# tests/captures/record_flightcheck_workday.py — that wrapper iterates
# the WORKFLOWS list in flightcheck/checks/workday.py against a real
# tenant and writes tests/fixtures/cassettes/flightcheck_workday.yaml.
# ─────────────────────────────────────────────────────────────────

References:
- Workday Web Services index: https://community.workday.com/sites/default/files/file-hosting/productionapi/index.html
- Get_Workers operation: https://community.workday.com/sites/default/files/file-hosting/productionapi/Human_Resources/v40.0/Get_Workers.html
- Production source: solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py
- Recording wrapper: tests/captures/record_flightcheck_workday.py
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape as xml_escape

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "placeholder"
MOCK_CASSETTE = None  # Awaiting tests/fixtures/cassettes/flightcheck_workday.yaml

# Common Workday SOAP namespaces.
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
BSVC_NS = "urn:com.workday/bsvc"
WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"

MOCK_EMPLOYEE_ID = "MOCK_EMP_001"
MOCK_WORKER_WID = "0" * 32  # WID format: 32 hex chars; redactor replaces real WIDs with this


# ────────────────────────────────────────────────────────────────────────
# Envelope builders — request side
# ────────────────────────────────────────────────────────────────────────


def soap_envelope(
    *,
    body: str,
    user: str = "ISU_MOCK",
    password: str = "REDACTED_WSSE_PASSWORD",
) -> str:
    """Wrap a body fragment in a Workday-style SOAP envelope with
    WS-Security UsernameToken header."""
    user_x = xml_escape(user)
    pwd_x = xml_escape(password)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope
    xmlns:soapenv="{SOAP_NS}"
    xmlns:bsvc="{BSVC_NS}">
  <soapenv:Header>
    <wsse:Security xmlns:wsse="{WSSE_NS}">
      <wsse:UsernameToken>
        <wsse:Username>{user_x}</wsse:Username>
        <wsse:Password>{pwd_x}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>{body}</soapenv:Body>
</soapenv:Envelope>"""


def get_workers_request(
    *,
    employee_id: str = MOCK_EMPLOYEE_ID,
    response_group: str = "<bsvc:Include_Reference>true</bsvc:Include_Reference>",
) -> str:
    """Build a Get_Workers request body.

    Mirrors the envelope shape constructed by
    flightcheck/checks/workday.py:_test_workflow.
    """
    return f"""<bsvc:Get_Workers_Request bsvc:version="v40.0">
      <bsvc:Request_References>
        <bsvc:Worker_Reference>
          <bsvc:ID bsvc:type="Employee_ID">{xml_escape(employee_id)}</bsvc:ID>
        </bsvc:Worker_Reference>
      </bsvc:Request_References>
      <bsvc:Response_Group>{response_group}</bsvc:Response_Group>
    </bsvc:Get_Workers_Request>"""


# ────────────────────────────────────────────────────────────────────────
# Envelope builders — response side (success)
# ────────────────────────────────────────────────────────────────────────


def get_workers_success_response(
    *,
    employee_id: str = MOCK_EMPLOYEE_ID,
    worker_wid: str = MOCK_WORKER_WID,
    extra_worker_data: str = "",
) -> str:
    """Build a minimal Get_Workers_Response success envelope.

    The kit's check parses this with defusedxml ET.fromstring and
    walks the tree looking for `.//*[@*='Employee_ID']` and similar
    XPaths — see flightcheck/checks/workday.py:WORKFLOWS.

    Pass `extra_worker_data` to inject additional <bsvc:Worker_Data>
    children (e.g. Organization_Data, Hire_Date, etc.) for workflow-
    specific tests.
    """
    body = f"""<bsvc:Get_Workers_Response xmlns:bsvc="{BSVC_NS}" bsvc:version="v40.0">
      <bsvc:Response_Data>
        <bsvc:Worker>
          <bsvc:Worker_Reference>
            <bsvc:ID bsvc:type="WID">{worker_wid}</bsvc:ID>
            <bsvc:ID bsvc:type="Employee_ID">{xml_escape(employee_id)}</bsvc:ID>
          </bsvc:Worker_Reference>
          <bsvc:Worker_Data>
            <bsvc:Worker_ID>{xml_escape(employee_id)}</bsvc:Worker_ID>
            {extra_worker_data}
          </bsvc:Worker_Data>
        </bsvc:Worker>
      </bsvc:Response_Data>
    </bsvc:Get_Workers_Response>"""
    return soap_envelope(body=body)


# ────────────────────────────────────────────────────────────────────────
# Envelope builders — response side (fault)
# ────────────────────────────────────────────────────────────────────────


def soap_fault(
    *,
    fault_code: str = "SOAP-ENV:Server",
    fault_string: str = "Invalid Worker_Reference",
    detail: str = "<wd:Validation_Error><wd:Message>Worker not found</wd:Message></wd:Validation_Error>",
) -> str:
    """Build a SOAP 1.1 fault envelope.

    Real Workday faults usually have a `bsvc:Validation_Error_Detail`
    or `bsvc:Processing_Faults` element nested inside `<detail>`. The
    exact shape needs cassette validation — see banner above.
    """
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAP_NS}">
  <soapenv:Body>
    <soapenv:Fault>
      <faultcode>{xml_escape(fault_code)}</faultcode>
      <faultstring>{xml_escape(fault_string)}</faultstring>
      <detail>{detail}</detail>
    </soapenv:Fault>
  </soapenv:Body>
</soapenv:Envelope>"""


# ────────────────────────────────────────────────────────────────────────
# `responses` registration helpers
# ────────────────────────────────────────────────────────────────────────


def workday_url(
    *,
    tenant_host: str = "https://wd2-impl-services1.workday.com",
    tenant_name: str = "mocktenant",
    service: str = "Human_Resources",
    version: str = "v40.0",
) -> str:
    """Construct a Workday SOAP endpoint URL.

    Real format: https://{host}/ccx/service/{tenant}/{service}/{version}.
    """
    return f"{tenant_host.rstrip('/')}/ccx/service/{tenant_name}/{service}/{version}"


def soap_success(
    *,
    url: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Mock a successful Workday SOAP POST."""
    return {
        "method": "POST",
        "url": url or workday_url(),
        "body": body or get_workers_success_response(),
        "status": 200,
        "content_type": "text/xml; charset=utf-8",
    }


def soap_fault_response(
    *,
    url: str | None = None,
    fault_code: str = "SOAP-ENV:Server",
    fault_string: str = "Invalid Worker_Reference",
) -> dict[str, Any]:
    """Mock a SOAP fault response. Real Workday returns HTTP 500 with a
    fault envelope as the body."""
    return {
        "method": "POST",
        "url": url or workday_url(),
        "body": soap_fault(fault_code=fault_code, fault_string=fault_string),
        "status": 500,
        "content_type": "text/xml; charset=utf-8",
    }


def http_unauthorized(*, url: str | None = None) -> dict[str, Any]:
    """Mock a 401 response — happens when the WS-Security UsernameToken
    is rejected (invalid ISU username/password).

    Real Workday returns HTTP 401 with a small XML or HTML body
    explaining the auth failure. Exact shape needs cassette validation.
    """
    return {
        "method": "POST",
        "url": url or workday_url(),
        "body": "<error>Authentication failed</error>",
        "status": 401,
        "content_type": "text/xml; charset=utf-8",
    }
