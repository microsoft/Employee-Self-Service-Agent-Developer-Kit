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


def _runner(*, powerplatform, payg=None, env_id="env-guid"):
    runner = SimpleNamespace(powerplatform=powerplatform, env_id=env_id)
    if payg is not None:
        runner._payg_configured = payg
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


def test_warns_zero_capacity_with_payg():
    r = _run(_runner(powerplatform=_FakePP([]), payg=True))
    assert r.status == "Warning"
    assert "Pay-as-you-go billing is configured" in r.result


def test_warns_zero_capacity_unknown_payg():
    # No _payg_configured on the runner (PRE-005 did not run this scope).
    r = _run(_runner(powerplatform=_FakePP([])))
    assert r.status == "Warning"
    assert "not determined" in r.result


def test_manual_when_no_powerplatform_client():
    # No licensing client wired -> allocation unreadable -> MANUAL attestation.
    r = _run(_runner(powerplatform=None, payg=False))
    assert r.status == "Manual"
    assert "could not be read" in r.result
    assert "Manage capacity" in r.remediation


def test_manual_when_allocation_read_denied():
    pp_denied = _FakePP({"_error": "insufficient_permissions", "_status": 403})
    r = _run(_runner(powerplatform=pp_denied, payg=False))
    assert r.status == "Manual"
    assert "could not be read" in r.result


def test_manual_when_no_env_id():
    r = _run(_runner(powerplatform=_FakePP(_mcs(10)), env_id=None))
    assert r.status == "Manual"
    assert "Environment ID is unavailable" in r.result
