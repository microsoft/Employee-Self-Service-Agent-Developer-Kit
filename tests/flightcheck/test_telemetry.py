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
        "ESS_ADK_GIT_SHA",
        "ESS_ADK_GIT_BRANCH",
    ):
        monkeypatch.delenv(var, raising=False)
    # Toolkit git-sha/branch are ``@lru_cache``d — clear so the env
    # override the individual test sets is picked up.
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
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
        tenant_id="00000000-0000-0000-0000-0000000000ab",
        tenant_name="Contoso",
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
    assert run_data["tenantId"] == "00000000-0000-0000-0000-0000000000ab"
    # tenant_class is derived from tenant_id at emit time (ADO 7558661).
    assert run_data["tenantClass"] == "customer"
    assert events[1]["data"]["tenantClass"] == "customer"
    # tenant_name (org display name) rides on both run + check events (ADO 7590589).
    assert run_data["tenantName"] == "Contoso"
    assert events[1]["data"]["tenantName"] == "Contoso"
    # runOutcome buckets the verdict for the donut; FakeRun has 1 failed / 0 errored.
    assert run_data["runOutcome"] == "Failed"
    assert run_data["agentId"] == "bot-xyz"
    assert run_data["instanceId"] == "inst-123"
    assert run_data["invocationSource"] == "cli"
    # Precise upgrade-posture + CA/DA-attribution dimensions ride on the
    # run event (ADO #7943642). Best-effort: they resolve to "unknown"
    # outside a git clone. The dedicated tests below cover the resolution
    # code paths.
    assert "toolkitGitSha" in run_data
    assert "toolkitGitBranch" in run_data
    # Derived CA-vs-DA bucket rides on every run event (ADO #7830949)
    # so FlightCheck dashboards can split pass-rate / duration / etc.
    # by agent type without a join.
    assert run_data["agentType"] in telemetry.AGENT_TYPES


def test_get_toolkit_git_sha_prefers_env_override(monkeypatch):
    monkeypatch.setenv("ESS_ADK_GIT_SHA", "1234567")
    telemetry.get_toolkit_git_sha.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "1234567"


def test_get_toolkit_git_sha_truncates_oversized_override(monkeypatch):
    # An override longer than 40 chars is capped so a stray value never
    # inflates every emitted event.
    monkeypatch.setenv("ESS_ADK_GIT_SHA", "a" * 200)
    telemetry.get_toolkit_git_sha.cache_clear()
    assert len(telemetry.get_toolkit_git_sha()) == 40


def test_get_toolkit_git_branch_prefers_env_override(monkeypatch):
    monkeypatch.setenv("ESS_ADK_GIT_BRANCH", "main-ca")
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_branch() == "main-ca"


def test_get_toolkit_git_sha_reads_unpacked_ref(tmp_path, monkeypatch):
    """Fabricate a .git dir the sha helper can walk without git installed."""
    git_dir = tmp_path / ".git"
    refs_heads = git_dir / "refs" / "heads"
    refs_heads.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (refs_heads / "main").write_text(
        "abcdef0123456789abcdef0123456789abcdef01\n", encoding="utf-8"
    )
    monkeypatch.setattr(telemetry, "_find_git_dir", lambda: str(git_dir))
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "abcdef0"
    assert telemetry.get_toolkit_git_branch() == "main"


def test_get_toolkit_git_sha_reads_packed_refs(tmp_path, monkeypatch):
    """After ``git gc`` the ref file moves into ``packed-refs``."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main-ca\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "1111111222222223333333344444444555555556 refs/heads/main-ca\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(telemetry, "_find_git_dir", lambda: str(git_dir))
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "1111111"
    assert telemetry.get_toolkit_git_branch() == "main-ca"


def test_get_toolkit_git_sha_detached_head(tmp_path, monkeypatch):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(
        "abcdef0123456789abcdef0123456789abcdef01\n", encoding="utf-8"
    )
    monkeypatch.setattr(telemetry, "_find_git_dir", lambda: str(git_dir))
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "abcdef0"
    # Detached HEAD reports "detached", not the SHA (the SHA already lives
    # in toolkit_git_sha; splitting the concerns keeps dashboards tidy).
    assert telemetry.get_toolkit_git_branch() == "detached"


def test_get_toolkit_git_sha_no_repo_returns_unknown(monkeypatch):
    monkeypatch.setattr(telemetry, "_find_git_dir", lambda: "")
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "unknown"
    assert telemetry.get_toolkit_git_branch() == "unknown"


def test_get_toolkit_git_sha_gitdir_file_indirection(tmp_path, monkeypatch):
    """A worktree checkout has ``.git`` as a text file pointing at the real dir."""
    real_git = tmp_path / "real-git"
    refs_heads = real_git / "refs" / "heads"
    refs_heads.mkdir(parents=True)
    (real_git / "HEAD").write_text("ref: refs/heads/wt-branch\n", encoding="utf-8")
    (refs_heads / "wt-branch").write_text(
        "cafebabecafebabecafebabecafebabecafebabe\n", encoding="utf-8"
    )
    fake_git_file = tmp_path / "worktree" / ".git"
    fake_git_file.parent.mkdir()
    fake_git_file.write_text(f"gitdir: {real_git}\n", encoding="utf-8")
    monkeypatch.setattr(telemetry, "_find_git_dir", lambda: str(fake_git_file))
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "cafebab"
    assert telemetry.get_toolkit_git_branch() == "wt-branch"


def test_get_toolkit_git_sha_malformed_head_returns_unknown(tmp_path, monkeypatch):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("garbage\n", encoding="utf-8")
    monkeypatch.setattr(telemetry, "_find_git_dir", lambda: str(git_dir))
    telemetry.get_toolkit_git_sha.cache_clear()
    telemetry.get_toolkit_git_branch.cache_clear()
    assert telemetry.get_toolkit_git_sha() == "unknown"


def test_telemetry_schema_version_bumped_for_toolkit_git_fields():
    """Version-gate the new dimensions so dashboards can pin on schema 1.3."""
    assert telemetry.TELEMETRY_SCHEMA_VERSION == "1.3"


def test_classify_agent_type_maps_main_ca_to_custom_agent():
    assert telemetry.classify_agent_type("main-ca") == telemetry.AGENT_TYPE_CUSTOM


def test_classify_agent_type_maps_main_to_declarative_agent():
    assert telemetry.classify_agent_type("main") == telemetry.AGENT_TYPE_DECLARATIVE


def test_classify_agent_type_case_and_whitespace_insensitive():
    # A caller that pre-normalizes (upper-cases, pads whitespace) still
    # lands in the intended bucket instead of falling through to unknown.
    assert telemetry.classify_agent_type("  MAIN-CA  ") == telemetry.AGENT_TYPE_CUSTOM
    assert telemetry.classify_agent_type("Main") == telemetry.AGENT_TYPE_DECLARATIVE


def test_classify_agent_type_unknown_branches_bucketed():
    # Personal branches, detached HEAD, and the "unknown" sentinel from
    # a failed resolution all map to the "unknown" bucket so
    # out-of-taxonomy values never leak into custom_agent / declarative_agent.
    for branch in ("amilandin/adk-telemetry-agent-type", "detached", "unknown", "", "release/1.0"):
        assert telemetry.classify_agent_type(branch) == telemetry.AGENT_TYPE_UNKNOWN


def test_classify_agent_type_taxonomy_is_closed():
    # A test-time contract: the AGENT_TYPES frozenset is the *complete*
    # taxonomy dashboards can filter on. If a value is ever added to
    # the classifier, it must also land in AGENT_TYPES so the dashboard
    # split-by list stays exhaustive.
    assert telemetry.AGENT_TYPES == frozenset({
        telemetry.AGENT_TYPE_CUSTOM,
        telemetry.AGENT_TYPE_DECLARATIVE,
        telemetry.AGENT_TYPE_UNKNOWN,
    })


def test_derive_run_outcome_precedence():
    """errored > failed > warnings > ready (ADO 7590584)."""
    # errored wins even when failures/warnings are also present.
    assert telemetry.derive_run_outcome(
        FakeRun(errors=1, failed=3, warnings=2)) == "Blocked (check errored)"
    # failed wins over warnings when nothing errored.
    assert telemetry.derive_run_outcome(
        FakeRun(errors=0, failed=1, warnings=5)) == "Failed"
    # warnings-only run.
    assert telemetry.derive_run_outcome(
        FakeRun(errors=0, failed=0, warnings=1)) == "Ready with warnings"
    # clean run.
    assert telemetry.derive_run_outcome(
        FakeRun(errors=0, failed=0, warnings=0)) == "Ready"


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
    # the legacy FlightCheck emitter too, matching the documented opt-out
    # (README / CONTRIBUTING.md).
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
