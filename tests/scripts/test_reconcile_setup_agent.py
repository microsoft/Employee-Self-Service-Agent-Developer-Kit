# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path

import pytest

import reconcile_setup_agent as reconcile
from agentbuilder import AgentBuilderError, AgentBuilderHTTPError, RING_CONFIG
from http_errors import APIError


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
DATAVERSE_URL = "https://example.crm.dynamics.com"


def _environment_host(ring: str = "prod") -> str:
    compact = ENVIRONMENT_ID.replace("-", "")
    config = RING_CONFIG[ring]
    split = int(config["primary_split"])
    return (
        f"https://{compact[:split]}.{compact[split:]}."
        f"{config['host_suffix']}"
    )


@pytest.mark.parametrize(
    ("schema_name", "expected"),
    [
        (
            "msdyn_copilotforemployeeselfservice",
            "solution-backed-ess",
        ),
        (
            "msdyn_copilotforemployeeselfservicecore",
            "solution-backed-ess",
        ),
        (
            "msdyn_copilotforemployeeselfservicedahr",
            "solution-backed-ess",
        ),
        (
            "msdyn_copilotforemployeeselfservicecustomsuffix",
            "solution-backed-ess",
        ),
        (
            "gptagent_copilotforemployeeselfservice",
            "da-ga",
        ),
        (
            "gptagent_copilotforemployeeselfservicehr",
            "da-ga",
        ),
        (
            "gptagent_copilotforemployeeselfservicecustomsuffix",
            "da-ga",
        ),
        ("gptagent_employee_self_service", "unknown"),
        (
            "MSDYN_COPILOTFOREMPLOYEESELFSERVICEDAHR",
            "solution-backed-ess",
        ),
        (
            "GPTAGENT_COPILOTFOREMPLOYEESELFSERVICEIT",
            "da-ga",
        ),
        (None, "unknown"),
    ],
)
def test_classifies_supported_schema_prefixes(
    schema_name: str | None,
    expected: str,
) -> None:
    assert reconcile.classify_schema_name(schema_name) == expected


def test_known_native_identity_preserves_product_evidence() -> None:
    result = reconcile.known_native_identity(
        "gptagent_copilotforemployeeselfservicehr"
    )

    assert result == {
        "backend": "native",
        "outcome": "found",
        "evidence": "provided-native",
        "productFamily": "da-ga",
        "identity": {
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
    }


def test_native_probe_returns_identity_without_dataverse_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: {
            "fullBotName": "Employee Self-Service HR",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
            "managedProperties": {"isManaged": True},
        },
    )
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: pytest.fail(
            "Each probe must remain independent."
        ),
    )

    result = reconcile.reconcile_selected_agent(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        probe="native",
    )

    assert result == {
        "backend": "native",
        "outcome": "found",
        "evidence": "minimalbot-direct",
        "productFamily": "da-ga",
        "identity": {
            "displayName": "Employee Self-Service HR",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
            "isManaged": True,
        },
    }


@pytest.mark.parametrize(
    "schema_name",
    [
        "gptagent_copilotforemployeeselfservicehr",
        "gptagent_copilotforemployeeselfserviceit",
    ],
)
def test_native_probe_completes_missing_schema_from_dev_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    schema_name: str,
) -> None:
    observed: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            observed.append(("agent", agent_id))
            return {
                "botId": agent_id,
                "fullBotName": "Employee Self-Service",
                "realm": "Dev",
                "managedProperties": {"isManaged": True},
            }

        def get_dev_configuration(self, agent_id: str) -> dict:
            observed.append(("config", agent_id))
            return {
                "cdsBotId": agent_id,
                "realm": "Dev",
                "schemaName": schema_name,
            }

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert observed == [("agent", AGENT_ID), ("config", AGENT_ID)]
    assert result["outcome"] == "found"
    assert result["productFamily"] == "da-ga"
    assert result["identity"]["schemaName"] == schema_name
    assert result["identity"]["displayName"] == "Employee Self-Service"


def test_native_direct_schema_skips_configuration_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            return {
                "botId": agent_id,
                "fullBotName": "Employee Self-Service (HR)",
                "realm": "Dev",
                "schemaName": "gptagent_copilotforemployeeselfservicehr",
            }

        def get_dev_configuration(self, _agent_id: str) -> dict:
            pytest.fail("Configuration lookup is unnecessary with direct schema.")

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "found"
    assert result["productFamily"] == "da-ga"


@pytest.mark.parametrize("config_result", [{}, {"schemaName": ""}])
def test_native_probe_missing_configuration_schema_is_uncertain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    config_result: dict,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            return {
                "botId": agent_id,
                "fullBotName": "Employee Self-Service (HR)",
                "realm": "Dev",
            }

        def get_dev_configuration(self, _agent_id: str) -> dict:
            return {
                "cdsBotId": AGENT_ID,
                "realm": "Dev",
                **config_result,
            }

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert "productFamily" not in result
    assert "identity" not in result


def test_native_probe_configuration_failure_is_uncertain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            return {
                "botId": agent_id,
                "fullBotName": "Employee Self-Service (HR)",
                "realm": "Dev",
            }

        def get_dev_configuration(self, _agent_id: str) -> dict:
            raise AgentBuilderError("Dev configuration unavailable")

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert result["error"]["causes"][0]["type"] == "NativeIdentityIncomplete"
    assert result["error"]["causes"][1]["type"] == "AgentBuilderError"


@pytest.mark.parametrize(
    "agent",
    [
        {
            "botId": "00000000-0000-4000-8000-000000009999",
            "realm": "Dev",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
        {
            "botId": AGENT_ID,
            "realm": "Prod",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
        {
            "realm": "Dev",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
    ],
)
def test_native_direct_schema_requires_exact_dev_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent: dict,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, _agent_id: str) -> dict:
            return agent

        def get_dev_configuration(self, _agent_id: str) -> dict:
            pytest.fail("Direct schema path must not call Dev configuration.")

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert "productFamily" not in result


@pytest.mark.parametrize("schema_name", [{"bad": "shape"}, ["bad"], 42])
def test_native_direct_schema_rejects_non_string_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    schema_name: object,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            return {
                "botId": agent_id,
                "realm": "Dev",
                "schemaName": schema_name,
            }

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert "invalid schema-name shape" in result["error"]["causes"][0]["message"]


@pytest.mark.parametrize(
    "configuration",
    [
        {
            "cdsBotId": "00000000-0000-4000-8000-000000009999",
            "realm": "Dev",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
        {
            "cdsBotId": AGENT_ID,
            "realm": "Prod",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
        {
            "realm": "Dev",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
        {
            "cdsBotId": "not-a-guid",
            "realm": "Dev",
            "schemaName": "gptagent_copilotforemployeeselfservicehr",
        },
    ],
)
def test_native_configuration_schema_requires_exact_dev_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configuration: dict,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            return {
                "botId": agent_id,
                "fullBotName": "Employee Self-Service (HR)",
                "realm": "Dev",
            }

        def get_dev_configuration(self, _agent_id: str) -> dict:
            return configuration

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert "productFamily" not in result


@pytest.mark.parametrize("schema_name", [{"bad": "shape"}, ["bad"], 42])
def test_native_configuration_rejects_non_string_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    schema_name: object,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_agent(self, agent_id: str) -> dict:
            return {
                "botId": agent_id,
                "realm": "Dev",
                "fullBotName": "Employee Self-Service",
            }

        def get_dev_configuration(self, agent_id: str) -> dict:
            return {
                "cdsBotId": agent_id,
                "realm": "Dev",
                "schemaName": schema_name,
            }

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(reconcile, "AgentBuilderClient", FakeClient)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=_environment_host(),
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert "invalid schema-name shape" in result["error"]["causes"][0]["message"]


def test_native_probe_rejects_host_for_different_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    other_environment = "00000000-0000-4000-8000-000000009999"
    compact = other_environment.replace("-", "")
    config = RING_CONFIG["prod"]
    split = int(config["primary_split"])
    wrong_host = (
        f"https://{compact[:split]}.{compact[split:]}."
        f"{config['host_suffix']}"
    )

    monkeypatch.setattr(
        reconcile,
        "authenticate_flightcheck",
        lambda *_args, **_kwargs: ("token", "tenant"),
    )
    monkeypatch.setattr(
        reconcile,
        "AgentBuilderClient",
        lambda *_args, **_kwargs: pytest.fail(
            "Mismatched environment host must be rejected before probing."
        ),
    )

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
        kit_root=tmp_path,
        host=wrong_host,
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "identity-completion"
    assert "does not match" in result["error"]["causes"][0]["message"]


@pytest.mark.parametrize(
    ("status_code", "outcome"),
    [
        (401, "authentication-required"),
        (403, "access-denied"),
        (404, "not-found"),
        (500, "uncertain"),
    ],
)
def test_native_probe_preserves_http_failure_class(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    outcome: str,
) -> None:
    def fail_native(*_args, **_kwargs):
        raise AgentBuilderHTTPError(
            "Direct agent lookup",
            status_code,
            error_code="ObjectNotFound" if status_code == 404 else "Failure",
            request_id="request-123",
        )

    monkeypatch.setattr(reconcile, "_probe_native_agent", fail_native)

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )

    assert result["backend"] == "native"
    assert result["outcome"] == outcome
    assert result["stage"] == "agent-lookup"
    assert result["error"]["statusCode"] == status_code
    assert result["error"]["errorCode"]
    assert result["error"]["requestId"] == "request-123"
    assert result["error"]["causes"][0]["type"] == "AgentBuilderHTTPError"


def test_native_transport_failure_is_uncertain_and_keeps_cause_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        raise OSError("socket closed")
    except OSError as cause:
        failure = AgentBuilderError("native lookup unavailable")
        failure.__cause__ = cause

    monkeypatch.setattr(
        reconcile,
        "_probe_native_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    result = reconcile.probe_native_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        ring="prod",
    )

    assert result["outcome"] == "uncertain"
    assert [item["type"] for item in result["error"]["causes"]] == [
        "AgentBuilderError",
        "OSError",
    ]


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


@pytest.mark.parametrize(
    ("status_code", "outcome"),
    [(401, "authentication-required"), (403, "access-denied")],
)
def test_environment_resolution_preserves_permission_failure(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    outcome: str,
) -> None:
    class FakeClient:
        def __init__(self, _tenant: str) -> None:
            pass

        def authenticate(self, preferred_username=None):
            return "token"

        def list_environments_for_user(self):
            return {
                "_error": "insufficient_permissions",
                "_status": status_code,
            }

    monkeypatch.setattr(reconcile, "PowerPlatformClient", FakeClient)

    result = reconcile.probe_dataverse_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert result["outcome"] == outcome
    assert result["stage"] == "environment-resolution"
    assert result["error"]["statusCode"] == status_code


def test_missing_dataverse_url_is_uncertain_not_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_resolve_dataverse_url",
        lambda *_args, **_kwargs: None,
    )

    result = reconcile.probe_dataverse_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert result["outcome"] == "uncertain"
    assert result["stage"] == "environment-resolution"
    assert (
        result["error"]["causes"][0]["type"]
        == "EnvironmentUrlNotResolved"
    )


def test_dataverse_lookup_is_exact_and_preserves_selected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_authenticate(env_url, preferred_username=None):
        observed["auth"] = (env_url, preferred_username)
        return "token"

    def fake_dataverse_get(env_url, token, path, params):
        observed["query"] = (env_url, token, path, params)
        return {
            "botid": AGENT_ID,
            "name": "Employee Self-Service IT",
            "schemaname": "msdyn_CopilotForEmployeeSelfServiceDAIT",
            "ismanaged": True,
        }

    monkeypatch.setattr(reconcile, "authenticate", fake_authenticate)
    monkeypatch.setattr(reconcile, "dataverse_get", fake_dataverse_get)

    result = reconcile.probe_dataverse_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        account="maker@example.com",
        dataverse_url=DATAVERSE_URL,
    )

    assert observed["auth"] == (DATAVERSE_URL, "maker@example.com")
    assert observed["query"] == (
        DATAVERSE_URL,
        "token",
        f"bots({AGENT_ID})",
        {"$select": "botid,name,schemaname,ismanaged"},
    )
    assert result == {
        "backend": "dataverse",
        "outcome": "found",
        "evidence": "dataverse-direct",
        "productFamily": "solution-backed-ess",
        "identity": {
            "displayName": "Employee Self-Service IT",
            "schemaName": "msdyn_CopilotForEmployeeSelfServiceDAIT",
            "isManaged": True,
        },
    }


@pytest.mark.parametrize(
    ("status_code", "outcome"),
    [
        (401, "authentication-required"),
        (403, "access-denied"),
        (404, "not-found"),
        (503, "uncertain"),
    ],
)
def test_dataverse_probe_preserves_http_failure_class(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    outcome: str,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "_read_dataverse_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            APIError(
                status_code=status_code,
                message="Dataverse lookup failed",
                tip="",
            )
        ),
    )

    result = reconcile.probe_dataverse_identity(
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        dataverse_url=DATAVERSE_URL,
    )

    assert result["backend"] == "dataverse"
    assert result["outcome"] == outcome
    assert result["error"]["statusCode"] == status_code


def test_compatible_kit_result_is_release_pinned_and_side_by_side() -> None:
    windows = reconcile.compatible_kit_result("Windows")
    posix = reconcile.compatible_kit_result("Darwin")

    assert windows["outcome"] == "available"
    assert windows["releaseTag"] == "cea-v1.0.0-rc.1"
    assert "/cea-v1.0.0-rc.1/setup/bootstrap.ps1" in windows[
        "recoveryCommand"
    ]
    assert "-Branch cea-v1.0.0-rc.1" in windows["recoveryCommand"]
    assert (
        "-InstallRoot (Join-Path $env:USERPROFILE 'source-cea')"
        in windows["recoveryCommand"]
    )
    assert posix["recoveryShell"] == "bash"
    assert 'ESS_ADK_INSTALL_ROOT="$HOME/source-cea"' in posix[
        "recoveryCommand"
    ]


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


def test_cli_emits_one_bounded_known_native_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = reconcile.main(
        [
            "--known-native-schema",
            "gptagent_copilotforemployeeselfservicehr",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith(reconcile.RESULT_PREFIX)
    result = json.loads(output.removeprefix(reconcile.RESULT_PREFIX))
    assert result["backend"] == "native"
    assert result["outcome"] == "found"
    assert result["productFamily"] == "da-ga"


def test_cli_rejects_probe_without_exact_identity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = reconcile.main(["--probe", "native", "--ring", "prod"])

    assert exit_code == 2
    assert "Environment ID and agent ID are required" in capsys.readouterr().out


def test_compatible_kit_failure_is_not_success_shaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconcile,
        "build_recovery_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("manifest unavailable")
        ),
    )

    result = reconcile.compatible_kit_result("Windows")

    assert result["outcome"] == "unavailable"
    assert "recoveryCommand" not in result
    assert result["error"]["causes"][0]["type"] == "ValueError"
