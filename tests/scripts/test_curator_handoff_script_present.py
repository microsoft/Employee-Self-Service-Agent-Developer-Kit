from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"


def test_handoff_validator_script_present():
    # The curate wrapper's Step 4 invokes this script; guard against rename/removal.
    assert (SOLUTION_ROOT / "scripts" / "eval_curator_handoff.py").is_file()
