# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workday SOAP API client with Basic Auth, OAuth 2.0, retry, and XML parsing."""

import asyncio
import logging
import os
import random
from typing import Optional

# Use the stdlib ElementTree for BUILDING XML (defusedxml does not implement
# the full constructor / serialization API). Use defusedxml.ElementTree for
# PARSING any untrusted XML coming back from Workday so the parser is
# protected against billion-laughs / quadratic-blowup entity expansion.
from xml.etree import ElementTree as ET
from defusedxml import ElementTree as DET
from xml.sax.saxutils import escape as xml_escape

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("workday-mcp")

# Silence httpx and httpcore loggers - if a downstream operator enables global
# DEBUG logging they would otherwise echo full HTTP requests including
# Authorization headers (Basic auth credentials).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Workday SOAP namespace
BSVC_NS = "urn:com.workday/bsvc"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"

NS_MAP = {
    "soapenv": SOAP_NS,
    "bsvc": BSVC_NS,
    "wsse": WSSE_NS,
}


def _register_namespaces():
    """Register namespaces so ET output uses clean prefixes."""
    ET.register_namespace("soapenv", SOAP_NS)
    ET.register_namespace("bsvc", BSVC_NS)
    ET.register_namespace("wsse", WSSE_NS)


_register_namespaces()


class WorkdayClient:
    """Async HTTP client for Workday SOAP and RaaS APIs.

    Reads credentials from environment variables (set in .vscode/mcp.json
    via ${input:...} prompts so credentials never touch disk).

    Required env vars:
        WORKDAY_BASE_URL       — SOAP base URL (e.g. https://wd2-impl-services1.workday.com/ccx/service)
        WORKDAY_TENANT         — Workday tenant name (e.g. contoso_prod)
        WORKDAY_USERNAME       — ISU account username (format: user@domain@tenant)
        WORKDAY_PASSWORD       — ISU account password

    Optional env vars (for OAuth 2.0 user-context operations):
        WORKDAY_OAUTH_TOKEN_URL — OAuth token endpoint
        WORKDAY_OAUTH_CLIENT_ID — OAuth client ID (base64-encoded)
        WORKDAY_ENTRA_RESOURCE_URL — Entra resource URL for the Workday app
    """

    def __init__(self):
        self.base_url = os.environ.get("WORKDAY_BASE_URL", "").rstrip("/")
        self.tenant = os.environ.get("WORKDAY_TENANT", "")
        username = os.environ.get("WORKDAY_USERNAME", "")
        password = os.environ.get("WORKDAY_PASSWORD", "")

        if not self.base_url:
            raise ValueError("WORKDAY_BASE_URL environment variable is required")
        if not self.base_url.lower().startswith("https://"):
            raise ValueError(
                "WORKDAY_BASE_URL must use https:// - refusing to send ISU "
                "credentials over an unencrypted channel."
            )
        if not self.tenant:
            raise ValueError("WORKDAY_TENANT environment variable is required")
        if not username or not password:
            raise ValueError(
                "WORKDAY_USERNAME and WORKDAY_PASSWORD are required in env"
            )

        self._username = username
        self._password = password
        self._auth = httpx.BasicAuth(username, password)
        self.max_retries = 3
        self.timeout = 60.0

        # RaaS credentials (optional, separate from SOAP credentials)
        # RaaS uses Basic Auth with user@domain format (no @tenant suffix).
        # If not provided, derives from the main credentials by stripping @tenant.
        raas_user = os.environ.get("WORKDAY_RAAS_USERNAME", "")
        raas_pass = os.environ.get("WORKDAY_RAAS_PASSWORD", "")
        if raas_user and raas_pass:
            self._raas_username = raas_user
            self._raas_password = raas_pass
        else:
            # Derive from main credentials by stripping @tenant suffix
            self._raas_username = username
            self._raas_password = password
            tenant_suffix = f"@{self.tenant}"
            if self._raas_username.endswith(tenant_suffix):
                self._raas_username = self._raas_username[: -len(tenant_suffix)]

        # OAuth (optional)
        self.oauth_token_url = os.environ.get("WORKDAY_OAUTH_TOKEN_URL", "")
        self.oauth_client_id = os.environ.get("WORKDAY_OAUTH_CLIENT_ID", "")
        self.entra_resource_url = os.environ.get("WORKDAY_ENTRA_RESOURCE_URL", "")

    def _build_client(self, use_auth: bool = True) -> httpx.AsyncClient:
        kwargs = {
            "timeout": self.timeout,
            "headers": {"Content-Type": "text/xml; charset=utf-8"},
            # Disable redirect-following so a 302 response cannot replay our
            # Authorization header to an attacker-controlled host.
            "follow_redirects": False,
        }
        if use_auth:
            kwargs["auth"] = self._auth
        return httpx.AsyncClient(**kwargs)

    def __repr__(self) -> str:
        # Hide password from repr / tracebacks.
        return (
            f"<WorkdayClient base_url={self.base_url!r} "
            f"tenant={self.tenant!r} user={self._username!r}>"
        )

    def _service_url(self, service_name: str, version: str = "v42.0") -> str:
        """Build the SOAP service endpoint URL."""
        return f"{self.base_url}/{self.tenant}/{service_name}/{version}"

    def _raas_url(
        self,
        report_owner: str,
        report_name: str,
        report_instance: str = "",
        output_format: str = "json",
    ) -> str:
        """Build a RaaS (Reports as a Service) endpoint URL.

        Workday RaaS uses the customreport2 path:
            https://host/ccx/service/customreport2/{tenant}/{report_owner}/{report_name}

        The report_instance parameter is not used in the URL (it's a Workday
        internal concept for report versioning, not part of the REST path).
        """
        base = self.base_url.replace("/ccx/service", "/ccx/service/customreport2")
        return f"{base}/{self.tenant}/{report_owner}/{report_name}"

    def _raas_auth(self) -> httpx.BasicAuth:
        """Build Basic Auth credentials for RaaS endpoints.

        RaaS uses Basic Auth with the username in user@domain format
        (WITHOUT the @tenant suffix that SOAP WS-Security uses).
        Uses dedicated WORKDAY_RAAS_USERNAME/PASSWORD if set, otherwise
        derives from the main SOAP credentials.
        """
        return httpx.BasicAuth(self._raas_username, self._raas_password)

    def _wrap_soap_envelope(self, body_xml: str) -> str:
        """Wrap a SOAP body in a standard SOAP envelope with WS-Security.

        Workday requires WS-Security UsernameToken for SOAP authentication.
        HTTP Basic Auth is rejected by this tenant's auth policy.
        """
        # Escape username/password so XML special chars (e.g. & in passwords)
        # do not produce malformed envelopes.
        safe_user = xml_escape(self._username)
        safe_pass = xml_escape(self._password)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAP_NS}" xmlns:bsvc="{BSVC_NS}">
  <soapenv:Header>
    <wsse:Security soapenv:mustUnderstand="1" xmlns:wsse="{WSSE_NS}">
      <wsse:UsernameToken>
        <wsse:Username>{safe_user}</wsse:Username>
        <wsse:Password>{safe_pass}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </soapenv:Header>
  <soapenv:Body>
    {body_xml}
  </soapenv:Body>
</soapenv:Envelope>"""

    async def _soap_request(
        self,
        service_name: str,
        body_xml: str,
        version: str = "v42.0",
        soap_action: str = "",
    ) -> ET.Element:
        """Send a SOAP request and return the parsed XML response body.

        Uses WS-Security UsernameToken for authentication (no HTTP Basic Auth).
        Returns the first child element of the SOAP Body.
        """
        url = self._service_url(service_name, version)
        envelope = self._wrap_soap_envelope(body_xml)

        headers = {"Content-Type": "text/xml; charset=utf-8"}
        if soap_action:
            headers["SOAPAction"] = soap_action

        last_error = None
        for attempt in range(self.max_retries):
            async with self._build_client(use_auth=False) as client:
                try:
                    resp = await client.post(url, content=envelope, headers=headers)

                    if resp.status_code == 429:
                        wait = int(resp.headers.get("Retry-After", str(2 ** attempt)))
                        # Add jitter to avoid thundering-herd retries when many
                        # tools hit the rate limit at once.
                        wait += random.uniform(0, 1)
                        logger.warning(
                            "Rate limited (attempt %d/%d), waiting %.1fs",
                            attempt + 1, self.max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    if resp.status_code >= 400:
                        # Try to extract SOAP fault. Only surface the
                        # faultstring (and status code) - never the <detail>
                        # element, which can contain customer PII (employee
                        # IDs, names, validation messages) that would flow
                        # into the LLM context. Log the full body locally
                        # for the operator at DEBUG level, never higher.
                        try:
                            root = DET.fromstring(resp.text)
                            fault = root.find(f".//{{{SOAP_NS}}}Fault")
                            if fault is not None:
                                faultstring = fault.findtext("faultstring", "Unknown SOAP fault")
                                logger.debug(
                                    "Full SOAP fault response (operator-only): %s",
                                    resp.text,
                                )
                                raise Exception(
                                    f"Workday SOAP fault ({resp.status_code}): {faultstring}"
                                )
                        except DET.ParseError:
                            pass
                        # Generic non-SOAP-fault error - return only the
                        # status code, not the body.
                        logger.debug(
                            "Workday API error body (operator-only): %s",
                            resp.text,
                        )
                        raise Exception(
                            f"Workday API error ({resp.status_code})"
                        )

                    root = DET.fromstring(resp.text)
                    body = root.find(f"{{{SOAP_NS}}}Body")
                    if body is None:
                        raise Exception("No SOAP Body in response")

                    # Return the first child of Body (the actual response element)
                    children = list(body)
                    if not children:
                        raise Exception("Empty SOAP Body")
                    return children[0]

                except httpx.RequestError as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                        continue
                    raise

        raise Exception(f"Max retries exceeded: {last_error}")

    async def _raas_request(
        self,
        report_owner: str,
        report_name: str,
        report_instance: str = "",
        params: Optional[dict] = None,
        output_format: str = "json",
    ) -> dict:
        """Execute a RaaS (Reports as a Service) request.

        Uses Basic Auth with user@domain format (no @tenant suffix).
        URL pattern: /ccx/service/customreport2/{tenant}/{owner}/{report}
        """
        url = self._raas_url(report_owner, report_name, report_instance, output_format)
        query_params = {"format": output_format}
        if params:
            query_params.update(params)

        raas_auth = self._raas_auth()

        last_error = None
        for attempt in range(self.max_retries):
            async with httpx.AsyncClient(
                auth=raas_auth, timeout=self.timeout
            ) as client:
                try:
                    resp = await client.get(
                        url,
                        params=query_params,
                        headers={"Accept": "application/json"},
                    )

                    if resp.status_code == 429:
                        wait = int(resp.headers.get("Retry-After", str(2 ** attempt)))
                        await asyncio.sleep(wait)
                        continue

                    if resp.status_code >= 400:
                        raise Exception(
                            f"Workday RaaS error ({resp.status_code}): {resp.text[:500]}"
                        )

                    return resp.json()

                except httpx.RequestError as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise

        raise Exception(f"Max retries exceeded: {last_error}")

    # ── High-level SOAP operations ──────────────────────────────

    async def get_workers(
        self,
        employee_id: str = "",
        as_of_date: str = "",
        include_employment: bool = True,
        include_compensation: bool = False,
        include_organizations: bool = False,
        include_roles: bool = False,
        include_personal_info: bool = False,
        include_qualifications: bool = False,
        count: int = 1,
        version: str = "v42.0",
    ) -> ET.Element:
        """Call the Human_Resources Get_Workers operation."""
        # Escape LLM/tool-supplied values that get interpolated into XML.
        employee_id = xml_escape(employee_id) if employee_id else employee_id
        as_of_date = xml_escape(as_of_date) if as_of_date else as_of_date
        # Build request references
        ref_xml = ""
        if employee_id:
            ref_xml = f"""
            <bsvc:Request_References bsvc:Skip_Non_Existing_Instances="false" bsvc:Ignore_Invalid_References="true">
                <bsvc:Worker_Reference bsvc:Descriptor="Employee_ID">
                    <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
                </bsvc:Worker_Reference>
            </bsvc:Request_References>"""

        # Build response filter
        filter_parts = []
        if as_of_date:
            filter_parts.append(
                f"<bsvc:As_Of_Effective_Date>{as_of_date}</bsvc:As_Of_Effective_Date>"
            )
        if not employee_id:
            filter_parts.append(f"<bsvc:Count>{count}</bsvc:Count>")

        filter_xml = ""
        if filter_parts:
            filter_xml = f"""
            <bsvc:Response_Filter>
                {"".join(filter_parts)}
            </bsvc:Response_Filter>"""

        # Build response group
        group_xml = f"""
            <bsvc:Response_Group>
                <bsvc:Include_Reference>true</bsvc:Include_Reference>
                <bsvc:Include_Employment_Information>{"true" if include_employment else "false"}</bsvc:Include_Employment_Information>
                <bsvc:Include_Compensation>{"true" if include_compensation else "false"}</bsvc:Include_Compensation>
                <bsvc:Include_Organizations>{"true" if include_organizations else "false"}</bsvc:Include_Organizations>
                <bsvc:Include_Roles>{"true" if include_roles else "false"}</bsvc:Include_Roles>
                <bsvc:Include_Personal_Information>{"true" if include_personal_info else "false"}</bsvc:Include_Personal_Information>
                <bsvc:Include_Qualifications>{"true" if include_qualifications else "false"}</bsvc:Include_Qualifications>
            </bsvc:Response_Group>"""

        body = f"""<bsvc:Get_Workers_Request bsvc:version="{version}">
            {ref_xml}
            {filter_xml}
            {group_xml}
        </bsvc:Get_Workers_Request>"""

        return await self._soap_request("Human_Resources", body, version)

    async def get_absence_balance(
        self,
        employee_id: str,
        as_of_date: str = "",
        version: str = "v42.0",
    ) -> ET.Element:
        """Call the Absence_Management Get_Time_Off_Plan_Balances operation.

        Returns time off plan balances for a worker (vacation, sick, PTO, etc.).
        """
        # Escape LLM/tool-supplied values that get interpolated into XML.
        employee_id = xml_escape(employee_id) if employee_id else employee_id
        as_of_date = xml_escape(as_of_date) if as_of_date else as_of_date
        date_xml = ""
        if as_of_date:
            date_xml = f"<bsvc:As_Of_Effective_Date>{as_of_date}</bsvc:As_Of_Effective_Date>"

        body = f"""<bsvc:Get_Time_Off_Plan_Balances_Request bsvc:version="{version}">
            <bsvc:Request_Criteria>
                <bsvc:Employee_Reference>
                    <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
                </bsvc:Employee_Reference>
            </bsvc:Request_Criteria>
            <bsvc:Response_Filter>
                {date_xml}
            </bsvc:Response_Filter>
            <bsvc:Response_Group>
                <bsvc:Include_Reference>true</bsvc:Include_Reference>
                <bsvc:Include_Time_Off_Plan_Balance_Data>true</bsvc:Include_Time_Off_Plan_Balance_Data>
            </bsvc:Response_Group>
        </bsvc:Get_Time_Off_Plan_Balances_Request>"""

        return await self._soap_request("Absence_Management", body, version)

    async def enter_time_off(
        self,
        employee_id: str,
        date: str,
        time_off_type_id: str,
        hours: str = "8",
        comment: str = "",
        version: str = "v42.0",
    ) -> ET.Element:
        """Call the Absence_Management Enter_Time_Off operation.

        Uses the correct Enter_Time_Off_Data wrapper per the official WSDL.
        """
        # Escape LLM/tool-supplied values that get interpolated into XML.
        employee_id = xml_escape(employee_id)
        date = xml_escape(date)
        time_off_type_id = xml_escape(time_off_type_id)
        hours = xml_escape(hours)
        comment_safe = xml_escape(comment) if comment else comment
        comment_xml = ""
        if comment_safe:
            comment_xml = (
                "<bsvc:Business_Process_Parameters>"
                "<bsvc:Auto_Complete>true</bsvc:Auto_Complete>"
                "<bsvc:Comment_Data>"
                f"<bsvc:Comment>{comment_safe}</bsvc:Comment>"
                "</bsvc:Comment_Data>"
                "</bsvc:Business_Process_Parameters>"
            )

        body = f"""<bsvc:Enter_Time_Off_Request bsvc:version="{version}">
            {comment_xml}
            <bsvc:Enter_Time_Off_Data>
                <bsvc:Worker_Reference>
                    <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
                </bsvc:Worker_Reference>
                <bsvc:Enter_Time_Off_Entry_Data>
                    <bsvc:Time_Off_Date>{date}</bsvc:Time_Off_Date>
                    <bsvc:Daily_Quantity>{hours}</bsvc:Daily_Quantity>
                    <bsvc:Time_Off_Type_Reference>
                        <bsvc:ID bsvc:type="Time_Off_Type_ID">{time_off_type_id}</bsvc:ID>
                    </bsvc:Time_Off_Type_Reference>
                </bsvc:Enter_Time_Off_Entry_Data>
            </bsvc:Enter_Time_Off_Data>
        </bsvc:Enter_Time_Off_Request>"""

        return await self._soap_request("Absence_Management", body, version)

    async def get_organization(
        self,
        organization_id: str = "",
        organization_type: str = "Cost_Center_Reference_ID",
        count: int = 10,
        version: str = "v42.0",
    ) -> ET.Element:
        """Call the Human_Resources Get_Organizations operation.

        Note: Requires the account to have organization domain permissions.
        """
        # Escape LLM/tool-supplied values that get interpolated into XML.
        organization_id = xml_escape(organization_id) if organization_id else organization_id
        organization_type = xml_escape(organization_type)
        ref_xml = ""
        if organization_id:
            ref_xml = f"""
            <bsvc:Request_References>
                <bsvc:Organization_Reference>
                    <bsvc:ID bsvc:type="{organization_type}">{organization_id}</bsvc:ID>
                </bsvc:Organization_Reference>
            </bsvc:Request_References>"""

        filter_xml = ""
        if not organization_id:
            filter_xml = f"""
            <bsvc:Response_Filter>
                <bsvc:Count>{count}</bsvc:Count>
            </bsvc:Response_Filter>"""

        body = f"""<bsvc:Get_Organizations_Request bsvc:version="{version}">
            {ref_xml}
            {filter_xml}
        </bsvc:Get_Organizations_Request>"""

        return await self._soap_request("Human_Resources", body, version)

    async def raw_soap(
        self,
        service_name: str,
        body_xml: str,
        version: str = "v42.0",
    ) -> ET.Element:
        """Send a raw SOAP request body to any Workday service.

        The body_xml should be the inner request element (without the SOAP envelope).
        The client wraps it in an envelope with WS-Security authentication.
        """
        return await self._soap_request(service_name, body_xml, version)

    async def raas_query(
        self,
        report_owner: str,
        report_name: str,
        report_instance: str = "",
        params: Optional[dict] = None,
    ) -> dict:
        """Execute a RaaS (Reports as a Service) query."""
        return await self._raas_request(
            report_owner, report_name, report_instance, params
        )

    # ── XML helper ──────────────────────────────────────────────

    @staticmethod
    def xml_to_dict(element: ET.Element, strip_ns: bool = True) -> dict:
        """Convert an XML element tree to a nested dict.

        If strip_ns is True, namespace prefixes are removed from tag names.
        """

        def _strip_ns(tag: str) -> str:
            if strip_ns and "}" in tag:
                return tag.split("}", 1)[1]
            return tag

        def _elem_to_dict(elem: ET.Element) -> dict | str:
            result = {}

            # Attributes
            if elem.attrib:
                for k, v in elem.attrib.items():
                    result[f"@{_strip_ns(k)}"] = v

            # Children
            children = list(elem)
            if children:
                child_dict: dict = {}
                for child in children:
                    tag = _strip_ns(child.tag)
                    child_val = _elem_to_dict(child)
                    if tag in child_dict:
                        # Convert to list if multiple same-named children
                        existing = child_dict[tag]
                        if not isinstance(existing, list):
                            child_dict[tag] = [existing]
                        child_dict[tag].append(child_val)
                    else:
                        child_dict[tag] = child_val
                result.update(child_dict)
            elif elem.text and elem.text.strip():
                if result:
                    result["#text"] = elem.text.strip()
                else:
                    return elem.text.strip()

            return result if result else ""

        return {_strip_ns(element.tag): _elem_to_dict(element)}

    @staticmethod
    def extract_xpath(element: ET.Element, xpath: str) -> list[str]:
        """Extract values from an XML element using a simplified XPath.

        Supports the //*[local-name()='X'] patterns used in ESS template configs.
        Converts them to standard ET XPath with namespace wildcards.
        """
        import re

        # Convert //*[local-name()='Tag'] patterns to .//{*}Tag for ET
        et_xpath = xpath
        # Handle patterns like //*[local-name()='Tag']/text()
        et_xpath = re.sub(
            r"//\*\[local-name\(\)=['\"](\w+)['\"]\]",
            r".//{*}\1",
            et_xpath,
        )
        # Handle attribute conditions like @*[local-name()='type']='value'
        et_xpath = re.sub(
            r"/\*\[local-name\(\)=['\"](\w+)['\"](?:\s+and\s+@\*\[local-name\(\)=['\"](\w+)['\"]\]=['\"](\w+)['\"])\]",
            r"/{*}\1[@{*}\2='\3']",
            et_xpath,
        )
        # Remove /text() suffix (ET returns text via .text).
        # Use removesuffix() — rstrip("/text()") would strip individual chars, not the substring,
        # so an XPath ending in 'e' (e.g. .//{*}SomeType) would lose the 'e'.
        et_xpath = et_xpath.removesuffix("/text()")

        try:
            matches = element.findall(et_xpath)
            return [m.text for m in matches if m.text]
        except Exception:
            # Fallback: brute-force search by local name
            target = xpath.split("local-name()=")[-1].split("'")[1] if "local-name()" in xpath else ""
            if target:
                return [
                    e.text
                    for e in element.iter()
                    if e.tag.endswith(f"}}{target}") or e.tag == target
                    if e.text
                ]
            return []
