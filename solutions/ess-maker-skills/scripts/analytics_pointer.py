# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS ADK — Copilot Studio Analytics Pointer (September 2026 MVP).

This module implements the maker-facing /analytics pointer described in the
PM spec reviewed on ADO PR 5465946 ("ADK Copilot Studio Analytics Pointer").
The pointer has two surfaces:

* **/analytics slash command** — permanent action. Reads
  ``.local/config.json``, resolves the (maker, env, agent) triplet, and
  either prints a validated deep link to the agent's Copilot Studio
  analytics page or emits the FR7 repair/relink message when the
  association is missing.

* **Post-deploy report reminder** — one-time reminder printed by
  ``install_ess_agent.py`` after the ``INSTALLED_ESS_AGENT_JSON:`` line,
  exactly once per ``(maker_aad, env_id, agent_id)`` triplet. State lives
  in the ReminderStore (see below).

--------------------------------------------------------------------------
CRITICAL CAVEAT — READ BEFORE TOUCHING resolve_pointer_url()
--------------------------------------------------------------------------

The supported Copilot Studio direct-link deep-link contract is NOT yet
confirmed by the Copilot Studio partner team as of this session
(2026-08-07). The PM spec explicitly forbids shipping against a
reverse-engineered URL. Therefore this whole module ships behind a
feature flag env var:

    ADK_ANALYTICS_POINTER = "on" | "off"   (default: off)

When the flag is **off**, :func:`resolve_pointer_url` returns
``("", "feature_flag_off")`` and NO URL is constructed. When the flag is
**on**, the resolver uses the currently DOCUMENTED Copilot Studio path
shape

    https://copilotstudio.microsoft.com/environments/{envId}/bots/{agentId}/analytics

which mirrors the ``/overview`` shape already validated against a live
tenant in ``flightcheck/checks/local_files.py`` (see
``_studio_agent_url``) and is the pattern Microsoft Learn documents as
of this session. This is a **placeholder** pending partner contract
confirmation on ADO PR 5465946; the whole URL construction is contained
in :func:`resolve_pointer_url` so it can be swapped for the confirmed
pattern (or a Copilot Studio-side redirect endpoint) in one place.

Any real production rollout MUST be gated on the partner contract being
locked. See the ADO PR for status.

--------------------------------------------------------------------------
STORAGE — Dataverse follow-up
--------------------------------------------------------------------------

The PM spec calls for the reminder state to live in a Dataverse
``adk_makerreminder`` row so it is server-side and de-duplicates across
maker machines. That table is defined in the ESS Dataverse solution
package, which is NOT part of this repo — the solution is pre-built and
installed via ``install_ess_agent.py``. So for this MVP we ship a
**local-file** implementation and log the Dataverse implementation as a
follow-up. When the ESS Dataverse solution is next updated, add:

    Table: adk_makerreminder
      adk_makeraad        (String / lookup on systemuser, primary key part)
      adk_envid           (String, primary key part)
      adk_agentid         (String, primary key part)
      adk_reason          (Choice: post_deploy_install / manual_dismiss)
      adk_completedon     (DateTime)

and add a ``DataverseReminderStore`` implementation in this module that
targets that table via the same Dataverse client the other scripts use
(``auth.py``). The store factory :func:`get_reminder_store` already
reads ``ADK_ANALYTICS_STORE`` (``"local"`` default, ``"dataverse"``
future) so the swap is a one-line change from the caller's perspective.

--------------------------------------------------------------------------
Testability / CLI
--------------------------------------------------------------------------

The ``/analytics`` prompt drives this module through the CLI at the
bottom of the file (``--show``, ``--dismiss``, ``--status``) so the
SKILL.md doesn't need to shell out to Python for individual functions.
The Python API (``resolve_pointer_url``, ``read_association``,
``render_pointer_line``, ``get_reminder_store``) is what the
``install_ess_agent.py`` reminder path calls directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Protocol

# Mirror the sibling-import pattern the other scripts use so this works both
# when run as ``python scripts/analytics_pointer.py`` from the solution root
# and when imported as ``import analytics_pointer`` from a sibling script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# --- Feature flag + config -----------------------------------------------

FEATURE_FLAG_ENV = "ADK_ANALYTICS_POINTER"
STORE_ENV = "ADK_ANALYTICS_STORE"

# Documented Copilot Studio path shape as of 2026-08-07. See module docstring
# for the partner-contract caveat. Kept as a module constant so the swap point
# is exactly one line.
STUDIO_BASE = "https://copilotstudio.microsoft.com"
STUDIO_ANALYTICS_PATH = "/environments/{env_id}/bots/{agent_id}/analytics"

# Unresolved-reason enum shared between resolver, telemetry, and the
# maker-facing text. Any new reason MUST also be added to the telemetry
# ``unresolved_reason`` dimension in adk_telemetry.py.
REASON_FLAG_OFF = "feature_flag_off"
REASON_MISSING_ASSOCIATION = "missing_association"
REASON_VALIDATION_FAILED = "validation_failed"  # reserved for FR2 stub follow-up

# .local/config.json path resolution: normally in cwd (the maker's workspace)
# but tests can override via analytics_pointer.LOCAL_CONFIG_PATH_OVERRIDE.
_DEFAULT_LOCAL_CONFIG = os.path.join(".local", "config.json")


def _feature_flag_enabled() -> bool:
    """Return True iff the analytics pointer is ON for this process.

    The flag defaults OFF because the deep-link URL shape isn't confirmed by
    the Copilot Studio partner team yet (see module docstring). Any value in
    the ``on / 1 / true / yes / enabled`` set turns it on.
    """
    val = os.environ.get(FEATURE_FLAG_ENV, "").strip().lower()
    return val in ("on", "1", "true", "yes", "enabled")


# --- .local/config.json reading ------------------------------------------

def _load_local_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Best-effort read of the maker's .local/config.json.

    Returns ``{}`` on any error — this module must never crash a skill just
    because the config isn't set up yet (that's the FR7 case we WANT to
    render as ``missing_association``).
    """
    p = str(path) if path else _DEFAULT_LOCAL_CONFIG
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _extract_env_id(cfg: dict[str, Any]) -> str:
    """Extract the Power Platform (BAP) environment ID from local config.

    Setup.py writes ``dataverseEndpoint`` but not a raw ``environmentId`` yet;
    checks/prerequisites uses ``runner.env_id`` set by cli.py after a BAP
    round-trip. For the analytics pointer we accept either:
      * ``config["environmentId"]`` (future setup writes this),
      * ``config["agent"]["environmentId"]`` (mirrors drive_topic.py),
      * empty when neither is present (FR7 repair state).
    We deliberately do NOT round-trip BAP here — the /analytics command must
    stay a millisecond-level local read.
    """
    val = cfg.get("environmentId")
    if val:
        return str(val)
    agent = cfg.get("agent") or {}
    if isinstance(agent, dict):
        val = agent.get("environmentId")
        if val:
            return str(val)
    return ""


def _extract_agent_id(cfg: dict[str, Any]) -> str:
    """Extract the Copilot Studio bot / agent id from local config."""
    agent = cfg.get("agent") or {}
    if isinstance(agent, dict):
        val = agent.get("botId")
        if val:
            return str(val)
    return ""


def _extract_maker_aad(cfg: dict[str, Any]) -> str:
    """Extract the Maker AAD oid from local config, if setup captured one.

    Setup.py doesn't currently persist the Maker's AAD oid; when it starts,
    it will land under ``config["makerAad"]``. Until then this returns "" and
    the LocalFileReminderStore uses the ADK install ``instance_id`` as a
    per-machine stand-in (documented in LocalFileReminderStore). The
    DataverseReminderStore follow-up will require the real oid.
    """
    val = cfg.get("makerAad") or cfg.get("maker_aad")
    if val:
        return str(val)
    agent = cfg.get("agent") or {}
    if isinstance(agent, dict):
        val = agent.get("makerAad") or agent.get("maker_aad")
        if val:
            return str(val)
    return ""


def read_association(
    path: str | os.PathLike[str] | None = None,
) -> tuple[str, str, str] | None:
    """Return ``(maker_aad, env_id, agent_id)`` from ``.local/config.json``.

    Returns ``None`` when ANY of the three cannot be extracted. That
    ``None`` maps directly to the FR7 "association missing" repair path in
    the /analytics slash command and to the "skip the reminder" path in
    ``install_ess_agent.py``.

    Note: ``maker_aad`` is currently soft — see :func:`_extract_maker_aad`.
    Callers that want a fallback identity (e.g. LocalFileReminderStore keying
    on a per-machine ADK instance_id when maker_aad is empty) implement that
    themselves; this function stays strict so telemetry ``unresolved_reason``
    honestly reports ``missing_association`` when any of the three is absent.
    """
    cfg = _load_local_config(path)
    if not cfg:
        return None
    env_id = _extract_env_id(cfg)
    agent_id = _extract_agent_id(cfg)
    maker_aad = _extract_maker_aad(cfg)
    if not env_id or not agent_id or not maker_aad:
        return None
    return maker_aad, env_id, agent_id


# --- URL resolver --------------------------------------------------------

def resolve_pointer_url(env_id: str, agent_id: str) -> tuple[str, str]:
    """Resolve the Copilot Studio analytics deep link for one agent.

    Returns ``(url, unresolved_reason)``:

    * ``("", "feature_flag_off")`` when :envvar:`ADK_ANALYTICS_POINTER` is not
      enabled — this is the DEFAULT state until the partner contract is
      locked. No URL is constructed.
    * ``("", "missing_association")`` when either ``env_id`` or ``agent_id``
      is empty. The caller (/analytics or the install reminder) turns this
      into the FR7 repair message pointing at ``/setup``.
    * ``(url, "")`` when the flag is on AND both ids are present. The URL is
      constructed from :data:`STUDIO_BASE` + :data:`STUDIO_ANALYTICS_PATH`.

    **This function is a placeholder pending partner contract confirmation
    on ADO PR 5465946.** The URL shape here matches the currently documented
    Copilot Studio path (mirrors ``_studio_agent_url`` in
    ``flightcheck/checks/local_files.py`` which was validated live for
    ``/overview``). Do NOT rely on this for production without the partner
    contract being locked. Any change to the confirmed shape belongs HERE,
    in this one function — everything else in the module (telemetry,
    reminder store, CLI) uses only the ``(url, reason)`` return contract.

    FR2 (click-time validation of the destination) is not implemented in this
    stub. When it is added, it should return
    ``("", "validation_failed")`` — the enum value is reserved above.
    """
    if not _feature_flag_enabled():
        return "", REASON_FLAG_OFF
    if not env_id or not agent_id:
        return "", REASON_MISSING_ASSOCIATION
    url = STUDIO_BASE + STUDIO_ANALYTICS_PATH.format(env_id=env_id, agent_id=agent_id)
    return url, ""


# --- Maker-facing rendering ---------------------------------------------

_FLAG_OFF_LINE = (
    "Analytics pointer is not yet enabled in this build of the ADK. "
    "This surface is behind a feature flag while the Copilot Studio direct-"
    "link contract is being finalized. Track: ADO PR 5465946."
)

_MISSING_ASSOCIATION_LINE_PLAIN = (
    "No Copilot Studio agent is linked to this workspace yet. "
    "Run `/setup` to link one, then re-run `/analytics`."
)

_MISSING_ASSOCIATION_LINE_REMINDER = (
    "Once your Copilot Studio agent is linked, run `/analytics` at any time "
    "to jump to its analytics dashboard. Run `/setup` first to link one."
)


def render_pointer_line(
    url: str,
    reason: str,
    *,
    reminder_framing: bool = False,
) -> str:
    """Render the single maker-facing line for a pointer state.

    Used by BOTH surfaces:

    * ``/analytics`` slash command — ``reminder_framing=False``. Plain, in-
      the-moment framing ("here is your link" / "run /setup").
    * Post-deploy reminder from ``install_ess_agent.py`` — ``reminder_framing=
      True``. Softer, "one-time notice" framing so the maker doesn't read it
      as an error just because we're printing it after a successful install.

    The switch only affects wording, never the underlying state. When
    ``url`` is non-empty we show it verbatim (no shortening / no click
    tracking wrapper) so the maker can copy-paste into the browser.
    """
    if url:
        if reminder_framing:
            return (
                "Tip: your Copilot Studio agent analytics live at:\n"
                f"    {url}\n"
                "Run `/analytics` anytime to jump back here."
            )
        return (
            "Copilot Studio analytics for your agent:\n"
            f"    {url}"
        )
    if reason == REASON_FLAG_OFF:
        return _FLAG_OFF_LINE
    if reason == REASON_MISSING_ASSOCIATION:
        return (
            _MISSING_ASSOCIATION_LINE_REMINDER
            if reminder_framing
            else _MISSING_ASSOCIATION_LINE_PLAIN
        )
    if reason == REASON_VALIDATION_FAILED:
        return (
            "Could not validate the Copilot Studio analytics link right now. "
            "Try again in a moment, or open Copilot Studio directly."
        )
    # Defensive: unknown reason — don't invent copy, just say generic.
    return "Copilot Studio analytics link is not available right now."


# --- ReminderStore protocol + implementations ---------------------------

class ReminderStore(Protocol):
    """One-time-reminder gate for the post-deploy pointer.

    Implementations MUST be idempotent: ``mark_completed`` for an already-
    completed triplet is a no-op success, and ``is_completed`` never mutates.
    All calls MUST be fail-open: a store error must not crash the caller
    (install_ess_agent), it must be logged/ignored and treated as "not yet
    shown" so the maker still gets the reminder eventually.
    """

    def is_completed(self, maker_aad: str, env_id: str, agent_id: str) -> bool: ...

    def mark_completed(
        self, maker_aad: str, env_id: str, agent_id: str, reason: str
    ) -> None: ...


# --- LocalFileReminderStore ---------------------------------------------

# Per-machine JSON file. This is deliberately under the same ``~/.adk``
# directory adk_telemetry uses so all ADK per-install state lives in one
# place a maker can inspect / wipe if they hit a bug.
LOCAL_REMINDER_PATH = os.path.expanduser(
    os.path.join("~", ".adk", "analytics_reminder.json")
)


class LocalFileReminderStore:
    """Per-machine JSON-backed :class:`ReminderStore` implementation.

    MVP acceptable for the September 2026 release: the PM spec's "server-
    side / cross-device" requirement is documented as a follow-up in the
    module docstring (DataverseReminderStore).

    Concurrency: writes are best-effort. Two overlapping installer runs on
    the same machine could race and one might overwrite the other's mark —
    at worst the maker sees the reminder twice, which is a strictly better
    failure mode than crashing the installer. We do NOT take a filesystem
    lock: the installer already runs one at a time in practice, and cross-
    process locking on Windows without extra deps is more brittle than the
    bug it would prevent.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = str(path) if path else LOCAL_REMINDER_PATH

    @staticmethod
    def _key(maker_aad: str, env_id: str, agent_id: str) -> str:
        return f"{maker_aad}|{env_id}|{agent_id}"

    def _read(self) -> dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            # Fail-open: a store write that couldn't land just means the maker
            # sees the reminder again next install. Better than crashing.
            pass

    def is_completed(self, maker_aad: str, env_id: str, agent_id: str) -> bool:
        if not maker_aad or not env_id or not agent_id:
            return False
        data = self._read()
        entries = data.get("completed") or {}
        return isinstance(entries, dict) and self._key(maker_aad, env_id, agent_id) in entries

    def mark_completed(
        self, maker_aad: str, env_id: str, agent_id: str, reason: str
    ) -> None:
        if not maker_aad or not env_id or not agent_id:
            return
        data = self._read()
        entries = data.get("completed")
        if not isinstance(entries, dict):
            entries = {}
        entries[self._key(maker_aad, env_id, agent_id)] = {
            "reason": reason or "unspecified",
            "at": int(time.time()),
        }
        data["completed"] = entries
        self._write(data)


def get_reminder_store() -> ReminderStore:
    """Return the configured :class:`ReminderStore` implementation.

    Reads ``ADK_ANALYTICS_STORE`` env var (default ``"local"``). The
    ``"dataverse"`` value is reserved for the follow-up implementation
    documented in the module docstring. Any unknown value falls back to
    ``"local"`` — an env-var typo must not crash a skill.
    """
    kind = os.environ.get(STORE_ENV, "local").strip().lower()
    if kind == "dataverse":
        # TODO(adk-analytics-pointer): implement DataverseReminderStore once
        # the ESS Dataverse solution ships the adk_makerreminder table. See
        # the module docstring for the schema sketch. For now fall through.
        pass
    return LocalFileReminderStore()


# --- Telemetry helpers ---------------------------------------------------
# These are thin wrappers over adk_telemetry so the /analytics command and
# the install reminder call a stable local API instead of importing
# adk_telemetry directly (keeps future refactors — e.g. batching multiple
# analytics events into one — local to this module). All emits are best-
# effort and never propagate exceptions to the caller.


def _telemetry():
    """Import adk_telemetry lazily so a broken telemetry install doesn't
    break the /analytics command itself."""
    try:
        import adk_telemetry  # type: ignore
        return adk_telemetry
    except Exception:  # noqa: BLE001 — telemetry must never break a skill
        return None


def _emit(fn_name: str, **kwargs: Any) -> None:
    t = _telemetry()
    if t is None:
        return
    try:
        fn = getattr(t, fn_name, None)
        if fn is None:
            return
        fn(**kwargs)
    except Exception:  # noqa: BLE001
        pass


def record_pointer_shown(
    *, env_id: str, agent_id: str, outcome: str, unresolved_reason: str = ""
) -> None:
    """Emit ``adk.analytics.pointer.shown``.

    ``outcome`` is ``"resolved"`` when a URL was shown, ``"unresolved"``
    otherwise. ``unresolved_reason`` is one of the ``REASON_*`` enum values
    when outcome is ``unresolved`` (empty when resolved).
    """
    _emit(
        "emit_analytics_pointer_shown",
        env_id=env_id,
        agent_id=agent_id,
        outcome=outcome,
        unresolved_reason=unresolved_reason,
    )


def record_pointer_clicked(*, env_id: str, agent_id: str) -> None:
    _emit(
        "emit_analytics_pointer_clicked",
        env_id=env_id,
        agent_id=agent_id,
    )


def record_pointer_dismissed(*, env_id: str, agent_id: str) -> None:
    _emit(
        "emit_analytics_pointer_dismissed",
        env_id=env_id,
        agent_id=agent_id,
    )


def record_resolution_failed(
    *, env_id: str, agent_id: str, unresolved_reason: str
) -> None:
    _emit(
        "emit_analytics_pointer_resolution_failed",
        env_id=env_id,
        agent_id=agent_id,
        unresolved_reason=unresolved_reason,
    )


def record_repair_attempted(*, env_id: str, agent_id: str) -> None:
    _emit(
        "emit_analytics_pointer_repair_attempted",
        env_id=env_id,
        agent_id=agent_id,
    )


# --- CLI ----------------------------------------------------------------

def _cli_show(args: argparse.Namespace) -> int:
    """Resolve the pointer for the current workspace and print the maker
    line. Also emits the ``.shown`` telemetry event. This is what the
    /analytics prompt shells out to.
    """
    assoc = read_association(path=args.config)
    if assoc is None:
        line = render_pointer_line("", REASON_MISSING_ASSOCIATION, reminder_framing=False)
        print(line)
        record_pointer_shown(
            env_id="", agent_id="", outcome="unresolved",
            unresolved_reason=REASON_MISSING_ASSOCIATION,
        )
        return 0
    _maker, env_id, agent_id = assoc
    url, reason = resolve_pointer_url(env_id, agent_id)
    line = render_pointer_line(url, reason, reminder_framing=False)
    print(line)
    if url:
        record_pointer_shown(
            env_id=env_id, agent_id=agent_id, outcome="resolved",
        )
    else:
        record_pointer_shown(
            env_id=env_id, agent_id=agent_id, outcome="unresolved",
            unresolved_reason=reason,
        )
    return 0


def _cli_dismiss(args: argparse.Namespace) -> int:
    """Mark the pointer reminder as completed for the current triplet.

    Used by the /analytics command when the maker says "don't show this
    again" — a click-time dismissal path from the reminder surface. When
    the triplet is unresolvable we silently no-op (dismissing nothing is
    still a valid maker choice; we don't want to error at them).
    """
    assoc = read_association(path=args.config)
    if assoc is None:
        return 0
    maker, env_id, agent_id = assoc
    try:
        get_reminder_store().mark_completed(maker, env_id, agent_id, "manual_dismiss")
    except Exception:  # noqa: BLE001 — never crash the skill
        pass
    record_pointer_dismissed(env_id=env_id, agent_id=agent_id)
    return 0


def _cli_status(args: argparse.Namespace) -> int:
    """Print a small JSON blob describing pointer state for the current
    workspace. Consumed by the /analytics prompt when it wants to render
    a state-specific message without shelling out twice.
    """
    assoc = read_association(path=args.config)
    if assoc is None:
        payload = {
            "flag": "on" if _feature_flag_enabled() else "off",
            "association": None,
            "url": "",
            "reason": REASON_MISSING_ASSOCIATION,
            "completed": False,
        }
    else:
        maker, env_id, agent_id = assoc
        url, reason = resolve_pointer_url(env_id, agent_id)
        completed = False
        try:
            completed = get_reminder_store().is_completed(maker, env_id, agent_id)
        except Exception:  # noqa: BLE001
            pass
        payload = {
            "flag": "on" if _feature_flag_enabled() else "off",
            "association": {"env_id": env_id, "agent_id": agent_id},
            "url": url,
            "reason": reason,
            "completed": completed,
        }
    print(json.dumps(payload, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ESS ADK - Copilot Studio Analytics Pointer CLI.",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Path to .local/config.json (defaults to .local/config.json in cwd).",
    )
    # argparse can't accept a subcommand name that starts with '--', so we
    # model the three verbs as mutually-exclusive flags. That way both
    # `analytics_pointer.py --show` and (as a shorthand) no-verb-at-all work.
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--show",
        dest="verb",
        action="store_const",
        const="show",
        help="Show the analytics pointer line (default).",
    )
    group.add_argument(
        "--dismiss",
        dest="verb",
        action="store_const",
        const="dismiss",
        help="Mark the reminder complete.",
    )
    group.add_argument(
        "--status",
        dest="verb",
        action="store_const",
        const="status",
        help="Print pointer state as JSON.",
    )
    return p


_VERB_DISPATCH = {
    "show": _cli_show,
    "dismiss": _cli_dismiss,
    "status": _cli_status,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(argv)
    verb = getattr(args, "verb", None) or "show"
    return _VERB_DISPATCH[verb](args)


if __name__ == "__main__":
    raise SystemExit(main())
