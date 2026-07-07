#!/usr/bin/env python3
"""
scan_config.py — Detect ServiceNow config/topic silent-blank mismatches.

A ServiceNow topic parses an integration response into a record whose fields it
later renders. The set of fields the integration actually returns is fixed by the
scenario's template config (`OutputFieldMapping[].OutputName`, plus the connector
base config). If a topic parses a field the config never produces, that field is
silently blank at runtime with no error. This reconciles the two sets.

Resolution (ServiceNow's two-hop wiring):
  - A user topic reaches its integration through a BeginDialog into a system topic,
    referenced by schema name (`dialog: ...topic.<SchemaName>`).
  - `.component-map.json` maps that schema name to the system topic file.
  - The system topic declares `ScenarioName: msdyn_<Scenario>`, from which the
    config filename derives (`msdyn_X` -> `msdyn-x.json`, lowercase, `_`->`-`).
  - The BeginDialog output binding names the response variable; the ParseValue that
    reads that variable declares the fields the topic consumes.

Produced set = the scenario config's `OutputFieldMapping[].OutputName` union the
connector base-config keys (e.g. `ServiceNowPortalBaseURI`, injected downstream).

One anomaly class is reported, high precision:
  - parsed-but-not-produced: a ParseValue record field with no matching config
    output — the field renders blank at runtime.

Only scenarios that resolve to a JSON ServiceNow config are reconciled. Producers
whose scenario cannot be resolved locally are skipped, not flagged (Workday's XML
configs, which declare only a top-level key, are out of scope).

Output is bounded: anomalies to stdout (capped), full detail to --output. This
script only detects; it assigns no severity and makes no judgement.

Usage:
    python scripts/scan_config.py --agent employee-self-service-hr --topic servicenow-hrsd-get-case-details
    python scripts/scan_config.py --agent employee-self-service-hr --output results/config.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A ScenarioName value, e.g. ="msdyn_ServiceNowHRSDGetCaseDetails".
_SCENARIO_RE = re.compile(r"ScenarioName['\"\s:=]+.*?(msdyn_\w+)")
# A bare connector base config, e.g. msdyn-servicenowhrsd.json (no scenario suffix).
_BASE_CONFIG_RE = re.compile(r"^msdyn-servicenow(?:hrsd|itsm)\.json$")

_MAX_LISTED = 20


def _load(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None


def _walk(node):
    """Yield every dict found anywhere in a parsed topic tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _schema_suffix(schema_name: str) -> str:
    """`msdyn_...topic.ServiceNowHRSDSystemGetCaseDetails` -> the trailing segment."""
    return schema_name.rsplit(".", 1)[-1] if schema_name else ""


def load_component_map(agent_dir: Path) -> dict[str, Path]:
    """Map each component's short schema-name suffix to its topic file."""
    raw = _load(agent_dir / ".component-map.json")
    result: dict[str, Path] = {}
    if isinstance(raw, dict):
        for rel_path, meta in raw.items():
            if isinstance(meta, dict):
                suffix = _schema_suffix(meta.get("schemaname", ""))
                if suffix:
                    result[suffix] = agent_dir / rel_path
    return result


def load_base_keys(configs_dir: Path) -> set[str]:
    """Top-level keys of every connector base config, always injected downstream."""
    keys: set[str] = set()
    if configs_dir.is_dir():
        for cfg in configs_dir.glob("msdyn-servicenow*.json"):
            if _BASE_CONFIG_RE.match(cfg.name):
                data = _load(cfg)
                if isinstance(data, dict):
                    keys.update(data.keys())
    return keys


def scenario_of(system_topic_file: Path) -> str | None:
    """Read a system topic's ScenarioName, e.g. msdyn_ServiceNowHRSDGetCaseDetails."""
    if not system_topic_file.is_file():
        return None
    try:
        text = system_topic_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = _SCENARIO_RE.search(text)
    return match.group(1) if match else None


def produced_fields(scenario: str, configs_dir: Path, base_keys: set[str]) -> set[str] | None:
    """Config output names for a ServiceNow scenario, or None if not resolvable here."""
    if "servicenow" not in scenario.lower():
        return None
    config_file = configs_dir / (scenario.lower().replace("_", "-") + ".json")
    data = _load(config_file)
    if not isinstance(data, dict):
        return None
    mappings = data.get("OutputFieldMapping")
    if not isinstance(mappings, list):
        return None
    names = {
        m["OutputName"]
        for m in mappings
        if isinstance(m, dict) and isinstance(m.get("OutputName"), str)
    }
    return names | base_keys


def resolve_response_vars(
    topic, component_map: dict[str, Path], configs_dir: Path, base_keys: set[str]
) -> dict[str, set[str]]:
    """Map each response variable to the produced-field set of its scenario."""
    var_to_produced: dict[str, set[str]] = {}
    for node in _walk(topic):
        if node.get("kind") != "BeginDialog":
            continue
        suffix = _schema_suffix(node.get("dialog", "") or "")
        system_file = component_map.get(suffix)
        if system_file is None:
            continue
        scenario = scenario_of(system_file)
        if scenario is None:
            continue
        produced = produced_fields(scenario, configs_dir, base_keys)
        if produced is None:
            continue
        binding = (node.get("output") or {}).get("binding")
        if isinstance(binding, dict):
            for target in binding.values():
                if isinstance(target, str) and target.startswith("Topic."):
                    var_to_produced[target[len("Topic."):]] = produced
    return var_to_produced


def _value_source(value) -> str | None:
    """`=Topic.ServiceNowData` -> `ServiceNowData` (a single-variable source)."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"=?\s*Topic\.([A-Za-z_][A-Za-z0-9_]*)\s*", value)
    return match.group(1) if match else None


def parsed_records(topic) -> list[tuple[str, set[str]]]:
    """Return (response variable, top-level field names) for each ParseValue record."""
    records: list[tuple[str, set[str]]] = []
    for node in _walk(topic):
        if node.get("kind") != "ParseValue":
            continue
        source = _value_source(node.get("value"))
        if source is None:
            continue
        value_type = node.get("valueType")
        if not isinstance(value_type, dict):
            continue
        props = value_type.get("properties")
        if isinstance(props, dict):
            records.append((source, set(props.keys())))
    return records


def reconcile(topic, component_map, configs_dir, base_keys) -> dict[str, list[str]]:
    """Map each parsed-but-not-produced field to a one-line reason."""
    var_to_produced = resolve_response_vars(topic, component_map, configs_dir, base_keys)
    findings: dict[str, list[str]] = {}
    for source, fields in parsed_records(topic):
        produced = var_to_produced.get(source)
        if produced is None:
            continue
        for field in sorted(fields):
            if field not in produced:
                findings[f"{source}.{field}"] = [
                    "parsed but not produced (config never returns this field; renders blank)"
                ]
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect ServiceNow config/topic silent-blank mismatches."
    )
    parser.add_argument("--agent", "-a", help="Agent folder under workspace/agents/. Auto-detected if only one.")
    parser.add_argument("--topic", "-t", help="Topic file stem to review. Reviews all topics if omitted.")
    parser.add_argument("--output", "-o", help="Write the full per-topic detail to this JSON file.")
    args = parser.parse_args()

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

    configs_dir = agent_dir / "template-configs"
    component_map = load_component_map(agent_dir)
    base_keys = load_base_keys(configs_dir)

    if args.topic:
        stem = args.topic.removesuffix(".mcs.yml")
        topic_files = [topics_dir / f"{stem}.mcs.yml"]
    else:
        topic_files = sorted(topics_dir.glob("*.mcs.yml"))

    detail: dict[str, dict] = {}
    total = 0
    for topic_file in topic_files:
        if not topic_file.is_file():
            print(f"ERROR: topic not found: {topic_file}", file=sys.stderr)
            return 1
        parsed = _load(topic_file)
        if parsed is None:
            continue
        findings = reconcile(parsed, component_map, configs_dir, base_keys)
        if findings:
            detail[topic_file.name] = {"mismatched": dict(sorted(findings.items()))}
            total += len(findings)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")

    if not total:
        print("No config/topic silent-blank mismatches found.")
        return 0

    print(f"Config/topic silent-blank mismatches ({total}):")
    listed = 0
    for topic_name in sorted(detail):
        for path, reasons in sorted(detail[topic_name]["mismatched"].items()):
            if listed >= _MAX_LISTED:
                print(f"  +{total - listed} more")
                return 0
            print(f"  {topic_name}: Topic.{path} — {reasons[0]}")
            listed += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
