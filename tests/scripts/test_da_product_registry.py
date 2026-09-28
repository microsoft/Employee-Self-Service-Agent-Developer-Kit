# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json

import da_product_registry


def test_observe_product_mapping_upserts_newest_workspace_value(tmp_path) -> None:
    da_product_registry.observe_product_mapping(
        tmp_path,
        product_key="employee-self-service-hr",
        package_id="pkg-old",
        catalog_name="Employee Self-Service (HR)",
        agent_schema_name="schema-old",
        source="first observation",
        environment_id="environment-1",
        ring="test",
    )

    result = da_product_registry.observe_product_mapping(
        tmp_path,
        product_key="employee-self-service-hr",
        package_id="pkg-new",
        catalog_name="Employee Self-Service (HR)",
        agent_schema_name="schema-new",
        source="setup_mos_starter.py create collision",
        environment_id="environment-1",
        ring="test",
    )

    observations = da_product_registry.load_product_observations(tmp_path)
    assert len(observations) == 1
    assert observations[0]["packageId"] == "pkg-new"
    assert observations[0]["agentSchemaName"] == "schema-new"
    assert observations[0]["source"] == (
        "setup_mos_starter.py create collision"
    )
    assert observations[0]["observedAt"].endswith("Z")
    assert observations[0]["environmentId"] == "environment-1"
    assert observations[0]["ring"] == "test"
    assert observations[0]["installed"] is True
    assert result["path"] == (
        ".local/setup/da-product-observations.json"
    )


def test_workspace_observation_precedes_checked_in_seed(tmp_path) -> None:
    da_product_registry.observe_product_mapping(
        tmp_path,
        product_key="workspace-hr",
        package_id="pkg-hr",
        catalog_name="Employee Self-Service (HR)",
        agent_schema_name="workspace-schema",
        source="runtime evidence",
        environment_id="environment-1",
        ring="test",
    )

    result = da_product_registry.resolve_product_identity(
        package_id="pkg-hr",
        catalog_name="Employee Self-Service (HR)",
        kit_root=tmp_path,
    )

    assert result is not None
    assert result["productKey"] == "workspace-hr"
    assert result["agentSchemaName"] == "workspace-schema"
    assert result["identitySource"] == "workspace-observation"
    assert "installed" not in result


def test_workspace_observation_reports_installed_only_for_matching_target(
    tmp_path,
) -> None:
    da_product_registry.observe_product_mapping(
        tmp_path,
        product_key="workspace-it",
        package_id="pkg-it",
        catalog_name="Employee Self-Service (IT)",
        agent_schema_name="workspace-it-schema",
        source="setup_mos_starter.py create collision",
        environment_id="environment-1",
        ring="test",
    )

    matching = da_product_registry.resolve_product_identity(
        package_id="pkg-it",
        catalog_name="Employee Self-Service (IT)",
        kit_root=tmp_path,
        environment_id="environment-1",
        ring="test",
    )
    other_environment = da_product_registry.resolve_product_identity(
        package_id="pkg-it",
        catalog_name="Employee Self-Service (IT)",
        kit_root=tmp_path,
        environment_id="environment-2",
        ring="test",
    )

    assert matching is not None
    assert matching["installed"] is True
    assert other_environment is not None
    assert "installed" not in other_environment


def test_observe_command_emits_recorded_mapping(
    tmp_path,
    capsys,
) -> None:
    exit_code = da_product_registry.main(
        [
            "observe",
            "--kit-root",
            str(tmp_path),
            "--product-key",
            "employee-self-service-hub",
            "--package-id",
            "pkg-hub",
            "--catalog-name",
            "Employee Self-Service",
            "--agent-schema-name",
            "gptagent_copilotforemployeeselfservicecore",
            "--source",
            "setup_mos_starter.py create",
            "--environment-id",
            "environment-1",
            "--ring",
            "test",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    payload = json.loads(output.split("DA_PRODUCT_OBSERVATION_JSON:", 1)[1])
    assert payload["productKey"] == "employee-self-service-hub"
    assert payload["packageId"] == "pkg-hub"
    assert payload["environmentId"] == "environment-1"
    assert payload["ring"] == "test"
    assert payload["installed"] is True
