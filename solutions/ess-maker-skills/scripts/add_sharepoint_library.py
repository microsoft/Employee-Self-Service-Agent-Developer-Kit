# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Add one SharePoint library to the setup-selected native agent, without publishing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
import uuid

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    authenticate,
    environment_id_from_host,
)
from auth import load_config
from minimalbot_evaluation import is_minimalbot


def library_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = unquote(parsed.path, errors="strict").rstrip("/")
    segments = path.lstrip("/").split("/")
    if (
        parsed.scheme != "https"
        or not (parsed.hostname or "").endswith(".sharepoint.com")
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in path
        or any(not part or part in (".", "..") for part in segments)
        or not (
            len(segments) == 1
            or (len(segments) == 3 and segments[0].casefold() in ("sites", "teams"))
        )
        or segments[-1]
        .casefold()
        .endswith(
            (
                ".aspx",
                ".html",
                ".htm",
                ".pdf",
                ".docx",
                ".xlsx",
                ".pptx",
                ".doc",
                ".xls",
                ".ppt",
                ".txt",
                ".csv",
            )
        )
        or any(":" in part for part in segments)
        or path.casefold() in ("/sites", "/teams")
    ):
        raise ValueError(
            "Use a direct HTTPS SharePoint library-root URL, such as "
            "https://contoso.sharepoint.com/sites/HR/SitePages/ or "
            ".../Shared%20Documents/. Sharing links, query strings, site roots, "
            "pages, subwebs and subfolders are not supported by this workaround."
        )
    return urlunsplit(("https", parsed.hostname, quote(path, safe="/") + "/", "", ""))


def _url_key(value: str) -> tuple[str, str, str]:
    parsed = urlsplit(value)
    return (
        parsed.scheme.casefold(),
        (parsed.hostname or "").casefold(),
        unquote(parsed.path).rstrip("/").casefold(),
    )


def setup_context(config: dict[str, Any], state: dict[str, Any]) -> dict[str, str]:
    if not isinstance(state, dict) or not is_minimalbot(config) or state.get("schema_version") != 4:
        raise AgentBuilderError("Run /setup for the existing native DA GA agent first.")
    active = config.get("activeAgent")
    entries = state.get("agents")
    matches = (
        [
            entry
            for entry in entries.values()
            if isinstance(entry, dict)
            and isinstance(entry.get("agent"), dict)
            and entry["agent"].get("workspace_slug") == active
        ]
        if isinstance(entries, dict) and active
        else []
    )
    if len(matches) != 1:
        raise AgentBuilderError("Setup must identify exactly one active agent.")
    entry = matches[0]
    agent = entry["agent"]
    local_agent = config.get("agent") or {}
    environment = state.get("environment") or {}
    steps = entry.get("steps") or {}
    if not all(
        isinstance(value, dict)
        for value in (
            local_agent,
            environment,
            steps,
            entry.get("workspace"),
        )
    ) or not isinstance(steps.get("SETUP-07"), dict):
        raise AgentBuilderError("Setup state is malformed. Run /setup again.")
    if (
        (steps.get("SETUP-07") or {}).get("state") != "done"
        or not (entry.get("workspace") or {}).get("folder")
        or not (entry.get("workspace") or {}).get("agent_path")
        or agent.get("id") != local_agent.get("botId")
        or local_agent.get("slug") != active
        or agent.get("schema_name") != local_agent.get("schemaName")
        or environment.get("id")
        != (local_agent.get("environmentId") or config.get("environmentId"))
    ):
        raise AgentBuilderError(
            "The active agent and materialized setup workspace do not match. "
            "Run /setup again; no remote changes were made."
        )
    values = {
        "agent_id": agent.get("id"),
        "schema": local_agent.get("schemaName"),
        "environment_id": environment.get("id"),
        "tenant_id": environment.get("tenant_id"),
        "host": environment.get("power_platform_api_endpoint"),
        "ring": environment.get("ring"),
    }
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        raise AgentBuilderError("Setup is missing native agent identity. Run /setup again.")
    for key in ("agent_id", "environment_id", "tenant_id"):
        uuid.UUID(values[key])
    if environment_id_from_host(values["host"], values["ring"]) != str(
        uuid.UUID(values["environment_id"])
    ):
        raise AgentBuilderError("Setup environment ID and API host do not match.")
    return values


def components(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changes = snapshot.get("botComponentChanges")
    if not isinstance(changes, list):
        raise AgentBuilderError("Component fetch did not return a component list.")
    result: dict[str, dict[str, Any]] = {}
    for change in changes:
        component = change.get("component") if isinstance(change, dict) else None
        component_id = component.get("id") if isinstance(component, dict) else None
        if not isinstance(component_id, str) or not component_id or component_id in result:
            raise AgentBuilderError("Component fetch returned missing or duplicate identity.")
        result[component_id] = component
    return result


def _bot_identity(snapshot: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    bot = snapshot.get("bot")
    if (
        not isinstance(bot, dict)
        or bot.get("schemaName") != context["schema"]
        or (bot.get("cdsBotId") or bot.get("componentIdUnique")) != context["agent_id"]
    ):
        raise AgentBuilderError(
            "Live agent identity does not match setup. No further changes made."
        )
    return bot


def apply_library(
    client: AgentBuilderClient,
    context: dict[str, str],
    url: str,
    *,
    apply: bool = False,
    auto_yes: bool = False,
    backup_root: Path = Path(".local/backups/sharepoint-library"),
) -> dict[str, Any]:
    url = library_url(url)
    agent_id = context["agent_id"]
    before = client.fetch_components(agent_id)
    bot = _bot_identity(before, context)
    existing = components(before)
    matches = []
    for component in existing.values():
        if component.get("$kind") != "KnowledgeSourceComponent":
            continue
        configuration = component.get("configuration")
        source = configuration.get("source") if isinstance(configuration, dict) else None
        if not isinstance(source, dict):
            raise AgentBuilderError(
                "Existing knowledge source has malformed configuration. Review it before adding sources."
            )
        if source.get("$kind") != "SharePointSearchSource":
            continue
        site = source.get("site")
        if not isinstance(site, dict):
            raise AgentBuilderError("Existing SharePoint source has malformed URL configuration.")
        configured_url = site.get("literalValue")
        if isinstance(configured_url, str) and _url_key(configured_url) == _url_key(url):
            matches.append(component)
    if len(matches) > 1:
        raise AgentBuilderError(
            "This library has duplicate sources. Review them in Copilot Studio."
        )
    if matches:
        match = matches[0]
        if match.get("state") == "Inactive" or match.get("status") == "Inactive":
            raise AgentBuilderError(
                "This library is already present but inactive; review it in Copilot Studio."
            )
        print(f"Already configured: {url} [{match['id']}]. No changes made; not published.")
        return {"status": "already-configured", "componentId": match["id"], "url": url}
    change_token = before.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise AgentBuilderError("Component fetch omitted the change token. No changes made.")
    print(f"Agent: {bot.get('displayName') or agent_id} [{agent_id}]")
    print(f"Environment: {context['environment_id']}; ring: {context['ring']}")
    print(f"Add library: {url}\nExisting components: {len(existing)}. Publishing is not included.")
    if not apply:
        print("Preview only. Nothing was changed. Confirm this target before applying.")
        return {"status": "preview", "url": url}
    if (
        not auto_yes
        and input("Add this library without publishing? (yes/no): ").strip().lower() != "yes"
    ):
        print("Cancelled. No changes made.")
        return {"status": "cancelled", "url": url}

    component_id = str(uuid.uuid4())
    component = {
        "$kind": "KnowledgeSourceComponent",
        "version": 1,
        "id": component_id,
        "displayName": "SharePoint library - "
        + unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]),
        "description": f"This knowledge source provides information found in {url} SharePoint",
        "schemaName": f"{context['schema']}.knowledge.Library_{component_id.replace('-', '')}",
        "configuration": {
            "$kind": "KnowledgeSourceConfiguration",
            "source": {
                "$kind": "SharePointSearchSource",
                "cascadeShare": False,
                "site": {"$kind": "StringExpression", "literalValue": url},
            },
        },
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{agent_id}-{component_id}.json"
    with backup.open("x", encoding="utf-8") as handle:
        json.dump(before, handle, indent=2)
    print(f"Local backup: {backup}")
    try:
        client.insert_component(agent_id, change_token, component)
        after = client.fetch_components(agent_id)
        _bot_identity(after, context)
        actual = components(after)
    except (AgentBuilderError, requests.RequestException) as exc:
        raise AgentBuilderError(
            f"Write/readback did not complete: {exc}. The write may have committed. "
            f"Run the read-only preview before retrying; do not replay the backup. Source ID: {component_id}."
        ) from exc
    added = actual.get(component_id) or {}
    if (
        added.get("$kind") != component["$kind"]
        or added.get("schemaName") != component["schemaName"]
        or added.get("configuration") != component["configuration"]
        or set(actual) != set(existing) | {component_id}
        or any(actual.get(key) != value for key, value in existing.items())
    ):
        raise AgentBuilderError(
            "The write returned but library/preservation verification failed. "
            f"Inspect Copilot Studio and the local backup before retrying. Source ID: {component_id}."
        )
    print(f"Verified: {url} [{component_id}]. Existing components unchanged. Agent not published.")
    return {"status": "added", "componentId": component_id, "url": url, "backup": str(backup)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-url", required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Add the library; otherwise preview only."
    )
    parser.add_argument("--yes", action="store_true", help="Use only after maker confirmation.")
    parser.add_argument("--account", help="Prefer this cached maker sign-in.")
    parser.add_argument("--expected-agent-id", help="Agent ID confirmed in the preview.")
    parser.add_argument(
        "--expected-environment-id", help="Environment ID confirmed in the preview."
    )
    args = parser.parse_args(argv)
    try:
        url = library_url(args.library_url)
        config = load_config()
        state = json.loads(Path(".local/setup/config.json").read_text(encoding="utf-8-sig"))
        context = setup_context(config, state)
        if args.apply and (
            args.expected_agent_id != context["agent_id"]
            or args.expected_environment_id != context["environment_id"]
        ):
            raise AgentBuilderError(
                "Apply requires --expected-agent-id and --expected-environment-id "
                "matching the preview. Run the preview again if the target changed."
            )
        token = authenticate(context["tenant_id"], context["ring"], account_hint=args.account)
        client = AgentBuilderClient(
            context["host"], token, ring=context["ring"], tenant_id=context["tenant_id"]
        )
        apply_library(client, context, url, apply=args.apply, auto_yes=args.yes)
    except (AgentBuilderError, requests.RequestException, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
