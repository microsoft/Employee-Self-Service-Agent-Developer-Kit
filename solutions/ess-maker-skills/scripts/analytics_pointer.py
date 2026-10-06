# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS ADK — Copilot Studio Analytics Pointer (September 2026 MVP).

This module implements the maker-facing /analytics pointer described in the
PM spec reviewed on ADO PR 5465946 ("ADK Copilot Studio Analytics Pointer").
The pointer has two surfaces:

* **/analytics slash command** — permanent action. Reads
  ``.local/config.json``, resolves the DA environment and agent association,
  and either prints a validated deep link to the agent's Copilot Studio
  analytics page or emits the FR7 repair/relink message when the
  association is missing.
* **Post-deployment reminder** — one-time handoff after the first eligible
  DA deployment for the current environment and agent association. It is
  keyed by the same association as the permanent action and is silent after
  completion.

The current Maker Kit supports the DA workspace flow only. CEA installation
is no longer an entry point in this solution, so the pointer does not branch
on an experience type or construct a CEA-specific destination.

--------------------------------------------------------------------------
DA DEEP-LINK CONTRACT
--------------------------------------------------------------------------

The supported DA analytics URL is:

    https://copilotstudio.{ring}.microsoft.com/environments/{envId}/copilots/{agentId}/analytics

The ``ring`` segment is ``test``, ``preprod``, or empty for production. The
resolver derives it from the configured Power Platform API endpoint. The
``ADK_ANALYTICS_POINTER=off`` setting remains available as an explicit
emergency opt-out, but the pointer is enabled by default.

--------------------------------------------------------------------------
STORAGE — Dataverse follow-up
--------------------------------------------------------------------------

The PM spec calls for reminder state to live in a Dataverse
``adk_makerreminder`` row so it is server-side and de-duplicates across
maker machines. The current DA setup flow does not expose a server-side
reminder store, so this module retains a **local-file** implementation for
the optional reminder/dismissal state and logs the Dataverse implementation
as a follow-up. When the ESS Dataverse solution is next updated, add:

    Table: adk_makerreminder
      adk_makeraad        (String / lookup on systemuser, primary key part)
      adk_envid           (String, primary key part)
      adk_agentid         (String, primary key part)
      adk_reason          (Choice: post_deploy / manual_dismiss)
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
bottom of the file (``--record-invocation``, ``--show``,
``--post-deploy``, ``--dismiss``, ``--status``) so the SKILL.md doesn't need
to shell out to Python for individual functions. Verified evaluation
deployments write a short-lived local receipt; ``--post-deploy`` consumes a
matching receipt before it can mutate reminder state.
The Python API (``resolve_pointer_url``, ``read_association``,
``render_pointer_line``, ``get_reminder_store``) is also usable by future
post-setup reminder surfaces without duplicating the resolver logic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Protocol
from urllib.parse import quote, urlparse

# Mirror the sibling-import pattern the other scripts use so this works both
# when run as ``python scripts/analytics_pointer.py`` from the solution root
# and when imported as ``import analytics_pointer`` from a sibling script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# --- Feature flag + config -----------------------------------------------

FEATURE_FLAG_ENV = "ADK_ANALYTICS_POINTER"
STORE_ENV = "ADK_ANALYTICS_STORE"

# Confirmed DA Copilot Studio origins by service ring.
STUDIO_ORIGIN_BY_RING = {
    "prod": "https://copilotstudio.microsoft.com",
    "preprod": "https://copilotstudio.preprod.microsoft.com",
    "test": "https://copilotstudio.test.microsoft.com",
}
STUDIO_ANALYTICS_PATH = "/environments/{env_id}/copilots/{agent_id}/analytics"

# Unresolved-reason enum shared between resolver, telemetry, and the
# maker-facing text. Any new reason MUST also be added to the telemetry
# ``unresolved_reason`` dimension in adk_telemetry.py.
REASON_FLAG_OFF = "feature_flag_off"
REASON_MISSING_ASSOCIATION = "missing_association"
REASON_VALIDATION_FAILED = "validation_failed"  # reserved for FR2 stub follow-up

# .local/config.json path resolution: normally in cwd (the maker's workspace)
# but tests can override via analytics_pointer.LOCAL_CONFIG_PATH_OVERRIDE.
_DEFAULT_LOCAL_CONFIG = os.path.join(".local", "config.json")
_DEFAULT_DEPLOYMENT_RECEIPT = os.path.join(
    ".local", "analytics-deployment.json"
)


def _feature_flag_enabled() -> bool:
    """Return True iff the analytics pointer is ON for this process.

    The pointer defaults ON now that the DA deep-link contract is confirmed.
    Set the environment variable to an explicit off value to suppress link
    construction.
    """
    val = os.environ.get(FEATURE_FLAG_ENV, "").strip().lower()
    return val not in ("off", "0", "false", "no", "disabled")


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

    The current DA setup writes ``environmentId`` at the top level and on the
    active agent. We accept either location for compatibility with older
    workspaces. We deliberately do NOT round-trip BAP here — the /analytics
    command must stay a millisecond-level local read.
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


def _extract_studio_origin(cfg: dict[str, Any]) -> str:
    """Resolve the DA Copilot Studio origin for the configured service ring."""
    agent = cfg.get("agent") or {}
    if not isinstance(agent, dict):
        agent = {}

    explicit_ring = (
        cfg.get("serviceRing")
        or cfg.get("ring")
        or agent.get("serviceRing")
        or agent.get("ring")
        or ""
    )
    ring = str(explicit_ring).strip().lower()
    if ring in STUDIO_ORIGIN_BY_RING:
        return STUDIO_ORIGIN_BY_RING[ring]

    endpoint = str(
        cfg.get("powerPlatformApiEndpoint")
        or agent.get("powerPlatformApiEndpoint")
        or ""
    ).strip()
    hostname = (urlparse(endpoint).hostname or "").lower()
    if ".api.test.powerplatform.com" in hostname:
        return STUDIO_ORIGIN_BY_RING["test"]
    if ".api.preprod.powerplatform.com" in hostname:
        return STUDIO_ORIGIN_BY_RING["preprod"]
    return STUDIO_ORIGIN_BY_RING["prod"]


def _extract_maker_aad(cfg: dict[str, Any]) -> str:
    """Extract the Maker AAD oid from local config, if setup captured one.

    Setup.py doesn't currently persist the Maker's AAD oid. If a future
    setup flow adds it, this helper accepts either the top-level or active
    agent field. The local reminder store does not require it.
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


def _is_da_config(cfg: dict[str, Any]) -> bool:
    """Return whether the configured workspace is a native DA workspace."""
    agent = cfg.get("agent") or {}
    return (
        str(cfg.get("releaseLine") or "").strip().casefold() == "da"
        or (
            isinstance(agent, dict)
            and str(agent.get("releaseLine") or "").strip().casefold() == "da"
        )
    )


def read_association(
    path: str | os.PathLike[str] | None = None,
) -> tuple[str, str, str] | None:
    """Return ``(maker_aad, env_id, agent_id)`` from ``.local/config.json``.

    The DA setup flow persists the environment and bot IDs, but does not
    persist the maker's AAD object ID. The maker ID is therefore optional for
    local pointer resolution; the reminder store uses a machine-local
    fallback key when it is absent. ``None`` is returned only when the
    workspace has no active DA association.
    """
    cfg = _load_local_config(path)
    if not cfg:
        return None
    env_id = _extract_env_id(cfg)
    agent_id = _extract_agent_id(cfg)
    maker_aad = _extract_maker_aad(cfg)
    if not env_id or not agent_id:
        return None
    return maker_aad, env_id, agent_id


# --- URL resolver --------------------------------------------------------

def resolve_pointer_url(
    env_id: str,
    agent_id: str,
    *,
    studio_origin: str = STUDIO_ORIGIN_BY_RING["prod"],
) -> tuple[str, str]:
    """Resolve the Copilot Studio analytics deep link for one agent.

    Returns ``(url, unresolved_reason)``:

    * ``("", "feature_flag_off")`` when :envvar:`ADK_ANALYTICS_POINTER` is
      explicitly disabled. No URL is constructed.
    * ``("", "missing_association")`` when either ``env_id`` or ``agent_id``
      is empty. The caller (/analytics or the install reminder) turns this
      into the FR7 repair message pointing at ``/setup``.
    * ``(url, "")`` when the flag is on AND both ids are present. The URL is
      constructed from the ring-specific origin and
      :data:`STUDIO_ANALYTICS_PATH`.

    FR2 (click-time validation of the destination) is not implemented in this
    stub. When it is added, it should return
    ``("", "validation_failed")`` — the enum value is reserved above.
    """
    if not _feature_flag_enabled():
        return "", REASON_FLAG_OFF
    if not env_id or not agent_id:
        return "", REASON_MISSING_ASSOCIATION
    url = studio_origin.rstrip("/") + STUDIO_ANALYTICS_PATH.format(
        env_id=quote(str(env_id), safe=""),
        agent_id=quote(str(agent_id), safe=""),
    )
    return url, ""


# --- Maker-facing rendering ---------------------------------------------

_FLAG_OFF_LINE = (
    "Your Copilot Studio analytics link isn't available in this workspace "
    "right now. Please contact your administrator for help accessing "
    "analytics."
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
    * Optional reminder surface — ``reminder_framing=True``. Softer,
      "one-time notice" framing so the maker doesn't read it as an error.

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
    """One-time-reminder gate for an optional pointer reminder.

    Implementations MUST be idempotent: ``mark_completed`` for an already-
    completed triplet is a no-op success, and ``is_completed`` never mutates.
    All calls MUST be fail-open: a store error must not crash the caller; it
    must be logged/ignored and treated as "not yet
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
        # Current DA setup does not persist maker_aad. Keep reminder state
        # machine-local until a server-backed identity is available.
        owner = maker_aad or "local-machine"
        return f"{owner}|{env_id}|{agent_id}"

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
        if not env_id or not agent_id:
            return False
        data = self._read()
        entries = data.get("completed") or {}
        return isinstance(entries, dict) and self._key(maker_aad, env_id, agent_id) in entries

    def mark_completed(
        self, maker_aad: str, env_id: str, agent_id: str, reason: str
    ) -> None:
        if not env_id or not agent_id:
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


def write_verified_deployment_marker(
    config: dict[str, Any] | None = None,
    *,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    """Record a verified DA deployment for the post-deploy reminder.

    The deployment helper writes this receipt only after remote state and
    local synchronization have both been verified. The CLI consumes a
    matching receipt before showing the one-time reminder.
    """
    cfg = config if isinstance(config, dict) else _load_local_config()
    if not _is_da_config(cfg):
        return False
    assoc = read_association_from_config(cfg)
    if assoc is None:
        return False
    maker, env_id, agent_id = assoc
    receipt_path = str(path) if path else _DEFAULT_DEPLOYMENT_RECEIPT
    payload = {
        "maker_aad": maker,
        "environment_id": env_id,
        "agent_id": agent_id,
        "recorded_at": int(time.time()),
    }
    try:
        os.makedirs(os.path.dirname(receipt_path) or ".", exist_ok=True)
        temp_path = receipt_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(temp_path, receipt_path)
    except OSError:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return False
    return True


def read_association_from_config(
    cfg: dict[str, Any],
) -> tuple[str, str, str] | None:
    """Return the configured association without rereading the config file."""
    env_id = _extract_env_id(cfg)
    agent_id = _extract_agent_id(cfg)
    maker_aad = _extract_maker_aad(cfg)
    if not env_id or not agent_id:
        return None
    return maker_aad, env_id, agent_id


def _consume_verified_deployment_marker(
    association: tuple[str, str, str],
    *,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    receipt_path = str(path) if path else _DEFAULT_DEPLOYMENT_RECEIPT
    try:
        with open(receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
        if not isinstance(receipt, dict):
            return False
        expected = {
            "maker_aad": association[0],
            "environment_id": association[1],
            "agent_id": association[2],
        }
        if any(receipt.get(key) != value for key, value in expected.items()):
            return False
        os.remove(receipt_path)
        return True
    except (OSError, ValueError):
        return False


def _verified_deployment_marker_matches(
    association: tuple[str, str, str],
    *,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    receipt_path = str(path) if path else _DEFAULT_DEPLOYMENT_RECEIPT
    try:
        with open(receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
        if not isinstance(receipt, dict):
            return False
        expected = {
            "maker_aad": association[0],
            "environment_id": association[1],
            "agent_id": association[2],
        }
        return all(receipt.get(key) == value for key, value in expected.items())
    except (OSError, ValueError):
        return False


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


# --- CLI ----------------------------------------------------------------

def _cli_record_invocation(args: argparse.Namespace) -> int:
    """Record one capability-use event for an actual /analytics invocation."""
    try:
        import adk_telemetry  # type: ignore

        adk_telemetry.emit_capability_use("analytics", block=False)
    except Exception:  # noqa: BLE001 — telemetry must never break the skill
        pass
    return 0

def _cli_show(args: argparse.Namespace) -> int:
    """Resolve the pointer for the current workspace and print the maker
    line. This is what the /analytics prompt and deployment flow shell out
    to.
    """
    assoc = read_association(path=args.config)
    if assoc is None:
        line = render_pointer_line("", REASON_MISSING_ASSOCIATION, reminder_framing=False)
        print(line)
        return 0
    _maker, env_id, agent_id = assoc
    cfg = _load_local_config(args.config)
    url, reason = resolve_pointer_url(
        env_id,
        agent_id,
        studio_origin=_extract_studio_origin(cfg),
    )
    line = render_pointer_line(url, reason, reminder_framing=False)
    print(line)
    return 0


def _cli_post_deploy(args: argparse.Namespace) -> int:
    """Show and complete the one-time reminder after an eligible DA deploy."""
    cfg = _load_local_config(args.config)
    if not _is_da_config(cfg):
        return 0

    assoc = read_association(path=args.config)
    if assoc is None:
        return 0

    maker, env_id, agent_id = assoc
    receipt_path = _DEFAULT_DEPLOYMENT_RECEIPT
    if args.config:
        receipt_path = os.path.join(
            os.path.dirname(os.path.abspath(str(args.config))),
            os.path.basename(_DEFAULT_DEPLOYMENT_RECEIPT),
        )
    if not _verified_deployment_marker_matches(assoc, path=receipt_path):
        return 0
    try:
        store = get_reminder_store()
        if store.is_completed(maker, env_id, agent_id):
            _consume_verified_deployment_marker(assoc, path=receipt_path)
            return 0
    except Exception:  # noqa: BLE001 — reminder state must not break deploy
        store = None

    url, reason = resolve_pointer_url(
        env_id,
        agent_id,
        studio_origin=_extract_studio_origin(cfg),
    )
    if not url:
        # Do not consume the one-time reminder when the link cannot be
        # resolved; a later eligible deployment can try again.
        return 0

    if not _consume_verified_deployment_marker(assoc, path=receipt_path):
        return 0
    print(render_pointer_line(url, reason, reminder_framing=True))
    if store is not None:
        try:
            store.mark_completed(maker, env_id, agent_id, "post_deploy")
        except Exception:  # noqa: BLE001 — reminder state must not break deploy
            pass
    return 0


def _cli_dismiss(args: argparse.Namespace) -> int:
    """Mark the pointer reminder as completed for the current association.

    Used by the /analytics command when the maker says "don't show this
    again" — a click-time dismissal path from the reminder surface. When
    the association is unresolvable we silently no-op (dismissing nothing is
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
        cfg = _load_local_config(args.config)
        url, reason = resolve_pointer_url(
            env_id,
            agent_id,
            studio_origin=_extract_studio_origin(cfg),
        )
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
        "--record-invocation",
        dest="verb",
        action="store_const",
        const="record_invocation",
        help="Record one /analytics capability-use event.",
    )
    group.add_argument(
        "--show",
        dest="verb",
        action="store_const",
        const="show",
        help="Show the analytics pointer line (default).",
    )
    group.add_argument(
        "--post-deploy",
        dest="verb",
        action="store_const",
        const="post_deploy",
        help="Show the one-time DA post-deployment analytics reminder.",
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
    "record_invocation": _cli_record_invocation,
    "show": _cli_show,
    "post_deploy": _cli_post_deploy,
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
