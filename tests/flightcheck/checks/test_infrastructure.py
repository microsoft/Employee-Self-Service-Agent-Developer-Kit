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
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from flightcheck.checks.infrastructure import (
    ProbeResult,
    _discover_microsoft_service_targets,
    _host_from_url,
    check_microsoft_service_reachability,
    probe_endpoint,
    run_infrastructure_checks,
)
from flightcheck.runner import Status


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
        mock_ctx.wrap_socket.return_value.__enter__ = lambda: mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__ = lambda *_args: None
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
        mock_ctx.wrap_socket.return_value.__enter__ = lambda: mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__ = lambda *_args: None
        mock_ssl_ctx.return_value = mock_ctx

        result = probe_endpoint("example.com", 443)

        mock_sock.connect.assert_called_once_with(("2001:db8::1", 443, 0, 0))
        assert result.resolved_ip == "2001:db8::1"
        assert result.tcp_ok is True


class TestProbeEndpointDnsFailure:
    """probe_endpoint: DNS resolution fails."""

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
        mock_ctx.wrap_socket.return_value.__enter__ = lambda: mock_ssock
        mock_ctx.wrap_socket.return_value.__exit__ = lambda *_args: None
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
