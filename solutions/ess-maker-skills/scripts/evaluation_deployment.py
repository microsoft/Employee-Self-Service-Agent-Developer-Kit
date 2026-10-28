# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Prepare and deploy one explicitly selected evaluation set, never start a run."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, redirect_stdout
from glob import escape as escape_glob
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

import requests
import yaml

from workspace_state import _atomic_write_text, _ensure_utf8_stdout, compute_diff
import analytics_pointer
from auth import load_config
from alm_enrollment import _exception_chain, _redact_evidence
from evaluation_method_policy import EvaluationMethodError, validate_evaluation_folder
from evaluation_promotion import (
    EvaluationPromotionError,
    cleanup_workspace_set,
    promote_workspace_set,
)
from evaluation_review import (
    REVIEW_FILENAME,
    REVIEW_REQUESTED,
    ReviewMetadataError,
    parse_review_metadata,
    set_review_metadata,
)
from http_errors import APIError
from minimalbot_evaluation import (
    ComponentEditError,
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
    NATIVE_REVIEW_LOCAL_ONLY_WARNING,
    is_minimalbot,
)


class EvaluationDeploymentError(ValueError):
    """A selected deployment cannot safely proceed."""


ACTIONS = ("run", "request-review", "push")
SUCCESS_STATUSES = {"pushed", "up_to_date"}


@contextmanager
def _deployment_lock(agent: Path):
    path = agent / ".evaluation-deployment.lock"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise EvaluationDeploymentError(
            "Another deployment owns the agent lock. If its process stopped, "
            "reconcile pending deployment state before removing the stale lock."
        ) from exc
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


def _append_cleanup_warning(result: dict[str, Any], warning: str) -> None:
    result["cleanupWarning"] = (
        f"{result.get('cleanupWarning', '')} {warning}".strip()
    )


def _close_deployment_stack(
    stack: ExitStack, result: dict[str, Any],
) -> dict[str, Any]:
    try:
        stack.close()
    except OSError as exc:
        _append_cleanup_warning(
            result, f"Primary deployment result preserved; lock cleanup failed: {exc}",
        )
    return result


def _json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluationDeploymentError(f"Expected a JSON object: {path}")
    return value


def _configuration(config, set_folder, action, solution_root):
    if config is not None:
        return config
    try:
        return load_config()
    except SystemExit as exc:
        root = Path(solution_root or Path.cwd()).resolve()
        source = (root / set_folder).resolve()
        if action == "request-review" and source.parent == (
            root / "workspace" / "evaluations"
        ).resolve():
            validate_evaluation_folder(source)
            set_review_metadata(source, REVIEW_REQUESTED)
        raise EvaluationDeploymentError(
            f"Configuration is unavailable ({exc.code}). Run /setup; "
            "local files and workspace review intent are preserved."
        ) from exc


def _files(folder: Path) -> dict[str, str]:
    if any(
        path.parent != folder and (path.name.endswith(".mcs.yml") or path.name == REVIEW_FILENAME)
        for path in folder.rglob("*") if path.is_file()
    ):
        raise EvaluationDeploymentError(
            "Nested evaluation documents are not supported in a selected set."
        )
    paths = sorted(folder.glob("*.mcs.yml"))
    if (folder / REVIEW_FILENAME).is_file():
        paths.append(folder / REVIEW_FILENAME)
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def _status(files: dict[str, str]) -> str | None:
    content = files.get(REVIEW_FILENAME)
    return parse_review_metadata(content)["status"] if content is not None else None


def _parent(files: dict[str, str]) -> str:
    parents = [
        name for name, content in files.items()
        if name.endswith(".mcs.yml")
        and isinstance(document := yaml.safe_load(content), dict)
        and document.get("kind", document.get("$kind")) == "EvaluationSet"
    ]
    if len(parents) != 1:
        raise EvaluationDeploymentError("The selected folder must have exactly one parent.")
    return parents[0]


def _target(config: dict[str, Any], agent: Path) -> dict[str, Any]:
    active = config["agent"]
    return {
        "agentFolder": str(agent),
        "botId": str(active.get("botId") or ""),
        "environmentId": str(
            active.get("environmentId") or config.get("environmentId") or ""
        ),
        "dataverseEndpoint": str(config.get("dataverseEndpoint") or "").rstrip("/"),
        "powerPlatformApiEndpoint": str(config.get("powerPlatformApiEndpoint") or ""),
    }

def _prepare(
    set_folder: str | Path, *, action: str, config: dict[str, Any],
    replace: bool, solution_root: str | Path | None,
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise EvaluationDeploymentError(f"Unsupported deployment action: {action}")
    root = Path(solution_root or Path.cwd()).resolve()
    source = Path(set_folder)
    source = (root / source).resolve() if not source.is_absolute() else source.resolve()
    validate_evaluation_folder(source)
    workspace = (root / "workspace" / "evaluations").resolve()
    active = config.get("agent")
    if not isinstance(active, dict) or not active.get("folder"):
        if action == "request-review" and source.parent == workspace:
            set_review_metadata(source, REVIEW_REQUESTED)
        raise EvaluationDeploymentError("Run /setup to configure a deployment target.")
    agent = Path(active["folder"])
    agent = (root / agent).resolve() if not agent.is_absolute() else agent.resolve()
    agent_evaluations = (agent / "evaluations").resolve()
    if source.parent not in (workspace, agent_evaluations):
        raise EvaluationDeploymentError(
            "Select an exact workspace or active-agent evaluation folder."
        )
    if action == "request-review":
        set_review_metadata(source, REVIEW_REQUESTED)
    if not agent.is_dir() or not active.get("botId"):
        raise EvaluationDeploymentError(
            "Setup is incomplete. Local evaluation files and review intent are preserved."
        )
    target = _target(config, agent)
    config = {**config, "agent": {**active, "folder": str(agent)}}
    if not is_minimalbot(config):
        raise EvaluationDeploymentError(
            "Dataverse evaluation deployment is retired. "
            "Use a supported AgentBuilder evaluation workspace."
        )
    destination = (agent_evaluations / source.name).resolve()
    if destination.parent != agent_evaluations:
        raise EvaluationDeploymentError("The target set resolves outside the active agent.")
    source_files = _files(source)
    destination_files = _files(destination)
    baseline = _files(agent / ".baseline" / "evaluations" / source.name)
    if source != destination and (destination_files or baseline):
        if source_files != destination_files and not replace:
            raise EvaluationDeploymentError(
                "The target already has this set. Preview with --replace only "
                "after selecting replacement; exact changes still require consent."
            )
    component_map = _json_file(agent / ".component-map.json")
    prefix = f"evaluations/{source.name}/"
    selected_map = {
        path: entry for path, entry in component_map.items() if path.startswith(prefix)
    }
    if any(not isinstance(entry, dict) for entry in selected_map.values()):
        raise EvaluationDeploymentError("Invalid selected-set component tracking.")
    context = {
        "source": source, "agent": agent, "destination": destination,
        "workspace": workspace, "files": source_files, "baseline": baseline,
        "prefix": prefix, "target": target, "config": config, "action": action,
        "originalMap": component_map, "backend": "minimalbot",
    }
    recovery = False
    native_pending = _json_file(agent / ".evaluation-pending.json")
    client = MinimalBotEvaluationClient.from_config(config)
    preview_path = agent / ".evaluation-preview.json"
    prior_preview = _json_file(preview_path)
    plan = client.push_agent_evaluations(
        agent, dry_run=True, source_folder=source,
        plan=prior_preview.get("plan") if prior_preview.get("files") == source_files
        and prior_preview.get("target") == target
        and prior_preview.get("prefix") == prefix
        and prior_preview.get("baseline") == baseline
        and prior_preview.get("map") == selected_map else None,
    )
    client.authenticate()
    remote = client.read_components()
    context["nativeClient"] = client
    context["nativePlan"] = plan
    context["nativeRemote"] = remote
    remote_snapshot = remote
    if selected_map and not native_pending and not plan["changes"]:
        client.verify_deployed_components({"entries": selected_map}, remote)
    if native_pending:
        context["nativePending"] = native_pending
        client.verify_deployed_components(plan, remote)
        recovery = True
    local_status = _status(source_files)
    if action == "run":
        blocked = local_status == REVIEW_REQUESTED
        if blocked:
            raise EvaluationDeploymentError(
                "This test set is tagged for review and cannot run until "
                "the review is explicitly completed and pushed."
            )
    changed, new, deleted = compute_diff(baseline, source_files)
    local_changed, local_new, local_deleted = compute_diff(
        destination_files, source_files,
    )
    token_input = {
        "target": target, "source": str(source), "action": action, "replace": replace,
        "files": source_files, "destination": destination_files, "baseline": baseline,
        "map": selected_map, "remote": remote_snapshot,
        "nativePending": context.get("nativePending"),
        "nativePlan": context.get("nativePlan"),
    }
    token = hashlib.sha256(
        json.dumps(token_input, sort_keys=True).encode("utf-8")
    ).hexdigest()
    context.update({
        "confirmationToken": token,
        "requiresPush": bool(plan["changes"]) and not recovery,
        "changes": {"modified": changed, "new": new, "deleted": deleted},
        "recovering": recovery,
        "promotion": {
            "required": source != destination,
            "replacesLocalFiles": source != destination and bool(destination_files)
            and destination_files != source_files,
            "changes": {
                "modified": local_changed, "new": local_new, "deleted": local_deleted,
            },
        },
    })
    _atomic_write_text(str(preview_path), json.dumps({
        "target": target, "files": source_files, "plan": plan, "prefix": prefix,
        "baseline": baseline, "map": selected_map,
    }, indent=2))
    return context


def _public(context: dict[str, Any], status: str) -> dict[str, Any]:
    target = context["target"]
    result = {
        "status": status, "backend": context["backend"], "action": context["action"],
        "environmentId": target["environmentId"], "botId": target["botId"],
        "sourceFolder": str(context["source"]),
        "agentSetFolder": str(context["destination"]),
        "confirmationToken": context["confirmationToken"],
        "requiresPush": context["requiresPush"], "changes": context["changes"],
        "promotion": context["promotion"],
    }
    if context["backend"] == "minimalbot":
        result["deploymentBehavior"] = (
            "new_copy" if context["nativePlan"]["changes"] else "reuse"
        )
        result["reviewMetadataPersisted"] = False
        if REVIEW_FILENAME in context["files"]:
            result["reviewWarning"] = NATIVE_REVIEW_LOCAL_ONLY_WARNING
    return result


_INPUT_ERRORS = (
    EvaluationDeploymentError, EvaluationMethodError, EvaluationPromotionError,
    ReviewMetadataError, MinimalBotEvaluationError, OSError, json.JSONDecodeError,
    requests.RequestException, yaml.YAMLError, APIError,
)


def preview_deployment(
    set_folder: str | Path, *, action: str = "push",
    config: dict[str, Any] | None = None, replace: bool = False,
    solution_root: str | Path | None = None,
) -> dict[str, Any]:
    """Save local review intent if requested and preview; never write remotely/run."""
    try:
        context = _prepare(
            set_folder, action=action,
            config=_configuration(config, set_folder, action, solution_root),
            replace=replace, solution_root=solution_root,
        )
        return _public(context, "ready")
    except _INPUT_ERRORS as exc:
        return {"status": "blocked", "error": str(exc)}
    except SystemExit as exc:
        return {"status": "blocked", "error": f"Configuration/authentication stopped ({exc.code}). See diagnostics."}


def deploy_evaluation_set(
    set_folder: str | Path, *, action: str = "push", confirmation_token: str | None = None,
    yes: bool = False, force_delete: bool = False, replace: bool = False,
    config: dict[str, Any] | None = None, solution_root: str | Path | None = None,
) -> dict[str, Any]:
    """Deploy only a confirmed set; return a verified ID without starting a run."""
    if not yes:
        return {"status": "cancelled", "error": "Deployment was not confirmed."}
    stack = ExitStack()
    stage = "preparation"
    remote_result = None
    try:
        config = _configuration(config, set_folder, action, solution_root)
        context = _prepare(
            set_folder, action=action, config=config, replace=replace,
            solution_root=solution_root,
        )
        stack.enter_context(_deployment_lock(context["agent"]))
        if not confirmation_token or confirmation_token != context["confirmationToken"]:
            raise EvaluationDeploymentError(
                "The target, source, or deployed state changed after preview. Preview and confirm again."
            )
        if force_delete:
            raise EvaluationDeploymentError(
                "Existing native Push does not support --force-delete. A new "
                "copy can omit cases, but the old remote copy is retained."
            )
        source, destination, agent = (
            context["source"], context["destination"], context["agent"]
        )
        config = context["config"]
        if source != destination and _files(destination) != context["files"]:
            promote_workspace_set(context["workspace"], agent, source.name, replace)
        elif source != destination and not destination.is_dir():
            promote_workspace_set(context["workspace"], agent, source.name, replace)
        validate_evaluation_folder(destination)
        if _files(destination) != context["files"] or _files(source) != context["files"]:
            raise EvaluationDeploymentError("Selected source changed after confirmation.")
        scope = f"evaluations/{escape_glob(source.name)}/*"
        stage = "deployment"
        client = context["nativeClient"]
        plan = context["nativePlan"]
        outcome = client.push_agent_evaluations(agent, only_globs=[scope], plan=plan)
        remote_result = outcome
        set_id = outcome["sets"][0]["testSetId"]
        if _files(destination) != context["files"] or _files(source) != context["files"]:
            raise EvaluationDeploymentError(
                "Source changed during deployment; local synchronization is incomplete."
            )
        result = {
            **_public(context, outcome["status"]),
            "sets": [{
                "sourceFolder": str(source), "agentSetFolder": str(destination),
                "testSetId": set_id,
                "deployedReviewStatus": None,
            }],
        }
        try:
            (agent / ".evaluation-preview.json").unlink(missing_ok=True)
        except OSError as exc:
            _append_cleanup_warning(
                result, f"Verified deployment; preview record retained: {exc}",
            )
        if source != destination:
            try:
                cleanup_workspace_set(context["workspace"], agent, source.name)
            except OSError as exc:
                _append_cleanup_warning(result, str(exc))
        analytics_pointer.write_verified_deployment_marker(config)
        return _close_deployment_stack(stack, result)
    except _INPUT_ERRORS as exc:
        return _close_deployment_stack(stack, {
            "status": "blocked" if stage == "preparation" else "failed",
            "stage": stage, "error": str(exc),
            "deploymentMayHaveCommitted": stage == "deployment",
            "errors": _exception_chain(exc),
            **({"remoteResult": _redact_evidence(remote_result)}
               if remote_result is not None else {}),
            **({"evidence": exc.evidence} if hasattr(exc, "evidence") else {}),
        })
    except SystemExit as exc:
        return _close_deployment_stack(stack, {
            "status": "failed", "stage": stage,
            "error": f"Configuration/authentication stopped ({exc.code}). See diagnostics.",
        })
    except BaseException as exc:
        try:
            stack.close()
        except OSError as cleanup_exc:
            exc.add_note(f"Deployment lock cleanup also failed: {cleanup_exc}")
        if remote_result is not None and isinstance(exc, Exception):
            raise ComponentEditError(
                "Verified native deployment was followed by an unexpected local failure.",
                {"remoteResult": remote_result, "localCompletion": False},
            ) from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "deploy"))
    parser.add_argument("--set-folder", required=True)
    parser.add_argument("--action", choices=ACTIONS, default="push")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--confirmation-token")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--force-delete", action="store_true")
    args = parser.parse_args()
    _ensure_utf8_stdout(sys.stderr)
    with redirect_stdout(sys.stderr):
        if args.command == "preview":
            result = preview_deployment(
                args.set_folder, action=args.action, replace=args.replace,
            )
        else:
            result = deploy_evaluation_set(
                args.set_folder, action=args.action, replace=args.replace,
                confirmation_token=args.confirmation_token, yes=args.yes,
                force_delete=args.force_delete,
            )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in SUCCESS_STATUSES | {"ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
