# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agentbuilder import derive_environment_host
import install_oss_topics as installer


ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "Workday"
TARGET = installer.Target(
    environment_id="00000000-0000-0000-0000-000000000001",
    agent_id="00000000-0000-0000-0000-000000000002",
    agent_schema="gptagent_target",
    endpoint=derive_environment_host(
        "00000000-0000-0000-0000-000000000001",
        "test",
        resolver=lambda *_args: [(None, None, None, None, None)],
    ),
    ring="test",
    tenant="contoso",
)


def _wire_kinds(value):
    if isinstance(value, dict):
        return {
            "$kind" if key == "kind" else key: _wire_kinds(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_wire_kinds(child) for child in value]
    return value


def _unwire_kinds(value):
    if isinstance(value, dict):
        return {
            "kind" if key == "$kind" else key: _unwire_kinds(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_unwire_kinds(child) for child in value]
    return value


def _fake_convert(items):
    return [
        {
            "key": item["key"],
            "success": True,
            "elementType": "AdaptiveDialog",
            "objectModel": _wire_kinds(yaml.safe_load(item["yaml"])),
        }
        for item in items
    ]


def _fake_roundtrip(items):
    return [
        {
            "key": item["key"],
            "success": True,
            "elementType": "AdaptiveDialog",
            "yaml": yaml.safe_dump(_unwire_kinds(item["objectModel"])),
        }
        for item in items
    ]


def _remote_payload(*components, change_token="token-1"):
    return {
        "bot": {
            "cdsBotId": TARGET.agent_id,
            "schemaName": TARGET.agent_schema,
        },
        "changeToken": change_token,
        "botComponentChanges": [
            {"$kind": "BotComponentInsert", "component": component}
            for component in components
        ],
    }


def _dialog_component(
    schema_name,
    *,
    component_id=None,
    display_name=None,
    dialog=None,
):
    return {
        "$kind": "DialogComponent",
        "id": component_id or schema_name,
        "displayName": display_name or schema_name.rsplit(".topic.", 1)[-1],
        "schemaName": schema_name,
        "state": "Active",
        "status": "Active",
        "dialog": dialog or {"$kind": "AdaptiveDialog"},
    }


def _dependencies(entries):
    suffixes = {
        reference.rsplit(".topic.", 1)[1]
        for entry in entries
        for reference in entry.child_dialogs
    }
    return [
        _dialog_component(f"{TARGET.agent_schema}.topic.{suffix}")
        for suffix in sorted(suffixes)
    ]


class FakeTransport:
    def __init__(
        self,
        payload,
        *,
        omit_response_identity=False,
        fail_after_commit=False,
    ):
        self.payload = copy.deepcopy(payload)
        self.omit_response_identity = omit_response_identity
        self.fail_after_commit = fail_after_commit
        self.write_payloads = []
        self.read_count = 0

    def read_components(self):
        self.read_count += 1
        return copy.deepcopy(self.payload)

    def write_components(self, payload):
        self.write_payloads.append(copy.deepcopy(payload))
        change = copy.deepcopy(payload["botComponentChanges"][0])
        self.payload["botComponentChanges"].append(change)
        self.payload["changeToken"] = f"token-{len(self.write_payloads) + 1}"
        if self.fail_after_commit:
            raise installer.TransportError(
                "transport-failed",
                "lost response",
                indeterminate=True,
            )
        body = (
            {}
            if self.omit_response_identity
            else {"botComponentChanges": [change]}
        )
        return installer.BrowserResponse(200, body, "request-1")


@pytest.mark.parametrize(
    "route",
    [
        "overview",
        "details",
        "tools",
        "adaptive/b6bcb216-2247-4adb-9f00-44226f8daa48",
    ],
)
def test_browser_transport_accepts_safe_agent_configuration_routes(route):
    page = SimpleNamespace(
        url=(
            "https://copilotstudio.microsoft.com/environments/"
            f"{TARGET.environment_id}/copilots/{TARGET.agent_id}/{route}"
        )
    )

    assert installer.BrowserMinimalBotTransport._allowed_page(page)


def test_browser_transport_accepts_preview_agent_configuration_route():
    page = SimpleNamespace(
        url=(
            "https://copilotstudio.preview.microsoft.com/environments/"
            f"{TARGET.environment_id}/copilots/{TARGET.agent_id}/details"
            "?agentBackend=cosmos"
        )
    )

    assert installer.BrowserMinimalBotTransport._allowed_page(page)


@pytest.mark.parametrize("route", ["home", "topics", "activity"])
def test_browser_transport_rejects_non_configuration_routes(route):
    page = SimpleNamespace(
        url=(
            "https://copilotstudio.microsoft.com/environments/"
            f"{TARGET.environment_id}/copilots/{TARGET.agent_id}/{route}"
        )
    )

    assert not installer.BrowserMinimalBotTransport._allowed_page(page)


def test_browser_transport_selects_only_the_exact_target():
    selected = SimpleNamespace(
        url=(
            "https://copilotstudio.microsoft.com/environments/"
            f"{TARGET.environment_id}/copilots/{TARGET.agent_id}/details"
        )
    )
    unrelated = SimpleNamespace(
        url=(
            "https://copilotstudio.microsoft.com/environments/"
            f"{TARGET.environment_id}/copilots/"
            "00000000-0000-0000-0000-000000000099/details"
        )
    )
    transport = installer.BrowserMinimalBotTransport(TARGET)
    transport._browser = SimpleNamespace(
        contexts=[SimpleNamespace(pages=[unrelated, selected])]
    )

    assert transport._select_page() is selected


def test_readback_verification_ignores_server_structured_record_expression():
    expected = _dialog_component(
        "gptagent_target.topic.Example",
        dialog={
            "$kind": "AdaptiveDialog",
            "beginDialog": {
                "actions": [
                    {
                        "$kind": "SetVariable",
                        "value": {"literalValue": {"name": "example"}},
                    }
                ]
            },
        },
    )
    actual = copy.deepcopy(expected)
    actual["dialog"]["beginDialog"]["actions"][0]["value"][
        "structuredRecordExpression"
    ] = {"expression": "{name: \"example\"}"}

    verified = installer._verified_component(
        _remote_payload(actual),
        expected,
    )

    assert verified["id"] == expected["id"]


def test_manifest_has_documented_employee_manager_order():
    entries = installer.build_manifest(SAMPLES)

    assert len(entries) == 16
    assert [entry.name for entry in entries] == [
        *installer.EMPLOYEE_SCENARIOS,
        *installer.MANAGER_SCENARIOS,
    ]
    assert [entry.order for entry in entries] == list(range(1, 17))
    assert all(len(entry.source_sha256) == 64 for entry in entries)


def test_subset_contains_only_selected_scenarios():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )

    assert [entry.name for entry in entries] == ["WorkdayGetEducation"]


def test_display_prefix_applies_to_all_scenarios():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=installer.ALL_SCENARIOS,
        display_prefix="Workday OSS ",
    )

    assert len(entries) == 16
    assert [entry.name for entry in entries] == [
        *installer.EMPLOYEE_SCENARIOS,
        *installer.MANAGER_SCENARIOS,
    ]
    assert all(
        entry.display_name == f"Workday OSS {entry.name}"
        for entry in entries
    )


def test_unknown_and_duplicate_selections_fail_closed():
    with pytest.raises(installer.InstallerError, match="Unknown"):
        installer.build_manifest(SAMPLES, scenarios=["Missing"])
    with pytest.raises(installer.InstallerError, match="duplicates"):
        installer.build_manifest(
            SAMPLES,
            scenarios=["WorkdayGetEducation", "WorkdayGetEducation"],
        )


def test_resolve_target_rejects_environment_endpoint_mismatch(tmp_path):
    config = {
        "activeAgent": "hr",
        "agents": [
            {
                "slug": "hr",
                "agentId": TARGET.agent_id,
                "environmentId": "00000000-0000-0000-0000-000000000009",
                "schemaName": TARGET.agent_schema,
                "powerPlatformApiEndpoint": TARGET.endpoint,
            }
        ],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(installer.InstallerError, match="does not match"):
        installer.resolve_target(path)


def test_resolve_target_rejects_unsafe_tenant_text(tmp_path):
    config = {
        "activeAgent": "hr",
        "agents": [
            {
                "slug": "hr",
                "agentId": TARGET.agent_id,
                "environmentId": TARGET.environment_id,
                "schemaName": TARGET.agent_schema,
                "powerPlatformApiEndpoint": TARGET.endpoint,
            }
        ],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(installer.InstallerError, match="URL characters"):
        installer.resolve_target(path, tenant="contoso/path")


def test_resolve_target_accepts_explicit_values_without_config(tmp_path):
    target = installer.resolve_target(
        tmp_path / "missing.json",
        environment_id=TARGET.environment_id,
        agent_id=TARGET.agent_id,
        agent_schema=TARGET.agent_schema,
        endpoint=TARGET.endpoint,
        tenant=TARGET.tenant,
    )

    assert target == TARGET


def test_prepare_dialogs_rewrites_dependencies_and_tenant():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["EmployeeGetVacationBalance"],
    )
    payload = _remote_payload(*_dependencies(entries))

    prepared = installer.prepare_dialogs(
        entries,
        TARGET,
        payload,
        converter=_fake_convert,
        roundtrip_converter=_fake_roundtrip,
    )
    scenario = prepared["EmployeeGetVacationBalance"]
    text = json.dumps(scenario)

    assert f"{TARGET.agent_schema}.topic.WorkdaySystemGetCommonExecution" in text
    assert f"{installer.SOURCE_SCHEMA}.topic." not in text
    assert "<TENANT_NAME>" not in text
    assert "contoso" in text


def test_missing_dependency_blocks_before_any_write():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )
    transport = FakeTransport(_remote_payload())

    with pytest.raises(installer.InstallerError, match="requires exactly one"):
        installer.install_manifest(
            entries,
            TARGET,
            transport,
            dry_run=False,
            converter=_fake_convert,
            roundtrip_converter=_fake_roundtrip,
        )

    assert transport.write_payloads == []


@pytest.mark.parametrize("duplicate_key", ["display", "schema", "both"])
def test_existing_topics_are_preserved_by_display_or_schema(duplicate_key):
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )
    entry = entries[0]
    schema_name = entry.schema_name(TARGET.agent_schema)
    existing = _dialog_component(
        schema_name if duplicate_key in {"schema", "both"} else "other.topic.Setup",
        component_id="00000000-0000-0000-0000-000000000099",
        display_name=(
            entry.display_name
            if duplicate_key in {"display", "both"}
            else "Other setup"
        ),
    )
    transport = FakeTransport(
        _remote_payload(existing, *_dependencies(entries))
    )

    result = installer.install_manifest(
        entries,
        TARGET,
        transport,
        dry_run=True,
        converter=_fake_convert,
        roundtrip_converter=_fake_roundtrip,
    )

    assert result["topics"][0]["status"] == "preserved"
    assert transport.write_payloads == []


def test_display_and_schema_resolving_to_different_topics_is_ambiguous():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )
    entry = entries[0]
    transport = FakeTransport(
        _remote_payload(
            _dialog_component(
                entry.schema_name(TARGET.agent_schema),
                component_id="00000000-0000-0000-0000-000000000010",
                display_name="Different",
            ),
            _dialog_component(
                "gptagent_target.topic.Different",
                component_id="00000000-0000-0000-0000-000000000011",
                display_name=entry.display_name,
            ),
            *_dependencies(entries),
        )
    )

    with pytest.raises(installer.InstallerError, match="different existing"):
        installer.install_manifest(
            entries,
            TARGET,
            transport,
            dry_run=True,
            converter=_fake_convert,
            roundtrip_converter=_fake_roundtrip,
        )


def test_dry_run_is_deterministic_and_never_writes():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )
    payload = _remote_payload(*_dependencies(entries))
    first_transport = FakeTransport(payload)
    second_transport = FakeTransport(payload)

    first = installer.install_manifest(
        entries,
        TARGET,
        first_transport,
        dry_run=True,
        converter=_fake_convert,
        roundtrip_converter=_fake_roundtrip,
    )
    second = installer.install_manifest(
        entries,
        TARGET,
        second_transport,
        dry_run=True,
        converter=_fake_convert,
        roundtrip_converter=_fake_roundtrip,
    )

    assert first == second
    assert first["summary"] == {
        "selected": 1,
        "created": 0,
        "wouldCreate": 1,
        "preserved": 0,
    }
    assert first_transport.write_payloads == second_transport.write_payloads == []


def test_create_uses_sequential_insert_contract_and_verifies_each_readback():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=[
            "EmployeeGetVacationBalance",
            "WorkdayGetEducation",
        ],
    )
    transport = FakeTransport(_remote_payload(*_dependencies(entries)))

    result = installer.install_manifest(
        entries,
        TARGET,
        transport,
        dry_run=False,
        converter=_fake_convert,
        roundtrip_converter=_fake_roundtrip,
    )

    assert [topic["status"] for topic in result["topics"]] == [
        "created",
        "created",
    ]
    assert len(transport.write_payloads) == 2
    assert transport.read_count == 3
    for payload in transport.write_payloads:
        assert payload["changeToken"].startswith("token-")
        assert len(payload["botComponentChanges"]) == 1
        change = payload["botComponentChanges"][0]
        assert change["$kind"] == "BotComponentInsert"
        assert change["component"]["$kind"] == "DialogComponent"
        assert change["component"]["extensionData"] == {
            "UseProvidedBotComponentId": True
        }
        assert all(
            payload[key] == []
            for key in installer.EMPTY_CHANGE_COLLECTIONS
        )


def test_indeterminate_write_is_reconciled_without_retry():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )[:1]
    transport = FakeTransport(
        _remote_payload(*_dependencies(entries)),
        fail_after_commit=True,
    )

    result = installer.install_manifest(
        entries,
        TARGET,
        transport,
        dry_run=False,
        converter=_fake_convert,
        roundtrip_converter=_fake_roundtrip,
    )

    assert result["topics"][0]["status"] == (
        "created-after-indeterminate-response"
    )
    assert len(transport.write_payloads) == 1


def test_missing_write_response_identity_fails_without_retry():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )[:1]
    transport = FakeTransport(
        _remote_payload(*_dependencies(entries)),
        omit_response_identity=True,
    )

    with pytest.raises(
        installer.InstallerError,
        match="did not identify",
    ):
        installer.install_manifest(
            entries,
            TARGET,
            transport,
            dry_run=False,
            converter=_fake_convert,
            roundtrip_converter=_fake_roundtrip,
        )

    assert len(transport.write_payloads) == 1


def test_partial_failure_retains_verified_prior_results():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=[
            "EmployeeGetVacationBalance",
            "WorkdayGetEducation",
        ],
    )

    class SecondResponseMissingIdentity(FakeTransport):
        def write_components(self, payload):
            response = super().write_components(payload)
            if len(self.write_payloads) == 2:
                return installer.BrowserResponse(200, {}, "request-2")
            return response

    transport = SecondResponseMissingIdentity(
        _remote_payload(*_dependencies(entries))
    )

    with pytest.raises(installer.InstallRunError) as captured:
        installer.install_manifest(
            entries,
            TARGET,
            transport,
            dry_run=False,
            converter=_fake_convert,
            roundtrip_converter=_fake_roundtrip,
        )

    assert captured.value.failed_entry.name == "WorkdayGetEducation"
    assert [item["name"] for item in captured.value.results] == [
        "EmployeeGetVacationBalance"
    ]
    assert captured.value.results[0]["status"] == "created"


def test_blocking_diagnostics_fail_readback_verification():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )[:1]

    class DiagnosticTransport(FakeTransport):
        def write_components(self, payload):
            response = super().write_components(payload)
            component = self.payload["botComponentChanges"][-1]["component"]
            component["dialog"]["diagnostics"] = [
                {
                    "$kind": "AuthoringError",
                    "errorCode": "UnresolvedReference",
                    "errorMessage": "Missing topic",
                }
            ]
            return response

    transport = DiagnosticTransport(
        _remote_payload(*_dependencies(entries))
    )

    with pytest.raises(installer.InstallerError, match="blocking diagnostics"):
        installer.install_manifest(
            entries,
            TARGET,
            transport,
            dry_run=False,
            converter=_fake_convert,
            roundtrip_converter=_fake_roundtrip,
        )


def test_offline_plan_has_no_target_or_apply_claims():
    entries = installer.build_manifest(
        SAMPLES,
        scenarios=["WorkdayGetEducation"],
    )

    plan = installer.offline_plan(entries)

    assert plan["status"] == "offline-plan"
    assert plan["target"] is None
    assert all(
        topic["status"] == "remote-state-not-checked"
        for topic in plan["topics"]
    )


def test_browser_contract_match_rejects_extra_query_parameters():
    transport = installer.BrowserMinimalBotTransport(TARGET)
    expected = (
        f"{TARGET.endpoint}/copilotstudio/minimalBots/api/"
        f"{TARGET.agent_id}/components?api-version=2022-03-01-preview"
    )

    class Request:
        method = "POST"

        def __init__(self, url):
            self.url = url

    assert transport._matching_components_request(Request(expected))
    assert not transport._matching_components_request(
        Request(expected + "&token=not-allowed")
    )


def test_command_and_menu_registration_point_to_production_skill():
    solution = ROOT / "solutions" / "ess-maker-skills"
    prompt = (
        solution / ".github" / "prompts" / "import-oss.prompt.md"
    ).read_text(encoding="utf-8")
    menu = (
        solution / ".github" / "prompts" / "menu.prompt.md"
    ).read_text(encoding="utf-8")
    skill = (
        solution / "src" / "skills" / "topics" / "import-oss" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "description:" in prompt.split("---", 2)[1]
    assert "src/skills/topics/import-oss/SKILL.md" in prompt
    assert "| `/import-oss` |" in menu
    assert "Experimental design" not in skill
    assert "python scripts/install_oss_topics.py" in skill
