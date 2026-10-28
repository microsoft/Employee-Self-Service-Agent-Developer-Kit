# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit - skill builder tool inventory.

Reads MCP tool manifests and lists every tool with its full description, parameters, what it can do (create,
read, update, comment, delete) and a first-pass kind, plus the agent's knowledge sources (the `capabilities`
array of declarativeAgent.json), its existing skills and free skill slots.
Used by src/skills/ess-da-ga-skill-builder. Makes no network calls.

Inputs (at least one):
  --capabilities DIR  a capabilities folder: DIR/mcp/<server>/ holds each MCP server's tool list (tools.json)
                      and, optionally, its plugin manifest (plugin.json); DIR/knowledge/knowledge.json holds the
                      `capabilities` array copied from declarativeAgent.json; DIR/skills/<name>/SKILL.md holds the
                      agent's existing skills. Other folders are listed as not used yet.
  --package DIR       a declarative agent app package (declarativeAgent.json, its plugin actions and their
                      mcp_tool_description files, and its agent_skills)
  --plugin FILE       a plugin manifest; its mcp_tool_description file is read from the same folder
  --tools FILE        an MCP tool list such as an exported tools/list result: {"tools": [...]}

Tool kinds are first-pass hints from names and schemas only. How a tool fits a scenario is decided by reading
its description against the scenario's steps.
  generic        takes a table name, so the skill must supply the table, fields and query
  lookup         model-visible read bound to one entity
  widget         model-visible tool that shows records in a widget
  form           model-visible tool that opens a form the user reviews and submits
  scenario-write model-visible write bound to one entity or process
  widget-action  app-only: only the widget calls it; a skill must never tell the model to call it
  config         maker or agent-configuration tool

Exit codes: 0 success, 2 bad arguments or unreadable input, 3 no tools found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_SKILLS = 8
TABLE_PARAMS = frozenset({"table", "table_name"})
USED_CAPABILITY_KINDS = ("mcp", "knowledge", "skills")
KNOWLEDGE_CAPABILITIES = frozenset({"WebSearch", "OneDriveAndSharePoint", "GraphConnectors", "Dataverse",
                                    "TeamsMessages", "Email", "People", "Meetings", "EmbeddedKnowledge"})
OTHER_CAPABILITIES = frozenset({"CodeInterpreter", "GraphicArt", "ScenarioModels"})
OPERATION_WORDS = (
    ("delete", frozenset({"delete", "remove", "purge", "destroy"})),
    ("comment", frozenset({"comment", "comments", "note", "notes", "journal", "reply"})),
    ("create", frozenset({"create", "add", "new", "submit", "raise", "order", "request", "open"})),
    ("update", frozenset({"update", "edit", "patch", "set", "modify", "change", "close", "resolve", "reopen",
                          "assign", "approve", "reject", "cancel", "attach", "upload"})),
    ("read", frozenset({"get", "list", "search", "find", "query", "read", "show", "lookup", "view", "describe",
                        "fetch", "count", "browse"})),
)
MODE_OPERATIONS = {"create": "create", "new": "create", "edit": "update", "update": "update"}
FRONT_MATTER = re.compile(r"^---\r?\n(.*?)\r?\n---", re.S)
TOOL_NAME = re.compile(r"\b([a-z][a-z0-9]*__[a-z0-9_]+)\b(?![*])")


class InputError(Exception):
    """A missing or malformed input file."""


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise InputError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Not valid JSON: {path} ({exc})") from exc


def front_matter(text: str) -> dict:
    """The top-level key: value pairs of a SKILL.md front matter (nested blocks are skipped)."""
    match = FRONT_MATTER.match(text)
    fields: dict = {}
    if match:
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(":")
            if sep and not line.startswith((" ", "\t")):
                fields[key.strip()] = value.strip().strip('"')
    return fields


def access_of(tool: dict, ess: dict) -> str:
    annotations = tool.get("annotations") or {}
    if ess.get("access") in ("read", "write"):
        access = ess["access"]
    else:
        access = "read" if annotations.get("readOnlyHint") else "write"
    if annotations.get("destructiveHint"):
        access = "delete"
    return access


def classify(tool: dict) -> tuple[str, str, str, str]:
    """(kind, reason, access, visibility) for one MCP tool."""
    meta = tool.get("_meta") or {}
    ess, ui = meta.get("ess") or {}, meta.get("ui") or {}
    access = access_of(tool, ess)
    visibility = "app" if ui.get("visibility") == ["app"] else "model"
    params = (tool.get("inputSchema") or {}).get("properties") or {}
    free_table = sorted(p for p in TABLE_PARAMS & params.keys() if "enum" not in params[p])
    name = tool["name"]
    if ess.get("audience") == "maker" or ess.get("layer") == "agent_config":
        return "config", "maker or agent-configuration tool", access, visibility
    if visibility == "app":
        return "widget-action", "app-only: called by the widget, hidden from the model", access, visibility
    if free_table:
        return "generic", f"caller names the data with `{free_table[0]}`", access, visibility
    if ui.get("resourceUri"):
        if "form" in name.split("__")[-1] or "mode" in params:
            return "form", "opens a form the user reviews and submits", access, visibility
        if access != "read":
            return "scenario-write", "write bound to one entity or process; shows the result in a widget", access, visibility
        return "widget", "shows records in a widget", access, visibility
    if access != "read":
        return "scenario-write", "write bound to one entity or process", access, visibility
    return "lookup", "read bound to one entity", access, visibility


def operations_of(name: str, access: str, kind: str, params: dict) -> list[str]:
    """What a tool does for a user (create, read, update, comment, delete, or write), from its name and schema."""
    tokens = set(re.split(r"[^a-z0-9]+", name.split("__")[-1].lower()))
    ops = [op for op, words in OPERATION_WORDS if tokens & words]
    if kind == "form":
        mode = params.get("mode") or {}
        ops += [MODE_OPERATIONS[m] for m in mode.get("enum") or [] if m in MODE_OPERATIONS]
        if mode and not mode.get("enum"):
            ops += ["create", "update"]
        ops = [op for op in ops if op != "read"] or ["create"]
    elif access == "read":
        return ["read"]
    else:
        ops = [op for op in ops if op != "read"] or ["write"]
    if access == "delete":
        ops.append("delete")
    return sorted(set(ops))


def param_summary(schema: dict) -> list[dict]:
    required = set(schema.get("required") or [])
    out = []
    for pname, spec in (schema.get("properties") or {}).items():
        item = {"name": pname, "type": spec.get("type", "any"), "required": pname in required}
        if "enum" in spec:
            item["enum"] = spec["enum"]
        if "default" in spec:
            item["default"] = spec["default"]
        out.append(item)
    return out


def tool_entries(tools: list[dict], namespace: str, functions: list[dict], run_for: set[str],
                 server: str = "") -> list[dict]:
    listed = {f.get("name") for f in functions}
    confirmations = {f.get("name"): (f.get("capabilities") or {}).get("confirmation") for f in functions}
    entries = []
    for tool in tools:
        kind, reason, access, visibility = classify(tool)
        ui = (tool.get("_meta") or {}).get("ui") or {}
        params = (tool.get("inputSchema") or {}).get("properties") or {}
        entries.append({
            "name": tool["name"], "copilot_name": f"{namespace}_{tool['name']}" if namespace else tool["name"],
            "server": server or namespace, "plugin": namespace, "title": tool.get("title", ""),
            "description": tool.get("description", ""),
            "description_chars": len(tool.get("description", "")), "access": access, "visibility": visibility,
            "kind": kind, "kind_reason": reason, "operations": operations_of(tool["name"], access, kind, params),
            "widget": bool(ui.get("resourceUri")),
            "listed_in_plugin": (tool["name"] in listed and (not run_for or tool["name"] in run_for))
            if functions else None,
            "confirmation": confirmations.get(tool["name"]),
            "params": param_summary(tool.get("inputSchema") or {}),
            "input_schema": tool.get("inputSchema") or {},
        })
    return entries


def plugin_tools(plugin_path: Path) -> tuple[dict, list[dict]] | None:
    plugin = load_json(plugin_path)
    runtimes = [r for r in plugin.get("runtimes", []) if r.get("type") == "RemoteMCPServer"]
    if not runtimes:
        return None
    namespace = plugin.get("namespace", "")
    info = {"file": plugin_path.as_posix(), "namespace": namespace,
            "name_for_human": plugin.get("name_for_human", ""),
            "description_for_model": plugin.get("description_for_model", ""), "runtimes": []}
    tools: list[dict] = []
    for runtime in runtimes:
        spec = runtime.get("spec") or {}
        manifest_file = (spec.get("mcp_tool_description") or {}).get("file")
        info["runtimes"].append({"url": spec.get("url", ""), "auth": (runtime.get("auth") or {}).get("type", ""),
                                 "tools_file": manifest_file})
        if manifest_file:
            listed = tool_list(load_json(plugin_path.parent / manifest_file)) or []
            tools += tool_entries(listed, namespace, plugin.get("functions", []),
                                  set(runtime.get("run_for_functions") or []), namespace)
    info["tools"] = len(tools)
    return info, tools


def tool_list(data: object) -> list[dict] | None:
    """The tools in an MCP tool list: {"tools": [...]}, a raw tools/list response, or a bare list of tools."""
    if isinstance(data, dict):
        for holder in (data, data.get("result") or {}):
            if isinstance(holder, dict) and isinstance(holder.get("tools"), list):
                return holder["tools"]
        return None
    if isinstance(data, list) and data and all(isinstance(t, dict) and "name" in t for t in data):
        return data
    return None


def is_plugin(data: object) -> bool:
    return isinstance(data, dict) and any(isinstance(r, dict) and r.get("type") == "RemoteMCPServer"
                                          for r in data.get("runtimes") or [])


def capability_server(source: Path) -> tuple[dict, list[dict], list[str]]:
    """One MCP server from a capabilities folder: a folder of JSON files, or a single JSON file."""
    name = source.name if source.is_dir() else source.stem
    files = sorted(source.glob("*.json")) if source.is_dir() else [source]
    plugin, plugin_file, tools, problems = None, None, [], []
    for path in files:
        data = load_json(path)
        if is_plugin(data):
            if plugin is None:
                plugin, plugin_file = data, path
            else:
                problems.append(f"{name}: more than one plugin manifest; used {plugin_file.name}.")
        elif tool_list(data) is not None:
            tools += tool_list(data)
    if not tools and plugin is not None:
        for runtime in plugin.get("runtimes") or []:
            ref = ((runtime.get("spec") or {}).get("mcp_tool_description") or {}).get("file")
            if ref and (plugin_file.parent / ref).is_file():
                tools += tool_list(load_json(plugin_file.parent / ref)) or []
    unique: dict[str, dict] = {}
    for tool in tools:
        if isinstance(tool, dict) and tool.get("name"):
            unique.setdefault(tool["name"], tool)
    if not unique:
        problems.append(f"{name}: no tool list found; add the server's tools/list result as tools.json.")
    namespace = (plugin or {}).get("namespace", "")
    run_for = {f for r in (plugin or {}).get("runtimes") or [] for f in r.get("run_for_functions") or []}
    entries = tool_entries(list(unique.values()), namespace, (plugin or {}).get("functions", []), run_for, name)
    info = {"name": name, "source": source.as_posix(), "namespace": namespace,
            "plugin": plugin_file.as_posix() if plugin_file else "", "tools": len(entries)}
    return info, entries, problems


def capability_list(data: object) -> list[dict] | None:
    """The capabilities in {"capabilities": [...]} (as in declarativeAgent.json) or a bare list of them."""
    items = data.get("capabilities") if isinstance(data, dict) else data
    if isinstance(items, list) and all(isinstance(c, dict) and c.get("name") for c in items):
        return items
    return None


def capability_entry(capability: dict) -> dict:
    """One declarative agent capability: its kind and how far the manifest limits its scope."""
    name = capability["name"]
    kind = "knowledge" if name in KNOWLEDGE_CAPABILITIES else "other" if name in OTHER_CAPABILITIES else "unknown"
    scope = {k: len(v) for k, v in capability.items() if k != "name" and isinstance(v, list)}
    return {"name": name, "kind": kind, "scope": scope, "definition": capability}


def knowledge_summary(capabilities: list[dict], provided: bool, problems: list[str]) -> dict:
    entries, seen = [], set()
    for capability in capabilities:
        key = json.dumps(capability, sort_keys=True)
        if key not in seen:
            seen.add(key)
            entries.append(capability_entry(capability))
    for entry in entries:
        if entry["kind"] == "unknown":
            problems.append(f"knowledge: '{entry['name']}' isn't a known declarative agent capability.")
    return {"provided": provided, "sources": sum(e["kind"] == "knowledge" for e in entries),
            "code_interpreter": any(e["name"] == "CodeInterpreter" for e in entries), "capabilities": entries}


def read_knowledge(folder: Path, problems: list[str]) -> tuple[list[dict], bool]:
    """Capabilities from knowledge/*.json in a capabilities folder, and whether the folder exists."""
    knowledge = folder / "knowledge"
    if not knowledge.is_dir():
        return [], False
    capabilities: list[dict] = []
    for path in sorted(knowledge.glob("*.json")):
        found = capability_list(load_json(path))
        if found is None:
            problems.append(f"knowledge: {path.name} isn't a capabilities array; copy the `capabilities` array "
                            "from declarativeAgent.json as {\"capabilities\": [...]}.")
        else:
            capabilities += found
    return capabilities, True


def read_capabilities(folder: Path) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """(servers, tools, not-used capability kinds, problems) from a capabilities folder."""
    mcp = folder / "mcp"
    if not mcp.is_dir():
        raise InputError(f"No mcp/ folder in {folder}. Put each MCP server's tool list in "
                         f"{(mcp / '<server-name>' / 'tools.json').as_posix()}.")
    servers, tools, problems = [], [], []
    for source in sorted(mcp.iterdir()):
        if source.name.startswith(".") or not (source.is_dir() or source.suffix == ".json"):
            continue
        info, entries, found = capability_server(source)
        servers.append(info)
        tools += entries
        problems += found
    not_used = [{"kind": d.name, "items": sorted(c.name for c in d.iterdir() if not c.name.startswith("."))}
                for d in sorted(folder.iterdir())
                if d.is_dir() and d.name not in USED_CAPABILITY_KINDS and not d.name.startswith(".")]
    return servers, tools, not_used, problems


def skill_entry(folder: Path, relative: str, known: set[str] = frozenset()) -> dict:
    skill_md = folder / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8") if skill_md.is_file() else ""
    fields = front_matter(text)
    files = [p for p in folder.rglob("*") if p.is_file()] if folder.is_dir() else []
    markdown = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files if p.suffix == ".md")
    named = set(TOOL_NAME.findall(markdown)) | {n for n in known if re.search(rf"`{re.escape(n)}\b", markdown)}
    return {"name": fields.get("name", folder.name), "folder": relative, "description": fields.get("description", ""),
            "lines": text.count("\n") + 1 if text else 0, "chars": len(text), "files": len(files),
            "tools_named": sorted(named)}


def existing_skills(package: Path | None, skills_dir: Path | None, exclude: set[str],
                    known: set[str] = frozenset()) -> list[dict]:
    if skills_dir is not None:
        folders = [(p, p.name) for p in sorted(skills_dir.iterdir()) if (p / "SKILL.md").is_file()]
    elif package is not None:
        da = load_json(package / "declarativeAgent.json")
        folders = [(package / s["folder"], s["folder"]) for s in da.get("agent_skills", [])]
    else:
        return []
    return [skill_entry(folder, rel, known) for folder, rel in folders if folder.name not in exclude]


def write_paths(tools: list[dict]) -> dict[str, list[str]]:
    """Model-visible tools that change data (forms included), grouped by kind."""
    by_kind: dict[str, list[str]] = {}
    for t in tools:
        if t["visibility"] == "model" and t["kind"] != "config" and (t["access"] != "read" or t["kind"] == "form"):
            by_kind.setdefault(t["kind"], []).append(t["name"])
    return by_kind


def operations_summary(tools: list[dict]) -> dict[str, list[str]]:
    """Which model-visible tools can do each operation (app-only widget actions and config tools left out)."""
    ops: dict[str, list[str]] = {}
    for t in tools:
        if t["visibility"] == "model" and t["kind"] != "config":
            for op in t["operations"]:
                ops.setdefault(op, []).append(t["name"])
    return dict(sorted(ops.items()))


def server_summaries(tools: list[dict], servers: list[dict]) -> list[dict]:
    names = [s["name"] for s in servers] or sorted({t["server"] for t in tools})
    out = []
    for name in names:
        mine = [t for t in tools if t["server"] == name]
        counts: dict[str, int] = {}
        for t in mine:
            counts[t["kind"]] = counts.get(t["kind"], 0) + 1
        out.append({"name": name or "(standalone)", "tools": len(mine), "by_kind": counts,
                    "operations": operations_summary(mine)})
    return out


def build_inventory(package: Path | None = None, plugins: list[Path] = (), tools_files: list[Path] = (),
                    skills_dir: Path | None = None, exclude: set[str] = frozenset(),
                    capabilities: Path | None = None) -> dict:
    plugin_infos, tools, agent_name, instructions = [], [], "", 0
    servers, not_used, problems = [], [], []
    agent_capabilities: list[dict] = []
    knowledge_provided = False
    plugin_paths = list(plugins)
    if capabilities is not None:
        servers, tools, not_used, problems = read_capabilities(capabilities)
        agent_capabilities, knowledge_provided = read_knowledge(capabilities, problems)
        if skills_dir is None and (capabilities / "skills").is_dir():
            skills_dir = capabilities / "skills"
    if package is not None:
        da = load_json(package / "declarativeAgent.json")
        agent_name, instructions = da.get("name", ""), len(da.get("instructions", ""))
        agent_capabilities = (capability_list(da) or []) + agent_capabilities
        knowledge_provided = True
        plugin_paths = [package / a["file"] for a in da.get("actions", [])] + plugin_paths
    for path in plugin_paths:
        found = plugin_tools(path)
        if found:
            plugin_infos.append(found[0])
            tools += found[1]
    for path in tools_files:
        listed = tool_list(load_json(path))
        if listed is None:
            raise InputError(f'Not an MCP tool list: {path} (expected {{"tools": [...]}}).')
        tools += tool_entries(listed, "", [], set(), path.stem)
    if not tools:
        raise LookupError("No MCP tools found in the given capabilities, package, plugins or tool lists.")
    skills = existing_skills(package, skills_dir, exclude, {t["name"] for t in tools})
    counts: dict[str, int] = {}
    for t in tools:
        counts[t["kind"]] = counts.get(t["kind"], 0) + 1
    return {
        "capabilities": capabilities.as_posix() if capabilities else "",
        "package": package.as_posix() if package else "", "agent_name": agent_name,
        "instructions_chars": instructions, "plugins": plugin_infos, "tools": tools,
        "skills": {"max": MAX_SKILLS, "used": len(skills), "free": MAX_SKILLS - len(skills),
                   "excluded": sorted(exclude), "items": skills},
        "knowledge": knowledge_summary(agent_capabilities, knowledge_provided, problems),
        "not_used": not_used, "problems": problems,
        "summary": {"tools": len(tools), "by_kind": counts, "write_paths": write_paths(tools),
                    "operations": operations_summary(tools), "servers": server_summaries(tools, servers)},
    }


def summary_text(inv: dict) -> str:
    s, sk = inv["summary"], inv["skills"]
    paths = s["write_paths"]
    lines = [
        f"Tools: {s['tools']} from {len(s['servers'])} server(s); skills: {sk['used']} of {sk['max']} slots used",
        "Model-visible write paths: " + ("; ".join(f"{k}: {', '.join(v)}" for k, v in paths.items()) or "none"),
        "Operations: " + ("; ".join(f"{k}: {len(v)}" for k, v in s["operations"].items()) or "none"),
    ]
    knowledge = inv.get("knowledge") or {}
    if knowledge.get("provided"):
        described = [f"{c['name']} ({', '.join(f'{k}: {v}' for k, v in c['scope'].items()) or 'scope not limited'})"
                     for c in knowledge["capabilities"] if c["kind"] == "knowledge"]
        others = [c["name"] for c in knowledge["capabilities"] if c["kind"] != "knowledge"]
        lines.append("Knowledge: " + ("; ".join(described) or "none")
                     + ("; other capabilities: " + ", ".join(others) if others else ""))
    else:
        lines.append("Knowledge: not provided (add knowledge/knowledge.json to the capabilities folder)")
    for srv in s["servers"]:
        lines.append(f"Server {srv['name']}: {srv['tools']} tools; "
                     + ", ".join(f"{k} {v}" for k, v in sorted(srv["by_kind"].items()))
                     + "; can " + (", ".join(srv["operations"]) or "nothing"))
    lines += ["", "| tool | server | access | kind | operations | params (* required) |",
              "| --- | --- | --- | --- | --- | --- |"]
    for t in inv["tools"]:
        params = ", ".join(p["name"] + ("*" if p["required"] else "") for p in t["params"])
        lines.append(f"| {t['name']} | {t['server'] or '-'} | {t['access']} | {t['kind']} | "
                     f"{', '.join(t['operations'])} | {params} |")
    if sk["items"]:
        lines += ["", "| skill | lines | tools named | description |", "| --- | --- | --- | --- |"]
        for k in sk["items"]:
            lines.append(f"| {k['name']} | {k['lines']} | {len(k['tools_named'])} | {k['description'][:110]} |")
    if sk["excluded"]:
        lines.append(f"\nLeft out on request: {', '.join(sk['excluded'])}")
    for item in inv.get("not_used", []):
        lines.append(f"Not used yet: {item['kind']}/ ({', '.join(item['items']) or 'empty'})")
    for problem in inv.get("problems", []):
        lines.append(f"Problem: {problem}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List MCP tools and existing skills for the skill builder (no network calls).",
        epilog="Examples:\n"
               "  python scripts/ess-da-ga-skill-builder/skill_builder_inventory.py --capabilities workspace/ess-da-ga-skill-builder-capabilities --out ws/inventory.json\n"
               "  python scripts/ess-da-ga-skill-builder/skill_builder_inventory.py --package workspace/agents/hr/appPackage --out ws/inventory.json\n"
               "  python scripts/ess-da-ga-skill-builder/skill_builder_inventory.py --tools exported-tools.json --out ws/inventory.json\n"
               "Exit codes: 0 success, 2 bad input, 3 no tools found.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--capabilities", type=Path,
                        help="capabilities folder: mcp/<server>/tools.json (+ optional plugin.json), "
                             "knowledge/knowledge.json, skills/")
    parser.add_argument("--package", type=Path, help="declarative agent app package folder (with declarativeAgent.json)")
    parser.add_argument("--plugin", type=Path, action="append", default=[],
                        help="plugin manifest; its tool description file is read from the same folder (repeatable)")
    parser.add_argument("--tools", type=Path, action="append", default=[],
                        help='MCP tool list JSON, {"tools": [...]} (repeatable)')
    parser.add_argument("--skills-dir", type=Path, help="folder of existing skills to list (default: the package's)")
    parser.add_argument("--exclude-skill", action="append", default=[], metavar="NAME",
                        help="leave this existing skill out (repeatable), for example when rebuilding it")
    parser.add_argument("--out", default="-", help="inventory JSON file to write, or - for stdout (default)")
    args = parser.parse_args(argv)
    if not (args.capabilities or args.package or args.plugin or args.tools):
        print("Error: give --capabilities, --package, --plugin or --tools. Run with --help for examples.",
              file=sys.stderr)
        return 2
    try:
        inventory = build_inventory(args.package, args.plugin, args.tools, args.skills_dir, set(args.exclude_skill),
                                    args.capabilities)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    payload = json.dumps(inventory, indent=1, ensure_ascii=False)
    if args.out == "-":
        print(payload)
        print(summary_text(inventory), file=sys.stderr)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        print(summary_text(inventory))
        print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
