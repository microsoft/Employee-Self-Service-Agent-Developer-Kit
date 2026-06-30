# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Agent Development Kit — general telemetry SDK (Aria / 1DS).

Implements the ``adk.*`` event family from the *ADK Telemetry* PM spec
(ADO Feature #7403772) for the ADK's CLI skills — everything *except*
the FlightCheck outcome events, which keep their own dedicated emitter in
``flightcheck/telemetry.py`` (those feed the existing leadership
dashboards and must not change shape). This module is **additive**: it
adds the spec's session / agent / build / api / capability event family
plus spec-named ``adk.flightcheck.*`` events, all reusing the proven 1DS
OneCollector transport from ``flightcheck.telemetry``.

Design rules (deliberate — read before changing):

* **Fail-open, never block a skill.** Every emit is best-effort and
  swallows all errors. Public emitters dispatch on a daemon thread so a
  slow/blocked collector never stalls a CLI command (spec: "emit
  asynchronously, never block CLI/build/deploy paths"). Set
  ``ESS_ADK_TELEMETRY_SYNC=1`` (or pass ``block=True``) for deterministic
  emission in tests/validation.

* **Consent + opt-out.** Telemetry is enabled by default. The maker can
  opt out via ``python adk_telemetry.py off`` (persisted to
  ``~/.adk/config``) or the ``ESS_ADK_TELEMETRY=off`` env var. A one-time
  notice is printed on first use (``maybe_print_notice``).

* **Privacy: no developer identity collected; tenant_id raw OII; enums only,
  no free text.** We do NOT collect or emit any developer/user identifier
  (not even hashed). Active-user / DAU-WAU-MAU counts dedupe on
  ``instance_id`` — a random GUID generated per ADK install (persisted to
  ``.local/.instance_id``) that is not linkable to any AAD user. ``tenant_id``
  is emitted as the RAW Microsoft Entra tenant GUID: the approved Data Profile
  (Data Scout, privacy review COMPLETED) classifies it Organizational
  Identifiable Information (OII) with "No Data Transformation" (it identifies
  the enterprise tenant, not an individual user), retained <= 30 days. Error
  fields are scrubbed of paths / URLs and truncated. We never emit user
  content.

* **Reliability.** On send failure events are buffered to
  ``~/.adk/telemetry-buffer.ndjson`` (capped at 1000 events / 5 MB) and
  flushed on the next successful emit (spec Failure Scenarios).

iKeys / OneCollector contract are inherited from ``flightcheck.telemetry``
(same dev/prod Aria projects, so these events land alongside FlightCheck
in the same tenant the dashboards read from).
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from typing import Any

# Reuse the OneCollector transport + helpers from the FlightCheck emitter.
# Mirror the sibling-import pattern used by the other scripts so this works
# both when run as ``python scripts/adk_telemetry.py`` and when imported as
# ``import adk_telemetry`` from a sibling script that put scripts/ on path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flightcheck import telemetry as _fc  # noqa: E402


# --- Spec constants -------------------------------------------------------
SCHEMA_VERSION = "1.0.0"

# Surfaces the ADK emits from (spec enum: sdk | cli | studio | docs). The
# Python skill scripts are the CLI surface.
SURFACE_CLI = "cli"

# Event names (spec Event Catalog).
EVENT_SESSION_START = "adk.session.start"
EVENT_SESSION_END = "adk.session.end"
EVENT_AGENT_CREATE = "adk.agent.create"
EVENT_AGENT_DEPLOY = "adk.agent.deploy"
EVENT_BUILD_START = "adk.build.start"
EVENT_BUILD_COMPLETE = "adk.build.complete"
EVENT_API_CALL = "adk.api.call"
EVENT_CAPABILITY_USE = "adk.capability.use"
EVENT_FLIGHTCHECK_RUN = "adk.flightcheck.run"
EVENT_FLIGHTCHECK_RESULT = "adk.flightcheck.result"
EVENT_FLIGHTCHECK_ERROR = "adk.flightcheck.error"

# Outcomes the spec treats as errors (must carry error_* fields).
_ERROR_OUTCOMES = frozenset(
    {"client_error", "server_error", "timeout", "abandoned", "failure", "fail"}
)

# Local config / state lives under ~/.adk (spec Consent & Notice).
CONFIG_DIR = os.path.expanduser(os.path.join("~", ".adk"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config")
SESSION_PATH = os.path.join(CONFIG_DIR, "session.json")
BUFFER_PATH = os.path.join(CONFIG_DIR, "telemetry-buffer.ndjson")

SESSION_TIMEOUT_SECS = 30 * 60  # 30 min inactivity => new session (spec).
BUFFER_MAX_EVENTS = 1000
BUFFER_MAX_BYTES = 5 * 1024 * 1024
RUNS_PATH = os.path.join(CONFIG_DIR, "flightcheck-runs.json")

NOTICE_TEXT = (
    "ADK collects pseudonymous usage data to improve the product.\n"
    "To disable telemetry, run: adk telemetry off\n"
    "Learn more: https://aka.ms/adk-telemetry\n"
)

# When true (env or block=True), emit on the calling thread for determinism.
_SYNC = os.environ.get("ESS_ADK_TELEMETRY_SYNC", "").strip().lower() in (
    "1", "on", "true", "yes",
)

# Process-wide identity, set once after authentication (set_identity). All
# subsequent events inherit it so api.call / build / deploy don't each need
# to re-derive it. We deliberately do NOT keep any developer/user identifier
# here — only a random install ``instance_id`` and the raw tenant GUID.
_IDENTITY: dict[str, str] = {"instance_id": "", "tenant_id": ""}

# Track dispatched daemon threads so flush() can join them (tests / session end).
_THREADS: list[threading.Thread] = []


# --- Identity model (spec) ------------------------------------------------
def set_identity(tenant_id: str = "", instance_id: str | None = None) -> dict[str, str]:
    """Record the install + tenant identity for all subsequent events.

    ``instance_id`` is a random GUID identifying the ADK installation (not a
    user): it lets us compute active-install / DAU-WAU-MAU counts without any
    developer identifier. When omitted it defaults to the persisted per-install
    GUID (``flightcheck.telemetry.get_instance_id``). ``tenant_id`` is stored
    RAW (approved Data Profile: OII, no transformation) so dashboards can
    filter by the literal Entra tenant GUID. No developer/user id is collected.
    """
    _IDENTITY["instance_id"] = (
        _fc.get_instance_id() if instance_id is None else (instance_id or "")
    )
    _IDENTITY["tenant_id"] = tenant_id or ""
    return dict(_IDENTITY)


# --- Consent / opt-out (spec Consent & Notice) ----------------------------
def _read_config() -> dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_config(cfg: dict[str, Any]) -> bool:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except OSError:
        return False


def telemetry_enabled() -> bool:
    """True unless opted out via env var or ``~/.adk/config``."""
    val = os.environ.get("ESS_ADK_TELEMETRY", "").strip().lower()
    if val in ("0", "off", "false", "no", "disabled"):
        return False
    if val in ("1", "on", "true", "yes", "enabled"):
        return True
    return _read_config().get("telemetry", "enabled") != "disabled"


def set_telemetry(enabled: bool) -> bool:
    """Persist the opt-in/out preference to ``~/.adk/config``."""
    cfg = _read_config()
    cfg["telemetry"] = "enabled" if enabled else "disabled"
    _write_config(cfg)
    return enabled


def telemetry_status() -> str:
    return "enabled" if telemetry_enabled() else "disabled"


def maybe_print_notice(stream: Any = None) -> bool:
    """Print the one-time consent notice on first use. Returns True if shown.

    Idempotent across invocations via the ``noticeShown`` config flag. Never
    blocks execution — it prints and returns.
    """
    cfg = _read_config()
    if cfg.get("noticeShown"):
        return False
    (stream or sys.stderr).write("\n" + NOTICE_TEXT + "\n")
    cfg["noticeShown"] = True
    cfg.setdefault("telemetry", "enabled")
    _write_config(cfg)
    return True


# --- Session identity (spec: UUID v4, 30-min inactivity window) -----------
def get_session(surface: str = SURFACE_CLI) -> tuple[str, bool]:
    """Return ``(session_id, is_new)`` for the surface.

    Sessions persist across short-lived CLI processes via
    ``~/.adk/session.json`` and roll to a fresh UUID after 30 minutes of
    inactivity. ``is_new`` is True when a brand-new id was minted (so
    callers can emit exactly one ``session.start`` per session).
    """
    now = time.time()
    data: dict[str, Any] = {}
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}

    entry = data.get(surface)
    sid = None
    is_new = True
    if isinstance(entry, dict):
        last = entry.get("last", 0)
        sid = entry.get("id")
        if sid and (now - float(last or 0)) <= SESSION_TIMEOUT_SECS:
            is_new = False

    if not sid or is_new:
        sid = str(uuid.uuid4())
        is_new = True

    data[surface] = {"id": sid, "last": now}
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass
    return sid, is_new


def next_run_index(agent_id: str, surface: str = SURFACE_CLI) -> int:
    """Return the 1-based FlightCheck run index for ``agent_id`` in the
    current session.

    Persisted in ``~/.adk/flightcheck-runs.json`` keyed by session+agent so
    the "runs-to-first-pass" metric can count attempts within a sitting.
    Best-effort: on any IO error it returns 1.
    """
    sid, _ = get_session(surface)
    key = f"{sid}|{agent_id}"
    data: dict[str, Any] = {}
    try:
        with open(RUNS_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}

    idx = int(data.get(key, 0) or 0) + 1
    data[key] = idx
    # Bound file growth: keep only the most recent ~200 keys.
    if len(data) > 200:
        for stale in list(data.keys())[:-200]:
            data.pop(stale, None)
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(RUNS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass
    return idx


# --- Event construction (pure, testable) ----------------------------------
def common_dimensions(
    surface: str,
    *,
    session_id: str = "",
    instance_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Build the dimensions present on every event (spec Common Dimensions)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": (
            _IDENTITY["instance_id"] or _fc.get_instance_id()
        ) if instance_id is None else instance_id,
        "tenant_id": _IDENTITY["tenant_id"] if tenant_id is None else tenant_id,
        "session_id": session_id,
        "surface": surface,
        "adk_version": _fc.get_adk_version(),
        "timestamp": _fc._iso_ms(_fc._now()),
    }


def _scrub(text: str, limit: int = 200) -> str:
    """Strip newlines, Windows/Unix paths and URLs; truncate. PII defense."""
    if not text:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ").strip()
    s = re.sub(r"[A-Za-z]:\\[^\s]+", "<path>", s)
    s = re.sub(r"https?://[^\s]+", "<url>", s)
    s = re.sub(r"(?<!\w)/[^\s]+", "<path>", s)
    return s[:limit]


def _apply_error_fields(
    data: dict[str, Any],
    outcome: str,
    error_code: str,
    error_message: str,
    error_category: str,
) -> dict[str, Any]:
    """Attach the Error Capture Standard fields when the outcome is an error."""
    if outcome in _ERROR_OUTCOMES or error_code or error_category:
        data["error_code"] = error_code or ""
        data["error_message"] = _scrub(error_message)
        data["error_category"] = error_category or ""
    return data


def build_event(event_name: str, data: dict[str, Any], ikey_envelope: str) -> dict[str, Any]:
    """Build a Common Schema 4.0 envelope for one event."""
    return {
        "ver": "4.0",
        "name": event_name,
        "time": _fc._iso_ms(_fc._now()),
        "iKey": ikey_envelope,
        "data": data,
    }


# --- Transport: ikey resolution, buffering, emit --------------------------
def resolve_ikey() -> tuple[str, str]:
    """Resolve ``(full_ikey, env)`` for ADK general telemetry.

    Defaults to the same dev project as FlightCheck so all ADK telemetry
    lands in one Aria tenant. Override env via ``ESS_ADK_ARIA_ENV`` or the
    raw key via ``ESS_ADK_ARIA_IKEY``.
    """
    env = os.environ.get("ESS_ADK_ARIA_ENV", _fc.DEFAULT_ENV).strip().lower()
    if env not in _fc.ARIA_IKEYS:
        env = _fc.DEFAULT_ENV
    override = os.environ.get("ESS_ADK_ARIA_IKEY", "").strip()
    return (override or _fc.ARIA_IKEYS[env]), env


def _buffer_append(envelopes: list[dict[str, Any]]) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        existing: list[str] = []
        if os.path.exists(BUFFER_PATH):
            if os.path.getsize(BUFFER_PATH) > BUFFER_MAX_BYTES:
                return  # buffer full — drop newest rather than grow unbounded
            with open(BUFFER_PATH, "r", encoding="utf-8") as f:
                existing = [ln for ln in f.read().splitlines() if ln.strip()]
        new_lines = [json.dumps(e, separators=(",", ":")) for e in envelopes]
        combined = (existing + new_lines)[-BUFFER_MAX_EVENTS:]
        with open(BUFFER_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(combined) + "\n")
    except OSError:
        pass


def _buffer_flush(ikey: str) -> None:
    if not os.path.exists(BUFFER_PATH):
        return
    try:
        with open(BUFFER_PATH, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if not lines:
            return
        envs = [json.loads(ln) for ln in lines]
        if _fc._post(ikey, envs) in (200, 204):
            os.remove(BUFFER_PATH)
    except (OSError, ValueError):
        pass
    except Exception:  # noqa: BLE001 — flush is best-effort, never raises
        pass


def _emit_sync(event_name: str, data: dict[str, Any]) -> dict[str, Any]:
    if not telemetry_enabled():
        return {"sent": False, "events": 0, "status": None, "reason": "disabled"}
    try:
        ikey, env = resolve_ikey()
        data = dict(data)
        data.setdefault("env", env)
        envelope = build_event(event_name, data, _fc.envelope_ikey(ikey))
        _buffer_flush(ikey)
        status = _fc._post(ikey, [envelope])
        ok = status in (200, 204)
        if not ok:
            _buffer_append([envelope])
        return {"sent": ok, "events": 1, "status": status, "env": env,
                "event": event_name, "reason": "ok" if ok else f"http {status}"}
    except Exception as e:  # noqa: BLE001 — telemetry must never break a skill
        try:
            ikey, env = resolve_ikey()
            data = dict(data)
            data.setdefault("env", env)
            _buffer_append([build_event(event_name, data, _fc.envelope_ikey(ikey))])
        except Exception:  # noqa: BLE001
            pass
        return {"sent": False, "events": 0, "status": None,
                "event": event_name, "reason": f"{type(e).__name__}: {e}"}


def _emit(event_name: str, data: dict[str, Any], *, block: bool = False) -> dict[str, Any]:
    """Dispatch an emit. Async (daemon thread) unless sync/block requested."""
    if _SYNC or block:
        return _emit_sync(event_name, data)
    t = threading.Thread(target=_emit_sync, args=(event_name, data), daemon=True)
    t.start()
    _THREADS.append(t)
    return {"sent": None, "async": True, "event": event_name}


def flush(timeout: float = 5.0) -> None:
    """Join outstanding async emit threads (call before process exit)."""
    for t in list(_THREADS):
        try:
            t.join(timeout)
        except RuntimeError:
            pass


# --- Public event emitters (spec Event Catalog) ---------------------------
def start_session(
    surface: str = SURFACE_CLI,
    *,
    tenant_id: str = "",
    instance_id: str | None = None,
    adk_capability: str = "",
    block: bool = False,
) -> dict[str, Any]:
    """Set identity and emit ``adk.session.start`` once per session.

    Safe to call at the top of every skill: if the current session is still
    active (within the 30-min window) no duplicate start is emitted.
    """
    if tenant_id or instance_id is not None or not _IDENTITY["instance_id"]:
        set_identity(tenant_id=tenant_id, instance_id=instance_id)
    sid, is_new = get_session(surface)
    if not is_new:
        return {"sent": False, "reason": "existing-session", "session_id": sid}
    data = common_dimensions(surface, session_id=sid)
    if adk_capability:
        data["adk_capability"] = adk_capability
    return _emit(EVENT_SESSION_START, data, block=block)


def emit_session_end(
    surface: str = SURFACE_CLI, *, duration_ms: int = 0, block: bool = False
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data["duration_ms"] = int(duration_ms)
    return _emit(EVENT_SESSION_END, data, block=block)


def emit_agent_create(
    *,
    agent_id: str = "",
    adk_capability: str = "onboarding",
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({"agent_id": agent_id, "adk_capability": adk_capability})
    return _emit(EVENT_AGENT_CREATE, data, block=block)


def emit_agent_deploy(
    *,
    agent_id: str = "",
    deploy_target: str = "test",
    adk_capability: str = "publishing",
    outcome: str = "success",
    duration_ms: int = 0,
    error_code: str = "",
    error_message: str = "",
    error_category: str = "",
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({
        "agent_id": agent_id,
        "deploy_target": deploy_target,
        "adk_capability": adk_capability,
        "outcome": outcome,
        "duration_ms": int(duration_ms),
    })
    _apply_error_fields(data, outcome, error_code, error_message, error_category)
    return _emit(EVENT_AGENT_DEPLOY, data, block=block)


def emit_build_start(
    *,
    agent_id: str = "",
    adk_capability: str = "",
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({"agent_id": agent_id, "adk_capability": adk_capability})
    return _emit(EVENT_BUILD_START, data, block=block)


def emit_build_complete(
    *,
    agent_id: str = "",
    adk_capability: str = "",
    outcome: str = "success",
    duration_ms: int = 0,
    error_code: str = "",
    error_message: str = "",
    error_category: str = "",
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({
        "agent_id": agent_id,
        "adk_capability": adk_capability,
        "outcome": outcome,
        "duration_ms": int(duration_ms),
    })
    _apply_error_fields(data, outcome, error_code, error_message, error_category)
    return _emit(EVENT_BUILD_COMPLETE, data, block=block)


def emit_api_call(
    *,
    api_endpoint: str = "",
    outcome: str = "success",
    latency_ms: int = 0,
    error_code: str = "",
    error_message: str = "",
    error_category: str = "",
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({
        "api_endpoint": api_endpoint,
        "outcome": outcome,
        "latency_ms": int(latency_ms),
    })
    _apply_error_fields(data, outcome, error_code, error_message, error_category)
    return _emit(EVENT_API_CALL, data, block=block)


def emit_capability_use(
    adk_capability: str, *, surface: str = SURFACE_CLI, block: bool = False
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data["adk_capability"] = adk_capability
    return _emit(EVENT_CAPABILITY_USE, data, block=block)


def emit_flightcheck_run(
    *,
    agent_id: str = "",
    adk_capability: str = "flightcheck",
    run_index: int = 0,
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({
        "agent_id": agent_id,
        "adk_capability": adk_capability,
        "run_index": int(run_index),
    })
    return _emit(EVENT_FLIGHTCHECK_RUN, data, block=block)


def emit_flightcheck_result(
    *,
    agent_id: str = "",
    adk_capability: str = "flightcheck",
    run_index: int = 0,
    result: str = "pass",
    duration_ms: int = 0,
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({
        "agent_id": agent_id,
        "adk_capability": adk_capability,
        "run_index": int(run_index),
        "result": result,
        "duration_ms": int(duration_ms),
    })
    return _emit(EVENT_FLIGHTCHECK_RESULT, data, block=block)


def emit_flightcheck_error(
    *,
    agent_id: str = "",
    error_code: str = "",
    error_category: str = "runtime",
    error_message: str = "",
    surface: str = SURFACE_CLI,
    block: bool = False,
) -> dict[str, Any]:
    sid, _ = get_session(surface)
    data = common_dimensions(surface, session_id=sid)
    data.update({"agent_id": agent_id})
    _apply_error_fields(data, "server_error", error_code, error_message, error_category)
    return _emit(EVENT_FLIGHTCHECK_ERROR, data, block=block)


# --- CLI: opt-out controls + synthetic emit for validation ----------------
def _emit_synthetic(n: int = 1) -> int:
    """Emit a representative spread of every event type (block, synchronous).

    Used to seed the Aria dashboards with data before real skills run.
    Returns a process exit code (0 if all accepted).
    """
    import random

    # Only emit capabilities that have real telemetry wiring in the ADK
    # (session start -> connect; discover/list_environments -> onboarding;
    # evaluate_evals -> evaluations; push -> publishing; flightcheck/cli ->
    # flightcheck). Other real SKILL.md skills (topic_create/topic_update,
    # troubleshoot, workflows, cleanup) have no emit_* hook yet, so seeding
    # them here would paint the dashboards with capabilities that never appear
    # in production. Keep this list in sync with the capability donut value-lists.
    capabilities = [
        "onboarding", "connect", "evaluations", "publishing", "flightcheck",
    ]
    deploy_targets = ["test", "staging", "production"]
    api_endpoints = ["dataverse/bots", "dataverse/botcomponents", "bap/environments"]
    # Fixed, recognizable demo tenant GUIDs so dashboards are filterable by a
    # known tenant_id (raw OII per approved Data Profile). Weighted so one
    # tenant dominates for a clear "filter to this tenant" demo.
    synth_tenants = (
        ["11111111-1111-1111-1111-111111111111"] * 3  # Contoso (demo, primary)
        + ["22222222-2222-2222-2222-222222222222"] * 2  # Fabrikam (demo)
        + ["33333333-3333-3333-3333-333333333333"]      # Northwind (demo)
    )
    bad = 0
    for _ in range(max(1, n)):
        # Random instance per iteration (so active-install / DAU counts vary),
        # but a fixed-pool tenant so per-tenant filtering returns meaningful
        # slices. No developer/user identifier is ever emitted.
        set_identity(tenant_id=random.choice(synth_tenants), instance_id=str(uuid.uuid4()))
        # Force a brand-new session each iteration; otherwise start_session
        # short-circuits as "existing-session" (30-min window) and only the
        # first loop emits adk.session.start, starving the Sessions cube.
        try:
            os.remove(SESSION_PATH)
        except OSError:
            pass
        cap = random.choice(capabilities)
        agent_id = str(uuid.uuid4())
        emitters = [
            lambda: start_session(adk_capability=cap, block=True),
            lambda: emit_capability_use(cap, block=True),
            lambda: emit_agent_create(agent_id=agent_id, adk_capability="onboarding", block=True),
            lambda: emit_build_start(agent_id=agent_id, adk_capability=cap, block=True),
            lambda: emit_build_complete(
                agent_id=agent_id, adk_capability=cap,
                outcome=random.choice(["success", "success", "failure"]),
                duration_ms=random.randint(800, 9000),
                error_code="BUILD_FAILED", error_category="runtime",
                error_message="synthetic failure",
            ),
            lambda: emit_api_call(
                api_endpoint=random.choice(api_endpoints),
                outcome=random.choice(["success", "success", "client_error", "server_error"]),
                latency_ms=random.randint(40, 2500),
                error_code="HTTP_400", error_category="infra",
            ),
            lambda: emit_agent_deploy(
                agent_id=agent_id, deploy_target=random.choice(deploy_targets),
                outcome=random.choice(["success", "success", "server_error"]),
                duration_ms=random.randint(2000, 30000),
                error_code="DEPLOY_AUTH_FAILURE", error_category="auth",
            ),
            lambda: emit_flightcheck_run(
                agent_id=agent_id, adk_capability=cap, run_index=random.randint(1, 4)),
            lambda: emit_flightcheck_result(
                agent_id=agent_id, adk_capability=cap, run_index=random.randint(1, 4),
                result=random.choice(["pass", "fail", "partial"]),
                duration_ms=random.randint(3000, 45000)),
            lambda: emit_flightcheck_error(
                agent_id=agent_id, error_code="FC_TIMEOUT",
                error_category=random.choice(["runtime", "auth", "infra", "timeout"]),
                error_message="synthetic flightcheck error"),
            lambda: emit_session_end(duration_ms=random.randint(60000, 1800000)),
        ]
        for fn in emitters:
            res = fn()
            if res.get("sent") is False and res.get("reason") != "existing-session":
                bad += 1
    return 1 if bad else 0


def _main(argv: list[str]) -> int:
    args = argv[1:]
    cmd = args[0].lower() if args else "status"

    if cmd in ("on", "enable"):
        set_telemetry(True)
        print("Telemetry: enabled")
        return 0
    if cmd in ("off", "disable"):
        set_telemetry(False)
        print("Telemetry: disabled")
        return 0
    if cmd == "status":
        print(f"Telemetry: {telemetry_status()}")
        return 0
    if cmd in ("selftest", "synth", "synthetic"):
        n = 1
        if len(args) > 1:
            try:
                n = int(args[1])
            except ValueError:
                n = 1
        if not telemetry_enabled():
            print("Telemetry is disabled (ESS_ADK_TELEMETRY=off or opted out).")
            return 0
        _ikey, env = resolve_ikey()
        print(f"Emitting {n} synthetic ADK session(s) to env='{env}'...")
        code = _emit_synthetic(n)
        flush(timeout=10)
        print("  Done." if code == 0 else "  Some events were not accepted.")
        print("  Check the Aria portal Data Inspector for 'adk.*' events "
              "within ~1-2 minutes.")
        return code

    print("Usage: python adk_telemetry.py {on|off|status|synth [N]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
