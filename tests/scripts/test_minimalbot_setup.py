# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the Dataverse-free (TEST-ring) existing-agent registration script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class FakeEvalClient:
    """Stand-in for MinimalBotEvaluationClient — no auth, no network."""

    def __init__(self, *, environment_id, bot_id, tenant_id, components=None):
        self.environment_id = environment_id
        self.bot_id = bot_id
        self.tenant_id = tenant_id
        self.signed_in_username = "maker@contoso.com"
        self._components = components if components is not None else {
            "botComponentChanges": [
                {
                    "component": {
                        "schemaName": "cr123_myessagent",
                        "definition": {
                            "$kind": "BotComponent",
                            "displayName": "My ESS Agent",
                        },
                    }
                }
            ]
        }
        self.authenticated = False

    def authenticate(self):
        self.authenticated = True
        return "fake-token"

    def read_components(self):
        assert self.authenticated, "read_components called before authenticate"
        return self._components


def _factory(**captured):
    """Build a client_factory that records the last client it produced."""

    def factory(*, environment_id, bot_id, tenant_id):
        client = FakeEvalClient(
            environment_id=environment_id,
            bot_id=bot_id,
            tenant_id=tenant_id,
            components=captured.get("components"),
        )
        captured["client"] = client
        return client

    return factory


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_verify_and_write_config_autodetects_name_and_schema(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"
    result = minimalbot_setup.register_existing_agent(
        "214d162d-0479-e7b3-b118-3ba749943035",
        "fc27c063-49bb-4241-9546-8239e385a267",
        config_path=config_path,
        client_factory=_factory(),
    )

    written = _load(config_path)
    assert written["configVersion"] == 1
    assert written["environmentId"] == "214d162d-0479-e7b3-b118-3ba749943035"
    assert "dataverseEndpoint" not in written
    agent = written["agent"]
    assert agent["botId"] == "fc27c063-49bb-4241-9546-8239e385a267"
    assert agent["name"] == "My ESS Agent"
    assert agent["schemaName"] == "cr123_myessagent"
    assert agent["slug"] == "my-ess-agent"
    assert written["agents"] == [agent]
    assert written["activeAgent"] == "my-ess-agent"
    assert result["verified"]["componentCount"] == 1


def test_written_config_is_recognised_as_minimalbot(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"
    minimalbot_setup.register_existing_agent(
        "env-guid",
        "bot-guid",
        config_path=config_path,
        client_factory=_factory(),
    )
    assert minimalbot_setup.is_minimalbot(_load(config_path)) is True


def test_no_verify_skips_auth_and_uses_flag_values(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"

    def exploding_factory(**_kwargs):  # pragma: no cover - must never run
        raise AssertionError("client_factory must not be called when verify=False")

    result = minimalbot_setup.register_existing_agent(
        "env-guid",
        "bot-guid-12345678",
        name="Custom Name",
        schema_name="cr9_custom",
        verify=False,
        config_path=config_path,
        client_factory=exploding_factory,
    )

    agent = _load(config_path)["agent"]
    assert agent["name"] == "Custom Name"
    assert agent["schemaName"] == "cr9_custom"
    assert agent["slug"] == "custom-name"
    assert result["verified"] is None


def test_defaults_tenant_to_organizations(tmp_path):
    import minimalbot_setup

    captured: dict = {}
    config_path = tmp_path / ".local" / "config.json"
    minimalbot_setup.register_existing_agent(
        "env-guid",
        "bot-guid",
        config_path=config_path,
        client_factory=_factory_capturing(captured),
    )

    assert captured["client"].tenant_id == "organizations"
    assert _load(config_path)["tenantId"] == "organizations"


def _factory_capturing(captured):
    def factory(*, environment_id, bot_id, tenant_id):
        client = FakeEvalClient(
            environment_id=environment_id, bot_id=bot_id, tenant_id=tenant_id
        )
        captured["client"] = client
        return client

    return factory


def test_generates_name_when_bot_has_no_detectable_identity(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"

    def factory(*, environment_id, bot_id, tenant_id):
        # Components with no bot/copilot component -> nothing to auto-detect.
        return FakeEvalClient(
            environment_id=environment_id,
            bot_id=bot_id,
            tenant_id=tenant_id,
            components={"botComponentChanges": []},
        )

    minimalbot_setup.register_existing_agent(
        "env-guid",
        "abcdef1234567890",
        config_path=config_path,
        client_factory=factory,
    )

    agent = _load(config_path)["agent"]
    assert agent["name"] == "MinimalBot abcdef12"
    assert agent["slug"] == "minimalbot-abcdef12"
    assert agent["schemaName"] == "minimalbot-abcdef12"


def test_preserves_existing_unrelated_fields_and_strips_dataverse(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "dataverseEndpoint": "https://old.crm.dynamics.com",
                "connections": {"shared_x": "abc"},
                "referenceSource": "keep-me",
            }
        ),
        encoding="utf-8",
    )

    minimalbot_setup.register_existing_agent(
        "env-guid",
        "bot-guid",
        verify=False,
        name="Agent",
        config_path=config_path,
        client_factory=_factory_capturing({}),
    )

    written = _load(config_path)
    assert "dataverseEndpoint" not in written
    assert written["connections"] == {"shared_x": "abc"}
    assert written["referenceSource"] == "keep-me"


def test_creates_agent_folder_and_evaluations_subdir(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"
    result = minimalbot_setup.register_existing_agent(
        "env-guid",
        "bot-guid",
        verify=False,
        name="My ESS Agent",
        config_path=config_path,
        client_factory=_factory(),
    )

    expected = tmp_path / "workspace" / "agents" / "my-ess-agent"
    assert expected.is_dir()
    assert (expected / "evaluations").is_dir()
    assert result["agentFolder"] == str(expected.resolve())


def test_no_folder_skips_directory_creation(tmp_path):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"
    result = minimalbot_setup.register_existing_agent(
        "env-guid",
        "bot-guid",
        verify=False,
        name="My ESS Agent",
        ensure_folder=False,
        config_path=config_path,
        client_factory=_factory(),
    )

    assert not (tmp_path / "workspace").exists()
    assert result["agentFolder"] is None


def test_requires_environment_id_and_bot_id(tmp_path):
    import minimalbot_setup

    with pytest.raises(ValueError, match="environment_id"):
        minimalbot_setup.register_existing_agent(
            "", "bot", verify=False, config_path=tmp_path / "c.json"
        )
    with pytest.raises(ValueError, match="bot_id"):
        minimalbot_setup.register_existing_agent(
            "env", "", verify=False, config_path=tmp_path / "c.json"
        )


def test_verify_error_propagates(tmp_path):
    import minimalbot_setup
    from minimalbot_evaluation import MinimalBotEvaluationError

    def failing_factory(*, environment_id, bot_id, tenant_id):
        class _Bad(FakeEvalClient):
            def read_components(self):
                raise MinimalBotEvaluationError("HTTP 403")

        return _Bad(
            environment_id=environment_id, bot_id=bot_id, tenant_id=tenant_id
        )

    config_path = tmp_path / ".local" / "config.json"
    with pytest.raises(MinimalBotEvaluationError, match="403"):
        minimalbot_setup.register_existing_agent(
            "env-guid",
            "bot-guid",
            config_path=config_path,
            client_factory=failing_factory,
        )
    # nothing written on failure
    assert not config_path.exists()


def test_main_prints_summary(tmp_path, capsys):
    import minimalbot_setup

    config_path = tmp_path / ".local" / "config.json"
    rc = minimalbot_setup.main(
        [
            "--environment-id",
            "214d162d-0479-e7b3-b118-3ba749943035",
            "--bot-id",
            "fc27c063-49bb-4241-9546-8239e385a267",
            "--no-verify",
            "--name",
            "Nightly Bot",
            "--config-path",
            str(config_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "MINIMALBOT_SETUP_JSON:" in out
    payload = json.loads(out.split("MINIMALBOT_SETUP_JSON:", 1)[1].strip())
    assert payload["status"] == "registered"
    assert payload["verified"] is False
    assert payload["slug"] == "nightly-bot"
    assert _load(config_path)["agent"]["name"] == "Nightly Bot"
