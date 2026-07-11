#!/usr/bin/env python3
"""
check_isv_coverage.py — Deterministically decide ISV field-conformance coverage.

The review's ISV field-conformance check (Step 6) can only run when the reference
doc for the in-scope topic's *specific backend* is present at
src/reference/ess-docs/isv/isv-<backend>.md. Those docs are synced from an ESS
reference source and are gitignored, so they may be absent for an external maker.

Deciding presence by asking the agent to "run a Test-Path" is model-dependent: it
was observed to be skipped mid-flow on some models, producing a *false* coverage
note (claiming a present doc was absent, or vice versa). This script removes that
variable: it resolves each in-scope topic's backend from its scenarioName and
checks the doc's presence via a path anchored on __file__ (cwd-immune), then emits
a machine-readable verdict the skill reads verbatim into the coverage note.

The check is presence-only — it does not read or judge the doc's contents.

Usage (from solutions/ess-maker-skills/):
    python scripts/check_isv_coverage.py --agent employee-self-service-hr --topic workday-get-basecompensation
    python scripts/check_isv_coverage.py --agent employee-self-service-hr --module workday
    python scripts/check_isv_coverage.py --agent employee-self-service-hr            # whole agent

Emits a human-readable summary plus a machine-readable block behind a sentinel:

    ###ISV_COVERAGE_JSON###{"mode": "reduced", "backends": [...], ...}
"""

import argparse
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SENTINEL = "###ISV_COVERAGE_JSON###"
# Every backend reference in a topic is an `msdyn_...` identifier — either a
# scenarioName the UI topic passes (Workday: msdyn_HRWorkdayHCMEmployee...) or a
# `dialog:` reference into the shared system topic (ServiceNow:
# msdyn_...topic.ServiceNowHRSDSystemUpdateCase). Collect all of them, then match
# the backend token against each — so both the direct-scenario (Workday) and the
# delegate-to-system-topic (ServiceNow) shapes are recognized.
_MSDYN_REF_RE = re.compile(r"msdyn_[\w.]+")

# Backend identity token found inside an `msdyn_...` reference. Tokens are chosen
# to appear in BOTH the scenarioName and the system-topic dialog form and not to
# collide with each other. `Workday` (not `WorkdayHCM`) because the Workday system
# dialog is `WorkdaySystemGetCommonExecution`, which omits the HCM qualifier.
_BACKEND_BY_TOKEN = (
    ("ServiceNowHRSD", ("servicenow-hrsd", "isv-servicenow-hrsd.md")),
    ("ServiceNowITSM", ("servicenow-itsm", "isv-servicenow-itsm.md")),
    ("SuccessFactors", ("successfactors", "isv-successfactors-hcm.md")),
    ("Workday", ("workday", "isv-workday-hcm.md")),
)

_ISV_DIR = Path(__file__).resolve().parent.parent / "src" / "reference" / "ess-docs" / "isv"


def _reject_pathy(flag: str, value: str) -> None:
    if value and ("/" in value or "\\" in value or ".." in value or Path(value).is_absolute()):
        print(f"ERROR: invalid {flag} '{value}': must be a bare name, not a path.", file=sys.stderr)
        sys.exit(1)


def backend_of_topic(topic_path: Path) -> "tuple[str, str] | None":
    """Return (backend_id, doc_filename) for a topic, or None if it calls no ISV backend."""
    try:
        text = topic_path.read_text(encoding="utf-8")
    except OSError:
        return None
    refs = _MSDYN_REF_RE.findall(text)
    if not refs:
        return None
    for token, backend in _BACKEND_BY_TOKEN:
        if any(token in ref for ref in refs):
            return backend
    return None


def in_scope_topics(topics_dir: Path, topic: "str | None", module: "str | None") -> list[Path]:
    if topic:
        stem = topic[:-len(".mcs.yml")] if topic.endswith(".mcs.yml") else topic
        p = topics_dir / f"{stem}.mcs.yml"
        return [p] if p.is_file() else []
    files = sorted(topics_dir.glob("*.mcs.yml"))
    if module:
        files = [f for f in files if f.name.startswith(module)]
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide ISV field-conformance coverage for a review scope.")
    parser.add_argument("--agent", "-a", help="Agent folder under workspace/agents/. Auto-detected if only one.")
    parser.add_argument("--topic", "-t", help="Single topic stem.")
    parser.add_argument("--module", help="Restrict to topics whose name starts with this module id. Ignored if --topic is given.")
    args = parser.parse_args()

    for flag, val in (("--agent", args.agent), ("--topic", args.topic), ("--module", args.module)):
        _reject_pathy(flag, val)

    repo_root = Path(__file__).resolve().parent.parent
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
    topics_dir = agent_dir / "topics"
    if not topics_dir.is_dir():
        print(f"ERROR: no topics/ folder in {agent_dir}", file=sys.stderr)
        return 1

    topics = in_scope_topics(topics_dir, args.topic, args.module)

    # Resolve each in-scope backend and its doc presence (present-only check).
    backends: dict[str, dict] = {}
    for tp in topics:
        b = backend_of_topic(tp)
        if b is None:
            continue
        backend_id, doc_name = b
        present = (_ISV_DIR / doc_name).is_file()
        entry = backends.setdefault(backend_id, {"doc": doc_name, "present": present, "topics": []})
        entry["topics"].append(tp.name)

    missing = sorted(bid for bid, e in backends.items() if not e["present"])
    covered = sorted(bid for bid, e in backends.items() if e["present"])
    mode = "reduced" if missing else "full"

    # Human-readable summary.
    if not backends:
        print("No in-scope topic calls an ISV backend — ISV conformance is not applicable (full coverage).")
    else:
        for bid in sorted(backends):
            e = backends[bid]
            state = "present" if e["present"] else "MISSING"
            print(f"  {bid}: {e['doc']} {state} ({len(e['topics'])} topic(s))")
        if mode == "reduced":
            print(f"Coverage: REDUCED — missing reference doc(s) for: {', '.join(missing)}")
        else:
            print("Coverage: FULL — every in-scope backend has its reference doc.")

    verdict = {
        "mode": mode,
        "missing_backends": missing,
        "covered_backends": covered,
        "isv_dir": str(_ISV_DIR),
        "backends": {bid: {"doc": e["doc"], "present": e["present"], "topics": e["topics"]}
                     for bid, e in backends.items()},
    }
    print(_SENTINEL + json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
