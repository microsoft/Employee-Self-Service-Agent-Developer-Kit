import json
from pathlib import Path

import pytest

from instruction_engine.coverage_check import ReportedProblem, check_coverage

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _reported_problem_from_fixture(data):
    return ReportedProblem(
        customer=data["customer"],
        description=data["description"],
        example_prompt=data.get("example_prompt"),
        example_response=data.get("example_response"),
        prior_attempts=data.get("prior_attempts", []),
    )


def _no_findings_client(prompt):
    # The semantic pass, scoped to the reported behavior, finds nothing
    # on-topic — meaning the existing rule already covers it correctly and
    # the platform just isn't honoring it.
    return "[]"


def test_blackstone_scenario_1_yields_likely_platform_limitation(monkeypatch):
    data = _load_fixture("blackstone_scenario_1.json")
    reported_problem = _reported_problem_from_fixture(data)

    monkeypatch.setattr(
        "instruction_engine.coverage_check.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )

    verdict = check_coverage(data["instructions_text"], reported_problem)
    assert verdict.verdict == "likely_platform_limitation"
    assert verdict.evidence is None


def test_blackstone_scenario_2_yields_likely_platform_limitation(monkeypatch):
    data = _load_fixture("blackstone_scenario_2.json")
    reported_problem = _reported_problem_from_fixture(data)

    monkeypatch.setattr(
        "instruction_engine.coverage_check.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )

    verdict = check_coverage(data["instructions_text"], reported_problem)
    assert verdict.verdict == "likely_platform_limitation"
    assert verdict.evidence is None


def test_on_topic_contradiction_yields_fix_proposed(monkeypatch):
    from instruction_engine.models import Finding

    data = _load_fixture("blackstone_scenario_2.json")
    reported_problem = _reported_problem_from_fixture(data)

    contradiction = Finding(
        id="INSTR-001", severity="error", category="contradiction",
        section="Workday benefits topic (read-only)", line=0,
        message="Contradiction: topic says read-only but also references 'update' capability elsewhere.",
        suggestion="Remove the conflicting reference to update capability.",
        source="semantic",
    )

    monkeypatch.setattr(
        "instruction_engine.coverage_check.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [contradiction],
    )

    verdict = check_coverage(data["instructions_text"], reported_problem)
    assert verdict.verdict == "fix_proposed"
    assert verdict.evidence is contradiction
    assert verdict.diff == contradiction.suggestion


def test_on_topic_gap_yields_fix_proposed(monkeypatch):
    from instruction_engine.models import Finding

    data = _load_fixture("blackstone_scenario_1.json")
    reported_problem = _reported_problem_from_fixture(data)

    gap = Finding(
        id="INSTR-013", severity="warn", category="ungrounded-response",
        section="Citation scoping", line=0,
        message="Citation scoping does not constrain the 'More references' panel, only inline citations.",
        suggestion="Add a rule suppressing the More references panel for out-of-scope articles.",
        source="semantic",
    )

    monkeypatch.setattr(
        "instruction_engine.coverage_check.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [gap],
    )

    verdict = check_coverage(data["instructions_text"], reported_problem)
    assert verdict.verdict == "fix_proposed"
    assert verdict.evidence is gap
