from __future__ import annotations

import json
import zipfile
from pathlib import Path

from conftest import dialog_component, reference_set
from essmig.packaging import check_pointers, scrub_config, write_package, zip_package


def test_connection_ids_never_travel_in_the_package() -> None:
    scrubbed = scrub_config(
        {
            "connections": {
                "shared_service-now": {
                    "connectorId": "/providers/Microsoft.PowerApps/apis/shared_service-now",
                    "connectionId": "a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03",
                }
            }
        }
    )
    connection = scrubbed["connections"]["shared_service-now"]
    # Unbound means connectionId: null — the key stays (the ESS template ships it
    # this way and the import binding step needs it), but no source binding leaks.
    assert connection["connectionId"] is None
    assert connection["connectorId"].endswith("shared_service-now")


def test_literal_secrets_are_dropped_but_key_vault_references_survive() -> None:
    scrubbed = scrub_config(
        {"secrets": {"good": "kv://vault/secret", "bad": "hunter2"}}
    )
    assert scrubbed["secrets"] == {"good": "kv://vault/secret"}


def test_scrubbing_does_not_mutate_the_input() -> None:
    config = {"connections": {"x": {"connectionId": "abc"}}}
    scrub_config(config)
    assert config["connections"]["x"]["connectionId"] == "abc"


def test_pointers_with_no_matching_config_value_are_reported() -> None:
    agent = {"entity": {"displayName": '${config.values["botName"]}'}}
    assert check_pointers(agent, {"values": {}}) == ["botName"]
    assert check_pointers(agent, {"values": {"botName": "ESS HR"}}) == []


def test_pointers_are_found_wherever_they_appear_in_the_tree() -> None:
    agent = {"components": [{"dialog": {"a": ['${config.values["deep"]}']}}]}
    assert check_pointers(agent, {"values": {}}) == ["deep"]


def test_the_package_layout_matches_the_template(tmp_path: Path) -> None:
    reference = reference_set([dialog_component("topic.Foo", {"beginDialog": {"id": "main"}})])
    plugin = write_package(tmp_path, reference, reference.agent)
    schema = "gptagent_copilotforemployeeselfservicehr"

    assert (plugin / "package.json").is_file()
    assert (plugin / "Agents" / schema / "agent.yml").is_file()
    assert (plugin / "Agents" / schema / "app.config.dev.json").is_file()


def test_the_template_identity_is_carried_forward(tmp_path: Path) -> None:
    reference = reference_set([])
    plugin = write_package(tmp_path, reference, reference.agent)
    package = json.loads((plugin / "package.json").read_text(encoding="utf-8"))
    # These are what mark the agent as templated and upgradeable; they must survive.
    assert package["packageType"] == "templated"
    assert package["publisher"] == "microsoftfirstparty"
    assert package["createdBy"] == "ess-ca-to-da"


def test_the_zip_nests_everything_under_the_plugin_folder(tmp_path: Path) -> None:
    reference = reference_set([])
    schema = reference.da_schemaname
    plugin = write_package(tmp_path, reference, reference.agent)
    archive = zip_package(plugin, tmp_path / "package.zip")

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    # The import API rejects a package whose agent.yml is not under Plugin/Agents/.
    assert "Plugin/package.json" in names
    assert f"Plugin/Agents/{schema}/agent.yml" in names
    assert all(name.startswith("Plugin/") for name in names)
