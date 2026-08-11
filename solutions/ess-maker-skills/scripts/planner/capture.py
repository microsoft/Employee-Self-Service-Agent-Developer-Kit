# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: capturing what a Task produced (observe mode).

A Task declares the output *keys* it should yield in ``produces`` (grounded
from the Learn doc). When the assignee finishes, the ADK fills a value for each
key one of two ways, then confirms before pinning it onto the Plan's ledger:

  (a) **Observe** — read the value(s) from the kit state the action actually
      changed. This module implements those deterministic detectors. The
      canonical case is ``/setup``: the ADK diffs ``.local/config.json`` and pins
      **every** id + name (and any other artifact) a skill recorded there — the
      environment, the cloned agent, connections, apps, or an unknown shape — not
      just one hard-coded value (:func:`detect_config_artifacts`).
  (b) **Ask** — the skill asks the assignee to supply the value (used for
      manual/portal/external steps, or anything not observable). This module
      provides :func:`ask_artifact` to shape that answer into a ``PlanArtifact``.

Detectors never trust the agent's narration — they diff a before/after snapshot
of real local state. All values are confirmed with the assignee (in chat) before
:meth:`planner.plan_model.Plan.add_output` pins them.

Local file IO only; no network.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from .plan_model import plan_artifact

CONFIG_PATH = os.path.join(".local", "config.json")

# Config keys that are bookkeeping/status, never artifacts to pin.
_CONFIG_NOISE_KEYS = {"setup"}

# Which Task actions have an observe-mode detector today. Anything not listed
# falls back to ask-mode (b). This is metadata the CLI/skill can surface.
OBSERVE_DETECTORS: dict[str, str] = {
    "onboarding": "config-artifacts",  # /setup -> every id+name in config.json
}


def read_config(path: str | os.PathLike[str] = CONFIG_PATH) -> dict[str, Any]:
    """Load ``.local/config.json`` best-effort; ``{}`` if missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def config_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    """A deep copy of the **whole** ``config.json`` — the setup capture diffs the
    entire file so it can pin **every** id + name (and any other artifact a skill
    recorded), not just the environment/agent. Bookkeeping keys (e.g. ``setup``)
    are ignored by the detectors, not stripped here."""
    return copy.deepcopy(config) if isinstance(config, dict) else {}


def snapshot_config(path: str | os.PathLike[str] = CONFIG_PATH) -> dict[str, Any]:
    """Convenience: read config.json and return the detector snapshot."""
    return config_snapshot(read_config(path))


def detect_environment(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    task_id: str,
    key: str = "primaryEnvironment",
) -> dict[str, Any] | None:
    """Detect an Environment artifact from a ``config.json`` before/after diff.

    Returns a ``PlanArtifact`` when ``/setup`` bound/recorded an environment
    that wasn't reflected before (a new/changed ``dataverseEndpoint`` or
    ``environmentId``, or setup transitioning to ``"complete"``), else ``None``.
    ``/setup`` connects the kit to an already-deployed agent and records its
    environment details; it does not create the environment.

    ``environmentId`` is a GUID assigned when the environment is created and is
    stable thereafter; ``dataverseEndpoint`` is the org URL. ``setup.py`` writes
    ``dataverseEndpoint`` today, and ``environmentId`` when the kit resolves it
    (see the design's open question on persisting the raw GUID).
    """
    endpoint = after.get("dataverseEndpoint")
    env_id = after.get("environmentId")
    if not endpoint and not env_id:
        return None

    became_complete = before.get("setup") != "complete" and after.get("setup") == "complete"
    endpoint_changed = endpoint and endpoint != before.get("dataverseEndpoint")
    env_changed = env_id and env_id != before.get("environmentId")
    if not (became_complete or endpoint_changed or env_changed):
        return None

    attributes: dict[str, Any] = {}
    if env_id:
        attributes["environmentId"] = env_id
    if endpoint:
        attributes["environmentUrl"] = endpoint
    if not attributes:
        return None

    inventory_ref = f"Environment:{env_id}" if env_id else ""
    return plan_artifact(
        key,
        "Environment",
        attributes,
        produced_by_task_id=task_id,
        inventory_ref=inventory_ref,
        source="Agent",
    )


def detect_agent(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    task_id: str,
    key: str = "essAgent",
) -> dict[str, Any] | None:
    """Detect the ESS **Agent** artifact from a ``config.json`` before/after diff.

    ``/setup`` connects to the deployed ESS agent and **clones it** — recording
    the agent identity (``botId``, ``schemaName``, ``name``, local ``folder`` /
    ``slug``) into ``.local/config.json`` and its components under
    ``workspace/agents/<slug>/``. Returns an ``Agent`` ``PlanArtifact`` when that
    identity appears or changes, else ``None`` (nothing to pin). This is the
    second half of the ``/setup`` capture — the environment is :func:`detect_environment`.
    """
    agent = after.get("agent") or {}
    bot_id = agent.get("botId")
    if not bot_id and not agent.get("schemaName"):
        return None
    if agent == (before.get("agent") or {}):
        return None  # unchanged

    attributes: dict[str, Any] = {
        k: agent[k] for k in ("botId", "schemaName", "name", "folder", "slug")
        if agent.get(k)
    }
    if not attributes:
        return None
    inventory_ref = f"Agent:{bot_id}" if bot_id else ""
    return plan_artifact(
        key,
        "Agent",
        attributes,
        produced_by_task_id=task_id,
        inventory_ref=inventory_ref,
        source="Agent",
    )


# --- Generic config-artifact capture -------------------------------------------------
# "Capture all ids + names in config, plus any other artifact a skill produced."
# The environment (a top-level scalar pair) and the cloned agent are recognised for
# nicer kinds/keys; any OTHER id-bearing object (or list of objects) is captured too.

def _artifact_attrs(obj: dict[str, Any]) -> dict[str, Any]:
    """The id / name / locator scalars that identify an artifact — captured
    generically (ids, names, slugs, schema names, urls/endpoints, folders, refs).
    Booleans and nested containers are skipped; only identifying scalars are kept."""
    attrs: dict[str, Any] = {}
    for k, v in obj.items():
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            continue
        kl = k.lower()
        if (
            kl == "id" or kl.endswith("id")
            or "name" in kl
            or kl in ("slug", "folder")
            or kl.endswith("url") or kl.endswith("endpoint")
            or kl.endswith("ref") or "reference" in kl
        ):
            attrs[k] = v
    return attrs


def _has_id(attrs: dict[str, Any]) -> bool:
    return any(k.lower() == "id" or k.lower().endswith("id") for k in attrs)


def _first_id(attrs: dict[str, Any]) -> Any:
    for k, v in attrs.items():
        if k.lower() == "id" or k.lower().endswith("id"):
            return v
    return ""


def _infer_kind(key: str, obj: dict[str, Any]) -> str:
    """Best-effort kind for a captured config object; falls back to ``Custom``."""
    k = key.lower()
    if "connection" in k or obj.get("connectionId") or obj.get("connectionReferenceId"):
        return "Connection"
    if "entra" in k or "app" in k or obj.get("appId") or obj.get("objectId"):
        return "EntraApp"
    if "agent" in k or obj.get("botId"):
        return "Agent"
    if "environment" in k or obj.get("environmentId"):
        return "Environment"
    if "knowledge" in k or "source" in k:
        return "KnowledgeSource"
    return "Custom"


def _sweep_value(
    key: str,
    value: Any,
    before_value: Any,
    *,
    task_id: str,
) -> list[dict[str, Any]]:
    """Emit a ``PlanArtifact`` for each changed id-bearing object under a config
    key — handling either a single object or a list of objects."""
    candidates: list[tuple[str, dict[str, Any], Any]] = []
    if isinstance(value, dict):
        candidates.append((key, value, before_value if isinstance(before_value, dict) else {}))
    elif isinstance(value, list):
        before_list = before_value if isinstance(before_value, list) else []
        for i, element in enumerate(value):
            if isinstance(element, dict):
                sub = _first_id(_artifact_attrs(element)) or element.get("name") or str(i)
                before_el = before_list[i] if i < len(before_list) else {}
                candidates.append((f"{key}.{sub}", element, before_el))

    out: list[dict[str, Any]] = []
    for art_key, obj, before_obj in candidates:
        if obj == before_obj:
            continue  # unchanged
        attrs = _artifact_attrs(obj)
        if not _has_id(attrs):
            continue
        kind = _infer_kind(art_key, obj)
        id_val = _first_id(attrs)
        out.append(plan_artifact(
            art_key,
            kind,
            attrs,
            produced_by_task_id=task_id,
            inventory_ref=f"{kind}:{id_val}" if id_val else "",
            source="Agent",
        ))
    return out


def detect_config_artifacts(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    task_id: str,
    env_key: str = "primaryEnvironment",
    agent_key: str = "essAgent",
) -> list[dict[str, Any]]:
    """Generic ``/setup`` (and any config-writing skill) capture — pin **every**
    id + name (and any other artifact) a skill recorded in ``config.json`` that
    changed since ``before``.

    Not env/agent-only: the environment (a top-level scalar pair) and the cloned
    agent get recognised kinds/keys, and **any other** top-level object — or list
    of objects — carrying an id is captured too (a Connection, an Entra app, a
    knowledge source, or an unknown ``Custom`` shape). Artifacts a skill writes
    *outside* ``config.json`` are covered by the per-kind detector registry
    (design §12.3); this is the config-file half of that contract.
    """
    before = before or {}
    after = after or {}
    artifacts: list[dict[str, Any]] = []
    handled = set(_CONFIG_NOISE_KEYS)

    env = detect_environment(before, after, task_id=task_id, key=env_key)
    if env is not None:
        artifacts.append(env)
    handled.update({"environmentId", "dataverseEndpoint"})

    agent = detect_agent(before, after, task_id=task_id, key=agent_key)
    if agent is not None:
        artifacts.append(agent)
    handled.add("agent")

    for key, value in after.items():
        if key in handled:
            continue
        artifacts.extend(_sweep_value(key, value, before.get(key), task_id=task_id))
    return artifacts


def ask_artifact(
    key: str,
    kind: str,
    attributes: dict[str, Any],
    *,
    task_id: str,
    inventory_ref: str | None = None,
) -> dict[str, Any]:
    """Shape an assignee-supplied answer (capture mode b) into a ``PlanArtifact``.

    Used when a Task's output is not observable from kit state (a manual/portal/
    external step) — the skill asks the assignee for the value(s) and passes them
    here. Provenance is stamped ``source="User"`` because the person supplied it.
    """
    return plan_artifact(
        key,
        kind,
        attributes,
        produced_by_task_id=task_id,
        inventory_ref=inventory_ref,
        source="User",
    )
