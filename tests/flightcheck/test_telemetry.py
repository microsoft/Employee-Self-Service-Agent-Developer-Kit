# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for flightcheck.telemetry — the Aria / 1DS OneCollector emitter.

These are pure-logic helper tests (no real network): the single HTTP POST
is monkeypatched. Per tests/AGENTS.md, the cassette/tier rules apply to
checks that call external data APIs; telemetry emits fire-and-forget events
and produces no CheckResult, so it is exercised here with mocks only.

What we lock down:
  * envelope iKey mapping (full key -> ``o:<32hex>``) and that the FULL key
    goes in the request HEADER.
  * Common Schema 4.0 required fields + millisecond ``Z`` time format.
  * NDJSON body shape (newline-delimited, never a JSON array).
  * privacy: check events carry NO ``result`` / ``remediation`` free text.
  * env/key resolution (default dev, prod, explicit override, disabled).
  * instance_id generate-once persistence.
  * fail-open: a raising POST never propagates out of emit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pytest

from flightcheck import telemetry


DEV_TOKEN = "08e397b2c6c243eeaeb341e111c36167"
PROD_TOKEN = "311254257bbc417e860c76781d4863c8"


# --- Minimal stand-ins for runner.CheckResult / RunResult -----------------
@dataclass
class FakeCheck:
    checkpoint_id: str = "CHK-1"
    category: str = "Authentication"
    priority: str = "Critical"
    status: str = "Passed"
    description: str = "desc"
    result: str = "SECRET finding text with /paths and agent names"
    remediation: str = "SECRET remediation text"
    roles: list = field(default_factory=lambda: ["Entra Admin", "ESS Maker / Agent Developer"])


@dataclass
class FakeRun:
    scope: str = "full"
    overall: str = "READY"
    duration_secs: float = 12.5
    results: list = field(default_factory=lambda: [FakeCheck(), FakeCheck(checkpoint_id="CHK-2", status="Failed")])
    total: int = 2
    passed: int = 1
    failed: int = 1
    warnings: int = 0
    not_configured: int = 0
    manual: int = 0
    skipped: int = 0
    errors: int = 0


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip telemetry env overrides so each test controls its own config."""
    for var in (
        "ESS_FLIGHTCHECK_TELEMETRY",
        "ESS_FLIGHTCHECK_ARIA_ENV",
        "ESS_FLIGHTCHECK_ARIA_IKEY",
        "ESS_ADK_VERSION",
    ):
        monkeypatch.delenv(var, raising=False)
    # resolve_ikey() now also honors the unified `adk telemetry off` opt-out
    # (adk_telemetry.telemetry_enabled). Pin it ON so these tests don't depend
    # on the developer's real ~/.adk/config; the opt-out test overrides this.
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "on")


# --- envelope iKey mapping ------------------------------------------------
def test_envelope_ikey_uses_tenant_token():
    assert telemetry.envelope_ikey(telemetry.ARIA_IKEYS["dev"]) == f"o:{DEV_TOKEN}"
    assert telemetry.envelope_ikey(telemetry.ARIA_IKEYS["prod"]) == f"o:{PROD_TOKEN}"


def test_time_format_is_iso_ms_z():
    from datetime import datetime, timezone

    ts = telemetry._iso_ms(datetime(2026, 6, 24, 20, 11, 16, 541678, tzinfo=timezone.utc))
    assert ts == "2026-06-24T20:11:16.541Z"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts)


# --- event construction ---------------------------------------------------
def test_build_events_shape_and_required_fields():
    events = telemetry.build_events(
        FakeRun(),
        env="dev",
        instance_id="inst-123",
        tenant_id="tenant-abc",
        agent_id="bot-xyz",
        agent_count=1,
        scope="full",
        invocation_source="cli",
        ikey_envelope=f"o:{DEV_TOKEN}",
        run_id="run-1",
    )
    # 1 run event + 2 check events.
    assert len(events) == 3
    assert events[0]["name"] == telemetry.EVENT_RUN
    assert all(e["name"] == telemetry.EVENT_CHECK for e in events[1:])

    for e in events:
        assert e["ver"] == "4.0"
        assert e["iKey"] == f"o:{DEV_TOKEN}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", e["time"])
        # Same run correlates all events.
        assert e["data"]["runId"] == "run-1"
        assert e["data"]["env"] == "dev"

    run_data = events[0]["data"]
    assert run_data["overall"] == "READY"
    assert run_data["total"] == 2 and run_data["passed"] == 1 and run_data["failed"] == 1
    assert run_data["tenantId"] == "tenant-abc"
    assert run_data["agentId"] == "bot-xyz"
    assert run_data["instanceId"] == "inst-123"
    assert run_data["invocationSource"] == "cli"


def test_check_events_never_leak_free_text():
    events = telemetry.build_events(
        FakeRun(),
        env="dev",
        instance_id="i",
        tenant_id="t",
        agent_id="a",
        agent_count=1,
        scope="full",
        invocation_source="cli",
        ikey_envelope=f"o:{DEV_TOKEN}",
    )
    blob = json.dumps(events)
    assert "SECRET finding text" not in blob
    assert "SECRET remediation" not in blob
    for e in events[1:]:
        assert "result" not in e["data"]
        assert "remediation" not in e["data"]
        assert "description" not in e["data"]
        # enums/ids that ARE allowed:
        assert e["data"]["checkpointId"]
        assert e["data"]["status"] in ("Passed", "Failed")
        assert e["data"]["roles"] == "Entra Admin, ESS Maker / Agent Developer"


# --- NDJSON serialization -------------------------------------------------
def test_serialize_ndjson_is_newline_delimited_not_array():
    events = [{"a": 1}, {"b": 2}, {"c": 3}]
    body = telemetry.serialize_ndjson(events).decode("utf-8")
    assert not body.lstrip().startswith("[")
    lines = body.splitlines()
    assert len(lines) == 3
    assert [json.loads(line) for line in lines] == events
    assert body.endswith("\n")


# --- env / key resolution -------------------------------------------------
def test_resolve_ikey_defaults_to_prod():
    ikey, env = telemetry.resolve_ikey()
    assert env == "prod"
    assert ikey == telemetry.ARIA_IKEYS["prod"]


def test_resolve_ikey_prod(monkeypatch):
    monkeypatch.setenv("ESS_FLIGHTCHECK_ARIA_ENV", "prod")
    ikey, env = telemetry.resolve_ikey()
    assert env == "prod"
    assert ikey == telemetry.ARIA_IKEYS["prod"]


def test_resolve_ikey_explicit_override(monkeypatch):
    monkeypatch.setenv("ESS_FLIGHTCHECK_ARIA_IKEY", "custom-key-123")
    ikey, _ = telemetry.resolve_ikey()
    assert ikey == "custom-key-123"


def test_resolve_ikey_disabled(monkeypatch):
    monkeypatch.setenv("ESS_FLIGHTCHECK_TELEMETRY", "off")
    ikey, env = telemetry.resolve_ikey()
    assert ikey is None
    assert env == "prod"


def test_resolve_ikey_disabled_via_unified_adk_optout(monkeypatch):
    # `adk telemetry off` (ESS_ADK_TELEMETRY=off / ~/.adk/config) must silence
    # the legacy FlightCheck emitter too, matching the printed consent notice.
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    ikey, env = telemetry.resolve_ikey()
    assert ikey is None
    assert env == "prod"


# --- instance_id persistence ----------------------------------------------
def test_instance_id_generated_once_and_stable(tmp_path):
    local = str(tmp_path / ".local")
    first = telemetry.get_instance_id(local)
    second = telemetry.get_instance_id(local)
    assert first == second
    # Looks like a GUID and is persisted to disk.
    assert re.fullmatch(r"[0-9a-f-]{36}", first)
    assert (tmp_path / ".local" / ".instance_id").read_text().strip() == first


# --- emit: happy path + fail-open -----------------------------------------
def test_emit_posts_full_key_in_header_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setenv("ESS_FLIGHTCHECK_ARIA_ENV", "dev")
    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(telemetry.requests, "post", fake_post)

    out = telemetry.emit_flightcheck_telemetry(
        FakeRun(),
        tenant_id="t",
        agent_id="a",
        scope="full",
        agent_count=1,
        local_dir=str(tmp_path / ".local"),
    )
    assert out["sent"] is True
    assert out["status"] == 200
    assert out["events"] == 3
    # FULL key in the header, tenant-token form in each envelope.
    assert captured["headers"]["apikey"] == telemetry.ARIA_IKEYS["dev"]
    assert captured["headers"]["Client-Id"] == "NO_AUTH"
    assert captured["headers"]["content-type"] == "application/x-json-stream"
    first_line = captured["data"].decode("utf-8").splitlines()[0]
    assert json.loads(first_line)["iKey"] == f"o:{DEV_TOKEN}"


def test_emit_tenant_id_is_raw(monkeypatch, tmp_path):
    """tenant_id is emitted RAW (Entra tenant GUID), never hashed/transformed.

    Per the approved Data Profile it is OII with "No Data Transformation"; a
    raw value is what makes per-tenant dashboard filtering usable.
    """
    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["data"] = data
        return FakeResp()

    monkeypatch.setattr(telemetry.requests, "post", fake_post)

    telemetry.emit_flightcheck_telemetry(
        FakeRun(),
        tenant_id="DEMO-TENANT-0001",
        agent_id="a",
        local_dir=str(tmp_path / ".local"),
    )
    for line in captured["data"].decode("utf-8").splitlines():
        assert json.loads(line)["data"]["tenantId"] == "DEMO-TENANT-0001"


def test_emit_is_fail_open_on_post_exception(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(telemetry.requests, "post", boom)

    out = telemetry.emit_flightcheck_telemetry(
        FakeRun(),
        tenant_id="t",
        agent_id="a",
        scope="full",
        local_dir=str(tmp_path / ".local"),
    )
    assert out["sent"] is False
    assert "RuntimeError" in out["reason"]


def test_emit_noop_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ESS_FLIGHTCHECK_TELEMETRY", "off")
    called = {"n": 0}

    def fake_post(*a, **k):
        called["n"] += 1

    monkeypatch.setattr(telemetry.requests, "post", fake_post)
    out = telemetry.emit_flightcheck_telemetry(
        FakeRun(), tenant_id="t", local_dir=str(tmp_path / ".local")
    )
    assert out["sent"] is False
    assert out["reason"] == "disabled"
    assert called["n"] == 0
