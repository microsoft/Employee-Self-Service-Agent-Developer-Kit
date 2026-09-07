# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Manually push a MinimalBot evaluation payload and start a TEST PPAPI run.

This is an opt-in, mutating POC. It creates a fresh copy of the supplied
evaluation set on every invocation so repeated runs do not overwrite existing
components or require their optimistic-concurrency versions.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid

import msal
import requests


DEFAULT_CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
PPAPI_SCOPE = "https://api.test.powerplatform.com/.default"
MCS_CONNECTOR = "shared_microsoftcopilotstudio"


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _authenticate(tenant_id: str, client_id: str) -> tuple[str, str]:
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )
    result = app.acquire_token_interactive(
        [PPAPI_SCOPE],
        prompt="select_account",
    )
    if "access_token" not in result:
        raise RuntimeError(
            f"Power Platform authentication failed ({result.get('error')})."
        )
    token = result["access_token"]
    claims = _claims(token)
    username = str(
        claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("unique_name")
        or ""
    )
    if not username:
        raise RuntimeError("The token did not identify the signed-in account.")
    return token, username


def _environment_host(environment_id: str) -> str:
    compact = environment_id.replace("-", "")
    return (
        f"https://{compact[:-1]}.{compact[-1:]}"
        ".environment.api.test.powerplatform.com"
    )


def _request_json(
    method: str,
    url: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> tuple[requests.Response, dict[str, Any]]:
    response = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        params=params,
        timeout=120,
    )
    try:
        content = response.json()
    except ValueError:
        content = {"raw": response.text[:2000]}
    return response, content


def _component_id(change: dict[str, Any]) -> str:
    return str((change.get("component") or {}).get("id") or "")


def _clone_payload(
    payload_path: Path,
    change_token: str,
) -> tuple[dict[str, Any], str]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    changes = payload.get("botComponentChanges")
    if not isinstance(changes, list) or not changes:
        raise RuntimeError("Payload has no botComponentChanges.")
    roots = [
        change for change in changes
        if (
            (change.get("component") or {}).get("definition") or {}
        ).get("$kind") == "EvaluationSet"
    ]
    if len(roots) != 1:
        raise RuntimeError("Payload must contain exactly one EvaluationSet.")

    payload["changeToken"] = change_token
    id_map = {
        _component_id(change): str(uuid.uuid4())
        for change in changes
    }
    if any(not old_id for old_id in id_map):
        raise RuntimeError("Every payload component must have an id.")
    for change in changes:
        component = change["component"]
        old_id = _component_id(change)
        new_id = id_map[old_id]
        change["$kind"] = "BotComponentInsert"
        component["id"] = new_id
        component["schemaName"] = (
            f"{component['schemaName'][:80]}_{new_id.replace('-', '')[:8]}"
        )
        parent_id = component.get("parentBotComponentId")
        if parent_id:
            component["parentBotComponentId"] = id_map[parent_id]

    root = roots[0]["component"]
    root["definition"]["displayName"] = (
        f"{root['definition']['displayName']} POC "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )
    return payload, str(root["id"])


def _connection_id(connection: dict[str, Any]) -> str:
    return str(
        connection.get("name")
        or connection.get("connectionId")
        or connection.get("id")
        or ""
    ).rstrip("/").rsplit("/", 1)[-1]


def _connected(
    host: str,
    token: str,
    environment_id: str,
    connector_id: str,
) -> list[dict[str, Any]]:
    response, body = _request_json(
        "GET",
        f"{host}/connectivity/apis/{connector_id}/connections",
        token,
        params={
            "api-version": "1",
            "$filter": f"environment eq '{environment_id}'",
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Connection discovery failed for {connector_id} "
            f"(HTTP {response.status_code})."
        )
    result = []
    for connection in body.get("value", []):
        properties = connection.get("properties") or {}
        statuses = properties.get("statuses") or connection.get("statuses") or []
        if statuses and not any(
            str(item.get("status", "")).casefold() == "connected"
            for item in statuses
            if isinstance(item, dict)
        ):
            continue
        if _connection_id(connection):
            result.append(connection)
    return result


def _select_one(
    connections: list[dict[str, Any]],
    connector_id: str,
) -> dict[str, Any]:
    if len(connections) != 1:
        raise RuntimeError(
            f"Expected exactly one connected {connector_id} profile for the "
            f"signed-in account; found {len(connections)}."
        )
    return connections[0]


def _tool_bindings(
    host: str,
    token: str,
    environment_id: str,
    bot_id: str,
    bot_schema_name: str,
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bindings = []
    for change in references:
        reference = change.get("connectionReference") or change
        connector_path = str(reference.get("connectorId") or "")
        connector_id = connector_path.rstrip("/").rsplit("/", 1)[-1]
        reference_name = str(
            reference.get("connectionReferenceLogicalName") or ""
        )
        if not connector_id or not reference_name:
            continue
        connection = _select_one(
            _connected(
                host,
                token,
                environment_id,
                connector_id,
            ),
            connector_id,
        )
        bindings.append({
            "connectorId": connector_id,
            "connectionId": _connection_id(connection),
            "connectionReferenceName": reference_name,
        })
    if not bindings:
        return []
    return [{
        "botId": bot_id,
        "botSchemaName": bot_schema_name,
        "connections": bindings,
    }]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    args = parser.parse_args()

    token, username = _authenticate(args.tenant_id, args.client_id)
    host = _environment_host(args.environment_id)
    components_url = (
        f"{host}/copilotstudio/minimalBots/api/{args.bot_id}/components"
        "?api-version=2022-03-01-preview"
    )
    response, before = _request_json(
        "POST",
        components_url,
        token,
        body={},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"MinimalBot read failed (HTTP {response.status_code})."
        )
    payload, test_set_id = _clone_payload(
        args.payload,
        str(before["changeToken"]),
    )
    response, _ = _request_json(
        "PUT",
        components_url,
        token,
        body=payload,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"MinimalBot push failed (HTTP {response.status_code})."
        )
    response, components = _request_json(
        "POST",
        components_url,
        token,
        body={},
    )
    expected = {
        _component_id(change)
        for change in payload["botComponentChanges"]
    }
    actual = {
        _component_id(change)
        for change in components.get("botComponentChanges", [])
    }
    missing = sorted(expected - actual)
    if response.status_code != 200 or missing:
        raise RuntimeError(f"MinimalBot verification failed: {missing}")

    mcs_profile = _select_one(
        _connected(
            host,
            token,
            args.environment_id,
            MCS_CONNECTOR,
        ),
        MCS_CONNECTOR,
    )
    bot = components.get("bot") or {}
    tools_connections = _tool_bindings(
        host,
        token,
        args.environment_id,
        args.bot_id,
        str(bot.get("schemaName") or ""),
        components.get("connectionReferenceChanges") or [],
    )
    body = {
        "evaluationRunName": (
            f"MinimalBot POC {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        ),
        "runOnPublishedBot": False,
        "mcsConnectionId": _connection_id(mcs_profile),
        "toolsConnections": tools_connections,
    }
    run_url = (
        "https://api.test.powerplatform.com/copilotstudio/environments/"
        f"{args.environment_id}/bots/{args.bot_id}/api/makerevaluation/"
        f"testsets/{test_set_id}/run?api-version=2024-10-01"
    )
    response, result = _request_json(
        "POST",
        run_url,
        token,
        body=body,
    )
    output = {
        "signedInAccount": username,
        "testSetId": test_set_id,
        "verifiedComponents": len(expected),
        "status": response.status_code,
        "serviceRequestId": (
            response.headers.get("x-ms-service-request-id")
            or response.headers.get("x-ms-request-id")
        ),
        "correlationId": response.headers.get("x-ms-correlation-id"),
        "response": result,
    }
    print(json.dumps(output, indent=2))
    return 0 if response.status_code == 202 else 1


if __name__ == "__main__":
    raise SystemExit(main())
