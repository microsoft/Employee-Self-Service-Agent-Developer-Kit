"""Constructs the Declarative Agent does not support.

Some Custom Engine Agent building blocks have no Declarative Agent equivalent. A
topic that uses one cannot simply be carried across: it would import but never
behave correctly. The mitigation is *disable but preserve* — the component is
carried with its logic intact and marked ``Inactive`` with a ``[DEPRECATED]``
title, so the customer keeps their work, can read it, and can rebuild it on
supported primitives. Nothing is deleted and no topic ``data`` is rewritten.

Two flavours:

* **Unsupported trigger** — the topic's ``beginDialog.kind``. The whole topic is
  unreachable, so the topic is disabled.
* **Unsupported node** — any action anywhere in the topic. The topic would run but
  fail at that node, so the topic is disabled.

Every entry also records an :class:`Owner` — whether the tool handled it, the Maker
must rebuild it, or it simply cannot be preserved — and, where one exists, the ADK
command that does the rebuilding. That is what turns a list of limitations into a
worklist, and it is what separates a migration that needs work from one that is
genuinely blocked.

.. warning::
   This catalog was compiled against the Declarative Agent *preview*. Some entries
   may since have gained support. Re-validate it whenever ESS picks up a new
   template version, and delete entries that are no longer restrictions — a stale
   entry needlessly disables a working topic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DEPRECATED_MARKER = "[DEPRECATED]"


class Owner(StrEnum):
    """Who has to act, per R2: the system, the Maker, or nobody — it is simply lost.

    The report groups gaps by this so a Maker can tell at a glance what the tool
    already handled from what is now their worklist, and from what no amount of
    work will bring back.
    """

    SYSTEM = "system"
    """Carried or reconfigured automatically; the Maker only needs to verify it."""

    MAKER = "maker"
    """The Maker must rebuild this on supported primitives before publishing."""

    PLATFORM = "platform"
    """No route today — the scenario waits on a capability that has not shipped yet."""


_OWNER_LABEL = {
    Owner.SYSTEM: "Handled for you — verify",
    Owner.MAKER: "You need to rebuild this",
    Owner.PLATFORM: "Not supported yet — no workaround",
}


def owner_label(owner: Owner) -> str:
    return _OWNER_LABEL[owner]


@dataclass(frozen=True)
class UnsupportedConstruct:
    kind: str
    is_trigger: bool
    guidance: str
    owner: Owner = Owner.MAKER
    adk: str = ""
    """The ADK command that helps rebuild this, if one does."""

    @property
    def reason(self) -> str:
        what = "trigger" if self.is_trigger else "node"
        return f"uses the unsupported '{self.kind}' {what}"

    @property
    def advice(self) -> str:
        """Guidance, ownership and the ADK route, as one line for the report."""
        parts = [f"**{_OWNER_LABEL[self.owner]}.** {self.guidance}"]
        if self.adk:
            parts.append(f"ADK: {self.adk}")
        return " ".join(parts)


UNSUPPORTED_TRIGGERS: tuple[UnsupportedConstruct, ...] = (
    UnsupportedConstruct(
        "OnActivity",
        True,
        "OnActivity has no Declarative Agent equivalent. Move its user-context / setup "
        "logic under an OnConversationStart topic, or discard it if no longer needed.",
        Owner.MAKER,
        "`/create` a conversation-start topic, then `/run` to check the greeting path.",
    ),
    UnsupportedConstruct(
        "OnGeneratedResponse",
        True,
        "OnGeneratedResponse is removed. If you used it to add a disclaimer or official "
        "badge to outgoing messages, add agent instructions that enforce that "
        "disclaimer/badge on every generated response instead.",
        Owner.MAKER,
        "`/update` the agent instructions, then `/evaluate` to confirm every response "
        "carries the disclaimer.",
    ),
    UnsupportedConstruct(
        "OnEscalate",
        True,
        "OnEscalate (live-agent hand-off) is not available yet. Implement escalation via "
        "a supported hand-off action, or wait for support in a later wave.",
        Owner.PLATFORM,
    ),
    UnsupportedConstruct(
        "OnPlanComplete",
        True,
        "OnPlanComplete has no equivalent. Move any needed post-response behavior into "
        "agent instructions or a supported topic.",
        Owner.MAKER,
        "`/update` the agent instructions.",
    ),
    UnsupportedConstruct(
        "OnSelectIntent",
        True,
        "OnSelectIntent (Multiple Topics Matched) is not supported. Rely on agent "
        "instructions to disambiguate, and design topics so one is selected per turn.",
        Owner.MAKER,
        "`/evaluate` with your ambiguous utterances to see which topic the agent picks.",
    ),
    UnsupportedConstruct(
        "OnSystemRedirect",
        True,
        "OnSystemRedirect (legacy Reset / End Conversation) is cut. Remove it, or "
        "redesign the reset/end flow using supported topics (e.g. End All Topics).",
        Owner.MAKER,
        "`/create` a replacement end-conversation topic.",
    ),
    UnsupportedConstruct(
        "OnUnknownIntent",
        True,
        "OnUnknownIntent (fallback) is not supported. Add agent instructions to steer "
        "graceful fallback replies, or route unmatched input to a supported topic.",
        Owner.MAKER,
        "`/update` the agent instructions, then `/evaluate` with out-of-scope questions.",
    ),
)

UNSUPPORTED_NODES: tuple[UnsupportedConstruct, ...] = (
    UnsupportedConstruct(
        "AnswerQuestionWithAI",
        False,
        "AnswerQuestionWithAI (generative answers) is not supported yet. Configure the "
        "agent's knowledge sources and instructions to answer from your content, or "
        "wait for support in a later wave.",
        Owner.MAKER,
        "`/connect` the knowledge source, then `/evaluate` the questions it used to answer.",
    ),
    UnsupportedConstruct(
        "ConversationHistory",
        False,
        "The ConversationHistory node is not supported. Rely on the agent's built-in "
        "context handling, or restructure the topic to not depend on it.",
        Owner.MAKER,
        "`/run` the topic to see whether built-in context already covers it.",
    ),
    UnsupportedConstruct(
        "IncludeSelectedTopics",
        False,
        "IncludeSelectedTopics is not supported. Restructure so the needed logic lives "
        "in standalone topics the agent can select directly.",
        Owner.MAKER,
        "`/create` standalone topics for the included logic.",
    ),
    UnsupportedConstruct(
        "InvokeAIBuilderModelAction",
        False,
        "Invoking AI Builder models from a topic is not supported. Call the model via a "
        "connected Power Automate flow instead, or wait for support.",
        Owner.MAKER,
        "`/connect` a Power Automate flow that wraps the model.",
    ),
    UnsupportedConstruct(
        "RecognizeIntent",
        False,
        "The RecognizeIntent node is not supported. Model the intent as a topic's "
        "trigger phrases, or rely on the agent's natural-language routing.",
        Owner.MAKER,
        "`/update` the topic's trigger phrases, then `/evaluate` the intent utterances.",
    ),
    UnsupportedConstruct(
        "SearchAndSummarizeContent",
        False,
        "SearchAndSummarizeContent (generative answers, advanced) is not supported yet. "
        "Use the agent's knowledge sources for grounded answers, or wait for support.",
        Owner.MAKER,
        "`/connect` the knowledge source, then `/evaluate` for grounding quality.",
    ),
    UnsupportedConstruct(
        "TransferConversationV2",
        False,
        "TransferConversationV2 is not supported yet. Implement hand-off with a "
        "supported action, or wait for support in a later wave.",
        Owner.PLATFORM,
    ),
)

_TRIGGERS_BY_KIND = {construct.kind: construct for construct in UNSUPPORTED_TRIGGERS}
_NODES_BY_KIND = {construct.kind: construct for construct in UNSUPPORTED_NODES}


def trigger_kind(dialog: Any) -> str | None:
    """A topic's trigger kind — ``dialog.beginDialog.kind``."""
    if not isinstance(dialog, dict):
        return None
    begin = dialog.get("beginDialog")
    kind = begin.get("kind") if isinstance(begin, dict) else None
    return kind if isinstance(kind, str) else None


def find_unsupported(dialog: Any) -> list[UnsupportedConstruct]:
    """Every unsupported construct used by a projected dialog, trigger first."""
    found: list[UnsupportedConstruct] = []
    trigger = _TRIGGERS_BY_KIND.get(trigger_kind(dialog) or "")
    if trigger is not None:
        found.append(trigger)
    seen: set[str] = set()
    for kind in _walk_kinds(dialog):
        node = _NODES_BY_KIND.get(kind)
        if node is not None and node.kind not in seen:
            seen.add(node.kind)
            found.append(node)
    return found


def deprecate(entry: dict[str, Any]) -> None:
    """Disable an ``agent.yml`` component and mark its title, idempotently.

    All of the component's logic is left untouched — the customer keeps it, can
    read it, and can rebuild it on supported primitives.
    """
    entry["state"] = "Inactive"
    entry["status"] = "Inactive"
    name = entry.get("displayName")
    if isinstance(name, str) and not name.startswith(DEPRECATED_MARKER):
        entry["displayName"] = f"{DEPRECATED_MARKER} {name}"


def is_deprecated(entry: dict[str, Any]) -> bool:
    name = entry.get("displayName")
    return entry.get("state") == "Inactive" and isinstance(name, str) and (
        name.startswith(DEPRECATED_MARKER)
    )


def _walk_kinds(node: Any) -> list[str]:
    kinds: list[str] = []
    if isinstance(node, dict):
        kind = node.get("kind")
        if isinstance(kind, str):
            kinds.append(kind)
        for value in node.values():
            kinds.extend(_walk_kinds(value))
    elif isinstance(node, list):
        for item in node:
            kinds.extend(_walk_kinds(item))
    return kinds
