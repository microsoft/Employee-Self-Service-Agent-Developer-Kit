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
    monkeypatch.setattr(adk, "_IDENTITY", {"instance_id": "", "tenant_id": "", "tenant_name": ""})

    # Isolate the persisted tenant-name cache (.local/.tenant_name) to tmp so
    # tests never read/write the repo's real .local dir. adk_telemetry calls
    # these on _fc at runtime, so patching them here redirects the cache dir.
    _cache_dir = str(tmp_path / ".local")
    _real_cache, _real_get = _fc.cache_tenant_name, _fc.get_cached_tenant_name
    _real_cache_id, _real_get_id = _fc.cache_tenant_id, _fc.get_cached_tenant_id
    monkeypatch.setattr(
        _fc, "cache_tenant_name",
        lambda tid, name, local_dir=_cache_dir, source="organization": _real_cache(
            tid, name, local_dir=local_dir, source=source
        ),
    )
    monkeypatch.setattr(
        _fc, "get_cached_tenant_name",
        lambda tid, local_dir=_cache_dir: _real_get(tid, local_dir=local_dir),
    )
    monkeypatch.setattr(
        _fc, "cache_tenant_id",
        lambda tid, local_dir=_cache_dir: _real_cache_id(tid, local_dir=local_dir),
    )
    monkeypatch.setattr(
        _fc, "get_cached_tenant_id",
        lambda local_dir=_cache_dir: _real_get_id(local_dir=local_dir),
    )

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
    ident = adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab")
    # No developer/user identifier is ever collected.
    assert "developer_id" not in ident
    assert ident["instance_id"] == "install-guid-1"
    assert ident["tenant_id"] == "00000000-0000-0000-0000-0000000000ab"


def test_set_identity_stores_tenant_name(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    ident = adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab", tenant_name="Contoso")
    assert ident["tenant_name"] == "Contoso"
    # Flows into every event's common dimensions (OII; privacy-approved).
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert dims["tenant_name"] == "Contoso"
    # Once resolved, the name is cached per-tenant and reused by later ADK
    # events that lack a Graph token to resolve it live (persist-and-reuse),
    # even when set_identity is later called for the same tenant without it.
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab")
    assert adk.common_dimensions(adk.SURFACE_CLI)["tenant_name"] == "Contoso"


def test_tenant_name_empty_when_never_resolved(monkeypatch):
    # No Graph-capable flow ever resolved a name for this tenant -> stays "".
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab")
    assert adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")["tenant_name"] == ""


def test_tenant_name_cache_not_reused_across_tenants(monkeypatch):
    # A name cached for 00000000-0000-0000-0000-0000000000ab must never be stamped on a different tenant's
    # events (the cache is keyed by tenant_id). Simulates a maker who resolved
    # 00000000-0000-0000-0000-0000000000ab via FlightCheck, then runs an ADK flow authenticated as 00000000-0000-0000-0000-0000000000cd.
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab", tenant_name="Contoso")  # seeds cache
    monkeypatch.setattr(
        adk, "_IDENTITY", {"instance_id": "", "tenant_id": "", "tenant_name": ""}
    )
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000cd")  # different tenant, no name available
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert dims["tenant_id"] == "00000000-0000-0000-0000-0000000000cd"
    assert dims["tenant_name"] == ""


def test_tenant_name_reused_by_later_process_without_identity(monkeypatch):
    # An ADK emit path (e.g. setup.py -> emit_agent_create) that never calls
    # set_identity should still pick up a name a prior FlightCheck run cached
    # for the same tenant, via the common_dimensions fallback.
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab", tenant_name="Contoso")  # FlightCheck run
    # Later process: fresh identity, no set_identity call, but tenant_id known.
    monkeypatch.setattr(
        adk, "_IDENTITY", {"instance_id": "", "tenant_id": "", "tenant_name": ""}
    )
    dims = adk.common_dimensions(adk.SURFACE_CLI, tenant_id="00000000-0000-0000-0000-0000000000ab")
    assert dims["tenant_name"] == "Contoso"


def test_tenant_id_reused_by_fresh_subprocess_without_identity(monkeypatch):
    # Reproduces the emit_capability.py shim scenario: SKILL.md steps launch
    # `python scripts/emit_capability.py <cap>` as a *fresh* Python subprocess,
    # which never calls set_identity. Without the on-disk tenant_id fallback,
    # such a subprocess emits with tenant_id="" -> classify_tenant("")=="unknown",
    # so the capability event never appears on the customer-filtered External
    # dashboard even though the maker's earlier auth flow knew the tenant.
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    # Auth flow (parent process) persists tenant_id.
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab")
    # Subprocess simulation: brand-new interpreter -> empty _IDENTITY, no
    # set_identity call.
    monkeypatch.setattr(
        adk, "_IDENTITY", {"instance_id": "", "tenant_id": "", "tenant_name": ""}
    )
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    # The persisted GUID is picked up and the event classifies as customer,
    # not unknown.
    assert dims["tenant_id"] == "00000000-0000-0000-0000-0000000000ab"
    assert dims["tenant_class"] == _fc.TENANT_CLASS_CUSTOMER


def test_tenant_id_explicit_kwarg_wins_over_cached(monkeypatch):
    # An explicit tenant_id passed by the caller must always win, even when a
    # different tenant_id sits in the on-disk cache (e.g. subprocess is
    # emitting on behalf of a specific tenant that isn't the last-cached one).
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab")  # writes 00000000-0000-0000-0000-0000000000ab to disk
    monkeypatch.setattr(
        adk, "_IDENTITY", {"instance_id": "", "tenant_id": "", "tenant_name": ""}
    )
    dims = adk.common_dimensions(adk.SURFACE_CLI, tenant_id="00000000-0000-0000-0000-0000000000cd")
    assert dims["tenant_id"] == "00000000-0000-0000-0000-0000000000cd"


def test_tenant_id_explicit_empty_kwarg_does_not_fall_back(monkeypatch):
    # An explicit empty tenant_id (caller genuinely knows there is none)
    # must NOT be overridden by the disk cache — that would leak a stale
    # tenant_id onto an event the caller deliberately marked anonymous.
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab")
    monkeypatch.setattr(
        adk, "_IDENTITY", {"instance_id": "", "tenant_id": "", "tenant_name": ""}
    )
    dims = adk.common_dimensions(adk.SURFACE_CLI, tenant_id="")
    assert dims["tenant_id"] == ""


def test_cache_tenant_id_round_trip_and_guards(tmp_path):
    d = str(tmp_path / "state")
    _fc.cache_tenant_id("00000000-0000-0000-0000-0000000000ab", local_dir=d)
    assert _fc.get_cached_tenant_id(local_dir=d) == "00000000-0000-0000-0000-0000000000ab"
    # Missing dir/file -> "".
    assert _fc.get_cached_tenant_id(local_dir=str(tmp_path / "nope")) == ""
    # Empty tenant_id is a no-op (never overwrite a valid cache with "").
    _fc.cache_tenant_id("", local_dir=d)
    assert _fc.get_cached_tenant_id(local_dir=d) == "00000000-0000-0000-0000-0000000000ab"
    # Whitespace is stripped on write.
    _fc.cache_tenant_id("  00000000-0000-0000-0000-0000000000cd  ", local_dir=d)
    assert _fc.get_cached_tenant_id(local_dir=d) == "00000000-0000-0000-0000-0000000000cd"


def test_cache_tenant_name_round_trip_and_guards(tmp_path):
    d = str(tmp_path / "state")
    # Round-trip for a matching tenant.
    _fc.cache_tenant_name("00000000-0000-0000-0000-0000000000ab", "Contoso", local_dir=d)
    assert _fc.get_cached_tenant_name("00000000-0000-0000-0000-0000000000ab", local_dir=d) == "Contoso"
    # Mismatched tenant never inherits the cached name.
    assert _fc.get_cached_tenant_name("00000000-0000-0000-0000-0000000000cd", local_dir=d) == ""
    # Missing dir/file -> "".
    assert _fc.get_cached_tenant_name("00000000-0000-0000-0000-0000000000ab", local_dir=str(tmp_path / "nope")) == ""
    # Malformed / non-dict cache content -> "" (defensive; never raises).
    import os as _os
    _os.makedirs(str(tmp_path / "bad"), exist_ok=True)
    with open(str(tmp_path / "bad" / _fc._TENANT_NAME_FILE), "w", encoding="utf-8") as _f:
        _f.write("not-json{{")
    assert _fc.get_cached_tenant_name("00000000-0000-0000-0000-0000000000ab", local_dir=str(tmp_path / "bad")) == ""
    with open(str(tmp_path / "bad" / _fc._TENANT_NAME_FILE), "w", encoding="utf-8") as _f:
        _f.write("[1, 2, 3]")
    assert _fc.get_cached_tenant_name("00000000-0000-0000-0000-0000000000ab", local_dir=str(tmp_path / "bad")) == ""
    # Empty inputs are no-ops (nothing cached, nothing returned).
    _fc.cache_tenant_name("", "Contoso", local_dir=d)
    _fc.cache_tenant_name("tenant-W", "", local_dir=d)
    assert _fc.get_cached_tenant_name("tenant-W", local_dir=d) == ""
    assert _fc.get_cached_tenant_name("", local_dir=d) == ""


def test_explicit_instance_id_overrides_persisted(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    ident = adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab", instance_id="explicit-2")
    assert ident["instance_id"] == "explicit-2"


def test_identity_flows_into_dimensions(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    adk.set_identity(tenant_id="00000000-0000-0000-0000-0000000000ab", instance_id="inst-9")
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert "developer_id" not in dims
    assert dims["instance_id"] == "inst-9"
    # tenant_id is emitted RAW (approved Data Profile: OII, no transformation).
    assert dims["tenant_id"] == "00000000-0000-0000-0000-0000000000ab"


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


def test_classify_tenant_non_guid_maps_to_unknown():
    # Defense-in-depth: a non-empty tenant_id that isn't a canonical Entra
    # tenant GUID must NEVER classify as "customer" — otherwise the External
    # dashboard silently absorbs fixture / placeholder / garbage values into
    # the customer bucket (the exact regression that produced 391 fixture
    # leak events in prod before the autouse conftest guard landed). This is
    # a second safety net on top of _sanitize_tenant_id at set_identity
    # ingress: even if a bad value bypasses the sanitizer (test that
    # overrides ESS_ADK_TELEMETRY, hand-edited cache file, future caller
    # that skips set_identity entirely), classify_tenant still labels it
    # "unknown" so it's excluded from customer usage counts.
    assert _fc.classify_tenant("tenant-id") == "unknown"       # fixture leak
    assert _fc.classify_tenant("unknown") == "unknown"          # sentinel
    assert _fc.classify_tenant("Contoso") == "unknown"          # display name
    assert _fc.classify_tenant("11111111-1111-1111-1111-11111") == "unknown"  # short


def test_guid_re_matches_adk_telemetry():
    # adk_telemetry._GUID_RE and flightcheck.telemetry._GUID_RE must stay in
    # lock-step (this module cannot import from adk_telemetry, so the regex
    # is duplicated). A drift would let one entry point accept a value the
    # other rejects.
    assert adk._GUID_RE.pattern == _fc._GUID_RE.pattern


def test_get_cached_tenant_id_rejects_non_guid_legacy_string(tmp_path):
    # The legacy raw-string compatibility shim in get_cached_tenant_id must
    # validate against _GUID_RE before returning — otherwise a torn /
    # hand-edited / garbage .tenant_id file would ride onto real events.
    d = tmp_path / "state"
    d.mkdir()
    (d / _fc._TENANT_ID_FILE).write_text("tenant-id", encoding="utf-8")
    assert _fc.get_cached_tenant_id(local_dir=str(d)) == ""
    # A canonical raw-string GUID (older ADK builds) is still honored.
    (d / _fc._TENANT_ID_FILE).write_text(
        "ABCDEF01-2345-6789-abcd-ef0123456789", encoding="utf-8"
    )
    assert (
        _fc.get_cached_tenant_id(local_dir=str(d))
        == "abcdef01-2345-6789-abcd-ef0123456789"
    )


def test_common_dimensions_sanitizes_explicit_tenant_id_kwarg(monkeypatch):
    # Single choke point: EVERY tenant_id source (explicit kwarg included)
    # is sanitized in common_dimensions, so an emit_* helper that forwards
    # a caller-supplied non-GUID never lands in the customer bucket.
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    dims = adk.common_dimensions(adk.SURFACE_CLI, tenant_id="tenant-id")
    assert dims["tenant_id"] == ""
    assert dims["tenant_class"] == _fc.TENANT_CLASS_UNKNOWN
    # A well-formed GUID is preserved (and lowercased).
    dims = adk.common_dimensions(
        adk.SURFACE_CLI, tenant_id="ABCDEF01-2345-6789-abcd-ef0123456789"
    )
    assert dims["tenant_id"] == "abcdef01-2345-6789-abcd-ef0123456789"


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
        "tenant_name",
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


# --- deploy-target classification (sandbox vs production) ------------------
def test_classify_deploy_target_non_prod_skus_map_to_sandbox():
    for sku in ("Sandbox", "Trial", "Developer", "Teams",
                "SubscriptionBasedTrial", "Support", "Playground"):
        assert adk.classify_deploy_target(sku) == "sandbox"


def test_classify_deploy_target_prod_skus_map_to_production():
    for sku in ("Production", "Default"):
        assert adk.classify_deploy_target(sku) == "production"


def test_classify_deploy_target_unknown_or_empty_defaults_to_production():
    for sku in ("", None, "SomethingNew", "   "):
        assert adk.classify_deploy_target(sku) == "production"


def test_classify_deploy_target_is_case_and_whitespace_insensitive():
    assert adk.classify_deploy_target("  sAnDbOx  ") == "sandbox"
    assert adk.classify_deploy_target(" PRODUCTION ") == "production"


# --- subprocess-spawn regression (SKILL.md shim path) ---------------------
def test_emit_capability_shim_subprocess_stamps_cached_tenant_id(tmp_path):
    """A *fresh* subprocess launched by SKILL.md must stamp tenant_id.

    Reproduces the regression that motivated PR #237: SKILL.md invokes
    ``python scripts/emit_capability.py <cap>`` from the maker's shell — a
    brand-new interpreter that never calls ``set_identity`` yet must still
    emit ``adk.capability.use`` events carrying the maker's tenant_id so
    they land on the customer-filtered dashboard. The on-disk
    ``.local/.tenant_id`` cache written by an earlier ``set_identity`` call
    (in the parent auth flow) is the only bridge across the process
    boundary. If we ever regress the ``common_dimensions`` fallback (e.g.
    someone re-adds a "tenant_id is None -> return ''" short-circuit),
    this test catches it end-to-end without any monkeypatching of the
    telemetry module.

    Transport is intentionally broken by pointing ``HTTPS_PROXY`` at a dead
    localhost port so the POST fails and the event lands in the on-disk
    ``telemetry-buffer.ndjson`` where we can inspect ``.data.tenant_id``.
    Sync mode keeps the emit on the calling thread — no daemon-thread race.
    """
    import os as _os
    import subprocess as _sp

    scripts_dir = _os.path.abspath(
        _os.path.join(
            _os.path.dirname(__file__),
            "..",
            "solutions",
            "ess-maker-skills",
            "scripts",
        )
    )
    shim = _os.path.join(scripts_dir, "emit_capability.py")
    assert _os.path.exists(shim), shim

    # Parent flow: seed the on-disk tenant_id cache with a canonical GUID.
    local_dir = tmp_path / ".local"
    local_dir.mkdir()
    (local_dir / _fc._TENANT_ID_FILE).write_text(
        json.dumps(
            {
                "version": 1,
                "tenant_id": "00000000-0000-0000-0000-0000000000ab",
            }
        ),
        encoding="utf-8",
    )

    home = tmp_path / "home"
    home.mkdir()
    env = {
        **_os.environ,
        "USERPROFILE": str(home),
        "HOME": str(home),
        # Force POST to fail so the event is buffered to disk (where we
        # can read it back).
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "HTTP_PROXY": "http://127.0.0.1:1",
        "ESS_ADK_TELEMETRY": "on",
        "ESS_ADK_TELEMETRY_SYNC": "1",
        "ESS_ADK_ARIA_ENV": "dev",
    }
    # Some CI hosts inject a NO_PROXY that would exempt the OneCollector
    # endpoint from the fake proxy — drop it so HTTPS_PROXY actually applies.
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)

    result = _sp.run(
        [__import__("sys").executable, shim, "setup"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    buf_path = home / ".adk" / "telemetry-buffer.ndjson"
    assert buf_path.exists(), (
        f"expected {buf_path} to be created by the shim; stdout={result.stdout!r}"
        f" stderr={result.stderr!r}"
    )
    lines = [
        line for line in buf_path.read_text(encoding="utf-8").splitlines() if line
    ]
    assert lines, "buffer file is empty"
    ev = json.loads(lines[-1])
    data = ev.get("data", {})
    assert data.get("tenant_id") == "00000000-0000-0000-0000-0000000000ab", data
    assert data.get("adk_capability") == "setup", data


# --- tenant-id sanitization (test-fixture leak defense) --------------------
# Historical bug: tests that monkey-patched ``auth.discover_tenant`` to return
# the literal string ``"tenant-id"`` (or that let it fall through the auth
# path with a similarly non-GUID value) shipped real ``adk.*`` events to the
# prod Aria cube during CI/local runs. Those events classified as ``customer``
# (since ``"tenant-id"`` is neither the Microsoft nor EmployeeHub GUID) and
# polluted the ``backup_template_configs`` / ``restore_template_configs``
# customer usage counts. The autouse ``_disable_adk_telemetry`` fixture in
# ``tests/conftest.py`` is the primary defense (short-circuits at
# ``telemetry_enabled()``); this sanitizer in ``set_identity`` is the second
# layer so that even if a future test overrides that env var, a bad
# ``tenant_id`` still can't reach the wire.
def test_set_identity_normalizes_non_guid_tenant_id_to_empty(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    ident = adk.set_identity(tenant_id="tenant-id")  # the historical leak value
    assert ident["tenant_id"] == ""
    # common_dimensions must NOT stamp a bad tenant on the event either.
    dims = adk.common_dimensions(adk.SURFACE_CLI, session_id="sid-1")
    assert dims["tenant_id"] == ""
    # classify_tenant then labels the event as "unknown" (excluded from the
    # customer bucket on the External dashboard).
    assert _fc.classify_tenant(dims["tenant_id"]) == "unknown"


def test_set_identity_accepts_canonical_guid_and_normalizes_case(monkeypatch):
    monkeypatch.setattr(_fc, "get_instance_id", lambda: "install-guid-1")
    # Mixed-case + surrounding whitespace round-trip to lowercase, dashes preserved.
    ident = adk.set_identity(tenant_id="  ABCDEF01-2345-6789-ABCD-EF0123456789  ")
    assert ident["tenant_id"] == "abcdef01-2345-6789-abcd-ef0123456789"


@pytest.mark.parametrize(
    "bad",
    [
        "tenant-id",                              # historical fixture leak
        "unknown",                                # sentinel string
        "abcdef01-2345-6789-abcd-ef012345678",    # 11-char trailing group (short)
        "abcdef012345-6789-abcd-ef0123456789",    # dash in wrong offset
        "gggggggg-gggg-gggg-gggg-gggggggggggg",   # non-hex
        "Contoso",                                # display name accidentally routed here
    ],
)
def test_sanitize_tenant_id_rejects_non_guid(bad):
    assert adk._sanitize_tenant_id(bad) == ""


def test_sanitize_tenant_id_preserves_empty():
    assert adk._sanitize_tenant_id("") == ""
    assert adk._sanitize_tenant_id("   ") == ""
