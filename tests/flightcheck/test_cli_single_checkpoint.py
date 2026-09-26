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
import json
from pathlib import Path

import pytest

from flightcheck import cli, registry
from flightcheck.runner import CheckResult, Priority, Status


def _args(
    checkpoint: str,
    tmp_path: Path,
    environment_url: str | None = None,
    environment_id: str | None = None,
    connect_config: str | None = None,
    agent_slug: str | None = None,
    no_telemetry: bool = True,
    invocation_source: str | None = None,
    quiet_auth: bool = False,
    ring: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        checkpoint=checkpoint,
        environment_url=environment_url,
        environment_id=environment_id,
        connect_config=connect_config,
        agent_slug=agent_slug,
        output=str(tmp_path / "out"),
        no_telemetry=no_telemetry,
        invocation_source=invocation_source,
        quiet_auth=quiet_auth,
        ring=ring,
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


@pytest.mark.parametrize(
    ("config", "explicit_ring", "expected"),
    [
        ({}, "test", "test"),
        (
            {
                "ring": "preprod",
                "powerPlatformApiEndpoint": (
                    "https://0000000000000000000000000000000.0."
                    "environment.api.preprod.powerplatform.com"
                ),
            },
            None,
            "preprod",
        ),
    ],
)
def test_resolve_environment_ring(
    config: dict,
    explicit_ring: str | None,
    expected: str,
) -> None:
    assert (
        cli._resolve_environment_ring(
            config,
            explicit_ring=explicit_ring,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("config", "explicit_ring", "message"),
    [
        ({}, None, "ring is unavailable"),
        (
            {
                "ring": "prod",
                "powerPlatformApiEndpoint": (
                    "https://0000000000000000000000000000000.0."
                    "environment.api.test.powerplatform.com"
                ),
            },
            None,
            "do not identify the same",
        ),
    ],
)
def test_resolve_environment_ring_rejects_inconclusive_state(
    config: dict,
    explicit_ring: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        cli._resolve_environment_ring(
            config,
            explicit_ring=explicit_ring,
        )


@pytest.fixture
def _silence_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the summary printer and results writer so the run-reaching tests
    stay hermetic (no report.html / results.json on disk, no console output
    coupled to report internals)."""
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *a, **k: None)
    monkeypatch.setattr(cli, "save_results", lambda *a, **k: None)


class TestGates:
    def test_connect_config_overlay_preserves_foundation_identity(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text(
            '{"entraAppId":"app-123","tenant":"acme","status":"in-progress"}',
            encoding="utf-8",
        )

        merged = cli._merge_connect_config(
            {
                "dataverseEndpoint": "https://example.crm.dynamics.com",
                "agent": {"slug": "ess-hr"},
                "status": "complete",
            },
            str(overlay),
        )

        assert merged["dataverseEndpoint"] == "https://example.crm.dynamics.com"
        assert merged["agent"] == {"slug": "ess-hr"}
        assert merged["entraAppId"] == "app-123"
        assert merged["tenant"] == "acme"
        assert merged["status"] == "complete"
        assert merged["_connectConfigPath"] == str(overlay)

    def test_connect_config_overlay_preserves_foundation_connections(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text(
            '{"connections":{"Workday":{"tenant":"wrong"}}}',
            encoding="utf-8",
        )

        merged = cli._merge_connect_config(
            {"connections": {"Workday": {"tenant": "foundation"}}},
            str(overlay),
        )

        assert merged["connections"]["Workday"]["tenant"] == "foundation"

    def test_connect_config_only_merges_provider_owned_fields(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text(
            json.dumps({
                "tenant": "provider-tenant",
                "releaseLine": "legacy",
                "powerPlatformApiEndpoint": "https://wrong.example",
                "workdayProbe": {"url": "https://wrong.example"},
            }),
            encoding="utf-8",
        )

        merged = cli._merge_connect_config(
            {
                "releaseLine": "da",
                "powerPlatformApiEndpoint": "https://api.powerplatform.com",
                "workdayProbe": {"url": "https://foundation.example"},
            },
            str(overlay),
        )

        assert merged["tenant"] == "provider-tenant"
        assert merged["releaseLine"] == "da"
        assert (
            merged["powerPlatformApiEndpoint"]
            == "https://api.powerplatform.com"
        )
        assert merged["workdayProbe"] == {
            "url": "https://foundation.example"
        }

    def test_connect_config_flattens_v2_workday_state(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "scope": {
                        "workdayTenant": "acme_impl",
                        "entraTenantId": "tenant-id",
                        "dataverseUrl": "https://acme.crm.dynamics.com",
                    },
                    "identifiers": {
                        "entraAppId": "app-id",
                        "entraAppIdUri": "api://app-id",
                        "workdaySamlEntityId": (
                            "http://www.workday.com/acme_impl"
                        ),
                    },
                    "endpoints": {
                        "restBaseUrl": (
                            "https://wd2-impl-services1.workday.com/ccx/api"
                        )
                    },
                }
            ),
            encoding="utf-8",
        )

        merged = cli._merge_connect_config({}, str(overlay))

        assert merged["tenant"] == "acme_impl"
        assert merged["tenantId"] == "tenant-id"
        assert merged["dataverseEndpoint"] == (
            "https://acme.crm.dynamics.com"
        )
        assert merged["entraAppId"] == "app-id"
        assert merged["appIdUri"] == "api://app-id"
        assert merged["workdaySamlEntityId"] == (
            "http://www.workday.com/acme_impl"
        )

    @pytest.mark.parametrize(
        "agent_slug",
            (
                ".",
                "..",
                "../other-agent",
                r"..\other-agent",
                "/tmp/agent",
                "C:other-agent",
                "other agent",
            ),
    )
    def test_single_checkpoint_rejects_unsafe_explicit_agent_slug(
        self,
        tmp_path: Path,
        agent_slug: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args("FAKE-001", tmp_path, agent_slug=agent_slug)
            )

        assert exc.value.code == 2
        assert "ERROR: Invalid --agent-slug:" in capsys.readouterr().out

    def test_connect_config_supplies_sidecar_dataverse(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text(
            '{"sidecarDataverseEndpoint":'
            '"https://sidecar.crm.dynamics.com"}',
            encoding="utf-8",
        )

        merged = cli._merge_connect_config(
            {"powerPlatformApiEndpoint": "https://api.powerplatform.com"},
            str(overlay),
        )

        assert (
            merged["dataverseEndpoint"]
            == "https://sidecar.crm.dynamics.com"
        )
        assert (
            merged["powerPlatformApiEndpoint"]
            == "https://api.powerplatform.com"
        )

    def test_foundation_dataverse_wins_over_sidecar(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text(
            '{"sidecarDataverseEndpoint":'
            '"https://sidecar.crm.dynamics.com"}',
            encoding="utf-8",
        )

        merged = cli._merge_connect_config(
            {"dataverseEndpoint": "https://foundation.crm.dynamics.com"},
            str(overlay),
        )

        assert (
            merged["dataverseEndpoint"]
            == "https://foundation.crm.dynamics.com"
        )

    def test_connect_config_overlay_rejects_non_object(
        self, tmp_path: Path
    ) -> None:
        overlay = tmp_path / "invalid.json"
        overlay.write_text('["not", "an", "object"]', encoding="utf-8")

        with pytest.raises(ValueError, match="must contain a JSON object"):
            cli._merge_connect_config({}, str(overlay))

    def test_environment_checkpoints_accept_explicit_foundation_context(
        self,
    ) -> None:
        for checkpoint in (
            "ENV-001",
            "ENV-002",
            "ENV-009",
        ):
            plan = registry.transitive_requirements(checkpoint)
            assert plan.requires_config is False
            assert plan.requires_dataverse_endpoint is True

        capacity = registry.transitive_requirements("ENV-CAPACITY-001")
        assert capacity.requires_config is False
        assert capacity.requires_dataverse_endpoint is False

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

    def test_capacity_uses_explicit_environment_id_without_dataverse(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)

        class _PowerPlatform:
            def __init__(self, tenant_id: str) -> None:
                assert tenant_id == "organizations"

            def authenticate(self) -> str:
                return "token"

            def get_currency_allocations(self, environment_id: str):
                assert (
                    environment_id
                    == "00000000-0000-4000-8000-000000001111"
                )
                return [{"currencyType": "MCSMessages", "allocated": 100}]

        monkeypatch.setattr(cli, "PowerPlatformClient", _PowerPlatform)

        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args(
                    "ENV-CAPACITY-001",
                    tmp_path,
                    environment_id=(
                        "00000000-0000-4000-8000-000000001111"
                    ),
                    ring="prod",
                )
            )

        assert exc.value.code == 0

    def test_capacity_uses_native_config_environment_id_without_dataverse(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        local_dir = tmp_path / ".local"
        local_dir.mkdir()
        (local_dir / "config.json").write_text(
            json.dumps(
                {
                    "releaseLine": "da",
                    "environmentId": (
                        "00000000-0000-4000-8000-000000001111"
                    ),
                    "ring": "test",
                    "powerPlatformApiEndpoint": (
                        "https://0000000000000000000000000000000.0."
                        "environment.api.test.powerplatform.com"
                    ),
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        class _PowerPlatform:
            def __init__(self, tenant_id: str) -> None:
                assert tenant_id == "organizations"

            def authenticate(self) -> str:
                return "token"

            def get_currency_allocations(self, environment_id: str):
                assert (
                    environment_id
                    == "00000000-0000-4000-8000-000000001111"
                )
                return [{"currencyType": "MCSMessages", "allocated": 100}]

        monkeypatch.setattr(cli, "PowerPlatformClient", _PowerPlatform)

        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args("ENV-CAPACITY-001", tmp_path)
            )

        assert exc.value.code == 0

    def test_capacity_requires_ring_when_setup_state_is_inconclusive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            cli,
            "PowerPlatformClient",
            lambda _tenant_id: pytest.fail(
                "ring validation must complete before authentication"
            ),
        )

        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args(
                    "ENV-CAPACITY-001",
                    tmp_path,
                    environment_id=(
                        "00000000-0000-4000-8000-000000001111"
                    ),
                )
            )

        assert exc.value.code == 1
        assert "Confirm whether the environment uses" in capsys.readouterr().out


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

    def test_assigns_explicit_agent_slug_and_connect_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _silence_output: None,
    ) -> None:
        overlay = tmp_path / "provider.json"
        overlay.write_text('{"tenant":"acme"}', encoding="utf-8")
        captured = {}

        class _Spec:
            category_label = "Fake"
            is_family = False

        class _Plan:
            clients = frozenset()
            requires_config = False
            requires_dataverse_endpoint = False

            def __init__(self) -> None:
                self.ordered_fns = [("Fake", self._fn)]

            @staticmethod
            def _fn(runner):
                captured["agent_slug"] = runner.agent_slug
                captured["config"] = runner.config
                return [_row("FAKE-001", Status.PASSED.value)]

        monkeypatch.setattr(registry, "resolve", lambda target: _Spec())
        monkeypatch.setattr(
            registry, "transitive_requirements", lambda target: _Plan()
        )
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc:
            cli._run_single_checkpoint(
                _args(
                    "FAKE-001",
                    tmp_path,
                    connect_config=str(overlay),
                    agent_slug="active-agent",
                )
            )

        assert exc.value.code == 0
        assert captured["agent_slug"] == "active-agent"
        assert captured["config"]["tenant"] == "acme"
        assert captured["config"]["_connectConfigPath"] == str(overlay)

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


class TestCheckpointAdkConnector:
    """Single-checkpoint runs on the CLI runtime path must derive the
    connector from the owning check's category and forward it to the ADK
    ``emit_flightcheck_run`` / ``emit_flightcheck_result`` calls (ADO 7943641
    review, finding 1). Without this, only the legacy
    ``ESSMakerKit.FlightCheck.*`` events were attributed and the ADK
    ``adk.flightcheck.*`` event family emitted an empty connector for real
    runs even though the standalone helper tests exercised the kwarg.
    """

    @staticmethod
    def _row_with_category(
        checkpoint_id: str, category: str, status: str = Status.PASSED.value
    ) -> CheckResult:
        return CheckResult(
            checkpoint_id=checkpoint_id,
            category=category,
            priority=Priority.MEDIUM.value,
            status=status,
            description="fake",
            result="fake",
        )

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> dict:
        from flightcheck import telemetry as _tele_mod
        import adk_telemetry as _adk_mod

        captured: dict = {"run_kwargs": None, "result_kwargs": None}

        def _fake_run(**kwargs):
            captured["run_kwargs"] = kwargs

        def _fake_result(**kwargs):
            captured["result_kwargs"] = kwargs

        monkeypatch.setattr(
            _tele_mod,
            "emit_flightcheck_telemetry",
            lambda *_a, **_k: {"sent": False, "events": 0, "status": None,
                               "env": "dev", "reason": "test"},
        )
        monkeypatch.setattr(_adk_mod, "set_identity", lambda *a, **k: None)
        monkeypatch.setattr(_adk_mod, "next_run_index", lambda *a, **k: 1)
        monkeypatch.setattr(_adk_mod, "emit_flightcheck_run", _fake_run)
        monkeypatch.setattr(_adk_mod, "emit_flightcheck_result", _fake_result)
        monkeypatch.setattr(_adk_mod, "flush", lambda *a, **k: None)
        return captured

    def test_workday_category_row_forwards_workday_connector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        TestHermeticRun._install_fake_plan(
            monkeypatch, [self._row_with_category("WD-CFG-001", "Workday")],
        )
        captured = self._capture(monkeypatch)
        with pytest.raises(SystemExit):
            cli._run_single_checkpoint(_args("WD-CFG-001", tmp_path, no_telemetry=False))
        assert captured["run_kwargs"] is not None
        assert captured["run_kwargs"]["connector"] == "workday"
        assert captured["result_kwargs"]["connector"] == "workday"

    def test_servicenow_subcategory_row_forwards_servicenow_connector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        TestHermeticRun._install_fake_plan(
            monkeypatch, [self._row_with_category("SN-HRSD-001", "ServiceNow HRSD")],
        )
        captured = self._capture(monkeypatch)
        with pytest.raises(SystemExit):
            cli._run_single_checkpoint(_args("SN-HRSD-001", tmp_path, no_telemetry=False))
        assert captured["run_kwargs"]["connector"] == "servicenow"
        assert captured["result_kwargs"]["connector"] == "servicenow"

    def test_cross_cutting_category_row_forwards_empty_connector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _silence_output: None,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        TestHermeticRun._install_fake_plan(
            monkeypatch, [self._row_with_category("ENV-001", "Environment")],
        )
        captured = self._capture(monkeypatch)
        with pytest.raises(SystemExit):
            cli._run_single_checkpoint(_args("ENV-001", tmp_path, no_telemetry=False))
        assert captured["run_kwargs"]["connector"] == ""
        assert captured["result_kwargs"]["connector"] == ""
