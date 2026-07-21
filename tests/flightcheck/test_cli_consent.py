# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
CLI-level tests for the runtime-reachability consent gate
(``cli._apply_runtime_reachability_consent`` — Approach C).

``test_consent.py`` unit-tests the ``consent`` module in isolation. This file
tests the CLI wiring that decides, for every run path, whether the mutating
egress probe may create its flow:

- forced on  (``--runtime-reachability``)            -> enabled, transparency notice
- forced off (``--no-runtime-reachability``)         -> declined, skip + manual links
- omit + interactive + endpoints -> ASK              -> honours the Y/N answer
- omit + non-tty / CI                                -> read-only, no prompt
- omit + no endpoints                                -> no offer
- ADK/chat path (``--invocation-source adk``)        -> never prompts (skill owns consent)
- INFRA-003 not in scope                             -> flag respected, no offer logic

The gate is the single chokepoint all run paths funnel through, so covering it
here locks the behaviour the live end-to-end scenarios would otherwise verify by
hand.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from flightcheck import cli


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


def _runner(connections: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(config={"connections": connections or {}})


def _args(**kw) -> SimpleNamespace:
    kw.setdefault("runtime_reachability", None)
    kw.setdefault("invocation_source", "cli")
    return SimpleNamespace(**kw)


_INFRA_CHECKS = [("Infrastructure", cli.run_infrastructure_checks)]
_NON_INFRA_CHECKS = [("Local", lambda runner: [])]

_WD = {"Workday": {"baseUrl": "https://wd.example.com"}}


def _force_tty(monkeypatch, *, interactive: bool) -> None:
    """Make both stdin and stdout report ``isatty()`` == ``interactive`` while
    still forwarding real writes (so ``print``/capsys keep working)."""

    class _TtyProxy:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def isatty(self):
            return interactive

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    monkeypatch.setattr(cli.sys, "stdin", _TtyProxy(cli.sys.stdin))
    monkeypatch.setattr(cli.sys, "stdout", _TtyProxy(cli.sys.stdout))


# ───────────────────────────────────────────────────────────────────────
# Forced on / off via the flag (no prompt either way)
# ───────────────────────────────────────────────────────────────────────


class TestForcedFlag:
    def test_forced_on_enables_and_prints_transparency_notice(self, capsys):
        runner = _runner(_WD)
        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=True), runner, _INFRA_CHECKS
        )
        assert runner.runtime_reachability is True
        assert runner.runtime_reachability_declined is False
        out = capsys.readouterr().out
        assert "Runtime-reachability probe enabled" in out
        assert "Workday" in out

    def test_forced_off_declines_and_prints_skip_and_links(self, capsys):
        runner = _runner(_WD)
        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=False), runner, _INFRA_CHECKS
        )
        assert runner.runtime_reachability is False
        assert runner.runtime_reachability_declined is True
        out = capsys.readouterr().out
        assert "Connectivity check skipped" in out
        assert cli.consent.OUTBOUND_IP_ARTICLE_URL in out
        assert cli.consent.SERVICE_TAGS_JSON_URL in out


# ───────────────────────────────────────────────────────────────────────
# Approach C: proactive offer on an interactive terminal
# ───────────────────────────────────────────────────────────────────────


class TestInteractiveOffer:
    def test_interactive_yes_enables_without_transparency_notice(
        self, monkeypatch, capsys
    ):
        _force_tty(monkeypatch, interactive=True)
        monkeypatch.setattr(cli.consent, "ask_yes_no", lambda label: True)
        runner = _runner(_WD)

        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=None), runner, _INFRA_CHECKS
        )

        assert runner.runtime_reachability is True
        assert runner.runtime_reachability_declined is False
        # It was PROMPTED, so the forced-on transparency notice must NOT print.
        assert "Runtime-reachability probe enabled" not in capsys.readouterr().out

    def test_interactive_no_declines_and_prints_skip(self, monkeypatch, capsys):
        _force_tty(monkeypatch, interactive=True)
        monkeypatch.setattr(cli.consent, "ask_yes_no", lambda label: False)
        runner = _runner(_WD)

        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=None), runner, _INFRA_CHECKS
        )

        assert runner.runtime_reachability is False
        assert runner.runtime_reachability_declined is True
        assert "Connectivity check skipped" in capsys.readouterr().out


# ───────────────────────────────────────────────────────────────────────
# Non-interactive / CI and no-endpoint paths stay read-only, no prompt
# ───────────────────────────────────────────────────────────────────────


class TestReadOnlyPaths:
    def test_non_tty_omit_flag_auto_declines_without_prompting(
        self, monkeypatch, capsys
    ):
        _force_tty(monkeypatch, interactive=False)
        # If the gate tried to prompt on a non-tty run, this would raise.
        def _boom(label):  # noqa: ANN001
            raise AssertionError("must not prompt on a non-tty run")

        monkeypatch.setattr(cli.consent, "ask_yes_no", _boom)
        runner = _runner(_WD)

        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=None), runner, _INFRA_CHECKS
        )

        assert runner.runtime_reachability is False
        # Passive skip (CI), not an explicit decline -> no manual-links spam.
        assert runner.runtime_reachability_declined is False
        assert "Connectivity check skipped" not in capsys.readouterr().out

    def test_no_endpoints_makes_no_offer(self, monkeypatch):
        _force_tty(monkeypatch, interactive=True)

        def _boom(label):  # noqa: ANN001
            raise AssertionError("must not prompt when there is nothing to probe")

        monkeypatch.setattr(cli.consent, "ask_yes_no", _boom)
        runner = _runner({})  # no connections

        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=None), runner, _INFRA_CHECKS
        )

        assert runner.runtime_reachability is False
        assert runner.runtime_reachability_declined is False


# ───────────────────────────────────────────────────────────────────────
# ADK / chat path: the skill owns consent, so the CLI never prompts
# ───────────────────────────────────────────────────────────────────────


class TestAdkChatPath:
    def test_adk_never_prompts_even_on_a_tty(self, monkeypatch):
        _force_tty(monkeypatch, interactive=True)

        def _boom(label):  # noqa: ANN001
            raise AssertionError("ADK path must not prompt; the skill asks the user")

        monkeypatch.setattr(cli.consent, "ask_yes_no", _boom)
        runner = _runner(_WD)

        # No flag on the ADK path (skill didn't pass one) -> stays off, no prompt.
        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=None, invocation_source="adk"),
            runner,
            _INFRA_CHECKS,
        )
        assert runner.runtime_reachability is False
        assert runner.runtime_reachability_declined is False

    def test_adk_with_flag_enables_without_prompting(self, monkeypatch, capsys):
        _force_tty(monkeypatch, interactive=True)

        def _boom(label):  # noqa: ANN001
            raise AssertionError("ADK path must not prompt")

        monkeypatch.setattr(cli.consent, "ask_yes_no", _boom)
        runner = _runner(_WD)

        # The skill asked the user and passed --runtime-reachability on YES.
        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=True, invocation_source="adk"),
            runner,
            _INFRA_CHECKS,
        )
        assert runner.runtime_reachability is True
        assert "Runtime-reachability probe enabled" in capsys.readouterr().out


# ───────────────────────────────────────────────────────────────────────
# INFRA-003 not in scope: flag is respected, offer logic is skipped
# ───────────────────────────────────────────────────────────────────────


class TestInfraNotInScope:
    @pytest.mark.parametrize(
        "flag,expected", [(True, True), (False, False), (None, False)]
    )
    def test_offer_skipped_when_infra_out_of_scope(self, monkeypatch, flag, expected):
        _force_tty(monkeypatch, interactive=True)

        def _boom(label):  # noqa: ANN001
            raise AssertionError("must not prompt when INFRA-003 is not in scope")

        monkeypatch.setattr(cli.consent, "ask_yes_no", _boom)
        runner = _runner(_WD)

        cli._apply_runtime_reachability_consent(
            _args(runtime_reachability=flag), runner, _NON_INFRA_CHECKS
        )
        assert runner.runtime_reachability is expected
        assert runner.runtime_reachability_declined is False
