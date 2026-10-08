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
        "maker-validation",
    ]
    assert model.next_phase_id(state) == "preflight"
    assert state["status"] == "in-progress"
    assert state["schemaVersion"] == 12
    assert state["activeTargetRealm"] == "dev"
    assert list(state["targets"]) == ["dev", "test", "prod"]
    assert state["targets"]["dev"]["deploymentStatus"] == (
        "needs-configuration"
    )
    assert state["targets"]["test"] is None
    assert state["targets"]["prod"] is None
    assert state["lifecycle"]["correlationId"]
    assert state["lifecycle"]["journal"] == []
    assert state["tenantFoundation"] is None
    assert state["phases"]["entra"]["administrator"] == {
        "substage": "not-started",
        "partialEvidence": {},
        "invalidFields": [],
        "updatedAt": None,
    }
    assert state["phases"]["workday-admin"]["administrator"] == (
        state["phases"]["entra"]["administrator"]
    )
    assert "administrator" not in state["phases"]["runtime"]


def test_active_target_projection_cannot_diverge() -> None:
    import pytest

    import workday_connect_model as model

    state = model.default_state()
    state["scope"]["environmentId"] = "different"

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="active target projection is inconsistent",
    ):
        model.validate_state(state)


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("microsoft_dpt6", "microsoft_dpt6"),
        (
            "https://wd2-impl-services1.workday.com/ccx/oauth2/"
            "microsoft_dpt6/token",
            "microsoft_dpt6",
        ),
        (
            "https://impl.workday.com/microsoft_dpt6/login-saml.htmld",
            "microsoft_dpt6",
        ),
        (
            "https://impl.workday.com/wday/authgwy/microsoft_dpt6/login.htmld",
            "microsoft_dpt6",
        ),
        (
            "https://wd5.myworkday.com/microsoft_dpt6/d/home.htmld",
            "microsoft_dpt6",
        ),
    ],
)
def test_normalize_workday_tenant_input_accepts_known_shapes(
    value: str,
    expected: str,
) -> None:
    import workday_connect_model as model

    assert model.normalize_workday_tenant_input(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/ccx/oauth2/microsoft_dpt6/token",
        "https://impl.workday.com/unrecognized/path",
        "api://microsoft_dpt6",
    ],
)
def test_normalize_workday_tenant_input_rejects_unknown_shapes(
    value: str,
) -> None:
    import workday_connect_model as model

    with pytest.raises(model.WorkdayConnectModelError):
        model.normalize_workday_tenant_input(value)


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
        "| 2 | Microsoft Entra | Current |\n"
        "| 3 | Workday administrator | Pending |\n"
        "| 4 | Connections | Pending |\n"
        "| 5 | Runtime configuration | Pending |\n"
        "| 6 | Maker validation | Pending |"
    )
    assert model.next_phase_summary(state) == {
        "id": "entra",
        "title": "Microsoft Entra",
        "whatHappens": [
            "Give the Microsoft Entra administrator one complete guided handoff.",
            (
                "Guide an Entra administrator through the required SAML, "
                "permission, consent, assignment, and employee sign-in settings."
            ),
            (
                "Validate and record the administrator's returned non-secret "
                "application and signing-certificate evidence."
            ),
        ],
    }


def test_maker_validation_summary_preserves_test_then_publish_order() -> None:
    import workday_connect_model as model

    state = model.default_state()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
    ):
        state["phases"][phase_id]["status"] = "complete"

    assert model.next_phase_summary(state) == {
        "id": "maker-validation",
        "title": "Maker validation",
        "whatHappens": [
            (
                "Smoke-test an enabled read-only Workday scenario in the "
                "Copilot Studio Test pane without publishing the agent."
            ),
            (
                "Complete the guided Workday connection lifecycle when the "
                "maker scenario returns the expected employee context and "
                "Workday data."
            ),
            (
                "Show publishing, deployment, employee-owned connections, and "
                "non-maker Microsoft 365 Chat validation as post-skill next "
                "steps."
            ),
        ],
    }


def test_pending_current_phase_and_following_phases_are_pending() -> None:
    import workday_connect_model as model

    state = model.default_state()

    progress = model.progress_text(state)
    assert "| 1 | Preflight | Current |" in progress
    assert "| 2 | Microsoft Entra | Pending |" in progress


def test_blocked_current_phase_is_marked_as_needing_attention() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["preflight"].update(
        {
            "status": "blocked",
            "blockerCode": "AUTH_REQUIRED",
            "blockerDetail": "Sign in again.",
        }
    )

    progress = model.progress_text(state)
    assert "| 1 | Preflight | Current - needs attention |" in progress
    assert "| 2 | Microsoft Entra | Pending |" in progress


def test_blocked_phase_requires_complete_blocker_evidence() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["preflight"]["status"] = "blocked"

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="complete blocker",
    ):
        model.validate_state(state)


def test_administrator_partial_evidence_is_allow_listed() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["entra"]["administrator"]["partialEvidence"] = {
        "accessToken": "must-not-be-stored",
    }

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="must not be persisted",
    ):
        model.validate_state(state)


def test_evidence_validated_requires_complete_phase() -> None:
    import workday_connect_model as model

    state = model.default_state()
    state["phases"]["entra"]["administrator"]["substage"] = (
        "evidence-validated"
    )

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="before the phase is complete",
    ):
        model.validate_state(state)
