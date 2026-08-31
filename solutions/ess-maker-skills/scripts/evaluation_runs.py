# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Run Copilot Studio evaluation test sets and retrieve their results."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

from auth import discover_tenant, load_config
from evaluation_review import (
    REVIEW_FILENAME,
    REVIEW_REQUESTED,
)
from flightcheck.pp_admin_client import PPAdminClient
from flightcheck.powerplatform_client import PowerPlatformClient


MCS_CONNECTOR_NAME = "shared_microsoftcopilotstudio"
RUN_WAIT_GUIDANCE = (
    "Running your evaluation may take a while. Please return in 10-15 "
    "minutes to see the results."
)
REVIEW_PENDING_GUIDANCE = (
    "This test set is tagged for review and cannot run until the review is "
    "completed and pushed."
)
REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE = (
    "Review is completed locally, but Copilot Studio still shows "
    "review_requested. Push the review completion before running."
)


class EvaluationRunError(RuntimeError):
    """Raised when an evaluation run operation cannot be completed."""


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def match_test_sets(
    test_sets: list[dict[str, Any]],
    query: str | None,
) -> list[dict[str, Any]]:
    """Rank active test sets by exact, substring, and fuzzy name similarity."""
    active = [
        item for item in test_sets
        if str(item.get("state", "Active")).casefold() == "active"
    ]
    if not query:
        return sorted(
            active,
            key=lambda item: str(item.get("displayName", "")).casefold(),
        )

    target = _normalized_name(query)
    ranked = []
    for item in active:
        name = str(item.get("displayName", ""))
        normalized = _normalized_name(name)
        if normalized == target:
            score = 1.0
        elif target and (target in normalized or normalized in target):
            score = 0.9
        else:
            score = SequenceMatcher(None, target, normalized).ratio()
        if score >= 0.45:
            ranked.append((score, name.casefold(), item))
    ranked.sort(key=lambda value: (-value[0], value[1]))
    return [
        {**item, "matchScore": round(score, 3)}
        for score, _, item in ranked
    ]


def resolve_environment_id(
    config: dict[str, Any],
    client: PowerPlatformClient,
) -> str:
    """Resolve the Power Platform environment ID for the Dataverse URL."""
    configured = config.get("environmentId")
    if isinstance(configured, str) and configured:
        return configured

    target_url = str(config.get("dataverseEndpoint", "")).rstrip("/")
    target_host = (urlparse(target_url).hostname or "").casefold()
    environments = client.list_environments_for_user()
    _raise_api_error(environments, "list environments")
    for environment in environments:
        url = str(environment.get("url", "")).rstrip("/")
        if not url:
            domain = str(environment.get("domainName", "")).strip()
            if domain:
                url = (
                    domain if domain.startswith("https://")
                    else f"https://{domain}"
                )
        host = (urlparse(url).hostname or "").casefold()
        if host == target_host:
            environment_id = environment.get("id")
            if environment_id:
                return str(environment_id)
    raise EvaluationRunError(
        "Could not resolve the Power Platform environment ID for "
        f"{target_url}."
    )


def _raise_api_error(value: Any, operation: str) -> None:
    if isinstance(value, dict) and value.get("_error"):
        status = value.get("_status", "unknown")
        if value.get("_error") == "not_found":
            raise EvaluationRunError(
                f"The requested evaluation run was not found (HTTP {status})."
            )
        raise EvaluationRunError(
            f"Power Platform API could not {operation} (HTTP {status})."
        )


def _connection_id(connection: dict[str, Any]) -> str:
    name = str(connection.get("name") or "").strip()
    if name:
        return name
    return str(connection.get("id") or "").rstrip("/").rsplit("/", 1)[-1]


def connected_mcs_connections(
    connections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize connected Copilot Studio profiles for safe selection."""
    connected = []
    for connection in connections:
        properties = connection.get("properties") or {}
        statuses = properties.get("statuses") or []
        if not any(
            str(status.get("status", "")).casefold() == "connected"
            for status in statuses
            if isinstance(status, dict)
        ):
            continue
        created_by = properties.get("createdBy") or {}
        connection_id = _connection_id(connection)
        if not connection_id:
            continue
        connected.append({
            "id": connection_id,
            "displayName": (
                properties.get("displayName")
                or properties.get("accountName")
                or connection_id
            ),
            "accountName": properties.get("accountName"),
            "createdByDisplayName": created_by.get("displayName"),
            "createdByUserPrincipalName": (
                created_by.get("userPrincipalName")
                or created_by.get("email")
            ),
        })
    return sorted(
        connected,
        key=lambda item: (
            str(item.get("displayName") or "").casefold(),
            item["id"],
        ),
    )


def select_mcs_connection(
    connections: list[dict[str, Any]],
    signed_in_username: str | None = None,
    requested_id: str | None = None,
) -> dict[str, Any]:
    """Select a connected profile, preferring the signed-in account."""
    connected = connected_mcs_connections(connections)
    if requested_id:
        selected = next(
            (item for item in connected if item["id"] == requested_id),
            None,
        )
        if selected:
            return selected
        raise EvaluationRunError(
            "The selected Copilot Studio connection is missing or is not "
            "Connected. Choose a connected profile and retry."
        )
    if not connected:
        raise EvaluationRunError(
            "No Connected Microsoft Copilot Studio connection was found in "
            "this environment. Create or repair the connection in Power Apps "
            "or Power Automate, then retry the evaluation run."
        )
    if len(connected) == 1:
        return connected[0]

    username = str(signed_in_username or "").casefold()
    if username:
        matching = [
            item for item in connected
            if username in {
                str(item.get("accountName") or "").casefold(),
                str(
                    item.get("createdByUserPrincipalName") or ""
                ).casefold(),
            }
        ]
        if len(matching) == 1:
            return matching[0]

    return connected[0]


def resolve_mcs_connection(
    config: dict[str, Any],
    environment_id: str,
    requested_id: str | None = None,
) -> dict[str, Any]:
    """Discover and select the current user's Copilot Studio connection."""
    env_url = str(config["dataverseEndpoint"]).rstrip("/")
    client = PPAdminClient(discover_tenant(env_url))
    client.authenticate(include_flow=False)
    connections = client.get_connector_connections(
        environment_id,
        MCS_CONNECTOR_NAME,
    )
    _raise_api_error(connections, "list Copilot Studio connections")
    return select_mcs_connection(
        connections,
        client.signed_in_username,
        requested_id,
    )


def _runtime(config: dict[str, Any]) -> tuple[
    PowerPlatformClient,
    str,
    str,
    Path,
]:
    env_url = str(config["dataverseEndpoint"]).rstrip("/")
    client = PowerPlatformClient(discover_tenant(env_url))
    client.authenticate()
    environment_id = resolve_environment_id(config, client)
    agent = config["agent"]
    bot_id = str(agent["botId"])
    agent_folder = Path(str(agent["folder"]))
    return client, environment_id, bot_id, agent_folder


def list_remote_test_sets(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """List active remote test sets, optionally ranked by a name query."""
    test_sets = client.list_maker_evaluation_test_sets(environment_id, bot_id)
    _raise_api_error(test_sets, "list evaluation test sets")
    return match_test_sets(test_sets, query)


def list_agent_test_sets(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    agent_folder: str | Path,
    query: str | None = None,
    include_blocked: bool = False,
) -> list[dict[str, Any]]:
    """List active local sets, optionally including review-blocked sets."""
    agent = Path(agent_folder)
    map_path = agent / ".component-map.json"
    if not map_path.is_file():
        raise EvaluationRunError(
            f"Agent component map not found: {map_path}. Run /setup first."
        )
    try:
        component_map = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationRunError(
            f"Unable to read agent component map {map_path}: {exc}"
        ) from exc

    remote_sets = client.list_maker_evaluation_test_sets(
        environment_id,
        bot_id,
    )
    _raise_api_error(remote_sets, "list evaluation test sets")
    remote_by_id = {
        str(item.get("id")): item
        for item in remote_sets
        if str(item.get("state", "Active")).casefold() == "active"
    }

    local_sets = []
    seen: set[str] = set()
    for relative_path, metadata in component_map.items():
        if (
            not isinstance(metadata, dict)
            or metadata.get("componenttype") != 19
            or metadata.get("parentbotcomponentid")
            or not str(relative_path).startswith("evaluations/")
        ):
            continue
        parts = Path(str(relative_path)).parts
        if len(parts) != 3:
            continue
        test_set_id = str(metadata.get("botcomponentid") or "")
        remote = remote_by_id.get(test_set_id)
        if not remote or test_set_id in seen:
            continue
        set_folder = agent / "evaluations" / parts[1]
        if not set_folder.is_dir():
            continue
        review_statuses: list[str | None] = []
        for review_path in (
            set_folder / REVIEW_FILENAME,
            agent / ".baseline" / "evaluations" / parts[1] / REVIEW_FILENAME,
        ):
            review_status = None
            if not review_path.is_file():
                review_statuses.append(review_status)
                continue
            try:
                review_metadata = json.loads(
                    review_path.read_text(encoding="utf-8")
                )
                if isinstance(review_metadata, dict):
                    status = review_metadata.get("status")
                    if isinstance(status, str):
                        review_status = status
            except (OSError, json.JSONDecodeError):
                pass
            review_statuses.append(review_status)
        local_review_status, deployed_review_status = review_statuses
        blocked_reason = None
        if (
            local_review_status == "review_completed"
            and deployed_review_status == REVIEW_REQUESTED
        ):
            blocked_reason = REVIEW_COMPLETION_NOT_PUSHED_GUIDANCE
        elif REVIEW_REQUESTED in review_statuses:
            blocked_reason = REVIEW_PENDING_GUIDANCE
        if blocked_reason and not include_blocked:
            continue
        seen.add(test_set_id)
        local_count = sum(
            1
            for path in set_folder.glob("*.mcs.yml")
            if "kind: EvaluationData" in path.read_text(encoding="utf-8")
        )
        local_sets.append({
            **remote,
            "localFolder": str(set_folder.resolve()),
            "localSetName": parts[1],
            "localTestCaseCount": local_count,
            "reviewStatus": local_review_status,
            "localReviewStatus": local_review_status,
            "deployedReviewStatus": deployed_review_status,
            "runnable": blocked_reason is None,
            "blockedReason": blocked_reason,
            "source": "Configured agent evaluations folder",
        })
    return match_test_sets(local_sets, query)


def start_run(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    test_set: dict[str, Any],
    mcs_connection_id: str,
    run_name: str | None = None,
    run_on_published_bot: bool = False,
) -> dict[str, Any]:
    """Start an evaluation run and return its initial API state."""
    test_set_id = str(test_set["id"])
    test_set_name = str(test_set.get("displayName") or test_set_id)
    now = datetime.now(timezone.utc)
    body: dict[str, Any] = {
        "evaluationRunName": (
            run_name
            or f"{test_set_name} - {now.strftime('%Y-%m-%d %H:%M UTC')}"
        ),
        "runOnPublishedBot": run_on_published_bot,
    }
    body["mcsConnectionId"] = mcs_connection_id

    response = client.run_maker_evaluation_test_set(
        environment_id,
        bot_id,
        test_set_id,
        body,
    )
    _raise_api_error(response, "start the evaluation run")
    run_id = response.get("runId")
    if not run_id:
        raise EvaluationRunError(
            "Power Platform API did not return an evaluation run ID."
        )
    run_details = {
        "runId": str(run_id),
        "testSetId": test_set_id,
        "testSetName": test_set_name,
        "runName": body["evaluationRunName"],
        "startedAt": now.isoformat(),
        "userGuidance": RUN_WAIT_GUIDANCE,
    }
    return {**response, **run_details}


def _remote_run_history(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
) -> list[dict[str, Any]]:
    test_sets = client.list_maker_evaluation_test_sets(environment_id, bot_id)
    _raise_api_error(test_sets, "list evaluation test sets")
    names = {
        str(item.get("id")): str(item.get("displayName") or item.get("id"))
        for item in test_sets
    }
    runs = client.list_maker_evaluation_test_runs(environment_id, bot_id)
    _raise_api_error(runs, "list evaluation runs")
    enriched = []
    for run in runs:
        test_set_id = str(run.get("testSetId", ""))
        enriched.append({
            **run,
            "runId": str(run.get("id") or run.get("runId") or ""),
            "testSetName": names.get(test_set_id, "Unknown test set"),
            "source": "Power Platform API",
        })
    return sorted(
        enriched,
        key=lambda item: str(item.get("startTime", "")),
        reverse=True,
    )


def list_runs(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
) -> list[dict[str, Any]]:
    """List remote runs with test-set display names."""
    return _remote_run_history(client, environment_id, bot_id)


def _case_names(agent_folder: Path) -> dict[str, str]:
    map_path = agent_folder / ".component-map.json"
    if not map_path.is_file():
        return {}
    try:
        component_map = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    names = {}
    for relative_path, metadata in component_map.items():
        if (
            isinstance(metadata, dict)
            and metadata.get("componenttype") == 19
            and metadata.get("parentbotcomponentid")
            and metadata.get("botcomponentid")
        ):
            names[str(metadata["botcomponentid"])] = str(
                metadata.get("name") or Path(relative_path).stem
            )
    return names


def _metric(
    case: dict[str, Any],
    metric_type: str,
) -> dict[str, Any] | None:
    metrics = case.get("metricsResults")
    if not isinstance(metrics, list):
        return None
    return next(
        (
            metric for metric in metrics
            if isinstance(metric, dict)
            and metric.get("type") == metric_type
        ),
        None,
    )


def _metric_result(metric: dict[str, Any] | None) -> dict[str, Any]:
    result = metric.get("result") if metric else None
    return result if isinstance(result, dict) else {}


def _case_passed(case: dict[str, Any]) -> bool:
    metrics = case.get("metricsResults")
    if not isinstance(metrics, list) or not metrics:
        return str(case.get("state", "")).casefold() == "completed"
    return all(
        str(_metric_result(metric).get("status", "")).casefold() == "pass"
        for metric in metrics
        if isinstance(metric, dict)
    )


def _failure_pattern(case: dict[str, Any]) -> dict[str, str]:
    compare = _metric_result(_metric(case, "CompareMeaning"))
    general = _metric_result(_metric(case, "GeneralQuality"))

    if str(compare.get("status", "")).casefold() == "fail":
        evidence = (
            compare.get("aiResultReason")
            or compare.get("errorReason")
            or "CompareMeaning returned Fail."
        )
        return {
            "category": "Expected-meaning mismatch",
            "suggestedAction": (
                "Inspect the agent response against the expected behavior and "
                "correct the operation, grounding, or response."
            ),
            "evidence": str(evidence),
        }

    if str(general.get("status", "")).casefold() == "fail":
        data = general.get("data")
        data = data if isinstance(data, dict) else {}
        abstention = str(data.get("abstention", "NA"))
        completeness = str(data.get("completeness", "NA"))
        compare_reason = str(compare.get("aiResultReason") or "").strip()
        if abstention.casefold() == "yes":
            category = "Abstention graded incomplete"
            action = (
                "Check whether abstention is expected for this case. If it is, "
                "review the General Quality grading behavior before changing "
                "the agent."
            )
        elif completeness.casefold() == "no":
            category = "Incomplete response"
            action = (
                "Add the missing user-facing information while preserving the "
                "expected behavior."
            )
        else:
            category = "General Quality failure"
            action = "Review the General Quality dimensions for this response."
        evidence = (
            f"General Quality: abstention={abstention}, "
            f"completeness={completeness}."
        )
        if compare_reason:
            evidence = f"{evidence} CompareMeaning: {compare_reason}"
        return {
            "category": category,
            "suggestedAction": action,
            "evidence": evidence,
        }

    return {
        "category": "Execution or metric failure",
        "suggestedAction": "Inspect the returned case state and metric errors.",
        "evidence": str(case.get("state") or "Unknown case state"),
    }


def analyze_run_results(result: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic summary and failure-group data for presentation."""
    cases = result.get("testCasesResults")
    cases = [
        case for case in cases
        if isinstance(case, dict)
    ] if isinstance(cases, list) else []
    passed = [case for case in cases if _case_passed(case)]
    failed = [case for case in cases if not _case_passed(case)]
    total = len(cases)
    pass_rate = round((len(passed) / total) * 100, 1) if total else 0.0

    groups: dict[str, dict[str, Any]] = {}
    for case in failed:
        pattern = _failure_pattern(case)
        group = groups.setdefault(pattern["category"], {
            "category": pattern["category"],
            "cases": [],
            "owner": "Unassigned",
            "suggestedAction": pattern["suggestedAction"],
            "representativeEvidence": pattern["evidence"],
        })
        group["cases"].append(
            case.get("testCaseName") or case.get("testCaseId")
        )

    failure_groups = []
    for group in groups.values():
        count = len(group.pop("cases"))
        failure_groups.append({
            **group,
            "caseCount": count,
            "failurePercentage": (
                round((count / len(failed)) * 100, 1) if failed else 0.0
            ),
        })
    failure_groups.sort(
        key=lambda item: (-item["caseCount"], item["category"])
    )

    test_set_name = str(
        result.get("testSetName")
        or result.get("testSetId")
        or "Evaluation set"
    )
    return {
        "summary": {
            "totalCases": total,
            "passedCases": len(passed),
            "failedCases": len(failed),
            "passRate": pass_rate,
        },
        "scenarioGroups": [{
            "group": test_set_name,
            "cases": total,
            "passed": len(passed),
            "failed": len(failed),
            "passRate": pass_rate,
        }],
        "failureGroups": failure_groups,
    }


def get_run_results(
    client: PowerPlatformClient,
    environment_id: str,
    bot_id: str,
    agent_folder: str | Path,
    run_id: str,
) -> dict[str, Any]:
    """Retrieve one run and enrich test case IDs with local case names."""
    result = client.get_maker_evaluation_test_run(
        environment_id,
        bot_id,
        run_id,
    )
    _raise_api_error(result, "retrieve evaluation run results")
    names = _case_names(Path(agent_folder))
    cases = result.get("testCasesResults")
    if isinstance(cases, list):
        result["testCasesResults"] = [
            {
                **case,
                "testCaseName": names.get(
                    str(case.get("testCaseId", "")),
                    "Unknown test case",
                ),
            }
            for case in cases
            if isinstance(case, dict)
        ]
    test_set_id = str(result.get("testSetId", ""))
    if not result.get("testSetName") and test_set_id:
        test_sets = client.list_maker_evaluation_test_sets(
            environment_id,
            bot_id,
        )
        _raise_api_error(test_sets, "list evaluation test sets")
        selected = next(
            (
                item for item in test_sets
                if str(item.get("id")) == test_set_id
            ),
            None,
        )
        if selected:
            result["testSetName"] = (
                selected.get("displayName") or test_set_id
            )
    result["analysis"] = analyze_run_results(result)
    return result


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Copilot Studio evaluation test sets and get results."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_sets_parser = subparsers.add_parser("list-sets")
    list_sets_parser.add_argument("--query")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--test-set-id", required=True)
    run_parser.add_argument("--test-set-name")
    run_parser.add_argument("--run-name")
    run_parser.add_argument("--published", action="store_true")
    run_parser.add_argument("--mcs-connection-id")

    list_runs_parser = subparsers.add_parser("list-runs")

    results_parser = subparsers.add_parser("results")
    results_parser.add_argument("--run-id", required=True)

    args = parser.parse_args()
    try:
        config = load_config()
        client, environment_id, bot_id, agent_folder = _runtime(config)
        if args.command == "list-sets":
            _print_json(list_agent_test_sets(
                client,
                environment_id,
                bot_id,
                agent_folder,
                args.query,
                include_blocked=True,
            ))
        elif args.command == "run":
            test_sets = list_agent_test_sets(
                client,
                environment_id,
                bot_id,
                agent_folder,
            )
            selected = next(
                (
                    item for item in test_sets
                    if str(item.get("id")) == args.test_set_id
                ),
                None,
            )
            if selected is None:
                raise EvaluationRunError(
                    "The selected test set is not active or no longer exists."
                )
            connection = resolve_mcs_connection(
                config,
                environment_id,
                args.mcs_connection_id,
            )
            _print_json(start_run(
                client,
                environment_id,
                bot_id,
                selected,
                connection["id"],
                run_name=args.run_name,
                run_on_published_bot=args.published,
            ))
        elif args.command == "list-runs":
            _print_json(list_runs(
                client,
                environment_id,
                bot_id,
            ))
        elif args.command == "results":
            _print_json(get_run_results(
                client,
                environment_id,
                bot_id,
                agent_folder,
                args.run_id,
            ))
    except EvaluationRunError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
