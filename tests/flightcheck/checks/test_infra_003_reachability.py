# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for INFRA-003 external endpoint reachability, NON-egress behavior.

INFRA-003 tests reachability only from the Power Platform environment's own
egress (the opt-in ``--runtime-reachability`` flow; see
test_infra_003_live_probe.py). The local TCP/TLS probe was removed: it runs
from the maker's machine, not the runtime egress, and never sends HTTP, so it
cannot prove the runtime path. When the egress probe does not run, the check
returns MANUAL guidance instead. These tests cover endpoint enumeration, the
NOT_CONFIGURED empty case, and that MANUAL-guidance path (default run, requested
but prerequisites missing, and operator-declined, including clickable links).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from flightcheck.checks.infrastructure import (
    _discover_external_endpoints,
    check_external_endpoint_reachability,
)
from flightcheck.runner import Priority, Role, Status


# ───────────────────────────────────────────────────────────────────────
# Runner builders
# ───────────────────────────────────────────────────────────────────────


def _runner(
    connections: dict[str, Any],
    *,
    runtime_reachability: bool = False,
    runtime_reachability_declined: bool = False,
) -> SimpleNamespace:
    """A runner with no egress prerequisites, so the egress probe never runs."""
    return SimpleNamespace(
        config={"connections": connections},
        runtime_reachability=runtime_reachability,
        runtime_reachability_declined=runtime_reachability_declined,
    )


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


# ───────────────────────────────────────────────────────────────────────
# Empty case + MANUAL guidance when the egress probe does not run
# ───────────────────────────────────────────────────────────────────────


class TestManualGuidanceWhenNoEgressProbe:
    def test_no_endpoints_is_not_configured(self):
        results = check_external_endpoint_reachability(_runner({}))

        assert len(results) == 1
        assert results[0].status == Status.NOT_CONFIGURED.value
        assert "Nothing to probe" in results[0].result

    def test_default_run_returns_manual_guidance_not_a_probe(self):
        # No --runtime-reachability: reachability is not tested; the check hands
        # back MANUAL guidance rather than a (meaningless) laptop probe.
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.MANUAL.value
        assert row.priority == Priority.CRITICAL.value
        # Names the endpoint and states reachability was NOT tested.
        assert "https://wd.example.com" in row.result
        assert "NOT tested" in row.result
        assert "own egress" in row.result
        # Points the operator at the egress probe + manual verification.
        assert "--runtime-reachability" in row.remediation
        assert "verify" in row.remediation.lower() or "allowlist" in row.remediation.lower()
        # Roles: owning system admin + Power Platform admin.
        assert Role.WORKDAY_ADMIN.value in row.roles
        assert Role.POWER_PLATFORM_ADMIN.value in row.roles

    def test_requested_but_prereqs_missing_is_manual_with_reason(self):
        # --runtime-reachability requested, but no pp_admin / env / token on the
        # runner, so the egress probe can't run; explain why, still MANUAL.
        runner = _runner(
            {"Workday": {"baseUrl": "https://wd.example.com"}}, runtime_reachability=True
        )
        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.MANUAL.value
        assert "could not run" in row.result
        assert "missing" in row.result

    def test_declined_egress_probe_surfaces_manual_ip_ranges_link(self):
        """When the operator declines the runtime-reachability probe, INFRA-003
        notes the skip in the result and puts the outbound-IP article +
        service-tags JSON links in the remediation so they render CLICKABLE in
        report.html (result is escaped but not linkified)."""
        from flightcheck import consent
        from flightcheck.runner import _render_check_card

        runner = _runner(
            {"Workday": {"baseUrl": "https://wd.example.com"}},
            runtime_reachability_declined=True,
        )
        results = check_external_endpoint_reachability(runner)

        row = results[0]
        assert row.status == Status.MANUAL.value
        # The skip caveat stays in result...
        assert "skipped by choice" in row.result
        # ...but the clickable links live in remediation (the linkified channel),
        # never as raw markdown in result.
        assert consent.OUTBOUND_IP_ARTICLE_URL in row.remediation
        assert consent.SERVICE_TAGS_JSON_URL in row.remediation
        assert "](http" not in row.result  # no raw markdown link leaked
        # And they actually render as clickable anchors in the report card.
        card = _render_check_card(row)
        assert card.count("<a href=") >= 2
        assert consent.OUTBOUND_IP_ARTICLE_URL in card
        assert consent.SERVICE_TAGS_JSON_URL in card

    def test_manual_guidance_is_idempotent(self):
        runner = _runner({"Workday": {"baseUrl": "https://wd.example.com"}})
        first = check_external_endpoint_reachability(runner)
        second = check_external_endpoint_reachability(runner)

        assert [(r.status, r.result) for r in first] == [
            (r.status, r.result) for r in second
        ]

    def test_every_row_sets_roles(self):
        """test_check_roles.py enforces roles on every constructor."""
        runner = _runner({
            "Workday": {"baseUrl": "https://wd.example.com"},
            "ServiceNow": {"instanceUrl": "https://sn.example.com"},
        })
        results = check_external_endpoint_reachability(runner)

        assert results  # non-empty
        for row in results:
            assert row.roles, f"{row.status} row missing roles"
            assert row.checkpoint_id == "INFRA-003"
