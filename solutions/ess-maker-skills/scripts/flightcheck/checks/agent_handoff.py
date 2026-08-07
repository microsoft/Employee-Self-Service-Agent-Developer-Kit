"""TOPIC-020 — Auto-handoff target-agent id resolved from placeholder.

The ESS agent ships with auto-handoff template topics (see
solutions/ess-maker-skills/src/reference/ess-docs/customization/agent-handoff.md).
Each template topic contains a **SetVariable** node that assigns
``Topic.HandoffAgentId``. Out of the box that node holds a placeholder
string literal the maker must replace with the GPT ID of the real target
agent (agent-handoff.md Step 4 "Set Handoff Agent ID"). The sample
template ships ``"AgentIdentifier"``; the out-of-the-box Handoff
Accelerators ship system-prefixed variants such as
``"ServiceNowAgentIdentifier"`` (observed on live OOTB accelerators). A
blank value is likewise unconfigured.

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

Identifying a handoff topic: a topic IS a handoff topic if, and only if,
it contains a SetVariable node assigning ``Topic.HandoffAgentId``. That
variable is what defines the topic as a handoff. We deliberately do NOT
key on the schemaName: agent-handoff.md tells makers to CLONE and RENAME
the sample template (Step 1) or to enable an out-of-the-box Handoff
Accelerator, so the real enabled topics carry their own schemaNames, not
``Agenthandoff-scenarioname``. Keying on the name would skip exactly the
topics the maker enabled and misconfigured, which is the case #152 exists
to catch.

New pattern: no prior check parses the DialogComponent action tree, so
this module walks ``dialog.beginDialog.actions`` recursively to locate
the SetVariable node. Structure confirmed against the captured cassette's
handoff DialogComponent (schemaName
``...topic.Agenthandoff-scenarioname``).

Inference note: the mapping ``status == "Active"`` meaning "enabled" is
inferred. The validated cassette only captured the disabled template
(``status == "Inactive"``); no cassette yet captures an enabled handoff
topic. The inference is consistent with how other live components report
state, but the enabled shape is unproven pending a captured cassette.
"""

from __future__ import annotations

from ..runner import CheckResult, Priority, Role, Status

DOC_LINK = (
    "https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/"
    "blob/main/solutions/ess-maker-skills/src/reference/ess-docs/"
    "customization/agent-handoff.md"
)

CATEGORY = "Agent Handoff"

# The shipped placeholder value on the SAMPLE template. Stored in the
# SetVariable node as a PowerFx string literal — i.e. the raw expressionText
# is the value plus surrounding quotes:
#   "AgentIdentifier"  ->  expressionText == '"AgentIdentifier"'
# The out-of-the-box Handoff Accelerators (Workday / ServiceNow) ship
# system-prefixed variants of the same placeholder, e.g.
# "ServiceNowAgentIdentifier". Real target ids are prefixed GUIDs (e.g.
# "T_<guid>...", "P_<guid>"), so they never end in "AgentIdentifier".
_PLACEHOLDER = "AgentIdentifier"

# The topic variable the handoff target id is written to. A topic is a
# handoff topic iff it contains a SetVariable assigning this variable.
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


def _resolved_agent_id(setvariable: dict) -> str | None:
    """Extract the assigned handoff agent id when it is a static literal.

    The maker can assign ``Topic.HandoffAgentId`` two different ways:

    - **Static PowerFx string literal** — the value node carries an
      ``expressionText`` that is a quoted string, e.g.
      ``'"AgentIdentifier"'``, ``'"T_<guid>..."'``, or the shipped empty
      literal ``'""'``. This is the only shape the placeholder/blank
      comparison applies to. Returns the unquoted id (``""`` for the empty
      literal ``'""'``).
    - **Variable reference or PowerFx formula** — the value is bound to
      another variable (``variableReference``) or is a non-literal
      expression, with no quoted string literal to read (``expressionText``
      is absent or not a quoted string). The captured cassette shows
      sibling SetVariables using ``variableReference`` (e.g.
      ``System.Activity.Text``) with no ``expressionText``. The kit cannot
      statically resolve what such an expression evaluates to at runtime,
      so there is no literal to compare against the placeholder. Returns
      ``None`` — the caller reports MANUAL rather than a false-positive
      blank/placeholder FAILED.
    """
    value = setvariable.get("value", {}) or {}
    expr = value.get("expressionText")
    if not isinstance(expr, str):
        return None
    expr = expr.strip()
    if len(expr) >= 2 and expr.startswith('"') and expr.endswith('"'):
        return expr[1:-1].strip()
    return None


def _is_placeholder_id(agent_id: str) -> bool:
    """True if the resolved id is a shipped placeholder the maker must
    replace, rather than a concrete target agent id.

    The sample template ships ``AgentIdentifier``; the Handoff Accelerators
    ship system-prefixed variants (e.g. ``ServiceNowAgentIdentifier``,
    observed on live OOTB ServiceNow accelerators). Real target ids are
    prefixed GUIDs (e.g. ``T_<guid>...``, ``P_<guid>``), so a case-insensitive
    ``...AgentIdentifier`` suffix reliably identifies any of these placeholders
    without matching a real id.
    """
    return agent_id.lower().endswith(_PLACEHOLDER.lower())


def run_handoff_topic_checks(runner) -> list[CheckResult]:
    """TOPIC-020: enabled auto-handoff topics must set a concrete target
    agent id, not the shipped ``AgentIdentifier`` placeholder.

    Conditional / gating:
    - Returns ``[]`` if PVA (Island Gateway) is not configured or the bot
      id is unknown — we cannot enumerate topics, mirroring EXT-002.
    - Returns ``[]`` if the agent has no ENABLED (status == "Active")
      handoff topic. A handoff topic is any topic containing a SetVariable
      that assigns ``Topic.HandoffAgentId``. Disabled handoff topics are
      the OOTB state and are intentionally not flagged.
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

    # Keep only ENABLED handoff topics. Identity is the presence of a
    # SetVariable assigning Topic.HandoffAgentId, NOT the schemaName — makers
    # clone/rename the template or enable an accelerator, so the enabled
    # topics do not carry the "Agenthandoff" name (see module docstring).
    handoff_topics: list[tuple[dict, dict]] = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        if comp.get("$kind") != "DialogComponent":
            continue
        if str(comp.get("status", "")).lower() != "active":
            continue
        setvariable = _find_handoff_setvariable(comp.get("dialog", {}))
        if setvariable is None:
            continue
        handoff_topics.append((comp, setvariable))

    if not handoff_topics:
        return []

    results: list[CheckResult] = []

    for i, (topic, setvariable) in enumerate(handoff_topics, start=1):
        cid = f"TOPIC-020-{i:03d}"
        name = (
            topic.get("displayName")
            or topic.get("schemaName")
            or f"Handoff topic {i}"
        )

        agent_id = _resolved_agent_id(setvariable)

        if agent_id is None:
            # Assigned via a variable reference / PowerFx expression, not a
            # static string literal. The value is definitively NOT the shipped
            # placeholder literal, but the kit cannot statically resolve what
            # it evaluates to at runtime, so it cannot confirm a concrete
            # target id either. Report MANUAL (observed programmatically, the
            # final comparison is the operator's) rather than a false-positive
            # blank/placeholder FAILED. MANUAL does not fail readiness.
            results.append(CheckResult(
                roles=[Role.ESS_MAKER.value],
                checkpoint_id=cid,
                category=CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.MANUAL.value,
                description=f"Handoff target agent id: {name}",
                result=(
                    f"Handoff topic '{name}' is enabled and sets "
                    f"{_HANDOFF_VAR} from a Power Fx expression or variable "
                    "reference, not a typed-in string value. It is not the "
                    "shipped placeholder, but the kit cannot statically "
                    "resolve the expression, so it could not confirm the "
                    "resolved target agent id."
                ),
                remediation=(
                    "Confirm the handoff resolves to a valid target agent id. "
                    "In Copilot Studio, open the topic, find the node that "
                    f"sets {_HANDOFF_VAR}, and verify the expression or "
                    "variable it reads from evaluates to the GPT ID of the "
                    "intended target agent (agent-handoff.md Step 4 'Set "
                    "Handoff Agent ID' and 'Locate the GPT ID of an agent'). "
                    "If you did not intend to enable this handoff, disable the "
                    "topic to return it to its default out-of-the-box state."
                ),
                doc_link=DOC_LINK,
            ))
        elif not agent_id or _is_placeholder_id(agent_id):
            if agent_id:
                detail = (
                    f"{_HANDOFF_VAR} still holds the shipped placeholder "
                    f"value '{agent_id}' (no concrete target agent id set)."
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
                    "Either set a valid target agent id or disable the "
                    "handoff. 1) To use this handoff, open the topic in "
                    "Copilot Studio, find the SetVariable node that sets "
                    f"{_HANDOFF_VAR} and replace the placeholder value with "
                    "the GPT ID of the target agent (agent-handoff.md Step 4 "
                    "'Set Handoff Agent ID' and 'Locate the GPT ID of an "
                    "agent'). 2) If you did not intend to enable this handoff, "
                    "disable the topic to return it to its default "
                    "out-of-the-box state."
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
