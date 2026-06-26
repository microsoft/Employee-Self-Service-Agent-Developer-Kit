# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for ``adk_telemetry`` — the spec ``adk.*`` event SDK (Feature
#7403772) that rides the same Aria / 1DS OneCollector transport as
``flightcheck.telemetry``.

These are pure-logic / mocked-POST tests (no real network): the single HTTP
POST (``flightcheck.telemetry._post``) is monkeypatched. Per tests/AGENTS.md
the cassette/tier rules apply to checks that call external data APIs;
telemetry emits fire-and-forget events and produces no CheckResult, so it is
exercised here with mocks only — mirroring ``test_telemetry.py``.

What we lock down:
  * identity hashing: determinism, per-tenant scoping, empty-oid => "".
  * common-dimensions shape + Common Schema 4.0 envelope.
  * error-field scrubbing/attachment (no paths / URLs / newlines leak).
  * consent: env override + ``~/.adk/config`` opt-out, one-time notice.
  * session: persists across calls, rolls after the 30-min window.
  * run-index counter: per-agent within a session.
  * ikey resolution (default dev, env override, raw-key override).
  * fail-open: a raising POST never propagates; the event is buffered, then
    a later successful POST flushes the buffer.
"""

from __future__ import annotations

import json
import re

import pytest

import adk_telemetry as adk
from flightcheck import telemetry as _fc


DEV_TOKEN = "08e397b2c6c243eeaeb341e111c36167"
PROD_TOKEN = "311254257bbc417e860c76781d4863c8"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect all ~/.adk state to tmp, force sync emit, reset identity.

    The module computes its CONFIG_DIR / *_PATH constants at import time from
    ``~``, so redirecting HOME after import is not enough — patch the module
    constants directly. Forcing ``_SYNC`` keeps emits on the calling thread so
    assertions are deterministic and no daemon threads escape the test.
    """
    cfg_dir = tmp_path / ".adk"
    monkeypatch.setattr(adk, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(adk, "CONFIG_PATH", str(cfg_dir / "config"))
    monkeypatch.setattr(adk, "SESSION_PATH", str(cfg_dir / "session.json"))
    monkeypatch.setattr(adk, "BUFFER_PATH", str(cfg_dir / "telemetry-buffer.ndjson"))
    monkeypatch.setattr(adk, "RUNS_PATH", str(cfg_dir / "flightcheck-runs.json"))
    monkeypatch.setattr(adk, "_SYNC", True)
    monkeypatch.setattr(adk, "_IDENTITY", {"developer_id": "", "tenant_id": ""})

    for var in (
        "ESS_ADK_TELEMETRY",
        "ESS_ADK_TELEMETRY_SYNC",
        "ESS_ADK_TELEMETRY_SALT",
        "ESS_ADK_ARIA_ENV",
        "ESS_ADK_ARIA_IKEY",
        "ESS_ADK_VERSION",
    ):
        monkeypatch.delenv(var, raising=False)
    return cfg_dir


@pytest.fixture
def captured_post(monkeypatch):
    """Patch the transport POST to record envelopes and return HTTP 200."""
    calls: list[tuple[str, list[dict]]] = []

    def _fake_post(ikey, envelopes):
        calls.append((ikey, envelopes))
        return 200

    monkeypatch.setattr(_fc, "_post", _fake_post)
    return calls


# --- identity hashing -----------------------------------------------------
def test_developer_hash_is_deterministic_and_tenant_scoped():
    a = adk.hash_developer_id("oid-1", "tenant-A")
    b = adk.hash_developer_id("oid-1", "tenant-A")
    other_tenant = adk.hash_developer_id("oid-1", "tenant-B")

    assert a == b                         # deterministic
    assert a != other_tenant              # same maker, different tenant => differs
    assert re.fullmatch(r"[0-9a-f]{64}", a)


def test_empty_oid_hashes_to_empty_string():
    assert adk.hash_developer_id("", "tenant-A") == ""


def test_tenant_hash_empty_and_distinct_from_developer():
    assert adk.hash_tenant_id("") == ""
    t = adk.hash_tenant_id("tenant-A")
    assert re.fullmatch(r"[0-9a-f]{64}", t)
    # Different salt domain prefix => tenant hash != developer hash.
    assert t != adk.hash_developer_id("tenant-A", "tenant-A")


def test_salt_override_changes_hash(monkeypatch):
    base = adk.hash_tenant_id("tenant-A")
    monkeypatch.setenv("ESS_ADK_TELEMETRY_SALT", "rotated-salt-2027")
    assert adk.hash_tenant_id("tenant-A") != base


def test_set_identity_populates_both_and_flows_into_dimensions():
    adk.set_identity("oid-9", "tenant-Z")
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert dims["developer_id"] == adk.hash_developer_id("oid-9", "tenant-Z")
    assert dims["tenant_id"] == adk.hash_tenant_id("tenant-Z")


# --- common dimensions + envelope ----------------------------------------
def test_common_dimensions_shape():
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    for key in (
        "schema_version", "developer_id", "tenant_id",
        "session_id", "surface", "adk_version", "timestamp",
    ):
        assert key in dims
    assert dims["schema_version"] == adk.SCHEMA_VERSION
    assert dims["surface"] == "cli"
    assert dims["session_id"] == "sid-1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", dims["timestamp"])


def test_build_event_is_common_schema_4_0():
    env = adk.build_event("adk.api.call", {"env": "dev"}, f"o:{DEV_TOKEN}")
    assert env["ver"] == "4.0"
    assert env["name"] == "adk.api.call"
    assert env["iKey"] == f"o:{DEV_TOKEN}"
    assert env["data"] == {"env": "dev"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", env["time"])


# --- scrubbing / error capture -------------------------------------------
def test_scrub_strips_paths_urls_newlines_and_truncates():
    out = adk._scrub("oops C:\\Users\\me\\secret.txt see https://x.y/z\nline2")
    assert "C:\\Users" not in out
    assert "https://" not in out
    assert "\n" not in out
    assert "<path>" in out and "<url>" in out
    assert len(adk._scrub("x" * 500)) == 200


def test_error_fields_attached_only_on_error_outcome():
    ok = {}
    adk._apply_error_fields(ok, "success", "", "", "")
    assert "error_code" not in ok

    bad = {}
    adk._apply_error_fields(bad, "server_error", "500", "boom at /tmp/x", "infra")
    assert bad["error_code"] == "500"
    assert bad["error_category"] == "infra"
    assert "<path>" in bad["error_message"]


# --- consent / opt-out ----------------------------------------------------
def test_enabled_by_default_then_env_overrides(monkeypatch):
    assert adk.telemetry_enabled() is True
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    assert adk.telemetry_enabled() is False
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "on")
    assert adk.telemetry_enabled() is True


def test_config_opt_out_persists():
    adk.set_telemetry(False)
    assert adk.telemetry_enabled() is False
    assert adk.telemetry_status() == "disabled"
    adk.set_telemetry(True)
    assert adk.telemetry_enabled() is True


def test_notice_shown_once(capsys):
    import io

    first = adk.maybe_print_notice(stream=io.StringIO())  # writes, flags shown
    assert first is True
    second = adk.maybe_print_notice(stream=io.StringIO())
    assert second is False


def test_disabled_emit_does_not_post(monkeypatch, captured_post):
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    res = adk.emit_capability_use("onboarding", block=True)
    assert res["sent"] is False
    assert res["reason"] == "disabled"
    assert captured_post == []


# --- session + run index --------------------------------------------------
def test_session_persists_then_rolls_after_window():
    sid1, new1 = adk.get_session()
    sid2, new2 = adk.get_session()
    assert new1 is True and new2 is False
    assert sid1 == sid2

    # Age the stored session past the 30-min window and confirm a fresh id.
    with open(adk.SESSION_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data[adk.SURFACE_CLI]["last"] -= adk.SESSION_TIMEOUT_SECS + 60
    with open(adk.SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)

    sid3, new3 = adk.get_session()
    assert new3 is True
    assert sid3 != sid1


def test_run_index_increments_per_agent_within_session():
    assert adk.next_run_index("bot-A") == 1
    assert adk.next_run_index("bot-A") == 2
    assert adk.next_run_index("bot-B") == 1  # independent per agent


# --- ikey resolution ------------------------------------------------------
def test_resolve_ikey_default_dev():
    ikey, env = adk.resolve_ikey()
    assert env == _fc.DEFAULT_ENV
    assert ikey == _fc.ARIA_IKEYS[_fc.DEFAULT_ENV]


def test_resolve_ikey_env_and_raw_override(monkeypatch):
    monkeypatch.setenv("ESS_ADK_ARIA_ENV", "prod")
    assert adk.resolve_ikey()[1] == "prod"
    monkeypatch.setenv("ESS_ADK_ARIA_IKEY", "raw-key-123")
    ikey, _ = adk.resolve_ikey()
    assert ikey == "raw-key-123"


# --- emit happy path + fail-open + buffering ------------------------------
def test_emit_happy_path_posts_envelope(captured_post):
    res = adk.emit_capability_use("evaluations", block=True)
    assert res["sent"] is True
    assert len(captured_post) == 1
    _ikey, envelopes = captured_post[0]
    assert envelopes[0]["name"] == "adk.capability.use"
    assert envelopes[0]["data"]["adk_capability"] == "evaluations"
    assert envelopes[0]["iKey"] == f"o:{DEV_TOKEN}"


def test_api_call_error_outcome_carries_error_fields(captured_post):
    adk.emit_api_call(
        api_endpoint="dataverse/bots",
        outcome="server_error",
        error_code="503",
        error_category="infra",
        block=True,
    )
    data = captured_post[0][1][0]["data"]
    assert data["outcome"] == "server_error"
    assert data["error_code"] == "503"
    assert data["error_category"] == "infra"


def test_failing_post_is_swallowed_and_buffered(monkeypatch):
    def _boom(ikey, envelopes):
        raise RuntimeError("network down")

    monkeypatch.setattr(_fc, "_post", _boom)
    res = adk.emit_capability_use("onboarding", block=True)  # must not raise
    assert res["sent"] is False
    import os
    assert os.path.exists(adk.BUFFER_PATH)
    with open(adk.BUFFER_PATH, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["name"] == "adk.capability.use"


def test_buffer_flushes_on_next_successful_emit(monkeypatch):
    # First emit fails -> buffered.
    monkeypatch.setattr(_fc, "_post", lambda ikey, envs: (_ for _ in ()).throw(OSError("x")))
    adk.emit_capability_use("onboarding", block=True)
    import os
    assert os.path.exists(adk.BUFFER_PATH)

    # Next emit succeeds -> buffer flushed and removed.
    posted: list[list[dict]] = []

    def _ok(ikey, envs):
        posted.append(envs)
        return 200

    monkeypatch.setattr(_fc, "_post", _ok)
    adk.emit_capability_use("topics", block=True)
    assert not os.path.exists(adk.BUFFER_PATH)
    # The buffered event was replayed (its own POST) plus the live event.
    flushed_names = [e["name"] for envs in posted for e in envs]
    assert "adk.capability.use" in flushed_names
