from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from workday_connect_contracts import (  # noqa: E402
    WorkdayConnectContractError,
    build_entra_handoff,
    build_workday_admin_packet,
    validate_connections_evidence,
    validate_employee_evidence,
    validate_entra_verification,
    validate_workday_admin_response,
)
from workday_connect_model import default_state  # noqa: E402


def _state():
    state = default_state()
    state["scope"].update(
        {
            "entraTenantId": "00000000-0000-0000-0000-000000000000",
            "workdayTenant": "contoso_impl",
        }
    )
    state["phases"]["preflight"]["status"] = "complete"
    return state


def test_entra_handoff_selects_only_exact_service_provider_id():
    handoff = build_entra_handoff(
        _state(),
        {
            "applications": [
                {
                    "displayName": "Workday wrong",
                    "appId": "11111111-1111-1111-1111-111111111111",
                    "objectId": "22222222-2222-2222-2222-222222222222",
                    "servicePrincipalId": "33333333-3333-3333-3333-333333333333",
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl_old"
                    ],
                },
                {
                    "displayName": "Workday exact",
                    "appId": "44444444-4444-4444-4444-444444444444",
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": "66666666-6666-6666-6666-666666666666",
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl/"
                    ],
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
    assert handoff["identifiers"]["workdaySamlEntityId"] != (
        handoff["identifiers"]["entraAppIdUri"]
    )
    assert "planHash" not in handoff


def test_entra_handoff_rejects_missing_exact_discovery():
    with pytest.raises(WorkdayConnectContractError, match="No exact"):
        build_entra_handoff(_state(), {"applications": []})


def test_entra_handoff_can_request_explicit_creation():
    handoff = build_entra_handoff(
        _state(),
        {"applications": [], "allowCreate": True},
    )

    assert handoff["target"]["mode"] == "create"
    assert handoff["identifiers"]["entraAppIdUri"] is None


def test_entra_verification_requires_all_expected_graph_evidence():
    app_id = "44444444-4444-4444-4444-444444444444"
    result = validate_entra_verification(
        _state(),
        {
            "application": {
                "displayName": "Workday exact",
                "appId": app_id,
                "objectId": "55555555-5555-5555-5555-555555555555",
                "servicePrincipalId": (
                    "66666666-6666-6666-6666-666666666666"
                ),
                "identifierUris": [
                    "http://www.workday.com/contoso_impl",
                    f"api://{app_id}",
                ],
            },
            "scopeGuid": "77777777-7777-7777-7777-777777777777",
            "checks": {
                "samlMode": True,
                "signingCertificate": True,
                "connectorPreauthorized": True,
                "graphDelegatedPermissions": True,
                "adminConsent": True,
                "userAssignmentAndNameId": True,
            },
        },
    )

    assert result["identifiers"]["entraAppId"] == app_id
    assert result["identifiers"]["entraAppIdUri"] == f"api://{app_id}"


def test_workday_packet_uses_service_provider_id_not_app_id_uri():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso_impl",
            "entraAppIdUri": (
                "api://44444444-4444-4444-4444-444444444444"
            ),
        }
    )
    packet = build_workday_admin_packet(state)

    assert packet["referenceValues"]["serviceProviderId"] == (
        "http://www.workday.com/contoso_impl"
    )
    assert packet["referenceValues"]["entraApplicationIdUri"].startswith(
        "api://"
    )
    assert "client secrets" in packet["responseForm"]["note"]


def test_workday_packet_rejects_identifier_aliasing():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso_impl",
            "entraAppIdUri": "http://www.workday.com/contoso_impl",
        }
    )

    with pytest.raises(WorkdayConnectContractError, match="remain distinct"):
        build_workday_admin_packet(state)


def test_workday_packet_rejects_tenant_drift():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/other",
            "entraAppIdUri": (
                "api://44444444-4444-4444-4444-444444444444"
            ),
        }
    )

    with pytest.raises(WorkdayConnectContractError, match="does not match"):
        build_workday_admin_packet(deepcopy(state))


def test_workday_admin_response_validates_exact_endpoints():
    result = validate_workday_admin_response(
        _state(),
        {
            "enabledServiceProviderId": (
                "http://www.workday.com/contoso_impl"
            ),
            "certificateValidFrom": "2026-01-01",
            "certificateValidTo": "2027-01-01",
            "oauthClientId": "safe-client-id",
            "oauthTokenUrl": (
                "https://example.workday.com/ccx/oauth2/"
                "contoso_impl/token"
            ),
            "restBaseUrl": "https://example.workday.com/ccx/api",
            "soapBaseUrl": (
                "https://example.workday.com/ccx/service/contoso_impl"
            ),
            "authenticationPolicyOutcome": "verified",
        },
    )

    assert result["endpoints"]["restBaseUrl"].endswith("/ccx/api")


def test_connections_and_employee_evidence_are_strict():
    assert validate_connections_evidence(
        {
            "workdayConnectionConnected": True,
            "dataverseConnectionConnected": True,
            "parameterSharingPassed": True,
            "flowAttachmentConfirmed": True,
        }
    )["parameterSharingPassed"] is True

    with pytest.raises(WorkdayConnectContractError, match="unsupported fields"):
        validate_employee_evidence(
            {
                "scenarioName": "Read-only scenario",
                "testUserCategory": "non-maker employee",
                "timestamp": "2026-09-25T00:00:00Z",
                "outcome": "passed",
                "employeeName": "not allowed",
            }
        )
