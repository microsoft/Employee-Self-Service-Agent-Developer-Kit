# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — FlightCheck telemetry (Aria / 1DS OneCollector).

Emits FlightCheck outcome telemetry to Microsoft's 1DS "OneCollector"
ingestion endpoint via a direct, dependency-light HTTPS POST. This is how
the "flight check success rate" (and per-checkpoint pass rates) leadership
asked for get measured: the JS VS Code extension only knows a button was
clicked, but the pass/fail OUTCOME is produced here in Python, so the
outcome events have to be emitted from the runner.

Design rules (all deliberate — read before changing):

* **Fail-open, never block readiness.** Telemetry is best-effort. Any
  failure (no network, bad key, timeout, malformed anything) is swallowed;
  ``emit_flightcheck_telemetry`` never raises and never changes
  FlightCheck's exit code. A telemetry bug must never break a customer's
  readiness check.

* **dev vs prod isolation.** Two separate Aria projects/iKeys exist so dev
  test runs don't pollute the production "success rate" dashboard. The
  active environment is selectable (``ESS_FLIGHTCHECK_ARIA_ENV``); every
  event also carries an ``env`` dimension as defense-in-depth so dashboards
  can hard-filter ``env == 'prod'``. Default is **dev**.

* **Privacy: identifiers + enums only, never free text.** Per the approved
  Data Profile (Data Scout, privacy review COMPLETED) for this feature,
  ``tenant_id`` is classified Organizational Identifiable Information (OII)
  with **"No Data Transformation"** — i.e. emitted as the RAW Microsoft Entra
  tenant GUID (it identifies the enterprise tenant, not an individual user),
  retained <= 30 days. We also emit instance/agent identifiers and
  System-Metadata enums (checkpoint id, category, priority, status, counts,
  verdict). We deliberately DO NOT emit a check's ``result`` or
  ``remediation`` strings — those can contain EUII / customer content
  (file paths, agent names, error fragments). Keep it that way.

iKeys below are 1DS *ingestion* keys: write-only, not secrets, and are
embedded in clients by design (the VS Code extension ships its key in
``package.json``'s ``ariaKey``). Embedding them here is consistent with
1DS guidance.

OneCollector contract (verified against microsoft/ApplicationInsights-JS
``@microsoft/1ds-post-js``, microsoft/vscode ``sendRawTelemetry``,
appcenter-sdk-android/apple, and two Python SDKs):

* POST ``https://mobile.events.data.microsoft.com/OneCollector/1.0/``
  ``?cors=true&content-type=application/x-json-stream``
* Headers: ``apikey`` = FULL iKey, ``Client-Id: NO_AUTH``,
  ``content-type: application/x-json-stream``, ``upload-time`` (epoch ms).
* Body: newline-delimited JSON ("x-json-stream"), one Common Schema 4.0
  envelope per line. A JSON *array* is rejected with HTTP 415.
* Envelope ``iKey`` field = ``o:<tenant-token>`` where tenant-token is the
  substring of the full iKey before the first ``-`` — NOT the full key.
* Success = HTTP 200 or 204.
"""

from __future__ import annotations

import json
import os
import platform
import uuid
from datetime import datetime, timezone
from typing import Any

import requests


# --- iKeys (write-only 1DS ingestion keys; safe to embed) -----------------
# Service Tree node: ADK (99ef9e56-2f29-4c5c-8745-a56ea914d509).
# Group: O365 Engineering Infra.
ARIA_IKEYS = {
    "dev": "08e397b2c6c243eeaeb341e111c36167-294d89f6-c806-4c65-adf3-dea3bb44f949-7206",
    "prod": "311254257bbc417e860c76781d4863c8-8cff75a4-47b7-4675-9646-45a4ca9bc138-7062",
}
# Emit everything to dev for now; flip the default (or set
# ESS_FLIGHTCHECK_ARIA_ENV=prod) when prod metrics are wanted.
DEFAULT_ENV = "dev"

COLLECTOR_URL = (
    "https://mobile.events.data.microsoft.com/OneCollector/1.0/"
    "?cors=true&content-type=application/x-json-stream"
)

EVENT_RUN = "ESSMakerKit.FlightCheck.Run"
EVENT_CHECK = "ESSMakerKit.FlightCheck.Check"

# Bump when the emitted field set changes so dashboards can version-gate.
TELEMETRY_SCHEMA_VERSION = "1.0"

# Short, fail-open timeout (connect, read) seconds. Telemetry runs at the
# very end of a FlightCheck; we never want it to hang the CLI.
_POST_TIMEOUT = (3.05, 5)


def _env_disabled() -> bool:
    """True if telemetry is explicitly turned off via env var."""
    val = os.environ.get("ESS_FLIGHTCHECK_TELEMETRY", "").strip().lower()
    return val in ("0", "off", "false", "no", "disabled")


def resolve_ikey() -> tuple[str | None, str]:
    """Resolve the active (iKey, env_label).

    Precedence:
      1. ``ESS_FLIGHTCHECK_TELEMETRY`` off  -> (None, env) (disabled)
      2. ``ESS_FLIGHTCHECK_ARIA_IKEY``      -> explicit key override
      3. ``ESS_FLIGHTCHECK_ARIA_ENV``       -> 'dev' | 'prod' (default dev)
    """
    env = os.environ.get("ESS_FLIGHTCHECK_ARIA_ENV", DEFAULT_ENV).strip().lower()
    if env not in ARIA_IKEYS:
        env = DEFAULT_ENV
    if _env_disabled():
        return None, env
    override = os.environ.get("ESS_FLIGHTCHECK_ARIA_IKEY", "").strip()
    if override:
        return override, env
    return ARIA_IKEYS[env], env


def envelope_ikey(full_ikey: str) -> str:
    """Map a full ingestion key to the CS4.0 envelope ``iKey`` form.

    ``o:`` + the tenant token (the part before the first ``-``).
    """
    return "o:" + full_ikey.split("-", 1)[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_ms(dt: datetime) -> str:
    """ISO8601 UTC with millisecond precision and a ``Z`` suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def get_instance_id(local_dir: str = ".local") -> str:
    """Return a stable, client-generated instance id (System Metadata).

    A random GUID generated once per install and persisted to
    ``.local/.instance_id``. It is NOT derived from and NOT linkable to any
    AAD user identity — it only correlates telemetry from the same install.
    On any IO error a fresh ephemeral GUID is returned (still valid, just
    not persisted).
    """
    path = os.path.join(local_dir, ".instance_id")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                return existing
        new_id = str(uuid.uuid4())
        os.makedirs(local_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_id)
        return new_id
    except OSError:
        return str(uuid.uuid4())


def get_adk_version() -> str:
    """Best-effort ADK version string (System Metadata).

    Order: ``ESS_ADK_VERSION`` env override -> the shipped VS Code
    extension's ``package.json`` version -> ``"unknown"``.
    """
    override = os.environ.get("ESS_ADK_VERSION", "").strip()
    if override:
        return override
    # Walk up from this file looking for the extension manifest.
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(8):
        candidate = os.path.join(
            cur, "tools", "ess-maker-profile", "extension", "package.json"
        )
        try:
            if os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    return str(json.load(f).get("version") or "unknown")
        except (OSError, ValueError):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return "unknown"


def _build_event(name: str, ikey_envelope: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal Common Schema 4.0 envelope.

    ``ext`` is omitted (optional). Custom fields live flat in ``data``.
    """
    return {
        "ver": "4.0",
        "name": name,
        "time": _iso_ms(_now()),
        "iKey": ikey_envelope,
        "data": data,
    }


def serialize_ndjson(events: list[dict[str, Any]]) -> bytes:
    """Serialize events as newline-delimited JSON (x-json-stream).

    One compact JSON object per line, trailing newline. NEVER a JSON array
    (the collector rejects arrays with HTTP 415).
    """
    lines = [json.dumps(e, separators=(",", ":")) for e in events]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _post(ikey: str, events: list[dict[str, Any]]) -> int:
    """POST a batch of envelopes. Returns the HTTP status code.

    Raises only on transport errors (caller swallows them).
    """
    now = _now()
    resp = requests.post(
        COLLECTOR_URL,
        data=serialize_ndjson(events),
        headers={
            "apikey": ikey,  # FULL key in header
            "Client-Id": "NO_AUTH",
            "client-version": f"ess-maker-flightcheck-{get_adk_version()}",
            "content-type": "application/x-json-stream",
            "upload-time": str(int(now.timestamp() * 1000)),
            "cache-control": "no-cache, no-store",
            "NoResponseBody": "true",
        },
        timeout=_POST_TIMEOUT,
    )
    return resp.status_code


def _run_data(
    run_result: Any,
    *,
    env: str,
    run_id: str,
    instance_id: str,
    tenant_id: str,
    agent_id: str,
    agent_count: int,
    scope: str,
    invocation_source: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": TELEMETRY_SCHEMA_VERSION,
        "env": env,
        "runId": run_id,
        "instanceId": instance_id,   # System Metadata
        "tenantId": tenant_id,       # OII (raw Entra tenant GUID; approved Data Profile)
        "agentId": agent_id,         # OII
        "agentCount": agent_count,
        "adkVersion": get_adk_version(),
        "scope": scope,
        "invocationSource": invocation_source,
        "overall": getattr(run_result, "overall", ""),
        "durationSecs": getattr(run_result, "duration_secs", 0),
        "total": getattr(run_result, "total", 0),
        "passed": getattr(run_result, "passed", 0),
        "failed": getattr(run_result, "failed", 0),
        "warnings": getattr(run_result, "warnings", 0),
        "notConfigured": getattr(run_result, "not_configured", 0),
        "manual": getattr(run_result, "manual", 0),
        "skipped": getattr(run_result, "skipped", 0),
        "errors": getattr(run_result, "errors", 0),
        "pythonVersion": platform.python_version(),
        "os": platform.system(),
    }


def _check_data(
    check: Any,
    *,
    env: str,
    run_id: str,
    instance_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    # Identifiers + enums ONLY. Never `result` / `remediation` (EUII risk).
    return {
        "schemaVersion": TELEMETRY_SCHEMA_VERSION,
        "env": env,
        "runId": run_id,
        "instanceId": instance_id,
        "tenantId": tenant_id,
        "checkpointId": getattr(check, "checkpoint_id", ""),
        "category": getattr(check, "category", ""),
        "priority": getattr(check, "priority", ""),
        "status": getattr(check, "status", ""),
        "roles": ", ".join(getattr(check, "roles", []) or []),
    }


def build_events(
    run_result: Any,
    *,
    env: str,
    instance_id: str,
    tenant_id: str,
    agent_id: str,
    agent_count: int,
    scope: str,
    invocation_source: str,
    ikey_envelope: str,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build the run envelope + one envelope per check (testable, no IO)."""
    run_id = run_id or str(uuid.uuid4())
    events = [
        _build_event(
            EVENT_RUN,
            ikey_envelope,
            _run_data(
                run_result,
                env=env,
                run_id=run_id,
                instance_id=instance_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                agent_count=agent_count,
                scope=scope,
                invocation_source=invocation_source,
            ),
        )
    ]
    for check in getattr(run_result, "results", []) or []:
        events.append(
            _build_event(
                EVENT_CHECK,
                ikey_envelope,
                _check_data(
                    check,
                    env=env,
                    run_id=run_id,
                    instance_id=instance_id,
                    tenant_id=tenant_id,
                ),
            )
        )
    return events


def emit_flightcheck_telemetry(
    run_result: Any,
    *,
    tenant_id: str = "",
    agent_id: str = "",
    scope: str = "",
    agent_count: int = 0,
    invocation_source: str = "cli",
    instance_id: str | None = None,
    local_dir: str = ".local",
) -> dict[str, Any]:
    """Emit FlightCheck telemetry. Best-effort; NEVER raises.

    Returns a small status dict (useful for tests / debugging):
      ``{"sent": bool, "events": int, "status": int|None, "env": str,
         "reason": str}``.
    """
    ikey, env = resolve_ikey()
    if not ikey:
        return {"sent": False, "events": 0, "status": None, "env": env,
                "reason": "disabled"}
    try:
        if instance_id is None:
            instance_id = get_instance_id(local_dir)
        events = build_events(
            run_result,
            env=env,
            instance_id=instance_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            agent_count=agent_count,
            scope=scope,
            invocation_source=invocation_source,
            ikey_envelope=envelope_ikey(ikey),
        )
        status = _post(ikey, events)
        ok = status in (200, 204)
        return {"sent": ok, "events": len(events), "status": status,
                "env": env, "reason": "ok" if ok else f"http {status}"}
    except Exception as e:  # noqa: BLE001 — telemetry must never break the run
        return {"sent": False, "events": 0, "status": None, "env": env,
                "reason": f"{type(e).__name__}: {e}"}


def selftest() -> int:
    """Send one synthetic event and print the result. Returns process code.

    Run: ``python scripts/flightcheck/telemetry.py --selftest``
    """
    ikey, env = resolve_ikey()
    if not ikey:
        print("Telemetry is disabled (ESS_FLIGHTCHECK_TELEMETRY=off).")
        return 0
    event = _build_event(
        EVENT_RUN,
        envelope_ikey(ikey),
        {
            "schemaVersion": TELEMETRY_SCHEMA_VERSION,
            "env": env,
            "selftest": True,
            "runId": str(uuid.uuid4()),
            "instanceId": get_instance_id(),
            "adkVersion": get_adk_version(),
        },
    )
    print(f"Posting selftest event to env='{env}' "
          f"(iKey tenant token {envelope_ikey(ikey)})...")
    try:
        status = _post(ikey, [event])
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED (transport error): {type(e).__name__}: {e}")
        return 1
    ok = status in (200, 204)
    print(f"  HTTP {status} — {'OK (accepted)' if ok else 'NOT accepted'}")
    print("  Check the Aria portal real-time/Data Inspector for "
          f"event '{EVENT_RUN}' within ~1-2 minutes.")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    print("Usage: python telemetry.py --selftest")
