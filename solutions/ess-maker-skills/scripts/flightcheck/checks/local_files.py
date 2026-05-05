# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Local Agent File Validation

Net-new capability: validates the extracted agent files on disk (topics,
agent identity, knowledge, variables). This covers checks that FlightCheck
marked as "NotConfigured" because it had no access to the actual files.
"""

import re
from pathlib import Path

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
    """Validate local agent files for ALL agents under workspace/agents/."""
    results: list[CheckResult] = []

    # Discover all agent folders under workspace/agents/
    agents_root = Path("workspace/agents")
    if not agents_root.exists():
        results.append(CheckResult(
            checkpoint_id="LOCAL-001", category="Local Files",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Agent files available",
            result="workspace/agents/ directory not found",
            remediation="Run /setup to extract agent files.",
        ))
        return results

    agent_folders = [d for d in agents_root.iterdir() if d.is_dir() and not d.name.startswith(".")]

    if not agent_folders:
        results.append(CheckResult(
            checkpoint_id="LOCAL-001", category="Local Files",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Agent files available",
            result="No agent folders found under workspace/agents/",
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

    # ---- Topic description quality ----
    results.extend(_check_topic_descriptions(agent_path, label, runner, agent_name))

    # ---- Template configs ----
    results.extend(_check_template_configs(agent_path, label))

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


# Minimum word count for a useful topic description
_MIN_DESCRIPTION_WORDS = 20

# System topics that don't use AI-based routing (no description needed)
_SYSTEM_TOPIC_PATTERNS = [
    r"conversation-start",
    r"on-error",
    r"reset-conversation",
    r"log-telemetry",
    r"microsoft-self-help",
    r"response-preparation",
]

# Placeholder phrases that indicate the description was never filled in
_PLACEHOLDER_PATTERNS = [
    r"\[add\s+keywords",
    r"\[add\s+.*here\]",
    r"\[describe",
    r"\[placeholder",
    r"\btodo\b",
    r"\bplaceholder\b",
    r"describe\s+this\s+topic",
    r"add\s+your\s+description",
]


def _friendly_filename(name: str) -> str:
    """Convert a Dataverse topic name to the local filename stem (matching extract.py logic)."""
    raw = re.sub(r"^\[.*?\]\s*[-\u2013\u2014]\s*", "", name)
    slug = raw.strip().replace("_", "-")
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug


def _get_disabled_topic_names(runner, agent_name: str) -> set[str]:
    """Query Dataverse for disabled topics and return their local filenames (lowercased)."""
    if not runner or not getattr(runner, 'dv_token', None) or not getattr(runner, 'env_url', None):
        return set()

    # Find botId from config
    import json
    try:
        config = json.load(open("my/config.json"))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

    bot_id = None
    for agent in config.get("agents", []):
        if agent.get("slug") == agent_name:
            bot_id = agent.get("botId")
            break
    if not bot_id:
        return set()

    try:
        from auth import query_all
        # componenttype 9 = Topic/Dialog, statecode 1 = Inactive/Disabled
        components = query_all(
            runner.env_url, runner.dv_token,
            "botcomponents",
            "name,schemaname,statecode",
            filter_expr=f"_parentbotid_value eq '{bot_id}' and componenttype eq 9 and statecode eq 1",
        )
        # Convert Dataverse names to local filenames for matching
        disabled = set()
        for c in components:
            name = c.get("name", "")
            if name:
                disabled.add(_friendly_filename(name))
        return disabled
    except Exception:
        return set()


def _check_topic_descriptions(agent_path: Path, label: str, runner=None, agent_name: str = "") -> list[CheckResult]:
    """CONFIG-014: Check that topic descriptions are specific enough for AI routing."""
    results = []
    topics_dir = agent_path / "topics"

    if not topics_dir.exists():
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.SKIPPED.value,
            description=f"{label}: Topic description quality",
            result="Topics directory not found",
        ))
        return results

    too_short: list[str] = []
    has_placeholder: list[str] = []
    checked = 0

    # Query Dataverse for disabled topics to skip them
    disabled_topics = _get_disabled_topic_names(runner, agent_name)

    for tf in sorted(topics_dir.glob("*.mcs.yml")):
        filename = tf.name.lower()

        # Skip system topics that don't use AI-based routing
        if any(re.search(pat, filename) for pat in _SYSTEM_TOPIC_PATTERNS):
            continue

        # Skip disabled topics (match filename stem against Dataverse-derived names)
        stem = tf.stem.replace(".mcs", "").lower()
        if stem in disabled_topics:
            continue

        content = tf.read_text(encoding="utf-8", errors="replace")

        # Extract modelDescription (multiline block scalar or inline)
        # The pattern allows blank lines within the indented block
        desc_match = re.search(
            r'modelDescription:\s*\|[\-\+]?\s*\n((?:(?:[ \t]+.+|[ \t]*)\n?)+)', content
        )
        if desc_match:
            desc_text = desc_match.group(1).strip()
        else:
            inline_match = re.search(r'modelDescription:\s*(?!\|)(.+)', content)
            if inline_match:
                desc_text = inline_match.group(1).strip()
            else:
                # No modelDescription ??? topic may use triggerQueries only
                continue

        checked += 1

        # Get the display name shown in Copilot Studio
        name_match = re.search(r'modelDisplayName:\s*(.+)', content)
        if name_match:
            display_name = name_match.group(1).strip()
        else:
            # Fall back to filename, formatted as a readable topic name
            display_name = tf.stem.replace(".mcs", "").replace("-", " ").title()
            display_name = f"{display_name} (file: {tf.name})"

        # Check for placeholder text
        if any(re.search(pat, desc_text, re.IGNORECASE) for pat in _PLACEHOLDER_PATTERNS):
            has_placeholder.append(display_name)
            continue

        # Check word count
        word_count = len(desc_text.split())
        if word_count < _MIN_DESCRIPTION_WORDS:
            too_short.append(f"{display_name} ({word_count} words)")

    if not checked:
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.SKIPPED.value,
            description=f"{label}: Topic description quality",
            result="No AI-routed topics with modelDescription found",
        ))
        return results

    # Report placeholder issues (higher severity)
    if has_placeholder:
        topic_list = "; ".join(has_placeholder[:5])
        if len(has_placeholder) > 5:
            topic_list += "..."
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.FAILED.value,
            description=f"{label}: Topic descriptions contain placeholders",
            result=f"{len(has_placeholder)} topic(s) have placeholder text instead of a real description. Topics: {topic_list}",
            remediation="Open these topics in Copilot Studio and replace the placeholder text in the Description field with specific trigger conditions and examples.",
            doc_link=f"{DOC_BASE}/customize#customize-topics",
        ))

    # Report too-short descriptions
    if too_short:
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description=f"{label}: Topic descriptions too short",
            result=f"{len(too_short)} topic(s) under {_MIN_DESCRIPTION_WORDS} words: {', '.join(too_short[:5])}{'...' if len(too_short) > 5 else ''}",
            remediation="Expand descriptions with trigger conditions, valid examples, and exclusion criteria for better routing.",
            doc_link=f"{DOC_BASE}/customize#customize-topics",
        ))

    if not has_placeholder and not too_short:
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description=f"{label}: Topic description quality",
            result=f"All {checked} AI-routed topic(s) have descriptions >= {_MIN_DESCRIPTION_WORDS} words with no placeholders",
            doc_link=f"{DOC_BASE}/customize#customize-topics",
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
