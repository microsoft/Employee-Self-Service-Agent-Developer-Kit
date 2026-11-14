# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Write-destination tests for scripts/discover_inventory.py.

Persisting to the WeveNova Inventory API is the *point* of a discovery pass, so it is
the default and ``--local-only`` is the explicit opt-out. The failure mode that matters
is a run reporting ``"status": "ok"`` while having persisted nothing -- an operator
would believe their tenant inventory was updated. So the rules pinned here are:

* the default resolves to the live service, not to a local mirror;
* a live path that cannot be used **degrades loudly** (reason recorded, exit 2) rather
  than aborting the crawl or silently succeeding;
* ``--local-only`` conflicts with an *explicit* base URL, but not with the built-in
  default, which carries no user intent.

Pure-logic tests: no network, no Dataverse, no crawl. Per tests/AGENTS.md the cassette
rule does not apply to the kit's pure-logic helpers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_CRAWLER_SRC = os.path.join(_REPO_ROOT, "tools", "tenant-inventory-discovery", "src")
if _CRAWLER_SRC not in sys.path:
    sys.path.insert(0, _CRAWLER_SRC)

import discover_inventory as di  # noqa: E402  (pythonpath adds scripts/)

from tenant_inventory_discovery.config import (  # noqa: E402
    DEFAULT_INVENTORY_BASE_URL,
    ENV_ACCESS_TOKEN,
    ENV_BASE_URL,
    DiscoveryConfig,
)

_HOST = "https://inventory.example.test"


def _args(*, base_url=None, local_only=False):
    return argparse.Namespace(base_url=base_url, local_only=local_only)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """The resolver reads the environment, so never inherit the developer's shell."""
    monkeypatch.delenv(ENV_BASE_URL, raising=False)
    monkeypatch.delenv(ENV_ACCESS_TOKEN, raising=False)


class TestResolveWriteMode:
    def test_default_is_the_live_write_path(self):
        """No flags means persist. Discovery exists to update the inventory."""
        base_url, local_only = di._resolve_write_mode(_args())
        assert local_only is False
        assert base_url == DEFAULT_INVENTORY_BASE_URL

    def test_both_flags_conflict(self):
        with pytest.raises(SystemExit, match="conflicts"):
            di._resolve_write_mode(_args(base_url=_HOST, local_only=True))

    def test_local_only_selects_the_no_write_path(self):
        """The built-in default is not user intent, so --local-only must still work.

        If the default origin were treated like an explicit --base-url, plain
        ``--local-only`` would always raise a conflict and the opt-out would be dead.
        """
        base_url, local_only = di._resolve_write_mode(_args(local_only=True))
        assert local_only is True
        assert base_url is None

    def test_base_url_overrides_the_default(self):
        base_url, local_only = di._resolve_write_mode(_args(base_url=_HOST))
        assert base_url == _HOST
        assert local_only is False

    def test_env_var_overrides_the_default(self, monkeypatch):
        monkeypatch.setenv(ENV_BASE_URL, _HOST)
        base_url, local_only = di._resolve_write_mode(_args())
        assert base_url == _HOST
        assert local_only is False

    def test_explicit_flag_wins_over_the_env_var(self, monkeypatch):
        monkeypatch.setenv(ENV_BASE_URL, "https://stale.example.test")
        base_url, _ = di._resolve_write_mode(_args(base_url=_HOST))
        assert base_url == _HOST

    def test_env_var_still_conflicts_with_local_only(self, monkeypatch):
        """An inherited env var must not be silently overridden by --local-only.

        Exporting WEVENOVA_BASE_URL is a deliberate act, so honouring --local-only
        without comment would hide a real disagreement about where writes should go.
        """
        monkeypatch.setenv(ENV_BASE_URL, _HOST)
        with pytest.raises(SystemExit) as exc:
            di._resolve_write_mode(_args(local_only=True))
        # The message has to say where the base URL came from, or it looks like a bug.
        assert ENV_BASE_URL in str(exc.value)


class TestBuildInventoryClient:
    def test_local_only_builds_the_in_memory_client(self):
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        client, label, degraded = di._build_inventory_client(
            True, "contoso", DiscoveryConfig()
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        # An explicit opt-out is not a failure, so nothing should be reported.
        assert degraded is None

    def test_in_memory_client_inherits_the_configured_caps(self):
        """The opt-out must enforce the same caps, or it validates nothing useful."""
        config = DiscoveryConfig()
        client, _, _ = di._build_inventory_client(True, "contoso", config)
        assert client.caps is config.caps


class TestTlsHint:
    """A dev tunnel serves a self-signed cert; httpx rejects what Insomnia accepts.

    httpx validates against certifi, PowerShell and Insomnia against the Windows
    certificate store. Without a hint this reads as "the API is broken" when it is
    really a trust-store difference, so the remediation is named explicitly.
    """

    def test_certificate_failure_names_the_flag(self):
        hint = di._tls_hint(
            RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate"),
            insecure=False,
        )
        assert "--insecure-skip-tls-verify" in hint

    def test_unrelated_failure_gets_no_hint(self):
        """Suggesting a TLS flag for a 403 would send the user down the wrong path."""
        assert di._tls_hint(RuntimeError("403 Forbidden"), insecure=False) == ""

    def test_no_hint_when_verification_is_already_disabled(self):
        hint = di._tls_hint(
            RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED]"), insecure=True
        )
        assert hint == ""

    def test_probe_failure_surfaces_the_hint(self, monkeypatch):
        # The hint must reach the degrade reason through the MCP write path, which is
        # where a dev-tunnel certificate failure surfaces now.
        _patch_mcp_client(
            monkeypatch,
            probe_error=RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED]"),
        )
        _, _, degraded = di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, _HOST
        )
        assert "--insecure-skip-tls-verify" in degraded


class _StubMcpClient:
    """Stands in for McpInventoryClient; records the child environment it was given."""

    last_env: dict | None = None

    def __init__(self, *, info=None, probe_error=None, start_error=None):
        if start_error is not None:
            raise start_error
        self._info = info if info is not None else {
            "baseUrl": "https://localhost:444/weveb2", "tenantId": "contoso"
        }
        self._probe_error = probe_error
        self.closed = False
        self.probed = False

    def server_info(self):
        return self._info

    def probe(self):
        self.probed = True
        if self._probe_error is not None:
            raise self._probe_error

    def close(self):
        self.closed = True


def _patch_mcp_client(monkeypatch, **kwargs):
    """Install a stub factory and expose both the instance and the env it received."""
    captured = {}

    def _factory(tenant_id, *, server_argv, env=None, **_):
        captured["tenant_id"] = tenant_id
        captured["server_argv"] = server_argv
        captured["env"] = env
        instance = _StubMcpClient(**kwargs)
        captured["instance"] = instance
        return instance

    monkeypatch.setattr(
        "tenant_inventory_discovery.mcp_inventory.McpInventoryClient", _factory
    )
    return captured


class TestBuildMcpClient:
    """The ess-planner MCP server is the only live write path.

    The server owns the token, the origin, and the certificate decision, so the only
    thing the bridge controls is the child's environment. Getting that wrong is not
    loud -- forwarding the bridge's *production* default would silently point a
    developer's MCP run at production -- so the forwarding rules are pinned here.
    """

    def test_success_labels_the_write_path_with_the_servers_target(self, monkeypatch):
        captured = _patch_mcp_client(
            monkeypatch,
            info={"baseUrl": "https://localhost:444/weveb2", "tenantId": "contoso"},
        )
        client, label, degraded = di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, None
        )
        assert client is captured["instance"]
        # Reporting the server's own target, not the bridge's guess, is what makes a
        # run auditable after the fact.
        assert label == "mcp:https://localhost:444/weveb2"
        assert degraded is None

    @pytest.mark.parametrize("tenant", ["another-tenant", None, "", "organizations"])
    def test_an_unverified_mcp_tenant_blocks_access(self, monkeypatch, tenant):
        captured = _patch_mcp_client(
            monkeypatch, info={"baseUrl": _HOST, "tenantId": tenant}
        )
        _, label, degraded = di._build_inventory_client(
            False, "contoso", DiscoveryConfig()
        )
        assert label == "local-only"
        assert "tenant identity mismatch" in degraded
        assert captured["instance"].closed
        assert not captured["instance"].probed

    def test_tenant_comparison_ignores_case_and_surrounding_whitespace(self, monkeypatch):
        captured = _patch_mcp_client(
            monkeypatch, info={"baseUrl": _HOST, "tenantId": " CONTOSO "}
        )
        client, _, degraded = di._build_inventory_client(
            False, "contoso", DiscoveryConfig()
        )
        assert client is captured["instance"]
        assert degraded is None

    def test_an_explicit_base_url_is_forwarded(self, monkeypatch):
        captured = _patch_mcp_client(monkeypatch)
        di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, _HOST
        )
        assert captured["env"][ENV_BASE_URL] == _HOST

    def test_the_production_default_is_not_forwarded(self, monkeypatch):
        """Only user intent may override the server's dev-tunnel default."""
        monkeypatch.setenv(ENV_BASE_URL, "https://leaked.example.test")
        captured = _patch_mcp_client(monkeypatch)
        di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, None
        )
        assert ENV_BASE_URL not in captured["env"]

    def test_the_server_decides_verification_when_no_flag_is_given(self, monkeypatch):
        """The bridge must not force it: only the server knows its effective base URL.

        Forcing ``true`` here made every default run against the dev tunnel fail with
        CERTIFICATE_VERIFY_FAILED, because it overrode the server's loopback rule.
        """
        captured = _patch_mcp_client(monkeypatch)
        monkeypatch.setenv("WEVENOVA_VERIFY_TLS", "true")
        di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, _HOST
        )
        assert "WEVENOVA_VERIFY_TLS" not in captured["env"]

    def test_insecure_flag_forces_the_servers_verification_off(self, monkeypatch):
        captured = _patch_mcp_client(monkeypatch)
        di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), True, _HOST
        )
        assert captured["env"]["WEVENOVA_VERIFY_TLS"] == "false"

    def test_a_server_that_will_not_start_degrades(self, monkeypatch):
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        _patch_mcp_client(monkeypatch, start_error=RuntimeError("no such file"))
        client, label, degraded = di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, _HOST
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert "could not start the WeveNova MCP server" in degraded
        assert "no such file" in degraded

    def test_an_unreachable_api_degrades_and_stops_the_server(self, monkeypatch):
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        captured = _patch_mcp_client(
            monkeypatch, probe_error=RuntimeError("connection refused")
        )
        client, label, degraded = di._build_inventory_client(
            False, "contoso", DiscoveryConfig(), False, _HOST
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert "connection refused" in degraded
        # A leaked subprocess would outlive the run and hold the tunnel open.
        assert captured["instance"].closed is True

    def test_local_only_wins(self, monkeypatch):
        """--local-only is checked first, so the MCP server is never even started."""
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        captured = _patch_mcp_client(monkeypatch)
        client, label, _ = di._build_inventory_client(
            True, "contoso", DiscoveryConfig(), False, None
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert "instance" not in captured


class TestResolveEntraAppId:
    """Find the Entra app id wherever ``/connect`` actually persisted it.

    ``setup/shared/config-schema.md`` documents ``entraAppId`` as a top-level key of
    ``.local/config.json``, but no playbook writes it there -- each connector's
    ``/connect`` flow keeps it in its own file under its own key. Reading only the
    documented location made ``EntraApp`` report **Incomplete** on every run, including
    on tenants that had completed ``/connect``, because the lookup could never succeed.
    FlightCheck hit the same drift (see ``_workday_hints``); these pin the fallback so
    discovery does not silently regress to the documented-but-unwritten key.
    """

    @staticmethod
    def _write(root, *parts, payload):
        import json

        path = os.path.join(str(root), *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_the_documented_top_level_key_is_used_when_present(self, tmp_path):
        assert (
            di._resolve_entra_app_id({"entraAppId": "app-top"}, str(tmp_path))
            == "app-top"
        )

    def test_workday_connect_config_is_read(self, tmp_path):
        self._write(
            tmp_path, "connect", "workday", "config.json",
            payload={"entraAppId": "app-workday"},
        )
        assert di._resolve_entra_app_id({}, str(tmp_path)) == "app-workday"

    def test_servicenow_connect_config_is_read(self, tmp_path):
        # ServiceNow nests it under a different key than Workday.
        self._write(
            tmp_path, "connect", "servicenow", "config.json",
            payload={"entra": {"appClientId": "app-snow"}},
        )
        assert di._resolve_entra_app_id({}, str(tmp_path)) == "app-snow"

    def test_the_documented_key_wins_over_a_connect_config(self, tmp_path):
        self._write(
            tmp_path, "connect", "workday", "config.json",
            payload={"entraAppId": "app-workday"},
        )
        assert (
            di._resolve_entra_app_id({"entraAppId": "app-top"}, str(tmp_path))
            == "app-top"
        )

    def test_nothing_connected_yet_resolves_to_none(self, tmp_path):
        # A legitimate state, not an error: /setup alone never provisions an Entra app.
        assert di._resolve_entra_app_id({}, str(tmp_path)) is None

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_a_blank_value_is_not_a_hit(self, tmp_path, value):
        self._write(
            tmp_path, "connect", "workday", "config.json",
            payload={"entraAppId": value},
        )
        assert di._resolve_entra_app_id({"entraAppId": value}, str(tmp_path)) is None

    def test_a_blank_top_level_key_falls_through_to_connect(self, tmp_path):
        self._write(
            tmp_path, "connect", "servicenow", "config.json",
            payload={"entra": {"appClientId": "app-snow"}},
        )
        assert di._resolve_entra_app_id({"entraAppId": ""}, str(tmp_path)) == "app-snow"

    def test_a_malformed_connect_config_does_not_raise(self, tmp_path):
        path = os.path.join(str(tmp_path), "connect", "workday", "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        # A broken connect config must not take down a crawl of seven other kinds.
        assert di._resolve_entra_app_id({}, str(tmp_path)) is None

    def test_an_unexpected_shape_does_not_raise(self, tmp_path):
        self._write(
            tmp_path, "connect", "servicenow", "config.json",
            payload={"entra": "not-an-object"},
        )
        assert di._resolve_entra_app_id({}, str(tmp_path)) is None

    def test_workday_is_preferred_when_both_connectors_are_configured(self, tmp_path):
        self._write(
            tmp_path, "connect", "workday", "config.json",
            payload={"entraAppId": "app-workday"},
        )
        self._write(
            tmp_path, "connect", "servicenow", "config.json",
            payload={"entra": {"appClientId": "app-snow"}},
        )
        # Deterministic precedence matters: the natural key is the appId, so an
        # unstable pick would create and retire rows on alternating runs.
        assert di._resolve_entra_app_id({}, str(tmp_path)) == "app-workday"


class TestResolveDataverseEndpoint:
    """Find the Dataverse URL of the one environment ``/setup`` configured.

    Classic setup writes ``dataverseEndpoint``; DA setup writes only the Power Platform
    ``environmentId`` and ``ring``. Reading only the classic key ended every DA crawl
    before it started, so the URL is recovered from evidence setup and Workday connect
    already saved -- and only when that evidence names this exact environment.
    """

    _URL = "https://org.crm.dynamics.com"

    @staticmethod
    def _write(root, *parts, payload):
        path = os.path.join(str(root), *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _environment_list(self, root, *records, ring="prod"):
        self._write(
            root, "setup", f"environment-list-{ring}.json",
            payload={"tenantId": "tenant", "ring": ring, "environments": list(records)},
        )

    def _workday_scope(self, root, environment_id, url):
        self._write(
            root, "connect", "workday-da", "config.json",
            payload={"scope": {"environmentId": environment_id, "dataverseUrl": url}},
        )

    def test_the_classic_key_wins(self, tmp_path):
        self._environment_list(
            tmp_path, {"id": "env-1", "url": "https://other.crm.dynamics.com"}
        )
        cfg = {"dataverseEndpoint": f" {self._URL}/ ", "environmentId": "env-1"}
        assert di._resolve_dataverse_endpoint(cfg, str(tmp_path)) == self._URL

    def test_a_da_environment_is_found_in_the_saved_environment_list(self, tmp_path):
        # The list can name the default environment "Default-<guid>", in any case.
        self._environment_list(
            tmp_path,
            {"id": "env-2", "url": "https://other.crm.dynamics.com"},
            {"id": "Default-ENV-1", "url": f"{self._URL}/"},
        )
        cfg = {"environmentId": "env-1", "ring": "prod"}
        assert di._resolve_dataverse_endpoint(cfg, str(tmp_path)) == self._URL

    def test_a_bap_shaped_record_is_read_and_the_ring_defaults_to_prod(self, tmp_path):
        self._environment_list(
            tmp_path,
            {
                "id": "env-1",
                "properties": {"linkedEnvironmentMetadata": {"instanceUrl": self._URL}},
            },
        )
        assert (
            di._resolve_dataverse_endpoint({"environmentId": "env-1"}, str(tmp_path))
            == self._URL
        )

    def test_the_ring_selects_the_environment_list(self, tmp_path):
        self._environment_list(
            tmp_path, {"id": "env-1", "url": "https://prod.crm.dynamics.com"}
        )
        self._environment_list(
            tmp_path, {"id": "env-1", "url": self._URL}, ring="preprod"
        )
        cfg = {"environmentId": "env-1", "ring": "preprod"}
        assert di._resolve_dataverse_endpoint(cfg, str(tmp_path)) == self._URL

    def test_an_unknown_ring_is_not_used_as_a_file_name(self, tmp_path):
        self._environment_list(tmp_path, {"id": "env-1", "url": self._URL}, ring="dev")
        cfg = {"environmentId": "env-1", "ring": "dev"}
        assert di._resolve_dataverse_endpoint(cfg, str(tmp_path)) is None

    @pytest.mark.parametrize(
        "records",
        [
            # DA setup can select an environment that has no Dataverse database.
            pytest.param([{"id": "env-1", "url": ""}], id="no-dataverse-database"),
            pytest.param(
                [
                    {"id": "env-1", "url": "https://org.crm.dynamics.com"},
                    {"id": "Default-env-1", "url": "https://other.crm.dynamics.com"},
                ],
                id="ambiguous",
            ),
            pytest.param(
                [{"id": "env-2", "url": "https://org.crm.dynamics.com"}],
                id="another-environment",
            ),
        ],
    )
    def test_the_list_must_name_one_url_for_this_environment(self, tmp_path, records):
        self._environment_list(tmp_path, *records)
        assert (
            di._resolve_dataverse_endpoint({"environmentId": "env-1"}, str(tmp_path))
            is None
        )

    def test_the_workday_connect_scope_is_used_for_the_same_environment(self, tmp_path):
        self._workday_scope(tmp_path, "ENV-1", f"{self._URL}/")
        assert (
            di._resolve_dataverse_endpoint({"environmentId": "env-1"}, str(tmp_path))
            == self._URL
        )

    def test_a_workday_connect_scope_for_another_environment_is_ignored(self, tmp_path):
        self._workday_scope(tmp_path, "env-2", self._URL)
        assert (
            di._resolve_dataverse_endpoint({"environmentId": "env-1"}, str(tmp_path))
            is None
        )

    def test_blank_evidence_ids_do_not_match_a_missing_environment_id(self, tmp_path):
        self._environment_list(tmp_path, {"id": "", "url": self._URL})
        self._workday_scope(tmp_path, "", self._URL)
        assert di._resolve_dataverse_endpoint({}, str(tmp_path)) is None

    def test_malformed_evidence_does_not_raise(self, tmp_path):
        for parts in (
            ("setup", "environment-list-prod.json"),
            ("connect", "workday-da", "config.json"),
        ):
            path = os.path.join(str(tmp_path), *parts)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ this is not json")
        assert (
            di._resolve_dataverse_endpoint({"environmentId": "env-1"}, str(tmp_path))
            is None
        )

    def test_the_live_crawl_targets_the_da_environment(self, tmp_path, monkeypatch):
        import auth
        from discover_dataverse_platform import DataverseBackedPlatform

        self._environment_list(tmp_path / ".local", {"id": "env-1", "url": self._URL})
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(auth, "load_config", lambda: {"environmentId": "env-1"})

        _platform, environment_id = di._live_platform()

        assert environment_id == DataverseBackedPlatform(self._URL).environment_id

    @pytest.mark.parametrize(
        ("cfg", "named"),
        [({"environmentId": "env-1"}, "env-1"), ({}, "/setup")],
        ids=["da-environment", "no-environment"],
    )
    def test_an_unresolved_url_never_suggests_the_classic_key(
        self, tmp_path, monkeypatch, cfg, named
    ):
        import auth

        # Other skills treat a config carrying 'dataverseEndpoint' as classic
        # (minimalbot_evaluation.is_minimalbot), so a DA maker must not be told to add it.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(auth, "load_config", lambda: cfg)

        with pytest.raises(SystemExit) as excinfo:
            di._live_platform()

        message = str(excinfo.value)
        assert named in message
        assert "dataverseEndpoint" not in message


class TestCapabilityTelemetry:
    """/discover must appear on the ADK "Capability Usage by Type" donut.

    The event is emitted in-process by ``main()`` rather than by a
    ``scripts/emit_capability.py discover`` step in SKILL.md. Both would be
    wrong: ``emit_capability_use()`` does not dedupe, so wiring the shim on top
    of the in-process call double-counts every run. The shim exists for skills
    with no script to hook, and /discover always runs this one.

    It fires right after argparse succeeds, not on a clean exit. The donut
    measures that a maker *used* the capability; gating on success would
    undercount exactly the failed runs worth investigating.
    """

    _ARGV = ["--tenant-id", "demo-tenant", "--demo", "--local-only", "--quiet"]

    def _spy(self, monkeypatch):
        calls = []

        def _record(capability, **kwargs):
            calls.append((capability, kwargs))
            return {"sent": True}

        import adk_telemetry

        monkeypatch.setattr(adk_telemetry, "emit_capability_use", _record)
        return calls

    def test_discover_is_canonical_so_it_cannot_bucket_to_unknown(self):
        # The bug this guards is silent: an out-of-taxonomy value still emits,
        # but lands in the "unknown" slice instead of its own.
        import adk_telemetry

        assert "discover" in adk_telemetry.ADK_CAPABILITIES
        assert adk_telemetry.normalize_capability("discover") == "discover"

    def test_a_run_emits_the_capability_exactly_once(self, tmp_path, monkeypatch):
        calls = self._spy(monkeypatch)
        monkeypatch.chdir(tmp_path)

        assert di.main(list(self._ARGV)) == 0
        assert [capability for capability, _ in calls] == ["discover"]

    def test_the_emit_is_synchronous(self, tmp_path, monkeypatch):
        calls = self._spy(monkeypatch)
        monkeypatch.chdir(tmp_path)
        di.main(list(self._ARGV))

        # A short-lived CLI exits and kills a daemon emit thread before the
        # event leaves the process, so the emit must block.
        assert calls[0][1].get("block") is True

    def test_bad_arguments_do_not_count_as_usage(self, tmp_path, monkeypatch):
        calls = self._spy(monkeypatch)
        monkeypatch.chdir(tmp_path)

        # argparse exits before the emit, so --help and typos stay off the donut.
        with pytest.raises(SystemExit):
            di.main(["--demo"])  # --tenant-id is required
        assert calls == []

    def test_a_telemetry_failure_never_breaks_the_crawl(self, tmp_path, monkeypatch):
        import adk_telemetry

        def _boom(*_args, **_kwargs):
            raise RuntimeError("collector unreachable")

        monkeypatch.setattr(adk_telemetry, "emit_capability_use", _boom)
        monkeypatch.chdir(tmp_path)

        assert di.main(list(self._ARGV)) == 0


class TestUnchangedRerun:
    """A rerun over an unchanged tenant must not empty the results or the mirror.

    The crawler skips the sync when its payload already matches the service, so
    nothing passes through the recorder that both outputs are built from. Unless the
    bridge records that confirmed payload, the run lists no resources and the local
    mirror retires every row it holds.
    """

    def test_an_unchanged_rerun_keeps_every_row_active(self, tmp_path, monkeypatch):
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        # One store across both runs, standing in for WeveNova. --local-only builds a
        # fresh empty store per run, so its reruns are never unchanged.
        service = InMemoryInventoryClient()
        monkeypatch.setattr(
            di, "_build_inventory_client", lambda *_a, **_k: (service, "mcp:test", None)
        )
        monkeypatch.chdir(tmp_path)
        results = tmp_path / "results.json"
        mirror = tmp_path / "inventory.json"
        argv = ["--tenant-id", "demo-tenant", "--demo", "--quiet"]
        argv += ["--json-out", str(results), "--inventory-out", str(mirror)]

        assert di.main(list(argv)) == 0
        first = json.loads(results.read_text(encoding="utf-8"))
        assert di.main(list(argv)) == 0
        second = json.loads(results.read_text(encoding="utf-8"))

        assert second["sync"]["unchanged"]  # the skipped-sync path, not a second write
        assert second["discovered"] == first["discovered"]
        doc = json.loads(mirror.read_text(encoding="utf-8"))
        states = {rec["state"] for recs in doc["resources"].values() for rec in recs}
        assert states == {"Active"}


class TestDiscoverySafetyWiring:
    @pytest.mark.parametrize("source", ["another-tenant", None, "", "organizations"])
    def test_source_mismatch_never_builds_a_shared_client(
        self, tmp_path, monkeypatch, source
    ):
        from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient

        platform, env_id = di._demo_platform_and_inventory()
        monkeypatch.setattr(
            platform, "authenticated_tenant_id", lambda: source, raising=False
        )
        monkeypatch.setattr(di, "_live_platform", lambda: (platform, env_id))
        shared_calls = []

        def build(local_only, *_args):
            shared_calls.append(not local_only)
            assert local_only
            return InMemoryInventoryClient(), "local-only", None

        monkeypatch.setattr(di, "_build_inventory_client", build)
        monkeypatch.chdir(tmp_path)
        assert di.main(["--tenant-id", "contoso", "--quiet"]) == 2
        assert shared_calls == [False]
        result = json.loads((tmp_path / "workspace/discover/results.json").read_text())
        assert result["writeDegraded"]
        assert "source tenant" in result["writePathNote"]

    def test_unreadable_source_identity_disables_writes(self):
        class Source:
            def authenticated_tenant_id(self):
                raise ValueError("unreadable token")

        assert "unreadable token" in di._source_tenant_error(Source(), "contoso")

    @pytest.mark.parametrize("fail_sync", [False, True])
    def test_live_run_holds_one_shared_lock_through_read_and_write(
        self, tmp_path, monkeypatch, fail_sync
    ):
        from tenant_inventory_discovery.errors import RunLockError
        from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient

        platform, env_id = di._demo_platform_and_inventory()
        monkeypatch.setattr(
            platform, "authenticated_tenant_id", lambda: "contoso", raising=False
        )
        monkeypatch.setattr(di, "_live_platform", lambda: (platform, env_id))
        lock_dir = tmp_path / "locks"
        monkeypatch.setattr(di, "_run_lock_dir", lambda: lock_dir)
        other = di.FileRunLock(lock_dir, ttl_seconds=3600)
        calls = []

        class Service(InMemoryInventoryClient):
            def list_items(self, **kwargs):
                with pytest.raises(RunLockError):
                    other.acquire("contoso", "competitor")
                calls.append("read")
                return super().list_items(**kwargs)

            def sync_inventory(self, items, *, run_id=""):
                with pytest.raises(RunLockError):
                    other.acquire("contoso", "competitor")
                calls.append("write")
                if fail_sync:
                    raise RuntimeError("injected sync failure")
                return super().sync_inventory(items, run_id=run_id)

        service = Service()
        monkeypatch.setattr(
            di, "_build_inventory_client", lambda *_a: (service, "mcp:test", None)
        )
        monkeypatch.chdir(tmp_path)
        assert di.main(["--tenant-id", "CONTOSO", "--quiet"]) == (1 if fail_sync else 0)
        assert calls == ["read", "write"]
        other.acquire("contoso", "competitor")
        other.release("contoso", "competitor")

    def test_lock_location_is_independent_of_checkout(self, tmp_path, monkeypatch):
        original = di._run_lock_dir()
        monkeypatch.chdir(tmp_path)
        assert di._run_lock_dir() == original
