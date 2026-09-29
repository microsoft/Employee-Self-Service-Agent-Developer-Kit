# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the compact Workday connect lifecycle model."""

from __future__ import annotations

import pytest


def test_default_state_has_six_primary_phases() -> None:
    import workday_connect_model as model

    state = model.default_state()

    assert list(state["phases"]) == [
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "employee-validation",
    ]
    assert model.next_phase_id(state) == "preflight"
    assert state["status"] == "in-progress"
    assert state["schemaVersion"] == 5
    assert state["tenantFoundation"] is None


def test_workday_saml_entity_id_is_not_the_entra_app_uri() -> None:
    import workday_connect_model as model

    entity_id = model.workday_saml_entity_id("contoso_prod")

    assert entity_id == "http://www.workday.com/contoso_prod"
    assert not entity_id.startswith("api://")


@pytest.mark.parametrize("tenant", ["", "https://tenant", "tenant value", "api://id"])
def test_workday_saml_entity_id_rejects_invalid_tenant(tenant: str) -> None:
    import workday_connect_model as model

    with pytest.raises(model.WorkdayConnectModelError):
        model.workday_saml_entity_id(tenant)


def test_plan_hash_is_stable_and_ignores_embedded_hash() -> None:
    import workday_connect_model as model

    plan = {
        "phase": "entra",
        "scope": {"tenantId": "tenant", "applicationId": "app"},
        "actions": ["configure-saml", "configure-scope"],
    }
    observed = model.plan_hash(plan)

    assert observed == model.plan_hash({**plan, "planHash": observed})
    assert observed != model.plan_hash({**plan, "actions": ["configure-saml"]})


def test_sensitive_fields_are_rejected() -> None:
    import workday_connect_model as model

    with pytest.raises(model.WorkdayConnectModelError, match="must not be persisted"):
        model.reject_sensitive_data({"nested": {"access_token": "secret"}})


def test_progress_text_is_a_visible_phase_roadmap() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["preflight"]["status"] = "complete"
    state["phases"]["entra"]["status"] = "active"

    assert model.progress_text(state) == (
        "### Workday connection progress\n"
        "\n"
        "| # | Phase | Status |\n"
        "|---:|---|---|\n"
        "| 1 | Preflight | Complete |\n"
        "| 2 | Microsoft Entra | In progress |\n"
        "| 3 | Workday administrator | Pending |\n"
        "| 4 | Connections | Pending |\n"
        "| 5 | Runtime configuration | Pending |\n"
        "| 6 | Employee validation | Pending |"
    )
    assert model.next_phase_summary(state) == {
        "id": "entra",
        "title": "Microsoft Entra",
        "whatHappens": [
            (
                "Find the exact Workday enterprise application in the selected "
                "Microsoft Entra tenant."
            ),
            (
                "Guide an Entra administrator through the required SAML, "
                "permission, consent, assignment, and employee sign-in settings."
            ),
            "Verify the application and signing-certificate configuration.",
        ],
    }


def test_pending_current_phase_is_marked_next() -> None:
    import workday_connect_model as model

    state = model.default_state()

    assert "| 1 | Preflight | Next |" in model.progress_text(state)


def test_blocked_phase_requires_complete_blocker_evidence() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["preflight"]["status"] = "blocked"

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="complete blocker",
    ):
        model.validate_state(state)
