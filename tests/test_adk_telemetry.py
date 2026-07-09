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
  * identity: random ``instance_id`` dedup + raw ``tenant_id``, no developer id.
  * common-dimensions shape + Common Schema 4.0 envelope.
  * error-field scrubbing/attachment (no paths / URLs / newlines leak).
  * consent: env override + ``~/.adk/config`` opt-out, one-time notice.
  * session: persists across calls, rolls after the 30-min window.
  * run-index counter: per-agent within a session.
  * ikey resolution (shared default env, env override, raw-key override).
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
    monkeypatch.setattr(adk, "_IDENTITY", {"instance_id": "", "tenant_id": ""})

    for var in (
        "ESS_ADK_TELEMETRY",
        "ESS_ADK_TELEMETRY_SYNC",
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


# --- identity (instance_id; no developer identity) ------------------------
def test_set_identity_stores_instance_and_raw_tenant(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    ident = adk.set_identity(tenant_id="tenant-Z")
    # No developer/user identifier is ever collected.
    assert "developer_id" not in ident
    assert ident["instance_id"] == "install-guid-1"
    assert ident["tenant_id"] == "tenant-Z"


def test_explicit_instance_id_overrides_persisted(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    ident = adk.set_identity(tenant_id="tenant-Z", instance_id="explicit-2")
    assert ident["instance_id"] == "explicit-2"


def test_identity_flows_into_dimensions(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="tenant-Z", instance_id="inst-9")
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert "developer_id" not in dims
    assert dims["instance_id"] == "inst-9"
    # tenant_id is emitted RAW (approved Data Profile: OII, no transformation).
    assert dims["tenant_id"] == "tenant-Z"


# --- tenant_class (internal vs customer; ADO 7558661) ---------------------
def test_classify_tenant_microsoft_corp_is_internal():
    assert _fc.classify_tenant(_fc.MICROSOFT_CORP_TENANT_ID) == "internal"
    # case / whitespace insensitive
    assert _fc.classify_tenant(f"  {_fc.MICROSOFT_CORP_TENANT_ID.upper()} ") == "internal"


def test_classify_tenant_other_tenant_is_customer():
    assert _fc.classify_tenant("11111111-1111-1111-1111-111111111111") == "customer"


def test_classify_tenant_empty_is_unknown():
    assert _fc.classify_tenant("") == "unknown"
    assert _fc.classify_tenant(None) == "unknown"


def test_classify_tenant_env_allowlist_extends(monkeypatch):
    extra = "abababab-abab-abab-abab-abababababab"
    monkeypatch.setenv("ESS_ADK_INTERNAL_TENANTS", f"{extra}, dead-beef")
    assert _fc.classify_tenant(extra) == "internal"
    assert _fc.classify_tenant("DEAD-BEEF") == "internal"
    # corp tenant is still internal alongside the env additions
    assert _fc.classify_tenant(_fc.MICROSOFT_CORP_TENANT_ID) == "internal"
    # an unrelated tenant is still customer
    assert _fc.classify_tenant("11111111-1111-1111-1111-111111111111") == "customer"


def test_tenant_class_flows_into_dimensions(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id=_fc.MICROSOFT_CORP_TENANT_ID, instance_id="inst-9")
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert dims["tenant_class"] == "internal"

    adk.set_identity(tenant_id="11111111-1111-1111-1111-111111111111", instance_id="inst-9")
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert dims["tenant_class"] == "customer"

    # explicit tenant override is classified too
    dims = adk.common_dimensions(
        adk.SURFACE_CLI, session_id="sid-1", tenant_id=_fc.MICROSOFT_CORP_TENANT_ID
    )
    assert dims["tenant_class"] == "internal"


# --- common dimensions + envelope ----------------------------------------
def test_common_dimensions_shape():
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    for key in (
        "schema_version", "instance_id", "tenant_id", "tenant_class",
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


def test_scrub_redacts_emails_upns_and_guids():
    # Dataverse exceptions routinely echo a UPN or object id; neither may leak.
    out = adk._scrub(
        "User principal@contoso.onmicrosoft.com "
        "(6f7c8f9c-1234-4abc-9def-0123456789ab) lacks access"
    )
    assert "principal@contoso.onmicrosoft.com" not in out
    assert "6f7c8f9c-1234-4abc-9def-0123456789ab" not in out
    assert "<email>" in out and "<guid>" in out


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
    res = adk.emit_capability_use("setup", block=True)
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
def test_resolve_ikey_default_matches_shared_default():
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
def test_emit_happy_path_posts_envelope(captured_post, monkeypatch):
    monkeypatch.setenv("ESS_ADK_ARIA_ENV", "dev")
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
    res = adk.emit_capability_use("setup", block=True)  # must not raise
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
    adk.emit_capability_use("setup", block=True)
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


def test_buffer_oversize_drops_oldest_and_accepts_newest(monkeypatch):
    # Shrink the byte cap so a handful of events exceed it. The buffer must drop
    # the OLDEST events (never grow unbounded) while still accepting the newest.
    import os

    monkeypatch.setattr(adk, "BUFFER_MAX_BYTES", 200)
    for i in range(20):
        adk._buffer_append([adk.build_event(f"adk.evt.{i}", {"n": i}, "o:tok")])

    size = os.path.getsize(adk.BUFFER_PATH)
    assert size <= 300  # bounded near the cap, not accumulating all 20 events
    with open(adk.BUFFER_PATH, "r", encoding="utf-8") as f:
        names = [json.loads(ln)["name"] for ln in f.read().splitlines() if ln.strip()]
    assert "adk.evt.19" in names      # newest kept
    assert "adk.evt.0" not in names   # oldest dropped


# --- capability taxonomy + normalization ----------------------------------
def test_normalize_capability_known_values_pass_through():
    for cap in adk.ADK_CAPABILITIES:
        assert adk.normalize_capability(cap) == cap


def test_normalize_capability_empty_stays_empty():
    # Some events legitimately carry no capability (e.g. an uncategorized
    # session) — those must NOT be coerced to "unknown".
    assert adk.normalize_capability("") == ""
    assert adk.normalize_capability(None) == ""


def test_normalize_capability_case_and_whitespace_insensitive():
    assert adk.normalize_capability("  Topic_Create ") == "topic_create"
    assert adk.normalize_capability("WORKFLOW_DELETE") == "workflow_delete"


def test_normalize_capability_unknown_bucketed():
    assert adk.normalize_capability("bogus") == adk.CAPABILITY_UNKNOWN
    assert adk.normalize_capability("topics") == adk.CAPABILITY_UNKNOWN


def test_emit_capability_use_coerces_unknown(captured_post, monkeypatch):
    monkeypatch.setenv("ESS_ADK_ARIA_ENV", "dev")
    adk.emit_capability_use("not-a-real-cap", block=True)
    data = captured_post[0][1][0]["data"]
    # Out-of-taxonomy values still emit, but land in the controlled bucket so
    # the "Capability Usage by Type" dimension never mints stray slices.
    assert data["adk_capability"] == adk.CAPABILITY_UNKNOWN


def test_emit_capability_use_known_value_preserved(captured_post, monkeypatch):
    monkeypatch.setenv("ESS_ADK_ARIA_ENV", "dev")
    adk.emit_capability_use("Topic_Create", block=True)
    assert captured_post[0][1][0]["data"]["adk_capability"] == "topic_create"


# --- session start no longer carries a capability dimension ---------------
def test_start_session_omits_capability_dimension(captured_post):
    # "Sessions by Capability" was removed; adk.session.start is now a plain
    # engagement signal (feeds session total/trend only) and must NOT carry an
    # adk_capability. The old code hardcoded "connect" here, which is exactly
    # the mislabeling bug that motivated dropping the chart.
    res = adk.start_session(block=True)
    assert res["sent"] is True
    data = captured_post[0][1][0]["data"]
    assert "adk_capability" not in data


# --- the capabilities wired across the kit stay in the canonical list ------
def test_wired_capabilities_are_in_canonical_list():
    """Every capability string the entry points / SKILL.md skills emit must be
    a member of ADK_CAPABILITIES, or it would silently normalize to
    "unknown" on the dashboards. This is the "keep in sync" contract."""
    wired = {
        # emit_capability_use(...) from the Python entry points
        "setup", "evaluations",
        "backup_template_configs", "restore_template_configs",
        # emit_build_*/flightcheck_* event families
        "publishing", "flightcheck",
        # emit_capability.py shim invocations across the SKILL.md skills
        "connect",
        "topic_create", "topic_update", "topic_delete",
        "workflow_create", "workflow_update", "workflow_delete",
        "cleanup", "troubleshoot",
    }
    missing = wired - set(adk.ADK_CAPABILITIES)
    assert not missing, f"wired capabilities not in ADK_CAPABILITIES: {missing}"



# --- emit_capability.py shim (the SKILL.md-driven hook) -------------------
def test_shim_emits_capability_and_exits_zero(captured_post, monkeypatch):
    import emit_capability
    monkeypatch.setenv("ESS_ADK_ARIA_ENV", "dev")
    rc = emit_capability.main(["emit_capability.py", "topic_create"])
    assert rc == 0
    assert len(captured_post) == 1
    envelope = captured_post[0][1][0]
    assert envelope["name"] == "adk.capability.use"
    assert envelope["data"]["adk_capability"] == "topic_create"


def test_shim_unknown_capability_still_exits_zero(captured_post, monkeypatch):
    import emit_capability
    monkeypatch.setenv("ESS_ADK_ARIA_ENV", "dev")
    rc = emit_capability.main(["emit_capability.py", "not-real"])
    assert rc == 0
    # Emitted, but bucketed — a bad SKILL.md argument can't fail the step and
    # can't pollute the dashboard dimension.
    assert captured_post[0][1][0]["data"]["adk_capability"] == adk.CAPABILITY_UNKNOWN


def test_shim_list_and_help_do_not_emit(captured_post):
    import emit_capability
    assert emit_capability.main(["emit_capability.py", "--list"]) == 0
    assert emit_capability.main(["emit_capability.py", "--help"]) == 0
    assert emit_capability.main(["emit_capability.py"]) == 0  # no args -> help
    assert captured_post == []


def test_shim_no_op_when_telemetry_disabled(captured_post, monkeypatch):
    import emit_capability
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    rc = emit_capability.main(["emit_capability.py", "cleanup"])
    assert rc == 0
    assert captured_post == []


def test_shim_never_raises_even_if_post_fails(monkeypatch):
    import emit_capability

    def _boom(ikey, envelopes):
        raise RuntimeError("network down")

    monkeypatch.setattr(_fc, "_post", _boom)
    # Fail-open contract: a telemetry failure must never fail the skill step.
    assert emit_capability.main(["emit_capability.py", "troubleshoot"]) == 0
