"""CLI entry point for the instruction hardening engine.

Usage:
    python -m instruction_engine --instructions FILE [--problems FILE] [--json] [--fail-on error|warn|review]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .coverage_check import ReportedProblem
from .engine import run

_SEVERITY_RANK = {"review": 0, "warn": 1, "error": 2}


def _load_problems(path: Path) -> list:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        ReportedProblem(
            customer=item["customer"],
            description=item["description"],
            example_prompt=item.get("example_prompt"),
            example_response=item.get("example_response"),
            prior_attempts=item.get("prior_attempts", []),
        )
        for item in raw
    ]


def _render_text(result) -> str:
    lines = []
    if not result.findings:
        lines.append("No findings.")
    for f in result.findings:
        lines.append(f"[{f.severity.upper()}] {f.id} ({f.source}) — {f.section}: {f.message}")
        if f.suggestion:
            lines.append(f"    suggestion: {f.suggestion}")
    if result.coverage_verdicts:
        lines.append("")
        lines.append("Coverage verdicts:")
        for v in result.coverage_verdicts:
            lines.append(f"  - {v.verdict}")
            if v.evidence:
                lines.append(f"    evidence: {v.evidence.id} — {v.evidence.message}")
    return "\n".join(lines)


def _render_json(result) -> str:
    payload = {
        "findings": [dataclasses.asdict(f) for f in result.findings],
        "coverage_verdicts": [
            {
                "verdict": v.verdict,
                "evidence": dataclasses.asdict(v.evidence) if v.evidence else None,
                "diff": v.diff,
            }
            for v in result.coverage_verdicts
        ],
    }
    return json.dumps(payload, indent=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="instruction_engine")
    parser.add_argument("--instructions", required=True, type=Path)
    parser.add_argument("--problems", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fail-on", choices=["error", "warn", "review"], default=None)
    args = parser.parse_args(argv)

    if not args.instructions.is_file():
        print(f"error: instructions file not found: {args.instructions}", file=sys.stderr)
        return 2

    instructions_text = args.instructions.read_text(encoding="utf-8")
    problems = _load_problems(args.problems) if args.problems else None

    result = run(instructions_text, problems=problems)

    output = _render_json(result) if args.as_json else _render_text(result)
    print(output)

    if args.fail_on:
        threshold = _SEVERITY_RANK[args.fail_on]
        if any(_SEVERITY_RANK.get(f.severity, 0) >= threshold for f in result.findings):
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
