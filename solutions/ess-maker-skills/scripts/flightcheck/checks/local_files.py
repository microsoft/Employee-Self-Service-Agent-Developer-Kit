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

import yaml

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


# Minimum word count for a useful topic description
_MIN_DESCRIPTION_WORDS = 20

# System topics that don't use AI-based routing (no description needed).
# Match against the exact filename stem (without ".mcs.yml") so we don't
# accidentally skip topics whose filename merely contains one of these words
# (e.g. "handle-checkout-error.mcs.yml" must not match "on-error").
# Both `log-telemetry` and `log-telemetry-event` are included since different
# ESS template versions use either name.
_SYSTEM_TOPIC_STEMS = {
    "conversation-start",
    "on-error",
    "reset-conversation",
    "log-telemetry",
    "log-telemetry-event",
    "microsoft-self-help",
    "response-preparation",
}

# Placeholder patterns are split into two groups because the matching loops
# below use different case-sensitivity rules:
#
# _PLACEHOLDER_PATTERNS_INSENSITIVE: bracketed/markup forms and full phrases
#   that are unambiguous markers regardless of how they're cased.
# _PLACEHOLDER_PATTERNS_SENSITIVE: all-caps marker forms that authors actually
#   leave behind (TODO:, TBD, PLACEHOLDER). These MUST stay case-sensitive —
#   matching them under re.IGNORECASE would false-flag legitimate sentences
#   like "this topic acts as a placeholder until ..." or "today's todo list".
_PLACEHOLDER_PATTERNS_INSENSITIVE = [
    r"\[add\s+keywords",
    r"\[add\s+.*here\]",
    r"\[describe",
    r"\[placeholder",
    r"<placeholder>",
    r"describe\s+this\s+topic",
    r"add\s+your\s+description",
]
_PLACEHOLDER_PATTERNS_SENSITIVE = [
    r"\bTODO:",
    r"\[TODO\]",
    r"\bTBD\b",
    r"\bPLACEHOLDER\b",
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

    # Find botId from config. Prefer the already-parsed runner.config attached
    # by cli.py — re-reading from disk hardcodes the config path and breaks
    # whenever the kit's layout changes (regression after the folder reorg
    # moved my/config.json to .local/config.json).
    config = getattr(runner, "config", None) or {}
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
    parse_errors: list[str] = []
    checked = 0

    # Query Dataverse for disabled topics to skip them
    disabled_topics = _get_disabled_topic_names(runner, agent_name)

    for tf in sorted(topics_dir.glob("*.mcs.yml")):
        # Match the exact filename stem against the system-topic set — a
        # substring/regex match would skip legitimate topics whose names
        # merely contain one of these words.
        stem = tf.name.replace(".mcs.yml", "")
        if stem in _SYSTEM_TOPIC_STEMS:
            continue

        # Skip disabled topics (match filename stem against Dataverse-derived names)
        if stem.lower() in disabled_topics:
            continue

        content = tf.read_text(encoding="utf-8", errors="replace")

        # Parse the YAML rather than regex-matching the modelDescription
        # key: that way we correctly handle every valid scalar form
        # (literal `|`, folded `>`, single/double-quoted, plain) and any
        # trailing-comment / odd-indentation cases the regex would miss.
        try:
            doc = yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            parse_errors.append(f"{stem} ({e.__class__.__name__})")
            continue

        if not isinstance(doc, dict):
            # Topic file isn't a YAML mapping — nothing to check.
            continue

        desc_raw = doc.get("modelDescription")
        if desc_raw is None or not str(desc_raw).strip():
            # No modelDescription — topic may use triggerQueries only.
            continue

        desc_text = str(desc_raw).strip()
        checked += 1

        # Get the display name shown in Copilot Studio
        display_name_raw = doc.get("modelDisplayName")
        if display_name_raw and str(display_name_raw).strip():
            display_name = str(display_name_raw).strip()
        else:
            # Fall back to filename, formatted as a readable topic name
            readable = stem.replace("-", " ").title()
            display_name = f"{readable} (file: {tf.name})"

        # Check for placeholder text. Two passes because the marker patterns
        # (TODO:, TBD, PLACEHOLDER) MUST stay case-sensitive — matching them
        # under IGNORECASE would re-introduce the false-flag bug from round 1.
        is_placeholder = (
            any(re.search(pat, desc_text, re.IGNORECASE) for pat in _PLACEHOLDER_PATTERNS_INSENSITIVE)
            or any(re.search(pat, desc_text) for pat in _PLACEHOLDER_PATTERNS_SENSITIVE)
        )
        if is_placeholder:
            has_placeholder.append(display_name)
            continue

        # Check word count
        word_count = len(desc_text.split())
        if word_count < _MIN_DESCRIPTION_WORDS:
            too_short.append(f"{display_name} ({word_count} words)")

    # Report YAML parse errors so they don't silently skip checks
    if parse_errors:
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description=f"{label}: Topic YAML parse errors",
            result=f"{len(parse_errors)} topic file(s) failed to parse: {', '.join(parse_errors[:5])}{'...' if len(parse_errors) > 5 else ''}",
            remediation="Open the listed files and fix the YAML syntax errors so they can be validated.",
        ))

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


# Knowledge source crawl readiness statuses (the `status` field on the API response).
# These represent the indexing lifecycle, distinct from the lifecycle `state` field.
_READY_STATUSES = {"completed", "indexed", "ready", "succeeded"}
# Statuses that indicate the source is not yet ready for deployment.
_NOT_READY_STATUSES = {"pending", "crawling", "queued", "provisioning", "failed", "error"}


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

    if not pva or not pva.is_configured or not bot_id:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=f"{label}: Knowledge source readiness",
            result="Cannot verify — Copilot Studio API authentication required",
        ))
        return results

    return _check_knowledge_sources_via_gateway(pva, bot_id, knowledge_files, label)


def _check_knowledge_sources_via_gateway(pva, bot_id: str, knowledge_files: list, label: str) -> list[CheckResult]:
    """Check knowledge source status using the Island Gateway API.

    Note on local-to-remote matching: the local filename is derived from the
    Dataverse `botcomponents.name` field, while the Island Gateway returns
    `displayName` (which for SharePoint sources is the site URL, not a stable
    identifier). There is no reliable join key to match individual files to
    components, so we use a count comparison plus per-remote status check.
    """
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

    # Count comparison: warn if local files outnumber remote components.
    # This catches the case where a local source was never published (false PASSED
    # in the previous implementation when local>0 and remote=0 only).
    if len(knowledge_files) > len(sources):
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Local/remote knowledge source count mismatch",
            result=(
                f"{len(knowledge_files)} local knowledge file(s) but only {len(sources)} "
                "component(s) returned from Copilot Studio. Some sources may not be published."
            ),
            remediation=(
                "Publish the agent in Copilot Studio to provision missing sources, "
                "or remove the local file if it should not exist. Identify mismatched "
                "sources by comparing filenames in workspace/agents/{slug}/knowledge/ against "
                "Copilot Studio → Knowledge."
            ),
        ))

    if not sources:
        # No remote sources at all — nothing more to check beyond the count warning above.
        return results

    all_ready = True
    for source in sources:
        name = source.get("displayName", "Unknown")
        # `status` is the crawl/index readiness signal we want.
        # `state` is lifecycle (Active/Inactive/Provisioning/etc.) and does NOT
        # tell us whether indexing finished. Falling back to `state` here would
        # be a false-pass: an Active-but-still-crawling source could be PASSED.
        crawl_status = (source.get("status") or "").strip().lower()
        lifecycle_state = (source.get("state") or "").strip().lower()
        source_kind = ""
        config = source.get("configuration", {})
        if config:
            src = config.get("source", {})
            source_kind = src.get("$kind", "")

        # Determine source type for display
        source_type = _format_source_type(source_kind)

        if crawl_status in _READY_STATUSES:
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Status: {crawl_status} — indexed and ready",
            ))
        elif crawl_status in _NOT_READY_STATUSES:
            all_ready = False
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Status: {crawl_status} — not ready for deployment",
                remediation=(
                    f"Knowledge source '{name}' has not completed indexing. "
                    "Wait for the crawl to finish, or check for errors in "
                    "Copilot Studio → Knowledge."
                ),
            ))
        elif crawl_status:
            # Unknown status string, but the API DID return a status field.
            # WARNING with the raw value so we learn the new status over time.
            all_ready = False
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Unknown crawl status: {crawl_status}",
                remediation=(
                    "Verify in Copilot Studio → Knowledge whether the source has "
                    "finished indexing. File an issue so this status string can be "
                    "added to the readiness allowlist."
                ),
            ))
        else:
            # No `status` returned at all — we only have lifecycle `state`.
            # That is NOT proof of indexing; surface as WARNING, not PASSED.
            all_ready = False
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description=f"{label}: '{name}' ({source_type})",
                result=(
                    f"Crawl readiness unknown (lifecycle state={lifecycle_state or 'unknown'}). "
                    "API did not return a `status` field for this source."
                ),
                remediation=(
                    "Verify in Copilot Studio → Knowledge whether the source has "
                    "finished indexing before deploying."
                ),
            ))

    if all_ready and sources and len(knowledge_files) <= len(sources):
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
