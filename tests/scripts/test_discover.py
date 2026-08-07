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

        mock_instance.authenticate.assert_called_once_with(include_flow=False)
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

    def test_finds_environment_by_url_hostname(self):
        import list_environments

        environments = [
            {
                "id": "env-001",
                "displayName": "Target",
                "instanceUrl": "https://org.crm.dynamics.com",
            },
        ]

        selected = list_environments.find_environment_by_url(
            environments,
            "https://ORG.crm.dynamics.com/",
        )

        assert selected == environments[0]

    def test_resolve_environment_rejects_invalid_url_cleanly(
        self,
        capsys,
    ):
        import list_environments

        with pytest.raises(SystemExit) as exc_info:
            list_environments.resolve_environment_for_user(
                "http://insecure.example"
            )

        assert exc_info.value.code == 1
        assert "ERROR: Power Platform authentication failed" in (
            capsys.readouterr().out
        )

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


class TestParseRawEnvironments:
    """Tests for list_environments.parse_raw_environments().

    Regression coverage for the env-type column that previously always
    showed ``Unknown``: the real BAP Admin API returns the environment
    type under ``environmentSku`` (e.g. Production, Sandbox, Developer),
    not ``environmentType``. parse_raw_environments now reads
    ``environmentSku`` first and falls back to ``environmentType`` for
    forward-compat.
    """

    def test_reads_environment_sku(self):
        """The current BAP shape (environmentSku set) populates env type."""
        import list_environments

        envs = [pp.environment(display_name="Prod-Like")]
        # Confirm the test fixture matches the real API shape we depend on.
        assert envs[0]["properties"]["environmentSku"] == "Production"

        parsed = list_environments.parse_raw_environments(envs)
        assert parsed[0]["type"] == "Production"

    def test_falls_back_to_environment_type_when_sku_missing(self):
        """Forward-compat: if the API ever drops Sku, the legacy field wins."""
        import list_environments

        envs = [{
            "name": "env-legacy",
            "properties": {
                "displayName": "Legacy",
                # No environmentSku key at all
                "environmentType": "Sandbox",
                "linkedEnvironmentMetadata": {
                    "instanceUrl": "https://legacy.crm.dynamics.com/",
                    "geo": "US",
                },
                "states": {"runtime": {"id": "Enabled"}},
            },
        }]

        parsed = list_environments.parse_raw_environments(envs)
        assert parsed[0]["type"] == "Sandbox"

    def test_returns_unknown_when_both_fields_missing(self):
        """Defensive default when the API returns neither field."""
        import list_environments

        envs = [{
            "name": "env-bare",
            "properties": {
                "displayName": "Bare",
                "linkedEnvironmentMetadata": {
                    "instanceUrl": "https://bare.crm.dynamics.com/",
                },
                "states": {"runtime": {"id": "Enabled"}},
            },
        }]

        parsed = list_environments.parse_raw_environments(envs)
        assert parsed[0]["type"] == "Unknown"

    def test_environment_sku_wins_over_environment_type(self):
        """When both fields are present, prefer the current API field."""
        import list_environments

        envs = [{
            "name": "env-both",
            "properties": {
                "displayName": "Both",
                "environmentSku": "Developer",
                "environmentType": "Sandbox",  # legacy / stale
                "linkedEnvironmentMetadata": {
                    "instanceUrl": "https://both.crm.dynamics.com/",
                },
                "states": {"runtime": {"id": "Enabled"}},
            },
        }]

        parsed = list_environments.parse_raw_environments(envs)
        assert parsed[0]["type"] == "Developer"


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
    def test_list_outputs_reusable_environment_json(
        self, mock_cls, capsys, monkeypatch
    ):
        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        mock_instance.get_environments.return_value = _make_environments(count=2)
        monkeypatch.setattr(
            "sys.argv",
            ["discover.py", "--list-environments"],
        )

        import discover

        discover.main()

        output = capsys.readouterr().out
        json_line = [
            line
            for line in output.splitlines()
            if line.startswith("ENVIRONMENT_LIST_JSON:")
        ][0]
        payload = json.loads(json_line.split("ENVIRONMENT_LIST_JSON:", 1)[1])
        assert len(payload) == 2
        assert payload[0]["displayName"] == "Test Environment 0"

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

        json_line = [line for line in output.splitlines() if "SELECTED_ENV_JSON:" in line][0]
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

    @patch("list_environments.PowerPlatformClient")
    def test_resolve_environment_url_outputs_selected_json(
        self,
        mock_cls,
        capsys,
        monkeypatch,
    ):
        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        monkeypatch.setattr(
            "list_environments.discover_tenant",
            lambda _url: "tenant-id",
        )
        mock_instance.list_environments_for_user.return_value = [
            {
                "id": "env-000",
                "displayName": "Test Environment 0",
                "type": "Sandbox",
                "state": "Ready",
                "url": "https://org000.crm.dynamics.com/",
            },
            {
                "id": "env-001",
                "displayName": "Test Environment 1",
                "type": "Sandbox",
                "state": "Ready",
                "url": "https://org001.crm.dynamics.com/",
            },
        ]
        monkeypatch.setattr(
            "sys.argv",
            [
                "discover.py",
                "--resolve-environment-url",
                "https://org001.crm.dynamics.com/",
            ],
        )

        import discover

        discover.main()

        output = capsys.readouterr().out
        assert "Environment Name" not in output
        json_line = [
            line
            for line in output.splitlines()
            if line.startswith("SELECTED_ENV_JSON:")
        ][0]
        payload = json.loads(json_line.split("SELECTED_ENV_JSON:", 1)[1])
        assert payload["id"] == "env-001"
        assert payload["displayName"] == "Test Environment 1"

    @patch("list_environments.PowerPlatformClient")
    def test_resolve_environment_url_rejects_unknown_url(
        self,
        mock_cls,
        capsys,
        monkeypatch,
    ):
        mock_instance = mock_cls.return_value
        mock_instance.authenticate.return_value = "token"
        monkeypatch.setattr(
            "list_environments.discover_tenant",
            lambda _url: "tenant-id",
        )
        mock_instance.list_environments_for_user.return_value = [
            {
                "id": "env-000",
                "displayName": "Test Environment 0",
                "type": "Sandbox",
                "state": "Ready",
                "domainName": "org000.crm.dynamics.com",
            },
        ]
        monkeypatch.setattr(
            "sys.argv",
            [
                "discover.py",
                "--resolve-environment-url",
                "https://unknown.crm.dynamics.com",
            ],
        )

        import discover

        with pytest.raises(SystemExit) as exc_info:
            discover.main()

        assert exc_info.value.code == 1
        assert "did not match" in capsys.readouterr().out


class TestEssAgentInventory:
    def test_inventory_only_succeeds_when_no_agents_are_installed(
        self,
        capsys,
        monkeypatch,
    ):
        import discover

        monkeypatch.setattr(discover, "authenticate", lambda _url: "token")
        monkeypatch.setattr(
            discover,
            "discover_agents",
            lambda _url, _token: [],
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "discover.py",
                "--url",
                "https://org.crm.dynamics.com",
                "--inventory-only",
            ],
        )

        discover.main()

        output = capsys.readouterr().out
        json_line = [
            line
            for line in output.splitlines()
            if line.startswith("ESS_AGENT_DISCOVERY_JSON:")
        ][0]
        payload = json.loads(
            json_line.split("ESS_AGENT_DISCOVERY_JSON:", 1)[1]
        )
        assert payload["agents"] == []
        assert len(payload["availableInstallations"]) == 6
        assert "No supported ESS agents found" not in output

    def test_excludes_installed_product_and_unrelated_bots(self):
        import discover
        import install_ess_agent

        inventory = discover.build_ess_agent_inventory(
            [
                {
                    "botid": "ess",
                    "name": "ESS HR",
                    "schemaname": "msdyn_CopilotForEmployeeSelfServiceDAHR",
                    "ismanaged": True,
                },
                {
                    "botid": "other",
                    "name": "Unrelated",
                    "schemaname": "new_unrelated",
                    "ismanaged": False,
                },
            ],
            install_ess_agent.load_installation_config(),
        )

        assert [agent["botid"] for agent in inventory["agents"]] == ["ess"]
        assert inventory["installedInstallationKeys"] == ["da.hr"]
        assert [
            option["configKey"]
            for option in inventory["availableInstallations"]
        ] == [
            "da.essit",
            "da.esshub",
            "cea.esshr",
            "cea.essit",
            "cea.esshub",
        ]

    @patch("discover.load_installation_config")
    @patch("discover.discover_agents")
    @patch("discover.authenticate")
    def test_cli_emits_inventory_for_onboarding_choice(
        self,
        authenticate,
        discover_agents,
        load_config,
        capsys,
        monkeypatch,
    ):
        import discover
        import install_ess_agent

        authenticate.return_value = "token"
        load_config.return_value = install_ess_agent.load_installation_config()
        discover_agents.return_value = [{
            "botid": "ess",
            "name": "ESS HR",
            "schemaname": "msdyn_CopilotForEmployeeSelfServiceDAHR",
            "ismanaged": True,
        }]
        monkeypatch.setattr(
            "sys.argv",
            ["discover.py", "--url", "https://org.crm.dynamics.com"],
        )

        discover.main()

        output = capsys.readouterr().out
        marker = next(
            line
            for line in output.splitlines()
            if line.startswith("ESS_AGENT_DISCOVERY_JSON:")
        )
        payload = json.loads(marker.split(":", 1)[1])
        assert len(payload["agents"]) == 1
        assert len(payload["availableInstallations"]) == 5

    def test_url_required_without_list_environments(self, monkeypatch):
        """Without --list-environments, --url is required."""
        monkeypatch.setattr("sys.argv", ["discover.py"])

        import discover

        with pytest.raises(SystemExit) as exc_info:
            discover.main()
        assert exc_info.value.code == 2  # argparse error
