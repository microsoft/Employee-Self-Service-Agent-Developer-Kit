# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Setup materialization guards for the Org Announcements MCP server."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
SOLUTION = REPO_ROOT / "solutions" / "ess-maker-skills"
MCP_DEFAULTS_PATH = SOLUTION / ".vscode" / "mcp.defaults.json"
SERVER_NAME = "ess-org-announcements"

sys.path.insert(0, str(SOLUTION / "scripts"))

import mcp_config  # noqa: E402


def test_defaults_register_the_org_announcements_server() -> None:
    config = json.loads(MCP_DEFAULTS_PATH.read_text(encoding="utf-8"))

    assert SERVER_NAME in config["servers"]
    server = config["servers"][SERVER_NAME]
    assert server["command"] == "{pythonExecutable}"
    assert server["args"] == ["server.py"]
    assert (
        server["cwd"]
        == "${workspaceFolder}/src/mcp/agentconfig_org_announcements"
    )
    # Endpoints and origins fall back inside the server so no environment-
    # specific value is committed.
    assert "env" not in server


def test_defaults_carry_no_tenant_or_environment_specific_values() -> None:
    serialized = MCP_DEFAULTS_PATH.read_text(encoding="utf-8").lower()

    assert "localhost" not in serialized
    assert "tls_insecure" not in serialized
    assert "vorpal_widget_origin" not in serialized
    assert "titleid" not in serialized
    assert "substrate.office.com" not in serialized


def test_registering_announcements_keeps_the_existing_default_servers() -> None:
    config = json.loads(MCP_DEFAULTS_PATH.read_text(encoding="utf-8"))

    assert "ess-landing-page-config" in config["servers"]
    assert "ess-planner" not in config["servers"]


def _materialize(tmp_path: Path) -> dict:
    (tmp_path / ".vscode").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vscode" / "mcp.defaults.json").write_text(
        MCP_DEFAULTS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    mcp_config.materialize_defaults(tmp_path)
    return json.loads(
        (tmp_path / ".vscode" / "mcp.json").read_text(encoding="utf-8")
    )


def test_materialization_renders_the_active_python_executable(tmp_path) -> None:
    config = _materialize(tmp_path)

    command = config["servers"][SERVER_NAME]["command"]
    assert command == str(Path(sys.executable).absolute())
    assert "{pythonExecutable}" not in json.dumps(config)


def test_materialization_preserves_a_user_managed_server(tmp_path) -> None:
    (tmp_path / ".vscode").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vscode" / "mcp.defaults.json").write_text(
        MCP_DEFAULTS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".vscode" / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "my-own-server": {"command": "node", "args": ["mine.js"]}
                }
            }
        ),
        encoding="utf-8",
    )

    mcp_config.materialize_defaults(tmp_path)
    config = json.loads(
        (tmp_path / ".vscode" / "mcp.json").read_text(encoding="utf-8")
    )

    assert config["servers"]["my-own-server"] == {
        "command": "node",
        "args": ["mine.js"],
    }
    assert SERVER_NAME in config["servers"]


def test_materialization_preserves_a_customized_widget_origin(tmp_path) -> None:
    """A maker-set VORPAL_WIDGET_ORIGIN survives re-materialization."""
    (tmp_path / ".vscode").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vscode" / "mcp.defaults.json").write_text(
        MCP_DEFAULTS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    mcp_config.materialize_defaults(tmp_path)

    config_path = tmp_path / ".vscode" / "mcp.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["servers"][SERVER_NAME]["env"] = {
        "VORPAL_WIDGET_ORIGIN": "https://localhost:4200"
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    mcp_config.materialize_defaults(tmp_path)
    updated = json.loads(config_path.read_text(encoding="utf-8"))

    assert updated["servers"][SERVER_NAME]["env"] == {
        "VORPAL_WIDGET_ORIGIN": "https://localhost:4200"
    }


def test_validate_reports_the_server_as_configured(tmp_path) -> None:
    _materialize(tmp_path)

    status = mcp_config.validate_config(SERVER_NAME, tmp_path)

    assert status["status"] == "configured"
    assert status["server"] == SERVER_NAME


def test_validate_reports_a_missing_server_before_materialization(
    tmp_path,
) -> None:
    status = mcp_config.validate_config(SERVER_NAME, tmp_path)

    assert status["status"] == "missing-file"


def test_shared_token_caches_are_ignored_by_git() -> None:
    """The two shared delegated caches must be ignored by git *in practice*.

    Asserted with ``git check-ignore`` against the real paths rather than by
    grepping ``.gitignore`` for a substring: a substring match proves a pattern
    exists somewhere, not that it actually covers the file, and it would keep
    passing if a later negation rule (``!``) or a different precedence order
    silently un-ignored the cache.
    """
    caches = [
        SOLUTION / ".local" / ".token_cache.bin",
        SOLUTION
        / "src"
        / "mcp"
        / "agentconfig_core"
        / ".local"
        / "msal_token_cache.bin",
    ]

    for cache in caches:
        relative = cache.relative_to(REPO_ROOT)
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", "check-ignore", "-q", "--no-index", str(relative)],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{relative} is NOT ignored by git"


def test_the_graph_cache_the_server_uses_is_the_ignored_shared_cache() -> None:
    """Bind the ignore guarantee to the path the code actually writes.

    Checking a hard-coded literal would keep passing if the module started
    writing somewhere else, which is exactly the regression that produced a
    third, unignored cache.
    """
    sys.path.insert(0, str(SOLUTION / "src" / "mcp" / "agentconfig_org_announcements"))
    import graph_directory_client  # noqa: PLC0415 — imported for its constant

    cache = Path(graph_directory_client.GRAPH_TOKEN_CACHE_PATH)

    assert cache == SOLUTION / ".local" / ".token_cache.bin"
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [
            "git",
            "check-ignore",
            "-q",
            "--no-index",
            str(cache.relative_to(REPO_ROOT)),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0


def test_the_agentconfig_cache_the_core_uses_is_the_ignored_shared_cache() -> None:
    sys.path.insert(0, str(SOLUTION / "src" / "mcp" / "agentconfig_core"))
    import base_client  # noqa: PLC0415 — imported for its constant

    cache = Path(base_client._TOKEN_CACHE_PATH)

    assert (
        cache
        == SOLUTION
        / "src"
        / "mcp"
        / "agentconfig_core"
        / ".local"
        / "msal_token_cache.bin"
    )
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [
            "git",
            "check-ignore",
            "-q",
            "--no-index",
            str(cache.relative_to(REPO_ROOT)),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0


def test_the_announcements_server_introduces_no_third_token_cache() -> None:
    """Exactly two shared cache locations, no per-server private cache.

    A third cache is not a cosmetic duplication: it is a second interactive
    sign-in for a maker who already authenticated through /setup.
    """
    sys.path.insert(0, str(SOLUTION / "src" / "mcp" / "agentconfig_org_announcements"))
    import base_client  # noqa: PLC0415 — imported for its constant
    import graph_directory_client  # noqa: PLC0415 — imported for its constant

    locations = {
        Path(graph_directory_client.GRAPH_TOKEN_CACHE_PATH),
        Path(base_client._TOKEN_CACHE_PATH),
    }

    assert locations == {
        SOLUTION / ".local" / ".token_cache.bin",
        SOLUTION
        / "src"
        / "mcp"
        / "agentconfig_core"
        / ".local"
        / "msal_token_cache.bin",
    }
    announcements_local = (
        SOLUTION / "src" / "mcp" / "agentconfig_org_announcements" / ".local"
    )
    assert not any(
        announcements_local in location.parents for location in locations
    )
