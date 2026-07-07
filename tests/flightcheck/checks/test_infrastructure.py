# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for INFRA-001 infrastructure connectivity checks.

Mocks socket and ssl at the module level — no real network calls. These checks
use only Python stdlib (socket/ssl), so no external API mocks or cassette
validation is required (no require_validated_mock gate).
"""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from flightcheck.checks.infrastructure import (
    ProbeResult,
    _discover_microsoft_service_targets,
    _host_from_url,
    check_dlp_connector_classification,
    check_microsoft_service_reachability,
    probe_endpoint,
    run_infrastructure_checks,
)
import flightcheck.checks._dlp_utils as dlp_utils
from flightcheck.runner import Status

from tests.conftest import (
    FAKE_DATAVERSE_URL,
    FAKE_ENV_ID,
    FAKE_TOKEN,
    require_validated_mock,
)
from tests.mocks import pp_admin as ppa

require_validated_mock(ppa)


# ───────────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    """Minimal runner with fields used by infrastructure checks."""

    env_url: str = "https://orgmocktenant.crm.dynamics.com"
    config: dict[str, Any] | None = None


@pytest.fixture
def runner() -> _MinimalRunner:
    return _MinimalRunner()


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


def _mock_getaddrinfo_success(host, port, *args, **kwargs):
    """Simulate successful DNS resolution."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", port))]


def _mock_getaddrinfo_fail(host, port, *args, **kwargs):
    """Simulate DNS resolution failure."""
    raise socket.gaierror(8, f"nodename nor servname provided, or not known: {host}")


# ───────────────────────────────────────────────────────────────────────
# Shared probe tests
# ───────────────────────────────────────────────────────────────────────


class TestProbeEndpointDnsSuccess:
    """probe_endpoint: DNS resolves and all layers pass."""

    @patch("flightcheck.checks.infrastructure.ssl.create_default_context")
    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_success,
    )
    def test_all_layers_pass(self, mock_dns, mock_socket_cls, mock_ssl_ctx):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        mock_ssock = MagicMock()
        mock_ssock.version.return_value = "TLSv1.3"
        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value.__enter__.return_value = mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__.return_value = None
        mock_ssl_ctx.return_value = mock_ctx

        result = probe_endpoint("example.com", 443)

        assert result.dns_ok is True
        assert result.tcp_ok is True
        assert result.tls_ok is True
        assert result.resolved_ip == "93.184.216.34"
        assert result.tls_version == "TLSv1.3"
        assert result.error_layer is None
        assert result.error_message is None

    @patch("flightcheck.checks.infrastructure.ssl.create_default_context")
    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch("flightcheck.checks.infrastructure.socket.getaddrinfo")
    def test_ipv6_uses_sockaddr_tuple(self, mock_dns, mock_socket_cls, mock_ssl_ctx):
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 443, 0, 0))
        ]
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        mock_ssock = MagicMock()
        mock_ssock.version.return_value = "TLSv1.3"
        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value.__enter__.return_value = mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__.return_value = None
        mock_ssl_ctx.return_value = mock_ctx

        result = probe_endpoint("example.com", 443)

        mock_sock.connect.assert_called_once_with(("2001:db8::1", 443, 0, 0))
        assert result.resolved_ip == "2001:db8::1"
        assert result.tcp_ok is True


class TestProbeEndpointDualStackFallback:
    """probe_endpoint: Falls back to IPv4 when IPv6 connect fails."""

    @patch("flightcheck.checks.infrastructure.ssl.create_default_context")
    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch("flightcheck.checks.infrastructure.socket.getaddrinfo")
    def test_ipv6_unreachable_falls_back_to_ipv4(self, mock_dns, mock_socket_cls, mock_ssl_ctx):
        # DNS returns IPv6 first, then IPv4
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443)),
        ]

        # First socket (IPv6) fails with ENETUNREACH, second (IPv4) succeeds
        ipv6_sock = MagicMock()
        ipv6_sock.connect.side_effect = OSError(101, "Network is unreachable")
        ipv4_sock = MagicMock()
        mock_socket_cls.side_effect = [ipv6_sock, ipv4_sock]

        mock_ssock = MagicMock()
        mock_ssock.version.return_value = "TLSv1.3"
        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value.__enter__.return_value = mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__.return_value = None
        mock_ssl_ctx.return_value = mock_ctx

        result = probe_endpoint("example.com", 443)

        # IPv6 socket was closed after failure
        ipv6_sock.close.assert_called_once()
        # IPv4 socket was used for successful connection
        ipv4_sock.connect.assert_called_once_with(("93.184.216.34", 443))
        assert result.tcp_ok is True
        assert result.tls_ok is True
        assert result.resolved_ip == "93.184.216.34"


        # probe_endpoint: DNS resolution fails.

    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_fail,
    )
    def test_dns_failure(self, mock_dns):
        result = probe_endpoint("nonexistent.invalid", 443)

        assert result.dns_ok is False
        assert result.tcp_ok is False
        assert result.tls_ok is False
        assert result.error_layer == "dns"
        assert "DNS resolution failed" in result.error_message


class TestProbeEndpointTcpTimeout:
    """probe_endpoint: TCP connection times out (firewall dropping packets)."""

    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_success,
    )
    def test_tcp_timeout(self, mock_dns, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = socket.timeout("timed out")
        mock_socket_cls.return_value = mock_sock

        result = probe_endpoint("blocked.example.com", 443, timeout=5.0)

        assert result.dns_ok is True
        assert result.tcp_ok is False
        assert result.tls_ok is False
        assert result.error_layer == "tcp"
        assert "timed out" in result.error_message


class TestProbeEndpointConnectionRefused:
    """probe_endpoint: TCP connection refused (port closed or RST)."""

    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_success,
    )
    def test_connection_refused(self, mock_dns, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError("Connection refused")
        mock_socket_cls.return_value = mock_sock

        result = probe_endpoint("refused.example.com", 443)

        assert result.dns_ok is True
        assert result.tcp_ok is False
        assert result.error_layer == "tcp"
        assert "refused" in result.error_message


class TestProbeEndpointTlsFailure:
    """probe_endpoint: TLS handshake fails (proxy interception / cert issue)."""

    @patch("flightcheck.checks.infrastructure.ssl.create_default_context")
    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_success,
    )
    def test_tls_failure(self, mock_dns, mock_socket_cls, mock_ssl_ctx):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.side_effect = ssl.SSLError(
            "CERTIFICATE_VERIFY_FAILED"
        )
        mock_ssl_ctx.return_value = mock_ctx

        result = probe_endpoint("intercepted.example.com", 443)

        assert result.dns_ok is True
        assert result.tcp_ok is True
        assert result.tls_ok is False
        assert result.error_layer == "tls"
        assert "TLS handshake failed" in result.error_message


class TestProbeEndpointNoSideEffects:
    """probe_endpoint: verifies no files written and no env vars modified."""

    @patch("flightcheck.checks.infrastructure.ssl.create_default_context")
    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_success,
    )
    def test_no_side_effects(self, mock_dns, mock_socket_cls, mock_ssl_ctx, tmp_path, monkeypatch):
        import os

        monkeypatch.chdir(tmp_path)
        env_before = dict(os.environ)

        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_ctx = MagicMock()
        mock_ssock = MagicMock()
        mock_ssock.version.return_value = "TLSv1.3"
        mock_ctx.wrap_socket.return_value.__enter__.return_value = mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__.return_value = None
        mock_ssl_ctx.return_value = mock_ctx

        probe_endpoint("example.com", 443)

        # No files created
        assert list(tmp_path.iterdir()) == []
        # No env vars modified
        env_after = dict(os.environ)
        assert env_before == env_after


# ───────────────────────────────────────────────────────────────────────
# INFRA-001 tests
# ───────────────────────────────────────────────────────────────────────


def _patch_probe(results_map: dict[str, ProbeResult]):
    """Patch probe_endpoint to return predetermined results based on host."""

    def _fake_probe(host, port=443, timeout=10.0):
        for key, result in results_map.items():
            if key in host:
                return result
        # Default: all pass
        return ProbeResult(
            host=host, port=port,
            dns_ok=True, tcp_ok=True, tls_ok=True,
            resolved_ip="10.0.0.1", dns_ms=1.0, tcp_ms=10.0, tls_ms=5.0,
            tls_version="TLSv1.3",
        )

    return patch("flightcheck.checks.infrastructure.probe_endpoint", side_effect=_fake_probe)


class TestInfra001AllReachable:
    """INFRA-001: All Microsoft endpoints reachable → all PASSED."""

    def test_all_pass(self, runner):
        all_pass = ProbeResult(
            host="any", port=443,
            dns_ok=True, tcp_ok=True, tls_ok=True,
            resolved_ip="10.0.0.1", dns_ms=1.0, tcp_ms=10.0, tls_ms=5.0,
            tls_version="TLSv1.3",
        )
        with _patch_probe({"": all_pass}):
            results = check_microsoft_service_reachability(runner)

        assert len(results) >= 5  # At least 5 Microsoft endpoints + Dataverse
        for r in results:
            assert r.checkpoint_id == "INFRA-001"
            assert r.status == Status.PASSED.value
            assert "Reachable" in r.result
            assert r.category == "Infrastructure"


class TestInfra001FirewallBlocks:
    """INFRA-001: One endpoint blocked by firewall → that target FAILED."""

    def test_one_blocked(self, runner):
        blocked = ProbeResult(
            host="api.powerplatform.com", port=443,
            dns_ok=True, tcp_ok=False, tls_ok=False,
            resolved_ip="52.1.2.3", dns_ms=1.0, tcp_ms=10000.0,
            error_layer="tcp",
            error_message="TCP connection to api.powerplatform.com:443 (52.1.2.3) timed out after 10s",
        )
        with _patch_probe({"powerplatform": blocked}):
            results = check_microsoft_service_reachability(runner)

        failed = [r for r in results if r.status == Status.FAILED.value]
        passed = [r for r in results if r.status == Status.PASSED.value]
        assert len(failed) >= 1
        assert any("Power Platform" in r.result or "powerplatform" in r.result for r in failed)
        assert len(passed) >= 4


class TestInfra001DnsFailure:
    """INFRA-001: DNS failure on Entra ID → FAILED."""

    def test_dns_fail(self, runner):
        dns_fail = ProbeResult(
            host="login.microsoftonline.com", port=443,
            dns_ok=False, tcp_ok=False, tls_ok=False,
            dns_ms=2.0,
            error_layer="dns",
            error_message="DNS resolution failed for login.microsoftonline.com",
        )
        with _patch_probe({"login.microsoftonline": dns_fail}):
            results = check_microsoft_service_reachability(runner)

        failed = [r for r in results if r.status == Status.FAILED.value]
        assert len(failed) >= 1
        assert any("DNS resolution failed" in r.result for r in failed)


class TestInfra001TlsIntercepted:
    """INFRA-001: TLS intercepted by proxy → WARNING."""

    def test_tls_warning(self, runner):
        tls_fail = ProbeResult(
            host="graph.microsoft.com", port=443,
            dns_ok=True, tcp_ok=True, tls_ok=False,
            resolved_ip="10.0.0.5", dns_ms=1.0, tcp_ms=8.0, tls_ms=50.0,
            error_layer="tls",
            error_message="TLS handshake failed for graph.microsoft.com:443: CERTIFICATE_VERIFY_FAILED",
        )
        with _patch_probe({"graph.microsoft": tls_fail}):
            results = check_microsoft_service_reachability(runner)

        warnings = [r for r in results if r.status == Status.WARNING.value]
        assert len(warnings) >= 1
        assert any("Partially reachable" in r.result for r in warnings)
        assert any("proxy" in r.remediation.lower() or "certificate" in r.remediation.lower() for r in warnings)


class TestInfra001MultipleFailures:
    """INFRA-001: Multiple endpoints fail → mixed results, one per target."""

    def test_mixed_results(self, runner):
        blocked = ProbeResult(
            host="blocked", port=443,
            dns_ok=True, tcp_ok=False, tls_ok=False,
            resolved_ip="10.0.0.1", dns_ms=1.0, tcp_ms=10000.0,
            error_layer="tcp",
            error_message="timed out",
        )
        with _patch_probe({"login.microsoftonline": blocked, "api.powerplatform": blocked}):
            results = check_microsoft_service_reachability(runner)

        failed = [r for r in results if r.status == Status.FAILED.value]
        passed = [r for r in results if r.status == Status.PASSED.value]
        assert len(failed) == 2
        assert len(passed) >= 3

    def test_dataverse_missing_is_skipped(self):
        runner = _MinimalRunner(env_url="")
        all_pass = ProbeResult(
            host="any", port=443,
            dns_ok=True, tcp_ok=True, tls_ok=True,
            resolved_ip="10.0.0.1", dns_ms=1.0, tcp_ms=10.0, tls_ms=5.0,
            tls_version="TLSv1.3",
        )
        with _patch_probe({"": all_pass}):
            results = check_microsoft_service_reachability(runner)

        dataverse = [r for r in results if "Dataverse" in r.description]
        assert len(dataverse) == 1
        assert dataverse[0].status == Status.SKIPPED.value


# ───────────────────────────────────────────────────────────────────────
# Shared utility tests
# ───────────────────────────────────────────────────────────────────────


class TestHostFromUrl:
    """_host_from_url: extracts hostname from URLs with/without scheme."""

    def test_full_url(self):
        assert _host_from_url("https://example.com/path") == "example.com"

    def test_url_without_scheme(self):
        assert _host_from_url("example.com") == "example.com"

    def test_empty_string(self):
        assert _host_from_url("") is None

    def test_none_input(self):
        assert _host_from_url(None) is None


# ───────────────────────────────────────────────────────────────────────
# Target discovery tests
# ───────────────────────────────────────────────────────────────────────


class TestDiscoverMicrosoftServiceTargets:
    """_discover_microsoft_service_targets: always includes Microsoft endpoints + Dataverse."""

    def test_includes_all_microsoft_endpoints(self, runner):
        targets = _discover_microsoft_service_targets(runner)
        assert "Entra ID" in targets
        assert "Power Platform API" in targets
        assert "Power Apps API" in targets
        assert "Power Virtual Agents" in targets
        assert "Power Automate API" in targets
        assert "Microsoft Graph" in targets
        assert "Dataverse" in targets
        assert targets["Dataverse"] == ("orgmocktenant.crm.dynamics.com", 443)

    def test_no_dataverse_without_env_url(self):
        runner = _MinimalRunner(env_url="")
        targets = _discover_microsoft_service_targets(runner)
        assert "Dataverse" not in targets
        # Still has the hardcoded ones
        assert len(targets) >= 6


# ───────────────────────────────────────────────────────────────────────
# Integration: run_infrastructure_checks
# ───────────────────────────────────────────────────────────────────────


class TestRunInfrastructureChecks:
    """run_infrastructure_checks: orchestrates registered INFRA checks."""

    def test_returns_infra_001_results(self, runner):
        all_pass = ProbeResult(
            host="any", port=443,
            dns_ok=True, tcp_ok=True, tls_ok=True,
            resolved_ip="10.0.0.1", dns_ms=1.0, tcp_ms=10.0, tls_ms=5.0,
            tls_version="TLSv1.3",
        )
        with _patch_probe({"": all_pass}):
            results = run_infrastructure_checks(runner)

        infra_001 = [r for r in results if r.checkpoint_id == "INFRA-001"]
        assert len(infra_001) >= 5
        for r in infra_001:
            assert r.status == Status.PASSED.value


# ───────────────────────────────────────────────────────────────────────
# INFRA-006: DLP connector classification
#
# Unit tests drive check_dlp_connector_classification directly with a fake
# PP-Admin client (get_dlp_policies_for_env) and a monkeypatched
# _dlp_utils.query_all (the Dataverse connection-references source). DLP
# policies are built with the validated tests/mocks/pp_admin.dlp_policy()
# builder (apiPolicies 2021-04-01 connectorGroups shape).
# ───────────────────────────────────────────────────────────────────────

# Canonical agent connector api-names used across INFRA-006 tests.
_DATAVERSE = "shared_commondataserviceforapps"
_WORKDAY = "shared_workdaysoap"
_HTTP_AAD = "shared_webcontents"


class _FakeDlpPP:
    """Minimal PP-Admin stub exposing only get_dlp_policies_for_env.

    ``policies`` may be a list of policy dicts, a ``{"_error": ...}`` dict
    (permission failure), or an Exception instance to raise.
    """

    def __init__(self, policies):
        self._policies = policies

    def get_dlp_policies_for_env(self, _env_id):
        if isinstance(self._policies, Exception):
            raise self._policies
        return self._policies


def _dlp_runner(policies, *, env_url=FAKE_DATAVERSE_URL, dv_token=FAKE_TOKEN):
    return SimpleNamespace(
        pp_admin=_FakeDlpPP(policies),
        env_id=FAKE_ENV_ID,
        env_url=env_url,
        dv_token=dv_token,
    )


def _ref_rows(*connector_api_names):
    """Build Dataverse connectionreferences rows for the given connectors."""
    return [
        {
            "connectionreferenceid": f"00000000-0000-0000-0000-00000000000{i}",
            "connectorid": f"/providers/Microsoft.PowerApps/apis/{name}",
            "statuscode": 1,
        }
        for i, name in enumerate(connector_api_names)
    ]


def _patch_refs(monkeypatch, *connector_api_names):
    monkeypatch.setattr(
        dlp_utils, "query_all",
        lambda *a, **kw: _ref_rows(*connector_api_names),
    )


def _infra_006(results):
    return next(r for r in results if r.checkpoint_id == "INFRA-006")


class TestInfra006Verdicts:
    """INFRA-006 verdict mapping across the heritage scenarios (AC3/AC4/AC5)."""

    def test_all_allowed_same_group_passes(self, monkeypatch):
        # Arrange: both agent connectors classified Business (Confidential).
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy(business=[_DATAVERSE, _WORKDAY])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.PASSED.value
        assert "same data-group" in result.result
        assert "Business" in result.result
        assert result.remediation == ""

    def test_cross_group_warns(self, monkeypatch):
        # Arrange: Dataverse=Business, HTTP=Non-Business → all allowed but can't
        # be combined. AC5: cross-group is a WARNING, not a FAIL.
        _patch_refs(monkeypatch, _DATAVERSE, _HTTP_AAD)
        policies = [ppa.dlp_policy(business=[_DATAVERSE], non_business=[_HTTP_AAD])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.WARNING.value
        assert "split across data-groups" in result.result
        assert result.remediation  # non-empty, names the fix

    def test_all_non_business_same_group_warns(self, monkeypatch):
        # Arrange: both agent connectors allowed but classified Non-Business.
        # PASS requires Business (per the validation method), so an
        # all-Non-Business same-group config is a WARNING, not a PASS.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy(non_business=[_DATAVERSE, _WORKDAY])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.WARNING.value
        assert "Non-Business" in result.result
        assert result.remediation  # non-empty, names the fix

    def test_blocked_connector_fails(self, monkeypatch):
        # Arrange: Workday is Blocked.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy(business=[_DATAVERSE], blocked=[_WORKDAY])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.FAILED.value
        assert "Blocked" in result.result
        assert _WORKDAY in result.remediation

    def test_partial_indeterminate_across_policies_warns(self, monkeypatch):
        # Arrange: two effective policies. Policy A classifies both Business;
        # policy B omits Workday (default-group fallthrough) → indeterminate.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [
            ppa.dlp_policy(display_name="Policy A", business=[_DATAVERSE, _WORKDAY]),
            ppa.dlp_policy(display_name="Policy B", business=[_DATAVERSE]),
        ]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.WARNING.value
        assert _WORKDAY in result.result
        assert result.remediation

    def test_permission_error_warns(self, monkeypatch):
        # Arrange: apiPolicies admin endpoint denied access.
        _patch_refs(monkeypatch, _DATAVERSE)
        runner = _dlp_runner({"_error": "forbidden", "_status": 403})

        # Act
        result = _infra_006(check_dlp_connector_classification(runner))

        # Assert
        assert result.status == Status.WARNING.value
        assert "permissions error" in result.result.lower()

    def test_dataverse_unreadable_warns(self, monkeypatch):
        # Arrange: policy reads fine, but resolving connectors raises.
        monkeypatch.setattr(
            dlp_utils, "query_all",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("dv down")),
        )
        policies = [ppa.dlp_policy(business=[_DATAVERSE])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.WARNING.value
        assert "connection references" in result.result.lower()

    def test_no_policy_skips_and_defers_to_env_008(self, monkeypatch):
        # Arrange: no DLP policy applies to the environment.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)

        # Act
        results = check_dlp_connector_classification(_dlp_runner([]))

        # Assert: exactly one INFRA-006 finding, SKIPPED, deferring to ENV-008,
        # with NO duplicate "no DLP policy found" coverage claim.
        assert len(results) == 1
        result = results[0]
        assert result.status == Status.SKIPPED.value
        assert "ENV-008" in result.result
        assert result.remediation == ""


class TestInfra006ModernSchema:
    """INFRA-006 against the modern ``definition.apiGroups`` policy shape.

    Real tenants return classification under
    ``properties.definition.apiGroups.{hbi|lbi|blocked}`` with a
    ``defaultApiGroup``, not the legacy ``connectorGroups``. These tests use
    the ``dlp_policy_modern`` builder (verified against a live 2026-06-30
    apiPolicies response) to prevent regressing to the false WARN that the
    legacy-only parser produced.
    """

    def test_modern_all_business_passes(self, monkeypatch):
        # Arrange: both agent connectors classified Business (hbi).
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy_modern(business=[_DATAVERSE, _WORKDAY])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.PASSED.value
        assert "same data-group" in result.result
        assert "Business" in result.result

    def test_modern_default_group_resolves_not_indeterminate(self, monkeypatch):
        # Arrange: Dataverse explicit in hbi; Workday unlisted but the policy
        # default is hbi, so it resolves to Business rather than indeterminate.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy_modern(business=[_DATAVERSE], default_group="hbi")]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert: no false WARN — the default group makes the verdict provable.
        assert result.status == Status.PASSED.value

    def test_modern_default_group_causes_cross_group_warn(self, monkeypatch):
        # Arrange: mirrors the live tenant. Dataverse in hbi (Business); the
        # second connector is unlisted and inherits the lbi default
        # (Non-Business), so the two connectors are split across groups.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy_modern(business=[_DATAVERSE], default_group="lbi")]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert: AC5 — cross-group is a WARNING, not a FAIL.
        assert result.status == Status.WARNING.value
        assert "split across data-groups" in result.result

    def test_modern_blocked_connector_fails(self, monkeypatch):
        # Arrange: the second connector is explicitly Blocked.
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy_modern(business=[_DATAVERSE], blocked=[_WORKDAY])]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.FAILED.value
        assert "Blocked" in result.result

    def test_modern_default_blocked_fails(self, monkeypatch):
        # Arrange: unlisted connector inherits a Blocked default group.
        _patch_refs(monkeypatch, _WORKDAY)
        policies = [ppa.dlp_policy_modern(business=[_DATAVERSE], default_group="blocked")]

        # Act
        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        # Assert
        assert result.status == Status.FAILED.value
        assert "Blocked" in result.result


class TestDlpModernSchemaParsing:
    """Direct parser coverage for the modern ``definition.apiGroups`` shape."""

    def test_policy_connector_groups_reads_apigroups(self):
        policy = ppa.dlp_policy_modern(
            business=[_DATAVERSE], non_business=[_HTTP_AAD], blocked=[_WORKDAY],
        )
        cmap = dlp_utils.policy_connector_groups(policy)

        assert cmap[_DATAVERSE] == "business"
        assert cmap[_HTTP_AAD] == "nonbusiness"
        assert cmap[_WORKDAY] == "blocked"

    def test_policy_default_group_reads_default_api_group(self):
        assert dlp_utils.policy_default_group(
            ppa.dlp_policy_modern(default_group="lbi")) == "nonbusiness"
        assert dlp_utils.policy_default_group(
            ppa.dlp_policy_modern(default_group="hbi")) == "business"
        assert dlp_utils.policy_default_group(
            ppa.dlp_policy_modern(default_group="blocked")) == "blocked"

    def test_legacy_policy_has_no_default_group(self):
        # Legacy connectorGroups shape reports no default → None (unchanged).
        assert dlp_utils.policy_default_group(
            ppa.dlp_policy(business=[_DATAVERSE])) is None


class TestInfra006Schema:
    """INFRA-006 row schema + owning role guard (mirrors PRE-004/005)."""

    @pytest.mark.parametrize("policies, refs, expected_status", [
        ([ppa.dlp_policy(business=[_DATAVERSE])], (_DATAVERSE,), Status.PASSED.value),
        ([ppa.dlp_policy(blocked=[_DATAVERSE])], (_DATAVERSE,), Status.FAILED.value),
        ([ppa.dlp_policy(business=[_DATAVERSE])], (_WORKDAY,), Status.WARNING.value),
    ])
    def test_row_schema_and_owning_role(self, monkeypatch, policies, refs, expected_status):
        _patch_refs(monkeypatch, *refs)

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.checkpoint_id == "INFRA-006"
        assert result.category == "Infrastructure"
        assert result.priority == "Critical"
        assert result.roles == ["Power Platform Admin"]
        assert result.doc_link  # doc link always set
        assert result.status == expected_status
        # Remediation present iff the check is not a clean PASS.
        if expected_status == Status.PASSED.value:
            assert result.remediation == ""
        else:
            assert result.remediation

    def test_read_only_idempotent(self, monkeypatch):
        # Running twice against the same inputs yields identical verdicts (AC8).
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [ppa.dlp_policy(business=[_DATAVERSE, _WORKDAY])]

        first = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))
        second = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert first.status == second.status == Status.PASSED.value
        assert first.result == second.result


class TestInfra006Resilience:
    """INFRA-006 boundary/robustness behavior (reviewer findings M1, M2, I1, I2, I3)."""

    def test_malformed_policies_shape_warns_not_crashes(self, monkeypatch):
        # M1: client contract drift — a truthy dict without "_error". Must NOT
        # iterate dict keys and crash; degrade to WARN.
        _patch_refs(monkeypatch, _DATAVERSE)
        runner = _dlp_runner({"value": [{"properties": {}}]})

        result = _infra_006(check_dlp_connector_classification(runner))

        assert result.status == Status.WARNING.value
        assert "unexpected response shape" in result.result.lower()

    def test_list_with_non_dict_element_does_not_crash(self, monkeypatch):
        # M1 (inner): a list containing a stray non-dict entry must be tolerated
        # without raising. The junk entry parses as a policy with no groups, so
        # the connector reads indeterminate there → safe WARN, never a crash.
        _patch_refs(monkeypatch, _DATAVERSE)
        policies = ["garbage", ppa.dlp_policy(business=[_DATAVERSE])]

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.status == Status.WARNING.value

    def test_evaluate_helper_rejects_empty_inputs(self):
        # M2: the public helper must not return a false PASS for empty inputs.
        policies = [ppa.dlp_policy(business=[_DATAVERSE])]
        with pytest.raises(ValueError):
            dlp_utils.evaluate_connector_classification({_DATAVERSE}, [])
        with pytest.raises(ValueError):
            dlp_utils.evaluate_connector_classification(set(), policies)

    def test_inactive_reference_is_excluded(self, monkeypatch):
        # I2: a disabled (statuscode=2) reference to a Blocked connector must
        # NOT drive a FAIL — it is not a runtime dependency. Only the active
        # Dataverse ref counts → PASS.
        monkeypatch.setattr(dlp_utils, "query_all", lambda *a, **kw: [
            {"connectionreferenceid": "r1",
             "connectorid": f"/providers/Microsoft.PowerApps/apis/{_DATAVERSE}",
             "statuscode": 1},
            {"connectionreferenceid": "r2",
             "connectorid": f"/providers/Microsoft.PowerApps/apis/{_WORKDAY}",
             "statuscode": 2},
        ])
        policies = [ppa.dlp_policy(business=[_DATAVERSE], blocked=[_WORKDAY])]

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.status == Status.PASSED.value

    def test_blocked_custom_connector_id_mismatch_degrades_to_warn(self, monkeypatch):
        # I1: a custom connector whose Dataverse id carries an env/GUID suffix
        # will not match the policy's certified-style id, so a genuinely
        # Blocked custom connector currently surfaces as WARN (indeterminate),
        # not FAIL. This test LOCKS that documented limitation.
        monkeypatch.setattr(dlp_utils, "query_all", lambda *a, **kw: [
            {"connectionreferenceid": "r1",
             "connectorid": "/providers/Microsoft.PowerApps/apis/shared_custom-abc123env",
             "statuscode": 1},
        ])
        policies = [ppa.dlp_policy(blocked=["shared_custom"])]

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.status == Status.WARNING.value

    def test_cross_group_names_offending_policy(self, monkeypatch):
        # I3: the WARN message must name the specific policy that splits the
        # connectors, not a union across all effective policies.
        _patch_refs(monkeypatch, _DATAVERSE, _HTTP_AAD)
        policies = [
            ppa.dlp_policy(display_name="Split Policy",
                           business=[_DATAVERSE], non_business=[_HTTP_AAD]),
        ]

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.status == Status.WARNING.value
        assert "Split Policy" in result.result
        assert "Business" in result.result and "Non-Business" in result.result

    def test_disagreeing_policies_non_business_warns(self, monkeypatch):
        # Two policies classify the same connectors into different groups.
        # Policy B places them Non-Business; INFRA-006 requires Business, so
        # the effective verdict is WARN (not PASS).
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [
            ppa.dlp_policy(display_name="A", business=[_DATAVERSE, _WORKDAY]),
            ppa.dlp_policy(display_name="B", non_business=[_DATAVERSE, _WORKDAY]),
        ]

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.status == Status.WARNING.value
        assert "Non-Business" in result.result
