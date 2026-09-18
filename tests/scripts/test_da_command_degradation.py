# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA-GA commands use native APIs or fail before retired Dataverse paths."""

from __future__ import annotations

import json

import pytest

import agentbuilder
import auth
import plant_debug
import publish
import strip_debug


def _da_config() -> dict:
    return {
        "agent": {
            "botId": "00000000-0000-4000-8000-000000000001",
        },
    }


def test_publish_routes_da_ga_to_native_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def __init__(self, host, token, **kwargs):
            calls.append(("client", (host, token, kwargs)))

        def publish_agent(self, agent_id):
            calls.append(("publish", agent_id))
            return {"validationPending": False}

    monkeypatch.setattr(publish, "is_connect_ready", lambda: True)
    monkeypatch.setattr(
        publish,
        "_load_native_setup_state",
        lambda: {
            "environment": {
                "id": "00000000-0000-4000-8000-000000000010",
                "tenant_id": "00000000-0000-4000-8000-000000000020",
                "power_platform_api_endpoint": (
                    "https://00000000000040008000000000000010."
                    "0.environment.api.test.powerplatform.com"
                ),
                "ring": "test",
                "api_version": "2024-10-01",
            },
            "agent": {
                "id": "00000000-0000-4000-8000-000000000001",
                "name": "Mock native agent",
            },
        },
    )
    monkeypatch.setattr(
        publish,
        "authenticate_agentbuilder",
        lambda tenant_id, ring, **kwargs: calls.append(
            ("auth", (tenant_id, ring, kwargs))
        ) or "native-token",
    )
    monkeypatch.setattr(publish, "AgentBuilderClient", FakeClient)
    monkeypatch.setattr(publish, "_emit_telemetry", lambda: None)

    assert publish.main(["--yes", "--account", "maker@example.com"]) == 0

    assert calls[0] == (
        "auth",
        (
            "00000000-0000-4000-8000-000000000020",
            "test",
            {
                "account_hint": "maker@example.com",
                "force_account_selection": False,
            },
        ),
    )
    assert calls[-1] == (
        "publish",
        "00000000-0000-4000-8000-000000000001",
    )
    assert "Published" in capsys.readouterr().out


def test_publish_preserves_classic_dataverse_route(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {
        "dataverseEndpoint": "https://mock.crm.dynamics.com",
        "agent": {
            "botId": "00000000-0000-4000-8000-000000000001",
            "name": "Mock classic agent",
        },
    }
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(publish, "is_connect_ready", lambda: False)
    monkeypatch.setattr(publish, "load_config", lambda: config)
    monkeypatch.setattr(
        publish,
        "authenticate",
        lambda endpoint: calls.append(("auth", endpoint)) or "classic-token",
    )
    monkeypatch.setattr(
        publish,
        "publish_bot",
        lambda endpoint, token, bot_id: calls.append(
            ("publish", (endpoint, token, bot_id))
        ),
    )
    monkeypatch.setattr(publish, "_emit_telemetry", lambda: None)

    assert publish.main(["--yes"]) == 0

    assert calls == [
        ("auth", "https://mock.crm.dynamics.com"),
        (
            "publish",
            (
                "https://mock.crm.dynamics.com",
                "classic-token",
                "00000000-0000-4000-8000-000000000001",
            ),
        ),
    ]
    assert "Authenticating to Dataverse" in capsys.readouterr().out


def test_publish_prints_server_validation_details_without_mapping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diagnostic_groups = [
        {
            "reference": {
                "dialogId": "SystemCommonOrchestrator",
                "actionId": "Condition_1",
            },
            "diagnosticList": [
                {
                    "errorCode": "IdentifierNotRecognized",
                    "errorMessage": (
                        "Name isn't valid. 'ServiceNowHRSDTable' isn't "
                        "recognized."
                    ),
                }
            ],
        }
    ]
    response = type(
        "Response",
        (),
        {
            "json": lambda self: {
                "Error": {
                    "Code": "PublishValidationFailure",
                    "Message": "Validation for the bot failed",
                    "Properties": {
                        "Diagnostics": json.dumps(diagnostic_groups),
                    },
                }
            }
        },
    )()
    error = agentbuilder.AgentBuilderHTTPError(
        "Native agent publish",
        400,
        error_code="PublishValidationFailure",
        request_id="request-123",
        response=response,
    )

    publish._print_native_error(error)

    output = capsys.readouterr().out
    assert "PublishValidationFailure" in output
    assert "Validation for the bot failed" in output
    assert "IdentifierNotRecognized" in output
    assert "'ServiceNowHRSDTable' isn't recognized." in output
    assert "SystemCommonOrchestrator / Condition_1" in output
    assert "mapping" not in output.casefold()


def test_publish_malformed_diagnostics_keeps_server_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = type(
        "Response",
        (),
        {
            "json": lambda self: {
                "Error": {
                    "Code": "PublishValidationFailure",
                    "Message": "Validation for the bot failed",
                    "Properties": {"Diagnostics": "not-json"},
                }
            }
        },
    )()
    error = agentbuilder.AgentBuilderHTTPError(
        "Native agent publish",
        400,
        response=response,
    )

    publish._print_native_error(error)

    output = capsys.readouterr().out
    assert "PublishValidationFailure" in output
    assert "Validation for the bot failed" in output
    assert "Validation details" not in output


def test_plant_debug_reports_da_ga_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(auth, "is_connect_ready", lambda: True)
    monkeypatch.setattr(auth, "load_config", _da_config)

    result = plant_debug.main(
        [
            "--topic",
            "test-topic",
            "--after",
            "action",
            "--activity",
            "DBG value",
            "--yes",
        ]
    )

    assert result == 2
    assert "not yet available" in capsys.readouterr().out


def test_strip_debug_reports_da_ga_unavailable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provenance = tmp_path / "provenance.json"
    provenance.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(strip_debug, "PROVENANCE_PATH", provenance)
    monkeypatch.setattr(strip_debug, "load_provenance", object)
    monkeypatch.setattr(auth, "is_connect_ready", lambda: True)
    monkeypatch.setattr(auth, "load_config", _da_config)

    result = strip_debug.main(["--yes"])

    assert result == 2
    assert "not yet available" in capsys.readouterr().out
