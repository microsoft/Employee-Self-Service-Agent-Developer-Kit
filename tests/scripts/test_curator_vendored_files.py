from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CURATOR = (
    REPO_ROOT
    / "solutions/ess-maker-skills/src/skills/evaluations/curate/curator"
)


def test_vendored_curator_files_present():
    assert (CURATOR / "curate-evals.md").is_file()
    assert (CURATOR / "check_eval_artifacts.py").is_file()


def test_vendored_skill_is_host_adapted():
    body = (CURATOR / "curate-evals.md").read_text(encoding="utf-8")
    # Host-override language distinguishes the adapted copy from the origin skill.
    assert "Host paths take precedence" in body
    assert "structuralValidatorPath" in body


def test_vendored_validator_is_the_structural_checker():
    src = (CURATOR / "check_eval_artifacts.py").read_text(encoding="utf-8")
    assert "--evaluation-folder" in src
    assert "EvaluationSet" in src
    # Guard against vendoring a similar-but-wrong validator: assert on markers
    # unique to this structural checker.
    assert "def check_folder(" in src
    assert "NOT the 8-dimension quality rubric" in src
