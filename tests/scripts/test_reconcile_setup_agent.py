# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path

import pytest

import reconcile_setup_agent as reconcile
from agentbuilder import AgentBuilderError


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
DATAVERSE_URL = "https://example.crm.dynamics.com"


@pytest.mark.parametrize(
    ("schema_name", "expected"),
    [
        ("msdyn_copilotforemployeeselfservice", "cea"),
        ("msdyn_copilotforemployeeselfservicecore", "cea"),
        ("msdyn_copilotforemployeeselfservicehr", "cea"),
        ("msdyn_copilotforemployeeselfserviceit", "cea"),
        ("gptagent_copilotforemployeeselfservice", "da"),
        ("gptagent_copilotforemployeeselfservicecore", "da"),
        ("gptagent_copilotforemployeeselfservicehr", "da"),
        ("gptagent_copilotforemployeeselfserviceit", "da"),
        ("gptagent_employee_self_service", "unknown"),
        ("MSDYN_COPILOTFOREMPLOYEESELFSERVICEHR", "cea"),
        (None, "unknown"),
    ],
)
def test_classifies_only_exact_recognized_schema_names(
    schema_name: str | None,
    expected: str,
) -> None:
    assert reconcile.classify_schema_name(schema_name) == expected


def test_authoritative_native_evidence_short_circuits_remote_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: pytest.fail("native lookup should be skipped"),
    )
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: pytest.fail("Dataverse lookup should be skipped"),
    )

    result = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        native_da_ga=True,
    )

    assert result == {
        "action": "continue-da-ga-setup",
        "classification": "da-ga",
        "evidence": "provided-native",
    }


def test_live_native_identity_is_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: {
            "schemaName": "gptagent_copilotforemployeeselfservicehr"
        },
    )
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: pytest.fail("Dataverse lookup should be skipped"),
    )

    result = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )

    assert result["classification"] == "da-ga"
    assert result["evidence"] == "native-minimal-bot"


def test_positive_cea_schema_stops_with_release_pinned_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_native(*_args, **_kwargs):
        raise AgentBuilderError("not available through the native service")

    monkeypatch.setattr(reconcile, "_probe_native_agent", fail_native)
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: DATAVERSE_URL,
    )
    monkeypatch.setattr(
        reconcile,
        "_read_dataverse_agent",
        lambda *_args, **_kwargs: {
            "schemaname": "msdyn_copilotforemployeeselfserviceit"
        },
    )

    result = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        operating_system="Windows",
    )

    assert result["action"] == "stop-and-use-cea-kit"
    assert result["classification"] == "cea"
    assert result["releaseTag"] == "cea-v1.0.0-rc.1"
    assert "/cea-v1.0.0-rc.1/setup/bootstrap.ps1" in result["recoveryCommand"]
    assert "-Branch cea-v1.0.0-rc.1" in result["recoveryCommand"]
    assert (
        "-SourceBaseUrl https://raw.githubusercontent.com/"
        "microsoft/Employee-Self-Service-Agent-Developer-Kit/"
        "cea-v1.0.0-rc.1/setup"
    ) in result["recoveryCommand"]
    assert (
        "-InstallRoot (Join-Path $env:USERPROFILE 'source-cea')"
        in result["recoveryCommand"]
    )
    assert result["recoveryShell"] == "powershell"


def test_non_cea_and_unknown_evidence_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AgentBuilderError("native lookup failed")
        ),
    )
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: DATAVERSE_URL,
    )
    records = iter(
        [
            {"schemaname": "gptagent_copilotforemployeeselfservicehr"},
            {"schemaname": "contoso_unrecognized"},
        ]
    )
    monkeypatch.setattr(
        reconcile,
        "_read_dataverse_agent",
        lambda *_args, **_kwargs: next(records),
    )

    da_schema = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )
    unknown = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )

    assert da_schema == {
        "action": "continue-da-ga-setup",
        "classification": "da",
        "evidence": "dataverse-schema",
    }
    assert unknown == {
        "action": "continue-da-ga-setup",
        "classification": "unknown",
        "evidence": "dataverse-schema",
    }


def test_lookup_failures_are_not_cea_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AgentBuilderError("service unavailable")
        ),
    )
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("authentication unavailable")
        ),
    )

    result = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )

    assert result == {
        "action": "continue-da-ga-setup",
        "classification": "unknown",
        "evidence": "not-classified",
    }


def test_environment_resolution_uses_user_scoped_api_and_selected_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, tenant: str) -> None:
            observed["tenant"] = tenant

        def authenticate(self, preferred_username=None):
            observed["account"] = preferred_username
            return "token"

        def list_environments_for_user(self):
            return [
                {
                    "id": ENVIRONMENT_ID,
                    "url": f"{DATAVERSE_URL}/",
                }
            ]

    monkeypatch.setattr(reconcile, "PowerPlatformClient", FakeClient)

    result = reconcile._resolve_dataverse_url(
        ENVIRONMENT_ID,
        "maker@example.com",
    )

    assert result == DATAVERSE_URL
    assert observed == {
        "tenant": "organizations",
        "account": "maker@example.com",
    }


def test_dataverse_lookup_is_bounded_to_exact_agent_and_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_authenticate(env_url, preferred_username=None):
        observed["auth"] = (env_url, preferred_username)
        return "token"

    def fake_query_all(env_url, token, **kwargs):
        observed["query"] = (env_url, token, kwargs)
        return [
            {
                "botid": AGENT_ID,
                "name": "ESS",
                "schemaname": "msdyn_CopilotForEmployeeSelfServiceIT",
                "ismanaged": True,
            }
        ]

    monkeypatch.setattr(reconcile, "authenticate", fake_authenticate)
    monkeypatch.setattr(reconcile, "query_all", fake_query_all)

    record = reconcile._read_dataverse_agent(
        DATAVERSE_URL,
        AGENT_ID,
        "maker@example.com",
    )

    assert record is not None
    assert observed["auth"] == (DATAVERSE_URL, "maker@example.com")
    assert observed["query"] == (
        DATAVERSE_URL,
        "token",
        {
            "entity_set": "bots",
            "select": "botid,name,schemaname,ismanaged",
            "filter_expr": f"botid eq {AGENT_ID}",
        },
    )


def test_posix_recovery_is_release_pinned_and_side_by_side() -> None:
    command, shell = reconcile.build_recovery_command("Darwin")

    assert shell == "bash"
    assert 'ESS_ADK_INSTALL_ROOT="$HOME/source-cea"' in command
    assert "/cea-v1.0.0-rc.1/setup/bootstrap-mac.sh" in command
    assert "--branch cea-v1.0.0-rc.1" in command
    assert "--source-base-url" in command


def test_release_manifest_rejects_a_moving_branch(tmp_path: Path) -> None:
    manifest = tmp_path / "releases.json"
    manifest.write_text(
        json.dumps(
            {
                "products": {
                    "cea": {
                        "repository": (
                            "microsoft/Employee-Self-Service-Agent-Developer-Kit"
                        ),
                        "releaseTag": "main-ca",
                        "installRoot": "source-cea",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safe pinned release"):
        reconcile.build_recovery_command("Windows", manifest)


def test_cli_emits_bounded_json_for_native_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = reconcile.main(
        [
            "--environment-id",
            ENVIRONMENT_ID,
            "--agent-id",
            AGENT_ID,
            "--ring",
            "prod",
            "--native-da-ga",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith(reconcile.RESULT_PREFIX)
    result = json.loads(output.removeprefix(reconcile.RESULT_PREFIX))
    assert result["action"] == "continue-da-ga-setup"
    assert ENVIRONMENT_ID not in output
    assert AGENT_ID not in output


def test_positive_cea_result_still_stops_when_recovery_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: {
            "schemaName": "msdyn_copilotforemployeeselfservicehr"
        },
    )
    monkeypatch.setattr(
        reconcile,
        "build_recovery_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("manifest unavailable")
        ),
    )

    result = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )

    assert result == {
        "action": "stop-and-use-cea-kit",
        "classification": "cea",
        "evidence": "native-schema",
        "recoveryUnavailable": True,
    }
