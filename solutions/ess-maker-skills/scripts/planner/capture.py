# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: capturing what a Task produced (observe mode).

A Task declares the output *keys* it should yield in ``produces`` (grounded
from the Learn doc). When the assignee finishes, the ADK fills a value for each
key one of two ways, then confirms before pinning it onto the Plan's ledger:

  (a) **Observe** — read the value from the kit state the action actually
      changed. This module implements those deterministic detectors. The
      canonical case is ``/setup`` -> ``environmentId``, read from the
      ``.local/config.json`` that ``setup.py`` writes.
  (b) **Ask** — the skill asks the assignee to supply the value (used for
      manual/portal/external steps, or anything not observable). This module
      provides :func:`ask_artifact` to shape that answer into a ``PlanArtifact``.

Detectors never trust the agent's narration — they diff a before/after snapshot
of real local state. All values are confirmed with the assignee (in chat) before
:meth:`planner.plan_model.Plan.add_output` pins them.

Local file IO only; no network.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .plan_model import plan_artifact

CONFIG_PATH = os.path.join(".local", "config.json")

# Which Task actions have an observe-mode detector today. Anything not listed
# falls back to ask-mode (b). This is metadata the CLI/skill can surface.
OBSERVE_DETECTORS: dict[str, str] = {
    "onboarding": "environment",  # /setup -> Environment (config.json diff)
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
    """The subset of config.json the environment detector diffs on."""
    return {
        "setup": config.get("setup"),
        "dataverseEndpoint": config.get("dataverseEndpoint"),
        "environmentId": config.get("environmentId"),
    }


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

    Returns a ``PlanArtifact`` when ``/setup`` produced or bound an environment
    that wasn't reflected before (a new/changed ``dataverseEndpoint`` or
    ``environmentId``, or setup transitioning to ``"complete"``), else ``None``.

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
