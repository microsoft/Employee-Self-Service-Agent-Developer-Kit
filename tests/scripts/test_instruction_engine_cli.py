import json

import pytest

from instruction_engine import __main__ as cli


_INSTRUCTIONS = """
#Core identity
You are an HR assistant.

#Formatting rules
Always offer to help with anything else at the end of every response.
"""


@pytest.fixture(autouse=True)
def _stub_semantic_pass(monkeypatch):
    monkeypatch.setattr(
        "instruction_engine.engine.run_semantic_pass",
        lambda instructions_text, scope_hint=None: [],
    )


def _write_instructions_file(tmp_path, text=_INSTRUCTIONS):
    path = tmp_path / "instructions.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _write_problems_file(tmp_path, problems):
    path = tmp_path / "problems.json"
    path.write_text(json.dumps(problems), encoding="utf-8")
    return path


def test_cli_text_output_sweep_only(tmp_path, capsys):
    instructions_path = _write_instructions_file(tmp_path)

    exit_code = cli.main(["--instructions", str(instructions_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "AP" in out or "COV" in out


def test_cli_json_output_is_parseable(tmp_path, capsys):
    instructions_path = _write_instructions_file(tmp_path)

    exit_code = cli.main(["--instructions", str(instructions_path), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "findings" in payload
    assert "coverage_verdicts" in payload


def test_cli_with_problems_file_emits_coverage_verdicts(tmp_path, capsys, monkeypatch):
    from instruction_engine.coverage_check import CoverageVerdict

    monkeypatch.setattr(
        "instruction_engine.engine.check_coverage",
        lambda instructions_text, reported_problem: CoverageVerdict(verdict="fix_proposed"),
    )

    instructions_path = _write_instructions_file(tmp_path)
    problems_path = _write_problems_file(tmp_path, [
        {"customer": "Acme", "description": "agent keeps offering unsolicited help"}
    ])

    exit_code = cli.main([
        "--instructions", str(instructions_path),
        "--problems", str(problems_path),
        "--json",
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["coverage_verdicts"]) == 1
    assert payload["coverage_verdicts"][0]["verdict"] == "fix_proposed"


def test_cli_fail_on_error_sets_nonzero_exit_when_warn_finding_present(tmp_path, capsys, monkeypatch):
    from instruction_engine.models import Finding

    monkeypatch.setattr(
        "instruction_engine.engine.run_regex_rules",
        lambda prompt: [
            Finding(id="AP001", severity="warn", category="antipattern",
                    section="(document)", line=1, message="stub warn finding",
                    suggestion="", source="regex"),
        ],
    )

    instructions_path = _write_instructions_file(tmp_path)

    exit_code = cli.main([
        "--instructions", str(instructions_path),
        "--fail-on", "warn",
        "--json",
    ])

    assert exit_code == 1


def test_cli_fail_on_error_zero_exit_when_no_findings(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("instruction_engine.engine.run_regex_rules", lambda prompt: [])

    instructions_path = _write_instructions_file(tmp_path)

    exit_code = cli.main([
        "--instructions", str(instructions_path),
        "--fail-on", "error",
        "--json",
    ])

    assert exit_code == 0


def test_cli_missing_instructions_file_errors_cleanly(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.txt"

    exit_code = cli.main(["--instructions", str(missing)])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "does_not_exist" in err
