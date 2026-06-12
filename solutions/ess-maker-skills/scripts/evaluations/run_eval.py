#!/usr/bin/env python3
"""
run_eval.py — Run evaluation test sets (structural validation).

Reads eval YAML files from the agent's evaluations/ folder, validates their
structure, and reports results. Does not yet run against a live agent — that
requires the full AgentEvaluator pipeline.

Usage:
    python scripts/evaluations/run_eval.py
    python scripts/evaluations/run_eval.py --category topic-triggering
"""

import argparse
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from auth import load_config


def validate_eval_files(eval_dir, category=None):
    """Validate evaluation YAML files for structural correctness."""
    if not os.path.isdir(eval_dir):
        return {"error": f"Evaluations directory not found: {eval_dir}", "passed": 0, "failed": 0}

    results = []
    passed = 0
    failed = 0

    for fname in sorted(os.listdir(eval_dir)):
        if not fname.endswith(".mcs.yml"):
            continue
        if category and not fname.startswith(category):
            continue

        fpath = os.path.join(eval_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            results.append({"file": fname, "status": "FAIL", "error": f"YAML parse error: {e}"})
            failed += 1
            continue

        kind = data.get("kind")
        if kind == "EvaluationSet":
            graders = data.get("graders", [])
            if not graders:
                results.append({"file": fname, "status": "FAIL", "error": "Missing graders"})
                failed += 1
            else:
                results.append({"file": fname, "status": "PASS", "kind": kind, "graderCount": len(graders)})
                passed += 1

        elif kind == "EvaluationData":
            rows = data.get("rows", [])
            if not rows:
                results.append({"file": fname, "status": "FAIL", "error": "No rows in evaluation data"})
                failed += 1
            else:
                empty_inputs = sum(1 for r in rows if not r.get("input", "").strip())
                empty_outputs = sum(1 for r in rows if not r.get("expectedOutput", "").strip())
                status = "PASS" if empty_inputs == 0 and empty_outputs == 0 else "WARN"
                results.append({
                    "file": fname,
                    "status": status,
                    "kind": kind,
                    "rowCount": len(rows),
                    "emptyInputs": empty_inputs,
                    "emptyExpectedOutputs": empty_outputs,
                })
                if status == "PASS":
                    passed += 1
                else:
                    passed += 1  # WARN still counts as pass
        else:
            results.append({"file": fname, "status": "SKIP", "reason": f"Unknown kind: {kind}"})

    return {"passed": passed, "failed": failed, "results": results}


def main():
    parser = argparse.ArgumentParser(description="Run evaluation test sets")
    parser.add_argument("--category", help="Only validate a specific category")
    args = parser.parse_args()

    config = load_config()
    agent_config = config.get("agent") or {}
    agent_dir = agent_config.get("folder", "")
    if agent_dir and not os.path.isabs(agent_dir):
        agent_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), agent_dir)

    eval_dir = os.path.join(agent_dir, "evaluations")
    result = validate_eval_files(eval_dir, args.category)

    # Write results to workspace
    results_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "workspace", "evaluations"
    )
    os.makedirs(results_dir, exist_ok=True)
    results_path = os.path.join(results_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    result["resultsPath"] = results_path
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
