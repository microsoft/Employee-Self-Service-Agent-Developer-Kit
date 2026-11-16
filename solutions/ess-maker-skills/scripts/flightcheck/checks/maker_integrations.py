# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Optional integration applicability from the exact agent's captured read contracts."""

from dataclasses import asdict

from ._connection_dependencies import (
    READ_ERRORS, ConnectionAudit, _Access, _connector, _dependencies, _direct_references, _mapping, _nodes, _sap_only_topic,
)
from .workday_da import reviewed_workday_topic_schemas
from ..runner import CheckResult, Priority, Role, Status


CONNECTORS = {"Workday": "shared_workdaysoap", "ServiceNow": "shared_service-now"}


def _result(key, category, status, description, finding, *, evidence, remediation=""):
    return CheckResult(
        key, category, Priority.HIGH.value, status, description, finding, remediation,
        roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        evidence=evidence,
    )


def run_optional_integration_checks(runner, *, workday_configured=False):
    snapshot = getattr(runner, "_da_native_snapshot", None)
    audit = getattr(runner, "_da_connection_audit", None)
    if snapshot is None or audit is None:
        runner.maker_integrations = {}
        return []
    payload = snapshot["changeset"]
    limitations = []
    active_limitations = []
    inactive_audit = ConnectionAudit()
    try:
        direct = _direct_references(payload)
    except ValueError as exc:
        direct = {}
        limitations.append(str(exc))
        active_limitations.append(str(exc))
    schema = payload["bot"]["schemaName"]
    expected = {value.casefold() for value in reviewed_workday_topic_schemas(schema)}
    flows = getattr(runner, "_maker_flow_details", {})
    access = _Access(runner)
    selected = getattr(runner, "da_integration_names", frozenset(CONNECTORS))
    connectors_in_scope = {name: value for name, value in CONNECTORS.items() if name in selected}
    related = {name: [] for name in connectors_in_scope}
    for change in payload["botComponentChanges"]:
        component = change["component"]
        if component["$kind"] != "DialogComponent" or _sap_only_topic(component, payload):
            continue
        topic_limitations = []
        flow_audit = inactive_audit if component.get("status") == "Inactive" else audit
        connectors = set()
        if str(component.get("schemaName") or "").casefold() in expected:
            connectors.add(CONNECTORS["Workday"])
        for node in _nodes(component.get("dialog")):
            if node.get("$kind") == "InvokeConnectorAction":
                reference = direct.get(str(node.get("connectionReference") or "").casefold())
                if reference is None:
                    topic_limitations.append("A conversation has an unresolved connector reference.")
                else:
                    connectors.add(_connector(reference["connectorId"]))
            elif node.get("$kind") == "InvokeFlowAction":
                # The same parser validates active and inactive target IDs. Changing
                # a copy's status here never changes or proves actual activation.
                candidate = {**component, "status": "Active"}
                _, ids, errors = _dependencies({"botComponentChanges": [{"component": candidate}]})
                topic_limitations.extend(errors)
                for flow_id in ids:
                    if flow_id not in flows:
                        try:
                            flows[flow_id] = _mapping(
                                access.admin(flow=True).get_flow(runner.env_id, flow_id),
                                "Integration flow detail",
                            )
                        except READ_ERRORS as exc:
                            flow_audit.record_read_error(exc, f"Flow {flow_id}: integration discovery")
                            flows[flow_id] = exc
                    flow = flows[flow_id]
                    properties = flow.get("properties") if isinstance(flow, dict) else None
                    references = properties.get("connectionReferences") if isinstance(properties, dict) else None
                    if not isinstance(references, dict):
                        if not isinstance(flow, BaseException):
                            flow_audit.record_read_error(
                                ValueError("Flow detail omitted the supported connector-reference inventory."),
                                f"Flow {flow_id}: integration discovery",
                            )
                        topic_limitations.append(f"Flow {flow_id}: integration could not be determined.")
                        continue
                    for ref in references.values():
                        api = ref.get("apiDefinition") if isinstance(ref, dict) else None
                        connector_id = api.get("id") if isinstance(api, dict) else None
                        if isinstance(connector_id, str) and connector_id:
                            connectors.add(_connector(connector_id))
                        else:
                            topic_limitations.append(f"Flow {flow_id}: connector identity is unavailable.")
        for name, connector in connectors_in_scope.items():
            if connector in connectors:
                related[name].append({
                    "topic": component.get("schemaName", component.get("id", "")),
                    "activation": component.get("status", "unknown"),
                })
        if component.get("status") not in {"Active", "Inactive"} and connectors != {"shared_sapodata"}:
            topic_limitations.append("A conversation's activation is unknown.")
        limitations.extend(topic_limitations)
        if component.get("status") != "Inactive":
            active_limitations.extend(topic_limitations)

    rows, states = [], {}
    for name, connector in connectors_in_scope.items():
        prefix = "WD" if name == "Workday" else "SN"
        topics = related[name]
        declared = [item for item in direct.values() if _connector(item["connectorId"]) == connector]
        enabled = connector in audit.discovered_connectors or any(t["activation"] == "Active" for t in topics)
        uncertain = bool(limitations or audit.blocked or audit.warnings or audit.read_limitations)
        state = (
            "enabled" if enabled else "unknown" if uncertain else
            "disabled" if topics and all(t["activation"] == "Inactive" for t in topics) else
            "configured" if declared or (name == "Workday" and workday_configured) else "not_configured"
        )
        evidence = {
            "applicability": state, "topics": topics, "declaredReferences": len(declared),
            "discoveryLimitations": list(dict.fromkeys(
                [*limitations, *audit.warnings, *([audit.blocked] if audit.blocked else [])]
            )),
            "evidenceBoundary": "selected_agent_configuration_not_employee_execution",
            "inventoryReadLimitations": inactive_audit.read_limitations,
        }
        states[name] = evidence
        finding = {
            "enabled": f"{name} is used by active conversations or flows in this agent.",
            "disabled": f"{name} conversations are explicitly inactive. Integration health checks were not required.",
            "configured": f"{name} configuration is present, but no active use was verified. It is not required merely because it is configured.",
            "not_configured": f"No {name} configuration or use was found in this agent. This optional integration is not required.",
            "unknown": f"Discovery was incomplete; this run cannot establish whether {name} is enabled.",
        }[state]
        rows.append(_result(
            f"{prefix}-INTEGRATION-001", name,
            Status.PASSED.value if state == "enabled" else Status.BLOCKED.value if state == "unknown" else Status.NOT_CONFIGURED.value,
            f"{name} integration applicability", finding, evidence=evidence,
            remediation="Resolve the listed discovery limitations and rerun; do not assume this integration is disabled." if state == "unknown" else "",
        ))
        if state != "enabled":
            continue
        references = [ref for ref in audit.references if _connector(ref.connector_id) == connector]
        failed = any(
            ref.failures or ref.connection_id is None or ref.connection_id == ""
            for ref in references
        )
        # Connector/binding mismatches are diagnosed by the shared exact audit.
        # Never report this subset healthy when its inventory was inconclusive.
        binding_uncertain = bool(active_limitations or audit.blocked or audit.warnings or audit.read_limitations)
        status = Status.FAILED.value if failed else Status.BLOCKED.value if binding_uncertain or not references else Status.PASSED.value
        rows.append(_result(
            f"{prefix}-CONN-001", name, status, f"{name} connection bindings",
            f"{len(references)} required {name} reference(s) inspected. "
            + ("Exact bindings were verified; employee authentication was not tested." if status == Status.PASSED.value else
               "See the exact dependency findings; these bindings are not verified healthy."),
            evidence={
                "references": [asdict(ref) for ref in references],
                "dependencyCoverageComplete": not binding_uncertain,
                "inactiveInventoryReadLimitations": inactive_audit.read_limitations,
            },
            remediation="" if status == Status.PASSED.value else "Repair the identified binding or resolve its read-access limitation in Connection Settings.",
        ))
        relevant_flows = {flow_id for ref in references for flow_id in ref.flow_ids}
        if name == "ServiceNow" and relevant_flows:
            observed = {
                flow_id: (flows.get(flow_id, {}).get("properties", {}).get("state")
                          if isinstance(flows.get(flow_id), dict) else None)
                for flow_id in relevant_flows
            }
            stopped = [key for key, state_value in observed.items() if state_value in {"Stopped", "Suspended"}]
            unknown = [key for key, state_value in observed.items() if state_value not in {"Started", "Stopped", "Suspended"}]
            status = "Failed" if stopped else "Blocked" if unknown else "Passed"
            rows.append(_result(
                "SN-FLOW-001", name, status, "ServiceNow invoked flow state",
                f"Inspected {len(observed)} invoked flow(s); {len(stopped)} stopped/suspended and {len(unknown)} unverified.",
                evidence={"flowStates": observed},
                remediation="" if status == "Passed" else "Inspect the listed flows in Power Automate; enable only the flows this agent is intended to invoke.",
            ))
    runner.maker_integrations = states
    runner.maker_workday_extension = any(
        change["component"].get("$kind") == "DialogComponent"
        and str(change["component"].get("schemaName") or "").casefold() in expected
        and change["component"].get("status") == "Active"
        for change in payload["botComponentChanges"]
    )
    return rows
