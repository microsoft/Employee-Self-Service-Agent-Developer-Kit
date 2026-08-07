# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic tests for the integration-neutral setup state domain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import setup_state
from setup_state import (
    EnvironmentType,
    InstallationStatus,
    JsonSetupStateRepository,
    ProductId,
    SetupState,
    SetupStateError,
    SetupStateService,
    SetupWorkflow,
    StepMode,
    StepStatus,
)


def _record_step(
    state: SetupState,
    step_id: str,
    *,
    mode: StepMode = StepMode.AUTOMATED,
    checkpoint: str | None = None,
) -> None:
    if checkpoint is None:
        checkpoint = {
            "SETUP-02.1": "ENV-002",
            "SETUP-02.2": "ENV-CAPACITY-001",
            "SETUP-03": "ENV-001",
            "SETUP-04": "ENV-009",
        }.get(step_id)
    SetupWorkflow.record_step_result(
        state,
        step_id=step_id,
        mode=mode,
        checkpoint=checkpoint,
    )


def _complete_through_environment(state: SetupState) -> None:
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )
    for step_id, checkpoint in (
        ("SETUP-02.1", "ENV-002"),
        ("SETUP-02.2", "ENV-CAPACITY-001"),
        ("SETUP-03", "ENV-001"),
    ):
        _record_step(state, step_id, checkpoint=checkpoint)
        SetupWorkflow.update_step(state, step_id, StepStatus.DONE)


def _complete_through_alm(state: SetupState) -> None:
    _complete_through_environment(state)
    SetupWorkflow.skip_alm(state)
    SetupWorkflow.update_step(state, "SETUP-04", StepStatus.DONE)


def test_new_state_has_one_deterministic_resume_step() -> None:
    state = SetupState()

    assert state.active_step == "SETUP-01"
    assert SetupWorkflow.next_step(state) == "SETUP-01"
    assert all(record.state == "pending" for record in state.steps.values())
    assert set(state.products) == {
        "da.esshr",
        "da.essit",
        "da.esshub",
        "cea.esshr",
        "cea.essit",
        "cea.esshub",
    }


def test_workflow_rejects_multiple_in_progress_steps() -> None:
    state = SetupState()
    state.steps["SETUP-01"].state = StepStatus.IN_PROGRESS
    state.steps["SETUP-02.1"].state = StepStatus.IN_PROGRESS

    with pytest.raises(SetupStateError, match="Only one"):
        SetupWorkflow.validate(state)


def test_step_updates_advance_to_first_incomplete_step() -> None:
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )
    _record_step(state, "SETUP-02.1", checkpoint="ENV-002")
    SetupWorkflow.update_step(state, "SETUP-02.1", StepStatus.DONE)

    assert state.active_step == "SETUP-02.2"


def test_done_step_cannot_regress() -> None:
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )

    with pytest.raises(SetupStateError, match="Invalid transition"):
        SetupWorkflow.update_step(
            state,
            "SETUP-01",
            StepStatus.IN_PROGRESS,
        )


def test_step_result_contract_is_persisted() -> None:
    state = SetupState()

    SetupWorkflow.record_step_result(
        state,
        step_id="SETUP-02.1",
        mode=StepMode.MANUAL_ATTESTED,
        checkpoint="ENV-002",
    )

    record = state.steps["SETUP-02.1"]
    assert record.mode == "manual-attested"
    assert 10 <= len(record.note.split()) <= 12
    assert record.checkpoint == "ENV-002"
    assert record.recorded_at is not None


def test_step_notes_are_specific_and_concise() -> None:
    assert len(set(setup_state.STEP_NOTES.values())) == len(
        setup_state.STEP_NOTES
    )
    assert all(
        10 <= len(note.split()) <= 12
        for note in setup_state.STEP_NOTES.values()
    )


def test_current_state_view_is_compact() -> None:
    state = SetupState()
    view = setup_state._state_view(state, "current")

    assert view == {
        "active_step": "SETUP-01",
        "state": "pending",
        "note": None,
        "failure_causes": [],
        "connect_ready": False,
        "environment": {
            "locked": False,
            "tenant_endpoint": None,
        },
        "completed_steps": [],
    }
    assert "products" not in view
    assert "steps" not in view


def test_targeted_state_views_include_only_requested_domain() -> None:
    state = SetupState()
    state.environment = {"name": "Development"}
    state.selected_products = [ProductId.DA_ESSHR]
    state.products[ProductId.DA_ESSHR].selected = True

    environment = setup_state._state_view(state, "environment")
    products = setup_state._state_view(state, "products")

    assert environment == {
        "active_step": "SETUP-01",
        "environment": {"name": "Development"},
    }
    assert set(products) == {
        "active_step",
        "selected_products",
        "products",
    }
    assert set(products["products"]) == {"da.esshr"}


def test_mutation_result_reports_only_delta_and_next_step() -> None:
    state = SetupState()

    result = setup_state._mutation_result(
        state,
        command="update-step",
        changed="SETUP-01 is in-progress",
    )

    assert result == {
        "status": "ok",
        "command": "update-step",
        "changed": "SETUP-01 is in-progress",
        "active_step": "SETUP-01",
    }


def test_environment_checkpoint_refreshes_verification_time() -> None:
    state = SetupState()
    state.environment = {
        "locked": True,
        "verified_at": "2026-08-05T00:00:00+00:00",
    }

    SetupWorkflow.record_step_result(
        state,
        step_id="SETUP-03",
        checkpoint="ENV-001",
        mode=StepMode.AUTOMATED,
    )

    assert state.environment["verified_at"] == (
        state.steps["SETUP-03"].recorded_at
    )


def test_json_repository_round_trips_atomically(tmp_path: Path) -> None:
    state_path = tmp_path / ".local" / "setup" / "config.json"
    repository = JsonSetupStateRepository(state_path)
    state = SetupState()
    state.selected_products = [
        ProductId.DA_ESSHR,
        ProductId.CEA_ESSIT,
    ]
    state.products[ProductId.DA_ESSHR].selected = True
    state.products[ProductId.DA_ESSHR].installation_status = (
        InstallationStatus.PENDING
    )
    state.products[ProductId.CEA_ESSIT].selected = True
    state.products[ProductId.CEA_ESSIT].installation_status = (
        InstallationStatus.PENDING
    )

    repository.save(state)
    loaded = repository.load()

    assert loaded.selected_products == ["da.esshr", "cea.essit"]
    assert loaded.active_step == "SETUP-01"
    assert not list(state_path.parent.glob("*.tmp"))


def test_legacy_validation_collection_is_rejected() -> None:
    raw = SetupState().to_dict()
    raw["validations"] = {
        "SETUP-SCOPE-001": {"status": "pass"},
    }

    with pytest.raises(SetupStateError, match="unexpected fields"):
        SetupState.from_dict(raw)


def test_repository_rejects_corrupt_state(tmp_path: Path) -> None:
    state_path = tmp_path / "config.json"
    state_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(SetupStateError, match="unreadable"):
        JsonSetupStateRepository(state_path).load()


@pytest.mark.parametrize("corruption", [
    "step-string",
    "step-unknown-key",
    "products-container-list",
    "product-string",
])
def test_repository_normalizes_malformed_records(
    tmp_path: Path,
    corruption: str,
) -> None:
    state_path = tmp_path / "config.json"
    raw = SetupState().to_dict()
    if corruption == "step-string":
        raw["steps"]["SETUP-01"] = "not-a-step-record"
    elif corruption == "step-unknown-key":
        raw["steps"]["SETUP-01"] = {"unknown": True}
    elif corruption == "products-container-list":
        raw["products"] = []
    else:
        raw["products"]["da.esshr"] = "not-a-product-record"
    state_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SetupStateError, match="malformed"):
        JsonSetupStateRepository(state_path).load()


def test_manual_attestation_records_mode_without_duplicate_evidence() -> None:
    state = SetupState()

    SetupWorkflow.record_step_result(
        state,
        step_id="SETUP-02.1",
        mode=StepMode.MANUAL_ATTESTED,
        checkpoint="ENV-002",
    )

    assert state.steps["SETUP-02.1"].mode == StepMode.MANUAL_ATTESTED


def test_steps_cannot_complete_out_of_order() -> None:
    state = SetupState()
    _record_step(state, "SETUP-02.1", checkpoint="ENV-002")

    with pytest.raises(SetupStateError, match="prior steps"):
        SetupWorkflow.update_step(state, "SETUP-02.1", StepStatus.DONE)


def test_locked_scope_cannot_drift() -> None:
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )
    SetupWorkflow.select_initial_product(state, ProductId.DA_ESSHR)

    with pytest.raises(SetupStateError, match="scope is locked"):
        SetupWorkflow.set_scope(
            state,
            environment_id="env-2",
            environment_name="Production",
            environment_type=EnvironmentType.PROD,
            tenant_endpoint="https://prod.crm.dynamics.com",
        )


def test_scope_accepts_discovered_power_platform_environment_type() -> None:
    state = SetupState()

    SetupWorkflow.set_scope(
        state,
        environment_id="environment-id",
        environment_name="Developer Environment",
        environment_type="Developer",
        tenant_endpoint="https://dev.crm.dynamics.com",
    )

    assert state.environment["type"] == "Developer"
    assert state.environment["verified_at"] == state.environment["selected_at"]
    assert state.selected_products == []
    assert not hasattr(state.steps["SETUP-01"], "evidence")
    assert state.steps["SETUP-01"].mode == StepMode.AUTOMATED


def test_product_selection_has_a_separate_cli_transition() -> None:
    args = setup_state.build_parser().parse_args([
        "select-product",
        "--product",
        "da.esshr",
    ])

    assert args.command == "select-product"
    assert args.product == "da.esshr"


def test_initial_product_selection_requires_locked_environment() -> None:
    state = SetupState()

    with pytest.raises(SetupStateError, match="environment is locked"):
        SetupWorkflow.select_initial_product(state, ProductId.DA_ESSHR)


def test_initial_product_can_only_be_selected_once() -> None:
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )
    SetupWorkflow.select_initial_product(state, ProductId.DA_ESSHR)

    with pytest.raises(SetupStateError, match="already selected"):
        SetupWorkflow.select_initial_product(state, ProductId.CEA_ESSIT)


def test_product_installation_states_are_independent() -> None:
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )
    SetupWorkflow.select_initial_product(state, ProductId.DA_ESSHR)
    state.selected_products.append(ProductId.CEA_ESSIT)
    state.products[ProductId.CEA_ESSIT].selected = True
    state.products[ProductId.CEA_ESSIT].installation_status = (
        InstallationStatus.PENDING
    )

    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSHR,
        InstallationStatus.INSTALLING,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSHR,
        InstallationStatus.INSTALLED,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSHR,
        InstallationStatus.BOUND,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.CEA_ESSIT,
        InstallationStatus.CONNECTION_REQUIRED,
    )

    assert state.products["da.esshr"].installation_status == "bound"
    assert (
        state.products["cea.essit"].installation_status
        == "connection-required"
    )
    assert state.products["da.essit"].installation_status == "not-selected"


def test_unselected_product_cannot_be_updated() -> None:
    state = SetupState()

    with pytest.raises(SetupStateError, match="unselected product"):
        SetupWorkflow.update_product_installation(
            state,
            ProductId.DA_ESSHR,
            InstallationStatus.INSTALLING,
        )


def test_install_step_requires_every_selected_product_to_be_bound() -> None:
    state = SetupState()
    _complete_through_alm(state)
    state.selected_products = [ProductId.DA_ESSHR]
    state.products[ProductId.DA_ESSHR].selected = True
    state.products[ProductId.DA_ESSHR].installation_status = (
        InstallationStatus.INSTALLED
    )
    _record_step(state, "SETUP-05")

    with pytest.raises(SetupStateError, match="not installed and bound"):
        SetupWorkflow.update_step(state, "SETUP-05", StepStatus.DONE)


def test_installation_progress_updates_are_resumable() -> None:
    state = SetupState()
    state.selected_products = [ProductId.DA_ESSHR]
    state.products[ProductId.DA_ESSHR].selected = True
    state.products[ProductId.DA_ESSHR].installation_status = (
        InstallationStatus.INSTALLING
    )

    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSHR,
        InstallationStatus.INSTALLING,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSHR,
        InstallationStatus.INSTALLED,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSHR,
        InstallationStatus.INSTALLED,
    )

    assert state.products["da.esshr"].installation_status == "installed"


def test_invoker_connection_requires_maker_attestation_before_bound() -> None:
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="env-1",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://dev.crm.dynamics.com",
    )
    SetupWorkflow.select_initial_product(state, ProductId.DA_ESSIT)
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSIT,
        InstallationStatus.INSTALLING,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSIT,
        InstallationStatus.INSTALLED,
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSIT,
        InstallationStatus.CONNECTION_ATTESTATION_REQUIRED,
        connection_name="alchemy",
        schema_name="msdyn_CopilotForEmployeeSelfServiceDAIT",
        requires_connection_attestation=True,
        agent_id="agent-id",
        agent_name="Employee Self-Service IT",
        connection_settings_url=(
            "https://copilotstudio.microsoft.com/environments/"
            "env-1/copilots/agent-id/settings/connectionSettings"
        ),
    )

    with pytest.raises(SetupStateError, match="requires maker connection"):
        SetupWorkflow.update_product_installation(
            state,
            ProductId.DA_ESSIT,
            InstallationStatus.BOUND,
        )

    SetupWorkflow.attest_product_connection(state, ProductId.DA_ESSIT)

    product = state.products["da.essit"]
    assert product.installation_status == "bound"
    assert product.connection_attested_at is not None
    assert product.agent_id == "agent-id"


def test_verified_alm_solution_metadata_is_persisted() -> None:
    state = SetupState()

    SetupWorkflow.set_alm(
        state,
        solution_id="11111111-1111-1111-1111-111111111111",
        solution_name="ContosoESS",
        publisher_prefix="contoso",
        version="1.0.0.0",
    )

    assert state.alm == {
        "status": "configured",
        "solution_id": "11111111-1111-1111-1111-111111111111",
        "solution_name": "ContosoESS",
        "publisher_prefix": "contoso",
        "version": "1.0.0.0",
        "preferred": True,
        "updated_at": state.alm["updated_at"],
    }


def test_alm_solution_metadata_cannot_be_incomplete() -> None:
    state = SetupState()

    with pytest.raises(SetupStateError, match="publisher_prefix"):
        SetupWorkflow.set_alm(
            state,
            solution_id="11111111-1111-1111-1111-111111111111",
            solution_name="ContosoESS",
            publisher_prefix="",
            version="1.0.0.0",
        )


def test_optional_alm_step_can_complete_without_env009() -> None:
    state = SetupState()
    _complete_through_environment(state)
    SetupWorkflow.skip_alm(state)
    SetupWorkflow.update_step(state, "SETUP-04", StepStatus.DONE)

    assert state.steps["SETUP-04"].state == StepStatus.DONE
    assert state.steps["SETUP-04"].checkpoint is None
    assert state.steps["SETUP-04"].mode == "skipped"
    assert state.steps["SETUP-04"].recorded_at is not None
    assert state.alm["status"] == "skipped"
    assert state.alm["reason"] == "maker-selected"


def test_configured_alm_step_requires_env009_to_pass() -> None:
    state = SetupState()
    _complete_through_environment(state)
    SetupWorkflow.set_alm(
        state,
        solution_id="11111111-1111-1111-1111-111111111111",
        solution_name="ContosoESS",
        publisher_prefix="contoso",
        version="1.0.0.0",
    )

    with pytest.raises(SetupStateError, match="step result is not recorded"):
        SetupWorkflow.update_step(state, "SETUP-04", StepStatus.DONE)

    SetupWorkflow.record_step_result(
        state,
        step_id="SETUP-04",
        checkpoint="ENV-009",
        mode=StepMode.AUTOMATED,
    )
    SetupWorkflow.update_step(state, "SETUP-04", StepStatus.DONE)

    assert state.steps["SETUP-04"].state == StepStatus.DONE


def test_adding_product_reopens_only_dependent_foundation_steps() -> None:
    state = SetupState()
    state.environment = {"locked": True}
    state.selected_products = [ProductId.DA_ESSHR]
    state.products[ProductId.DA_ESSHR].selected = True
    state.products[ProductId.DA_ESSHR].installation_status = (
        InstallationStatus.BOUND
    )
    state.products[ProductId.DA_ESSHR].ready = True
    for record in state.steps.values():
        record.state = StepStatus.DONE
    state.active_step = "SETUP-07"
    state.connect_ready = True
    state.completed_at = "2026-08-04T00:00:00+00:00"
    _record_step(state, "SETUP-05")
    _record_step(state, "SETUP-07")

    SetupWorkflow.add_products(state, (ProductId.CEA_ESSIT,))

    assert state.selected_products == ["da.esshr", "cea.essit"]
    assert state.products["da.esshr"].installation_status == "bound"
    assert state.products["da.esshr"].ready is True
    assert state.products["cea.essit"].installation_status == "pending"
    assert state.steps["SETUP-04"].state == "done"
    assert state.steps["SETUP-05"].state == "pending"
    assert state.steps["SETUP-06"].state == "pending"
    assert state.steps["SETUP-07"].state == "pending"
    assert state.active_step == "SETUP-05"
    assert state.connect_ready is False
    assert state.completed_at is None
    assert state.steps["SETUP-05"].recorded_at is None
    assert state.steps["SETUP-07"].recorded_at is None


def test_product_cannot_be_added_before_foundation_completes() -> None:
    state = SetupState()
    state.environment = {"locked": True}

    with pytest.raises(SetupStateError, match="only after foundation"):
        SetupWorkflow.add_products(state, (ProductId.DA_ESSHR,))


def test_finalize_requires_all_prior_steps() -> None:
    state = SetupState()

    with pytest.raises(SetupStateError, match="incomplete steps"):
        SetupWorkflow.finalize(state)


def test_final_step_cannot_bypass_bundle() -> None:
    state = SetupState()

    with pytest.raises(SetupStateError, match="final setup bundle"):
        SetupWorkflow.update_step(state, "SETUP-07", StepStatus.DONE)


def test_finalize_marks_connect_ready() -> None:
    state = SetupState()
    _complete_through_alm(state)
    SetupWorkflow.select_initial_product(state, ProductId.DA_ESSHR)
    state.products[ProductId.DA_ESSHR].installation_status = (
        InstallationStatus.BOUND
    )
    state.products[ProductId.DA_ESSHR].ready = True
    for step_id in ("SETUP-05", "SETUP-06"):
        _record_step(state, step_id)
        SetupWorkflow.update_step(state, step_id, StepStatus.DONE)
    _record_step(
        state,
        "SETUP-07",
        mode=StepMode.MANUAL_ATTESTED,
    )

    SetupWorkflow.finalize(state)

    assert state.steps["SETUP-07"].state == "done"
    assert state.connect_ready is True
    assert state.completed_at is not None


def test_setup_cannot_complete_without_selected_product() -> None:
    state = SetupState()
    _complete_through_alm(state)
    _record_step(state, "SETUP-05")

    with pytest.raises(SetupStateError, match="no ESS product"):
        SetupWorkflow.update_step(state, "SETUP-05", StepStatus.DONE)
