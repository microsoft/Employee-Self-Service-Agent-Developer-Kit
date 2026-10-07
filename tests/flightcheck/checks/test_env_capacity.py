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
    """Power Platform Licensing stub for environment entitlement reads."""

    def __init__(self, entitlements):
        self._entitlements = entitlements

    def get_environment_entitlements(self, _env_id):
        if isinstance(self._entitlements, Exception):
            raise self._entitlements
        return self._entitlements


def _mcs_entitlement(
    *,
    allocated=0,
    auto_allocated=0,
    available=0,
    consumed=0,
    payg_entitled=0,
    payg_consumed=0,
    addons=None,
):
    return {
        "items": [
            {
                "entitlementId": "MCSMessages",
                "addons": list(addons or []),
                "entitlement": {
                    "capacity": {
                        "allocated": {
                            "value": allocated,
                            "autoAllocated": auto_allocated,
                        },
                        "availableQuantity": available,
                        "consumed": {"value": consumed},
                        "status": "WithinCapacity",
                    },
                    "payGo": {
                        "entitled": {"value": payg_entitled},
                        "consumed": {"value": payg_consumed},
                    },
                },
            }
        ],
        "_status": 200,
        "_request_id": "entitlement-request-200",
    }


def _runner(
    *,
    powerplatform,
    payg=None,
    env_id="env-guid",
    ring="prod",
    power_platform_admin_origin=None,
):
    runner = SimpleNamespace(
        powerplatform=powerplatform,
        env_id=env_id,
        ring=ring,
        power_platform_admin_origin=power_platform_admin_origin,
    )
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
    r = _run(_runner(powerplatform=_FakePP(
        _mcs_entitlement(
            allocated=25000.0,
            auto_allocated=750,
            available=0,
            consumed=25000,
        )
    )))
    assert r.status == "Passed"
    assert "25000" in r.result
    assert r.evidence["outcome"] == "verified"
    assert r.evidence["allocatedCredits"] == 25000
    assert r.evidence["source"] == "environment-entitlements"
    assert r.evidence["requestId"] == "entitlement-request-200"


def test_warns_when_zero_capacity_no_payg():
    r = _run(_runner(powerplatform=_FakePP(_mcs_entitlement()), payg=False))
    assert r.status == "Warning"
    assert r.evidence["outcome"] == "verified"
    assert r.evidence["allocatedCredits"] == 0
    assert "not configured" in r.result
    assert "administrator may explicitly attest" in r.remediation
    assert "Manage capacity" in r.remediation


def test_warns_when_zero_capacity_with_payg():
    r = _run(_runner(powerplatform=_FakePP(_mcs_entitlement()), payg=True))
    assert r.status == "Warning"
    assert "Pay-as-you-go billing is configured" in r.result
    assert "administrator may explicitly attest" in r.remediation
    assert "Manage capacity" in r.remediation


def test_warns_when_zero_capacity_unknown_payg():
    # No _payg_configured on the runner (PRE-005 did not run this scope).
    r = _run(_runner(powerplatform=_FakePP(_mcs_entitlement())))
    assert r.status == "Warning"
    assert "not determined" in r.result
    assert "administrator may explicitly attest" in r.remediation


def test_requires_manual_confirmation_when_no_powerplatform_client():
    r = _run(_runner(powerplatform=None, payg=False))
    assert r.status == "Manual"
    assert "API capability was unavailable" in r.result
    assert r.evidence["outcome"] == "unsupported-capability"
    assert "Manage capacity" in r.remediation
    assert "capacity check is skipped" in r.remediation


def test_requires_manual_confirmation_when_entitlement_read_denied():
    pp_denied = _FakePP({
        "_error": "insufficient_permissions",
        "_status": 403,
        "_request_id": "request-123",
    })
    r = _run(_runner(powerplatform=pp_denied, payg=False))
    assert r.status == "Manual"
    assert "access was denied" in r.result
    assert r.evidence["outcome"] == "denied-access"
    assert r.evidence["serviceStatus"] == 403
    assert r.evidence["requestId"] == "request-123"


def test_requires_manual_confirmation_when_mcs_entitlement_is_missing():
    r = _run(_runner(powerplatform=_FakePP({
        "items": [],
        "_status": 204,
        "_request_id": "entitlement-request-204",
    })))

    assert r.status == "Manual"
    assert "no MCSMessages entitlement" in r.result
    assert r.evidence["outcome"] == "missing-entitlement"
    assert r.evidence["matchingEntitlements"] == 0


def test_requires_manual_confirmation_when_mcs_entitlement_is_duplicated():
    item = _mcs_entitlement()["items"][0]
    r = _run(_runner(powerplatform=_FakePP({
        "items": [item, item],
        "_status": 200,
        "_request_id": "entitlement-request-200",
    })))

    assert r.status == "Manual"
    assert "multiple MCSMessages entitlements" in r.result
    assert r.evidence["outcome"] == "ambiguous-entitlement"
    assert r.evidence["matchingEntitlements"] == 2


def test_requires_manual_confirmation_when_entitlement_service_fails():
    class _Response:
        status_code = 503
        headers = {"x-ms-request-id": "request-503"}

    error = RuntimeError("service payload must not be exposed")
    error.response = _Response()

    r = _run(_runner(powerplatform=_FakePP(error), payg=False))

    assert r.status == "Manual"
    assert "service returned an error" in r.result
    assert "service payload" not in r.result
    assert r.evidence == {
        "environmentId": "env-guid",
        "source": "environment-entitlements",
        "outcome": "service-error",
        "errorType": "RuntimeError",
        "serviceStatus": 503,
        "requestId": "request-503",
    }


@pytest.mark.parametrize(
    "allocated",
    [
        "not-a-number",
        "25000",
        None,
        True,
        1.5,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_requires_manual_confirmation_when_entitlement_value_is_invalid(
    allocated,
):
    r = _run(
        _runner(
            powerplatform=_FakePP(
                _mcs_entitlement(allocated=allocated)
            ),
            payg=False,
        )
    )

    assert r.status == "Manual"
    assert "invalid entitlement value" in r.result
    assert r.evidence == {
        "environmentId": "env-guid",
        "source": "environment-entitlements",
        "outcome": "invalid-response",
        "serviceStatus": 200,
        "requestId": "entitlement-request-200",
        "matchingEntitlements": 1,
        "errorType": "InvalidEntitlementAllocationValue",
    }


@pytest.mark.parametrize(
    "response",
    [
        {"items": {}, "_status": 200},
        {
            "items": [
                {
                    "entitlementId": "MCSMessages",
                    "entitlement": {},
                }
            ],
            "_status": 200,
        },
    ],
)
def test_requires_manual_confirmation_when_entitlement_response_is_malformed(
    response,
):
    r = _run(_runner(powerplatform=_FakePP(response), payg=False))

    assert r.status == "Manual"
    assert "invalid entitlement response" in r.result
    assert r.evidence["outcome"] == "invalid-response"


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


def test_capacity_remediation_uses_retained_preview_admin_origin() -> None:
    preview_origin = "https://admin.preview.powerplatform.microsoft.com"
    r = _run(
        _runner(
            powerplatform=None,
            ring="prod",
            power_platform_admin_origin=preview_origin,
        )
    )
    assert (
        f"{preview_origin}/billing/licenses/copilotStudio/overview"
        in r.remediation
    )
    assert "https://admin.powerplatform.microsoft.com/billing" not in r.remediation


def test_capacity_remediation_falls_back_when_ring_unresolved():
    # Targeted --checkpoint runs never resolve the BAP ring, so runner.ring is
    # None. The capacity row must still be produced (no crash) with a
    # ring-agnostic production Admin Center link, rather than raising.
    r = _run(_runner(powerplatform=None, ring=None))
    assert r.status == "Manual"
    assert "could not verify" in r.result
    assert "https://admin.powerplatform.microsoft.com" in r.remediation
    assert "Manage capacity" in r.remediation


def test_fails_when_no_env_id():
    r = _run(_runner(
        powerplatform=_FakePP(_mcs_entitlement(allocated=10)),
        env_id=None,
    ))
    assert r.status == "Failed"
    assert "Environment ID is unavailable" in r.result
