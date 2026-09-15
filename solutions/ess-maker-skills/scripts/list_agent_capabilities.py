#!/usr/bin/env python3
"""
list_agent_capabilities.py — Summarize what an agent can actually *do*.

The riskiest change an instruction-hardening pass can make is prohibiting
something the agent genuinely supports: the instructions read as more
responsible, and the regression only shows up later as users being turned away.
Avoiding that requires knowing the agent's real capabilities.

Reading the topic files by hand does not scale — a stock ESS agent ships ~36 of
them, several over 40 KB of generated flow detail — so in practice the check
gets skipped or done from a sample, and two runs reach different conclusions.
This script reduces the tree to one screen: per topic, what the model is told it
handles (``modelDescription``), the trigger phrases if any, and whether it
merely replies or invokes a flow, connector, or HTTP call.

Usage (from solutions/ess-maker-skills/):
    python scripts/list_agent_capabilities.py --agent employee-self-service-preview

Emits a human-readable table plus a machine-readable block behind a sentinel:

    ###AGENT_CAPABILITIES_JSON###{"topics": [...], "workflows": [...]}
"""

import argparse
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SENTINEL = "###AGENT_CAPABILITIES_JSON###"

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_AGENTS_DIR = _SKILL_ROOT / "workspace" / "agents"

# Action kinds that mean the topic reaches a real system rather than just
# replying. The distinction is the whole point: "can answer about X" and "can
# do X" need different instruction rules.
_ACTING_KINDS = {
    "InvokeFlowAction": "flow",
    "InvokeConnectorAction": "connector",
    "HttpRequestAction": "http",
    "InvokeAIBuilderModelAction": "ai-builder",
    "SearchAndSummarizeContent": "knowledge-search",
    "BeginDialog": "calls-another-topic",
}
_MAX_DESCRIPTION = 320

_KIND_RE = re.compile(r"^\s*(?:-\s*)?kind:\s*([A-Za-z0-9_.]+)\s*$", re.MULTILINE)


def _resolve_agent_dir(value):
    """Accept a bare slug, a solution-root-relative path, or an absolute path.

    ``.local/config.json`` holds ``agent.folder`` as ``workspace/agents/<slug>``
    and ``activeAgent`` as a bare slug; both are natural things for a caller to
    pass, so both must work.
    """
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    relative_to_root = _SKILL_ROOT / value
    if relative_to_root.is_dir():
        return relative_to_root
    return _AGENTS_DIR / value


def _top_level_value(text, key):
    """Read a top-level key's value without parsing the file as YAML.

    Copilot Studio topic files are not valid YAML — they contain unquoted
    ``@type:`` keys that a compliant parser rejects — so ``yaml.safe_load``
    fails on exactly the Workday and ServiceNow topics whose descriptions
    matter most. The fields needed here are all at column 0, so a line scan is
    both more robust and sufficient.

    Handles an inline value and a block scalar (``|``, ``|-``, ``>``).
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(key + ":"):
            continue
        inline = line[len(key) + 1:].strip()
        if inline and not inline.startswith(("|", ">")):
            return inline.strip("'\"")
        collected = []
        for following in lines[index + 1:]:
            if following.strip() and not following.startswith((" ", "\t")):
                break
            collected.append(following.strip())
        return " ".join(part for part in collected if part)
    return None


def _top_level_list(text, key):
    """Read a top-level block-sequence value (``key:`` then ``  - item`` lines)."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() != key + ":":
            continue
        items = []
        for following in lines[index + 1:]:
            if not following.strip():
                continue
            if not following.startswith((" ", "\t")):
                break
            stripped = following.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip().strip("'\""))
            else:
                break
        return items
    return []


def _summarize_topic(path):
    """Return a capability summary for one topic file.

    Unreadable files are reported, never skipped silently — a topic that could
    not be read is a gap in the capability picture, and the caller is about to
    write prohibitions based on that picture.
    """
    entry = {"file": path.name, "description": None, "triggers": [], "actions": []}
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        entry["error"] = f"could not read: {exc.__class__.__name__}"
        return entry

    # Action kinds come from a text scan rather than the parse tree: they are
    # nested arbitrarily deep and a malformed topic should still disclose what
    # it reaches.
    kinds = {m.group(1) for m in _KIND_RE.finditer(text)}
    entry["actions"] = sorted({_ACTING_KINDS[k] for k in kinds if k in _ACTING_KINDS})

    description = _top_level_value(text, "modelDescription") or _top_level_value(text, "description")
    if description:
        collapsed = " ".join(description.split())
        # Descriptions run to a thousand characters of worked examples. The
        # opening sentences carry the capability; the rest floods the caller's
        # context for no gain.
        if len(collapsed) > _MAX_DESCRIPTION:
            collapsed = collapsed[:_MAX_DESCRIPTION].rstrip() + " ..."
            entry["description_truncated"] = True
        entry["description"] = collapsed
    entry["triggers"] = _top_level_list(text, "triggerQueries")
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Summarize an agent's configured topics and workflows."
    )
    parser.add_argument("--agent", required=True,
                        help="agent folder name under workspace/agents/, or the "
                             "'agent.folder' path from .local/config.json")
    args = parser.parse_args(argv)

    agent_dir = _resolve_agent_dir(args.agent)
    if not agent_dir.is_dir():
        print(f"Agent folder not found: {agent_dir}", file=sys.stderr)
        print(_SENTINEL + json.dumps({"error": "agent folder not found"}))
        return 2

    topics_dir = agent_dir / "topics"
    topics = [_summarize_topic(p) for p in sorted(topics_dir.glob("*.mcs.yml"))]

    workflows_dir = agent_dir / "workflows"
    workflows = sorted(p.name for p in workflows_dir.glob("*")) if workflows_dir.is_dir() else []

    result = {
        "agent": args.agent,
        "topic_count": len(topics),
        "workflow_count": len(workflows),
        # Descriptions and triggers stay out of the JSON: they are long, they
        # are already in the table above, and duplicating them pushed a real
        # agent's output past the caller's output limit — which cost the
        # capability evidence this probe exists to provide.
        "topics": [{"file": t["file"], "actions": t["actions"],
                    "has_description": bool(t["description"])} for t in topics],
        "workflows": workflows,
        "unreadable": [t["file"] for t in topics if "error" in t],
    }
    result["coverage_complete"] = not result["unreadable"]

    print(f"{len(topics)} topics, {len(workflows)} workflows\n")
    for topic in topics:
        acts = ", ".join(topic["actions"]) or "reply only"
        print(f"- {topic['file']}  [{acts}]")
        if topic["description"]:
            print(f"    {topic['description']}")
        if topic["triggers"]:
            print(f"    triggers: {'; '.join(topic['triggers'][:6])}")
        if "error" in topic:
            print(f"    NOT analyzed - {topic['error']}")
    if workflows:
        print("\nWorkflows: " + ", ".join(workflows))
    if result["unreadable"]:
        print(f"\n{len(result['unreadable'])} topic(s) NOT analyzed - "
              "capability coverage is incomplete.")

    print(_SENTINEL + json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
