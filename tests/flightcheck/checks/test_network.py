# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the vendor network reachability
FlightCheck checks (NET-001 / NET-002 / NET-003).

Cardinal-rule note: this is the deliberate exception to the
"validated/validatable/documented mock required" rule documented in
``tests/AGENTS.md`` and the "API tier registry" of
``tests/fixtures/cassettes/INDEX.md`` (see the "Vendor TCP/HTTPS
reachability" row). The check is a transport-level diagnostic — it does
NOT consume vendor API response contracts — so the tier system does not
apply. Instead, ``run_network_checks`` accepts injectable ``TcpProber``
and ``HttpsProber`` arguments, and these tests substitute deterministic
fake implementations for the six relevant failure modes (refused,
timeout, DNS failure, TLS error, 4xx-style, 5xx).

There is intentionally no ``require_validated_mock`` here and no
``responses`` / ``respx`` involvement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from flightcheck.checks.network import (
    ProbeResult,
    ProbeStatus,
    run_network_checks,
)


# ───────────────────────────────────────────────────────────────────────
# Fakes
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    config: dict[str, Any]


class _ScriptedProber:
    """Returns a pre-programmed ``ProbeResult`` per ``host:port`` key.

    Tests construct one of these with a dict mapping ``"host:port"`` to a
    ``ProbeResult`` and pass it as ``tcp_prober`` / ``https_prober``.
    Unknown hosts default to ``REACHABLE`` so test setups stay terse —
    individual tests override only the hosts they care about.
    """

    def __init__(self, scripted: dict[str, ProbeResult] | None = None,
                 default_status: str = ProbeStatus.REACHABLE):
        self.scripted = scripted or {}
        self.default_status = default_status
        self.calls: list[tuple[str, int, float]] = []

    def probe(self, host: str, port: int, timeout: float) -> ProbeResult:
        self.calls.append((host, port, timeout))
        key = f"{host}:{port}"
        if key in self.scripted:
            return self.scripted[key]
        return ProbeResult(host=host, port=port, status=self.default_status,
                           detail=f"default {self.default_status}")


# ───────────────────────────────────────────────────────────────────────
# Fixture catalog — minimal, deterministic. Avoids using the real
# required-endpoints.json so the tests don't break if vendor endpoints
# are added later.
# ───────────────────────────────────────────────────────────────────────

_FIXTURE_CATALOG = {
    "integrations": [
        {
            "name": "Workday",
            "required": True,
            "hostingPattern": "Data center based",
            "ipRangeNote": "Workday IP ranges per data center at https://community.workday.com",
            "endpoints": [
                {"host": "wd2-impl-services1.workday.com", "port": 443, "purpose": "Impl services"},
                {"host": "wd5.myworkday.com", "port": 443, "purpose": "Prod services"},
            ],
        },
        {
            "name": "ServiceNow",
            "required": True,
            "hostingPattern": "Instance-prefixed hostname",
            "ipRangeNote": "ServiceNow IP ranges at https://docs.servicenow.com",
            "endpoints": [
                {"host": "{instance}.service-now.com", "port": 443, "purpose": "Instance API"},
            ],
        },
        {
            "name": "SAP SuccessFactors",
            "required": False,
            "hostingPattern": "Data center based",
            "ipRangeNote": "SAP DC IP ranges at https://help.sap.com",
            "endpoints": [
                {"host": "api.successfactors.com", "port": 443, "purpose": "SF API"},
            ],
        },
    ],
}


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "required-endpoints.json"
    path.write_text(json.dumps(_FIXTURE_CATALOG), encoding="utf-8")
    return path


def _runner(network_config: dict | None = None) -> _MinimalRunner:
    return _MinimalRunner(config={"network": network_config or {}})


def _by_id(results, checkpoint_id):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    if len(matches) != 1:
        ids = [r.checkpoint_id for r in results]
        raise AssertionError(f"Expected exactly one {checkpoint_id} in {ids}")
    return matches[0]


# ───────────────────────────────────────────────────────────────────────
# Happy path
# ───────────────────────────────────────────────────────────────────────


class TestAllReachable:
    def test_default_selects_required_only(self, catalog_path: Path) -> None:
        """No ``network.integrations`` in config → required integrations are
        probed, optional ones are Skipped. Matches the source PS behavior."""
        runner = _runner()  # no integrations key
        tcp = _ScriptedProber()
        https = _ScriptedProber()

        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )

        wd = _by_id(results, "NET-001")
        assert wd.status == "Passed"
        assert "2/2 reachable" in wd.result

        sn = _by_id(results, "NET-002")
        # No servicenow_instance configured -> all hosts are placeholders -> Skipped
        assert sn.status == "Skipped"

        sap = _by_id(results, "NET-003")
        # Optional and not in selected_names default (required only) -> Skipped
        assert sap.status == "Skipped"
        assert "not in network.integrations" in sap.result

    def test_explicit_integrations_list_probes_each(self, catalog_path: Path) -> None:
        runner = _runner({
            "integrations": ["Workday", "ServiceNow", "SAP SuccessFactors"],
            "servicenow_instance": "contoso",
        })
        tcp = _ScriptedProber()
        https = _ScriptedProber()

        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )

        assert _by_id(results, "NET-001").status == "Passed"
        assert _by_id(results, "NET-002").status == "Passed"
        assert _by_id(results, "NET-003").status == "Passed"

        # Confirm placeholder substitution happened.
        sn_hosts = [call[0] for call in tcp.calls]
        assert "contoso.service-now.com" in sn_hosts
        assert "{instance}.service-now.com" not in sn_hosts


# ───────────────────────────────────────────────────────────────────────
# Failure modes — exactly the six the docstring promises to cover
# ───────────────────────────────────────────────────────────────────────


class TestFailureBranches:
    def test_tcp_refused_is_failed(self, catalog_path: Path) -> None:
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber({
            "wd5.myworkday.com:443": ProbeResult(
                host="wd5.myworkday.com", port=443,
                status=ProbeStatus.REFUSED,
                detail="TCP 443 refused/unreachable",
            ),
        })
        https = _ScriptedProber()

        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        wd = _by_id(results, "NET-001")
        assert wd.status == "Failed"
        assert "1/2 reachable" in wd.result
        assert "FAIL" in wd.result
        assert "firewall" in wd.remediation.lower()
        assert "export-firewall-requirements" in wd.remediation

    def test_tcp_timeout_is_failed(self, catalog_path: Path) -> None:
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber({
            "wd2-impl-services1.workday.com:443": ProbeResult(
                host="wd2-impl-services1.workday.com", port=443,
                status=ProbeStatus.TIMEOUT,
                detail="TCP 443 timed out after 5.0s",
            ),
        })
        https = _ScriptedProber()
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        assert _by_id(results, "NET-001").status == "Failed"

    def test_dns_failure_is_failed(self, catalog_path: Path) -> None:
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber({
            "wd2-impl-services1.workday.com:443": ProbeResult(
                host="wd2-impl-services1.workday.com", port=443,
                status=ProbeStatus.DNS_FAILURE,
                detail="DNS resolution failed",
            ),
            "wd5.myworkday.com:443": ProbeResult(
                host="wd5.myworkday.com", port=443,
                status=ProbeStatus.DNS_FAILURE,
                detail="DNS resolution failed",
            ),
        })
        https = _ScriptedProber()
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        wd = _by_id(results, "NET-001")
        assert wd.status == "Failed"
        assert "DNS resolution failed" in wd.result

    def test_tls_error_is_warning(self, catalog_path: Path) -> None:
        """TCP open + TLS handshake failure = likely SSL inspection. Surface
        as Warning, not Failed — the network is reachable, just intercepted."""
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber()  # All TCP OK
        https = _ScriptedProber({
            "wd2-impl-services1.workday.com:443": ProbeResult(
                host="wd2-impl-services1.workday.com", port=443,
                status=ProbeStatus.TLS_ERROR,
                detail="TLS handshake failed",
            ),
        })
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        wd = _by_id(results, "NET-001")
        assert wd.status == "Warning"
        assert "1 warning" in wd.result
        assert "TLS" in wd.remediation or "SSL" in wd.remediation

    def test_http_5xx_is_warning(self, catalog_path: Path) -> None:
        """5xx means vendor reachable but something server-side; surface as
        warning so deployment teams can retry or escalate to the vendor."""
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber()
        https = _ScriptedProber({
            "wd2-impl-services1.workday.com:443": ProbeResult(
                host="wd2-impl-services1.workday.com", port=443,
                status=ProbeStatus.HTTP_5XX,
                detail="HTTPS 503 server error",
            ),
        })
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        assert _by_id(results, "NET-001").status == "Warning"

    def test_https_4xx_is_still_reachable(self, catalog_path: Path) -> None:
        """4xx (e.g. 401, 403, 404) means TLS + HTTP layer worked. The probe
        intentionally does not authenticate, so a 401 IS reachable."""
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber()
        https = _ScriptedProber({
            "wd2-impl-services1.workday.com:443": ProbeResult(
                host="wd2-impl-services1.workday.com", port=443,
                status=ProbeStatus.REACHABLE,
                detail="HTTPS 401",
            ),
            "wd5.myworkday.com:443": ProbeResult(
                host="wd5.myworkday.com", port=443,
                status=ProbeStatus.REACHABLE,
                detail="HTTPS 404",
            ),
        })
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        assert _by_id(results, "NET-001").status == "Passed"


# ───────────────────────────────────────────────────────────────────────
# Selection / configuration edge cases
# ───────────────────────────────────────────────────────────────────────


class TestSelectionAndConfig:
    def test_servicenow_without_instance_is_skipped_with_remediation(
        self, catalog_path: Path
    ) -> None:
        runner = _runner({"integrations": ["ServiceNow"]})
        tcp = _ScriptedProber()
        https = _ScriptedProber()
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        sn = _by_id(results, "NET-002")
        assert sn.status == "Skipped"
        assert "network.servicenow_instance" in sn.remediation

    def test_integration_not_selected_is_skipped(self, catalog_path: Path) -> None:
        runner = _runner({"integrations": ["Workday"]})  # ServiceNow not opted-in
        tcp = _ScriptedProber()
        https = _ScriptedProber()
        results = run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        sn = _by_id(results, "NET-002")
        assert sn.status == "Skipped"
        assert "not in network.integrations" in sn.result

    def test_no_https_call_when_tcp_blocked(self, catalog_path: Path) -> None:
        """Short-circuit guarantee: if TCP is closed, we don't waste a 5s
        timeout on a follow-up HTTPS attempt that's also going to fail."""
        runner = _runner({"integrations": ["Workday"]})
        tcp = _ScriptedProber({
            "wd2-impl-services1.workday.com:443": ProbeResult(
                host="wd2-impl-services1.workday.com", port=443,
                status=ProbeStatus.REFUSED, detail="refused",
            ),
            "wd5.myworkday.com:443": ProbeResult(
                host="wd5.myworkday.com", port=443,
                status=ProbeStatus.REFUSED, detail="refused",
            ),
        })
        https = _ScriptedProber()
        run_network_checks(
            runner, tcp_prober=tcp, https_prober=https,
            config_path=str(catalog_path),
        )
        # HTTPS prober should have been called zero times — TCP failed
        # for every host so the short-circuit kicked in.
        assert https.calls == []

    def test_missing_config_file_returns_error_result(self, tmp_path: Path) -> None:
        """Defensive: tampered repo with a missing config doesn't crash;
        emits a single ERROR result so the operator sees what to fix."""
        runner = _runner()
        missing_path = tmp_path / "does-not-exist.json"
        results = run_network_checks(
            runner, tcp_prober=_ScriptedProber(), https_prober=_ScriptedProber(),
            config_path=str(missing_path),
        )
        assert len(results) == 1
        assert results[0].checkpoint_id == "NET-CONFIG"
        assert results[0].status == "Error"
