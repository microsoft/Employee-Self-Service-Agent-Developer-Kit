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

import push
from auth import load_config
from evaluation_method_policy import EvaluationMethodError, validate_evaluation_folder
from evaluation_promotion import (
    EvaluationPromotionError,
    cleanup_workspace_set,
    promote_workspace_set,
)
from evaluation_review import (
    REVIEW_COMPLETED,
    REVIEW_FILENAME,
    REVIEW_REQUESTED,
    ReviewMetadataError,
    parse_review_marker,
    parse_review_metadata,
    set_review_metadata,
)
from http_errors import APIError
from minimalbot_evaluation import (
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


def _rows(config: dict[str, Any], token: str) -> dict[str, dict[str, Any]]:
    bot_id = str(config["agent"]["botId"]).replace("'", "''")
    rows = push.query_all(
        config["dataverseEndpoint"], token, "botcomponents",
        "botcomponentid,data,description,schemaname,_parentbotcomponentid_value,statecode",
        filter_expr=f"_parentbotid_value eq '{bot_id}' and componenttype eq 19",
    )
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not row.get("botcomponentid") for row in rows
    ):
        raise EvaluationDeploymentError("Malformed Dataverse component response.")
    by_id = {str(row["botcomponentid"]): row for row in rows}
    if len(by_id) != len(rows):
        raise EvaluationDeploymentError("Duplicate Dataverse component identities.")
    return by_id


def _verify_dataverse(
    context: dict[str, Any], component_map: dict[str, Any], rows: dict[str, Any],
) -> str:
    prefix = context["prefix"]
    source = context["files"]
    parent_entry = component_map.get(prefix + _parent(source), {})
    parent_id = str(parent_entry.get("botcomponentid") or "")
    if not parent_id:
        raise EvaluationDeploymentError("The deployed parent identity is not known.")
    expected_children = {
        str(component_map.get(prefix + name, {}).get("botcomponentid") or "")
        for name in source if name.endswith(".mcs.yml") and name != _parent(source)
    }
    actual_children = {
        str(row["botcomponentid"]) for row in rows.values()
        if str(row.get("_parentbotcomponentid_value") or "").casefold()
        == parent_id.casefold()
    }
    if expected_children != actual_children:
        raise EvaluationDeploymentError(
            "The deployed case identities do not match the complete selected set."
        )
    for name, content in source.items():
        if not name.endswith(".mcs.yml"):
            continue
        relative = prefix + name
        entry = component_map.get(relative, {})
        row = rows.get(str(entry.get("botcomponentid") or ""))
        if not row or yaml.safe_load(row.get("data") or "") != yaml.safe_load(content):
            raise EvaluationDeploymentError(
                f"Remote content verification failed for {relative}; no run may start."
            )
        if row.get("statecode", 0) != 0:
            raise EvaluationDeploymentError(f"The deployed component is inactive: {relative}")
        if name != _parent(source) and str(
            row.get("_parentbotcomponentid_value") or ""
        ).casefold() != parent_id.casefold():
            raise EvaluationDeploymentError(f"Remote parent mismatch for {relative}.")
    remote_parent = rows[parent_id]
    if remote_parent.get("_parentbotcomponentid_value"):
        raise EvaluationDeploymentError("The deployed set identity points to a child component.")
    remote_status = parse_review_marker(remote_parent.get("description"))
    if (remote_status or {}).get("status") != _status(source):
        raise EvaluationDeploymentError("The deployed review marker does not match local intent.")
    for relative, entry in context["originalMap"].items():
        if relative.startswith(prefix) and relative not in {
            prefix + name for name in source if name.endswith(".mcs.yml")
        } and str(entry.get("botcomponentid")) in rows:
            raise EvaluationDeploymentError(
                f"Deleted component remains deployed: {relative}"
            )
    return parent_id


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
    native = is_minimalbot(config)
    if not native and (
        not target["dataverseEndpoint"] or not active.get("schemaName")
        or not (agent / ".baseline").is_dir()
        or not (agent / ".component-map.json").is_file()
    ):
        raise EvaluationDeploymentError("Dataverse setup/baseline is incomplete; run /setup.")
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
        "originalMap": component_map, "backend": "minimalbot" if native else "dataverse",
    }
    pending_path = agent / ".evaluation-deployment.json"
    pending = _json_file(pending_path)
    recovery = False
    if pending and (
        pending.get("target") != target or pending.get("prefix") != prefix
        or pending.get("files") != source_files
    ):
        raise EvaluationDeploymentError(
            "A different or changed deployment is unresolved. Reconcile it before continuing."
        )
    if native:
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
            expected = client._expected_components({"entries": selected_map})
            client._verify_components(
                expected, client._remote_components(remote), set(expected)
            )
        if native_pending:
            context["nativePending"] = native_pending
            expected = client._expected_components(plan)
            client._verify_components(
                expected, client._remote_components(remote), set(expected),
            )
            recovery = True
    else:
        auth = push._AuthHolder(config["dataverseEndpoint"])
        auth.acquire()
        context["auth"] = auth
        remote = _rows(config, auth.token)
        if pending:
            context["originalMap"] = pending.get("originalMap", component_map)
            candidate_map = pending.get("candidateMap") or component_map
            recovered_map = {
                **{path: entry for path, entry in component_map.items()
                   if not path.startswith(prefix)},
                **{path: entry for path, entry in candidate_map.items()
                   if path.startswith(prefix)},
            }
            _verify_dataverse(context, recovered_map, remote)
            context["recoveredMap"] = recovered_map
            recovery = True
        else:
            for name in baseline:
                if name.endswith(".mcs.yml") and prefix + name not in selected_map:
                    raise EvaluationDeploymentError(
                        "Baseline component identity is missing. Refresh/reconcile before pushing."
                    )
            for relative, entry in selected_map.items():
                name = relative[len(prefix):]
                row = remote.get(str(entry.get("botcomponentid") or ""))
                if name in baseline and (
                    not row or yaml.safe_load(row.get("data") or "")
                    != yaml.safe_load(baseline[name])
                ):
                    raise EvaluationDeploymentError(
                        "The deployed set changed since the local baseline. "
                        "Refresh/reconcile before replacing it."
                    )
                if name not in baseline:
                    raise EvaluationDeploymentError(
                        "Component tracking and baseline disagree. Reconcile before pushing."
                    )
                if name == _parent(baseline) and (
                    (row.get("description") or "") != (entry.get("description") or "")
                ):
                    raise EvaluationDeploymentError(
                        "The remote parent description changed. Refresh/reconcile "
                        "before replacing review metadata."
                    )
            if baseline:
                _verify_dataverse({**context, "files": baseline}, component_map, remote)
        ids = {
            str(entry.get("botcomponentid"))
            for entry in (
                context.get("recoveredMap", component_map)[path]
                for path in context.get("recoveredMap", component_map)
                if path.startswith(prefix)
            )
        }
        remote_snapshot = {key: remote[key] for key in sorted(ids) if key in remote}
        parent_id = selected_map.get(prefix + _parent(source_files), {}).get("botcomponentid")
        remote_marker = parse_review_marker(
            remote.get(str(parent_id), {}).get("description")
        )
        remote_status = (remote_marker or {}).get("status") or _status(baseline)
        local_status, baseline_status = _status(source_files), _status(baseline)
        if not pending and parent_id and (remote_marker or {}).get("status") != baseline_status:
            raise EvaluationDeploymentError(
                "Remote review state differs from the baseline. Refresh/reconcile "
                "without implicitly completing or replacing a review."
            )
    if native:
        local_status, baseline_status = _status(source_files), _status(baseline)
        remote_status = baseline_status
    if action == "run":
        pending_change = local_status != baseline_status
        blocked = local_status == REVIEW_REQUESTED if native else (
            (
                pending_change and local_status != REVIEW_COMPLETED
                and REVIEW_REQUESTED in (local_status, baseline_status)
            ) or (not pending_change and remote_status == REVIEW_REQUESTED)
        )
        if blocked:
            raise EvaluationDeploymentError(
                "This test set is tagged for review and cannot run until "
                "the review is explicitly completed and pushed."
            )
    changed, new, deleted = push.compute_diff(baseline, source_files)
    local_changed, local_new, local_deleted = push.compute_diff(
        destination_files, source_files,
    )
    token_input = {
        "target": target, "source": str(source), "action": action, "replace": replace,
        "files": source_files, "destination": destination_files, "baseline": baseline,
        "map": selected_map, "remote": remote_snapshot,
        "pending": pending, "nativePending": context.get("nativePending"),
        "nativePlan": context.get("nativePlan"),
    }
    token = hashlib.sha256(
        json.dumps(token_input, sort_keys=True).encode("utf-8")
    ).hexdigest()
    context.update({
        "confirmationToken": token,
        "requiresPush": (
            bool(plan["changes"]) if native else bool(changed or new or deleted)
        ) and not recovery,
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
    if native:
        push._atomic_write_text(str(preview_path), json.dumps({
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
    elif status in SUCCESS_STATUSES:
        result["reviewMetadataPersisted"] = True
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
        deletions = [
            path for path in context["changes"]["deleted"] if path != REVIEW_FILENAME
        ]
        if context["backend"] == "minimalbot" and force_delete:
            raise EvaluationDeploymentError(
                "Existing native Push does not support --force-delete. A new "
                "copy can omit cases, but the old remote copy is retained."
            )
        if deletions and context["backend"] != "minimalbot" and not force_delete:
            raise EvaluationDeploymentError(
                "Selected case deletions require explicit approval and --force-delete."
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
        if context["backend"] == "minimalbot":
            client = context["nativeClient"]
            plan = context["nativePlan"]
            outcome = client.push_agent_evaluations(agent, only_globs=[scope], plan=plan)
            set_id = outcome["sets"][0]["testSetId"]
        else:
            pending_path = agent / ".evaluation-deployment.json"
            pending = {
                "target": context["target"], "prefix": context["prefix"],
                "files": context["files"],
                "originalMap": context["originalMap"],
            }
            def verify(candidate_map):
                pending["candidateMap"] = candidate_map
                push._atomic_write_text(str(pending_path), json.dumps(pending, indent=2))
                if _files(destination) != context["files"] or _files(source) != context["files"]:
                    raise EvaluationDeploymentError(
                        "Source changed during deployment; local synchronization is incomplete."
                    )
                _verify_dataverse(context, candidate_map, _rows(config, context["auth"].token))

            if context["recovering"]:
                recovered_map = context["recoveredMap"]
                verify(recovered_map)
                push.update_baseline_scoped(str(agent), [scope])
                push.save_component_map(str(agent), recovered_map)
                outcome = {"status": "pushed"}
            else:
                if context["requiresPush"]:
                    push._atomic_write_text(str(pending_path), json.dumps(pending, indent=2))
                argv = ["--only", scope, "--yes"]
                if force_delete:
                    argv.append("--force-delete")
                try:
                    outcome = push.main(argv, config=config, verify=verify)
                except SystemExit as exc:
                    return _close_deployment_stack(stack, {
                        **_public(context, "failed"),
                        "error": f"Push stopped with exit code {exc.code}; local source retained.",
                    })
                if outcome["status"] not in SUCCESS_STATUSES:
                    if outcome.get("pendingCreates"):
                        pending["candidateMap"] = {
                            **context["originalMap"], **outcome["pendingCreates"],
                        }
                        push._atomic_write_text(str(pending_path), json.dumps(pending, indent=2))
                    return _close_deployment_stack(stack, {
                        **_public(context, outcome["status"]),
                        **{key: outcome[key] for key in ("error", "remoteCommitted")
                           if key in outcome},
                    })
            component_map = _json_file(agent / ".component-map.json")
            set_id = _verify_dataverse(
                context, component_map, _rows(config, context["auth"].token)
            )
            if _files(agent / ".baseline" / "evaluations" / source.name) != context["files"]:
                raise EvaluationDeploymentError("Baseline synchronization is incomplete.")
            if pending_path.exists():
                pending_path.unlink()
        if _files(destination) != context["files"] or _files(source) != context["files"]:
            raise EvaluationDeploymentError(
                "Source changed during deployment; local synchronization is incomplete."
            )
        result = {
            **_public(context, outcome["status"]),
            "sets": [{
                "sourceFolder": str(source), "agentSetFolder": str(destination),
                "testSetId": set_id,
                "deployedReviewStatus": (
                    _status(context["files"]) if context["backend"] == "dataverse" else None
                ),
            }],
        }
        if context["backend"] == "minimalbot":
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
        return _close_deployment_stack(stack, result)
    except _INPUT_ERRORS as exc:
        return _close_deployment_stack(stack, {
            "status": "blocked" if stage == "preparation" else "failed",
            "stage": stage, "error": str(exc),
            "deploymentMayHaveCommitted": stage == "deployment",
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
    push._ensure_utf8_stdout(sys.stderr)
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
