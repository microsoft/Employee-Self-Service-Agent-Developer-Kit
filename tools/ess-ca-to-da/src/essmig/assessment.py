"""Is this customer ready to migrate, and if not, what is in the way?

The migration spec's leading success metric counts customers who have been
*assessed for scenario parity* and told either that they are eligible or what is
blocking them. That is a verdict, not a pile of counts, so the tool states one
plainly and separates the three things a Maker actually needs to tell apart:

* **Blockers** — capability that does not survive the move, at all. Nobody can
  close these by working harder; they are a decision to accept a loss or wait.
* **Worklist** — real work, but work that can be done: conflicts to resolve and
  topics to rebuild on supported primitives.
* **Employee impact** — what changes for the people using the agent every day,
  which is invisible in a component-by-component report and is exactly what the
  spec insists must not be discovered after cutover.

The verdict is deliberately conservative. ``ready`` means the tool found nothing
needing a human, not that the agent is proven correct — only the Maker's own
testing establishes that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from essmig.merge import _AGENT_SUFFIX, ComponentResult, MergeResult, Outcome


class Eligibility(StrEnum):
    READY = "ready"
    """Everything carried across; the Maker's job is to test and publish."""

    NEEDS_WORK = "needs-work"
    """Migratable, but with conflicts to resolve or topics to rebuild first."""

    BLOCKED = "blocked"
    """Something the customer relies on cannot be migrated at all."""


_VERDICT = {
    Eligibility.READY: "Ready to migrate",
    Eligibility.NEEDS_WORK: "Can migrate, with work to do first",
    Eligibility.BLOCKED: "Blocked — some capability cannot be migrated",
}

_HISTORY_IMPACT = (
    "Employee conversation history does not move. The Declarative Agent starts "
    "with no history of conversations held with the Custom Engine Agent, so any "
    "employee mid-way through a multi-turn task at cutover starts over."
)
_ANALYTICS_IMPACT = (
    "Usage analytics start from zero. Reporting is per-agent, so the Declarative "
    "Agent will not continue the Custom Engine Agent's adoption trend line. Export "
    "the reports leaders depend on before cutover if you need the history."
)
_ENTRY_POINT_IMPACT = (
    "This tool does not move employees between agents. It prepares the Declarative "
    "Agent's content; how employees are cut over — and whether they must re-find or "
    "re-pin the agent — is decided by how the agent is published and distributed."
)


@dataclass(frozen=True)
class Assessment:
    eligibility: Eligibility
    blockers: list[str] = field(default_factory=list)
    worklist: list[str] = field(default_factory=list)
    employee_impact: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return _VERDICT[self.eligibility]

    def to_json(self) -> dict[str, object]:
        return {
            "eligibility": self.eligibility.value,
            "verdict": self.verdict,
            "blockers": self.blockers,
            "worklist": self.worklist,
            "employeeImpact": self.employee_impact,
        }


def assess(merged: MergeResult) -> Assessment:
    """The migration verdict for one agent."""
    blockers = _blockers(merged.results)
    worklist = _worklist(merged.results)
    if blockers:
        eligibility = Eligibility.BLOCKED
    elif worklist:
        eligibility = Eligibility.NEEDS_WORK
    else:
        eligibility = Eligibility.READY
    return Assessment(
        eligibility=eligibility,
        blockers=blockers,
        worklist=worklist,
        employee_impact=_employee_impact(merged.results),
    )


def _blockers(results: list[ComponentResult]) -> list[str]:
    blockers: list[str] = []
    for result in results:
        name = _name(result)
        if result.outcome is Outcome.FAILED:
            blockers.append(f"{name} could not be processed: {result.detail}")
        elif result.outcome is Outcome.BLOCKED:
            blockers.append(f"{name} cannot be migrated. {result.detail}")
        elif result.outcome is Outcome.NO_TARGET:
            blockers.append(
                f"{name} is a {result.component_type_label} customization this tool "
                "does not know how to migrate. Its configuration is in the report — "
                "check by hand whether the Declarative Agent supports it."
            )
        elif result.outcome is Outcome.LOCKED:
            blockers.append(
                f"{name} is locked by the ESS template, so your change to it cannot be kept."
            )
        elif result.needs_platform_support:
            blockers.append(
                f"{name} uses a capability the Declarative Agent does not support yet, "
                "with no workaround available: " + "; ".join(result.unsupported)
            )
    return blockers


def _worklist(results: list[ComponentResult]) -> list[str]:
    worklist: list[str] = []
    for result in results:
        name = _name(result)
        if result.suffix == _AGENT_SUFFIX:
            if result.outcome is Outcome.CONFLICTED:
                worklist.append(f"{name}: {result.detail}")
            continue
        if result.outcome is Outcome.CONFLICTED:
            count = len(result.conflicts)
            worklist.append(
                f"{name}: re-apply your change by hand — ESS changed the same "
                f"{'place' if count == 1 else f'{count} places'} in this topic."
            )
        if result.outcome is Outcome.MANUAL:
            detail = result.detail.strip()
            if detail:
                worklist.append(f"{name}: {detail}")
            else:
                worklist.append(
                    f"{name}: re-create this {result.component_type_label.lower()} in the "
                    "agent's settings after importing — the package cannot carry it. Your "
                    "configuration is reproduced in the report."
                )
        if result.deprecated and result.needs_maker_work:
            worklist.append(
                f"{name}: rebuild on supported building blocks — "
                + "; ".join(result.unsupported)
            )
    return worklist


def _employee_impact(results: list[ComponentResult]) -> list[str]:
    impact = [_HISTORY_IMPACT, _ANALYTICS_IMPACT, _ENTRY_POINT_IMPACT]
    disabled = [result for result in results if result.deprecated]
    if disabled:
        impact.insert(
            0,
            f"{len(disabled)} topic(s) are disabled in the package. Until you rebuild "
            "them, employees who ask for those scenarios will fall through to a "
            "general answer instead of the flow they get today.",
        )
    return impact


def _name(result: ComponentResult) -> str:
    return result.display_name or result.suffix


__all__ = ["Assessment", "Eligibility", "assess"]
