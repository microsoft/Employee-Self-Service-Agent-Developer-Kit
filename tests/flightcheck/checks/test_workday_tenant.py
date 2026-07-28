# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for checks/workday_tenant.py (skill-4 configure-workday-tenant).

Pure-logic tests (no network, no clients). The two skill-4 checkpoints are
always-MANUAL attestations that read only ``runner.config`` — Workday exposes
no queryable admin API the kit can reach, so there is nothing to mock. Per the
cardinal cassette rule in ``tests/AGENTS.md`` (which excludes tests of the
kit's pure-logic helpers), no cassette/mock tier is required.

Each assertion pins something an operator or a downstream skill relies on: the
MANUAL contract (never PASSED, never fails readiness), the echoed connection
values, the remediation naming the exact Workday admin screens, and the
never-raise WARNING guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flightcheck.checks.workday_tenant import (
    _NOT_CAPTURED,
    run_workday_tenant_checks,
)
from flightcheck.runner import Priority, Role, Status


@dataclass
class _MinimalRunner:
    """Stand-in for FlightCheckRunner. ``run_workday_tenant_checks`` reads
    only ``runner.config``."""

    config: Any = field(default_factory=dict)


class _BoomConfig:
    """A config object whose ``.get`` raises — exercises the per-emitter
    WARNING guard without any network. Truthy so ``config or {}`` keeps it."""

    def __bool__(self) -> bool:
        return True

    def get(self, *_a: Any, **_k: Any):
        raise RuntimeError("boom")


_FULL_CONFIG = {
    "oauthClientId": "WD_CLIENT_XYZ",
    "tokenEndpoint": "https://wd2-impl-services1.workday.com/ccx/oauth2/acme/token",
    "tenant": "acme_dpt1",
    "restBaseUrl": "https://wd2-impl-services1.workday.com/ccx/api",
    "soapBaseUrl": "https://wd2-impl-services1.workday.com/ccx/service",
    "appIdUri": "api://11111111-1111-1111-1111-111111111111",
}


def _by_id(results):
    return {r.checkpoint_id: r for r in results}


class TestEmitsBothCheckpoints:
    def test_emits_exactly_two_manual_checkpoints(self):
        results = run_workday_tenant_checks(_MinimalRunner(config=_FULL_CONFIG))
        assert [r.checkpoint_id for r in results] == [
            "WD-API-CLIENT-001",
            "WD-TENANT-001",
        ]
        assert all(r.status == Status.MANUAL.value for r in results)

    def test_category_priority_and_roles(self):
        by_id = _by_id(
            run_workday_tenant_checks(_MinimalRunner(config=_FULL_CONFIG))
        )
        api = by_id["WD-API-CLIENT-001"]
        tenant = by_id["WD-TENANT-001"]
        assert api.category == "Workday Tenant"
        assert tenant.category == "Workday Tenant"
        # WD-API-CLIENT-001 is CRITICAL (S4.1), WD-TENANT-001 is HIGH (S4.2/3).
        assert api.priority == Priority.CRITICAL.value
        assert tenant.priority == Priority.HIGH.value
        assert api.roles == [Role.WORKDAY_ADMIN.value]
        assert tenant.roles == [Role.WORKDAY_ADMIN.value]


class TestConfigPresentEchoesValues:
    def test_api_client_echoes_client_id_and_token_endpoint(self):
        by_id = _by_id(
            run_workday_tenant_checks(_MinimalRunner(config=_FULL_CONFIG))
        )
        api = by_id["WD-API-CLIENT-001"]
        assert "WD_CLIENT_XYZ" in api.result
        assert _FULL_CONFIG["tokenEndpoint"] in api.result
        # Attests the required registration facts a Workday admin must confirm.
        assert "SAML ******" in api.result
        assert "Include Workday Owned Scope = Yes" in api.result
        # Remediation names the Workday screens and the ordering rule.
        assert "Register API Client" in api.remediation
        assert "View API Client" in api.remediation
        assert "BEFORE" in api.remediation

    def test_tenant_echoes_connection_fields(self):
        by_id = _by_id(
            run_workday_tenant_checks(_MinimalRunner(config=_FULL_CONFIG))
        )
        tenant = by_id["WD-TENANT-001"]
        for value in (
            "acme_dpt1",
            _FULL_CONFIG["restBaseUrl"],
            _FULL_CONFIG["soapBaseUrl"],
            _FULL_CONFIG["appIdUri"],
        ):
            assert value in tenant.result
        assert "Service Provider ID" in tenant.result
        assert "Tenant Setup - Security" in tenant.remediation
        assert "Activate All Pending" in tenant.remediation


class TestConfigAbsentStaysManual:
    def test_absent_config_still_two_manual_rows(self):
        results = run_workday_tenant_checks(_MinimalRunner(config={}))
        assert [r.checkpoint_id for r in results] == [
            "WD-API-CLIENT-001",
            "WD-TENANT-001",
        ]
        for r in results:
            assert r.status == Status.MANUAL.value
            assert r.remediation  # still tells the operator what to do

    def test_absent_api_client_notes_not_captured(self):
        by_id = _by_id(run_workday_tenant_checks(_MinimalRunner(config={})))
        assert "captured yet" in by_id["WD-API-CLIENT-001"].result

    def test_absent_tenant_fields_show_marker(self):
        by_id = _by_id(run_workday_tenant_checks(_MinimalRunner(config={})))
        assert _NOT_CAPTURED in by_id["WD-TENANT-001"].result

    def test_none_config_does_not_crash(self):
        results = run_workday_tenant_checks(_MinimalRunner(config=None))
        assert len(results) == 2
        assert all(r.status == Status.MANUAL.value for r in results)


class TestNeverRaises:
    def test_emitter_failure_degrades_to_warning(self):
        # Both emitters hit the raising ``.get`` and must degrade to WARNING;
        # the run still returns (the guard never lets an emitter abort it).
        results = run_workday_tenant_checks(_MinimalRunner(config=_BoomConfig()))
        assert [r.checkpoint_id for r in results] == [
            "WD-API-CLIENT-001",
            "WD-TENANT-001",
        ]
        assert all(r.status == Status.WARNING.value for r in results)
        assert all("Unable to attest" in r.result for r in results)
