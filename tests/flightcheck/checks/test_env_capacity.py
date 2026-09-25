# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for ENV-CAPACITY-001 — Copilot Studio capacity provisioned.

Pure-logic tests (no network): the emitter
``_check_copilot_studio_capacity_provisioned`` is driven directly with a fake
Power Platform Licensing client, mirroring the PRE-004 capacity stubs in
``test_prerequisites.py``. Exempt from the cassette rule (``tests/AGENTS.md``)
as a pure-logic helper test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    repo_root = Path(__file__).resolve().parents[3]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


class _FakePP:
    """Power Platform Licensing stub: only get_currency_allocations is read."""

    def __init__(self, allocations):
        self._alloc = allocations  # list | {"_error": ...} | Exception

    def get_currency_allocations(self, _env_id):
        if isinstance(self._alloc, Exception):
            raise self._alloc
        return self._alloc


def _mcs(allocated: int) -> list[dict]:
    """One MCSMessages allocation row at the given credit count."""
    return [{"currencyType": "MCSMessages", "allocated": allocated}]


def _runner(
    *,
    powerplatform,
    payg=None,
    env_id="env-guid",
    ring=None,
    host=None,
):
    runner = SimpleNamespace(
        powerplatform=powerplatform,
        env_id=env_id,
        config={"powerPlatformApiEndpoint": host} if host else {},
    )
    if payg is not None:
        runner._payg_configured = payg
    if ring is not None:
        runner.ring = ring
    return runner


def _run(runner):
    from flightcheck.checks.environment import (
        _check_copilot_studio_capacity_provisioned,
    )
    results = _check_copilot_studio_capacity_provisioned(runner)
    assert len(results) == 1
    r = results[0]
    assert r.checkpoint_id == "ENV-CAPACITY-001"
    assert r.priority == "Critical"
    return r


def test_passed_when_capacity_allocated():
    r = _run(_runner(powerplatform=_FakePP(_mcs(25000))))
    assert r.status == "Passed"
    assert "25000" in r.result


def test_failed_when_zero_capacity_no_payg():
    r = _run(_runner(powerplatform=_FakePP([]), payg=False))
    assert r.status == "Failed"
    assert "runtime" in r.result.lower()
    assert "Manage capacity" in r.remediation


def test_fails_zero_capacity_with_payg():
    r = _run(_runner(powerplatform=_FakePP([]), payg=True))
    assert r.status == "Failed"
    assert "does not satisfy" in r.result
    assert "Manage capacity" in r.remediation


def test_fails_zero_capacity_unknown_payg():
    # No _payg_configured on the runner (PRE-005 did not run this scope).
    r = _run(_runner(powerplatform=_FakePP([])))
    assert r.status == "Failed"
    assert "not determined" in r.result
    assert "cannot continue" in r.remediation.lower()


def test_requires_manual_confirmation_when_no_powerplatform_client():
    r = _run(_runner(powerplatform=None, payg=False))
    assert r.status == "Manual"
    assert "could not verify" in r.result
    assert "Manage capacity" in r.remediation
    assert "explicitly attest" in r.remediation


def test_requires_manual_confirmation_when_allocation_read_denied():
    pp_denied = _FakePP({"_error": "insufficient_permissions", "_status": 403})
    r = _run(_runner(powerplatform=pp_denied, payg=False))
    assert r.status == "Manual"
    assert "could not verify" in r.result


@pytest.mark.parametrize(
    ("ring", "expected_origin"),
    [
        ("prod", "https://admin.powerplatform.microsoft.com"),
        ("preprod", "https://admin.preprod.powerplatform.microsoft.com"),
        ("test", "https://admin.test.powerplatform.microsoft.com"),
    ],
)
def test_capacity_remediation_uses_ring_admin_center(
    ring: str,
    expected_origin: str,
) -> None:
    r = _run(_runner(powerplatform=None, ring=ring))
    assert expected_origin in r.remediation


def test_capacity_remediation_derives_test_ring_from_environment_host():
    r = _run(
        _runner(
            powerplatform=None,
            host=(
                "https://00000000000000000000000000000000.0."
                "environment.api.test.powerplatform.com"
            ),
        )
    )
    assert "https://admin.test.powerplatform.microsoft.com" in r.remediation


def test_fails_when_no_env_id():
    r = _run(_runner(powerplatform=_FakePP(_mcs(10)), env_id=None))
    assert r.status == "Failed"
    assert "Environment ID is unavailable" in r.result
