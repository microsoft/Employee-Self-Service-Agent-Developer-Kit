"""Carrying customer-authored cloud flows across the migration.

The Declarative Agent package can *reference* a flow but not *contain* one, so a
carried topic's ``InvokeFlowAction`` only resolves if the flow already exists in
the target. These tests cover the two halves of closing that gap: synthesising
the agent.yml ``flows:`` interface for each carried flow, and re-emitting the
customer's flows as an importable solution zip. They also cover the honest
degradation — a referenced flow whose definition cannot be carried is reported as
dangling, not silently dropped.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from essmig import flows, package_source


def _agent_with_flow(flow_id: str, *, declared: list[str] | None = None) -> dict:
    """A minimal agent doc: one topic invoking ``flow_id`` plus any declared flows."""
    return {
        "components": [
            {
                "schemaName": "gptagent_x.topic.ConversationStart",
                "data": {
                    "beginDialog": {
                        "actions": [
                            {"kind": "InvokeFlowAction", "flowId": flow_id},
                        ]
                    }
                },
            }
        ],
        "flows": [{"workflowId": wid} for wid in (declared or [])],
    }


def _carried_flow(flow_id: str, name: str = "ESS_GetUserProfile") -> flows.CarriedFlow:
    return flows.CarriedFlow(
        workflow_id=flows.canonical_id(flow_id),
        name=name,
        description="desc",
        json_name=f"{name}-{flow_id.upper()}.json",
        input_schema={
            "type": "object",
            "properties": {
                "email": {"title": "Email", "description": "an email", "type": "string"}
            },
            "required": ["email"],
        },
        output_schema={
            "properties": {
                "jobtitle": {"title": "JobTitle", "type": "string"},
                "active": {"title": "Active", "type": "boolean"},
            }
        },
        connectors=("shared_office365users",),
    )


def test_canonical_id_strips_braces_and_lowercases() -> None:
    assert flows.canonical_id("{802EA1E8-CAC0-072C-020C-E6AB29A74BAD}") == (
        "802ea1e8-cac0-072c-020c-e6ab29a74bad"
    )


def test_referenced_flow_ids_finds_invoke_flow_actions() -> None:
    agent = _agent_with_flow("802EA1E8-CAC0-072C-020C-E6AB29A74BAD")
    assert flows.referenced_flow_ids(agent) == {"802ea1e8-cac0-072c-020c-e6ab29a74bad"}


def test_declared_flow_ids_reads_the_flows_block() -> None:
    agent = _agent_with_flow("aaa", declared=["3164DAE9-3A2B-5843-98DD-E62BB5123324"])
    assert "3164dae9-3a2b-5843-98dd-e62bb5123324" in flows.declared_flow_ids(agent)


def test_interface_entry_maps_schema_types() -> None:
    entry = flows.interface_entry(_carried_flow("802ea1e8"))
    assert entry["workflowId"] == "802ea1e8"
    assert entry["triggerType"] == "Copilot"
    assert entry["connectionType"] == "EmbeddedOnly"
    assert entry["secureInputs"] is True and entry["secureOutputs"] is True
    email = entry["inputType"]["properties"]["email"]
    assert email == {
        "displayName": "Email",
        "description": "an email",
        "isRequired": True,
        "type": "String",
    }
    outputs = entry["outputType"]["properties"]
    assert outputs["jobtitle"] == {"displayName": "JobTitle", "type": "String"}
    assert outputs["active"]["type"] == "Boolean"


def test_interface_entry_omits_empty_output() -> None:
    flow = flows.CarriedFlow(
        workflow_id="x", name="F", description="", json_name="F.json", output_schema={}
    )
    assert "outputType" not in flows.interface_entry(flow)


def test_add_interfaces_adds_referenced_and_skips_declared() -> None:
    flow = _carried_flow("802ea1e8")
    agent = _agent_with_flow("802ea1e8")
    added = flows.add_interfaces(agent, [flow])
    assert [f.workflow_id for f in added] == ["802ea1e8"]
    assert "802ea1e8" in flows.declared_flow_ids(agent)
    # Idempotent: a second pass adds nothing.
    assert flows.add_interfaces(agent, [flow]) == []


def test_register_config_flows_maps_id_to_itself_and_skips_existing() -> None:
    config = {"flows": {"3164dae9": "3164dae9"}}
    added = flows.register_config_flows(config, [_carried_flow("802ea1e8")])
    assert added == ["802ea1e8"]
    assert config["flows"] == {"3164dae9": "3164dae9", "802ea1e8": "802ea1e8"}
    # Idempotent, and creates the block when absent.
    assert flows.register_config_flows(config, [_carried_flow("802ea1e8")]) == []
    empty: dict = {}
    flows.register_config_flows(empty, [_carried_flow("802ea1e8")])
    assert empty["flows"] == {"802ea1e8": "802ea1e8"}


def test_plan_splits_carried_dangling_and_template() -> None:
    carried = _carried_flow("802ea1e8")
    export = flows.FlowExport(
        flows=(carried,), solution_xml="", customizations_xml="", workflow_files={}
    )
    # ConversationStart invokes 802ea1e8 (carried) and template flow 3164; a second
    # topic invokes an unknown flow (dangling).
    agent = {
        "components": [
            {"data": {"a": [{"kind": "InvokeFlowAction", "flowId": "802ea1e8"}]}},
            {"data": {"a": [{"kind": "InvokeFlowAction", "flowId": "3164dae9"}]}},
            {"data": {"a": [{"kind": "InvokeFlowAction", "flowId": "deadbeef"}]}},
        ],
        "flows": [{"workflowId": "3164dae9"}],
    }
    findings = flows.plan(agent, export)
    assert [f.workflow_id for f in findings.carried] == ["802ea1e8"]
    assert findings.dangling == ("deadbeef",)
    assert findings.template_provided == ("3164dae9",)
    assert findings.needs_flow_import and findings.has_dangling


def test_plan_without_export_reports_customer_flow_as_dangling() -> None:
    agent = _agent_with_flow("802ea1e8", declared=["3164dae9"])
    findings = flows.plan(agent, None)
    assert findings.carried == ()
    assert findings.dangling == ("802ea1e8",)


def test_build_solution_zip_strips_missing_dependencies_and_carries_parts() -> None:
    export = flows.FlowExport(
        flows=(_carried_flow("802ea1e8"),),
        solution_xml=(
            "<ImportExportXml><SolutionManifest><UniqueName>S</UniqueName>"
            "<RootComponents><RootComponent type=\"29\" id=\"{802ea1e8}\" /></RootComponents>"
            "<MissingDependencies><MissingDependency>x</MissingDependency>"
            "</MissingDependencies></SolutionManifest></ImportExportXml>"
        ),
        customizations_xml="<ImportExportXml><Workflows /></ImportExportXml>",
        workflow_files={"ESS_GetUserProfile-802EA1E8.json": b"{}"},
    )
    raw = flows.build_solution_zip(export)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        solution = archive.read("solution.xml").decode("utf-8")
    assert names == {
        "[Content_Types].xml",
        "solution.xml",
        "customizations.xml",
        "Workflows/ESS_GetUserProfile-802EA1E8.json",
    }
    assert "<MissingDependency>" not in solution
    assert 'type="29"' in solution


# --- reading flows out of an exported package -------------------------------


def _flow_json(with_response: bool = True) -> str:
    definition = {
        "properties": {
            "connectionReferences": {
                "ref": {"api": {"name": "shared_office365users"}}
            },
            "definition": {
                "triggers": {
                    "manual": {
                        "type": "Request",
                        "inputs": {
                            "schema": {
                                "type": "object",
                                "properties": {"email": {"title": "Email", "type": "string"}},
                                "required": ["email"],
                            }
                        },
                    }
                },
                "actions": {
                    "Respond": {
                        "type": "Response",
                        "inputs": {
                            "schema": {"properties": {"jobtitle": {"title": "JobTitle"}}}
                        },
                    }
                }
                if with_response
                else {},
            },
        }
    }
    return json.dumps(definition)


def _write_flow_package(root: Path) -> None:
    workflow_id = "{802ea1e8-cac0-072c-020c-e6ab29a74bad}"
    json_name = "ESS_GetUserProfile-802EA1E8-CAC0-072C-020C-E6AB29A74BAD.json"
    (root / "solution.xml").write_text(
        "<ImportExportXml><SolutionManifest><UniqueName>S</UniqueName>"
        "<MissingDependencies /></SolutionManifest></ImportExportXml>",
        encoding="utf-8",
    )
    (root / "customizations.xml").write_text(
        "<ImportExportXml><Workflows>"
        f'<Workflow WorkflowId="{workflow_id}" Name="ESS_GetUserProfile" Description="d">'
        f"<JsonFileName>/Workflows/{json_name}</JsonFileName>"
        "</Workflow></Workflows></ImportExportXml>",
        encoding="utf-8",
    )
    (root / "Workflows").mkdir()
    (root / "Workflows" / json_name).write_text(_flow_json(), encoding="utf-8")


def test_read_flow_export_parses_workflow_and_definition(tmp_path: Path) -> None:
    _write_flow_package(tmp_path)
    export = package_source.read_flow_export(tmp_path)
    assert export is not None
    (flow,) = export.flows
    assert flow.workflow_id == "802ea1e8-cac0-072c-020c-e6ab29a74bad"
    assert flow.name == "ESS_GetUserProfile"
    assert flow.connectors == ("shared_office365users",)
    assert flow.input_schema["properties"]["email"]["title"] == "Email"
    assert flow.output_schema["properties"]["jobtitle"]["title"] == "JobTitle"
    assert set(export.workflow_files) == {
        "ESS_GetUserProfile-802EA1E8-CAC0-072C-020C-E6AB29A74BAD.json"
    }


def test_read_flow_export_returns_none_without_workflows(tmp_path: Path) -> None:
    (tmp_path / "solution.xml").write_text(
        "<ImportExportXml><SolutionManifest /></ImportExportXml>", encoding="utf-8"
    )
    (tmp_path / "customizations.xml").write_text(
        "<ImportExportXml><Workflows /></ImportExportXml>", encoding="utf-8"
    )
    assert package_source.read_flow_export(tmp_path) is None


def test_read_flow_export_from_zip(tmp_path: Path) -> None:
    staging = tmp_path / "pkg"
    staging.mkdir()
    _write_flow_package(staging)
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in staging.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(staging).as_posix())
    export = package_source.read_flow_export(archive)
    assert export is not None and len(export.flows) == 1
