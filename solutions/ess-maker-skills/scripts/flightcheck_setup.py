# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Select a native DA for standalone FlightCheck without running foundation setup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
import uuid

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    DEFAULT_API_VERSION,
    DEFAULT_TOKEN_CACHE,
    authenticate_flightcheck,
    derive_environment_host,
    list_environments,
)
from setup_existing_da import (
    ExistingDASetupError,
    _confirm_direct_native_authoring_identity,
    _write_json,
    resolve_da_target,
    summarize_environments,
)


def _choose(options: list[dict[str, Any]], label: str, name_key: str) -> dict[str, Any]:
    if not options:
        raise ValueError(
            f"No {label} are visible to this account. Verify access or rerun "
            "with the intended DA's Copilot Studio URL."
        )
    for index, option in enumerate(options, 1):
        name = option.get(name_key) or option.get("shortBotName") or option.get("botId") or option.get("id")
        print(f"  {index}. {name}")
    choice = input(f"Select {label} number: ").strip()
    if not choice.isdecimal() or not 1 <= int(choice) <= len(options):
        raise ValueError(f"Select one of the listed {label}; selection cannot be skipped.")
    return options[int(choice) - 1]


def configure_standalone(kit_root: Path, ring: str) -> dict[str, Any]:
    config_path = kit_root / ".local" / "config.json"
    existing: dict[str, Any] = {}
    if config_path.exists():
        existing = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(existing, dict):
            raise ValueError("Existing .local/config.json must contain an object.")
        if existing.get("flightCheckOnly") is not True:
            raise ValueError(
                "This is an existing maker workspace. Run /flightcheck there, "
                "or choose a different -InstallRoot for standalone FlightCheck. "
                "Its configuration has not been changed."
            )
        print("Selecting a DA for this run; the saved configuration changes only after verification.")
    version = existing.get("agentBuilderApiVersion", DEFAULT_API_VERSION)
    if not isinstance(version, str) or not version.strip():
        raise ValueError("agentBuilderApiVersion must be a non-empty string.")

    print("Standalone FlightCheck checks Declarative Agents (DA), not legacy/custom-engine agents.")
    supplied_url = input(
        "Paste the DA's Copilot Studio URL, or press Enter to list environments and agents: "
    ).strip()
    target = (
        resolve_da_target(
            target_url=supplied_url, environment_id=None, ring=ring, require_agent=True,
        )
        if supplied_url else None
    )
    cache = kit_root / DEFAULT_TOKEN_CACHE
    token, tenant_id, account = authenticate_flightcheck(
        ring,
        cache_path=cache,
        force_account_selection=True,
        include_connectivity=False,
        allow_write=False,
        emit_account_identity=False,
        return_account_identity=True,
        require_account_identity=True,
    )
    if not account:
        raise ValueError("Sign-in did not verify the selected Microsoft account.")
    tenant_id = str(uuid.UUID(tenant_id))
    if target:
        environment_id = target["environmentId"]
    else:
        environments = summarize_environments(
            list_environments(token, ring, api_version=version)
        )
        environment_id = _choose(environments, "environment", "name")["id"]
    environment_id = str(uuid.UUID(environment_id))
    host = derive_environment_host(environment_id, ring)
    client = AgentBuilderClient(
        host, token, ring=ring, tenant_id=tenant_id, api_version=version,
    )
    if target:
        agent_id = target["agentId"]
    else:
        agents = client.list_minimal_bots()
        agent_id = _choose(agents, "DA agent", "fullBotName").get("botId")
    agent_id = str(uuid.UUID(str(agent_id or "")))
    agent = client.get_agent(agent_id)
    _confirm_direct_native_authoring_identity(agent_id, agent)
    slug = f"flightcheck-{agent_id}"
    entry = {
        "botId": agent_id,
        "name": agent.get("fullBotName") or agent.get("shortBotName") or agent_id,
        "releaseLine": "da",
        "slug": slug,
        "folder": "",
    }
    config = {
        "configVersion": 1,
        "setup": "flightcheck-only",
        "flightCheckOnly": True,
        "releaseLine": "da",
        "environmentId": environment_id,
        "tenantId": tenant_id,
        "powerPlatformApiEndpoint": host,
        "ring": ring,
        "agentBuilderApiVersion": version,
        "account": account,
        "agent": entry,
        "agents": [entry],
        "activeAgent": slug,
    }
    _write_json(config_path, config)
    print(f"Selected DA: {entry['name']} ({agent_id}) in environment {environment_id}.")
    print("Cloud checks use this exact target. Local-file checks need an existing agent workspace.")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ring", choices=("prod", "preprod", "test"), default="prod")
    parser.add_argument("--kit-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        configure_standalone(args.kit_root.resolve(), args.ring)
    except (EOFError, KeyboardInterrupt):
        print("DA selection cancelled. FlightCheck was not started.", file=sys.stderr)
        return 130
    except (
        ValueError, OSError, AgentBuilderError, ExistingDASetupError, requests.RequestException,
    ) as exc:
        print(f"ERROR: DA selection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
