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
import re
from typing import Any
import uuid

import msal
import requests
import yaml


DEFAULT_CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
PPAPI_SCOPE = "https://api.test.powerplatform.com/.default"
MCS_CONNECTOR = "shared_microsoftcopilotstudio"
DEFAULT_CONFIG_PATHS = (
    Path(".local/config.json"),
    Path("solutions/ess-maker-skills/.local/config.json"),
)


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
) -> tuple[requests.Response, Any]:
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


def _wire_kinds(value: Any) -> Any:
    """Convert workspace ``kind`` discriminators to JSON ``$kind``."""
    if isinstance(value, dict):
        return {
            "$kind" if key == "kind" else key: _wire_kinds(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_wire_kinds(child) for child in value]
    return value


def _unwire_kinds(value: Any) -> Any:
    """Convert MinimalBot JSON ``$kind`` discriminators to workspace YAML."""
    if isinstance(value, dict):
        return {
            "kind" if key == "$kind" else key: _unwire_kinds(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_unwire_kinds(child) for child in value]
    return value


def _safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return name or fallback


def _component_name(component: dict[str, Any]) -> str:
    definition = component.get("definition") or {}
    return str(
        definition.get("displayName")
        or component.get("displayName")
        or component.get("schemaName")
        or component.get("id")
        or "evaluation"
    )


def _write_workspace_evaluations(
    response: dict[str, Any],
    output_dir: Path,
) -> dict[str, int]:
    """Write MinimalBot evaluation components as workspace ``.mcs.yml``."""
    changes = response.get("botComponentChanges")
    if not isinstance(changes, list):
        raise RuntimeError(
            "MinimalBot response did not contain botComponentChanges."
        )

    evaluations = []
    for change in changes:
        component = change.get("component") if isinstance(change, dict) else None
        definition = (
            component.get("definition")
            if isinstance(component, dict)
            else None
        )
        if not isinstance(definition, dict):
            continue
        if definition.get("$kind") not in {"EvaluationSet", "EvaluationData"}:
            continue
        evaluations.append(component)

    parents = {
        str(component.get("id")): component
        for component in evaluations
        if (
            (component.get("definition") or {}).get("$kind") == "EvaluationSet"
            and component.get("id")
        )
    }
    cases = [
        component
        for component in evaluations
        if (component.get("definition") or {}).get("$kind") == "EvaluationData"
    ]
    if not parents:
        raise RuntimeError(
            "MinimalBot response did not expose any EvaluationSet components."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    component_map: dict[str, dict[str, Any]] = {}
    used_paths: set[str] = set()

    def write_component(
        component: dict[str, Any],
        folder_name: str,
    ) -> None:
        component_id = str(component.get("id") or "")
        name = _component_name(component)
        stem = _safe_name(name, "evaluation")
        relative_path = f"evaluations/{folder_name}/{stem}.mcs.yml"
        if relative_path in used_paths:
            relative_path = (
                f"evaluations/{folder_name}/{stem}-"
                f"{component_id.replace('-', '')[:8]}.mcs.yml"
            )
        used_paths.add(relative_path)
        path = output_dir.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        definition = _unwire_kinds(component["definition"])
        path.write_text(
            yaml.safe_dump(
                definition,
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        entry = {
            "botcomponentid": component_id,
            "schemaname": str(component.get("schemaName") or ""),
            "componenttype": 19,
            "name": name,
            "description": str(component.get("description") or ""),
        }
        parent_id = str(component.get("parentBotComponentId") or "")
        if parent_id:
            entry["parentbotcomponentid"] = parent_id
        component_map[relative_path] = entry

    parent_folders = {}
    for parent_id, component in parents.items():
        folder_name = _safe_name(_component_name(component), "evaluation-set")
        if folder_name in parent_folders.values():
            folder_name = f"{folder_name}-{parent_id.replace('-', '')[:8]}"
        parent_folders[parent_id] = folder_name
        write_component(component, folder_name)

    orphan_ids = []
    for component in cases:
        parent_id = str(component.get("parentBotComponentId") or "")
        folder_name = parent_folders.get(parent_id)
        if not folder_name:
            orphan_ids.append(str(component.get("id") or "unknown"))
            continue
        write_component(component, folder_name)
    if orphan_ids:
        raise RuntimeError(
            "EvaluationData components referenced unavailable parents: "
            + ", ".join(orphan_ids)
        )

    map_path = output_dir / ".component-map.json"
    existing_map = {}
    if map_path.is_file():
        try:
            existing_map = json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing_map = {}
    if not isinstance(existing_map, dict):
        existing_map = {}
    existing_map.update(component_map)
    map_path.write_text(
        json.dumps(existing_map, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"sets": len(parents), "cases": len(cases)}


def _load_config(config_path: Path | None) -> dict[str, Any]:
    candidates = (config_path,) if config_path else DEFAULT_CONFIG_PATHS
    for candidate in candidates:
        if candidate and candidate.is_file():
            try:
                config = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    f"Unable to read config {candidate}: {exc}"
                ) from exc
            if not isinstance(config, dict):
                raise RuntimeError(f"Config must contain an object: {candidate}")
            return config
    if config_path:
        raise RuntimeError(f"Config file does not exist: {config_path}")
    return {}


def _resolve_target(
    environment_id: str | None,
    bot_id: str | None,
    config_path: Path | None,
) -> tuple[str, str]:
    config = (
        _load_config(config_path)
        if config_path or not (environment_id and bot_id)
        else {}
    )
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    resolved_environment = str(
        environment_id
        or agent.get("environmentId")
        or config.get("environmentId")
        or ""
    )
    resolved_bot = str(bot_id or agent.get("botId") or "")
    if not resolved_environment:
        raise RuntimeError(
            "Environment ID is required. Pass --environment-id or configure "
            "environmentId in .local/config.json."
        )
    if not resolved_bot:
        raise RuntimeError(
            "Bot ID is required. Pass --bot-id or configure agent.botId in "
            ".local/config.json."
        )
    return resolved_environment, resolved_bot


def _schema_name(stem: str, component_id: str) -> str:
    safe_stem = re.sub(r"[^a-z0-9]+", "_", stem.casefold()).strip("_")
    safe_stem = safe_stem or "evaluation"
    suffix = component_id.replace("-", "")[:8]
    return f"mspva_{safe_stem[:70]}_{suffix}"


def _workspace_payload(
    evaluation_folder: Path,
    change_token: str,
) -> tuple[dict[str, Any], str]:
    """Convert one workspace evaluation folder to a MinimalBot change set."""
    if not evaluation_folder.is_dir():
        raise RuntimeError(
            f"Evaluation folder does not exist: {evaluation_folder}"
        )
    documents = []
    for path in sorted(evaluation_folder.glob("*.mcs.yml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise RuntimeError(f"Unable to read evaluation YAML {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise RuntimeError(f"Evaluation YAML must contain an object: {path}")
        documents.append((path, document))

    parents = [
        item for item in documents
        if item[1].get("kind") == "EvaluationSet"
    ]
    cases = [
        item for item in documents
        if item[1].get("kind") == "EvaluationData"
    ]
    if len(parents) != 1:
        raise RuntimeError(
            "Evaluation folder must contain exactly one EvaluationSet."
        )
    if not cases:
        raise RuntimeError(
            "Evaluation folder must contain at least one EvaluationData file."
        )
    if len(cases) > 100:
        raise RuntimeError("Copilot Studio evaluation sets support at most 100 cases.")

    parent_path, parent_document = parents[0]
    parent_id = str(uuid.uuid4())
    parent_definition = _wire_kinds(parent_document)
    parent_definition["displayName"] = (
        f"{parent_definition.get('displayName') or parent_path.stem} POC "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    )
    changes = [{
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": "TestCaseComponent",
            "id": parent_id,
            "schemaName": _schema_name(parent_path.stem, parent_id),
            "definition": parent_definition,
            "extensionData": {"UseProvidedBotComponentId": True},
        },
    }]

    for case_path, case_document in cases:
        case_id = str(uuid.uuid4())
        case_definition = _wire_kinds(case_document)
        rows = case_definition.get("rows")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError(
                f"EvaluationData must contain at least one row: {case_path}"
            )
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"EvaluationData rows must be objects: {case_path}"
                )
            row.setdefault("$kind", "SimpleEvaluationCase")
        changes.append({
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "TestCaseComponent",
                "id": case_id,
                "parentBotComponentId": parent_id,
                "schemaName": _schema_name(case_path.stem, case_id),
                "definition": case_definition,
                "extensionData": {"UseProvidedBotComponentId": True},
            },
        })

    return {
        "changeToken": change_token,
        "botComponentChanges": changes,
        "connectionReferenceChanges": [],
        "connectorDefinitionChanges": [],
    }, parent_id


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
    parser.add_argument("--environment-id")
    parser.add_argument("--bot-id")
    parser.add_argument(
        "--config",
        type=Path,
        help=(
            "Config containing environmentId and agent.botId. Defaults to "
            ".local/config.json."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--evaluation-folder",
        type=Path,
        help="Folder containing one EvaluationSet and its EvaluationData YAML files.",
    )
    source.add_argument(
        "--payload",
        type=Path,
        help="Prebuilt MinimalBot JSON payload template.",
    )
    source.add_argument(
        "--pull-output-folder",
        type=Path,
        help="Pull MinimalBot evaluations into this workspace folder.",
    )
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    args = parser.parse_args()

    environment_id, bot_id = _resolve_target(
        args.environment_id,
        args.bot_id,
        args.config,
    )
    token, username = _authenticate(args.tenant_id, args.client_id)
    host = _environment_host(environment_id)
    components_url = (
        f"{host}/copilotstudio/minimalBots/api/{bot_id}/components"
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
    if args.pull_output_folder:
        counts = _write_workspace_evaluations(
            before,
            args.pull_output_folder,
        )
        print(json.dumps({
            "signedInAccount": username,
            "environmentId": environment_id,
            "botId": bot_id,
            "outputFolder": str(args.pull_output_folder),
            "evaluationSets": counts["sets"],
            "evaluationCases": counts["cases"],
        }, indent=2))
        return 0
    if args.evaluation_folder:
        payload, test_set_id = _workspace_payload(
            args.evaluation_folder,
            str(before["changeToken"]),
        )
    else:
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
            environment_id,
            MCS_CONNECTOR,
        ),
        MCS_CONNECTOR,
    )
    bot = components.get("bot") or {}
    tools_connections = _tool_bindings(
        host,
        token,
        environment_id,
        bot_id,
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
        f"{environment_id}/bots/{bot_id}/api/makerevaluation/"
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
