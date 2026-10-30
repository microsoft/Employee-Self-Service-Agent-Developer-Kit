# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the skill builder scripts and the ess-da-ga-skill-builder guide."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import skill_builder_inventory as inventory_mod
import skill_builder_package as package_mod
import skill_builder_validate as validate_mod

_REPO = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO / "solutions" / "ess-maker-skills"
_BUILDER = _SOLUTION / "src" / "skills" / "ess-da-ga-skill-builder"
_FIXTURES = _REPO / "tests" / "fixtures" / "ess-da-ga-skill-builder"
_CAPABILITIES = _FIXTURES / "ess-da-ga-skill-builder-capabilities"
_GOOD_SKILL = _FIXTURES / "skills" / "good-case-create"


@pytest.fixture(scope="module")
def inventory() -> dict:
    return inventory_mod.build_inventory(capabilities=_CAPABILITIES)


def _tool(inv: dict, name: str) -> dict:
    return next(t for t in inv["tools"] if t["name"] == name)


def _errors(report: validate_mod.Report) -> list[str]:
    return [f["message"] for f in report.findings if f["level"] == "error"]


def _warnings(report: validate_mod.Report) -> list[str]:
    return [f["message"] for f in report.findings if f["level"] == "warning"]


def _draft(tmp_path: Path, name: str, body: str, description: str | None = None) -> Path:
    skill = tmp_path / name
    skill.mkdir(parents=True)
    description = description or (f"Handles {name} requests for the employee and confirms the result. "
                                   "Use when someone asks about it.")
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# Draft\n\n{body}\n",
                                    encoding="utf-8")
    return skill


# Inventory


def test_capabilities_folder_lists_servers_tools_and_skills(inventory: dict) -> None:
    servers = {s["name"]: s for s in inventory["summary"]["servers"]}
    assert set(servers) == {"hrcases", "records"}
    assert servers["records"]["tools"] == 5 and servers["hrcases"]["tools"] == 5
    assert inventory["skills"]["used"] == 1 and inventory["skills"]["free"] == 7
    assert inventory["skills"]["items"][0]["tools_named"] == ["get_current_user"]
    assert inventory["not_used"] == []
    assert inventory["problems"] == []


def test_knowledge_comes_from_the_agent_capabilities_array(inventory: dict) -> None:
    knowledge = inventory["knowledge"]
    assert knowledge["provided"] is True and knowledge["sources"] == 2
    assert knowledge["code_interpreter"] is False
    scopes = {c["name"]: c["scope"] for c in knowledge["capabilities"]}
    assert scopes == {"GraphConnectors": {"connections": 1}, "OneDriveAndSharePoint": {"items_by_sharepoint_ids": 1}}
    assert all(c["kind"] == "knowledge" for c in knowledge["capabilities"])
    assert "Knowledge: GraphConnectors (connections: 1)" in inventory_mod.summary_text(inventory)


def test_package_capabilities_and_unknown_folders(tmp_path: Path) -> None:
    package = tmp_path / "appPackage"
    package.mkdir()
    for name in ("plugin.json", "tools.json"):
        shutil.copy(_CAPABILITIES / "mcp" / "records" / name, package / name)
    capabilities = [{"name": "WebSearch"}, {"name": "CodeInterpreter"}, {"name": "Teleport"}]
    (package / "declarativeAgent.json").write_text(json.dumps(
        {"name": "Contoso HR", "instructions": "x", "actions": [{"file": "plugin.json"}], "capabilities": capabilities}),
        encoding="utf-8")
    inv = inventory_mod.build_inventory(package=package)
    kinds = {c["name"]: c["kind"] for c in inv["knowledge"]["capabilities"]}
    assert kinds == {"WebSearch": "knowledge", "CodeInterpreter": "other", "Teleport": "unknown"}
    assert inv["knowledge"]["sources"] == 1 and inv["knowledge"]["code_interpreter"] is True
    assert any("'Teleport' isn't a known" in p for p in inv["problems"])

    caps = tmp_path / "caps"
    shutil.copytree(_CAPABILITIES / "mcp", caps / "mcp")
    (caps / "actions").mkdir()
    (caps / "knowledge").mkdir()
    (caps / "knowledge" / "knowledge.json").write_text('{"items": []}', encoding="utf-8")
    inv = inventory_mod.build_inventory(capabilities=caps)
    assert inv["not_used"] == [{"kind": "actions", "items": []}]
    assert inv["knowledge"]["provided"] is True and inv["knowledge"]["sources"] == 0
    assert any("isn't a capabilities array" in p for p in inv["problems"])


def test_tool_kinds_are_first_pass_hints(inventory: dict) -> None:
    kinds = {t["name"]: t["kind"] for t in inventory["tools"]}
    assert kinds["list_records"] == "generic"
    assert kinds["create_record"] == "generic"
    assert kinds["get_current_user"] == "lookup"
    assert kinds["hr__get_cases"] == "widget"
    assert kinds["hr__create_case_form"] == "form"
    assert kinds["hr__update_case"] == "scenario-write"
    assert kinds["hr__attach_file"] == "widget-action"


def test_operations_come_from_names_and_schemas(inventory: dict) -> None:
    ops = {t["name"]: t["operations"] for t in inventory["tools"]}
    assert ops["list_records"] == ["read"]
    assert ops["create_record"] == ["create"]
    assert ops["update_record"] == ["update"]
    assert ops["hr__create_case_form"] == ["create"]
    assert ops["hr__update_case"] == ["update"]
    assert "delete" in ops["hr__delete_case"]
    summary = inventory["summary"]["operations"]
    assert "hr__attach_file" not in summary.get("update", [])


def test_inventory_has_no_whole_agent_shape_label(inventory: dict) -> None:
    assert "shape" not in inventory["summary"]
    assert all("shape" not in s for s in inventory["summary"]["servers"])


def test_plugin_adds_namespace_and_confirmation(inventory: dict) -> None:
    create = _tool(inventory, "create_record")
    assert create["copilot_name"] == "records_create_record"
    assert create["listed_in_plugin"] is True
    assert create["confirmation"]["isNonConsequential"] is True
    assert _tool(inventory, "hr__get_cases")["copilot_name"] == "hr__get_cases"


def test_plugin_only_server_reads_the_referenced_tool_file(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shutil.copy(_CAPABILITIES / "mcp" / "records" / "tools.json", shared / "records-tools.json")
    server = tmp_path / "capabilities" / "mcp" / "records"
    server.mkdir(parents=True)
    plugin = json.loads((_CAPABILITIES / "mcp" / "records" / "plugin.json").read_text(encoding="utf-8"))
    plugin["runtimes"][0]["spec"]["mcp_tool_description"]["file"] = "../../../shared/records-tools.json"
    (server / "plugin.json").write_text(json.dumps(plugin), encoding="utf-8")
    inv = inventory_mod.build_inventory(capabilities=tmp_path / "capabilities")
    assert inv["summary"]["tools"] == 5


def test_server_without_tools_is_reported_as_a_problem(tmp_path: Path) -> None:
    caps = tmp_path / "capabilities"
    shutil.copytree(_CAPABILITIES / "mcp" / "hrcases", caps / "mcp" / "hrcases")
    (caps / "mcp" / "empty").mkdir()
    inv = inventory_mod.build_inventory(capabilities=caps)
    assert any(p.startswith("empty:") for p in inv["problems"])


def test_tools_file_accepts_a_raw_tools_list_response(tmp_path: Path) -> None:
    tools = json.loads((_CAPABILITIES / "mcp" / "hrcases" / "tools.json").read_text(encoding="utf-8"))
    raw = tmp_path / "hr.json"
    raw.write_text(json.dumps({"jsonrpc": "2.0", "id": 1, "result": tools}), encoding="utf-8")
    inv = inventory_mod.build_inventory(tools_files=[raw])
    assert inv["summary"]["tools"] == 5
    assert {t["server"] for t in inv["tools"]} == {"hr"}


def test_inventory_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert inventory_mod.main([]) == 2
    assert inventory_mod.main(["--capabilities", str(tmp_path)]) == 2
    assert "mcp/" in capsys.readouterr().err
    not_tools = tmp_path / "not-tools.json"
    not_tools.write_text('{"name": "x"}', encoding="utf-8")
    assert inventory_mod.main(["--tools", str(not_tools)]) == 2
    empty = tmp_path / "empty.json"
    empty.write_text('{"tools": []}', encoding="utf-8")
    assert inventory_mod.main(["--tools", str(empty)]) == 3
    out = tmp_path / "inv.json"
    assert inventory_mod.main(["--capabilities", str(_CAPABILITIES), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["tools"] == 10


# Validator


def test_good_skill_passes_with_its_promised_operations(inventory: dict) -> None:
    report = validate_mod.validate([_GOOD_SKILL], inventory, None, ["create", "read"])
    assert _errors(report) == []


def test_promised_operation_without_a_tool_is_an_error(inventory: dict) -> None:
    report = validate_mod.validate([_GOOD_SKILL], inventory, None, ["update"])
    assert any("should update" in e for e in _errors(report))


def test_knowledge_promises_need_a_knowledge_source(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "policy-answers", "Answer policy questions with knowledge search; call `get_current_user` "
                                               "to add the user's country.")
    assert _errors(validate_mod.validate([skill], inventory, None, ["knowledge"])) == []
    no_sources = {**inventory, "knowledge": {"provided": True, "sources": 0, "capabilities": []}}
    report = validate_mod.validate([skill], no_sources, None, ["knowledge"])
    assert any("no knowledge source" in e for e in _errors(report))
    assert any("relies on knowledge search" in w for w in _warnings(report))
    tools_only = {k: v for k, v in inventory.items() if k != "knowledge"}
    assert any("inventory has no capabilities" in e
               for e in _errors(validate_mod.validate([skill], tools_only, None, ["knowledge"])))


def test_comment_can_be_covered_by_an_update_with_a_note_field(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "case-note", 'Confirm the text, then call `hr__update_case(sys_id="<id>", work_note="<text>")`.')
    report = validate_mod.validate([skill], inventory, None, ["comment"])
    assert _errors(report) == []
    assert any("Comments go through hr__update_case" in f["message"] for f in report.findings)


def test_unknown_tools_and_arguments_are_errors(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "bad-calls", 'Confirm first. Then `make_case(table="x")` and '
                                          'create_record(tabel="hr_case", body={"a": "b"}).')
    errors = _errors(validate_mod.validate([skill], inventory, None))
    assert any("'make_case' isn't in the agent's tool inventory" in e for e in errors)
    assert any("'create_record' has no parameter 'tabel'" in e for e in errors)


def test_plain_tool_names_in_code_are_recognized(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "plain-names", "Look the user up with `get_current_user`. Prose that says list records "
                                            "is not a tool reference.")
    report = validate_mod.validate([skill], inventory, None, ["read"])
    assert _errors(report) == []


def test_structure_problems_are_errors(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "structure", "Use `list_records`. Read [the guide](references/missing.md).")
    (skill / "SKILL.md").write_text((skill / "SKILL.md").read_text(encoding="utf-8").replace(
        "name: structure", "name: other-name"), encoding="utf-8")
    deep = skill / "references" / "deeper"
    deep.mkdir(parents=True)
    (deep / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (skill / "tool.exe").write_bytes(b"MZ")
    errors = _errors(validate_mod.validate([skill], inventory, None))
    assert any("must match the folder name" in e for e in errors)
    assert any("doesn't exist" in e for e in errors)
    assert any("nested too deeply" in e for e in errors)
    assert any("doesn't accept '.exe'" in e for e in errors)


def test_instructions_over_twenty_thousand_characters_are_an_error(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "too-long", "Use `list_records`.\n" + "\n".join(["Words for the agent."] * 1100))
    assert any("under 20,000" in e for e in _errors(validate_mod.validate([skill], inventory, None)))


def test_front_matter_must_load_in_copilot_studio(tmp_path: Path, inventory: dict) -> None:
    colon = _draft(tmp_path, "colon", "Use `list_records`.",
                   description="Shows cases. Use when: the employee asks about their HR cases or their status.")
    quoted = _draft(tmp_path, "quoted", "Use `list_records`.",
                    description='"Shows cases. Use when: the employee asks about their HR cases or their status."')
    bom = _draft(tmp_path, "bom", "Use `list_records`.")
    (bom / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + (bom / "SKILL.md").read_bytes())
    latin = _draft(tmp_path, "latin", "Use `list_records`.")
    (latin / "SKILL.md").write_bytes((latin / "SKILL.md").read_bytes() + "caf\u00e9".encode("latin-1"))
    assert any("isn't valid YAML" in e for e in _errors(validate_mod.validate([colon], inventory, None)))
    assert not any("YAML" in e for e in _errors(validate_mod.validate([quoted], inventory, None)))
    assert any("byte-order mark" in e for e in _errors(validate_mod.validate([bom], inventory, None)))
    assert any("isn't UTF-8" in e for e in _errors(validate_mod.validate([latin], inventory, None)))


def test_app_only_and_delete_tools_are_flagged(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "risky", "Confirm, then call `hr__attach_file` or `hr__delete_case`.")
    warnings = _warnings(validate_mod.validate([skill], inventory, None))
    assert any("'hr__attach_file' is app-only" in w for w in warnings)
    assert any("'hr__delete_case' deletes data" in w for w in warnings)


def test_write_without_confirmation_is_flagged(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "unsafe", 'Call `create_record(table="hr_case", body={})` straight away.',
                   description="Opens a new HR case for the employee. Use when someone wants to open an HR case.")
    assert any("never mentions a confirmation" in w for w in _warnings(validate_mod.validate([skill], inventory, None)))


def test_scripts_must_work_offline_with_the_standard_library(tmp_path: Path, inventory: dict) -> None:
    skill = _draft(tmp_path, "scripted", "Use `list_records`, then run `scripts/format.py`.")
    scripts = skill / "scripts"
    scripts.mkdir()
    (scripts / "format.py").write_text("import json\nimport urllib.parse\nimport yaml\n", encoding="utf-8")
    (scripts / "fetch.py").write_text("import requests\nfrom urllib import request\n", encoding="utf-8")
    (scripts / "setup.sh").write_text("pip install pandas\ncurl https://contoso.com\n", encoding="utf-8")
    (scripts / "call.js").write_text("fetch('https://contoso.com')\n", encoding="utf-8")
    report = validate_mod.validate([skill], inventory, None)
    errors, warnings = _errors(report), _warnings(report)
    assert any("Imports 'requests'" in e for e in errors)
    assert any("Imports 'urllib.request'" in e for e in errors)
    assert not any("urllib.parse" in e for e in errors)
    assert any("Installs packages" in e for e in errors)
    assert any("Uses 'curl'" in e for e in errors)
    assert any("Makes network calls" in e for e in errors)
    assert any("Imports 'yaml'" in w for w in warnings)


def test_package_limits_allow_at_most_eight_skills(tmp_path: Path, inventory: dict) -> None:
    package = tmp_path / "appPackage"
    folders = []
    for i in range(8):
        _draft(package / "skills", f"skill-{i}", "Use `list_records`.")
        folders.append({"folder": f"skills/skill-{i}"})
    (package / "declarativeAgent.json").write_text(json.dumps({"agent_skills": folders}), encoding="utf-8")
    (package / "manifest.json").write_text(json.dumps({"agentSkills": folders}), encoding="utf-8")
    report = validate_mod.validate([_GOOD_SKILL], inventory, package)
    assert any("would exceed 8" in e for e in _errors(report))


# Packager


def test_package_writes_a_zip_with_skill_md_at_the_root(tmp_path: Path, inventory: dict) -> None:
    out = tmp_path / "good-case-create.zip"
    findings, written = package_mod.package_skill(_GOOD_SKILL, out, inventory, ["create"])
    assert written == 2
    assert not [f for f in findings if f["level"] == "error"]
    with zipfile.ZipFile(out) as archive:
        assert sorted(archive.namelist()) == ["SKILL.md", "references/services.md"]


def test_package_refuses_a_skill_with_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    skill = _draft(tmp_path, "broken", "Call `missing_tool(x=1)` after confirming.")
    inv_file = tmp_path / "inv.json"
    inv_file.write_text(json.dumps(inventory_mod.build_inventory(capabilities=_CAPABILITIES)), encoding="utf-8")
    out = tmp_path / "broken.zip"
    assert package_mod.main([str(skill), "--inventory", str(inv_file), "--out", str(out)]) == 1
    assert not out.exists()
    assert "Not packaged" in capsys.readouterr().out


def test_scripts_run_from_the_grouped_folder(tmp_path: Path) -> None:
    scripts = _SOLUTION / "scripts" / "ess-da-ga-skill-builder"
    inventory_file = tmp_path / "inventory.json"
    archive_path = tmp_path / "skill.zip"
    commands = [
        ("skill_builder_inventory.py", ["--capabilities", str(_CAPABILITIES), "--out", str(inventory_file)]),
        ("skill_builder_validate.py", [str(_GOOD_SKILL), "--inventory", str(inventory_file), "--expect", "create"]),
        ("skill_builder_package.py", [str(_GOOD_SKILL), "--inventory", str(inventory_file),
                                      "--expect", "create", "--out", str(archive_path)]),
    ]
    for name, args in commands:
        result = subprocess.run(
            [sys.executable, str(scripts / name), *args], cwd=_SOLUTION,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 0, f"{name}: {result.stdout}\n{result.stderr}"
    assert json.loads(inventory_file.read_text(encoding="utf-8"))["tools"]
    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ["SKILL.md", "references/services.md"]


# The builder guide and its wiring


def test_builder_folder_names_are_consistent() -> None:
    name = "ess-da-ga-skill-builder"
    assert _BUILDER.name == _FIXTURES.name == name
    assert _CAPABILITIES.name == f"{name}-capabilities"
    for module in (inventory_mod, validate_mod, package_mod):
        assert Path(module.__file__).resolve().parent == _SOLUTION / "scripts" / name
    guidance = (_BUILDER / "SKILL.md").read_text(encoding="utf-8")
    assert f"workspace/{name}/<plan-name>/iteration-<n>/" in guidance
    assert f"workspace/{name}-capabilities/" in guidance


def test_builder_skill_meets_the_agent_skills_spec() -> None:
    text = (_BUILDER / "SKILL.md").read_text(encoding="utf-8")
    fields, _, _ = validate_mod.parse_front_matter(text)
    assert fields["name"] == _BUILDER.name == "ess-da-ga-skill-builder"
    assert 40 <= len(fields["description"]) <= 1024
    assert text.count("\n") < 500
    report = validate_mod.Report()
    body = validate_mod.check_front_matter(_BUILDER, text, report)
    validate_mod.check_size(_BUILDER, text, body, report)
    validate_mod.check_files(_BUILDER, report)
    assert _errors(report) == [], _errors(report)


def test_builder_references_resolve_and_scripts_exist() -> None:
    text = (_BUILDER / "SKILL.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\(((?:references|assets)/[^)]+)\)", text):
        assert (_BUILDER / target).is_file(), target
    scripts = re.findall(r"python (scripts/ess-da-ga-skill-builder/skill_builder_\w+\.py)", text)
    assert {Path(script).name for script in scripts} == {
        "skill_builder_inventory.py", "skill_builder_validate.py", "skill_builder_package.py",
    }
    for script in scripts:
        assert (_SOLUTION / script).is_file(), script
        assert not (_SOLUTION / "scripts" / Path(script).name).exists(), script
    readme = (_BUILDER / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\((\.\./[^)]+)\)", readme):
        assert (_BUILDER / target).exists(), target
    assert "shape-decision" not in text
    assert not re.search(r"(?i)fan-(in|out)", text)
    for reference in ("limitations.md", "sources.md", "scenario-analysis.md", "authoring-rules.md"):
        assert f"](references/{reference})" in text, reference
    assert "ess-da-ga-skill-builder-capabilities/" in text and "knowledge.json" in text
    assert "workspace/capabilities/" not in text
    analysis = (_BUILDER / "references" / "scenario-analysis.md").read_text(encoding="utf-8")
    examples = (_BUILDER / "references" / "examples.md").read_text(encoding="utf-8")
    assert "orchestration skill" in analysis and "## An orchestration skill across knowledge and actions" in examples


def _limitation_rows() -> dict[str, list[str]]:
    text = (_BUILDER / "references" / "limitations.md").read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        match = re.match(r"\| ([A-Z]{2}-\d{2}) \|", line)
        if match:
            assert match.group(1) not in rows, f"duplicate limitation ID {match.group(1)}"
            rows[match.group(1)] = [c.strip() for c in line.strip().strip("|").split("|")]
    return rows


def test_limitations_record_matches_the_scripts() -> None:
    rows = _limitation_rows()
    text = lambda rid: " ".join(rows[rid])  # noqa: E731
    assert f"Up to {validate_mod.MAX_SKILLS} skills" in text("PK-01")
    assert f"under {validate_mod.MAX_SKILL_CHARS:,} characters" in text("PK-02")
    assert f"depth {validate_mod.MAX_DIRS_IN_SKILL + 2}" in text("PK-03")
    assert f"{validate_mod.MAX_FILES} files" in text("PK-04")
    assert f"{package_mod.MAX_ZIP_BYTES // 2**20} MB" in text("PK-05")
    assert f"{package_mod.MAX_FILE_BYTES // 2**20} MB" in text("PK-06")
    assert f"Up to {inventory_mod.MAX_SKILLS} skills" in text("PK-01")
    assert set(re.findall(r"`(\.[a-z0-9]+)`", text("FS-01"))) == set(validate_mod.RESOURCE_TYPES)
    assert set(re.findall(r"`(\.[a-z0-9]+)`", text("FS-02"))) == set(validate_mod.SCRIPT_TYPES)


def test_limitations_record_is_well_formed() -> None:
    text = (_BUILDER / "references" / "limitations.md").read_text(encoding="utf-8")
    assert re.search(r"^Last reviewed: \d{4}-\d{2}-\d{2}\.$", text, re.M)
    defined = set(re.findall(r"^\[(\d+)\]: https://", text, re.M))
    for rid, cells in _limitation_rows().items():
        status = cells[2] if rid.startswith("UV") else cells[3]
        assert status in {"Documented", "Observed", "Spec", "Unverified"}, rid
        if status == "Documented":
            refs = re.findall(r"\]\[(\d+)\]", cells[4])
            assert refs and set(refs) <= defined, f"{rid} needs a defined documentation source"
    assert {"PK-01", "PK-02", "FS-03", "FS-04", "RT-02"} <= set(_limitation_rows())


def test_sources_list_every_external_guide() -> None:
    text = (_BUILDER / "references" / "sources.md").read_text(encoding="utf-8")
    urls = re.findall(r"\]\((https://[^)]+)\)", text)
    assert len(urls) == len(set(urls)) >= 25
    for expected in ("agentskills.io/specification", "agentskills.io/skill-creation/best-practices",
                     "agentskills.io/skill-creation/optimizing-descriptions",
                     "agentskills.io/skill-creation/evaluating-skills", "agentskills.io/skill-creation/using-scripts",
                     "platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
                     "learn.chatgpt.com/docs/build-skills", "openai.com/academy/skills",
                     "developers.openai.com/api/docs/guides/tools-skills",
                     "learn.microsoft.com/microsoft-365/copilot/extensibility/declarative-agent-skills"):
        assert any(expected in url for url in urls), expected
    assert not any("/en-us/" in url for url in urls)


def test_documentation_prioritizes_copilot_and_labels_observations() -> None:
    sources = (_BUILDER / "references" / "sources.md").read_text(encoding="utf-8")
    ordered_sections = (
        "Microsoft 365 Copilot declarative agents", "Copilot Studio", "Agent Skills open standard",
        "Anthropic", "OpenAI", "Model Context Protocol",
    )
    positions = [sources.index(f"## {section}\n") for section in ordered_sections]
    assert positions == sorted(positions)
    readme = (_BUILDER / "README.md").read_text(encoding="utf-8")
    practices = readme.split("## Practices from external guides\n", 1)[1]
    assert re.findall(r"^### (.+)$", practices, re.M)[0] == "Microsoft 365 Copilot and Copilot Studio"
    definitions = re.findall(r"^\[[a-z0-9-]+\]: (https://\S+)$", readme, re.M)
    assert definitions[0].startswith("https://learn.microsoft.com/microsoft-365/copilot/")
    for relative in ("SKILL.md", "README.md", "references/authoring-rules.md"):
        text = (_BUILDER / relative).read_text(encoding="utf-8")
        start = text.index("Grounded in Microsoft 365 Copilot documentation")
        provenance = text[start:].split("\n", 1)[0]
        names = ("Microsoft 365 Copilot", "Agent Skills specification", "Anthropic", "OpenAI")
        assert [provenance.index(name) for name in names] == sorted(provenance.index(name) for name in names)
        assert "**Observed**" in text and "not platform guarantees" in text
    rows = _limitation_rows()
    for rid in ("RT-02", "RT-03", "RT-04", "RT-05"):
        assert rows[rid][3] == "Observed", rid


def test_readme_links_resolve_and_match_the_source_list() -> None:
    readme = (_BUILDER / "README.md").read_text(encoding="utf-8")
    sources = set(re.findall(r"\]\((https://[^)]+)\)",
                             (_BUILDER / "references" / "sources.md").read_text(encoding="utf-8")))
    defined = dict(re.findall(r"^\[([a-z0-9-]+)\]: (https://\S+)$", readme, re.M))
    used = set(re.findall(r"\]\[([a-z0-9-]+)\]", readme))
    assert used == set(defined), f"undefined {used - set(defined)}, unused {set(defined) - used}"
    assert set(defined.values()) <= sources, set(defined.values()) - sources
    for target in re.findall(r"\]\(([^)#:]+)\)", readme):
        assert (_BUILDER / target).resolve().exists(), target


def test_interview_questions_are_valid_ask_questions_json() -> None:
    text = (_BUILDER / "references" / "interview.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, re.S)
    assert len(blocks) >= 14
    for block in blocks:
        question = json.loads(block)
        assert {"header", "question", "options", "allowFreeformInput"} <= question.keys()
        assert sum(bool(o.get("recommended")) for o in question["options"]) <= 1
        assert all({"label", "description"} <= o.keys() for o in question["options"])
    json.loads((_BUILDER / "assets" / "evals-template.json").read_text(encoding="utf-8"))


def test_build_skill_command_is_routed_and_listed() -> None:
    prompt = (_SOLUTION / ".github" / "prompts" / "build-skill.prompt.md").read_text(encoding="utf-8")
    assert "agent: agent" in prompt and "mode:" not in prompt and "description:" in prompt
    assert "src/skills/ess-da-ga-skill-builder/SKILL.md" in prompt
    instructions = (_SOLUTION / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    setup_gate = instructions.index("### Setup gate for all other requests")
    assert instructions.index("`/build-skill`") < setup_gate
    assert "| `src/skills/ess-da-ga-skill-builder/SKILL.md`" in instructions
    menu = (_SOLUTION / ".github" / "prompts" / "menu.prompt.md").read_text(encoding="utf-8")
    readme = (_SOLUTION / "README.md").read_text(encoding="utf-8")
    assert "| `/build-skill` |" in menu and "| `/build-skill` |" in readme
