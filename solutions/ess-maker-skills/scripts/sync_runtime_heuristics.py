# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Sync Runtime-Heuristics Docs

Copies the ESS runtime-heuristics docs (confirmed-runtime-heuristics.md and
pending-runtime-heuristics.md) from a local ESSVivaCopilot checkout into
src/reference/ess-docs/runtime/ so the review lenses can consult them when
scoring reachability/severity. The destination is gitignored: these docs are not
part of this repository and are not committed.

The confirmed catalog is authoritative (e.g. the AI-orchestration "no data"
rule and the OnError dialog-termination rule cap certain findings at LOW). The
pending catalog is provisional — apply with caution.

Must be run from solutions/ess-maker-skills/ (paths are relative).

Usage:
    cd solutions/ess-maker-skills
    python scripts/sync_runtime_heuristics.py
    python scripts/sync_runtime_heuristics.py --source <path-to-ESSVivaCopilot>
    python scripts/sync_runtime_heuristics.py --force   - overwrite existing files

If no ESSVivaCopilot checkout is found and none is given with --source, the
script prints where it looked and exits without error, leaving the lenses to
score severity from the finding-contract rubric alone (less calibrated, but the
review still runs).
"""

import argparse
import sys
from pathlib import Path

# The runtime-heuristics docs live here inside an ESSVivaCopilot checkout.
_DOCS_SUBPATH = Path("skills") / "docs"
_OUTPUT_DIR = Path("src") / "reference" / "ess-docs" / "runtime"
_DOC_GLOB = "*runtime-heuristics.md"


def find_source(explicit: str | None) -> Path | None:
    """Locate an ESSVivaCopilot checkout containing skills/docs/*runtime-heuristics.md."""
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
        if docs.is_dir() and any(docs.glob(_DOC_GLOB)):
            return docs
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ESS runtime-heuristics docs into the workspace.")
    parser.add_argument("--source", help="Path to an ESSVivaCopilot checkout (or its skills/docs folder).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = parser.parse_args()

    source = find_source(args.source)
    if source is None:
        print("No ESSVivaCopilot checkout with skills/docs/*runtime-heuristics.md was found.")
        print("Looked for an 'ESSVivaCopilot' folder among this directory's ancestors.")
        print("Pass one explicitly with --source <path>, or skip: the lenses will score")
        print("severity from the finding-contract rubric alone until the docs are available.")
        return 0

    out_dir = _OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = sorted(source.glob(_DOC_GLOB))
    copied = 0
    skipped = 0
    for doc in docs:
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
