# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Local, per-agent evaluation session: ADK-started runs and workflow context.

The file lives in this workspace's ``.local`` folder and is keyed by agent, so
each agent in each workspace has its own run history and selected-set context.
It records only confirmed facts (a run is stored once Copilot Studio returns its
run ID). It is never pruned automatically; context is cleared when the selected
set is deleted or the maker starts over.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SESSION_PATH_ENV = "ESS_EVALUATION_SESSION_PATH"
DEFAULT_SESSION_PATH = Path(".local") / "evaluation-session.json"
WORKSPACE_KEY = "workspace"
STAGES = ("created", "ready_for_review", "running", "complete", "failed")
_RUN_FIELDS = (
    "runId", "runName", "testSetId", "testSetName", "environmentId", "botId",
    "agentStudioUrl",
)


class EvaluationSessionError(ValueError):
    """The evaluation session could not be read or updated."""


def session_path() -> Path:
    return Path(os.environ.get(SESSION_PATH_ENV) or DEFAULT_SESSION_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def agent_key(config: dict[str, Any] | None) -> str:
    """Identify the agent; sets authored before setup use the workspace key."""
    if not isinstance(config, dict):
        return WORKSPACE_KEY
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    for value in (
        config.get("activeAgent"), agent.get("slug"), agent.get("botId"),
        Path(str(agent.get("folder") or "")).name,
    ):
        if value:
            return str(value)
    return WORKSPACE_KEY


def _read() -> dict[str, Any]:
    path = session_path()
    if not path.is_file():
        return {"schemaVersion": 1, "agents": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationSessionError(
            f"The local evaluation session at {path} could not be read: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
        raise EvaluationSessionError(f"The local evaluation session at {path} is invalid.")
    return data


def _write(data: dict[str, Any]) -> None:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _agent(data: dict[str, Any], key: str) -> dict[str, Any]:
    entry = data["agents"].setdefault(key, {})
    entry.setdefault("runs", [])
    entry.setdefault("context", None)
    entry.setdefault("sets", {})
    return entry


def record_run(
    key: str,
    result: dict[str, Any],
    *,
    source_folder: str | Path | None = None,
) -> dict[str, Any] | None:
    """Store a run started from ADK. Without a returned run ID, store nothing."""
    run_id = result.get("runId") if isinstance(result, dict) else None
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    data = _read()
    entry = _agent(data, key)
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    run = {field: result.get(field) for field in _RUN_FIELDS if result.get(field)}
    run.update({
        "sourceFolder": str(Path(source_folder).resolve()) if source_folder else None,
        "startedAt": result.get("startedAt") or _now(),
        "lastObserved": {
            "state": result.get("state") or response.get("state") or "Started",
            "observedAt": _now(),
        },
    })
    entry["runs"] = [item for item in entry["runs"] if item.get("runId") != run_id]
    entry["runs"].append(run)
    context = entry.get("context")
    if isinstance(context, dict):
        context.update({"lastRunId": run_id, "stage": "running", "updatedAt": _now()})
    _write(data)
    return run


def observe_run(key: str, run_id: str, result: dict[str, Any]) -> bool:
    """Cache the latest returned state of an ADK-started run."""
    data = _read()
    entry = _agent(data, key)
    run = next((item for item in entry["runs"] if item.get("runId") == run_id), None)
    if run is None or not isinstance(result, dict):
        return False
    state = result.get("state")
    if state:
        run["lastObserved"] = {"state": state, "observedAt": _now()}
    if result.get("testSetName") and not run.get("testSetName"):
        run["testSetName"] = result["testSetName"]
    context = entry.get("context")
    if (
        isinstance(context, dict) and context.get("lastRunId") == run_id
        and str(state or "").casefold() == "completed"
    ):
        context.update({"stage": "complete", "updatedAt": _now()})
    _write(data)
    return True


def adk_runs(key: str) -> list[dict[str, Any]]:
    return list(_agent(_read(), key)["runs"])


def get_context(key: str) -> dict[str, Any] | None:
    return _agent(_read(), key)["context"]


def set_details(key: str) -> dict[str, dict[str, Any]]:
    """Per-set details such as the scenario, keyed by resolved set folder."""
    return dict(_agent(_read(), key)["sets"])


def set_context(key: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge workflow context such as the selected set, stage, and pending action.

    A ``scenario`` update is also kept per set so overviews can show it after
    the maker moves on to another set.
    """
    stage = updates.get("stage")
    if stage is not None and stage not in STAGES:
        raise EvaluationSessionError(
            f"Unknown stage {stage!r}. Use one of: {', '.join(STAGES)}."
        )
    data = _read()
    entry = _agent(data, key)
    context = dict(entry.get("context") or {})
    previous_folder = context.get("setFolder")
    context.update(updates)
    if context.get("setFolder"):
        context["setFolder"] = str(Path(context["setFolder"]).resolve())
    if context.get("setFolder") != previous_folder and not updates.get("scenario"):
        context["scenario"] = entry["sets"].get(context.get("setFolder"), {}).get("scenario")
    scenario = updates.get("scenario")
    if scenario:
        if not context.get("setFolder"):
            raise EvaluationSessionError("A scenario needs --set-folder to identify its test set.")
        entry["sets"].setdefault(context["setFolder"], {})["scenario"] = scenario
    context["updatedAt"] = _now()
    entry["context"] = context
    _write(data)
    return context


def clear_context(key: str, *, set_folder: str | Path | None = None) -> bool:
    """Clear context; with ``set_folder``, only when that set is the selected one.

    With ``set_folder`` (used when a set is deleted), that set's saved details
    are removed as well.
    """
    data = _read()
    entry = _agent(data, key)
    removed_details = False
    if set_folder is not None:
        removed_details = entry["sets"].pop(str(Path(set_folder).resolve()), None) is not None
    context = entry.get("context")
    cleared = bool(context) and (
        set_folder is None or context.get("setFolder") == str(Path(set_folder).resolve())
    )
    if cleared:
        entry["context"] = None
    if cleared or removed_details:
        _write(data)
    return cleared


def _configured_key() -> str:
    path = Path(".local") / "config.json"
    try:
        return agent_key(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return WORKSPACE_KEY


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", help="Agent key; defaults to the active agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show")
    context_set = subparsers.add_parser("set-context")
    context_set.add_argument("--set-folder")
    context_set.add_argument("--set-name")
    context_set.add_argument("--scenario")
    context_set.add_argument("--stage", choices=STAGES)
    context_set.add_argument("--pending-action")
    context_set.add_argument("--clear-pending-action", action="store_true")
    context_clear = subparsers.add_parser("clear-context")
    context_clear.add_argument("--set-folder")
    args = parser.parse_args()
    key = args.agent or _configured_key()
    try:
        if args.command == "show":
            result: Any = {
                "agent": key, "context": get_context(key), "runs": adk_runs(key),
                "sets": set_details(key),
            }
        elif args.command == "set-context":
            updates = {
                name: value for name, value in (
                    ("setFolder", args.set_folder), ("setName", args.set_name),
                    ("scenario", args.scenario),
                    ("stage", args.stage), ("pendingAction", args.pending_action),
                ) if value is not None
            }
            if args.clear_pending_action:
                updates["pendingAction"] = None
            result = {"agent": key, "context": set_context(key, updates)}
        else:
            result = {
                "agent": key,
                "cleared": clear_context(key, set_folder=args.set_folder),
            }
    except (EvaluationSessionError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
