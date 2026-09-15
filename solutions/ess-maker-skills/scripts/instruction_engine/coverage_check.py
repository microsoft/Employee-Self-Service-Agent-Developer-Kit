"""Coverage-check mode: distinguish a fixable instruction defect from a
platform limitation the maker cannot reach by editing instruction text.

See docs/plans/2026-09-11-ess-instruction-hardening-engine-design.md for the
rationale — this exists because real customer data (Blackstone) showed the
maker had already written correct, explicit, on-topic instructions and the
unwanted behavior did not change, because the behavior was emitted by the
platform/pipeline, not controllable from instruction text. A tool that only
ever proposes another reworded prohibition in that situation wastes the
maker's time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import Finding
from .semantic_rules.runner import run_semantic_pass

# Semantic finding IDs that mean "a rule contradicts or creates a gap around
# this behavior" — if any of these are on-topic for the reported problem, the
# instructions do NOT actually cover it cleanly, so the verdict must not be
# likely_platform_limitation.
_CONTRADICTION_IDS = {"INSTR-001", "INSTR-002", "INSTR-003", "INSTR-005"}


@dataclass
class ReportedProblem:
    customer: str
    description: str
    example_prompt: Optional[str] = None
    example_response: Optional[str] = None
    prior_attempts: list = field(default_factory=list)


@dataclass
class CoverageVerdict:
    verdict: str  # "fix_proposed" | "likely_platform_limitation"
    evidence: Optional[Finding] = None
    diff: Optional[str] = None


def _on_topic(finding: Finding, reported_problem: ReportedProblem) -> bool:
    """Cheap keyword overlap between a finding and what was reported.

    Deliberately simple: the semantic pass was already scoped to the
    reported behavior via the scope_hint, so this only needs to reject
    findings the LLM returned that clearly talk about something else.
    """
    haystack = f"{finding.message} {finding.suggestion}".lower()
    needles = [w for w in reported_problem.description.lower().split() if len(w) > 4]
    return any(n in haystack for n in needles)


def check_coverage(instructions_text: str, reported_problem: ReportedProblem) -> CoverageVerdict:
    """Determine whether ``instructions_text`` already holistically and
    correctly addresses ``reported_problem``.

    Runs the semantic pass scoped to the reported description. If it finds
    an on-topic finding that is a contradiction/gap (INSTR-001/002/003/005)
    touching the reported behavior, the instructions do not actually cover
    it -> fix_proposed. If it finds an on-topic finding proposing a NEW rule
    is missing for this behavior, that is also a fixable gap -> fix_proposed.
    Otherwise, if the semantic pass surfaces no on-topic defect at all, an
    existing rule must already address it correctly and the platform is
    just not honoring it -> likely_platform_limitation.
    """
    scope_hint = reported_problem.description
    semantic_findings = run_semantic_pass(instructions_text, scope_hint=scope_hint)

    on_topic = [f for f in semantic_findings if _on_topic(f, reported_problem)]

    contradictions = [f for f in on_topic if f.id in _CONTRADICTION_IDS]
    if contradictions:
        f = contradictions[0]
        return CoverageVerdict(verdict="fix_proposed", evidence=f, diff=f.suggestion or None)

    if on_topic:
        f = on_topic[0]
        return CoverageVerdict(verdict="fix_proposed", evidence=f, diff=f.suggestion or None)

    return CoverageVerdict(verdict="likely_platform_limitation", evidence=None, diff=None)
