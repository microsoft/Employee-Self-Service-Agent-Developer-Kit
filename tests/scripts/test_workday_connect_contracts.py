from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import sys
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from workday_connect_contracts import (  # noqa: E402
    WorkdayConnectContractError,
    build_entra_handoff,
    build_workday_admin_packet,
    parse_entra_return_worksheet,
    parse_workday_admin_return_worksheet,
    validate_agent_binding_evidence,
    validate_administrator_partial_evidence,
    validate_maker_evidence,
    validate_maker_failure_evidence,
    validate_entra_verification,
    validate_workday_admin_response,
)
import workday_connect_contracts as contracts  # noqa: E402
from workday_connect_entra_contracts import (  # noqa: E402
    ENTRA_ADMIN_COMPLETION_QUESTION,
    ENTRA_ADMIN_CONSENT_NOTE,
    ENTRA_ADMIN_ENGAGEMENT_QUESTION,
    ENTRA_APP_ADMIN_ROLE,
)
from workday_connect_model import (  # noqa: E402
    ADMINISTRATOR_REQUIRED_FIELDS,
    default_state,
)
from workday_connect_workbook import (  # noqa: E402
    ENTRA_ADMIN_WORKBOOK_PATH,
    DETAILED_WORKSHEET_SHEET_NAME,
    WORKBOOK_ASSET_DIRECTORY,
    WORKDAY_ADMIN_WORKBOOK_PATH,
    WORKSHEET_HEADERS,
    WorkdayConnectWorkbookError,
    read_administrator_workbook,
    write_administrator_workbook,
)


def _state():
    state = default_state()
    state["scope"].update(
        {
            "entraTenantId": "00000000-0000-0000-0000-000000000000",
            "workdayTenant": "contoso_impl",
            "packageFlavor": "runtime",
        }
    )
    state["identifiers"].update(
        {
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/"
                "00000000-0000-0000-0000-000000000000/"
            ),
            "entraLoginUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "replyUrl": "https://www.workday.com/saml/acs",
        }
    )
    state["phases"]["preflight"]["status"] = "complete"
    return state


def _entra_checks():
    return {
        "samlMode": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "signingCertificate": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "connectorPreauthorized": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "graphDelegatedPermissions": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "adminConsent": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "userAssignment": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "nameId": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "user.userPrincipalName",
        },
        "samlSigningOption": {
            "outcome": "confirmed",
            "provenance": "administrator-attestation",
            "observedValue": "Sign SAML response and assertion",
        },
        "existingScopesPreserved": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "preserved",
        },
        "authorizedClientsPreserved": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "preserved",
        },
        "permissionsPreserved": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "preserved",
        },
    }


def _entra_verification(*, reply_urls=None, reply_url=None):
    app_id = "44444444-4444-4444-4444-444444444444"
    return {
        "tenantId": "00000000-0000-0000-0000-000000000000",
        "selectedDirectory": {
            "tenantId": "00000000-0000-0000-0000-000000000000",
            "displayName": "Contoso",
        },
        "application": {
            "displayName": "Workday exact",
            "appId": app_id,
            "objectId": "55555555-5555-5555-5555-555555555555",
            "servicePrincipalId": "66666666-6666-6666-6666-666666666666",
            "identifierUris": [
                "http://www.workday.com/contoso_impl",
                f"api://{app_id}",
            ],
            "replyUrls": (
                reply_urls
                if reply_urls is not None
                else ["https://www.workday.com/saml/acs"]
            ),
        },
        "scopeGuid": "77777777-7777-7777-7777-777777777777",
        "replyUrl": reply_url or "https://www.workday.com/saml/acs",
        "microsoftEntraIdentifier": (
            "https://sts.windows.net/"
            "00000000-0000-0000-0000-000000000000/"
        ),
        "loginUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "certificate": {
            "thumbprint": "AA11",
            "validFrom": "2026-01-01T00:00:00Z",
            "validTo": "2027-01-01T00:00:00Z",
        },
        "checks": _entra_checks(),
    }


def _workday_state():
    state = _state()
    state["identifiers"]["workdaySamlEntityId"] = (
        "http://www.workday.com/contoso_impl"
    )
    state["identifiers"]["entraAppIdUri"] = (
        "api://44444444-4444-4444-4444-444444444444"
    )
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }
    return state


def _workday_response(**overrides):
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": "http://www.workday.com/contoso_impl",
        "certificateSelectionOutcome": "entra-signing-certificate-selected",
        "certificateValidityOutcome": "matches-verified-entra-certificate",
        "oauthClientId": "safe-client-id",
        "clientGrantType": "saml-bearer",
        "includeWorkdayOwnedScope": "yes",
        "identityProviderSsoServiceUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "signOnRedirectUrl": "https://www.workday.com/saml/acs",
        "oauthTokenUrl": (
            "https://example.workday.com/ccx/oauth2/contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "rolloutType": "limited-or-test",
        "employeeSecurityGroup": "ESS Workday Pilot Employees",
        "publicWorkerReportsOutcome": "get-permission-verified",
        "integrationPermissionsGetOutcome": "get-permission-verified",
        "functionalAreaScopes": [
            "Core Payroll",
            "Organizations and Roles",
            "Staffing",
            "Time Off and Leave",
        ],
    }
    response.update(overrides)
    return response


def _entra_worksheet() -> str:
    return """Application ID: 44444444-4444-4444-4444-444444444444
Selected Reply URL: https://www.workday.com/saml/acs
NameID source: user.userPrincipalName
SAML signing: Sign SAML response and assertion
Certificate thumbprint (active certificate row): AA11
Certificate expiration date (active certificate row): 2027-01-01
SAML configuration: Yes, confirmed
Signing certificate: Yes, confirmed
Authorized connector: Yes, confirmed
Permissions and consent: Yes, permissions and consent are confirmed
Employee assignment: Yes, access is confirmed or assignment is not required
"""


def _workday_worksheet() -> str:
    return """SAML row settings: Yes, all four values match exactly
Certificate: The certificate transferred from the completed Entra handoff
Certificate expiration: Yes, the expiration date matches exactly
OAuth client ID: safe-client-id
OAuth token URL: https://example.workday.com/ccx/oauth2/contoso_impl/token
REST base URL: https://example.workday.com/ccx/api
SOAP base URL: https://example.workday.com/ccx/service
Authentication policy: An existing active policy scopes the ESS OAuth client and allows SAML for the intended employees
Rollout: Entire workforce - All Employees access is configured
API client access: Yes, SAML Bearer, Workday Owned Scope, and all four required functional areas are configured
Required employee access: Yes, Get permission is verified for Public Worker Reports and Integration Permissions
"""


def _worksheet_table(packet: dict, worksheet: str) -> str:
    values = {}
    current_label = None
    expected_labels = packet["responseForm"]["collection"]["labels"]
    for raw_line in worksheet.splitlines():
        if not raw_line:
            continue
        matched = next(
            (
                label
                for label in expected_labels
                if raw_line.startswith(label + ":")
            ),
            None,
        )
        if matched is not None:
            values[matched] = raw_line[len(matched) + 1 :].strip()
            current_label = matched
        elif current_label == "Additional scenario domains":
            values[current_label] += "\n" + raw_line.strip()
        else:
            raise AssertionError(f"Unexpected worksheet line: {raw_line}")

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    lines = [
        (
            "| Information to capture | Where to find it | What to record | "
            "Example value | Your tenant values |"
        ),
        "| --- | --- | --- | --- | --- |",
    ]
    for instruction in packet["captureInstructions"]:
        information = instruction["information"]
        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    information,
                    instruction["portalLocation"],
                    instruction["instruction"],
                    instruction["exampleValue"],
                    values[information],
                )
            )
            + " |"
        )
    return "\n".join(lines)


def _worksheet_answers(worksheet: str) -> dict[str, str]:
    return {
        label.strip(): value.strip()
        for line in worksheet.splitlines()
        for label, separator, value in [line.partition(":")]
        if separator
    }


def _rewrite_workbook_member(
    path: Path,
    member_name: str,
    transform,
) -> None:
    with ZipFile(path) as archive:
        members = {
            member.filename: archive.read(member.filename)
            for member in archive.infolist()
        }
    members[member_name] = transform(members[member_name])
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_checked_in_administrator_workbooks_match_current_contracts() -> None:
    pairs = (
        (ENTRA_ADMIN_WORKBOOK_PATH, build_entra_handoff(_state())),
        (
            WORKDAY_ADMIN_WORKBOOK_PATH,
            build_workday_admin_packet(_workday_state()),
        ),
    )
    for path, packet in pairs:
        assert path.is_file()
        assert path.stat().st_size > 0
        worksheet = read_administrator_workbook(path)
        lines = worksheet.splitlines()
        assert [line.partition(":")[0] for line in lines] == (
            packet["responseForm"]["collection"]["labels"]
        )
        assert all(not line.partition(":")[2].strip() for line in lines)
        with ZipFile(path) as archive:
            assert "xl/worksheets/sheet1.xml" in archive.namelist()
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            worksheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            strings = [
                "".join(node.itertext())
                for node in ET.fromstring(
                    archive.read("xl/sharedStrings.xml")
                ).findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si")
            ] if "xl/sharedStrings.xml" in archive.namelist() else []
        namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets = workbook.findall("s:sheets/s:sheet", namespace)
        assert len(sheets) == 1
        assert sheets[0].get("name") == DETAILED_WORKSHEET_SHEET_NAME
        worksheet = ET.fromstring(worksheet_xml)
        rows = worksheet.findall("s:sheetData/s:row", namespace)[1:]
        assert len(rows) == len(packet["captureInstructions"])
        locations = [
            row.find(f"s:c[@r='B{index}']", namespace)
            for index, row in enumerate(rows, start=2)
        ]
        instructions = [
            strings[int(cell.find("s:v", namespace).text)]
            if cell.get("t") == "s"
            else "".join(cell.itertext())
            for cell in locations
        ]
        assert all(text.startswith("1.") and "\n2." in text for text in instructions)
        assert path.parent == WORKBOOK_ASSET_DIRECTORY
        assert WORKBOOK_ASSET_DIRECTORY.parts[-4:] == (
            "skills", "connect", "workday", "assets"
        )


def _fill_detailed_workbook(path: Path, answers: dict[str, str]) -> None:
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    main_ns = namespace["s"]

    def fill(content: bytes) -> bytes:
        worksheet = ET.fromstring(content)
        for index, answer in enumerate(answers.values(), start=2):
            row = worksheet.find(f"s:sheetData/s:row[@r='{index}']", namespace)
            reference = f"E{index}"
            cell = row.find(f"s:c[@r='{reference}']", namespace)
            if cell is None:
                cell = ET.SubElement(row, f"{{{main_ns}}}c", {"r": reference})
            for node in list(cell):
                cell.remove(node)
            cell.set("t", "inlineStr")
            inline = ET.SubElement(cell, f"{{{main_ns}}}is")
            ET.SubElement(inline, f"{{{main_ns}}}t").text = answer
        return ET.tostring(worksheet, encoding="utf-8", xml_declaration=True)

    _rewrite_workbook_member(path, "xl/worksheets/sheet1.xml", fill)


@pytest.mark.parametrize(
    ("filename", "state", "packet", "worksheet", "parser", "validator"),
    [
        (
            "entra.xlsx",
            _state(),
            build_entra_handoff(_state()),
            _entra_worksheet(),
            parse_entra_return_worksheet,
            validate_entra_verification,
        ),
        (
            "workday.xlsx",
            _workday_state(),
            build_workday_admin_packet(_workday_state()),
            _workday_worksheet(),
            parse_workday_admin_return_worksheet,
            validate_workday_admin_response,
        ),
    ],
)
@pytest.mark.parametrize("detailed_template", [False, True])
def test_completed_administrator_workbook_round_trips_through_contract(
    tmp_path: Path,
    filename: str,
    state: dict,
    packet: dict,
    worksheet: str,
    parser,
    validator,
    detailed_template: bool,
) -> None:
    path = tmp_path / filename
    if detailed_template:
        source = (
            ENTRA_ADMIN_WORKBOOK_PATH if filename == "entra.xlsx"
            else WORKDAY_ADMIN_WORKBOOK_PATH
        )
        shutil.copyfile(source, path)
        _fill_detailed_workbook(path, _worksheet_answers(worksheet))
    else:
        write_administrator_workbook(
            path,
            title="Administrator handoff",
            administrator_role=packet["administratorRole"],
            actions=packet["actions"],
            capture_instructions=packet["captureInstructions"],
            answers=_worksheet_answers(worksheet),
        )

    parsed = parser(state, read_administrator_workbook(path))
    result = validator(state, parsed)

    assert result["identifiers"]


def test_workbook_rejects_ambiguous_answer_sheets(
    tmp_path: Path,
) -> None:
    packet = build_entra_handoff(_state())
    path = write_administrator_workbook(
        tmp_path / "ambiguous.xlsx",
        title="Administrator handoff",
        administrator_role=packet["administratorRole"],
        actions=packet["actions"],
        capture_instructions=packet["captureInstructions"],
    )
    _rewrite_workbook_member(
        path,
        "xl/workbook.xml",
        lambda content: content.replace(
            b'name="Steps"', b'name="Worksheet - Detailed"', 1,
        ),
    )

    with pytest.raises(WorkdayConnectWorkbookError, match="multiple answer sheets"):
        read_administrator_workbook(path)


@pytest.mark.parametrize("encrypted", [True, False])
def test_workbook_recognizes_protected_and_legacy_excel_files(
    tmp_path: Path,
    encrypted: bool,
) -> None:
    path = tmp_path / "administrator.xlsx"
    stream_name = "EncryptedPackage" if encrypted else "Workbook"
    path.write_bytes(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + stream_name.encode("utf-16le")
    )

    with pytest.raises(WorkdayConnectWorkbookError) as caught:
        read_administrator_workbook(path)

    message = str(caught.value)
    assert "organization-approved" in message
    if encrypted:
        assert "encrypted or protected" in message
        assert "information protection administrator" in message
        assert "Do not share a password or bypass required protections" in message
    else:
        assert "legacy Excel format" in message


def test_entra_workbook_returns_all_independent_corrections() -> None:
    from workday_connect_contract_common import WorkdayConnectWorksheetError

    worksheet = (
        _entra_worksheet()
        .replace("Yes, permissions and consent are confirmed", "Not done")
        .replace("Yes, access is confirmed or assignment is not required", "Not sure")
        .replace("2027-01-01", "invalid-date")
    )
    with pytest.raises(WorkdayConnectWorksheetError) as caught:
        parse_entra_return_worksheet(_state(), worksheet)

    errors = caught.value.details["fieldErrors"]
    assert {error["label"] for error in errors} == {
        "Permissions and consent",
        "Employee assignment",
        "Certificate expiration date (active certificate row)",
    }
    assert "Yes, permissions and consent are confirmed" in str(caught.value)
    assert "Yes, access is confirmed or assignment is not required" in str(caught.value)
    assert "Not done" not in str(caught.value)
    assert "correct the listed cells in the same workbook" in str(caught.value)


def test_workday_workbook_returns_choice_and_endpoint_corrections_together() -> None:
    from workday_connect_contract_common import WorkdayConnectWorksheetError

    worksheet = (
        _workday_worksheet()
        .replace("Yes, all four values match exactly", "No")
        .replace("/ccx/api\n", "/ccx/api/contoso_impl\n")
        .replace("/ccx/service\n", "/ccx/service/contoso_impl\n")
    )
    with pytest.raises(WorkdayConnectWorksheetError) as caught:
        parse_workday_admin_return_worksheet(_workday_state(), worksheet)

    assert {error["label"] for error in caught.value.details["fieldErrors"]} == {
        "SAML row settings",
        "REST base URL",
        "SOAP base URL",
    }
    assert "must end exactly at /ccx/api" in str(caught.value)
    assert "must end exactly at /ccx/service" in str(caught.value)


def test_worksheet_choice_accepts_whitespace_without_weakening_attestation() -> None:
    parsed = parse_entra_return_worksheet(
        _state(),
        _entra_worksheet().replace(
            "Yes, permissions and consent are confirmed",
            "Yes,  permissions   and consent are confirmed",
        ),
    )
    assert parsed["checks"]["adminConsent"]["provenance"] == (
        "administrator-attestation"
    )
    with pytest.raises(WorkdayConnectContractError, match="Permissions and consent"):
        parse_entra_return_worksheet(
            _state(),
            _entra_worksheet().replace(
                "Yes, permissions and consent are confirmed", "Yes"
            ),
        )


def test_administrator_workbook_rejects_changed_headers(
    tmp_path: Path,
) -> None:
    packet = build_entra_handoff(_state())
    path = write_administrator_workbook(
        tmp_path / "changed-header.xlsx",
        title="Administrator handoff",
        administrator_role=packet["administratorRole"],
        actions=packet["actions"],
        capture_instructions=packet["captureInstructions"],
    )
    _rewrite_workbook_member(
        path,
        "xl/worksheets/sheet2.xml",
        lambda content: content.replace(
            WORKSHEET_HEADERS[0].encode(),
            b"Changed heading",
            1,
        ),
    )

    with pytest.raises(
        WorkdayConnectWorkbookError,
        match="headers were changed",
    ):
        read_administrator_workbook(path)


@pytest.mark.parametrize(
    "member_name", ["xl/workbook.xml", "xl/worksheets/sheet2.xml"]
)
def test_administrator_workbook_reports_corrupt_member_as_validation_error(
    tmp_path: Path,
    member_name: str,
) -> None:
    packet = build_entra_handoff(_state())
    path = write_administrator_workbook(
        tmp_path / "corrupt.xlsx",
        title="Administrator handoff",
        administrator_role=packet["administratorRole"],
        actions=packet["actions"],
        capture_instructions=packet["captureInstructions"],
    )
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    with ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    with ZipFile(path) as archive:
        member = archive.getinfo(member_name)
    payload = bytearray(path.read_bytes())
    offset = member.header_offset + 30 + len(member.filename.encode("utf-8"))
    payload[offset] ^= 1
    path.write_bytes(payload)

    with pytest.raises(WorkdayConnectWorkbookError, match="corrupt"):
        read_administrator_workbook(path)


@pytest.mark.parametrize(
    ("label", "answer", "field", "outcome"),
    [
        (
            "Authentication policy",
            "A reviewed policy scoped to the ESS OAuth client was activated",
            "authenticationPolicyOutcome",
            "reviewed-policy-activated",
        ),
        (
            "Rollout",
            "Entire workforce - All Employees access is configured",
            "rolloutType",
            "entire-workforce",
        ),
    ],
)
def test_workday_workbook_explains_alternative_successful_answers(
    tmp_path: Path,
    label: str,
    answer: str,
    field: str,
    outcome: str,
) -> None:
    path = tmp_path / "workday.xlsx"
    with ZipFile(WORKDAY_ADMIN_WORKBOOK_PATH) as archive:
        workbook_text = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith(".xml")
        )
    assert answer in workbook_text
    answers = _worksheet_answers(_workday_worksheet())
    answers[label] = answer
    shutil.copyfile(WORKDAY_ADMIN_WORKBOOK_PATH, path)
    _fill_detailed_workbook(path, answers)
    response = parse_workday_admin_return_worksheet(
        _workday_state(), read_administrator_workbook(path),
    )
    result = validate_workday_admin_response(_workday_state(), response)
    assert result["evidence"][field] == outcome


def test_administrator_workbook_accepts_absolute_package_relationships(
    tmp_path: Path,
) -> None:
    packet = build_entra_handoff(_state())
    path = write_administrator_workbook(
        tmp_path / "absolute-relationship.xlsx",
        title="Administrator handoff",
        administrator_role=packet["administratorRole"],
        actions=packet["actions"],
        capture_instructions=packet["captureInstructions"],
    )
    _rewrite_workbook_member(
        path,
        "xl/_rels/workbook.xml.rels",
        lambda content: content.replace(
            b'Target="worksheets/sheet2.xml"',
            b'Target="/xl/worksheets/sheet2.xml"',
        ),
    )

    worksheet = read_administrator_workbook(path)

    assert worksheet.startswith("Application ID: ")


def test_administrator_workbook_rejects_formulas(
    tmp_path: Path,
) -> None:
    packet = build_entra_handoff(_state())
    path = write_administrator_workbook(
        tmp_path / "formula.xlsx",
        title="Administrator handoff",
        administrator_role=packet["administratorRole"],
        actions=packet["actions"],
        capture_instructions=packet["captureInstructions"],
        answers={"Application ID": "44444444-4444-4444-4444-444444444444"},
    )

    def add_formula(content: bytes) -> bytes:
        text = content.decode("utf-8")
        start = text.index('<c r="E2"')
        end = text.index("</c>", start) + len("</c>")
        return (
            text[:start]
            + '<c r="E2"><f>1+1</f><v>2</v></c>'
            + text[end:]
        ).encode("utf-8")

    _rewrite_workbook_member(
        path,
        "xl/worksheets/sheet2.xml",
        add_formula,
    )

    with pytest.raises(WorkdayConnectWorkbookError, match="formulas"):
        read_administrator_workbook(path)


def test_administrator_workbook_rejects_unsupported_columns(
    tmp_path: Path,
) -> None:
    packet = build_entra_handoff(_state())
    path = write_administrator_workbook(
        tmp_path / "extra-column.xlsx",
        title="Administrator handoff",
        administrator_role=packet["administratorRole"],
        actions=packet["actions"],
        capture_instructions=packet["captureInstructions"],
    )

    def add_column(content: bytes) -> bytes:
        text = content.decode("utf-8")
        marker = '<row r="2"'
        row_start = text.index(marker)
        row_end = text.index("</row>", row_start)
        extra_cell = (
            '<c r="F2" t="inlineStr"><is><t>unexpected</t></is></c>'
        )
        return (text[:row_end] + extra_cell + text[row_end:]).encode("utf-8")

    _rewrite_workbook_member(
        path,
        "xl/worksheets/sheet2.xml",
        add_column,
    )

    with pytest.raises(
        WorkdayConnectWorkbookError,
        match="unsupported columns",
    ):
        read_administrator_workbook(path)


def test_administrator_workbook_rejects_unsafe_archive_paths(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsafe.xlsx"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../unsafe.xml", b"<unsafe/>")

    with pytest.raises(WorkdayConnectWorkbookError, match="unsafe file path"):
        read_administrator_workbook(path)


def test_entra_handoff_selects_only_exact_service_provider_id():
    handoff = build_entra_handoff(
        _state(),
        {
            "directoryDisplayName": "Contoso",
            "applications": [
                {
                    "displayName": "Workday wrong",
                    "appId": "11111111-1111-1111-1111-111111111111",
                    "objectId": "22222222-2222-2222-2222-222222222222",
                    "servicePrincipalId": "33333333-3333-3333-3333-333333333333",
                    "identifierUris": ["http://www.workday.com/contoso_impl_old"],
                },
                {
                    "displayName": "Workday exact",
                    "appId": "44444444-4444-4444-4444-444444444444",
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": "66666666-6666-6666-6666-666666666666",
                    "identifierUris": ["http://www.workday.com/contoso_impl/"],
                },
            ]
        },
    )

    assert handoff["target"]["displayName"] == "Workday exact"
    assert handoff["identifiers"]["workdaySamlEntityId"] == (
        "http://www.workday.com/contoso_impl"
    )
    assert handoff["identifiers"]["entraAppIdUri"] == (
        "api://44444444-4444-4444-4444-444444444444"
    )
    assert (
        handoff["identifiers"]["workdaySamlEntityId"]
        != (handoff["identifiers"]["entraAppIdUri"])
    )
    assert "planHash" not in handoff


def test_entra_handoff_builds_guided_packet_without_graph_discovery():
    handoff = build_entra_handoff(_state())

    assert handoff["target"]["mode"] == "administrator-selection"
    assert handoff["requiresRediscovery"] is False
    assert "directoryDisplayName" not in handoff["scope"]
    assert handoff["captureInstructions"]
    assert handoff["informationToReturn"]
    assert handoff["identifiers"]["entraAppIdUri"] is None


def test_entra_handoff_rejects_missing_exact_discovery():
    with pytest.raises(WorkdayConnectContractError, match="No exact"):
        build_entra_handoff(
            _state(),
            {
                "directoryDisplayName": "Contoso",
                "applications": [],
            },
        )


def test_entra_handoff_can_request_explicit_creation():
    handoff = build_entra_handoff(
        _state(),
        {
            "directoryDisplayName": "Contoso",
            "applications": [],
            "allowCreate": True,
        },
    )

    assert handoff["target"]["mode"] == "create"
    assert handoff["identifiers"]["entraAppIdUri"] is None
    assert handoff["requiresRediscovery"] is True
    assert handoff["scope"]["directoryDisplayName"] == "Contoso"
    assert handoff["administratorRole"] == ENTRA_APP_ADMIN_ROLE
    assert handoff["consentNote"] == ENTRA_ADMIN_CONSENT_NOTE
    assert handoff["engagementQuestion"] == ENTRA_ADMIN_ENGAGEMENT_QUESTION
    assert handoff["completionQuestion"] == ENTRA_ADMIN_COMPLETION_QUESTION
    assert any("NameID" in item for item in handoff["informationToReturn"])
    capture_by_field = {
        field: instruction
        for instruction in handoff["captureInstructions"]
        for field in instruction["fields"]
    }
    assert (
        ADMINISTRATOR_REQUIRED_FIELDS["entra"] - {"entraChecks"}
        <= capture_by_field.keys()
    )
    assert {
        "entraChecks.samlMode",
        "entraChecks.signingCertificate",
        "entraChecks.connectorPreauthorized",
        "entraChecks.graphDelegatedPermissions",
        "entraChecks.adminConsent",
        "entraChecks.userAssignment",
        "entraChecks.nameId",
        "entraChecks.samlSigningOption",
    } <= capture_by_field.keys()
    assert "selectedDirectoryDisplayName" not in capture_by_field
    assert "applicationDisplayName" not in capture_by_field
    assert "entraChecks.existingScopesPreserved" not in capture_by_field
    assert set(handoff["responseForm"]["required"]) == (
        ADMINISTRATOR_REQUIRED_FIELDS["entra"]
    )
    assert len(handoff["responseForm"]["required"]) == 7
    assert handoff["responseForm"]["collection"]["mode"] == "xlsx-workbook"
    assert handoff["responseForm"]["collection"]["validator"] == (
        "parse_entra_return_worksheet"
    )
    assert handoff["responseForm"]["collection"]["acceptedFormats"] == [
        "xlsx-workbook",
        "five-column-markdown-table",
        "labeled-worksheet",
    ]
    assert "Upload the completed administrator workbook" in (
        handoff["responseForm"]["note"]
    )
    assert "Basic SAML Configuration" in capture_by_field[
        "replyUrl"
    ]["portalLocation"]
    assert "Unique User Identifier" in capture_by_field[
        "nameIdSource"
    ]["portalLocation"]
    signing_location = capture_by_field["samlSigningOption"]["portalLocation"]
    assert "SAML Signing Certificate" in signing_location
    assert "Edit pencil -> Signing Option" in signing_location
    assert "Expose an API" in capture_by_field[
        "entraChecks.connectorPreauthorized"
    ]["portalLocation"]
    assert "API permissions" in capture_by_field[
        "entraChecks.graphDelegatedPermissions"
    ]["portalLocation"]


def test_entra_labeled_worksheet_parses_to_validated_evidence() -> None:
    parsed = parse_entra_return_worksheet(_state(), _entra_worksheet())

    result = validate_entra_verification(_state(), parsed)

    assert result["identifiers"]["entraAppId"] == (
        "44444444-4444-4444-4444-444444444444"
    )
    assert result["evidence"]["checks"]["adminConsent"] == {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }


def test_entra_completed_capture_table_parses_to_validated_evidence() -> None:
    packet = build_entra_handoff(_state())
    assert [
        row["information"] for row in packet["captureInstructions"]
    ] == packet["responseForm"]["collection"]["labels"]
    assert all(row["exampleValue"] for row in packet["captureInstructions"])

    parsed = parse_entra_return_worksheet(
        _state(),
        _worksheet_table(packet, _entra_worksheet()),
    )

    result = validate_entra_verification(_state(), parsed)
    assert result["identifiers"]["entraAppId"] == (
        "44444444-4444-4444-4444-444444444444"
    )


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("January 1, 2027", "2027-01-01"),
        ("1 Jan 2027", "2027-01-01"),
        ("2027-01-01T17:45:00-08:00", "2027-01-01"),
        ("31/01/2027", "2027-01-31"),
        ("10/5/2027", "10/5/2027"),
    ],
)
def test_entra_certificate_expiration_accepts_maker_friendly_dates(
    supplied: str,
    expected: str,
) -> None:
    worksheet = _entra_worksheet().replace(
        (
            "Certificate expiration date (active certificate row): "
            "2027-01-01"
        ),
        (
            "Certificate expiration date (active certificate row): "
            f"{supplied}"
        ),
    )

    parsed = parse_entra_return_worksheet(_state(), worksheet)

    assert parsed["certificate"]["validTo"] == expected


def test_entra_customer_labeled_list_needs_no_table_headers() -> None:
    worksheet = """Directory: Workday MSFT DPT6
Application name: Workday MSFT DPT6
App ID: d64a50b6-f92c-43af-be17-53132d75b94d
Reply URL: https://impl.workday.com/microsoft_dpt6/login-saml.htmld
Name ID source: user.userprincipalname
SAML signing: Sign SAML response and assertion
Certificate thumbprint: 905236D91F87B87FDD6AD3A832909751D7C403EA
Certificate expiry date: 6/23/2028, 9:43:11 AM
SAML configuration: Yes, confirmed
Signing certificate: Yes, confirmed
Authorized connector: Yes, confirmed
Permissions and consent: Yes, permissions and consent are confirmed
Employee assignment: Yes, access is confirmed or assignment is not required
Existing configuration: Preserved without changes
"""

    parsed = parse_entra_return_worksheet(_state(), worksheet)

    assert parsed["selectedDirectory"]["displayName"] == "Workday MSFT DPT6"
    assert parsed["application"]["appId"] == (
        "d64a50b6-f92c-43af-be17-53132d75b94d"
    )
    assert parsed["certificate"]["validTo"] == "2028-06-23"
    assert parsed["checks"]["existingScopesPreserved"]["observedValue"] == (
        "preserved"
    )


@pytest.mark.parametrize(
    "worksheet",
    [
        _entra_worksheet().replace(
            (
                "Application ID: "
                "44444444-4444-4444-4444-444444444444\n"
            ),
            (
                "Application ID: "
                "44444444-4444-4444-4444-444444444444\n"
                "Application ID: "
                "55555555-5555-5555-5555-555555555555\n"
            ),
        ),
        _entra_worksheet() + "Unknown field: value\n",
        _entra_worksheet().replace(
            "SAML configuration: Yes, confirmed",
            "SAML configuration: I'm not sure",
        ),
    ],
)
def test_entra_labeled_worksheet_rejects_ambiguous_or_failed_evidence(
    worksheet: str,
) -> None:
    with pytest.raises(WorkdayConnectContractError):
        parse_entra_return_worksheet(_state(), worksheet)


def test_entra_handoff_reuses_matching_tenant_foundation():
    state = _state()
    app_id = "44444444-4444-4444-4444-444444444444"
    state["tenantFoundation"] = {
        "scope": {
            "entraTenantId": state["scope"]["entraTenantId"],
            "workdayTenant": state["scope"]["workdayTenant"],
        },
        "identifiers": {"entraAppId": app_id},
        "endpoints": {},
        "phases": {
            "entra": {
                "completedActions": [],
                "evidence": [],
            },
            "workday-admin": {
                "completedActions": [],
                "evidence": [],
            },
        },
        "capturedAt": "2026-09-26T00:00:00Z",
    }

    handoff = build_entra_handoff(
        state,
        {
            "directoryDisplayName": "Contoso",
            "applications": [
                {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": ["http://www.workday.com/contoso_impl"],
                }
            ]
        },
    )

    assert handoff["foundationReuse"]["eligible"] is True
    assert set(handoff["foundationReuse"]) == {"eligible"}
    assert "administrator to review" in handoff["actions"][0]


def test_entra_verification_requires_all_expected_graph_evidence():
    app_id = "44444444-4444-4444-4444-444444444444"
    result = validate_entra_verification(
        _state(),
        {
            "tenantId": "00000000-0000-0000-0000-000000000000",
            "selectedDirectory": {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "displayName": "Contoso",
            },
            "application": {
                "displayName": "Workday exact",
                "appId": app_id,
                "objectId": "55555555-5555-5555-5555-555555555555",
                "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                "identifierUris": [
                    "http://www.workday.com/contoso_impl",
                    f"api://{app_id}",
                ],
                "replyUrls": [
                    "https://www.workday.com/saml/acs",
                ],
            },
            "scopeGuid": "77777777-7777-7777-7777-777777777777",
            "replyUrl": "https://www.workday.com/saml/acs",
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/"
                "00000000-0000-0000-0000-000000000000/"
            ),
            "loginUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "certificate": {
                "thumbprint": "AA11",
                "validFrom": "2026-01-01T00:00:00Z",
                "validTo": "2027-01-01T00:00:00Z",
            },
            "checks": _entra_checks(),
        },
    )

    assert result["identifiers"]["entraAppId"] == app_id
    assert result["identifiers"]["entraAppIdUri"] == f"api://{app_id}"
    assert result["evidence"]["checks"]["samlSigningOption"] == {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
        "observedValue": "Sign SAML response and assertion",
    }


def test_entra_verification_accepts_reduced_guided_evidence():
    app_id = "44444444-4444-4444-4444-444444444444"

    result = validate_entra_verification(
        _state(),
        {
            "selectedDirectory": {"displayName": "Contoso"},
            "application": {
                "displayName": "Workday exact",
                "appId": app_id,
            },
            "replyUrl": "https://www.workday.com/saml/acs",
            "certificate": {
                "thumbprint": "AA11",
                "validTo": "2027-01-01T00:00:00Z",
            },
            "checks": _entra_checks(),
        },
    )

    assert result["identifiers"]["entraAppIdUri"] == f"api://{app_id}"
    assert result["identifiers"]["microsoftEntraIdentifier"].startswith(
        "https://sts.windows.net/"
    )
    assert "entraAppObjectId" not in result["identifiers"]
    assert "entraServicePrincipalId" not in result["identifiers"]
    assert "scopeGuid" not in result["identifiers"]
    assert "validFrom" not in result["identifiers"]["signingCertificate"]
    assert "certificateValidFrom" not in result["partialEvidence"]
    assert result["partialEvidence"]["applicationIdentifierUris"] == [
        "http://www.workday.com/contoso_impl",
        f"api://{app_id}",
    ]


def test_entra_verification_binds_reply_url_to_graph_evidence():
    with pytest.raises(
        WorkdayConnectContractError,
        match="not present",
    ):
        validate_entra_verification(
            _state(),
            _entra_verification(
                reply_urls=["https://www.workday.com/other/acs"],
            ),
        )


def test_saml_signing_option_records_the_exact_required_value():
    with pytest.raises(
        WorkdayConnectContractError,
        match="Sign SAML response and assertion",
    ):
        contracts._normalize_entra_check(
            "samlSigningOption",
            {
                "outcome": "confirmed",
                "provenance": "administrator-attestation",
                "observedValue": "Sign SAML assertion only",
            },
        )


def test_entra_verification_rejects_a_different_graph_tenant():
    app_id = "44444444-4444-4444-4444-444444444444"
    with pytest.raises(
        WorkdayConnectContractError,
        match="does not match",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "99999999-9999-9999-9999-999999999999",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "77777777-7777-7777-7777-777777777777",
                "certificate": {
                    "thumbprint": "AA11",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": _entra_checks(),
            },
        )


def test_entra_verification_rejects_provenance_free_checks():
    app_id = "44444444-4444-4444-4444-444444444444"
    checks = _entra_checks()
    checks["nameId"] = {"outcome": "verified"}

    with pytest.raises(
        WorkdayConnectContractError,
        match="lacks provenance",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "77777777-7777-7777-7777-777777777777",
                "certificate": {
                    "thumbprint": "AA11",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": checks,
            },
        )


def test_entra_verification_rejects_unused_check_fields():
    app_id = "44444444-4444-4444-4444-444444444444"
    checks = _entra_checks()
    checks["nameId"]["details"] = "not part of the evidence contract"

    with pytest.raises(
        WorkdayConnectContractError,
        match="unsupported fields",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "77777777-7777-7777-7777-777777777777",
                "certificate": {
                    "thumbprint": "AA11",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": checks,
            },
        )


def test_entra_verification_accepts_guided_admin_attestation():
    verification = _entra_verification()
    verification["checks"]["adminConsent"] = {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }

    result = validate_entra_verification(_state(), verification)

    assert result["evidence"]["checks"]["adminConsent"] == {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }


def test_workday_packet_uses_service_provider_id_not_app_id_uri():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso_impl",
            "entraAppIdUri": ("api://44444444-4444-4444-4444-444444444444"),
            "signingCertificate": {
                "thumbprint": "AA11",
                "validTo": "2027-01-01T00:00:00Z",
            },
        }
    )
    packet = build_workday_admin_packet(state)

    assert packet["referenceValues"]["serviceProviderId"] == (
        "http://www.workday.com/contoso_impl"
    )
    assert packet["referenceValues"]["entraApplicationIdUri"].startswith("api://")
    assert packet["referenceValues"]["expectedIdentityProviderIssuer"] == (
        "https://sts.windows.net/00000000-0000-0000-0000-000000000000/"
    )
    assert "certificateValidFrom" not in packet["referenceValues"]
    assert packet["referenceValues"]["certificateValidTo"] == "2027-01-01"
    provider_question = packet["identityProviderQuestion"]
    assert "sign-in provider" in provider_question["question"]
    assert any("Microsoft Entra ID" in option for option in provider_question["options"])
    assert any("Okta" in option for option in provider_question["options"])
    assert any("Ping Identity" in option for option in provider_question["options"])
    assert "Another sign-in provider" in provider_question["options"]
    assert "No enabled SAML row" in provider_question["options"]
    assert "I'm not sure" in provider_question["options"]
    certificate_question = packet["certificateSelectionQuestion"]
    assert "Which certificate is selected" in certificate_question["question"]
    assert (
        "The certificate transferred from the completed Entra handoff"
        in certificate_question["options"]
    )
    assert (
        "A different existing Workday certificate"
        in certificate_question["options"]
    )
    assert "No certificate is selected" in certificate_question["options"]
    assert "I'm not sure" in certificate_question["options"]
    identifier_question = packet["issuerConfirmationQuestion"]
    assert "identity-provider SSO service URL" in identifier_question["question"]
    assert "sign-on redirect URL" in identifier_question["question"]
    assert "http://www.workday.com/contoso_impl" in identifier_question["question"]
    assert "Yes, all four values match exactly" in identifier_question["options"]
    assert "expiration date matches exactly" in (
        packet["certificateValidityQuestion"]["options"][0]
    )
    assert "customerTaskList" not in packet
    assert packet["actions"][0].startswith(
        "Identify which sign-in provider the enabled Workday SAML row"
    )
    assert not any(
        "network readiness" in action.casefold()
        for action in packet["actions"]
    )
    assert any(
        "already transferred during the completed Entra handoff" in action
        for action in packet["actions"]
    )
    assert "certificateName" not in packet["responseForm"]["required"]
    assert "client secrets" in packet["responseForm"]["note"]
    assert packet["responseForm"]["collection"]["mode"] == "xlsx-workbook"
    assert packet["responseForm"]["collection"]["validator"] == (
        "parse_workday_admin_return_worksheet"
    )
    assert packet["responseForm"]["collection"]["acceptedFormats"] == [
        "xlsx-workbook",
        "five-column-markdown-table",
        "labeled-worksheet",
    ]
    assert packet["engagementQuestion"].startswith("Have you looped in")
    assert packet["completionQuestion"].startswith("Has the Workday")
    assert any(
        "OAuth client ID" in item for item in packet["informationToReturn"]
    )


def test_workday_legacy_certificate_choice_remains_accepted() -> None:
    worksheet = _workday_worksheet().replace(
        "The certificate transferred from the completed Entra handoff",
        "The new certificate created from the Entra Base64 file",
    )

    parsed = parse_workday_admin_return_worksheet(
        _workday_state(),
        worksheet,
    )

    assert parsed["certificateSelectionOutcome"] == (
        "entra-signing-certificate-selected"
    )


def test_workday_packet_preserves_ambiguous_displayed_certificate_date():
    state = _workday_state()
    state["identifiers"]["signingCertificate"]["validTo"] = "10/5/2027"

    packet = build_workday_admin_packet(state)

    assert packet["referenceValues"]["certificateValidTo"] == "10/5/2027"


def test_workday_labeled_worksheet_parses_to_validated_evidence() -> None:
    parsed = parse_workday_admin_return_worksheet(
        _workday_state(),
        _workday_worksheet(),
    )

    result = validate_workday_admin_response(_workday_state(), parsed)

    assert result["identifiers"]["oauthClientId"] == "safe-client-id"
    assert result["evidence"]["rolloutType"] == "entire-workforce"
    assert "optionalDomains" not in result["evidence"]


def test_workday_legacy_authentication_policy_choice_remains_accepted() -> None:
    worksheet = _workday_worksheet().replace(
        (
            "An existing active policy scopes the ESS OAuth client and allows "
            "SAML for the intended employees"
        ),
        "An existing active policy allows SAML",
    )

    parsed = parse_workday_admin_return_worksheet(
        _workday_state(),
        worksheet,
    )

    assert parsed["authenticationPolicyOutcome"] == "existing-active-policy"


def test_workday_phase_three_worksheet_excludes_runtime_authorization() -> None:
    packet = build_workday_admin_packet(_workday_state())
    labels = packet["responseForm"]["collection"]["labels"]
    required = packet["responseForm"]["required"]

    assert "API client access" in labels
    assert "Required employee access" in labels
    assert "API client" not in labels
    assert "Network readiness" not in labels
    assert "Additional scenario domains" not in labels
    assert "apiClientOutcome" not in required
    assert "networkReadinessOutcome" not in required
    assert "optionalDomains" not in required
    assert "optionalDomains" not in ADMINISTRATOR_REQUIRED_FIELDS[
        "workday-admin"
    ]
    assert not any("authorization" in label.casefold() for label in labels)
    assert not any("retest" in label.casefold() for label in labels)
    authentication_instruction = next(
        row
        for row in packet["captureInstructions"]
        if row["information"] == "Authentication policy"
    )
    assert "ESS OAuth client identity" in (
        authentication_instruction["portalLocation"]
    )
    assert "intended employees" in authentication_instruction["instruction"]


def test_workday_customer_labeled_response_accepts_common_labels() -> None:
    worksheet = _workday_worksheet()
    for canonical, customer_label in {
        "SAML row settings": "SAML configuration",
        "Certificate expiration": "Certificate expiry date",
        "OAuth client ID": "Client ID",
        "OAuth token URL": "Token URL",
        "REST base URL": "REST URL",
        "SOAP base URL": "SOAP URL",
        "Authentication policy": "Auth policy",
        "Network readiness": "Network access",
        "Rollout": "Employee population",
        "API client access": "API access",
        "Required employee access": "Employee access",
        "Additional scenario domains": "Additional domains",
    }.items():
        worksheet = worksheet.replace(
            f"{canonical}:",
            f"{customer_label}:",
        )

    parsed = parse_workday_admin_return_worksheet(
        _workday_state(),
        worksheet,
    )

    assert parsed["oauthClientId"] == "safe-client-id"
    assert parsed["rolloutType"] == "entire-workforce"


def test_workday_completed_capture_table_parses_to_validated_evidence() -> None:
    packet = build_workday_admin_packet(_workday_state())
    assert [
        row["information"] for row in packet["captureInstructions"]
    ] == packet["responseForm"]["collection"]["labels"]
    assert all(row["exampleValue"] for row in packet["captureInstructions"])

    parsed = parse_workday_admin_return_worksheet(
        _workday_state(),
        _worksheet_table(packet, _workday_worksheet()),
    )

    result = validate_workday_admin_response(_workday_state(), parsed)
    assert result["identifiers"]["oauthClientId"] == "safe-client-id"


def test_workday_legacy_optional_fields_remain_accepted() -> None:
    worksheet = (
        _workday_worksheet()
        + "API client: An existing approved client was verified\n"
        + "Network readiness: Both Workday hosts are allowed\n"
        + "Additional scenario domains: Worker Data | custom worker lookup\n"
        + "Absence | custom leave lookup\n"
    )

    parsed = parse_workday_admin_return_worksheet(
        _workday_state(),
        worksheet,
    )

    assert parsed["apiClientOutcome"] == "existing-client-verified"
    assert parsed["networkReadinessOutcome"] == "confirmed-hosts-allowed"
    assert parsed["optionalDomains"] == [
        {
            "domain": "Worker Data",
            "scenario": "custom worker lookup",
        },
        {
            "domain": "Absence",
            "scenario": "custom leave lookup",
        },
    ]


def test_workday_generated_capture_table_omits_legacy_optional_fields() -> None:
    packet = build_workday_admin_packet(_workday_state())

    labels = packet["responseForm"]["collection"]["labels"]
    assert "API client" not in labels
    assert "Network readiness" not in labels
    assert "Additional scenario domains" not in labels


@pytest.mark.parametrize(
    "worksheet",
    [
        _workday_worksheet().replace(
            (
                "API client access: Yes, SAML Bearer, Workday Owned Scope, "
                "and all four required functional areas are configured"
            ),
            "API client access: No, one or more settings are missing",
        ),
        _workday_worksheet().replace(
            "OAuth client ID: safe-client-id\n",
            "",
        ),
        _workday_worksheet() + "Unknown field: value\n",
    ],
)
def test_workday_labeled_worksheet_rejects_incomplete_or_failed_evidence(
    worksheet: str,
) -> None:
    with pytest.raises(WorkdayConnectContractError):
        parse_workday_admin_return_worksheet(
            _workday_state(),
            worksheet,
        )


def test_workday_packet_rejects_identifier_aliasing():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso_impl",
            "entraAppIdUri": "http://www.workday.com/contoso_impl",
            "signingCertificate": {
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
        }
    )

    with pytest.raises(WorkdayConnectContractError, match="remain distinct"):
        build_workday_admin_packet(state)


def test_workday_packet_rejects_tenant_drift():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/other",
            "entraAppIdUri": ("api://44444444-4444-4444-4444-444444444444"),
            "signingCertificate": {
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
        }
    )

    with pytest.raises(WorkdayConnectContractError, match="does not match"):
        build_workday_admin_packet(deepcopy(state))


def test_workday_admin_response_validates_exact_endpoints():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }
    result = validate_workday_admin_response(
        state,
        {
            "identityProviderOutcome": "verified-entra-issuer",
            "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
            "certificateSelectionOutcome": "entra-signing-certificate-selected",
            "certificateValidityOutcome": (
                "matches-verified-entra-certificate"
            ),
            "oauthClientId": "safe-client-id",
            "apiClientOutcome": "existing-client-verified",
            "clientGrantType": "saml-bearer",
            "includeWorkdayOwnedScope": "yes",
            "identityProviderSsoServiceUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "signOnRedirectUrl": "https://www.workday.com/saml/acs",
            "oauthTokenUrl": (
                "https://example.workday.com/ccx/oauth2/contoso_impl/token"
            ),
            "restBaseUrl": "https://example.workday.com/ccx/api",
            "soapBaseUrl": "https://example.workday.com/ccx/service",
            "authenticationPolicyOutcome": "existing-active-policy",
            "networkReadinessOutcome": "confirmed-hosts-allowed",
            "rolloutType": "limited-or-test",
            "employeeSecurityGroup": "ESS Workday Pilot Employees",
            "publicWorkerReportsOutcome": "get-permission-verified",
            "integrationPermissionsGetOutcome": "get-permission-verified",
            "functionalAreaScopes": [
                "Core Payroll",
                "Organizations and Roles",
                "Staffing",
                "Time Off and Leave",
            ],
            "optionalDomains": [],
        },
    )

    assert result["endpoints"]["restBaseUrl"].endswith("/ccx/api")
    assert result["evidence"]["activeIdentityProviderIssuer"] == (
        "https://sts.windows.net/00000000-0000-0000-0000-000000000000/"
    )
    assert "certificateName" not in result["evidence"]
    assert result["evidence"]["networkReadinessOutcome"] == ("confirmed-hosts-allowed")
    assert result["evidence"]["rolloutType"] == "limited-or-test"
    assert result["evidence"]["employeeSecurityGroup"] == (
        "ESS Workday Pilot Employees"
    )


def test_workday_admin_response_enforces_limited_rollout_group():
    with pytest.raises(
        WorkdayConnectContractError,
        match="cannot use All Employees",
    ):
        validate_workday_admin_response(
            _workday_state(),
            _workday_response(employeeSecurityGroup="All Employees"),
        )


def test_workday_admin_response_omits_unrequested_optional_evidence() -> None:
    result = validate_workday_admin_response(
        _workday_state(),
        _workday_response(),
    )

    for field in (
        "apiClientOutcome",
        "networkReadinessOutcome",
        "optionalDomains",
    ):
        assert field not in result["evidence"]
        assert field not in result["partialEvidence"]


def test_workday_admin_response_requires_exact_functional_area_scopes():
    with pytest.raises(
        WorkdayConnectContractError,
        match="must contain exactly",
    ):
        validate_workday_admin_response(
            _workday_state(),
            _workday_response(
                functionalAreaScopes=["Staffing", "Personal Data"],
            ),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("clientGrantType", "authorization-code", "saml-bearer"),
        ("includeWorkdayOwnedScope", "no", "must be yes"),
        (
            "identityProviderSsoServiceUrl",
            "https://login.microsoftonline.com/other/saml2",
            "does not match",
        ),
        (
            "signOnRedirectUrl",
            "https://www.workday.com/other/acs",
            "does not match",
        ),
    ],
)
def test_workday_admin_response_enforces_api_client_and_saml_mapping(
    field,
    value,
    message,
):
    with pytest.raises(WorkdayConnectContractError, match=message):
        validate_workday_admin_response(
            _workday_state(),
            _workday_response(**{field: value}),
        )


def test_workday_admin_response_accepts_legacy_authorization_retest():
    response = _workday_response(
        authorizationOutcome="task-not-authorized-remediated",
    )
    with pytest.raises(
        WorkdayConnectContractError,
        match="authorizationRemediationDomain",
    ):
        validate_workday_admin_response(_workday_state(), response)

    result = validate_workday_admin_response(
        _workday_state(),
        {
            **response,
            "authorizationRemediationDomain": (
                "Worker Data: Public Worker Reports"
            ),
            "authorizationRemediationScenario": (
                "Signed-in employee profile read"
            ),
            "authorizationRetestOutcome": "verified-after-remediation",
        },
    )

    assert "authorizationOutcome" not in result["evidence"]
    assert "authorizationRemediationDomain" not in result["evidence"]
    assert "authorizationRemediationScenario" not in result["evidence"]
    assert "authorizationRetestOutcome" not in result["evidence"]
    assert "authorizationOutcome" not in result["partialEvidence"]


def test_partial_workday_evidence_keeps_valid_siblings() -> None:
    result = validate_administrator_partial_evidence(
        _state(),
        "workday-admin",
        {
            "oauthClientId": "safe-client-id",
            "oauthTokenUrl": "https://example.workday.com/wrong",
            "rolloutType": "limited-or-test",
        },
    )

    assert result["validFields"] == {
        "oauthClientId": "safe-client-id",
        "rolloutType": "limited-or-test",
    }
    assert set(result["fieldErrors"]) == {"oauthTokenUrl"}


def test_partial_workday_evidence_rejects_legacy_authorization_fields() -> None:
    with pytest.raises(
        WorkdayConnectContractError,
        match="unsupported fields: authorizationOutcome",
    ):
        validate_administrator_partial_evidence(
            _state(),
            "workday-admin",
            {"authorizationOutcome": "verified"},
        )


def test_partial_administrator_evidence_rejects_secret_material() -> None:
    result = validate_administrator_partial_evidence(
        _state(),
        "entra",
        {
            "certificateThumbprint": (
                "-----BEGIN PRIVATE KEY-----\nnot-safe"
            ),
        },
    )

    assert result["validFields"] == {}
    assert "secret or certificate material" in (
        result["fieldErrors"]["certificateThumbprint"]
    )


def test_partial_entra_evidence_normalizes_maker_friendly_certificate_date() -> None:
    result = validate_administrator_partial_evidence(
        _state(),
        "entra",
        {"certificateValidTo": "January 1, 2027 at 5:00 PM"},
    )

    assert result["validFields"]["certificateValidTo"] == "2027-01-01"


def test_workday_admin_response_rejects_certificate_date_drift():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="conflicts",
    ):
        validate_workday_admin_response(
            state,
            {
                "identityProviderOutcome": "verified-entra-issuer",
                "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
                "certificateSelectionOutcome": (
                    "entra-signing-certificate-selected"
                ),
                "certificateValidityOutcome": (
                    "matches-verified-entra-certificate"
                ),
                "certificateValidFrom": "2026-01-01",
                "certificateValidTo": "2028-01-01",
                "oauthClientId": "safe-client-id",
                "apiClientOutcome": "existing-client-verified",
                "clientGrantType": "saml-bearer",
                "includeWorkdayOwnedScope": "yes",
                "identityProviderSsoServiceUrl": (
                    "https://login.microsoftonline.com/"
                    "00000000-0000-0000-0000-000000000000/saml2"
                ),
                "signOnRedirectUrl": "https://www.workday.com/saml/acs",
                "oauthTokenUrl": (
                    "https://example.workday.com/ccx/oauth2/contoso_impl/token"
                ),
                "restBaseUrl": "https://example.workday.com/ccx/api",
                "soapBaseUrl": "https://example.workday.com/ccx/service",
                "authenticationPolicyOutcome": "existing-active-policy",
                "networkReadinessOutcome": "confirmed-hosts-allowed",
            },
        )


def test_workday_admin_response_rejects_conflicting_confirmed_defaults():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": "http://www.workday.com/contoso_impl",
        "certificateSelectionOutcome": "entra-signing-certificate-selected",
        "certificateValidityOutcome": "matches-verified-entra-certificate",
        "oauthClientId": "safe-client-id",
        "apiClientOutcome": "existing-client-verified",
        "clientGrantType": "saml-bearer",
        "includeWorkdayOwnedScope": "yes",
        "identityProviderSsoServiceUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "signOnRedirectUrl": "https://www.workday.com/saml/acs",
        "oauthTokenUrl": (
            "https://example.workday.com/ccx/oauth2/contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
    }

    with pytest.raises(WorkdayConnectContractError, match="Issuer conflicts"):
        validate_workday_admin_response(
            state,
            {
                **response,
                "activeIdentityProviderIssuer": "https://sts.windows.net/other/",
            },
        )

    with pytest.raises(WorkdayConnectContractError, match="Valid To date conflicts"):
        validate_workday_admin_response(
            state,
            {
                **response,
                "certificateValidTo": "2028-01-01",
            },
        )


def test_workday_admin_rejects_unused_response_fields():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="unsupported fields",
    ):
        validate_workday_admin_response(
            state,
            {
                "activeIdentityProviderIssuer": "https://sts.example/",
                "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
                "certificateName": "ESS Workday Entra signing certificate",
                "certificateValidFrom": "2026-01-01",
                "certificateValidTo": "2027-01-01",
                "oauthClientId": "safe-client-id",
                "oauthTokenUrl": (
                    "https://example.workday.com/ccx/oauth2/contoso_impl/token"
                ),
                "restBaseUrl": "https://example.workday.com/ccx/api",
                "soapBaseUrl": "https://example.workday.com/ccx/service",
                "authenticationPolicyOutcome": "existing-active-policy",
                "networkReadinessOutcome": "confirmed-hosts-allowed",
                "notes": "not part of the evidence contract",
            },
        )


def test_agent_binding_and_maker_evidence_are_strict():
    state = _state()
    state["scope"].update(
        {
            "environmentId": "environment-id",
            "agent": {"botId": "bot-id"},
        }
    )
    state["operators"]["powerPlatformMaker"] = {"username": "maker@example.com"}
    assert (
        validate_agent_binding_evidence(
            state,
            {
                "environmentId": "environment-id",
                "botId": "bot-id",
                "makerUsername": "maker@example.com",
                "workdayTopics": {
                    "expected": 23,
                    "verified": 23,
                    "active": 23,
                    "blockingDiagnostics": [],
                },
                "flowAttachment": {
                    "outcome": "maker-confirmed",
                    "botId": "bot-id",
                    "flowNames": [
                        "ESS Workday Runtime",
                        "ESS Workday Runtime REST Execution",
                    ],
                    "parameterSharingOutcome": (
                        "enabled-for-exposed-connections"
                    ),
                },
            },
        )["workdayTopics"]["active"]
        == 23
    )

    diagnostic_evidence = validate_agent_binding_evidence(
        state,
        {
            "environmentId": "environment-id",
            "botId": "bot-id",
            "makerUsername": "maker@example.com",
            "workdayTopics": {
                "expected": 23,
                "verified": 23,
                "active": 23,
                "blockingDiagnostics": [{"errorCode": "NotFound"}],
            },
            "flowAttachment": {
                "outcome": "maker-confirmed",
                "botId": "bot-id",
                "flowNames": [
                    "ESS Workday Runtime",
                    "ESS Workday Runtime REST Execution",
                ],
                "parameterSharingOutcome": (
                    "enabled-for-exposed-connections"
                ),
            },
        },
    )
    assert diagnostic_evidence["workdayTopics"]["blockingDiagnostics"] == [
        {"errorCode": "NotFound"}
    ]

    with pytest.raises(WorkdayConnectContractError, match="unsupported fields"):
        validate_maker_evidence(
            {
                "scenarioName": "Read-only scenario",
                "testUserCategory": "maker",
                "timestamp": "2026-09-25T00:00:00Z",
                "outcome": "passed",
                "employeeName": "not allowed",
            }
        )


def test_entra_check_outcome_must_match_provenance():
    app_id = "44444444-4444-4444-4444-444444444444"
    checks = _entra_checks()
    checks["nameId"] = {
        "outcome": "confirmed",
        "provenance": "microsoft-graph",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="does not match its provenance",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "object-id",
                    "servicePrincipalId": "service-principal-id",
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "scope-guid",
                "certificate": {
                    "thumbprint": "ABC123",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": checks,
            },
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "oauthTokenUrl",
            "https://example.workday.com/ccx/oauth2/other/token",
            "OAuth token URL must end exactly",
        ),
        (
            "restBaseUrl",
            "https://example.workday.com/prefix/ccx/api",
            "REST base URL must end exactly",
        ),
        (
            "soapBaseUrl",
            "https://example.workday.com/ccx/service/contoso_impl",
            "SOAP base URL must end exactly",
        ),
    ],
)
def test_workday_admin_rejects_endpoint_path_drift(
    field,
    value,
    message,
):
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "ABC123",
        "validFrom": "2026-01-01",
        "validTo": "2027-01-01",
    }
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
        "certificateSelectionOutcome": (
            "entra-signing-certificate-selected"
        ),
        "certificateValidityOutcome": (
            "matches-verified-entra-certificate"
        ),
        "oauthClientId": "safe-client-id",
        "oauthTokenUrl": ("https://example.workday.com/ccx/oauth2/contoso_impl/token"),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
    }
    response[field] = value

    with pytest.raises(WorkdayConnectContractError, match=message):
        validate_workday_admin_response(state, response)


def test_workday_admin_rejects_legacy_identity_provider_evidence():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "ABC123",
        "validFrom": "2026-01-01",
        "validTo": "2027-01-01",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="identityProviderOutcome",
    ):
        validate_workday_admin_response(
            state,
            {
                "activeIdentityProviderIssuer": "https://wrong.example/",
                "enabledServiceProviderId": (
                    "http://www.workday.com/contoso_impl"
                ),
                "certificateName": "Unrelated certificate",
                "certificateValidFrom": "2026-01-01",
                "certificateValidTo": "2027-01-01",
                "oauthClientId": "safe-client-id",
                "oauthTokenUrl": (
                    "https://example.workday.com/ccx/oauth2/"
                    "contoso_impl/token"
                ),
                "restBaseUrl": "https://example.workday.com/ccx/api",
                "soapBaseUrl": (
                    "https://example.workday.com/ccx/service"
                ),
                "authenticationPolicyOutcome": "existing-active-policy",
                "networkReadinessOutcome": "confirmed-hosts-allowed",
            },
        )


def test_workday_admin_rejects_non_workday_or_mixed_endpoint_hosts():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "ABC123",
        "validFrom": "2026-01-01",
        "validTo": "2027-01-01",
    }
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": "http://www.workday.com/contoso_impl",
        "certificateSelectionOutcome": "entra-signing-certificate-selected",
        "certificateValidityOutcome": "matches-verified-entra-certificate",
        "oauthClientId": "safe-client-id",
        "oauthTokenUrl": (
            "https://attacker.example/ccx/oauth2/contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
    }

    with pytest.raises(WorkdayConnectContractError, match="Workday-owned"):
        validate_workday_admin_response(state, response)

    response["oauthTokenUrl"] = (
        "https://other.workday.com/ccx/oauth2/contoso_impl/token"
    )
    with pytest.raises(WorkdayConnectContractError, match="same verified"):
        validate_workday_admin_response(state, response)

    response["oauthTokenUrl"] = (
        "https://example.workday.com:notaport/ccx/oauth2/"
        "contoso_impl/token"
    )
    with pytest.raises(WorkdayConnectContractError, match="HTTPS URL"):
        validate_workday_admin_response(state, response)


def test_maker_evidence_rejects_non_maker_and_invalid_timestamp() -> None:
    with pytest.raises(
        WorkdayConnectContractError,
        match="post-skill activity",
    ):
        validate_maker_evidence(
            {
                "scenarioName": "Read-only scenario",
                "testUserCategory": "non-maker employee",
                "timestamp": "2026-09-25T00:00:00Z",
                "outcome": "passed",
            }
        )

    with pytest.raises(WorkdayConnectContractError, match="ISO-8601"):
        validate_maker_evidence(
            {
                "testUserCategory": "maker",
                "timestamp": "not-a-time",
                "outcome": "passed",
            }
        )


def test_maker_validation_evidence_is_accepted() -> None:
    assert validate_maker_evidence(
        {
            "scenarioName": "View my time off balance",
            "testUserCategory": "maker",
            "timestamp": "2026-09-25T00:00:00+00:00",
            "outcome": "passed",
        }
    ) == {
        "scenarioName": "View my time off balance",
        "testUserCategory": "maker",
        "timestamp": "2026-09-25T00:00:00Z",
        "outcome": "passed",
    }


def test_maker_failure_evidence_derives_bounded_canonical_fields() -> None:
    contract = contracts.MAKER_VALIDATION_REMEDIATIONS["WD-E2E-006"]

    assert validate_maker_failure_evidence(
        {
            "remediationId": "wd-e2e-006",
            "scenarioName": "View my time off balance",
            "affectedDomain": "Worker Data: Time Off",
            "timestamp": "2026-09-25T00:00:00+00:00",
        }
    ) == {
        "remediationId": "WD-E2E-006",
        "failureCategory": contract["failureCategory"],
        "failureSurface": contract["failureSurface"],
        "timestamp": "2026-09-25T00:00:00Z",
        "remediation": contract["remediation"],
        "scenarioName": "View my time off balance",
        "affectedDomain": "Worker Data: Time Off",
    }


def test_maker_failure_evidence_requires_guided_remediation_fields() -> None:
    for missing_field in ("scenarioName", "affectedDomain"):
        evidence = {
            "remediationId": "WD-E2E-006",
            "scenarioName": "View my time off balance",
            "affectedDomain": "Worker Data: Time Off",
            "timestamp": "2026-09-25T00:00:00Z",
        }
        evidence.pop(missing_field)
        with pytest.raises(
            WorkdayConnectContractError,
            match=rf"{missing_field} is required",
        ):
            validate_maker_failure_evidence(evidence)


def test_maker_failure_evidence_rejects_unsafe_or_unbounded_fields() -> None:
    with pytest.raises(WorkdayConnectContractError, match="unsupported fields"):
        validate_maker_failure_evidence(
            {
                "remediationId": "WD-E2E-006",
                "scenarioName": "View my time off balance",
                "affectedDomain": "Worker Data: Time Off",
                "timestamp": "2026-09-25T00:00:00Z",
                "accessToken": "must-not-be-recorded",
            }
        )

    with pytest.raises(
        WorkdayConnectContractError,
        match="must be WD-E2E-006",
    ):
        validate_maker_failure_evidence(
            {
                "remediationId": "WD-E2E-123",
                "scenarioName": "View my time off balance",
                "affectedDomain": "Worker Data: Time Off",
                "timestamp": "2026-09-25T00:00:00Z",
            }
        )
