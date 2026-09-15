import pytest

from instruction_engine.engine import EngineResult, run
from instruction_engine.coverage_check import ReportedProblem
from instruction_engine.models import Finding


_INSTRUCTIONS = """
#Core identity
You are an HR assistant.

#Formatting rules
Always offer to help with anything else at the end of every response.
"""


def _stub_semantic_client(prompt):
    return "[]"


def test_run_without_problems_returns_regex_and_semantic_findings(monkeypatch):
    monkeypatch.setattr(
        "instruction_engine.engine.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )

    result = run(_INSTRUCTIONS)

    assert isinstance(result, EngineResult)
    assert isinstance(result.findings, list)
    assert result.coverage_verdicts == []


def test_run_without_problems_includes_regex_findings(monkeypatch):
    monkeypatch.setattr(
        "instruction_engine.engine.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )

    result = run(_INSTRUCTIONS)

    assert any(f.source == "regex" for f in result.findings)


def test_run_merges_semantic_findings(monkeypatch):
    semantic_finding = Finding(
        id="INSTR-001", severity="warn", category="over-commitment",
        section="Formatting rules", line=0,
        message="Always offering help conflicts with scoped topics.",
        suggestion="Remove the blanket offer.", source="semantic",
    )
    monkeypatch.setattr(
        "instruction_engine.engine.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [semantic_finding],
    )

    result = run(_INSTRUCTIONS)

    assert semantic_finding in result.findings


def test_run_with_problems_runs_coverage_check_per_problem(monkeypatch):
    from instruction_engine.coverage_check import CoverageVerdict

    monkeypatch.setattr(
        "instruction_engine.engine.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )
    monkeypatch.setattr(
        "instruction_engine.engine.check_coverage",
        lambda instructions_text, reported_problem: CoverageVerdict(
            verdict="likely_platform_limitation",
        ),
    )

    problem = ReportedProblem(customer="Acme", description="agent keeps doing X")
    result = run(_INSTRUCTIONS, problems=[problem])

    assert len(result.coverage_verdicts) == 1
    assert result.coverage_verdicts[0].verdict == "likely_platform_limitation"


def test_run_with_multiple_problems_returns_one_verdict_each(monkeypatch):
    from instruction_engine.coverage_check import CoverageVerdict

    monkeypatch.setattr(
        "instruction_engine.engine.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )

    calls = []

    def _fake_check_coverage(instructions_text, reported_problem):
        calls.append(reported_problem.description)
        return CoverageVerdict(verdict="fix_proposed")

    monkeypatch.setattr("instruction_engine.engine.check_coverage", _fake_check_coverage)

    problems = [
        ReportedProblem(customer="Acme", description="problem one"),
        ReportedProblem(customer="Acme", description="problem two"),
    ]
    result = run(_INSTRUCTIONS, problems=problems)

    assert calls == ["problem one", "problem two"]
    assert len(result.coverage_verdicts) == 2
