#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Register an existing Dataverse-free (TEST-ring) agent into ``.local/config.json``.

This is the no-Dataverse counterpart to the ``/setup`` wizard's
environment-lock + config-write steps. The wizard is built entirely around a
Dataverse environment *URL* (role checks, ``discover.py --resolve-environment-url``,
Dataverse MCP, connection binding), so an environment with no linked Dataverse
database — a Cosmos-backed "MinimalBot" environment on the Power Platform TEST
ring — can never clear its scope step.

Given a Power Platform ``environmentId`` and the ``botId`` of an agent that
already exists in that environment, this script:

  1. (optionally) verifies the bot is reachable on the TEST ring by reading its
     components through the same transport the evaluation path uses, and
  2. writes a MinimalBot-shaped ``.local/config.json`` so downstream skills
     (evaluation, scan, ...) recognise the environment via ``is_minimalbot()``
     and operate on the registered agent.

It does NOT install marketplace packages and does NOT materialise an agent
workspace folder — it only writes the config the rest of the kit reads. Use
``install_ess_agent.py --environment-id`` if you need to install a starter
agent first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from minimalbot_evaluation import (
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
    is_minimalbot,
)

# Kept in lockstep with auth.EXPECTED_CONFIG_VERSION / setup.py so the file this
# script writes passes auth.load_config()'s schema gate.
CONFIG_VERSION = 1
DEFAULT_CONFIG_PATH = Path(".local/config.json")


def _slugify(value: str) -> str:
    """Lower-case, hyphenate, and strip a display name into a config slug."""
    chars: list[str] = []
    for char in value.strip().lower():
        if char.isalnum():
            chars.append(char)
        elif char in " -_":
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _extract_bot_identity(components: dict[str, Any]) -> tuple[str, str]:
    """Best-effort ``(displayName, schemaName)`` for the bot's own component.

    The component read returns every component on the agent under
    ``botComponentChanges``. The bot itself is the component whose definition
    ``$kind`` names a bot/copilot. When it can't be identified we return empty
    strings and the caller falls back to flags or a generated name.
    """
    for change in components.get("botComponentChanges", []) or []:
        component = change.get("component") if isinstance(change, dict) else None
        if not isinstance(component, dict):
            continue
        definition = component.get("definition") or {}
        kind = str(definition.get("$kind") or "")
        if "Bot" in kind or "Copilot" in kind:
            name = str(
                definition.get("displayName")
                or component.get("displayName")
                or ""
            ).strip()
            schema = str(component.get("schemaName") or "").strip()
            if name or schema:
                return name, schema
    return "", ""


def verify_bot(
    environment_id: str,
    bot_id: str,
    tenant_id: str,
    *,
    client_factory=MinimalBotEvaluationClient,
) -> dict[str, Any]:
    """Authenticate and read the bot's components to prove it is reachable.

    Returns a small summary dict (signed-in user, detected name/schema,
    component count). Raises :class:`MinimalBotEvaluationError` if the TEST-ring
    transport rejects the request or the bot can't be read.
    """
    client = client_factory(
        environment_id=environment_id,
        bot_id=bot_id,
        tenant_id=tenant_id or "organizations",
    )
    client.authenticate()
    components = client.read_components()
    name, schema = _extract_bot_identity(components)
    return {
        "username": getattr(client, "signed_in_username", None),
        "name": name,
        "schemaName": schema,
        "componentCount": len(components.get("botComponentChanges", []) or []),
    }


def _build_config(
    existing: dict[str, Any],
    *,
    environment_id: str,
    bot_id: str,
    tenant_id: str,
    name: str,
    schema_name: str,
    slug: str,
    managed: bool,
    folder: str,
) -> dict[str, Any]:
    """Merge a MinimalBot agent entry into any existing config payload."""
    agent_entry = {
        "name": name,
        "botId": bot_id,
        "schemaName": schema_name,
        "isManaged": managed,
        "slug": slug,
        "folder": folder,
        "environmentId": environment_id,
    }
    config = dict(existing) if isinstance(existing, dict) else {}
    # A Dataverse-free agent must NOT carry a dataverseEndpoint, or
    # is_minimalbot() would classify it as a Dataverse agent.
    config.pop("dataverseEndpoint", None)
    config.update(
        {
            "configVersion": CONFIG_VERSION,
            "setup": "complete",
            "agent": agent_entry,
            "activeAgent": slug,
            "agents": [agent_entry],
            "environmentId": environment_id,
            "tenantId": tenant_id or "organizations",
        }
    )
    return config


def _write_config(config: dict[str, Any], path: Path) -> None:
    """Atomically write the config JSON (tmp + fsync + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp_path, path)


def register_existing_agent(
    environment_id: str,
    bot_id: str,
    *,
    tenant_id: str | None = None,
    name: str | None = None,
    schema_name: str | None = None,
    slug: str | None = None,
    managed: bool = True,
    verify: bool = True,
    ensure_folder: bool = True,
    config_path: Path = DEFAULT_CONFIG_PATH,
    client_factory=MinimalBotEvaluationClient,
) -> dict[str, Any]:
    """Point ``.local/config.json`` at an existing Dataverse-free agent.

    When ``verify`` is true the bot is read over the TEST ring first (and its
    display name / schema are auto-filled when not supplied). The resulting
    config is validated with :func:`is_minimalbot` before it is written.

    When ``ensure_folder`` is true the agent's workspace folder (and an empty
    ``evaluations/`` subfolder) is created so the evaluation cycle
    (create -> push -> run) has the on-disk folder that ``_minimalbot_push``
    and the create skill require. Topic files are NOT downloaded.
    """
    if not environment_id:
        raise ValueError("environment_id is required.")
    if not bot_id:
        raise ValueError("bot_id is required.")

    tenant_id = (tenant_id or "organizations").strip() or "organizations"

    verified: dict[str, Any] | None = None
    if verify:
        verified = verify_bot(
            environment_id, bot_id, tenant_id, client_factory=client_factory
        )
        name = name or verified.get("name") or ""
        schema_name = schema_name or verified.get("schemaName") or ""

    name = (name or f"MinimalBot {bot_id[:8]}").strip()
    slug = (slug or _slugify(name) or f"minimalbot-{bot_id[:8]}").strip()
    schema_name = (schema_name or slug).strip()
    folder = f"workspace/agents/{slug}"

    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            existing = {}

    config = _build_config(
        existing,
        environment_id=environment_id,
        bot_id=bot_id,
        tenant_id=tenant_id,
        name=name,
        schema_name=schema_name,
        slug=slug,
        managed=managed,
        folder=folder,
    )

    if not is_minimalbot(config):
        raise RuntimeError(
            "Constructed config is not recognised as a MinimalBot "
            "(missing environmentId or an unexpected dataverseEndpoint); "
            "refusing to write it."
        )

    _write_config(config, config_path)

    folder_path: Path | None = None
    if ensure_folder:
        # agent.folder is stored relative to the kit root (the directory that
        # holds .local), so resolve it against that same base and create the
        # empty evaluations/ subfolder the eval cycle expects.
        kit_root = config_path.resolve().parent.parent
        folder_path = kit_root / folder
        (folder_path / "evaluations").mkdir(parents=True, exist_ok=True)

    return {
        "config": config,
        "verified": verified,
        "configPath": str(config_path),
        "agentFolder": str(folder_path) if folder_path is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register an existing Dataverse-free (TEST-ring) agent into "
            ".local/config.json (no-DV counterpart to /setup)."
        )
    )
    parser.add_argument(
        "--environment-id",
        required=True,
        help="Power Platform environment ID (GUID) that hosts the agent.",
    )
    parser.add_argument(
        "--bot-id",
        required=True,
        help="Existing Copilot Studio bot ID (GUID) to register.",
    )
    parser.add_argument(
        "--tenant-id",
        help="Tenant ID (defaults to organizations).",
    )
    parser.add_argument(
        "--name",
        help="Agent display name (auto-detected from the bot when omitted).",
    )
    parser.add_argument(
        "--schema-name",
        help="Agent schema name (auto-detected from the bot when omitted).",
    )
    parser.add_argument(
        "--slug",
        help="Agent slug (defaults to a slug of the display name).",
    )
    parser.add_argument(
        "--unmanaged",
        action="store_true",
        help="Record the agent as unmanaged (default is managed).",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help=(
            "Skip the TEST-ring reachability check and write the config from "
            "the supplied flags only."
        ),
    )
    parser.add_argument(
        "--no-folder",
        action="store_true",
        help=(
            "Do not create the agent workspace folder / evaluations subfolder "
            "(config is still written)."
        ),
    )
    parser.add_argument(
        "--config-path",
        default=str(DEFAULT_CONFIG_PATH),
        help="Config output path (defaults to .local/config.json).",
    )
    args = parser.parse_args(argv)

    try:
        result = register_existing_agent(
            args.environment_id,
            args.bot_id,
            tenant_id=args.tenant_id,
            name=args.name,
            schema_name=args.schema_name,
            slug=args.slug,
            managed=not args.unmanaged,
            verify=not args.no_verify,
            ensure_folder=not args.no_folder,
            config_path=Path(args.config_path),
        )
    except (MinimalBotEvaluationError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1

    agent = result["config"]["agent"]
    summary: dict[str, Any] = {
        "status": "registered",
        "configPath": result["configPath"],
        "agentFolder": result["agentFolder"],
        "environmentId": result["config"]["environmentId"],
        "botId": agent["botId"],
        "name": agent["name"],
        "slug": agent["slug"],
        "verified": bool(result["verified"]),
    }
    if result["verified"]:
        summary["signedInUser"] = result["verified"].get("username")
        summary["componentCount"] = result["verified"].get("componentCount")
    print("MINIMALBOT_SETUP_JSON: " + json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
