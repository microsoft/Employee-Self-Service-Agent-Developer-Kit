# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Maker Kit - skill builder validator.

Validates drafted agent skills against Microsoft 365 Copilot's skill limits, the Agent Skills specification
and the agent's tool inventory (from skill_builder_inventory.py). Used by
src/skills/ess-da-ga-skill-builder.

Checks SKILL.md front matter (name, description, compatibility), size (Copilot's 20,000-character limit), file
types Copilot accepts, file references, directory depth, scripts (Copilot runs them with no network and no
package installs), tool names and argument names (each must exist in the inventory), with --expect that the
skill names a tool for every operation it promises, and, with --package, the declarative agent's skill limits.
Warnings flag likely problems that need a maker's decision. The limits mirror
src/skills/ess-da-ga-skill-builder/references/limitations.md; change both together.

Output: one line per finding and a summary on stdout (or JSON with --json).
Exit codes: 0 no errors, 1 errors found (or warnings with --strict), 2 bad arguments or unreadable input.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

MAX_SKILLS, MAX_FILES, MAX_DIRS_IN_SKILL, MAX_SKILL_CHARS = 8, 350, 1, 20_000
RESOURCE_TYPES = frozenset(
    ".json .xml .yaml .yml .ini .config .utf8 .docx .doc .docm .pdf .txt .rtf .md .ppt .pptx .ppsm .xlsx .xls "
    ".xlsm .csv .tsv .html .htm .png .jpg .jpeg .gif .bmp .log".split())
SCRIPT_TYPES = frozenset(".py .js .mjs .cjs .ts .mts .sh .bash".split())
NETWORK_MODULES = frozenset({"socket", "ssl", "http.client", "http.server", "urllib.request", "ftplib", "smtplib",
                             "imaplib", "poplib", "telnetlib", "xmlrpc", "requests", "httpx", "aiohttp", "urllib3",
                             "websocket", "websockets"})
JS_NETWORK = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket)\s*\(|(require\(|from\s+)\s*['\"](node:)?(https?|net|tls|"
                        r"dgram|axios|node-fetch|undici)['\"]")
SHELL_NETWORK = re.compile(r"\b(curl|wget|nc|ssh|scp|ftp)\b")
INSTALL = re.compile(r"\b(pip3?|npm|yarn|pnpm|apt(-get)?)\s+(install|add)\b")
EXPECTABLE = ("create", "read", "update", "comment", "delete", "knowledge")
KNOWLEDGE_USE = re.compile(r"(?i)\bknowledge (search|sources?|base)\b|\bsearch (the agent's |its )?knowledge\b")
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONT_MATTER = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.S)
TOOL_NAME = re.compile(r"\b([a-z][a-z0-9]*__[a-z0-9_]+)\b(?![*])")
QUALIFIED_TOOL = re.compile(r"\b([a-z][a-z0-9]*_[a-z][a-z0-9]*__[a-z0-9_]+)\b(?![*])")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
CODE_SPAN = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"```.*?```", re.S)
CALL = re.compile(r"\b([a-z][a-z0-9]*(?:_+[a-z0-9]+)+)\(")
SCRIPT_FUNCTION = re.compile(r"^\s*(?:def|function|async function)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
IGNORED = ("__pycache__", ".pyc", ".DS_Store")
XML_TAG = re.compile(r"<[A-Za-z/][^>]*>")
TIME_SENSITIVE = re.compile(r"(?i)\b(before|after|until|as of)\s+(january|february|march|april|may|june|july|august|"
                            r"september|october|november|december|q[1-4]|20\d\d)\b")
CONFIRMATION = re.compile(r"(?i)confirm|form|go ahead")


class InputError(Exception):
    """A missing or malformed input file."""


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise InputError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Not valid JSON: {path} ({exc})") from exc


def parse_front_matter(text: str) -> tuple[dict, list[str], str]:
    """(fields, raw lines, body). Top-level `key: value` only; indented blocks belong to the previous key."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, [], text
    raw = match.group(1).splitlines()
    fields: dict = {}
    for line in raw:
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip()
    return fields, raw, text[match.end():]


class Report:
    def __init__(self) -> None:
        self.findings: list[dict] = []

    def add(self, level: str, file: Path, message: str) -> None:
        try:
            shown = Path(os.path.relpath(file)).as_posix()
        except ValueError:  # another drive on Windows
            shown = file.as_posix()
        finding = {"level": level, "file": shown, "message": message}
        if finding not in self.findings:
            self.findings.append(finding)

    def error(self, file: Path, message: str) -> None:
        self.add("error", file, message)

    def warn(self, file: Path, message: str) -> None:
        self.add("warning", file, message)


def check_front_matter(skill: Path, text: str, report: Report) -> str:
    md = skill / "SKILL.md"
    fields, raw, body = parse_front_matter(text)
    if not raw:
        report.error(md, "SKILL.md must start with YAML front matter between --- lines.")
        return body
    for key in ("name", "description"):
        value = fields.get(key, "")
        quoted = len(value) > 1 and value[0] == value[-1] and value[0] in "'\""
        if value and not quoted and (": " in value or value.endswith(":") or " #" in value
                                     or value[0] in "[]{}&*!|>%@`,'\""):
            report.error(md, f"`{key}` isn't valid YAML as written; wrap the whole value in double quotes "
                             "(it contains ': ', ' #' or starts with a special character).")
    name = fields.get("name", "").strip('"')
    if not name:
        report.error(md, "Front matter needs `name`.")
    else:
        if len(name) > 64 or not NAME.match(name):
            report.error(md, f"`name` '{name}' must be 1-64 lowercase letters, digits and single hyphens.")
        if name != skill.name:
            report.error(md, f"`name` '{name}' must match the folder name '{skill.name}'.")
        if any(word in name for word in ("anthropic", "claude")):
            report.error(md, f"`name` '{name}' uses a reserved word.")
    description = fields.get("description", "").strip('"')
    desc_lines = [line for line in raw if line.startswith("description:")]
    if not description:
        report.error(md, "Front matter needs a one-line `description` (what the skill does and when to use it).")
    else:
        if not re.fullmatch(r"description: .{40,1024}", desc_lines[0] if desc_lines else ""):
            report.error(md, f"`description` must be one line of 40-1,024 characters (it is {len(description)}).")
        if XML_TAG.search(description):
            report.error(md, "`description` must not contain XML or HTML tags.")
        if not re.search(r"(?i)\buse (it |this skill )?(when|for)\b", description):
            report.warn(md, "`description` has no 'Use when …' clause; say when to load the skill, with the "
                            "phrasings users type.")
        if re.match(r"(?i)(i |you |we )", description):
            report.warn(md, "`description` should be in third person ('Opens …'), not first or second person.")
        if re.search(r"(?i)read this skill", description):
            report.warn(md, "'Read this skill …' in a description didn't make Copilot read skills; describe the "
                            "intent instead.")
    compatibility = fields.get("compatibility", "")
    if compatibility and len(compatibility.strip('"')) > 500:
        report.error(md, "`compatibility` must be 500 characters or fewer.")
    return body


def check_size(skill: Path, text: str, body: str, report: Report) -> None:
    md = skill / "SKILL.md"
    if len(text) >= MAX_SKILL_CHARS:
        report.error(md, f"SKILL.md has {len(text):,} characters; Copilot requires under {MAX_SKILL_CHARS:,}. "
                         "Move detail to references/.")
    lines = text.count("\n") + 1
    if lines > 500:
        report.error(md, f"SKILL.md has {lines} lines; keep it under 500 and move detail to references/.")
    elif body.count("\n") + 1 > 250:
        report.warn(md, f"SKILL.md body has {body.count(chr(10)) + 1} lines; aim for about 250 so it stays focused.")
    if len(body) / 4 > 5000:
        report.warn(md, f"SKILL.md body is about {len(body) // 4} tokens; the spec recommends under 5,000.")


def skill_files(folder: Path) -> list[Path]:
    """Files that would ship with the skill (build caches left out)."""
    return [p for p in folder.rglob("*") if p.is_file() and not any(part.endswith(IGNORED) for part in p.parts)]


def check_files(skill: Path, report: Report) -> list[Path]:
    files = skill_files(skill)
    for path in files:
        rel = path.relative_to(skill)
        if len(rel.parts) - 1 > MAX_DIRS_IN_SKILL:
            report.error(path, f"'{rel.as_posix()}' is nested too deeply: Copilot allows a directory depth of 3 "
                               "(skills/<name>/<folder>/file).")
        if path.suffix.lower() not in RESOURCE_TYPES | SCRIPT_TYPES:
            report.error(path, f"Copilot doesn't accept '{path.suffix or rel.name}' files in a skill; use a "
                               "supported type such as .md, .json, .csv or .py.")
    for path in (p for p in files if p.suffix == ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in LINK.findall(CODE_SPAN.sub("", text)):
            if re.match(r"^[a-z]+:", target) or ("/" not in target and "." not in target) or "<" in target:
                continue  # URLs, template placeholders, and example text such as (link) in a sample reply
            if "\\" in target:
                report.error(path, f"Link '{target}' uses backslashes; use forward slashes.")
                continue
            if not (path.parent / target).resolve().exists():
                report.error(path, f"Link '{target}' points to a file that doesn't exist.")
            elif path.name not in ("SKILL.md", "README.md") and target.endswith(".md"):
                report.warn(path, f"Reference file links to '{target}'; keep references one level deep from SKILL.md.")
        if path.name != "SKILL.md" and text.count("\n") > 100 and not re.search(r"(?im)^#+\s*contents", text):
            report.warn(path, "Reference file is over 100 lines; add a short 'Contents' section at the top.")
        if TIME_SENSITIVE.search(text):
            report.warn(path, f"Time-sensitive wording ('{TIME_SENSITIVE.search(text).group(0)}') goes stale; "
                              "state the current rule only.")
        if re.search(r"(?i)\btopics?\b", text):
            report.warn(path, "Uses 'topic'; in skill text say 'scenario' or 'action' so it isn't confused with Copilot Studio topics.")
    return files


def check_scripts(skill: Path, files: list[Path], report: Report) -> None:
    """Copilot runs skill scripts in a sandbox with no network access and no package installs."""
    scripts = [p for p in files if p.suffix.lower() in SCRIPT_TYPES]
    if scripts:
        report.add("info", skill / "SKILL.md", f"{len(scripts)} script(s): Copilot runs them with no network access "
                   "and only preinstalled packages. Prefer references and the agent's tools.")
    local = {p.stem for p in scripts}
    for path in scripts:
        text = path.read_text(encoding="utf-8", errors="replace")
        if INSTALL.search(text):
            report.error(path, f"Installs packages ('{INSTALL.search(text).group(0)}'); Copilot's sandbox can't.")
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                report.error(path, f"Python syntax error on line {exc.lineno}: {exc.msg}.")
                continue
            modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    modules |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
            network = sorted(m for m in modules if any(m == n or m.startswith(n + ".") for n in NETWORK_MODULES))
            for module in network:
                report.error(path, f"Imports '{module}', which makes network calls; Copilot's sandbox has no network. "
                                   "Let the agent call its tools instead.")
            top = {m.split(".")[0] for m in modules} - {m.split(".")[0] for m in network}
            for module in sorted(top - set(sys.stdlib_module_names) - local):
                report.warn(path, f"Imports '{module}', which isn't in the Python standard library and may not be "
                                  "preinstalled; use the standard library.")
        elif path.suffix in (".sh", ".bash"):
            if SHELL_NETWORK.search(text):
                report.error(path, f"Uses '{SHELL_NETWORK.search(text).group(0)}'; Copilot's sandbox has no network.")
        elif JS_NETWORK.search(text):
            report.error(path, f"Makes network calls ('{JS_NETWORK.search(text).group(0).strip()}'); Copilot's "
                               "sandbox has no network.")


def code_text(text: str) -> str:
    """Fenced blocks and inline code spans, where a skill names tools."""
    return "\n".join(FENCE.findall(text) + CODE_SPAN.findall(FENCE.sub("", text)))


def tools_used(text: str, known: set[str]) -> set[str]:
    """Tool names a skill text uses: prefixed names anywhere, snake_case calls, and known names in code."""
    code = code_text(text)
    found = set(TOOL_NAME.findall(text)) | set(QUALIFIED_TOOL.findall(text)) | set(CALL.findall(text))
    found |= {n for n in known if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", code)}
    return found


def check_tools(skill: Path, files: list[Path], inventory: dict, report: Report) -> dict:
    tools = {t["name"]: t for t in inventory.get("tools", [])}
    tools.update({t["copilot_name"]: t for t in inventory.get("tools", [])})
    script_functions = {name for p in files if p.suffix.lower() in SCRIPT_TYPES
                        for name in SCRIPT_FUNCTION.findall(p.read_text(encoding="utf-8", errors="replace"))}
    used: dict[str, Path] = {}
    for path in (p for p in files if p.suffix == ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in tools_used(text, set(tools)) - script_functions:
            used.setdefault(name, path)
    named = {n: tools[n] for n in used if n in tools}
    for name, path in sorted(used.items()):
        if name in tools:
            continue
        if any(name.endswith("_" + t) for t in tools):
            continue  # a qualified form of a known tool, e.g. snhr_sn__get_hr_cases
        report.error(path, f"Tool '{name}' isn't in the agent's tool inventory; name only tools the agent has.")
    md = skill / "SKILL.md"
    for name, tool in sorted(named.items()):
        if tool["visibility"] == "app":
            report.warn(used[name], f"'{name}' is app-only (called by the widget); make sure the skill never tells "
                                    "the model to call it.")
        if tool["access"] == "delete":
            report.warn(used[name], f"'{name}' deletes data; confirm the scenario needs it and that the skill "
                                    "requires an explicit confirmation first.")
    all_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files if p.suffix == ".md")
    writes = sorted(n for n, t in named.items() if t["visibility"] == "model" and t["access"] != "read")
    if writes and not CONFIRMATION.search(all_text):
        report.warn(md, f"The skill writes ({', '.join(writes)}) but never mentions a confirmation or a form.")
    unconfirmed = [n for n in writes if (named[n].get("confirmation") or {}).get("isNonConsequential")]
    if unconfirmed:
        report.add("info", md, f"Copilot won't ask before {', '.join(unconfirmed)} (the plugin marks them "
                               "non-consequential), so the skill's confirmation or form is the only safeguard.")
    for path in (p for p in files if p.suffix == ".md"):
        for name, args in call_arguments(path.read_text(encoding="utf-8", errors="replace"), set(tools)):
            tool = tools.get(name)
            if not tool:
                continue
            known = set((tool.get("input_schema") or {}).get("properties") or {}) or {p["name"] for p in tool["params"]}
            for arg in sorted(args - known):
                report.error(path, f"'{name}' has no parameter '{arg}'; its parameters are {', '.join(sorted(known))}.")
    knowledge = inventory.get("knowledge") or {}
    if knowledge.get("provided") and not knowledge.get("sources") and KNOWLEDGE_USE.search(all_text):
        report.warn(md, "The skill relies on knowledge search, but the agent has no knowledge source in its "
                        "capabilities; add one to the agent or route those questions elsewhere.")
    if not named:
        report.warn(md, "The skill names no tools; say which tool does each fragile or writing step.")
    return named


def check_expected(skill: Path, named: dict, expect: list[str], report: Report, inventory: dict) -> None:
    """Each operation the skill promises needs a model-visible tool the skill names, or a knowledge source."""
    visible = {n: t for n, t in named.items() if t["visibility"] == "model"}
    for op in expect:
        if op == "knowledge":
            knowledge = inventory.get("knowledge") or {}
            if not knowledge.get("provided"):
                report.error(skill / "SKILL.md", "The skill should answer from knowledge, but the inventory has no "
                             "capabilities; add knowledge/knowledge.json to the capabilities folder or use --package.")
            elif not knowledge.get("sources"):
                report.error(skill / "SKILL.md", "The skill should answer from knowledge, but the agent has no "
                             "knowledge source (such as SharePoint or a Copilot connector) in its capabilities.")
            continue
        able = sorted(n for n, t in visible.items() if op in (t.get("operations") or []))
        if op == "comment" and not able:
            updates = {n: t for n, t in visible.items() if "update" in (t.get("operations") or [])}
            able = sorted(n for n, t in updates.items()
                          if any(re.search(r"comment|note|journal", p["name"]) for p in t.get("params") or [])) \
                or sorted(n for n, t in updates.items() if t.get("kind") == "generic")
            if able:
                report.add("info", skill / "SKILL.md", f"Comments go through {', '.join(able)}; make sure the "
                           "skill says which field holds the comment.")
        if not able:
            report.error(skill / "SKILL.md", f"The skill should {op}, but names no tool that can. Name the tool, or "
                         f"drop '{op}' from what the skill promises.")


def call_arguments(text: str, known: set[str] = frozenset()) -> list[tuple[str, set[str]]]:
    """(tool, argument names) for each written call such as list_records(table="x", query="y")."""
    calls = []
    for match in re.finditer(r"\b([a-z][a-z0-9_]*)\(", text):
        if "__" not in match.group(1) and match.group(1) not in known:
            continue
        depth, i, start = 1, match.end(), match.end()
        while i < len(text) and depth:
            depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(text[i], 0)
            i += 1
        inner, names, level, quote = text[start:i - 1], set(), 0, ""
        for j, ch in enumerate(inner):
            if quote:
                quote = "" if ch == quote else quote
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                level += 1
            elif ch in ")]}":
                level -= 1
            elif ch == "=" and level == 0 and inner[j + 1:j + 2] != "=":
                key = re.search(r"([a-z_][a-z0-9_]*)\s*$", inner[:j])
                if key:
                    names.add(key.group(1))
        calls.append((match.group(1), names))
    return calls


def check_package(skills: list[Path], package: Path, report: Report) -> None:
    da = load_json(package / "declarativeAgent.json")
    manifest = load_json(package / "manifest.json")
    registered = [Path(s["folder"]).name for s in da.get("agent_skills", [])]
    in_manifest = [Path(s["folder"]).name for s in manifest.get("agentSkills", [])]
    if registered != in_manifest:
        report.error(package / "manifest.json", "manifest.json agentSkills must list the same folders, in the same "
                                                "order, as declarativeAgent.json agent_skills.")
    new = [s.name for s in skills if s.name not in registered]
    if len(registered) + len(new) > MAX_SKILLS:
        report.error(package / "declarativeAgent.json",
                     f"The agent has {len(registered)} skills; adding {', '.join(new)} would exceed {MAX_SKILLS}. "
                     "Merge into or replace an existing skill.")
    for name in new:
        report.add("info", package / "declarativeAgent.json", f"'{name}' isn't registered in the agent yet.")
    existing_files = sum(len(skill_files(package / "skills" / name)) for name in registered
                         if name not in {s.name for s in skills})
    total = existing_files + sum(len(skill_files(s)) for s in skills)
    if total > MAX_FILES:
        report.error(package, f"Skills would have {total} files; Copilot allows {MAX_FILES} across all skills.")


def validate(skills: list[Path], inventory: dict, package: Path | None, expect: list[str] = ()) -> Report:
    report = Report()
    for skill in skills:
        md = skill / "SKILL.md"
        if not md.is_file():
            report.error(skill, "No SKILL.md in this folder.")
            continue
        raw = md.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            report.error(md, "SKILL.md starts with a byte-order mark; save it as UTF-8 without one, or Copilot Studio "
                             "skips the skill.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            report.error(md, "SKILL.md isn't UTF-8; save it as UTF-8 without a byte-order mark.")
            continue
        body = check_front_matter(skill, text, report)
        check_size(skill, text, body, report)
        files = check_files(skill, report)
        check_scripts(skill, files, report)
        named = check_tools(skill, files, inventory, report)
        if expect:
            check_expected(skill, named, list(expect), report, inventory)
    if package is not None:
        check_package(skills, package, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate drafted agent skills against the spec, the tool inventory and Copilot limits.",
        epilog="Example: python scripts/ess-da-ga-skill-builder/skill_builder_validate.py ws/hr-case-create --inventory ws/inventory.json "
               "--package workspace/agents/hr/appPackage\n"
               "Exit codes: 0 no errors, 1 errors (or warnings with --strict), 2 bad input.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("skills", nargs="+", type=Path, help="skill folders (each containing SKILL.md)")
    parser.add_argument("--inventory", required=True, type=Path, help="inventory JSON from skill_builder_inventory.py")
    parser.add_argument("--package", type=Path, help="agent package folder, to check skill limits and registration")
    parser.add_argument("--expect", default="", metavar="OPS",
                        help="operations the skill promises, comma-separated: " + ", ".join(EXPECTABLE))
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args(argv)
    expect = [op.strip() for op in args.expect.split(",") if op.strip()]
    unknown = sorted(set(expect) - set(EXPECTABLE))
    if unknown:
        print(f"Error: unknown --expect operation(s) {', '.join(unknown)}; use {', '.join(EXPECTABLE)}.",
              file=sys.stderr)
        return 2
    try:
        inventory = load_json(args.inventory)
        report = validate(args.skills, inventory, args.package, expect)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    errors = sum(f["level"] == "error" for f in report.findings)
    warnings = sum(f["level"] == "warning" for f in report.findings)
    summary = (f"{len(args.skills)} skill(s): {errors} error(s), {warnings} warning(s). Checked front matter, size, "
               "file types, references and depth, scripts, tool names and arguments"
               + (", promised operations" if expect else "") + (", package limits" if args.package else "") + ".")
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "summary": summary, "findings": report.findings},
                         indent=1))
    else:
        for f in report.findings:
            print(f"{f['level'].upper():7} {f['file']}: {f['message']}")
        print(summary)
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
