# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Live native-agent verification for Workday lifecycle completion."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping

from minimalbot_evaluation import (
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
    resolve_workday_dialogs,
)


class WorkdayConnectAgentError(RuntimeError):
    """Raised when native Workday agent readiness cannot be proven."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkdayConnectAgentError(
            f"Required workspace state could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectAgentError(
            f"Required workspace state must contain an object: {path}"
        )
    return document


def _required_text(
    values: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(values.get(key) or "").strip()
    if not value:
        raise WorkdayConnectAgentError(f"{label} is missing.")
    return value


def _active_agent(config: Mapping[str, Any]) -> dict[str, Any]:
    active_slug = str(config.get("activeAgent") or "").strip()
    agents = config.get("agents")
    if isinstance(agents, list) and active_slug:
        matches = [
            dict(agent)
            for agent in agents
            if isinstance(agent, Mapping)
            and str(agent.get("slug") or "") == active_slug
        ]
        if len(matches) == 1:
            return matches[0]
    agent = config.get("agent")
    if isinstance(agent, Mapping) and str(agent.get("slug") or "") == active_slug:
        return dict(agent)
    raise WorkdayConnectAgentError(
        "The active agent could not be resolved from foundation setup state."
    )


def _agent_folder(
    workspace_root: Path,
    agent: Mapping[str, Any],
) -> Path:
    configured = str(agent.get("folder") or "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
    else:
        candidate = (
            workspace_root
            / "workspace"
            / "agents"
            / _required_text(agent, "slug", "Active agent slug")
        )
    candidate = candidate.resolve()
    agents_root = (workspace_root / "workspace" / "agents").resolve()
    try:
        candidate.relative_to(agents_root)
    except ValueError as exc:
        raise WorkdayConnectAgentError(
            "The active agent folder is outside workspace/agents."
        ) from exc
    if not candidate.is_dir():
        raise WorkdayConnectAgentError(
            f"The active agent workspace folder does not exist: {candidate}"
        )
    return candidate


def run_flightcheck_checkpoint(
    workspace_root: Path,
    state: Mapping[str, Any],
    checkpoint_id: str,
    *,
    preferred_username: str,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    """Run one checkpoint and require an explicit Passed result row."""
    scope = state.get("scope") or {}
    agent = scope.get("agent") or {}
    command = [
        sys.executable,
        str(workspace_root / "scripts" / "flightcheck" / "cli.py"),
        "--checkpoint",
        checkpoint_id,
        "--connect-config",
        str(workspace_root / ".local" / "connect" / "workday-da" / "config.json"),
        "--agent-slug",
        _required_text(agent, "slug", "Active agent slug"),
        "--environment-id",
        _required_text(scope, "environmentId", "Environment ID"),
        "--environment-url",
        _required_text(scope, "dataverseUrl", "Dataverse URL"),
        "--preferred-username",
        preferred_username,
        "--quiet-auth",
        "--no-open",
        "--no-telemetry",
    ]
    with tempfile.TemporaryDirectory(prefix="workday-checkpoint-") as output:
        command.extend(["--output", output])
        try:
            completed = runner(
                command,
                cwd=workspace_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkdayConnectAgentError(
                f"FlightCheck {checkpoint_id} did not finish within five minutes."
            ) from exc
        results_path = Path(output) / "results.json"
        try:
            report = json.loads(results_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            detail = (completed.stderr or completed.stdout or "").strip()[:500]
            raise WorkdayConnectAgentError(
                f"FlightCheck {checkpoint_id} produced no readable result"
                + (f": {detail}" if detail else ".")
            ) from exc
    results = report.get("results")
    if not isinstance(results, list):
        raise WorkdayConnectAgentError(
            f"FlightCheck {checkpoint_id} returned an invalid result document."
        )
    matching = [
        result
        for result in results
        if isinstance(result, dict) and result.get("checkpoint_id") == checkpoint_id
    ]
    statuses = {str(result.get("status") or "") for result in matching}
    if completed.returncode != 0 or not matching or statuses != {"Passed"}:
        details = "; ".join(
            str(result.get("result") or result.get("status") or "")
            for result in matching
        )
        raise WorkdayConnectAgentError(
            f"FlightCheck {checkpoint_id} did not pass"
            + (f": {details}" if details else ".")
        )
    return "Passed"


def verify_agent_binding(
    workspace_root: Path,
    state: Mapping[str, Any],
    *,
    checkpoint_verifier: Callable[..., str] = run_flightcheck_checkpoint,
    client_factory: Callable[
        [dict[str, Any]], MinimalBotEvaluationClient
    ] = MinimalBotEvaluationClient.from_config,
) -> dict[str, Any]:
    """Verify Workday binding without using topic diagnostics as runtime proof."""
    context = _agent_verification_context(workspace_root, state)
    checkpoints = {
        checkpoint_id: checkpoint_verifier(
            workspace_root,
            state,
            checkpoint_id,
            preferred_username=context["makerUsername"],
        )
        for checkpoint_id in ("WD-REST-002", "WD-CONN-013")
    }
    evidence = _verify_workday_topics(
        context,
        client_factory=client_factory,
        require_clean_diagnostics=False,
    )
    evidence["checkpoints"] = checkpoints
    return evidence


def _agent_verification_context(
    workspace_root: Path,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    foundation = _read_json(workspace_root / ".local" / "config.json")
    scope = state.get("scope") or {}
    recorded_agent = scope.get("agent") or {}
    active_agent = _active_agent(foundation)
    environment_id = _required_text(
        scope,
        "environmentId",
        "Recorded environment ID",
    )
    foundation_environment = _required_text(
        foundation,
        "environmentId",
        "Foundation environment ID",
    )
    if foundation_environment.casefold() != environment_id.casefold():
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state target different environments."
        )
    recorded_slug = _required_text(
        recorded_agent,
        "slug",
        "Recorded agent slug",
    )
    if (
        _required_text(active_agent, "slug", "Active agent slug").casefold()
        != recorded_slug.casefold()
    ):
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state target different agents."
        )
    bot_id = _required_text(recorded_agent, "botId", "Recorded agent bot ID")
    if (
        _required_text(active_agent, "botId", "Active agent bot ID").casefold()
        != bot_id.casefold()
    ):
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state target different agents."
        )
    agent_schema = _required_text(
        active_agent,
        "schemaName",
        "Active agent schema name",
    )
    if (
        _required_text(
            recorded_agent,
            "schemaName",
            "Recorded agent schema name",
        ).casefold()
        != agent_schema.casefold()
    ):
        raise WorkdayConnectAgentError(
            "Foundation setup and Workday state contain different agent schemas."
        )
    maker = _required_text(
        (state.get("operators") or {}).get("powerPlatformMaker") or {},
        "username",
        "Power Platform maker account",
    )
    return {
        "foundation": foundation,
        "environmentId": environment_id,
        "botId": bot_id,
        "makerUsername": maker,
        "agentSchema": agent_schema,
        "agentFolder": _agent_folder(workspace_root, active_agent),
    }


def _verify_workday_topics(
    context: Mapping[str, Any],
    *,
    client_factory: Callable[[dict[str, Any]], MinimalBotEvaluationClient],
    require_clean_diagnostics: bool,
) -> dict[str, Any]:
    topics = resolve_workday_dialogs(
        context["agentFolder"],
        str(context["agentSchema"]),
    )
    expectations = [
        {
            **topic,
            "state": "Active",
            "status": "Active",
            "requireCleanDiagnostics": require_clean_diagnostics,
        }
        for topic in topics
    ]
    try:
        client = client_factory(dict(context["foundation"]))
        client.authenticate(
            preferred_username=str(context["makerUsername"]),
        )
        verification = client.verify_dialog_components(expectations)
    except MinimalBotEvaluationError as exc:
        customer_safe = (
            str(exc)
            .replace("MinimalBot dialog", "Copilot Studio topic")
            .replace("MinimalBot", "Copilot Studio")
            .replace("component map", "topic inventory")
        )
        raise WorkdayConnectAgentError(customer_safe) from exc

    return {
        "environmentId": context["environmentId"],
        "botId": context["botId"],
        "makerUsername": str(client.signed_in_username or context["makerUsername"]),
        "checkpoints": {},
        "workdayTopics": {
            "expected": len(topics),
            "verified": verification["verifiedComponents"],
            "active": verification["activeComponents"],
            "blockingDiagnostics": verification["blockingDiagnostics"],
        },
    }


def verify_topic_activation(
    workspace_root: Path,
    state: Mapping[str, Any],
    *,
    client_factory: Callable[
        [dict[str, Any]], MinimalBotEvaluationClient
    ] = MinimalBotEvaluationClient.from_config,
) -> dict[str, Any]:
    """Verify live topic activation without treating dependency health as state."""
    return _verify_workday_topics(
        _agent_verification_context(workspace_root, state),
        client_factory=client_factory,
        require_clean_diagnostics=False,
    )
