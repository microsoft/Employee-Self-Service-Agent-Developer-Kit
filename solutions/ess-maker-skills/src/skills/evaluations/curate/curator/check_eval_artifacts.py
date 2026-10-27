"""Structural validation for generated .mcs.yml evaluation artifacts.

No external API calls — checks shape only (required fields, kind values,
grader block presence). This is NOT the 8-dimension quality rubric (that
runs as an in-skill LLM judgment per the design doc); it just catches
malformed YAML before a human or the skill's validator looks at it.
"""
import argparse
import sys
from pathlib import Path

import yaml


def check_folder(folder: Path) -> list[str]:
    errors = []
    files = sorted(folder.glob("*.mcs.yml"))
    if not files:
        return [f"no .mcs.yml files found in {folder}"]

    parents = [f for f in files if _load(f).get("kind") == "EvaluationSet"]
    children = [f for f in files if _load(f).get("kind") in ("EvaluationData", "MultiTurnEvaluationCase")]

    if len(parents) != 1:
        errors.append(f"expected exactly 1 EvaluationSet parent file, found {len(parents)}")

    for f in parents:
        data = _load(f)
        if not data.get("graders"):
            errors.append(f"{f.name}: missing graders block")
        if not data.get("displayName"):
            errors.append(f"{f.name}: missing displayName")

    for f in children:
        data = _load(f)
        if data.get("kind") == "EvaluationData":
            rows = data.get("rows") or []
            if not rows:
                errors.append(f"{f.name}: EvaluationData has no rows")
            for row in rows:
                if not row.get("input"):
                    errors.append(f"{f.name}: row missing input")
                if "expectedOutput" not in row:
                    errors.append(f"{f.name}: row missing expectedOutput")
        if not data.get("extensionData", {}).get("displayOrder"):
            errors.append(f"{f.name}: missing extensionData.displayOrder")

    return errors


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-folder", required=True)
    args = parser.parse_args()

    errors = check_folder(Path(args.evaluation_folder))
    if errors:
        print(f"FAIL — {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASS — artifact structure OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
