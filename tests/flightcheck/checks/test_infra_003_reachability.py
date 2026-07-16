# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for INFRA-003 external endpoint reachability (default local probe).

The default INFRA-003 path uses only Python stdlib (socket/ssl) via the shared
``probe_endpoint()`` helper, so no external API mock or cassette validation is
required (no ``require_validated_mock`` gate). These tests patch
``probe_endpoint`` to drive each reachability outcome and assert INFRA-003's
enumeration, status bucketing, five-field remediation, and roles.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from flightcheck.checks.infrastructure import (
    ProbeResult,
    _discover_external_endpoints,
    check_external_endpoint_reachability,
)
from flightcheck.runner import Priority, Role, Status


# ───────────────────────────────────────────────────────────────────────
# ProbeResult builders (one per reachability outcome)
# ───────────────────────────────────────────────────────────────────────


def _reachable(host: str) -> ProbeResult:
    return ProbeResult(
        host=host, port=443, dns_ok=True, tcp_ok=True, tls_ok=True,
        resolved_ip="203.0.113.10", dns_ms=5.0, tcp_ms=12.0, tls_ms=20.0,
        tls_version="TLSv1.3",
    )


def _dns_fail(host: str) -> ProbeResult:
    return ProbeResult(
        host=host, port=443, dns_ok=False, dns_ms=8.0,
        error_layer="dns",
        error_message=f"DNS resolution failed for {host}: name not known",
    )


def _refused(host: str) -> ProbeResult:
    return ProbeResult(
        host=host, port=443, dns_ok=True, resolved_ip="203.0.113.10",
        dns_ms=5.0, tcp_ms=3.0, error_layer="tcp",
        error_message=(
            f"TCP connection to {host}:443 (203.0.113.10) refused — "
            f"port closed or firewall sending RST"
        ),
    )


def _timeout(host: str) -> ProbeResult:
    return ProbeResult(
        host=host, port=443, dns_ok=True, resolved_ip="203.0.113.10",
        dns_ms=5.0, tcp_ms=10000.0, error_layer="tcp",
        error_message=(
            f"TCP connection to {host}:443 (203.0.113.10) timed out after 10.0s "
            f"— firewall may be silently dropping packets"
        ),
    )


def _tls_fail(host: str) -> ProbeResult:
    return ProbeResult(
        host=host, port=443, dns_ok=True, tcp_ok=True, resolved_ip="203.0.113.10",
        dns_ms=5.0, tcp_ms=12.0, tls_ms=30.0, error_layer="tls",
        error_message=f"TLS handshake failed for {host}:443: certificate verify failed",
    )


def _runner(connections: dict[str, Any], *, live_probe: bool = False) -> SimpleNamespace:
    return SimpleNamespace(config={"connections": connections}, live_probe=live_probe)


def _patch_probe(mapping: dict[str, ProbeResult]):
    """Patch probe_endpoint to return a crafted ProbeResult keyed by host."""

    def fake(host: str, port: int = 443, timeout: float = 10.0) -> ProbeResult:
        assert host in mapping, f"unexpected host probed: {host}"
        return mapping[host]

    return patch("flightcheck.checks.infrastructure.probe_endpoint", side_effect=fake)


def _rows_by_status(results: list) -> dict[str, Any]:
    return {r.status: r for r in results}


# ───────────────────────────────────────────────────────────────────────
# AC1 — enumeration
# ───────────────────────────────────────────────────────────────────────


class TestEnumeration:
    def test_reads_workday_baseurl_and_servicenow_instanceurl(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://impl.workday.example.com"},
            "ServiceNow": {"instanceUrl": "https://dev12345.service-now.example"},
        })
        eps = _discover_external_endpoints(runner)
        by_system = {e.system: e for e in eps}

        assert by_system["Workday"].host == "impl.workday.example.com"
        assert by_system["Workday"].role == Role.WORKDAY_ADMIN.value
        assert by_system["ServiceNow"].host == "dev12345.service-now.example"
        assert by_system["ServiceNow"].role == Role.SERVICENOW_ADMIN.value

    def test_unknown_system_maps_to_custom_http_power_platform_role(self):
        runner = _runner({"AcmeHR": {"url": "https://api.acme.example"}})
        eps = _discover_external_endpoints(runner)

        assert len(eps) == 1
        assert eps[0].role == Role.POWER_PLATFORM_ADMIN.value

    def test_deduplicates_by_host(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://impl.workday.example.com"},
            "WorkdayDup": {"baseUrl": "https://impl.workday.example.com/extra"},
        })
        eps = _discover_external_endpoints(runner)
        assert len(eps) == 1

    def test_entries_without_url_are_skipped(self):
        runner = _runner({"Workday": {"tenant": "contoso"}})
        assert _discover_external_endpoints(runner) == []

    def test_extracts_explicit_port_from_url(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://impl.workday.example.com:8443/ccx"},
            "ServiceNow": {"instanceUrl": "https://dev.service-now.example"},
        })
        by_system = {e.system: e for e in _discover_external_endpoints(runner)}

        assert by_system["Workday"].port == 8443
        assert by_system["ServiceNow"].port == 443  # default when omitted

    def test_same_host_different_port_not_deduplicated(self):
        runner = _runner({
            "A": {"url": "https://host.example.com:8443"},
            "B": {"url": "https://host.example.com:9443"},
        })
        eps = _discover_external_endpoints(runner)
        assert {e.port for e in eps} == {8443, 9443}

    def test_probe_called_with_extracted_port(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://impl.workday.example.com:8443"},
        })
        seen: list[int] = []

        def fake(host: str, port: int = 443, timeout: float = 10.0) -> ProbeResult:
            seen.append(port)
            return _reachable(host)

        with patch(
            "flightcheck.checks.infrastructure.probe_endpoint", side_effect=fake
        ):
            check_external_endpoint_reachability(runner)

        assert seen == [8443]


# ───────────────────────────────────────────────────────────────────────
# AC2 / AC3 / AC4 — status mapping
# ───────────────────────────────────────────────────────────────────────


class TestReachabilityStatus:
    def test_all_reachable_passes(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://wd.example.com"},
            "ServiceNow": {"instanceUrl": "https://sn.example.com"},
        })
        mapping = {"wd.example.com": _reachable("wd.example.com"),
                   "sn.example.com": _reachable("sn.example.com")}
        with _patch_probe(mapping):
            results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.PASSED.value
        assert row.priority == Priority.CRITICAL.value
        assert "wd.example.com" in row.result
        assert "sn.example.com" in row.result
        # Necessary-but-not-sufficient caveat is surfaced on PASS.
        assert "necessary but not sufficient" in row.result
        assert row.remediation == ""

    def test_one_blocked_fails_and_names_endpoint_and_hop(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://wd.example.com"},
            "ServiceNow": {"instanceUrl": "https://sn.example.com"},
        })
        mapping = {"wd.example.com": _reachable("wd.example.com"),
                   "sn.example.com": _refused("sn.example.com")}
        with _patch_probe(mapping):
            results = check_external_endpoint_reachability(runner)

        by_status = _rows_by_status(results)
        assert Status.FAILED.value in by_status
        assert Status.PASSED.value in by_status

        fail = by_status[Status.FAILED.value]
        # Names the endpoint URL and the blocking hop (AC3).
        assert "https://sn.example.com" in fail.result
        assert "UNREACHABLE at TCP connect" in fail.result
        # Five-field role-aware finding (AC5) + manual verification (Step G).
        assert "Impact:" in fail.remediation
        assert "Probable cause:" in fail.remediation
        assert "What it implies:" in fail.remediation
        assert "Next steps:" in fail.remediation
        assert "InfoSec" in fail.remediation
        assert "outbound IP" in fail.remediation.lower() or "outbound-ip" in fail.doc_link
        # Roles: owning system admin + Power Platform admin.
        assert Role.SERVICENOW_ADMIN.value in fail.roles
        assert Role.POWER_PLATFORM_ADMIN.value in fail.roles

    def test_dns_failure_fails(self):
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        with _patch_probe({"wd.example.com": _dns_fail("wd.example.com")}):
            results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.FAILED.value
        assert "UNREACHABLE at DNS resolution" in row.result

    def test_tls_failure_warns(self):
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        with _patch_probe({"wd.example.com": _tls_fail("wd.example.com")}):
            results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.WARNING.value
        assert "PARTIALLY reachable" in row.result
        assert "TLS handshake failed" in row.result
        assert "interception" in row.remediation.lower()

    def test_timeout_warns_not_fails(self):
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        with _patch_probe({"wd.example.com": _timeout("wd.example.com")}):
            results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.WARNING.value
        assert "timed out" in row.result.lower()


# ───────────────────────────────────────────────────────────────────────
# AC7 / principle 7 — bucketing, empty case, idempotency, live-probe note
# ───────────────────────────────────────────────────────────────────────


class TestBucketingAndEdges:
    def test_no_endpoints_is_not_configured(self):
        runner = _runner({})
        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        assert results[0].status == Status.NOT_CONFIGURED.value
        assert "Nothing to probe" in results[0].result

    def test_multiple_unreachable_collapse_to_one_fail_row(self):
        runner = _runner({
            "Workday": {"baseUrl": "https://wd.example.com"},
            "SAPSuccessFactors": {"apiUrl": "https://sf.example.com"},
        })
        mapping = {"wd.example.com": _refused("wd.example.com"),
                   "sf.example.com": _dns_fail("sf.example.com")}
        with _patch_probe(mapping):
            results = check_external_endpoint_reachability(runner)

        fail_rows = [r for r in results if r.status == Status.FAILED.value]
        assert len(fail_rows) == 1  # principle 7: one row per status
        assert "https://wd.example.com" in fail_rows[0].result
        assert "https://sf.example.com" in fail_rows[0].result
        assert Role.WORKDAY_ADMIN.value in fail_rows[0].roles
        assert Role.SAP_ADMIN.value in fail_rows[0].roles

    def test_probe_exception_is_unverifiable_warn_not_crash(self):
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        with patch(
            "flightcheck.checks.infrastructure.probe_endpoint",
            side_effect=RuntimeError("boom"),
        ):
            results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        assert results[0].status == Status.WARNING.value
        assert "UNVERIFIABLE" in results[0].result

    def test_idempotent_same_result_and_no_side_effects(self):
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        mapping = {"wd.example.com": _reachable("wd.example.com")}
        with _patch_probe(mapping):
            first = check_external_endpoint_reachability(runner)
        with _patch_probe(mapping):
            second = check_external_endpoint_reachability(runner)

        assert [(r.status, r.result) for r in first] == [
            (r.status, r.result) for r in second
        ]

    def test_live_probe_requested_notes_egress_probe_pending(self):
        runner = _runner(
            {"Workday": {"baseUrl": "https://wd.example.com"}}, live_probe=True
        )
        with _patch_probe({"wd.example.com": _reachable("wd.example.com")}):
            results = check_external_endpoint_reachability(runner)

        assert results[0].status == Status.PASSED.value
        assert "not yet available" in results[0].result

    def test_every_row_sets_roles(self):
        """test_check_roles.py enforces roles on every constructor."""
        runner = _runner({
            "Workday": {"baseUrl": "https://wd.example.com"},
            "ServiceNow": {"instanceUrl": "https://sn.example.com"},
        })
        mapping = {"wd.example.com": _reachable("wd.example.com"),
                   "sn.example.com": _refused("sn.example.com")}
        with _patch_probe(mapping):
            results = check_external_endpoint_reachability(runner)

        assert results  # non-empty
        for row in results:
            assert row.roles, f"{row.status} row missing roles"
            assert row.checkpoint_id == "INFRA-003"
