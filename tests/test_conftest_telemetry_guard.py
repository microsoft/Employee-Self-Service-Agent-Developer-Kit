# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for the autouse telemetry guard in ``tests/conftest.py``.

The guard sets ``ESS_ADK_TELEMETRY=off`` (and ``ESS_ADK_TELEMETRY_SYNC=1``)
for every test in the suite so no test can accidentally ship real Aria
events to prod. This module is *deliberately* free of a local ``_isolate``
fixture (which would clear the env var) so we can observe the ambient
guard directly, and it patches the ``_fc._post`` transport as a paranoia
check: even in a hypothetical world where the env var got unset,
``_post`` would have been called with the payload.

Historical context: before this guard, tests that exercised ``main()`` end-
to-end (auth → discover → session start → capability use) with a monkey-
patched ``discover_tenant`` returning ``"tenant-id"`` shipped 391 ``api.call``
+ 88 ``capability.use`` events (P30D at the time of the fix) to the prod
Aria cube, stamped ``tenant_id="tenant-id"`` — inflating the customer
bucket on the External dashboard.
"""

from __future__ import annotations

import os

import adk_telemetry as adk
from flightcheck import telemetry as _fc


def test_conftest_disables_telemetry_env_var():
    # The autouse fixture in tests/conftest.py must have set this for every
    # test that doesn't explicitly override it.
    assert os.environ.get("ESS_ADK_TELEMETRY") == "off"
    assert adk.telemetry_enabled() is False


def test_conftest_forces_sync_emit_env_var():
    # Sync-emit is belt-and-braces: any accidental leak is at least
    # inspectable in-process instead of racing off in a daemon thread.
    assert os.environ.get("ESS_ADK_TELEMETRY_SYNC") == "1"


def test_emit_short_circuits_before_touching_transport(monkeypatch):
    """No ``_fc._post`` call should be dispatched while the guard is active."""
    posted: list = []

    def _fail_post(ikey, envelopes):  # pragma: no cover — must never run
        posted.append((ikey, envelopes))
        return 200

    monkeypatch.setattr(_fc, "_post", _fail_post)
    # Fire every public emit; each MUST bail at telemetry_enabled().
    adk.start_session()
    adk.emit_api_call(api_endpoint="/x", outcome="success", latency_ms=1)
    adk.emit_capability_use("setup")
    adk.emit_agent_deploy(agent_id="a", deploy_target="production")
    assert posted == []
