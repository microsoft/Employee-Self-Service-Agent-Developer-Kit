"""Three-way merge of CA customizations onto the DA template.

This tool is a one-time, offline implementation of the platform's *Upgrade* for
templated agents. The platform cannot do it for a CA customer — they have no Git
Repository Service repo, no base commit and no ``templateBaseVersion``, so there is
no merge base. But every input can be reconstructed from sources ESS owns:

====== ======================================== ==========================
input  meaning                                  source
====== ======================================== ==========================
base   the CA component as ESS shipped it       ``essmig.reference`` baseline
ours   the customer's edit of it                ``essmig.discovery`` (Dataverse)
theirs the DA component ESS ships today         ``essmig.reference`` agent.yml
====== ======================================== ==========================

The merge is intentionally conservative. Where the customer and ESS changed the
same thing in different ways, the result is a **conflict** that a human resolves —
never a silent pick. Measured against the real templates, many edited out-of-box
topics will land here, because ESS substantially rewrote the DA content rather
than re-wrapping the CA content.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from essmig.discovery import AgentMetadata, CaComponent
from essmig.ess import non_ported_pack_of, schema_suffix
from essmig.instructions import (
    InstructionMerger,
    InstructionReconciliationSkipped,
    reconcile_instructions,
)
from essmig.llm import LlmUnavailable
from essmig.projection import (
    ManualConfigurationRequired,
    ProjectionError,
    _state_of,
    as_new_component,
    describe,
    parse_ca_data,
    project,
    shape_for,
)
from essmig.reference import ReferenceSet
from essmig.rules import Owner, deprecate, find_unsupported


class Outcome(StrEnum):
    CARRIED_NEW = "carried-new"
    """Customer-authored component with no template counterpart; carried wholesale."""
    MERGED = "merged"
    """Customer edit of an out-of-box component, merged cleanly onto the template."""
    CONFLICTED = "conflicted"
    """Customer and ESS changed the same thing differently; needs a human."""
    LOCKED = "locked"
    """The template marks this read-only; the customer's edit cannot be carried."""
    UNCHANGED = "unchanged"
    """The customer's version matches the shipped baseline; nothing to carry."""
    NO_TARGET = "no-target"
    """The tool has no mapping for this component type; check it by hand."""
    MANUAL = "manual"
    """Supported by the DA, but as agent settings — re-create it after importing."""
    BLOCKED = "blocked"
    """Belongs to an extension pack with no Declarative Agent equivalent; cannot migrate."""
    FAILED = "failed"
    """The component could not be projected or merged; see ``detail``."""


@dataclass
class ComponentResult:
    suffix: str
    schemaname: str
    display_name: str
    component_type_label: str
    outcome: Outcome
    detail: str = ""
    conflicts: list[Conflict] = field(default_factory=list)
    deprecated: bool = False
    """True when the component was carried but disabled for using unsupported constructs."""
    unsupported: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    """Who must act on each gap, aligned with ``guidance`` — see :class:`essmig.rules.Owner`."""
    configuration: str = ""
    """For ``MANUAL``: the customer's configuration, reproduced so they can re-create it."""
    customer_version: str = ""
    """For ``CONFLICTED``: the customer's complete version, so every edit that could not
    be applied automatically is on record for manual re-application — not just the
    subset of nodes that conflicted."""
    customer_state: str = ""
    """The customer's enabled/disabled state when it could not be applied automatically
    (i.e. it was lost to a payload conflict). Surfaced so the setting stays actionable
    for manual re-application even though ESS's component was kept."""

    @property
    def needs_maker_work(self) -> bool:
        return Owner.MAKER in self.owners

    @property
    def needs_platform_support(self) -> bool:
        """A gap with no route today — it waits on a capability ESS has not shipped."""
        return Owner.PLATFORM in self.owners


@dataclass(frozen=True)
class Conflict:
    """One node both sides changed, or one side changed and the other removed."""

    path: str
    base: Any
    ours: Any
    theirs: Any
    reason: str


class Resolution(StrEnum):
    """A human's decision about one conflicting spot."""

    OURS = "ours"
    """Keep the customer's version at this spot."""
    THEIRS = "theirs"
    """Keep ESS's (the DA template's) version at this spot."""
    MANUAL = "manual"
    """Neither as-is — use a value the human merged by hand."""


@dataclass(frozen=True)
class Decision:
    """A resolver's answer for one conflict: which side, plus a hand-merged value."""

    resolution: Resolution
    value: Any = None
    """For :attr:`Resolution.MANUAL`: the value to place at the spot."""

    @classmethod
    def ours(cls) -> Decision:
        return cls(Resolution.OURS)

    @classmethod
    def theirs(cls) -> Decision:
        return cls(Resolution.THEIRS)

    @classmethod
    def manual(cls, value: Any) -> Decision:
        return cls(Resolution.MANUAL, value)


ConflictResolver = Callable[[Conflict], "Decision | None"]
"""Decide one conflict. Returns ``None`` to leave it unresolved (keep ESS's and
report it), matching the non-interactive default."""

ResolverFactory = Callable[[CaComponent], ConflictResolver]
"""Builds a fresh resolver for one component, so per-topic state (e.g. an
'apply to the rest of this topic' choice) does not leak across components."""


@dataclass
class MergeResult:
    vertical: str
    agent: Any
    """The DA ``agent.yml`` document with merged components substituted in place."""
    results: list[ComponentResult]

    @property
    def conflicted(self) -> list[ComponentResult]:
        return [r for r in self.results if r.outcome is Outcome.CONFLICTED]

    def count(self, outcome: Outcome) -> int:
        return sum(1 for r in self.results if r.outcome is outcome)


# --- Overlay policy ---------------------------------------------------------


class Policy(StrEnum):
    MERGE = "merge"
    """Template default, customer may customize — 3-way merge (isManaged/isCustomizable)."""
    LOCKED = "locked"
    """Author-locked — template always wins (isManaged + readOnly)."""
    CUSTOMER_OWNED = "customer-owned"
    """Customer owns the value outright — ours always wins (not isManaged)."""


@dataclass
class Overlays:
    """``Overlays.json`` read as merge policy, with a safe default.

    Each overlay names a ``path`` selector and the managed-property flags for what
    it selects. The legal flag combinations map onto :class:`Policy`:

    ``isManaged`` + ``readOnly``      → LOCKED
    ``isManaged`` + ``isCustomizable``→ MERGE
    neither managed nor read-only     → CUSTOMER_OWNED

    ESS has not authored an ``Overlays.json`` yet. With none present every path
    falls back to MERGE, which is both the most common real classification and the
    safest: it can produce a conflict for a human, but it never silently discards a
    customer's change nor silently overrides ESS's.
    """

    rules: list[tuple[str, Policy]] = field(default_factory=list)

    @classmethod
    def from_document(cls, document: dict[str, Any] | None) -> Overlays:
        rules: list[tuple[str, Policy]] = []
        for overlay in (document or {}).get("overlays") or []:
            if not isinstance(overlay, dict):
                continue
            path = overlay.get("path")
            if not isinstance(path, str) or not path:
                continue
            rules.append((path, _policy_of(overlay)))
        # Longest (most specific) selector wins.
        rules.sort(key=lambda rule: len(rule[0]), reverse=True)
        return cls(rules=rules)

    def policy_for(self, path: str) -> Policy:
        for selector, policy in self.rules:
            if _matches(path, selector):
                return policy
        return Policy.MERGE


def _matches(path: str, selector: str) -> bool:
    """Glob match where only ``*`` and ``?`` are special.

    Overlay selectors contain square brackets (``components[DialogComponent:topic.X]``)
    which :mod:`fnmatch` would read as character classes, so the pattern is built
    explicitly instead.
    """
    pattern = "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char) for char in selector
    )
    return re.fullmatch(pattern, path) is not None


def _policy_of(overlay: dict[str, Any]) -> Policy:
    if overlay.get("readOnly") is True:
        return Policy.LOCKED
    if overlay.get("isManaged") is False:
        return Policy.CUSTOMER_OWNED
    return Policy.MERGE


# --- Merge ------------------------------------------------------------------


def merge(
    reference: ReferenceSet,
    components: dict[str, CaComponent],
    vertical: str,
    *,
    agent_metadata: AgentMetadata | None = None,
    merge_instructions: InstructionMerger | None = None,
    resolver_factory: ResolverFactory | None = None,
) -> MergeResult:
    """Apply the customer's customizations to the DA template.

    ``agent_metadata`` carries the agent's own display name and description; when
    the customer renamed or re-described the agent it is applied to the emitted
    config (``botName``/``gptDisplayName``) and ``agent.yml`` (``entity.description``)
    and reported like any other customization.

    ``merge_instructions`` reconciles the GPT ``instructions`` scalar, which no
    structural merge can carry (the CA and DA word the same instructions
    differently). It defaults to the model-backed
    :func:`essmig.instructions.reconcile_instructions`; the assessment/dry-run path
    passes :func:`essmig.instructions.keep_target_instructions` to stay offline, and
    tests inject a stub.

    ``resolver_factory`` turns conflicts into interactive decisions. When given, each
    contested spot is offered to the resolver; a resolved spot is applied into the
    package and the component lands MERGED instead of CONFLICTED. When ``None`` (the
    non-interactive default) nothing is prompted: contested spots keep ESS's version
    and are reported for a human, exactly as before.
    """
    reconcile = merge_instructions or reconcile_instructions
    overlays = Overlays.from_document(reference.overlays)
    da_components = reference.da_components
    agent = reference.agent
    entries = agent.get("components")
    if not isinstance(entries, list):
        raise RuntimeError("Reference agent.yml has no 'components' list.")

    results: list[ComponentResult] = []
    agent_result = _merge_agent_metadata(reference, agent_metadata)
    if agent_result is not None:
        results.append(agent_result)
    for component in sorted(components.values(), key=lambda c: c.schemaname):
        result = _merge_one(
            component,
            vertical,
            reference,
            da_components,
            overlays,
            entries,
            reconcile,
            resolver_factory,
        )
        results.append(result)

    _apply_unsupported_rules(entries, results)
    _ensure_knowledge_search(entries)
    return MergeResult(vertical=vertical, agent=agent, results=results)


_AGENT_SUFFIX = "(agent settings)"


def _merge_agent_metadata(
    reference: ReferenceSet, metadata: AgentMetadata | None
) -> ComponentResult | None:
    """Carry a renamed / re-described agent onto the DA, or flag it for review.

    Returns ``None`` when there is nothing to say — no metadata was read, or the
    agent's name and description are unchanged from what ESS shipped. A confirmed
    change (the customer's value differs from the shipped baseline) is applied to the
    emitted config and ``agent.yml`` and reported ``MERGED``. When the baseline could
    not be read the tool will not silently overwrite the DA's own name/description:
    if the customer's value differs from the DA's it is reported ``CONFLICTED`` for a
    human to confirm; if it matches, there is nothing to do.
    """
    if metadata is None:
        return None

    entity = reference.agent.get("entity") if isinstance(reference.agent, dict) else None
    values = reference.config.get("values") if isinstance(reference.config, dict) else None
    da_description = entity.get("description") if isinstance(entity, dict) else None
    da_name = values.get("botName") if isinstance(values, dict) else None

    applied: list[str] = []
    review: list[str] = []

    # Display name -> config botName / gptDisplayName (agent.yml resolves displayName
    # from botName via a ${config.values[...]} pointer).
    if metadata.name is not None and metadata.name.strip():
        if metadata.name_changed:
            _set_agent_name(values, metadata.name)
            applied.append(f'display name -> "{metadata.name}"')
        elif metadata.baseline_name is None and _differs(metadata.name, da_name):
            review.append(
                f'you have "{metadata.name}"; the template ships "{da_name}". '
                "Confirm which name the agent should keep."
            )

    # Description -> agent.yml entity.description.
    if metadata.description is not None and metadata.description.strip():
        if metadata.description_changed:
            if isinstance(entity, dict):
                entity["description"] = metadata.description
            applied.append("description")
        elif metadata.baseline_description is None and _differs(
            metadata.description, da_description
        ):
            review.append(
                "your description differs from the template's. Confirm which "
                "description the agent should keep."
            )

    if not applied and not review:
        return None

    result = ComponentResult(
        suffix=_AGENT_SUFFIX,
        schemaname=reference.da_schemaname,
        display_name=metadata.name or "Agent",
        component_type_label="Agent",
        outcome=Outcome.MERGED if applied else Outcome.CONFLICTED,
    )
    if applied:
        result.detail = "Carried your agent " + " and ".join(applied) + " onto the template."
    if review:
        joined = " ".join(review)
        result.detail = (result.detail + " " if result.detail else "") + joined
        result.configuration = _agent_configuration(metadata)
    return result


def _set_agent_name(values: Any, name: str) -> None:
    """Set every display-name config value the template drives off ``botName``."""
    if not isinstance(values, dict):
        return
    for key in ("botName", "gptDisplayName"):
        if key in values:
            values[key] = name


def _differs(ours: str | None, theirs: Any) -> bool:
    return isinstance(theirs, str) and ours is not None and ours.strip() != theirs.strip()


def _agent_configuration(metadata: AgentMetadata) -> str:
    lines = []
    if metadata.name is not None:
        lines.append(f"name: {metadata.name}")
    if metadata.description is not None:
        lines.append(f"description: {metadata.description}")
    return "\n".join(lines)


def _ensure_knowledge_search(entries: list[Any]) -> None:
    """Point the GPT at its knowledge sources once at least one is present.

    Copilot Studio adds ``knowledgeSources: {kind: SearchAllKnowledgeSources}`` to
    the GPT component's metadata as soon as an agent has any knowledge source; a
    carried source the GPT never searches would be inert. The shipped ESS template
    has no knowledge sources and so no such reference — mirror the platform here,
    without disturbing a reference that already declares its own policy.
    """
    if not any(
        isinstance(entry, dict) and entry.get("kind") == "KnowledgeSourceComponent"
        for entry in entries
    ):
        return
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "GptComponent":
            continue
        metadata = entry.get("metadata")
        if isinstance(metadata, dict) and "knowledgeSources" not in metadata:
            metadata["knowledgeSources"] = {"kind": "SearchAllKnowledgeSources"}


def _apply_unsupported_rules(entries: list[Any], results: list[ComponentResult]) -> None:
    """Disable-but-preserve any carried topic that uses a construct the DA lacks.

    Runs after the merge so it sees the final content: a customer edit may well have
    introduced the unsupported node, and an ESS rewrite may equally have removed it.
    """
    by_suffix = {result.suffix: result for result in results}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "DialogComponent":
            continue
        result = by_suffix.get(schema_suffix(str(entry.get("schemaName") or "")))
        if result is None or result.outcome not in (Outcome.MERGED, Outcome.CARRIED_NEW):
            continue
        found = find_unsupported(entry.get("dialog"))
        if not found:
            continue
        deprecate(entry)
        result.deprecated = True
        result.unsupported = [construct.reason for construct in found]
        result.guidance = [construct.advice for construct in found]
        result.owners = [construct.owner for construct in found]


def _pack_label(solution_unique_name: str) -> str:
    """A human-readable name for an extension-pack solution's unique name.

    ``msdyn_EssHRServiceNowITSM`` → ``HR ServiceNow ITSM``. Falls back to the raw
    unique name when it does not follow the ``msdyn_Ess<...>`` shape.
    """
    stem = solution_unique_name
    for prefix in ("msdyn_Ess", "msdyn_EmployeeSelfService", "msdyn_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", stem)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return spaced.strip() or solution_unique_name


def _merge_one(
    component: CaComponent,
    vertical: str,
    reference: ReferenceSet,
    da_components: dict[str, Any],
    overlays: Overlays,
    entries: list[Any],
    reconcile: InstructionMerger,
    resolver_factory: ResolverFactory | None = None,
) -> ComponentResult:
    suffix = component.suffix
    base_result = ComponentResult(
        suffix=suffix,
        schemaname=component.schemaname,
        display_name=component.name,
        component_type_label=component.component_type_label,
        outcome=Outcome.FAILED,
    )

    try:
        shape = shape_for(component)
    except ManualConfigurationRequired as error:
        base_result.outcome = Outcome.MANUAL
        base_result.detail = str(error)
        base_result.configuration = describe(component, vertical)
        return base_result
    except ProjectionError as error:
        base_result.outcome = Outcome.NO_TARGET
        base_result.detail = str(error)
        base_result.configuration = describe(component, vertical)
        return base_result

    target = da_components.get(suffix)

    try:
        if target is None:
            pack = non_ported_pack_of(component.solutions)
            if pack is not None:
                base_result.outcome = Outcome.BLOCKED
                base_result.detail = (
                    f"Belongs to the {_pack_label(pack)} integration, which this ESS "
                    "Declarative Agent release does not include. There is no agent for "
                    "this customization to attach to, so it cannot be migrated. Its "
                    "configuration is reproduced below."
                )
                base_result.configuration = describe(component, vertical)
                return base_result
            entries.append(as_new_component(component, vertical))
            base_result.outcome = Outcome.CARRIED_NEW
            base_result.detail = (
                "No template counterpart; carried as a customer-owned component."
            )
            return base_result

        policy = overlays.policy_for(_selector(component, vertical, shape.da_kind))
        if policy is Policy.LOCKED:
            base_result.outcome = Outcome.LOCKED
            base_result.detail = (
                "The template marks this component read-only. Your change was not "
                "carried; re-apply it as a new topic if you still need it."
            )
            return base_result

        ours = project(component, vertical)[shape.payload_key]
        theirs = target.get(shape.payload_key)

        if policy is Policy.CUSTOMER_OWNED:
            target[shape.payload_key] = ours
            base_result.outcome = Outcome.MERGED
            base_result.detail = "Customer-owned by overlay policy; your version was kept."
            return base_result

        baseline = reference.baseline.get(suffix)
        base_tree = (
            parse_ca_data(baseline.data, vertical)
            if baseline is not None and baseline.data
            else None
        )
        base_payload = (
            {k: v for k, v in base_tree.items() if k != "kind"}
            if isinstance(base_tree, dict)
            else None
        )

        # Enabled/disabled state lives beside the payload, not inside it, so a
        # structural payload merge never sees it. The DA template ships each topic
        # with a state; if the customer set a different one — e.g. disabling the
        # ConversationStart greeting the template itself suggests turning off — that
        # is a real customization and must be carried, not silently dropped as
        # "unchanged" because the topic body happens to match.
        customer_state = _state_of(component)
        state_changed = (
            customer_state is not None
            and "state" in target
            and customer_state != target.get("state")
        )
        payload_unchanged = base_payload is not None and _equal(base_payload, ours)

        if payload_unchanged and not state_changed:
            base_result.outcome = Outcome.UNCHANGED
            base_result.detail = "Matches the shipped baseline; nothing to carry."
            return base_result

        if payload_unchanged and state_changed and customer_state is not None:
            _apply_state(target, customer_state)
            _mark_customized(target)
            base_result.outcome = Outcome.MERGED
            base_result.detail = _state_detail(customer_state)
            return base_result

        if base_payload is None:
            # No baseline to diff against, so every difference from the template is
            # indistinguishable from a customer edit. Treat the whole component as a
            # conflict rather than guess, and reproduce the customer's complete
            # version so nothing is lost for hand re-application.
            base_result.outcome = Outcome.CONFLICTED
            base_result.customer_version = describe(component, vertical)
            base_result.conflicts = [
                Conflict(
                    path=suffix,
                    base=None,
                    ours=ours,
                    theirs=theirs,
                    reason="no shipped baseline for this component; cannot tell which "
                    "differences are yours",
                )
            ]
            _record_unapplied_state(base_result, state_changed, customer_state)
            return base_result

        resolve: ConflictResolver | None = None
        decisions: list[Resolution] = []
        if resolver_factory is not None:
            per_component = resolver_factory(component)

            def resolve(conflict: Conflict) -> Decision | None:
                decision = per_component(conflict)
                if decision is not None:
                    decisions.append(decision.resolution)
                return decision

        merged, conflicts = merge_node(base_payload, ours, theirs, path=suffix, resolve=resolve)

        instruction_note: str | None = None
        if shape.da_kind == "GptComponent":
            merged, conflicts, instruction_note = _reconcile_gpt_instructions(
                merged, conflicts, base_payload, ours, theirs, suffix, reconcile
            )

        if conflicts:
            # Keeping ESS's component whole is the safe default, but the conflict list
            # only names the *contested* nodes — any edit the customer made that merged
            # cleanly is thrown away with the discarded merge and would otherwise vanish
            # from both the package and the report. Reproduce the customer's complete
            # version so every unapplied edit is on record for manual re-application.
            base_result.outcome = Outcome.CONFLICTED
            base_result.conflicts = conflicts
            base_result.customer_version = describe(component, vertical)
            base_result.detail = (
                f"{len(conflicts)} node(s) changed by both you and ESS. Your complete "
                "version is reproduced below so every edit — including any that are not "
                "listed as a conflict — can be re-applied by hand."
            )
            if instruction_note:
                base_result.detail = f"{base_result.detail} {instruction_note}"
            _record_unapplied_state(base_result, state_changed, customer_state)
            return base_result

        target[shape.payload_key] = merged
        if state_changed and customer_state is not None:
            _apply_state(target, customer_state)
        _mark_customized(target)
        base_result.outcome = Outcome.MERGED
        detail = _merged_detail(decisions, instruction_note)
        if state_changed and customer_state is not None:
            detail = f"{detail} {_state_detail(customer_state)}"
        base_result.detail = detail
        return base_result
    except ProjectionError as error:
        base_result.outcome = Outcome.FAILED
        base_result.detail = str(error)
        return base_result


def _instructions_of(payload: Any) -> str | None:
    """The ``instructions`` string from a GPT component's metadata, if present."""
    if isinstance(payload, dict):
        value = payload.get("instructions")
        if isinstance(value, str):
            return value
    return None


def _reconcile_gpt_instructions(
    merged: Any,
    conflicts: list[Conflict],
    base: Any,
    ours: Any,
    theirs: Any,
    suffix: str,
    reconcile: InstructionMerger,
) -> tuple[Any, list[Conflict], str | None]:
    """Migrate an edited ``instructions`` scalar the structural merge cannot carry.

    Only acts when the customer actually edited the instructions (``ours`` differs
    from the shipped CA ``base``). It then re-expresses that delta onto the DA's
    wording via ``reconcile`` and drops the ``.instructions`` conflict the structural
    merge raised. If the model is unreachable, it keeps the DA's instructions and
    leaves the conflict in place so a human can re-apply the edit by hand.
    """
    base_instructions = _instructions_of(base)
    our_instructions = _instructions_of(ours)
    da_instructions = _instructions_of(theirs)
    if base_instructions is None or our_instructions is None or da_instructions is None:
        return merged, conflicts, None
    if our_instructions.strip() == base_instructions.strip():
        return merged, conflicts, None  # customer left the instructions alone

    try:
        reconciled = reconcile(base_instructions, our_instructions, da_instructions)
    except InstructionReconciliationSkipped as error:
        # Deliberately not merged (--keep-instructions). Keep the DA wording and leave
        # the conflict so the outcome is honestly CONFLICTED, not a false success.
        return merged, conflicts, str(error)
    except LlmUnavailable as error:
        note = (
            "Your instruction edits could not be auto-migrated "
            f"({error}); the DA's instructions were kept — re-apply your changes by hand."
        )
        return merged, conflicts, note

    if isinstance(merged, dict):
        merged = dict(merged)
        merged["instructions"] = reconciled
    remaining = [
        conflict for conflict in conflicts if not conflict.path.endswith(".instructions")
    ]
    note = "Your instruction edits were re-applied to the DA's wording by the model."
    return merged, remaining, note


def _merged_detail(decisions: list[Resolution], instruction_note: str | None) -> str:
    """The MERGED detail line, noting any conflicts the human resolved by hand."""
    if decisions:
        kept_yours = sum(1 for d in decisions if d is Resolution.OURS)
        kept_ess = sum(1 for d in decisions if d is Resolution.THEIRS)
        hand_merged = sum(1 for d in decisions if d is Resolution.MANUAL)
        parts = [f"{kept_yours} kept yours", f"{kept_ess} kept ESS's"]
        if hand_merged:
            parts.append(f"{hand_merged} merged by hand")
        note = f"You resolved {len(decisions)} conflicting spot(s) here — {', '.join(parts)}."
        return f"{note} {instruction_note}" if instruction_note else note
    return instruction_note or "Your changes were applied on top of the updated template."


def _resolve_atomic(
    resolve: ConflictResolver | None, conflict: Conflict, ours: Any, theirs: Any
) -> tuple[Any, list[Conflict]]:
    """Offer a whole-value conflict to the resolver, else keep theirs and report it."""
    decision = resolve(conflict) if resolve is not None else None
    if decision is None:
        return theirs, [conflict]
    if decision.resolution is Resolution.OURS:
        return ours, []
    if decision.resolution is Resolution.THEIRS:
        return theirs, []
    return decision.value, []  # MANUAL: the human's hand-merged value


def merge_node(base: Any, ours: Any, theirs: Any, *, path: str,
               resolve: ConflictResolver | None = None) -> tuple[Any, list[Conflict]]:
    """Three-way merge one node.

    The rules, in order: if we did not change it, take theirs; if they did not
    change it, take ours; if we both made the same change, take it. Otherwise the
    node is contested — recurse into matching containers to localise the
    disagreement, and report a conflict only at the deepest point where the two
    sides genuinely differ.
    """
    if _equal(ours, base):
        return theirs, []
    if _equal(theirs, base):
        return ours, []
    if _equal(ours, theirs):
        return theirs, []

    if isinstance(base, dict) and isinstance(ours, dict) and isinstance(theirs, dict):
        return _merge_dict(base, ours, theirs, path, resolve)
    if isinstance(base, list) and isinstance(ours, list) and isinstance(theirs, list):
        return _merge_list(base, ours, theirs, path, resolve)

    return _resolve_atomic(
        resolve,
        Conflict(path=path, base=base, ours=ours, theirs=theirs, reason="both sides changed"),
        ours,
        theirs,
    )


def _merge_dict(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any], path: str,
    resolve: ConflictResolver | None = None,
) -> tuple[dict[str, Any], list[Conflict]]:
    conflicts: list[Conflict] = []
    merged: dict[str, Any] = {}
    missing = object()

    # Preserve the template's key order, then append keys only the customer added.
    keys = list(theirs) + [key for key in ours if key not in theirs]
    keys += [key for key in base if key not in theirs and key not in ours]

    for key in keys:
        child = f"{path}.{key}"
        b, o, t = base.get(key, missing), ours.get(key, missing), theirs.get(key, missing)

        if o is missing and t is missing:
            continue  # both removed it
        if o is missing:
            if b is missing:
                # ESS *added* a key neither the baseline nor the customer had. This
                # is a new template default, not a customer deletion — take it
                # cleanly. (Mislabelling this an "you removed it" conflict is exactly
                # what made an ESS contract rename look like the customer deleted
                # every renamed field.)
                merged[key] = t
                continue
            # The baseline had it and the customer dropped it. Honour the deletion
            # only if ESS left the value untouched.
            if _equal(b, t):
                continue
            conflict = Conflict(
                path=child,
                base=b,
                ours=None,
                theirs=t,
                reason="you removed this; ESS changed it",
            )
            decision = resolve(conflict) if resolve is not None else None
            if decision is None:
                conflicts.append(conflict)
                merged[key] = t
            elif decision.resolution is Resolution.OURS:
                continue  # honour the customer's removal
            elif decision.resolution is Resolution.THEIRS:
                merged[key] = t
            else:
                merged[key] = decision.value  # MANUAL
            continue
        if t is missing:
            if b is missing:
                # The customer *added* a key ESS never had. ESS did not "remove" it
                # (it was never in the baseline), so this is a clean customer
                # addition — keep the customer's value.
                merged[key] = o
                continue
            # The baseline had it and ESS dropped it. Keep the customer's value only
            # if they actually changed it from the baseline.
            if _equal(b, o):
                continue
            conflict = Conflict(
                path=child,
                base=b,
                ours=o,
                theirs=None,
                reason="ESS removed this; you changed it",
            )
            decision = resolve(conflict) if resolve is not None else None
            if decision is None:
                conflicts.append(conflict)
                merged[key] = o
            elif decision.resolution is Resolution.THEIRS:
                continue  # honour ESS's removal
            elif decision.resolution is Resolution.OURS:
                merged[key] = o
            else:
                merged[key] = decision.value  # MANUAL
            continue

        value, child_conflicts = merge_node(
            None if b is missing else b, o, t, path=child, resolve=resolve
        )
        merged[key] = value
        conflicts.extend(child_conflicts)

    return merged, conflicts


def _merge_list(
    base: list[Any], ours: list[Any], theirs: list[Any], path: str,
    resolve: ConflictResolver | None = None,
) -> tuple[list[Any], list[Conflict]]:
    """Merge a list by element ``id`` where possible, else treat it as one value.

    Power Fx dialog action lists give every action a stable ``id``, which makes them
    mergeable element-wise: inserts, deletes and edits can be told apart. Lists
    without ids (message variations, trigger phrases) carry no identity, so they are
    merged as a single atomic value.
    """
    if not _all_keyed(base) or not _all_keyed(ours) or not _all_keyed(theirs):
        return _resolve_atomic(
            resolve,
            Conflict(
                path=path,
                base=base,
                ours=ours,
                theirs=theirs,
                reason="both sides changed this list and its items carry no ids",
            ),
            ours,
            theirs,
        )

    base_by_id = {item["id"]: item for item in base}
    ours_by_id = {item["id"]: item for item in ours}
    theirs_by_id = {item["id"]: item for item in theirs}

    conflicts: list[Conflict] = []
    resolved: dict[str, Any] = {}  # id -> merged value, only for actions that survive
    reconciled: set[str] = set()

    def reconcile(item_id: str) -> None:
        """Resolve one action's *value* (into ``resolved``), independent of ordering."""
        if item_id in reconciled:
            return
        reconciled.add(item_id)
        b = base_by_id.get(item_id)
        o = ours_by_id.get(item_id)
        t = theirs_by_id.get(item_id)
        child = f"{path}[{item_id}]"
        if o is None and t is None:
            return
        if o is None:
            if b is not None and _equal(b, t):
                return  # customer deleted an untouched action
            if b is None:
                resolved[item_id] = t
                return
            conflict = Conflict(
                child, b, None, t, "you removed this action; ESS changed it"
            )
            decision = resolve(conflict) if resolve is not None else None
            if decision is None:
                conflicts.append(conflict)
                resolved[item_id] = t
            elif decision.resolution is Resolution.OURS:
                pass  # honour the customer's removal
            elif decision.resolution is Resolution.THEIRS:
                resolved[item_id] = t
            else:
                resolved[item_id] = decision.value  # MANUAL
            return
        if t is None:
            if b is not None and _equal(b, o):
                return  # ESS deleted an action the customer never touched
            if b is None:
                resolved[item_id] = o
                return
            conflict = Conflict(
                child, b, o, None, "ESS removed this action; you changed it"
            )
            decision = resolve(conflict) if resolve is not None else None
            if decision is None:
                conflicts.append(conflict)
                resolved[item_id] = o
            elif decision.resolution is Resolution.THEIRS:
                pass  # honour ESS's removal
            elif decision.resolution is Resolution.OURS:
                resolved[item_id] = o
            else:
                resolved[item_id] = decision.value  # MANUAL
            return
        value, child_conflicts = merge_node(b, o, t, path=child, resolve=resolve)
        resolved[item_id] = value
        conflicts.extend(child_conflicts)

    for item in theirs:
        reconcile(item["id"])
    for item in ours:
        reconcile(item["id"])

    # Ordering is load-bearing in a Power Fx action list: an action inserted before
    # a terminal action (e.g. EndDialog) must stay before it, and a reorder the
    # customer made is itself a customization. Merge the *order* three-way over the
    # actions common to both sides, then weave in whichever side's inserts are not
    # yet placed.
    common = {item_id for item_id in resolved if item_id in ours_by_id and item_id in theirs_by_id}

    def _relative(seq: list[Any]) -> list[str]:
        return [item["id"] for item in seq if item["id"] in common]

    # The customer's relative order wins only when ESS left the order alone; if both
    # reordered the same set differently there is no automatic answer, so keep ESS's
    # order and flag it. We can only attribute a reorder when the baseline actually
    # contained every common action; otherwise fall back to ESS's sequence.
    use_customer_order = False
    if common and all(item_id in base_by_id for item_id in common):
        base_order = _relative(base)
        ours_order = _relative(ours)
        theirs_order = _relative(theirs)
        ours_reordered = ours_order != base_order
        theirs_reordered = theirs_order != base_order
        if ours_reordered and not theirs_reordered:
            use_customer_order = True
        elif ours_reordered and theirs_reordered and ours_order != theirs_order:
            conflicts.append(
                Conflict(
                    path,
                    base_order,
                    ours_order,
                    theirs_order,
                    "you and ESS both reordered these actions differently; ESS's order "
                    "was kept — re-check the sequence by hand",
                )
            )

    # Spine = the side whose order we adopt for the common actions; weave = the other
    # side, whose inserts we thread back in after their nearest surviving predecessor.
    spine, weave = (ours, theirs) if use_customer_order else (theirs, ours)
    weave_by_id = ours_by_id if weave is ours else theirs_by_id
    order: list[str] = [item["id"] for item in spine if item["id"] in resolved]
    for index, item in enumerate(weave):
        item_id = item["id"]
        if item_id not in resolved or item_id in order:
            continue
        anchor = next(
            (
                order.index(prev["id"])
                for prev in reversed(weave[:index])
                if prev["id"] in order
            ),
            None,
        )
        if anchor is not None:
            order.insert(anchor + 1, item_id)
        elif index == 0:
            order.insert(0, item_id)  # inserted at the very front
        elif weave is ours:
            conflicts.append(
                Conflict(
                    f"{path}[{item_id}]",
                    None,
                    weave_by_id[item_id],
                    None,
                    "you inserted this action, but every action it followed is gone "
                    "from the updated template, so its position cannot be preserved "
                    "automatically — place it by hand",
                )
            )
            order.append(item_id)
        else:
            conflicts.append(
                Conflict(
                    f"{path}[{item_id}]",
                    None,
                    None,
                    weave_by_id[item_id],
                    "ESS added this action, but the actions it followed are gone from "
                    "your reordered version, so its position cannot be placed "
                    "automatically — check the sequence by hand",
                )
            )
            order.append(item_id)

    merged = [resolved[item_id] for item_id in order]
    return merged, conflicts


def _all_keyed(items: list[Any]) -> bool:
    return all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in items)


def _equal(left: Any, right: Any) -> bool:
    """Structural equality that ignores YAML round-trip wrapper types."""
    return bool(_plain(left) == _plain(right))


def _plain(node: Any) -> Any:
    if isinstance(node, dict):
        return {str(key): _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(item) for item in node]
    return node


def _selector(component: CaComponent, vertical: str, da_kind: str) -> str:
    """The Overlays path this component is matched against."""
    del vertical
    return f"components[{da_kind}:{component.suffix}]"


def _mark_customized(target: dict[str, Any]) -> None:
    """Record that a managed component now carries customer content."""
    properties = target.get("managedProperties")
    if isinstance(properties, dict):
        properties["isCustomizable"] = True


def _apply_state(target: dict[str, Any], state: str) -> None:
    """Carry the customer's enabled/disabled state onto the DA component."""
    target["state"] = state
    target["status"] = state


def _state_detail(state: str) -> str:
    verb = "disabled" if state == "Inactive" else "enabled"
    return (
        f"You {verb} this topic; that setting was carried onto the DA component "
        "(verify it in the agent after import)."
    )


def _record_unapplied_state(
    result: ComponentResult, state_changed: bool, customer_state: str | None
) -> None:
    """Surface a customer enabled/disabled state that a payload conflict left behind.

    On conflict ESS's whole component is kept, so the customer's state is not applied.
    Record it as a structured field and a detail line so the setting stays visible and
    actionable for manual re-application rather than vanishing with the discarded merge.
    """
    if not (state_changed and customer_state is not None):
        return
    result.customer_state = customer_state
    verb = "disabled" if customer_state == "Inactive" else "enabled"
    note = (
        f"You had {verb} this topic; because of the conflict ESS's version was kept and "
        "that setting was not applied — re-apply it by hand after import."
    )
    result.detail = f"{result.detail} {note}".strip()
