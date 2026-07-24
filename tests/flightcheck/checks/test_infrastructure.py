# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for INFRA-001 infrastructure connectivity checks.

Mocks socket and ssl at the module level — no real network calls. These checks
use only Python stdlib (socket/ssl), so no external API mocks or cassette
validation is required (no require_validated_mock gate).
"""

from __future__ import annotations

import json
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
    _infra_002_from_live,
    _infra_002_tcp,
    _resolve_probe_target,
    check_dlp_connector_classification,
    check_hr_system_reachability,
    check_microsoft_service_reachability,
    probe_endpoint,
    run_infrastructure_checks,
)
import flightcheck.checks.infrastructure as infra
import flightcheck.flow_probe as fp
import flightcheck.checks._dlp_utils as dlp_utils
from flightcheck.runner import Priority, Role, Status

from tests.conftest import (
    FAKE_DATAVERSE_URL,
    FAKE_ENV_ID,
    FAKE_TOKEN,
    require_validated_mock,
)
from tests.mocks import pp_admin as ppa
from tests.mocks import dataverse as dv

require_validated_mock(ppa)
require_validated_mock(dv)


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

    def test_consistent_disagreeing_policies_pass_with_deterministic_label(self, monkeypatch):
        # I3 (PASS half): two policies that classify the same connectors into
        # different but internally-consistent groups are combinable in both →
        # PASS, and the label is deterministic (last policy wins = Non-Business).
        _patch_refs(monkeypatch, _DATAVERSE, _WORKDAY)
        policies = [
            ppa.dlp_policy(display_name="A", business=[_DATAVERSE, _WORKDAY]),
            ppa.dlp_policy(display_name="B", non_business=[_DATAVERSE, _WORKDAY]),
        ]

        result = _infra_006(check_dlp_connector_classification(_dlp_runner(policies)))

        assert result.status == Status.PASSED.value
        assert "Non-Business" in result.result


# ═══════════════════════════════════════════════════════════════════════
# INFRA-002 — HR-system reachability from Power Platform's egress boundary
#
# Two paths under test:
#   * default / fallback: local TCP probe (socket+ssl mocked, stdlib only)
#   * consent-gated live: temporary Power Platform flow (flow_probe). The
#     live path's external surfaces (listCallbackUrl + invoke) are validated-
#     tier with a capture PENDING, so these tests DO NOT fabricate those
#     response shapes — they exercise the check wiring via run_live_probe's
#     own verdict contract, and the Dataverse workflow lifecycle (documented
#     tier) via hand-rolled documented-shaped responses. The flow-path
#     cassette-backed GOOD/BAD tests are added once flightcheck_infra002.yaml
#     is captured (Phase 2).
# ═══════════════════════════════════════════════════════════════════════

WD_TARGET = "https://impl.workday.com/microsoft_dpt6"


def _infra_002(results):
    """Extract the single INFRA-002 row from a check's results."""
    rows = [r for r in results if r.checkpoint_id == "INFRA-002"]
    assert len(rows) == 1, f"expected exactly one INFRA-002 row, got {len(rows)}"
    return rows[0]


def _live_runner(**overrides):
    base = dict(
        live_network_probe=True,
        probe_target_url=WD_TARGET,
        pp_admin=object(),
        env_id=FAKE_ENV_ID,
        env_url=FAKE_DATAVERSE_URL,
        dv_token=FAKE_TOKEN,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _wire_tls_ok(mock_ssl_ctx, version="TLSv1.3"):
    mock_ssock = MagicMock()
    mock_ssock.version.return_value = version
    mock_ctx = MagicMock()
    mock_ctx.wrap_socket.return_value.__enter__.return_value = mock_ssock
    mock_ctx.wrap_socket.return_value.__exit__.return_value = None
    mock_ssl_ctx.return_value = mock_ctx


class TestInfra002BuildClientData:
    """The flow definition we author (our own reachability contract)."""

    def test_flow_definition_structure(self):
        cd = json.loads(fp.build_client_data(WD_TARGET))
        d = cd["properties"]["definition"]
        assert set(d["actions"]) == {"HTTP_HEAD", "Response"}
        assert list(d["triggers"]) == ["manual"]
        head = d["actions"]["HTTP_HEAD"]
        assert head["type"] == "Http"                      # native, no connector
        assert head["inputs"]["method"] == "HEAD"          # no body, no credentials
        assert head["inputs"]["uri"] == WD_TARGET
        # No connector reference => nothing authenticates against the target.
        assert cd["properties"]["connectionReferences"] == {}

    def test_response_action_reports_reachability_fields(self):
        d = json.loads(fp.build_client_data(WD_TARGET))["properties"]["definition"]
        resp = d["actions"]["Response"]
        assert set(resp["inputs"]["body"]) >= {
            "reachable", "http_status", "redirect_location", "error",
        }
        # Response runs whether the HEAD succeeded, failed, or timed out.
        assert resp["runAfter"] == {"HTTP_HEAD": ["Succeeded", "Failed", "TimedOut"]}


class TestInfra002Classify:
    """flow_probe.classify — reachability / instance-validity / access."""

    def test_reachable_and_valid_on_login_redirect(self):
        v = fp.classify({"body": {
            "reachable": True, "http_status": 302,
            "redirect_location": "https://impl.workday.com/microsoft_dpt6/login.flex",
        }})
        assert v["reachable"] is True
        assert v["instance_valid"] is True
        assert v["access"] == "not_tested"

    def test_reachable_but_invalid_instance_on_invalid_url_redirect(self):
        v = fp.classify({"body": {
            "reachable": True, "http_status": 302,
            "redirect_location": "https://community.workday.com/invalid-url",
        }})
        assert v["reachable"] is True
        assert v["instance_valid"] is False

    def test_unreachable_when_no_status(self):
        v = fp.classify({"body": {"reachable": False, "http_status": None}})
        assert v["reachable"] is False
        assert v["instance_valid"] is False

    def test_reachable_via_positive_status_even_if_flag_missing(self):
        v = fp.classify({"body": {"http_status": 200}})
        assert v["reachable"] is True
        assert v["instance_valid"] is True

    def test_async_body_nested_under_final(self):
        v = fp.classify({"final": {"body": {
            "reachable": True, "http_status": 200, "redirect_location": "",
        }}})
        assert v["reachable"] is True
        assert v["instance_valid"] is True

    def test_access_is_never_tested_even_on_auth_challenge(self):
        # A 401 still proves the network path is open; we never test authz.
        v = fp.classify({"body": {"http_status": 401}})
        assert v["reachable"] is True
        assert v["access"] == "not_tested"


class TestInfra002FromLive:
    """Verdict dict -> CheckResult mapping (PASS iff reachable AND valid)."""

    def _v(self, **kw):
        base = {
            "reachable": True, "instance_valid": True, "access": "not_tested",
            "http_status": 302, "redirect_location": None, "error": None,
            "flow_id": "wf-1", "flow_name": "probe", "deleted": True,
            "cleanup_note": "", "raw": {},
        }
        base.update(kw)
        return base

    def test_reachable_valid_deleted_passes(self):
        r = _infra_002_from_live(WD_TARGET, "impl.workday.com", self._v())
        assert r.status == Status.PASSED.value
        assert r.priority == Priority.HIGH.value
        assert "Reachable from Power Platform" in r.result
        assert "authorization was not tested" in r.result.lower()

    def test_reachable_valid_but_delete_failed_warns_with_cleanup(self):
        r = _infra_002_from_live(
            WD_TARGET, "impl.workday.com",
            self._v(deleted=False, cleanup_note="delete returned 500"),
        )
        assert r.status == Status.WARNING.value
        assert "could not be auto-deleted" in r.result
        assert "Cleanup:" in r.remediation
        assert "delete returned 500" in r.remediation

    def test_invalid_instance_fails_with_workday_and_maker_roles(self):
        r = _infra_002_from_live(
            WD_TARGET, "impl.workday.com",
            self._v(instance_valid=False,
                    redirect_location="https://community.workday.com/invalid-url"),
        )
        assert r.status == Status.FAILED.value
        assert "is NOT valid" in r.result
        assert "invalid-url" in r.result
        assert Role.WORKDAY_ADMIN.value in r.roles
        assert Role.ESS_MAKER.value in r.roles
        assert "config.json" in r.remediation

    def test_unreachable_fails_with_pp_and_workday_roles(self):
        r = _infra_002_from_live(
            WD_TARGET, "impl.workday.com",
            self._v(reachable=False, instance_valid=False, http_status=None,
                    error="connection timed out"),
        )
        assert r.status == Status.FAILED.value
        assert "UNREACHABLE" in r.result
        assert Role.POWER_PLATFORM_ADMIN.value in r.roles
        assert Role.WORKDAY_ADMIN.value in r.roles
        assert "allowlist" in r.remediation.lower()

    def test_failed_and_not_deleted_keeps_fail_and_appends_cleanup(self):
        r = _infra_002_from_live(
            WD_TARGET, "impl.workday.com",
            self._v(reachable=False, instance_valid=False, http_status=None,
                    deleted=False, cleanup_note="flow stuck"),
        )
        assert r.status == Status.FAILED.value
        assert "Cleanup:" in r.remediation


class TestInfra002CheckTcpPath:
    """check_hr_system_reachability — default/fallback local TCP probe."""

    @patch("flightcheck.checks.infrastructure.ssl.create_default_context")
    @patch("flightcheck.checks.infrastructure.socket.socket")
    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_success,
    )
    def test_tcp_default_pass_notes_local_boundary(self, _dns, _sock, mock_ssl_ctx):
        _wire_tls_ok(mock_ssl_ctx)
        runner = SimpleNamespace(live_network_probe=False, probe_target_url=WD_TARGET)

        r = _infra_002(check_hr_system_reachability(runner))

        assert r.status == Status.PASSED.value
        assert r.priority == Priority.HIGH.value
        assert "THIS MACHINE" in r.result
        assert "not Power Platform's egress boundary" in r.result
        assert "--live-network-probe" in r.result

    @patch(
        "flightcheck.checks.infrastructure.socket.getaddrinfo",
        side_effect=_mock_getaddrinfo_fail,
    )
    def test_tcp_default_dns_failure_fails_with_firewall_remediation(self, _dns):
        runner = SimpleNamespace(live_network_probe=False, probe_target_url=WD_TARGET)

        r = _infra_002(check_hr_system_reachability(runner))

        assert r.status == Status.FAILED.value
        assert "UNREACHABLE from this machine" in r.result
        assert "allowlist" in r.remediation.lower()

    def test_skip_when_no_target_configured(self, monkeypatch):
        monkeypatch.setattr(infra, "_load_workday_connect_config", lambda: {})
        runner = SimpleNamespace(live_network_probe=False, probe_target_url=None)

        r = _infra_002(check_hr_system_reachability(runner))

        assert r.status == Status.SKIPPED.value
        assert "no target URL configured" in r.result

    def test_skip_when_target_has_no_host(self):
        runner = SimpleNamespace(live_network_probe=False, probe_target_url="https://")

        r = _infra_002(check_hr_system_reachability(runner))

        assert r.status == Status.SKIPPED.value
        assert "not a valid URL" in r.result

    def test_probe_target_url_override_beats_connect_config(self, monkeypatch):
        monkeypatch.setattr(infra, "_load_workday_connect_config",
                            lambda: {"baseUrl": "https://from-config.example"})
        runner = SimpleNamespace(probe_target_url="https://override.example/tenant")
        assert _resolve_probe_target(runner) == "https://override.example/tenant"

    def test_connect_config_baseurl_used_when_no_override(self, monkeypatch):
        monkeypatch.setattr(infra, "_load_workday_connect_config",
                            lambda: {"baseUrl": "https://from-config.example/t"})
        runner = SimpleNamespace(probe_target_url=None)
        assert _resolve_probe_target(runner) == "https://from-config.example/t"


class TestInfra002CheckLivePath:
    """check_hr_system_reachability — consent-gated live probe + fallbacks."""

    def test_live_requested_but_no_signin_context_falls_back_to_tcp(self, monkeypatch):
        monkeypatch.setattr(
            infra, "probe_endpoint",
            lambda host, port=443: ProbeResult(
                host=host, port=port, dns_ok=True, tcp_ok=True, tls_ok=True,
                tls_version="TLSv1.3"),
        )
        runner = SimpleNamespace(
            live_network_probe=True, probe_target_url=WD_TARGET,
            pp_admin=None, env_id=None, env_url=None, dv_token=None,
        )

        r = _infra_002(check_hr_system_reachability(runner))

        assert r.status == Status.PASSED.value
        assert "Live probe unavailable" in r.result
        assert "--scope full" in r.result

    def test_live_probe_error_falls_back_to_tcp_with_reason(self, monkeypatch):
        monkeypatch.setattr(
            infra, "probe_endpoint",
            lambda host, port=443: ProbeResult(
                host=host, port=port, dns_ok=False, error_layer="dns",
                dns_ms=1.0, error_message="DNS resolution failed"),
        )

        def boom(**kwargs):
            raise fp.FlowProbeError("DLP policy blocks the HTTP connector")

        monkeypatch.setattr(fp, "run_live_probe", boom)

        r = _infra_002(check_hr_system_reachability(_live_runner()))

        assert r.status == Status.FAILED.value
        assert "Live probe unavailable" in r.result
        assert "DLP policy blocks the HTTP connector" in r.result

    def test_live_success_maps_verdict_and_passes_target(self, monkeypatch):
        captured = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {
                "reachable": True, "instance_valid": True, "access": "not_tested",
                "http_status": 302, "redirect_location": None, "error": None,
                "flow_id": "wf", "flow_name": "probe", "deleted": True,
                "cleanup_note": "", "raw": {},
            }

        monkeypatch.setattr(fp, "run_live_probe", fake_run)

        r = _infra_002(check_hr_system_reachability(_live_runner()))

        assert r.status == Status.PASSED.value
        assert "Reachable from Power Platform" in r.result
        assert captured["target_url"] == WD_TARGET
        assert captured["env_id"] == FAKE_ENV_ID
        assert captured["env_url"] == FAKE_DATAVERSE_URL

    def test_live_invalid_instance_maps_to_fail(self, monkeypatch):
        monkeypatch.setattr(fp, "run_live_probe", lambda **kw: {
            "reachable": True, "instance_valid": False, "access": "not_tested",
            "http_status": 302,
            "redirect_location": "https://community.workday.com/invalid-url",
            "error": None, "flow_id": "wf", "flow_name": "probe",
            "deleted": True, "cleanup_note": "", "raw": {},
        })

        r = _infra_002(check_hr_system_reachability(_live_runner()))

        assert r.status == Status.FAILED.value
        assert "is NOT valid" in r.result


class TestInfra002DataverseWorkflowLifecycle:
    """flow_probe Dataverse workflow ops (documented tier — see INDEX.md).

    Shapes per MS Learn 'workflow' entity docs: create returns the row
    (``workflowid`` in body, else ``OData-EntityId`` header); delete is the
    net-zero cleanup the maker emphasised, and must survive the intermittent
    500 'There is no active transaction' error.
    """

    def test_create_flow_reads_workflowid_from_body(self, monkeypatch):
        resp = MagicMock(status_code=201, content=b'{"workflowid":"wf-123"}')
        resp.json.return_value = {"workflowid": "wf-123"}
        posted = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            posted["url"] = url
            posted["json"] = json
            return resp

        monkeypatch.setattr(fp.requests, "post", fake_post)

        wid = fp.create_flow(FAKE_DATAVERSE_URL, FAKE_TOKEN, "probe", WD_TARGET)

        assert wid == "wf-123"
        assert posted["url"].endswith("/api/data/v9.2/workflows")
        assert posted["json"]["category"] == fp.WORKFLOW_CATEGORY_MODERN_FLOW

    def test_create_flow_reads_id_from_odata_entityid_header(self, monkeypatch):
        resp = MagicMock(status_code=204, content=b"")
        resp.headers = {
            "OData-EntityId":
                "https://x/api/data/v9.2/workflows(aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee)",
        }
        monkeypatch.setattr(fp.requests, "post", lambda *a, **k: resp)

        wid = fp.create_flow(FAKE_DATAVERSE_URL, FAKE_TOKEN, "probe", WD_TARGET)

        assert wid == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_create_flow_raises_on_http_error(self, monkeypatch):
        resp = MagicMock(status_code=403, content=b"{}")
        resp.json.return_value = {"error": {"message": "privilege missing"}}
        monkeypatch.setattr(fp.requests, "post", lambda *a, **k: resp)

        with pytest.raises(fp.FlowProbeError) as exc:
            fp.create_flow(FAKE_DATAVERSE_URL, FAKE_TOKEN, "probe", WD_TARGET)
        assert "403" in str(exc.value)

    def test_delete_flow_retries_on_500_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(fp.time, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(fp.requests, "patch",
                            lambda *a, **k: MagicMock(status_code=200))
        calls = {"n": 0}

        def fake_delete(url, headers=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                m = MagicMock(status_code=500)
                m.json.return_value = {
                    "error": {"message": "There is no active transaction"}}
                return m
            return MagicMock(status_code=204)

        monkeypatch.setattr(fp.requests, "delete", fake_delete)

        fp.delete_flow(FAKE_DATAVERSE_URL, FAKE_TOKEN, "wf", attempts=5)

        assert calls["n"] == 2  # retried once, then succeeded

    def test_delete_flow_treats_404_as_success(self, monkeypatch):
        monkeypatch.setattr(fp.time, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(fp.requests, "patch",
                            lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr(fp.requests, "delete",
                            lambda *a, **k: MagicMock(status_code=404))

        fp.delete_flow(FAKE_DATAVERSE_URL, FAKE_TOKEN, "wf")  # must not raise

    def test_delete_flow_raises_after_exhausting_attempts(self, monkeypatch):
        monkeypatch.setattr(fp.time, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(fp.requests, "patch",
                            lambda *a, **k: MagicMock(status_code=200))
        m = MagicMock(status_code=500)
        m.json.return_value = {"error": {"message": "still no transaction"}}
        monkeypatch.setattr(fp.requests, "delete", lambda *a, **k: m)

        with pytest.raises(fp.FlowProbeError):
            fp.delete_flow(FAKE_DATAVERSE_URL, FAKE_TOKEN, "wf", attempts=3)


class TestInfra002RunLiveProbeNetZero:
    """run_live_probe orchestration — the flow is ALWAYS deleted (net-zero)."""

    def _patch_chain(self, monkeypatch, *, trigger, delete_raises=False):
        monkeypatch.setattr(fp.time, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(fp, "create_flow", lambda *a, **k: "wf-1")
        monkeypatch.setattr(fp, "set_flow_state", lambda *a, **k: None)
        monkeypatch.setattr(fp, "trigger_and_read", lambda *a, **k: trigger)
        deleted = {"called": False}

        def fake_delete(*a, **k):
            deleted["called"] = True
            if delete_raises:
                raise fp.FlowProbeError("delete failed 500")

        monkeypatch.setattr(fp, "delete_flow", fake_delete)
        return deleted

    def test_happy_path_deletes_and_classifies(self, monkeypatch):
        deleted = self._patch_chain(monkeypatch, trigger={"body": {
            "reachable": True, "http_status": 302, "redirect_location": ""}})
        pp = SimpleNamespace(list_callback_url=lambda env_id, flow_id: "https://cb")

        v = fp.run_live_probe(env_url=FAKE_DATAVERSE_URL, dv_token=FAKE_TOKEN,
                              pp_admin=pp, env_id=FAKE_ENV_ID, target_url=WD_TARGET)

        assert deleted["called"] is True
        assert v["reachable"] is True and v["instance_valid"] is True
        assert v["deleted"] is True
        assert v["flow_id"] == "wf-1"

    def test_delete_runs_even_when_trigger_raises(self, monkeypatch):
        deleted = self._patch_chain(monkeypatch, trigger=None)
        monkeypatch.setattr(
            fp, "trigger_and_read",
            lambda *a, **k: (_ for _ in ()).throw(fp.FlowProbeError("invoke failed")),
        )
        pp = SimpleNamespace(list_callback_url=lambda env_id, flow_id: "https://cb")

        with pytest.raises(fp.FlowProbeError):
            fp.run_live_probe(env_url=FAKE_DATAVERSE_URL, dv_token=FAKE_TOKEN,
                              pp_admin=pp, env_id=FAKE_ENV_ID, target_url=WD_TARGET)

        assert deleted["called"] is True  # net-zero: deleted in finally

    def test_delete_failure_sets_cleanup_note_and_not_deleted(self, monkeypatch):
        deleted = self._patch_chain(monkeypatch, delete_raises=True, trigger={"body": {
            "reachable": True, "http_status": 200, "redirect_location": ""}})
        pp = SimpleNamespace(list_callback_url=lambda env_id, flow_id: "https://cb")

        v = fp.run_live_probe(env_url=FAKE_DATAVERSE_URL, dv_token=FAKE_TOKEN,
                              pp_admin=pp, env_id=FAKE_ENV_ID, target_url=WD_TARGET)

        assert deleted["called"] is True
        assert v["deleted"] is False
        assert "could not be deleted" in v["cleanup_note"]

    def test_missing_callback_url_raises_but_still_deletes(self, monkeypatch):
        deleted = self._patch_chain(monkeypatch, trigger={"body": {}})
        pp = SimpleNamespace(list_callback_url=lambda env_id, flow_id: None)

        with pytest.raises(fp.FlowProbeError):
            fp.run_live_probe(env_url=FAKE_DATAVERSE_URL, dv_token=FAKE_TOKEN,
                              pp_admin=pp, env_id=FAKE_ENV_ID, target_url=WD_TARGET)

        assert deleted["called"] is True
