#!/usr/bin/env python3
"""
scan_bindings.py — Detect card/topic binding mismatches in an agent's topics.

An adaptive card in a topic renders `Topic.X` values. If a card references a
`Topic.*` value that the topic never populates, that field renders blank at
runtime with no error. This detects those references by reconciling what the
card consumes against what the topic populates.

What a topic populates:
  - ParseValue targets, expanded through their declared record/table schema
    (so `Topic.CaseDetails.ShortDescription` counts as populated when the
    ParseValue schema for `Topic.CaseDetails` declares `ShortDescription`);
  - SetVariable / SetTextVariable targets;
  - BeginDialog output bindings;
  - Question variables.

What a card consumes: every `Topic.*` path referenced inside an adaptive card
body (`AdaptiveCardTemplate.cardContent` / `AdaptiveCardPrompt.card`).

Two anomaly classes are reported, both high precision:
  - unpopulated variable: a card reads `Topic.X` whose root variable is never
    populated anywhere in the topic;
  - unknown field: a card reads `Topic.X.Y` where `Topic.X` is populated by a
    ParseValue record schema that does not declare `Y`.

Output is bounded: anomalies to stdout (capped), full detail to --output. This
script only detects; it assigns no severity and makes no judgement.

Usage:
    python scripts/scan_bindings.py --agent employee-self-service-hr --topic servicenow-hrsd-get-case-details
    python scripts/scan_bindings.py --agent employee-self-service-hr --output results/bindings.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A Topic.* path reference, e.g. Topic.CaseDetails.ShortDescription.
_TOPIC_REF_RE = re.compile(r"\bTopic\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")
# Keys whose string value is an adaptive card body.
_CARD_KEYS = ("cardContent", "card")

_MAX_LISTED = 20


# PyYAML rejects plain scalars that begin with a reserved indicator. Workday WSDL/XML
# topics carry @-prefixed mapping keys (@Public, @Primary, @Descriptor, @type); quote
# such bare keys so the topic parses instead of being silently skipped.
_RESERVED_KEY_RE = re.compile(
    r'^(?P<indent>[ \t]*(?:-[ \t]+)?)(?P<key>@[^\s:#]+)(?P<sep>[ \t]*:(?:[ \t]|$))',
    re.MULTILINE,
)


def _quote_reserved_keys(text: str) -> str:
    return _RESERVED_KEY_RE.sub(
        lambda m: f'{m.group("indent")}"{m.group("key")}"{m.group("sep")}', text
    )


def _load(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return yaml.safe_load(_quote_reserved_keys(text))
    except yaml.YAMLError:
        return None


def _strip_topic(ref: str) -> str:
    """`Topic.A.B` -> `A.B`; leave a non-Topic ref unchanged."""
    return ref[len("Topic."):] if ref.startswith("Topic.") else ref


def _walk(node):
    """Yield every dict found anywhere in a parsed topic tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _expand_schema(schema, prefix: str, populated: set[str], schema_roots: set[str]) -> None:
    """Add every dotted path declared by a ParseValue valueType schema."""
    if not isinstance(schema, dict):
        return
    props = schema.get("properties")
    if props is None:
        inner = schema.get("type")
        if isinstance(inner, dict):
            _expand_schema(inner, prefix, populated, schema_roots)
        return
    schema_roots.add(prefix)
    if not isinstance(props, dict):
        return
    for name, sub in props.items():
        path = f"{prefix}.{name}"
        populated.add(path)
        inner = sub.get("type", sub) if isinstance(sub, dict) else None
        if isinstance(inner, dict):
            _expand_schema(inner, path, populated, schema_roots)


def collect(topic) -> tuple[set[str], set[str], list[str]]:
    """Return (populated paths, schema-known roots, card-consumed paths)."""
    populated: set[str] = set()
    schema_roots: set[str] = set()
    consumed: list[str] = []

    # Declared inputs are populated by the caller.
    if isinstance(topic, dict):
        input_props = (topic.get("inputType") or {}).get("properties")
        if isinstance(input_props, dict):
            populated.update(input_props.keys())

    for node in _walk(topic):
        kind = node.get("kind")
        # Input parameters (AutomaticTaskInput / inputs) declare an available Topic value.
        pn = node.get("propertyName")
        if isinstance(pn, str):
            populated.add(pn)
        var = node.get("variable")
        if isinstance(var, str) and var.startswith("Topic."):
            path = _strip_topic(var)
            populated.add(path)
            if kind == "ParseValue" and isinstance(node.get("valueType"), dict):
                _expand_schema(node["valueType"], path, populated, schema_roots)
        # BeginDialog output bindings: {OutName: Topic.X}
        if kind == "BeginDialog":
            binding = (node.get("output") or {}).get("binding")
            if isinstance(binding, dict):
                for target in binding.values():
                    if isinstance(target, str) and target.startswith("Topic."):
                        populated.add(_strip_topic(target))
        # Card bodies.
        for key in _CARD_KEYS:
            body = node.get(key)
            if isinstance(body, str) and "AdaptiveCard" in body:
                consumed.extend(_strip_topic(m.group(0)) for m in _TOPIC_REF_RE.finditer(body))

    return populated, schema_roots, consumed


def reconcile(
    populated: set[str], schema_roots: set[str], consumed: list[str]
) -> dict[str, list[str]]:
    """Map each dangling consumed path to a one-line reason."""
    populated_roots = {p.split(".")[0] for p in populated}
    findings: dict[str, list[str]] = {}
    for path in sorted(set(consumed)):
        root = path.split(".")[0]
        if root not in populated_roots:
            findings[path] = ["unpopulated variable (never set anywhere in the topic)"]
        elif path in populated:
            continue
        elif root in schema_roots:
            findings[path] = ["unknown field (not declared by the record's ParseValue schema)"]
        # else: root populated by an opaque means; sub-field cannot be verified — not flagged.
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect card/topic binding mismatches in an agent's topics."
    )
    parser.add_argument("--agent", "-a", help="Agent folder under workspace/agents/. Auto-detected if only one.")
    parser.add_argument("--topic", "-t", help="Topic file stem to review. Reviews all topics if omitted.")
    parser.add_argument("--module", help="Restrict to topics whose name starts with this module id (e.g. workday, servicenow-hrsd). Ignored if --topic is given.")
    parser.add_argument("--output", "-o", help="Write the full per-topic detail to this JSON file.")
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
    topics_dir = agent_dir / "topics"
    if not topics_dir.is_dir():
        print(f"ERROR: no topics/ folder in {agent_dir}", file=sys.stderr)
        return 1

    if args.topic:
        stem = args.topic.removesuffix(".mcs.yml")
        topic_files = [topics_dir / f"{stem}.mcs.yml"]
    elif args.module:
        topic_files = sorted(f for f in topics_dir.glob(f"{args.module}*.mcs.yml"))
    else:
        topic_files = sorted(topics_dir.glob("*.mcs.yml"))

    detail: dict[str, dict] = {}
    total = 0
    skipped = 0
    for topic_file in topic_files:
        if not topic_file.is_file():
            print(f"ERROR: topic not found: {topic_file}", file=sys.stderr)
            return 1
        parsed = _load(topic_file)
        if parsed is None:
            print(
                f"WARNING: could not read/parse {topic_file.name}; it was NOT analyzed "
                f"(a clean result does not cover this topic).",
                file=sys.stderr,
            )
            skipped += 1
            continue
        populated, schema_roots, consumed = collect(parsed)
        findings = reconcile(populated, schema_roots, consumed)
        if findings:
            detail[topic_file.name] = {
                "dangling": {k: v for k, v in sorted(findings.items())},
                "populated": sorted(populated),
                "consumed": sorted(set(consumed)),
            }
            total += len(findings)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")

    if not total:
        if skipped:
            print(
                f"No card/topic binding mismatches found in the topics that were read "
                f"({skipped} skipped — see warnings above; coverage is incomplete)."
            )
        else:
            print("No card/topic binding mismatches found.")
        return 0

    print(f"Card/topic binding mismatches ({total}):")
    listed = 0
    for topic_name in sorted(detail):
        for path, reasons in sorted(detail[topic_name]["dangling"].items()):
            if listed >= _MAX_LISTED:
                print(f"  +{total - listed} more")
                return 0
            print(f"  {topic_name}: Topic.{path} — {reasons[0]}")
            listed += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
