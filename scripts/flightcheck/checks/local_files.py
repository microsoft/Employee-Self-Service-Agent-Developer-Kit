# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Local Agent File Validation

Net-new capability: validates the extracted agent files on disk (topics,
agent identity, knowledge, variables). This covers checks that FlightCheck
marked as "NotConfigured" because it had no access to the actual files.
"""

import os
import re
from pathlib import Path
from urllib.parse import urljoin

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# Required topics that ESS agents should have (by schema name substring)
REQUIRED_TOPICS = [
    {"id": "TOPIC-001", "pattern": "usercontext", "name": "[Admin] User Context - Setup", "priority": "Critical"},
    {"id": "TOPIC-002", "pattern": "responsepreparation", "name": "[System] Response Preparation", "priority": "Critical"},
    {"id": "TOPIC-004", "pattern": "sensitivetopic", "name": "[Example] Sensitive Topics", "priority": "High"},
    {"id": "TOPIC-005", "pattern": "onerror", "name": "[System] On Error", "priority": "High"},
    {"id": "TOPIC-009", "pattern": "emotionalintelligence|emotionalquotient", "name": "Emotional Intelligence", "priority": "High"},
    {"id": "TOPIC-010", "pattern": "ambiguity", "name": "Ambiguity Clarification", "priority": "High"},
]


def run_local_file_checks(runner) -> list[CheckResult]:
    """Validate local agent files for ALL agents under my/agents/."""
    results: list[CheckResult] = []

    # Discover all agent folders under my/agents/
    agents_root = Path("my/agents")
    if not agents_root.exists():
        results.append(CheckResult(
            checkpoint_id="LOCAL-001", category="Local Files",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Agent files available",
            result="my/agents/ directory not found",
            remediation="Run /setup to extract agent files.",
        ))
        return results

    agent_folders = [d for d in agents_root.iterdir() if d.is_dir() and not d.name.startswith(".")]

    if not agent_folders:
        results.append(CheckResult(
            checkpoint_id="LOCAL-001", category="Local Files",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Agent files available",
            result="No agent folders found under my/agents/",
            remediation="Run /setup to extract agent files.",
        ))
        return results

    # Run checks for each agent
    for agent_path in sorted(agent_folders):
        agent_name = agent_path.name
        results.extend(_check_single_agent(agent_path, agent_name, runner))

    return results


def _check_single_agent(agent_path: Path, agent_name: str, runner=None) -> list[CheckResult]:
    """Run all local file checks for a single agent."""
    results: list[CheckResult] = []

    # Use agent name as a prefix in descriptions for multi-agent clarity
    label = agent_name.replace("-", " ").title()

    # ---- Agent identity (agent.mcs.yml) ----
    results.extend(_check_agent_identity(agent_path, label))

    # ---- Required topics ----
    results.extend(_check_required_topics(agent_path, label))

    # ---- Topic count ----
    results.extend(_check_topic_inventory(agent_path, label))

    # ---- Variables ----
    results.extend(_check_variables(agent_path, label))

    # ---- Template configs ----
    results.extend(_check_template_configs(agent_path, label))

    # ---- Knowledge source readiness ----
    results.extend(_check_knowledge_sources(agent_path, label, runner))

    return results


def _check_agent_identity(agent_path: Path, label: str) -> list[CheckResult]:
    """Check agent.mcs.yml for instructions, name, starter prompts."""
    results = []
    agent_file = agent_path / "agent.mcs.yml"

    if not agent_file.exists():
        results.append(CheckResult(
            checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description=f"{label}: Agent identity file",
            result="agent.mcs.yml not found",
            remediation="Re-run /setup to extract agent files.",
        ))
        return results

    content = agent_file.read_text(encoding="utf-8")

    instructions_match = re.search(r'instructions:\s*[|>]?\s*\n((?:\s+.+\n)+)', content)
    if instructions_match:
        instruction_text = instructions_match.group(1).strip()
        word_count = len(instruction_text.split())
        if word_count >= 50:
            results.append(CheckResult(
                checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description=f"{label}: Agent instructions",
                result=f"Instructions present ({word_count} words)",
                doc_link=f"{DOC_BASE}/customize",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description=f"{label}: Agent instructions",
                result=f"Instructions seem short ({word_count} words)",
                remediation="Expand agent instructions for better responses.",
                doc_link=f"{DOC_BASE}/customize",
            ))
    else:
        results.append(CheckResult(
            checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description=f"{label}: Agent instructions",
            result="No instructions block found in agent.mcs.yml",
            remediation="Add agent instructions in [Copilot Studio](https://copilotstudio.microsoft.com/), then re-extract with `/setup`.",
            doc_link=f"{DOC_BASE}/customize",
        ))

    prompt_count = len(re.findall(r'conversationStarters?:', content, re.IGNORECASE))
    starter_items = re.findall(r'-\s+text:', content)
    count = len(starter_items) if starter_items else prompt_count
    if count >= 3:
        results.append(CheckResult(
            checkpoint_id="CONFIG-005", category=f"Configuration ({label})",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=f"{label}: Starter prompts",
            result=f"{count} starter prompt(s) found",
            doc_link=f"{DOC_BASE}/customize#customize-starter-prompts",
        ))
    elif count > 0:
        results.append(CheckResult(
            checkpoint_id="CONFIG-005", category=f"Configuration ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Starter prompts",
            result=f"Only {count} starter prompt(s) — recommend 6-12",
            remediation="Add more starter prompts in [Copilot Studio](https://copilotstudio.microsoft.com/).",
            doc_link=f"{DOC_BASE}/customize#customize-starter-prompts",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="CONFIG-005", category=f"Configuration ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Starter prompts",
            result="No starter prompts detected",
            remediation="Add starter prompts in [Copilot Studio](https://copilotstudio.microsoft.com/).",
            doc_link=f"{DOC_BASE}/customize#customize-starter-prompts",
        ))

    return results


def _check_required_topics(agent_path: Path, label: str) -> list[CheckResult]:
    """Check that required system/admin topics exist."""
    results = []
    topics_dir = agent_path / "topics"

    if not topics_dir.exists():
        for req in REQUIRED_TOPICS:
            results.append(CheckResult(
                checkpoint_id=req["id"], category=f"Topics ({label})",
                priority=req["priority"], status=Status.SKIPPED.value,
                description=f"{label}: {req['name']}",
                result="Topics directory not found",
            ))
        return results

    topic_contents = {}
    for tf in topics_dir.glob("*.mcs.yml"):
        topic_contents[tf.name.lower()] = tf.read_text(encoding="utf-8", errors="replace")

    for req in REQUIRED_TOPICS:
        pattern = req["pattern"]
        found = False
        for fname, content in topic_contents.items():
            if re.search(pattern, fname) or re.search(pattern, content, re.IGNORECASE):
                found = True
                break

        if found:
            results.append(CheckResult(
                checkpoint_id=req["id"], category=f"Topics ({label})",
                priority=req["priority"], status=Status.PASSED.value,
                description=f"{label}: {req['name']}",
                result="Topic found",
                doc_link=f"{DOC_BASE}/customize#customize-topics",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id=req["id"], category=f"Topics ({label})",
                priority=req["priority"], status=Status.WARNING.value,
                description=f"{label}: {req['name']}",
                result="Required topic not found in extracted files",
                remediation=f"Verify '{req['name']}' exists in [Copilot Studio](https://copilotstudio.microsoft.com/).",
                doc_link=f"{DOC_BASE}/customize#customize-topics",
            ))

    return results


def _check_topic_inventory(agent_path: Path, label: str) -> list[CheckResult]:
    """Count total topics and flag if unusually low."""
    results = []
    topics_dir = agent_path / "topics"

    if not topics_dir.exists():
        return results

    count = len(list(topics_dir.glob("*.mcs.yml")))

    results.append(CheckResult(
        checkpoint_id="TOPIC-011", category=f"Topics ({label})",
        priority=Priority.MEDIUM.value,
        status=Status.PASSED.value if count >= 5 else Status.WARNING.value,
        description=f"{label}: Topic inventory",
        result=f"{count} topic(s) in agent",
        remediation="ESS agents typically have 20+ topics." if count < 5 else "",
    ))

    return results


def _check_variables(agent_path: Path, label: str) -> list[CheckResult]:
    """Check for User Context variables."""
    results = []
    vars_dir = agent_path / "variables"

    if not vars_dir.exists():
        results.append(CheckResult(
            checkpoint_id="CONFIG-012", category=f"Configuration ({label})",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description=f"{label}: User Context variables",
            result="Variables directory not found",
            remediation="Run /setup to extract agent files.",
        ))
        return results

    var_files = list(vars_dir.glob("*.mcs.yml"))
    results.append(CheckResult(
        checkpoint_id="CONFIG-012", category=f"Configuration ({label})",
        priority=Priority.CRITICAL.value,
        status=Status.PASSED.value if var_files else Status.WARNING.value,
        description=f"{label}: User Context variables",
        result=f"{len(var_files)} variable(s) found",
        remediation="Create User Context variables for employee data." if not var_files else "",
        doc_link=f"{DOC_BASE}/customize",
    ))

    return results


def _check_template_configs(agent_path: Path, label: str) -> list[CheckResult]:
    """Check template config inventory."""
    results = []
    tc_dir = agent_path / "template-configs"

    if not tc_dir.exists():
        return results

    xml_files = list(tc_dir.glob("*.xml"))
    meta_files = list(tc_dir.glob("*.meta.json"))

    results.append(CheckResult(
        checkpoint_id="LOCAL-TC-001", category=f"Template Configs ({label})",
        priority=Priority.MEDIUM.value, status=Status.PASSED.value,
        description=f"{label}: Template configurations",
        result=f"{len(xml_files)} XML template(s), {len(meta_files)} metadata file(s)",
    ))

    return results


# Knowledge source statuses that indicate readiness
_READY_STATUSES = {"active", "completed", "indexed", "ready", "succeeded"}
# Statuses that indicate a knowledge source is not ready for deployment
_NOT_READY_STATUSES = {"pending", "crawling", "queued", "provisioning", "failed", "error", "inactive"}


def _check_knowledge_sources(agent_path: Path, label: str, runner=None) -> list[CheckResult]:
    """
    CONFIG-013: Verify that all configured knowledge sources have completed
    their initial crawl and are fully indexed.

    Uses the Copilot Studio Island Gateway API to get live status when available,
    otherwise falls back to local file validation only.
    """
    results = []
    knowledge_dir = agent_path / "knowledge"

    if not knowledge_dir.exists():
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=f"{label}: Knowledge source readiness",
            result="No knowledge directory found — no sources configured",
        ))
        return results

    knowledge_files = list(knowledge_dir.glob("*.mcs.yml"))
    if not knowledge_files:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=f"{label}: Knowledge source readiness",
            result="No knowledge source files found",
        ))
        return results

    # Require the Island Gateway API for live status
    pva = getattr(runner, "pva", None) if runner else None
    bot_id = None
    if runner and hasattr(runner, "config"):
        bot_id = runner.config.get("agent", {}).get("botId")

    if not pva or not hasattr(pva, "is_configured") or not pva.is_configured or not bot_id:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=f"{label}: Knowledge source readiness",
            result="Cannot verify — Copilot Studio API authentication required",
        ))
        return results

    return _check_knowledge_sources_via_gateway(pva, bot_id, knowledge_files, label)


def _check_knowledge_sources_via_gateway(pva, bot_id: str, knowledge_files: list, label: str) -> list[CheckResult]:
    """Check knowledge source status using the Island Gateway API."""
    results = []

    try:
        sources = pva.get_knowledge_sources(bot_id)
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Knowledge source crawl status",
            result=f"Could not query Copilot Studio API: {e}",
            remediation="Check authentication and retry. Verify status manually in Copilot Studio → Knowledge.",
        ))
        return results

    if not sources:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Knowledge source readiness",
            result=f"{len(knowledge_files)} local knowledge file(s) but no matching components returned from API",
            remediation="Knowledge sources may not be published yet. Publish the agent in Copilot Studio.",
        ))
        return results

    all_ready = True
    for source in sources:
        name = source.get("displayName", "Unknown")
        status_value = (source.get("status") or source.get("state") or "unknown").lower()
        source_kind = ""
        config = source.get("configuration", {})
        if config:
            src = config.get("source", {})
            source_kind = src.get("$kind", "")

        # Determine source type for display
        source_type = _format_source_type(source_kind)

        if status_value in _READY_STATUSES:
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Status: {status_value} — indexed and ready",
            ))
        elif status_value in _NOT_READY_STATUSES:
            all_ready = False
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Status: {status_value} — not ready for deployment",
                remediation=(
                    f"Knowledge source '{name}' has not completed indexing. "
                    "Wait for the crawl to finish, or check for errors in "
                    "Copilot Studio → Knowledge."
                ),
            ))
        else:
            all_ready = False
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Status: '{status_value}' — verify in Copilot Studio",
                remediation=(
                    "Could not confirm index readiness. "
                    "Verify knowledge source status in Copilot Studio → Knowledge."
                ),
            ))

    if all_ready and sources:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=f"{label}: All knowledge sources indexed",
            result=f"{len(sources)} knowledge source(s) fully indexed and ready",
        ))

    return results


def _format_source_type(source_kind: str) -> str:
    """Convert a $kind value to a human-readable source type."""
    mapping = {
        "SharePointSearchSource": "SharePoint",
        "GraphConnectorSearchSource": "Graph Connector",
        "FileSource": "File Upload",
        "WebSearchSource": "Web",
        "DataverseSource": "Dataverse",
    }
    return mapping.get(source_kind, source_kind or "Unknown")
