# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/flightcheck/cli.py helpers.

Currently covers ``open_report_in_browser``, the post-run hook that
launches the HTML report in the default browser. The helper is a small
pure-side-effect function (file existence check + ``webbrowser.open``);
tests stub out ``webbrowser.open`` so no browser tab opens during the run.

The motivation for testing this at all is that the first implementation
built the ``file://`` URI with f-string concatenation, which produced
malformed URIs on Windows for any path containing spaces (e.g.
``C:\\Users\\foo\\OneDrive - Microsoft Corporation\\...``). The helper
now goes through ``pathlib.Path.as_uri()`` to produce RFC 8089 compliant
URIs. These tests pin that behavior so it doesn't regress.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from flightcheck import cli


def test_workday_da_check_is_explicit_scope_only() -> None:
    """An optional DA HR package must not fail unrelated full runs."""
    assert cli.SCOPE_MAP["workdayda"] == [
        ("Workday DA", cli.run_workday_da_checks)
    ]
    assert ("Workday DA", cli.run_workday_da_checks) not in cli.FULL_SCOPE


class TestOpenReportInBrowser:
    """Tests for cli.open_report_in_browser."""

    def test_returns_false_when_report_missing(self, tmp_path: Path) -> None:
        # FlightCheck can abort before save_results (e.g. fatal config
        # error). The helper must no-op cleanly in that case rather
        # than 404'ing a browser tab.
        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            result = cli.open_report_in_browser(str(tmp_path))
        assert result is False
        mock_open.assert_not_called()

    def test_returns_true_when_webbrowser_open_succeeds(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "report.html").write_text("<html></html>")
        with patch(
            "flightcheck.cli.webbrowser.open", return_value=True
        ) as mock_open:
            result = cli.open_report_in_browser(str(tmp_path))
        assert result is True
        mock_open.assert_called_once()

    def test_returns_false_when_webbrowser_open_reports_failure(
        self, tmp_path: Path
    ) -> None:
        # ``webbrowser.open`` returns False when it could not locate a
        # browser (e.g. SSH session with no DISPLAY). The helper must
        # propagate that so callers can decide what to do — and it must
        # NOT raise, because FlightCheck's exit code reflects check
        # results, not browser-launch success.
        (tmp_path / "report.html").write_text("<html></html>")
        with patch("flightcheck.cli.webbrowser.open", return_value=False):
            result = cli.open_report_in_browser(str(tmp_path))
        assert result is False

    def test_passes_well_formed_file_uri(self, tmp_path: Path) -> None:
        # All file URIs must start with ``file:///`` (three slashes —
        # empty host segment) per RFC 8089. The pre-fix f-string
        # produced ``file://C:\path...`` on Windows; ``Path.as_uri()``
        # produces ``file:///C:/path/...``.
        (tmp_path / "report.html").write_text("<html></html>")
        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            cli.open_report_in_browser(str(tmp_path))

        uri = mock_open.call_args[0][0]
        assert uri.startswith("file:///")
        assert uri.endswith("/report.html")
        assert "\\" not in uri  # forward slashes only

    def test_handles_paths_with_spaces(self, tmp_path: Path) -> None:
        # The original bug: ``f"file://{abs_path}"`` produces an
        # unescaped URI for paths with spaces (e.g. Windows OneDrive
        # paths). ``Path.as_uri()`` percent-encodes them as ``%20``.
        spaced = tmp_path / "my output dir"
        spaced.mkdir()
        (spaced / "report.html").write_text("<html></html>")

        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            cli.open_report_in_browser(str(spaced))

        uri = mock_open.call_args[0][0]
        assert "%20" in uri
        assert " " not in uri  # raw space would be malformed

    def test_resolves_relative_output_dir(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # CLI's default ``--output`` is ``workspace/flightcheck`` (relative).
        # The helper must resolve it to an absolute path so the resulting
        # ``file:///`` URI points at the right place even after a later
        # ``os.chdir``.
        monkeypatch.chdir(tmp_path)
        rel_out = Path("workspace/flightcheck")
        rel_out.mkdir(parents=True)
        (rel_out / "report.html").write_text("<html></html>")

        with patch("flightcheck.cli.webbrowser.open") as mock_open:
            cli.open_report_in_browser(str(rel_out))

        uri = mock_open.call_args[0][0]
        # tmp_path is absolute; the resolved URI must contain it (modulo
        # platform-specific drive-letter encoding).
        assert "workspace/flightcheck/report.html" in uri


class _FakeRunner:
    last_instance = None

    def __init__(self, scope: str) -> None:
        type(self).last_instance = self
        self.scope = scope
        self.registered = []
        self.config = None
        self.env_url = None
        self.dv_token = None
        self.env_id = None
        self.graph = None
        self.pp_admin = None
        self.pva = None
        self.powerplatform = None
        self.azure_arm = None
        self.agentbuilder = None
        self.connectivity = None
        self.native_connector_filter = None

    def register(self, category, fn):
        self.registered.append((category, fn))

    def run(self):
        return SimpleNamespace(
            failed=0,
            results=[],
            overall="READY",
            warnings=0,
            errors=0,
            manual=0,
            not_configured=0,
            skipped=0,
            passed=0,
            total=0,
            duration_secs=0,
        )


class TestInfrastructureScopeAuthGating:
    def test_infrastructure_scope_runs_without_dataverse_endpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text('{"agents":[]}', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli, "FlightCheckRunner", _FakeRunner)
        monkeypatch.setattr(cli, "_print_prioritized_summary", lambda _result: None)
        monkeypatch.setattr(cli, "save_results", lambda _result, _output: None)
        monkeypatch.setattr(
            cli,
            "GraphClient",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Graph auth should be skipped")),
        )
        monkeypatch.setattr(
            cli,
            "PPAdminClient",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PP auth should be skipped")),
        )
        monkeypatch.setattr(
            cli,
            "PVAClient",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PVA auth should be skipped")),
        )
        monkeypatch.setattr("sys.argv", ["cli.py", "--scope", "infrastructure", "--no-open"])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0

    def test_non_infrastructure_scope_requires_dataverse_endpoint(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text('{"agents":[]}', encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["cli.py", "--scope", "environment", "--no-open"])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 1


class TestAgentBuilderLocalScope:
    def test_runs_without_dataverse_or_remote_authentication(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text(
            json.dumps(
                {
                    "environmentId": "environment-id",
                    "agents": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli, "FlightCheckRunner", _FakeRunner)
        monkeypatch.setattr(
            cli,
            "_print_prioritized_summary",
            lambda _result: None,
        )
        monkeypatch.setattr(cli, "save_results", lambda _result, _output: None)
        for client_name in (
            "GraphClient",
            "PPAdminClient",
            "PVAClient",
            "PowerPlatformClient",
            "AzureArmClient",
        ):
            monkeypatch.setattr(
                cli,
                client_name,
                lambda *_args, _name=client_name, **_kwargs: (
                    _ for _ in ()
                ).throw(
                    AssertionError(
                        f"{_name} auth should be skipped"
                    )
                ),
            )
        monkeypatch.setattr(
            "sys.argv",
            [
                "cli.py",
                "--scope",
                "local",
                "--no-open",
                "--no-telemetry",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0


class TestAgentBuilderNativeScopes:
    @pytest.mark.parametrize(
        (
            "scope",
            "expected_categories",
            "expects_agent_clients",
            "expects_capacity_client",
            "expected_filter",
        ),
        [
            (
                "full",
                ["Native Agent", "Environment", "Local Files", "Publishing"],
                True,
                True,
                None,
            ),
            ("environment", ["Environment"], False, True, None),
            (
                "servicenow",
                ["Native Agent"],
                True,
                False,
                ("shared_service-now",),
            ),
            (
                "workday",
                ["Native Agent"],
                True,
                False,
                ("shared_workdaysoap",),
            ),
            ("publishing", ["Publishing"], True, False, None),
        ],
    )
    def test_native_no_dataverse_scope_uses_only_native_clients(
        self,
        scope: str,
        expected_categories: list[str],
        expects_agent_clients: bool,
        expects_capacity_client: bool,
        expected_filter: tuple[str, ...] | None,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        config = {
            "releaseLine": "da",
            "environmentId": "00000000-0000-4000-8000-000000001111",
            "agent": {
                "slug": "mock-agent",
                "botId": "00000000-0000-4000-8000-000000002222",
                "releaseLine": "da",
            },
            "activeAgent": "mock-agent",
        }
        if expects_agent_clients:
            config["powerPlatformApiEndpoint"] = (
                "https://0000000000004000800000000000111."
                "1.environment.api.test.powerplatform.com"
            )
        (local_dir / "config.json").write_text(
            json.dumps(config),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli, "FlightCheckRunner", _FakeRunner)
        monkeypatch.setattr(
            cli,
            "_print_prioritized_summary",
            lambda _result: None,
        )
        monkeypatch.setattr(cli, "save_results", lambda _result, _output: None)
        monkeypatch.setattr(
            cli,
            "_resolve_target_selection",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("Legacy target selection should be skipped")
            ),
        )
        for client_name in ("GraphClient", "PPAdminClient", "PVAClient", "AzureArmClient"):
            monkeypatch.setattr(
                cli,
                client_name,
                lambda *_a, _name=client_name, **_k: (
                    _ for _ in ()
                ).throw(AssertionError(f"{_name} should be skipped")),
            )

        auth_calls = []

        def _authenticate_native(ring, **kwargs):
            auth_calls.append((ring, kwargs))
            return "native-token", "tenant-id"

        created_agent_clients = []
        created_connectivity_clients = []
        created_capacity_clients = []
        monkeypatch.setattr(cli, "authenticate_flightcheck", _authenticate_native)
        monkeypatch.setattr(
            cli,
            "AgentBuilderClient",
            lambda *args, **kwargs: (
                created_agent_clients.append((args, kwargs)) or object()
            ),
        )
        monkeypatch.setattr(
            cli,
            "ConnectivityClient",
            lambda *args, **kwargs: (
                created_connectivity_clients.append((args, kwargs)) or object()
            ),
        )

        class _CapacityClient:
            def __init__(self, *args, **kwargs) -> None:
                created_capacity_clients.append((args, kwargs))

            def authenticate(self):
                return None

        monkeypatch.setattr(cli, "PowerPlatformClient", _CapacityClient)
        monkeypatch.setattr(
            "sys.argv",
            [
                "cli.py",
                "--scope",
                scope,
                "--no-open",
                "--no-telemetry",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0
        assert auth_calls == (
            [("test", {"include_connectivity": True})]
            if expects_agent_clients
            else []
        )
        assert bool(created_agent_clients) is expects_agent_clients
        assert bool(created_connectivity_clients) is expects_agent_clients
        assert bool(created_capacity_clients) is expects_capacity_client
        runner = _FakeRunner.last_instance
        assert runner is not None
        assert [category for category, _ in runner.registered] == expected_categories
        assert runner.native_connector_filter == expected_filter

    def test_native_no_dataverse_rejects_legacy_only_scope(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text(
            json.dumps(
                {
                    "releaseLine": "da",
                    "environmentId": "00000000-0000-4000-8000-000000001111",
                    "powerPlatformApiEndpoint": (
                        "https://0000000000004000800000000000111."
                        "1.environment.api.test.powerplatform.com"
                    ),
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            cli,
            "authenticate_flightcheck",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("Authentication should not start")
            ),
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "cli.py",
                "--scope",
                "solution",
                "--no-open",
                "--no-telemetry",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 1


class _OkClient:
    """Minimal client stub whose authenticate() succeeds and does nothing."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def authenticate(self):
        return None


class _RecordingPVA:
    """PVAClient stub that records whether main() instantiated it."""

    instantiated = False

    def __init__(self, *args, **kwargs) -> None:
        type(self).instantiated = True
        self.is_configured = True

    def authenticate(self):
        return "pva-token"


class TestPvaScopeGating:
    """Regression coverage for the ``--scope handoff`` PVA-auth gate.

    ``SCOPE_MAP['handoff']`` wires ``run_handoff_topic_checks`` (TOPIC-020),
    which reads ``runner.pva.get_dialog_components(bot_id)``. If the ``handoff``
    scope is omitted from the PVA-auth gate in ``main()``, ``runner.pva`` is
    ``None`` and the check silently returns ``[]`` WITHOUT ever querying the
    tenant — the run reports 0 checks and looks "ready" while validating
    nothing. These pin that the handoff scope authenticates Copilot Studio.
    """

    def test_pva_scopes_includes_every_pva_dependent_scope(self) -> None:
        # Every scope whose SCOPE_MAP checks read runner.pva must be gated
        # into PVA auth: local (CONFIG-013), graphconnector (KB status),
        # handoff (TOPIC-020). "full" runs all of them.
        assert {"full", "local", "graphconnector", "handoff"} <= cli.PVA_SCOPES

    def test_handoff_scope_authenticates_pva(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text(
            '{"agents":[],"dataverseEndpoint":"https://org.crm.dynamics.com"}',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("auth.authenticate", lambda *_a, **_k: "dv-token")
        monkeypatch.setattr("auth.discover_tenant", lambda *_a, **_k: "tenant-id")
        monkeypatch.setattr(cli, "GraphClient", _OkClient)
        monkeypatch.setattr(cli, "PPAdminClient", _OkClient)
        monkeypatch.setattr(cli, "derive_environment_id", lambda *_a, **_k: "env-id")
        _RecordingPVA.instantiated = False
        monkeypatch.setattr(cli, "PVAClient", _RecordingPVA)
        monkeypatch.setattr(cli, "FlightCheckRunner", _FakeRunner)
        monkeypatch.setattr(cli, "_resolve_target_selection", lambda *_a, **_k: None)
        monkeypatch.setattr(
            cli, "_apply_runtime_reachability_consent", lambda *_a, **_k: None
        )
        monkeypatch.setattr(cli, "_print_prioritized_summary", lambda _result: None)
        monkeypatch.setattr(cli, "save_results", lambda _result, _output: None)
        monkeypatch.setattr(
            "sys.argv",
            ["cli.py", "--scope", "handoff", "--no-open", "--no-telemetry"],
        )

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0
        assert _RecordingPVA.instantiated is True
