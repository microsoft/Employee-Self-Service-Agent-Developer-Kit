# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/discover.py (--list-environments)
and solutions/ess-maker-skills/scripts/list_environments.py.

These test the kit's pure-logic helpers for environment listing, filtering,
table display, and selection. They mock PPAdminClient.get_environments() at
the function level — no external API calls are made.
"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest

from tests.mocks import pp_admin as pp


def _make_environments(count: int = 3, include_no_dataverse: bool = False):
    """Build a list of BAP environment records for testing."""
    envs = []
    for i in range(count):
        envs.append(pp.environment(
            env_id=f"env-{i:03d}",
            display_name=f"Test Environment {i}",
            instance_url=f"https://org{i:03d}.crm.dynamics.com/",
        ))
    if include_no_dataverse:
        # Environment with no linked Dataverse
        envs.append({
            "name": "env-no-dv",
            "properties": {
                "displayName": "No Dataverse Env",
                "environmentType": "Sandbox",
                "linkedEnvironmentMetadata": {},
                "states": {"runtime": {"id": "Enabled"}},
            },
        })
    return envs


class TestListEnvironments:
    """Tests for list_environments.get_dataverse_environments()."""

    @patch("list_environments.PPAdminClient")
    def test_returns_only_dataverse_linked_environments(self, mock_cls):
        """Environments without instanceUrl are excluded."""
        import list_environments

        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        mock_instance.get_environments.return_value = _make_environments(
            count=2, include_no_dataverse=True
        )

        dv_envs, excluded = list_environments.get_dataverse_environments()

        assert len(dv_envs) == 2
        assert excluded == 1
        assert all(e["instanceUrl"] for e in dv_envs)

    @patch("list_environments.PPAdminClient")
    def test_strips_trailing_slash_from_instance_url(self, mock_cls):
        """instanceUrl trailing slashes are normalized."""
        import list_environments

        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        mock_instance.get_environments.return_value = [
            pp.environment(instance_url="https://org.crm.dynamics.com/")
        ]

        dv_envs, _ = list_environments.get_dataverse_environments()

        assert dv_envs[0]["instanceUrl"] == "https://org.crm.dynamics.com"

    @patch("list_environments.PPAdminClient")
    def test_exits_on_permission_error(self, mock_cls):
        """get_environments returning an error dict causes sys.exit."""
        import list_environments

        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        mock_instance.get_environments.return_value = {"_error": "insufficient_permissions"}

        with pytest.raises(SystemExit) as exc_info:
            list_environments.get_dataverse_environments()
        assert exc_info.value.code == 1

    @patch("list_environments.PPAdminClient")
    def test_exits_on_auth_failure(self, mock_cls):
        """PPAdminClient.authenticate() raising causes sys.exit."""
        import list_environments

        mock_instance = mock_cls.return_value
        mock_instance.authenticate.side_effect = RuntimeError("auth failed")

        with pytest.raises(SystemExit) as exc_info:
            list_environments.get_dataverse_environments()
        assert exc_info.value.code == 1


class TestPrintEnvironmentTable:
    """Tests for list_environments.print_environment_table()."""

    def test_prints_all_environments(self, capsys):
        """Table output includes all provided environments."""
        import list_environments

        url_a = "https://a.crm.dynamics.com"
        url_b = "https://b.crm.dynamics.com"
        envs = [
            {"displayName": "Env A", "type": "Production", "region": "US", "instanceUrl": url_a},
            {"displayName": "Env B", "type": "Sandbox", "region": "EU", "instanceUrl": url_b},
        ]

        list_environments.print_environment_table(envs)
        output = capsys.readouterr().out

        assert "Env A" in output
        assert "Env B" in output
        # Verify URLs appear in output by checking the exact value we passed in
        assert url_a in output
        assert url_b in output

    def test_shows_no_dataverse_for_empty_url(self, capsys):
        """Environments with empty instanceUrl show placeholder text."""
        import list_environments

        envs = [
            {"displayName": "Empty", "type": "Dev", "region": "", "instanceUrl": ""},
        ]

        list_environments.print_environment_table(envs)
        output = capsys.readouterr().out

        assert "(no Dataverse linked)" in output


class TestDiscoverListEnvironmentsMode:
    """Tests for discover.py --list-environments integration with list_environments."""

    @patch("list_environments.PPAdminClient")
    def test_select_outputs_json(self, mock_cls, capsys, monkeypatch):
        """--list-environments --select N outputs SELECTED_ENV_JSON."""
        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        mock_instance.get_environments.return_value = _make_environments(count=3)

        monkeypatch.setattr(
            "sys.argv",
            ["discover.py", "--list-environments", "--select", "2"],
        )

        import discover

        with pytest.raises(SystemExit) as exc_info:
            discover.main()
        assert exc_info.value.code == 0

        output = capsys.readouterr().out
        assert "SELECTED_ENV_JSON:" in output

        json_line = [l for l in output.splitlines() if "SELECTED_ENV_JSON:" in l][0]
        payload = json.loads(json_line.split("SELECTED_ENV_JSON:", 1)[1])
        assert payload["displayName"] == "Test Environment 1"
        assert payload["instanceUrl"] == "https://org001.crm.dynamics.com"

    @patch("list_environments.PPAdminClient")
    def test_select_invalid_number_exits_with_error(self, mock_cls, capsys, monkeypatch):
        """--select with out-of-range number exits with code 1."""
        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        mock_instance.get_environments.return_value = _make_environments(count=2)

        monkeypatch.setattr(
            "sys.argv",
            ["discover.py", "--list-environments", "--select", "99"],
        )

        import discover

        with pytest.raises(SystemExit) as exc_info:
            discover.main()
        assert exc_info.value.code == 1

    def test_url_required_without_list_environments(self, monkeypatch):
        """Without --list-environments, --url is required."""
        monkeypatch.setattr("sys.argv", ["discover.py"])

        import discover

        with pytest.raises(SystemExit) as exc_info:
            discover.main()
        assert exc_info.value.code == 2  # argparse error
