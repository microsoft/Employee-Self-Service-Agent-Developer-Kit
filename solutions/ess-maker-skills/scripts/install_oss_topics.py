# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Install reviewed Workday OSS topics through an authenticated browser session.

The installer attaches to an already authenticated Copilot Studio agent
configuration page over CDP. It observes the page's own MinimalBot components
request, keeps the request credentials in memory, and uses the browser context
for bounded API calls. It never writes tokens, cookies, authorization headers,
or browser storage state.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlparse
import uuid

import yaml

from agentbuilder import (
    environment_id_from_host,
    ring_from_environment_host,
    validate_environment_host,
)
from agentbuilder_object_model import (
    ObjectModelConverterError,
    object_models_to_yaml,
    validate_object_model_runtime,
    yaml_to_object_models,
)


COMPONENTS_PATH = "/copilotstudio/minimalBots/api/{agent_id}/components"
DEFAULT_CDP_ENDPOINT = "http://localhost:9222"
SETUP_NAME = "WorkdayOSSTemplateConfigurationSetup"
SOURCE_SCHEMA = "gptagent_copilotforemployeeselfservicehr"
EMPTY_CHANGE_COLLECTIONS = {
    "cloudFlowDefinitionChanges": [],
    "connectionReferenceChanges": [],
    "connectorDefinitionChanges": [],
    "environmentVariableChanges": [],
    "aIPluginOperationChanges": [],
    "componentCollectionChanges": [],
    "dataverseTableSearchChanges": [],
    "connectedAgentDefinitionChanges": [],
}
EMPLOYEE_SCENARIOS = (
    "EmployeeAddDependents",
    "EmployeeGetVacationBalance",
    "EmployeeUpdateResidentialAddress",
    "WorkdayEmployeeRequestTimeOff",
    "WorkdayEmployeesviewtheirjobtaxonomy",
    "WorkdayGetContactInformation",
    "WorkdayGetEducation",
    "WorkdayGetGovernmentIDs",
    "WorkdayGetUserProfile",
    "WorkdayGivePeerFeedback",
    "WorkdayManageEmergencyContact",
)
MANAGER_SCENARIOS = (
    "WorkdayGetManagerReporteesTimeInPosition",
    "WorkdayManagerServiceAnniversary",
    "WorkdayManagersdirect-CompanyCode",
    "WorkdayManagersdirect-CostCenter",
    "WorkdayManagersdirect-Jobtaxanomy",
)
ALL_SCENARIOS = EMPLOYEE_SCENARIOS + MANAGER_SCENARIOS
ALLOWED_PAGE_HOSTS = (
    "copilotstudio.microsoft.com",
    "copilotstudio.preview.microsoft.com",
    "make.powerapps.com",
)


class InstallerError(RuntimeError):
    """A safe, user-actionable installer failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TransportError(InstallerError):
    """A MinimalBot request failure that may have an indeterminate outcome."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        indeterminate: bool = False,
    ) -> None:
        super().__init__(code, message)
        self.status = status
        self.indeterminate = indeterminate


class InstallRunError(InstallerError):
    """A failed topic operation with verified prior progress."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        results: list[dict[str, Any]],
        failed_entry: "ManifestEntry",
    ) -> None:
        super().__init__(code, message)
        self.results = results
        self.failed_entry = failed_entry


@dataclass(frozen=True)
class Target:
    environment_id: str
    agent_id: str
    agent_schema: str
    endpoint: str
    ring: str
    tenant: str | None


@dataclass(frozen=True)
class ManifestEntry:
    order: int
    category: str
    name: str
    display_name: str
    schema_suffix: str
    source_path: Path
    source_relative_path: str
    source_sha256: str
    raw_yaml: str
    child_dialogs: tuple[str, ...]

    def schema_name(self, agent_schema: str) -> str:
        return f"{agent_schema}.topic.{self.schema_suffix}"


@dataclass(frozen=True)
class BrowserResponse:
    status: int
    body: dict[str, Any]
    request_id: str | None


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def source_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallerError(
            "source-revision-unavailable",
            "Unable to resolve the source Git commit.",
        ) from exc
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise InstallerError(
            "source-revision-unavailable",
            "Unable to resolve the source Git commit.",
        )
    return commit.lower()


def _normalize_guid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError) as exc:
        raise InstallerError(
            "invalid-target",
            f"{label} must be a GUID.",
        ) from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InstallerError(
            "missing-config",
            f"Configuration file not found: {path}",
        ) from exc
    except (OSError, ValueError) as exc:
        raise InstallerError(
            "invalid-config",
            f"Configuration file is not valid JSON: {path}",
        ) from exc
    if not isinstance(value, dict):
        raise InstallerError(
            "invalid-config",
            f"Configuration file must contain a JSON object: {path}",
        )
    return value


def _active_agent(config: dict[str, Any]) -> dict[str, Any]:
    active_slug = str(config.get("activeAgent") or "").strip()
    agents = config.get("agents")
    if active_slug and isinstance(agents, list):
        matches = [
            agent
            for agent in agents
            if isinstance(agent, dict)
            and str(
                agent.get("slug")
                or agent.get("workspaceSlug")
                or agent.get("workspace_slug")
                or ""
            ).strip()
            == active_slug
        ]
        if len(matches) != 1:
            raise InstallerError(
                "invalid-config",
                "activeAgent does not resolve to exactly one configured agent.",
            )
        return matches[0]
    agent = config.get("agent")
    if isinstance(agent, dict):
        return agent
    raise InstallerError(
        "invalid-config",
        "No active agent is configured.",
    )


def _configured_tenant(config_path: Path) -> str | None:
    candidates = (
        config_path.parent / "connect" / "workday" / "config.json",
        config_path.parent.parent / "connect" / "workday" / "config.json",
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            tenant = str(value.get("tenant") or "").strip()
            if tenant:
                return tenant
    return None


def resolve_target(
    config_path: Path,
    *,
    environment_id: str | None = None,
    agent_id: str | None = None,
    agent_schema: str | None = None,
    endpoint: str | None = None,
    tenant: str | None = None,
) -> Target:
    config = _read_json(config_path) if config_path.is_file() else {}
    try:
        agent = _active_agent(config)
    except InstallerError:
        agent = {}
    resolved_environment_id = _normalize_guid(
        environment_id
        or str(agent.get("environmentId") or config.get("environmentId") or ""),
        "Environment ID",
    )
    resolved_agent_id = _normalize_guid(
        agent_id
        or str(
            agent.get("agentId")
            or agent.get("botId")
            or agent.get("id")
            or ""
        ),
        "Agent ID",
    )
    resolved_schema = str(
        agent_schema
        or agent.get("schemaName")
        or agent.get("schema_name")
        or ""
    ).strip()
    if not resolved_schema or not re.fullmatch(r"[A-Za-z0-9_]+", resolved_schema):
        raise InstallerError(
            "invalid-target",
            "Agent schema name is missing or contains unsupported characters.",
        )
    resolved_endpoint = str(
        endpoint
        or agent.get("powerPlatformApiEndpoint")
        or config.get("powerPlatformApiEndpoint")
        or ""
    ).strip()
    try:
        ring = ring_from_environment_host(resolved_endpoint)
        resolved_endpoint = validate_environment_host(resolved_endpoint, ring)
        endpoint_environment = environment_id_from_host(resolved_endpoint, ring)
    except ValueError as exc:
        raise InstallerError(
            "invalid-target",
            "Power Platform API endpoint is missing or is not a supported "
            "environment-specific HTTPS host.",
        ) from exc
    if endpoint_environment.casefold() != resolved_environment_id.casefold():
        raise InstallerError(
            "target-mismatch",
            "The configured environment ID does not match the Power Platform "
            "API endpoint.",
        )
    resolved_tenant = (
        str(tenant).strip()
        if tenant is not None
        else _configured_tenant(config_path)
    )
    if resolved_tenant and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*",
        resolved_tenant,
    ):
        raise InstallerError(
            "invalid-target",
            "Workday tenant contains unsupported URL characters.",
        )
    return Target(
        environment_id=resolved_environment_id,
        agent_id=resolved_agent_id,
        agent_schema=resolved_schema,
        endpoint=resolved_endpoint,
        ring=ring,
        tenant=resolved_tenant or None,
    )


def _schema_suffix(name: str) -> str:
    suffix = re.sub(r"[^0-9A-Za-z]", "", name)
    if not suffix:
        raise InstallerError(
            "invalid-source",
            f"Topic name has no usable schema characters: {name!r}",
        )
    return suffix


def _child_dialogs(value: Any) -> tuple[str, ...]:
    found: set[str] = set()
    if isinstance(value, dict):
        if (
            value.get("kind") == "BeginDialog"
            and isinstance(value.get("dialog"), str)
        ):
            found.add(value["dialog"])
        for child in value.values():
            found.update(_child_dialogs(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_child_dialogs(child))
    return tuple(sorted(found, key=str.casefold))


def _manifest_source_paths(
    samples_root: Path,
    scenarios: Iterable[str],
    *,
    include_setup: bool = True,
) -> list[tuple[str, str, Path]]:
    paths = []
    if include_setup:
        paths.append(
            (
                "shared",
                SETUP_NAME,
                samples_root / f"{SETUP_NAME}.yaml",
            )
        )
    selected = set(scenarios)
    for name in EMPLOYEE_SCENARIOS:
        if name in selected:
            paths.append(("employee", name, samples_root / "Employee" / name / "topic.yaml"))
    for name in MANAGER_SCENARIOS:
        if name in selected:
            paths.append(("manager", name, samples_root / "Manager" / name / "topic.yaml"))
    return paths


def build_manifest(
    samples_root: Path,
    *,
    scenarios: Iterable[str] = ALL_SCENARIOS,
    include_setup: bool = True,
    display_prefix: str = "",
) -> list[ManifestEntry]:
    root = samples_root.resolve()
    selected = tuple(scenarios)
    if len(selected) != len(set(selected)):
        raise InstallerError(
            "invalid-selection",
            "Topic selection contains duplicates.",
        )
    unknown = sorted(set(selected) - set(ALL_SCENARIOS))
    if unknown:
        raise InstallerError(
            "invalid-selection",
            "Unknown Workday OSS topic(s): " + ", ".join(unknown),
        )
    entries: list[ManifestEntry] = []
    for order, (category, name, path) in enumerate(
        _manifest_source_paths(root, selected, include_setup=include_setup),
        start=1,
    ):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            raw = resolved.read_text(encoding="utf-8")
            document = yaml.safe_load(raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            raise InstallerError(
                "invalid-source",
                f"Unable to load Workday OSS source: {path}",
            ) from exc
        if not isinstance(document, dict) or document.get("kind") != "AdaptiveDialog":
            raise InstallerError(
                "invalid-source",
                f"Expected an AdaptiveDialog source: {path}",
            )
        try:
            source_relative_path = resolved.relative_to(
                repository_root()
            ).as_posix()
        except ValueError as exc:
            raise InstallerError(
                "invalid-source",
                "Workday OSS sources must be inside this ADK checkout.",
            ) from exc
        entries.append(
            ManifestEntry(
                order=order,
                category=category,
                name=name,
                display_name=f"{display_prefix}{name}",
                schema_suffix=_schema_suffix(name),
                source_path=resolved,
                source_relative_path=source_relative_path,
                source_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                raw_yaml=raw,
                child_dialogs=_child_dialogs(document),
            )
        )
    if not entries:
        raise InstallerError(
            "invalid-selection",
            "At least one Workday OSS topic must be selected.",
        )
    if include_setup and entries[0].name != SETUP_NAME:
        raise InstallerError(
            "invalid-source",
            "The shared Workday OSS setup topic must be first.",
        )
    return entries


def _changes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    changes = payload.get("botComponentChanges")
    if not isinstance(changes, list):
        raise InstallerError(
            "invalid-response",
            "MinimalBot component response has no botComponentChanges list.",
        )
    return [change for change in changes if isinstance(change, dict)]


def _components(payload: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for change in _changes(payload):
        component = change.get("component")
        if isinstance(component, dict):
            components.append(component)
    return components


def validate_remote_identity(payload: dict[str, Any], target: Target) -> None:
    bot = payload.get("bot")
    if not isinstance(bot, dict):
        raise InstallerError(
            "invalid-response",
            "MinimalBot component response did not include bot identity.",
        )
    fetched_id = _normalize_guid(
        str(bot.get("cdsBotId") or bot.get("componentIdUnique") or ""),
        "Fetched agent ID",
    )
    if fetched_id.casefold() != target.agent_id.casefold():
        raise InstallerError(
            "target-mismatch",
            "MinimalBot returned content for a different agent.",
        )
    fetched_schema = str(bot.get("schemaName") or "").strip()
    if fetched_schema.casefold() != target.agent_schema.casefold():
        raise InstallerError(
            "target-mismatch",
            "MinimalBot returned content for a different agent schema.",
        )


def _dialog_components(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        component
        for component in _components(payload)
        if component.get("$kind") == "DialogComponent"
    ]


def _component_display_name(component: dict[str, Any]) -> str:
    for value in (
        component.get("displayName"),
        component.get("name"),
        (component.get("dialog") or {}).get("displayName")
        if isinstance(component.get("dialog"), dict)
        else None,
    ):
        text = str(value or "").strip()
        if text:
            return text
    schema_name = str(component.get("schemaName") or "")
    return schema_name.rsplit(".topic.", 1)[-1]


def _duplicate_match(
    entry: ManifestEntry,
    target: Target,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    expected_schema = entry.schema_name(target.agent_schema)
    dialogs = _dialog_components(payload)
    by_schema = [
        component
        for component in dialogs
        if str(component.get("schemaName") or "").casefold()
        == expected_schema.casefold()
    ]
    by_display = [
        component
        for component in dialogs
        if _component_display_name(component).casefold()
        == entry.display_name.casefold()
    ]
    if len(by_schema) > 1 or len(by_display) > 1:
        raise InstallerError(
            "ambiguous-duplicate",
            f"Existing topic identity is ambiguous for {entry.display_name}.",
        )
    matches = {
        str(component.get("id") or ""): component
        for component in [*by_schema, *by_display]
        if str(component.get("id") or "")
    }
    if len(matches) > 1:
        raise InstallerError(
            "ambiguous-duplicate",
            f"Display and schema identity resolve to different existing topics "
            f"for {entry.display_name}.",
        )
    if not matches:
        return None, None
    component = next(iter(matches.values()))
    reason = (
        "displayName+schemaName"
        if by_schema and by_display
        else "schemaName"
        if by_schema
        else "displayName"
    )
    return component, reason


def _dialog_reference_map(
    entries: Iterable[ManifestEntry],
    payload: dict[str, Any],
) -> dict[str, str]:
    dialogs = _dialog_components(payload)
    by_suffix: dict[str, list[str]] = {}
    for component in dialogs:
        schema_name = str(component.get("schemaName") or "").strip()
        if ".topic." not in schema_name:
            continue
        suffix = schema_name.rsplit(".topic.", 1)[1].casefold()
        by_suffix.setdefault(suffix, []).append(schema_name)
    mapping: dict[str, str] = {}
    for entry in entries:
        for reference in entry.child_dialogs:
            if ".topic." not in reference:
                raise InstallerError(
                    "missing-dependency",
                    f"{entry.display_name} has an unsupported child topic "
                    f"reference: {reference}",
                )
            suffix = reference.rsplit(".topic.", 1)[1]
            matches = sorted(set(by_suffix.get(suffix.casefold(), [])))
            if len(matches) != 1:
                raise InstallerError(
                    "missing-dependency",
                    f"{entry.display_name} requires exactly one existing "
                    f"topic ending in .topic.{suffix}; found {len(matches)}.",
                )
            mapping[reference] = matches[0]
    return mapping


def _prepared_yaml(
    entry: ManifestEntry,
    reference_map: dict[str, str],
    tenant: str | None,
) -> str:
    content = entry.raw_yaml
    for source, target in sorted(reference_map.items()):
        content = content.replace(source, target)
    if "<TENANT_NAME>" in content:
        if not tenant:
            raise InstallerError(
                "missing-tenant",
                f"{entry.display_name} requires the Workday tenant name. "
                "Pass --tenant or configure .local/connect/workday/config.json.",
            )
        content = content.replace("<TENANT_NAME>", tenant)
    return content


def prepare_dialogs(
    entries: list[ManifestEntry],
    target: Target,
    payload: dict[str, Any],
    *,
    converter: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ] = yaml_to_object_models,
    roundtrip_converter: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ] = object_models_to_yaml,
) -> dict[str, dict[str, Any]]:
    reference_map = _dialog_reference_map(entries, payload)
    prepared_yaml = {
        entry.name: _prepared_yaml(entry, reference_map, target.tenant)
        for entry in entries
    }
    converted = converter(
        [
            {"key": entry.name, "yaml": prepared_yaml[entry.name]}
            for entry in entries
        ]
    )
    by_key = {
        str(item.get("key") or ""): item
        for item in converted
        if isinstance(item, dict)
    }
    prepared: dict[str, dict[str, Any]] = {}
    for entry in entries:
        result = by_key.get(entry.name)
        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or result.get("elementType") != "AdaptiveDialog"
            or not isinstance(result.get("objectModel"), dict)
        ):
            detail = (
                str((result or {}).get("error", {}).get("message") or "")
                if isinstance(result, dict)
                else ""
            )
            raise InstallerError(
                "conversion-failed",
                f"Microsoft Object Model conversion failed for "
                f"{entry.display_name}: {detail or 'invalid conversion result'}",
            )
        prepared[entry.name] = result["objectModel"]
    roundtrip = roundtrip_converter(
        [
            {"key": entry.name, "objectModel": prepared[entry.name]}
            for entry in entries
        ]
    )
    roundtrip_by_key = {
        str(item.get("key") or ""): item
        for item in roundtrip
        if isinstance(item, dict)
    }
    for entry in entries:
        result = roundtrip_by_key.get(entry.name)
        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or result.get("elementType") != "AdaptiveDialog"
            or not isinstance(result.get("yaml"), str)
        ):
            raise InstallerError(
                "conversion-failed",
                f"Microsoft Object Model round-trip failed for "
                f"{entry.display_name}.",
            )
        try:
            if yaml.safe_load(result["yaml"]).get("kind") != "AdaptiveDialog":
                raise ValueError("round-trip is not AdaptiveDialog")
        except (AttributeError, ValueError, yaml.YAMLError) as exc:
            raise InstallerError(
                "conversion-failed",
                f"Microsoft Object Model round-trip was invalid for "
                f"{entry.display_name}.",
            ) from exc
    return prepared


def _component_id(target: Target, schema_name: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"ess-adk:workday-oss:{target.agent_id}:{schema_name.casefold()}",
        )
    )


def _insert_change(
    entry: ManifestEntry,
    target: Target,
    dialog: dict[str, Any],
) -> dict[str, Any]:
    schema_name = entry.schema_name(target.agent_schema)
    return {
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": "DialogComponent",
            "id": _component_id(target, schema_name),
            "displayName": entry.display_name,
            "schemaName": schema_name,
            "state": "Active",
            "status": "Active",
            "dialog": dialog,
            "extensionData": {"UseProvidedBotComponentId": True},
        },
    }


def _without_server_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_server_fields(child)
            for key, child in value.items()
            if key not in {
                "diagnostics",
                "structuredCondition",
                "structuredRecordExpression",
            }
        }
    if isinstance(value, list):
        return [_without_server_fields(child) for child in value]
    return value


def blocking_diagnostics(
    value: Any,
    *,
    path: str = "$",
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if isinstance(value, dict):
        diagnostics = value.get("diagnostics")
        if isinstance(diagnostics, list):
            for index, diagnostic in enumerate(diagnostics):
                if not isinstance(diagnostic, dict):
                    continue
                kind = str(diagnostic.get("$kind") or "")
                code = str(diagnostic.get("errorCode") or "")
                if not code and not kind.casefold().endswith("error"):
                    continue
                findings.append(
                    {
                        "path": f"{path}.diagnostics[{index}]",
                        "kind": kind,
                        "errorCode": code,
                        "message": str(diagnostic.get("errorMessage") or ""),
                        "referenceType": str(
                            diagnostic.get("referenceType") or ""
                        ),
                        "referenceId": str(
                            diagnostic.get("referenceId") or ""
                        ),
                    }
                )
        for key, child in value.items():
            if key != "diagnostics":
                findings.extend(
                    blocking_diagnostics(child, path=f"{path}.{key}")
                )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(
                blocking_diagnostics(child, path=f"{path}[{index}]")
            )
    return findings


def _verified_component(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    expected_id = str(expected["id"])
    matches = [
        component
        for component in _dialog_components(payload)
        if str(component.get("id") or "").casefold()
        == expected_id.casefold()
    ]
    if len(matches) != 1:
        raise InstallerError(
            "verification-failed",
            f"Read-back did not find exactly one component ID {expected_id}.",
        )
    component = matches[0]
    if (
        str(component.get("schemaName") or "").casefold()
        != str(expected["schemaName"]).casefold()
        or _component_display_name(component).casefold()
        != str(expected["displayName"]).casefold()
        or component.get("state") != "Active"
        or component.get("status") != "Active"
        or _without_server_fields(component.get("dialog"))
        != _without_server_fields(expected["dialog"])
    ):
        raise InstallerError(
            "verification-failed",
            f"Read-back content or identity did not match "
            f"{expected['displayName']}.",
        )
    diagnostics = blocking_diagnostics(component)
    if diagnostics:
        first = diagnostics[0]
        detail = first["errorCode"] or first["kind"] or "error"
        raise InstallerError(
            "blocking-diagnostics",
            f"{expected['displayName']} has blocking diagnostics after save: "
            f"{detail}.",
        )
    return component


def _response_component_ids(body: dict[str, Any]) -> list[str]:
    changes = body.get("botComponentChanges")
    components = (
        [
            change.get("component")
            for change in changes
            if isinstance(change, dict)
            and isinstance(change.get("component"), dict)
        ]
        if isinstance(changes, list)
        else []
    )
    ids = {
        str(component.get("id") or "")
        for component in components
        if str(component.get("id") or "")
    }
    for key in ("componentId", "id"):
        value = str(body.get(key) or "")
        if value:
            ids.add(value)
    return sorted(ids, key=str.casefold)


class BrowserMinimalBotTransport:
    """CDP-attached transport that keeps browser credentials only in memory."""

    def __init__(
        self,
        target: Target,
        *,
        cdp_endpoint: str = DEFAULT_CDP_ENDPOINT,
        page_url_contains: str | None = None,
        capture_timeout_seconds: int = 45,
    ) -> None:
        self.target = target
        self.cdp_endpoint = cdp_endpoint
        self.page_url_contains = page_url_contains
        self.capture_timeout_seconds = capture_timeout_seconds
        self._playwright = None
        self._browser = None
        self._page = None
        self._request_context = None
        self._components_url = ""
        self._headers: dict[str, str] = {}

    def __enter__(self) -> "BrowserMinimalBotTransport":
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    @staticmethod
    def _allowed_page(page: Any) -> bool:
        parsed = urlparse(str(page.url or ""))
        hostname = (parsed.hostname or "").casefold()
        path = parsed.path.casefold().rstrip("/")
        route_is_safe = (
            path.rsplit("/", 1)[-1] in {"details", "overview", "tools"}
            or re.search(r"/adaptive/[0-9a-f-]{36}$", path) is not None
        )
        return (
            parsed.scheme == "https"
            and any(
                hostname == allowed or hostname.endswith(f".{allowed}")
                for allowed in ALLOWED_PAGE_HOSTS
            )
            and route_is_safe
        )

    def _select_page(self) -> Any:
        agent_match = self.target.agent_id.casefold()
        environment_match = self.target.environment_id.casefold()
        pages = [
            page
            for context in self._browser.contexts
            for page in context.pages
            if self._allowed_page(page)
            and agent_match in str(page.url or "").casefold()
            and environment_match in str(page.url or "").casefold()
        ]
        if self.page_url_contains:
            pages = [
                page
                for page in pages
                if self.page_url_contains.casefold()
                in str(page.url or "").casefold()
            ]
        if len(pages) != 1:
            raise InstallerError(
                "browser-page-not-found",
                "Open exactly one Copilot Studio agent Details or Overview "
                "page for the selected environment and agent, then rerun. Use "
                "--page-url-contains only to disambiguate multiple safe "
                "agent configuration tabs.",
            )
        return pages[0]

    def _matching_components_request(self, request: Any) -> bool:
        parsed = urlparse(str(request.url or ""))
        expected = COMPONENTS_PATH.format(agent_id=self.target.agent_id)
        query = parse_qs(parsed.query)
        return (
            str(request.method or "").upper() == "POST"
            and f"{parsed.scheme}://{parsed.netloc}".casefold()
            == self.target.endpoint.casefold()
            and parsed.path.casefold() == expected.casefold()
            and set(query) == {"api-version"}
            and len(query["api-version"]) == 1
            and bool(query["api-version"][0])
        )

    def _capture_contract(self) -> None:
        captured: dict[str, Any] = {}

        def observe(request: Any) -> None:
            if captured or not self._matching_components_request(request):
                return
            all_headers = getattr(request, "all_headers", None)
            raw_headers = (
                all_headers()
                if callable(all_headers)
                else request.headers
            )
            headers = {
                str(key).casefold(): str(value)
                for key, value in raw_headers.items()
            }
            authorization = headers.get("authorization", "")
            if not authorization.casefold().startswith("bearer "):
                return
            captured["url"] = request.url
            captured["headers"] = {
                "authorization": authorization,
                **(
                    {"x-ms-client-name": headers["x-ms-client-name"]}
                    if headers.get("x-ms-client-name")
                    else {}
                ),
            }

        self._page.on("request", observe)
        try:
            self._page.reload(
                wait_until="domcontentloaded",
                timeout=self.capture_timeout_seconds * 1000,
            )
            deadline = time.monotonic() + self.capture_timeout_seconds
            while not captured and time.monotonic() < deadline:
                self._page.wait_for_timeout(250)
        finally:
            self._page.remove_listener("request", observe)
        if not captured:
            raise InstallerError(
                "browser-auth-not-captured",
                "The Copilot Studio agent configuration page did not issue an "
                "authenticated MinimalBot components request. Confirm the "
                "page is fully loaded and signed in, then rerun. Use "
                "--offline-plan for a no-network fallback.",
            )
        self._components_url = str(captured["url"])
        self._headers = dict(captured["headers"])

    def connect(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise InstallerError(
                "missing-playwright",
                "Playwright is required. Install scripts/requirements.txt; "
                "a browser download is not required for CDP attach.",
            ) from exc
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(
                self.cdp_endpoint
            )
            self._page = self._select_page()
            self._request_context = self._page.context.request
            self._capture_contract()
        except InstallerError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise InstallerError(
                "browser-attach-failed",
                "Unable to attach to and inspect the authenticated Copilot "
                "Studio agent configuration page.",
            ) from exc

    def close(self) -> None:
        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None
                self._browser = None
                self._page = None
                self._request_context = None
                self._components_url = ""
                self._headers = {}

    def _request(self, method: str, body: dict[str, Any]) -> BrowserResponse:
        if self._request_context is None or not self._components_url:
            raise InstallerError(
                "browser-not-connected",
                "Browser transport is not connected.",
            )
        try:
            response = self._request_context.fetch(
                self._components_url,
                method=method,
                headers={
                    **self._headers,
                    "content-type": "application/json",
                    "accept": "application/json",
                },
                data=json.dumps(body, separators=(",", ":")),
                fail_on_status_code=False,
                timeout=180_000,
            )
        except Exception as exc:
            raise TransportError(
                "transport-failed",
                f"MinimalBot {method} request failed before a response was "
                "available.",
                indeterminate=method.upper() == "PUT",
            ) from exc
        try:
            content = response.json()
        except Exception:
            content = {}
        if not isinstance(content, dict):
            content = {}
        headers = {
            str(key).casefold(): str(value)
            for key, value in response.headers.items()
        }
        request_id = next(
            (
                headers[name]
                for name in (
                    "x-ms-request-id",
                    "x-ms-correlation-request-id",
                    "request-id",
                )
                if headers.get(name)
            ),
            None,
        )
        return BrowserResponse(response.status, content, request_id)

    def read_components(self) -> dict[str, Any]:
        response = self._request("POST", {})
        if response.status != 200:
            raise TransportError(
                "component-read-failed",
                f"MinimalBot component read failed with HTTP {response.status}.",
                status=response.status,
            )
        return response.body

    def write_components(self, payload: dict[str, Any]) -> BrowserResponse:
        response = self._request("PUT", payload)
        if response.status != 200:
            raise TransportError(
                "component-write-failed",
                f"MinimalBot component write failed with HTTP {response.status}.",
                status=response.status,
                indeterminate=response.status not in {400, 401, 403, 409, 412},
            )
        return response


def _entry_result(
    entry: ManifestEntry,
    target: Target,
    *,
    status: str,
    component_id: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    response_identity: bool | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "order": entry.order,
        "category": entry.category,
        "name": entry.name,
        "displayName": entry.display_name,
        "schemaName": entry.schema_name(target.agent_schema),
        "source": entry.source_relative_path,
        "sourceSha256": entry.source_sha256,
        "status": status,
        **({"componentId": component_id} if component_id else {}),
        **({"reason": reason} if reason else {}),
        **({"requestId": request_id} if request_id else {}),
        **(
            {"responseIdentityConfirmed": response_identity}
            if response_identity is not None
            else {}
        ),
        "blockingDiagnostics": diagnostics or [],
    }


def install_manifest(
    entries: list[ManifestEntry],
    target: Target,
    transport: Any,
    *,
    dry_run: bool,
    converter: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ] = yaml_to_object_models,
    roundtrip_converter: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]]
    ] = object_models_to_yaml,
) -> dict[str, Any]:
    initial = transport.read_components()
    validate_remote_identity(initial, target)
    prepared = prepare_dialogs(
        entries,
        target,
        initial,
        converter=converter,
        roundtrip_converter=roundtrip_converter,
    )
    results: list[dict[str, Any]] = []
    current = initial
    for entry in entries:
        try:
            existing, duplicate_reason = _duplicate_match(
                entry,
                target,
                current,
            )
            if existing is not None:
                results.append(
                    _entry_result(
                        entry,
                        target,
                        status="preserved",
                        component_id=str(existing.get("id") or "") or None,
                        reason=f"existing-{duplicate_reason}",
                        diagnostics=blocking_diagnostics(existing),
                    )
                )
                continue
            change = _insert_change(entry, target, prepared[entry.name])
            component = change["component"]
            if dry_run:
                results.append(
                    _entry_result(
                        entry,
                        target,
                        status="would-create",
                        component_id=str(component["id"]),
                    )
                )
                continue
            change_token = str(current.get("changeToken") or "")
            if not change_token:
                raise InstallerError(
                    "invalid-response",
                    "MinimalBot component response did not include a "
                    "changeToken.",
                )
            payload = {
                "changeToken": change_token,
                "botComponentChanges": [change],
                **EMPTY_CHANGE_COLLECTIONS,
            }
            response: BrowserResponse | None = None
            write_error: TransportError | None = None
            try:
                response = transport.write_components(payload)
            except TransportError as exc:
                write_error = exc
            readback = transport.read_components()
            validate_remote_identity(readback, target)
            verified = _verified_component(readback, component)
            if write_error is not None:
                if not write_error.indeterminate:
                    raise write_error
            response_ids = (
                _response_component_ids(response.body)
                if response is not None
                else []
            )
            response_identity = (
                str(component["id"]).casefold()
                in {value.casefold() for value in response_ids}
            )
            if response is not None and not response_identity:
                raise InstallerError(
                    "response-identity-missing",
                    f"MinimalBot saved {entry.display_name}, but the write "
                    "response did not identify the created component. "
                    "Read-back was retained; no automatic retry was performed.",
                )
            results.append(
                _entry_result(
                    entry,
                    target,
                    status=(
                        "created"
                        if write_error is None
                        else "created-after-indeterminate-response"
                    ),
                    component_id=str(verified["id"]),
                    request_id=response.request_id if response else None,
                    response_identity=(
                        response_identity if response else False
                    ),
                )
            )
            current = readback
        except InstallerError as exc:
            raise InstallRunError(
                exc.code,
                str(exc),
                results=results,
                failed_entry=entry,
            ) from exc
    return {
        "schemaVersion": 1,
        "sourceCommit": source_commit(),
        "status": "dry-run" if dry_run else "completed",
        "dryRun": dry_run,
        "target": {
            "environmentId": target.environment_id,
            "agentId": target.agent_id,
            "agentSchema": target.agent_schema,
            "endpoint": target.endpoint,
            "ring": target.ring,
        },
        "summary": {
            "selected": len(entries),
            "created": sum(
                1
                for item in results
                if item["status"].startswith("created")
            ),
            "wouldCreate": sum(
                1 for item in results if item["status"] == "would-create"
            ),
            "preserved": sum(
                1 for item in results if item["status"] == "preserved"
            ),
        },
        "topics": results,
    }


def offline_plan(entries: list[ManifestEntry]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "sourceCommit": source_commit(),
        "status": "offline-plan",
        "dryRun": True,
        "target": None,
        "summary": {
            "selected": len(entries),
            "created": 0,
            "wouldCreate": 0,
            "preserved": 0,
        },
        "topics": [
            {
                "order": entry.order,
                "category": entry.category,
                "name": entry.name,
                "displayName": entry.display_name,
                "schemaSuffix": entry.schema_suffix,
                "source": entry.source_relative_path,
                "sourceSha256": entry.source_sha256,
                "childDialogs": list(entry.child_dialogs),
                "status": "remote-state-not-checked",
            }
            for entry in entries
        ],
        "limitations": [
            "No agent or environment identity was validated.",
            "No duplicate or dependency inventory was read.",
            "No Microsoft Object Model conversion or remote write was attempted.",
        ],
    }


def _selected_scenarios(args: argparse.Namespace) -> tuple[str, ...]:
    if args.all:
        return ALL_SCENARIOS
    selected = tuple(args.topics or ())
    if not selected:
        raise InstallerError(
            "invalid-selection",
            "Select --all or pass one or more --topics names.",
        )
    return selected


def _json_print(value: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        ),
        file=stream,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--all",
        action="store_true",
        help=(
            "Select all 16 Workday scenarios; the shared setup topic is "
            "included unless --scenarios-only is passed."
        ),
    )
    selection.add_argument(
        "--topics",
        nargs="+",
        choices=ALL_SCENARIOS,
        help=(
            "Select scenario names; the shared setup topic is included first "
            "unless --scenarios-only is passed."
        ),
    )
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and validate the target, but do not write components.",
    )
    operation.add_argument(
        "--apply",
        action="store_true",
        help="Create only missing topics and verify each save.",
    )
    operation.add_argument(
        "--offline-plan",
        action="store_true",
        help="Validate only the local source manifest; no browser or API calls.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(".local/config.json"),
    )
    parser.add_argument("--environment-id")
    parser.add_argument("--agent-id")
    parser.add_argument("--agent-schema")
    parser.add_argument("--endpoint")
    parser.add_argument("--tenant")
    parser.add_argument("--cdp", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--page-url-contains")
    parser.add_argument(
        "--scenarios-only",
        action="store_true",
        help="Exclude the shared setup topic and install only selected scenarios.",
    )
    parser.add_argument(
        "--display-prefix",
        default="",
        help="Prefix applied to each installed topic display name.",
    )
    args = parser.parse_args(argv)

    target: Target | None = None
    try:
        entries = build_manifest(
            repository_root() / "samples" / "Workday",
            scenarios=_selected_scenarios(args),
            include_setup=not args.scenarios_only,
            display_prefix=args.display_prefix,
        )
        if args.offline_plan:
            _json_print(offline_plan(entries))
            return 0
        target = resolve_target(
            args.config,
            environment_id=args.environment_id,
            agent_id=args.agent_id,
            agent_schema=args.agent_schema,
            endpoint=args.endpoint,
            tenant=args.tenant,
        )
        validate_object_model_runtime()
        with BrowserMinimalBotTransport(
            target,
            cdp_endpoint=args.cdp,
            page_url_contains=args.page_url_contains,
        ) as transport:
            result = install_manifest(
                entries,
                target,
                transport,
                dry_run=not args.apply,
            )
        _json_print(result)
        return 0
    except InstallRunError as exc:
        _json_print(
            {
                "schemaVersion": 1,
                "sourceCommit": source_commit(),
                "status": "failed",
                "target": (
                    {
                        "environmentId": target.environment_id,
                        "agentId": target.agent_id,
                        "agentSchema": target.agent_schema,
                        "endpoint": target.endpoint,
                        "ring": target.ring,
                    }
                    if target is not None
                    else None
                ),
                "summary": {
                    "completedBeforeFailure": len(exc.results),
                    "created": sum(
                        1
                        for item in exc.results
                        if item["status"].startswith("created")
                    ),
                    "preserved": sum(
                        1
                        for item in exc.results
                        if item["status"] == "preserved"
                    ),
                },
                "topics": exc.results,
                "failedTopic": {
                    "order": exc.failed_entry.order,
                    "name": exc.failed_entry.name,
                    "displayName": exc.failed_entry.display_name,
                    "source": exc.failed_entry.source_relative_path,
                    "sourceSha256": exc.failed_entry.source_sha256,
                },
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                },
            },
            stream=sys.stderr,
        )
        return 2
    except (InstallerError, ObjectModelConverterError) as exc:
        code = getattr(exc, "code", "object-model-runtime")
        _json_print(
            {
                "schemaVersion": 1,
                "status": "failed",
                "error": {
                    "code": code,
                    "message": str(exc),
                },
            },
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
