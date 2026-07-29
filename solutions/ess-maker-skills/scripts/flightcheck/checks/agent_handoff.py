"""TOPIC-020 — Auto-handoff target-agent id resolved from placeholder.

The ESS agent ships with auto-handoff template topics (see
solutions/ess-maker-skills/src/reference/ess-docs/customization/agent-handoff.md).
Each template topic contains a **SetVariable** node that assigns
``Topic.HandoffAgentId``. Out of the box that node holds the placeholder
string literal ``"AgentIdentifier"``; the maker must replace it with the
GPT ID of the real target agent (agent-handoff.md Step 4 "Set Handoff
Agent ID").

By default every handoff template topic is **disabled** (agent-handoff.md
line 63). So this check is conditional: it only validates handoff topics
that the maker has ENABLED (``status == "Active"``). An enabled handoff
topic still carrying the shipped placeholder means the handoff will fail
at runtime — the agent is configured to hand off but has no valid target.

Data source: the DialogComponent (topic) definitions returned by the
Island Gateway botcomponents API, enumerated via
``PVAClient.get_dialog_components`` (same endpoint/tier as the
Graph-Connector knowledge-source check). Mock tier: validated —
tests/fixtures/cassettes/island_gateway_botcomponents.yaml.

New pattern: no prior check parses the DialogComponent action tree, so
this module walks ``dialog.beginDialog.actions`` recursively to locate
the SetVariable node. Structure confirmed against the captured cassette's
handoff DialogComponent (schemaName
``...topic.Agenthandoff-scenarioname``).
"""

from __future__ import annotations

from ..runner import CheckResult, Priority, Role, Status

DOC_LINK = (
    "https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/"
    "blob/main/solutions/ess-maker-skills/src/reference/ess-docs/"
    "customization/agent-handoff.md"
)

CATEGORY = "Agent Handoff"

# The shipped placeholder value the maker is expected to replace. Stored
# in the SetVariable node as a PowerFx string literal — i.e. the raw
# expressionText is the six characters plus surrounding quotes:
#   "AgentIdentifier"  ->  expressionText == '"AgentIdentifier"'
_PLACEHOLDER = "AgentIdentifier"

# Case-insensitive substring identifying a handoff auto-template topic by
# its schemaName (e.g. "...topic.Agenthandoff-scenarioname").
_HANDOFF_MARKER = "agenthandoff"

# The topic variable the handoff target id is written to.
_HANDOFF_VAR = "Topic.HandoffAgentId"


def _find_handoff_setvariable(node) -> dict | None:
    """Recursively search a DialogComponent action tree for the
    SetVariable node that assigns ``Topic.HandoffAgentId``.

    Handles both dict nodes and list containers (an action tree is a list
    of action dicts, some of which nest further action lists). Returns the
    matching SetVariable dict, or ``None`` if not present.
    """
    if isinstance(node, dict):
        if node.get("$kind") == "SetVariable" and node.get("variable") == _HANDOFF_VAR:
            return node
        for value in node.values():
            found = _find_handoff_setvariable(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_handoff_setvariable(item)
            if found is not None:
                return found
    return None


def _resolved_agent_id(setvariable: dict) -> str:
    """Extract and normalize the assigned handoff agent id.

    The value is a PowerFx ValueExpression whose ``expressionText`` is a
    quoted string literal. Strip the surrounding PowerFx quotes so the
    caller can compare the concrete id against the placeholder.
    """
    value = setvariable.get("value", {})
    expr = value.get("expressionText", "")
    return expr.strip().strip('"').strip()


def run_handoff_topic_checks(runner) -> list[CheckResult]:
    """TOPIC-020: enabled auto-handoff topics must set a concrete target
    agent id, not the shipped ``AgentIdentifier`` placeholder.

    Conditional / gating:
    - Returns ``[]`` if PVA (Island Gateway) is not configured or the bot
      id is unknown — we cannot enumerate topics, mirroring EXT-002.
    - Returns ``[]`` if the agent has no handoff template topic that is
      ENABLED (status == "Active"). Disabled handoff topics are the OOTB
      state and are intentionally not flagged.
    """
    pva = getattr(runner, "pva", None)
    config = getattr(runner, "config", {}) or {}
    bot_id = config.get("agent", {}).get("botId")

    if not pva or not getattr(pva, "is_configured", False) or not bot_id:
        return []

    try:
        components = pva.get_dialog_components(bot_id)
    except Exception:
        # CONFIG-013 already surfaces PVA connectivity errors; don't double-warn.
        return []

    # Keep only ENABLED handoff auto-template topics.
    handoff_topics = [
        comp
        for comp in components
        if isinstance(comp, dict)
        and _HANDOFF_MARKER in str(comp.get("schemaName", "")).lower()
        and str(comp.get("status", "")).lower() == "active"
    ]

    if not handoff_topics:
        return []

    results: list[CheckResult] = []

    for i, topic in enumerate(handoff_topics, start=1):
        cid = f"TOPIC-020-{i:03d}"
        name = (
            topic.get("displayName")
            or topic.get("schemaName")
            or f"Handoff topic {i}"
        )

        setvariable = _find_handoff_setvariable(topic.get("dialog", {}))

        if setvariable is None:
            results.append(CheckResult(
                roles=[Role.ESS_MAKER.value],
                checkpoint_id=cid,
                category=CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=f"Handoff target agent id: {name}",
                result=(
                    "Enabled handoff topic has no SetVariable node assigning "
                    f"{_HANDOFF_VAR}; unable to verify the target agent id."
                ),
                remediation=(
                    "Open the topic in Copilot Studio and confirm it still "
                    "contains the SetVariable node that sets "
                    f"{_HANDOFF_VAR}. See agent-handoff.md Step 4."
                ),
                doc_link=DOC_LINK,
            ))
            continue

        agent_id = _resolved_agent_id(setvariable)

        if not agent_id or agent_id == _PLACEHOLDER:
            if agent_id == _PLACEHOLDER:
                detail = (
                    f"{_HANDOFF_VAR} still holds the shipped placeholder "
                    f"'{_PLACEHOLDER}' (no concrete target agent id set)."
                )
            else:
                detail = (
                    f"{_HANDOFF_VAR} is blank (no target agent id set)."
                )
            results.append(CheckResult(
                roles=[Role.ESS_MAKER.value],
                checkpoint_id=cid,
                category=CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.FAILED.value,
                description=f"Handoff target agent id: {name}",
                result=(
                    f"Handoff topic '{name}' is enabled but {detail} "
                    "The handoff will fail at runtime."
                ),
                remediation=(
                    "In the topic's flow, find the SetVariable node that "
                    f"sets {_HANDOFF_VAR} and replace the placeholder "
                    f"'{_PLACEHOLDER}' with the GPT ID of the target agent. "
                    "See agent-handoff.md Step 4 'Set Handoff Agent ID' and "
                    "'Locate the GPT ID of an agent'."
                ),
                doc_link=DOC_LINK,
            ))
        else:
            results.append(CheckResult(
                roles=[Role.ESS_MAKER.value],
                checkpoint_id=cid,
                category=CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description=f"Handoff target agent id: {name}",
                result=(
                    f"Handoff topic '{name}' is enabled and "
                    f"{_HANDOFF_VAR} is set to a concrete target agent id."
                ),
                remediation="",
                doc_link=DOC_LINK,
            ))

    return results
