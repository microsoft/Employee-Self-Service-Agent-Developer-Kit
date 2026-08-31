# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for safe MCP configuration materialization."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

import mcp_config


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _defaults(*names: str) -> dict:
    return {
        "servers": {
            name: {
                "command": "python",
                "args": [f"{name}.py"],
            }
            for name in names
        }
    }


def test_materialize_defaults_is_idempotent_and_adds_new_catalog_servers(
    tmp_path: Path,
) -> None:
    defaults_path = tmp_path / mcp_config.DEFAULTS_PATH
    _write_json(defaults_path, _defaults("first"))

    created = mcp_config.materialize_defaults(tmp_path)
    first_content = (tmp_path / mcp_config.CONFIG_PATH).read_bytes()
    unchanged = mcp_config.materialize_defaults(tmp_path)
    assert (tmp_path / mcp_config.CONFIG_PATH).read_bytes() == first_content

    _write_json(defaults_path, _defaults("first", "second"))
    updated = mcp_config.materialize_defaults(tmp_path)
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert created["action"] == "created"
    assert created["addedServers"] == ["first"]
    assert unchanged["action"] == "unchanged"
    assert (tmp_path / mcp_config.CONFIG_PATH).read_bytes() != first_content
    assert updated["addedServers"] == ["second"]
    assert list(config["servers"]) == ["first", "second"]


def test_materialize_defaults_preserves_unknown_content(tmp_path: Path) -> None:
    _write_json(tmp_path / mcp_config.DEFAULTS_PATH, _defaults("bundled"))
    _write_json(
        tmp_path / mcp_config.CONFIG_PATH,
        {
            "inputs": [
                {
                    "id": "customToken",
                    "type": "promptString",
                    "password": True,
                }
            ],
            "servers": {"custom": {"type": "http", "url": "https://example.com"}},
            "customTopLevelField": {"enabled": True},
        },
    )

    mcp_config.materialize_defaults(tmp_path)
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert config["customTopLevelField"] == {"enabled": True}
    assert config["inputs"][0]["id"] == "customToken"
    assert config["servers"]["custom"]["url"] == "https://example.com"
    assert "bundled" in config["servers"]


def test_materialize_defaults_updates_untouched_managed_definition(
    tmp_path: Path,
) -> None:
    defaults_path = tmp_path / mcp_config.DEFAULTS_PATH
    _write_json(defaults_path, _defaults("bundled"))
    mcp_config.materialize_defaults(tmp_path)

    changed_defaults = _defaults("bundled")
    changed_defaults["servers"]["bundled"]["args"] = ["new.py"]
    _write_json(defaults_path, changed_defaults)

    result = mcp_config.materialize_defaults(tmp_path)
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert result["updatedServers"] == ["bundled"]
    assert config["servers"]["bundled"]["args"] == ["new.py"]


def test_materialize_defaults_preserves_local_override(tmp_path: Path) -> None:
    defaults_path = tmp_path / mcp_config.DEFAULTS_PATH
    config_path = tmp_path / mcp_config.CONFIG_PATH
    _write_json(defaults_path, _defaults("bundled"))
    mcp_config.materialize_defaults(tmp_path)

    config = json.loads(config_path.read_text())
    config["servers"]["bundled"]["args"] = ["local.py"]
    _write_json(config_path, config)
    changed_defaults = _defaults("bundled")
    changed_defaults["servers"]["bundled"]["args"] = ["new.py"]
    _write_json(defaults_path, changed_defaults)

    result = mcp_config.materialize_defaults(tmp_path)
    preserved = json.loads(config_path.read_text())

    assert result["action"] == "unchanged"
    assert result["preservedServerOverrides"] == ["bundled"]
    assert preserved["servers"]["bundled"]["args"] == ["local.py"]


def test_invalid_generated_config_fails_without_writing(tmp_path: Path) -> None:
    _write_json(tmp_path / mcp_config.DEFAULTS_PATH, _defaults("bundled"))
    config_path = tmp_path / mcp_config.CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    invalid = '{"servers": {}}\n{"servers": {}}\n'
    config_path.write_text(invalid, encoding="utf-8")

    with pytest.raises(mcp_config.McpConfigError, match="not valid JSON"):
        mcp_config.materialize_defaults(tmp_path)

    assert config_path.read_text(encoding="utf-8") == invalid


def test_duplicate_json_keys_fail_without_writing(tmp_path: Path) -> None:
    _write_json(tmp_path / mcp_config.DEFAULTS_PATH, _defaults("bundled"))
    config_path = tmp_path / mcp_config.CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    invalid = (
        '{"servers":{"custom":{"command":"first"},'
        '"custom":{"command":"second"}}}\n'
    )
    config_path.write_text(invalid, encoding="utf-8")

    with pytest.raises(mcp_config.McpConfigError, match="duplicate JSON key"):
        mcp_config.materialize_defaults(tmp_path)

    assert config_path.read_text(encoding="utf-8") == invalid


def test_validate_reports_missing_and_configured_server(tmp_path: Path) -> None:
    assert mcp_config.validate_config("bundled", tmp_path)["status"] == "missing-file"

    _write_json(
        tmp_path / mcp_config.CONFIG_PATH,
        {"servers": {"other": {"command": "python"}}},
    )
    assert (
        mcp_config.validate_config("bundled", tmp_path)["status"]
        == "missing-server"
    )

    _write_json(
        tmp_path / mcp_config.CONFIG_PATH,
        {"servers": {"bundled": {"command": "python"}}},
    )
    assert mcp_config.validate_config("bundled", tmp_path)["status"] == "configured"


def test_configure_contextual_server_preserves_other_servers_and_inputs(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "src/mcp/example/mcp.server.json",
        {
            "id": "example",
            "serverName": "Example",
            "parameters": {
                "endpoint": {
                    "argument": "--endpoint",
                    "format": "https-url",
                    "stripTrailingSlash": True,
                    "required": True,
                }
            },
            "inputs": [
                {
                    "id": "examplePassword",
                    "type": "promptString",
                    "password": True,
                }
            ],
            "server": {
                "type": "http",
                "url": "{endpoint}/mcp",
            },
        },
    )
    _write_json(
        tmp_path / mcp_config.CONFIG_PATH,
        {
            "inputs": [{"id": "custom", "type": "promptString"}],
            "servers": {"custom": {"command": "custom"}},
        },
    )

    result = mcp_config.configure_server(
        "example",
        ["--endpoint", "https://example.com/"],
        tmp_path,
    )
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert result == {
        "action": "updated",
        "path": ".vscode/mcp.json",
        "server": "Example",
    }
    assert config["servers"]["custom"] == {"command": "custom"}
    assert config["servers"]["Example"]["url"] == "https://example.com/mcp"
    assert [item["id"] for item in config["inputs"]] == [
        "custom",
        "examplePassword",
    ]


def test_shipped_contextual_descriptors_render_complete_servers(
    tmp_path: Path,
) -> None:
    for name in ("dataverse", "servicenow", "agentconfig"):
        source = SOLUTION_ROOT / "src" / "mcp" / name / "mcp.server.json"
        destination = tmp_path / "src" / "mcp" / name / "mcp.server.json"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)

    mcp_config.configure_server(
        "dataverse",
        ["--environment-url", "https://org.example.com/"],
        tmp_path,
    )
    mcp_config.configure_server(
        "servicenow",
        ["--instance-url", "https://example.service-now.com/"],
        tmp_path,
    )
    mcp_config.configure_server("landing-page", [], tmp_path)
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert config["servers"]["Dataverse"] == {
        "type": "http",
        "url": "https://org.example.com/api/mcp",
    }
    assert config["servers"]["ServiceNow"]["env"] == {
        "SERVICENOW_INSTANCE_URL": "https://example.service-now.com",
        "SERVICENOW_USERNAME": "${input:servicenowUsername}",
        "SERVICENOW_PASSWORD": "${input:servicenowPassword}",
    }
    assert [item["id"] for item in config["inputs"]] == [
        "servicenowUsername",
        "servicenowPassword",
    ]
    assert config["servers"]["ServiceNow"]["command"] == str(
        Path(sys.executable).resolve()
    )
    assert config["servers"]["ess-landing-page-config"] == {
        "command": str(Path(sys.executable).resolve()),
        "args": ["server.py"],
        "cwd": "${workspaceFolder}/src/mcp/agentconfig",
    }


def test_configure_applies_env_overrides_and_survives_materialize_defaults(
    tmp_path: Path,
) -> None:
    for relative in (mcp_config.DEFAULTS_PATH, Path("src/mcp/agentconfig/mcp.server.json")):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOLUTION_ROOT / relative, destination)

    mcp_config.materialize_defaults(tmp_path)
    configured = mcp_config.configure_server(
        "landing-page",
        [
            "--env",
            "VORPAL_WIDGET_ORIGIN=https://widgets.example.com",
            "--env",
            "AGENTCONFIG_BASE_URL=https://api.example.com/v1.1",
        ],
        tmp_path,
    )
    rematerialized = mcp_config.materialize_defaults(tmp_path)
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert configured["action"] == "updated"
    assert config["servers"]["ess-landing-page-config"]["env"] == {
        "VORPAL_WIDGET_ORIGIN": "https://widgets.example.com",
        "AGENTCONFIG_BASE_URL": "https://api.example.com/v1.1",
    }
    assert rematerialized["preservedServerOverrides"] == ["ess-landing-page-config"]


def test_configure_merges_env_overrides_into_descriptor_env(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "src/mcp/example/mcp.server.json",
        {
            "id": "example",
            "serverName": "Example",
            "parameters": {
                "endpoint": {
                    "argument": "--endpoint",
                    "format": "https-url",
                    "required": True,
                }
            },
            "server": {
                "command": "python",
                "env": {"EXAMPLE_ENDPOINT": "{endpoint}", "EXAMPLE_MODE": "default"},
            },
        },
    )

    mcp_config.configure_server(
        "example",
        ["--endpoint", "https://example.com", "--env", "EXAMPLE_MODE=override"],
        tmp_path,
    )
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert config["servers"]["Example"]["env"] == {
        "EXAMPLE_ENDPOINT": "https://example.com",
        "EXAMPLE_MODE": "override",
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("NOT_A_PAIR", "expects NAME=VALUE"),
        ("2INVALID=value", "name must match"),
        ("HAS SPACE=value", "name must match"),
    ],
)
def test_configure_rejects_malformed_env_overrides(
    tmp_path: Path,
    value: str,
    message: str,
) -> None:
    _write_json(
        tmp_path / "src/mcp/example/mcp.server.json",
        {"id": "example", "serverName": "Example", "server": {"command": "python"}},
    )

    with pytest.raises(mcp_config.McpConfigError, match=message):
        mcp_config.configure_server("example", ["--env", value], tmp_path)

    assert not (tmp_path / mcp_config.CONFIG_PATH).exists()


def test_configure_rejects_repeated_env_name(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "src/mcp/example/mcp.server.json",
        {"id": "example", "serverName": "Example", "server": {"command": "python"}},
    )

    with pytest.raises(mcp_config.McpConfigError, match="was supplied twice"):
        mcp_config.configure_server(
            "example",
            ["--env", "NAME=first", "--env", "NAME=second"],
            tmp_path,
        )


def test_shipped_defaults_materialize_the_active_python_interpreter(
    tmp_path: Path,
) -> None:
    defaults_source = SOLUTION_ROOT / mcp_config.DEFAULTS_PATH
    defaults_destination = tmp_path / mcp_config.DEFAULTS_PATH
    defaults_destination.parent.mkdir(parents=True)
    shutil.copyfile(defaults_source, defaults_destination)

    mcp_config.materialize_defaults(tmp_path)
    config = json.loads((tmp_path / mcp_config.CONFIG_PATH).read_text())

    assert config["servers"]["ess-landing-page-config"]["command"] == str(
        Path(sys.executable).resolve()
    )
