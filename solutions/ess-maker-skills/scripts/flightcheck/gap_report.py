# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Report FlightCheck gaps for human review. Never edits guidance.

Run from ``solutions/ess-maker-skills/scripts``::

    python -m flightcheck.gap_report [--base origin/main] [--strict]

Findings (warnings only; exit code is 0 unless ``--strict``):

* A registered check ID that no file under ``tests/`` mentions (no test evidence).
* A documentation source cited by ``da_inventory.csv`` that is missing from
  ``doc-sources.csv``, or a manifest row with an invalid ``applies_to``.
* With ``--base``: guidance (``da_inventory.csv`` or ``ess-docs/flightcheck``)
  changed without a matching ``doc-sources.csv`` change.

A mention in tests is a coarse signal, not proof that every outcome is covered.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import subprocess
import sys

from . import registry

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
KIT_ROOT = SCRIPTS_DIR.parent
REPO_ROOT = KIT_ROOT.parents[1]
INVENTORY = Path(__file__).with_name("da_inventory.csv")
DOCS_DIR = KIT_ROOT / "src" / "reference" / "ess-docs" / "flightcheck"
MANIFEST = DOCS_DIR / "doc-sources.csv"
TESTS_DIR = REPO_ROOT / "tests"
APPLIES_TO = {"CA", "DA", "both", "unrecorded"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def untested_checks(test_text: str) -> list[str]:
    missing = []
    for spec in registry.list_checkpoints():
        needle = f"{spec.key}-" if spec.is_family else spec.key
        if needle not in test_text:
            missing.append(spec.key)
    return missing


def manifest_problems(manifest: list[dict[str, str]], inventory: list[dict[str, str]]) -> list[str]:
    problems = []
    known = {row["source"] for row in manifest}
    cited = {
        row["documentation"].split("#")[0]
        for row in inventory if row.get("documentation")
    }
    problems += [f"Cited by da_inventory.csv but not in doc-sources.csv: {url}" for url in sorted(cited - known)]
    problems += [
        f"doc-sources.csv row '{row['source']}' has applies_to='{row['applies_to']}' "
        f"(expected one of {sorted(APPLIES_TO)})"
        for row in manifest if row["applies_to"] not in APPLIES_TO
    ]
    return problems


def changed_without_manifest(changed_paths: list[str]) -> list[str]:
    guidance_prefixes = (
        "solutions/ess-maker-skills/scripts/flightcheck/da_inventory.csv",
        "solutions/ess-maker-skills/src/reference/ess-docs/flightcheck/",
    )
    manifest_path = "solutions/ess-maker-skills/src/reference/ess-docs/flightcheck/doc-sources.csv"
    guidance = [p for p in changed_paths if p.startswith(guidance_prefixes) and p != manifest_path]
    if guidance and manifest_path not in changed_paths:
        return [
            "Guidance changed without a doc-sources.csv update (record source version and "
            f"CA/DA applicability): {', '.join(sorted(guidance))}"
        ]
    return []


def _git_changed(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def collect(base: str | None) -> list[str]:
    test_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in TESTS_DIR.rglob("*.py")
    )
    findings = [f"No test mentions check {key}" for key in untested_checks(test_text)]
    findings += manifest_problems(_read_csv(MANIFEST), _read_csv(INVENTORY))
    if base:
        findings += changed_without_manifest(_git_changed(base))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", help="Git ref to diff against (e.g. origin/main).")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when findings exist.")
    args = parser.parse_args(argv)
    findings = collect(args.base)
    for finding in findings:
        print(f"::warning::{finding}")
    print(f"{len(findings)} gap(s) found for review.")
    return 1 if findings and args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
