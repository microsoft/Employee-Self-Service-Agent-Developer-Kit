# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pins the single-checkpoint gating of the interactive Workday runtime
prompts (test employee ID + ISU credentials).

Bug this pins the fix for: running ``--checkpoint WD-PKG-001`` used to
block on ``Test Employee ID (e.g. 21508):``. WD-PKG-001's registered
``category_fn`` is ``run_workday_checks`` — the whole Workday pipeline —
so the workflow / personal-data checks (which consume the test employee
ID and ISU credentials) execute during hydration even though only the
WD-PKG-001 rows survive ``run()``'s post-filter. The prompt therefore
fired for a row that is immediately discarded.

The fix (``_interactive_workday_prompts_allowed``) allows the prompt on
full/scope runs (legacy behavior) and, in ``--checkpoint`` mode, only
when the target overlaps a runtime-input-consuming family (WD-WF-*).

These are pure-logic tests (no external API), so the cassette/mock-tier
cardinal rule in tests/AGENTS.md does not apply.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from flightcheck import registry


@dataclass
class _CheckpointRunner:
    """Stand-in mirroring the two attributes the gate reads on a real
    ``FlightCheckRunner``: ``scope`` (``"checkpoint:{target}"`` in
    single-checkpoint mode, ``"full"`` otherwise) and ``_target_matcher``
    (None on full/scope runs). ``config`` is read by the resolvers."""

    scope: str = "full"
    _target_matcher: Callable[[str], bool] | None = None
    config: dict[str, Any] = field(default_factory=dict)


def _checkpoint_runner(target: str) -> _CheckpointRunner:
    """Build a runner exactly as cli.py's ``_run_single_checkpoint`` does:
    scope pinned to ``checkpoint:{target}`` and the matcher wired to the
    real ``registry.matches`` so family / wildcard / exact-dynamic target
    resolution is exercised for real."""
    return _CheckpointRunner(
        scope=f"checkpoint:{target}",
        _target_matcher=lambda cid: registry.matches(target, cid),
    )


def _full_runner() -> _CheckpointRunner:
    return _CheckpointRunner(scope="full", _target_matcher=None)


class TestInteractivePromptsAllowed:
    """Unit tests for the gate predicate itself."""

    def test_full_run_allows_prompt(self) -> None:
        from flightcheck.checks.workday import _interactive_workday_prompts_allowed

        assert _interactive_workday_prompts_allowed(_full_runner()) is True

    def test_minimal_runner_without_matcher_attr_allows_prompt(self) -> None:
        """Legacy minimal runners in other tests have neither
        ``_target_matcher`` nor ``scope``; ``getattr`` defaults keep the
        legacy prompt-allowed behavior for them."""
        from flightcheck.checks.workday import _interactive_workday_prompts_allowed

        class _Bare:
            pass

        assert _interactive_workday_prompts_allowed(_Bare()) is True

    def test_wd_pkg_001_checkpoint_suppresses_prompt(self) -> None:
        from flightcheck.checks.workday import _interactive_workday_prompts_allowed

        assert _interactive_workday_prompts_allowed(
            _checkpoint_runner("WD-PKG-001")
        ) is False

    def test_unrelated_checkpoint_suppresses_prompt(self) -> None:
        from flightcheck.checks.workday import _interactive_workday_prompts_allowed

        assert _interactive_workday_prompts_allowed(
            _checkpoint_runner("WD-ENV-001")
        ) is False

    @pytest.mark.parametrize(
        "target",
        ["WD-WF", "WD-WF-*", "WD-WF-000", "WD-WF-005"],
    )
    def test_workflow_family_targets_allow_prompt(self, target: str) -> None:
        """The WD-WF family is the only directly-targetable runtime-input
        consumer, so every addressable form of it — bare family key,
        wildcard, and exact-dynamic member — must keep the prompt."""
        from flightcheck.checks.workday import _interactive_workday_prompts_allowed

        assert _interactive_workday_prompts_allowed(
            _checkpoint_runner(target)
        ) is True


class TestEmployeeIdPromptGating:
    """The employee-ID prompt in ``_resolve_workday_metadata`` respects
    the gate."""

    @pytest.fixture(autouse=True)
    def _isolate_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
        monkeypatch.delenv("WORKDAY_TENANT", raising=False)
        monkeypatch.delenv("WORKDAY_TEST_EMPLOYEE_ID", raising=False)
        monkeypatch.chdir(tmp_path)
        # Pretend we're on an interactive TTY so only the gate — not the
        # isatty guard — decides whether the prompt fires.
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def _install_input_spy(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []

        def _fake_input(prompt: str = "") -> str:
            calls.append(prompt)
            return "21508"

        monkeypatch.setattr("builtins.input", _fake_input)
        # Avoid touching disk when the prompt does fire + returns a value.
        monkeypatch.setattr(
            "flightcheck.checks.workday._cache_test_employee_id",
            lambda _v: None,
        )
        return calls

    def test_wd_pkg_001_does_not_prompt_for_employee_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.workday import _resolve_workday_metadata

        calls = self._install_input_spy(monkeypatch)
        _, _, test_employee = _resolve_workday_metadata(
            _checkpoint_runner("WD-PKG-001")
        )

        assert calls == []
        assert test_employee == ""

    def test_wd_wf_checkpoint_still_prompts_for_employee_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.workday import _resolve_workday_metadata

        calls = self._install_input_spy(monkeypatch)
        _, _, test_employee = _resolve_workday_metadata(
            _checkpoint_runner("WD-WF")
        )

        assert len(calls) == 1
        assert "Test Employee ID" in calls[0]
        assert test_employee == "21508"

    def test_full_run_still_prompts_for_employee_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.workday import _resolve_workday_metadata

        calls = self._install_input_spy(monkeypatch)
        _, _, test_employee = _resolve_workday_metadata(_full_runner())

        assert len(calls) == 1
        assert test_employee == "21508"


class TestIsuCredentialPromptGating:
    """The ISU username/password prompt in ``_resolve_workday_credentials``
    respects the gate — important because when the employee ID comes from
    env/config the metadata prompt is skipped but the credential prompt
    would otherwise still block a WD-PKG-001 hydration run."""

    @pytest.fixture(autouse=True)
    def _isolate_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WORKDAY_USERNAME", raising=False)
        monkeypatch.delenv("WORKDAY_PASSWORD", raising=False)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def _install_cred_spies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[list[str], list[str]]:
        inputs: list[str] = []
        getpasses: list[str] = []

        def _fake_input(prompt: str = "") -> str:
            inputs.append(prompt)
            return "isu_flightcheck"

        def _fake_getpass(prompt: str = "") -> str:
            getpasses.append(prompt)
            return "secret"

        monkeypatch.setattr("builtins.input", _fake_input)
        monkeypatch.setattr("getpass.getpass", _fake_getpass)
        return inputs, getpasses

    def test_wd_pkg_001_does_not_prompt_for_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.workday import _resolve_workday_credentials

        inputs, getpasses = self._install_cred_spies(monkeypatch)
        username, password = _resolve_workday_credentials(
            _checkpoint_runner("WD-PKG-001"), "mocktenant"
        )

        assert inputs == []
        assert getpasses == []
        assert username == ""
        assert password == ""

    def test_wd_wf_checkpoint_still_prompts_for_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.workday import _resolve_workday_credentials

        inputs, getpasses = self._install_cred_spies(monkeypatch)
        username, password = _resolve_workday_credentials(
            _checkpoint_runner("WD-WF"), "mocktenant"
        )

        assert len(inputs) == 1
        assert len(getpasses) == 1
        # Tenant suffix appended by concatenation (never logged).
        assert username == "isu_flightcheck@mocktenant"
        assert password == "secret"
