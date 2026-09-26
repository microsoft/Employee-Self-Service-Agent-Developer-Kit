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
    build_entra_plan,
    build_workday_admin_packet,
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


def test_entra_plan_selects_only_exact_service_provider_id():
    plan = build_entra_plan(
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

    assert plan["target"]["displayName"] == "Workday exact"
    assert plan["identifiers"]["workdaySamlEntityId"] == (
        "http://www.workday.com/contoso_impl"
    )
    assert plan["identifiers"]["entraAppIdUri"] == (
        "api://44444444-4444-4444-4444-444444444444"
    )
    assert plan["identifiers"]["workdaySamlEntityId"] != (
        plan["identifiers"]["entraAppIdUri"]
    )
    assert len(plan["planHash"]) == 64


def test_entra_plan_rejects_approval_before_exact_discovery():
    with pytest.raises(WorkdayConnectContractError, match="No exact"):
        build_entra_plan(_state(), {"applications": []})


def test_entra_plan_can_plan_explicit_creation():
    plan = build_entra_plan(
        _state(),
        {"applications": [], "allowCreate": True},
    )

    assert plan["target"]["mode"] == "create"
    assert plan["identifiers"]["entraAppIdUri"] is None


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
