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
STUDIO_BASE = "https://copilotstudio.microsoft.com"


def _studio_agent_url(runner, agent_name: str) -> str | None:
    """Build a Copilot Studio deep link to a specific agent's overview page.

    Returns None when the BAP environment ID or the agent's botId can't be
    resolved from the runner's parsed config — callers fall back to the
    generic Copilot Studio homepage.

    URL shape verified against a live tenant:
      https://copilotstudio.microsoft.com/environments/{envId}/bots/{botId}/overview
    """
    if not runner or not agent_name:
        return None
    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return None
    config = getattr(runner, "config", None) or {}
    bot_id = None
    for agent in config.get("agents", []):
        if agent.get("slug") == agent_name:
            bot_id = agent.get("botId")
            break
    if not bot_id:
        # Fall back to the single-agent shape used by older configs.
        bot_id = (config.get("agent") or {}).get("botId")
    if not bot_id:
        return None
    return f"{STUDIO_BASE}/environments/{env_id}/bots/{bot_id}/overview"


def _studio_link_md(runner, agent_name: str, anchor: str = "Copilot Studio") -> str:
    """Markdown link to the specific agent in Copilot Studio, or to the
    homepage when the deep link can't be resolved."""
    url = _studio_agent_url(runner, agent_name) or f"{STUDIO_BASE}/"
    return f"[{anchor}]({url})"

# Required topics that ESS agents should have. The `pattern` is a regex
# matched against the **normalized** filename stem (lowercase + all
# non-alphanumerics stripped) of every file under topics/. Normalization
# is required because filenames are slugged with hyphens
# (response-preparation.mcs.yml) but the patterns are written without
# separators so a single pattern matches every hyphenation choice
# Copilot Studio / extract.py might emit.
REQUIRED_TOPICS = [
    {"id": "TOPIC-001", "pattern": "usercontext", "name": "[Admin] User Context - Setup", "priority": "Critical"},
    {"id": "TOPIC-002", "pattern": "responsepreparation", "name": "[System] Response Preparation", "priority": "Critical"},
    {"id": "TOPIC-004", "pattern": "sensitivetopic", "name": "[Example] Sensitive Topics", "priority": "High"},
    {"id": "TOPIC-005", "pattern": "onerror", "name": "[System] On Error", "priority": "High"},
    {"id": "TOPIC-009", "pattern": "emotionalintelligence|emotionalquotient", "name": "Emotional Intelligence", "priority": "High"},
    # The ESS template ships this as ``seek-clarification-to-avoid-ambiguous-answers``;
    # normalized that becomes ``seekclarificationtoavoidambiguousanswers``. Pattern
    # ``ambigu|clarif`` matches both "ambiguous" and "clarification" so the check
    # passes whether the user adapts the topic name toward either concept.
    {"id": "TOPIC-010", "pattern": "ambigu|clarif", "name": "Ambiguity Clarification", "priority": "High"},
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
    results.extend(_check_agent_identity(agent_path, label, runner, agent_name))

    # ---- Required topics ----
    results.extend(_check_required_topics(agent_path, label, runner, agent_name))

    # ---- Topic count ----
    results.extend(_check_topic_inventory(agent_path, label))

    # ---- Variables ----
    results.extend(_check_variables(agent_path, label))

    # ---- Topic description quality ----
    results.extend(_check_topic_descriptions(agent_path, label, runner, agent_name))

    # ---- Template configs ----
    results.extend(_check_template_configs(agent_path, label))

    # ---- Knowledge source readiness ----
    results.extend(_check_knowledge_sources(agent_path, label, runner, agent_name))

    return results


def _check_agent_identity(agent_path: Path, label: str, runner=None, agent_name: str = "") -> list[CheckResult]:
    """Check agent.mcs.yml for instructions, name, starter prompts."""
    results = []
    agent_file = agent_path / "agent.mcs.yml"
    studio_link = _studio_link_md(runner, agent_name, "the agent in Copilot Studio")

    if not agent_file.exists():
        results.append(CheckResult(
            checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description=f"{label}: Agent identity file",
            result="agent.mcs.yml not found",
            remediation=f"Verify {studio_link} exists and you can open it, then re-run `/setup` to extract agent files.",
        ))
        return results

    content = agent_file.read_text(encoding="utf-8")

    # Parse the YAML once and operate on the parsed dict. The earlier
    # regex approach (``instructions:\s*[|>]?\s*\n…``) silently missed
    # YAML's chomping-indicator block scalars (``|-``, ``|+``, ``>-``,
    # ``>+``) — which Copilot Studio routinely emits — and reported
    # the agent as having no instructions at all. yaml.safe_load
    # handles every block-scalar variant correctly and matches the
    # parsing pattern already used by run_local_file_checks at line
    # ~451 for topic files.
    parsed: dict | None = None
    try:
        loaded = yaml.safe_load(content)
        if isinstance(loaded, dict):
            parsed = loaded
    except yaml.YAMLError:
        parsed = None

    if parsed is None:
        results.append(CheckResult(
            checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description=f"{label}: Agent instructions",
            result="agent.mcs.yml could not be parsed as YAML",
            remediation=f"Re-extract the agent with `/setup`. If the problem persists, inspect {studio_link} and check for unsupported customizations.",
            doc_link=f"{DOC_BASE}/customize",
        ))
        return results

    instructions_value = parsed.get("instructions")
    instruction_text = instructions_value.strip() if isinstance(instructions_value, str) else ""
    if instruction_text:
        word_count = len(instruction_text.split())
        if word_count >= 50:
            results.append(CheckResult(
                checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description=f"{label}: Agent instructions",
                result=f"Instructions present ({word_count} words)",
                remediation=f"Validated: the agent identity file contains a non-empty instructions field ({word_count} words, above the minimum threshold).",
                doc_link=f"{DOC_BASE}/customize",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description=f"{label}: Agent instructions",
                result=f"Instructions seem short ({word_count} words)",
                remediation=f"Open {studio_link} and expand the agent instructions for better responses, then re-run `/setup`.",
                doc_link=f"{DOC_BASE}/customize",
            ))
    else:
        results.append(CheckResult(
            checkpoint_id="CONFIG-007", category=f"Configuration ({label})",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description=f"{label}: Agent instructions",
            result="No instructions block found in agent.mcs.yml",
            remediation=f"Open {studio_link} and add agent instructions on the Overview tab, then re-run `/setup`.",
            doc_link=f"{DOC_BASE}/customize",
        ))

    # Starter prompts. Real Copilot Studio agent.mcs.yml uses the
    # ``conversationStarters`` key whose value is a list of dicts with
    # ``title`` + ``text`` fields. Parsing the YAML lets us count
    # accurately regardless of indentation or quoting choices that
    # tripped up the previous regex-based heuristic.
    starters = parsed.get("conversationStarters") or parsed.get("conversationStarter") or []
    if not isinstance(starters, list):
        starters = []
    count = sum(1 for item in starters if isinstance(item, dict) and item.get("text"))
    if count >= 3:
        results.append(CheckResult(
            checkpoint_id="CONFIG-005", category=f"Configuration ({label})",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=f"{label}: Starter prompts",
            result=f"{count} starter prompt(s) found",
            remediation=f"Validated: {count} conversation starter prompt(s) are defined in the local agent identity file.",
            doc_link=f"{DOC_BASE}/customize#customize-starter-prompts",
        ))
    elif count > 0:
        results.append(CheckResult(
            checkpoint_id="CONFIG-005", category=f"Configuration ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Starter prompts",
            result=f"Only {count} starter prompt(s) -- recommend 6-12",
            remediation=f"Open {studio_link} and add more starter prompts on the Overview tab, then re-run `/setup`.",
            doc_link=f"{DOC_BASE}/customize#customize-starter-prompts",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="CONFIG-005", category=f"Configuration ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Starter prompts",
            result="No starter prompts detected",
            remediation=f"Open {studio_link} and add starter prompts on the Overview tab, then re-run `/setup`.",
            doc_link=f"{DOC_BASE}/customize#customize-starter-prompts",
        ))

    return results


def _check_required_topics(agent_path: Path, label: str, runner=None, agent_name: str = "") -> list[CheckResult]:
    """Check that required system/admin topics exist."""
    results = []
    topics_dir = agent_path / "topics"
    studio_link = _studio_link_md(runner, agent_name, "Copilot Studio")

    if not topics_dir.exists():
        for req in REQUIRED_TOPICS:
            results.append(CheckResult(
                checkpoint_id=req["id"], category=f"Topics ({label})",
                priority=req["priority"], status=Status.SKIPPED.value,
                description=f"{label}: {req['name']}",
                result="Topics directory not found",
            ))
        return results

    # Normalize each filename stem the same way pattern-authors expect:
    # lowercase + drop every non-alphanumeric character. This collapses
    # ``response-preparation.mcs.yml`` to ``responsepreparation`` so a
    # single pattern like ``responsepreparation`` matches regardless of
    # whether extract.py emitted hyphens, underscores, or a different
    # casing. Pre-fix the matcher compared the raw hyphenated filename
    # against the no-separator pattern and missed every system topic.
    #
    # We deliberately do NOT scan the topic's YAML body anymore: system
    # topics like response-preparation.mcs.yml don't carry their schema
    # name in the body at all (just ``kind: AdaptiveDialog`` + actions),
    # and a body scan is a false-positive trap — any topic mentioning
    # "on error" anywhere in its dialog text would satisfy TOPIC-005.
    # Filename is the authoritative slug derived from the Dataverse
    # botcomponents.name by extract.py.
    normalized_stems = []
    for tf in topics_dir.glob("*.mcs.yml"):
        stem = tf.name.lower().replace(".mcs.yml", "")
        normalized_stems.append(re.sub(r"[^a-z0-9]", "", stem))

    for req in REQUIRED_TOPICS:
        pattern = req["pattern"]
        found = any(re.search(pattern, stem) for stem in normalized_stems)

        if found:
            results.append(CheckResult(
                checkpoint_id=req["id"], category=f"Topics ({label})",
                priority=req["priority"], status=Status.PASSED.value,
                description=f"{label}: {req['name']}",
                result="Topic found",
                remediation=f"Validated: the required topic '{req['name']}' is present in the agent's local topics/ folder.",
                doc_link=f"{DOC_BASE}/customize#customize-topics",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id=req["id"], category=f"Topics ({label})",
                priority=req["priority"], status=Status.WARNING.value,
                description=f"{label}: {req['name']}",
                result="Required topic not found in extracted files",
                remediation=f"Verify '{req['name']}' exists in {studio_link} \u2192 Topics.",
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
        remediation="ESS agents typically have 20+ topics." if count < 5 else f"Validated: the agent has {count} local topic file(s), at least the minimum of 5 expected.",
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
        remediation="Create User Context variables for employee data." if not var_files else f"Validated: {len(var_files)} local variable definition file(s) (User Context variables) are present in the agent's variables/ folder.",
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


_XML_ATTR_KEY_RE = re.compile(r"^(\s+)([@#][A-Za-z_][\w.-]*)(\s*:(?:\s|$))", re.MULTILINE)


def _salvage_xml_attribute_yaml(content: str) -> str:
    """Quote bare ``@key:`` / ``#key:`` keys so PyYAML can parse the document.

    Copilot Studio's topic export embeds connector-action response schemas
    derived from XML/XSD definitions (e.g. Workday SOAP actions). It emits
    XML attribute markers (``@type``) and text-node markers (``#text``) as
    unquoted YAML keys, even though ``@`` and ``#`` are reserved indicators
    in YAML 1.2 that must be quoted. Copilot Studio's own parser accepts
    them; PyYAML correctly does not.

    The maker can't fix this — it's not their YAML — and editing the file
    locally would be overwritten on the next ``/scan``. Quote them in a
    salvaged copy so CONFIG-014 can still inspect ``modelDescription`` for
    these topics. The on-disk file is never mutated.

    Only keys that begin with ``@`` or ``#`` at the start of a mapping line
    are rewritten; any other YAML construct is left exactly as the parser
    saw it, so a genuinely-broken file still raises.
    """
    return _XML_ATTR_KEY_RE.sub(r'\1"\2"\3', content)


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
    # Files we couldn't parse even after salvaging Copilot Studio's
    # XML-attribute-style keys. These are the only ones worth surfacing —
    # the salvaged-and-parsed case is silent because the salvage is a
    # workaround for a known upstream quirk, not maker-actionable.
    unparseable: list[str] = []
    checked = 0

    # Query Dataverse for disabled topics to skip them
    disabled_topics = _get_disabled_topic_names(runner, agent_name)
    studio_link = _studio_link_md(runner, agent_name, "the agent in Copilot Studio")

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
        #
        # Two-pass parse: on YAMLError, try once more after quoting the
        # XML-attribute keys Copilot Studio emits unquoted for
        # connector-action schemas (see _salvage_xml_attribute_yaml).
        # The salvage is silent on success — it's a workaround for a known
        # upstream quirk, not something a maker can act on. If the second
        # pass still fails the file goes on ``unparseable`` and we surface
        # it as a low-priority Skipped row.
        try:
            doc = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            salvaged = _salvage_xml_attribute_yaml(content)
            if salvaged != content:
                try:
                    doc = yaml.safe_load(salvaged) or {}
                except yaml.YAMLError:
                    unparseable.append(tf.name)
                    continue
            else:
                unparseable.append(tf.name)
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

    # If a file couldn't be parsed even after quoting Copilot Studio's
    # XML-attribute-style keys, surface a single low-noise Skipped row so
    # there's an audit trail. We deliberately do NOT recommend "fix the
    # YAML" — in practice the file came verbatim from Copilot Studio's
    # exporter and is overwritten on the next ``/scan``.
    if unparseable:
        names = ", ".join(unparseable[:10])
        overflow = f" (+{len(unparseable) - 10} more)" if len(unparseable) > 10 else ""
        studio_link_for_unparseable = _studio_link_md(runner, agent_name, "the agent in Copilot Studio")
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.LOW.value, status=Status.SKIPPED.value,
            description=f"{label}: Topic description quality (unparseable files skipped)",
            result=(
                f"{len(unparseable)} topic file(s) could not be parsed as YAML and were "
                f"skipped for description-quality checks: {names}{overflow}"
            ),
            remediation=(
                f"These files were written verbatim by Copilot Studio's exporter. "
                f"Open each topic in {studio_link_for_unparseable} \u2192 Topics and confirm "
                "it loads in the Code editor without errors. If it does, no action is needed; "
                "if it doesn't, edit the topic in the Code editor and save \u2014 then re-run `/scan`."
            ),
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
            remediation=f"Open {studio_link} \u2192 Topics and replace the placeholder text in each topic's Description field with specific trigger conditions and examples.",
            doc_link=f"{DOC_BASE}/customize#customize-topics",
        ))

    # Report too-short descriptions
    if too_short:
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description=f"{label}: Topic descriptions too short",
            result=f"{len(too_short)} topic(s) under {_MIN_DESCRIPTION_WORDS} words: {', '.join(too_short[:5])}{'...' if len(too_short) > 5 else ''}",
            remediation=f"Open {studio_link} \u2192 Topics and expand each topic's description with trigger conditions, valid examples, and exclusion criteria for better routing.",
            doc_link=f"{DOC_BASE}/customize#customize-topics",
        ))

    if not has_placeholder and not too_short:
        results.append(CheckResult(
            checkpoint_id="CONFIG-014", category=f"Topics ({label})",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description=f"{label}: Topic description quality",
            result=f"All {checked} AI-routed topic(s) have descriptions >= {_MIN_DESCRIPTION_WORDS} words with no placeholders",
            remediation=f"Validated: every AI-routed topic ({checked} checked) has a modelDescription of at least {_MIN_DESCRIPTION_WORDS} words with no placeholder text.",
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
        remediation=f"Validated: the agent's local template-config folder contains {len(xml_files)} XML template(s) and {len(meta_files)} metadata file(s).",
    ))

    return results


# Knowledge source crawl readiness statuses (the `status` field on the API response).
# These represent the indexing lifecycle, distinct from the lifecycle `state` field.
_READY_STATUSES = {"completed", "indexed", "ready", "succeeded"}
# Statuses that indicate the source is not yet ready for deployment.
_NOT_READY_STATUSES = {"pending", "crawling", "queued", "provisioning", "failed", "error"}


def _check_knowledge_sources(agent_path: Path, label: str, runner=None, agent_name: str = "") -> list[CheckResult]:
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
            result="No knowledge directory found \u2014 no sources configured",
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
            result="Cannot verify \u2014 Copilot Studio API authentication required",
        ))
        return results

    return _check_knowledge_sources_via_gateway(pva, bot_id, knowledge_files, label, runner, agent_name)


def _check_knowledge_sources_via_gateway(pva, bot_id: str, knowledge_files: list, label: str, runner=None, agent_name: str = "") -> list[CheckResult]:
    """Check knowledge source status using the Island Gateway API.

    Note on local-to-remote matching: the local filename is derived from the
    Dataverse `botcomponents.name` field, while the Island Gateway returns
    `displayName` (which for SharePoint sources is the site URL, not a stable
    identifier). There is no reliable join key to match individual files to
    components, so we use a count comparison plus per-remote status check.
    """
    results = []
    studio_link = _studio_link_md(runner, agent_name, "the agent in Copilot Studio")
    knowledge_path_hint = f"workspace/agents/{agent_name}/knowledge/" if agent_name else "workspace/agents/{slug}/knowledge/"

    try:
        sources = pva.get_knowledge_sources(bot_id)
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=f"{label}: Knowledge source crawl status",
            result=f"Could not query Copilot Studio API: {e}",
            remediation=f"Check authentication and retry. Verify status manually under {studio_link} \u2192 Knowledge.",
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
                f"Publish {studio_link} to provision missing sources, "
                "or remove the local file if it should not exist. Identify mismatched "
                f"sources by comparing filenames in {knowledge_path_hint} against the "
                f"Knowledge tab in {studio_link}."
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
                result=f"Status: {crawl_status} \u2014 indexed and ready",
                remediation=f"Validated: knowledge source '{name}' ({source_type}) reports an indexed/ready crawl status ('{crawl_status}').",
            ))
        elif crawl_status in _NOT_READY_STATUSES:
            all_ready = False
            results.append(CheckResult(
                checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description=f"{label}: '{name}' ({source_type})",
                result=f"Status: {crawl_status} \u2014 not ready for deployment",
                remediation=(
                    f"Knowledge source '{name}' has not completed indexing. "
                    f"Wait for the crawl to finish, or check for errors under "
                    f"{studio_link} \u2192 Knowledge."
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
                    f"Verify under {studio_link} \u2192 Knowledge whether the source has "
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
                    f"Verify under {studio_link} \u2192 Knowledge whether the source has "
                    "finished indexing before deploying."
                ),
            ))

    if all_ready and sources and len(knowledge_files) <= len(sources):
        results.append(CheckResult(
            checkpoint_id="CONFIG-013", category=f"Knowledge Sources ({label})",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=f"{label}: All knowledge sources indexed",
            result=f"{len(sources)} knowledge source(s) fully indexed and ready",
            remediation=f"Validated: all {len(sources)} knowledge source(s) report a fully indexed/ready crawl status.",
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
