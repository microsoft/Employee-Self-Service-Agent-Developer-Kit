# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Sync Runtime-Heuristics Docs

Copies the ESS runtime-heuristics docs (confirmed-runtime-heuristics.md and
pending-runtime-heuristics.md) from a local ESS reference checkout into
src/reference/ess-docs/runtime/ so the review lenses can consult them when
scoring reachability/severity. The destination is gitignored: these docs are not
part of this repository and are not committed.

The confirmed catalog is authoritative (e.g. the AI-orchestration "no data"
rule and the OnError dialog-termination rule cap certain findings at LOW). The
pending catalog is provisional — apply with caution.

The reference checkout is an internal source; external makers will not have it,
in which case this sync is skipped and severity is scored structurally.

Output and config lookup are anchored on the script location, so the sync can be
run from any directory; only auto-discovery consults the current directory.

Usage:
    python scripts/sync_runtime_heuristics.py
    python scripts/sync_runtime_heuristics.py --source <path-to-reference-checkout>
    python scripts/sync_runtime_heuristics.py --force   - overwrite existing files

The reference checkout is located, in order, via: --source, the
ESS_REFERENCE_SOURCE environment variable, or the `referenceSource` key in
.local/config.json (a maintained per-environment path that survives /setup
re-runs). A declared source that does not expose the docs is a hard stop. If no
source is declared (the external default), the sync is skipped and severity is
scored structurally from the finding-contract rubric alone (less calibrated, but
the review still runs).
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Anchor output and config lookup on the script location (not cwd), so a sync run
# from any directory writes where the review's coverage probe looks. Only
# auto-discovery consults the cwd.
_SKILL_ROOT = Path(__file__).resolve().parent.parent

# Within a reference checkout, the docs live under skills/docs/.
_DOCS_SUBPATH = Path("skills") / "docs"
_OUTPUT_DIR = _SKILL_ROOT / "src" / "reference" / "ess-docs" / "runtime"
_DOC_GLOB = "*runtime-heuristics.md"
_SOURCE_ENV = "ESS_REFERENCE_SOURCE"


def _config_reference_source() -> str | None:
    """The `referenceSource` path recorded in .local/config.json, or None.

    A missing or unreadable config is not an error here — it simply means no
    configured source (the default external case). Read directly, not via
    auth.load_config(), so a config schema change can never break a manual
    --source / env-var sync.
    """
    try:
        data = json.loads((_SKILL_ROOT / ".local" / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get("referenceSource") if isinstance(data, dict) else None
    return val if isinstance(val, str) and val.strip() else None


def _docs_dir(cand: Path) -> Path | None:
    """If `cand` (a checkout root or a docs folder) exposes the docs, return the
    docs folder; else None."""
    docs = cand if cand.name == "docs" else cand / _DOCS_SUBPATH
    return docs if docs.is_dir() and any(docs.glob(_DOC_GLOB)) else None


def find_source(explicit: str | None) -> Path | None:
    """Locate a local ESS reference checkout exposing skills/docs/*runtime-heuristics.md.

    Resolution order: --source, the ESS_REFERENCE_SOURCE env var, then the
    `referenceSource` key in .local/config.json. The path must expose the docs; a
    source that is set but does not is a hard stop (print an error and exit 1). If
    no source is declared, returns None — the external default, where the sync is
    skipped and severity is scored structurally. No specific repository name is
    assumed and no directory scan is performed.
    """
    declared = [
        ("--source", explicit),
        (_SOURCE_ENV, os.environ.get(_SOURCE_ENV)),
        ("referenceSource in .local/config.json", _config_reference_source()),
    ]
    for label, raw in declared:
        if not raw:
            continue
        base = Path(raw).expanduser().resolve()
        for cand in (base, base / _DOCS_SUBPATH, base.parent):
            docs = _docs_dir(cand)
            if docs is not None:
                return docs
        print(
            f"ERROR: {label} is set to '{raw}', but no skills/docs/{_DOC_GLOB} was "
            f"found there. Fix or clear it.",
            file=sys.stderr,
        )
        sys.exit(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ESS runtime-heuristics docs into the workspace.")
    parser.add_argument("--source", help="Path to a local ESS reference checkout (or its skills/docs folder).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    args = parser.parse_args()

    source = find_source(args.source)
    if source is None:
        print("No ESS reference checkout exposing skills/docs/*runtime-heuristics.md was found.")
        print("Provide one with --source <path>, set the ESS_REFERENCE_SOURCE environment")
        print("variable, or skip: the lenses will score severity from the finding-contract")
        print("rubric alone until the docs are available.")
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
