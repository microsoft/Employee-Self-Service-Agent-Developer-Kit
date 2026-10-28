# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit - skill builder packager.

Validates a finished agent skill with skill_builder_validate.py and packages it as the .zip that Copilot Studio
and Microsoft 365 Agent Builder accept: SKILL.md at the root of the archive, with its resource files and folders.
Used by src/skills/ess-da-ga-skill-builder. Makes no network calls.

Exit codes: 0 packaged, 1 validation errors or limits exceeded (nothing written), 2 bad arguments or input.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from skill_builder_validate import InputError, load_json, skill_files, validate

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024


def package_skill(skill: Path, out: Path, inventory: dict, expect: list[str] = ()) -> tuple[list[dict], int]:
    """Validate, then write the zip. Returns (findings, files written); writes nothing when there are errors."""
    report = validate([skill], inventory, None, expect)
    files = sorted(skill_files(skill), key=lambda p: p.relative_to(skill).as_posix())
    for path in files:
        if path.stat().st_size > MAX_FILE_BYTES:
            report.error(path, f"File is {path.stat().st_size // (1024 * 1024)} MB; Copilot allows 25 MB per file.")
    if any(f["level"] == "error" for f in report.findings):
        return report.findings, 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(skill).as_posix())
    if out.stat().st_size > MAX_ZIP_BYTES:
        out.unlink()
        report.error(out, "The .zip is over 50 MB, the most Copilot accepts; remove large resource files.")
        return report.findings, 0
    return report.findings, len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an agent skill and package it as a .zip with SKILL.md at the root.",
        epilog="Example: python scripts/ess-da-ga-skill-builder/skill_builder_package.py workspace/skills/hr-case-create --inventory ws/inventory.json "
               "--out workspace/skills/hr-case-create.zip\n"
               "Exit codes: 0 packaged, 1 errors (nothing written), 2 bad input.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skill", type=Path, help="skill folder containing SKILL.md")
    parser.add_argument("--inventory", required=True, type=Path, help="inventory JSON from skill_builder_inventory.py")
    parser.add_argument("--out", type=Path, help="zip to write (default: <skill folder>.zip next to the folder)")
    parser.add_argument("--expect", default="", metavar="OPS", help="operations the skill promises, as for the validator")
    args = parser.parse_args(argv)
    if not (args.skill / "SKILL.md").is_file():
        print(f"Error: no SKILL.md in {args.skill}.", file=sys.stderr)
        return 2
    out = args.out or args.skill.parent / f"{args.skill.name}.zip"
    try:
        inventory = load_json(args.inventory)
        findings, written = package_skill(args.skill, out, inventory,
                                          [op.strip() for op in args.expect.split(",") if op.strip()])
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(f"{f['level'].upper():7} {f['file']}: {f['message']}")
    if not written:
        print("Not packaged: fix the errors above first.")
        return 1
    print(f"Packaged {written} file(s) into {out.as_posix()} ({out.stat().st_size:,} bytes), SKILL.md at the root.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
