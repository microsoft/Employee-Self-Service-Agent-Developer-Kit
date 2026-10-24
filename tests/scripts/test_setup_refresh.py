# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exercise initial extraction and repeated refresh through the real setup CLI."""

import json
import sys

import pytest
import setup


def _component(component_id="selected-component", name="Greeting", ctype=9, **extra):
    return {
        "botcomponentid": component_id,
        "name": name,
        "schemaname": f"selected.component.{component_id}",
        "componenttype": ctype,
        "data": "kind: AdaptiveDialog\n",
        **extra,
    }


def _run_setup(tmp_path, monkeypatch, *, refresh=False, inventory=None):
    components = tmp_path / "components.json"
    components.write_text(
        json.dumps([_component()] if inventory is None else inventory),
        encoding="utf-8",
    )
    arguments = [
        "setup.py", "--url", "https://selected.crm.dynamics.com",
        "--bot-id", "selected-bot", "--name", "Selected Agent",
        "--schema", "selected", "--components", str(components),
    ]
    if refresh:
        arguments.append("--refresh")
    monkeypatch.setattr(sys, "argv", arguments)
    setup.main()


@pytest.mark.parametrize("saved_folder", ["", "workspace/agents/other-agent"])
def test_refresh_checkpoints_selected_folder_and_replaces_baseline(
    tmp_path, monkeypatch, saved_folder,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    _run_setup(tmp_path, monkeypatch)
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    topic = next((agent / "topics").rglob("*.mcs.yml"))
    topic.write_text("local edit\n", encoding="utf-8")
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["agent"]["folder"] = saved_folder
    config["ring"] = "prod"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    _run_setup(tmp_path, monkeypatch, refresh=True)

    assert topic.read_text(encoding="utf-8") == "kind: AdaptiveDialog\n"
    copies = list((agent / ".checkpoints").rglob(topic.name))
    assert len(copies) == 1
    assert copies[0].read_text(encoding="utf-8") == "local edit\n"
    assert (agent / ".baseline" / topic.relative_to(agent)).read_text(
        encoding="utf-8",
    ) == "kind: AdaptiveDialog\n"
    assert not (agent / ".baseline" / ".checkpoints").exists()
    refreshed = json.loads(config_path.read_text(encoding="utf-8"))
    assert refreshed["ring"] == "prod"
    assert refreshed["agent"]["botId"] == "selected-bot"


def test_refresh_stops_before_overwrite_when_checkpoint_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    _run_setup(tmp_path, monkeypatch)
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    topic = next((agent / "topics").rglob("*.mcs.yml"))
    topic.write_text("local edit\n", encoding="utf-8")
    config_path = tmp_path / ".local" / "config.json"
    original_config = config_path.read_bytes()

    def fail_checkpoint(*args):
        raise OSError("checkpoint storage unavailable")

    monkeypatch.setattr(setup, "create_checkpoint", fail_checkpoint)

    with pytest.raises(OSError, match="checkpoint storage unavailable"):
        _run_setup(tmp_path, monkeypatch, refresh=True)

    assert topic.read_text(encoding="utf-8") == "local edit\n"
    assert config_path.read_bytes() == original_config


@pytest.mark.parametrize("ctype,folder", [
    (9, "topics"), (12, "variables"), (16, "knowledge"),
    (14, "attachments"), (99, "other"),
])
def test_refresh_removes_deleted_owned_files_but_preserves_local_only(
    tmp_path, monkeypatch, ctype, folder,
):
    monkeypatch.chdir(tmp_path)
    _run_setup(tmp_path, monkeypatch, inventory=[
        _component(), _component("deleted", "User Context", ctype),
    ])
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    deleted = agent / folder / "user-context.mcs.yml"
    deleted.write_text("locally edited deleted component\n", encoding="utf-8")
    local = agent / folder / "local-only.mcs.yml"
    local.write_text("local-only content\n", encoding="utf-8")
    if ctype == 9:
        from flightcheck.checks.local_files import _check_required_topics

        before = next(
            row for row in _check_required_topics(agent, "Selected", None, "")
            if row.checkpoint_id == "TOPIC-001"
        )
        assert before.status == "Passed"
        assert before.result == "Topic found"

    _run_setup(tmp_path, monkeypatch, refresh=True)

    assert not deleted.exists()
    assert not (agent / ".baseline" / deleted.relative_to(agent)).exists()
    assert (agent / ".checkpoints" / "1" / deleted.relative_to(agent)).read_text(
        encoding="utf-8",
    ) == "locally edited deleted component\n"
    assert local.read_text(encoding="utf-8") == "local-only content\n"
    assert (agent / ".baseline" / local.relative_to(agent)).is_file()
    if ctype == 9:
        result = next(
            row for row in _check_required_topics(agent, "Selected", None, "")
            if row.checkpoint_id == "TOPIC-001"
        )
        assert result.status == "Warning"
        assert "Required topic not found" in result.result
        assert "Verify '[Admin] User Context - Setup'" in result.remediation


def test_refresh_renames_owned_file_and_allows_reusing_deleted_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _run_setup(tmp_path, monkeypatch, inventory=[
        _component(), _component("removed", "Old"),
    ])
    agent = tmp_path / "workspace" / "agents" / "selected-agent"

    _run_setup(tmp_path, monkeypatch, refresh=True, inventory=[
        _component(name="Renamed"), _component("replacement", "Old", data="new\n"),
    ])

    assert not (agent / "topics" / "greeting.mcs.yml").exists()
    assert (agent / "topics" / "renamed.mcs.yml").is_file()
    assert (agent / "topics" / "old.mcs.yml").read_text(encoding="utf-8") == "new\n"


def test_refresh_preserves_optional_inventory_files_and_ownership(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _run_setup(tmp_path, monkeypatch)
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    map_path = agent / ".component-map.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    optional = {
        "template-configs/config.xml": {"templateconfigid": "config-id"},
        "workflows/flow/workflow.json": {"workflowid": "flow-id"},
    }
    for relative in optional:
        path = agent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("optional content", encoding="utf-8")
    map_path.write_text(json.dumps({**mapping, **optional}), encoding="utf-8")

    _run_setup(tmp_path, monkeypatch, refresh=True)

    refreshed = json.loads(map_path.read_text(encoding="utf-8"))
    for relative, entry in optional.items():
        assert refreshed[relative] == entry
        assert (agent / relative).read_text(encoding="utf-8") == "optional content"


@pytest.mark.parametrize("problem", [
    "missing-map", "corrupt-map", "non-object-map", "invalid-entry", "missing-id",
    "unsafe-path", "protected-path", "drive-path", "backslash-traversal",
    "missing-data", "invalid-data", "duplicate-id", "duplicate-path", "local-conflict", "empty",
    "mapped-directory",
])
def test_refresh_refuses_untrustworthy_input_before_overwrite(
    tmp_path, monkeypatch, problem,
):
    monkeypatch.chdir(tmp_path)
    _run_setup(tmp_path, monkeypatch)
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    topic = agent / "topics" / "greeting.mcs.yml"
    topic.write_text("local edit\n", encoding="utf-8")
    map_path = agent / ".component-map.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    inventory = [_component()]
    if problem == "missing-map":
        map_path.unlink()
    elif problem == "corrupt-map":
        map_path.write_text("{", encoding="utf-8")
    elif problem == "non-object-map":
        map_path.write_text("[]", encoding="utf-8")
    elif problem == "invalid-entry":
        map_path.write_text(json.dumps({"topics/greeting.mcs.yml": None}), encoding="utf-8")
    elif problem == "missing-id":
        mapping["topics/greeting.mcs.yml"]["botcomponentid"] = None
        map_path.write_text(json.dumps(mapping), encoding="utf-8")
    elif problem in {"unsafe-path", "protected-path", "drive-path", "backslash-traversal"}:
        path = {
            "unsafe-path": "../outside.mcs.yml",
            "protected-path": ".baseline/owned.mcs.yml",
            "drive-path": "C:\\outside.mcs.yml",
            "backslash-traversal": "topics\\..\\..\\outside.mcs.yml",
        }[problem]
        map_path.write_text(json.dumps({path: next(iter(mapping.values()))}), encoding="utf-8")
    elif problem == "missing-data":
        inventory = [_component(data=None)]
    elif problem == "invalid-data":
        inventory.append(_component("different", "Different", data={"not": "text"}))
    elif problem == "duplicate-id":
        inventory.append(_component(name="Different"))
    elif problem == "duplicate-path":
        inventory.append(_component("different", "Greeting!"))
    elif problem == "local-conflict":
        (agent / "topics" / "local-only.mcs.yml").write_text("local", encoding="utf-8")
        inventory.append(_component("different", "Local Only"))
    elif problem == "empty":
        inventory = []
    elif problem == "mapped-directory":
        mapping["topics/directory.mcs.yml"] = _component("directory")
        (agent / "topics" / "directory.mcs.yml").mkdir()
        map_path.write_text(json.dumps(mapping), encoding="utf-8")
    original_map = map_path.read_bytes() if map_path.exists() else None
    original_config = (tmp_path / ".local" / "config.json").read_bytes()

    with pytest.raises(SystemExit) as exc:
        _run_setup(tmp_path, monkeypatch, refresh=True, inventory=inventory)

    assert exc.value.code == 1
    assert topic.read_text(encoding="utf-8") == "local edit\n"
    assert (agent / ".baseline" / "topics" / "greeting.mcs.yml").read_text(
        encoding="utf-8",
    ) == "kind: AdaptiveDialog\n"
    assert (map_path.read_bytes() if map_path.exists() else None) == original_map
    assert (tmp_path / ".local" / "config.json").read_bytes() == original_config
    assert not (agent / ".checkpoints").exists()


def test_refresh_cleanup_failure_does_not_publish_map_or_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _run_setup(tmp_path, monkeypatch, inventory=[_component(), _component("deleted", "Old")])
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    original_map = (agent / ".component-map.json").read_bytes()
    original_remove = setup.os.remove

    def fail_cleanup(path):
        if str(path).endswith("old.mcs.yml"):
            raise PermissionError("stale file locked")
        return original_remove(path)

    monkeypatch.setattr(setup.os, "remove", fail_cleanup)
    with pytest.raises(PermissionError, match="stale file locked"):
        _run_setup(tmp_path, monkeypatch, refresh=True)

    assert (agent / ".component-map.json").read_bytes() == original_map
    assert (agent / ".baseline" / "topics" / "old.mcs.yml").exists()
    assert (agent / ".checkpoints" / "1" / "topics" / "old.mcs.yml").exists()


@pytest.mark.parametrize("ctype,relative,data", [
    (15, "agent.mcs.yml", "kind: GptComponent\n"),
    (18, "settings.mcs.yml", "kind: Settings\n"),
    (19, "evaluations/old/old.mcs.yml", "kind: EvaluationSet\n"),
])
def test_refresh_reconciles_singletons_and_evaluation_sources(
    tmp_path, monkeypatch, ctype, relative, data,
):
    monkeypatch.chdir(tmp_path)
    _run_setup(tmp_path, monkeypatch, inventory=[
        _component(), _component("deleted", "Old", ctype, data=data),
    ])
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    assert (agent / relative).is_file()

    _run_setup(tmp_path, monkeypatch, refresh=True)

    assert not (agent / relative).exists()
    assert not (agent / ".baseline" / relative).exists()
    assert (agent / ".checkpoints" / "1" / relative).is_file()


@pytest.mark.parametrize("relative", [
    "/outside.mcs.yml", "\\\\server\\share\\outside.mcs.yml",
    "topics/file.mcs.yml:stream", ".checkpoints/1/file.mcs.yml",
    "topics/./file.mcs.yml", "topics/../file.mcs.yml",
    "topics /file.mcs.yml",
])
def test_component_paths_refuse_unsafe_manifest_paths(tmp_path, relative):
    with pytest.raises(ValueError, match="Unsafe component path"):
        setup.checked_component_path(str(tmp_path), relative)


def test_component_inventory_rejects_unfetched_pages(tmp_path):
    inventory = tmp_path / "partial.json"
    inventory.write_text(json.dumps({
        "value": [_component()], "@odata.nextLink": "next-page",
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="all component inventory pages"):
        setup.load_json(inventory, require_complete=True)
