# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Reconcile a selected setup agent with the kit's DA-GA product line."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    authenticate_flightcheck,
    derive_environment_host,
    validate_environment_host,
)
from auth import AuthExpiredError, authenticate, query_all
from flightcheck.powerplatform_client import PowerPlatformClient
from http_errors import APIError


CEA_SCHEMA_NAMES = frozenset(
    {
        "msdyn_copilotforemployeeselfservice",
        "msdyn_copilotforemployeeselfservicecore",
        "msdyn_copilotforemployeeselfservicehr",
        "msdyn_copilotforemployeeselfserviceit",
    }
)
DA_SCHEMA_NAMES = frozenset(
    {
        "gptagent_copilotforemployeeselfservice",
        "gptagent_copilotforemployeeselfservicecore",
        "gptagent_copilotforemployeeselfservicehr",
        "gptagent_copilotforemployeeselfserviceit",
    }
)
RESULT_PREFIX = "DA_SETUP_PRODUCT_RECONCILIATION_JSON:"
_RELEASE_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "reference"
    / "product-line-releases.json"
)
_SAFE_RELEASE_VALUE = re.compile(r"^[A-Za-z0-9._-]+$")
_GUID_AT_END = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def _normalize_guid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a GUID.") from exc


def classify_schema_name(schema_name: str | None) -> str:
    """Classify only exact, recognized solution-backed bot schema names."""
    normalized = str(schema_name or "").strip().casefold()
    if normalized in CEA_SCHEMA_NAMES:
        return "cea"
    if normalized in DA_SCHEMA_NAMES:
        return "da"
    return "unknown"


def _load_release(manifest_path: Path = _RELEASE_MANIFEST) -> dict[str, str]:
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        release = document["products"]["cea"]
        repository = release["repository"]
        release_tag = release["releaseTag"]
        install_root = release["installRoot"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("The CEA release manifest is missing or invalid.") from exc

    if repository != "microsoft/Employee-Self-Service-Agent-Developer-Kit":
        raise ValueError("The CEA release repository is not recognized.")
    if not release_tag.startswith("cea-v") or not _SAFE_RELEASE_VALUE.fullmatch(
        release_tag
    ):
        raise ValueError("The CEA release tag is not a safe pinned release.")
    if not _SAFE_RELEASE_VALUE.fullmatch(install_root):
        raise ValueError("The CEA install folder is not safe.")
    return {
        "repository": repository,
        "releaseTag": release_tag,
        "installRoot": install_root,
    }


def build_recovery_command(
    operating_system: str | None = None,
    manifest_path: Path = _RELEASE_MANIFEST,
) -> tuple[str, str]:
    """Build a release-pinned, side-by-side CEA installation command."""
    release = _load_release(manifest_path)
    repository = release["repository"]
    release_tag = release["releaseTag"]
    install_root = release["installRoot"]
    setup_url = (
        f"https://raw.githubusercontent.com/{repository}/{release_tag}/setup"
    )
    system_name = (operating_system or platform.system()).casefold()

    if system_name == "windows":
        command = (
            f"& ([scriptblock]::Create((irm {setup_url}/bootstrap.ps1))) "
            f"-Branch {release_tag} -SourceBaseUrl {setup_url} "
            f"-InstallRoot (Join-Path $env:USERPROFILE '{install_root}')"
        )
        return command, "powershell"

    command = (
        f'ESS_ADK_INSTALL_ROOT="$HOME/{install_root}" '
        f'/bin/bash -c "$(curl -fsSL {setup_url}/bootstrap-mac.sh)" -- '
        f"--branch {release_tag} --source-base-url {setup_url}"
    )
    return command, "bash"


def _probe_native_agent(
    environment_id: str,
    agent_id: str,
    ring: str,
    account: str | None,
    kit_root: Path,
    host: str | None,
    api_version: str,
) -> dict[str, Any]:
    cache_path = kit_root / ".local" / ".agentbuilder_token_cache.bin"
    token, tenant_id = authenticate_flightcheck(
        ring,
        cache_path=cache_path,
        account_hint=account,
        include_connectivity=False,
    )
    service_host = (
        validate_environment_host(host, ring)
        if host
        else derive_environment_host(environment_id, ring)
    )
    client = AgentBuilderClient(
        service_host,
        token,
        ring=ring,
        tenant_id=tenant_id,
        api_version=api_version,
    )
    return client.get_agent(agent_id)


def _resolve_dataverse_url(
    environment_id: str,
    account: str | None,
) -> str | None:
    client = PowerPlatformClient("organizations")
    client.authenticate(preferred_username=account)
    raw_environments = client.list_environments_for_user()
    if isinstance(raw_environments, dict) and "_error" in raw_environments:
        return None

    target = _normalize_guid(environment_id, "Environment ID")
    for environment in raw_environments:
        raw_id = str(environment.get("id") or "")
        match = _GUID_AT_END.search(raw_id)
        if not match:
            continue
        candidate = str(uuid.UUID(match.group(1)))
        if candidate != target:
            continue
        instance_url = str(environment.get("url") or "").rstrip("/")
        if instance_url:
            return instance_url
        domain_name = str(environment.get("domainName") or "").strip()
        if domain_name:
            return f"https://{domain_name}".rstrip("/")
    return None


def _read_dataverse_agent(
    env_url: str,
    agent_id: str,
    account: str | None,
) -> dict[str, Any] | None:
    token = authenticate(env_url, preferred_username=account)
    records = query_all(
        env_url,
        token,
        entity_set="bots",
        select="botid,name,schemaname,ismanaged",
        filter_expr=f"botid eq {agent_id}",
    )
    if len(records) > 1:
        raise ValueError("Dataverse returned duplicate records for one agent ID.")
    return records[0] if records else None


def _continue_result(classification: str, evidence: str) -> dict[str, Any]:
    return {
        "action": "continue-da-ga-setup",
        "classification": classification,
        "evidence": evidence,
    }


def reconcile_selected_agent(
    *,
    environment_id: str,
    agent_id: str,
    ring: str,
    account: str | None = None,
    kit_root: Path = Path("."),
    host: str | None = None,
    api_version: str = "2024-10-01",
    native_da_ga: bool = False,
    dataverse_url: str | None = None,
    operating_system: str | None = None,
) -> dict[str, Any]:
    """Return a bounded routing result; unknown evidence always fails open."""
    normalized_environment = _normalize_guid(environment_id, "Environment ID")
    normalized_agent = _normalize_guid(agent_id, "Agent ID")

    if native_da_ga:
        return _continue_result("da-ga", "provided-native")

    cea_evidence = "dataverse-schema"
    try:
        native_agent = _probe_native_agent(
            normalized_environment,
            normalized_agent,
            ring,
            account,
            kit_root.resolve(),
            host,
            api_version,
        )
        native_classification = classify_schema_name(
            native_agent.get("schemaName")
        )
        if native_classification == "cea":
            classification = "cea"
            cea_evidence = "native-schema"
        else:
            return _continue_result("da-ga", "native-minimal-bot")
    except (AgentBuilderError, OSError, ValueError, requests.RequestException):
        classification = "unknown"

    if classification != "cea":
        resolved_url = dataverse_url
        if not resolved_url:
            try:
                resolved_url = _resolve_dataverse_url(
                    normalized_environment,
                    account,
                )
            except (
                OSError,
                RuntimeError,
                SystemExit,
                ValueError,
                requests.RequestException,
            ):
                return _continue_result("unknown", "not-classified")
        if not resolved_url:
            return _continue_result("unknown", "not-classified")

        try:
            record = _read_dataverse_agent(
                resolved_url.rstrip("/"),
                normalized_agent,
                account,
            )
        except (
            APIError,
            AuthExpiredError,
            OSError,
            SystemExit,
            ValueError,
            requests.RequestException,
        ):
            return _continue_result("unknown", "not-classified")

        if not record:
            return _continue_result("unknown", "not-classified")
        classification = classify_schema_name(
            str(record.get("schemaname") or "")
        )
    if classification != "cea":
        return _continue_result(classification, "dataverse-schema")

    result = {
        "action": "stop-and-use-cea-kit",
        "classification": "cea",
        "evidence": cea_evidence,
    }
    try:
        command, shell = build_recovery_command(operating_system)
        release = _load_release()
    except ValueError:
        result["recoveryUnavailable"] = True
        return result
    result.update(
        {
            "releaseTag": release["releaseTag"],
            "recoveryCommand": command,
            "recoveryShell": shell,
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile one selected agent before DA-GA setup."
    )
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--ring", required=True)
    parser.add_argument("--account")
    parser.add_argument("--kit-root", type=Path, default=Path("."))
    parser.add_argument("--host")
    parser.add_argument("--api-version", default="2024-10-01")
    parser.add_argument("--native-da-ga", action="store_true")
    parser.add_argument("--dataverse-url")
    parser.add_argument(
        "--operating-system",
        choices=("Windows", "Darwin", "Linux"),
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = reconcile_selected_agent(
            environment_id=args.environment_id,
            agent_id=args.agent_id,
            ring=args.ring,
            account=args.account,
            kit_root=args.kit_root,
            host=args.host,
            api_version=args.api_version,
            native_da_ga=args.native_da_ga,
            dataverse_url=args.dataverse_url,
            operating_system=args.operating_system,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"{RESULT_PREFIX}{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
