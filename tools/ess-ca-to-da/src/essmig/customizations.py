"""The ``inspect`` diff report — exactly what the customer changed versus ESS.

``customizations.json`` is a faithful *snapshot*: for every component the customer
touched or authored it stores the full effective ``data``. That answers "what does
this component look like now" but not the question a Maker actually asks first —
"what did I change from the original ESS agent?". A component that lives only in the
customer's unmanaged solution is flagged ``is_net_new`` by the layer heuristic even
when it is a near-verbatim copy of an ESS out-of-box topic, so the snapshot alone
cannot tell a real edit from shipped content or from pure re-serialisation.

This module answers that question directly. Each discovered component is matched to
the shipped ESS baseline (``reference/ca-baseline.json``) by schema-name suffix and
classified by *content*, not by layer:

* **Edited** — a baseline counterpart exists and the text differs. A unified diff
  (ESS baseline -> your version) shows the exact lines that changed.
* **New** — no baseline counterpart. Genuinely customer-authored; the body is shown.
* **Unchanged** — a baseline counterpart exists and the text is identical once line
  endings are normalised. Listed for completeness so the Maker can see the tool did
  not simply miss it.

Line endings are normalised via :meth:`str.splitlines` before both the equality test
and the diff, so a component that differs only in CRLF-vs-LF re-serialisation reads as
*Unchanged* rather than as a spurious wall of changes.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import StrEnum

from essmig.discovery import CaComponent, DiscoveryResult
from essmig.merge import _AGENT_SUFFIX, ComponentResult, Outcome
from essmig.reference import BaselineComponent

_BODY_LIMIT = 400
"""Max lines of a New component's body (or of a single diff) before truncation."""


class Change(StrEnum):
    EDITED = "edited"
    NEW = "new"
    UNCHANGED = "unchanged"


_HEADLINE = {
    Change.EDITED: "Edited (differs from the ESS baseline)",
    Change.NEW: "New (no ESS baseline counterpart)",
    Change.UNCHANGED: "Unchanged from the ESS baseline",
}

# Most actionable first. UNCHANGED sorts last but is excluded from the report.
_ORDER = (Change.EDITED, Change.NEW, Change.UNCHANGED)

# Sections and summary rows the report actually shows — unchanged is deliberately
# omitted, as an unedited copy of ESS content is noise, not a customization.
_REPORTED = (Change.EDITED, Change.NEW)


class Migratability(StrEnum):
    """Whether a customization will make it onto the Declarative Agent, at a glance."""

    MIGRATABLE = "migratable"
    ACTION = "action"
    UNSUPPORTED = "unsupported"


_MIGRATABILITY_HEADLINE = {
    Migratability.MIGRATABLE: "✅ Migratable now",
    Migratability.ACTION: "⚠️ Migratable, but needs you",
    Migratability.UNSUPPORTED: "⛔ Not supported yet",
}

# The order migratability rows appear in the summary — worst news first.
_MIGRATABILITY_ORDER = (
    Migratability.UNSUPPORTED,
    Migratability.ACTION,
    Migratability.MIGRATABLE,
)


def migratability(result: ComponentResult) -> tuple[Migratability, str]:
    """Bucket one component's merge outcome into a migratability tier and a one-liner.

    This is the same classification the migration report makes, phrased for someone
    reading the *diff*: after seeing *what* changed, they immediately learn whether
    that change carries onto the Declarative Agent, needs their hand, or has no home
    yet.
    """
    outcome = result.outcome
    if result.suffix == _AGENT_SUFFIX:
        if outcome is Outcome.MERGED:
            return Migratability.MIGRATABLE, "carries onto the Declarative Agent automatically"
        return Migratability.ACTION, "confirm which name/description the agent should keep"
    if result.deprecated:
        reasons = "; ".join(result.unsupported) or "an unsupported construct"
        return (
            Migratability.ACTION,
            f"carried, but disabled — {reasons}; rebuild on supported building blocks",
        )
    if outcome in (Outcome.MERGED, Outcome.CARRIED_NEW):
        return Migratability.MIGRATABLE, "carries onto the Declarative Agent automatically"
    if outcome is Outcome.UNCHANGED:
        return Migratability.MIGRATABLE, "nothing to carry once re-serialisation is normalised"
    if outcome is Outcome.CONFLICTED:
        count = len(result.conflicts)
        spot = "spot" if count == 1 else "spots"
        return Migratability.ACTION, f"carries, but you must resolve {count} conflicting {spot}"
    if outcome is Outcome.MANUAL:
        return Migratability.ACTION, "re-create it by hand in the agent's settings after importing"
    if outcome is Outcome.LOCKED:
        return (
            Migratability.UNSUPPORTED,
            "the template marks this read-only; your edit is not carried",
        )
    if outcome is Outcome.BLOCKED:
        return Migratability.UNSUPPORTED, "no Declarative Agent equivalent exists in this release"
    if outcome is Outcome.NO_TARGET:
        return Migratability.UNSUPPORTED, "the Declarative Agent has no component for this type"
    return Migratability.UNSUPPORTED, "could not be processed"


@dataclass(frozen=True)
class ComponentDiff:
    """One discovered component classified against the ESS baseline."""

    suffix: str
    schemaname: str
    component_type_label: str
    change: Change
    diff: str
    """Unified diff (EDITED), the body (NEW), or empty (UNCHANGED)."""


def classify(component: CaComponent, baseline: BaselineComponent | None) -> ComponentDiff:
    """Compare one component to its baseline counterpart and describe the change."""
    ours = component.data or ""
    if baseline is None:
        change = Change.NEW
        body = _truncate(ours.splitlines())
    else:
        theirs = baseline.data or ""
        if theirs.splitlines() == ours.splitlines():
            change = Change.UNCHANGED
            body = ""
        else:
            change = Change.EDITED
            body = _unified(theirs, ours)
    return ComponentDiff(
        suffix=component.suffix,
        schemaname=component.schemaname,
        component_type_label=component.component_type_label,
        change=change,
        diff=body,
    )


def diffs(
    result: DiscoveryResult, baseline: dict[str, BaselineComponent]
) -> list[ComponentDiff]:
    """Classify every discovered component, sorted most-actionable first then by name."""
    entries = [
        classify(component, baseline.get(component.suffix))
        for component in result.components.values()
    ]
    return sorted(entries, key=lambda entry: (_ORDER.index(entry.change), entry.suffix))


def render_markdown(
    result: DiscoveryResult,
    baseline: dict[str, BaselineComponent],
    outcomes: dict[str, ComponentResult] | None = None,
) -> str:
    """The ``customizations.md`` body: a unified diff per customized component.

    When ``outcomes`` (a ``{suffix: ComponentResult}`` map from a merge run) is
    supplied, every component is also tagged with whether the change is migratable
    now, needs a human, or is not supported yet — so the diff answers both "what
    changed?" and "will it carry over?" in one place.
    """
    entries = diffs(result, baseline)
    reported = [entry for entry in entries if entry.change in _REPORTED]
    counts = {change: sum(entry.change is change for entry in entries) for change in _REPORTED}
    outcomes = outcomes or {}

    lines: list[str] = [
        f"# ESS customizations — {result.vertical.upper()}",
        "",
        f"- Source (Custom Engine Agent): `{result.solution_unique_name}`",
        f"- Customizations found: **{len(reported)}** "
        f"(of {len(entries)} components inspected)",
        "",
        "Each component below is compared against the original ESS agent it descends "
        "from, matched by schema-name suffix. **Edited** shows a unified diff of just "
        "the lines you changed; **New** has no ESS counterpart. Components identical to "
        "what ESS shipped are omitted. Each is also tagged **✅ migratable now**, "
        "**⚠️ migratable but needs you**, or **⛔ not supported yet**.",
        "",
        "## Summary",
        "",
        "| Change | Count |",
        "| --- | ---: |",
    ]
    for change in _REPORTED:
        lines.append(f"| {_HEADLINE[change]} | {counts[change]} |")

    if outcomes:
        lines += _migratability_summary(reported, outcomes)

    agent_outcome = outcomes.get(_AGENT_SUFFIX)
    if agent_outcome is not None or (result.agent is not None and result.agent.is_customized):
        lines += _agent_section(result, agent_outcome)

    for change in _REPORTED:
        section = [entry for entry in reported if entry.change is change]
        if not section:
            continue
        lines += ["", f"## {_HEADLINE[change]}", ""]
        for entry in section:
            lines += _component_section(entry, outcomes.get(entry.suffix))

    if not reported:
        lines += ["", "_No customizations were found in scope._"]

    return "\n".join(lines) + "\n"


def _migratability_summary(
    reported: list[ComponentDiff], outcomes: dict[str, ComponentResult]
) -> list[str]:
    """A second summary table: of the reported customizations, how many will carry."""
    tiers = [
        migratability(outcomes[entry.suffix])[0]
        for entry in reported
        if entry.suffix in outcomes
    ]
    counts = {tier: tiers.count(tier) for tier in _MIGRATABILITY_ORDER}
    lines = [
        "",
        "### Will it migrate?",
        "",
        "| Migratability | Count |",
        "| --- | ---: |",
    ]
    for tier in _MIGRATABILITY_ORDER:
        lines.append(f"| {_MIGRATABILITY_HEADLINE[tier]} | {counts[tier]} |")
    return lines


def _agent_section(result: DiscoveryResult, outcome: ComponentResult | None) -> list[str]:
    """The agent's own name/description change — not a component, but a customization."""
    agent = result.agent
    lines = ["", "## Agent name & description", ""]
    if outcome is not None:
        tier, note = migratability(outcome)
        lines.append(f"- Migration: **{_MIGRATABILITY_HEADLINE[tier]}** — {note}")
        lines.append("")
    if agent is None:
        return lines
    if agent.name_changed or (agent.name is not None and agent.baseline_name is not None):
        lines.append("**Display name**")
        lines.append("")
        lines.append(f"- ESS baseline: `{agent.baseline_name}`")
        lines.append(f"- Your version: `{agent.name}`")
        lines.append("")
    elif agent.name is not None:
        lines += [f"- Your display name: `{agent.name}`", ""]
    if agent.description_changed or (
        agent.description is not None and agent.baseline_description is not None
    ):
        lines.append("**Description**")
        lines.append("")
        lines += _text_diff(agent.baseline_description or "", agent.description or "")
        lines.append("")
    elif agent.description is not None:
        lines += ["**Description**", "", "```", agent.description, "```", ""]
    return lines


def _text_diff(before: str, after: str) -> list[str]:
    """A fenced unified diff between two blocks of prose."""
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="ESS baseline",
        tofile="your version",
        lineterm="",
    )
    body = list(diff)
    if not body:
        return ["_(no textual change)_"]
    return ["```diff", *body, "```"]


def _component_section(entry: ComponentDiff, outcome: ComponentResult | None) -> list[str]:
    lines = [f"### {entry.suffix}", "", f"- Type: `{entry.component_type_label}`",
             f"- Schema name: `{entry.schemaname}`"]
    if outcome is not None:
        tier, note = migratability(outcome)
        lines.append(f"- Migration: **{_MIGRATABILITY_HEADLINE[tier]}** — {note}")
    lines.append("")
    if entry.change is Change.EDITED:
        lines += ["```diff", entry.diff, "```", ""]
    elif entry.change is Change.NEW:
        lines += ["Customer-authored; shown in full (no ESS version to diff against).",
                  "", "```yaml", entry.diff, "```", ""]
    else:
        lines += ["No textual differences from the ESS baseline.", ""]
    return lines


def _unified(theirs: str, ours: str) -> str:
    diff = difflib.unified_diff(
        theirs.splitlines(),
        ours.splitlines(),
        fromfile="ESS baseline",
        tofile="your version",
        lineterm="",
    )
    return _truncate(list(diff))


def _truncate(body: list[str]) -> str:
    if len(body) <= _BODY_LIMIT:
        return "\n".join(body)
    kept = body[:_BODY_LIMIT]
    return "\n".join([*kept, f"# ... truncated {len(body) - _BODY_LIMIT} more line(s)"])


__all__ = [
    "Change",
    "ComponentDiff",
    "Migratability",
    "classify",
    "diffs",
    "migratability",
    "render_markdown",
]
