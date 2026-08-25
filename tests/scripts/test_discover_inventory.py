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
import os
import sys
import types

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


class _StubMsalApp:
    def __init__(self, *, silent=None, interactive=None):
        self._silent = silent
        self._interactive = interactive
        self.interactive_calls = 0

    def get_accounts(self):
        return ["account"] if self._silent is not None else []

    def acquire_token_silent(self, scopes, account=None):
        return self._silent

    def acquire_token_interactive(self, scopes, prompt=None):
        self.interactive_calls += 1
        return self._interactive


def _install_stub_msal(monkeypatch, app):
    """Put a fake ``msal`` in sys.modules so the helper's lazy import finds it."""

    class _Cache:
        has_state_changed = False

        def deserialize(self, _data):
            return None

        def serialize(self):
            return "{}"

    module = types.SimpleNamespace(
        SerializableTokenCache=_Cache,
        PublicClientApplication=lambda *a, **k: app,
    )
    monkeypatch.setitem(sys.modules, "msal", module)
    return app


class TestAcquireInventoryToken:
    def test_env_var_wins_and_skips_interactive_auth(self, monkeypatch):
        """CI and token-holders must never be forced through a browser prompt."""
        monkeypatch.setenv(ENV_ACCESS_TOKEN, "env-token")
        app = _install_stub_msal(monkeypatch, _StubMsalApp())
        token, source = di._acquire_inventory_token("contoso")
        assert token == "env-token"
        assert source == ENV_ACCESS_TOKEN
        assert app.interactive_calls == 0

    def test_falls_back_to_a_silent_cached_token(self, monkeypatch):
        app = _install_stub_msal(
            monkeypatch, _StubMsalApp(silent={"access_token": "cached"})
        )
        token, source = di._acquire_inventory_token("contoso")
        assert token == "cached"
        assert source == "interactive sign-in"
        # A cached token that satisfies the scope must not trigger a prompt.
        assert app.interactive_calls == 0

    def test_prompts_when_no_cached_token_satisfies_the_scope(self, monkeypatch):
        app = _install_stub_msal(
            monkeypatch, _StubMsalApp(interactive={"access_token": "fresh"})
        )
        token, _ = di._acquire_inventory_token("contoso")
        assert token == "fresh"
        assert app.interactive_calls == 1

    def test_auth_failure_does_not_leak_the_error_description(self, monkeypatch):
        """CWE-209: error_description can carry tenant ids and internal flow details."""
        _install_stub_msal(
            monkeypatch,
            _StubMsalApp(
                interactive={
                    "error": "invalid_grant",
                    "error_description": "tenant 72f9-secret rejected the request",
                }
            ),
        )
        with pytest.raises(RuntimeError) as exc:
            di._acquire_inventory_token("contoso")
        assert "invalid_grant" in str(exc.value)
        assert "72f9-secret" not in str(exc.value)


class _StubHttpClient:
    """Stands in for HttpInventoryClient so no test touches the network."""

    def __init__(self, probe_error=None):
        self._probe_error = probe_error
        self.closed = False

    def probe(self):
        if self._probe_error is not None:
            raise self._probe_error

    def close(self):
        self.closed = True


def _patch_http_client(monkeypatch, stub):
    monkeypatch.setattr(
        "tenant_inventory_discovery.inventory_client.HttpInventoryClient",
        lambda *a, **k: stub,
    )
    return stub


class TestBuildInventoryClient:
    def test_local_only_builds_the_in_memory_client(self):
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        client, label, degraded = di._build_inventory_client(
            None, True, "contoso", DiscoveryConfig()
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        # An explicit opt-out is not a failure, so nothing should be reported.
        assert degraded is None

    def test_in_memory_client_inherits_the_configured_caps(self):
        """The opt-out must enforce the same caps, or it validates nothing useful."""
        config = DiscoveryConfig()
        client, _, _ = di._build_inventory_client(None, True, "contoso", config)
        assert client.caps is config.caps

    def test_live_path_builds_the_http_client_after_a_successful_probe(
        self, monkeypatch
    ):
        monkeypatch.setenv(ENV_ACCESS_TOKEN, "token")
        stub = _patch_http_client(monkeypatch, _StubHttpClient())
        config = DiscoveryConfig()
        client, label, degraded = di._build_inventory_client(
            _HOST, False, "contoso", config
        )
        assert client is stub
        assert label == _HOST
        assert degraded is None
        assert config.inventory_base_url == _HOST

    def test_probe_failure_degrades_instead_of_aborting(self, monkeypatch):
        """A 403 must not kill the crawl -- the enumeration is still worth having."""
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        monkeypatch.setenv(ENV_ACCESS_TOKEN, "token")
        stub = _patch_http_client(
            monkeypatch, _StubHttpClient(probe_error=RuntimeError("403 Forbidden"))
        )
        client, label, degraded = di._build_inventory_client(
            _HOST, False, "contoso", DiscoveryConfig()
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert degraded is not None
        assert "403 Forbidden" in degraded
        assert _HOST in degraded
        # The rejected client owns an httpx connection pool; leaking it is a bug.
        assert stub.closed is True

    def test_missing_token_degrades_rather_than_exiting(self, monkeypatch):
        """No token is a write-path failure, not a reason to throw away the crawl."""
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        def _boom(_tenant):
            raise RuntimeError("no token available")

        monkeypatch.setattr(di, "_acquire_inventory_token", _boom)
        client, label, degraded = di._build_inventory_client(
            _HOST, False, "contoso", DiscoveryConfig()
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert "no token available" in degraded


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
        monkeypatch.setenv(ENV_ACCESS_TOKEN, "token")
        _patch_http_client(
            monkeypatch,
            _StubHttpClient(
                probe_error=RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED]")
            ),
        )
        _, _, degraded = di._build_inventory_client(
            _HOST, False, "contoso", DiscoveryConfig()
        )
        assert "--insecure-skip-tls-verify" in degraded


class _StubMcpClient:
    """Stands in for McpInventoryClient; records the child environment it was given."""

    last_env: dict | None = None

    def __init__(self, *, info=None, probe_error=None, start_error=None):
        if start_error is not None:
            raise start_error
        self._info = info or {"baseUrl": "https://localhost:444/weveb2"}
        self._probe_error = probe_error
        self.closed = False

    def server_info(self):
        return self._info

    def probe(self):
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
    """``--via-mcp`` hands the write path to the local server.

    The server owns the token, the origin, and the certificate decision, so the only
    thing the bridge controls is the child's environment. Getting that wrong is not
    loud -- forwarding the bridge's *production* default would silently point a
    developer's MCP run at production -- so the forwarding rules are pinned here.
    """

    def test_success_labels_the_write_path_with_the_servers_target(self, monkeypatch):
        captured = _patch_mcp_client(
            monkeypatch, info={"baseUrl": "https://localhost:444/weveb2"}
        )
        client, label, degraded = di._build_inventory_client(
            DEFAULT_INVENTORY_BASE_URL,
            False,
            "contoso",
            DiscoveryConfig(),
            False,
            True,
            None,
        )
        assert client is captured["instance"]
        # Reporting the server's own target, not the bridge's guess, is what makes a
        # run auditable after the fact.
        assert label == "mcp:https://localhost:444/weveb2"
        assert degraded is None

    def test_an_explicit_base_url_is_forwarded(self, monkeypatch):
        captured = _patch_mcp_client(monkeypatch)
        di._build_inventory_client(
            _HOST, False, "contoso", DiscoveryConfig(), False, True, _HOST
        )
        assert captured["env"][ENV_BASE_URL] == _HOST

    def test_the_production_default_is_not_forwarded(self, monkeypatch):
        """Only user intent may override the server's dev-tunnel default."""
        monkeypatch.setenv(ENV_BASE_URL, "https://leaked.example.test")
        captured = _patch_mcp_client(monkeypatch)
        di._build_inventory_client(
            DEFAULT_INVENTORY_BASE_URL,
            False,
            "contoso",
            DiscoveryConfig(),
            False,
            True,
            None,
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
            _HOST, False, "contoso", DiscoveryConfig(), False, True, _HOST
        )
        assert "WEVENOVA_VERIFY_TLS" not in captured["env"]

    def test_insecure_flag_forces_the_servers_verification_off(self, monkeypatch):
        captured = _patch_mcp_client(monkeypatch)
        di._build_inventory_client(
            _HOST, False, "contoso", DiscoveryConfig(), True, True, _HOST
        )
        assert captured["env"]["WEVENOVA_VERIFY_TLS"] == "false"

    def test_a_server_that_will_not_start_degrades(self, monkeypatch):
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        _patch_mcp_client(monkeypatch, start_error=RuntimeError("no such file"))
        client, label, degraded = di._build_inventory_client(
            _HOST, False, "contoso", DiscoveryConfig(), False, True, _HOST
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
            _HOST, False, "contoso", DiscoveryConfig(), False, True, _HOST
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert "connection refused" in degraded
        # A leaked subprocess would outlive the run and hold the tunnel open.
        assert captured["instance"].closed is True

    def test_local_only_wins_over_via_mcp(self, monkeypatch):
        """--local-only is checked first, so it can never be bypassed by --via-mcp."""
        from tenant_inventory_discovery.in_memory_inventory import (
            InMemoryInventoryClient,
        )

        captured = _patch_mcp_client(monkeypatch)
        client, label, _ = di._build_inventory_client(
            None, True, "contoso", DiscoveryConfig(), False, True, None
        )
        assert isinstance(client, InMemoryInventoryClient)
        assert label == "local-only"
        assert "instance" not in captured


def _flags(*, via_mcp=False, direct=False, local_only=False):
    return argparse.Namespace(
        via_mcp=via_mcp, direct=direct, local_only=local_only
    )


class TestWritePathDefaultsToMcp:
    """The MCP server is the default write path.

    It is the only path that reads the saved ``.local/wevenova_token`` file. The direct
    path acquires its own token, and the app id it can mint for is not admitted by the
    service's authorization policy -- so when it was the default, an ordinary run
    opened a browser, failed to sign in, degraded to the local mirror and exited 2,
    even though a usable token was sitting on disk.
    """

    def test_a_bare_run_goes_through_mcp(self):
        assert di._resolve_write_path(_flags()).via_mcp is True

    def test_direct_opts_out(self):
        assert di._resolve_write_path(_flags(direct=True)).via_mcp is False

    def test_via_mcp_is_still_accepted(self):
        """It predates the flip; existing commands and docs must keep working."""
        assert di._resolve_write_path(_flags(via_mcp=True)).via_mcp is True

    def test_local_only_does_not_conflict_with_the_new_default(self):
        """--local-only is no longer contradicted by the implicit MCP default."""
        assert di._resolve_write_path(_flags(local_only=True)).via_mcp is True

    def test_via_mcp_with_direct_is_rejected(self):
        with pytest.raises(SystemExit, match="--via-mcp conflicts with --direct"):
            di._resolve_write_path(_flags(via_mcp=True, direct=True))

    def test_direct_with_local_only_is_rejected(self):
        with pytest.raises(SystemExit, match="--direct conflicts with --local-only"):
            di._resolve_write_path(_flags(direct=True, local_only=True))


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
