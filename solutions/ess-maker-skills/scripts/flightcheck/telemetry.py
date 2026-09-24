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
  can hard-filter ``env == 'prod'``. Default is **prod** (real maker runs go
  to prod); set ``ESS_FLIGHTCHECK_ARIA_ENV=dev`` for test / seeding runs.

* **Privacy: identifiers + enums only, never free text.** Per the approved
  Data Profile (Data Scout, privacy review COMPLETED) for this feature,
  ``tenant_id`` is classified Organizational Identifiable Information (OII)
  with **"No Data Transformation"** — i.e. emitted as the RAW Microsoft Entra
  tenant GUID (it identifies the enterprise tenant, not an individual user),
  retained <= 30 days. ``tenant_name`` (the tenant's organization display
  name from Graph ``/organization``) is likewise OII identifying the
  enterprise tenant, not a person; privacy review gave the green light to
  emit it without a Data Profile update. It is best-effort — emitted as ``""``
  when unavailable. We also emit instance/agent identifiers and
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
import re
import tempfile
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import requests


# --- iKeys (write-only 1DS ingestion keys; safe to embed) -----------------
# Service Tree node: ADK (99ef9e56-2f29-4c5c-8745-a56ea914d509).
# Group: O365 Engineering Infra.
ARIA_IKEYS = {
    "dev": "08e397b2c6c243eeaeb341e111c36167-294d89f6-c806-4c65-adf3-dea3bb44f949-7206",
    "prod": "311254257bbc417e860c76781d4863c8-8cff75a4-47b7-4675-9646-45a4ca9bc138-7062",
}
# Emit real maker runs to prod. Set ESS_FLIGHTCHECK_ARIA_ENV=dev (or
# ESS_ADK_ARIA_ENV=dev) for local testing / dashboard seeding so those runs
# don't pollute the production "success rate" dashboard.
DEFAULT_ENV = "prod"

COLLECTOR_URL = (
    "https://mobile.events.data.microsoft.com/OneCollector/1.0/"
    "?cors=true&content-type=application/x-json-stream"
)

EVENT_RUN = "ESSMakerKit.FlightCheck.Run"
EVENT_CHECK = "ESSMakerKit.FlightCheck.Check"

# Bump when the emitted field set changes so dashboards can version-gate.
# 1.1: added derived ``tenantClass`` (internal vs customer) — ADO 7558661.
# 1.2: added ``toolkitGitSha`` + ``toolkitGitBranch`` for precise
# upgrade-posture and CA-vs-DA attribution — ADO 7943642.
# 1.3: added derived ``agentType`` (custom_agent | declarative_agent |
# unknown) driven by ``toolkitGitBranch`` — ADO 7830949.
TELEMETRY_SCHEMA_VERSION = "1.3"

# Short, fail-open timeout (connect, read) seconds. Telemetry runs at the
# very end of a FlightCheck; we never want it to hang the CLI.
_POST_TIMEOUT = (3.05, 5)


# --- Tenant classification (ADO 7558661) ----------------------------------
# Report internal Microsoft dogfood/testing traffic separately from real
# external customer usage. ``tenant_class`` is DERIVED from ``tenant_id`` — a
# coarse, non-identifying bucket (strictly lower sensitivity than the raw
# tenant GUID it is computed from). It is classified at EMIT time, not in the
# Aria cube, because 1DS RTA cubes map an event property straight to a
# dimension and cannot derive one dimension's value from another.
#
# Seeded with the Microsoft corporate Entra tenant plus known internal
# dogfood/demo tenants that we own. Additional internal / dogfood tenants
# can be added WITHOUT a code change via the ``ESS_ADK_INTERNAL_TENANTS``
# env var (comma-separated GUIDs) — preferred for one-off / short-lived
# additions; the hard-coded list is for well-known, long-lived tenancies.
MICROSOFT_CORP_TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
# EmployeeHub dogfood tenant (team-owned; see PR #242 / customer-attribution
# analysis).
EMPLOYEEHUB_TENANT_ID = "935884d7-bdee-469b-a461-fcc530a3ac83"
# ESS internal demo/test tenants surfaced by usage analysis. tenant_name
# lookup during the auth path resolves these to ``Contoso`` and
# ``Crontoso, Inc`` respectively; both are internal test tenancies.
CONTOSO_INTERNAL_TENANT_ID = "ed667978-98e2-41a3-ad41-bafc8f728f02"
CRONTOSO_INTERNAL_TENANT_ID = "99f9fd00-6145-4c3e-b3ba-d4c7e59470d8"
# Cocreate test tenancy (``TESTTEST_Cocreate_06302026`` /
# ``devtestcocreate0630.onmicrosoft.com``); internal dev/test only.
COCREATE_TEST_TENANT_ID = "8d36aacf-bbb3-4388-ac14-8844210f377b"

# Well-known internal Microsoft tenancies. Kept as a module-level constant
# so tests and analytics tooling can enumerate the same set.
_HARDCODED_INTERNAL_TENANT_IDS: frozenset[str] = frozenset(
    {
        MICROSOFT_CORP_TENANT_ID,
        EMPLOYEEHUB_TENANT_ID,
        CONTOSO_INTERNAL_TENANT_ID,
        CRONTOSO_INTERNAL_TENANT_ID,
        COCREATE_TEST_TENANT_ID,
    }
)

TENANT_CLASS_INTERNAL = "internal"
TENANT_CLASS_CUSTOMER = "customer"
TENANT_CLASS_UNKNOWN = "unknown"

# Canonical Entra tenant GUID (8-4-4-4-12 lowercase hex). Used by
# ``get_cached_tenant_id`` to validate the legacy raw-string cache format
# so a torn / hand-edited / garbage ``.tenant_id`` file can never leak onto
# real events. Duplicated from ``adk_telemetry._GUID_RE`` (this module
# cannot import from adk_telemetry — the dependency direction goes the
# other way); the two regexes are kept in lock-step by a regression test
# in ``test_adk_telemetry.py``.
_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _internal_tenant_ids() -> frozenset[str]:
    """Allow-list of tenant GUIDs treated as internal Microsoft tenancy.

    The env var is still consulted on every call (a cheap dict lookup), so a
    changed ``ESS_ADK_INTERNAL_TENANTS`` is honored without a restart, but the
    frozenset build is cached on the raw env-var string so hot paths
    (``common_dimensions``, per-check events, synthetic seeding) don't rebuild
    it every call.
    """
    return _parse_internal_tenant_ids(os.environ.get("ESS_ADK_INTERNAL_TENANTS", ""))


@lru_cache(maxsize=8)
def _parse_internal_tenant_ids(extra: str) -> frozenset[str]:
    """Parse the comma-separated allow-list, cached per distinct env value."""
    ids = set(_HARDCODED_INTERNAL_TENANT_IDS)
    ids.update(t.strip().lower() for t in extra.split(",") if t.strip())
    return frozenset(ids)


def classify_tenant(tenant_id: str) -> str:
    """Map a raw Entra tenant GUID to ``internal`` | ``customer`` | ``unknown``.

    Empty / missing tenant -> ``unknown`` (we never guess). A tenant in the
    internal allow-list -> ``internal``. Any well-formed non-internal Entra
    tenant GUID -> ``customer``. Case/whitespace-insensitive.

    Defense-in-depth: a non-empty ``tenant_id`` that is **not** a canonical
    Entra tenant GUID (test-fixture placeholders like ``"tenant-id"``, org
    display names accidentally routed here, truncated / garbage values that
    escaped ``set_identity``'s sanitizer, hand-edited cache files) maps to
    ``unknown`` rather than ``customer``. Without this guard the External
    dashboard's ``tenant_class == "customer"`` filter would silently absorb
    any such value into the customer bucket — the exact failure mode that
    produced 391 fixture-leak events in prod before the autouse conftest
    guard landed. Aligns with the guarantee ``adk_telemetry._sanitize_tenant_id``
    already gives at the identity ingress layer, and the same _GUID_RE
    validation ``get_cached_tenant_id`` applies to the on-disk cache.

    The internal allow-list is checked BEFORE the GUID shape check so that
    non-GUID strings added to ``ESS_ADK_INTERNAL_TENANTS`` (e.g. a
    non-canonical CI marker) still classify as ``internal``.
    """
    if not tenant_id:
        return TENANT_CLASS_UNKNOWN
    v = str(tenant_id).strip().lower()
    if v in _internal_tenant_ids():
        return TENANT_CLASS_INTERNAL
    if not _GUID_RE.match(v):
        return TENANT_CLASS_UNKNOWN
    return TENANT_CLASS_CUSTOMER


def _env_disabled() -> bool:
    """True if telemetry is explicitly turned off via env var."""
    val = os.environ.get("ESS_FLIGHTCHECK_TELEMETRY", "").strip().lower()
    return val in ("0", "off", "false", "no", "disabled")


def _consent_disabled() -> bool:
    """True if the maker opted out via the unified opt-out control.

    The consent notice we print tells makers to run
    ``python scripts/adk_telemetry.py off`` to disable telemetry. That writes
    ``~/.adk/config`` (and/or sets ``ESS_ADK_TELEMETRY``), which the ``adk.*``
    emitter honors. Consult the same signal here so that single documented
    opt-out ALSO silences these legacy ``ESSMakerKit.FlightCheck.*`` events —
    otherwise a maker who follows the instruction is still tracked. Best-effort:
    if ``adk_telemetry`` can't be imported, fall back to the FlightCheck-specific
    env var only.
    """
    try:
        import adk_telemetry  # sibling module (scripts/ is on sys.path)

        return not adk_telemetry.telemetry_enabled()
    except Exception:  # noqa: BLE001 — never let opt-out resolution raise
        return False


def resolve_ikey() -> tuple[str | None, str]:
    """Resolve the active (iKey, env_label).

    Precedence:
      1. ``ESS_FLIGHTCHECK_TELEMETRY`` off / opted-out via
         ``python scripts/adk_telemetry.py off`` -> (None, env)
      2. ``ESS_FLIGHTCHECK_ARIA_IKEY``      -> explicit key override
      3. ``ESS_FLIGHTCHECK_ARIA_ENV``       -> 'dev' | 'prod' (default prod)
    """
    env = os.environ.get("ESS_FLIGHTCHECK_ARIA_ENV", DEFAULT_ENV).strip().lower()
    if env not in ARIA_IKEYS:
        env = DEFAULT_ENV
    if _env_disabled() or _consent_disabled():
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


# Persisted tenant display name ({tenant_id, tenant_name}) so ADK events that
# run in a *later* process without a Microsoft Graph token (session start,
# build, deploy, capability, api — see adk_telemetry.py) can still stamp the
# org name. Only a Graph-capable flow (FlightCheck) can resolve it live; it
# caches the result here and the pure-ADK paths read it back. The cache is
# keyed by tenant_id so a name resolved for one tenant is never reused for a
# different tenant (e.g. a maker who switches tenants between runs).
_TENANT_NAME_FILE = ".tenant_name"


def cache_tenant_name(
    tenant_id: str,
    tenant_name: str,
    local_dir: str = ".local",
    source: str = "organization",
) -> None:
    """Persist the resolved org display name for reuse by later ADK events.

    Best-effort: any IO error is swallowed (telemetry must never break a
    flow). No-op when either value is empty — we only cache a real, resolved
    ``(tenant_id, tenant_name)`` pair. ``tenant_name`` is OII (org display
    name); it is written under the gitignored ``.local/`` dir on the maker's
    own machine, mirroring how ``.instance_id`` is persisted.

    ``source`` records where the name came from. ``"organization"`` means it
    came from Graph's ``/organization`` endpoint — the authoritative source.
    ``"me"`` means it came from ``/me?$select=companyName``, which is a
    per-user attribute (some tenants leave it unset or use a different
    display value than the org record). A cached ``"organization"`` entry
    is never overwritten by an ``"me"`` entry for the same tenant, so a
    single unlucky call can't downgrade the label the whole dashboard uses.
    A same-tenant write with the *same or better* source (organization ≥ me)
    always wins.
    """
    if not tenant_id or not tenant_name:
        return
    path = os.path.join(local_dir, _TENANT_NAME_FILE)
    _rank = {"organization": 2, "me": 1}
    new_rank = _rank.get(source, 0)
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if (
            isinstance(existing, dict)
            and existing.get("tenant_id") == tenant_id
            and _rank.get(existing.get("source", "organization"), 0) > new_rank
        ):
            return
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(local_dir, exist_ok=True)
        # Atomic write via tempfile + os.replace, matching cache_tenant_id.
        # A concurrent reader (a sibling emit_capability.py subprocess spawned
        # from a SKILL.md step) must never see a truncated file — otherwise
        # the reader would fall back to a blank tenant_name for the whole
        # session, undoing the very cache we're populating.
        payload = {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "source": source,
        }
        fd, tmp = tempfile.mkstemp(prefix=".tenant_name.", dir=local_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except OSError:
        pass


# Persisted raw tenant GUID so ADK events emitted from a *fresh Python
# subprocess* (e.g. `python scripts/emit_capability.py <cap>` invoked from a
# SKILL.md step) can still stamp the tenant_id — without this, the subprocess'
# in-memory ``_IDENTITY["tenant_id"]`` is empty, ``classify_tenant("")`` returns
# ``unknown``, and the event never lands on the External (``tenant_class ==
# "customer"``) dashboard. Separate file from ``.tenant_name`` because tenant_id
# is available before (and even without) any Graph tenant-name resolution.
_TENANT_ID_FILE = ".tenant_id"


def cache_tenant_id(tenant_id: str, local_dir: str = ".local") -> None:
    """Persist the raw tenant GUID for reuse by later same-install processes.

    Best-effort: any IO error is swallowed (telemetry must never break a
    flow). No-op when ``tenant_id`` is empty — we never persist a placeholder.
    The value is written under the gitignored ``.local/`` dir on the maker's
    own machine, mirroring how ``.instance_id`` is persisted. Overwrites any
    prior value so a maker who switches tenants sees the latest one.

    Write is atomic (``tempfile`` + ``os.replace``) so a concurrent reader
    can never observe a truncated / half-written file — otherwise the reader
    would silently see ``""`` and stamp the event as anonymous. Stored as
    versioned JSON so a torn / legacy write from an older ADK build is
    recognizable and discarded on read.
    """
    if not tenant_id:
        return
    path = os.path.join(local_dir, _TENANT_ID_FILE)
    payload = {"version": 1, "tenant_id": str(tenant_id).strip()}
    try:
        os.makedirs(local_dir, exist_ok=True)
        # tempfile.NamedTemporaryFile with delete=False so we can rename it in
        # place with os.replace, which is atomic on POSIX AND Windows.
        fd, tmp = tempfile.mkstemp(prefix=".tenant_id.", dir=local_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except OSError:
        pass


def get_cached_tenant_id(local_dir: str = ".local") -> str:
    """Return the persisted tenant GUID, or ``""`` if unavailable/unreadable.

    Reads the versioned JSON produced by ``cache_tenant_id`` and validates
    the schema before returning the value. A missing / malformed / wrong-
    schema-version file returns ``""`` — the caller's fallback path treats
    that as "no cache" and either uses the in-memory identity or lets
    ``classify_tenant`` label the event ``"unknown"``. That is safer than
    returning a torn / legacy raw string that would silently ride onto
    real events.

    A very small compatibility shim recognizes the pre-versioning raw-string
    format (a single line whose contents look like a canonical GUID) so a
    maker who upgrades mid-session doesn't lose their cached tenant. The
    raw string is validated against ``_GUID_RE`` (case-insensitive) before
    being returned; any other content (truncated GUID, non-hex, garbage,
    JSON at a future schema version) is discarded.
    """
    path = os.path.join(local_dir, _TENANT_ID_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        return ""
    if not raw:
        return ""
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
        except ValueError:
            return ""
        if not isinstance(obj, dict) or obj.get("version") != 1:
            return ""
        return str(obj.get("tenant_id", "")).strip()
    # Legacy raw-string format from pre-versioned ADK builds: only trust the
    # value when it matches the canonical GUID shape. Otherwise return ""
    # and let the caller's fallback path (or classify_tenant) treat it as
    # unknown — never leak a torn / hand-edited / garbage cache onto real
    # events. Matches the docstring guarantee above.
    v = raw.lower()
    return v if _GUID_RE.match(v) else ""


def get_cached_tenant_name(tenant_id: str, local_dir: str = ".local") -> str:
    """Return the cached org display name IFF it matches ``tenant_id``.

    Returns ``""`` when there is no cache, the cache is unreadable/malformed,
    or the cached tenant_id doesn't match the current one (so a name resolved
    for a different tenant is never leaked onto this tenant's events).
    """
    if not tenant_id:
        return ""
    path = os.path.join(local_dir, _TENANT_NAME_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict) or data.get("tenant_id") != tenant_id:
        return ""
    name = data.get("tenant_name")
    return name if isinstance(name, str) else ""


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


def _find_git_dir() -> str:
    """Walk up from this file until a ``.git`` directory (or file) is
    found. Returns the absolute path of the ``.git`` entry, or ``""`` if
    no repo is found within a safe walk depth.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(10):
        candidate = os.path.join(cur, ".git")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ""


# Bounded set of branch classifications emitted as toolkit_git_branch.
# Anything outside this set (personal branches, fork names, customer
# labels, aliases) collapses to "other" to avoid leaking free-form
# identifiers per the privacy contract documented in CONTRIBUTING.md and
# solutions/ess-maker-skills/README.md. Extend this set only after a
# privacy review approves the new value(s).
_ALLOWED_BRANCHES = frozenset({"main", "main-ca"})


def _classify_branch(branch: str) -> str:
    """Collapse an arbitrary branch string to one of the allowed values.

    Returns one of: ``main``, ``main-ca``, ``detached``, ``other``,
    ``unknown``. All personal / fork / topic branch names collapse to
    ``other`` so branch names never appear in telemetry.
    """
    if not branch:
        return "unknown"
    if branch == "detached" or branch == "unknown":
        return branch
    if branch in _ALLOWED_BRANCHES:
        return branch
    return "other"


def _is_short_sha(value: str) -> bool:
    """True if ``value`` looks like a hex commit ID (>=7 chars, all hex)."""
    if not value or len(value) < 7 or len(value) > 40:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _resolve_git_dirs(git_dir: str) -> tuple[str, str]:
    """Return ``(gitdir, commondir)`` for a ``.git`` entry.

    ``gitdir`` is the per-worktree administrative directory (holds
    ``HEAD``); ``commondir`` is the shared directory that holds
    ``refs/`` and ``packed-refs`` for real linked worktrees. For a
    plain non-worktree checkout the two are identical.

    Returns ``("", "")`` on any error so callers fail open.
    """
    try:
        # ``.git`` may be a file for worktrees / submodules pointing at
        # the real per-worktree gitdir via ``gitdir: <path>``.
        if os.path.isfile(git_dir):
            with open(git_dir, "r", encoding="utf-8") as f:
                content = f.read().strip()
            prefix = "gitdir:"
            if not content.startswith(prefix):
                return ("", "")
            real = content[len(prefix):].strip()
            if not os.path.isabs(real):
                real = os.path.normpath(
                    os.path.join(os.path.dirname(git_dir), real)
                )
            git_dir = real
        # Linked worktrees drop a ``commondir`` file in the per-worktree
        # gitdir pointing at the shared administrative directory (which
        # holds refs/ and packed-refs). Plain checkouts have no
        # ``commondir`` file, so gitdir IS commondir.
        commondir = git_dir
        commondir_file = os.path.join(git_dir, "commondir")
        if os.path.exists(commondir_file):
            with open(commondir_file, "r", encoding="utf-8") as f:
                rel = f.read().strip()
            if rel:
                if not os.path.isabs(rel):
                    rel = os.path.normpath(os.path.join(git_dir, rel))
                commondir = rel
        return (git_dir, commondir)
    except (OSError, ValueError, UnicodeDecodeError):
        return ("", "")


@lru_cache(maxsize=1)
def get_toolkit_git_sha() -> str:
    """Best-effort short git SHA of the ADK clone (System Metadata).

    Precise upgrade-posture signal: ``adk_version`` (extension package.json
    version) can lag the actual toolkit state — for example a hotfix on the
    same extension version, or an install that was cloned before the version
    bump landed. The short SHA lets dashboards distinguish "install is on
    latest bits" from "install is on last-week's tree at the same version".

    Order: ``ESS_ADK_GIT_SHA`` env override (used by CI to inject a known
    build SHA) -> ``.git/HEAD`` + ref file read (no subprocess) -> ``"unknown"``.

    Overrides go through the same canonicalization as repo-derived values
    (lowercased, validated hex, truncated to 7 chars) so an env-injected
    build SHA doesn't create a distinct telemetry bucket from the same
    commit resolved via ``.git``.

    Fail-open: any error (missing repo, malformed HEAD, unreadable file)
    resolves to ``"unknown"`` so telemetry never blocks the CLI.
    """
    override = os.environ.get("ESS_ADK_GIT_SHA", "").strip().lower()
    if override:
        # Apply the same validation as repo-derived values so an
        # env-injected build SHA and a git-resolved SHA land in the
        # same telemetry bucket for the same commit.
        return override[:7] if _is_short_sha(override) else "unknown"
    git_dir = _find_git_dir()
    if not git_dir:
        return "unknown"
    gitdir, commondir = _resolve_git_dirs(git_dir)
    if not gitdir:
        return "unknown"
    try:
        # HEAD is per-worktree — read it from gitdir. Refs and packed-refs
        # live in the common directory for real linked worktrees, so read
        # them from commondir.
        head_path = os.path.join(gitdir, "HEAD")
        if not os.path.exists(head_path):
            return "unknown"
        with open(head_path, "r", encoding="utf-8") as f:
            head = f.read().strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            # Resolve the ref file in the common directory; fall back to
            # packed-refs if unpacked.
            ref_path = os.path.join(commondir, ref)
            if os.path.exists(ref_path):
                with open(ref_path, "r", encoding="utf-8") as f:
                    sha = f.read().strip()
            else:
                packed = os.path.join(commondir, "packed-refs")
                if not os.path.exists(packed):
                    return "unknown"
                sha = ""
                with open(packed, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.endswith(" " + ref):
                            sha = line.split(" ", 1)[0].strip()
                            break
                if not sha:
                    return "unknown"
        else:
            # Detached HEAD: HEAD contains the SHA directly.
            sha = head
        sha = sha.lower()
        if not _is_short_sha(sha):
            return "unknown"
        return sha[:7]
    except (OSError, ValueError, UnicodeDecodeError):
        return "unknown"


@lru_cache(maxsize=1)
def get_toolkit_git_branch() -> str:
    """Best-effort git branch classification of the ADK clone (System Metadata).

    Returns one of a **bounded** set of strings so raw branch names —
    which can carry aliases, personal names, customer labels, or other
    free-form content — are never emitted:

    * ``"main"``      — on the shipping DA branch (or an override says so)
    * ``"main-ca"``   — on the shipping CA branch (used by ADO #7830949
      for CA vs DA attribution)
    * ``"detached"``  — HEAD points directly at a commit (no branch),
      confirmed by a valid hex commit ID in HEAD
    * ``"other"``     — on some other branch (topic / fork / customer
      label); collapsed to a single bucket for privacy
    * ``"unknown"``   — no repo, malformed HEAD, or any error

    Order: ``ESS_ADK_GIT_BRANCH`` env override (also classified against
    the bounded set) -> ``.git/HEAD`` ref parse -> ``"unknown"``.

    Fail-open: any error resolves to ``"unknown"``.
    """
    override = os.environ.get("ESS_ADK_GIT_BRANCH", "").strip()
    if override:
        return _classify_branch(override)
    git_dir = _find_git_dir()
    if not git_dir:
        return "unknown"
    gitdir, _commondir = _resolve_git_dirs(git_dir)
    if not gitdir:
        return "unknown"
    try:
        head_path = os.path.join(gitdir, "HEAD")
        if not os.path.exists(head_path):
            return "unknown"
        with open(head_path, "r", encoding="utf-8") as f:
            head = f.read().strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            # ``refs/heads/<branch>`` -> ``<branch>``. Anything else
            # (tag ref, remote-tracking) falls through to unknown.
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                return _classify_branch(ref[len(prefix):])
            return "unknown"
        # No ``ref:`` prefix: HEAD contains a commit ID directly, IFF it
        # actually parses as one. A malformed HEAD (empty, garbage,
        # partial write) shouldn't masquerade as "detached HEAD" — that
        # would emit ``branch=detached`` alongside ``sha=unknown``, which
        # is a lie about the checkout state.
        return "detached" if _is_short_sha(head.lower()) else "unknown"
    except (OSError, ValueError, UnicodeDecodeError):
        return "unknown"


# --- Agent-type classification (ADO #7830949) -----------------------------
# Distinguishes Custom Agent (CA) makers from Declarative Agent (DA) makers
# so PMs can split adoption / capability / build / FlightCheck dashboards
# by agent type. The signal is the ADK clone's current git branch: the CEA
# (Custom Agent) migration lives on ``main-ca``; the DA-GA line lives on
# ``main``. Anything else (a personal working branch, a detached tag,
# ``"unknown"`` when git resolution failed) is bucketed to ``"unknown"``
# so out-of-taxonomy values never leak into the two named buckets.
#
# Emitted as a common dimension on every ADK / FlightCheck event, so a
# single query can attribute any event stream (capability, build, deploy,
# api, session, flightcheck) to the correct audience.
AGENT_TYPE_CUSTOM = "custom_agent"
AGENT_TYPE_DECLARATIVE = "declarative_agent"
AGENT_TYPE_UNKNOWN = "unknown"
AGENT_TYPES = frozenset({AGENT_TYPE_CUSTOM, AGENT_TYPE_DECLARATIVE, AGENT_TYPE_UNKNOWN})


def classify_agent_type(git_branch: str) -> str:
    """Map a git branch name to the ``agent_type`` common dimension.

    ``main-ca`` -> ``custom_agent``. ``main`` -> ``declarative_agent``.
    Anything else -> ``unknown`` (personal branches, tags, detached
    HEAD, ``"unknown"`` when git resolution failed).

    Case- and whitespace-insensitive on the branch name so a caller that
    pre-normalizes (or a future CI override that pads whitespace) still
    lands in the intended bucket.
    """
    if not git_branch:
        return AGENT_TYPE_UNKNOWN
    normalized = git_branch.strip().lower()
    if normalized == "main-ca":
        return AGENT_TYPE_CUSTOM
    if normalized == "main":
        return AGENT_TYPE_DECLARATIVE
    return AGENT_TYPE_UNKNOWN


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


# Run-outcome buckets for the "Runs by Verdict" donut. Finer-grained than
# ``overall``: it splits the NOT_READY verdict into "a check couldn't even run"
# (``errored`` — an unhandled exception inside a check, runner.py:135) vs.
# "checks ran and reported failures" (``failed``). Precedence is errored ->
# failed -> warnings -> ready so the donut surfaces checks that could not be
# evaluated at all (the "why did FlightCheck fail to run" signal). We can NOT
# attribute WHY a check errored (auth vs runtime vs network) — the exception
# text is never emitted (EUII risk) — so the bucket is deliberately just
# "errored", not "runtime error". Aria renders the raw value as the slice
# label (no per-value aliasing), so the values are human-readable.
RUN_OUTCOME_READY = "Ready"
RUN_OUTCOME_WARNINGS = "Ready with warnings"
RUN_OUTCOME_FAILED = "Failed"
RUN_OUTCOME_ERRORED = "Blocked (check errored)"


def derive_run_outcome(run_result: Any) -> str:
    """Bucket a run into a single verdict slice (errored > failed > warnings > ready)."""
    errors = getattr(run_result, "errors", 0) or 0
    failed = getattr(run_result, "failed", 0) or 0
    warnings = getattr(run_result, "warnings", 0) or 0
    if errors > 0:
        return RUN_OUTCOME_ERRORED
    if failed > 0:
        return RUN_OUTCOME_FAILED
    if warnings > 0:
        return RUN_OUTCOME_WARNINGS
    return RUN_OUTCOME_READY


def _run_data(
    run_result: Any,
    *,
    env: str,
    run_id: str,
    instance_id: str,
    tenant_id: str,
    tenant_name: str,
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
        "tenantClass": classify_tenant(tenant_id),  # derived: internal|customer|unknown
        "tenantName": tenant_name,   # OII (org display name; privacy-approved, best-effort)
        "agentId": agent_id,         # OII
        "agentCount": agent_count,
        "adkVersion": get_adk_version(),
        "toolkitGitSha": get_toolkit_git_sha(),
        "toolkitGitBranch": get_toolkit_git_branch(),
        "agentType": classify_agent_type(get_toolkit_git_branch()),
        "scope": scope,
        "invocationSource": invocation_source,
        "overall": getattr(run_result, "overall", ""),
        "runOutcome": derive_run_outcome(run_result),  # verdict donut split (errored|failed|warnings|ready)
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
    tenant_name: str = "",
) -> dict[str, Any]:
    # Identifiers + enums ONLY. Never `result` / `remediation` (EUII risk).
    return {
        "schemaVersion": TELEMETRY_SCHEMA_VERSION,
        "env": env,
        "runId": run_id,
        "instanceId": instance_id,
        "tenantId": tenant_id,
        "tenantClass": classify_tenant(tenant_id),
        "tenantName": tenant_name,
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
    tenant_name: str = "",
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
                tenant_name=tenant_name,
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
                    tenant_name=tenant_name,
                ),
            )
        )
    return events


def emit_flightcheck_telemetry(
    run_result: Any,
    *,
    tenant_id: str = "",
    tenant_name: str = "",
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
            tenant_name=tenant_name,
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
            "toolkitGitSha": get_toolkit_git_sha(),
            "toolkitGitBranch": get_toolkit_git_branch(),
            "agentType": classify_agent_type(get_toolkit_git_branch()),
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
