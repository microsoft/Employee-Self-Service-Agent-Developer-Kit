# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read the selected agents' active connection dependencies, without setup state.

Native topic references are agent-local. Flow references are solution-local and
must be joined by logical name, not inferred from the connector's presence in an
environment. A failed read leaves coverage incomplete even if other reads work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import requests

from auth import discover_tenant, query_all
from ..agent_scope import configured_agents
from ..pp_admin_client import FLOW_SCOPE, PP_SCOPE, PPAdminClient
from ._da_connection_refs import agent_bot_ids, _require_identity_field


READ_ERRORS = (ValueError, RuntimeError, PermissionError, requests.RequestException)


@dataclass
class Reference:
    agent_id: str
    logical_name: str
    connector_id: str
    connection_id: str | None
    flow_ids: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class ConnectionAudit:
    references: list[Reference] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: str = ""
    additional_connections: int = 0
    flow_count: int = 0
    discovered_connectors: set[str] = field(default_factory=set)
    has_direct_references: bool = False
    excluded_topics: list[dict[str, str]] = field(default_factory=list)
    read_limitations: list[dict[str, Any]] = field(default_factory=list)

    def record_read_error(self, exc, context):
        response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None) or (
            response.status_code if response is not None else None
        )
        if isinstance(exc, PermissionError):
            status = 403
        self.read_limitations.append({
            "context": context, "type": type(exc).__name__, "httpStatus": status,
            "kind": "permission_denied" if status == 403 else "error",
        })


def selected_agent_ids(runner) -> tuple[str, ...]:
    explicit = getattr(runner, "connection_agent_ids", None)
    values = explicit if explicit is not None else agent_bot_ids(
        getattr(runner, "config", None) or {}
    )
    return tuple(dict.fromkeys(str(UUID(value)) for value in values))


def _identity(value: Any, field_name: str) -> str:
    return _require_identity_field(value, field_name).strip()


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} returned an invalid object.")
    if value.get("_error"):
        if value.get("_status") == 403:
            raise PermissionError(f"{name} returned HTTP 403.")
        raise RuntimeError(f"{name} failed: HTTP {value.get('_status')}; {value['_error']}.")
    return value


def _connector(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1].casefold()


def _connection(value: str) -> str:
    return value.rstrip("/").rsplit("/", 1)[-1].casefold()


def _nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item)


def _sap_only_topic(component: dict, payload: dict) -> bool:
    """Only exclude self-contained SAP calls, never names or guessed activation."""
    dialog = component.get("dialog")
    if not isinstance(dialog, dict) or dialog.get("$kind") != "AdaptiveDialog":
        return False
    begin = dialog.get("beginDialog")
    actions = begin.get("actions") if isinstance(begin, dict) else None
    if not isinstance(actions, list) or not actions or any(
        not isinstance(action, dict)
        or action.get("$kind") not in {"InvokeConnectorAction", "SetVariable", "SendActivity"}
        for action in actions
    ):
        return False
    nodes = list(_nodes(dialog))
    if any(
        node.get("$kind") == "BeginDialog"
        or (isinstance(node.get("$kind"), str) and node["$kind"].endswith("Action")
            and node["$kind"] != "InvokeConnectorAction")
        for node in nodes
    ):
        return False
    calls = [node for node in nodes if node.get("$kind") == "InvokeConnectorAction"]
    changes = payload.get("connectionReferenceChanges")
    if not calls or not isinstance(changes, list):
        return False
    for call in calls:
        name = call.get("connectionReference")
        if not isinstance(name, str) or not name.strip():
            return False
        matches = [
            change["connectionReference"] for change in changes
            if isinstance(change, dict) and isinstance(change.get("connectionReference"), dict)
            and isinstance(change["connectionReference"].get("connectionReferenceLogicalName"), str)
            and change["connectionReference"]["connectionReferenceLogicalName"].casefold() == name.casefold()
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("connectorId"), str):
            return False
        if _connector(matches[0]["connectorId"]) != "shared_sapodata":
            return False
    return True


def _dependencies(
    payload: dict, *, excluded_topics: list[dict[str, str]] | None = None,
) -> tuple[set[str], set[str], list[str]]:
    changes = payload.get("botComponentChanges")
    if not isinstance(changes, list):
        raise ValueError("Component fetch omitted the topic collection.")
    direct: set[str] = set()
    flows: set[str] = set()
    warnings: list[str] = []
    for index, change in enumerate(changes, 1):
        component = change.get("component") if isinstance(change, dict) else None
        if not isinstance(component, dict):
            warnings.append(f"Component {index}: malformed component.")
            continue
        if component.get("$kind") != "DialogComponent":
            continue
        subject = component.get("schemaName") or f"component {index}"
        status = component.get("status")
        if status == "Inactive":
            continue
        if excluded_topics is not None and _sap_only_topic(component, payload):
            excluded_topics.append({
                "topic": str(subject), "reason": "self_contained_sap_only_calls",
                "activation": status if status == "Active" else "unverified",
            })
            continue
        if status != "Active":
            warnings.append(
                f"Topic {subject}: activation could not be verified "
                "(status must be Active or Inactive; component state is not activation evidence)."
            )
            continue
        if not isinstance(component.get("dialog"), dict):
            warnings.append(f"Topic {subject}: dialog could not be verified.")
            continue
        for node in _nodes(component["dialog"]):
            try:
                if node.get("$kind") == "InvokeFlowAction":
                    flows.add(str(UUID(_identity(node.get("flowId"), "flowId"))))
                elif node.get("$kind") == "InvokeConnectorAction":
                    direct.add(_identity(
                        node.get("connectionReference"), "connectionReference"
                    ).casefold())
            except ValueError as exc:
                warnings.append(f"Topic {subject}: dependency could not be verified ({exc}).")
    return direct, flows, warnings


def _direct_references(payload: dict) -> dict[str, dict]:
    changes = payload.get("connectionReferenceChanges", [])
    if not isinstance(changes, list):
        raise ValueError("Malformed native connection-reference collection.")
    references: dict[str, dict] = {}
    for change in changes:
        item = change.get("connectionReference") if isinstance(change, dict) else None
        if not isinstance(item, dict):
            raise ValueError("Malformed native connection reference.")
        name = _identity(item.get("connectionReferenceLogicalName"), "logical name")
        _identity(item.get("connectorId"), "connectorId")
        key = name.casefold()
        if key in references:
            raise ValueError("Duplicate native connection-reference identity.")
        references[key] = item
    return references


class _Access:
    def __init__(self, runner):
        self.runner = runner
        self.token_provider = getattr(runner, "connection_dependency_token", None)
        self.pp = (
            getattr(runner, "_da_pp_read_client", None)
            if self.token_provider else getattr(runner, "pp_admin", None)
        )

    def admin(self, *, flow: bool = False):
        if getattr(self.runner, "ring", "prod") != "prod":
            raise ValueError("Flow and connection administration is only verified on the prod service ring.")
        if self.token_provider:
            if self.pp is None:
                self.pp = PPAdminClient(self.runner.tenant_id)
                self.runner._da_pp_read_client = self.pp
            if flow and not self.pp.has_flow_token:
                self.pp.set_read_tokens(flow_token=self.token_provider(FLOW_SCOPE))
            if not flow and not self.pp.has_powerapps_token:
                self.pp.set_read_tokens(powerapps_token=self.token_provider(PP_SCOPE))
        if self.pp is None:
            raise ValueError("Power Platform administration read access is unavailable.")
        return self.pp

    def dataverse(self) -> tuple[str, str]:
        env_url = str(getattr(self.runner, "env_url", "") or "").strip().rstrip("/")
        token = getattr(self.runner, "dv_token", None)
        cached = getattr(self.runner, "_da_dependency_dataverse", None)
        if self.token_provider and cached:
            cached_url, cached_token, cached_pp = cached
            if env_url and env_url.casefold() != cached_url.casefold():
                raise ValueError("The Dataverse URL differs from the verified selected environment.")
            self.pp = cached_pp
            return cached_url, cached_token
        if self.token_provider:
            snapshot = getattr(self.runner, "_maker_environment_snapshot", None)
            environment = _mapping(
                snapshot if snapshot is not None else self.admin().get_environment(self.runner.env_id),
                "Environment lookup",
            )
            if str(environment.get("name", "")).casefold() != self.runner.env_id.casefold():
                raise ValueError("Environment lookup returned a different subject.")
            self.runner._maker_environment_snapshot = environment
            properties = _mapping(environment.get("properties"), "Environment properties")
            metadata = _mapping(properties.get("linkedEnvironmentMetadata"), "Linked environment metadata")
            server_url = _identity(metadata.get("instanceUrl"), "Dataverse URL").rstrip("/")
            verified_urls = {
                value.strip().rstrip("/").casefold()
                for field_name in ("instanceUrl", "instanceApiUrl")
                if isinstance(value := metadata.get(field_name), str) and value.strip()
            }
            if env_url and env_url.casefold() not in verified_urls:
                raise ValueError("The Dataverse URL belongs to a different Power Platform environment.")
            env_url = env_url or server_url
            parsed = urlparse(env_url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.path
                    or parsed.query or parsed.fragment or parsed.username
                    or parsed.password or parsed.port not in (None, 443)):
                raise ValueError("The environment has no verified Dataverse root URL.")
            if str(discover_tenant(env_url)).casefold() != self.runner.tenant_id.casefold():
                raise ValueError("Dataverse belongs to a different tenant.")
            token = self.token_provider(env_url + "/user_impersonation")
        if not env_url or not token:
            raise ValueError("Dataverse connection-reference read access is unavailable.")
        if getattr(self.runner, "maker_diagnostics", False) is True:
            self.runner._da_dependency_dataverse = (env_url, token, self.pp)
        return env_url, token


def audit_connections(runner) -> ConnectionAudit:
    """Return failures and incomplete evidence separately; never substitute agents.

    Only a successful admin-scoped inventory can prove a physical connection is
    absent. A maker-visible listing alone is insufficient evidence of deletion.
    """
    audit = ConnectionAudit()
    if getattr(runner, "connection_validation_error", None):
        audit.blocked = runner.connection_validation_error
        return audit
    if getattr(runner, "connection_agent_ids", None) is None:
        for index, agent in enumerate(configured_agents(
            getattr(runner, "config", None) or {}
        ), 1):
            bot_id = agent.get("botId")
            if not isinstance(bot_id, str) or not bot_id.strip():
                subject = agent.get("slug") or f"configured agent {index}"
                audit.warnings.append(
                    f"Agent {subject}: dependency discovery incomplete (botId not available)."
                )
    try:
        agent_ids = selected_agent_ids(runner)
    except (ValueError, TypeError, AttributeError):
        audit.blocked = "The target agent ID must be a GUID."
        return audit
    if not agent_ids or getattr(runner, "agentbuilder", None) is None:
        audit.blocked = "An exact agent target and AgentBuilder read access are required."
        return audit
    access = _Access(runner)
    required: dict[tuple[str, str], Reference] = {}
    flow_details: dict[str, dict | Exception] = {}
    runner._maker_flow_details = flow_details
    for agent_id in agent_ids:
        try:
            agent = _mapping(runner.agentbuilder.get_agent(agent_id), "Agent lookup")
            if str(agent.get("botId", "")).casefold() != agent_id.casefold():
                raise ValueError("Agent lookup returned a different subject.")
            snapshot = getattr(runner, "_da_native_snapshot", None)
            if (
                getattr(runner, "maker_diagnostics", False) is True
                and isinstance(snapshot, dict)
                and snapshot.get("agentId") == agent_id
                and snapshot.get("environmentId") == runner.env_id
            ):
                payload = snapshot["changeset"]
            else:
                payload = runner.agentbuilder.fetch_components(agent_id)
            if not isinstance(payload, dict):
                raise ValueError("Component fetch returned a malformed snapshot.")
            da_full = getattr(runner, "maker_diagnostics", False) is True
            direct, flow_ids, topic_warnings = _dependencies(
                payload, excluded_topics=audit.excluded_topics if da_full else None,
            )
            audit.warnings.extend(
                f"Agent {agent_id}: dependency discovery incomplete ({warning})."
                for warning in topic_warnings
            )
            native = _direct_references(payload) if direct else {}
            if da_full:
                direct = {
                    name for name in direct
                    if name not in native or _connector(native[name]["connectorId"]) != "shared_sapodata"
                }
            audit.has_direct_references |= bool(direct)
        except READ_ERRORS as exc:
            audit.record_read_error(exc, f"agent:{agent_id}")
            audit.warnings.append(f"Agent {agent_id}: dependency discovery incomplete ({type(exc).__name__}: {exc}).")
            continue
        for name in sorted(direct):
            item = native.get(name)
            if item is None:
                audit.failures.append(f"Agent {agent_id}: required native reference {name} is missing.")
                continue
            selected_connectors = getattr(runner, "da_connector_filter", None)
            if selected_connectors is not None and _connector(item["connectorId"]) not in selected_connectors:
                continue
            audit.discovered_connectors.add(_connector(item["connectorId"]))
            audit.references.append(Reference(
                agent_id, item["connectionReferenceLogicalName"],
                item["connectorId"], item.get("connectionId"),
            ))
        audit.flow_count += len(flow_ids)
        for flow_id in sorted(flow_ids):
            try:
                # Flows are environment-local, while every consumer still needs
                # its own reference and incomplete-read evidence.
                if flow_id not in flow_details:
                    try:
                        flow_details[flow_id] = _mapping(
                            access.admin(flow=True).get_flow(runner.env_id, flow_id),
                            "Flow lookup",
                        )
                    except READ_ERRORS as exc:
                        flow_details[flow_id] = exc
                detail = flow_details[flow_id]
                if isinstance(detail, Exception):
                    raise detail
                properties = _mapping(detail.get("properties"), "Flow properties")
                refs = properties.get("connectionReferences")
                if not isinstance(refs, dict):
                    raise ValueError("Flow detail omitted its connection-reference map.")
                for item in refs.values():
                    if not isinstance(item, dict):
                        raise ValueError("Flow detail returned a malformed connection reference.")
                    name = _identity(item.get("connectionReferenceLogicalName"), "logical name")
                    connector = _identity(
                        _mapping(item.get("apiDefinition"), "Flow connector").get("id"), "connector ID"
                    )
                    selected_connectors = getattr(runner, "da_connector_filter", None)
                    if selected_connectors is not None and _connector(connector) not in selected_connectors:
                        continue
                    audit.discovered_connectors.add(_connector(connector))
                    key = (agent_id, name.casefold())
                    if key in required:
                        if _connector(required[key].connector_id) != _connector(connector):
                            audit.failures.append(f"Agent {agent_id}: flows disagree on the connector for {name}.")
                            required[key].failures.append("Invoked flows disagree on the required connector.")
                        required[key].flow_ids.append(flow_id)
                    else:
                        required[key] = Reference(agent_id, name, connector, None, [flow_id])
            except READ_ERRORS as exc:
                audit.record_read_error(exc, f"flow:{flow_id}")
                audit.warnings.append(f"Agent {agent_id}, flow {flow_id}: dependencies unverified ({type(exc).__name__}: {exc}).")

    if required:
        try:
            env_url, token = access.dataverse()
            names = sorted({ref.logical_name for ref in required.values()})
            filter_expr = " or ".join(
                "connectionreferencelogicalname eq '" + name.replace("'", "''") + "'"
                for name in names
            )
            rows = query_all(
                env_url, token, "connectionreferences",
                "connectionreferencelogicalname,connectorid,connectionid", filter_expr,
                strict_collection=True,
            )
            if not isinstance(rows, list):
                raise ValueError("Dataverse references returned an invalid collection.")
            by_name: dict[str, dict] = {}
            for row in rows:
                row = _mapping(row, "Dataverse reference")
                name = _identity(row.get("connectionreferencelogicalname"), "logical name")
                key = name.casefold()
                if key in by_name:
                    raise ValueError("Duplicate Dataverse connection-reference identity.")
                by_name[key] = row
            for (_, name), reference in required.items():
                row = by_name.get(name)
                if row is None:
                    audit.failures.append(
                        f"Agent {reference.agent_id}: required flow reference {reference.logical_name} is missing."
                    )
                    reference.failures.append("Required flow reference is missing.")
                    audit.references.append(reference)
                    continue
                connector = _identity(row.get("connectorid"), "connectorid")
                if _connector(connector) != _connector(reference.connector_id):
                    audit.failures.append(f"Reference {reference.logical_name}: the binding uses the wrong connector.")
                    reference.failures.append("The reference binding uses the wrong connector.")
                reference.connection_id = row.get("connectionid")
                audit.references.append(reference)
        except READ_ERRORS as exc:
            audit.record_read_error(exc, "flow-reference-bindings")
            audit.warnings.append(f"Flow reference bindings unverified ({type(exc).__name__}: {exc}).")

    for reference in audit.references:
        if reference.connection_id is None or reference.connection_id == "":
            audit.failures.append(f"Agent {reference.agent_id}: reference {reference.logical_name} is unbound.")
            reference.failures.append("The reference is unbound.")
        elif not isinstance(reference.connection_id, str) or not reference.connection_id.strip():
            audit.warnings.append(f"Reference {reference.logical_name}: malformed physical connection identity.")

    bound = [ref for ref in audit.references
             if isinstance(ref.connection_id, str) and ref.connection_id.strip()]
    if not bound:
        return audit
    inventory = getattr(runner, "connectivity", None)
    try:
        if inventory is None:
            raise ValueError("Native physical connection inventory is unavailable.")
        connections = inventory.list_connections(runner.env_id)
        _compare_connections(audit, bound, connections, access)
    except READ_ERRORS as exc:
        audit.record_read_error(exc, "physical-connections")
        audit.warnings.append(f"Physical connection existence unverified ({type(exc).__name__}: {exc}).")
    return audit


def _connection_index(connections):
    if not isinstance(connections, list):
        raise ValueError("Physical connection inventory returned an invalid collection.")
    by_id = {}
    for row in connections:
        row = _mapping(row, "Physical connection")
        name = _identity(row.get("name"), "physical connection name")
        properties = _mapping(row.get("properties"), "Physical connection properties")
        _identity(properties.get("apiId"), "physical connector ID")
        key = _connection(name)
        if key in by_id:
            raise ValueError("Duplicate physical connection identity.")
        by_id[key] = row
    return by_id


def _compare_connections(audit, references, connections, access):
    by_id = _connection_index(connections)
    invisible = [ref for ref in references if _connection(ref.connection_id) not in by_id]
    authoritative = False
    if invisible:
        try:
            admin_rows = access.admin().get_connections(
                access.runner.env_id, strict_collection=True,
            )
            admin_index = _connection_index(admin_rows)
            for name, row in admin_index.items():
                if name in by_id and (
                    _connector(row["properties"]["apiId"])
                    != _connector(by_id[name]["properties"]["apiId"])
                ):
                    raise ValueError("Connection inventories disagree on the physical connector.")
            by_id.update(admin_index)
            authoritative = True
        except READ_ERRORS as exc:
            audit.record_read_error(exc, "admin-physical-connections")
            audit.warnings.append(
                "Some bound connections are not maker-visible; their existence "
                f"could not be verified with admin access ({type(exc).__name__}: {exc})."
            )
    for ref in references:
        row = by_id.get(_connection(ref.connection_id))
        if row is None:
            if authoritative:
                audit.failures.append(f"Reference {ref.logical_name}: bound physical connection does not exist.")
                ref.failures.append("The bound physical connection does not exist.")
        elif _connector(row["properties"]["apiId"]) != _connector(ref.connector_id):
            audit.failures.append(f"Reference {ref.logical_name}: the physical connection uses the wrong connector.")
            ref.failures.append("The physical connection uses the wrong connector.")
    used = {_connection(ref.connection_id) for ref in references}
    connectors = {_connector(ref.connector_id) for ref in references}
    audit.additional_connections = sum(
        name not in used and _connector(row["properties"]["apiId"]) in connectors
        for name, row in by_id.items()
    )
