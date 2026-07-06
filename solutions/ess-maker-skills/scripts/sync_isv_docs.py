# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Sync ISV Reference Docs

Copies the ESS ISV reference docs (isv-*.md) from a local ESSVivaCopilot
checkout into src/reference/ess-docs/isv/ so the review skill can read them
from inside the workspace. The destination is gitignored: these docs are not
part of this repository and are not committed.

Must be run from solutions/ess-maker-skills/ (paths are relative).

Usage:
    cd solutions/ess-maker-skills
    python scripts/sync_isv_docs.py
    python scripts/sync_isv_docs.py --source <path-to-ESSVivaCopilot>
    python scripts/sync_isv_docs.py --force   - overwrite existing files

If no ESSVivaCopilot checkout is found and none is given with --source, the
script prints where it looked and exits without error, leaving ISV conformance
checks to degrade gracefully.
"""

import argparse
import sys
from pathlib import Path

# isv-*.md live here inside an ESSVivaCopilot checkout.
_DOCS_SUBPATH = Path("skills") / "docs"
_OUTPUT_DIR = Path("src") / "reference" / "ess-docs" / "isv"


def find_source(explicit: str | None) -> Path | None:
    """Locate an ESSVivaCopilot checkout containing skills/docs/isv-*.md."""
    candidates: list[Path] = []
    if explicit:
        p = Path(explicit).expanduser().resolve()
        # Accept either the repo root or the docs folder directly.
        candidates += [p, p / _DOCS_SUBPATH, p.parent]
    # Walk up from the current directory looking for a sibling ESSVivaCopilot.
    here = Path.cwd().resolve()
    for ancestor in [here, *here.parents]:
        candidates.append(ancestor / "ESSVivaCopilot")
    for cand in candidates:
        docs = cand if cand.name == "docs" else cand / _DOCS_SUBPATH
        if docs.is_dir() and any(docs.glob("isv-*.md")):
            return docs
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ESS ISV reference docs into the workspace.")
    parser.add_argument("--source", help="Path to an ESSVivaCopilot checkout (or its skills/docs folder).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = parser.parse_args()

    source = find_source(args.source)
    if source is None:
        print("No ESSVivaCopilot checkout with skills/docs/isv-*.md was found.")
        print("Looked for an 'ESSVivaCopilot' folder among this directory's ancestors.")
        print("Pass one explicitly with --source <path>, or skip: ISV conformance will")
        print("be reported as not checked until the reference docs are available.")
        return 0

    out_dir = _OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    isv_docs = sorted(source.glob("isv-*.md"))
    copied = 0
    skipped = 0
    for doc in isv_docs:
        dest = out_dir / doc.name
        if dest.exists() and not args.force:
            print(f"  SKIP {dest} (exists, use --force to overwrite)")
            skipped += 1
            continue
        dest.write_text(doc.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  {doc.name} -> {dest}")
        copied += 1

    print(f"\nDone. {copied} copied, {skipped} skipped, from {source}")
    print(f"Output: {out_dir}/ (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
