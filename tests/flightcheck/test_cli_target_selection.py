# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the standalone-flightcheck target-selection CLI helpers.

These cover the pure decision logic the ``--scope`` path uses to let an
operator pin which Workday SSO app / ServiceNow connection to verify:

  * ``_prompt_choice``   — the numbered interactive picker + "0 = All".
  * ``_maybe_prompt``    — whether to prompt at all (ambiguity + TTY gate,
                            plus the ``--select-targets`` override).
  * ``_resolve_workday_app`` / ``_resolve_servicenow_connection`` — apply an
    explicit flag or a picked value to the runner (Workday writes the
    ``entraAppId`` hint on ``runner.config`` so it flows through the same
    ``_workday_hints`` path every Workday-SSO-app check reads; ServiceNow
    writes ``runner.servicenow_connection_pin``).
  * ``_resolve_target_selection`` — the scope gate that only pins targets
    for scopes that actually run the affected checks.
  * ``_discover_*`` — projecting the raw client responses into picker rows.

All helpers are pure/side-effect-on-runner, so no network or real auth is
needed: discovery clients are stubbed and ``input`` is patched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from flightcheck import cli
from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)

# `_resolve_workday_app` resolves the persisted pin through the shared
# `_workday_hints` (runner.config / .local/connect/workday/config.json); patch
# it at its source module so the inline `from ... import _workday_hints` picks
# up the stub.
_HINTS = "flightcheck.checks._workday_app_assignment._workday_hints"


def _args(**overrides):
    """Argparse-Namespace stand-in with the target-selection defaults."""
    base = dict(
        workday_app_id=None,
        servicenow_connection=None,
        select_targets="auto",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_WD_CANDIDATES = [
    {"appId": "app-a", "displayName": "Workday Prod", "id": "id-a"},
    {"appId": "app-b", "displayName": "Workday Dev", "id": "id-b"},
]
_SN_CANDIDATES = [
    {"name": "sn-prod-1", "displayName": "ServiceNow Prod", "status": "Connected"},
    {"name": "sn-dev-2", "displayName": "ServiceNow Dev", "status": "Connected"},
]


def _tty(is_tty: bool):
    """Patch cli.sys.stdin/stdout so the TTY gate sees the given state.

    The fake stream also provides no-op ``write``/``flush`` so the helpers'
    ``print`` calls don't blow up (and don't pollute captured output).
    """
    stream = SimpleNamespace(
        isatty=lambda: is_tty,
        write=lambda *a, **k: None,
        flush=lambda *a, **k: None,
    )
    return (
        patch.object(cli.sys, "stdin", stream),
        patch.object(cli.sys, "stdout", stream),
    )


# ───────────────────────────────────────────────────────────────────────
# _prompt_choice
# ───────────────────────────────────────────────────────────────────────


class TestPromptChoice:
    def test_workday_pick_returns_app_id(self) -> None:
        with patch("builtins.input", return_value="1"):
            assert cli._prompt_choice(_WD_CANDIDATES, kind="workday") == "app-a"

    def test_workday_second_pick_returns_second_app_id(self) -> None:
        with patch("builtins.input", return_value="2"):
            assert cli._prompt_choice(_WD_CANDIDATES, kind="workday") == "app-b"

    def test_servicenow_pick_returns_connection_name(self) -> None:
        with patch("builtins.input", return_value="1"):
            assert cli._prompt_choice(_SN_CANDIDATES, kind="servicenow") == "sn-prod-1"

    def test_zero_returns_select_all(self) -> None:
        with patch("builtins.input", return_value="0"):
            assert cli._prompt_choice(_WD_CANDIDATES, kind="workday") == cli._SELECT_ALL

    def test_blank_defaults_to_select_all(self) -> None:
        with patch("builtins.input", return_value=""):
            assert cli._prompt_choice(_WD_CANDIDATES, kind="workday") == cli._SELECT_ALL

    def test_invalid_then_valid_reprompts(self) -> None:
        # Out-of-range, then non-numeric, then a valid pick.
        with patch("builtins.input", side_effect=["9", "abc", "2"]):
            assert cli._prompt_choice(_WD_CANDIDATES, kind="workday") == "app-b"

    def test_eof_returns_none(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            assert cli._prompt_choice(_WD_CANDIDATES, kind="workday") is None


# ───────────────────────────────────────────────────────────────────────
# _maybe_prompt
# ───────────────────────────────────────────────────────────────────────


class TestMaybePrompt:
    def test_never_disables_prompting(self) -> None:
        stdin, stdout = _tty(True)
        with stdin, stdout, patch("builtins.input", return_value="1"):
            assert cli._maybe_prompt(
                _WD_CANDIDATES, kind="workday", args=_args(select_targets="never")
            ) is None

    def test_single_candidate_does_not_prompt(self) -> None:
        stdin, stdout = _tty(True)
        with stdin, stdout, patch("builtins.input") as inp:
            assert cli._maybe_prompt(
                _WD_CANDIDATES[:1], kind="workday", args=_args()
            ) is None
            inp.assert_not_called()

    def test_zero_candidates_does_not_prompt(self) -> None:
        assert cli._maybe_prompt([], kind="workday", args=_args()) is None

    def test_auto_non_tty_falls_back_to_all(self) -> None:
        stdin, stdout = _tty(False)
        with stdin, stdout, patch("builtins.input") as inp:
            assert cli._maybe_prompt(
                _WD_CANDIDATES, kind="workday", args=_args(select_targets="auto")
            ) is None
            inp.assert_not_called()

    def test_always_non_tty_falls_back_to_all(self) -> None:
        stdin, stdout = _tty(False)
        with stdin, stdout, patch("builtins.input") as inp:
            assert cli._maybe_prompt(
                _WD_CANDIDATES, kind="workday", args=_args(select_targets="always")
            ) is None
            inp.assert_not_called()

    def test_auto_tty_prompts_and_returns_choice(self) -> None:
        stdin, stdout = _tty(True)
        with stdin, stdout, patch("builtins.input", return_value="2"):
            assert cli._maybe_prompt(
                _WD_CANDIDATES, kind="workday", args=_args()
            ) == "app-b"


# ───────────────────────────────────────────────────────────────────────
# _resolve_workday_app / _resolve_servicenow_connection
# ───────────────────────────────────────────────────────────────────────


class TestResolveWorkdayApp:
    def test_explicit_flag_sets_entra_app_id(self) -> None:
        runner = SimpleNamespace(graph=None, config={})
        cli._resolve_workday_app(_args(workday_app_id="app-a"), runner)
        assert runner.config["entraAppId"] == "app-a"

    def test_flag_takes_precedence_over_picker(self) -> None:
        runner = SimpleNamespace(graph=object(), config={})
        with patch.object(cli, "_discover_workday_apps") as disc, \
                patch.object(cli, "_maybe_prompt") as prompt:
            cli._resolve_workday_app(_args(workday_app_id="app-a"), runner)
        # A flag short-circuits discovery entirely.
        disc.assert_not_called()
        prompt.assert_not_called()
        assert runner.config["entraAppId"] == "app-a"

    def test_picker_selection_sets_entra_app_id(self) -> None:
        runner = SimpleNamespace(graph=object(), config={})
        with patch.object(cli, "_discover_workday_apps", return_value=_WD_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value="app-b"):
            cli._resolve_workday_app(_args(select_targets="always"), runner)
        assert runner.config["entraAppId"] == "app-b"

    def test_select_all_clears_existing_hint(self) -> None:
        runner = SimpleNamespace(graph=object(), config={"entraAppId": "stale-app"})
        with patch.object(cli, "_discover_workday_apps", return_value=_WD_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value=cli._SELECT_ALL):
            cli._resolve_workday_app(_args(select_targets="always"), runner)
        assert runner.config["entraAppId"] == ""

    def test_never_leaves_config_untouched(self) -> None:
        runner = SimpleNamespace(graph=object(), config={})
        with patch.object(cli, "_discover_workday_apps") as disc:
            cli._resolve_workday_app(_args(select_targets="never"), runner)
        disc.assert_not_called()
        assert "entraAppId" not in runner.config

    def test_persisted_config_used_on_auto_without_flag(self) -> None:
        # Default `auto` + no flag: the app the setup flow persisted (resolved
        # via the shared `_workday_hints`) is confirmed and used, and the
        # interactive picker is skipped (the fix for the setup P5.9 block).
        runner = SimpleNamespace(graph=object(), config={})
        with patch(_HINTS, return_value=("app-cfg", "")), \
                patch.object(cli, "_confirm_persisted_workday_app", return_value=True) as confirm, \
                patch.object(cli, "_discover_workday_apps") as disc, \
                patch.object(cli, "_maybe_prompt") as prompt:
            cli._resolve_workday_app(_args(), runner)
        confirm.assert_called_once()
        disc.assert_not_called()
        prompt.assert_not_called()
        assert runner.config["entraAppId"] == "app-cfg"

    def test_persisted_config_declined_falls_back_to_picker(self) -> None:
        # Operator declines the stored app at the confirm prompt → fall through
        # to the picker and use their pick for this run, not the stored app.
        runner = SimpleNamespace(graph=object(), config={})
        with patch(_HINTS, return_value=("app-cfg", "")), \
                patch.object(cli, "_confirm_persisted_workday_app", return_value=False), \
                patch.object(cli, "_discover_workday_apps", return_value=_WD_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value="app-b"):
            cli._resolve_workday_app(_args(), runner)
        assert runner.config["entraAppId"] == "app-b"

    def test_flag_wins_over_persisted_config(self) -> None:
        runner = SimpleNamespace(graph=object(), config={})
        with patch(_HINTS) as hints:
            cli._resolve_workday_app(_args(workday_app_id="app-a"), runner)
        # An explicit flag short-circuits before the persisted-config lookup.
        hints.assert_not_called()
        assert runner.config["entraAppId"] == "app-a"

    def test_persisted_config_ignored_when_always(self) -> None:
        # `always` forces the picker even when a persisted app exists.
        runner = SimpleNamespace(graph=object(), config={})
        with patch(_HINTS) as hints, \
                patch.object(cli, "_discover_workday_apps", return_value=_WD_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value="app-b"):
            cli._resolve_workday_app(_args(select_targets="always"), runner)
        hints.assert_not_called()
        assert runner.config["entraAppId"] == "app-b"

    def test_persisted_config_ignored_when_never(self) -> None:
        runner = SimpleNamespace(graph=object(), config={})
        with patch(_HINTS) as hints, \
                patch.object(cli, "_discover_workday_apps") as disc:
            cli._resolve_workday_app(_args(select_targets="never"), runner)
        hints.assert_not_called()
        disc.assert_not_called()
        assert "entraAppId" not in runner.config

    def test_auto_falls_back_to_picker_when_no_persisted(self) -> None:
        runner = SimpleNamespace(graph=object(), config={})
        with patch(_HINTS, return_value=("", "")), \
                patch.object(cli, "_discover_workday_apps", return_value=_WD_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value="app-b"):
            cli._resolve_workday_app(_args(), runner)
        assert runner.config["entraAppId"] == "app-b"


class TestConfirmPersistedWorkdayApp:
    """`_confirm_persisted_workday_app` — the stored-app reminder + confirm
    shown on the installer / python paths before the run is scoped."""

    def test_non_interactive_uses_app_without_prompting(self) -> None:
        # Installer child process / piped run: never block on input().
        with patch.object(cli, "_is_interactive", return_value=False), \
                patch.object(cli, "_discover_workday_apps", return_value=[]), \
                patch("builtins.input", side_effect=AssertionError("must not prompt")):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is True

    def test_interactive_yes_confirms(self) -> None:
        with patch.object(cli, "_is_interactive", return_value=True), \
                patch.object(cli, "_discover_workday_apps", return_value=[]), \
                patch("builtins.input", return_value="y"):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is True

    def test_interactive_blank_defaults_to_yes(self) -> None:
        with patch.object(cli, "_is_interactive", return_value=True), \
                patch.object(cli, "_discover_workday_apps", return_value=[]), \
                patch("builtins.input", return_value=""):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is True

    def test_interactive_no_declines(self) -> None:
        with patch.object(cli, "_is_interactive", return_value=True), \
                patch.object(cli, "_discover_workday_apps", return_value=[]), \
                patch("builtins.input", return_value="n"):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is False

    def test_interactive_invalid_then_yes_reprompts(self) -> None:
        with patch.object(cli, "_is_interactive", return_value=True), \
                patch.object(cli, "_discover_workday_apps", return_value=[]), \
                patch("builtins.input", side_effect=["maybe", "yes"]):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is True

    def test_interactive_eof_defaults_to_yes(self) -> None:
        with patch.object(cli, "_is_interactive", return_value=True), \
                patch.object(cli, "_discover_workday_apps", return_value=[]), \
                patch("builtins.input", side_effect=EOFError):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is True

    def test_reminder_shows_resolved_display_name(self, capsys) -> None:
        with patch.object(cli, "_is_interactive", return_value=False), \
                patch.object(cli, "_discover_workday_apps", return_value=_WD_CANDIDATES):
            cli._confirm_persisted_workday_app("app-a", graph=object())
        out = capsys.readouterr().out
        assert "Workday Prod" in out          # friendly name from discovery
        assert "app-a" in out                 # and the appId
        assert "subsequent Workday configuration" in out

    def test_no_graph_skips_discovery_and_uses_id(self, capsys) -> None:
        with patch.object(cli, "_is_interactive", return_value=False), \
                patch.object(cli, "_discover_workday_apps") as disc:
            assert cli._confirm_persisted_workday_app("app-a", graph=None) is True
        disc.assert_not_called()
        assert "app-a" in capsys.readouterr().out

    def test_discovery_failure_falls_back_to_id(self, capsys) -> None:
        with patch.object(cli, "_is_interactive", return_value=False), \
                patch.object(cli, "_discover_workday_apps",
                             side_effect=RuntimeError("graph down")):
            assert cli._confirm_persisted_workday_app("app-a", graph=object()) is True
        assert "app-a" in capsys.readouterr().out


class TestResolveServiceNowConnection:
    def test_explicit_flag_sets_pin(self) -> None:
        runner = SimpleNamespace(pp_admin=None, env_id=None, servicenow_connection_pin="")
        cli._resolve_servicenow_connection(
            _args(servicenow_connection="sn-prod-1"), runner
        )
        assert runner.servicenow_connection_pin == "sn-prod-1"

    def test_picker_selection_sets_pin(self) -> None:
        runner = SimpleNamespace(
            pp_admin=object(), env_id="env-1", servicenow_connection_pin=""
        )
        with patch.object(cli, "_discover_servicenow_connections",
                          return_value=_SN_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value="sn-dev-2"):
            cli._resolve_servicenow_connection(_args(select_targets="always"), runner)
        assert runner.servicenow_connection_pin == "sn-dev-2"

    def test_select_all_leaves_pin_empty(self) -> None:
        runner = SimpleNamespace(
            pp_admin=object(), env_id="env-1", servicenow_connection_pin=""
        )
        with patch.object(cli, "_discover_servicenow_connections",
                          return_value=_SN_CANDIDATES), \
                patch.object(cli, "_maybe_prompt", return_value=cli._SELECT_ALL):
            cli._resolve_servicenow_connection(_args(select_targets="always"), runner)
        assert runner.servicenow_connection_pin == ""


# ───────────────────────────────────────────────────────────────────────
# _resolve_target_selection — scope gate
# ───────────────────────────────────────────────────────────────────────


class TestResolveTargetSelection:
    def _runner(self, scope: str):
        return SimpleNamespace(
            scope=scope, graph=None, pp_admin=None, env_id=None,
            config={}, servicenow_connection_pin="",
        )

    def test_workday_scope_pins_only_workday(self) -> None:
        runner = self._runner("workday")
        cli._resolve_target_selection(
            _args(workday_app_id="app-a", servicenow_connection="sn-x"), runner
        )
        assert runner.config["entraAppId"] == "app-a"
        # ServiceNow is not in a Workday scope → its pin must stay empty.
        assert runner.servicenow_connection_pin == ""

    def test_servicenow_scope_pins_only_servicenow(self) -> None:
        runner = self._runner("servicenow")
        cli._resolve_target_selection(
            _args(workday_app_id="app-a", servicenow_connection="sn-x"), runner
        )
        assert runner.servicenow_connection_pin == "sn-x"
        assert "entraAppId" not in runner.config

    def test_full_scope_pins_both(self) -> None:
        runner = self._runner("full")
        cli._resolve_target_selection(
            _args(workday_app_id="app-a", servicenow_connection="sn-x"), runner
        )
        assert runner.config["entraAppId"] == "app-a"
        assert runner.servicenow_connection_pin == "sn-x"

    def test_unrelated_scope_pins_nothing(self) -> None:
        runner = self._runner("environment")
        cli._resolve_target_selection(
            _args(workday_app_id="app-a", servicenow_connection="sn-x"), runner
        )
        assert "entraAppId" not in runner.config
        assert runner.servicenow_connection_pin == ""


# ───────────────────────────────────────────────────────────────────────
# _discover_workday_apps / _discover_servicenow_connections
# ───────────────────────────────────────────────────────────────────────


class TestDiscovery:
    def test_discover_workday_apps_projects_rows(self) -> None:
        raw = [
            {"appId": "app-a", "displayName": "Workday Prod", "id": "id-a",
             "extra": "ignored"},
        ]
        graph = SimpleNamespace(get_workday_saml_service_principals=lambda: raw)
        rows = cli._discover_workday_apps(graph)
        assert rows == [{"appId": "app-a", "displayName": "Workday Prod", "id": "id-a"}]

    def test_discover_servicenow_filters_non_servicenow(self) -> None:
        conns = [
            pp.servicenow_connection(
                display_name="ServiceNow Prod", connection_name="sn-1",
                status="Connected",
            ),
            pp.connection(
                name="wd-1", display_name="Workday SOAP",
                api_name="shared_workdaysoap", status="Connected",
            ),
        ]
        pp_admin = SimpleNamespace(get_connections=lambda env_id: conns)
        rows = cli._discover_servicenow_connections(pp_admin, "env-1")
        assert rows == [
            {"name": "sn-1", "displayName": "ServiceNow Prod", "status": "Connected"}
        ]

    def test_discover_servicenow_handles_error_dict(self) -> None:
        pp_admin = SimpleNamespace(get_connections=lambda env_id: {"_error": "403"})
        assert cli._discover_servicenow_connections(pp_admin, "env-1") == []

    def test_discover_servicenow_no_env_returns_empty(self) -> None:
        pp_admin = SimpleNamespace(get_connections=lambda env_id: [])
        assert cli._discover_servicenow_connections(pp_admin, None) == []
