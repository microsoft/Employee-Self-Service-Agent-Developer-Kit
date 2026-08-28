#!/usr/bin/env python3
"""
check_instruction_budget.py — Deterministically measure an agent's system
instructions against the character budget.

Hardening usually lengthens instructions. Copilot Studio constrains how long an
agent's instructions may be, so a hardening pass that does not measure will
happily produce instructions that cannot be saved — or that get silently
truncated, which is worse than not hardening at all (a truncated prompt can
lose the very guardrail that was just added).

Asking the agent to "count the characters" is model-dependent and was observed
to drift. This script removes that variable: it reads the ``instructions`` block
out of ``agent.mcs.yml``, measures it, compares it against the baseline copy so
the maker can see what a pass *added*, and emits a machine-readable verdict the
skill reads verbatim.

The limit is a **working assumption, not a verified platform constant**. It
defaults to 8000 and is overridable with ``--limit`` so a maker who knows their
real ceiling is not blocked by ours.

Usage (from solutions/ess-maker-skills/):
    python scripts/check_instruction_budget.py --agent employee-self-service-hr
    python scripts/check_instruction_budget.py --agent employee-self-service-hr --candidate .local/harden/candidate.txt
    python scripts/check_instruction_budget.py --agent employee-self-service-hr --limit 6000

Emits a human-readable summary plus a machine-readable block behind a sentinel:

    ###INSTRUCTION_BUDGET_JSON###{"verdict": "ok", "chars": 5996, ...}
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SENTINEL = "###INSTRUCTION_BUDGET_JSON###"

DEFAULT_LIMIT = 8000

# Headroom below which a maker should be warned that the next edit will not fit.
# Not a failure — a "you are nearly out of room" signal, so the skill can tell
# the maker to plan a removal before proposing another addition.
TIGHT_HEADROOM = 250

_AGENTS_DIR = Path(__file__).resolve().parent.parent / "workspace" / "agents"
_SKILL_ROOT = Path(__file__).resolve().parent.parent


def _resolve_agent_dir(value):
    """Resolve --agent from any of the forms a caller reasonably has to hand.

    ``.local/config.json`` stores ``agent.folder`` as a path relative to the
    solution root (``workspace/agents/<slug>``) and ``activeAgent`` as a bare
    slug. Accepting only one of them means whichever the caller reaches for
    first is a coin flip, and the failure is an unhelpful "not found" against a
    doubled-up path.
    """
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    relative_to_root = _SKILL_ROOT / value
    if relative_to_root.is_dir():
        return relative_to_root
    return _AGENTS_DIR / value


def _read_instructions(path):
    """Return (instructions, error). ``instructions`` is None when unreadable.

    A missing ``instructions:`` key and an empty one are different problems, so
    they return different messages — an empty block usually means extraction
    ran against an agent that was never configured, which is worth saying out
    loud rather than reporting as "0 characters, plenty of headroom".
    """
    if not path.is_file():
        return None, f"{path} not found"
    if yaml is None:
        return None, "PyYAML is not installed in this environment"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, f"{path.name} could not be parsed as YAML: {exc}"
    if not isinstance(data, dict):
        return None, f"{path.name} did not parse to a mapping"
    if "instructions" not in data:
        return None, f"{path.name} has no 'instructions' block"
    value = data["instructions"]
    if value is None:
        return None, f"{path.name} has an empty 'instructions' block"
    return str(value), None


def _verdict(chars, limit):
    if chars > limit:
        return "over"
    if limit - chars < TIGHT_HEADROOM:
        return "tight"
    return "ok"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure agent instructions against the character budget."
    )
    parser.add_argument("--agent", required=True,
                        help="agent folder name under workspace/agents/, or the "
                             "'agent.folder' path from .local/config.json")
    parser.add_argument(
        "--candidate",
        help="path to a file holding proposed replacement instructions "
             "(plain text, not YAML); measured instead of the live block",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"character ceiling (default {DEFAULT_LIMIT})")
    args = parser.parse_args(argv)

    if args.limit <= 0:
        print("--limit must be a positive number of characters", file=sys.stderr)
        print(_SENTINEL + json.dumps({"verdict": "unknown", "error": "invalid --limit"}))
        return 2

    agent_dir = _resolve_agent_dir(args.agent)
    live_path = agent_dir / "agent.mcs.yml"
    baseline_path = agent_dir / ".baseline" / "agent.mcs.yml"

    result = {
        "agent": args.agent,
        "limit": args.limit,
        "source": "candidate" if args.candidate else "working",
    }

    # Baseline is advisory context, never fatal: a freshly extracted agent has
    # one, but an agent mid-edit may not, and that must not block the measure.
    baseline_text, _ = _read_instructions(baseline_path)
    result["baseline_chars"] = len(baseline_text) if baseline_text is not None else None

    if args.candidate:
        cand = Path(args.candidate)
        if not cand.is_file():
            print(f"Candidate file not found: {cand}", file=sys.stderr)
            print(_SENTINEL + json.dumps({**result, "verdict": "unknown",
                                          "error": "candidate not found"}))
            return 2
        text = cand.read_text(encoding="utf-8")
        error = None
    else:
        text, error = _read_instructions(live_path)

    if text is None:
        print(f"Could not measure instructions: {error}", file=sys.stderr)
        print(_SENTINEL + json.dumps({**result, "verdict": "unknown", "error": error}))
        return 2

    chars = len(text)
    headroom = args.limit - chars
    result.update({
        "chars": chars,
        "headroom": headroom,
        "verdict": _verdict(chars, args.limit),
        "delta": (chars - result["baseline_chars"])
        if result["baseline_chars"] is not None else None,
    })

    print(f"Instructions: {chars} characters (limit {args.limit}, headroom {headroom})")
    if result["delta"] is not None:
        sign = "+" if result["delta"] >= 0 else ""
        print(f"Change vs. last extract: {sign}{result['delta']} characters")
    if result["verdict"] == "over":
        print(f"OVER BUDGET by {-headroom} characters — this will not fit.")
    elif result["verdict"] == "tight":
        print(f"Within budget, but only {headroom} characters remain.")

    print(_SENTINEL + json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
