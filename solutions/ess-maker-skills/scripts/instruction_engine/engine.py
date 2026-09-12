"""Orchestration entry point: run the regex + semantic sweep over instruction
text, and optionally triage a list of reported problems via coverage-check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .coverage_check import CoverageVerdict, ReportedProblem, check_coverage
from .models import Finding
from .parser import parse
from .regex_rules import run_rules as run_regex_rules
from .semantic_rules.runner import run_semantic_pass


@dataclass
class EngineResult:
    findings: list
    coverage_verdicts: list = field(default_factory=list)


def run(instructions_text: str, problems: Optional[list] = None) -> EngineResult:
    """Run the full instruction-hardening sweep.

    Always runs the regex pass and an unscoped semantic pass over
    ``instructions_text``. If ``problems`` (a list of ``ReportedProblem``) is
    given, also runs ``check_coverage`` for each one, in order.
    """
    prompt = parse(instructions_text)
    findings = list(run_regex_rules(prompt))
    findings.extend(run_semantic_pass(instructions_text))

    coverage_verdicts = []
    for problem in problems or []:
        coverage_verdicts.append(check_coverage(instructions_text, problem))

    return EngineResult(findings=findings, coverage_verdicts=coverage_verdicts)
