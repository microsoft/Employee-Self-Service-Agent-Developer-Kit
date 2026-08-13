# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for ``cli._run_single_checkpoint`` branch / exit-code logic.

Pure-logic tests (no network) — the cardinal cassette rule in
``tests/AGENTS.md`` excludes "tests of the kit's pure-logic helpers (no
network)". The three gate paths (unknown id, missing config, missing
Dataverse endpoint) all ``sys.exit()`` BEFORE any client auth, so they run
against the real registry with no network. The two paths that reach
``runner.run()`` are made hermetic by monkeypatching the registry to hand
back a fake plan whose client set is EMPTY, so no client is ever
constructed and no auth is attempted.

Contracts pinned:
  * unknown checkpoint id                     -> SystemExit code 2
  * requires_config, no ``.local/config.json`` -> SystemExit code 1
  * requires_dataverse_endpoint, no endpoint  -> SystemExit code 1
  * plan producing a PASSED row               -> SystemExit code 0
  * plan producing a FAILED row               -> SystemExit code 1
  * plan producing an ERROR row                -> SystemExit code 1
  * exact checkpoint producing no row          -> SystemExit code 1
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from flightcheck import cli, registry
from flightcheck.runner import CheckResult, Priority, Status


def _args(
    checkpoint: str,
    tmp_path: Path,
    environment_url: str | None = None,
    no_telemetry: bool = True,
    invocation_source: str | None = None,
    quiet_auth: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        checkpoint=checkpoint,
        environment_url=environment_url,
        environment_id=None,
        output=str(tmp_path / "out"),
        no_telemetry=no_telemetry,
        invocation_source=invocation_source,
        quiet_auth=quiet_auth,
    )


def _row(checkpoint_id: str, status: str) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category="Fake",
        priority=Priority.MEDIUM.value,
        status=status,
        description="fake",
        result="fake",
    )


@pytest.fixture
def _silence_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the summary printer and results writer so the run-reaching tests
    stay hermetic (no report.html / results.json on disk, no console output
    coupled to report internals)."""
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *a, **k: None)
    monkeypatch.setattr(cli, "save_results", lambda *a, **k: None)


class TestGates:
    def test_environment_checkpoints_accept_explicit_foundation_context(
        self,
    ) -> None:
        for checkpoint in (
            "ENV-001",
            "ENV-002",
            "ENV-009",
            "ENV-CAPACITY-001",
        ):
            plan = registry.transitive_requirements(checkpoint)
            assert plan.requires_config is False
            assert plan.requires_dataverse_endpoint is True

    def test_unknown_checkpoint_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert registry.resolve("DEFINITELY-NOT-A-REAL-ID-ZZZ") is None
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("DEFINITELY-NOT-A-REAL-ID-ZZZ", tmp_path))
        assert exc.value.code == 2

    def test_missing_config_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ESS-SOLN-001 requires config; with no .local/config.json present the
        # per-checkpoint config gate fires before any client auth.
        plan = registry.transitive_requirements("ESS-SOLN-001")
        assert plan.requires_config, "test assumes ESS-SOLN-001 requires config"
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / ".local" / "config.json").exists()
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("ESS-SOLN-001", tmp_path))
        assert exc.value.code == 1

    def test_missing_dataverse_endpoint_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Config present (so the config gate passes) but no dataverseEndpoint,
        # and ESS-SOLN-001 requires one -> the endpoint gate fires, still
        # before any auth.
        plan = registry.transitive_requirements("ESS-SOLN-001")
        assert plan.requires_dataverse_endpoint, (
            "test assumes ESS-SOLN-001 requires a Dataverse endpoint"
        )
        local = tmp_path / ".local"
        local.mkdir()
        (local / "config.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("ESS-SOLN-001", tmp_path))
        assert exc.value.code == 1


class TestHermeticRun:
    """Reaches ``runner.run()`` with an empty client set — no network."""

    @staticmethod
    def _install_fake_plan(
        monkeypatch: pytest.MonkeyPatch, rows: list[CheckResult]
    ) -> None:
        class _Spec:
            category_label = "Fake"
            is_family = False

        class _Plan:
            clients = frozenset()
            requires_config = False
            requires_dataverse_endpoint = False

            def __init__(self, fns: list) -> None:
                self.ordered_fns = fns

        def _fn(runner):  # noqa: ARG001 — runner arg is the check-fn contract
            return list(rows)

        monkeypatch.setattr(registry, "resolve", lambda target: _Spec())
        monkeypatch.setattr(
            registry,
            "transitive_requirements",
            lambda target: _Plan([("Fake", _fn)]),
        )

    def test_passed_row_exits_0(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._install_fake_plan(monkeypatch, [_row("FAKE-001", Status.PASSED.value)])
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("FAKE-001", tmp_path))
        assert exc.value.code == 0

    def test_failed_row_exits_1(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._install_fake_plan(monkeypatch, [_row("FAKE-001", Status.FAILED.value)])
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("FAKE-001", tmp_path))
        assert exc.value.code == 1

    def test_error_row_exits_1(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._install_fake_plan(
            monkeypatch,
            [_row("FAKE-ERR", Status.ERROR.value)],
        )
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("FAKE-ERR", tmp_path))
        assert exc.value.code == 1

    def test_exact_checkpoint_without_result_exits_1(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._install_fake_plan(monkeypatch, [])
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(_args("FAKE-EMPTY", tmp_path))
        assert exc.value.code == 1

    def test_quiet_auth_suppresses_routine_checkpoint_chatter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._install_fake_plan(
            monkeypatch,
            [_row("FAKE-001", Status.PASSED.value)],
        )

        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args("FAKE-001", tmp_path, quiet_auth=True)
            )

        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert "Single Checkpoint" not in output
        assert "Running checkpoint" not in output


class TestCheckpointTelemetry:
    """Single-checkpoint runs emit outcome telemetry attributed to the
    ``connect`` invocation source with a ``checkpoint:<ID>`` scope (ADO
    7587431). The emit is best-effort and never affects the exit code.
    """

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> dict:
        """Stub both telemetry families and capture the kwargs passed to the
        legacy ``emit_flightcheck_telemetry`` call. Returns a dict that is
        populated with ``called`` / ``kwargs`` once the emit runs."""
        from flightcheck import telemetry as _tele_mod
        import adk_telemetry as _adk_mod

        captured: dict = {"called": False, "kwargs": None}

        def _fake_emit(run_result, **kwargs):  # noqa: ARG001
            captured["called"] = True
            captured["kwargs"] = kwargs
            return {"sent": False, "events": 0, "status": None, "env": "dev", "reason": "test"}

        monkeypatch.setattr(_tele_mod, "emit_flightcheck_telemetry", _fake_emit)
        # Neutralise the adk.* family so no network / real identity is touched.
        monkeypatch.setattr(_adk_mod, "set_identity", lambda *a, **k: None)
        monkeypatch.setattr(_adk_mod, "next_run_index", lambda *a, **k: 1)
        monkeypatch.setattr(_adk_mod, "emit_flightcheck_run", lambda *a, **k: None)
        monkeypatch.setattr(_adk_mod, "emit_flightcheck_result", lambda *a, **k: None)
        monkeypatch.setattr(_adk_mod, "flush", lambda *a, **k: None)
        return captured

    def test_emits_connect_source_and_checkpoint_scope(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        TestHermeticRun._install_fake_plan(
            monkeypatch, [_row("WD-ENTRA-CONSENT-001", Status.PASSED.value)]
        )
        captured = self._capture(monkeypatch)
        # no_telemetry=False reaches the emit; invocation_source unset -> connect.
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args("WD-ENTRA-CONSENT-001", tmp_path, no_telemetry=False)
            )
        assert exc.value.code == 0
        assert captured["called"] is True
        assert captured["kwargs"]["invocation_source"] == "connect"
        assert captured["kwargs"]["scope"] == "checkpoint:WD-ENTRA-CONSENT-001"

    def test_explicit_invocation_source_wins(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        TestHermeticRun._install_fake_plan(
            monkeypatch, [_row("FAKE-001", Status.PASSED.value)]
        )
        captured = self._capture(monkeypatch)
        with pytest.raises(SystemExit):
            cli._run_single_checkpoint(
                _args("FAKE-001", tmp_path, no_telemetry=False, invocation_source="adk")
            )
        assert captured["kwargs"]["invocation_source"] == "adk"

    def test_no_telemetry_flag_suppresses_emit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        TestHermeticRun._install_fake_plan(
            monkeypatch, [_row("FAKE-001", Status.PASSED.value)]
        )
        captured = self._capture(monkeypatch)
        with pytest.raises(SystemExit):
            cli._run_single_checkpoint(
                _args("FAKE-001", tmp_path, no_telemetry=True)
            )
        assert captured["called"] is False

    def test_tenant_name_falls_back_to_cache_when_graph_unavailable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        """When ``graph is None`` (infra-only scope, or Graph auth failed),
        ``cli`` must fall back to the persisted ``.local/.tenant_name`` cache
        so previously-resolved tenants keep their name on FlightCheck events
        instead of emitting blank. Regression guard for the split observed in
        prod telemetry where the same tenant emitted both blank and named
        runs on the same ADK version.
        """
        monkeypatch.chdir(tmp_path)
        from flightcheck import telemetry as _tele_mod
        from flightcheck import registry as _reg

        cached_tid = "11111111-1111-1111-1111-111111111111"
        _tele_mod.cache_tenant_name(cached_tid, "Contoso Cached")

        # Make the plan require GRAPH so the code reaches the tenant_id
        # discovery path and then tries to build a Graph client.
        class _Spec:
            category_label = "Fake"
            is_family = False

        class _Plan:
            clients = frozenset({_reg.GRAPH})
            requires_config = False
            requires_dataverse_endpoint = False

            def __init__(self, fns: list) -> None:
                self.ordered_fns = fns

        def _fn(runner):  # noqa: ARG001
            return [_row("FAKE-001", Status.PASSED.value)]

        monkeypatch.setattr(_reg, "resolve", lambda target: _Spec())
        monkeypatch.setattr(
            _reg, "transitive_requirements", lambda target: _Plan([("Fake", _fn)])
        )

        # Force tenant_id to our seeded cache key and make Graph fail so the
        # code sets ``graph = None`` — the exact scenario we're guarding.
        import auth as _auth

        monkeypatch.setattr(_auth, "discover_tenant", lambda *a, **k: cached_tid)

        class _NoGraph:
            def __init__(self, *a, **k):
                pass

            def authenticate(self):
                raise RuntimeError("no graph in this test")

            def get_organization(self):
                raise RuntimeError("no graph in this test")

        monkeypatch.setattr(cli, "GraphClient", _NoGraph, raising=False)
        import flightcheck.graph_client as _gc

        monkeypatch.setattr(_gc, "GraphClient", _NoGraph)

        captured = self._capture(monkeypatch)
        with pytest.raises(SystemExit):
            cli._run_single_checkpoint(
                _args(
                    "FAKE-001",
                    tmp_path,
                    no_telemetry=False,
                    environment_url="https://contoso.crm.dynamics.com",
                )
            )
        assert captured["called"] is True
        # Regression assertion: with graph unavailable, the cache must be
        # consulted so a previously-seen tenant still gets its display name.
        assert captured["kwargs"]["tenant_name"] == "Contoso Cached"
        assert captured["kwargs"]["tenant_id"] == cached_tid
