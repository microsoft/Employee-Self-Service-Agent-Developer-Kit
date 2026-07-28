#!/usr/bin/env python3
"""
scan_globals.py — Detect dangling Global.* references in an agent's topics.

A "dangling" reference is a `Global.X` that a topic reads but that is never made
available anywhere in the agent — i.e. no topic writes it (`variable: Global.X`)
and no variable declares it. These are usually typos or references to a variable
that was renamed or removed.

Availability is resolved across the whole agent, because a Global written by one
topic (e.g. a shared system topic that populates a lookup table at runtime) is
available to every other topic. The reader/writer sets therefore have to be
aggregated across every topic — which is why this runs as a script rather than by
reading a single file.

Output is bounded: the dangling references (the anomalies) are printed to stdout,
capped, with a "+N more" tail. The full reader/writer/declared map is written to
--output as JSON when requested. This script only detects; it assigns no severity
and makes no judgement about whether a dangling reference is a real defect.

Usage:
    python scripts/scan_globals.py
    python scripts/scan_globals.py --agent employee-self-service-hr
    python scripts/scan_globals.py --topic servicenow-hrsd-get-user-cases
    python scripts/scan_globals.py --output results/globals.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A read: any Global.<name> token in an expression.
_READ_RE = re.compile(r"\bGlobal\.([A-Za-z_][A-Za-z0-9_]*)")
# A write: an action assigning to a Global variable (`variable: Global.<name>`).
_WRITE_RE = re.compile(r"\bvariable:\s*Global\.([A-Za-z_][A-Za-z0-9_]*)")
# A declaration: a variable definition file's `name: <name>`.
_DECL_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)

# Number of dangling references to list before collapsing into "+N more".
_MAX_LISTED = 20


def _read(path: Path) -> str | None:
    """Return the file text, or None if it could not be read (distinct from an
    empty file, which returns "")."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def scan_topics(topics_dir: Path) -> tuple[dict[str, list[str]], set[str], list[str]]:
    """Return (reads, writes, skipped) where reads maps Global name -> sorted site
    list (`file:line`), writes is the set of Global names assigned anywhere, and
    skipped lists topics that could not be read (so a read failure is never a
    silent clean bill)."""
    reads: dict[str, list[str]] = {}
    writes: set[str] = set()
    skipped: list[str] = []
    for topic in sorted(topics_dir.glob("*.mcs.yml")):
        text = _read(topic)
        if text is None:
            skipped.append(topic.name)
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for m in _WRITE_RE.finditer(line):
                writes.add(m.group(1))
            for m in _READ_RE.finditer(line):
                reads.setdefault(m.group(1), []).append(f"{topic.name}:{i}")
    return reads, writes, skipped


def scan_declarations(variables_dir: Path) -> set[str]:
    """Return the set of Global names declared as variables."""
    declared: set[str] = set()
    if not variables_dir.is_dir():
        return declared
    for var in variables_dir.glob("*.mcs.yml"):
        text = _read(var)
        if text is None:
            continue
        for m in _DECL_RE.finditer(text):
            declared.add(m.group(1))
    return declared


def find_dangling(
    reads: dict[str, list[str]], writes: set[str], declared: set[str]
) -> dict[str, list[str]]:
    """A Global is dangling if it is read but neither written nor declared."""
    available = writes | declared
    return {name: sites for name, sites in reads.items() if name not in available}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect dangling Global.* references in an agent's topics."
    )
    parser.add_argument(
        "--agent", "-a",
        help="Agent folder name under workspace/agents/. Auto-detected if only one exists.",
    )
    parser.add_argument(
        "--topic", "-t",
        help="Report only dangling references read by this topic (file stem). "
             "Availability is still resolved across the whole agent.",
    )
    parser.add_argument(
        "--module",
        help="Report only dangling references read by topics whose name starts with this "
             "module id (e.g. workday, servicenow-hrsd). Availability is still resolved "
             "across the whole agent. Ignored if --topic is given.",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write the full reads/writes/declared/dangling map to this JSON file.",
    )
    args = parser.parse_args()

    for _flag, _val in (("--agent", args.agent), ("--topic", args.topic), ("--module", args.module)):
        if _val and ("/" in _val or "\\" in _val or ".." in _val or Path(_val).is_absolute()):
            print(f"ERROR: invalid {_flag} '{_val}': must be a bare name, not a path.", file=sys.stderr)
            return 1

    repo_root = Path(__file__).parent.parent
    agents_dir = repo_root / "workspace" / "agents"
    if not agents_dir.is_dir():
        print(f"ERROR: no workspace/agents/ folder at {agents_dir}", file=sys.stderr)
        return 1

    if args.agent:
        agent_dir = agents_dir / args.agent
    else:
        candidates = [d for d in agents_dir.iterdir() if d.is_dir()]
        if len(candidates) != 1:
            print("ERROR: specify --agent (zero or multiple agents found).", file=sys.stderr)
            return 1
        agent_dir = candidates[0]
    if not (agent_dir / "topics").is_dir():
        print(f"ERROR: no topics/ folder in {agent_dir}", file=sys.stderr)
        return 1

    reads, writes, skipped = scan_topics(agent_dir / "topics")
    declared = scan_declarations(agent_dir / "variables")
    dangling = find_dangling(reads, writes, declared)

    if skipped:
        print(
            f"WARNING: {len(skipped)} topic(s) could not be read and were NOT analyzed "
            f"(a clean result does not cover them): {', '.join(sorted(skipped))}",
            file=sys.stderr,
        )

    if args.topic:
        stem = args.topic.removesuffix(".mcs.yml")
        dangling = {
            name: [s for s in sites if s.startswith(f"{stem}.mcs.yml:")]
            for name, sites in dangling.items()
        }
        dangling = {name: sites for name, sites in dangling.items() if sites}
    elif args.module:
        dangling = {
            name: [s for s in sites if s.split(":", 1)[0].startswith(args.module)]
            for name, sites in dangling.items()
        }
        dangling = {name: sites for name, sites in dangling.items() if sites}

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "reads": {k: sorted(v) for k, v in sorted(reads.items())},
                    "writes": sorted(writes),
                    "declared": sorted(declared),
                    "dangling": {k: sorted(v) for k, v in sorted(dangling.items())},
                    "skipped": sorted(skipped),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if not dangling:
        if skipped:
            print(
                f"No dangling Global.* references found in the topics that were read "
                f"({len(skipped)} skipped — see warning above; coverage is incomplete)."
            )
        else:
            print("No dangling Global.* references found.")
        return 0

    total = len(dangling)
    print(f"Dangling Global.* references ({total}):")
    for name in sorted(dangling)[:_MAX_LISTED]:
        sites = dangling[name]
        shown = ", ".join(sites[:3])
        extra = f" (+{len(sites) - 3} more sites)" if len(sites) > 3 else ""
        print(f"  Global.{name}  read at {shown}{extra}")
    if total > _MAX_LISTED:
        print(f"  +{total - _MAX_LISTED} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
