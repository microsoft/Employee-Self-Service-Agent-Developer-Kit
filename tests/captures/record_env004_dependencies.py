# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Record read-only ENV-004 dependency contracts, without setup configuration.

Required environment variables: ENV004_ENVIRONMENT_ID, ENV004_AGENT_ID,
ENV004_ACCOUNT, ENV004_TOKEN_CACHE. Optional: ENV004_OUTPUT.
Flow administration is currently verified only on the prod service ring.
Topic text, variables, connector definitions, connection parameters, account
data, and authentication headers are excluded before any file is written.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "solutions" / "ess-maker-skills" / "scripts"))

from agentbuilder import (  # noqa: E402
    AgentBuilderClient, ConnectivityClient, authenticate_flightcheck,
    authenticate_flightcheck_dependency, derive_environment_host,
)
from flightcheck.checks._connection_dependencies import _dependencies  # noqa: E402
from flightcheck.pp_admin_client import PPAdminClient, PP_SCOPE, FLOW_SCOPE  # noqa: E402
import flightcheck.pp_admin_client as pp_module  # noqa: E402
from _redact import redact_cassette  # noqa: E402


def _topic_actions(value):
    if isinstance(value, dict):
        if value.get("$kind") in {"InvokeFlowAction", "InvokeConnectorAction"}:
            return {key: item for key, item in value.items()
                    if key in {"$kind", "flowId", "connectionReference"}}
        result = {}
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                child = _topic_actions(item)
                if child:
                    result[key] = child
        if result and "$kind" in value:
            result["$kind"] = value["$kind"]
        return result
    if isinstance(value, list):
        return [child for item in value if (child := _topic_actions(item))]
    return None


def _projection(url, body):
    if "/components" in url:
        changes = []
        for change in body["botComponentChanges"]:
            component = change["component"]
            if component.get("$kind") != "DialogComponent":
                continue
            projected = {
                "$kind": component["$kind"], "status": component["status"],
                "dialog": _topic_actions(component["dialog"]),
            }
            changes.append({"$kind": change["$kind"], "component": projected})
        refs = []
        for change in body.get("connectionReferenceChanges", []):
            refs.append({
                "$kind": change["$kind"],
                "connectionReference": {
                    key: value for key, value in change["connectionReference"].items()
                    if key in {"id", "$kind", "connectionReferenceLogicalName",
                               "connectorId", "connectionId"}
                },
            })
        return {"botComponentChanges": changes, "connectionReferenceChanges": refs}
    if "/minimalBots/api/" in url:
        return {key: body[key] for key in ("botId", "realm")}
    if "/flows/" in url:
        refs = body["properties"]["connectionReferences"]
        return {"properties": {"connectionReferences": {
            name: {
                "connectionReferenceLogicalName": ref["connectionReferenceLogicalName"],
                "connectionName": ref.get("connectionName"),
                "source": ref.get("source"),
                "apiDefinition": {"id": ref["apiDefinition"]["id"]},
            } for name, ref in refs.items()
        }}}
    if "/connectionreferences" in url:
        return {"value": [
            {key: row.get(key) for key in (
                "connectionreferencelogicalname", "connectorid", "connectionid"
            )} for row in body["value"]
        ]}
    if "/connections" in url:
        rows = body["value"]
        return {"value": [{
            "id": row["id"], "name": row["name"],
            "properties": {"apiId": row["properties"]["apiId"],
                           "statuses": row["properties"].get("statuses")},
        } for row in rows]}
    return {
        "name": body["name"],
        "properties": {"linkedEnvironmentMetadata": {
            "instanceUrl": body["properties"]["linkedEnvironmentMetadata"]["instanceUrl"]
        }},
    }


def main():
    environment_id = os.environ["ENV004_ENVIRONMENT_ID"]
    agent_id = os.environ["ENV004_AGENT_ID"]
    cache_path = Path(os.environ["ENV004_TOKEN_CACHE"])
    account = os.environ["ENV004_ACCOUNT"]
    output = Path(os.environ.get(
        "ENV004_OUTPUT",
        str(ROOT / "tests" / "fixtures" / "cassettes" / "env004_dependencies.yaml"),
    ))
    token, tenant, authenticated = authenticate_flightcheck(
        "prod", cache_path=cache_path, account_hint=account,
        emit_account_identity=False, return_account_identity=True,
    )
    if not authenticated or authenticated.casefold() != account.casefold():
        raise ValueError("The recorder did not authenticate the selected account.")

    def dependency_token(scope):
        return authenticate_flightcheck_dependency(
            scope, tenant_id=tenant, ring="prod",
            account_hint=account, cache_path=cache_path,
        )

    interactions = []

    def record(response, **_kwargs):
        response.raise_for_status()
        interactions.append({
            "request": {
                "method": response.request.method, "uri": response.request.url,
                "body": "{}" if response.request.method == "POST" else None,
                "headers": {},
            },
            "response": {
                "status": {"code": response.status_code, "message": response.reason},
                "headers": {"Content-Type": ["application/json"]},
                "body": {"string": json.dumps(_projection(response.request.url, response.json()))},
            },
        })

    client = AgentBuilderClient(
        derive_environment_host(environment_id, "prod"), token,
        ring="prod", tenant_id=tenant,
    )
    connectivity = ConnectivityClient(token, ring="prod")
    pp = PPAdminClient(tenant)
    pp.set_read_tokens(
        powerapps_token=dependency_token(PP_SCOPE),
        flow_token=dependency_token(FLOW_SCOPE),
    )
    client.session.hooks["response"].append(record)
    connectivity.session.hooks["response"].append(record)
    pp_module._SESSION.hooks["response"].append(record)
    agent = client.get_agent(agent_id)
    if agent["botId"].casefold() != agent_id.casefold():
        raise ValueError("The recorder received a different agent.")
    components = client.fetch_components(agent_id)
    _, flow_ids = _dependencies(components)
    for flow_id in sorted(flow_ids):
        pp.get_flow(environment_id, flow_id)
    environment = pp.get_environment(environment_id)
    url = environment["properties"]["linkedEnvironmentMetadata"]["instanceUrl"].rstrip("/")
    session = requests.Session()
    session.hooks["response"].append(record)
    response = session.get(
        url + "/api/data/v9.2/connectionreferences",
        params={"$select": "connectionreferencelogicalname,connectorid,connectionid"},
        headers={"Authorization": "Bearer " + dependency_token(url + "/user_impersonation")},
        timeout=60,
    )
    response.raise_for_status()
    connectivity.list_connections(environment_id)
    pp.get_connections(environment_id)

    # Shield graph identifiers before canonical redaction, then substitute
    # distinct fake identities. Otherwise the canonical all-GUIDs-to-one rule
    # destroys the dependency joins this capture is intended to demonstrate.
    text = yaml.safe_dump({"version": 1, "interactions": interactions})
    identifiers = sorted(set(re.findall(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|\b[0-9a-fA-F]{32}\b",
        text,
    )))
    for index, value in enumerate(identifiers, 1):
        text = text.replace(value, f"ENV004_ID_{index}_ALIAS")
    with TemporaryDirectory(prefix="env004-capture-") as temporary:
        source = Path(temporary) / "projected.yaml"
        redacted = Path(temporary) / "redacted.yaml"
        source.write_text(text, encoding="utf-8")
        redact_cassette(source, redacted)
        text = redacted.read_text(encoding="utf-8")
    for index, value in enumerate(identifiers, 1):
        fake = f"{index:032d}" if len(value) == 32 else f"00000000-0000-0000-0000-{index:012d}"
        text = text.replace(f"ENV004_ID_{index}_ALIAS", fake)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Captured {len(interactions)} projected read-only responses: {output}")


if __name__ == "__main__":
    main()
