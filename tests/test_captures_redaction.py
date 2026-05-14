# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the recording-wrapper redaction primitives in tests/captures/_common.py.

These tests don't require network or a real cassette — they exercise the
redaction functions directly with synthetic input. If they pass we have
confidence that real captures will be scrubbed correctly before write.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


# Make tests/captures importable so we can poke at its internals.
CAPTURES_DIR = Path(__file__).resolve().parent / "captures"
sys.path.insert(0, str(CAPTURES_DIR))

from _common import (  # noqa: E402
    SCRUB_HEADERS,
    _before_record_request,
    _before_record_response,
    _redact_body_text,
    _redact_text,
    _scrub_headers,
    _scrub_json_keys,
)


class TestRedactText:
    def test_empty_input_returns_empty(self) -> None:
        assert _redact_text("") == ""
        assert _redact_text(None) is None  # type: ignore[arg-type]

    def test_replaces_real_tenant_guid(self) -> None:
        text = "user_id = 4f24a3e1-9bcd-4f00-aa11-deadbeef0001"
        out = _redact_text(text)
        assert "4f24a3e1-9bcd-4f00-aa11-deadbeef0001" not in out
        assert "00000000-0000-0000-0000-000000001111" in out

    def test_replaces_workday_wid(self) -> None:
        wid = "ab" * 16  # 32 hex chars
        text = f"<wd:ID>{wid}</wd:ID>"
        out = _redact_text(text)
        assert wid not in out
        assert "0" * 32 in out

    def test_replaces_email(self) -> None:
        text = "Contact: alice.smith@contoso.com"
        out = _redact_text(text)
        assert "alice.smith@contoso.com" not in out
        assert "mock.user@contoso.com" in out

    def test_idempotent(self) -> None:
        text = "user 4f24a3e1-9bcd-4f00-aa11-deadbeef0001 wrote alice@example.com"
        once = _redact_text(text)
        twice = _redact_text(once)
        assert once == twice

    def test_replaces_dataverse_org_subdomain(self) -> None:
        text = "https://orgcae533e6.crm.dynamics.com/api/data"
        out = _redact_text(text)
        assert "orgcae533e6" not in out
        assert "orgmocktenant" in out

    def test_replaces_servicenow_dev_instance_hostname(self) -> None:
        text = '"instance":"https://dev184242.service-now.com/api"'
        out = _redact_text(text)
        assert "dev184242" not in out.lower()
        # URL-position match (preceded by ://) — avoids CodeQL's
        # incomplete-URL-sanitization warning that fires on plain
        # substring assertions over URL-shaped strings.
        assert re.search(r"https?://devmocktenant\.service-now\.com\b", out), (
            f"expected redacted URL with mock hostname, got: {out!r}"
        )

    def test_replaces_servicenow_short_instance_name(self) -> None:
        text = '"instance":"Dev184242"'
        out = _redact_text(text)
        assert "Dev184242" not in out
        assert "DevMockInstance" in out

    def test_replaces_successfactors_tenant_url(self) -> None:
        text = "https://apisalesdemo8.successfactors.com/odata/v2"
        out = _redact_text(text)
        assert "apisalesdemo8" not in out.lower()
        # URL-position match (preceded by ://) — same rationale as
        # test_replaces_servicenow_dev_instance_hostname above.
        assert re.search(r"https?://apisalesdemomock\.successfactors\.com\b", out), (
            f"expected redacted URL with mock hostname, got: {out!r}"
        )

    def test_replaces_sf_company_id(self) -> None:
        text = '"CompanyId":"SFCPART001804"'
        out = _redact_text(text)
        assert "SFCPART001804" not in out
        assert "SFCPARTMOCK000" in out

    def test_replaces_dataverse_unique_name(self) -> None:
        text = '"uniqueName":"unq2012fca7bd1bf111afbf6045bd056"'
        out = _redact_text(text)
        assert "unq2012fca7bd1bf111afbf6045bd056" not in out
        assert "unqmocktenant" in out

    def test_replaces_scale_group(self) -> None:
        text = '"scaleGroup":"NAMCRMLIVESG731"'
        out = _redact_text(text)
        assert "NAMCRMLIVESG731" not in out
        assert "MOCKCRMLIVESG000" in out

    def test_replaces_pva_gateway_cluster_suffix(self) -> None:
        text = "https://powervamg.us-il107.gateway.prod.island.powerapps.com"
        out = _redact_text(text)
        assert "us-il107" not in out
        assert "us-il000.gateway.prod.island" in out

    def test_scrubs_wsse_password_element(self) -> None:
        body = (
            '<wsse:UsernameToken><wsse:Username>isu@tenant</wsse:Username>'
            '<wsse:Password>SuperSecret123!</wsse:Password></wsse:UsernameToken>'
        )
        out = _redact_text(body)
        assert "SuperSecret123!" not in out
        assert "REDACTED_WSSE_PASSWORD" in out

    def test_scrubs_password_element_with_other_namespace_prefix(self) -> None:
        body = '<ns0:Password>SuperSecret123!</ns0:Password>'
        out = _redact_text(body)
        assert "SuperSecret123!" not in out
        assert "REDACTED_WSSE_PASSWORD" in out

    def test_scrubs_password_element_with_attributes(self) -> None:
        body = (
            '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-username-token-profile-1.0#PasswordText">'
            'SuperSecret123!</wsse:Password>'
        )
        out = _redact_text(body)
        assert "SuperSecret123!" not in out
        assert "REDACTED_WSSE_PASSWORD" in out

    def test_scrubs_wsse_username_element(self) -> None:
        body = (
            '<wsse:UsernameToken><wsse:Username>isu_account_name</wsse:Username>'
            '<wsse:Password>x</wsse:Password></wsse:UsernameToken>'
        )
        out = _redact_text(body)
        # Bare ISU username (no @ to trigger the email regex) should still
        # be scrubbed by the explicit Username element rule.
        assert "isu_account_name" not in out
        assert "REDACTED_WSSE_USERNAME" in out


class TestWorkdayPiiScrubbing:
    """The Workday PII element scrubber lives outside REDACT_REGEX so it
    gets its own dedicated tests. Each test uses one PII element name
    with a real-looking value, then asserts the value is gone."""

    def test_scrubs_first_name(self) -> None:
        body = "<wd:First_Name>Sarah</wd:First_Name>"
        out = _redact_text(body)
        assert "Sarah" not in out
        assert "<wd:First_Name>Mock</wd:First_Name>" in out

    def test_scrubs_last_name_with_namespace_prefix(self) -> None:
        body = "<bsvc:Last_Name>Connor</bsvc:Last_Name>"
        out = _redact_text(body)
        assert "Connor" not in out
        assert "User" in out  # the replacement

    def test_scrubs_phone_number(self) -> None:
        body = "<wd:Phone_Number>+1 (425) 555-0123</wd:Phone_Number>"
        out = _redact_text(body)
        assert "(425) 555-0123" not in out
        assert "<wd:Phone_Number>555-555-0100</wd:Phone_Number>" in out

    def test_scrubs_email_address(self) -> None:
        body = "<wd:Email_Address>real.person@contoso.com</wd:Email_Address>"
        out = _redact_text(body)
        # The email regex would catch this even without the element rule,
        # but we want the element rule to override with the canonical mock.
        assert "real.person" not in out
        assert "mock.user@contoso.com" in out

    def test_scrubs_hire_date(self) -> None:
        body = "<wd:Hire_Date>2007-04-15</wd:Hire_Date>"
        out = _redact_text(body)
        assert "2007-04-15" not in out
        assert "<wd:Hire_Date>2020-01-01</wd:Hire_Date>" in out

    def test_scrubs_birth_date(self) -> None:
        body = "<wd:Birth_Date>1985-07-22</wd:Birth_Date>"
        out = _redact_text(body)
        assert "1985-07-22" not in out
        assert "1990-01-01" in out

    def test_scrubs_address_line(self) -> None:
        body = "<wd:Address_Line_Data>123 Real Street</wd:Address_Line_Data>"
        out = _redact_text(body)
        assert "Real Street" not in out
        assert "1 Mock Street" in out

    def test_scrubs_typed_employee_id(self) -> None:
        """`<wd:ID wd:type="Employee_ID">21005</wd:ID>` is the most common
        leak shape — Workday uses attribute-discriminated IDs everywhere."""
        body = '<wd:ID wd:type="Employee_ID">21005</wd:ID>'
        out = _redact_text(body)
        assert "21005" not in out
        assert "MOCK_ID" in out

    def test_scrubs_typed_position_id(self) -> None:
        body = '<wd:ID wd:type="Position_ID">P-12345</wd:ID>'
        out = _redact_text(body)
        assert "P-12345" not in out
        assert "MOCK_ID" in out

    def test_scrubs_typed_manager_id(self) -> None:
        body = '<wd:ID wd:type="Manager_ID">99999</wd:ID>'
        out = _redact_text(body)
        assert "99999" not in out

    def test_replacement_with_digit_does_not_break_substitution(self) -> None:
        """Regression test: International_Phone_Code's replacement is "1",
        which used to crash with `re.PatternError: invalid group reference 11`
        because the substitution template `\\1{replacement}\\2` became `\\11\\2`
        and Python tried to interpret `\\11` as group 11. The lambda-based
        substitution prevents this."""
        body = "<wd:International_Phone_Code>44</wd:International_Phone_Code>"
        out = _redact_text(body)  # must not raise
        assert "44" not in out
        assert "<wd:International_Phone_Code>1</wd:International_Phone_Code>" in out

    def test_preserves_attributes_on_element(self) -> None:
        """Some Workday elements have attributes (e.g.
        `<wd:Phone_Number wd:Workday_ID="...">...</wd:Phone_Number>`).
        The pattern should match regardless of attributes and replace
        only the contents."""
        body = '<wd:Phone_Number wd:Workday_ID="abc">+1 555-1234</wd:Phone_Number>'
        out = _redact_text(body)
        assert "555-1234" not in out
        assert "555-555-0100" in out

    def test_does_not_match_unrelated_elements(self) -> None:
        body = "<wd:NotAPiiField>keep this</wd:NotAPiiField>"
        out = _redact_text(body)
        assert "keep this" in out

    def test_scrubs_worker_descriptor(self) -> None:
        body = "<wd:Worker_Descriptor>Sarah Connor</wd:Worker_Descriptor>"
        out = _redact_text(body)
        assert "Sarah Connor" not in out
        assert "<wd:Worker_Descriptor>Mock User</wd:Worker_Descriptor>" in out

    def test_scrubs_formatted_name_attribute(self) -> None:
        body = '<wd:Worker wd:Formatted_Name="Sarah Connor"><wd:Worker_Data/></wd:Worker>'
        out = _redact_text(body)
        assert "Sarah Connor" not in out
        assert 'wd:Formatted_Name="Mock User"' in out

    def test_scrubs_reporting_name_attribute(self) -> None:
        body = '<wd:Worker wd:Reporting_Name="Connor, Sarah"/>'
        out = _redact_text(body)
        assert "Connor" not in out
        assert 'wd:Reporting_Name="Mock User"' in out

    def test_scrubs_multiple_attributes_on_same_element(self) -> None:
        body = (
            '<wd:Worker wd:Formatted_Name="Sarah Connor" '
            'wd:Reporting_Name="Connor, Sarah">data</wd:Worker>'
        )
        out = _redact_text(body)
        assert "Sarah" not in out
        assert "Connor" not in out
        assert 'wd:Formatted_Name="Mock User"' in out
        assert 'wd:Reporting_Name="Mock User"' in out


class TestScrubJsonKeys:
    def test_scrubs_display_name(self) -> None:
        out = _scrub_json_keys({"displayName": "EmployeeHub"})
        assert out["displayName"] == "Mock Display Name"

    def test_scrubs_friendly_name_in_nested_struct(self) -> None:
        payload = {
            "properties": {
                "linkedEnvironmentMetadata": {
                    "friendlyName": "PROD_ESS_WORKDAY_PREOPT",
                    "uniqueName": "unqRealValue",
                }
            }
        }
        out = _scrub_json_keys(payload)
        assert out["properties"]["linkedEnvironmentMetadata"]["friendlyName"] == "Mock Friendly Name"
        assert out["properties"]["linkedEnvironmentMetadata"]["uniqueName"] == "unqmocktenant"

    def test_scrubs_address_fields(self) -> None:
        payload = {"city": "Redmond", "postalCode": "98052-8300", "street": "1 Microsoft Way"}
        out = _scrub_json_keys(payload)
        assert out["city"] == "Mocktown"
        assert out["postalCode"] == "00000"
        assert out["street"] == "1 Mock Street"

    def test_scrubs_created_by_user_name(self) -> None:
        payload = {"createdBy": {"displayName": "Armando Lopez", "id": "abc"}}
        out = _scrub_json_keys(payload)
        assert out["createdBy"]["displayName"] == "Mock Display Name"
        # non-scrubbed sibling preserved
        assert out["createdBy"]["id"] == "abc"

    def test_scrubs_in_list_of_records(self) -> None:
        payload = {"value": [{"displayName": "A"}, {"displayName": "B"}]}
        out = _scrub_json_keys(payload)
        assert out["value"] == [
            {"displayName": "Mock Display Name"},
            {"displayName": "Mock Display Name"},
        ]


class TestRedactBodyText:
    def test_json_body_runs_key_scrub_then_text_redact(self) -> None:
        body = (
            '{"displayName":"EmployeeHub","tenantId":"4f24a3e1-9bcd-4f00-aa11-deadbeef0001",'
            '"createdBy":{"displayName":"Armando Lopez","email":"alice@contoso.com"}}'
        )
        out = _redact_body_text(body)
        # JSON-key scrub
        assert "EmployeeHub" not in out
        assert "Armando Lopez" not in out
        assert "Mock Display Name" in out
        # Text-regex redact
        assert "4f24a3e1-9bcd-4f00-aa11-deadbeef0001" not in out
        assert "00000000-0000-0000-0000-000000001111" in out
        assert "alice@contoso.com" not in out
        assert "mock.user@contoso.com" in out

    def test_non_json_body_falls_back_to_text_redaction_only(self) -> None:
        body = "<soap:Envelope>alice@contoso.com 4f24a3e1-9bcd-4f00-aa11-deadbeef0001</soap:Envelope>"
        out = _redact_body_text(body)
        assert "alice@contoso.com" not in out
        assert "4f24a3e1-9bcd-4f00-aa11-deadbeef0001" not in out

    def test_empty_body_returns_empty(self) -> None:
        assert _redact_body_text("") == ""
        assert _redact_body_text(None) is None  # type: ignore[arg-type]


class TestScrubHeaders:
    def test_strips_authorization(self) -> None:
        out = _scrub_headers({"Authorization": "Bearer abc123"})
        assert out["Authorization"] == "REDACTED"

    def test_strips_cookie(self) -> None:
        out = _scrub_headers({"Cookie": "session=abc"})
        assert out["Cookie"] == "REDACTED"

    def test_case_insensitive(self) -> None:
        out = _scrub_headers({"AUTHORIZATION": "x"})
        assert out["AUTHORIZATION"] == "REDACTED"

    def test_preserves_non_sensitive(self) -> None:
        out = _scrub_headers({"Accept": "application/json"})
        assert out["Accept"] == "application/json"

    def test_handles_list_valued_headers(self) -> None:
        # vcrpy serializes headers as {key: [values]} sometimes.
        out = _scrub_headers({"Set-Cookie": ["s=1", "t=2"]})
        assert out["Set-Cookie"] == ["REDACTED"]

    def test_strips_all_known_sensitive_headers(self) -> None:
        for name in SCRUB_HEADERS:
            out = _scrub_headers({name: "secret"})
            assert out[name] == "REDACTED", f"{name} not scrubbed"

    def test_redacts_guid_in_non_scrubbed_header_value(self) -> None:
        """Correlation-style headers carry GUIDs that aren't secret per
        se but are tenant-correlated. Even when the header name isn't
        on the SCRUB list, GUID values in the header should be replaced
        via _redact_text so they don't land in committed cassettes."""
        out = _scrub_headers({"X-Diag-Trace": "cd9239bf-a990-442a-9477-20db6b401818"})
        assert out["X-Diag-Trace"] == "00000000-0000-0000-0000-000000001111"

    def test_redacts_email_in_non_scrubbed_header_value(self) -> None:
        out = _scrub_headers({"X-Forwarded-User": "alice@contoso.com"})
        assert out["X-Forwarded-User"] == "mock.user@contoso.com"

    def test_redacts_list_valued_non_scrubbed_header(self) -> None:
        out = _scrub_headers({
            "X-Diag-Tokens": [
                "abcdef0123456789abcdef0123456789",
                "fedcba9876543210fedcba9876543210",
            ]
        })
        # Both values are 32-hex Workday-WID-shaped strings → redacted to zeros
        assert out["X-Diag-Tokens"] == ["0" * 32, "0" * 32]


class TestBeforeRecordHooks:
    def test_request_hook_redacts_url(self) -> None:
        class _R:
            uri = "https://orgmocktenant.crm.dynamics.com/api/4f24a3e1-9bcd-4f00-aa11-deadbeef0001"
            headers = {"Authorization": "Bearer x"}
            body = None

        out = _before_record_request(_R())
        assert "4f24a3e1-9bcd-4f00-aa11-deadbeef0001" not in out.uri
        assert out.headers["Authorization"] == "REDACTED"

    def test_request_hook_redacts_string_body(self) -> None:
        class _R:
            uri = "https://example/"
            headers: dict = {}
            body = "user alice@example.com"

        out = _before_record_request(_R())
        assert "alice@example.com" not in out.body

    def test_response_hook_redacts_string_body(self) -> None:
        resp = {
            "headers": {"Authorization": ["x"]},
            "body": {"string": "Hello alice@example.com from tenant abcdef0123456789abcdef0123456789"},
        }
        out = _before_record_response(resp)
        body = out["body"]["string"]
        assert "alice@example.com" not in body
        assert "abcdef0123456789abcdef0123456789" not in body
        assert out["headers"]["Authorization"] == ["REDACTED"]

    def test_response_hook_handles_bytes_body(self) -> None:
        resp = {
            "headers": {},
            "body": {"string": b"<email>bob@example.com</email>"},
        }
        out = _before_record_response(resp)
        # bytes body should be re-encoded after redaction
        assert b"bob@example.com" not in out["body"]["string"]
        assert b"mock.user@contoso.com" in out["body"]["string"]
