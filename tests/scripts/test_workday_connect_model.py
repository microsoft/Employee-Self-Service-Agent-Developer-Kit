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
    assert state["schemaVersion"] == 3


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
    assert observed != model.plan_hash(
        {**plan, "actions": ["configure-saml"]}
    )


def test_sensitive_fields_are_rejected() -> None:
    import workday_connect_model as model

    with pytest.raises(model.WorkdayConnectModelError, match="must not be persisted"):
        model.reject_sensitive_data({"nested": {"access_token": "secret"}})


def test_progress_text_is_compact() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["preflight"]["status"] = "complete"
    state["phases"]["entra"]["status"] = "active"

    assert model.progress_text(state) == (
        "Progress: Preflight ✓ · Entra → · Workday · Connections · "
        "Runtime · Validate"
    )
