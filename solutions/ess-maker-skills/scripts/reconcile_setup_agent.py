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
from auth import AuthExpiredError, authenticate, dataverse_get
from flightcheck.powerplatform_client import PowerPlatformClient
from http_errors import APIError


SOLUTION_BACKED_ESS_PREFIX = "msdyn_copilotforemployeeselfservice"
DA_GA_PREFIX = "gptagent_copilotforemployeeselfservice"
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
    """Classify the two supported ESS schema families by stable prefix."""
    normalized = str(schema_name or "").strip().casefold()
    if normalized.startswith(SOLUTION_BACKED_ESS_PREFIX):
        return "solution-backed-ess"
    if normalized.startswith(DA_GA_PREFIX):
        return "da-ga"
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
        raise APIError(
            status_code=int(raw_environments.get("_status") or 0),
            resource_name="environment",
            operation="read",
        )

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
) -> dict[str, Any]:
    token = authenticate(env_url, preferred_username=account)
    record = dataverse_get(
        env_url,
        token,
        f"bots({agent_id})",
        {"$select": "botid,name,schemaname,ismanaged"},
    )
    if not isinstance(record, dict):
        raise ValueError("Dataverse agent lookup returned an invalid shape.")
    return record


def _exception_evidence(exc: BaseException) -> dict[str, Any]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        chain.append(
            {
                "type": type(current).__name__,
                "message": str(current),
            }
        )
        current = current.__cause__ or current.__context__

    result: dict[str, Any] = {"causes": chain}
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        result["statusCode"] = status_code
    error_code = getattr(exc, "error_code", None)
    if error_code:
        result["errorCode"] = str(error_code)
    request_id = getattr(exc, "request_id", None)
    if request_id:
        result["requestId"] = str(request_id)
    return result


def _failure_result(
    backend: str,
    exc: BaseException,
    *,
    stage: str = "agent-lookup",
) -> dict[str, Any]:
    error = _exception_evidence(exc)
    status_code = error.get("statusCode")
    if status_code == 404:
        outcome = "not-found"
    elif status_code == 401:
        outcome = "authentication-required"
    elif status_code == 403:
        outcome = "access-denied"
    else:
        outcome = "uncertain"
    return {
        "backend": backend,
        "outcome": outcome,
        "stage": stage,
        "error": error,
    }


def _identity_summary(
    backend: str,
    agent: dict[str, Any],
    *,
    evidence: str,
) -> dict[str, Any]:
    schema_name = str(
        agent.get("schemaName") or agent.get("schemaname") or ""
    ).strip()
    display_name = str(
        agent.get("fullBotName")
        or agent.get("displayName")
        or agent.get("name")
        or ""
    ).strip()
    managed = agent.get("ismanaged")
    if managed is None:
        managed = agent.get("isManaged")
    if managed is None and isinstance(agent.get("managedProperties"), dict):
        managed = agent["managedProperties"].get("isManaged")

    identity: dict[str, Any] = {"schemaName": schema_name}
    if display_name:
        identity["displayName"] = display_name
    if isinstance(managed, bool):
        identity["isManaged"] = managed
    return {
        "backend": backend,
        "outcome": "found",
        "evidence": evidence,
        "productFamily": classify_schema_name(schema_name),
        "identity": identity,
    }


def probe_native_identity(
    *,
    environment_id: str,
    agent_id: str,
    ring: str,
    account: str | None = None,
    kit_root: Path = Path("."),
    host: str | None = None,
    api_version: str = "2024-10-01",
) -> dict[str, Any]:
    normalized_environment = _normalize_guid(environment_id, "Environment ID")
    normalized_agent = _normalize_guid(agent_id, "Agent ID")
    try:
        agent = _probe_native_agent(
            normalized_environment,
            normalized_agent,
            ring,
            account,
            kit_root.resolve(),
            host,
            api_version,
        )
    except (
        AgentBuilderError,
        OSError,
        ValueError,
        requests.RequestException,
    ) as exc:
        return _failure_result("native", exc)
    return _identity_summary(
        "native",
        agent,
        evidence="minimalbot-direct",
    )


def probe_dataverse_identity(
    *,
    environment_id: str,
    agent_id: str,
    account: str | None = None,
    dataverse_url: str | None = None,
) -> dict[str, Any]:
    normalized_environment = _normalize_guid(environment_id, "Environment ID")
    normalized_agent = _normalize_guid(agent_id, "Agent ID")
    resolved_url = dataverse_url
    if not resolved_url:
        try:
            resolved_url = _resolve_dataverse_url(
                normalized_environment,
                account,
            )
        except (
            APIError,
            OSError,
            RuntimeError,
            ValueError,
            requests.RequestException,
        ) as exc:
            return _failure_result(
                "dataverse",
                exc,
                stage="environment-resolution",
            )
    if not resolved_url:
        return {
            "backend": "dataverse",
            "outcome": "uncertain",
            "stage": "environment-resolution",
            "error": {
                "causes": [
                    {
                        "type": "EnvironmentUrlNotResolved",
                        "message": (
                            "The exact Dataverse URL was not available from "
                            "the user-scoped environment list."
                        ),
                    }
                ]
            },
        }

    try:
        agent = _read_dataverse_agent(
            resolved_url.rstrip("/"),
            normalized_agent,
            account,
        )
    except (
        APIError,
        AuthExpiredError,
        OSError,
        ValueError,
        requests.RequestException,
    ) as exc:
        return _failure_result("dataverse", exc)
    return _identity_summary(
        "dataverse",
        agent,
        evidence="dataverse-direct",
    )


def reconcile_selected_agent(
    *,
    environment_id: str,
    agent_id: str,
    ring: str,
    account: str | None = None,
    kit_root: Path = Path("."),
    host: str | None = None,
    api_version: str = "2024-10-01",
    dataverse_url: str | None = None,
    probe: str,
) -> dict[str, Any]:
    """Run one independent, read-only identity probe."""
    if probe == "native":
        return probe_native_identity(
            environment_id=environment_id,
            agent_id=agent_id,
            ring=ring,
            account=account,
            kit_root=kit_root,
            host=host,
            api_version=api_version,
        )
    if probe == "dataverse":
        return probe_dataverse_identity(
            environment_id=environment_id,
            agent_id=agent_id,
            account=account,
            dataverse_url=dataverse_url,
        )
    raise ValueError("Probe must be 'native' or 'dataverse'.")


def known_native_identity(schema_name: str) -> dict[str, Any]:
    """Classify identity already proven by a native MinimalBot operation."""
    return _identity_summary(
        "native",
        {"schemaName": schema_name},
        evidence="provided-native",
    )


def compatible_kit_result(
    operating_system: str | None = None,
) -> dict[str, Any]:
    """Return the pinned compatible-kit installation operation."""
    try:
        command, shell = build_recovery_command(operating_system)
        release = _load_release()
    except ValueError as exc:
        return {
            "outcome": "unavailable",
            "error": _exception_evidence(exc),
        }
    return {
        "outcome": "available",
        "releaseTag": release["releaseTag"],
        "recoveryCommand": command,
        "recoveryShell": shell,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe one selected agent before DA-GA setup."
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--probe", choices=("native", "dataverse"))
    operation.add_argument("--known-native-schema")
    operation.add_argument("--compatible-kit", action="store_true")
    parser.add_argument("--environment-id")
    parser.add_argument("--agent-id")
    parser.add_argument("--ring")
    parser.add_argument("--account")
    parser.add_argument("--kit-root", type=Path, default=Path("."))
    parser.add_argument("--host")
    parser.add_argument("--api-version", default="2024-10-01")
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
        if args.compatible_kit:
            result = compatible_kit_result(args.operating_system)
        elif args.known_native_schema is not None:
            result = known_native_identity(args.known_native_schema)
        else:
            if not args.environment_id or not args.agent_id:
                raise ValueError(
                    "Environment ID and agent ID are required for a probe."
                )
            if args.probe == "native" and not args.ring:
                raise ValueError("Ring is required for a native probe.")
            result = reconcile_selected_agent(
                environment_id=args.environment_id,
                agent_id=args.agent_id,
                ring=args.ring or "",
                account=args.account,
                kit_root=args.kit_root,
                host=args.host,
                api_version=args.api_version,
                dataverse_url=args.dataverse_url,
                probe=args.probe or "",
            )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"{RESULT_PREFIX}{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
