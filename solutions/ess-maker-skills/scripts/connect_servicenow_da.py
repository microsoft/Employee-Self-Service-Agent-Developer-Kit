# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Connect the DA-GA HR agent to ServiceNow HRSD without Dataverse."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from connect_lifecycle import (
    STATE_INTEGRITY_KEY,
    STATE_TAMPERED_MESSAGE,
    decide_next_step,
    state_integrity_digest,
    state_integrity_mismatch,
)
import servicenow_connect_realms as realms
from agentbuilder import (
    AgentBuilderAccountMismatch,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    RING_CONFIG,
    authenticate,
    derive_environment_host,
    validate_environment_host,
)
from servicenow_connect_telemetry import (
    emit_lifecycle_event as emit_servicenow_lifecycle_event,
    prepare_lifecycle_projection,
)


SETUP_STATE = Path(".local/setup/config.json")
ACTIVE_CONFIG = Path(".local/config.json")
SOLUTION_ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_ID = "/providers/Microsoft.PowerApps/apis/shared_service-now"
CONNECTOR_NAME = "shared_service-now"
CONNECTIVITY_API_VERSION = "1"
CONNECTIVITY_READ_TIMEOUT_SECONDS = 60
SETUP_SCHEMA_VERSION = 4
HR_SCHEMA_NAME = "gptagent_copilotforemployeeselfservicehr"
IT_SCHEMA_NAME = "gptagent_copilotforemployeeselfserviceit"
TOKEN_CACHE = Path(".local/.agentbuilder_token_cache.bin")
LIFECYCLE_SCHEMA_VERSION = 13
CHECKPOINT_RESULT_STATUSES = frozenset(
    {
        "Passed",
        "Failed",
        "Blocked",
        "Warning",
        "NotConfigured",
        "Skipped",
        "Error",
        "Manual",
    }
)
ADMIN_SETUP_SCHEMA_VERSION = 4
AUTH_MODE = "entraIDUserLogin"
LEGACY_ENTRA_CHECKPOINT_SUFFIXES = (
    "APP",
    "CLAIMS",
    "SCOPE",
    "PREAUTH",
)
RETIRED_ENTRA_CHECKPOINT_SUFFIXES = (
    "PERMISSIONS",
    "CONSENT",
)
IDENTITY_RUNTIME_INSTRUCTION_PATHS = {
    "entra": Path(
        "src/skills/connect/shared/runtime-instructions/"
        "entra-administrator.md"
    ),
    "servicenow": Path(
        "src/skills/connect/shared/runtime-instructions/"
        "servicenow-administrator.md"
    ),
}
IDENTITY_REQUIREMENT_CHOICES = {
    "email": {
        "label": "Email",
        "category": "standard",
    },
    "upn": {
        "label": "UPN",
        "category": "standard",
    },
    "pay-employee-id": {
        "label": "Pay ID / employee ID",
        "category": "custom",
    },
    "other-non-email": {
        "label": "Other non-email identifier",
        "category": "custom",
    },
    "not-sure": {
        "label": "Not sure",
        "category": "unknown",
    },
}
PORTAL_ORIGINS = {
    "prod": {
        "powerAutomate": "https://make.powerautomate.com",
        "powerApps": "https://make.powerapps.com",
        "copilotStudio": "https://copilotstudio.microsoft.com",
    },
    "preprod": {
        "powerAutomate": "https://make.preprod.powerautomate.com",
        "powerApps": "https://make.preprod.powerapps.com",
        "copilotStudio": "https://copilotstudio.preprod.microsoft.com",
    },
    "test": {
        "powerAutomate": "https://make.test.powerautomate.com",
        "powerApps": "https://make.test.powerapps.com",
        "copilotStudio": "https://copilotstudio.test.microsoft.com",
    },
}


_SAFE_USER_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SAFE_IDENTITY_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,255}$")
_SAFE_AGENT_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ServiceNowProductProfile:
    key: str
    provider_key: str
    schema_name: str
    agent_display_name: str
    product_name: str
    portal_topic_suffix: str
    portal_node_display_name: str
    portal_variable_name: str
    connection_display_name: str
    test_prompt_category: str
    test_prompt: str
    requires_hr_core: bool
    admin_phases: frozenset[str]
    agent_names: tuple[str, ...]

    @property
    def contract_path(self) -> Path:
        return Path(f"src/skills/connect/{self.provider_key}/contract.json")


HRSD_PROFILE = ServiceNowProductProfile(
    key="hrsd",
    provider_key="servicenow-da-hrsd",
    schema_name=HR_SCHEMA_NAME,
    agent_display_name="Employee Self-Service (HR)",
    product_name="ServiceNow HRSD",
    portal_topic_suffix=".topic.ServiceNowHRSDSetupConfigurations",
    portal_node_display_name="Set ServiceNow Portal BaseURI",
    portal_variable_name="Global.ServiceNowHRSDPortalBaseURI",
    connection_display_name="ESS HR ServiceNow HRSD Connection",
    test_prompt_category="list-my-open-hr-cases",
    test_prompt="Show my open HR cases",
    requires_hr_core=True,
    admin_phases=frozenset(
        {
            "preflight",
            "plugin-prerequisites",
            "entra-registration",
            "servicenow-oidc",
            "credential",
        }
    ),
    agent_names=("Employee Self-Service HR", "Employee Self-Service (HR)"),
)

ITSM_PROFILE = ServiceNowProductProfile(
    key="itsm",
    provider_key="servicenow-da-itsm",
    schema_name=IT_SCHEMA_NAME,
    agent_display_name="Employee Self-Service (IT)",
    product_name="ServiceNow ITSM",
    portal_topic_suffix=".topic.ServiceNowITSMSetupConfigurations",
    portal_node_display_name="Set ServiceNow Portal Base URI",
    portal_variable_name="Global.ServiceNowITSMPortalBaseURI",
    connection_display_name="ESS IT ServiceNow ITSM Connection",
    test_prompt_category="list-my-open-it-tickets",
    test_prompt="Show my open IT tickets",
    requires_hr_core=False,
    admin_phases=frozenset(
        {
            "preflight",
            "entra-registration",
            "servicenow-oidc",
            "credential",
        }
    ),
    agent_names=("Employee Self-Service IT", "Employee Self-Service (IT)"),
)

PRODUCT_PROFILES = {
    HRSD_PROFILE.key: HRSD_PROFILE,
    ITSM_PROFILE.key: ITSM_PROFILE,
}
ACTIVE_PROFILE = HRSD_PROFILE
PROVIDER_KEY = ACTIVE_PROFILE.provider_key
PROFILE_KEY = ACTIVE_PROFILE.key
CONTRACT_PATH = ACTIVE_PROFILE.contract_path
AGENT_SCHEMA_NAME = ACTIVE_PROFILE.schema_name
PORTAL_TOPIC_SCHEMA_SUFFIX = ACTIVE_PROFILE.portal_topic_suffix
PORTAL_NODE_DISPLAY_NAME = ACTIVE_PROFILE.portal_node_display_name
PORTAL_VARIABLE_NAME = ACTIVE_PROFILE.portal_variable_name
ADMIN_PHASES = ACTIVE_PROFILE.admin_phases


def configure_product_profile(key: str) -> ServiceNowProductProfile:
    try:
        profile = PRODUCT_PROFILES[key]
    except KeyError as exc:
        raise ServiceNowConnectError(
            f"Unsupported ServiceNow product profile: {key!r}."
        ) from exc
    global ACTIVE_PROFILE
    global PROVIDER_KEY
    global PROFILE_KEY
    global CONTRACT_PATH
    global AGENT_SCHEMA_NAME
    global PORTAL_TOPIC_SCHEMA_SUFFIX
    global PORTAL_NODE_DISPLAY_NAME
    global PORTAL_VARIABLE_NAME
    global ADMIN_PHASES
    ACTIVE_PROFILE = profile
    PROVIDER_KEY = profile.provider_key
    PROFILE_KEY = profile.key
    CONTRACT_PATH = profile.contract_path
    AGENT_SCHEMA_NAME = profile.schema_name
    PORTAL_TOPIC_SCHEMA_SUFFIX = profile.portal_topic_suffix
    PORTAL_NODE_DISPLAY_NAME = profile.portal_node_display_name
    PORTAL_VARIABLE_NAME = profile.portal_variable_name
    ADMIN_PHASES = profile.admin_phases
    return profile


@contextmanager
def product_profile_context(key: str):
    previous = ACTIVE_PROFILE.key
    profile = configure_product_profile(key)
    try:
        yield profile
    finally:
        configure_product_profile(previous)


def product_profile_for_schema(
    schema_name: str,
) -> ServiceNowProductProfile | None:
    folded = schema_name.casefold()
    return next(
        (
            profile
            for profile in PRODUCT_PROFILES.values()
            if profile.schema_name.casefold() == folded
        ),
        None,
    )


def product_profile_for_provider(
    provider_key: str,
) -> ServiceNowProductProfile | None:
    return next(
        (
            profile
            for profile in PRODUCT_PROFILES.values()
            if profile.provider_key == provider_key
        ),
        None,
    )


def product_profile_for_name(
    display_name: str,
) -> ServiceNowProductProfile | None:
    folded = display_name.strip().casefold()
    return next(
        (
            profile
            for profile in PRODUCT_PROFILES.values()
            if any(name.casefold() == folded for name in profile.agent_names)
        ),
        None,
    )


class ServiceNowConnectError(RuntimeError):
    """Raised when the DA-GA ServiceNow prototype cannot proceed safely."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ServiceNowConnectError(f"Required file is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceNowConnectError(f"Could not read JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ServiceNowConnectError(f"Expected a JSON object in {path}.")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _create_json_atomic_no_clobber(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ServiceNowConnectError(
                "ServiceNow lifecycle state appeared during initialization; "
                "the existing state was preserved."
            ) from exc
        except OSError as exc:
            raise ServiceNowConnectError(
                "Could not publish the initial ServiceNow lifecycle state "
                "without replacing an existing file."
            ) from exc
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def normalize_client_id(value: str) -> str:
    try:
        return str(uuid.UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise ServiceNowConnectError(
            "Application client ID must be a GUID."
        ) from exc


def normalize_instance_name(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ServiceNowConnectError("ServiceNow instance name is required.")
    if "://" in candidate:
        parsed = urlparse(candidate)
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ServiceNowConnectError(
                "ServiceNow instance URL must be a plain HTTPS origin."
            )
        hostname = parsed.hostname or ""
    else:
        hostname = candidate.rstrip("/")
    suffix = ".service-now.com"
    if hostname.casefold().endswith(suffix):
        hostname = hostname[: -len(suffix)]
    if "." in hostname or not re.fullmatch(r"[A-Za-z0-9-]+", hostname):
        raise ServiceNowConnectError(
            "ServiceNow instance must be an instance name or a "
            "https://<instance>.service-now.com URL."
        )
    return hostname.casefold()


def maker_portal_links(
    context: dict[str, Any],
    *,
    instance_name: str | None = None,
) -> dict[str, dict[str, str]]:
    ring = str(context["environment"].get("ring") or "")
    origins = PORTAL_ORIGINS.get(ring)
    if origins is None:
        raise ServiceNowConnectError(
            f"Unsupported Power Platform ring for maker links: {ring!r}."
        )
    environment_id = str(uuid.UUID(context["environment"]["id"]))
    agent_id = str(uuid.UUID(context["agent"]["id"]))
    links = {
        "entra": {
            "label": "Open Microsoft Entra admin center",
            "url": "https://entra.microsoft.com/",
        },
        "powerAutomateConnections": {
            "label": "Open connections for this environment",
            "url": (
                f"{origins['powerAutomate']}/environments/"
                f"{environment_id}/connections"
            ),
        },
        "powerApps": {
            "label": "Open Power Apps",
            "url": f"{origins['powerApps']}/",
        },
        "copilotStudioAgent": {
            "label": (
                f"Open {_spec_agent_name()} in Copilot Studio"
            ),
            "url": (
                f"{origins['copilotStudio']}/environments/{environment_id}/"
                f"copilots/{agent_id}/details?agentBackend=cosmos"
            ),
        },
    }
    if instance_name:
        normalized_instance = normalize_instance_name(instance_name)
        links["serviceNowInstance"] = {
            "label": "Open this ServiceNow instance",
            "url": f"https://{normalized_instance}.service-now.com/",
        }
        if ACTIVE_PROFILE.requires_hr_core:
            links["hrCorePlugin"] = {
                "label": "Open HR Service Delivery Core",
                "url": (
                    f"https://{normalized_instance}.service-now.com/now/"
                    "app-manager/home/plugin/id/com.sn_hr_core/details"
                ),
            }
    return links


def connection_expected_values(
    *,
    resource_uri: str | None,
    instance_name: str | None,
    display_name: str | None = None,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if display_name:
        values.append(
            {
                "field": "displayName",
                "label": "Display name (optional)",
                "value": display_name,
            }
        )
    values.extend(
        [
            {
                "field": "authenticationType",
                "label": "Authentication Type",
                "value": "Microsoft Entra ID User Login",
                "technicalValue": AUTH_MODE,
            },
            {
                "field": "resourceUri",
                "label": "Resource URI",
                "value": resource_uri,
                "description": (
                    "Verified resource Application client ID; never an "
                    "object ID, ADK client ID, connector app ID, or api:// URI."
                ),
            },
            {
                "field": "instanceName",
                "label": "Instance Name",
                "value": instance_name,
                "description": "ServiceNow instance name only, not a URL.",
            },
        ]
    )
    return values


def _render_connection_expected_values(
    *,
    resource_uri: str | None,
    instance_name: str | None,
    display_name: str | None = None,
) -> str:
    rendered = []
    for item in connection_expected_values(
        display_name=display_name,
        resource_uri=resource_uri,
        instance_name=instance_name,
    ):
        value = item.get("value")
        rendered.append(
            f"- {item['label']}: "
            + (f"`{value}`" if value else "not yet confirmed")
        )
    return "\n".join(rendered)


def physical_connection_navigation(
    context: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    if mode not in {"create", "repair"}:
        raise ServiceNowConnectError(
            "Physical connection navigation mode must be create or repair."
        )
    links = maker_portal_links(context)
    return {
        "mode": mode,
        "environmentId": context["environment"]["id"],
        "url": links["powerAutomateConnections"]["url"],
        "surface": "selected-environment-connections-list",
        "directServiceNowFormRoute": "unknown",
        "fallbackUsed": True,
        "automaticCreate": False,
        "automaticSignIn": False,
        "automaticSubmit": False,
        "instruction": (
            "Open the selected environment's Connections list. "
            + (
                "Choose New connection, search for the Microsoft-published "
                "ServiceNow connector, and open its standard form."
                if mode == "create"
                else "Open the exact discovered candidate and use its "
                "available Repair, Fix connection, or sign-in action."
            )
            + " The direct connector form/detail route is not verified, so "
            "the kit does not construct or claim one."
        ),
    }


def required_servicenow_prerequisites(
    scope: str,
    auth_mode: str = AUTH_MODE,
) -> list[dict[str, Any]]:
    normalized_scope = scope.strip().casefold()
    if normalized_scope not in {"hrsd", "itsm"}:
        raise ServiceNowConnectError(
            "ServiceNow scope must be hrsd or itsm."
        )
    if auth_mode != AUTH_MODE:
        raise ServiceNowConnectError(
            "Only Microsoft Entra ID User Login is supported."
        )
    requirements: list[dict[str, Any]] = []
    if normalized_scope == "hrsd":
        requirements.append(
            {
                "id": "hr-core",
                "aliases": ["com.sn_hr_core", "sn_hr_core"],
                "requiredFor": ["hrsd"],
            }
        )
    return requirements


def _empty_admin_setup() -> dict[str, Any]:
    return {
        "schemaVersion": ADMIN_SETUP_SCHEMA_VERSION,
        "scope": PROFILE_KEY,
        "authMode": AUTH_MODE,
        "preflight": {
            "discovery": {},
        },
        "phaseHandoffs": {
            phase: {"status": "pending"}
            for phase in sorted(ADMIN_PHASES)
        },
    }


def _legacy_oidc_handoff_proves_capability(
    handoff: object,
) -> bool:
    if not isinstance(handoff, dict):
        return False
    evidence = handoff.get("evidence")
    return bool(
        handoff.get("status") in {"completed", "reused"}
        and isinstance(evidence, dict)
        and evidence.get("kind") == "structured-admin-attestation"
        and isinstance(evidence.get("recordedAt"), str)
        and evidence.get("recordedAt")
        and evidence.get("claim")
        and evidence.get("userField")
    )


def _legacy_oidc_handoff_proves_completion(
    handoff: object,
) -> bool:
    return bool(
        _legacy_oidc_handoff_proves_capability(handoff)
        or (
            isinstance(handoff, dict)
            and handoff.get("status") in {"completed", "reused"}
            and isinstance(handoff.get("evidence"), dict)
            and handoff["evidence"].get("kind")
            == "structured-admin-attestation"
            and isinstance(handoff["evidence"].get("recordedAt"), str)
            and handoff["evidence"].get("recordedAt")
            and handoff["evidence"].get("runbookCompleted") is True
            and handoff["evidence"].get("oidcCapabilityConfirmed") is True
        )
    )


def _admin_setup(state: dict[str, Any]) -> dict[str, Any]:
    setup = state.setdefault("adminSetup", _empty_admin_setup())
    if not isinstance(setup, dict):
        raise ServiceNowConnectError(
            "ServiceNow admin setup state must be an object."
        )
    version = setup.get("schemaVersion", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ServiceNowConnectError(
            "ServiceNow admin setup schemaVersion must be an integer."
        )
    if version > ADMIN_SETUP_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            "ServiceNow admin setup state was written by a newer kit version."
        )
    setup["schemaVersion"] = ADMIN_SETUP_SCHEMA_VERSION
    setup.setdefault("scope", PROFILE_KEY)
    setup.setdefault("authMode", AUTH_MODE)
    preflight = setup.setdefault("preflight", {})
    if not isinstance(preflight, dict):
        raise ServiceNowConnectError(
            "ServiceNow preflight state must be an object."
        )
    preflight.pop("scenario", None)
    preflight.pop("reuseDecision", None)
    discovery = preflight.setdefault("discovery", {})
    if not isinstance(discovery, dict):
        raise ServiceNowConnectError(
            "ServiceNow preflight discovery state must be an object."
        )
    discovery.pop("fingerprint", None)
    handoffs = setup.setdefault("phaseHandoffs", {})
    if not isinstance(handoffs, dict):
        raise ServiceNowConnectError(
            "ServiceNow admin phase handoffs must be an object."
        )
    for phase in sorted(ADMIN_PHASES):
        handoffs.setdefault(phase, {"status": "pending"})
    oidc_handoff = handoffs.get("servicenow-oidc")
    if version < 4 and isinstance(oidc_handoff, dict):
        oidc_evidence = oidc_handoff.get("evidence")
        qualified_completion = _legacy_oidc_handoff_proves_completion(
            oidc_handoff
        )
        if isinstance(oidc_evidence, dict) and qualified_completion:
            oidc_evidence["oidcCapabilityConfirmed"] = True
            oidc_evidence["runbookCompleted"] = True
            oidc_evidence["mappingDetailsCollected"] = False
            oidc_evidence.pop("claim", None)
            oidc_evidence.pop("userField", None)
        elif isinstance(oidc_evidence, dict) and (
            "claim" in oidc_evidence or "userField" in oidc_evidence
        ):
            state.setdefault("migration", {})[
                "retiredOidcMappingEvidence"
            ] = {
                "sourceSha256": _canonical_json_hash(oidc_evidence),
                "qualifiedCompletion": False,
                "retiredAt": _utc_now(),
            }
            handoffs["servicenow-oidc"] = {"status": "pending"}
    preflight_handoff = handoffs.get("preflight")
    if isinstance(preflight_handoff, dict):
        evidence = preflight_handoff.get("evidence")
        if isinstance(evidence, dict):
            evidence.pop("decision", None)
            evidence.pop("discoveryFingerprint", None)
            if evidence.get("kind") == "maker-reuse-decision":
                evidence["kind"] = "read-only-resource-discovery"
    return setup


def _required_context_identity(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, str]:
    environment = context.get("environment")
    if not isinstance(environment, dict):
        raise ServiceNowConnectError(
            "The active ServiceNow context has no environment identity."
        )
    tenant_id = environment.get("tenant_id")
    environment_id = environment.get("id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ServiceNowConnectError(
            "The active ServiceNow context has no tenant identity."
        )
    if not isinstance(environment_id, str) or not environment_id:
        raise ServiceNowConnectError(
            "The active ServiceNow context has no environment ID."
        )
    setup = _admin_setup(state)
    preflight = setup.get("preflight")
    instance_name = (
        preflight.get("instanceName")
        if isinstance(preflight, dict)
        else None
    )
    if not isinstance(instance_name, str) or not instance_name:
        raise ServiceNowConnectError(
            "Confirm the ServiceNow instance before importing identity "
            "mapping evidence."
        )
    return {
        "tenantId": str(uuid.UUID(tenant_id)),
        "environmentId": str(uuid.UUID(environment_id)),
        "instanceName": normalize_instance_name(instance_name),
    }


def _safe_identity_name(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_IDENTITY_NAME.fullmatch(text):
        raise ServiceNowConnectError(
            f"{label} must be an explicit non-secret attribute or claim name."
        )
    return text


def _identity_requirement_binding(
    context: dict[str, Any],
    expected_identity: dict[str, str],
) -> dict[str, str]:
    return {
        **expected_identity,
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": str(context["agent"]["id"]),
    }


def _identity_requirement_hash(receipt: dict[str, Any]) -> str:
    binding = receipt.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    return _canonical_json_hash(
        {
            "choice": receipt.get("choice"),
            "category": receipt.get("category"),
            "tenantId": binding.get("tenantId"),
            "environmentId": binding.get("environmentId"),
            "instanceName": binding.get("instanceName"),
            "provider": binding.get("provider"),
            "profile": binding.get("profile"),
            "agentSlug": binding.get("agentSlug"),
            "agentId": binding.get("agentId"),
        }
    )


def _validated_identity_requirement(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    raw = state.get("evidence", {}).get("identityRequirement")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ServiceNowConnectError(
            "The saved ServiceNow identity requirement is invalid."
        )
    choice = str(raw.get("choice") or "")
    choice_config = IDENTITY_REQUIREMENT_CHOICES.get(choice)
    if choice_config is None or choice == "not-sure":
        raise ServiceNowConnectError(
            "The saved ServiceNow identity requirement choice is invalid."
        )
    if raw.get("category") != choice_config["category"]:
        raise ServiceNowConnectError(
            "The saved ServiceNow identity requirement category changed."
        )
    expected_identity = _required_context_identity(context, state)
    expected_binding = _identity_requirement_binding(
        context,
        expected_identity,
    )
    if raw.get("binding") != expected_binding:
        raise ServiceNowConnectError(
            "The saved ServiceNow identity requirement does not match the "
            "active tenant, environment, agent, or instance."
        )
    if raw.get("requirementSha256") != _identity_requirement_hash(raw):
        raise ServiceNowConnectError(
            "The saved ServiceNow identity requirement hash is stale."
        )
    return copy.deepcopy(raw)


def _native_question(
    *,
    header: str,
    question: str,
    option_labels: list[str] | None = None,
    allow_freeform_input: bool = False,
) -> dict[str, Any]:
    if not header.strip() or not question.strip():
        raise ServiceNowConnectError(
            "Native question header and body must both be non-empty."
        )
    payload: dict[str, Any] = {
        "header": header,
        "question": question,
        "allowFreeformInput": allow_freeform_input,
    }
    if option_labels is not None:
        if allow_freeform_input or len(option_labels) < 2 or any(
            not isinstance(label, str) or not label.strip()
            for label in option_labels
        ):
            raise ServiceNowConnectError(
                "Native question options are invalid."
            )
        payload["options"] = [
            {"label": label}
            for label in option_labels
        ]
    return payload


def adapt_question_to_ask_user(
    question: dict[str, Any],
) -> dict[str, Any]:
    canonical = copy.deepcopy(question)
    header = canonical.get("header")
    body = canonical.get("question")
    allow_freeform = canonical.get("allowFreeformInput")
    options = canonical.get("options")
    if not isinstance(header, str) or not header.strip():
        raise ServiceNowConnectError(
            "Canonical question header must be a non-empty string."
        )
    if not isinstance(body, str) or not body.strip():
        raise ServiceNowConnectError(
            "Canonical question body must be a non-empty string."
        )
    if not isinstance(allow_freeform, bool):
        raise ServiceNowConnectError(
            "Canonical question allowFreeformInput must be boolean."
        )
    if options is None:
        normalized_options: list[dict[str, str]] = []
    elif isinstance(options, list):
        normalized_options = []
        seen_values: set[str] = set()
        for option in options:
            if not isinstance(option, dict):
                raise ServiceNowConnectError(
                    "Canonical question options must be objects."
                )
            label = option.get("label")
            value = option.get("selectionKey", label)
            if (
                not isinstance(label, str)
                or not label.strip()
                or not isinstance(value, str)
                or not value.strip()
                or value in seen_values
            ):
                raise ServiceNowConnectError(
                    "Canonical question options must have unique non-empty "
                    "labels and values."
                )
            seen_values.add(value)
            normalized_options.append(
                {
                    "const": value,
                    "title": label,
                }
            )
    else:
        raise ServiceNowConnectError(
            "Canonical question options must be a list when present."
        )
    if normalized_options and allow_freeform:
        raise ServiceNowConnectError(
            "The active ask_user_2 contract cannot faithfully combine "
            "bounded options with canonical freeform input."
        )
    if not normalized_options and not allow_freeform:
        raise ServiceNowConnectError(
            "A canonical question without options must allow freeform input."
        )

    # The card title is the question itself. The explanation (`question`) is
    # sent as the agent's chat response, never repeated inside the card.
    field: dict[str, Any] = {
        "type": "string",
        "title": "Selection" if normalized_options else "Input",
    }
    if normalized_options:
        field["oneOf"] = normalized_options
    requested_schema = {
        "properties": {
            "response": field,
        },
        "required": ["response"],
    }
    return {
        "schemaVersion": "servicenow.ask-user-arguments.v1",
        "canonicalQuestion": canonical,
        "answerField": "response",
        "canonicalAllowFreeformInput": allow_freeform,
        "askUserArguments": {
            "message": header,
            "requestedSchema": requested_schema,
        },
        "knownHostLimitation": (
            "The active ask_user_2 schema has no freeform-control field. "
            "Agent Host currently exposes and accepts custom enum answers "
            "despite canonical allowFreeformInput=false."
            if normalized_options and not allow_freeform
            else None
        ),
    }


def _identity_direct_questions(
    stage: str,
    *,
    captured_client_id: str | None = None,
    confirmed_claim_name: str | None = None,
    captured_user_field: str | None = None,
) -> list[dict[str, Any]]:
    if stage == "entra":
        canonical = [
            _native_question(
                header="What did your Entra administrator reply?",
                question=(
                    "Paste your Entra administrator's non-sensitive reply, "
                    "including the Application (client) ID. If it names the "
                    "claim ServiceNow should use, or says the standard email "
                    "claim applies, we'll use that; otherwise we'll ask for "
                    "the claim name next."
                ),
                allow_freeform_input=True,
            ),
        ]
        if captured_client_id is not None:
            normalize_client_id(captured_client_id)
            canonical = [
                _native_question(
                    header="Which claim name did your Entra administrator confirm?",
                    question=(
                        "We have the Client ID. Next, we need the exact "
                        "claim name your Entra administrator configured for "
                        "ServiceNow to use (`email`, `upn`, or a custom "
                        "claim name).\n\n"
                        "Ask your Entra administrator for that name, or paste "
                        "the rest of their non-sensitive reply. You don't "
                        "need to resend the Client ID."
                    ),
                    allow_freeform_input=True,
                )
            ]
    elif stage == "servicenow":
        if not confirmed_claim_name:
            raise ServiceNowConnectError(
                "ServiceNow direct questions require the locked "
                "Entra-confirmed User Claim name."
            )
        if captured_user_field is None:
            canonical = [
                _native_question(
                    header="Which User Field did your administrator select?",
                    question=(
                        "Ask your administrator which **User Field** they "
                        "selected. Send that value on its own."
                    ),
                    allow_freeform_input=True,
                )
            ]
        else:
            user_field = str(captured_user_field).strip()
            if not _SAFE_USER_FIELD.fullmatch(user_field):
                raise ServiceNowConnectError(
                    "servicenow_user_field must be an explicit safe "
                    "ServiceNow internal field name."
                )
            canonical = []
    else:
        raise ServiceNowConnectError(
            "Identity direct handoff stage must be entra or servicenow."
        )
    return [
        {
            "canonicalQuestion": question,
            "askUserArguments": adapt_question_to_ask_user(question)[
                "askUserArguments"
            ],
        }
        for question in canonical
    ]


def _identity_direct_group(
    context: dict[str, Any],
    *,
    stage: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    phase_id = (
        "entra-registration" if stage == "entra" else "servicenow-oidc"
    )
    contract = _load_json(SOLUTION_ROOT / CONTRACT_PATH)
    group = next(
        (
            candidate
            for candidate in _business_groups(contract)
            if phase_id in candidate["phaseIds"]
        ),
        None,
    )
    if not isinstance(group, dict):
        raise ServiceNowConnectError(
            "The identity administrator business group is missing."
        )
    return contract, group


def _normalize_directory_tenant_id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ServiceNowConnectError(
            "Directory tenant ID must be a GUID."
        ) from exc


def _identity_runtime_instruction_source(
    stage: str,
) -> tuple[Path, str, str]:
    relative_path = IDENTITY_RUNTIME_INSTRUCTION_PATHS.get(stage)
    if relative_path is None:
        raise ServiceNowConnectError(
            "Identity runtime instruction stage is invalid."
        )
    path = SOLUTION_ROOT / relative_path
    if not path.is_file():
        raise ServiceNowConnectError(
            f"Required identity runtime instruction is missing: {path}"
        )
    raw = path.read_text(encoding="utf-8")
    normalized = raw.replace("\u00a0", " ").replace("\r\n", "\n").strip()
    return (
        relative_path,
        normalized,
        hashlib.sha256(normalized.encode("utf-8")).hexdigest().upper(),
    )


def _ready_to_send_block(body: str) -> str:
    longest_run = max(
        (len(run) for run in re.findall(r"`+", body)),
        default=0,
    )
    fence = "`" * max(3, longest_run + 1)
    return f"**Ready-to-send message**\n{fence}text\n{body}\n{fence}"


def _identity_handoff_lead_in(stage: str) -> str:
    if stage == "entra":
        prerequisite = (
            "The HR prerequisite is confirmed. Next, send"
            if ACTIVE_PROFILE.requires_hr_core
            else "Next, send"
        )
        return (
            f"{prerequisite} this message to your Microsoft Entra "
            "administrator to prepare ServiceNow sign-in.\n\n"
            "When they reply, paste their response here without secrets. "
            "We'll use it to prepare the ServiceNow handoff; you don't need "
            "to interpret the settings."
        )
    return (
        "We have the Entra values. Send this message to your ServiceNow "
        "administrator to set up employee matching.\n\n"
        "It includes the values already supplied. When they reply, paste "
        "their saved-configuration confirmation, **User Claim**, and "
        "**User Field** here without secrets."
    )


def _render_identity_runtime_instruction(
    context: dict[str, Any],
    *,
    stage: str,
    application_client_id: str | None = None,
    claim_name: str | None = None,
) -> tuple[str, str, str]:
    relative_path, text, source_sha256 = (
        _identity_runtime_instruction_source(stage)
    )
    if stage == "entra":
        return text, str(relative_path), source_sha256
    if not application_client_id or not claim_name:
        raise ServiceNowConnectError(
            "ServiceNow runtime instructions require the current confirmed "
            "Application client ID and User Claim name."
        )
    state = _load_lifecycle_state(context)
    identity = _required_context_identity(context, state)
    tenant_id = _normalize_directory_tenant_id(identity["tenantId"])
    instance_name = normalize_instance_name(identity["instanceName"])
    rendered = (
        text.replace("<client ID>", application_client_id)
        .replace("<tenant ID>", tenant_id)
        .replace("<instance>", instance_name)
        .replace("<claim>", claim_name)
    )
    if ACTIVE_PROFILE.key != "hrsd":
        rendered = re.sub(
            r"(?m)^8\. \*\*HR agent only:\*\*.*(?:\n|$)",
            "",
            rendered,
        ).rstrip()
    if any(
        placeholder in rendered
        for placeholder in (
            "<client ID>",
            "<tenant ID>",
            "<instance>",
            "<claim>",
        )
    ):
        raise ServiceNowConnectError(
            "ServiceNow runtime instruction placeholders were not resolved."
        )
    return rendered, str(relative_path), source_sha256


def identity_direct_handoff(
    context: dict[str, Any],
    *,
    stage: str,
    captured_client_id: str | None = None,
    captured_user_field: str | None = None,
) -> dict[str, Any]:
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError(
            "Identity direct handoff stage is invalid."
        )
    if stage != "entra" and captured_client_id is not None:
        raise ServiceNowConnectError(
            "Current-turn Client ID retention is supported only for the "
            "Entra direct handoff."
        )
    if stage != "servicenow" and captured_user_field is not None:
        raise ServiceNowConnectError(
            "Current-turn User Field retention is supported only for the "
            "ServiceNow direct handoff."
        )
    state = _load_lifecycle_state(context)
    phase = (
        "entra-registration" if stage == "entra" else "servicenow-oidc"
    )
    if _identity_admin_handoff_is_ready(
        context,
        state,
        phase=phase,
    ):
        return {
            "schemaVersion": "servicenow.identity-direct-handoff.v1",
            "stage": stage,
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "decision": "no-action",
            "ordinaryReply": None,
            "availability": {
                "required": False,
                "acknowledged": False,
                "reason": "current-completed-or-reused-evidence",
                "question": None,
                "askUserArguments": None,
            },
            "questions": [],
            "secretsAccepted": False,
            "employeeValuesAccepted": False,
            "remoteMutationCount": 0,
        }
    contract, group = _identity_direct_group(context, stage=stage)
    group_context = _business_group_context(context, contract, group)
    context_sha256 = _canonical_json_hash(group_context)
    availability_current = _business_group_acknowledgement_current(
        state,
        group=group,
        context_sha256=context_sha256,
    )
    if not availability_current:
        question = _business_group_availability_question(group)
        return {
            "schemaVersion": "servicenow.identity-direct-handoff.v1",
            "stage": stage,
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "decision": "availability-required",
            "ordinaryReply": None,
            "availability": {
                "required": True,
                "acknowledged": False,
                "businessGroupId": group["id"],
                "contextIdentity": group_context,
                "contextIdentitySha256": context_sha256,
                "question": question,
                "questionSha256": _canonical_json_hash(question),
                "askUserArguments": adapt_question_to_ask_user(question)[
                    "askUserArguments"
                ],
                "unavailableReply": (
                    f"Please involve your {group['role']} for "
                    f"{group['label']}, then answer the same question again."
                    "\n\nNo business group, lifecycle phase, evidence, "
                    "attestation, or accepted contract revision has advanced."
                ),
            },
            "questions": [],
            "secretsAccepted": False,
            "employeeValuesAccepted": False,
            "remoteMutationCount": 0,
        }
    expected_identity = _required_context_identity(context, state)
    candidate_receipt = None
    if stage == "entra":
        source_text, instruction_path, instruction_sha256 = (
            _render_identity_runtime_instruction(
                context,
                stage="entra",
            )
        )
        locked_values = None
        contract_boundary = (
            "The Manual Entra identity phase completes only from one valid "
            "Application client ID GUID and one explicit safe User Claim name "
            "with current target binding, provenance, and hashes. This does "
            "not prove app configuration, claim emission, scope, "
            "pre-authorization, a real token, authentication, permission, or "
            "a business result."
        )
    else:
        candidate_receipt = _validated_claim_candidates(context, state)
        candidates = list(candidate_receipt.get("candidates") or [])
        if len(candidates) != 1:
            raise ServiceNowConnectError(
                "Direct ServiceNow capture requires exactly one current "
                "Entra-confirmed User Claim name."
            )
        client_id = normalize_client_id(
            str(candidate_receipt.get("applicationClientId") or "")
        )
        claim_name = _safe_identity_name(
            candidates[0],
            "confirmed_user_claim_name",
        )
        source_text, instruction_path, instruction_sha256 = (
            _render_identity_runtime_instruction(
                context,
                stage="servicenow",
                application_client_id=client_id,
                claim_name=claim_name,
            )
        )
        locked_values = {
            "applicationClientId": client_id,
            "directoryTenantId": expected_identity["tenantId"],
            "selectedClaimName": claim_name,
        }
        contract_boundary = (
            "Completion remains Manual evidence. It requires the exact "
            "saved configuration and locked claim-to-field mapping for the "
            "current target. It does not prove a real token, authentication, "
            "permission, Active-user match, or business result."
        )
    existing_kind = _existing_identity_kind(state)
    packet_text = source_text
    lead_in = _identity_handoff_lead_in(stage)
    if existing_kind:
        instance_for_packet = normalize_instance_name(
            expected_identity["instanceName"]
        )
        if stage == "entra":
            packet_text = _existing_entra_packet(
                context, existing_kind, instance_for_packet
            )
        else:
            packet_text = _existing_servicenow_packet(
                context,
                existing_kind,
                instance_name=instance_for_packet,
                client_id=client_id,
                tenant_id=_normalize_directory_tenant_id(
                    expected_identity["tenantId"]
                ),
                claim_name=claim_name,
            )
        lead_in = _existing_identity_lead_in(
            stage,
            existing_kind,
            claim_name=claim_name if stage == "servicenow" else None,
        )
    elif second_agent := _second_agent_reuse(context, state):
        instance_for_packet = normalize_instance_name(
            expected_identity["instanceName"]
        )
        if stage == "entra":
            packet_text = _second_agent_entra_packet(
                context, second_agent, instance_for_packet
            )
            lead_in = _second_agent_entra_lead_in(second_agent)
        else:
            packet_text = _second_agent_servicenow_packet(
                context,
                second_agent,
                instance_name=instance_for_packet,
                client_id=client_id,
                tenant_id=_normalize_directory_tenant_id(
                    expected_identity["tenantId"]
                ),
                claim_name=claim_name,
            )
            lead_in = _second_agent_servicenow_lead_in(
                second_agent, claim_name
            )
    target_text = (
        f"Target agent: `{_agent_slug(context)}` "
        f"(`{context['agent']['id']}`)\n"
        f"Tenant: `{context['environment'].get('tenant_id')}`\n"
        f"Environment: `{context['environment']['id']}`\n"
        f"ServiceNow instance: `{expected_identity['instanceName']}`"
    )
    return {
        "schemaVersion": "servicenow.identity-direct-handoff.v1",
        "stage": stage,
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "decision": "instructions-required",
        "runtimeInstructionPath": instruction_path,
        "runtimeInstructionSha256": instruction_sha256,
        "runtimeInstructionContentSha256": _canonical_json_hash(source_text),
        "ordinaryReply": (
            None
            if captured_client_id is not None
            else {
                "kind": "ordinary-agent-response",
                "text": _existing_identity_message(
                    context, state, existing_kind, "servicenow-incomplete"
                )[0]
                if existing_kind
                else (
                    "Thanks—please ask your ServiceNow administrator to "
                    "confirm that the configuration is saved and name both "
                    "the **User Claim** and **User Field**.\n\n"
                    "That will clarify which settings use "
                    f"`{claim_name}` to identify the signed-in employee."
                ),
            }
            if captured_user_field is not None
            else {
                "kind": "ordinary-agent-response",
                "text": (
                    f"{lead_in}\n\n{_ready_to_send_block(packet_text)}"
                ),
            }
        ),
        "availability": {
            "required": False,
            "acknowledged": True,
            "businessGroupId": group["id"],
            "contextIdentity": group_context,
            "contextIdentitySha256": context_sha256,
            "question": None,
            "askUserArguments": None,
        },
        "target": target_text,
        "contractBoundary": contract_boundary,
        "lockedValues": locked_values,
        "retainedDirectInput": (
            {
                "applicationClientId": normalize_client_id(
                    captured_client_id
                )
            }
            if stage == "entra" and captured_client_id is not None
            else {
                "serviceNowUserField": str(captured_user_field).strip()
            }
            if stage == "servicenow" and captured_user_field is not None
            else None
        ),
        "questions": _identity_direct_questions(
            stage,
            captured_client_id=captured_client_id,
            confirmed_claim_name=(
                claim_name if stage == "servicenow" else None
            ),
            captured_user_field=captured_user_field,
        ),
        "secretsAccepted": False,
        "employeeValuesAccepted": False,
        "remoteMutationCount": 0,
    }


def record_identity_requirement(
    context: dict[str, Any],
    *,
    choice: str,
) -> dict[str, Any]:
    choice_config = IDENTITY_REQUIREMENT_CHOICES.get(choice)
    if choice_config is None:
        raise ServiceNowConnectError(
            "Unsupported ServiceNow identity requirement choice."
        )
    if choice == "not-sure":
        return {
            "status": "waiting",
            "recorded": False,
            "choice": choice,
            "guidance": (
                "Ask the Entra or ServiceNow administrator which identifier "
                "type should match the ServiceNow user. Do not provide or "
                "record an employee value."
            ),
        }
    state = _load_lifecycle_state(context)
    expected_identity = _required_context_identity(context, state)
    existing = _validated_identity_requirement(context, state)
    if existing is not None:
        if existing.get("choice") == choice:
            return existing
        raise ServiceNowConnectError(
            "A different ServiceNow identity requirement is already confirmed "
            "for this tenant, environment, agent, and instance. The choice is "
            "immutable for this lifecycle; start an explicit fresh "
            "lifecycle before changing it."
        )
    receipt = {
        "kind": "maker-confirmed-identity-routing",
        "status": "confirmed",
        "choice": choice,
        "label": choice_config["label"],
        "category": choice_config["category"],
        "binding": _identity_requirement_binding(
            context,
            expected_identity,
        ),
        "recordedAt": _utc_now(),
    }
    receipt["requirementSha256"] = _identity_requirement_hash(receipt)
    state.setdefault("evidence", {})["identityRequirement"] = receipt
    _write_lifecycle_state(context, state)
    return copy.deepcopy(receipt)


def _known_entra_client_id(
    state: dict[str, Any],
) -> str | None:
    handoff = _admin_setup(state).get("phaseHandoffs", {}).get(
        "entra-registration"
    )
    evidence = handoff.get("evidence") if isinstance(handoff, dict) else None
    raw_client_id = (
        evidence.get("clientId") if isinstance(evidence, dict) else None
    )
    if not raw_client_id:
        return None
    try:
        return normalize_client_id(str(raw_client_id))
    except ServiceNowConnectError:
        return None


def _entra_checkpoint_outcomes(
    state: dict[str, Any],
) -> dict[str, str]:
    phase = state.get("phases", {}).get("entra-registration")
    results = phase.get("checkpointResults") if isinstance(phase, dict) else None
    if not isinstance(results, dict):
        return {}
    return {
        str(checkpoint_id).rsplit("-", 2)[-2]: status
        for checkpoint_id, status in results.items()
        if isinstance(checkpoint_id, str)
        and checkpoint_id.endswith("-001")
        and isinstance(status, str)
    }


def _entra_setup_checkpoint_id() -> str:
    profile = "HRSD" if ACTIVE_PROFILE.key == "hrsd" else "ITSM"
    return f"SN-DA-{profile}-ENTRA-SETUP-001"


def _legacy_entra_checkpoint_outcomes(
    state: dict[str, Any],
) -> dict[str, str]:
    outcomes = {
        suffix: status
        for suffix, status in _entra_checkpoint_outcomes(state).items()
        if suffix in LEGACY_ENTRA_CHECKPOINT_SUFFIXES
    }
    retired = state.get("retiredCheckpointResults")
    retired = retired if isinstance(retired, dict) else {}
    entra = retired.get("entra-registration")
    entra = entra if isinstance(entra, dict) else {}
    for checkpoint_id, record in entra.items():
        if not isinstance(checkpoint_id, str):
            continue
        suffix = checkpoint_id.rsplit("-", 2)[-2]
        if suffix not in LEGACY_ENTRA_CHECKPOINT_SUFFIXES:
            continue
        if isinstance(record, dict):
            status = record.get("status")
        else:
            status = record
        if isinstance(status, str):
            outcomes.setdefault(suffix, status)
    return outcomes


def _has_historical_entra_graph_pass(
    state: dict[str, Any],
) -> bool:
    outcomes = _legacy_entra_checkpoint_outcomes(state)
    return all(
        outcomes.get(suffix) == "Passed"
        for suffix in LEGACY_ENTRA_CHECKPOINT_SUFFIXES
    )


def _identity_mapping_relationship_hash(
    mapping: dict[str, Any],
) -> str:
    binding = mapping.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    return _canonical_json_hash(
        {
            "applicationClientId": mapping.get("applicationClientId"),
            "tokenClaimName": mapping.get("tokenClaimName"),
            "serviceNowUserField": mapping.get("serviceNowUserField"),
            "candidateSetSha256": mapping.get("candidateSetSha256"),
            "tenantId": binding.get("tenantId"),
            "environmentId": binding.get("environmentId"),
            "instanceName": binding.get("instanceName"),
            "provider": binding.get("provider"),
            "profile": binding.get("profile"),
            "agentSlug": binding.get("agentSlug"),
            "agentId": binding.get("agentId"),
        }
    )


def _invalidate_oidc_handoff(state: dict[str, Any]) -> None:
    setup = _admin_setup(state)
    setup["phaseHandoffs"]["servicenow-oidc"] = {"status": "pending"}
    phase = state.setdefault("phases", {}).setdefault(
        "servicenow-oidc",
        {
            "status": "pending",
            "checkpointResults": {},
            "checkpointAcknowledgements": {},
        },
    )
    if not isinstance(phase, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle phase servicenow-oidc must be an object."
        )
    phase["status"] = "pending"
    phase["checkpointResults"] = {}
    phase["checkpointAcknowledgements"] = {}
    for key in (
        "actionApplied",
        "lastActionAt",
        "lastVerifiedAt",
        "rollbackPushGlob",
    ):
        phase.pop(key, None)


def _invalidate_identity_mapping_handoffs(
    state: dict[str, Any],
) -> None:
    setup = _admin_setup(state)
    for phase_id in ("entra-registration", "servicenow-oidc"):
        setup["phaseHandoffs"][phase_id] = {"status": "pending"}
        phase = state.setdefault("phases", {}).setdefault(
            phase_id,
            {
                "status": "pending",
                "checkpointResults": {},
                "checkpointAcknowledgements": {},
            },
        )
        if not isinstance(phase, dict):
            raise ServiceNowConnectError(
                f"ServiceNow lifecycle phase {phase_id} must be an object."
            )
        phase["status"] = (
            "in-progress" if phase_id == "entra-registration" else "pending"
        )
        phase["checkpointResults"] = {}
        phase["checkpointAcknowledgements"] = {}
        for key in (
            "actionApplied",
            "lastActionAt",
            "lastVerifiedAt",
            "rollbackPushGlob",
        ):
            phase.pop(key, None)


def _identity_candidate_set_hash(
    *,
    application_client_id: str,
    candidates: list[str],
    binding: dict[str, Any],
) -> str:
    return _canonical_json_hash(
        {
            "applicationClientId": application_client_id,
            "candidates": candidates,
            "tenantId": binding.get("tenantId"),
            "environmentId": binding.get("environmentId"),
            "instanceName": binding.get("instanceName"),
            "provider": binding.get("provider"),
            "profile": binding.get("profile"),
            "agentSlug": binding.get("agentSlug"),
            "agentId": binding.get("agentId"),
        }
    )


def _invalidate_identity_dependents(
    state: dict[str, Any],
    *,
    reason: str,
) -> None:
    evidence = state.setdefault("evidence", {})
    if not isinstance(evidence, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle evidence must be an object."
        )
    retired = {
        key: copy.deepcopy(evidence[key])
        for key in (
            "credential",
            "agentConnection",
            "test",
        )
        if key in evidence
    }
    if retired:
        state.setdefault("migration", {}).setdefault(
            "identityDependentInvalidations",
            [],
        ).append(
            {
                "reason": reason,
                "invalidatedAt": _utc_now(),
                "evidence": retired,
            }
        )
    for key in retired:
        evidence.pop(key, None)
    state.pop("agentBindingIdentitySha256", None)
    state.pop("connectionBindingHash", None)
    setup = _admin_setup(state)
    setup["phaseHandoffs"]["credential"] = {"status": "pending"}
    for phase_id in ("credential", "test"):
        phase = state.setdefault("phases", {}).setdefault(
            phase_id,
            {
                "status": "pending",
                "checkpointResults": {},
                "checkpointAcknowledgements": {},
            },
        )
        if not isinstance(phase, dict):
            raise ServiceNowConnectError(
                f"ServiceNow lifecycle phase {phase_id} must be an object."
            )
        phase["status"] = "pending"
        phase["checkpointResults"] = {}
        phase["checkpointAcknowledgements"] = {}
        for key in (
            "actionApplied",
            "lastActionAt",
            "lastVerifiedAt",
            "rollbackPushGlob",
        ):
            phase.pop(key, None)


def _reconcile_entra_handoff_from_receipt(
    context: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    try:
        receipt = _validated_claim_candidates(
            context,
            state,
            require_completion=True,
        )
    except ServiceNowConnectError:
        return False
    candidates = list(receipt.get("candidates") or [])
    imported_receipt_sha256 = receipt.get("importedWorkbookSha256")
    if (
        len(candidates) != 1
        or not isinstance(imported_receipt_sha256, str)
        or not imported_receipt_sha256
    ):
        return False
    setup = _admin_setup(state)
    existing = setup["phaseHandoffs"].get("entra-registration")
    existing = existing if isinstance(existing, dict) else {}
    existing_evidence = existing.get("evidence")
    existing_evidence = (
        copy.deepcopy(existing_evidence)
        if isinstance(existing_evidence, dict)
        else {}
    )
    evidence = {
        **existing_evidence,
        "kind": "structured-admin-attestation",
        "currentSource": "identity-handoff",
        "identityHandoffConfirmed": True,
        "entraAdministratorConfirmed": True,
        "clientId": receipt["applicationClientId"],
        "directoryTenantId": (
            receipt.get("directoryTenantId")
            or receipt["binding"]["tenantId"]
        ),
        "tokenClaimCandidates": candidates,
        "selectedClaimName": candidates[0],
        "candidateSetSha256": receipt["candidateSetSha256"],
        "mappingWorkbookSha256": imported_receipt_sha256,
        "binding": copy.deepcopy(receipt["binding"]),
        "recordedAt": (
            existing_evidence.get("recordedAt")
            or receipt.get("recordedAt")
            or _utc_now()
        ),
    }
    record = {
        "status": (
            "reused"
            if existing.get("status") == "reused"
            else "completed"
        ),
        "evidence": evidence,
        "verifiedBy": (
            existing.get("verifiedBy")
            if existing.get("status") == "reused"
            else "current-target-identity-handoff"
        ),
    }
    if existing == record:
        return False
    setup["phaseHandoffs"]["entra-registration"] = record
    migration = state.setdefault("migration", {})
    migration.setdefault(
        "entraTwoFieldCompletion",
        {
            "criterion": "client-id-and-one-claim-name",
            "reconciledAt": _utc_now(),
        },
    )
    return True


def _servicenow_mapping_receipt_provenance_current(
    mapping: dict[str, Any],
) -> bool:
    provenance_sha256 = str(mapping.get("provenanceSha256") or "")
    imported_workbook_sha256 = str(
        mapping.get("importedWorkbookSha256") or ""
    )
    return bool(
        re.fullmatch(r"[0-9a-fA-F]{64}", provenance_sha256)
        and imported_workbook_sha256 == provenance_sha256
        and mapping.get("importedFileFormat") in {"direct", "xlsx", "csv"}
    )


def _reconcile_servicenow_handoff_from_receipt(
    context: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    try:
        mapping = _validated_identity_mapping(context, state)
    except ServiceNowConnectError:
        return False
    if not _servicenow_mapping_receipt_provenance_current(mapping):
        return False
    setup = _admin_setup(state)
    existing = setup["phaseHandoffs"].get("servicenow-oidc")
    existing = existing if isinstance(existing, dict) else {}
    existing_evidence = existing.get("evidence")
    existing_evidence = (
        copy.deepcopy(existing_evidence)
        if isinstance(existing_evidence, dict)
        else {}
    )
    evidence = {
        **existing_evidence,
        "kind": "structured-admin-attestation",
        "currentSource": "identity-mapping",
        "identityMappingReceiptConfirmed": True,
        "mappingReceiptCurrent": True,
        "mappingDetailsCollected": True,
        "tokenClaimName": mapping["tokenClaimName"],
        "serviceNowUserField": mapping["serviceNowUserField"],
        "candidateSetSha256": mapping["candidateSetSha256"],
        "mappingWorkbookSha256": mapping["importedWorkbookSha256"],
        "mappingRelationshipSha256": mapping["relationshipSha256"],
        "binding": copy.deepcopy(mapping["binding"]),
        "recordedAt": (
            existing_evidence.get("recordedAt")
            or mapping.get("recordedAt")
            or _utc_now()
        ),
    }
    record = {
        "status": (
            "reused"
            if existing.get("status") == "reused"
            else "completed"
        ),
        "evidence": evidence,
        "verifiedBy": (
            existing.get("verifiedBy")
            if existing.get("status") == "reused"
            else "current-target-identity-mapping"
        ),
    }
    if existing == record:
        return False
    setup["phaseHandoffs"]["servicenow-oidc"] = record
    state.setdefault("migration", {}).setdefault(
        "serviceNowMappingReceiptCompletion",
        {
            "criterion": "current-target-bound-claim-field-receipt",
            "reconciledAt": _utc_now(),
        },
    )
    return True


def _persist_identity_mapping_values(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    stage: str,
    application_client_id: str,
    candidates: list[str],
    selection: dict[str, str] | None,
    provenance_sha256: str,
    provenance_format: str,
    sheet_protected: bool,
    confirmed_directory_tenant_id: str | None = None,
    saved_mapping_confirmed: bool | None = None,
) -> dict[str, Any]:
    expected_identity = _required_context_identity(context, state)
    application_client_id = normalize_client_id(application_client_id)
    binding = {
        **expected_identity,
        "applicationClientId": application_client_id,
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
    }
    evidence = state.setdefault("evidence", {})
    recorded_at = _utc_now()
    if stage == "entra":
        safe_candidates = [
            _safe_identity_name(candidate, "token_claim_name")
            for candidate in candidates
        ]
        if not safe_candidates or (
            provenance_format == "direct"
            and len(safe_candidates) != 1
        ):
            raise ServiceNowConnectError(
                "At least one selected User Claim name is required; direct "
                "capture requires exactly one."
            )
        if safe_candidates[0].casefold() == "aud":
            raise ServiceNowConnectError(
                "The aud audience claim cannot be selected as the "
                "user-matching User Claim."
            )
        candidate_hash = _identity_candidate_set_hash(
            application_client_id=application_client_id,
            candidates=safe_candidates,
            binding=binding,
        )
        existing = evidence.get("identityClaimCandidates")
        unchanged = (
            isinstance(existing, dict)
            and existing.get("candidateSetSha256") == candidate_hash
        )
        if not unchanged:
            legacy = evidence.get("identityMapping")
            if isinstance(legacy, dict):
                state.setdefault("migration", {}).setdefault(
                    "retiredIdentityMapping",
                    copy.deepcopy(legacy),
                )
                evidence.pop("identityMapping", None)
            _invalidate_identity_mapping_handoffs(state)
            _invalidate_identity_dependents(
                state,
                reason="Entra client ID or selected User Claim changed.",
            )
        result = {
            "kind": "administrator-confirmed-claim-candidates",
            "status": "entra-confirmed",
            "currentSource": (
                "direct-capture"
                if provenance_format == "direct"
                else "local-handoff"
            ),
            "applicationClientId": application_client_id,
            "candidates": safe_candidates,
            "candidateSetSha256": candidate_hash,
            "entraAdministratorConfirmed": True,
            "identityHandoffConfirmed": True,
            "binding": binding,
            "provenanceSha256": provenance_sha256,
            "importedWorkbookSha256": provenance_sha256,
            "importedFileFormat": provenance_format,
            "sheetProtected": sheet_protected,
            "recordedAt": recorded_at,
        }
        if (
            isinstance(existing, dict)
            and "tokenClaimEmissionConfirmed" in existing
        ):
            result["tokenClaimEmissionConfirmed"] = existing[
                "tokenClaimEmissionConfirmed"
            ]
        if confirmed_directory_tenant_id is not None:
            result["directoryTenantId"] = confirmed_directory_tenant_id
        evidence["identityClaimCandidates"] = result
        _reconcile_entra_handoff_from_receipt(context, state)
    else:
        candidate_receipt = _validated_claim_candidates(context, state)
        expected_candidates = list(
            candidate_receipt.get("candidates") or []
        )
        if (
            candidate_receipt.get("candidateSetSha256")
            != _identity_candidate_set_hash(
                application_client_id=application_client_id,
                candidates=expected_candidates,
                binding=binding,
            )
        ):
            raise ServiceNowConnectError(
                "The Entra candidate receipt is stale for this lifecycle."
            )
        if not isinstance(selection, dict):
            raise ServiceNowConnectError(
                "The ServiceNow identity mapping selection is required."
            )
        claim_name = _safe_identity_name(
            selection.get("tokenClaimName"),
            "token_claim_name",
        )
        if claim_name not in expected_candidates:
            raise ServiceNowConnectError(
                "The ServiceNow mapping must use the exact locked "
                "Entra-confirmed User Claim name."
            )
        user_field = str(
            selection.get("serviceNowUserField") or ""
        ).strip()
        if not _SAFE_USER_FIELD.fullmatch(user_field):
            raise ServiceNowConnectError(
                "servicenow_user_field must be an explicit safe ServiceNow "
                "internal field name."
            )
        result = {
            "kind": "administrator-confirmed-identity-mapping",
            "status": "servicenow-confirmed",
            "applicationClientId": application_client_id,
            "tokenClaimName": claim_name,
            "serviceNowUserField": user_field,
            "candidateSetSha256": candidate_receipt[
                "candidateSetSha256"
            ],
            "entraAdministratorConfirmed": True,
            "tokenClaimEmissionConfirmed": (
                candidate_receipt.get("tokenClaimEmissionConfirmed") is True
            ),
            "serviceNowAdministratorConfirmed": True,
            "binding": binding,
            "provenanceSha256": provenance_sha256,
            "importedWorkbookSha256": provenance_sha256,
            "importedFileFormat": provenance_format,
            "sheetProtected": sheet_protected,
            "recordedAt": recorded_at,
        }
        result["relationshipSha256"] = (
            _identity_mapping_relationship_hash(result)
        )
        existing = evidence.get("identityMapping")
        same_relationship = bool(
            isinstance(existing, dict)
            and existing.get("relationshipSha256")
            == result["relationshipSha256"]
        )
        if not same_relationship:
            _invalidate_oidc_handoff(state)
            _invalidate_identity_dependents(
                state,
                reason="ServiceNow internal user-field mapping changed.",
            )
        elif isinstance(existing, dict):
            preserved = copy.deepcopy(existing)
            preserved.update(
                {
                    key: value
                    for key, value in result.items()
                    if key
                    not in {
                        "provenanceSha256",
                        "importedWorkbookSha256",
                        "importedFileFormat",
                        "sheetProtected",
                        "recordedAt",
                    }
                }
            )
            result = preserved
        if saved_mapping_confirmed is True:
            result["savedMappingConfirmed"] = True
            result.setdefault("savedMappingConfirmedAt", recorded_at)
            result.pop("savedMappingRejectedAt", None)
        elif saved_mapping_confirmed is False:
            result["savedMappingConfirmed"] = False
            result.pop("savedMappingConfirmedAt", None)
            result.setdefault("savedMappingRejectedAt", recorded_at)
        evidence["identityMapping"] = result
        _reconcile_servicenow_handoff_from_receipt(context, state)
    _write_lifecycle_state(context, state)
    return copy.deepcopy(result)


def record_identity_direct(
    context: dict[str, Any],
    *,
    stage: str,
    client_id: str | None,
    directory_tenant_id: str | None = None,
    claim_name: str | None,
    user_field: str | None,
    confirmed: bool,
    saved_mapping_confirmed: bool | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Direct identity data capture requires explicit confirmation."
        )
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError(
            "Identity direct capture stage is invalid."
        )
    if saved_mapping_confirmed is not None and stage != "servicenow":
        raise ServiceNowConnectError(
            "Saved mapping confirmation is accepted only for the "
            "ServiceNow stage."
        )
    state = _load_lifecycle_state(context)
    if stage == "entra":
        if not client_id or not claim_name:
            raise ServiceNowConnectError(
                "Direct Entra capture requires the Application client ID "
                "GUID and exactly one selected User Claim name."
            )
        application_client_id = normalize_client_id(client_id)
        expected_tenant_id = _normalize_directory_tenant_id(
            _required_context_identity(context, state)["tenantId"]
        )
        if (
            directory_tenant_id is not None
            and _normalize_directory_tenant_id(directory_tenant_id)
            != expected_tenant_id
        ):
            raise ServiceNowConnectError(
                "The confirmed Directory tenant ID does not match the "
                "current target tenant."
            )
        confirmed_tenant_id = expected_tenant_id
        safe_claim = _safe_identity_name(claim_name, "user_claim")
        if safe_claim.casefold() == "aud":
            raise ServiceNowConnectError(
                "The aud audience claim cannot be selected as the "
                "user-matching User Claim."
            )
        candidates = [safe_claim]
        selection = None
    else:
        if (
            client_id is not None
            or directory_tenant_id is not None
            or claim_name is not None
        ):
            raise ServiceNowConnectError(
                "The ServiceNow stage uses the locked Entra-confirmed client "
                "ID and User Claim; do not re-enter or change them."
            )
        if not user_field:
            raise ServiceNowConnectError(
                "Direct ServiceNow capture requires the actual internal "
                "sys_user field."
            )
        candidate_receipt = _validated_claim_candidates(context, state)
        candidates = list(candidate_receipt.get("candidates") or [])
        if len(candidates) != 1:
            raise ServiceNowConnectError(
                "Direct ServiceNow capture requires exactly one current "
                "Entra-confirmed User Claim."
            )
        application_client_id = normalize_client_id(
            str(candidate_receipt.get("applicationClientId") or "")
        )
        selection = {
            "tokenClaimName": candidates[0],
            "serviceNowUserField": user_field,
        }
        confirmed_tenant_id = None
    provenance_sha256 = _canonical_json_hash(
        {
            "kind": "administrator-direct-capture",
            "stage": stage,
            "applicationClientId": application_client_id,
            "candidates": candidates,
            "selection": selection,
            "binding": _required_context_identity(context, state),
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
        }
    )
    return _persist_identity_mapping_values(
        context,
        state,
        stage=stage,
        application_client_id=application_client_id,
        candidates=candidates,
        selection=selection,
        provenance_sha256=provenance_sha256,
        provenance_format="direct",
        sheet_protected=False,
        confirmed_directory_tenant_id=confirmed_tenant_id,
        saved_mapping_confirmed=saved_mapping_confirmed,
    )


def _identity_handoff_binding_matches(
    context: dict[str, Any],
    state: dict[str, Any],
    evidence: dict[str, Any],
    *,
    application_client_id: str,
) -> bool:
    binding = evidence.get("binding")
    if not isinstance(binding, dict):
        return False
    expected = {
        **_required_context_identity(context, state),
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
    }
    if any(
        str(binding.get(field) or "").casefold()
        != str(value).casefold()
        for field, value in expected.items()
    ):
        return False
    bound_client_id = binding.get("applicationClientId")
    return (
        bound_client_id is None
        or str(bound_client_id).casefold()
        == application_client_id.casefold()
    )


def _validate_reused_identity_provenance(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    phase: str,
    handoff_evidence: dict[str, Any],
    target_candidates: dict[str, Any],
    target_mapping: dict[str, Any] | None,
) -> None:
    reuse_source = handoff_evidence.get("reuseSource")
    reuse_record = state.get("sharedConfigurationReuse")
    if not isinstance(reuse_source, dict) or not isinstance(reuse_record, dict):
        raise ServiceNowConnectError(
            "The reused Shared Identity administrator evidence has no "
            "source provenance."
        )
    expected_source = {
        "sourceKey": reuse_record.get("sourceKey"),
        "sourceProvider": reuse_record.get("sourceProvider"),
        "sourceAgentSlug": reuse_record.get("sourceAgentSlug"),
        "sourceStateSha256": reuse_record.get("sourceStateSha256"),
    }
    if (
        reuse_record.get("decision") != "accepted"
        or phase not in list(reuse_record.get("applicableItems") or [])
        or any(reuse_source.get(key) != value for key, value in expected_source.items())
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity administrator evidence does not match "
            "the accepted reuse decision."
        )
    source_provider = str(reuse_source.get("sourceProvider") or "")
    source_agent_slug = str(reuse_source.get("sourceAgentSlug") or "")
    if (
        source_provider
        not in {
            profile.provider_key for profile in PRODUCT_PROFILES.values()
        }
        or not _SAFE_AGENT_SLUG.fullmatch(source_agent_slug)
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity source identity is invalid."
        )
    source_path = (
        Path(context["root"])
        / ".local"
        / "connect"
        / source_provider
        / "agents"
        / source_agent_slug
        / "lifecycle.json"
    )
    if not source_path.is_file() or source_path.is_symlink():
        raise ServiceNowConnectError(
            "The reused Shared Identity source lifecycle is unavailable."
        )
    source_bytes = source_path.read_bytes()
    if (
        hashlib.sha256(source_bytes).hexdigest()
        != reuse_source.get("sourceStateSha256")
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity source changed after it was accepted."
        )
    try:
        source_state = json.loads(source_bytes)
    except json.JSONDecodeError as exc:
        raise ServiceNowConnectError(
            "The reused Shared Identity source lifecycle is invalid."
        ) from exc
    if (
        not isinstance(source_state, dict)
        or source_state.get("provider") != source_provider
        or str(source_state.get("agentSlug") or "") != source_agent_slug
        or str(source_state.get("environmentId") or "").casefold()
        != str(context["environment"]["id"]).casefold()
        or str(source_state.get("ring") or "").casefold()
        != str(context["environment"]["ring"]).casefold()
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity source lifecycle no longer matches "
            "the active environment."
        )
    source_setup = source_state.get("adminSetup")
    source_setup = source_setup if isinstance(source_setup, dict) else {}
    source_handoff = _completed_handoff(source_setup, phase)
    source_candidates = _shared_mapping_compatible(
        context,
        source_state,
        require_servicenow=False,
    )
    source_mapping = (
        _shared_mapping_compatible(
            context,
            source_state,
            require_servicenow=True,
        )
        if phase == "servicenow-oidc"
        else None
    )
    if (
        source_handoff is None
        or source_candidates is None
        or (phase == "servicenow-oidc" and source_mapping is None)
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity source administrator evidence is no "
            "longer valid."
        )
    if (
        source_candidates.get("applicationClientId")
        != target_candidates.get("applicationClientId")
        or source_candidates.get("candidates")
        != target_candidates.get("candidates")
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity source claims no longer match the "
            "accepted target evidence."
        )
    if phase == "servicenow-oidc" and (
        not isinstance(target_mapping, dict)
        or source_mapping.get("tokenClaimName")
        != target_mapping.get("tokenClaimName")
        or source_mapping.get("serviceNowUserField")
        != target_mapping.get("serviceNowUserField")
    ):
        raise ServiceNowConnectError(
            "The reused Shared Identity source mapping no longer matches the "
            "accepted target evidence."
        )


def _identity_admin_handoff_is_ready(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    phase: str,
) -> bool:
    setup = _admin_setup(state)
    handoff = _completed_handoff(setup, phase)
    if handoff is None:
        return False
    phase_state = state.get("phases", {}).get(phase)
    checkpoint_results = (
        phase_state.get("checkpointResults")
        if isinstance(phase_state, dict)
        else None
    )
    checkpoint_results = (
        checkpoint_results if isinstance(checkpoint_results, dict) else {}
    )
    if checkpoint_results and any(
        status not in {"Passed", "Manual"}
        for status in checkpoint_results.values()
    ):
        return False
    evidence = handoff["evidence"]
    reuse_record = state.get("sharedConfigurationReuse")
    strict_shared_reuse = bool(
        handoff.get("status") == "reused"
        and isinstance(evidence.get("reuseSource"), dict)
        and isinstance(reuse_record, dict)
        and reuse_record.get("decision") == "accepted"
        and phase in list(reuse_record.get("applicableItems") or [])
    )
    try:
        candidates = _validated_claim_candidates(context, state)
        client_id = normalize_client_id(
            str(candidates.get("applicationClientId") or "")
        )
        mapping = (
            _validated_identity_mapping(context, state)
            if phase == "servicenow-oidc"
            else None
        )
    except ServiceNowConnectError as exc:
        if strict_shared_reuse:
            raise ServiceNowConnectError(
                "The accepted Shared Identity administrator evidence is no "
                f"longer valid. {exc}"
            ) from exc
        return False
    if not _identity_handoff_binding_matches(
        context,
        state,
        evidence,
        application_client_id=client_id,
    ):
        if strict_shared_reuse:
            raise ServiceNowConnectError(
                "The accepted Shared Identity administrator evidence no "
                "longer matches the active target."
            )
        return False
    validated_evidence = evidence
    repaired = False
    if strict_shared_reuse:
        _validate_reused_identity_provenance(
            context,
            state,
            phase=phase,
            handoff_evidence=evidence,
            target_candidates=candidates,
            target_mapping=mapping,
        )
        validated_evidence = copy.deepcopy(evidence)
        derived_values: dict[str, Any]
        if phase == "entra-registration":
            derived_values = {
                "clientId": client_id,
                "tokenClaimCandidates": copy.deepcopy(
                    candidates["candidates"]
                ),
                "identityHandoffConfirmed": True,
                "selectedClaimName": candidates["candidates"][0],
                "candidateSetSha256": candidates["candidateSetSha256"],
                "mappingWorkbookSha256": candidates[
                    "importedWorkbookSha256"
                ],
            }
        else:
            derived_values = {
                "identityMappingReceiptConfirmed": True,
                "mappingReceiptCurrent": True,
                "mappingDetailsCollected": True,
                "tokenClaimName": mapping["tokenClaimName"],
                "serviceNowUserField": mapping["serviceNowUserField"],
                "candidateSetSha256": mapping["candidateSetSha256"],
                "mappingRelationshipSha256": mapping[
                    "relationshipSha256"
                ],
            }
        for key, value in derived_values.items():
            if validated_evidence.get(key) != value:
                validated_evidence[key] = value
                repaired = True
        binding = validated_evidence["binding"]
        if binding.get("applicationClientId") != client_id:
            binding["applicationClientId"] = client_id
            repaired = True
    if phase == "entra-registration":
        try:
            evidence_client_id = normalize_client_id(
                str(validated_evidence.get("clientId") or "")
            )
        except ServiceNowConnectError as exc:
            if strict_shared_reuse:
                raise ServiceNowConnectError(
                    "The accepted Shared Identity administrator handoff has "
                    "an invalid Application client ID."
                ) from exc
            return False
        fresh_confirmation = bool(
            validated_evidence.get("kind")
            == "structured-admin-attestation"
            and evidence_client_id == client_id
            and validated_evidence.get("tokenClaimCandidates")
            == candidates.get("candidates")
            and validated_evidence.get("candidateSetSha256")
            == candidates.get("candidateSetSha256")
            and validated_evidence.get("mappingWorkbookSha256")
            == candidates.get("importedWorkbookSha256")
            and validated_evidence.get("entraAdministratorConfirmed") is True
            and len(candidates.get("candidates") or []) == 1
            and validated_evidence.get("selectedClaimName")
            == candidates["candidates"][0]
            and _normalize_directory_tenant_id(
                str(
                    validated_evidence.get("directoryTenantId")
                    or candidates["binding"]["tenantId"]
                )
            )
            == _normalize_directory_tenant_id(
                str(candidates["binding"]["tenantId"])
            )
        )
        historical_graph_pass = _has_historical_entra_graph_pass(state)
        migrated_historical_graph_pass = (
            _historical_entra_marker_current(validated_evidence)
        )
        ready = (
            fresh_confirmation
            or historical_graph_pass
            or migrated_historical_graph_pass
        )
    else:
        ready = bool(
            isinstance(mapping, dict)
            and validated_evidence.get("kind")
            == "structured-admin-attestation"
            and validated_evidence.get("identityMappingReceiptConfirmed")
            is True
            and validated_evidence.get("mappingReceiptCurrent") is True
            and validated_evidence.get("mappingDetailsCollected") is True
            and validated_evidence.get("tokenClaimName")
            == mapping.get("tokenClaimName")
            and validated_evidence.get("serviceNowUserField")
            == mapping.get("serviceNowUserField")
            and validated_evidence.get("candidateSetSha256")
            == mapping.get("candidateSetSha256")
            and validated_evidence.get("mappingRelationshipSha256")
            == mapping.get("relationshipSha256")
        )
    if not ready:
        if strict_shared_reuse:
            raise ServiceNowConnectError(
                "The accepted Shared Identity administrator handoff is "
                "incomplete or inconsistent."
            )
        return False
    if strict_shared_reuse and repaired:
        validated_evidence["recordedAt"] = _utc_now()
        handoff["evidence"] = validated_evidence
        _write_lifecycle_state(context, state)
    return True


def _historical_entra_marker_current(
    evidence: dict[str, Any],
) -> bool:
    return bool(
        evidence.get("currentSource") == "historical-graph-pass"
        and evidence.get("historicalGraphPassCompatible") is True
        and isinstance(evidence.get("historicalGraphPassMigratedAt"), str)
        and evidence["historicalGraphPassMigratedAt"]
    )


def _migrate_historical_entra_confirmation(
    context: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    setup = _admin_setup(state)
    handoff = _completed_handoff(setup, "entra-registration")
    if handoff is None:
        return False
    evidence = handoff["evidence"]
    if _historical_entra_marker_current(evidence):
        return False
    if (
        evidence.get("currentSource") == "administrator-confirmed"
        or not _has_historical_entra_graph_pass(state)
    ):
        return False
    try:
        candidates = _validated_claim_candidates(context, state)
        client_id = normalize_client_id(
            str(candidates.get("applicationClientId") or "")
        )
        evidence_client_id = normalize_client_id(
            str(evidence.get("clientId") or "")
        )
    except ServiceNowConnectError:
        return False
    if (
        evidence.get("kind") != "structured-admin-attestation"
        or evidence_client_id != client_id
        or evidence.get("tokenClaimCandidates")
        != candidates.get("candidates")
        or evidence.get("tokenClaimEmissionConfirmed") is not True
        or evidence.get("candidateSetSha256")
        != candidates.get("candidateSetSha256")
        or evidence.get("mappingWorkbookSha256")
        != candidates.get("importedWorkbookSha256")
        or not _identity_handoff_binding_matches(
            context,
            state,
            evidence,
            application_client_id=client_id,
        )
    ):
        return False
    migrated_at = _utc_now()
    evidence["currentSource"] = "historical-graph-pass"
    evidence["historicalGraphPassCompatible"] = True
    evidence["historicalGraphPassMigratedAt"] = migrated_at
    handoff["verifiedBy"] = "historical-graph-pass-migration"
    state.setdefault("migration", {})["entraHistoricalGraphPass"] = {
        "source": "four-persisted-passed-checkpoints",
        "migratedAt": migrated_at,
    }
    return True


def _preflight_discovery_complete(setup: dict[str, Any]) -> bool:
    preflight = setup.get("preflight")
    if not isinstance(preflight, dict):
        return False
    instance_name = preflight.get("instanceName")
    if not isinstance(instance_name, str) or not instance_name:
        return False
    if (
        preflight.get("instanceSource") == "maker-confirmed"
        and isinstance(preflight.get("recordedAt"), str)
        and preflight["recordedAt"]
    ):
        return True
    handoffs = setup.get("phaseHandoffs")
    handoff = (
        handoffs.get("preflight")
        if isinstance(handoffs, dict)
        else None
    )
    evidence = (
        handoff.get("evidence")
        if isinstance(handoff, dict)
        and handoff.get("status") in {"completed", "reused"}
        else None
    )
    if bool(
        isinstance(evidence, dict)
        and evidence.get("instanceName") == instance_name
    ):
        return True
    discovery = preflight.get("discovery")
    return bool(
        isinstance(handoff, dict)
        and handoff.get("status") in {"completed", "reused"}
        and isinstance(discovery, dict)
        and isinstance(discovery.get("observedAt"), str)
        and discovery.get("observedAt")
        and isinstance(discovery.get("connectionCandidates"), list)
        and isinstance(discovery.get("requiredPlugins"), list)
    )


def _normalize_preflight_handoff(
    state: dict[str, Any],
    setup: dict[str, Any],
) -> bool:
    complete = _preflight_discovery_complete(setup)
    preflight = setup["preflight"]
    handoffs = setup["phaseHandoffs"]
    if complete:
        handoffs["preflight"] = {
            "status": "completed",
            "evidence": {
                "kind": "maker-confirmed-target",
                "instanceName": preflight.get("instanceName"),
                "recordedAt": (
                    preflight.get("recordedAt")
                    or handoffs.get("preflight", {})
                    .get("evidence", {})
                    .get("recordedAt")
                    or _utc_now()
                ),
            },
        }
        return True

    handoffs["preflight"] = {"status": "pending"}
    phase = state.setdefault("phases", {}).setdefault("preflight", {})
    if not isinstance(phase, dict):
        raise ServiceNowConnectError(
            "ServiceNow preflight phase must be an object."
        )
    phase["status"] = "in-progress"
    phase["checkpointResults"] = {}
    phase["checkpointAcknowledgements"] = {}
    for key in (
        "actionApplied",
        "lastActionAt",
        "lastVerifiedAt",
        "rollbackPushGlob",
    ):
        phase.pop(key, None)
    return False


def _legacy_state_path(agent_id: str) -> Path:
    return Path(".local/connect/servicenow/agents") / agent_id / "state.json"


def _agent_slug(context: dict[str, Any]) -> str:
    agent = context.get("agent")
    active = context.get("active")
    if isinstance(agent, dict):
        slug = agent.get("workspace_slug")
        if isinstance(slug, str) and slug:
            return slug
    if isinstance(active, dict):
        slug = active.get("slug")
        if isinstance(slug, str) and slug:
            return slug
    if isinstance(agent, dict):
        agent_id = agent.get("id")
        if isinstance(agent_id, str) and agent_id:
            return agent_id
    raise ServiceNowConnectError("The active agent has no workspace slug.")


def _lifecycle_state_path(context: dict[str, Any]) -> Path:
    return (
        Path(".local/connect")
        / PROVIDER_KEY
        / "agents"
        / _agent_slug(context)
        / "lifecycle.json"
    )


def _normalize_agent_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ServiceNowConnectError("The selected agent ID is invalid.") from exc


def _agent_card_identity(card: dict[str, Any]) -> tuple[str, str] | None:
    raw_id = str(
        card.get("botId")
        or card.get("cdsBotId")
        or card.get("componentIdUnique")
        or ""
    )
    try:
        agent_id = _normalize_agent_id(raw_id)
    except ServiceNowConnectError:
        return None
    display_name = str(
        card.get("fullBotName")
        or card.get("displayName")
        or card.get("shortBotName")
        or agent_id
    )
    return agent_id, display_name


def _canonical_agent(
    canonical_agents: dict[str, Any],
    agent_id: str,
) -> dict[str, Any] | None:
    return next(
        (
            value
            for key, value in canonical_agents.items()
            if isinstance(key, str)
            and key.casefold() == agent_id.casefold()
            and isinstance(value, dict)
        ),
        None,
    )


def _operational_agent(
    operational_agents: list[Any],
    agent_id: str,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in operational_agents
            if isinstance(item, dict)
            and str(item.get("botId") or "").casefold()
            == agent_id.casefold()
        ),
        None,
    )


def _canonical_profile_and_readiness(
    canonical: dict[str, Any] | None,
    operational: dict[str, Any] | None,
    agent_id: str,
) -> tuple[ServiceNowProductProfile | None, bool]:
    agent = canonical.get("agent") if isinstance(canonical, dict) else None
    if not isinstance(agent, dict):
        return None, False
    profile = product_profile_for_schema(str(agent.get("schema_name") or ""))
    workspace = canonical.get("workspace")
    ready = (
        profile is not None
        and str(agent.get("id") or "").casefold() == agent_id.casefold()
        and _canonical_local_authoring_ready(canonical, agent)
        and _canonical_authoring_ready(canonical)
        and isinstance(workspace, dict)
        and bool(workspace.get("folder"))
        and bool(workspace.get("agent_path"))
        and isinstance(operational, dict)
        and agent.get("workspace_slug") == operational.get("slug")
        and bool(operational.get("agentBuilderChangeSetPath"))
    )
    return profile, ready


def _canonical_authoring_ready(canonical: dict[str, Any]) -> bool:
    try:
        from setup_existing_da import is_authoring_ready
    except ImportError as exc:  # pragma: no cover - installation failure
        raise ServiceNowConnectError(
            "The /setup readiness helper is unavailable."
        ) from exc
    return is_authoring_ready(canonical.get("steps"), canonical.get("workspace"))


def _canonical_local_authoring_ready(
    canonical: dict[str, Any],
    agent: dict[str, Any],
) -> bool:
    realm = agent.get("realm")
    if realm == "dev":
        return True
    alm = agent.get("alm")
    return (
        realm in (None, "")
        and canonical.get("setup_source") == "existing-dev"
        and isinstance(alm, dict)
        and alm.get("isEnrolled") is False
    )


def _validate_discovery_binding(
    environment: dict[str, Any],
    config: dict[str, Any],
) -> str | None:
    environment_fields = {
        "environmentId": "id",
        "tenantId": "tenant_id",
        "powerPlatformApiEndpoint": "power_platform_api_endpoint",
        "ring": "ring",
        "agentBuilderApiVersion": "api_version",
    }
    for config_key, canonical_key in environment_fields.items():
        operational_value = str(config.get(config_key) or "").strip()
        canonical_value = str(environment.get(canonical_key) or "").strip()
        if (
            operational_value
            and canonical_value
            and operational_value.casefold() != canonical_value.casefold()
        ):
            raise ServiceNowConnectError(
                "Canonical setup state and operational config identify "
                f"different environment {config_key} values."
            )
    canonical_account = str(environment.get("account") or "").strip()
    operational_account = str(config.get("account") or "").strip()
    if (
        canonical_account
        and operational_account
        and canonical_account.casefold() != operational_account.casefold()
    ):
        raise ServiceNowConnectError(
            "Canonical setup state and operational config identify different "
            "Microsoft accounts."
        )
    return canonical_account or operational_account or None


def _discovery_error_status(exc: AgentBuilderHTTPError) -> str:
    if exc.status_code == 401:
        return "authentication-required"
    if exc.status_code == 403:
        return "not-authorized"
    if exc.status_code == 404:
        return "not-found"
    if exc.status_code == 429:
        return "throttled"
    if exc.status_code >= 500:
        return "service-unavailable"
    return "lookup-failed"


def _exact_canonical_identity(
    client: AgentBuilderClient,
    *,
    agent_id: str,
    canonical_name: str,
    profile: ServiceNowProductProfile,
) -> tuple[str, ServiceNowProductProfile]:
    components = client.fetch_components(agent_id)
    bot = components.get("bot")
    if not isinstance(bot, dict):
        raise ServiceNowConnectError(
            "Direct component lookup did not return an exact BotEntity."
        )
    exact_identity = _agent_card_identity(bot)
    if (
        exact_identity is None
        or exact_identity[0].casefold() != agent_id.casefold()
    ):
        raise ServiceNowConnectError(
            "Direct component lookup returned a different agent identity."
        )
    exact_schema = str(bot.get("schemaName") or "").strip()
    exact_profile = product_profile_for_schema(exact_schema)
    if exact_profile is None:
        raise ServiceNowConnectError(
            "Direct component lookup did not return a supported Employee "
            "Self-Service HR or IT schema."
        )
    if exact_profile.key != profile.key:
        raise ServiceNowConnectError(
            "Direct component lookup returned a different Employee "
            "Self-Service product profile."
        )
    return exact_identity[1] or canonical_name, exact_profile


def _agent_choice(
    root: Path,
    *,
    agent_id: str,
    agent_slug: str,
    display_name: str,
    profile: ServiceNowProductProfile,
    setup_ready: bool,
) -> dict[str, Any]:
    status = "setup-required"
    if setup_ready:
        status = "ready"
        state_path = (
            root
            / ".local"
            / "connect"
            / profile.provider_key
            / "agents"
            / agent_slug
            / "lifecycle.json"
        )
        if state_path.exists():
            state = _load_json(state_path)
            phases = state.get("phases")
            if (
                isinstance(phases, dict)
                and phases
                and all(
                    isinstance(value, dict)
                    and value.get("status") == "done"
                    for value in phases.values()
                )
            ):
                status = "connected-revalidation-required"
    return {
        "id": agent_id,
        "slug": agent_slug,
        "name": display_name,
        "profile": profile.key,
        "provider": profile.provider_key,
        "product": profile.product_name,
        "status": status,
        "selectable": setup_ready,
    }


def list_agent_choices(
    root: Path = Path("."),
    *,
    maker_username: str | None = None,
) -> dict[str, Any]:
    setup = _load_json(root / SETUP_STATE)
    config = _load_json(root / ACTIVE_CONFIG)
    if setup.get("schema_version") != SETUP_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            f"Expected /setup schema {SETUP_SCHEMA_VERSION}."
        )
    environment = setup.get("environment")
    canonical_agents = setup.get("agents")
    operational_agents = config.get("agents")
    if not isinstance(environment, dict):
        raise ServiceNowConnectError("The setup handoff has no environment.")
    if not isinstance(canonical_agents, dict):
        raise ServiceNowConnectError("Canonical setup state has no agent map.")
    if not isinstance(operational_agents, list):
        raise ServiceNowConnectError("Operational setup config has no agent list.")
    setup_account = _validate_discovery_binding(environment, config)
    account = str(maker_username or "").strip() or setup_account
    client = _agentbuilder_client(
        {"environment": environment, "account": account}
    )
    choices: list[dict[str, Any]] = []
    discovery_errors: list[dict[str, Any]] = []
    listed_agent_ids: set[str] = set()
    for card in client.list_agents():
        identity = _agent_card_identity(card)
        if identity is None:
            continue
        agent_id, display_name = identity
        if agent_id.casefold() in listed_agent_ids:
            continue
        listed_agent_ids.add(agent_id.casefold())
        canonical = _canonical_agent(canonical_agents, agent_id)
        operational = _operational_agent(operational_agents, agent_id)
        profile, ready = _canonical_profile_and_readiness(
            canonical,
            operational,
            agent_id,
        )
        if profile is None and canonical is None:
            live_schema = str(
                card.get("schemaName") or card.get("schemaname") or ""
            )
            profile = (
                product_profile_for_schema(live_schema)
                or product_profile_for_name(display_name)
            )
        if profile is None:
            continue
        choice = _agent_choice(
            root,
            agent_id=agent_id,
            agent_slug=str(
                operational.get("slug") if operational else agent_id
            ),
            display_name=display_name,
            profile=profile,
            setup_ready=ready,
        )
        choices.append(choice)

    for raw_agent_id, canonical in canonical_agents.items():
        if not isinstance(raw_agent_id, str) or not isinstance(canonical, dict):
            continue
        try:
            agent_id = _normalize_agent_id(raw_agent_id)
        except ServiceNowConnectError:
            continue
        if agent_id.casefold() in listed_agent_ids:
            continue
        operational = _operational_agent(operational_agents, agent_id)
        profile, ready = _canonical_profile_and_readiness(
            canonical,
            operational,
            agent_id,
        )
        if profile is None or not ready:
            continue
        canonical_agent = canonical["agent"]
        canonical_name = str(
            canonical_agent.get("display_name")
            or canonical_agent.get("name")
            or profile.agent_display_name
        )
        try:
            exact_name, exact_profile = _exact_canonical_identity(
                client,
                agent_id=agent_id,
                canonical_name=canonical_name,
                profile=profile,
            )
        except AgentBuilderHTTPError as exc:
            discovery_errors.append(
                {
                    "id": agent_id,
                    "name": canonical_name,
                    "profile": profile.key,
                    "provider": profile.provider_key,
                    "status": _discovery_error_status(exc),
                    "message": str(exc),
                }
            )
            continue
        except (AgentBuilderError, ServiceNowConnectError) as exc:
            discovery_errors.append(
                {
                    "id": agent_id,
                    "name": canonical_name,
                    "profile": profile.key,
                    "provider": profile.provider_key,
                    "status": "lookup-failed",
                    "message": str(exc),
                }
            )
            continue
        choice = _agent_choice(
            root,
            agent_id=agent_id,
            agent_slug=str(operational.get("slug") or agent_id),
            display_name=exact_name,
            profile=exact_profile,
            setup_ready=True,
        )
        choices.append(choice)

    result: dict[str, Any] = {
        "environmentId": environment.get("id"),
        "agents": sorted(
            choices,
            key=lambda item: (
                str(item["name"]).casefold(),
                str(item["id"]),
            ),
        ),
    }
    if discovery_errors:
        result["discoveryErrors"] = sorted(
            discovery_errors,
            key=lambda item: (
                str(item["name"]).casefold(),
                str(item["id"]),
            ),
        )
    return result


def _prepared_agent_choices(
    root: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    setup = _load_json(root / SETUP_STATE)
    config = _load_json(root / ACTIVE_CONFIG)
    if setup.get("schema_version") != SETUP_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            f"Expected /setup schema {SETUP_SCHEMA_VERSION}."
        )
    environment = setup.get("environment")
    canonical_agents = setup.get("agents")
    operational_agents = config.get("agents")
    if not isinstance(environment, dict):
        raise ServiceNowConnectError("The setup handoff has no environment.")
    if not isinstance(canonical_agents, dict):
        raise ServiceNowConnectError("Canonical setup state has no agent map.")
    if not isinstance(operational_agents, list):
        raise ServiceNowConnectError("Operational setup config has no agent list.")
    _validate_discovery_binding(environment, config)

    choices: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for raw_agent_id, canonical in canonical_agents.items():
        if not isinstance(raw_agent_id, str) or not isinstance(canonical, dict):
            continue
        try:
            agent_id = _normalize_agent_id(raw_agent_id)
        except ServiceNowConnectError:
            continue
        operational = _operational_agent(operational_agents, agent_id)
        profile, ready = _canonical_profile_and_readiness(
            canonical,
            operational,
            agent_id,
        )
        canonical_agent = canonical.get("agent")
        if profile is None and isinstance(canonical_agent, dict):
            unsupported.append(
                {
                    "id": agent_id,
                    "name": str(
                        canonical_agent.get("display_name")
                        or canonical_agent.get("name")
                        or agent_id
                    ),
                }
            )
        if profile is None or not isinstance(canonical_agent, dict):
            continue
        display_name = str(
            canonical_agent.get("display_name")
            or canonical_agent.get("name")
            or (operational or {}).get("name")
            or profile.agent_display_name
        )
        if not ready or not isinstance(operational, dict):
            # A Dev-eligible agent whose Setup steps are still pending.
            if _canonical_local_authoring_ready(canonical, canonical_agent):
                incomplete.append({"id": agent_id, "name": display_name})
            continue
        choices.append(
            {
                "id": agent_id,
                "slug": str(operational["slug"]),
                "name": display_name,
                "profile": profile.key,
                "provider": profile.provider_key,
                "product": profile.product_name,
                "status": "prepared",
                "selectable": True,
            }
        )
    return (
        environment,
        sorted(
            choices,
            key=lambda item: (
                str(item["name"]).casefold(),
                str(item["id"]),
            ),
        ),
        incomplete,
        unsupported,
    )


UNSUPPORTED_AGENT_MESSAGE = (
    "We can connect **Employee Self-Service HR to ServiceNow HR Service "
    "Delivery** or **Employee Self-Service IT to ServiceNow IT Service "
    "Management**, one agent at a time. The selected agent isn't supported."
    "\n\nSelect Employee Self-Service HR or IT to continue."
)


def _unsupported_agent_result(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "unsupported-agent",
        "branch": "unsupported-agent",
        "message": UNSUPPORTED_AGENT_MESSAGE,
        "agent": agent,
        "stateChanged": False,
    }


def _setup_incomplete_result(
    agent: dict[str, Any],
    setup_handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "setup-incomplete",
        "branch": "setup-not-finished",
        "message": (
            "This agent is in the workspace, but its setup isn't finished "
            "yet. Setup's remaining steps run first, then Connect continues "
            "with it."
        ),
        "agent": agent,
        "setupHandoff": setup_handoff
        or {"command": "/setup", "agentId": agent["id"]},
        "stateChanged": False,
    }


def _prepared_agent_result(choice: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "ready",
        "branch": "prepared-agent",
        "selectedAgent": choice,
        "stateChanged": False,
    }


def _agent_link_question() -> dict[str, Any]:
    return {
        "header": "What is the Copilot Studio link for the agent?",
        "question": (
            "Paste the full Copilot Studio link for the existing agent you "
            "want to use."
        ),
        "options": [],
        "allowFreeformInput": True,
    }


def _resolve_link_target(
    agent_link: str,
    environment_id: str,
    ring: str,
) -> dict[str, Any]:
    try:
        from setup_existing_da import (
            ExistingDASetupError,
            parse_da_target_url,
            resolve_da_target,
        )
    except ImportError as exc:  # pragma: no cover - installation failure
        raise ServiceNowConnectError(
            "The existing-agent setup URL resolver is unavailable."
        ) from exc

    try:
        parsed = parse_da_target_url(agent_link)
        if parsed.get("source") != "copilot-studio-url":
            raise ServiceNowConnectError(
                "Paste the full Copilot Studio link for the existing agent."
            )
        return resolve_da_target(
            target_url=agent_link,
            environment_id=environment_id,
            ring=ring or None,
            require_agent=True,
        )
    except ExistingDASetupError as exc:
        message = str(exc)
        if "different environments" in message:
            raise ServiceNowConnectError(
                "This agent link points to a different environment. Run "
                "/setup and explicitly confirm that environment before using "
                "the agent."
            ) from exc
        if "different service rings" in message:
            raise ServiceNowConnectError(
                "This agent link points to a different Copilot Studio ring. "
                "Run /setup and explicitly confirm that environment before "
                "using the agent."
            ) from exc
        raise ServiceNowConnectError(
            "Paste the full Copilot Studio link for the existing agent. The "
            "link must include both the environment and agent."
        ) from exc


def _setup_handoff_for_link(
    agent_link: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "command": "/setup",
        "targetUrl": agent_link.strip(),
        "environmentId": target["environmentId"],
        "agentId": str(target["agentId"]),
        "ring": target["ring"],
        "requiresEnvironmentConfirmation": True,
        "requiresAccountConfirmation": True,
    }


def _resolve_explicit_agent_link(
    *,
    agent_link: str,
    environment: dict[str, Any],
    prepared_choices: list[dict[str, Any]],
    incomplete_agents: list[dict[str, Any]],
    unsupported_agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = _resolve_link_target(agent_link, "", "")
    workspace_environment = str(environment.get("id") or "")
    if str(target["environmentId"]).casefold() != workspace_environment.casefold():
        return {
            "schemaVersion": "servicenow.agent-chooser.v1",
            "status": "setup-required",
            "branch": "explicit-agent-link",
            "message": (
                "This agent is in a different environment than this "
                "workspace. Setup runs first and asks how to handle the "
                "environment change, then Connect continues with this agent."
            ),
            "setupHandoff": {
                **_setup_handoff_for_link(agent_link, target),
                "workspaceEnvironmentDiffers": True,
            },
            "stateChanged": False,
        }
    workspace_ring = str(environment.get("ring") or "")
    if workspace_ring and target["ring"] != workspace_ring:
        raise ServiceNowConnectError(
            "This agent link points to a different Copilot Studio ring. "
            "Run /setup and explicitly confirm that environment before "
            "using the agent."
        )
    agent_id = str(target["agentId"])
    prepared = next(
        (
            choice
            for choice in prepared_choices
            if str(choice.get("id") or "").casefold() == agent_id.casefold()
        ),
        None,
    )
    if prepared is not None:
        return _prepared_agent_result(prepared)
    unfinished = next(
        (
            agent
            for agent in incomplete_agents
            if str(agent["id"]).casefold() == agent_id.casefold()
        ),
        None,
    )
    if unfinished is not None:
        return _setup_incomplete_result(
            unfinished,
            _setup_handoff_for_link(agent_link, target),
        )
    unsupported = next(
        (
            agent
            for agent in unsupported_agents or []
            if str(agent["id"]).casefold() == agent_id.casefold()
        ),
        None,
    )
    if unsupported is not None:
        return _unsupported_agent_result(unsupported)
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "setup-required",
        "branch": "explicit-agent-link",
        "message": (
            "This agent isn't prepared in this workspace yet. Setup runs "
            "first for this exact agent, then Connect continues with it."
        ),
        "setupHandoff": _setup_handoff_for_link(agent_link, target),
        "stateChanged": False,
    }


def _workspace_not_prepared(root: Path) -> bool:
    return not (root / SETUP_STATE).exists() or not (root / ACTIVE_CONFIG).exists()


def _unprepared_workspace_handoff(agent_link: str | None) -> dict[str, Any]:
    handoff: dict[str, Any] = {"command": "/setup"}
    if agent_link is not None:
        handoff = _setup_handoff_for_link(
            agent_link,
            _resolve_link_target(agent_link, "", ""),
        )
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "setup-required",
        "branch": "workspace-not-prepared",
        "message": (
            "Basic ADK setup is not finished in this workspace. Setup runs "
            "first, then Connect continues."
        ),
        "setupHandoff": handoff,
        "stateChanged": False,
    }


def _chooser_option_labels(choices: list[dict[str, Any]]) -> list[str]:
    """Return display labels; IDs and slugs are never shown to the maker."""
    labels = [str(choice["name"]) for choice in choices]
    totals = {label: labels.count(label) for label in labels}
    # Only agents sharing a display name get a differentiator.
    labels = [
        label
        if totals[label] == 1
        else f"{label} — {choice['product']}"
        for label, choice in zip(labels, choices)
    ]
    totals = {label: labels.count(label) for label in labels}
    seen: dict[str, int] = {}
    unique: list[str] = []
    for label in labels:
        if totals[label] == 1:
            unique.append(label)
            continue
        # Same name and product: only an ordinal can tell them apart.
        seen[label] = seen.get(label, 0) + 1
        unique.append(f"{label} ({seen[label]})")
    return unique


def agent_chooser_handoff(
    root: Path = Path("."),
    *,
    selection_key: str | None = None,
    agent_link: str | None = None,
) -> dict[str, Any]:
    if agent_link is not None and selection_key not in (None, "another-agent"):
        raise ServiceNowConnectError(
            "An agent link can be supplied only for Use another agent."
        )
    if _workspace_not_prepared(root):
        return _unprepared_workspace_handoff(agent_link)
    environment, prepared_choices, incomplete_agents, unsupported_agents = (
        _prepared_agent_choices(root)
    )
    if agent_link is not None:
        return _resolve_explicit_agent_link(
            agent_link=agent_link,
            environment=environment,
            prepared_choices=prepared_choices,
            incomplete_agents=incomplete_agents,
            unsupported_agents=unsupported_agents,
        )
    if selection_key is not None:
        if selection_key == "another-agent":
            return {
                "schemaVersion": "servicenow.agent-chooser.v1",
                "status": "agent-link-required",
                "branch": "explicit-agent-link",
                "question": _agent_link_question(),
                "stateChanged": False,
            }
        prepared = next(
            (
                choice
                for choice in prepared_choices
                if selection_key == f"prepared:{choice['id']}"
            ),
            None,
        )
        if prepared is None:
            unfinished = next(
                (
                    agent
                    for agent in incomplete_agents
                    if selection_key == f"prepared:{agent['id']}"
                ),
                None,
            )
            if unfinished is not None:
                return _setup_incomplete_result(unfinished)
            raise ServiceNowConnectError(
                "The selected prepared agent is no longer available in this "
                "workspace. Choose again."
            )
        return _prepared_agent_result(prepared)

    labels = _chooser_option_labels(prepared_choices)
    options = [
        {
            "label": label,
            "selectionKey": f"prepared:{choice['id']}",
        }
        for choice, label in zip(prepared_choices, labels)
    ]
    options.append(
        {
            "label": "Another agent",
            "selectionKey": "another-agent",
        }
    )
    question_text = (
        "The listed agents are prepared in this workspace. This is not a "
        "list of every agent in the environment."
        if prepared_choices
        else (
            "No Employee Self-Service agents are prepared in this workspace. "
            "Choose Another agent and paste its Copilot Studio link."
        )
    )
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "choice-required",
        "branch": "choose-agent",
        "environmentId": environment.get("id"),
        "agents": prepared_choices,
        "question": {
            "header": "Which agent should we connect to ServiceNow?",
            "question": question_text,
            "options": options,
            "allowFreeformInput": False,
        },
        "stateChanged": False,
    }


def load_context(
    root: Path = Path("."),
    *,
    agent_id: str | None = None,
    agent_slug: str | None = None,
    maker_username: str | None = None,
) -> dict[str, Any]:
    setup = _load_json(root / SETUP_STATE)
    if setup.get("schema_version") != SETUP_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            f"Expected /setup schema {SETUP_SCHEMA_VERSION}."
        )
    if setup.get("intent") != "DA foundation setup":
        raise ServiceNowConnectError("The setup state is not DA foundation setup.")

    environment = setup.get("environment")
    config = _load_json(root / ACTIVE_CONFIG)
    operational_agents = config.get("agents")
    if not isinstance(environment, dict):
        raise ServiceNowConnectError("The setup handoff has no environment.")
    preferred_account = _validate_discovery_binding(environment, config)
    if not isinstance(operational_agents, list):
        raise ServiceNowConnectError("Operational setup config has no agent list.")
    if agent_id is None and agent_slug is None:
        active_slug = config.get("activeAgent")
        if not isinstance(active_slug, str) or not active_slug:
            raise ServiceNowConnectError("Operational config has no active agent.")
        active = next(
            (
                item
                for item in operational_agents
                if isinstance(item, dict) and item.get("slug") == active_slug
            ),
            None,
        )
        if not isinstance(active, dict):
            raise ServiceNowConnectError("Could not resolve the active setup agent.")
        active_bot_id = active.get("botId")
        if not isinstance(active_bot_id, str):
            raise ServiceNowConnectError("The active agent has no bot ID.")
        normalized_bot_id = _normalize_agent_id(active_bot_id)
    else:
        if agent_id is not None:
            normalized_bot_id = _normalize_agent_id(agent_id)
            active = _operational_agent(operational_agents, normalized_bot_id)
        else:
            active = next(
                (
                    item
                    for item in operational_agents
                    if isinstance(item, dict)
                    and item.get("slug") == agent_slug
                ),
                None,
            )
            selected_bot_id = (
                active.get("botId") if isinstance(active, dict) else None
            )
            if not isinstance(selected_bot_id, str):
                raise ServiceNowConnectError(
                    "The selected agent has no local /setup workspace."
                )
            normalized_bot_id = _normalize_agent_id(selected_bot_id)
        if not isinstance(active, dict):
            raise ServiceNowConnectError(
                "The selected agent has no local /setup workspace."
            )
        active_slug = active.get("slug")
        if not isinstance(active_slug, str) or not active_slug:
            raise ServiceNowConnectError(
                "The selected agent has no workspace slug."
            )

    canonical_agents = setup.get("agents")
    if not isinstance(canonical_agents, dict):
        raise ServiceNowConnectError("Canonical setup state has no agent map.")
    canonical = next(
        (
            value
            for key, value in canonical_agents.items()
            if isinstance(key, str)
            and key.casefold() == normalized_bot_id.casefold()
            and isinstance(value, dict)
        ),
        None,
    )
    if not isinstance(canonical, dict):
        raise ServiceNowConnectError(
            "The active agent has no canonical /setup record."
        )
    agent = canonical.get("agent")
    if not isinstance(agent, dict):
        raise ServiceNowConnectError("The setup record has no agent identity.")
    if str(agent.get("id") or "").casefold() != normalized_bot_id.casefold():
        raise ServiceNowConnectError(
            "Canonical setup state and active agent config identify different agents."
        )
    if agent.get("workspace_slug") != active_slug:
        raise ServiceNowConnectError(
            "Canonical setup state and active workspace identify different agents."
        )
    if not _canonical_local_authoring_ready(canonical, agent):
        raise ServiceNowConnectError("/connect only supports the editable Dev realm.")
    if agent.get("schema_name") != AGENT_SCHEMA_NAME:
        raise ServiceNowConnectError(
            f"This provider supports only {ACTIVE_PROFILE.agent_display_name}."
        )
    if not _canonical_authoring_ready(canonical):
        raise ServiceNowConnectError(
            "DA foundation setup is not ready for authoring."
        )
    workspace = canonical.get("workspace")
    if (
        not isinstance(workspace, dict)
        or not workspace.get("folder")
        or not workspace.get("agent_path")
    ):
        raise ServiceNowConnectError(
            "DA foundation setup has no materialized agent workspace."
        )

    relative_snapshot = active.get("agentBuilderChangeSetPath")
    if not isinstance(relative_snapshot, str) or not relative_snapshot:
        raise ServiceNowConnectError("The active agent has no component snapshot path.")
    snapshot_path = root / Path(relative_snapshot)
    context: dict[str, Any] = {
        "root": root,
        "setup": setup,
        "agentSetup": canonical,
        "config": config,
        "environment": environment,
        "agent": agent,
        "active": active,
        "account": preferred_account,
        "profile": ACTIVE_PROFILE,
        "snapshotPath": snapshot_path,
    }
    explicit_account = str(maker_username or "").strip() or None
    pinned_account = _recorded_maker_account(context)
    context["accountPin"] = pinned_account
    context["account"] = explicit_account or pinned_account or preferred_account
    _remember_agent_name(context)
    return context


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _profile_topic_suffix(change: dict[str, Any]) -> str | None:
    component = change.get("component")
    if (
        not isinstance(component, dict)
        or component.get("$kind") != "DialogComponent"
        or not isinstance(component.get("dialog"), dict)
    ):
        return None
    schema_name = str(component.get("schemaName") or "")
    schema_prefix = f"{ACTIVE_PROFILE.schema_name}.topic."
    if not schema_name.casefold().startswith(schema_prefix.casefold()):
        return None
    suffix = schema_name[len(schema_prefix):]
    namespace = (
        "servicenowhrsd"
        if ACTIVE_PROFILE.key == "hrsd"
        else "servicenowitsm"
    )
    return suffix if suffix.casefold().startswith(namespace) else None


def _servicenow_topic_changes(
    components: dict[str, Any],
) -> list[dict[str, Any]]:
    changes = components.get("botComponentChanges")
    if not isinstance(changes, list):
        raise ServiceNowConnectError(
            "Agent components have an invalid topic collection."
        )
    return [
        change
        for change in changes
        if isinstance(change, dict) and _profile_topic_suffix(change) is not None
    ]


def find_servicenow_reference(components: dict[str, Any]) -> dict[str, Any]:
    matches = []
    for change in components.get("connectionReferenceChanges") or []:
        if not isinstance(change, dict):
            continue
        reference = change.get("connectionReference")
        if (
            isinstance(reference, dict)
            and str(reference.get("connectorId") or "").casefold()
            == CONNECTOR_ID.casefold()
        ):
            matches.append(reference)
    if len(matches) != 1:
        raise ServiceNowConnectError(
            "Expected exactly one ServiceNow connection reference; "
            f"found {len(matches)}."
        )
    return matches[0]


def _shared_parameters(reference: dict[str, Any]) -> dict[str, Any]:
    raw = reference.get("sharedConnectionParameters")
    if not raw:
        return {}
    if isinstance(raw, dict):
        value = raw
    elif isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ServiceNowConnectError(
                "ServiceNow shared connection parameters are invalid JSON."
            ) from exc
    else:
        raise ServiceNowConnectError(
            "ServiceNow shared connection parameters have an invalid shape."
        )
    return value if isinstance(value, dict) else {}


def _parameter_value(parameters: dict[str, Any], name: str) -> str | None:
    values = parameters.get("values")
    if not isinstance(values, dict):
        return None
    item = values.get(name)
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    return str(value) if value not in (None, "") else None


def summarize_components(components: dict[str, Any]) -> dict[str, Any]:
    reference = find_servicenow_reference(components)
    service_now_topics = _servicenow_topic_changes(components)
    action_counts = {"InvokeFlowAction": 0, "InvokeConnectorAction": 0}
    service_now_action_counts = {"InvokeFlowAction": 0, "InvokeConnectorAction": 0}
    flow_ids: set[str] = set()
    for change in components.get("botComponentChanges") or []:
        is_service_now = (
            isinstance(change, dict)
            and _profile_topic_suffix(change) is not None
        )
        for node in _walk(change):
            kind = node.get("$kind")
            if kind in action_counts:
                action_counts[kind] += 1
                if is_service_now:
                    service_now_action_counts[kind] += 1
            flow_id = node.get("flowId")
            if isinstance(flow_id, str) and flow_id:
                flow_ids.add(flow_id)

    parameters = _shared_parameters(reference)
    topic_summaries = sorted(
        (
            {
                "id": change["component"].get("id"),
                "version": change["component"].get("version"),
                "displayName": change["component"].get("displayName"),
                "schemaName": change["component"].get("schemaName"),
                "state": change["component"].get("state"),
                "status": change["component"].get("status"),
            }
            for change in service_now_topics
            if isinstance(change.get("component"), dict)
        ),
        key=lambda item: str(item.get("displayName") or ""),
    )
    return {
        "profile": {
            "key": ACTIVE_PROFILE.key,
            "provider": ACTIVE_PROFILE.provider_key,
            "productName": ACTIVE_PROFILE.product_name,
            "agentDisplayName": _spec_agent_name(),
            "testPrompt": ACTIVE_PROFILE.test_prompt,
        },
        "botComponentCount": len(components.get("botComponentChanges") or []),
        "serviceNowTopicCount": len(service_now_topics),
        "activeServiceNowTopicCount": sum(
            1
            for change in service_now_topics
            if isinstance(change.get("component"), dict)
            and change["component"].get("state") == "Active"
            and change["component"].get("status") == "Active"
        ),
        "serviceNowTopics": topic_summaries,
        "connectionReferenceCount": len(
            components.get("connectionReferenceChanges") or []
        ),
        "connectorDefinitionCount": len(
            components.get("connectorDefinitionChanges") or []
        ),
        "cloudFlowDefinitionCount": len(
            components.get("cloudFlowDefinitionChanges") or []
        ),
        "invokeFlowActionCount": action_counts["InvokeFlowAction"],
        "invokeConnectorActionCount": action_counts["InvokeConnectorAction"],
        "serviceNowInvokeFlowActionCount": service_now_action_counts[
            "InvokeFlowAction"
        ],
        "serviceNowInvokeConnectorActionCount": service_now_action_counts[
            "InvokeConnectorAction"
        ],
        "flowIds": sorted(flow_ids),
        "reference": {
            "id": reference.get("id"),
            "connectionId": reference.get("connectionId"),
            "logicalName": reference.get("connectionReferenceLogicalName"),
            "displayName": reference.get("displayName"),
            "authMode": parameters.get("name"),
            "instanceName": _parameter_value(
                parameters,
                "token:InstanceName",
            ),
            "resourceUri": _parameter_value(
                parameters,
                "token:ResourceUri",
            ),
        },
        "hasChangeToken": bool(components.get("changeToken")),
    }


def connectivity_scopes(ring: str) -> list[str]:
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ServiceNowConnectError(f"Unsupported Power Platform ring: {ring}")
    audience = str(config["audience"])
    return [
        f"{audience}/Connectivity.Connections.Read",
        f"{audience}/Connectivity.Connectors.Read",
        f"{audience}/Connectivity.ConnectionPermissions.Read",
    ]


class ConnectivityClient:
    """Small client for the per-environment Power Platform Connectivity API."""

    def __init__(
        self,
        host: str,
        environment_id: str,
        token: str,
        *,
        ring: str,
        session: requests.Session | None = None,
    ) -> None:
        self.host = validate_environment_host(host, ring)
        self.environment_id = str(uuid.UUID(environment_id))
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-ms-client-name": "EssAdk",
        }

    def _filter(self) -> str:
        return f"environment eq '{self.environment_id}'"

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        include_filter: bool = True,
        timeout: int = CONNECTIVITY_READ_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        params = {"api-version": CONNECTIVITY_API_VERSION}
        if include_filter:
            params["$filter"] = self._filter()
        try:
            response = self.session.request(
                method,
                f"{self.host}{path}",
                params=params,
                headers=headers,
                json=body,
                timeout=timeout,
            )
        except requests.Timeout as exc:
            raise ServiceNowConnectError(
                "ServiceNow connection discovery reached the configured "
                f"{timeout}-second HTTP connect/read timeout. This is not a "
                "whole-invocation deadline and does not include interactive "
                "authorization. No remote write was attempted. Check network "
                "access, then retry `/connect servicenow`.",
                details={
                    "category": "timeout",
                    "timeoutSeconds": timeout,
                    "mutationMayHaveOccurred": False,
                    "retryable": True,
                },
            ) from exc
        except requests.RequestException as exc:
            raise ServiceNowConnectError(
                "ServiceNow connection discovery could not reach the Power "
                "Platform Connectivity API. No remote write was attempted. "
                "Check network access, then retry `/connect servicenow`.",
                details={
                    "category": "transport",
                    "errorType": type(exc).__name__,
                    "mutationMayHaveOccurred": False,
                    "retryable": True,
                },
            ) from exc
        if not response.ok:
            error_code = None
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error") or payload
                if isinstance(error, dict):
                    error_code = error.get("code")
            detail = f"Connectivity API returned HTTP {response.status_code}"
            if error_code:
                detail += f" ({error_code})"
            retry_after = response.headers.get("Retry-After")
            request_id = next(
                (
                    response.headers.get(name)
                    for name in (
                        "x-ms-service-request-id",
                        "x-ms-request-id",
                        "request-id",
                    )
                    if response.headers.get(name)
                ),
                None,
            )
            if retry_after:
                detail += f" [retry-after {retry_after}]"
            if request_id:
                detail += f" [request {request_id}]"
            raise ServiceNowConnectError(
                detail,
                details={
                    "category": (
                        "throttled"
                        if response.status_code == 429
                        else "http"
                    ),
                    "statusCode": response.status_code,
                    "errorCode": error_code,
                    "retryAfter": retry_after,
                    "requestId": request_id,
                    "mutationMayHaveOccurred": False,
                    "retryable": response.status_code
                    in {408, 429, 500, 502, 503, 504},
                },
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise ServiceNowConnectError(
                "Connectivity API returned non-JSON content."
            ) from exc
        if not isinstance(value, dict):
            raise ServiceNowConnectError(
                "Connectivity API returned an invalid JSON shape."
            )
        return value

    def list_connections(self) -> list[dict[str, Any]]:
        body = self._request(
            "GET",
            f"/connectivity/connectors/{CONNECTOR_NAME}/connections",
        )
        values = body.get("value")
        if not isinstance(values, list):
            raise ServiceNowConnectError(
                "Connection listing returned an invalid shape."
            )
        return [value for value in values if isinstance(value, dict)]

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        normalized = uuid.UUID(connection_id).hex
        return self._request(
            "GET",
            f"/connectivity/connectors/{CONNECTOR_NAME}/connections/"
            f"{quote(normalized, safe='')}",
        )

def connection_summary(record: dict[str, Any]) -> dict[str, Any]:
    properties = record.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    statuses = properties.get("statuses")
    if not isinstance(statuses, list):
        statuses = []
    selected = next(
        (
            status
            for status in statuses
            if isinstance(status, dict) and status.get("target") == "token"
        ),
        next((status for status in statuses if isinstance(status, dict)), {}),
    )
    parameter_set = properties.get("connectionParametersSet")
    if not isinstance(parameter_set, dict):
        parameter_set = {}
    values = parameter_set.get("values")
    visible_values = {}
    if isinstance(values, dict):
        visible_values = {
            key: value.get("value")
            for key, value in values.items()
            if key in {
                "instance",
                "token:InstanceName",
                "token:ResourceUri",
            }
            if isinstance(value, dict) and "value" in value
        }
    return {
        "connectionId": record.get("name"),
        "displayName": properties.get("displayName"),
        "status": selected.get("status"),
        "statusTarget": selected.get("target"),
        "authMode": parameter_set.get("name"),
        "parameterValues": visible_values,
    }


def find_servicenow_topic(
    components: dict[str, Any],
    topic_id: str,
) -> dict[str, Any]:
    normalized_topic_id = str(uuid.UUID(topic_id))
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            isinstance(component, dict)
            and str(component.get("id") or "").casefold()
            == normalized_topic_id.casefold()
            and _profile_topic_suffix(change) is not None
        ):
            return component
    raise ServiceNowConnectError(
        "The requested ServiceNow topic was not found in the active agent."
    )


def build_topic_state_update_payload(
    components: dict[str, Any],
    topic_id: str,
    target_state: str,
) -> dict[str, Any]:
    if target_state not in {"Active", "Inactive"}:
        raise ServiceNowConnectError(
            "Topic state must be Active or Inactive."
        )
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    component = copy.deepcopy(find_servicenow_topic(components, topic_id))
    if component.get("$kind") != "DialogComponent":
        raise ServiceNowConnectError(
            "The requested ServiceNow component is not a dialog topic."
        )
    if not component.get("id") or not isinstance(component.get("version"), int):
        raise ServiceNowConnectError(
            "The requested ServiceNow topic lacks identity or version evidence."
        )
    component["state"] = target_state
    component["status"] = target_state
    return {
        "changeToken": change_token,
        "botComponentChanges": [
            {
                "$kind": "BotComponentUpdate",
                "component": component,
            }
        ],
    }


def build_enable_all_topics_payload(
    components: dict[str, Any],
) -> dict[str, Any]:
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    changes = []
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            not isinstance(component, dict)
            or _profile_topic_suffix(change) is None
            or (
                component.get("state") == "Active"
                and component.get("status") == "Active"
            )
        ):
            continue
        topic_id = component.get("id")
        if not topic_id:
            raise ServiceNowConnectError(
                "A ServiceNow topic lacks identity evidence."
            )
        topic_payload = build_topic_state_update_payload(
            components,
            str(topic_id),
            "Active",
        )
        changes.extend(topic_payload["botComponentChanges"])
    return {
        "changeToken": change_token,
        "botComponentChanges": changes,
    }


def _portal_topic_component(
    components: dict[str, Any],
) -> dict[str, Any]:
    matches = []
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            isinstance(component, dict)
            and str(component.get("schemaName") or "").endswith(
                PORTAL_TOPIC_SCHEMA_SUFFIX
            )
        ):
            matches.append(component)
    if len(matches) != 1:
        raise ServiceNowConnectError(
            f"Expected exactly one {ACTIVE_PROFILE.product_name} Setup "
            "Configurations topic; "
            f"found {len(matches)}."
        )
    topic = matches[0]
    if (
        topic.get("$kind") != "DialogComponent"
        or not topic.get("id")
        or not isinstance(topic.get("version"), int)
    ):
        raise ServiceNowConnectError(
            "The ServiceNow portal configuration topic lacks safe dialog "
            "identity or version evidence."
        )
    return topic


def _portal_value_nodes(value: Any) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if (
            value.get("$kind") == "SetVariable"
            and value.get("displayName") == PORTAL_NODE_DISPLAY_NAME
            and value.get("variable") == PORTAL_VARIABLE_NAME
        ):
            matches.append(value)
        for child in value.values():
            matches.extend(_portal_value_nodes(child))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_portal_value_nodes(child))
    return matches


def _portal_value_node(topic: dict[str, Any]) -> dict[str, Any]:
    matches = _portal_value_nodes(topic.get("dialog"))
    if len(matches) != 1:
        raise ServiceNowConnectError(
            "Expected exactly one Set ServiceNow Portal BaseURI node; "
            f"found {len(matches)}."
        )
    node = matches[0]
    _decode_portal_value(node.get("value"))
    return node


def _decode_portal_value(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ServiceNowConnectError(
            "The ServiceNow Portal BaseURI node has an unsupported value shape."
        )
    if set(value) == {"$kind", "literalValue"}:
        kind = value.get("$kind")
        literal = value.get("literalValue")
        if (
            kind not in {"Literal", "PowerFx", "ValueExpression"}
            or not isinstance(literal, str)
        ):
            raise ServiceNowConnectError(
                "The ServiceNow Portal BaseURI value is not a supported "
                "string literal."
            )
        return "literalValue", literal
    if set(value) == {"$kind", "expressionText"}:
        if value.get("$kind") != "ValueExpression":
            raise ServiceNowConnectError(
                "The ServiceNow Portal BaseURI expression has an unsupported "
                "kind."
            )
        expression = value.get("expressionText")
        if not isinstance(expression, str) or expression != expression.strip():
            raise ServiceNowConnectError(
                "The ServiceNow Portal BaseURI expression must be one quoted "
                "string literal."
            )
        try:
            literal = json.loads(expression)
        except json.JSONDecodeError as exc:
            raise ServiceNowConnectError(
                "The ServiceNow Portal BaseURI expression must be one quoted "
                "string literal."
            ) from exc
        if not isinstance(literal, str):
            raise ServiceNowConnectError(
                "The ServiceNow Portal BaseURI expression must resolve to a "
                "string literal."
            )
        return "expressionText", literal
    raise ServiceNowConnectError(
        "The ServiceNow Portal BaseURI node has an unsupported value shape."
    )


def _write_portal_value(value: dict[str, Any], literal: str) -> None:
    field, _current = _decode_portal_value(value)
    if field == "literalValue":
        value[field] = literal
    else:
        value[field] = json.dumps(literal, ensure_ascii=True)


def normalize_portal_url(
    value: str,
    *,
    expected_instance_name: str,
) -> str:
    stripped = value.strip()
    parsed = urlparse(stripped)
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ServiceNowConnectError(
            "ServiceNow portal URL has an invalid network port."
        ) from exc
    if (
        any(character.isspace() for character in stripped)
        or parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.params
        or parsed_port not in {None, 443}
    ):
        raise ServiceNowConnectError(
            "ServiceNow portal URL must be a plain HTTPS URL without "
            "credentials, query, fragment, or a nonstandard port."
        )
    expected_host = f"{expected_instance_name}.service-now.com"
    if parsed.hostname.casefold() != expected_host.casefold():
        raise ServiceNowConnectError(
            "ServiceNow portal URL must use the confirmed ServiceNow instance."
        )
    path = parsed.path.rstrip("/")
    return f"https://{expected_host}{path}"


def build_portal_url_update_payload(
    components: dict[str, Any],
    portal_url: str,
    *,
    expected_instance_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    change_token = components.get("changeToken")
    if not isinstance(change_token, str) or not change_token:
        raise ServiceNowConnectError(
            "MinimalBot component state has no concurrency change token."
        )
    before = copy.deepcopy(_portal_topic_component(components))
    updated = copy.deepcopy(before)
    node = _portal_value_node(updated)
    normalized_url = normalize_portal_url(
        portal_url,
        expected_instance_name=expected_instance_name,
    )
    _write_portal_value(node["value"], normalized_url)
    payload = {
        "changeToken": change_token,
        "botComponentChanges": [
            {
                "$kind": "BotComponentUpdate",
                "component": updated,
            }
        ],
    }
    return payload, before, updated


def _portal_literal_value(topic: dict[str, Any]) -> str:
    _field, literal = _decode_portal_value(
        _portal_value_node(topic)["value"]
    )
    return literal


def portal_configuration_summary(
    components: dict[str, Any],
    *,
    expected_instance_name: str | None = None,
) -> dict[str, Any]:
    topic = _portal_topic_component(components)
    literal = _portal_literal_value(topic).strip()
    summary = {
        "topicId": topic.get("id"),
        "topicSchemaName": topic.get("schemaName"),
        "topicDisplayName": topic.get("displayName"),
        "topicState": topic.get("state"),
        "topicStatus": topic.get("status"),
        "variable": PORTAL_VARIABLE_NAME,
        "configured": False,
        "valid": False,
        "origin": None,
        "path": None,
        "reason": "missing",
    }
    if not literal:
        return summary
    if re.fullmatch(
        r"https://<instance>\.service-now\.com(?:/[^?#]*)?",
        literal,
        flags=re.IGNORECASE,
    ):
        summary["reason"] = "placeholder"
        return summary
    parsed = urlparse(literal)
    summary["origin"] = (
        f"{parsed.scheme}://{parsed.hostname}"
        if parsed.scheme and parsed.hostname
        else None
    )
    summary["path"] = parsed.path or "/"
    summary["configured"] = True
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        summary["reason"] = "invalid-url"
        return summary
    if expected_instance_name and (
        parsed.hostname.casefold()
        != f"{expected_instance_name}.service-now.com".casefold()
    ):
        summary["reason"] = "wrong-instance"
        return summary
    summary["valid"] = True
    summary["reason"] = "valid"
    return summary


def _component_hash(components: dict[str, Any]) -> str:
    encoded = json.dumps(
        components,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _agentbuilder_client(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
) -> AgentBuilderClient:
    environment = context["environment"]
    token = _agentbuilder_token(
        context,
        force_account_selection=force_account_selection,
    )
    return AgentBuilderClient(
        environment["power_platform_api_endpoint"],
        token,
        ring=environment["ring"],
        tenant_id=environment["tenant_id"],
        api_version=environment.get("api_version", "2024-10-01"),
    )


def _agentbuilder_token(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
) -> str:
    return _authenticate_maker(
        context,
        force_account_selection=force_account_selection,
    )


MAKER_ACCOUNT_KEY = "makerAccount"


def _maker_account_from_state(state: Any) -> str | None:
    record = state.get(MAKER_ACCOUNT_KEY) if isinstance(state, dict) else None
    username = record.get("username") if isinstance(record, dict) else None
    return username.strip() or None if isinstance(username, str) else None


def _recorded_maker_account(context: dict[str, Any]) -> str | None:
    """Read the Maker account pinned in this agent's Connect state."""
    path = _lifecycle_state_path(context)
    if not path.is_file():
        return None
    try:
        state = _load_json(path)
    except ServiceNowConnectError:
        return None
    if state_integrity_mismatch(state):
        return None
    return _maker_account_from_state(state)


def _authenticate_maker(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
    scopes: tuple[str, ...] | None = None,
) -> str:
    environment = context["environment"]
    extra: dict[str, Any] = {} if scopes is None else {"scopes": scopes}
    try:
        result = authenticate(
            environment["tenant_id"],
            environment["ring"],
            cache_path=TOKEN_CACHE,
            force_account_selection=force_account_selection,
            account_hint=context.get("account"),
            require_account_identity=True,
            return_account_identity=True,
            **extra,
        )
    except AgentBuilderAccountMismatch as exc:
        pinned = context.get("accountPin")
        expected = context.get("account")
        if pinned and expected and pinned.casefold() == expected.casefold():
            raise ServiceNowConnectError(
                "This ServiceNow Connect run is pinned to the Maker account "
                f"{pinned}, but sign-in used a different account. Sign in "
                "again with the pinned account.",
                details={"decision": "stop-account-mismatch"},
            ) from exc
        raise
    token, account = result if isinstance(result, tuple) else (result, None)
    _record_verified_maker_account(context, account)
    return token


def _record_verified_maker_account(
    context: dict[str, Any],
    account: str | None,
) -> None:
    """Pin the verified Maker account in Connect's own lifecycle state."""
    if not account or not isinstance(context.get("agent"), dict):
        return
    context["verifiedAccount"] = account
    path = _lifecycle_state_path(context)
    if not path.is_file():
        return
    try:
        state = _load_json(path)
    except ServiceNowConnectError:
        return
    if state_integrity_mismatch(state):
        return
    recorded = _maker_account_from_state(state)
    if recorded and recorded.casefold() == account.casefold():
        return
    state[MAKER_ACCOUNT_KEY] = {"username": account}
    state[STATE_INTEGRITY_KEY] = state_integrity_digest(state)
    _write_json_atomic(path, state)


def _connectivity_client(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
) -> ConnectivityClient:
    environment = context["environment"]
    token = _authenticate_maker(
        context,
        force_account_selection=force_account_selection,
        scopes=tuple(connectivity_scopes(environment["ring"])),
    )
    return ConnectivityClient(
        environment["power_platform_api_endpoint"],
        environment["id"],
        token,
        ring=environment["ring"],
    )


def _state_base(
    context: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    summary = summarize_components(components)
    return {
        "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "intent": f"DA-GA {ACTIVE_PROFILE.product_name} connection",
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "agentSchemaName": context["agent"]["schema_name"],
        "tenantId": context["environment"].get("tenant_id"),
        "environmentId": context["environment"]["id"],
        "ring": context["environment"]["ring"],
        "componentHash": _component_hash(components),
        "draftSemanticHash": _draft_semantic_hash(components),
        "reference": summary["reference"],
        "phases": {},
        "evidence": {},
        "adminSetup": _empty_admin_setup(),
        "transactions": {"topics": {}},
        "businessGroupAcknowledgements": {},
        "migration": {},
        "updatedAt": _utc_now(),
    }


def initialize_lifecycle_state(
    context: dict[str, Any],
    *,
    contract_revision: int,
) -> dict[str, Any]:
    if (
        not isinstance(contract_revision, int)
        or isinstance(contract_revision, bool)
        or contract_revision < 1
    ):
        raise ServiceNowConnectError(
            "Contract revision must be a positive integer."
        )
    contract = _load_json(context["root"] / CONTRACT_PATH)
    if (
        contract.get("provider") != PROVIDER_KEY
        or contract.get("profile") != PROFILE_KEY
        or contract.get("contractRevision") != contract_revision
    ):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle contract identity or revision does not "
            "match the initialization request."
        )
    phases = contract.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ServiceNowConnectError(
            "ServiceNow lifecycle contract has no phases."
        )
    phase_ids: list[str] = []
    for phase in phases:
        phase_id = phase.get("id") if isinstance(phase, dict) else None
        if (
            not isinstance(phase_id, str)
            or not phase_id
            or phase_id in phase_ids
        ):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle contract has invalid phase IDs."
            )
        phase_ids.append(phase_id)

    path = _lifecycle_state_path(context)
    if path.exists():
        before = path.read_bytes()
        state = _load_json(path)
        expected_identity: dict[str, Any] = {
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "environmentId": context["environment"]["id"],
            "ring": context["environment"]["ring"],
        }
        tenant_id = context["environment"].get("tenant_id")
        if tenant_id:
            expected_identity["tenantId"] = tenant_id
        for key, expected in expected_identity.items():
            recorded = state.get(key)
            if (
                not isinstance(recorded, str)
                or not recorded
                or recorded.casefold() != str(expected).casefold()
            ):
                raise ServiceNowConnectError(
                    "Existing ServiceNow lifecycle state does not match the "
                    f"active {key}."
                )
        schema_version = state.get("schemaVersion")
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version < 1
            or schema_version > LIFECYCLE_SCHEMA_VERSION
        ):
            raise ServiceNowConnectError(
                "Existing ServiceNow lifecycle state has an invalid schema."
            )
        if state.get("attested") is not True or not isinstance(
            state.get("attestedAt"),
            str,
        ):
            raise ServiceNowConnectError(
                "Existing ServiceNow lifecycle state is not attested."
            )
        if state.get("acceptedContractRevision") != contract_revision:
            raise ServiceNowConnectError(
                "Existing ServiceNow lifecycle state has not accepted the "
                "requested contract revision."
            )
        state_phases = state.get("phases")
        if not isinstance(state_phases, dict):
            raise ServiceNowConnectError(
                "Existing ServiceNow lifecycle state has no phase map."
            )
        for phase_id in phase_ids:
            phase_state = state_phases.get(phase_id)
            if (
                not isinstance(phase_state, dict)
                or phase_state.get("status")
                not in {"pending", "in-progress", "done", "blocked"}
                or not isinstance(
                    phase_state.get("checkpointResults"),
                    dict,
                )
            ):
                raise ServiceNowConnectError(
                    "Existing ServiceNow lifecycle state has invalid phase "
                    f"{phase_id!r}."
                )
        if path.read_bytes() != before:
            raise ServiceNowConnectError(
                "Existing ServiceNow lifecycle state changed during "
                "compatibility validation."
            )
        return {
            "status": "existing-compatible-state",
            "statePath": str(path),
            "stateExists": True,
            "preservedExistingState": True,
            "schemaVersion": schema_version,
            "provider": state["provider"],
            "profile": state["profile"],
            "agentSlug": state["agentSlug"],
            "agentId": state["agentId"],
            "environmentId": state["environmentId"],
            "acceptedContractRevision": state[
                "acceptedContractRevision"
            ],
            "phaseIds": phase_ids,
        }

    components = _load_json(context["snapshotPath"])
    state = _state_base(context, components)
    state.update(
        {
            "attested": True,
            "attestedAt": _utc_now(),
            "acceptedContractRevision": contract_revision,
            "roleAttestations": {},
            "phases": {
                phase_id: {
                    "status": "pending",
                    "checkpointResults": {},
                    "checkpointAcknowledgements": {},
                }
                for phase_id in phase_ids
            },
        }
    )
    events = _prepare_lifecycle_telemetry(
        context,
        None,
        state,
        timestamp=state["updatedAt"],
        new_lifecycle=True,
        required_phase_ids=tuple(phase_ids),
    )
    _create_json_atomic_no_clobber(path, state)
    for event in events:
        try:
            emit_servicenow_lifecycle_event(state, event)
        except Exception:  # noqa: BLE001 - telemetry cannot break Connect
            continue
    return {
        "status": "initialized",
        "statePath": str(path),
        "stateExists": False,
        "preservedExistingState": False,
        "schemaVersion": state["schemaVersion"],
        "provider": state["provider"],
        "profile": state["profile"],
        "agentSlug": state["agentSlug"],
        "agentId": state["agentId"],
        "environmentId": state["environmentId"],
        "acceptedContractRevision": state["acceptedContractRevision"],
        "phaseIds": phase_ids,
    }


def _canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_state_identity(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    expected = {
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
    }
    for key, value in expected.items():
        recorded = state.get(key)
        if (
            not isinstance(recorded, str)
            or not recorded
            or recorded.casefold() != str(value).casefold()
        ):
            raise ServiceNowConnectError(
                f"ServiceNow lifecycle {key} does not match the active agent."
            )


def _validate_legacy_state_identity(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    for key, value in {
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
    }.items():
        recorded = state.get(key)
        if (
            not isinstance(recorded, str)
            or not recorded
            or recorded.casefold() != str(value).casefold()
        ):
            raise ServiceNowConnectError(
                f"Legacy ServiceNow state {key} does not match the active agent."
            )


def _migrate_lifecycle_schema(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    version = state.get("schemaVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle schemaVersion must be an integer."
        )
    if version > LIFECYCLE_SCHEMA_VERSION:
        raise ServiceNowConnectError(
            "ServiceNow lifecycle state was written by a newer kit version."
        )
    if version < 2:
        raise ServiceNowConnectError(
            "Unsupported canonical ServiceNow lifecycle schema."
        )
    if version == LIFECYCLE_SCHEMA_VERSION:
        _admin_setup(state)
        return state

    source_sha256 = _canonical_json_hash(state)
    phases = state.setdefault("phases", {})
    if not isinstance(phases, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle phases must be an object."
        )
    migration = state.setdefault("migration", {})
    if not isinstance(migration, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle migration state must be an object."
        )

    if version == 2:
        added_phase_ids = [
            "preflight",
            "plugin-prerequisites",
            "entra-registration",
            "servicenow-oidc",
        ]
        for phase_id in added_phase_ids:
            phases.setdefault(
                phase_id,
                {
                    "status": "pending",
                    "checkpointResults": {},
                    "checkpointAcknowledgements": {},
                },
            )

        invalidated_phase_ids: list[str] = []
        credential = phases.setdefault(
            "credential",
            {"status": "pending", "checkpointResults": {}},
        )
        if not isinstance(credential, dict):
            raise ServiceNowConnectError(
                "ServiceNow credential phase must be an object."
            )
        credential["status"] = "in-progress"
        credential["checkpointResults"] = {}
        credential["checkpointAcknowledgements"] = {}
        for key in ("actionApplied", "lastActionAt", "lastVerifiedAt"):
            credential.pop(key, None)
        invalidated_phase_ids.append("credential")

        for phase_id in (
            "topics",
            "agent-connection",
            "parameter-sharing",
            "publish",
            "test",
        ):
            phase = phases.get(phase_id)
            if not isinstance(phase, dict):
                continue
            phase["status"] = "pending"
            phase["checkpointResults"] = {}
            phase["checkpointAcknowledgements"] = {}
            phase.pop("lastVerifiedAt", None)
            invalidated_phase_ids.append(phase_id)

        state["schemaVersion"] = 3
        state.setdefault("acceptedContractRevision", 1)
        migration["schemaV3"] = {
            "from": version,
            "to": 3,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "addedPhaseIds": added_phase_ids,
            "invalidatedPhaseIds": invalidated_phase_ids,
            "reuseApprovalInferred": False,
        }

    raw_admin_setup = state.get("adminSetup")
    raw_oidc_handoff = (
        raw_admin_setup.get("phaseHandoffs", {}).get("servicenow-oidc")
        if isinstance(raw_admin_setup, dict)
        and isinstance(raw_admin_setup.get("phaseHandoffs"), dict)
        else None
    )
    inferred_oidc_capability = _legacy_oidc_handoff_proves_capability(
        raw_oidc_handoff
    )
    setup = _admin_setup(state)
    retained_preflight = _normalize_preflight_handoff(state, setup)
    if version <= 3:
        migration["schemaV4"] = {
            "from": 3,
            "to": 4,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "removedGlobalReuseDecision": True,
            "retainedCompletedPreflight": retained_preflight,
        }
    if version <= 4:
        migration["schemaV5"] = {
            "from": 4,
            "to": 5,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "removedScenarioGate": True,
            "retainedCompletedPreflight": retained_preflight,
            "inferredOidcCapabilityFromCompletedHandoff": (
                inferred_oidc_capability
            ),
        }
    retired_parameter_sharing = None
    if version < 6:
        retired_phases = state.setdefault("retiredPhases", {})
        if not isinstance(retired_phases, dict):
            raise ServiceNowConnectError(
                "ServiceNow retiredPhases state must be an object."
            )
        retired_parameter_sharing = phases.pop("parameter-sharing", None)
        if retired_parameter_sharing is not None:
            retired_phases.setdefault(
                "parameter-sharing",
                retired_parameter_sharing,
            )
        state["schemaVersion"] = 6
        migration["schemaV6"] = {
            "from": 5 if version <= 5 else version,
            "to": 6,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "collapsedOidcMappingEvidence": inferred_oidc_capability,
            "removedOidcMappingCollection": True,
            "retiredParameterSharingPhase": (
                retired_parameter_sharing is not None
            ),
            "testBeforePublish": True,
        }
    retired_publish = None
    if version < 7:
        retired_phases = state.setdefault("retiredPhases", {})
        if not isinstance(retired_phases, dict):
            raise ServiceNowConnectError(
                "ServiceNow retiredPhases state must be an object."
            )
        retired_publish = phases.pop("publish", None)
        if retired_publish is not None:
            retired_phases.setdefault("publish", retired_publish)
        state["schemaVersion"] = 7
        migration["schemaV7"] = {
            "from": 6 if version <= 6 else version,
            "to": 7,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "retiredAutomaticPublishPhase": retired_publish is not None,
            "preservedPublishEvidence": isinstance(
                state.get("evidence", {}).get("publish"),
                dict,
            ),
            "connectCompletionEndsAtTest": True,
        }
    retired_entra_checkpoints: list[str] = []
    if version < 8:
        entra_phase = phases.get("entra-registration")
        if isinstance(entra_phase, dict):
            results = entra_phase.get("checkpointResults")
            acknowledgements = entra_phase.get("checkpointAcknowledgements")
            results = results if isinstance(results, dict) else {}
            acknowledgements = (
                acknowledgements
                if isinstance(acknowledgements, dict)
                else {}
            )
            retired_results = state.setdefault(
                "retiredCheckpointResults",
                {},
            )
            if not isinstance(retired_results, dict):
                raise ServiceNowConnectError(
                    "ServiceNow retired checkpoint results must be an object."
                )
            retired_entra = retired_results.setdefault(
                "entra-registration",
                {},
            )
            if not isinstance(retired_entra, dict):
                raise ServiceNowConnectError(
                    "Retired Entra checkpoint results must be an object."
                )
            for checkpoint_id in list(results):
                if not any(
                    checkpoint_id.endswith(
                        f"-ENTRA-{suffix}-001"
                    )
                    for suffix in RETIRED_ENTRA_CHECKPOINT_SUFFIXES
                ):
                    continue
                retired_entra.setdefault(
                    checkpoint_id,
                    {
                        "status": results[checkpoint_id],
                        "acknowledgement": copy.deepcopy(
                            acknowledgements.get(checkpoint_id)
                        ),
                        "retiredAt": _utc_now(),
                        "reason": (
                            "Graph permission and Graph AllPrincipals checks "
                            "are not ServiceNow Connect completion gates."
                        ),
                    },
                )
                results.pop(checkpoint_id, None)
                acknowledgements.pop(checkpoint_id, None)
                retired_entra_checkpoints.append(checkpoint_id)
            entra_phase["checkpointResults"] = results
            entra_phase["checkpointAcknowledgements"] = acknowledgements
        state["schemaVersion"] = 8
        migration["schemaV8"] = {
            "from": 7 if version <= 7 else version,
            "to": 8,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "retiredEntraCheckpointIds": sorted(
                retired_entra_checkpoints
            ),
            "preservedEntraAdminEvidence": isinstance(
                state.get("adminSetup", {})
                .get("phaseHandoffs", {})
                .get("entra-registration"),
                dict,
            ),
        }
    if version < 9:
        state["schemaVersion"] = 9
        migration["schemaV9"] = {
            "from": 8 if version <= 8 else version,
            "to": 9,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
        }
    if version < 10:
        evidence = state.setdefault("evidence", {})
        if not isinstance(evidence, dict):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle evidence must be an object."
            )
        old_connection_binding_hash = state.get("connectionBindingHash")
        test_record = evidence.get("test")
        test_binding = (
            test_record.get("binding")
            if isinstance(test_record, dict)
            else None
        )
        old_test_current = (
            isinstance(test_record, dict)
            and isinstance(test_binding, dict)
            and test_binding.get("draftSemanticHash")
            == state.get("draftSemanticHash")
            and isinstance(old_connection_binding_hash, str)
            and test_binding.get("connectionBindingHash")
            == old_connection_binding_hash
        )
        agent_record = evidence.get("agentConnection")
        binding_identity = _legacy_agent_binding_identity(state)
        migrated_binding = (
            isinstance(agent_record, dict)
            and binding_identity is not None
        )
        retired_evidence = state.setdefault("retiredEvidence", {})
        if not isinstance(retired_evidence, dict):
            raise ServiceNowConnectError(
                "ServiceNow retiredEvidence state must be an object."
            )
        reset_phase_ids: list[str] = []

        def reset_phase(phase_id: str) -> None:
            phase = phases.get(phase_id)
            if not isinstance(phase, dict):
                return
            phase["status"] = "pending"
            phase["checkpointResults"] = {}
            phase["checkpointAcknowledgements"] = {}
            for key in ("actionApplied", "lastActionAt", "lastVerifiedAt"):
                phase.pop(key, None)
            reset_phase_ids.append(phase_id)

        combined = phases.pop("agent-connection-and-test", None)
        if combined is not None:
            state.setdefault("retiredPhases", {})[
                "agent-connection-and-test"
            ] = combined
            migrated_binding = False

        if migrated_binding:
            assert isinstance(agent_record, dict)
            binding = agent_record.setdefault("binding", {})
            binding_identity_sha256 = _canonical_json_hash(binding_identity)
            binding["bindingIdentity"] = binding_identity
            binding["bindingIdentitySha256"] = binding_identity_sha256
            binding["migratedFromDraftSemanticHash"] = binding.pop(
                "draftSemanticHash",
                None,
            )
            state["agentBindingIdentitySha256"] = binding_identity_sha256
            new_connection_binding_hash = (
                _connection_binding_hash_for_identity(
                    binding_identity,
                    recorded_at=agent_record.get("recordedAt"),
                )
            )
            state["connectionBindingHash"] = new_connection_binding_hash
            if old_test_current and isinstance(test_binding, dict):
                test_binding["connectionBindingHash"] = (
                    new_connection_binding_hash
                )
            else:
                if isinstance(test_record, dict):
                    retired_evidence.setdefault(
                        "testSchemaV9",
                        copy.deepcopy(test_record),
                    )
                    evidence.pop("test", None)
                reset_phase("test")
        else:
            if isinstance(agent_record, dict):
                retired_evidence.setdefault(
                    "agentConnectionSchemaV9",
                    copy.deepcopy(agent_record),
                )
                evidence.pop("agentConnection", None)
            if isinstance(test_record, dict):
                retired_evidence.setdefault(
                    "testSchemaV9",
                    copy.deepcopy(test_record),
                )
                evidence.pop("test", None)
            state.pop("agentBindingIdentitySha256", None)
            state.pop("connectionBindingHash", None)
            for phase_id in (
                "agent-connection",
                "topics",
                "portal-url",
                "test",
            ):
                reset_phase(phase_id)

        ordered_ids = [
            "preflight",
            "plugin-prerequisites",
            "entra-registration",
            "servicenow-oidc",
            "credential",
            "agent-connection",
            "topics",
            "portal-url",
            "test",
        ]
        state["phases"] = {
            phase_id: phases[phase_id]
            for phase_id in ordered_ids
            if phase_id in phases
        }
        state["phases"].update(
            {
                phase_id: phase
                for phase_id, phase in phases.items()
                if phase_id not in state["phases"]
            }
        )
        phases = state["phases"]
        state["schemaVersion"] = 10
        migration["schemaV10"] = {
            "from": 9 if version <= 9 else version,
            "to": 10,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "phaseOrder": [
                phase_id
                for phase_id in ordered_ids
                if phase_id in phases
            ],
            "bindingEvidenceMigrated": migrated_binding,
            "testEvidenceMigrated": bool(
                migrated_binding and old_test_current
            ),
            "retiredCombinedPhase": combined is not None,
            "resetPhaseIds": sorted(set(reset_phase_ids)),
            "completionInferred": False,
        }
    if version < 11:
        acknowledgements = state.get("businessGroupAcknowledgements")
        if acknowledgements is not None and not isinstance(
            acknowledgements,
            dict,
        ):
            raise ServiceNowConnectError(
                "ServiceNow business-group acknowledgements must be an "
                "object."
            )
        state["businessGroupAcknowledgements"] = {}
        state["schemaVersion"] = 11
        migration["schemaV11"] = {
            "from": 10 if version <= 10 else version,
            "to": 11,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "legacyRoleAvailabilityMigrated": False,
            "completionInferred": False,
        }
    if version < 12:
        historical_compatibility_migrated = (
            _migrate_historical_entra_confirmation(context, state)
        )
        entra_phase = phases.setdefault(
            "entra-registration",
            {
                "status": "pending",
                "checkpointResults": {},
                "checkpointAcknowledgements": {},
            },
        )
        if not isinstance(entra_phase, dict):
            raise ServiceNowConnectError(
                "ServiceNow Entra phase state must be an object."
            )
        results = entra_phase.get("checkpointResults")
        acknowledgements = entra_phase.get("checkpointAcknowledgements")
        results = results if isinstance(results, dict) else {}
        acknowledgements = (
            acknowledgements
            if isinstance(acknowledgements, dict)
            else {}
        )
        retired_results = state.setdefault("retiredCheckpointResults", {})
        if not isinstance(retired_results, dict):
            raise ServiceNowConnectError(
                "ServiceNow retired checkpoint results must be an object."
            )
        retired_entra = retired_results.setdefault(
            "entra-registration",
            {},
        )
        if not isinstance(retired_entra, dict):
            raise ServiceNowConnectError(
                "Retired Entra checkpoint results must be an object."
            )
        retired_ids: list[str] = []
        legacy_checkpoint_ids = {
            checkpoint_id
            for checkpoint_id in {*results, *acknowledgements}
            if isinstance(checkpoint_id, str)
            and any(
                checkpoint_id.endswith(f"-ENTRA-{suffix}-001")
                for suffix in LEGACY_ENTRA_CHECKPOINT_SUFFIXES
            )
        }
        for checkpoint_id in sorted(legacy_checkpoint_ids):
            retired_entra.setdefault(
                checkpoint_id,
                {
                    "status": results.get(checkpoint_id),
                    "acknowledgement": copy.deepcopy(
                        acknowledgements.get(checkpoint_id)
                    ),
                    "retiredAt": _utc_now(),
                    "reason": (
                        "The current Entra phase uses one target-bound "
                        "administrator setup confirmation."
                    ),
                },
            )
            results.pop(checkpoint_id, None)
            acknowledgements.pop(checkpoint_id, None)
            retired_ids.append(checkpoint_id)
        entra_phase["checkpointAcknowledgements"] = acknowledgements
        try:
            setup_current = _identity_admin_handoff_is_ready(
                context,
                state,
                phase="entra-registration",
            )
        except ServiceNowConnectError:
            setup_current = False
        setup_status = "Manual" if setup_current else "NotConfigured"
        entra_phase["checkpointResults"] = {
            _entra_setup_checkpoint_id(): setup_status
        }
        if setup_current:
            entra_phase["status"] = "done"
        else:
            entra_phase["status"] = "pending"
            for key in ("actionApplied", "lastActionAt", "lastVerifiedAt"):
                entra_phase.pop(key, None)
        completed_entra_handoff = _completed_handoff(
            _admin_setup(state),
            "entra-registration",
        )
        historical_compatibility_current = bool(
            historical_compatibility_migrated
            or (
                completed_entra_handoff is not None
                and _historical_entra_marker_current(
                    completed_entra_handoff["evidence"]
                )
            )
        )
        state["schemaVersion"] = 12
        migration["schemaV12"] = {
            "from": 11 if version <= 11 else version,
            "to": 12,
            "sourceSha256": source_sha256,
            "migratedAt": _utc_now(),
            "currentCheckpointId": _entra_setup_checkpoint_id(),
            "currentCheckpointStatus": setup_status,
            "retiredLegacyCheckpointIds": sorted(retired_ids),
            "preservedLegacyCheckpointEvidence": bool(retired_ids),
            "historicalGraphPassCompatibilityMigrated": (
                historical_compatibility_current
            ),
            "completionRecomputedFromCurrentEvidence": setup_current,
            "completionInferred": False,
        }
    if version < 13:
        _merge_connection_phases(state, phases, migration, source_sha256, version)
    return state


def _merge_connection_phases(
    state: dict[str, Any],
    phases: dict[str, Any],
    migration: dict[str, Any],
    source_sha256: str,
    version: int,
) -> None:
    """Fold the retired `agent-connection` phase into `credential`."""
    evidence = state.setdefault("evidence", {})
    if not isinstance(evidence, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle evidence must be an object."
        )
    retired_phases = state.setdefault("retiredPhases", {})
    retired_evidence = state.setdefault("retiredEvidence", {})
    if not isinstance(retired_phases, dict) or not isinstance(
        retired_evidence, dict
    ):
        raise ServiceNowConnectError(
            "ServiceNow retired lifecycle state must be an object."
        )
    credential_phase = phases.get("credential")
    binding_phase = phases.pop("agent-connection", None)
    if binding_phase is not None:
        retired_phases["agent-connection"] = binding_phase
    credential_done = (
        isinstance(credential_phase, dict)
        and credential_phase.get("status") == "done"
    )
    binding_done = (
        isinstance(binding_phase, dict)
        and binding_phase.get("status") == "done"
    )
    agent_record = evidence.get("agentConnection")
    merged_done = bool(
        credential_done
        and binding_done
        and isinstance(agent_record, dict)
        and agent_record.get("makerAttested") is True
    )
    if merged_done:
        assert isinstance(agent_record, dict)
        agent_record.pop("makerAttested", None)
        agent_record["kind"] = "binding-proof"
        agent_record["bindingVerified"] = True
        agent_record["verificationSource"] = "migrated-maker-attestation"
    else:
        if isinstance(agent_record, dict):
            retired_evidence.setdefault(
                "agentConnectionSchemaV12",
                copy.deepcopy(agent_record),
            )
            evidence.pop("agentConnection", None)
        state.pop("agentBindingIdentitySha256", None)
        state.pop("connectionBindingHash", None)
        if credential_done and isinstance(credential_phase, dict):
            credential_phase["status"] = "pending"
            credential_phase["checkpointResults"] = {}
            credential_phase["checkpointAcknowledgements"] = {}
            for key in ("actionApplied", "lastActionAt", "lastVerifiedAt"):
                credential_phase.pop(key, None)
    state["schemaVersion"] = LIFECYCLE_SCHEMA_VERSION
    migration["schemaV13"] = {
        "from": 12 if version <= 12 else version,
        "to": LIFECYCLE_SCHEMA_VERSION,
        "sourceSha256": source_sha256,
        "migratedAt": _utc_now(),
        "retiredPhaseId": "agent-connection",
        "mergedPhaseId": "credential",
        "mergedPhaseStayedDone": merged_done,
        "completionInferred": False,
    }


def _migrate_legacy_state(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    legacy_path = _legacy_state_path(context["agent"]["id"])
    if not legacy_path.exists():
        return state
    legacy = _load_json(legacy_path)
    _validate_legacy_state_identity(context, legacy)
    digest = _canonical_json_hash(legacy)
    migration = state.setdefault("migration", {})
    if migration.get("legacySha256") == digest:
        return state

    evidence = state.setdefault("evidence", {})
    mapping = {
        "topicEnablement": "topics",
        "connection": "credentialPreparation",
        "publish": "publish",
    }
    phase_for_evidence: dict[str, str | None] = {
        "topics": "topics",
        "credentialPreparation": "credential",
        "publish": None,
    }
    imported: list[str] = []
    conflicts = list(migration.get("conflicts") or [])
    for legacy_key, evidence_key in mapping.items():
        value = legacy.get(legacy_key)
        if not isinstance(value, dict):
            continue
        record_id = _canonical_json_hash({legacy_key: value})
        existing = evidence.get(evidence_key)
        if isinstance(existing, dict) and existing != value:
            conflicts.append(
                {
                    "field": evidence_key,
                    "legacyRecordId": record_id,
                    "recordedAt": _utc_now(),
                }
            )
            phase_id = phase_for_evidence[evidence_key]
            if phase_id is not None:
                phase = state.setdefault("phases", {}).setdefault(
                    phase_id,
                    {"checkpointResults": {}},
                )
                phase["status"] = "in-progress"
            continue
        evidence.setdefault(evidence_key, copy.deepcopy(value))
        imported.append(record_id)

    for legacy_key, evidence_key in (
        ("agentConnection", "agentConnection"),
        ("parameterSharing", "parameterSharing"),
        ("test", "test"),
    ):
        value = legacy.get(legacy_key)
        if not isinstance(value, dict):
            continue
        record_id = _canonical_json_hash({legacy_key: value})
        target = evidence.setdefault(evidence_key, {})
        if not isinstance(target, dict):
            target = {}
            evidence[evidence_key] = target
        existing_legacy = target.get("legacy")
        if isinstance(existing_legacy, dict) and existing_legacy != value:
            conflicts.append(
                {
                    "field": evidence_key,
                    "legacyRecordId": record_id,
                    "recordedAt": _utc_now(),
                }
            )
        else:
            target.setdefault("legacy", copy.deepcopy(value))
            target["reconfirmRequired"] = True
            imported.append(record_id)

    migration.update(
        {
            "legacySourcePath": str(legacy_path),
            "legacySchemaVersion": legacy.get("schemaVersion"),
            "legacySha256": digest,
            "completedAt": _utc_now(),
            "importedRecordIds": sorted(
                set(migration.get("importedRecordIds") or []) | set(imported)
            ),
            "conflicts": conflicts,
            "legacySteps": copy.deepcopy(legacy.get("steps") or {}),
            "lastLegacyInspection": copy.deepcopy(
                legacy.get("lastInspection")
            ),
        }
    )
    return state


def _load_lifecycle_state(
    context: dict[str, Any],
    components: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = _lifecycle_state_path(context)
    if path.exists():
        state = _load_json(path)
        if state_integrity_mismatch(state):
            raise ServiceNowConnectError(
                STATE_TAMPERED_MESSAGE,
                details={"decision": "stop-tampered"},
            )
        version = state.get("schemaVersion")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle schemaVersion must be an integer."
            )
        if version > LIFECYCLE_SCHEMA_VERSION:
            raise ServiceNowConnectError(
                "ServiceNow lifecycle state was written by a newer kit version."
            )
        _validate_state_identity(context, state)
        state = _migrate_lifecycle_schema(context, state)
    elif components is not None:
        state = _state_base(context, components)
    else:
        state = {
            "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "intent": f"DA-GA {ACTIVE_PROFILE.product_name} connection",
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "agentSchemaName": context["agent"].get("schema_name"),
            "tenantId": context["environment"].get("tenant_id"),
            "environmentId": context["environment"]["id"],
            "ring": context["environment"].get("ring"),
            "phases": {},
            "evidence": {},
            "adminSetup": _empty_admin_setup(),
            "transactions": {"topics": {}},
            "businessGroupAcknowledgements": {},
            "migration": {},
        }
    if ACTIVE_PROFILE.key == "hrsd":
        state = _migrate_legacy_state(context, state)
    if components is not None:
        current = _state_base(context, components)
        for key in (
            "schemaVersion",
            "provider",
            "profile",
            "intent",
            "agentSlug",
            "agentId",
            "agentSchemaName",
            "tenantId",
            "environmentId",
            "ring",
            "componentHash",
            "draftSemanticHash",
            "reference",
        ):
            state[key] = current[key]
        credential = state.get("evidence", {}).get("credential")
        if (
            isinstance(credential, dict)
            and credential.get("connectionId")
            and _agent_binding_proof_current(state, components)
        ):
            state["agentBindingIdentitySha256"] = (
                _agent_binding_identity_hash(
                    context,
                    state,
                    components,
                )
            )
            state["connectionBindingHash"] = _connection_binding_hash(
                context,
                state,
                components,
            )
        else:
            state.pop("agentBindingIdentitySha256", None)
            state.pop("connectionBindingHash", None)
        publish_record = state.get("evidence", {}).get("publish")
        test_record = state.get("evidence", {}).get("test")
        published_hash = (
            publish_record.get("publishedComponentHash")
            or publish_record.get("componentHash")
            if isinstance(publish_record, dict)
            else None
        )
        test_binding = (
            test_record.get("binding")
            if isinstance(test_record, dict)
            else None
        )
        if (
            isinstance(publish_record, dict)
            and publish_record.get("status")
            in {"completed", "confirmation-required"}
            and published_hash == state["componentHash"]
            and isinstance(test_record, dict)
            and test_record.get("status") == "completed"
            and test_record.get("result") == "pass"
            and isinstance(test_binding, dict)
            and test_binding.get("draftSemanticHash")
            == state["draftSemanticHash"]
            and test_binding.get("connectionBindingHash")
            == state.get("connectionBindingHash")
        ):
            publish_record.setdefault(
                "testedDraftSemanticHash",
                state["draftSemanticHash"],
            )
            publish_record.setdefault(
                "publishedSemanticHash",
                state["draftSemanticHash"],
            )
            publish_record.setdefault(
                "connectionBindingHash",
                state["connectionBindingHash"],
            )
    state.setdefault("phases", {})
    state.setdefault("evidence", {})
    _admin_setup(state)
    _migrate_historical_entra_confirmation(context, state)
    _reconcile_entra_handoff_from_receipt(context, state)
    _reconcile_servicenow_handoff_from_receipt(context, state)
    state.setdefault("transactions", {}).setdefault("topics", {})
    state.setdefault("migration", {})
    return state


def _write_lifecycle_state(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    path = _lifecycle_state_path(context)
    existing = _load_json(path) if path.exists() else None
    verified_account = context.get("verifiedAccount")
    if verified_account:
        recorded_account = _maker_account_from_state(state)
        if (
            not recorded_account
            or recorded_account.casefold() != verified_account.casefold()
        ):
            state[MAKER_ACCOUNT_KEY] = {"username": verified_account}
    timestamp = _utc_now()
    events = _prepare_lifecycle_telemetry(
        context,
        existing,
        state,
        timestamp=timestamp,
        new_lifecycle=existing is None,
    )
    if existing is not None:
        before = copy.deepcopy(existing)
        after = copy.deepcopy(state)
        before.pop("updatedAt", None)
        after.pop("updatedAt", None)
        if before == after:
            state["updatedAt"] = existing.get("updatedAt")
            return
    state["updatedAt"] = timestamp
    state[STATE_INTEGRITY_KEY] = state_integrity_digest(state)
    _write_json_atomic(path, state)
    for event in events:
        try:
            emit_servicenow_lifecycle_event(state, event)
        except Exception:  # noqa: BLE001 - telemetry cannot break Connect
            continue


def _prepare_lifecycle_telemetry(
    context: dict[str, Any],
    previous: dict[str, Any] | None,
    state: dict[str, Any],
    *,
    timestamp: str,
    new_lifecycle: bool,
    required_phase_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    try:
        contract_path = Path(context["root"]) / CONTRACT_PATH
        contract = _load_json(contract_path) if contract_path.is_file() else {}
        phases = contract.get("phases")
        contract_phases = (
            [
                phase
                for phase in phases
                if isinstance(phase, dict)
                and isinstance(phase.get("id"), str)
            ]
            if isinstance(phases, list)
            else []
        )
        if required_phase_ids is None:
            required_phase_ids = tuple(
                str(phase["id"])
                for phase in contract_phases
            )
        allowed_remediation_ids: set[str] = set()
        for phase in contract_phases:
            targets = phase.get("checkpoints")
            if not isinstance(targets, list):
                continue
            for target in targets:
                if not isinstance(target, str):
                    continue
                if "*" not in target:
                    allowed_remediation_ids.add(target)
        return prepare_lifecycle_projection(
            previous,
            state,
            timestamp=timestamp,
            new_lifecycle=new_lifecycle,
            required_phase_ids=required_phase_ids,
            completion_ready_phase_ids=_completed_contract_phase_ids(
                state,
                contract_phases,
            ),
            allowed_remediation_ids=frozenset(
                allowed_remediation_ids
            ),
        )
    except Exception as exc:  # noqa: BLE001 - telemetry cannot break Connect
        print(
            "WARNING: ServiceNow lifecycle telemetry projection failed "
            f"({type(exc).__name__}); continuing without telemetry.",
            file=sys.stderr,
        )
        return []


def _state_for_components(
    context: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    return _load_lifecycle_state(context, components)


def _inspection_progress(
    state: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, dict[str, str]]:
    components = result["components"]
    connections = result.get("connectivity", {}).get("connections", [])
    connected = {
        str(connection.get("connectionId")): connection
        for connection in connections
        if connection.get("status") == "Connected"
        and connection.get("authMode") == "entraIDUserLogin"
    }
    evidence = state.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    total_topics = components["serviceNowTopicCount"]
    active_topics = components["activeServiceNowTopicCount"]
    topic_enablement = evidence.get("topics")
    kept_current_topics = (
        isinstance(topic_enablement, dict)
        and topic_enablement.get("customerChoice") == "keep-current"
        and topic_enablement.get("boundComponentHash")
        == state.get("componentHash")
    )
    topics_done = (
        total_topics > 0 and active_topics == total_topics
    ) or kept_current_topics

    attestation = evidence.get("agentConnection")
    if not isinstance(attestation, dict):
        attestation = {}
    attested_connection_id = str(attestation.get("connectionId") or "")
    agent_connection_done = (
        attestation.get("bindingVerified") is True
        and attested_connection_id in connected
    )

    publish_record = evidence.get("publish")
    if not isinstance(publish_record, dict):
        publish_record = {}
    published_hash = publish_record.get("componentHash")
    current_hash = state.get("componentHash")
    current_draft_hash = state.get("draftSemanticHash")
    publish_done = (
        publish_record.get("status") == "completed"
        and published_hash == current_hash
        and publish_record.get("testedDraftSemanticHash")
        == current_draft_hash
        and publish_record.get("publishedSemanticHash")
        == current_draft_hash
    )

    test_record = evidence.get("test")
    if not isinstance(test_record, dict):
        test_record = {}
    test_result = test_record.get("result")
    test_binding = test_record.get("binding")
    test_current = bool(
        isinstance(test_binding, dict)
        and test_binding.get("draftSemanticHash") == current_draft_hash
        and test_binding.get("connectionBindingHash")
        == state.get("connectionBindingHash")
    )

    return {
        "topics": {
            "status": "done" if topics_done else "pending",
            "message": (
                f"{active_topics}/{total_topics} "
                f"{ACTIVE_PROFILE.product_name} topics are "
                f"active."
            ),
        },
        "credential": {
            "status": (
                "done" if connected and agent_connection_done else "pending"
            ),
            "message": (
                f"{len(connected)} Connected Entra user-login ServiceNow "
                "credential(s) found. "
                + (
                    "The agent's saved settings use the verified connection."
                    if agent_connection_done
                    else "The agent's saved settings must be verified."
                )
            ),
        },
        "test": {
            "status": (
                "confirmation-required"
                if test_current and test_result in {"pass", "fail"}
                else "pending"
            ),
            "message": (
                "A passing Test pane result was previously recorded; a "
                "current functional result requires maker confirmation."
                if test_current and test_result == "pass"
                else (
                    "A failing Test pane result was previously recorded; a "
                    "current functional result requires maker confirmation."
                )
                if test_current and test_result == "fail"
                else (
                    "Functional Test pane validation has not been recorded "
                    "for the current saved draft and selected connection."
                )
            ),
        },
        "legacyPublish": {
            "status": "historical" if publish_record else "not-recorded",
            "message": (
                "Historical publish evidence is retained for read-only "
                "diagnostics; publishing is not a ServiceNow Connect phase."
                if publish_done
                else (
                    "Historical publish evidence is retained but does not "
                    "match the current draft; publishing remains outside "
                    "ServiceNow Connect."
                    if publish_record
                    else (
                        "No historical publish evidence is recorded. "
                        "Publishing remains outside ServiceNow Connect."
                    )
                )
            ),
        },
    }


def record_preflight_instance(
    context: dict[str, Any],
    *,
    instance_url: str,
) -> dict[str, Any]:
    instance_name = normalize_instance_name(instance_url)
    state = _load_lifecycle_state(context)
    preflight = _admin_setup(state)["preflight"]
    preflight.update(
        {
            "instanceName": instance_name,
            "instanceOrigin": (
                f"https://{instance_name}.service-now.com"
            ),
            "instanceSource": "maker-confirmed",
            "recordedAt": _utc_now(),
        }
    )
    _admin_setup(state)["phaseHandoffs"]["preflight"] = {
        "status": "pending"
    }
    _write_lifecycle_state(context, state)
    return copy.deepcopy(preflight)


def _discovered_instance_candidates(
    connections: list[dict[str, Any]],
) -> list[str]:
    names: set[str] = set()
    for connection in connections:
        values = connection.get("parameterValues")
        values = values if isinstance(values, dict) else {}
        raw_name = values.get("token:InstanceName") or values.get("instance")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        try:
            names.add(normalize_instance_name(raw_name))
        except ServiceNowConnectError:
            continue
    return sorted(names)


def _preflight_instance_question(
    *,
    context: dict[str, Any],
    candidates: list[str],
    discovery_error: dict[str, Any] | None,
) -> tuple[
    dict[str, Any],
    dict[str, str],
    dict[str, Any],
]:
    agent_label = _spec_agent_name()
    error_text = ""
    if discovery_error is not None:
        error_text = (
            "\n\nWe couldn't check your existing connections automatically. "
            "You can still send the public ServiceNow address; we'll verify "
            "it when the connection is created."
        )
    manual_question = {
        "header": f"Which ServiceNow instance should {agent_label} use?",
        "question": (
            "Send its public HTTPS URL, not credentials.\n\n"
            "Example: `https://<your-instance>.service-now.com`\n\n"
            "Use only the instance address, without a portal path such as "
            "`/sp` or `/esc`. If you don't know it, ask your ServiceNow "
            f"administrator.{error_text}"
        ),
        "allowFreeformInput": True,
    }
    if candidates:
        single = len(candidates) == 1
        if single:
            choices = {
                "Yes": f"https://{candidates[0]}.service-now.com",
                "No": "manual",
            }
            header = (
                f"Should {agent_label} use the ServiceNow instance "
                f"{candidates[0]}?"
            )
            explanation = (
                f"We found **{candidates[0]}** in your existing "
                f"connections.{error_text}"
            )
        else:
            choices = {
                candidate: f"https://{candidate}.service-now.com"
                for candidate in candidates
            }
            choices["Another instance"] = "manual"
            header = f"Which ServiceNow instance should {agent_label} use?"
            explanation = (
                "We found these instances in your existing "
                f"connections.{error_text}"
            )
        question = {
            "header": header,
            "question": explanation,
            "options": [
                {"label": label}
                for label in choices
            ],
            "allowFreeformInput": False,
        }
        return question, choices, manual_question
    return manual_question, {}, manual_question


def _credential_selection_key(connection_id: str) -> str:
    normalized = uuid.UUID(connection_id).hex
    return f"connection-{hashlib.sha256(normalized.encode()).hexdigest()[:12]}"


def _connection_matches_expected_credential(
    connection: dict[str, Any],
    *,
    expected_instance: str | None,
    expected_client_id: str | None,
) -> bool:
    if connection.get("authMode") != AUTH_MODE:
        return False
    values = connection.get("parameterValues")
    values = values if isinstance(values, dict) else {}
    instance_name = values.get("token:InstanceName") or values.get("instance")
    resource_uri = values.get("token:ResourceUri")
    if not expected_instance or not expected_client_id:
        return False
    try:
        return (
            normalize_instance_name(str(instance_name)) == expected_instance
            and normalize_client_id(str(resource_uri)) == expected_client_id
        )
    except ServiceNowConnectError:
        return False


def _credential_resolution(
    setup: dict[str, Any],
    connections: list[dict[str, Any]],
) -> dict[str, Any]:
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    expected_instance = preflight.get("instanceName")
    app_record = setup.get("phaseHandoffs", {}).get("entra-registration")
    app_evidence = (
        app_record.get("evidence")
        if isinstance(app_record, dict)
        else {}
    )
    app_evidence = app_evidence if isinstance(app_evidence, dict) else {}
    expected_client_id = app_evidence.get("clientId")
    exact = [
        connection
        for connection in connections
        if _connection_matches_expected_credential(
            connection,
            expected_instance=expected_instance,
            expected_client_id=expected_client_id,
        )
    ]
    healthy = [
        connection
        for connection in exact
        if connection.get("status") == "Connected"
    ]
    unhealthy = [
        connection
        for connection in exact
        if connection.get("status") != "Connected"
    ]
    healthy = sorted(
        healthy,
        key=lambda connection: (
            str(connection.get("displayName") or ""),
            str(connection.get("connectionId") or ""),
        ),
    )
    return {
        "expected": {
            "authMode": AUTH_MODE,
            "instanceName": expected_instance,
            "resourceUri": expected_client_id,
        },
        "healthyExactCount": len(healthy),
        "unhealthyExactCount": len(unhealthy),
        "healthyExactCandidates": [
            {
                "selectionKey": _credential_selection_key(
                    str(connection["connectionId"])
                ),
                "label": (
                    f"{connection.get('displayName') or 'ServiceNow connection'} "
                    f"(Connected, option {index})"
                ),
            }
            for index, connection in enumerate(healthy, start=1)
            if connection.get("connectionId")
        ],
    }


def _completed_handoff(
    setup: dict[str, Any],
    phase: str,
) -> dict[str, Any] | None:
    handoffs = setup.get("phaseHandoffs")
    record = handoffs.get(phase) if isinstance(handoffs, dict) else None
    if (
        isinstance(record, dict)
        and record.get("status") in {"completed", "reused"}
        and isinstance(record.get("evidence"), dict)
    ):
        return record
    return None


def _local_compatible_agent_states(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    root = Path(context.get("root") or Path.cwd()) / ".local" / "connect"
    records: list[dict[str, Any]] = []
    for profile in PRODUCT_PROFILES.values():
        agents_root = root / profile.provider_key / "agents"
        if not agents_root.is_dir() or agents_root.is_symlink():
            continue
        for agent_dir in sorted(agents_root.iterdir(), key=lambda item: item.name):
            if (
                not agent_dir.is_dir()
                or agent_dir.is_symlink()
                or not _SAFE_AGENT_SLUG.fullmatch(agent_dir.name)
                or (
                    profile.provider_key == PROVIDER_KEY
                    and agent_dir.name == _agent_slug(context)
                )
            ):
                continue
            state_path = agent_dir / "lifecycle.json"
            if not state_path.is_file() or state_path.is_symlink():
                continue
            try:
                state_bytes = state_path.read_bytes()
                state = json.loads(state_bytes)
            except (OSError, json.JSONDecodeError):
                continue
            if (
                not isinstance(state, dict)
                or state.get("provider") != profile.provider_key
                or state.get("profile") != profile.key
                or str(state.get("agentSlug") or "") != agent_dir.name
                or str(state.get("tenantId") or "").casefold()
                != str(context["environment"]["tenant_id"]).casefold()
                or str(state.get("environmentId") or "").casefold()
                != str(context["environment"]["id"]).casefold()
                or str(state.get("ring") or "").casefold()
                != str(context["environment"]["ring"]).casefold()
            ):
                continue
            records.append(
                {
                    "profile": profile,
                    "agentSlug": agent_dir.name,
                    "statePath": state_path,
                    "stateBytes": state_bytes,
                    "stateSha256": hashlib.sha256(state_bytes).hexdigest(),
                    "state": state,
                }
            )
    return records


def _locally_confirmed_instance_candidates(
    context: dict[str, Any],
) -> list[str]:
    candidates: set[str] = set()
    for source in _local_compatible_agent_states(context):
        state = source["state"]
        setup = state.get("adminSetup")
        setup = setup if isinstance(setup, dict) else {}
        handoff = _completed_handoff(setup, "preflight")
        preflight = setup.get("preflight")
        preflight = preflight if isinstance(preflight, dict) else {}
        instance_name = preflight.get("instanceName")
        instance_origin = preflight.get("instanceOrigin")
        if (
            handoff is None
            or handoff["evidence"].get("kind") != "maker-confirmed-target"
            or handoff["evidence"].get("instanceName") != instance_name
            or not isinstance(handoff["evidence"].get("recordedAt"), str)
            or not handoff["evidence"]["recordedAt"]
            or not isinstance(instance_name, str)
            or not instance_name
            or not isinstance(instance_origin, str)
            or not instance_origin
        ):
            continue
        try:
            normalized_name = normalize_instance_name(instance_name)
            normalized_origin = normalize_portal_url(
                instance_origin,
                expected_instance_name=normalized_name,
            )
        except ServiceNowConnectError:
            continue
        if normalized_origin == f"https://{normalized_name}.service-now.com":
            candidates.add(normalized_name)
    return sorted(candidates)


def _portal_value_reuse_candidates(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    target_state = _load_lifecycle_state(context)
    target_instance = _admin_setup(target_state)["preflight"].get(
        "instanceName"
    )
    if not isinstance(target_instance, str) or not target_instance:
        return []
    target_instance = normalize_instance_name(target_instance)
    by_url: dict[str, list[dict[str, Any]]] = {}
    for source in _local_compatible_agent_states(context):
        state = source["state"]
        setup = state.get("adminSetup")
        setup = setup if isinstance(setup, dict) else {}
        source_instance = setup.get("preflight", {}).get("instanceName")
        try:
            source_instance = normalize_instance_name(
                str(source_instance or "")
            )
        except ServiceNowConnectError:
            continue
        if source_instance != target_instance:
            continue
        receipt = state.get("evidence", {}).get("portalConfirmation")
        if not isinstance(receipt, dict):
            continue
        binding = receipt.get("binding")
        readback = receipt.get("readbackEvidence")
        expected_binding = {
            "provider": state.get("provider"),
            "profile": state.get("profile"),
            "agentSlug": state.get("agentSlug"),
            "agentId": state.get("agentId"),
            "environmentId": state.get("environmentId"),
            "tenantId": state.get("tenantId"),
            "instanceName": source_instance,
        }
        if (
            receipt.get("kind") != "maker-confirmed-portal-url"
            or receipt.get("status") != "confirmed"
            or not isinstance(receipt.get("recordedAt"), str)
            or not receipt["recordedAt"]
            or not isinstance(receipt.get("readbackAt"), str)
            or not receipt["readbackAt"]
            or not isinstance(binding, dict)
            or any(binding.get(key) != value for key, value in expected_binding.items())
            or not isinstance(binding.get("topicId"), str)
            or not binding["topicId"]
            or not isinstance(binding.get("topicSchemaName"), str)
            or not binding["topicSchemaName"]
            or not isinstance(readback, dict)
            or readback.get("topicVersion") is None
            or not isinstance(
                readback.get("topicContentHashExcludingVersion"),
                str,
            )
            or not readback["topicContentHashExcludingVersion"]
        ):
            continue
        try:
            portal_url = normalize_portal_url(
                str(receipt.get("portalUrl") or ""),
                expected_instance_name=target_instance,
            )
        except ServiceNowConnectError:
            continue
        receipt_sha256 = _canonical_json_hash(receipt)
        source_record = {
            "sourceProvider": state["provider"],
            "sourceProfile": state["profile"],
            "sourceAgentSlug": state["agentSlug"],
            "sourceAgentId": state["agentId"],
            "sourceStateSha256": source["stateSha256"],
            "sourceReceiptSha256": receipt_sha256,
            "sourceRecordedAt": receipt["recordedAt"],
            "portalUrl": portal_url,
        }
        by_url.setdefault(portal_url, []).append(source_record)
    candidates: list[dict[str, Any]] = []
    for portal_url, sources in sorted(by_url.items()):
        sources.sort(
            key=lambda row: (
                row["sourceProvider"],
                row["sourceAgentSlug"],
                row["sourceReceiptSha256"],
            )
        )
        source = sources[0]
        source_key = hashlib.sha256(
            (
                f"{source['sourceProvider']}|{source['sourceAgentSlug']}|"
                f"{source['sourceReceiptSha256']}|{portal_url}"
            ).encode("utf-8")
        ).hexdigest()[:24]
        candidates.append(
            {
                **source,
                "sourceKey": source_key,
                "sources": copy.deepcopy(sources),
                "sourceLabels": [
                    (
                        f"{PRODUCT_PROFILES[row['sourceProfile']].agent_display_name} "
                        f"agent `{row['sourceAgentSlug']}`"
                    )
                    for row in sources
                ],
            }
        )
    return candidates


def _validate_portal_value_reuse_record_target(
    context: dict[str, Any],
    state: dict[str, Any],
    record: dict[str, Any],
) -> str:
    instance_name = _admin_setup(state)["preflight"].get("instanceName")
    if not isinstance(instance_name, str) or not instance_name:
        raise ServiceNowConnectError(
            "The saved portal URL reuse record has no confirmed target "
            "instance."
        )
    instance_name = normalize_instance_name(instance_name)
    expected = {
        "targetProvider": PROVIDER_KEY,
        "targetProfile": PROFILE_KEY,
        "targetAgentSlug": _agent_slug(context),
        "targetAgentId": context["agent"]["id"],
        "tenantId": context["environment"]["tenant_id"],
        "environmentId": context["environment"]["id"],
        "instanceName": instance_name,
    }
    if (
        record.get("kind") != "maker-confirmed-saved-value-reuse"
        or record.get("valueType") != "employee-portal-url"
        or record.get("decision") not in {"accepted", "declined"}
        or any(
            str(record.get(field) or "").casefold()
            != str(value).casefold()
            for field, value in expected.items()
        )
    ):
        raise ServiceNowConnectError(
            "The saved portal URL reuse decision does not match the active "
            "target."
        )
    try:
        return normalize_portal_url(
            str(record.get("portalUrl") or ""),
            expected_instance_name=instance_name,
        )
    except ServiceNowConnectError as exc:
        raise ServiceNowConnectError(
            "The saved portal URL reuse decision has an invalid value."
        ) from exc


def portal_value_reuse_handoff(
    context: dict[str, Any],
    *,
    source_key: str | None = None,
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    prior = state.get("portalValueReuse")
    candidates = _portal_value_reuse_candidates(context)
    if isinstance(prior, dict) and prior.get("decision") in {
        "accepted",
        "declined",
    }:
        prior_portal_url = _validate_portal_value_reuse_record_target(
            context,
            state,
            prior,
        )
        if prior.get("decision") == "declined":
            return {
                "schemaVersion": "servicenow.portal-value-reuse.v1",
                "decision": "already-recorded",
                "record": copy.deepcopy(prior),
            }
        current = []
        for candidate in candidates:
            if candidate["portalUrl"] != prior_portal_url:
                continue
            matching_sources = [
                source
                for source in candidate["sources"]
                if all(
                    source.get(field) == prior.get(field)
                    for field in (
                        "sourceProvider",
                        "sourceProfile",
                        "sourceAgentSlug",
                        "sourceAgentId",
                        "sourceReceiptSha256",
                    )
                )
            ]
            if len(matching_sources) == 1:
                current.append(candidate)
        if len(current) != 1:
            raise ServiceNowConnectError(
                "The accepted saved portal URL source changed or is no longer "
                "compatible."
            )
        return {
            "schemaVersion": "servicenow.portal-value-reuse.v1",
            "decision": "already-recorded",
            "record": copy.deepcopy(prior),
            "candidate": copy.deepcopy(current[0]),
        }
    if not candidates:
        return {
            "schemaVersion": "servicenow.portal-value-reuse.v1",
            "decision": "none",
            "candidates": [],
        }
    if source_key is None and len(candidates) > 1:
        choices = [
            {
                "label": candidate["portalUrl"],
                "sourceKey": candidate["sourceKey"],
            }
            for candidate in candidates
        ]
        return {
            "schemaVersion": "servicenow.portal-value-reuse.v1",
            "decision": "source-selection-required",
            "candidates": copy.deepcopy(candidates),
            "portalSourceChoices": choices,
            "question": {
                "header": "Which saved employee portal URL should we use?",
                "question": (
                    "Compatible employee portal URLs confirmed by an "
                    "administrator were saved for other agents in this "
                    "workspace."
                ),
                "options": [
                    {"label": choice["label"]} for choice in choices
                ],
                "allowFreeformInput": False,
            },
        }
    selected = (
        candidates[0]
        if source_key is None
        else next(
            (
                candidate
                for candidate in candidates
                if candidate["sourceKey"] == source_key
            ),
            None,
        )
    )
    if selected is None:
        raise ServiceNowConnectError(
            "The selected saved portal URL source is stale or unavailable."
        )
    decision_choices = [
        {"label": "Yes", "decision": "accept"},
        {"label": "No", "decision": "decline"},
    ]
    return {
        "schemaVersion": "servicenow.portal-value-reuse.v1",
        "decision": "question-required",
        "candidate": copy.deepcopy(selected),
        "portalDecisionChoices": decision_choices,
        "question": {
            "header": (
                f"Reuse the saved employee portal URL "
                f"{selected['portalUrl']}?"
            ),
            "question": (
                "An employee portal URL confirmed by an administrator is "
                "already saved for another agent in this workspace "
                f"(from {', '.join(selected['sourceLabels'])}). We'll still "
                "check and update this agent's own portal setting if needed."
            ),
            "options": [
                {"label": choice["label"]} for choice in decision_choices
            ],
            "allowFreeformInput": False,
        },
    }


def record_portal_value_reuse(
    context: dict[str, Any],
    *,
    source_key: str,
    decision: str,
) -> dict[str, Any]:
    if decision not in {"accept", "decline"}:
        raise ServiceNowConnectError(
            "Saved portal URL decision must be accept or decline."
        )
    state = _load_lifecycle_state(context)
    candidates = [
        candidate
        for candidate in _portal_value_reuse_candidates(context)
        if candidate["sourceKey"] == source_key
    ]
    if len(candidates) != 1:
        raise ServiceNowConnectError(
            "The saved portal URL source is stale or no longer unique."
        )
    candidate = candidates[0]
    record = {
        "kind": "maker-confirmed-saved-value-reuse",
        "valueType": "employee-portal-url",
        "decision": "accepted" if decision == "accept" else "declined",
        "portalUrl": candidate["portalUrl"],
        "sourceKey": candidate["sourceKey"],
        "sourceProvider": candidate["sourceProvider"],
        "sourceProfile": candidate["sourceProfile"],
        "sourceAgentSlug": candidate["sourceAgentSlug"],
        "sourceAgentId": candidate["sourceAgentId"],
        "sourceStateSha256": candidate["sourceStateSha256"],
        "sourceReceiptSha256": candidate["sourceReceiptSha256"],
        "sourceRecordedAt": candidate["sourceRecordedAt"],
        "targetProvider": PROVIDER_KEY,
        "targetProfile": PROFILE_KEY,
        "targetAgentSlug": _agent_slug(context),
        "targetAgentId": context["agent"]["id"],
        "tenantId": context["environment"]["tenant_id"],
        "environmentId": context["environment"]["id"],
        "instanceName": _admin_setup(state)["preflight"]["instanceName"],
        "recordedAt": _utc_now(),
    }
    state["portalValueReuse"] = record
    _write_lifecycle_state(context, state)
    return copy.deepcopy(record)


def _shared_mapping_compatible(
    context: dict[str, Any],
    source_state: dict[str, Any],
    *,
    require_servicenow: bool,
) -> dict[str, Any] | None:
    evidence = source_state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    candidates = evidence.get("identityClaimCandidates")
    if (
        not isinstance(candidates, dict)
        or candidates.get("kind")
        != "administrator-confirmed-claim-candidates"
        or candidates.get("status") != "entra-confirmed"
        or candidates.get("entraAdministratorConfirmed") is not True
        or not isinstance(candidates.get("candidates"), list)
        or len(candidates["candidates"]) != 1
    ):
        return None
    binding = candidates.get("binding")
    if not isinstance(binding, dict):
        return None
    expected = {
        "tenantId": str(context["environment"]["tenant_id"]),
        "environmentId": str(context["environment"]["id"]),
    }
    for field, value in expected.items():
        if str(binding.get(field) or "").casefold() != value.casefold():
            return None
    if (
        str(binding.get("applicationClientId") or "").casefold()
            != str(candidates.get("applicationClientId") or "").casefold()
    ):
        return None
    source_binding = {
        "provider": source_state.get("provider"),
        "profile": source_state.get("profile"),
        "agentSlug": source_state.get("agentSlug"),
        "agentId": source_state.get("agentId"),
    }
    if any(
        str(binding.get(field) or "").casefold()
        != str(value or "").casefold()
        for field, value in source_binding.items()
    ):
        return None
    source_setup = source_state.get("adminSetup")
    source_setup = source_setup if isinstance(source_setup, dict) else {}
    source_preflight = source_setup.get("preflight")
    source_preflight = (
        source_preflight if isinstance(source_preflight, dict) else {}
    )
    instance_name = source_preflight.get("instanceName")
    if (
        not isinstance(instance_name, str)
        or str(binding.get("instanceName") or "").casefold()
        != normalize_instance_name(instance_name).casefold()
    ):
        return None
    try:
        candidate_hash = _identity_candidate_set_hash(
            application_client_id=normalize_client_id(
                str(candidates.get("applicationClientId") or "")
            ),
            candidates=list(candidates["candidates"]),
            binding=binding,
        )
    except ServiceNowConnectError:
        return None
    if candidates.get("candidateSetSha256") != candidate_hash:
        return None
    if not require_servicenow:
        return candidates
    mapping = evidence.get("identityMapping")
    if not isinstance(mapping, dict):
        return None
    try:
        candidate_client_id = normalize_client_id(
            str(candidates.get("applicationClientId") or "")
        )
        mapping_client_id = normalize_client_id(
            str(mapping.get("applicationClientId") or "")
        )
        binding_client_id = normalize_client_id(
            str(binding.get("applicationClientId") or "")
        )
    except ServiceNowConnectError:
        return None
    if (
        mapping.get("kind")
        != "administrator-confirmed-identity-mapping"
        or mapping.get("status") != "servicenow-confirmed"
        or mapping.get("serviceNowAdministratorConfirmed") is not True
        or mapping_client_id != candidate_client_id
        or binding_client_id != candidate_client_id
        or mapping.get("candidateSetSha256")
        != candidate_hash
        or mapping.get("tokenClaimName") not in candidates["candidates"]
        or not mapping.get("serviceNowUserField")
        or mapping.get("binding") != binding
        or not _servicenow_mapping_receipt_provenance_current(mapping)
        or mapping.get("relationshipSha256")
        != _identity_mapping_relationship_hash(mapping)
    ):
        return None
    return mapping


def _shared_reuse_candidates(
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    target_state = _load_lifecycle_state(context)
    target_setup = _admin_setup(target_state)
    target_preflight = target_setup.get("preflight")
    target_preflight = (
        target_preflight if isinstance(target_preflight, dict) else {}
    )
    target_instance = target_preflight.get("instanceName")
    if not isinstance(target_instance, str) or not target_instance:
        return []
    target_handoffs = target_setup.get("phaseHandoffs")
    target_handoffs = (
        target_handoffs if isinstance(target_handoffs, dict) else {}
    )
    target_evidence = target_state.get("evidence")
    target_evidence = (
        target_evidence if isinstance(target_evidence, dict) else {}
    )
    target_entra = _completed_handoff(
        target_setup,
        "entra-registration",
    )
    target_client_id = None
    if target_entra is not None:
        try:
            target_client_id = normalize_client_id(
                str(target_entra["evidence"].get("clientId") or "")
            )
        except ServiceNowConnectError:
            target_client_id = None
    target_candidates = target_evidence.get("identityClaimCandidates")
    target_candidates = (
        target_candidates if isinstance(target_candidates, dict) else None
    )
    candidates: list[dict[str, Any]] = []
    for profile in PRODUCT_PROFILES.values():
        agents_root = (
            Path(".local/connect") / profile.provider_key / "agents"
        )
        if not agents_root.is_dir():
            continue
        for agent_dir in sorted(agents_root.iterdir(), key=lambda item: item.name):
            if (
                not agent_dir.is_dir()
                or agent_dir.is_symlink()
                or not _SAFE_AGENT_SLUG.fullmatch(agent_dir.name)
                or (
                    profile.provider_key == PROVIDER_KEY
                    and agent_dir.name == _agent_slug(context)
                )
            ):
                continue
            state_path = agent_dir / "lifecycle.json"
            if not state_path.is_file() or state_path.is_symlink():
                continue
            try:
                source_bytes = state_path.read_bytes()
                source_state = json.loads(source_bytes)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(source_state, dict):
                continue
            if (
                source_state.get("provider") != profile.provider_key
                or source_state.get("profile") != profile.key
                or str(source_state.get("agentSlug") or "") != agent_dir.name
                or str(source_state.get("environmentId") or "").casefold()
                != str(context["environment"]["id"]).casefold()
                or str(source_state.get("ring") or "").casefold()
                != str(context["environment"]["ring"]).casefold()
            ):
                continue
            source_setup = source_state.get("adminSetup")
            if not isinstance(source_setup, dict):
                continue
            if source_setup.get("authMode") != AUTH_MODE:
                continue
            source_preflight = source_setup.get("preflight")
            source_preflight = (
                source_preflight
                if isinstance(source_preflight, dict)
                else {}
            )
            source_instance = source_preflight.get("instanceName")
            if not isinstance(source_instance, str) or not source_instance:
                continue
            try:
                source_instance = normalize_instance_name(source_instance)
            except ServiceNowConnectError:
                continue
            if (
                isinstance(target_instance, str)
                and target_instance
                and normalize_instance_name(target_instance) != source_instance
            ):
                continue

            items: list[dict[str, Any]] = []

            source_entra = _completed_handoff(
                source_setup,
                "entra-registration",
            )
            entra_candidates = _shared_mapping_compatible(
                context,
                source_state,
                require_servicenow=False,
            )
            client_id = None
            if source_entra is not None:
                source_entra_evidence = source_entra["evidence"]
                raw_client_id = source_entra_evidence.get("clientId")
                try:
                    client_id = normalize_client_id(str(raw_client_id))
                except ServiceNowConnectError:
                    client_id = None
            source_identity_client_id = (
                client_id
                or (
                    entra_candidates.get("applicationClientId")
                    if isinstance(entra_candidates, dict)
                    else None
                )
            )
            identity_compatible = (
                target_client_id is None
                or target_client_id == source_identity_client_id
            )
            if target_candidates is not None:
                identity_compatible = bool(
                    identity_compatible
                    and entra_candidates is not None
                    and target_candidates.get("applicationClientId")
                    == entra_candidates.get("applicationClientId")
                    and target_candidates.get("candidates")
                    == entra_candidates.get("candidates")
                )
            if (
                _completed_handoff(target_setup, "entra-registration") is None
                and source_entra is not None
                and entra_candidates is not None
                and client_id == entra_candidates.get("applicationClientId")
                and identity_compatible
            ):
                items.append(
                    {
                        "id": "entra-registration",
                        "summary": (
                            "Entra administrator-confirmed application and "
                            "employee claim candidates: "
                            + ", ".join(entra_candidates["candidates"])
                        ),
                    }
                )

            source_oidc = _completed_handoff(
                source_setup,
                "servicenow-oidc",
            )
            oidc_mapping = _shared_mapping_compatible(
                context,
                source_state,
                require_servicenow=True,
            )
            if (
                _completed_handoff(target_setup, "servicenow-oidc") is None
                and source_oidc is not None
                and oidc_mapping is not None
                and identity_compatible
                and all(
                    source_oidc["evidence"].get(key)
                    == oidc_mapping.get(key)
                    for key in (
                        "tokenClaimName",
                        "serviceNowUserField",
                    )
                )
            ):
                items.append(
                    {
                        "id": "servicenow-oidc",
                        "summary": (
                            "Current target-bound ServiceNow user-field "
                            f"mapping receipt for token claim "
                            f"{oidc_mapping['tokenClaimName']}"
                        ),
                    }
                )

            if not items:
                continue
            source_sha256 = hashlib.sha256(source_bytes).hexdigest()
            source_key = hashlib.sha256(
                (
                    f"{profile.provider_key}|{agent_dir.name}|"
                    f"{source_sha256}"
                ).encode("utf-8")
            ).hexdigest()[:24]
            candidates.append(
                {
                    "sourceKey": source_key,
                    "sourceStateSha256": source_sha256,
                    "sourcePath": str(state_path),
                    "sourceProvider": profile.provider_key,
                    "sourceProfile": profile.key,
                    "sourceAgentSlug": agent_dir.name,
                    "sourceAgentId": source_state.get("agentId"),
                    "environmentId": context["environment"]["id"],
                    "tenantId": context["environment"]["tenant_id"],
                    "instanceName": source_instance,
                    "applicationClientId": client_id,
                    "items": items,
                }
            )
    return sorted(
        candidates,
        key=lambda candidate: (
            -len(candidate["items"]),
            candidate["sourceProvider"],
            candidate["sourceAgentSlug"],
        ),
    )


def _shared_identity_item_decisions(
    record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(record, dict):
        return []
    rows = record.get("identityItemDecisions")
    if isinstance(rows, list):
        return [
            copy.deepcopy(row)
            for row in rows
            if isinstance(row, dict)
            and row.get("itemId")
            in {"entra-registration", "servicenow-oidc"}
            and row.get("decision") in {"accepted", "declined"}
            and row.get("sourceProvider")
            and row.get("sourceAgentSlug")
        ]
    decision = record.get("decision")
    if decision not in {"accepted", "declined"}:
        return []
    return [
        {
            "sourceProvider": record.get("sourceProvider"),
            "sourceAgentSlug": record.get("sourceAgentSlug"),
            "itemId": item_id,
            "decision": decision,
            "recordedAt": record.get("recordedAt"),
        }
        for item_id in record.get("applicableItems") or []
        if item_id in {"entra-registration", "servicenow-oidc"}
        and record.get("sourceProvider")
        and record.get("sourceAgentSlug")
    ]


def _filter_shared_identity_candidates(
    state: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prior = state.get("sharedConfigurationReuse")
    prior_decisions = _shared_identity_item_decisions(
        prior if isinstance(prior, dict) else None
    )
    target_candidates = state.get("evidence", {}).get(
        "identityClaimCandidates"
    )
    filtered = copy.deepcopy(candidates)
    for candidate in filtered:
        decided_ids = {
            row["itemId"]
            for row in prior_decisions
            if row["sourceProvider"] == candidate["sourceProvider"]
            and row["sourceAgentSlug"] == candidate["sourceAgentSlug"]
        }
        candidate["items"] = [
            item
            for item in candidate["items"]
            if item["id"] not in decided_ids
        ]
        if (
            not isinstance(target_candidates, dict)
            and not any(
                item["id"] == "entra-registration"
                for item in candidate["items"]
            )
        ):
            candidate["items"] = [
                item
                for item in candidate["items"]
                if item["id"] != "servicenow-oidc"
            ]
    return (
        [candidate for candidate in filtered if candidate["items"]],
        prior_decisions,
    )


def shared_reuse_handoff(
    context: dict[str, Any],
    *,
    source_key: str | None = None,
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    prior = state.get("sharedConfigurationReuse")
    candidates, prior_decisions = _filter_shared_identity_candidates(
        state,
        _shared_reuse_candidates(context),
    )
    if (
        isinstance(prior, dict)
        and prior_decisions
        and not candidates
    ):
        return {
            "schemaVersion": "servicenow.shared-reuse-handoff.v1",
            "decision": "already-recorded",
            "record": copy.deepcopy(prior),
        }
    if source_key is None and len(candidates) > 1:
        return {
            "schemaVersion": "servicenow.shared-reuse-handoff.v1",
            "decision": "source-selection-required",
            "candidates": [
                {
                    "sourceKey": candidate["sourceKey"],
                    "label": (
                        f"{candidate['sourceProfile'].upper()} "
                        f"{candidate['sourceAgentSlug']} "
                        f"({len(candidate['items'])} reusable items)"
                    ),
                    "items": copy.deepcopy(candidate["items"]),
                }
                for candidate in candidates
            ],
        }
    if source_key is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate["sourceKey"] == source_key
        ]
        if not candidates:
            raise ServiceNowConnectError(
                "The selected shared configuration source is stale or no "
                "longer compatible."
            )
    if not candidates:
        return {
            "schemaVersion": "servicenow.shared-reuse-handoff.v1",
            "decision": "none",
            "candidates": [],
        }
    candidate = candidates[0]
    item_lines = "\n".join(
        f"- {item['summary']}"
        for item in candidate["items"]
    )
    decision_choices = [
        {
            "label": "Yes",
            "decision": "accept",
        },
        {
            "label": "No",
            "decision": "decline",
        },
    ]
    source_label = {"hrsd": "HR", "itsm": "IT"}.get(
        str(candidate["sourceProfile"]),
        str(candidate["sourceProfile"]).upper(),
    )
    return {
        "schemaVersion": "servicenow.shared-reuse-handoff.v1",
        "decision": "question-required",
        "candidate": copy.deepcopy(candidate),
        "reuseDecisionChoices": decision_choices,
        "question": {
            "header": (
                f"Reuse the shared setup from your existing "
                f"{source_label} agent?"
            ),
            "question": (
                f"Your {source_label} agent in this "
                "workspace already has compatible administrator setup for "
                f"this ServiceNow instance. You can reuse these "
                f"items:\n\n{item_lines}\n\n"
                "Reuse avoids repeating compatible administrator setup, but "
                "each readiness check still runs for this agent."
            ),
            "options": [
                {"label": choice["label"]}
                for choice in decision_choices
            ],
            "allowFreeformInput": False,
        },
    }


def apply_shared_configuration_reuse(
    context: dict[str, Any],
    *,
    source_key: str,
    decision: str,
) -> dict[str, Any]:
    if decision not in {"accept", "decline"}:
        raise ServiceNowConnectError(
            "Shared configuration decision must be accept or decline."
        )
    state = _load_lifecycle_state(context)
    candidates, prior_decisions = _filter_shared_identity_candidates(
        state,
        _shared_reuse_candidates(context),
    )
    candidates = [
        candidate
        for candidate in candidates
        if candidate["sourceKey"] == source_key
    ]
    if len(candidates) != 1:
        raise ServiceNowConnectError(
            "The shared configuration source is stale or no longer unique."
        )
    candidate = candidates[0]
    record = {
        "decision": "accepted" if decision == "accept" else "declined",
        "sourceKey": source_key,
        "sourceStateSha256": candidate["sourceStateSha256"],
        "sourceProvider": candidate["sourceProvider"],
        "sourceProfile": candidate["sourceProfile"],
        "sourceAgentSlug": candidate["sourceAgentSlug"],
        "sourceAgentId": candidate["sourceAgentId"],
        "targetProvider": PROVIDER_KEY,
        "targetProfile": PROFILE_KEY,
        "targetAgentSlug": _agent_slug(context),
        "targetAgentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "tenantId": context["environment"]["tenant_id"],
        "instanceName": candidate["instanceName"],
        "applicableItems": [
            item["id"] for item in candidate["items"]
        ],
        "recordedAt": _utc_now(),
    }
    current_decision = "accepted" if decision == "accept" else "declined"
    decided_item_ids = {
        item["id"] for item in candidate["items"]
    }
    merged_decisions = [
        row
        for row in prior_decisions
        if not (
            row["sourceProvider"] == candidate["sourceProvider"]
            and row["sourceAgentSlug"] == candidate["sourceAgentSlug"]
            and row["itemId"] in decided_item_ids
        )
    ]
    merged_decisions.extend(
        {
            "sourceProvider": candidate["sourceProvider"],
            "sourceAgentSlug": candidate["sourceAgentSlug"],
            "itemId": item_id,
            "decision": current_decision,
            "sourceStateSha256": candidate["sourceStateSha256"],
            "recordedAt": record["recordedAt"],
        }
        for item_id in sorted(decided_item_ids)
    )
    record["identityItemDecisions"] = merged_decisions
    if decision == "decline":
        state["sharedConfigurationReuse"] = record
        _write_lifecycle_state(context, state)
        return copy.deepcopy(record)

    source_path = Path(candidate["sourcePath"])
    source_bytes = source_path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != candidate["sourceStateSha256"]:
        raise ServiceNowConnectError(
            "The shared configuration source changed before reuse was applied."
        )
    source_state = json.loads(source_bytes)
    if not isinstance(source_state, dict):
        raise ServiceNowConnectError(
            "The shared configuration source is invalid."
        )
    source_setup = source_state["adminSetup"]
    target_setup = _admin_setup(state)
    item_ids = set(record["applicableItems"])
    now = _utc_now()

    source_evidence = source_state.get("evidence")
    source_evidence = (
        source_evidence if isinstance(source_evidence, dict) else {}
    )
    source_candidates = source_evidence.get("identityClaimCandidates")
    reused_candidates = None
    if (
        item_ids.intersection({"entra-registration", "servicenow-oidc"})
        and isinstance(source_candidates, dict)
    ):
        target_candidates = state.get("evidence", {}).get(
            "identityClaimCandidates"
        )
        reused_candidates = copy.deepcopy(
            target_candidates
            if (
                "entra-registration" not in item_ids
                and isinstance(target_candidates, dict)
            )
            else source_candidates
        )
        if "entra-registration" in item_ids:
            reused_candidates["binding"] = {
                "tenantId": context["environment"]["tenant_id"],
                "environmentId": context["environment"]["id"],
                "instanceName": candidate["instanceName"],
                "applicationClientId": candidate["applicationClientId"],
                "provider": PROVIDER_KEY,
                "profile": PROFILE_KEY,
                "agentSlug": _agent_slug(context),
                "agentId": context["agent"]["id"],
            }
            reused_candidates["reuseSource"] = {
                "sourceKey": source_key,
                "sourceProvider": candidate["sourceProvider"],
                "sourceAgentSlug": candidate["sourceAgentSlug"],
                "sourceStateSha256": candidate["sourceStateSha256"],
            }
            reused_candidates["recordedAt"] = now
            reused_candidates["candidateSetSha256"] = (
                _identity_candidate_set_hash(
                    application_client_id=reused_candidates[
                        "applicationClientId"
                    ],
                    candidates=list(reused_candidates["candidates"]),
                    binding=reused_candidates["binding"],
                )
            )
        elif (
            reused_candidates.get("applicationClientId")
            != candidate["applicationClientId"]
        ):
            raise ServiceNowConnectError(
                "The target Entra identity evidence changed before OIDC reuse "
                "was applied."
            )
    if "entra-registration" in item_ids and isinstance(
        reused_candidates,
        dict,
    ):
        state.setdefault("evidence", {})[
            "identityClaimCandidates"
        ] = reused_candidates

    source_mapping = source_evidence.get("identityMapping")
    reused_mapping = None
    if (
        "servicenow-oidc" in item_ids
        and isinstance(source_mapping, dict)
        and isinstance(reused_candidates, dict)
    ):
        reused_mapping = copy.deepcopy(source_mapping)
        reused_mapping["binding"] = copy.deepcopy(
            reused_candidates["binding"]
        )
        reused_mapping["candidateSetSha256"] = reused_candidates[
            "candidateSetSha256"
        ]
        reused_mapping["reuseSource"] = {
            "sourceKey": source_key,
            "sourceProvider": candidate["sourceProvider"],
            "sourceAgentSlug": candidate["sourceAgentSlug"],
            "sourceStateSha256": candidate["sourceStateSha256"],
        }
        reused_mapping["recordedAt"] = now
        reused_mapping["relationshipSha256"] = (
            _identity_mapping_relationship_hash(reused_mapping)
        )
        state.setdefault("evidence", {})["identityMapping"] = reused_mapping

    for phase in ("entra-registration", "servicenow-oidc"):
        if phase not in item_ids:
            continue
        source_record = _completed_handoff(source_setup, phase)
        if source_record is None:
            raise ServiceNowConnectError(
                f"The shared {phase} evidence disappeared before reuse."
            )
        reused_evidence = copy.deepcopy(source_record["evidence"])
        reused_evidence["recordedAt"] = now
        reused_evidence["reuseSource"] = {
            "sourceKey": source_key,
            "sourceProvider": candidate["sourceProvider"],
            "sourceAgentSlug": candidate["sourceAgentSlug"],
            "sourceStateSha256": candidate["sourceStateSha256"],
        }
        reused_evidence["binding"] = {
            "tenantId": context["environment"]["tenant_id"],
            "environmentId": context["environment"]["id"],
            "instanceName": candidate["instanceName"],
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
        }
        if phase == "entra-registration" and isinstance(
            reused_candidates,
            dict,
        ):
            reused_evidence["candidateSetSha256"] = reused_candidates[
                "candidateSetSha256"
            ]
            reused_evidence["tokenClaimCandidates"] = copy.deepcopy(
                reused_candidates["candidates"]
            )
        if phase == "servicenow-oidc" and isinstance(reused_mapping, dict):
            reused_evidence["candidateSetSha256"] = reused_mapping[
                "candidateSetSha256"
            ]
            reused_evidence["mappingRelationshipSha256"] = reused_mapping[
                "relationshipSha256"
            ]
            reused_evidence["tokenClaimName"] = reused_mapping[
                "tokenClaimName"
            ]
            reused_evidence["serviceNowUserField"] = reused_mapping[
                "serviceNowUserField"
            ]
            reused_evidence["binding"]["applicationClientId"] = (
                reused_mapping["applicationClientId"]
            )
        target_setup["phaseHandoffs"][phase] = {
            "status": "reused",
            "evidence": reused_evidence,
            "verifiedBy": source_record.get("verifiedBy"),
        }

    state["sharedConfigurationReuse"] = record
    _write_lifecycle_state(context, state)
    return {
        **copy.deepcopy(record),
        "reusedItems": sorted(item_ids),
    }


def inspect_admin_setup(context: dict[str, Any]) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    discovery_error = None
    try:
        connectivity = _connectivity_client(context)
        print(
            "DA_ADMIN_PREFLIGHT_PROGRESS_JSON:"
            + json.dumps(
                {
                    "stage": "connection-inventory",
                    "state": "starting",
                    "mode": "read-only",
                    "httpConnectReadTimeoutSeconds": (
                        CONNECTIVITY_READ_TIMEOUT_SECONDS
                    ),
                    "wholeInvocationDeadline": None,
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
        connections = [
            connection_summary(record)
            for record in connectivity.list_connections()
        ]
    except ServiceNowConnectError as exc:
        connections = []
        discovery_error = {
            "message": str(exc),
            "details": copy.deepcopy(exc.details),
            "observedAt": _utc_now(),
        }
    user_login_connections = sorted(
        [
        connection
        for connection in connections
        if connection.get("authMode") == AUTH_MODE
        ],
        key=lambda connection: (
            str(connection.get("connectionId") or ""),
            str(connection.get("displayName") or ""),
        ),
    )
    preflight = setup["preflight"]
    instance_name = preflight.get("instanceName")
    instance_name = (
        instance_name
        if isinstance(instance_name, str) and instance_name
        else None
    )
    instance_candidates = sorted(
        set(_discovered_instance_candidates(user_login_connections))
        | set(_locally_confirmed_instance_candidates(context))
    )
    instance_question = None
    manual_instance_question = None
    instance_choices: dict[str, str] = {}
    if instance_name is None:
        (
            instance_question,
            instance_choices,
            manual_instance_question,
        ) = _preflight_instance_question(
            context=context,
            candidates=instance_candidates,
            discovery_error=discovery_error,
        )
    handoffs = setup["phaseHandoffs"]
    app_record = handoffs.get("entra-registration")
    client_id = None
    if isinstance(app_record, dict):
        client_id = (app_record.get("evidence") or {}).get("clientId")
    discovery = {
        "source": "connectivity-readonly",
        "observedAt": _utc_now(),
        "scope": setup["scope"],
        "authMode": setup["authMode"],
        "instanceName": instance_name,
        "instanceInputRequired": not bool(instance_name),
        "instanceSelectionRequired": bool(
            instance_name is None and instance_candidates
        ),
        "instanceCandidates": [
            f"https://{candidate}.service-now.com"
            for candidate in instance_candidates
        ],
        "instanceQuestion": instance_question,
        "manualInstanceQuestion": manual_instance_question,
        "instanceChoices": instance_choices,
        "discoveryError": discovery_error,
        "requiredPlugins": required_servicenow_prerequisites(
            setup["scope"],
            setup["authMode"],
        ),
        "connectionCandidates": user_login_connections,
        "credentialResolution": _credential_resolution(
            setup,
            connections,
        ),
        "entraClientId": client_id,
        "links": maker_portal_links(
            context,
            instance_name=instance_name,
        ),
        "limitations": [
            (
                "ServiceNow HR Core plugin and OIDC security objects require "
                "admin confirmation when no supported read-only API is "
                "available."
                if ACTIVE_PROFILE.requires_hr_core
                else (
                    "ServiceNow OIDC security objects require admin "
                    "confirmation when no supported read-only API is "
                    "available."
                )
            ),
            "Entra application setup is confirmed through one target-bound "
            "administrator handoff. The Maker does not run a Microsoft Graph "
            "API recheck.",
        ],
    }
    setup["preflight"]["discovery"] = discovery
    _normalize_preflight_handoff(state, setup)
    _write_lifecycle_state(context, state)
    return discovery


def resolve_credential_completion(
    context: dict[str, Any],
    *,
    selection_key: str | None = None,
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    connections = [
        connection_summary(record)
        for record in _connectivity_client(context).list_connections()
    ]
    resolution = _credential_resolution(setup, connections)
    healthy = [
        connection
        for connection in connections
        if _connection_matches_expected_credential(
            connection,
            expected_instance=resolution["expected"]["instanceName"],
            expected_client_id=resolution["expected"]["resourceUri"],
        )
        and connection.get("status") == "Connected"
        and connection.get("connectionId")
    ]
    healthy = sorted(
        healthy,
        key=lambda connection: (
            str(connection.get("displayName") or ""),
            str(connection.get("connectionId") or ""),
        ),
    )
    if selection_key is not None:
        selected = next(
            (
                connection
                for connection in healthy
                if _credential_selection_key(
                    str(connection["connectionId"])
                )
                == selection_key
            ),
            None,
        )
        if selected is None:
            raise ServiceNowConnectError(
                "The selected ServiceNow connection is no longer an exact "
                "healthy candidate. Refresh and select again."
            )
        evidence = record_credential_selection(
            context,
            str(selected["connectionId"]),
        )
        return {
            "status": "selected",
            "selection": {
                "label": selected.get("displayName"),
            },
            "evidence": evidence,
        }
    if len(healthy) == 1:
        evidence = record_credential_selection(
            context,
            str(healthy[0]["connectionId"]),
        )
        return {
            "status": "selected",
            "selection": {
                "label": healthy[0].get("displayName"),
            },
            "evidence": evidence,
        }
    if len(healthy) > 1:
        return {
            "status": "choice-required",
            "candidates": resolution["healthyExactCandidates"],
            "message": (
                "Multiple exact healthy ServiceNow connections are available. "
                "Select one candidate by label."
            ),
        }
    unhealthy_exact = int(resolution.get("unhealthyExactCount") or 0)
    return {
        "status": "not-ready",
        "expected": resolution["expected"],
        "unhealthyExactCount": resolution["unhealthyExactCount"],
        "remediation": (
            (
                "A ServiceNow connection with these settings exists, but it "
                "doesn't show Connected. In Copilot Studio, open Settings > "
                "Connection Settings > ServiceNow, sign in again so it shows "
                "Connected, and save the agent settings. Then tell me again."
            )
            if unhealthy_exact
            else (
                "I couldn't find a Connected ServiceNow connection that "
                "matches this setup (Microsoft Entra ID User Login, the "
                "instance name, and the Resource URI shown in the card) in "
                "this environment. Finish creating it in Copilot Studio "
                "(Settings > Connection Settings > ServiceNow > Connect > "
                "Create new connection), or check that you used the same "
                "values and environment. Then tell me again."
            )
        ),
    }


def _validated_claim_candidates(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    require_completion: bool = True,
) -> dict[str, Any]:
    receipt = state.get("evidence", {}).get("identityClaimCandidates")
    if (
        not isinstance(receipt, dict)
        or receipt.get("kind")
        != "administrator-confirmed-claim-candidates"
        or receipt.get("entraAdministratorConfirmed") is not True
        or not isinstance(receipt.get("candidates"), list)
        or not receipt["candidates"]
        or (
            require_completion
            and len(receipt.get("candidates") or []) != 1
        )
    ):
        raise ServiceNowConnectError(
            "Current target-bound Entra client ID and selected User Claim "
            "evidence is required."
        )
    expected = _required_context_identity(context, state)
    binding = receipt.get("binding")
    if not isinstance(binding, dict):
        raise ServiceNowConnectError(
            "Claim candidate evidence has no target binding."
        )
    for field, value in expected.items():
        if str(binding.get(field) or "").casefold() != value.casefold():
            raise ServiceNowConnectError(
                "Claim candidate evidence does not match the active target."
            )
    if (
        str(binding.get("applicationClientId") or "").casefold()
        != str(receipt.get("applicationClientId") or "").casefold()
    ):
        raise ServiceNowConnectError(
            "Claim candidate evidence does not match the recorded "
            "Application client ID."
        )
    receipt_tenant_id = receipt.get("directoryTenantId")
    if receipt_tenant_id and (
        _normalize_directory_tenant_id(str(receipt_tenant_id))
        != _normalize_directory_tenant_id(expected["tenantId"])
    ):
        raise ServiceNowConnectError(
            "The confirmed Directory tenant ID does not match the active "
            "target."
        )
    if (
        binding.get("provider") != PROVIDER_KEY
        or binding.get("profile") != PROFILE_KEY
        or str(binding.get("agentSlug") or "").casefold()
        != _agent_slug(context).casefold()
        or str(binding.get("agentId") or "").casefold()
        != str(context["agent"]["id"]).casefold()
    ):
        raise ServiceNowConnectError(
            "Claim candidate evidence does not match the active agent."
        )
    expected_hash = _identity_candidate_set_hash(
        application_client_id=receipt["applicationClientId"],
        candidates=list(receipt["candidates"]),
        binding=binding,
    )
    if receipt.get("candidateSetSha256") != expected_hash:
        raise ServiceNowConnectError(
            "Claim candidate evidence hash does not match its scoped values."
        )
    return receipt


def _validated_identity_mapping(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    candidates = _validated_claim_candidates(context, state)
    mapping = state.get("evidence", {}).get("identityMapping")
    candidate_client_id = normalize_client_id(
        str(candidates.get("applicationClientId") or "")
    )
    mapping_client_id = (
        normalize_client_id(str(mapping.get("applicationClientId") or ""))
        if isinstance(mapping, dict)
        else None
    )
    if (
        not isinstance(mapping, dict)
        or mapping.get("kind")
        != "administrator-confirmed-identity-mapping"
        or mapping.get("serviceNowAdministratorConfirmed") is not True
        or mapping_client_id != candidate_client_id
        or mapping.get("binding") != candidates.get("binding")
        or mapping.get("candidateSetSha256")
        != candidates.get("candidateSetSha256")
        or mapping.get("tokenClaimName") not in candidates["candidates"]
        or not _SAFE_USER_FIELD.fullmatch(
            str(mapping.get("serviceNowUserField") or "")
        )
    ):
        raise ServiceNowConnectError(
            "A valid ServiceNow-selected claim and user-field pair is "
            "required."
        )
    if (
        mapping.get("relationshipSha256")
        != _identity_mapping_relationship_hash(mapping)
    ):
        raise ServiceNowConnectError(
            "The selected identity mapping relationship hash is stale."
        )
    return mapping


def record_admin_phase(
    context: dict[str, Any],
    *,
    phase: str,
    status: str,
    client_id: str | None = None,
    application_registration_confirmed: bool = False,
    claim_emission_confirmed: bool = False,
    user_impersonation_scope_confirmed: bool = False,
    connector_preauthorization_confirmed: bool = False,
    configuration_saved_confirmed: bool = False,
    oidc_provider_confirmed: bool = False,
    claim_mapping_confirmed: bool = False,
    active_user_match_confirmed: bool = False,
) -> dict[str, Any]:
    if phase not in ADMIN_PHASES:
        raise ServiceNowConnectError("Unsupported ServiceNow admin phase.")
    if status not in {"completed", "reused"}:
        raise ServiceNowConnectError(
            "Admin operation status must be completed or reused."
        )
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    prior_handoff = setup["phaseHandoffs"].get(phase)
    prior_evidence = (
        prior_handoff.get("evidence")
        if isinstance(prior_handoff, dict)
        else None
    )
    prior_evidence = (
        copy.deepcopy(prior_evidence)
        if isinstance(prior_evidence, dict)
        else {}
    )

    evidence: dict[str, Any] = {
        "kind": "structured-admin-attestation",
        "ownerBoundary": "admin-owned-guided-workflow",
        "recordedAt": _utc_now(),
        "binding": {
            "tenantId": context["environment"]["tenant_id"],
            "environmentId": context["environment"]["id"],
            "instanceName": (
                setup.get("preflight", {}).get("instanceName")
            ),
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
        },
    }
    if phase == "entra-registration":
        confirmations = {
            "application registration": application_registration_confirmed,
            "selected claim emission": claim_emission_confirmed,
            "user_impersonation scope": user_impersonation_scope_confirmed,
            "Microsoft ServiceNow connector preauthorization": (
                connector_preauthorization_confirmed
            ),
        }
        missing = [
            label
            for label, confirmed in confirmations.items()
            if confirmed is not True
        ]
        if missing:
            raise ServiceNowConnectError(
                "Entra completion requires explicit confirmation of all four "
                "current-target requirements: "
                + ", ".join(missing)
                + "."
            )
        candidates = _validated_claim_candidates(
            context,
            state,
            require_completion=False,
        )
        receipt_client_id = normalize_client_id(
            str(candidates.get("applicationClientId") or "")
        )
        normalized_client_id = (
            normalize_client_id(client_id)
            if client_id is not None
            else receipt_client_id
        )
        if receipt_client_id != normalized_client_id:
            raise ServiceNowConnectError(
                "The explicitly supplied Application client ID conflicts "
                "with the Entra-confirmed receipt."
            )
        selected_claims = list(candidates.get("candidates") or [])
        if len(selected_claims) != 1:
            raise ServiceNowConnectError(
                "The current Entra administrator confirmation requires one "
                "explicit selected user claim. Return a current one-claim "
                "handoff; do not choose or infer a claim from older fields."
            )
        evidence.update(
            {
                "currentSource": "administrator-confirmed",
                "entraAdministratorConfirmed": True,
                "applicationRegistrationConfirmed": (
                    application_registration_confirmed
                ),
                "clientId": normalized_client_id,
                "directoryTenantId": (
                    candidates.get("directoryTenantId")
                    or candidates["binding"]["tenantId"]
                ),
                "tokenClaimCandidates": copy.deepcopy(
                    selected_claims
                ),
                "selectedClaimName": selected_claims[0],
                "tokenClaimEmissionConfirmed": claim_emission_confirmed,
                "userImpersonationScopeConfirmed": (
                    user_impersonation_scope_confirmed
                ),
                "connectorPreauthorizationConfirmed": (
                    connector_preauthorization_confirmed
                ),
                "candidateSetSha256": candidates["candidateSetSha256"],
                "mappingWorkbookSha256": candidates[
                    "importedWorkbookSha256"
                ],
            }
        )
        candidates["tokenClaimEmissionConfirmed"] = True
        candidates["completionConfirmedAt"] = _utc_now()
        state.setdefault("evidence", {})[
            "identityClaimCandidates"
        ] = candidates
        evidence["binding"]["applicationClientId"] = normalized_client_id
    elif client_id is not None:
        raise ServiceNowConnectError(
            "Application client ID is accepted only for entra-registration."
        )

    if phase == "plugin-prerequisites":
        evidence.update(
            {
                "pluginId": "com.sn_hr_core",
                "applicationTitle": "Human Resources Scoped App: Core",
                "versionDetails": "Installed",
                "installedReadyMessageConfirmed": True,
            }
        )

    if phase == "servicenow-oidc":
        configuration_saved = bool(
            configuration_saved_confirmed or oidc_provider_confirmed
        )
        if not (configuration_saved and claim_mapping_confirmed):
            raise ServiceNowConnectError(
                "ServiceNow OIDC completion requires explicit confirmation "
                "that the exact configuration is saved and the locked User "
                "Claim is mapped to the recorded User Field."
            )
        mapping = _validated_identity_mapping(context, state)
        evidence.update(
            {
                "oidcCapabilityConfirmed": configuration_saved,
                "configurationSavedConfirmed": configuration_saved,
                "runbookCompleted": bool(
                    configuration_saved and claim_mapping_confirmed
                ),
                "mappingDetailsCollected": True,
                "claimMappingConfirmed": claim_mapping_confirmed,
                "tokenClaimName": mapping["tokenClaimName"],
                "serviceNowUserField": mapping["serviceNowUserField"],
                "candidateSetSha256": mapping["candidateSetSha256"],
                "mappingWorkbookSha256": mapping[
                    "importedWorkbookSha256"
                ],
                "mappingRelationshipSha256": mapping[
                    "relationshipSha256"
                ],
            }
        )
        if active_user_match_confirmed:
            evidence["activeUserMatchConfirmed"] = True
        if "connectorPreauthorizationConfirmed" in prior_evidence:
            evidence["connectorPreauthorizationConfirmed"] = prior_evidence[
                "connectorPreauthorizationConfirmed"
            ]
        evidence["binding"]["applicationClientId"] = mapping[
            "applicationClientId"
        ]

    record = {
        "status": status,
        "evidence": evidence,
        "verifiedBy": (
            "administrator-confirmed-local-validation"
            if phase == "entra-registration"
            else "structured-attestation"
        ),
    }
    setup["phaseHandoffs"][phase] = record
    if phase == "servicenow-oidc":
        _reconcile_servicenow_handoff_from_receipt(context, state)
    _write_lifecycle_state(context, state)
    return copy.deepcopy(record)


def inspect(context: dict[str, Any], *, offline: bool = False) -> dict[str, Any]:
    if offline:
        components = _load_json(context["snapshotPath"])
    else:
        components = _agentbuilder_client(context).fetch_components(
            context["agent"]["id"]
        )
    summary = summarize_components(components)
    result = {
        "mode": "offline" if offline else "live",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "componentHash": _component_hash(components),
        "components": summary,
        "links": maker_portal_links(
            context,
            instance_name=(
                _admin_setup(
                    _load_lifecycle_state(context, components)
                )["preflight"].get("instanceName")
            ),
        ),
    }
    if not offline:
        connectivity = _connectivity_client(context)
        connections = [
            connection_summary(record)
            for record in connectivity.list_connections()
        ]
        result["connectivity"] = {
            "connections": connections,
            "userConnectionBinding": {
                "mode": "maker-ui",
                "automationAvailable": False,
                "requiredDelegatedScope": "PowerVirtualAgents.Tokens.Read",
            },
        }
        state = _state_for_components(context, components)
        result["progress"] = _inspection_progress(state, result)
        state.setdefault("evidence", {})["lastInspection"] = result
        _write_lifecycle_state(context, state)
    return result


def inspect_portal_configuration(
    context: dict[str, Any],
    *,
    offline: bool = False,
    expected_portal_url: str | None = None,
) -> dict[str, Any]:
    components = (
        _load_json(context["snapshotPath"])
        if offline
        else _agentbuilder_client(context).fetch_components(
            context["agent"]["id"]
        )
    )
    state = _load_lifecycle_state(context, components)
    expected_instance = _admin_setup(state)["preflight"].get("instanceName")
    summary = portal_configuration_summary(
        components,
        expected_instance_name=(
            expected_instance
            if isinstance(expected_instance, str)
            else None
        ),
    )
    topic = _portal_topic_component(components)
    current_portal_url = (
        normalize_portal_url(
            _portal_literal_value(topic),
            expected_instance_name=expected_instance,
        )
        if summary["valid"]
        and isinstance(expected_instance, str)
        and expected_instance
        else None
    )
    confirmed_portal_url = (
        portal_confirmation_url(
            state,
            topic=topic,
            current_portal_url=current_portal_url,
            expected_instance_name=expected_instance,
        )
        if current_portal_url is not None
        else None
    )
    verification_url = expected_portal_url
    explicit_root_confirmed = True
    if (
        summary["valid"]
        and summary["path"] == "/"
        and verification_url is None
    ):
        verification_url = confirmed_portal_url
        explicit_root_confirmed = verification_url is not None
    expected_match: bool | None = None
    if verification_url is not None:
        if not isinstance(expected_instance, str) or not expected_instance:
            raise ServiceNowConnectError(
                "The lifecycle has no confirmed ServiceNow instance."
            )
        expected = normalize_portal_url(
            verification_url,
            expected_instance_name=expected_instance,
        )
        current = (
            normalize_portal_url(
                _portal_literal_value(_portal_topic_component(components)),
                expected_instance_name=expected_instance,
            )
            if summary["valid"]
            else None
        )
        expected_match = current == expected
    configured = (
        summary["valid"]
        and expected_match is not False
        and explicit_root_confirmed
    )
    return {
        "status": "configured" if configured else "input-required",
        "mode": "offline" if offline else "live",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "portal": summary,
        "confirmationRecorded": confirmed_portal_url is not None,
        "expectedPortalUrlMatch": expected_match,
        "input": (
            None
            if configured
            else {
                "field": "portalUrl",
                "description": (
                    "Explicit administrator confirmation of this exact root "
                    "ServiceNow URL for the employee portal."
                    if not explicit_root_confirmed
                    else (
                    "The exact administrator-confirmed full ServiceNow "
                    "employee portal URL supplied for this phase."
                    if expected_match is False
                    else (
                        "Administrator-confirmed full ServiceNow employee "
                        "portal URL. Use a root URL only when the administrator "
                        "explicitly confirms that exact value."
                    )
                    )
                ),
            }
        ),
    }


def _portal_confirmation_binding(
    state: dict[str, Any],
    topic: dict[str, Any],
    *,
    instance_name: str,
) -> dict[str, str]:
    return {
        "provider": str(state.get("provider") or ""),
        "profile": str(state.get("profile") or ""),
        "agentSlug": str(state.get("agentSlug") or ""),
        "agentId": str(state.get("agentId") or ""),
        "environmentId": str(state.get("environmentId") or ""),
        "tenantId": str(state.get("tenantId") or ""),
        "instanceName": instance_name,
        "topicId": str(topic.get("id") or ""),
        "topicSchemaName": str(topic.get("schemaName") or ""),
    }


def _record_portal_confirmation(
    state: dict[str, Any],
    *,
    topic: dict[str, Any],
    portal_url: str,
    instance_name: str,
    source: str,
) -> dict[str, Any]:
    now = _utc_now()
    receipt = {
        "kind": "maker-confirmed-portal-url",
        "status": "confirmed",
        "source": source,
        "portalUrl": portal_url,
        "recordedAt": now,
        "readbackAt": now,
        "binding": _portal_confirmation_binding(
            state,
            topic,
            instance_name=instance_name,
        ),
        "readbackEvidence": {
            "topicVersion": topic.get("version"),
            "topicContentHashExcludingVersion": _component_content_hash(topic),
        },
    }
    state.setdefault("evidence", {})["portalConfirmation"] = receipt
    return receipt


def portal_confirmation_url(
    state: dict[str, Any],
    *,
    topic: dict[str, Any],
    current_portal_url: str | None,
    expected_instance_name: str | None,
) -> str | None:
    if (
        not isinstance(current_portal_url, str)
        or not current_portal_url
        or not isinstance(expected_instance_name, str)
        or not expected_instance_name
    ):
        return None
    evidence = state.get("evidence")
    receipt = (
        evidence.get("portalConfirmation")
        if isinstance(evidence, dict)
        else None
    )
    if not isinstance(receipt, dict):
        return None
    binding = receipt.get("binding")
    if (
        receipt.get("kind") != "maker-confirmed-portal-url"
        or receipt.get("status") != "confirmed"
        or not isinstance(receipt.get("recordedAt"), str)
        or not receipt["recordedAt"]
        or not isinstance(receipt.get("readbackAt"), str)
        or not receipt["readbackAt"]
        or binding
        != _portal_confirmation_binding(
            state,
            topic,
            instance_name=expected_instance_name,
        )
    ):
        return None
    try:
        confirmed_url = normalize_portal_url(
            str(receipt.get("portalUrl") or ""),
            expected_instance_name=expected_instance_name,
        )
    except ServiceNowConnectError:
        return None
    return confirmed_url if confirmed_url == current_portal_url else None


def prepare_manual_connection(
    context: dict[str, Any],
    *,
    instance_name: str | None,
    resource_uri: str | None,
    display_name: str | None,
) -> dict[str, Any]:
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _state_for_components(context, components)
    setup = _admin_setup(state)
    app_record = setup["phaseHandoffs"].get("entra-registration")
    app_evidence = (
        app_record.get("evidence")
        if isinstance(app_record, dict)
        else {}
    )
    if not isinstance(app_evidence, dict):
        app_evidence = {}
    validated_instance = setup["preflight"].get("instanceName")
    validated_resource = app_evidence.get("clientId")
    supplied_instance = (
        normalize_instance_name(str(instance_name))
        if instance_name
        else None
    )
    if resource_uri and str(resource_uri).casefold().startswith("api://"):
        raise ServiceNowConnectError(
            "Resource URI must be the Application client ID, not api:// URI."
        )
    supplied_resource = (
        normalize_client_id(str(resource_uri))
        if resource_uri
        else None
    )
    if not validated_instance or not validated_resource:
        missing_fields = []
        if not validated_resource:
            missing_fields.append("resourceUri")
        if not validated_instance:
            missing_fields.append("instanceName")
        return {
            "status": "input-required",
            "creationMode": "manual",
            "agentId": context["agent"]["id"],
            "environmentId": context["environment"]["id"],
            "missingFields": missing_fields,
            "knownValues": {
                "resourceUri": validated_resource,
                "instanceName": validated_instance,
            },
            "expectedValues": connection_expected_values(
                resource_uri=(
                    str(validated_resource)
                    if validated_resource
                    else None
                ),
                instance_name=(
                    str(validated_instance)
                    if validated_instance
                    else None
                ),
            ),
            "message": (
                "The lifecycle does not contain every validated value "
                "required to prepare the ServiceNow connection."
            ),
        }
    instance_name = normalize_instance_name(str(validated_instance))
    resource_uri = normalize_client_id(str(validated_resource))
    if supplied_instance and supplied_instance != instance_name:
        raise ServiceNowConnectError(
            "Instance Name must match the confirmed lifecycle target."
        )
    if supplied_resource and supplied_resource != resource_uri:
        raise ServiceNowConnectError(
            "Resource URI must match the verified App A Application client ID."
        )
    preparation = {
        "connectionId": None,
        "displayName": (
            display_name or ACTIVE_PROFILE.connection_display_name
        ),
        "status": "maker-action-required",
        "authMode": "entraIDUserLogin",
        "resourceUri": resource_uri,
        "instanceName": instance_name,
        "createdBySkill": False,
    }
    state.setdefault("evidence", {})["credentialPreparation"] = preparation
    _write_lifecycle_state(context, state)
    return {
        "status": "maker-action-required",
        "creationMode": "manual",
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "connection": preparation,
        "expectedValues": connection_expected_values(
            display_name=preparation["displayName"],
            resource_uri=resource_uri,
            instance_name=instance_name,
        ),
        "navigation": physical_connection_navigation(
            context,
            mode="create",
        ),
        "conditionalRemediations": [
            {
                "condition": "sign-in reports Invalid_redirect_uri",
                "observed": False,
                "action": (
                    "URL-decode the exact redirect_uri reported by the "
                    "sign-in page, update the ServiceNow OIDC Application "
                    "Registry redirect URL, and retry."
                ),
            }
        ],
        "instructions": [
            (
                "Open the selected environment Connections list from the "
                "returned navigation fallback."
            ),
            "Select New connection.",
            "Use the search box in the upper-right to search ServiceNow.",
            (
                "Select the Microsoft-published ServiceNow connector by "
                "choosing its + action."
            ),
            "Choose Microsoft Entra ID User Login.",
            "Enter the Resource URI and Instance Name shown in this output.",
            "Select Sign in, complete authentication, then select Submit.",
            "Wait until the credential status is Connected.",
            "Return to VS Code after the physical connection shows Connected.",
        ],
        "afterCompletion": {
            "command": "python scripts/connect_servicenow_da.py inspect",
            "expected": (
                "A ServiceNow credential with status Connected, followed by "
                "maker confirmation that it was connected to the agent."
            ),
        },
    }


def _healthy_connection(
    context: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    connectivity = _connectivity_client(context)
    physical = connection_summary(connectivity.get_connection(connection_id))
    if physical.get("status") != "Connected":
        raise ServiceNowConnectError(
            "The physical ServiceNow connection is not Connected."
        )
    if physical.get("authMode") != "entraIDUserLogin":
        raise ServiceNowConnectError(
            "The physical ServiceNow connection must use Microsoft Entra ID "
            "User Login."
        )
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    expected_instance = setup["preflight"].get("instanceName")
    app_record = setup["phaseHandoffs"].get("entra-registration")
    app_evidence = (
        app_record.get("evidence")
        if isinstance(app_record, dict)
        else {}
    )
    if not isinstance(app_evidence, dict):
        app_evidence = {}
    expected_client_id = app_evidence.get("clientId")
    values = physical.get("parameterValues")
    if not isinstance(values, dict):
        values = {}
    actual_instance = values.get("token:InstanceName") or values.get("instance")
    actual_resource = values.get("token:ResourceUri")
    if expected_instance:
        if not actual_instance:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection did not expose its "
                "Instance Name for exact verification."
            )
        if normalize_instance_name(str(actual_instance)) != expected_instance:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection targets a different "
                "Instance Name."
            )
    if expected_client_id:
        if not actual_resource:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection did not expose its "
                "Resource URI for exact verification."
            )
        if normalize_client_id(str(actual_resource)) != expected_client_id:
            raise ServiceNowConnectError(
                "The physical ServiceNow connection Resource URI does not "
                "match the verified Application client ID."
            )
    return physical


def record_credential_selection(
    context: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    physical = _healthy_connection(context, connection_id)
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _load_lifecycle_state(context, components)
    setup = _admin_setup(state)
    values = physical.get("parameterValues")
    values = values if isinstance(values, dict) else {}
    instance_name = values.get("token:InstanceName") or values.get("instance")
    resource_uri = values.get("token:ResourceUri")
    normalized_connection_id = uuid.UUID(connection_id).hex
    evidence = {
        "connectionId": normalized_connection_id,
        "displayName": physical.get("displayName"),
        "connectorId": CONNECTOR_ID,
        "physicalStatus": physical.get("status"),
        "authMode": physical.get("authMode"),
        "environmentId": context["environment"]["id"],
        "selectedAt": _utc_now(),
        "lastVerifiedAt": _utc_now(),
        "instanceName": (
            normalize_instance_name(str(instance_name))
            if instance_name
            else setup["preflight"].get("instanceName")
        ),
        "resourceUri": (
            normalize_client_id(str(resource_uri))
            if resource_uri
            else (
                (
                    setup["phaseHandoffs"]
                    .get("entra-registration", {})
                    .get("evidence", {})
                    .get("clientId")
                )
            )
        ),
        "parameterMetadata": copy.deepcopy(
            physical.get("parameterValues") or {}
        ),
    }
    state_evidence = state.setdefault("evidence", {})
    state_evidence["credential"] = evidence
    proof = _verified_agent_binding_proof(
        context,
        state,
        components,
        physical,
    )
    state_evidence["agentConnection"] = proof
    state["agentBindingIdentitySha256"] = proof["binding"][
        "bindingIdentitySha256"
    ]
    state["connectionBindingHash"] = _connection_binding_hash_for_identity(
        proof["binding"]["bindingIdentity"],
        recorded_at=proof["recordedAt"],
    )
    setup["phaseHandoffs"]["credential"] = {
        "status": "completed",
        "evidence": {
            "kind": "maker-connection-return",
            "connectionId": normalized_connection_id,
            "displayName": physical.get("displayName"),
            "recordedAt": _utc_now(),
        },
    }
    _write_lifecycle_state(context, state)
    return evidence


def _verified_agent_binding_proof(
    context: dict[str, Any],
    state: dict[str, Any],
    components: dict[str, Any],
    physical: dict[str, Any],
) -> dict[str, Any]:
    """Prove the agent's saved draft references the selected connection.

    Raises a recovery-specific error before any state is persisted, so the
    merged credential phase is never completed without both proofs.
    """
    credential = state["evidence"]["credential"]
    selected_id = str(credential["connectionId"]).replace("-", "")
    display_name = physical.get("displayName") or "the connection you created"
    recovery_details = {
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "requiredPhase": "credential",
    }
    try:
        reference = find_servicenow_reference(components)
    except ServiceNowConnectError as exc:
        raise ServiceNowConnectError(
            "The connection exists and shows Connected, but I could not find "
            "this agent's ServiceNow connection in its saved settings. In "
            "Copilot Studio, open the agent, go to Settings > Connection "
            "Settings > ServiceNow, select the connection, and save. Then "
            "tell me again.",
            details={**recovery_details, "blockingIssue": "agent-reference-missing"},
        ) from exc
    parameters = _shared_parameters(reference)
    reference_id = str(reference.get("connectionId") or "").replace("-", "")
    if not reference_id:
        raise ServiceNowConnectError(
            f"**{display_name}** is created and Connected, but this agent's "
            "saved settings don't use it yet. In Copilot Studio, go to "
            "Settings > Connection Settings > ServiceNow, select "
            f"**{display_name}**, and save the agent settings. Then tell me "
            "again. You don't need to create the connection again.",
            details={**recovery_details, "blockingIssue": "agent-not-bound"},
        )
    if reference_id.casefold() != selected_id.casefold():
        raise ServiceNowConnectError(
            "This agent's saved settings use a different ServiceNow "
            f"connection than **{display_name}**. In Copilot Studio, go to "
            "Settings > Connection Settings > ServiceNow, select "
            f"**{display_name}**, and save the agent settings. Then tell me "
            "again.",
            details={**recovery_details, "blockingIssue": "agent-bound-elsewhere"},
        )
    expected = {
        "authentication type": (parameters.get("name"), AUTH_MODE),
        "instance name": (
            _parameter_value(parameters, "token:InstanceName"),
            credential.get("instanceName"),
        ),
        "Resource URI": (
            _parameter_value(parameters, "token:ResourceUri"),
            credential.get("resourceUri"),
        ),
    }
    for label, (actual, wanted) in expected.items():
        if actual and wanted and str(actual).casefold() != str(wanted).casefold():
            raise ServiceNowConnectError(
                f"This agent's saved ServiceNow settings use a different "
                f"{label} than the connection you created. Select "
                f"**{display_name}** again in Settings > Connection "
                "Settings > ServiceNow and save the agent settings. Then "
                "tell me again.",
                details={**recovery_details, "blockingIssue": "agent-binding-mismatch"},
            )
    binding_identity = _agent_binding_identity(context, state, components)
    binding_identity_sha256 = _canonical_json_hash(binding_identity)
    recorded_at = _utc_now()
    return {
        "kind": "binding-proof",
        "status": "completed",
        "mode": "adk-verified",
        "verificationSource": "saved-draft-connection-reference",
        "bindingVerified": True,
        "connectionId": selected_id,
        "displayName": physical.get("displayName"),
        "physicalStatus": physical.get("status"),
        "authMode": physical.get("authMode"),
        "recordedAt": recorded_at,
        "physicalVerifiedAt": recorded_at,
        "binding": {
            "connectionId": selected_id,
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "bindingIdentity": binding_identity,
            "bindingIdentitySha256": binding_identity_sha256,
        },
    }


def set_topic_state(
    context: dict[str, Any],
    topic_id: str,
    target_state: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Topic state mutation requires explicit confirmation (--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    state = _load_lifecycle_state(context, before)
    _require_current_agent_binding(context, state, before)
    before_topic = find_servicenow_topic(before, topic_id)
    before_state = before_topic.get("state")
    before_status = before_topic.get("status")
    changed = (
        before_state != target_state
        or before_status != target_state
    )
    if changed:
        payload = build_topic_state_update_payload(
            before,
            topic_id,
            target_state,
        )
        agentbuilder.update_components(context["agent"]["id"], payload)
    after = agentbuilder.fetch_components(context["agent"]["id"])
    after_topic = find_servicenow_topic(after, topic_id)
    if (
        after_topic.get("state") != target_state
        or after_topic.get("status") != target_state
    ):
        raise ServiceNowConnectError(
            "MinimalBot update completed without the expected topic state."
        )
    return {
        "topicId": str(uuid.UUID(topic_id)),
        "displayName": after_topic.get("displayName"),
        "schemaName": after_topic.get("schemaName"),
        "previousState": before_state,
        "previousStatus": before_status,
        "state": after_topic.get("state"),
        "status": after_topic.get("status"),
        "previousVersion": before_topic.get("version"),
        "version": after_topic.get("version"),
        "changed": changed,
        "published": False,
    }


def _servicenow_topic_components(
    components: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    topics: dict[str, dict[str, Any]] = {}
    for change in components.get("botComponentChanges") or []:
        component = change.get("component")
        if (
            isinstance(component, dict)
            and _profile_topic_suffix(change) is not None
            and component.get("id")
        ):
            topics[str(component["id"]).casefold()] = component
    return topics


def _component_content_hash(component: dict[str, Any]) -> str:
    normalized = copy.deepcopy(component)
    normalized.pop("version", None)
    normalized.pop("auditInfo", None)
    return _canonical_json_hash(normalized)


def _draft_semantic_hash(components: dict[str, Any]) -> str:
    topics: list[dict[str, Any]] = []
    changes = components.get("botComponentChanges")
    if not isinstance(changes, list):
        raise ServiceNowConnectError(
            "MinimalBot component state has an invalid topic collection."
        )
    for change in changes:
        if not isinstance(change, dict):
            raise ServiceNowConnectError(
                "MinimalBot topic collection contains an invalid change."
            )
        component = change.get("component")
        if not isinstance(component, dict):
            continue
        if _profile_topic_suffix(change) is None:
            continue
        normalized = copy.deepcopy(component)
        normalized.pop("version", None)
        normalized.pop("auditInfo", None)
        topics.append(normalized)
    topics.sort(
        key=lambda component: (
            str(component.get("id") or ""),
            str(component.get("schemaName") or ""),
        )
    )
    reference = copy.deepcopy(find_servicenow_reference(components))
    reference.pop("version", None)
    reference.pop("auditInfo", None)
    reference["sharedConnectionParameters"] = _shared_parameters(reference)
    projection = {
        "serviceNowTopics": topics,
        "serviceNowReference": reference,
    }
    return _canonical_json_hash(projection)


def _agent_binding_identity(
    context: dict[str, Any],
    state: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    credential = state.get("evidence", {}).get("credential")
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording the "
            "agent binding."
        )
    reference = find_servicenow_reference(components)
    parameters = _shared_parameters(reference)
    return {
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "physicalConnection": {
            "connectionId": str(credential.get("connectionId") or "").replace(
                "-",
                "",
            ),
            "connectorId": str(
                credential.get("connectorId") or CONNECTOR_ID
            ),
            "environmentId": str(
                credential.get("environmentId")
                or context["environment"]["id"]
            ),
            "physicalStatus": credential.get("physicalStatus"),
            "authMode": credential.get("authMode"),
            "instanceName": credential.get("instanceName"),
            "resourceUri": credential.get("resourceUri"),
        },
        "connectionReference": {
            "id": reference.get("id"),
            "logicalName": reference.get("connectionReferenceLogicalName"),
            "connectorId": reference.get("connectorId"),
            "connectionId": (
                str(reference.get("connectionId") or "").replace("-", "")
                or None
            ),
            "authMode": parameters.get("name"),
            "instanceName": _parameter_value(
                parameters,
                "token:InstanceName",
            ),
            "resourceUri": _parameter_value(
                parameters,
                "token:ResourceUri",
            ),
        },
    }


def _legacy_agent_binding_identity(
    state: dict[str, Any],
) -> dict[str, Any] | None:
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    credential = evidence.get("credential")
    attestation = evidence.get("agentConnection")
    binding = (
        attestation.get("binding")
        if isinstance(attestation, dict)
        else None
    )
    reference = state.get("reference")
    if (
        not isinstance(credential, dict)
        or not isinstance(attestation, dict)
        or not isinstance(binding, dict)
        or not isinstance(reference, dict)
        or attestation.get("kind") != "maker-attestation"
        or attestation.get("status") != "completed"
        or attestation.get("makerAttested") is not True
        or attestation.get("physicalStatus") != "Connected"
        or attestation.get("authMode") != AUTH_MODE
    ):
        return None
    connection_id = str(credential.get("connectionId") or "").replace("-", "")
    if (
        not connection_id
        or str(attestation.get("connectionId") or "").replace("-", "")
        != connection_id
        or str(binding.get("connectionId") or connection_id).replace("-", "")
        != connection_id
    ):
        return None
    expected_binding = {
        "provider": state.get("provider"),
        "profile": state.get("profile"),
        "agentSlug": state.get("agentSlug"),
        "agentId": state.get("agentId"),
        "environmentId": state.get("environmentId"),
    }
    if any(
        str(binding.get(key) or "").casefold()
        != str(value or "").casefold()
        for key, value in expected_binding.items()
    ):
        return None
    instance_name = credential.get("instanceName")
    resource_uri = credential.get("resourceUri")
    if (
        credential.get("physicalStatus") != "Connected"
        or credential.get("authMode") != AUTH_MODE
        or not instance_name
        or not resource_uri
        or not reference.get("id")
        or not reference.get("logicalName")
        or reference.get("authMode") != AUTH_MODE
        or reference.get("instanceName") != instance_name
        or str(reference.get("resourceUri") or "").casefold()
        != str(resource_uri).casefold()
    ):
        return None
    return {
        **expected_binding,
        "physicalConnection": {
            "connectionId": connection_id,
            "connectorId": str(
                credential.get("connectorId") or CONNECTOR_ID
            ),
            "environmentId": str(
                credential.get("environmentId")
                or state.get("environmentId")
                or ""
            ),
            "physicalStatus": credential.get("physicalStatus"),
            "authMode": credential.get("authMode"),
            "instanceName": instance_name,
            "resourceUri": resource_uri,
        },
        "connectionReference": {
            "id": reference.get("id"),
            "logicalName": reference.get("logicalName"),
            "connectorId": CONNECTOR_ID,
            "connectionId": (
                str(reference.get("connectionId") or "").replace("-", "")
                or None
            ),
            "authMode": reference.get("authMode"),
            "instanceName": reference.get("instanceName"),
            "resourceUri": reference.get("resourceUri"),
        },
    }


def _connection_binding_hash_for_identity(
    binding_identity: dict[str, Any],
    *,
    recorded_at: Any,
) -> str:
    return _canonical_json_hash(
        {
            "bindingIdentity": binding_identity,
            "agentConnectionRecordedAt": recorded_at,
        }
    )


def _agent_binding_identity_hash(
    context: dict[str, Any],
    state: dict[str, Any],
    components: dict[str, Any],
) -> str:
    return _canonical_json_hash(
        _agent_binding_identity(context, state, components)
    )


def _agent_binding_proof_current(
    state: dict[str, Any],
    components: dict[str, Any],
) -> bool:
    credential = state.get("evidence", {}).get("credential")
    attestation = state.get("evidence", {}).get("agentConnection")
    attestation_binding = (
        attestation.get("binding")
        if isinstance(attestation, dict)
        else None
    )
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        return False
    normalized_connection_id = str(credential["connectionId"]).replace("-", "")
    try:
        current_identity = _agent_binding_identity(
            {
                "agent": {
                    "id": state.get("agentId"),
                    "workspace_slug": state.get("agentSlug"),
                },
                "environment": {"id": state.get("environmentId")},
            },
            state,
            components,
        )
    except ServiceNowConnectError:
        return False
    current_identity_sha256 = _canonical_json_hash(current_identity)
    return not (
        not isinstance(attestation, dict)
        or attestation.get("kind") != "binding-proof"
        or attestation.get("status") != "completed"
        or attestation.get("bindingVerified") is not True
        or attestation.get("physicalStatus") != "Connected"
        or str(attestation.get("connectionId") or "").replace("-", "")
        != normalized_connection_id
        or not isinstance(attestation_binding, dict)
        or attestation_binding.get("bindingIdentity") != current_identity
        or attestation_binding.get("bindingIdentitySha256")
        != current_identity_sha256
    )


def _require_current_agent_binding(
    context: dict[str, Any],
    state: dict[str, Any],
    components: dict[str, Any],
) -> None:
    if not _agent_binding_proof_current(state, components):
        raise ServiceNowConnectError(
            "Create and connect ServiceNow first: the agent's saved settings "
            "must use the verified connection before reviewing or changing "
            "topics or the portal URL.",
            details={
                "provider": PROVIDER_KEY,
                "profile": PROFILE_KEY,
                "agentId": context["agent"]["id"],
                "environmentId": context["environment"]["id"],
                "requiredPhase": "credential",
            },
        )


def _connection_binding_hash(
    context: dict[str, Any],
    state: dict[str, Any],
    components: dict[str, Any],
    *,
    require_agent_attestation: bool = True,
) -> str:
    credential = state.get("evidence", {}).get("credential")
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording Test "
            "evidence."
        )
    attestation = state.get("evidence", {}).get("agentConnection")
    attestation_current = _agent_binding_proof_current(
        state,
        components,
    )
    if require_agent_attestation and not attestation_current:
        raise ServiceNowConnectError(
            "Verify the ServiceNow connection and agent binding for this "
            "saved draft before recording Test evidence."
        )
    binding_identity = _agent_binding_identity(
        context,
        state,
        components,
    )
    return _connection_binding_hash_for_identity(
        binding_identity,
        recorded_at=(
            attestation.get("recordedAt")
            if isinstance(attestation, dict)
            else None
        ),
    )


def _topic_transaction_diagnostics(
    transaction: dict[str, Any],
) -> dict[str, Any]:
    rollback_statuses = transaction.get("topics")
    if not isinstance(rollback_statuses, dict):
        rollback_statuses = {}
    targets = transaction.get("targets")
    if not isinstance(targets, dict):
        targets = {}
    target_summaries = []
    for topic_id, target in sorted(targets.items())[:20]:
        if not isinstance(target, dict):
            continue
        component = target.get("component")
        display_name = (
            component.get("displayName")
            if isinstance(component, dict)
            else None
        )
        target_summaries.append(
            {
                "topicId": topic_id,
                "displayName": display_name,
                "beforeVersion": target.get("beforeVersion"),
                "postVersion": target.get("postVersion"),
                "ownershipStatus": target.get("ownershipStatus"),
                "changedByOperation": target.get("changedByOperation"),
                "rollbackStatus": rollback_statuses.get(topic_id),
            }
        )
    details = {
        "operationId": transaction.get("operationId"),
        "transactionStatus": transaction.get("status"),
        "mutationMayHaveOccurred": transaction.get(
            "mutationMayHaveOccurred"
        ),
        "updateError": transaction.get("updateError"),
        "reconciliationError": transaction.get("reconciliationError"),
        "rollbackError": transaction.get("rollbackError"),
        "before": transaction.get("before"),
        "after": transaction.get("after"),
        "targets": target_summaries,
    }
    remediation = transaction.get("remediation")
    if isinstance(remediation, str) and remediation:
        details["remediation"] = remediation
    if len(targets) > len(target_summaries):
        details["omittedTargetCount"] = len(targets) - len(target_summaries)
    return details


def _rollback_topic_transaction(
    context: dict[str, Any],
    agentbuilder: AgentBuilderClient,
    state: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    transactions = state.setdefault("transactions", {}).setdefault(
        "topics", {}
    )
    transaction = transactions.get(operation_id)
    if not isinstance(transaction, dict):
        raise ServiceNowConnectError(
            f"Unknown topic transaction: {operation_id}"
        )
    current = agentbuilder.fetch_components(context["agent"]["id"])
    current_topics = _servicenow_topic_components(current)
    changes = []
    statuses: dict[str, str] = {}
    for topic_id, target in transaction.get("targets", {}).items():
        if not isinstance(target, dict):
            continue
        current_topic = current_topics.get(topic_id.casefold())
        if current_topic is None:
            statuses[topic_id] = "missing"
            continue
        current_hash = _component_content_hash(current_topic)
        pre_hash = target.get("beforeContentHashExcludingVersion")
        if pre_hash and current_hash == pre_hash:
            statuses[topic_id] = "restored"
            continue
        if target.get("ownershipStatus") != "owned":
            statuses[topic_id] = "conflict"
            continue
        expected_post_hash = target.get(
            "expectedPostContentHashExcludingVersion"
        )
        if (
            not expected_post_hash
            or current_hash != expected_post_hash
        ):
            statuses[topic_id] = "conflict"
            continue
        preimage = target.get("component")
        if not isinstance(preimage, dict):
            statuses[topic_id] = "missing"
            continue
        restored = copy.deepcopy(preimage)
        restored["version"] = current_topic.get("version")
        changes.append(
            {
                "$kind": "BotComponentUpdate",
                "component": restored,
            }
        )
        statuses[topic_id] = "pending"
    if any(value in {"conflict", "missing"} for value in statuses.values()):
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "topics": statuses,
                "remediation": (
                    "Review conflicting or missing topics before restoring "
                    "their pre-mutation content."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    rollback_error: Exception | None = None
    if changes:
        token = current.get("changeToken")
        if not isinstance(token, str) or not token:
            raise ServiceNowConnectError(
                "Cannot roll back topics without a fresh change token."
            )
        try:
            agentbuilder.update_components(
                context["agent"]["id"],
                {
                    "changeToken": token,
                    "botComponentChanges": changes,
                },
            )
        except Exception as exc:
            rollback_error = exc
    verified = agentbuilder.fetch_components(context["agent"]["id"])
    verified_topics = _servicenow_topic_components(verified)
    for topic_id, target in transaction.get("targets", {}).items():
        restored = verified_topics.get(topic_id.casefold())
        preimage = target.get("component") if isinstance(target, dict) else None
        if (
            restored is None
            or not isinstance(preimage, dict)
        ):
            statuses[topic_id] = "pending"
        elif (
            _component_content_hash(restored)
            == _component_content_hash(preimage)
        ):
            statuses[topic_id] = "restored"
        elif (
            target.get("expectedPostContentHashExcludingVersion")
            and _component_content_hash(restored)
            == target["expectedPostContentHashExcludingVersion"]
        ):
            statuses[topic_id] = "pending"
        else:
            statuses[topic_id] = "conflict"
    transaction.update(
        {
            "status": (
                "rolled-back"
                if all(value == "restored" for value in statuses.values())
                else "rollback-incomplete"
            ),
            "rolledBackAt": _utc_now(),
            "topics": statuses,
        }
    )
    if transaction["status"] != "rolled-back":
        transaction["remediation"] = (
            "Refetch the pending topics and retry rollback only when their "
            "current content still matches the provider-owned postimage."
        )
        if rollback_error is not None:
            transaction["rollbackError"] = type(rollback_error).__name__
    _write_lifecycle_state(context, state)
    return transaction


def rollback_topic_transaction(
    context: dict[str, Any],
    operation_id: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Topic rollback requires explicit confirmation (--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    state = _load_lifecycle_state(context)
    return _rollback_topic_transaction(
        context,
        agentbuilder,
        state,
        operation_id,
    )


def _rollback_portal_transaction(
    context: dict[str, Any],
    agentbuilder: AgentBuilderClient,
    state: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    transactions = state.setdefault("transactions", {}).setdefault(
        "portal", {}
    )
    transaction = transactions.get(operation_id)
    if not isinstance(transaction, dict):
        raise ServiceNowConnectError(
            f"Unknown portal transaction: {operation_id}"
        )
    try:
        current = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "rollbackError": type(exc).__name__,
                "remediation": (
                    "The skill could not read the portal topic before "
                    "rollback. Stop and verify the current authored value "
                    "manually before retrying."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    current_topic = _portal_topic_component(current)
    expected_post_hash = transaction.get(
        "expectedPostContentHashExcludingVersion"
    )
    if (
        not expected_post_hash
        or _component_content_hash(current_topic) != expected_post_hash
    ):
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "remediation": (
                    "The portal configuration topic changed after the guarded "
                    "update. Preserve the current authored content and restore "
                    "the prior value manually after reviewing the conflict."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    preimage = transaction.get("component")
    if not isinstance(preimage, dict):
        raise ServiceNowConnectError(
            "Portal transaction has no rollback preimage."
        )
    token = current.get("changeToken")
    if not isinstance(token, str) or not token:
        raise ServiceNowConnectError(
            "Cannot roll back the portal URL without a fresh change token."
        )
    restored = copy.deepcopy(preimage)
    restored["version"] = current_topic.get("version")
    rollback_error: Exception | None = None
    try:
        agentbuilder.update_components(
            context["agent"]["id"],
            {
                "changeToken": token,
                "botComponentChanges": [
                    {
                        "$kind": "BotComponentUpdate",
                        "component": restored,
                    }
                ],
            },
        )
    except Exception as exc:
        rollback_error = exc
    try:
        verified = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "rollback-incomplete",
                "rolledBackAt": _utc_now(),
                "rollbackVerified": False,
                "rollbackError": type(exc).__name__,
                "remediation": (
                    "The rollback write could not be verified. Stop and "
                    "inspect the current portal value manually before "
                    "retrying."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        return transaction
    verified_topic = _portal_topic_component(verified)
    restored_ok = (
        _component_content_hash(verified_topic)
        == _component_content_hash(preimage)
    )
    transaction.update(
        {
            "status": "rolled-back" if restored_ok else "rollback-incomplete",
            "rolledBackAt": _utc_now(),
            "rollbackVerified": restored_ok,
        }
    )
    if not restored_ok:
        transaction["rollbackError"] = (
            type(rollback_error).__name__
            if rollback_error is not None
            else "ReadbackMismatch"
        )
        transaction["remediation"] = (
            "Rollback did not restore the original portal configuration. "
            "Stop and restore the prior value manually from the recorded "
            "preimage before retrying."
        )
    _write_lifecycle_state(context, state)
    return transaction


def portal_url_confirmation(
    context: dict[str, Any],
    portal_url: str,
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    instance_name = _admin_setup(state)["preflight"].get("instanceName")
    if not isinstance(instance_name, str) or not instance_name:
        raise ServiceNowConnectError(
            "The lifecycle has no confirmed ServiceNow instance."
        )
    typed_url = portal_url.strip()
    if "://" not in typed_url:
        typed_url = f"https://{typed_url}"
    normalized_url = normalize_portal_url(
        typed_url,
        expected_instance_name=instance_name,
    )
    return {
        "schemaVersion": "servicenow.portal-url-confirmation.v1",
        "portalUrl": normalized_url,
        "header": f"Is {normalized_url} the employee portal URL?",
        "question": (
            f"You entered **{normalized_url}** as the employee portal URL."
        ),
        "options": [
            {"label": "Yes"},
            {"label": "No"},
        ],
        "allowFreeformInput": False,
        "savedMessage": "We'll save that portal URL.",
    }


def set_portal_url(
    context: dict[str, Any],
    portal_url: str,
    *,
    confirmed: bool,
    rollback_after_verify: bool = False,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Portal URL update requires explicit confirmation (--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    state = _load_lifecycle_state(context, before)
    _require_current_agent_binding(context, state, before)
    setup = _admin_setup(state)
    expected_instance = setup["preflight"].get("instanceName")
    if not isinstance(expected_instance, str) or not expected_instance:
        raise ServiceNowConnectError(
            "The lifecycle has no confirmed ServiceNow instance."
        )
    payload, preimage, expected_postimage = build_portal_url_update_payload(
        before,
        portal_url,
        expected_instance_name=expected_instance,
    )
    normalized_url = _portal_literal_value(expected_postimage)
    if _portal_literal_value(preimage) == normalized_url:
        receipt = _record_portal_confirmation(
            state,
            topic=preimage,
            portal_url=normalized_url,
            instance_name=expected_instance,
            source="already-configured",
        )
        _write_lifecycle_state(context, state)
        return {
            "status": "already-configured",
            "portal": portal_configuration_summary(
                before,
                expected_instance_name=expected_instance,
            ),
            "readbackVerified": True,
            "confirmation": receipt,
        }
    operation_id = str(uuid.uuid4())
    transaction = {
        "operationId": operation_id,
        "status": "prepared",
        "preparedAt": _utc_now(),
        "topicId": preimage.get("id"),
        "topicSchemaName": preimage.get("schemaName"),
        "beforeContentHashExcludingVersion": _component_content_hash(preimage),
        "expectedPostContentHashExcludingVersion": _component_content_hash(
            expected_postimage
        ),
        "beforePortalUrl": _portal_literal_value(preimage),
        "requestedPortalUrl": normalized_url,
        "component": preimage,
    }
    state.setdefault("transactions", {}).setdefault("portal", {})[
        operation_id
    ] = transaction
    _write_lifecycle_state(context, state)
    update_error: Exception | None = None
    try:
        agentbuilder.update_components(context["agent"]["id"], payload)
    except Exception as exc:
        update_error = exc
    transaction.update(
        {
            "status": "reconciliation-required",
            "mutationMayHaveOccurred": True,
            "mutationAttemptedAt": _utc_now(),
            "updateError": (
                type(update_error).__name__
                if update_error is not None
                else None
            ),
        }
    )
    _write_lifecycle_state(context, state)
    try:
        after = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "reconciliation-required",
                "reconciliationError": type(exc).__name__,
                "remediation": (
                    "The portal URL update may have occurred, but readback "
                    "failed. Do not retry or roll back until a fresh component "
                    "read establishes the current authored content."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            transaction["remediation"],
            details={
                "operationId": operation_id,
                "transaction": copy.deepcopy(transaction),
            },
        ) from exc
    postimage = _portal_topic_component(after)
    post_hash = _component_content_hash(postimage)
    transaction.update(
        {
            "postContentHashExcludingVersion": post_hash,
            "readbackAt": _utc_now(),
        }
    )
    if post_hash == transaction["expectedPostContentHashExcludingVersion"]:
        transaction.update(
            {
                "status": "committed",
                "committedAt": _utc_now(),
                "readbackVerified": (
                    _portal_literal_value(postimage) == normalized_url
                ),
            }
        )
        _write_lifecycle_state(context, state)
        if rollback_after_verify:
            rolled_back = _rollback_portal_transaction(
                context,
                agentbuilder,
                state,
                operation_id,
            )
            if rolled_back.get("status") != "rolled-back":
                raise ServiceNowConnectError(
                    str(rolled_back.get("remediation")),
                    details={
                        "operationId": operation_id,
                        "transaction": copy.deepcopy(rolled_back),
                    },
                )
            return {
                "status": "verified-and-rolled-back",
                "operationId": operation_id,
                "topicId": preimage.get("id"),
                "portalUrl": normalized_url,
                "rollbackVerified": True,
            }
        receipt = _record_portal_confirmation(
            state,
            topic=postimage,
            portal_url=normalized_url,
            instance_name=expected_instance,
            source="committed",
        )
        _write_lifecycle_state(context, state)
        return {
            "status": "committed",
            "operationId": operation_id,
            "topicId": preimage.get("id"),
            "portalUrl": normalized_url,
            "readbackVerified": True,
            "confirmation": receipt,
        }
    if post_hash == transaction["beforeContentHashExcludingVersion"]:
        transaction.update(
            {
                "status": "failed-unchanged",
                "mutationMayHaveOccurred": False,
                "readbackVerified": True,
                "rollbackVerified": True,
                "remediation": (
                    "The component API did not apply the Portal BaseURI "
                    "change. Use the manual Copilot Studio topic step."
                ),
            }
        )
    else:
        transaction.update(
            {
                "status": "conflict",
                "remediation": (
                    "The portal configuration topic changed unexpectedly. "
                    "Do not overwrite it; review the current topic manually."
                ),
            }
        )
    _write_lifecycle_state(context, state)
    raise ServiceNowConnectError(
        transaction["remediation"],
        details={
            "operationId": operation_id,
            "transaction": copy.deepcopy(transaction),
        },
    )


def enable_all_servicenow_topics(
    context: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Enabling all ServiceNow topics requires explicit confirmation "
            "(--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
    state = _load_lifecycle_state(context, before)
    before_summary = summarize_components(before)
    inactive = [
        topic
        for topic in before_summary["serviceNowTopics"]
        if topic.get("state") != "Active"
        or topic.get("status") != "Active"
    ]
    if inactive:
        _require_current_agent_binding(context, state, before)
        payload = build_enable_all_topics_payload(before)
    operation_id = str(uuid.uuid4())
    transaction = {
        "operationId": operation_id,
        "status": "prepared",
        "preparedAt": _utc_now(),
        "changeTokenHash": _canonical_json_hash(before.get("changeToken")),
        "beforeComponentHash": _component_hash(before),
        "before": {
            "total": before_summary["serviceNowTopicCount"],
            "active": before_summary["activeServiceNowTopicCount"],
            "inactive": len(inactive),
        },
        "targets": {
            str(topic["id"]): {
                "beforeVersion": topic.get("version"),
                "beforeContentHashExcludingVersion": _component_content_hash(
                    find_servicenow_topic(before, str(topic["id"]))
                ),
                "component": copy.deepcopy(
                    find_servicenow_topic(before, str(topic["id"]))
                ),
                "expectedPostContentHashExcludingVersion": (
                    _component_content_hash(
                        {
                            **copy.deepcopy(
                                find_servicenow_topic(
                                    before,
                                    str(topic["id"]),
                                )
                            ),
                            "state": "Active",
                            "status": "Active",
                        }
                    )
                ),
            }
            for topic in inactive
        },
    }
    state.setdefault("transactions", {}).setdefault("topics", {})[
        operation_id
    ] = transaction
    _write_lifecycle_state(context, state)
    update_error: Exception | None = None
    if inactive:
        try:
            agentbuilder.update_components(context["agent"]["id"], payload)
        except Exception as exc:  # refetch decides whether rollback is needed
            update_error = exc
        transaction.update(
            {
                "status": "reconciliation-required",
                "mutationMayHaveOccurred": True,
                "mutationAttemptedAt": _utc_now(),
                "updateError": (
                    type(update_error).__name__
                    if update_error is not None
                    else None
                ),
            }
        )
        _write_lifecycle_state(context, state)
    try:
        after = agentbuilder.fetch_components(context["agent"]["id"])
    except Exception as exc:
        transaction.update(
            {
                "status": "reconciliation-required",
                "mutationMayHaveOccurred": bool(inactive),
                "reconciliationError": type(exc).__name__,
                "reconciliationFailedAt": _utc_now(),
                "remediation": (
                    "Refetch the agent components before any rollback. "
                    "Ownership of the remote postimage is not established."
                ),
            }
        )
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            "ServiceNow topic mutation may have occurred, but the required "
            "post-update refetch failed. Do not roll back until ownership "
            "can be established from a fresh component fetch.",
            details=_topic_transaction_diagnostics(transaction),
        ) from exc
    after_summary = summarize_components(after)
    transaction["after"] = {
        "total": after_summary["serviceNowTopicCount"],
        "active": after_summary["activeServiceNowTopicCount"],
        "inactive": (
            after_summary["serviceNowTopicCount"]
            - after_summary["activeServiceNowTopicCount"]
        ),
    }
    after_topics = _servicenow_topic_components(after)
    for topic_id, target in transaction["targets"].items():
        postimage = after_topics.get(topic_id.casefold())
        if postimage is None:
            target["ownershipStatus"] = "missing"
            target["changedByOperation"] = None
            target["targetStateVerified"] = False
            continue
        target["postVersion"] = postimage.get("version")
        target["postContentHashExcludingVersion"] = _component_content_hash(
            postimage
        )
        target["targetStateVerified"] = (
            postimage.get("state") == "Active"
            and postimage.get("status") == "Active"
        )
        if (
            target["postContentHashExcludingVersion"]
            == target["expectedPostContentHashExcludingVersion"]
        ):
            target["ownershipStatus"] = "owned"
            target["changedByOperation"] = True
            target["fullPostimageOwned"] = True
        elif (
            target["postContentHashExcludingVersion"]
            == target["beforeContentHashExcludingVersion"]
        ):
            target["ownershipStatus"] = "unchanged"
            target["changedByOperation"] = False
            target["fullPostimageOwned"] = False
        else:
            target["ownershipStatus"] = "conflict"
            target["changedByOperation"] = None
            target["fullPostimageOwned"] = False
    not_active = [
        topic
        for topic in after_summary["serviceNowTopics"]
        if topic.get("state") != "Active"
        or topic.get("status") != "Active"
    ]
    missing_targets = [
        topic_id
        for topic_id, target in transaction["targets"].items()
        if target.get("ownershipStatus") == "missing"
    ]
    target_state_verified = all(
        target.get("targetStateVerified") is True
        for target in transaction["targets"].values()
    )
    semantic_success = (
        update_error is None
        and not not_active
        and not missing_targets
        and target_state_verified
    )
    unattributed_postimage_topics = []
    if semantic_success:
        for topic_id, target in transaction["targets"].items():
            if target.get("ownershipStatus") != "conflict":
                continue
            target["ownershipStatus"] = "content-difference"
            target["changedByOperation"] = None
            component = target.get("component")
            unattributed_postimage_topics.append(
                {
                    "id": topic_id,
                    "displayName": (
                        component.get("displayName")
                        if isinstance(component, dict)
                        else None
                    ),
                }
            )
        transaction["semanticOutcome"] = "target-state-verified"
        transaction["unattributedPostimageTargetCount"] = len(
            unattributed_postimage_topics
        )
    target_issues = [
        topic_id
        for topic_id, target in transaction["targets"].items()
        if target.get("ownershipStatus") in {"missing", "conflict"}
    ]
    if not semantic_success and (
        update_error is not None or not_active or target_issues
    ):
        changed = any(
            target.get("ownershipStatus") in {"owned", "missing", "conflict"}
            for target in transaction["targets"].values()
        )
        if not changed:
            transaction.update(
                {
                    "status": "failed-no-mutation",
                    "afterComponentHash": _component_hash(after),
                    "failedAt": _utc_now(),
                }
            )
            _write_lifecycle_state(context, state)
            raise ServiceNowConnectError(
                "ServiceNow topic update failed before any topic mutation.",
                details=_topic_transaction_diagnostics(transaction),
            ) from update_error
        transaction["status"] = "rollback-required"
        transaction["afterComponentHash"] = _component_hash(after)
        _write_lifecycle_state(context, state)
        rollback = _rollback_topic_transaction(
            context,
            agentbuilder,
            state,
            operation_id,
        )
        if rollback.get("status") != "rolled-back":
            raise ServiceNowConnectError(
                "ServiceNow topic update failed and automatic rollback is "
                "incomplete; review the transaction remediation.",
                details=_topic_transaction_diagnostics(rollback),
            ) from update_error
        names = ", ".join(
            str(topic.get("displayName") or topic.get("id"))
            for topic in not_active
        )
        raise ServiceNowConnectError(
            (
                "ServiceNow topic update failed and was rolled back safely."
                if update_error is not None
                else "MinimalBot update left inactive topics and was rolled "
                f"back safely: {names}."
            ),
            details=_topic_transaction_diagnostics(rollback),
        ) from update_error
    result = {
        "status": "updated" if inactive else "already-active",
        "customerChoice": "enable-all",
        "before": {
            "total": before_summary["serviceNowTopicCount"],
            "active": before_summary["activeServiceNowTopicCount"],
            "inactive": len(inactive),
        },
        "changedTopics": [
            {
                "id": topic.get("id"),
                "displayName": topic.get("displayName"),
                "previousState": topic.get("state"),
                "previousStatus": topic.get("status"),
            }
            for topic in inactive
        ],
        "after": {
            "total": after_summary["serviceNowTopicCount"],
            "active": after_summary["activeServiceNowTopicCount"],
            "inactive": len(not_active),
        },
        "published": False,
        "operationId": operation_id,
        "transactionStatus": "committed",
        "unattributedPostimageTopics": unattributed_postimage_topics,
    }
    transaction.update(
        {
            "status": "committed",
            "committedAt": _utc_now(),
            "afterComponentHash": _component_hash(after),
        }
    )
    state.setdefault("evidence", {})["topics"] = result
    state["componentHash"] = _component_hash(after)
    _write_lifecycle_state(context, state)
    return result


def record_keep_current_topic_choice(
    context: dict[str, Any],
) -> dict[str, Any]:
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    summary = summarize_components(components)
    counts = {
        "total": summary["serviceNowTopicCount"],
        "active": summary["activeServiceNowTopicCount"],
        "inactive": (
            summary["serviceNowTopicCount"]
            - summary["activeServiceNowTopicCount"]
        ),
    }
    state = _load_lifecycle_state(context, components)
    result = {
        "kind": "maker-attestation",
        "status": "recorded",
        "customerChoice": "keep-current",
        "before": counts,
        "changedTopics": [],
        "after": counts,
        "published": False,
    }
    result["boundComponentHash"] = _component_hash(components)
    result["topicStates"] = summary["serviceNowTopics"]
    result["makerAttested"] = True
    result["recordedAt"] = _utc_now()
    state.setdefault("evidence", {})["topics"] = result
    state["componentHash"] = _component_hash(components)
    _write_lifecycle_state(context, state)
    return result


def topic_action_handoff(
    context: dict[str, Any],
    *,
    offline: bool = False,
) -> dict[str, Any]:
    components = (
        _load_json(context["snapshotPath"])
        if offline
        else _agentbuilder_client(context).fetch_components(
            context["agent"]["id"]
        )
    )
    summary = summarize_components(components)
    total = summary["serviceNowTopicCount"]
    active = summary["activeServiceNowTopicCount"]
    if total <= 0:
        raise ServiceNowConnectError(
            f"The exact selected agent has no {ACTIVE_PROFILE.product_name} topics."
        )
    component_hash = _component_hash(components)
    state = _load_lifecycle_state(context, components)
    topic_evidence = state.get("evidence", {}).get("topics")
    keep_current = (
        isinstance(topic_evidence, dict)
        and topic_evidence.get("status") == "recorded"
        and topic_evidence.get("customerChoice") == "keep-current"
        and topic_evidence.get("makerAttested") is True
        and topic_evidence.get("boundComponentHash") == component_hash
    )
    inventory = [
        {
            "id": topic.get("id"),
            "displayName": topic.get("displayName"),
            "schemaName": topic.get("schemaName"),
            "state": topic.get("state"),
            "status": topic.get("status"),
        }
        for topic in summary["serviceNowTopics"]
    ]
    inactive = [
        topic
        for topic in inventory
        if topic.get("state") != "Active" or topic.get("status") != "Active"
    ]
    base: dict[str, Any] = {
        "schemaVersion": "servicenow.topic-action-handoff.v1",
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "componentHash": component_hash,
        "inventory": {
            "total": total,
            "active": active,
            "inactive": len(inactive),
            "topics": inventory,
        },
    }
    if active == total:
        return {
            **base,
            "decision": "verified-noop",
            "actionResult": "applied",
            "reason": "all-topics-active",
        }
    if keep_current:
        return {
            **base,
            "decision": "verified-noop",
            "actionResult": "applied",
            "reason": "current-keep-current-attestation",
        }

    inactive_names = [
        str(topic.get("displayName") or topic.get("schemaName") or "")
        for topic in inactive
    ]
    reply_before_question = (
        f"Current topic inventory: {total} {ACTIVE_PROFILE.product_name} "
        f"topics; {active} active and {len(inactive)} inactive.\n\n"
        f"Inactive {ACTIVE_PROFILE.product_name} topics:\n"
        + "\n".join(f"- {name}" for name in inactive_names)
    )
    question = (
        "Only topics in the inventory listed above are in scope; unrelated "
        "topics remain unchanged."
    )
    return {
        **base,
        "decision": "question-required",
        "actionResult": None,
        "replyBeforeQuestion": reply_before_question,
        "question": _native_question(
            header="Should we enable the inactive ServiceNow topics?",
            question=question,
            option_labels=["Yes", "No"],
        ),
    }


def _phase_progress_completion_kind(
    state: dict[str, Any],
    phase_id: str,
    phase_state: dict[str, Any],
) -> str:
    setup = state.get("adminSetup")
    handoffs = setup.get("phaseHandoffs") if isinstance(setup, dict) else None
    handoff = handoffs.get(phase_id) if isinstance(handoffs, dict) else None
    if isinstance(handoff, dict) and handoff.get("status") == "reused":
        return "reused"
    results = phase_state.get("checkpointResults")
    if isinstance(results, dict) and any(
        value in {"Manual", "Warning"} for value in results.values()
    ):
        return "manual"
    return "checked"


_CONNECTION_STEP_LABEL = "Create and connect ServiceNow"


def _phase_customer_label(
    phase_id: str,
    contract_label: str,
) -> str:
    labels = {
        "preflight": "Review the current setup",
        "plugin-prerequisites": "Confirm HR ServiceNow prerequisites",
        "entra-registration": "Confirm Microsoft Entra identity details",
        "servicenow-oidc": (
            "Confirm ServiceNow single sign-on and user mapping"
        ),
        "credential": _CONNECTION_STEP_LABEL,
        "topics": "Turn on ServiceNow topics",
        "portal-url": "Set the employee portal URL",
        "test": "Test a ServiceNow request",
        "publish": "Publish agent",
    }
    return labels.get(phase_id, contract_label)


def _phase_responsible_roles(
    phase_id: str,
    phase: dict[str, Any],
) -> list[str]:
    configured = phase.get("responsibleRoles")
    if isinstance(configured, list) and all(
        isinstance(role, str) and role.strip()
        for role in configured
    ):
        return list(configured)
    defaults = {
        "plugin-prerequisites": ["ServiceNow Admin"],
        "entra-registration": [
            "Microsoft Entra Application Administrator or higher"
        ],
        "servicenow-oidc": ["ServiceNow Admin / security_admin"],
        "portal-url": [
            "ESS Maker / Agent Developer",
            "ServiceNow Admin (provides portal URL)",
        ],
    }
    return defaults.get(phase_id, ["ESS Maker / Agent Developer"])


def _phase_status_icon(status: str) -> str:
    icons = {
        "complete-checked": "✅",
        "complete-manual": "✅",
        "complete-reused": "✅",
        "rechecking": "🔄",
        "checking": "🔄",
        "current": "🔄",
        "pending": "⬜",
        "needs-attention": "❌",
    }
    try:
        return icons[status]
    except KeyError as exc:
        raise ServiceNowConnectError(
            "ServiceNow lifecycle progress status is invalid."
        ) from exc


_DEV_FINAL_SCOPE = {
    "hrsd": ("HR case lookup", "cases"),
    "itsm": ("IT ticket lookup", "tickets"),
}


def _dev_final_message(
    environment_display_name: str | None,
    existing_kind: str | None = None,
    other_agent: str | None = None,
) -> str:
    lookup, records = _DEV_FINAL_SCOPE[ACTIVE_PROFILE.key]
    in_env = f" in {environment_display_name}" if environment_display_name else ""
    return (
        f"**Your ServiceNow connection worked for the {lookup}{in_env}.** "
        f"{_spec_agent_name()} returned the {records} you expected in the "
        f"Test pane.\n\nCreating {records} and sign-in for other employees "
        "haven't been verified."
        + (
            f" {_EXISTING_IDENTITY_KINDS[existing_kind]['retest']}"
            if existing_kind
            else f" {other_agent} wasn't retested in this setup."
            if other_agent
            else ""
        )
    )


_STAGE_WAITING_TEXT = {
    "entra-registration": (
        "We're waiting for your Entra administrator's Application (client) ID "
        "and, if they did Part 4, the claim name.\n\n"
        "When you return, paste their reply without secrets. You won't need "
        "to repeat anything you've already sent."
    ),
    "servicenow-oidc": (
        "We're waiting for your ServiceNow administrator's "
        "saved-configuration confirmation, User Claim, and User Field.\n\n"
        "When you return, paste their non-sensitive reply or send those "
        "items individually. Don't include employee identifiers or secrets. "
        "You won't need to repeat the Entra values."
    ),
}


def _build_phase_progress(
    contract: dict[str, Any],
    state: dict[str, Any] | None,
    decision: dict[str, Any],
    *,
    executed_actions: frozenset[str],
    verified_phases: frozenset[str],
    environment_display_name: str | None = None,
    other_agent: str | None = None,
) -> dict[str, Any]:
    phases = contract.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ServiceNowConnectError(
            "ServiceNow lifecycle contract has no progress phases."
        )
    state_phases = state.get("phases") if isinstance(state, dict) else {}
    if not isinstance(state_phases, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle state has no progress phase map."
        )
    current = decision.get("phase")
    current_id = (
        str(current.get("id"))
        if isinstance(current, dict) and current.get("id")
        else None
    )
    items: list[dict[str, Any]] = []
    for phase in phases:
        if not isinstance(phase, dict):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle contract has an invalid progress phase."
            )
        phase_id = phase.get("id")
        label = phase.get("label")
        responsible_roles = _phase_responsible_roles(phase_id, phase)
        if not isinstance(phase_id, str) or not isinstance(label, str) or not label:
            raise ServiceNowConnectError(
                "ServiceNow lifecycle progress phase identity is invalid."
            )
        phase_state = state_phases.get(phase_id)
        if not isinstance(phase_state, dict):
            phase_state = {"status": "pending", "checkpointResults": {}}
        persisted_status = phase_state.get("status", "pending")
        if persisted_status not in {"pending", "in-progress", "done", "blocked"}:
            raise ServiceNowConnectError(
                "ServiceNow lifecycle progress phase status is invalid."
            )
        if phase_id in verified_phases and persisted_status == "done":
            completion_kind = _phase_progress_completion_kind(
                state or {},
                phase_id,
                phase_state,
            )
            status = f"complete-{completion_kind}"
            text = {
                "checked": "Complete — checked",
                "manual": "Complete — admin confirmed",
                "reused": "Reused — checked",
            }[completion_kind]
        elif persisted_status == "done":
            status = "rechecking"
            text = "Rechecking"
        elif persisted_status == "blocked":
            status = "needs-attention"
            text = "Needs attention"
        elif phase_id == current_id:
            action_finished = (
                phase_state.get("actionApplied") is True
                or phase_id in executed_actions
            )
            if decision.get("decision") == "run-checkpoints" and action_finished:
                status = "checking"
                text = "Checking"
            else:
                status = "current"
                text = "In progress"
        else:
            status = "pending"
            text = "Pending"
        items.append(
            {
                "id": phase_id,
                "label": label,
                "customerLabel": _phase_customer_label(phase_id, label),
                "responsibleRoles": list(responsible_roles),
                "persistedStatus": persisted_status,
                "roleAvailabilityRequired": persisted_status
                not in {"done", "skipped"},
                "status": status,
                "text": text,
            }
        )

    completed_count = sum(
        item["status"].startswith("complete-") for item in items
    )
    current_item = next(
        (item for item in items if item["id"] == current_id),
        None,
    )
    has_prior_progress = any(
        item["status"] not in {"pending", "current"} for item in items
    )
    headline = _setup_title()

    def render_grouped(
        *,
        current_status: tuple[str, str] | None = None,
    ) -> str:
        override = (
            (current_id, current_status[0], current_status[1])
            if current_status is not None and current_id is not None
            else None
        )
        return _render_grouped_phases(
            contract,
            items,
            title=headline,
            current_override=override,
        )

    grouped = render_grouped()
    final_message = (
        _dev_final_message(
            environment_display_name,
            _existing_identity_kind(state),
            other_agent,
        )
        if decision.get("decision") == "complete"
        and completed_count == len(items)
        else None
    )
    internal: dict[str, Any] = {
        "renderable": False,
        "groupedText": grouped,
        "groupedFinalText": (
            f"{grouped}\n\n{final_message}"
            if final_message is not None
            else None
        ),
        "currentPhase": None,
    }
    progress: dict[str, Any] = {
        "schemaVersion": "servicenow.phase-progress.v1",
        "mode": "resume" if has_prior_progress else "fresh",
        "headline": headline,
        "completedCount": completed_count,
        "totalCount": len(items),
        "items": items,
        "currentPhase": None,
        "internal": internal,
    }
    if current_item is not None:
        label = current_item["customerLabel"]
        start_verb = {
            "rechecking": "Rechecking",
            "checking": "Checking",
            "needs-attention": "Needs attention",
        }.get(current_item["status"], "Starting")
        progress["currentPhase"] = dict(current_item)
        internal["currentPhase"] = {
            "startText": f"{start_verb}: {label}",
            "groupedWaitingText": render_grouped(
                current_status=("⏳", "Waiting")
            ),
            "groupedErrorText": render_grouped(
                current_status=("❌", "Needs attention")
            ),
            "waitingText": (
                _existing_waiting_text()
                if _existing_identity_kind(state)
                and str(current_item["id"])
                in {"entra-registration", "servicenow-oidc"}
                else None
            )
            or _STAGE_WAITING_TEXT.get(
                str(current_item["id"]),
                f"Waiting — {label}: please provide the requested information to continue.",
            ),
            "needsAttentionText": f"{label} needs your review before setup can continue.",
        }
    return progress


def _business_groups(
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    phases = contract.get("phases")
    groups = contract.get("businessGroups")
    if not isinstance(phases, list):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle contract has no business groups."
        )
    if not isinstance(groups, list):
        phase_ids = {
            str(phase.get("id"))
            for phase in phases
            if isinstance(phase, dict) and isinstance(phase.get("id"), str)
        }
        groups = [
            *(
                [
                    {
                        "id": "hr-prerequisite",
                        "label": "HR prerequisite",
                        "role": "ServiceNow admin",
                        "phaseIds": ["plugin-prerequisites"],
                    }
                ]
                if "plugin-prerequisites" in phase_ids
                else []
            ),
            *(
                [
                    {
                        "id": "entra-identity",
                        "label": "Entra identity",
                        "role": "Entra admin",
                        "phaseIds": ["entra-registration"],
                    }
                ]
                if "entra-registration" in phase_ids
                else []
            ),
            *(
                [
                    {
                        "id": "servicenow-sso",
                        "label": "ServiceNow SSO and user mapping",
                        "role": "ServiceNow admin / security_admin",
                        "phaseIds": ["servicenow-oidc"],
                    }
                ]
                if "servicenow-oidc" in phase_ids
                else []
            ),
            {
                "id": "maker-configuration",
                "label": "Maker configuration and validation",
                "role": "Maker",
                "phaseIds": [
                    phase_id
                    for phase_id in (
                        "credential",
                        "topics",
                        "portal-url",
                        "test",
                    )
                    if phase_id in phase_ids
                ],
            },
        ]
        groups = [
            group for group in groups if group["phaseIds"]
        ]
    phase_ids = {
        str(phase.get("id"))
        for phase in phases
        if isinstance(phase, dict) and isinstance(phase.get("id"), str)
    }
    seen_groups: set[str] = set()
    seen_phases: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ServiceNowConnectError(
                "ServiceNow business-group contract is invalid."
            )
        group_id = group.get("id")
        label = group.get("label")
        role = group.get("role")
        group_phase_ids = group.get("phaseIds")
        if (
            not isinstance(group_id, str)
            or not group_id
            or group_id in seen_groups
            or not isinstance(label, str)
            or not label
            or not isinstance(role, str)
            or not role
            or not isinstance(group_phase_ids, list)
            or not group_phase_ids
            or not all(
                isinstance(phase_id, str)
                and phase_id in phase_ids
                and phase_id != "preflight"
                and phase_id not in seen_phases
                for phase_id in group_phase_ids
            )
        ):
            raise ServiceNowConnectError(
                "ServiceNow business-group identity or phase mapping is "
                "invalid."
            )
        seen_groups.add(group_id)
        seen_phases.update(group_phase_ids)
        normalized.append(
            {
                "id": group_id,
                "label": label,
                "role": role,
                "phaseIds": list(group_phase_ids),
            }
        )
    expected_grouped = phase_ids - {"preflight"}
    if seen_phases != expected_grouped:
        raise ServiceNowConnectError(
            "ServiceNow business groups do not cover every collaboration "
            "phase exactly once."
        )
    return normalized


def _business_group_context(
    context: dict[str, Any],
    contract: dict[str, Any],
    group: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": "servicenow.business-group-context.v1",
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "contractRevision": contract["contractRevision"],
        "businessGroupId": group["id"],
        "label": group["label"],
        "role": group["role"],
        "phaseIds": list(group["phaseIds"]),
    }


def _business_group_acknowledgement_current(
    state: dict[str, Any] | None,
    *,
    group: dict[str, Any],
    context_sha256: str,
) -> bool:
    if not isinstance(state, dict):
        return False
    records = state.get("businessGroupAcknowledgements")
    record = (
        records.get(group["id"])
        if isinstance(records, dict)
        else None
    )
    recorded_context = (
        record.get("contextIdentity")
        if isinstance(record, dict)
        else None
    )
    return bool(
        isinstance(record, dict)
        and record.get("kind") == "maker-attestation"
        and record.get("status") == "available"
        and record.get("businessGroupId") == group["id"]
        and record.get("contextIdentitySha256") == context_sha256
        and isinstance(recorded_context, dict)
        and _canonical_json_hash(recorded_context) == context_sha256
        and isinstance(record.get("recordedAt"), str)
        and record["recordedAt"]
    )


def _current_business_group(
    contract: dict[str, Any],
    progress: dict[str, Any],
) -> dict[str, Any] | None:
    groups = _business_groups(contract)
    current = progress.get("currentPhase")
    current_phase_id = (
        current.get("id") if isinstance(current, dict) else None
    )
    if not isinstance(current_phase_id, str) or current_phase_id == "preflight":
        return None
    for group in groups:
        if current_phase_id in group["phaseIds"]:
            return group
    return None


def _business_group_availability_question(
    group: dict[str, Any],
) -> dict[str, Any]:
    copy_by_group = {
        "hr-prerequisite": {
            "question": "Is your ServiceNow administrator available to complete this step?",
        },
        "entra-identity": {
            "question": "Is your Microsoft Entra administrator available to complete this step?",
        },
        "servicenow-sso": {
            "question": (
                "Is your ServiceNow administrator available to complete "
                "this step?"
            ),
        },
        "maker-configuration": {
            "question": (
                "Are you available, with the ESS Maker / Agent Developer "
                "role, to complete this step?"
            ),
        },
    }
    configured = copy_by_group.get(str(group.get("id") or ""))
    if configured is None:
        raise ServiceNowConnectError(
            "ServiceNow business-group availability copy is missing."
        )
    return _native_question(
        header=configured["question"],
        question=str(group.get("label") or configured["question"]),
        option_labels=["Yes", "No"],
    )


def _credential_lead_in(state: dict[str, Any]) -> str:
    mapping = state.get("evidence", {}).get("identityMapping")
    claim = field = None
    if (
        isinstance(mapping, dict)
        and mapping.get("serviceNowAdministratorConfirmed") is True
    ):
        claim = mapping.get("tokenClaimName")
        field = mapping.get("serviceNowUserField")
    if isinstance(claim, str) and claim and isinstance(field, str) and field:
        return (
            "Your ServiceNow administrator has confirmed that the "
            f"configuration is saved, using `{claim}` as the User Claim and "
            f"**{field}** as the User Field.\n\n"
        )
    return ""


def _product_audience() -> str:
    return "HR" if ACTIVE_PROFILE.key == "hrsd" else "IT"


def _first_text(container: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(container, dict):
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _display_environment_name(context: dict[str, Any]) -> str:
    return _first_text(
        context.get("environment"),
        ("display_name", "displayName", "name"),
    ) or str(context["environment"]["id"])


def _recorded_environment_name(context: dict[str, Any]) -> str | None:
    return _first_text(
        context.get("environment"),
        ("display_name", "displayName", "name"),
    )


ACTIVE_AGENT_NAME: str | None = None


def _remember_agent_name(context: dict[str, Any] | None) -> None:
    """Record the selected agent's own name as the one maker-facing name."""
    global ACTIVE_AGENT_NAME
    name = _first_text(
        context.get("agent") if isinstance(context, dict) else None,
        ("display_name", "displayName", "name"),
    )
    if name:
        ACTIVE_AGENT_NAME = name


def _spec_agent_name() -> str:
    if ACTIVE_AGENT_NAME:
        return ACTIVE_AGENT_NAME
    return ACTIVE_PROFILE.agent_display_name.replace("(", "").replace(")", "")


def _display_agent_name(context: dict[str, Any]) -> str:
    _remember_agent_name(context)
    return _spec_agent_name()


_DEV_OPENING_PURPOSE = {
    "hrsd": "create and track their own HR cases",
    "itsm": "create and track their own ServiceNow IT tickets",
}


def _other_agent_already_connected(
    context: dict[str, Any],
    state: dict[str, Any] | None,
) -> bool:
    """True when another ESS agent in this environment has recorded shared setup.

    Uses the same local lifecycle records as the shared-configuration reuse
    offer: same tenant, environment and ring, a different agent, a completed
    shared-identity phase, and the same ServiceNow instance when this run has
    already recorded one.
    """
    return bool(_other_agent_reuse_sources(context, state))


def _other_agent_reuse_sources(
    context: dict[str, Any],
    state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Local records of other agents with shared setup this run can reuse."""
    sources: list[dict[str, Any]] = []
    target_setup = state.get("adminSetup") if isinstance(state, dict) else None
    target_preflight = (
        target_setup.get("preflight") if isinstance(target_setup, dict) else None
    )
    target_instance = (
        target_preflight.get("instanceName")
        if isinstance(target_preflight, dict)
        else None
    )
    try:
        target_instance = (
            normalize_instance_name(target_instance)
            if isinstance(target_instance, str) and target_instance.strip()
            else None
        )
    except ServiceNowConnectError:
        target_instance = None
    for source in _local_compatible_agent_states(context):
        setup = source["state"].get("adminSetup")
        if not isinstance(setup, dict) or setup.get("authMode") != AUTH_MODE:
            continue
        if not any(
            _completed_handoff(setup, phase) is not None
            for phase in ("entra-registration", "servicenow-oidc")
        ):
            continue
        preflight = setup.get("preflight")
        source_instance = (
            preflight.get("instanceName") if isinstance(preflight, dict) else None
        )
        if target_instance and source_instance:
            try:
                if normalize_instance_name(str(source_instance)) != target_instance:
                    continue
            except ServiceNowConnectError:
                continue
        sources.append(source)
    return sources


def _dev_opening_text(
    context: dict[str, Any],
    state: dict[str, Any] | None,
) -> str:
    """Step 1 opening for a fresh Dev run; omits values that are not recorded."""
    environment = _recorded_environment_name(context)
    in_bold = f" in **{environment}**" if environment else ""
    in_plain = f" in {environment}" if environment else ""
    reuse = _other_agent_already_connected(context, state)
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    if reuse:
        lines = [
            f"We'll add **{_spec_agent_name()}**{in_bold} so employees can "
            f"{_DEV_OPENING_PURPOSE[ACTIVE_PROFILE.key]}.",
            "",
            f"Your administrators will confirm whether {copy_['audience']} "
            "can use the existing sign-in setup. Then we'll select a "
            f"connection, configure {copy_['audience']}'s portal and topics, "
            f"and test {copy_['article']} {copy_['audience']} request with "
            "your account.",
        ]
    else:
        lines = [
            f"We'll connect **{_spec_agent_name()}** to ServiceNow{in_bold} so "
            f"employees can {_DEV_OPENING_PURPOSE[ACTIVE_PROFILE.key]}.",
            "",
            "You'll need help from your ServiceNow and Microsoft Entra "
            "administrators. We'll confirm their setup, create the connection "
            "in Copilot Studio, then test it with your account.",
        ]
    setup = state.get("adminSetup") if isinstance(state, dict) else None
    preflight = setup.get("preflight") if isinstance(setup, dict) else None
    instance = (
        preflight.get("instanceName") if isinstance(preflight, dict) else None
    )
    if isinstance(instance, str) and instance.strip():
        try:
            instance_name = normalize_instance_name(instance)
        except ServiceNowConnectError:
            instance_name = None
        if instance_name:
            lines.extend(
                [
                    "",
                    "**ServiceNow instance:** "
                    f"https://{instance_name}.service-now.com",
                ]
            )
    lines.extend(
        [
            "",
            "We're checking whether your account can configure "
            f"{_spec_agent_name() if reuse else 'this agent'}"
            f"{in_plain} before setup begins.",
        ]
    )
    return "\n".join(lines)


def _take_dev_opening(
    context: dict[str, Any],
    state: dict[str, Any] | None,
    progress: dict[str, Any],
) -> str | None:
    """Return the opening once per lifecycle, only at the start of a fresh run."""
    if progress.get("mode") != "fresh" or not isinstance(state, dict):
        return None
    if state.get("openingShown"):
        return None
    kind = _existing_identity_kind(state)
    text = (
        _existing_identity_opening(context, state, kind)
        if kind
        else _dev_opening_text(context, state)
    )
    state["openingShown"] = {"shownAt": _utc_now()}
    _write_lifecycle_state(context, state)
    return text


def _checklist_shown_path(context: dict[str, Any]) -> Path:
    return _lifecycle_state_path(context).with_name("checklist-shown.json")


def _checklist_due(
    context: dict[str, Any],
    checklist_text: str,
    *,
    force: bool = False,
) -> bool:
    """True when the setup checklist should be shown to the maker.

    The checklist is shown at the start, whenever its checked state changed
    since it was last shown, and always at the end. The last shown state is
    kept beside, not inside, the lifecycle state so read-only resumes never
    change the lifecycle file.
    """
    path = _checklist_shown_path(context)
    digest = hashlib.sha256(checklist_text.encode("utf-8")).hexdigest()
    shown = _load_json(path) if path.exists() else None
    if (
        not force
        and isinstance(shown, dict)
        and shown.get("sha256") == digest
    ):
        return False
    _write_json_atomic(path, {"sha256": digest, "shownAt": _utc_now()})
    return True


_DEV_TEST_COPY = {
    "hrsd": {
        "article": "an",
        "audience": "HR",
        "records": "cases",
        "record": "case",
        "example": "Show my open HR cases",
    },
    "itsm": {
        "article": "an",
        "audience": "IT",
        "records": "tickets",
        "record": "ticket",
        "example": "Show my open IT tickets",
    },
}


def _dev_test_ready_message(existing_kind: str | None = None) -> str:
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    return (
        f"We're ready to try {copy_['article']} {copy_['audience']} request.\n\n"
        f"In **{_spec_agent_name()}'s Test pane**, run a request that should "
        "return your real ServiceNow data—for example "
        f"**\"{copy_['example']},\"** if you have open {copy_['records']}.\n\n"
        "Come back and tell us what happened and whether it matched what you "
        f"expected. You don't need to paste {copy_['record']} contents.\n\n"
        "You can also finish without testing; the "
        f"{'ESS ' if existing_kind else ''}integration will "
        "remain untested."
    )


def _dev_test_clarifying_question() -> str:
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    return (
        f"What did the request return—your expected {copy_['records']}, an "
        "empty result, or an error? No need to share "
        f"{copy_['record']} contents."
    )


def _dev_empty_result_message() -> str:
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    return (
        "An empty result alone doesn't show whether the agent can retrieve "
        f"your {copy_['audience']} data.\n\n"
        "Try a supported request for ServiceNow data you know exists for "
        "your account, then tell us whether the result matches. You can "
        "also finish without testing."
    )


def _dev_untested_message(existing_kind: str | None = None) -> str:
    audience = "ESS" if existing_kind else _product_audience()
    return (
        f"**The {audience} setup steps are finished, but this integration "
        f"hasn't been tested.** Test {_spec_agent_name()} before employees "
        "use it.\n\n"
        f"Your progress is saved at the {_product_audience()} Test-pane request. When "
        "you return, we'll continue there."
    )


def _dev_test_guidance(
    context: dict[str, Any],
    state: dict[str, Any],
) -> str:
    evidence = state.get("evidence")
    record = evidence.get("test") if isinstance(evidence, dict) else None
    if not (isinstance(record, dict) and record.get("status") == "untested"):
        return _dev_test_ready_message(_existing_identity_kind(state))
    environment = _recorded_environment_name(context)
    in_env = f" in {environment}" if environment else ""
    audience = _product_audience()
    return (
        f"Next, test a request in **{_spec_agent_name()}'s Test pane"
        f"{in_env}**.\n\n"
        f"Run {_DEV_TEST_COPY[ACTIVE_PROFILE.key]['article']} {audience} "
        "request that should return your real ServiceNow data, then tell us "
        "whether it returned what you expected."
    )


_PORTAL_URL_RECORD_COPY = {
    "hrsd": {"audience": "HR", "singular": "case", "plural": "cases"},
    "itsm": {"audience": "IT", "singular": "ticket", "plural": "tickets"},
}
_PORTAL_URL_STANDARD_CLAIMS = frozenset({"email", "upn"})


def _custom_claim_identity(state: dict[str, Any] | None) -> bool:
    """True when the confirmed identity uses a custom token claim (spec S4)."""
    evidence = state.get("evidence") if isinstance(state, dict) else None
    mapping = (
        evidence.get("identityMapping") if isinstance(evidence, dict) else None
    )
    claim = mapping.get("tokenClaimName") if isinstance(mapping, dict) else None
    return (
        isinstance(claim, str)
        and bool(claim.strip())
        and claim.strip().casefold() not in _PORTAL_URL_STANDARD_CLAIMS
    )


def _portal_url_ask_guidance(
    context: dict[str, Any],
    state: dict[str, Any],
) -> str:
    """Plain-text lead-in and URL question for the portal URL step.

    Wording follows the spec variant for the setup mode: existing sign-in
    (S3), a second agent (S2), a custom identity claim (S4), or the first
    agent (S1).
    """
    copy_ = _PORTAL_URL_RECORD_COPY[ACTIVE_PROFILE.key]
    audience = copy_["audience"]
    singular = copy_["singular"]
    plural = copy_["plural"]
    if _existing_identity_kind(state):
        return (
            f"Next, we'll make sure the agent's {singular} links open in the "
            "employee portal.\n\n"
            "What is the full HTTPS base URL employees should use for "
            f"{audience} {plural}? It may differ from the ServiceNow "
            "instance URL."
        )
    if _other_agent_already_connected(context, state):
        other = "IT" if audience == "HR" else "HR"
        return (
            f"Next, we'll make sure the {audience} agent's {singular} links "
            "open in the right employee portal.\n\n"
            "What is the full HTTPS base URL of the portal employees should "
            f"use for {audience} {plural}? It may differ from the {other} "
            "portal."
        )
    if _custom_claim_identity(state):
        return (
            f"Next, we'll make sure {audience} {singular} links open in the "
            "employee portal.\n\n"
            "What is the full HTTPS base URL employees should use for "
            f"{audience} {plural}?"
        )
    return (
        f"Next, we'll make sure the agent's {audience} {singular} links open "
        "in the right employee portal.\n\n"
        "What is the full HTTPS base URL of your ServiceNow employee portal? "
        "It may differ from the instance URL, so we won't assume `/sp` or "
        "`/esc`."
    )


def _current_task_guidance(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    phase_id: str,
    role: str,
) -> str:
    setup = state.get("adminSetup")
    setup = setup if isinstance(setup, dict) else {}
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    instance_name = str(preflight.get("instanceName") or "not confirmed")
    client_id = _known_entra_client_id(state)
    links = maker_portal_links(
        context,
        instance_name=(
            instance_name
            if instance_name != "not confirmed"
            else None
        ),
    )
    if phase_id == "plugin-prerequisites":
        instance_url = links.get("serviceNowInstance", {}).get("url")
        if not instance_url or not links.get("hrCorePlugin", {}).get("url"):
            raise ServiceNowConnectError(
                "The plugin prerequisite message requires the confirmed "
                "ServiceNow instance URL."
            )
        instance_url = instance_url.rstrip("/")
        if _existing_identity_kind(state):
            return _existing_plugin_prerequisite_guidance(instance_url)
        return (
            "First, your ServiceNow administrator needs to confirm that this "
            "instance supports the HR scenarios.\n\n"
            "Send them this message. When they reply, paste their "
            "confirmation here.\n\n"
        ) + _ready_to_send_block(
            f"We're connecting **{_spec_agent_name()}** to ServiceNow HR "
            f"Service Delivery on [**{instance_url}**]({instance_url}).\n\n"
            "Please confirm that the **HR Service Delivery Core** plugin "
            "(`com.sn_hr_core`) is installed and active:\n\n"
            "1. In ServiceNow, go to **All > System Definition > Plugins**.\n"
            "2. Search for **Human Resources Scoped App: Core**.\n"
            "3. Confirm whether it is installed and active.\n\n"
            "**Please send back:** confirmation that the plugin is "
            "installed and active on this instance. If it isn't, tell us "
            "what remains to be completed."
        )
    if phase_id in {"entra-registration", "servicenow-oidc"}:
        # The administrator handoff and its lead-in are rendered by the
        # identity direct handoff, not by this card.
        return ""
    if phase_id == "credential":
        audience = _product_audience()
        existing_kind = _existing_identity_kind(state)
        if existing_kind:
            return _existing_connection_guidance(
                context,
                state,
                existing_kind,
                client_id=client_id,
                instance_name=instance_name,
            )
        second_agent = _second_agent_reuse(context, state)
        if second_agent:
            return _second_agent_connection_guidance(
                context, state, second_agent
            )
        return _credential_lead_in(state) + (
            "Next, create the sign-in connection that "
            f"{_spec_agent_name()} will use to access ServiceNow. This part "
            "happens in "
            "Copilot Studio:\n\n"
            f"1. Open **{_display_agent_name(context)}** in "
            f"**{_display_environment_name(context)}**.\n"
            "2. Go to **Settings > Connection Settings > ServiceNow > "
            "Connect > Create new connection**.\n"
            "3. Use:\n"
            "   - **Authentication type:** Microsoft Entra ID User Login\n"
            f"   - **Resource URI:** `{client_id or 'not yet confirmed'}`\n"
            f"   - **Instance name:** `{instance_name}`—not the full URL\n"
            "4. Complete the connection creation.\n\n"
            "Return here and tell us which connection you used. You won't "
            "need to resend the administrator replies.\n\n"
            f"After that, we'll test an {audience} request with your account "
            "to check sign-in and employee matching."
        )
    if phase_id == "topics":
        return (
            f"We'll turn on the built-in ServiceNow {_product_audience()} "
            "topics, including system topics. Unrelated topics will stay "
            "unchanged."
        )
    if phase_id == "portal-url":
        return _portal_url_ask_guidance(context, state)
    if phase_id == "test":
        return _dev_test_guidance(context, state)
    raise ServiceNowConnectError(
        "ServiceNow current-task guidance is missing."
    )


def _setup_title() -> str:
    return (
        "Set up ServiceNow IT"
        if ACTIVE_PROFILE.key == "itsm"
        else "Set up ServiceNow HR"
    )


def _render_grouped_phases(
    contract: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    title: str,
    current_override: tuple[str, str, str] | None = None,
) -> str:
    """Render the flat setup checklist used by every Connect transition.

    One checkbox line per phase, in group order. Done phases are checked and
    the rest are unchecked; only a phase that needs attention gets a note.
    ``current_override`` is ``(phase_id, icon, text)`` for the current step.
    """
    items_by_id = {str(item["id"]): item for item in items}

    def task_line(item: dict[str, Any]) -> str:
        status = str(item["status"])
        needs_attention = status == "needs-attention"
        if current_override is not None and item["id"] == current_override[0]:
            status = "current"
            needs_attention = current_override[1] == "❌"
        label = item["customerLabel"]
        if needs_attention:
            return f"- ❌ {label} — needs attention"
        icon = "✅" if status.startswith("complete-") else "⬜"
        return f"- {icon} {label}"

    lines = [
        f"**{title}**",
        "",
        "Complete these tasks to finish setup.",
        "",
    ]
    for group in _business_groups(contract):
        for phase_id in group["phaseIds"]:
            item = items_by_id.get(phase_id)
            if item is not None:
                lines.append(task_line(item))
    return "\n".join(lines)


def _business_group_transport(
    *,
    context: dict[str, Any],
    contract: dict[str, Any],
    state: dict[str, Any] | None,
    title: str,
    phase_items: list[dict[str, Any]],
    current_group: dict[str, Any] | None,
    roles_available: bool | None,
    availability_group_id: str | None,
    availability_context_sha256: str | None,
    show_checklist: bool = True,
) -> dict[str, Any]:
    groups = _business_groups(contract)
    ordinary_text = (
        _render_grouped_phases(contract, phase_items, title=title)
        if show_checklist
        else ""
    )
    group_context = (
        _business_group_context(context, contract, current_group)
        if current_group is not None
        else None
    )
    context_sha256 = (
        _canonical_json_hash(group_context)
        if group_context is not None
        else None
    )
    acknowledged = bool(
        current_group is not None
        and context_sha256 is not None
        and _business_group_acknowledgement_current(
            state,
            group=current_group,
            context_sha256=context_sha256,
        )
    )
    gate_required = current_group is not None and not acknowledged
    current_phase = next(
        (
            item
            for item in phase_items
            if item.get("status")
            in {
                "current",
                "checking",
                "rechecking",
                "needs-attention",
            }
        ),
        None,
    )
    if (
        acknowledged
        and current_group is not None
        and isinstance(current_phase, dict)
        and isinstance(current_phase.get("id"), str)
    ):
        guidance = _current_task_guidance(
            context,
            state or {},
            phase_id=current_phase["id"],
            role=current_group["role"],
        )
        if guidance:
            ordinary_text = (
                f"{ordinary_text}\n\n{guidance}" if ordinary_text else guidance
            )
    question = (
        _business_group_availability_question(current_group)
        if gate_required
        else None
    )
    if roles_available is not None:
        if question is None:
            raise ServiceNowConnectError(
                "No current business-group availability question accepts an "
                "answer."
            )
        if (
            availability_group_id != current_group["id"]
            or availability_context_sha256 != context_sha256
        ):
            raise ServiceNowConnectError(
                "The business-group availability answer is stale or belongs "
                "to another group, target, or contract revision."
            )
    return {
        "schemaVersion": "servicenow.lifecycle-transport.v2",
        "internal": {
            "renderable": False,
            "ordinaryReply": {
                "kind": "ordinary-agent-response",
                "text": ordinary_text,
                "businessGroupCount": len(groups),
            },
        },
        "businessGroupAvailability": {
            "gateRequired": gate_required,
            "currentGroup": copy.deepcopy(current_group),
            "contextIdentity": group_context,
            "contextIdentitySha256": context_sha256,
            "question": copy.deepcopy(question),
            "questionSha256": (
                _canonical_json_hash(question)
                if question is not None
                else None
            ),
            "available": roles_available,
            "stateChanged": False,
            "unavailableReply": (
                f"Please involve your {current_group['role']} for "
                f"{current_group['label']}, then answer the same question "
                "again.\n\nNo business group, lifecycle phase, evidence, "
                "attestation, or accepted contract revision has advanced."
                if current_group is not None
                else None
            ),
        },
    }


def _resume_progress(
    context: dict[str, Any],
    decision: dict[str, Any],
    *,
    executed_actions: frozenset[str],
    verified_phases: frozenset[str],
) -> dict[str, Any]:
    root = Path(context["root"])
    provider = ACTIVE_PROFILE.provider_key
    contract = _load_json(
        root / "src" / "skills" / "connect" / provider / "contract.json"
    )
    state_path = (
        root
        / ".local"
        / "connect"
        / provider
        / "agents"
        / _agent_slug(context)
        / "lifecycle.json"
    )
    state = _load_json(state_path) if state_path.exists() else None
    return _build_phase_progress(
        contract,
        state,
        decision,
        executed_actions=executed_actions,
        verified_phases=verified_phases,
        environment_display_name=_recorded_environment_name(context),
        other_agent=_second_agent_audience(context, state),
    )


def _pending_preflight_input(
    state: dict[str, Any] | None,
    decision: dict[str, Any],
) -> dict[str, Any] | None:
    if decision.get("decision") != "run-checkpoints":
        return None
    phase = decision.get("phase")
    if not isinstance(phase, dict) or phase.get("id") != "preflight":
        return None
    setup = state.get("adminSetup") if isinstance(state, dict) else None
    setup = setup if isinstance(setup, dict) else {}
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    instance_name = preflight.get("instanceName")
    if isinstance(instance_name, str) and instance_name.strip():
        return None
    discovery = preflight.get("discovery")
    discovery = discovery if isinstance(discovery, dict) else {}
    if discovery.get("instanceInputRequired") is not True:
        return None
    question = discovery.get("instanceQuestion")
    if (
        not isinstance(question, dict)
        or not isinstance(question.get("header"), str)
        or not question["header"].strip()
        or not isinstance(question.get("question"), str)
        or not question["question"].strip()
        or not isinstance(question.get("allowFreeformInput"), bool)
    ):
        raise ServiceNowConnectError(
            "ServiceNow preflight requires Maker input, but its persisted "
            "instance question is invalid."
        )
    manual_question = discovery.get("manualInstanceQuestion")
    if not isinstance(manual_question, dict):
        manual_question = None
    choices = discovery.get("instanceChoices")
    choices = choices if isinstance(choices, dict) else {}
    return {
        "schemaVersion": "servicenow.pending-input.v1",
        "kind": "instance-confirmation",
        "phase": "preflight",
        "question": copy.deepcopy(question),
        "manualQuestion": copy.deepcopy(manual_question),
        "choiceValues": copy.deepcopy(choices),
    }


def _accept_connect_contract(
    context: dict[str, Any],
    contract: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    if decision.get("decision") != "plan-required":
        return _load_lifecycle_state(context)
    revision = contract.get("contractRevision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ServiceNowConnectError(
            "ServiceNow contract revision is invalid."
        )
    if decision.get("stateExists") is False:
        initialize_lifecycle_state(
            context,
            contract_revision=revision,
        )
        state = _load_lifecycle_state(context)
        state["attestationSource"] = "explicit-connect-invocation"
        _write_lifecycle_state(context, state)
        return state
    state = _load_lifecycle_state(context)
    phases = contract.get("phases")
    if not isinstance(phases, list):
        raise ServiceNowConnectError(
            "ServiceNow contract phases are invalid."
        )
    state_phases = state.setdefault("phases", {})
    if not isinstance(state_phases, dict):
        raise ServiceNowConnectError(
            "ServiceNow lifecycle phases are invalid."
        )
    for phase in phases:
        phase_id = phase.get("id") if isinstance(phase, dict) else None
        if not isinstance(phase_id, str) or not phase_id:
            raise ServiceNowConnectError(
                "ServiceNow contract phase identity is invalid."
            )
        state_phases.setdefault(
            phase_id,
            {
                "status": "pending",
                "checkpointResults": {},
                "checkpointAcknowledgements": {},
            },
        )
    state["attested"] = True
    state["attestedAt"] = _utc_now()
    state["attestationSource"] = "explicit-connect-invocation"
    state["acceptedContractRevision"] = revision
    _write_lifecycle_state(context, state)
    return state


def _record_business_group_acknowledgement(
    context: dict[str, Any],
    state: dict[str, Any],
    contract: dict[str, Any],
    group: dict[str, Any],
    *,
    context_sha256: str,
) -> dict[str, Any]:
    group_context = _business_group_context(context, contract, group)
    if _canonical_json_hash(group_context) != context_sha256:
        raise ServiceNowConnectError(
            "The business-group availability context changed before it was "
            "recorded."
        )
    record = {
        "kind": "maker-attestation",
        "status": "available",
        "businessGroupId": group["id"],
        "role": group["role"],
        "contextIdentity": group_context,
        "contextIdentitySha256": context_sha256,
        "recordedAt": _utc_now(),
    }
    records = state.setdefault("businessGroupAcknowledgements", {})
    if not isinstance(records, dict):
        raise ServiceNowConnectError(
            "ServiceNow business-group acknowledgements are invalid."
        )
    records[group["id"]] = record
    _record_group_role_attestations(state, contract, group)
    _write_lifecycle_state(context, state)
    return copy.deepcopy(record)


def _group_required_roles(
    contract: dict[str, Any],
    group: dict[str, Any],
) -> list[str]:
    phases = {
        str(phase.get("id")): phase
        for phase in contract.get("phases", [])
        if isinstance(phase, dict)
    }
    roles: list[str] = []
    for phase_id in group["phaseIds"]:
        phase = phases.get(phase_id) or {}
        role = phase.get("requiredRole")
        if (
            phase.get("mutates") is True
            and phase.get("gateMode", "attested") == "attested"
            and isinstance(role, str)
            and role
            and role not in roles
        ):
            roles.append(role)
    return roles


def _record_group_role_attestations(
    state: dict[str, Any],
    contract: dict[str, Any],
    group: dict[str, Any],
) -> bool:
    """Count a Maker group Yes as the lifecycle role attestation.

    Only the Maker configuration group carries attested mutating phases, so
    the phase-start availability answer replaces the per-phase role prompts.
    """
    if group.get("id") != "maker-configuration":
        return False
    roles = _group_required_roles(contract, group)
    if not roles:
        return False
    attestations = state.setdefault("roleAttestations", {})
    if not isinstance(attestations, dict):
        raise ServiceNowConnectError(
            "ServiceNow role attestations are invalid."
        )
    changed = False
    for role in roles:
        existing = attestations.get(role)
        if (
            isinstance(existing, dict)
            and existing.get("verifiedBy") == "attested"
            and existing.get("provider") == state.get("provider")
            and existing.get("agentSlug") == state.get("agentSlug")
        ):
            continue
        attestations[role] = {
            "verifiedBy": "attested",
            "provider": state.get("provider"),
            "agentSlug": state.get("agentSlug"),
            "attestedAt": _utc_now(),
            "note": (
                f"maker confirmed availability as {role} at the start of "
                f"{group['label']}"
            ),
        }
        changed = True
    return changed


def _shared_reuse_before_availability(
    context: dict[str, Any],
    state: dict[str, Any] | None,
    decision: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(state, dict):
        return None, False
    phase = decision.get("phase")
    phase_id = phase.get("id") if isinstance(phase, dict) else None
    if phase_id not in {"entra-registration", "servicenow-oidc"}:
        return None, False
    accepted_current = bool(
        any(
            row.get("itemId") == phase_id
            and row.get("decision") == "accepted"
            for row in _shared_identity_item_decisions(
                state.get("sharedConfigurationReuse")
                if isinstance(
                    state.get("sharedConfigurationReuse"),
                    dict,
                )
                else None
            )
        )
        and _identity_admin_handoff_is_ready(
            context,
            state,
            phase=phase_id,
        )
    )
    if accepted_current:
        return None, True
    if (
        phase_id != "entra-registration"
        or decision.get("decision") != "run-action"
    ):
        return None, False
    handoff = shared_reuse_handoff(context)
    if handoff.get("decision") in {
        "question-required",
        "source-selection-required",
    }:
        return handoff, True
    return handoff, False


_RENDER_INSTRUCTION = (
    "Emit `text` verbatim as your very next assistant message, before any "
    "other tool call. Terminal or tool output does not count as showing it. "
    "This is the only renderable field; everything under `internal` is "
    "never shown."
)


_WAITING_RESUME_NOTE = (
    "Progress is saved. Run `/connect servicenow` again when you are ready "
    "to continue."
)


def _resume_render_block(
    progress: dict[str, Any],
    transport: dict[str, Any],
    *,
    group_changed: bool,
    waiting: bool = False,
    show_checklist: bool = True,
) -> dict[str, Any]:
    availability = transport["businessGroupAvailability"]
    internal = progress["internal"]
    current = internal.get("currentPhase")
    current_item = progress.get("currentPhase")
    final_text = internal.get("groupedFinalText")
    if isinstance(final_text, str) and final_text:
        kind = "final"
        parts = [final_text]
    elif waiting and isinstance(current, dict):
        kind = "waiting"
        parts = [
            str(current["groupedWaitingText"]) if show_checklist else "",
            str(current["waitingText"]),
            _WAITING_RESUME_NOTE,
        ]
    elif (
        isinstance(current, dict)
        and isinstance(current_item, dict)
        and current_item.get("status") == "needs-attention"
    ):
        kind = "error"
        parts = [
            str(current["groupedErrorText"]) if show_checklist else "",
            str(current["needsAttentionText"]),
        ]
    else:
        plan = (
            progress.get("mode") == "fresh"
            or group_changed
            or availability["gateRequired"]
        )
        kind = "plan" if plan else "progress"
        parts = [
            str(
                transport["internal"]["ordinaryReply"]["text"]
                if plan
                else (internal["groupedText"] if show_checklist else "")
            )
        ]
        if isinstance(current, dict) and not availability["gateRequired"]:
            parts.append(str(current["startText"]))
    return {
        "kind": kind,
        "text": "\n\n".join(part for part in parts if part),
        "instruction": _RENDER_INSTRUCTION,
    }


def _checkpoint_render_block(
    context: dict[str, Any],
    *,
    phase_id: str,
    outcome: str,
) -> dict[str, Any] | None:
    """Grouped render for a recorded outcome; ``None`` for ``done`` (resume-handoff renders it)."""
    if outcome == "done":
        return None
    root = Path(context["root"])
    contract = _load_json(root / CONTRACT_PATH)
    state = _load_json(_lifecycle_state_path(context))
    done = frozenset(
        key
        for key, value in (state.get("phases") or {}).items()
        if isinstance(value, dict) and value.get("status") == "done"
    )
    progress = _build_phase_progress(
        contract,
        state,
        {"decision": "run-checkpoints", "phase": {"id": phase_id}},
        executed_actions=frozenset(),
        verified_phases=done,
    )
    current = progress["internal"]["currentPhase"]
    if outcome == "blocked":
        kind = "error"
        checklist = current["groupedErrorText"]
        parts = [current["needsAttentionText"]]
    else:
        kind = "waiting"
        checklist = current["groupedWaitingText"]
        parts = [current["waitingText"], _WAITING_RESUME_NOTE]
    if _checklist_due(context, checklist):
        parts.insert(0, checklist)
    return {
        "kind": kind,
        "text": "\n\n".join(parts),
        "instruction": _RENDER_INSTRUCTION,
    }


def resume_handoff(
    context: dict[str, Any],
    *,
    executed_actions: frozenset[str] = frozenset(),
    verified_phases: frozenset[str] = frozenset(),
    roles_available: bool | None = None,
    availability_group_id: str | None = None,
    availability_context_sha256: str | None = None,
    group_changed: bool = False,
) -> dict[str, Any]:
    root = Path(context["root"])
    contract = _load_json(root / CONTRACT_PATH)
    state_path = _lifecycle_state_path(context)
    state = None
    if state_path.exists():
        state = _load_lifecycle_state(context)
        _write_lifecycle_state(context, state)
    decision = decide_next_step(
        root,
        provider=ACTIVE_PROFILE.provider_key,
        agent_slug=_agent_slug(context),
        executed_actions=executed_actions,
        verified_phases=verified_phases,
    )
    if decision.get("decision") == "plan-required":
        state = _accept_connect_contract(context, contract, decision)
        decision = decide_next_step(
            root,
            provider=ACTIVE_PROFILE.provider_key,
            agent_slug=_agent_slug(context),
            executed_actions=executed_actions,
            verified_phases=verified_phases,
        )
    progress = _resume_progress(
        context,
        decision,
        executed_actions=executed_actions,
        verified_phases=verified_phases,
    )
    current_group = _current_business_group(contract, progress)
    is_final = bool(progress["internal"].get("groupedFinalText"))
    show_checklist = _checklist_due(
        context,
        str(progress["internal"]["groupedText"]),
        force=is_final,
    )
    pre_action_handoff, bypass_availability = (
        _shared_reuse_before_availability(
            context,
            state,
            decision,
        )
    )
    transport = _business_group_transport(
        context=context,
        contract=contract,
        state=state,
        title=str(progress["headline"]),
        phase_items=progress["items"],
        current_group=(
            None if bypass_availability else current_group
        ),
        roles_available=roles_available,
        availability_group_id=availability_group_id,
        availability_context_sha256=availability_context_sha256,
        show_checklist=show_checklist,
    )
    opening = _take_dev_opening(context, state, progress)

    def with_opening(block: dict[str, Any]) -> dict[str, Any]:
        if opening:
            block["text"] = f"{opening}\n\n{block['text']}"
        return block

    result: dict[str, Any] = {
        "schemaVersion": "servicenow.resume-handoff.v1",
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "lifecycle": decision,
        "progress": progress,
        "transport": transport,
        "renderBlock": with_opening(
            _resume_render_block(
                progress,
                transport,
                group_changed=group_changed,
                show_checklist=show_checklist,
            )
        ),
    }
    if (
        isinstance(pre_action_handoff, dict)        and pre_action_handoff.get("decision")
        in {"question-required", "source-selection-required"}
    ):
        result["status"] = "shared-identity-reuse-required"
        result["preActionHandoff"] = pre_action_handoff
        return result
    availability = transport["businessGroupAvailability"]
    group_question = availability["question"]
    if group_question is not None and roles_available is not True:
        result["status"] = "business-group-availability-required"
        return result
    if group_question is not None:
        assert current_group is not None
        assert availability["contextIdentitySha256"] is not None
        _record_business_group_acknowledgement(
            context,
            state or _load_lifecycle_state(context),
            contract,
            current_group,
            context_sha256=availability["contextIdentitySha256"],
        )
        return resume_handoff(
            context,
            executed_actions=executed_actions,
            verified_phases=verified_phases,
            group_changed=True,
        )
    result["businessGroupAvailabilityAccepted"] = False
    if (
        current_group is not None
        and not bypass_availability
        and isinstance(state, dict)
        and _record_group_role_attestations(state, contract, current_group)
    ):
        _write_lifecycle_state(context, state)
    pending_input = _pending_preflight_input(state, decision)
    if pending_input is not None:
        result["pendingInput"] = pending_input
        result["renderBlock"] = with_opening(
            _resume_render_block(
                progress,
                transport,
                group_changed=group_changed,
                waiting=True,
                show_checklist=show_checklist,
            )
        )
        return result
    if decision.get("decision") == "run-action":
        phase = decision.get("phase")
        if not isinstance(phase, dict):
            raise ServiceNowConnectError(
                "Lifecycle controller returned an invalid action phase."
            )
        action_doc = str(phase.get("actionDoc") or "")
        result["action"] = {
            "decision": "read-action-doc",
            "actionDoc": action_doc,
        }
    elif decision.get("decision") == "run-checkpoints":
        phase = decision.get("phase")
        checkpoints = (
            phase.get("checkpoints")
            if isinstance(phase, dict)
            else None
        )
        if (
            not isinstance(checkpoints, list)
            or not checkpoints
            or not all(
                isinstance(target, str) and target
                for target in checkpoints
            )
        ):
            raise ServiceNowConnectError(
                "Lifecycle controller returned invalid checkpoint targets."
            )
        commands = []
        for target in checkpoints:
            invocation_id = str(uuid.uuid4())
            argv = [
                "python",
                "scripts/flightcheck/cli.py",
                "--checkpoint",
                target,
                "--compact-result",
                "--invocation-id",
                invocation_id,
                "--quiet-auth",
                "--agent-slug",
                _agent_slug(context),
                "--environment-id",
                str(context["environment"]["id"]),
                "--tenant-id",
                str(context["environment"]["tenant_id"]),
                "--ring",
                str(context["environment"]["ring"]),
                "--no-telemetry",
            ]
            if context.get("account"):
                argv.extend(["--preferred-username", str(context["account"])])
            commands.append(
                {
                    "target": target,
                    "invocationId": invocation_id,
                    "argv": argv,
                    "command": subprocess.list2cmdline(argv),
                    "expectedIdentity": {
                        "provider": ACTIVE_PROFILE.provider_key,
                        "profile": ACTIVE_PROFILE.key,
                        "agentSlug": _agent_slug(context),
                        "agentId": context["agent"]["id"],
                        "environmentId": context["environment"]["id"],
                    },
                }
            )
        result["checkpoints"] = {
            "decision": "run-exact-commands",
            "interpreterNote": (
                "Replace the leading `python` with the launcher resolved "
                "by /setup (`py -3`, `python3`, then `python`); never "
                "assume bare `python`."
            ),
            "commands": commands,
        }
    return result


def _checkpoint_targets_present(
    phase_contract: dict[str, Any],
    results: dict[str, Any],
) -> bool:
    targets = phase_contract.get("checkpoints")
    if not isinstance(targets, list) or not targets:
        return False
    for target in targets:
        if not isinstance(target, str) or not target:
            return False
        if target.endswith("*"):
            prefix = target[:-1]
            if not any(key.startswith(prefix) for key in results):
                return False
        elif target not in results:
            return False
    return True


def _state_dot_value(
    value: dict[str, Any],
    path: str,
    *,
    phase_id: str,
) -> Any:
    current: Any = value
    rendered = path.replace("{phaseId}", phase_id)
    for part in rendered.split(".") if rendered else ():
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _manual_evidence_current(
    state: dict[str, Any],
    phase_contract: dict[str, Any],
) -> bool:
    phase_id = str(phase_contract.get("id") or "")
    config = phase_contract.get("manualAcknowledgementEvidence")
    if not isinstance(config, dict):
        return False
    wrapper = _state_dot_value(
        state,
        str(config.get("path") or ""),
        phase_id=phase_id,
    )
    if not isinstance(wrapper, dict):
        return False
    accepted = config.get("acceptedRecordStatuses")
    if (
        not isinstance(accepted, list)
        or wrapper.get("status") not in accepted
    ):
        return False
    evidence_path = str(config.get("evidenceObjectPath") or "")
    evidence = (
        _state_dot_value(wrapper, evidence_path, phase_id=phase_id)
        if evidence_path
        else wrapper
    )
    if (
        not isinstance(evidence, dict)
        or evidence.get("kind") != config.get("requiredEvidenceKind")
        or not isinstance(evidence.get("recordedAt"), str)
        or not evidence["recordedAt"]
    ):
        return False
    required_values = config.get("requiredValues") or {}
    if not isinstance(required_values, dict) or any(
        evidence.get(key) != expected
        for key, expected in required_values.items()
    ):
        return False
    bindings = config.get("bindings") or []
    if not isinstance(bindings, list):
        return False
    for binding in bindings:
        if not isinstance(binding, dict):
            return False
        evidence_value = _state_dot_value(
            evidence,
            str(binding.get("evidencePath") or ""),
            phase_id=phase_id,
        )
        state_value = _state_dot_value(
            state,
            str(binding.get("statePath") or ""),
            phase_id=phase_id,
        )
        if evidence_value in {None, ""} or evidence_value != state_value:
            return False
    return True


def _phase_contract_complete(
    state: dict[str, Any],
    phase_contract: dict[str, Any],
) -> bool:
    phase_id = phase_contract.get("id")
    state_phases = state.get("phases")
    phase_state = (
        state_phases.get(phase_id)
        if isinstance(state_phases, dict)
        else None
    )
    results = (
        phase_state.get("checkpointResults")
        if isinstance(phase_state, dict)
        else None
    )
    allowed = phase_contract.get("completionStatuses")
    valid_results = (
        isinstance(results, dict)
        and bool(results)
        and isinstance(allowed, list)
        and all(value in allowed for value in results.values())
        and _checkpoint_targets_present(phase_contract, results)
    )
    if (
        valid_results
        and "Manual" in results.values()
        and not _manual_evidence_current(state, phase_contract)
    ):
        valid_results = False
    return (
        isinstance(phase_state, dict)
        and phase_state.get("status") == "done"
        and valid_results
    )


def _completed_contract_phase_ids(
    state: dict[str, Any],
    phases: list[dict[str, Any]],
) -> frozenset[str]:
    return frozenset(
        str(phase_contract["id"])
        for phase_contract in phases
        if isinstance(phase_contract.get("id"), str)
        and _phase_contract_complete(state, phase_contract)
    )


def _resolved_manual_evidence(
    state: dict[str, Any],
    phase_contract: dict[str, Any],
) -> dict[str, Any]:
    phase_id = str(phase_contract.get("id") or "")
    config = phase_contract["manualAcknowledgementEvidence"]
    record_path = str(config.get("path") or "").replace("{phaseId}", phase_id)
    object_path = str(config.get("evidenceObjectPath") or "")
    evidence_path = ".".join(part for part in (record_path, object_path) if part)
    evidence = _state_dot_value(state, evidence_path, phase_id=phase_id)
    evidence = evidence if isinstance(evidence, dict) else {}
    bindings = {}
    for binding in config.get("bindings") or []:
        key = str(binding.get("evidencePath") or "")
        bindings[key] = _state_dot_value(evidence, key, phase_id=phase_id)
    return {
        "source": "matching-action-evidence",
        "evidencePath": evidence_path,
        "evidenceKind": evidence.get("kind"),
        "evidenceRecordedAt": evidence.get("recordedAt"),
        "bindings": bindings,
    }


def _parse_checkpoint_result_args(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        checkpoint_id, separator, status = value.partition("=")
        checkpoint_id = checkpoint_id.strip()
        status = status.strip()
        if not separator or not checkpoint_id or not status:
            raise ServiceNowConnectError(
                f"Checkpoint result {value!r} must be CHECKPOINT_ID=Status."
            )
        if status not in CHECKPOINT_RESULT_STATUSES:
            raise ServiceNowConnectError(
                f"Checkpoint {checkpoint_id} has unknown status {status!r}."
            )
        if checkpoint_id in parsed:
            raise ServiceNowConnectError(
                f"Checkpoint {checkpoint_id} was supplied more than once."
            )
        parsed[checkpoint_id] = status
    return parsed


def record_checkpoint_results(
    context: dict[str, Any],
    *,
    phase_id: str,
    results: list[str],
    maker_acknowledged: list[str] | None = None,
) -> dict[str, Any]:
    """Persist validated checkpoint outcomes; the sole writer of phase checkpoint state."""
    root = Path(context["root"])
    contract = _load_json(root / CONTRACT_PATH)
    if not _lifecycle_state_path(context).exists():
        raise ServiceNowConnectError(
            "No lifecycle state exists. Run resume-handoff first."
        )
    state = _load_lifecycle_state(context)
    revision = contract.get("contractRevision")
    if (
        state.get("attested") is not True
        or state.get("acceptedContractRevision") != revision
    ):
        raise ServiceNowConnectError(
            "The lifecycle plan is not accepted for the current contract "
            "revision. Run resume-handoff first."
        )
    phases = contract.get("phases")
    phases = phases if isinstance(phases, list) else []
    phase_contract = next(
        (
            item
            for item in phases
            if isinstance(item, dict) and item.get("id") == phase_id
        ),
        None,
    )
    if phase_contract is None:
        raise ServiceNowConnectError(
            f"Phase {phase_id!r} is not in the lifecycle contract."
        )
    state_phases = state.get("phases")
    if not isinstance(state_phases, dict) or not isinstance(
        state_phases.get(phase_id), dict
    ):
        raise ServiceNowConnectError(
            f"Lifecycle state has no phase {phase_id!r}."
        )
    for earlier in phases:
        if earlier is phase_contract:
            break
        earlier_state = state_phases.get(earlier.get("id"))
        if (
            not isinstance(earlier_state, dict)
            or earlier_state.get("status") != "done"
        ):
            raise ServiceNowConnectError(
                f"Phase {earlier.get('id')!r} must be done before "
                f"recording {phase_id!r}."
            )
    parsed = _parse_checkpoint_result_args(results)
    targets = phase_contract.get("checkpoints") or []
    for checkpoint_id in parsed:
        if not any(
            checkpoint_id.startswith(target[:-1])
            if target.endswith("*")
            else checkpoint_id == target
            for target in targets
        ):
            raise ServiceNowConnectError(
                f"Checkpoint {checkpoint_id} does not belong to phase "
                f"{phase_id!r}."
            )
    if not _checkpoint_targets_present(phase_contract, parsed):
        raise ServiceNowConnectError(
            f"Phase {phase_id!r} requires results for: "
            + ", ".join(str(target) for target in targets)
            + "."
        )
    acknowledged = list(dict.fromkeys(maker_acknowledged or []))
    for checkpoint_id in acknowledged:
        if parsed.get(checkpoint_id) not in {"Manual", "Warning"}:
            raise ServiceNowConnectError(
                f"Checkpoint {checkpoint_id} is not a Manual or Warning "
                "result and cannot be acknowledged."
            )

    phase_state = state_phases[phase_id]
    previous_acks = phase_state.get("checkpointAcknowledgements")
    previous_acks = previous_acks if isinstance(previous_acks, dict) else {}
    phase_state["checkpointResults"] = dict(parsed)
    allowed = phase_contract.get("completionStatuses") or ["Passed"]
    now = _utc_now()
    reasons: list[str] = []
    acknowledgements: dict[str, Any] = {}
    if any(status in {"Failed", "Error", "Blocked"} for status in parsed.values()):
        outcome = "blocked"
    else:
        outcome = "done"
        evidence_current = _manual_evidence_current(state, phase_contract)
        for checkpoint_id, status in parsed.items():
            if status not in allowed:
                outcome = "in-progress"
                reasons.append(
                    f"{checkpoint_id} is {status}, which does not complete "
                    "this phase."
                )
            elif status == "Manual":
                if evidence_current:
                    acknowledgements[checkpoint_id] = {
                        "status": status,
                        "acknowledgedAt": now,
                        **_resolved_manual_evidence(state, phase_contract),
                    }
                else:
                    outcome = "in-progress"
                    reasons.append(
                        f"{checkpoint_id} is Manual and no current "
                        "provider evidence is recorded for this phase."
                    )
            elif status == "Warning":
                if checkpoint_id in acknowledged:
                    acknowledgements[checkpoint_id] = {
                        "status": status,
                        "acknowledgedAt": now,
                        "source": "maker-confirmation",
                    }
                else:
                    outcome = "in-progress"
                    reasons.append(
                        f"{checkpoint_id} is Warning and needs the "
                        "maker's explicit confirmation."
                    )
    for checkpoint_id, status in parsed.items():
        previous = previous_acks.get(checkpoint_id)
        if (
            checkpoint_id not in acknowledgements
            and isinstance(previous, dict)
            and previous.get("status") == status
            and outcome != "blocked"
        ):
            acknowledgements[checkpoint_id] = previous
    phase_state["checkpointAcknowledgements"] = acknowledgements
    phase_state["status"] = outcome
    if outcome == "done":
        phase_state["lastVerifiedAt"] = now
    else:
        phase_state.pop("lastVerifiedAt", None)
    _write_lifecycle_state(context, state)
    result: dict[str, Any] = {
        "schemaVersion": "servicenow.checkpoint-recording.v1",
        "status": "recorded",
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "phase": phase_id,
        "outcome": outcome,
        "checkpointResults": dict(parsed),
        "acknowledged": sorted(acknowledgements),
        "reasons": reasons,
        "resumeArguments": (
            _verified_prefix_arguments(context, phase_id, include_self=True)
            if outcome == "done"
            else []
        ),
    }
    block = _checkpoint_render_block(
        context, phase_id=phase_id, outcome=outcome
    )
    if block is not None:
        result = {"renderBlock": block, **result}
    return result


def _verified_prefix_arguments(
    context: dict[str, Any],
    phase_id: str,
    *,
    include_self: bool,
) -> list[str]:
    """`--verified-phase` pairs for the done phases up to ``phase_id``.

    Only the contract-order prefix is listed, so a later done phase that has not
    been reached yet is still re-verified by the controller.
    """
    contract = _load_json(Path(context["root"]) / CONTRACT_PATH)
    state = _load_json(_lifecycle_state_path(context))
    phases = state.get("phases") if isinstance(state, dict) else None
    arguments: list[str] = []
    if not isinstance(phases, dict):
        return arguments
    for phase in contract.get("phases") or []:
        current = phase.get("id") if isinstance(phase, dict) else None
        if not isinstance(current, str):
            continue
        if current == phase_id and not include_self:
            break
        value = phases.get(current)
        if isinstance(value, dict) and value.get("status") == "done":
            arguments.extend(["--verified-phase", current])
        if current == phase_id:
            break
    return arguments


def _recovery_handoff(
    *,
    problem: str,
    category: str,
    owner: str,
    where: str,
    values: str,
    action: str,
    success: str,
    recheck: str,
) -> dict[str, str]:
    message = (
        f"**Problem**\n{problem}\n\n"
        f"**Category**\n{category}\n\n"
        f"**Owner**\n{owner}\n\n"
        f"**Where**\n{where}\n\n"
        f"**Values to use**\n{values}\n\n"
        f"**Action**\n{action}\n\n"
        f"**Success**\n{success}\n\n"
        f"**Check again and resume**\n{recheck}"
    )
    return {
        "problem": problem,
        "category": category,
        "owner": owner,
        "where": where,
        "values": values,
        "action": action,
        "success": success,
        "recheck": recheck,
        "message": message,
    }


def _publish_remote_snapshot(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    agentbuilder = _agentbuilder_client(context)
    agent = agentbuilder.get_agent(context["agent"]["id"])
    components = agentbuilder.fetch_components(context["agent"]["id"])
    last_published_at = agent.get("lastPublishedAt")
    return {
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "componentHash": _component_hash(components),
        "draftSemanticHash": _draft_semantic_hash(components),
        "connectionBindingHash": _connection_binding_hash(
            context,
            state,
            components,
        ),
        "serverLastPublishedAt": (
            last_published_at
            if isinstance(last_published_at, str) and last_published_at
            else None
        ),
    }


def inspect_publish_state(
    context: dict[str, Any],
) -> dict[str, Any]:
    state = _load_lifecycle_state(context)
    receipt = state.get("evidence", {}).get("publish")
    receipt = receipt if isinstance(receipt, dict) else {}
    snapshot = _publish_remote_snapshot(context, state)
    return {
        "status": "read-only",
        **snapshot,
        "receipt": {
            "status": receipt.get("status"),
            "requestedAt": receipt.get("requestedAt"),
            "completedAt": receipt.get("completedAt"),
            "componentHash": receipt.get("componentHash"),
            "requestedComponentHash": receipt.get(
                "requestedComponentHash"
            ),
            "publishedComponentHash": receipt.get(
                "publishedComponentHash"
            ),
        },
        "reconciliationEligible": bool(
            snapshot["serverLastPublishedAt"]
            and receipt.get("requestedAt")
            and receipt.get("status")
            in {"confirmation-required", "needs_remediation"}
            and receipt.get("publishedComponentHash") is None
        ),
    }


def _parse_utc_timestamp(value: str, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ServiceNowConnectError(
            f"{label} must be an ISO 8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise ServiceNowConnectError(f"{label} must include a timezone.")
    return parsed.astimezone(dt.UTC)


def reconcile_publish_receipt(
    context: dict[str, Any],
    *,
    expected_component_hash: str,
    expected_last_published_at: str,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Publish receipt reconciliation requires explicit confirmation."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_component_hash):
        raise ServiceNowConnectError(
            "Expected component hash must be a lowercase SHA-256 value."
        )
    state = _load_lifecycle_state(context)
    evidence = state.setdefault("evidence", {})
    receipt = evidence.get("publish")
    if not isinstance(receipt, dict):
        raise ServiceNowConnectError(
            "No legacy publish receipt is available to reconcile."
        )
    if receipt.get("publishedComponentHash") is not None:
        raise ServiceNowConnectError(
            "The publish receipt already has a post-publish component hash."
        )
    requested_at = receipt.get("requestedAt")
    if not isinstance(requested_at, str) or not requested_at:
        raise ServiceNowConnectError(
            "The legacy publish receipt has no request timestamp."
        )
    expected_published = _parse_utc_timestamp(
        expected_last_published_at,
        "Expected server lastPublishedAt",
    )
    requested = _parse_utc_timestamp(
        requested_at,
        "Legacy publish requestedAt",
    )
    if abs((expected_published - requested).total_seconds()) > 300:
        raise ServiceNowConnectError(
            "The server publish timestamp does not match the legacy request."
        )

    snapshot = _publish_remote_snapshot(context, state)
    if snapshot["componentHash"] != expected_component_hash:
        raise ServiceNowConnectError(
            "The current component revision changed after maker confirmation."
        )
    if snapshot["serverLastPublishedAt"] != expected_last_published_at:
        raise ServiceNowConnectError(
            "The server publish timestamp changed after maker confirmation."
        )
    test_record = evidence.get("test")
    if (
        not isinstance(test_record, dict)
        or test_record.get("status") != "completed"
        or test_record.get("result") != "pass"
        or not isinstance(test_record.get("binding"), dict)
        or test_record["binding"].get("draftSemanticHash")
        != snapshot["draftSemanticHash"]
        or test_record["binding"].get("connectionBindingHash")
        != snapshot["connectionBindingHash"]
    ):
        raise ServiceNowConnectError(
            "The current draft and selected connection do not have a matching "
            "privacy-safe Test result for publish receipt reconciliation."
        )

    legacy_receipt = {
        key: copy.deepcopy(receipt.get(key))
        for key in (
            "requestedAt",
            "completedAt",
            "status",
            "componentHash",
            "requestedComponentHash",
            "response",
        )
        if key in receipt
    }
    reconciled_at = _utc_now()
    reconciled = {
        **receipt,
        "kind": "maker-attestation",
        "status": "confirmation-required",
        "completedAt": (
            receipt.get("completedAt") or expected_last_published_at
        ),
        "requestedComponentHash": (
            receipt.get("requestedComponentHash")
            or receipt.get("componentHash")
        ),
        "publishedComponentHash": expected_component_hash,
        "componentHash": expected_component_hash,
        "testedDraftSemanticHash": snapshot["draftSemanticHash"],
        "publishedSemanticHash": snapshot["draftSemanticHash"],
        "connectionBindingHash": snapshot["connectionBindingHash"],
        "serverLastPublishedAt": expected_last_published_at,
        "verifiedBy": "maker-attested-current-revision",
        "recordedAt": reconciled_at,
        "attestedAt": reconciled_at,
        "reconciledAt": reconciled_at,
        "legacyReceipt": legacy_receipt,
    }
    evidence["publish"] = reconciled
    state["componentHash"] = expected_component_hash
    state["draftSemanticHash"] = snapshot["draftSemanticHash"]
    state["connectionBindingHash"] = snapshot["connectionBindingHash"]
    _write_lifecycle_state(context, state)
    return reconciled


def publish(
    context: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    raise ServiceNowConnectError(
        "Automatic publishing is disabled for ServiceNow Connect. Complete "
        "the current Test pane validation, then publish manually outside "
        "Connect when you are ready."
    )


def record_test_attestation(
    context: dict[str, Any],
    *,
    prompt_category: str,
    result: str,
    failure_category: str | None,
) -> dict[str, Any]:
    allowed_prompts = {ACTIVE_PROFILE.test_prompt_category}
    allowed_failures = {
        "authentication",
        "permission",
        "empty-result",
        "connector",
        "unexpected",
    }
    if prompt_category not in allowed_prompts:
        raise ServiceNowConnectError(
            "Unsupported privacy-safe Test pane prompt category."
        )
    if result == "empty":
        if failure_category is not None:
            raise ServiceNowConnectError(
                "An empty-result answer cannot have a failure category."
            )
        # An empty result is not evidence: nothing is recorded and the Test
        # step stays open.
        return {
            "status": "open",
            "result": "empty",
            "recorded": False,
            "message": _dev_empty_result_message(),
        }
    if result not in {"pass", "fail", "untested"}:
        raise ServiceNowConnectError(
            "Test pane result must be pass, fail, or untested."
        )
    if result == "pass" and failure_category is not None:
        raise ServiceNowConnectError(
            "A passing Test pane result cannot have a failure category."
        )
    if result == "untested" and failure_category is not None:
        raise ServiceNowConnectError(
            "An untested Test pane result cannot have a failure category."
        )
    if (
        result == "fail"
        and failure_category is not None
        and failure_category not in allowed_failures
    ):
        raise ServiceNowConnectError(
            "The Test pane failure category is unsupported."
        )
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )
    state = _load_lifecycle_state(context, components)
    evidence = state.setdefault("evidence", {})
    credential = evidence.get("credential")
    if not isinstance(credential, dict) or not credential.get("connectionId"):
        raise ServiceNowConnectError(
            "Select and verify a ServiceNow credential before recording a test."
        )
    draft_semantic_hash = _draft_semantic_hash(components)
    connection_binding_hash = _connection_binding_hash(
        context,
        state,
        components,
    )
    attestation = {
        "kind": "maker-attestation",
        "status": {
            "pass": "completed",
            "fail": "failed",
            "untested": "untested",
        }[result],
        "promptCategory": prompt_category,
        "result": result,
        "failureCategory": failure_category,
        "recordedAt": _utc_now(),
        "binding": {
            "connectionId": credential["connectionId"],
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
            "draftSemanticHash": draft_semantic_hash,
            "connectionBindingHash": connection_binding_hash,
        },
    }
    evidence["test"] = attestation
    state["draftSemanticHash"] = draft_semantic_hash
    state["connectionBindingHash"] = connection_binding_hash
    _write_lifecycle_state(context, state)
    if result == "untested":
        return {
            **attestation,
            "message": _dev_untested_message(_existing_identity_kind(state)),
        }
    return attestation


def migrate_state(context: dict[str, Any]) -> dict[str, Any]:
    if ACTIVE_PROFILE.key != "hrsd":
        raise ServiceNowConnectError(
            "Legacy state migration is supported only for the HRSD provider."
        )
    state = _load_lifecycle_state(context)
    _write_lifecycle_state(context, state)
    return {
        "status": "migrated",
        "statePath": str(_lifecycle_state_path(context)),
        "migration": state.get("migration", {}),
    }


REALM_COMMANDS = frozenset(
    {
        "discover-realm-target",
        "realm-status",
        "check-realm",
        "record-realm-test",
        "record-realm-admin",
        "select-realm",
    }
)
REALM_RECOVERY_CHOICES = ("Yes", "No")


def _realm_dev_state(context: dict[str, Any]) -> dict[str, Any]:
    """Dev lifecycle record; a missing or unreadable record is not an error."""
    path = _lifecycle_state_path(context)
    if not path.is_file():
        return {}
    try:
        state = _load_json(path)
    except ServiceNowConnectError:
        return {}
    if state_integrity_mismatch(state):
        return {}
    return state


def _realm_dev_reference(context: dict[str, Any]) -> dict[str, str]:
    """Optional Dev record values; a missing or unreadable record is not an error."""
    state = _realm_dev_state(context)
    return realms.dev_reference_from_state(state) if state else {}


def _realm_admin_case(
    context: dict[str, Any],
    identity: dict[str, Any],
) -> str:
    """Decide from the recorded Dev lifecycle, never from the model."""
    state = _realm_dev_state(context)
    if state and realms.dev_admin_setup_complete(
        state, tenant_id=identity.get("tenantId")
    ):
        return realms.ADMIN_CASE_REUSE
    return realms.ADMIN_CASE_INDEPENDENT


def _realm_servicenow_instruction(
    context: dict[str, Any],
    *,
    client_id: str,
    claim_name: str,
    instance_name: str,
) -> str:
    _path, text, _sha = _identity_runtime_instruction_source("servicenow")
    rendered = (
        text.replace("<client ID>", client_id)
        .replace(
            "<tenant ID>",
            _normalize_directory_tenant_id(context["environment"]["tenant_id"]),
        )
        .replace("<instance>", normalize_instance_name(instance_name))
        .replace("<claim>", claim_name)
    )
    if ACTIVE_PROFILE.key != "hrsd":
        rendered = re.sub(
            r"(?m)^8\. \*\*HR agent only:\*\*.*(?:\n|$)",
            "",
            rendered,
        ).rstrip()
    if any(
        placeholder in rendered
        for placeholder in ("<client ID>", "<tenant ID>", "<instance>", "<claim>")
    ):
        raise ServiceNowConnectError(
            "ServiceNow runtime instruction placeholders were not resolved."
        )
    return rendered


def _realm_admin_instruction(
    context: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, str]:
    """Reuse the Dev administrator messages for the one step still open."""
    waiting = realms.independent_pending(target)
    if waiting is None:
        return {}
    setup = target.get("adminSetup") or {}
    if waiting == "instance":
        return {
            "instance": (
                "What is your ServiceNow instance name, for example "
                "`contoso`? We need it to prepare the message for your "
                "Microsoft Entra administrator."
            )
        }
    if waiting == "entra":
        _path, text, _sha = _identity_runtime_instruction_source("entra")
        lead_in = _identity_handoff_lead_in("entra").replace(
            "The HR prerequisite is confirmed. Next, send", "Next, send"
        )
        return {"entra": f"{lead_in}\n\n{_ready_to_send_block(text)}"}
    rendered = _realm_servicenow_instruction(
        context,
        client_id=setup["entra"]["clientId"],
        claim_name=setup["entra"]["claimName"],
        instance_name=setup["instanceName"],
    )
    return {
        "servicenow": (
            f"{_identity_handoff_lead_in('servicenow')}\n\n"
            f"{_ready_to_send_block(rendered)}"
        )
    }


def _realm_topic_states(components: dict[str, Any]) -> list[dict[str, Any]]:
    """Profile topics keyed by name so promoted schema prefixes still match."""
    namespace = (
        "servicenowhrsd" if ACTIVE_PROFILE.key == "hrsd" else "servicenowitsm"
    )
    topics = []
    for change in components.get("botComponentChanges") or []:
        component = change.get("component") if isinstance(change, dict) else None
        if not isinstance(component, dict) or not isinstance(
            component.get("dialog"), dict
        ):
            continue
        _prefix, _marker, name = str(component.get("schemaName") or "").partition(
            ".topic."
        )
        if name.casefold().startswith(namespace):
            topics.append(
                {
                    "schemaName": name,
                    "state": component.get("state"),
                    "status": component.get("status"),
                }
            )
    return topics


def _realm_target_context(
    context: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    identity = target["identity"]
    return {
        **context,
        "environment": {**context["environment"], "id": identity["environmentId"]},
        "agent": {**context["agent"], "id": identity["agentId"]},
    }


def _realm_run_checks(
    context: dict[str, Any],
    target: dict[str, Any],
) -> None:
    """Re-read the promoted realm; nothing here writes to the agent."""
    environment = context["environment"]
    ring = environment["ring"]
    identity = target["identity"]
    expected = target["expected"]
    host = derive_environment_host(identity["environmentId"], ring)
    target_client = AgentBuilderClient(
        host,
        _agentbuilder_token(context),
        ring=ring,
        tenant_id=environment["tenant_id"],
        api_version=environment.get("api_version", "2024-10-01"),
    )
    target_components = target_client.fetch_components(identity["agentId"])
    try:
        reference = summarize_components(target_components)["reference"]
    except ServiceNowConnectError:
        reference = {}
    connections: list[dict[str, Any]] = []
    if reference.get("connectionId"):
        connectivity = ConnectivityClient(
            host,
            identity["environmentId"],
            _authenticate_maker(
                context,
                scopes=tuple(connectivity_scopes(ring)),
            ),
            ring=ring,
        )
        connections = [
            connection_summary(record)
            for record in connectivity.list_connections()
        ]
    try:
        portal = portal_configuration_summary(
            target_components,
            expected_instance_name=expected["values"].get("instanceName"),
        )
    except ServiceNowConnectError:
        portal = {"valid": False, "reason": "portal-topic-missing"}
    realms.apply_checks(
        target,
        connections=realms.evaluate_connections(
            expected,
            reference,
            connections,
        ),
        runtime=realms.evaluate_runtime(
            expected,
            _realm_topic_states(target_components),
            portal,
        ),
    )


REALM_COMPLETION_SCOPE = {
    "hrsd": ("HR case lookup", "case creation"),
    "itsm": ("IT ticket lookup", "ticket creation, the HR agent"),
}
REALM_COMPLETION_LIMIT = {"test": "Prod behavior", "prod": "release readiness"}


def _realm_completion_message(realm: str) -> str:
    lookup, not_covered = REALM_COMPLETION_SCOPE[ACTIVE_PROFILE.key]
    label = realm.title()
    return (
        f"**Your {lookup} worked in {label}.** "
        f"{_spec_agent_name()} "
        "returned the result you expected for your account. This confirms the "
        f"lookup for your tested account and this agent in {label}, not "
        f"{not_covered}, other employees' sign-in mapping, or "
        f"{REALM_COMPLETION_LIMIT[realm]}."
    )


def _realm_untested_message(realm: str) -> str:
    label = realm.title()
    return (
        f"**The applicable ServiceNow setup steps in {label} are finished, "
        "but this destination integration remains untested.** Test this "
        "agent before employees use it.\n\n"
        "Your progress is saved at the destination Test-pane request. When "
        "you return, we'll continue there."
    )


def _realm_render_context(
    context: dict[str, Any],
    registry: dict[str, Any],
    realm: str,
) -> dict[str, Any] | None:
    target = registry["targets"].get(realm)
    if realm not in realms.PROMOTED_REALMS or not isinstance(target, dict):
        return None
    hr = ACTIVE_PROFILE.key == "hrsd"
    status = realms.target_status(registry, realm)
    footer = None
    if status == "ready":
        footer = _realm_completion_message(realm)
    elif status == "untested":
        footer = _realm_untested_message(realm)
    return {
        "agent": _spec_agent_name(),
        "kind": "HR" if hr else "IT",
        "record": "case" if hr else "ticket",
        "example": "Show my open HR cases" if hr else "Show my open IT tickets",
        "agentUrl": maker_portal_links(_realm_target_context(context, target))[
            "copilotStudioAgent"
        ]["url"],
        "footer": footer,
        "adminInstruction": _realm_admin_instruction(context, target),
    }


def _realm_status_result(
    context: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    active = str(registry.get("activeTargetRealm") or "dev")
    return realms.realm_status(
        registry, render=_realm_render_context(context, registry, active)
    )


def _realm_check_result(
    context: dict[str, Any],
    registry: dict[str, Any],
    realm: str,
) -> dict[str, Any]:
    result = realms.realm_status(
        registry, render=_realm_render_context(context, registry, realm)
    )
    target = registry["targets"][realm]
    result["realm"] = realm
    result["promotedAgent"] = {
        "environmentId": target["identity"]["environmentId"],
        "agentId": target["identity"]["agentId"],
        "copilotStudioUrl": maker_portal_links(
            _realm_target_context(context, target)
        )["copilotStudioAgent"]["url"],
    }
    if realms.target_status(registry, realm) == "ready":
        result["message"] = _realm_completion_message(realm)
    elif realms.target_status(registry, realm) == "untested":
        result["message"] = _realm_untested_message(realm)
    return result


def _realm_expected_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "instanceName": getattr(args, "expected_instance", None),
        "clientId": getattr(args, "expected_client_id", None),
    }


def _run_realm_command(
    context: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    root = Path(context["root"])
    provider = ACTIVE_PROFILE.provider_key
    slug = _agent_slug(context)
    registry = realms.load_registry(root, provider, slug)
    command = args.command
    if command == "realm-status":
        return _realm_status_result(context, registry)
    if command == "select-realm":
        realms.select_realm(registry, args.realm)
        realms.save_registry(root, registry)
        return _realm_status_result(context, registry)

    if command == "discover-realm-target":
        if not args.realm and not args.agent_link:
            raise ServiceNowConnectError(
                "Specify --realm test|prod, or --agent-link with the "
                "promoted agent's Copilot Studio link."
            )
        environment = context["environment"]
        realm, identity = realms.discover_realm(
            root=root,
            ring=environment["ring"],
            tenant_id=environment["tenant_id"],
            source_host=environment["power_platform_api_endpoint"],
            api_version=environment.get("api_version", "2024-10-01"),
            source_agent_id=context["agent"]["id"],
            expected_schema_name=AGENT_SCHEMA_NAME,
            realm=args.realm,
            environment_selector=args.environment,
            agent_link=args.agent_link,
            account_hint=context.get("account"),
        )
        previous = registry["targets"].get(realm)
        same_target = (
            isinstance(previous, dict)
            and previous["identity"]["agentId"] == identity["agentId"]
            and previous["identity"]["environmentId"] == identity["environmentId"]
        )
        admin_setup = previous.get("adminSetup") if same_target else None
        if not isinstance(admin_setup, dict):
            admin_setup = realms.new_admin_setup(_realm_admin_case(context, identity))
        if admin_setup["case"] == realms.ADMIN_CASE_REUSE:
            expected = realms.resolve_expected(
                identity,
                dev_reference=_realm_dev_reference(context),
                previous=(previous or {}).get("expected"),
                provided=_realm_expected_args(args),
                admin_confirmed=args.admin_confirmed,
            )
        else:
            expected = (
                previous["expected"]
                if same_target
                else {
                    "values": {},
                    "sources": {},
                    "adminConfirmed": False,
                    "devRecordDifferences": [],
                }
            )
        target = realms.record_target(
            registry, realm, identity, expected, admin_setup
        )
        if admin_setup["case"] == realms.ADMIN_CASE_INDEPENDENT:
            _realm_apply_independent_args(target, args)
        realms.save_registry(root, registry)
    else:
        realm = args.realm
        target = registry["targets"].get(realm)
        if not isinstance(target, dict):
            raise ServiceNowConnectError(
                f"The {realm.title()} realm has not been discovered yet."
            )
        if command == "record-realm-admin":
            _record_realm_admin(context, target, args)
        elif command == "check-realm":
            if realms.admin_case(target) == realms.ADMIN_CASE_INDEPENDENT:
                _realm_apply_independent_args(target, args)
            else:
                target = realms.update_expected(
                    registry,
                    realm,
                    realms.resolve_expected(
                        target["identity"],
                        dev_reference=_realm_dev_reference(context),
                        previous=target["expected"],
                        provided=_realm_expected_args(args),
                        admin_confirmed=args.admin_confirmed,
                    ),
                )

    if command in {"discover-realm-target", "check-realm", "record-realm-admin"}:
        if realms.independent_pending(target) is None:
            _realm_run_checks(context, target)
    else:
        realms.record_validation(
            target,
            prompt_category=args.prompt_category,
            allowed_prompt_category=ACTIVE_PROFILE.test_prompt_category,
            result=args.result,
            failure_category=args.failure_category,
        )
    realms.save_registry(root, registry)
    return _realm_check_result(context, registry, realm)


def _realm_apply_independent_args(
    target: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    if getattr(args, "expected_client_id", None) or getattr(
        args, "admin_confirmed", False
    ):
        raise realms.ServiceNowRealmError(
            "This destination runs its own administrator setup, so the "
            "Client ID comes from the Microsoft Entra administrator's reply "
            "and is never typed in by the maker."
        )
    if getattr(args, "expected_instance", None):
        realms.set_independent_instance(target, args.expected_instance)


def _record_realm_admin(
    context: dict[str, Any],
    target: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    if realms.admin_case(target) != realms.ADMIN_CASE_INDEPENDENT:
        raise realms.ServiceNowRealmError(
            "This destination reuses the administrator-confirmed setup from "
            "Dev, so no administrator reply is needed."
        )
    if args.stage == "entra":
        if not args.client_id or not args.claim_name:
            raise ServiceNowConnectError(
                "The Microsoft Entra administrator's reply needs the "
                "Application (client) ID and one User Claim name."
            )
        claim = _safe_identity_name(args.claim_name, "user_claim")
        if claim.casefold() == "aud":
            raise ServiceNowConnectError(
                "The aud audience claim cannot be selected as the "
                "user-matching User Claim."
            )
        if args.directory_tenant_id is not None and (
            _normalize_directory_tenant_id(args.directory_tenant_id)
            != _normalize_directory_tenant_id(context["environment"]["tenant_id"])
        ):
            raise ServiceNowConnectError(
                "The confirmed Directory tenant ID does not match the "
                "current target tenant."
            )
        realms.record_admin_entra(
            target,
            client_id=normalize_client_id(args.client_id),
            claim_name=claim,
        )
        return
    if not args.user_field or not _SAFE_USER_FIELD.fullmatch(
        str(args.user_field).strip()
    ):
        raise ServiceNowConnectError(
            "The ServiceNow administrator's reply needs the actual internal "
            "sys_user field name."
        )
    realms.record_admin_servicenow(
        target,
        user_field=str(args.user_field).strip(),
        confirmed=bool(args.confirm_saved_mapping),
    )


def run_realm_command(
    context: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    try:
        return _run_realm_command(context, args)
    except realms.ServiceNowRealmError as exc:
        raise ServiceNowConnectError(
            str(exc),
            details={
                "remediation": exc.customer_remediation,
                "recoveryChoices": list(REALM_RECOVERY_CHOICES),
            },
        ) from exc


def _add_realm_expectation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--expected-instance",
        help="ServiceNow instance this realm should use; ask only when missing.",
    )
    parser.add_argument(
        "--expected-client-id",
        help="Entra application (client) ID this realm should use; ask only when missing.",
    )
    parser.add_argument(
        "--admin-confirmed",
        action="store_true",
        help="The ServiceNow administrator confirmed the values the maker gave.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DA-GA Employee Self-Service ServiceNow connection setup.",
    )
    parser.add_argument(
        "--provider",
        choices=tuple(
            profile.provider_key for profile in PRODUCT_PROFILES.values()
        ),
        default=HRSD_PROFILE.provider_key,
        help="ServiceNow lifecycle provider for the selected ESS agent.",
    )
    parser.add_argument(
        "--maker-username",
        default=None,
        help=(
            "Maker account (UPN) for this run. Overrides the account pinned "
            "in this agent's Connect state."
        ),
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--agent-id",
        help="Selected AgentBuilder bot ID; does not change activeAgent.",
    )
    target.add_argument(
        "--agent-slug",
        help="Selected local agent slug; does not change activeAgent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "adapt-question",
        help=(
            "Read one canonical ServiceNow question object from stdin and "
            "return the active ask_user message/requestedSchema arguments."
        ),
    )
    subparsers.add_parser(
        "list-agents",
        help="List recognizable live ESS HR/IT agents for this environment.",
    )
    chooser_parser = subparsers.add_parser(
        "agent-chooser",
        help=(
            "Choose a locally prepared ESS agent or resolve one explicit "
            "Copilot Studio agent link without changing state."
        ),
    )
    chooser_parser.add_argument("--selection-key")
    chooser_parser.add_argument("--agent-link")
    claim_parser = subparsers.add_parser(
        "claim-confirmation-handoff",
        help=(
            "Return the fixed reply for a custom claim the Entra "
            "administrator has not confirmed; records nothing."
        ),
    )
    claim_parser.add_argument("--custom-claim", action="store_true")
    claim_parser.add_argument("--claim-name-given", action="store_true")
    claim_parser.add_argument("--servicenow-confirmed", action="store_true")
    metadata_parser = subparsers.add_parser(
        "metadata-url-handoff",
        help=(
            "Return the fixed reply when the administrator reports a /v2.0 "
            "metadata URL; records nothing."
        ),
    )
    metadata_parser.add_argument("--metadata-url", required=True)
    target_change_parser = subparsers.add_parser(
        "target-change-handoff",
        help=(
            "Fixed notice when the maker changes the target environment, "
            "agent, instance, tenant, or signed-in user."
        ),
    )
    target_change_parser.add_argument(
        "--change", choices=_TARGET_CHANGES, required=True
    )
    target_change_parser.add_argument(
        "--target",
        help="Friendly name of the new environment or agent (never an ID or URL).",
    )
    test_failure_parser = subparsers.add_parser(
        "test-failure-handoff",
        help=(
            "Fixed reply when this agent's Test pane request fails although "
            "another ESS agent worked with the same connection; records "
            "nothing."
        ),
    )
    test_failure_parser.add_argument("--reported-claim")
    test_failure_parser.add_argument("--reported-user-field")
    existing_parser = subparsers.add_parser(
        "existing-identity-handoff",
        help=(
            "Fixed reply when the maker says ESS should reuse an existing "
            "ServiceNow Knowledge, single sign-on, or Microsoft Graph "
            "sign-in setup; records only a non-identity marker so every "
            "later administrator message keeps the compatibility-review "
            "wording."
        ),
    )
    existing_parser.add_argument(
        "--existing",
        choices=tuple(_EXISTING_IDENTITY_KINDS),
        required=True,
    )
    existing_parser.add_argument(
        "--situation",
        choices=_EXISTING_IDENTITY_SITUATIONS,
        default="disclosure",
    )
    existing_parser.add_argument("--connection-name")
    existing_parser.add_argument("--metadata-url")
    service_areas_parser = subparsers.add_parser(
        "empty-service-areas-handoff",
        help=(
            "Return the fixed reply when the maker reports an empty HR "
            "service-area list; records nothing."
        ),
    )
    service_areas_parser.add_argument(
        "--realm", choices=("dev", "test", "prod"), default="dev"
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect the selected ESS agent and ServiceNow connection state.",
    )
    inspect_parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the cached component snapshot and skip live APIs.",
    )
    inspect_portal_parser = subparsers.add_parser(
        "inspect-portal-url",
        help="Inspect the exact profile Portal Base URI topic value.",
    )
    inspect_portal_parser.add_argument("--offline", action="store_true")
    inspect_portal_parser.add_argument("--expected-portal-url")
    subparsers.add_parser(
        "inspect-admin-setup",
        help="Discover reusable ServiceNow admin setup with read-only APIs.",
    )
    reuse_handoff_parser = subparsers.add_parser(
        "shared-reuse-handoff",
        help=(
            "Return compatible HR/IT shared configuration and the bounded "
            "maker reuse question without changing state."
        ),
    )
    reuse_handoff_parser.add_argument("--source-key")
    reuse_parser = subparsers.add_parser(
        "record-shared-reuse",
        help=(
            "Record the maker's shared-configuration decision and apply only "
            "compatible confirmed items."
        ),
    )
    reuse_parser.add_argument("--source-key", required=True)
    reuse_parser.add_argument(
        "--decision",
        choices=("accept", "decline"),
        required=True,
    )
    portal_reuse_handoff_parser = subparsers.add_parser(
        "portal-reuse-handoff",
        help=(
            "Return compatible locally confirmed employee portal URL values "
            "without changing state."
        ),
    )
    portal_reuse_handoff_parser.add_argument("--source-key")
    portal_reuse_parser = subparsers.add_parser(
        "record-portal-reuse",
        help=(
            "Record the Maker's saved portal URL reuse decision for this "
            "agent without changing the remote topic."
        ),
    )
    portal_reuse_parser.add_argument("--source-key", required=True)
    portal_reuse_parser.add_argument(
        "--decision",
        choices=("accept", "decline"),
        required=True,
    )
    preflight_parser = subparsers.add_parser(
        "record-preflight",
        help="Record the public ServiceNow instance URL when discovery cannot derive it.",
    )
    preflight_parser.add_argument("--instance-url", required=True)
    direct_handoff_parser = subparsers.add_parser(
        "identity-direct-handoff",
        help=(
            "Return source-faithful administrator instructions and native "
            "direct-capture questions without changing state."
        ),
    )
    direct_handoff_parser.add_argument(
        "--stage",
        choices=("entra", "servicenow"),
        required=True,
    )
    direct_handoff_parser.add_argument(
        "--client-id",
        help=(
            "Current-turn Application client ID already accepted by the "
            "caller. It is validated but not persisted."
        ),
    )
    direct_handoff_parser.add_argument(
        "--user-field",
        help=(
            "Current-turn ServiceNow internal user field already accepted by "
            "the caller. It is validated but not persisted by this command."
        ),
    )
    requirement_parser = subparsers.add_parser(
        "record-identity-requirement",
        help=(
            "Record the Maker-confirmed ServiceNow user identifier type as "
            "routing intent before the Entra administrator handoff."
        ),
    )
    requirement_parser.add_argument(
        "--choice",
        choices=tuple(IDENTITY_REQUIREMENT_CHOICES),
        required=True,
    )
    direct_mapping_parser = subparsers.add_parser(
        "record-identity-direct",
        help=(
            "Record direct non-secret Entra or ServiceNow identity values "
            "after explicit confirmation."
        ),
    )
    direct_mapping_parser.add_argument(
        "--stage",
        choices=("entra", "servicenow"),
        required=True,
    )
    direct_mapping_parser.add_argument("--client-id")
    direct_mapping_parser.add_argument(
        "--directory-tenant-id",
        help=argparse.SUPPRESS,
    )
    direct_mapping_parser.add_argument("--claim-name")
    direct_mapping_parser.add_argument(
        "--claim-setup-confirmed",
        action="store_true",
        help=(
            "The Entra administrator confirmed the custom claim setup is "
            "complete. Required to record a claim other than email or upn."
        ),
    )
    direct_mapping_parser.add_argument("--user-field")
    direct_mapping_parser.add_argument("--yes", action="store_true")
    saved_mapping_group = direct_mapping_parser.add_mutually_exclusive_group()
    saved_mapping_group.add_argument(
        "--confirm-saved-mapping",
        action="store_true",
        help=(
            "Confirm that the ServiceNow configuration is saved and the "
            "locked claim is mapped to the recorded user field."
        ),
    )
    saved_mapping_group.add_argument(
        "--reject-saved-mapping",
        action="store_true",
        help=(
            "Record the latest explicit No answer and keep the ServiceNow "
            "mapping receipt pending."
        ),
    )
    phase_parser = subparsers.add_parser(
        "record-admin-phase",
        help="Record one complete non-secret delegated admin phase.",
    )
    phase_parser.add_argument(
        "--phase",
        required=True,
        choices=tuple(sorted(ADMIN_PHASES)),
    )
    phase_parser.add_argument(
        "--status",
        required=True,
        choices=("completed", "reused"),
    )
    phase_parser.add_argument("--client-id")
    phase_parser.add_argument(
        "--confirm-application-registration",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    phase_parser.add_argument(
        "--confirm-claim-emission",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    phase_parser.add_argument(
        "--confirm-user-impersonation-scope",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    phase_parser.add_argument(
        "--confirm-connector-preauthorization",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    phase_parser.add_argument(
        "--confirm-configuration-saved",
        action="store_true",
    )
    phase_parser.add_argument(
        "--confirm-oidc-provider",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    phase_parser.add_argument(
        "--confirm-claim-mapping",
        action="store_true",
    )
    phase_parser.add_argument(
        "--confirm-active-user-match",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    create_parser = subparsers.add_parser(
        "create",
        help="Show guided steps for manually creating the ServiceNow connection.",
    )
    create_parser.add_argument("--instance-name")
    create_parser.add_argument("--resource-uri")
    create_parser.add_argument("--display-name")

    credential_parser = subparsers.add_parser(
        "record-credential",
        help="Record a selected healthy ServiceNow credential.",
    )
    credential_parser.add_argument("--connection-id", required=True)
    resolve_credential_parser = subparsers.add_parser(
        "resolve-credential",
        help=(
            "Freshly verify exact healthy ServiceNow credentials and "
            "automatically select one when unambiguous."
        ),
    )
    resolve_credential_parser.add_argument("--selection-key")

    topic_state_parser = subparsers.add_parser(
        "set-topic-state",
        help="Set one ServiceNow topic to Active or Inactive.",
    )
    topic_state_parser.add_argument("--topic-id", required=True)
    topic_state_parser.add_argument(
        "--state",
        choices=("active", "inactive"),
        required=True,
    )
    topic_state_parser.add_argument("--yes", action="store_true")

    enable_all_parser = subparsers.add_parser(
        "enable-all-topics",
        help="Enable every official profile topic after customer confirmation.",
    )
    enable_all_parser.add_argument("--yes", action="store_true")

    rollback_parser = subparsers.add_parser(
        "rollback-topics",
        help="Restore a prepared ServiceNow topic transaction.",
    )
    rollback_parser.add_argument("--operation-id", required=True)
    rollback_parser.add_argument("--yes", action="store_true")

    topic_choice_parser = subparsers.add_parser(
        "record-topic-choice",
        help="Record the customer's decision to keep current topic states.",
    )
    topic_choice_parser.add_argument(
        "--choice",
        choices=("keep-current",),
        required=True,
    )
    topic_handoff_parser = subparsers.add_parser(
        "topic-action-handoff",
        help="Return the current safe topic action or complete maker question.",
    )
    topic_handoff_parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the cached component snapshot and skip live APIs.",
    )
    resume_parser = subparsers.add_parser(
        "resume-handoff",
        help=(
            "Resolve the executable lifecycle next step and current provider "
            "handoff before any checkpoint."
        ),
    )
    resume_parser.add_argument("--executed-action", action="append", default=[])
    resume_parser.add_argument("--verified-phase", action="append", default=[])
    resume_parser.add_argument(
        "--roles-available",
        choices=("yes", "no"),
        help=(
            "Continue only after the Maker confirms the currently required "
            "roles are available."
        ),
    )
    resume_parser.add_argument(
        "--business-group-id",
        help="Stable current business-group ID returned by resume-handoff.",
    )
    resume_parser.add_argument(
        "--availability-context-sha256",
        help=(
            "Current business-group context hash returned by resume-handoff."
        ),
    )
    record_results_parser = subparsers.add_parser(
        "record-checkpoint-results",
        help=(
            "Record validated checkpoint outcomes for one lifecycle phase. "
            "The only supported way to persist phase completion; never edit "
            "lifecycle.json by hand."
        ),
    )
    record_results_parser.add_argument("--phase", required=True)
    record_results_parser.add_argument(
        "--result",
        action="append",
        default=[],
        required=True,
        metavar="CHECKPOINT_ID=STATUS",
        help="Validated checkpoint status; repeat once per emitted row.",
    )
    record_results_parser.add_argument(
        "--maker-acknowledged",
        action="append",
        default=[],
        metavar="CHECKPOINT_ID",
        help="Checkpoint whose Warning the maker explicitly confirmed.",
    )
    portal_parser = subparsers.add_parser(
        "set-portal-url",
        help=(
            "Set the exact profile Setup Configurations Portal Base URI topic "
            "value with guarded readback and rollback."
        ),
    )
    portal_parser.add_argument("--portal-url", required=True)
    portal_parser.add_argument("--yes", action="store_true")
    portal_parser.add_argument(
        "--rollback-after-verify",
        action="store_true",
        help="Restore the original value after a successful guarded readback.",
    )
    portal_confirmation_parser = subparsers.add_parser(
        "portal-url-confirmation",
        help=(
            "Normalize a Maker-supplied portal URL and return the "
            "confirmation question without changing state."
        ),
    )
    portal_confirmation_parser.add_argument("--portal-url", required=True)

    publish_parser = subparsers.add_parser(
        "publish",
        help=(
            "Compatibility entry that reports automatic ServiceNow Connect "
            "publishing is disabled."
        ),
    )
    publish_parser.add_argument("--yes", action="store_true")
    subparsers.add_parser(
        "inspect-publish",
        help="Read the current remote publish marker and component revision.",
    )
    reconcile_publish_parser = subparsers.add_parser(
        "reconcile-publish-receipt",
        help="Record maker-confirmed current publish evidence without publishing.",
    )
    reconcile_publish_parser.add_argument(
        "--expected-component-hash",
        required=True,
    )
    reconcile_publish_parser.add_argument(
        "--expected-last-published-at",
        required=True,
    )
    reconcile_publish_parser.add_argument("--yes", action="store_true")

    test_parser = subparsers.add_parser(
        "record-test",
        help="Record the maker's ServiceNow Test pane attestation.",
    )
    test_parser.add_argument(
        "--prompt-category",
        choices=tuple(
            profile.test_prompt_category
            for profile in PRODUCT_PROFILES.values()
        ),
        required=True,
    )
    test_parser.add_argument(
        "--result",
        choices=("pass", "fail", "untested", "empty"),
        required=True,
    )
    test_parser.add_argument(
        "--failure-category",
        choices=(
            "authentication",
            "permission",
            "empty-result",
            "connector",
            "unexpected",
        ),
    )
    subparsers.add_parser(
        "migrate-state",
        help="Migrate legacy Agent-ID ServiceNow state into lifecycle state.",
    )
    initialize_parser = subparsers.add_parser(
        "initialize-state",
        help="Create the first provider-owned lifecycle state after plan approval.",
    )
    initialize_parser.add_argument(
        "--contract-revision",
        type=int,
        required=True,
    )
    discover_parser = subparsers.add_parser(
        "discover-realm-target",
        help=(
            "Prove the promoted sibling realm of the recorded Dev "
            "agent, reuse the Dev tenant foundation, and check the realm."
        ),
    )
    discover_parser.add_argument("--realm", choices=("test", "prod"))
    discover_parser.add_argument(
        "--environment",
        help="Friendly environment name or Dataverse URL when discovery asks.",
    )
    discover_parser.add_argument(
        "--agent-link",
        help="Optional Copilot Studio link of the promoted agent.",
    )
    _add_realm_expectation_arguments(discover_parser)
    subparsers.add_parser(
        "realm-status",
        help="Show the active realm, targets, and stage status without APIs.",
    )
    check_realm_parser = subparsers.add_parser(
        "check-realm",
        help="Re-read the promoted realm's Connections and Runtime stages.",
    )
    check_realm_parser.add_argument(
        "--realm", choices=("test", "prod"), required=True
    )
    _add_realm_expectation_arguments(check_realm_parser)
    realm_test_parser = subparsers.add_parser(
        "record-realm-test",
        help="Record the maker's Test pane attestation for a promoted realm.",
    )
    realm_test_parser.add_argument(
        "--realm", choices=("test", "prod"), required=True
    )
    realm_test_parser.add_argument(
        "--prompt-category",
        choices=tuple(
            profile.test_prompt_category
            for profile in PRODUCT_PROFILES.values()
        ),
        required=True,
    )
    realm_test_parser.add_argument(
        "--result", choices=("pass", "fail", "untested"), required=True
    )
    realm_test_parser.add_argument(
        "--failure-category",
        choices=(
            "authentication",
            "permission",
            "empty-result",
            "connector",
            "unexpected",
        ),
    )
    realm_admin_parser = subparsers.add_parser(
        "record-realm-admin",
        help=(
            "Record an administrator reply for a destination that runs its "
            "own administrator setup, then run the checks."
        ),
    )
    realm_admin_parser.add_argument(
        "--realm", choices=("test", "prod"), required=True
    )
    realm_admin_parser.add_argument(
        "--stage", choices=("entra", "servicenow"), required=True
    )
    realm_admin_parser.add_argument("--client-id")
    realm_admin_parser.add_argument("--claim-name")
    realm_admin_parser.add_argument("--user-field")
    realm_admin_parser.add_argument("--directory-tenant-id")
    realm_admin_parser.add_argument(
        "--confirm-saved-mapping", action="store_true"
    )
    select_realm_parser = subparsers.add_parser(
        "select-realm",
        help="Switch the active realm after its target was discovered.",
    )
    select_realm_parser.add_argument(
        "--realm", choices=("dev", "test", "prod"), required=True
    )
    return parser


def _command_error_recovery(
    context: dict[str, Any],
    args: argparse.Namespace,
    exc: BaseException,
) -> dict[str, str]:
    command = str(getattr(args, "command", "") or "")
    admin_phase = str(getattr(args, "phase", "") or "")
    if command == "record-admin-phase" and admin_phase:
        command = admin_phase
    phase = (
        "preflight"
        if command
        in {
            "inspect",
            "inspect-admin-setup",
            "shared-reuse-handoff",
            "record-shared-reuse",
            "portal-reuse-handoff",
            "record-portal-reuse",
            "record-preflight",
        }
        else "entra-registration"
        if command
        in {
            "record-identity-requirement",
            "entra-registration",
        }
        or (
            command in {
                "record-identity-direct",
                "identity-direct-handoff",
            }
            and getattr(args, "stage", "") == "entra"
        )
        else "servicenow-oidc"
        if command in {"servicenow-oidc"}
        or (
            command in {
                "record-identity-direct",
                "identity-direct-handoff",
            }
            and getattr(args, "stage", "") == "servicenow"
        )
        else "credential"
        if command
        in {
            "create",
            "record-credential",
            "resolve-credential",
        }
        else "topics"
        if command
        in {
            "set-topic-state",
            "enable-all-topics",
            "rollback-topics",
            "record-topic-choice",
            "topic-action-handoff",
        }
        else "portal-url"
        if command
        in {
            "inspect-portal-url",
            "set-portal-url",
            "portal-url-confirmation",
            "portal-reuse-handoff",
            "record-portal-reuse",
        }
        else "test"
        if command == "record-test"
        else "lifecycle"
    )
    if command in {
        "preflight",
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
        "credential",
        "topics",
        "portal-url",
        "test",
    }:
        phase = command
    try:
        links = maker_portal_links(context)
    except Exception:
        links = {
            "entra": {"url": "https://entra.microsoft.com/"},
            "powerAutomateConnections": {
                "url": PORTAL_ORIGINS["prod"]["powerAutomate"]
            },
            "copilotStudioAgent": {
                "url": PORTAL_ORIGINS["prod"]["copilotStudio"]
            },
        }
    try:
        state = _load_lifecycle_state(context)
    except Exception:
        try:
            raw_state = _load_json(_lifecycle_state_path(context))
            state = raw_state if isinstance(raw_state, dict) else {}
        except Exception:
            state = {}
    setup = state.get("adminSetup")
    setup = setup if isinstance(setup, dict) else {}
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    instance_name = preflight.get("instanceName")
    phase_handoffs = setup.get("phaseHandoffs")
    phase_handoffs = (
        phase_handoffs if isinstance(phase_handoffs, dict) else {}
    )
    entra = phase_handoffs.get("entra-registration")
    entra = entra if isinstance(entra, dict) else {}
    entra_evidence = entra.get("evidence")
    entra_evidence = (
        entra_evidence if isinstance(entra_evidence, dict) else {}
    )
    client_id = entra_evidence.get("clientId")
    phase_specs = {
        "preflight": (
            "ESS Maker / Agent Developer",
            links["copilotStudioAgent"]["url"],
            (
                "Use the exact selected agent/environment/Dev realm. "
                + (
                    f"Confirmed ServiceNow instance: `{instance_name}`."
                    if instance_name
                    else (
                        "The ServiceNow admin must provide the public instance "
                        "URL; do not infer it from connection inventory."
                    )
                )
            ),
            "The exact agent target and public instance are confirmed.",
        ),
        "entra-registration": (
            "Microsoft Entra Application Administrator or higher",
            links["entra"]["url"],
            (
                f"Verified App A client ID: `{client_id}`."
                if client_id
                else (
                    "The Entra admin must return the non-secret App A "
                    "Application client ID through the protected handoff."
                )
            ),
            "The protected Entra handoff and all active App A checks are current.",
        ),
        "plugin-prerequisites": (
            "ServiceNow Admin",
            (
                f"https://{instance_name}.service-now.com/now/app-manager/"
                "home/plugin/id/com.sn_hr_core/details"
                if instance_name
                else (
                    "The exact ServiceNow instance -> All -> System "
                    "Applications -> All Available Applications -> All"
                )
            ),
            (
                "Application: Human Resources Scoped App: Core; Plugin ID: "
                "`com.sn_hr_core`; Version Details: `Installed`; confirm the "
                "installed-and-ready message."
            ),
            (
                "Application Manager shows the required plugin ID, Installed "
                "status, and ready message."
            ),
        ),
        "servicenow-oidc": (
            "ServiceNow Admin / security_admin",
            (
                f"https://{instance_name}.service-now.com/"
                if instance_name
                else "The exact ServiceNow instance supplied by its admin"
            ),
            (
                "Use one Entra-confirmed emitted claim name and the exact "
                "ServiceNow user field selected through the protected handoff. "
                "Never return an employee identifier or token value."
            ),
            "The bounded OIDC/user-mapping receipt is current.",
        ),
        "credential": (
            "ESS Maker / Agent Developer",
            links["copilotStudioAgent"]["url"]
            + " -> Settings -> Connection Settings -> ServiceNow",
            _render_connection_expected_values(
                resource_uri=(
                    str(client_id) if client_id else None
                ),
                instance_name=(
                    str(instance_name) if instance_name else None
                ),
            ),
            (
                "Fresh inventory shows one exact Connected current-maker "
                "connection and the agent's saved draft uses it."
            ),
        ),
        "topics": (
            "ESS Maker / Agent Developer",
            links["copilotStudioAgent"]["url"] + " -> Topics",
            (
                "Use the exact current ServiceNow topic inventory; preserve "
                "unrelated and customer-authored topics."
            ),
            "Required ServiceNow topic states match the current maker decision.",
        ),
        "portal-url": (
            "ESS Maker / Agent Developer with ServiceNow Admin input",
            (
                links["copilotStudioAgent"]["url"]
                + " -> Topics -> ServiceNow Setup Configurations"
            ),
            (
                "Use the exact administrator-confirmed HTTPS employee portal "
                "URL on the confirmed instance; never infer `/sp` or `/esc`."
            ),
            "The saved portal literal matches the confirmed target URL.",
        ),
        "test": (
            "ESS Maker / Agent Developer",
            links["copilotStudioAgent"]["url"] + " -> Test pane",
            (
                "Use the profile's bounded test category and record only the "
                "result/failure category; never return employee or ticket data."
            ),
            "A passing bounded result is current for the saved draft and binding.",
        ),
        "lifecycle": (
            "ESS Maker / Agent Developer",
            links["copilotStudioAgent"]["url"],
            "Use the current provider, agent, environment, and lifecycle state.",
            "The current command completes without changing unrelated phases.",
        ),
    }
    if phase == "lifecycle" and command in {
        "resume-handoff",
        "migrate-state",
    }:
        phases = state.get("phases")
        phases = phases if isinstance(phases, dict) else {}
        for candidate in (
            "preflight",
            "plugin-prerequisites",
            "entra-registration",
            "servicenow-oidc",
            "credential",
            "topics",
            "portal-url",
            "test",
        ):
            candidate_state = phases.get(candidate)
            if (
                isinstance(candidate_state, dict)
                and candidate_state.get("status") != "done"
            ):
                phase = candidate
                break
    owner, where, values, success = phase_specs[phase]
    message = str(exc)
    lowered = message.casefold()
    details = getattr(exc, "details", None)
    details = details if isinstance(details, dict) else {}
    status_code = details.get("statusCode") or details.get("httpStatus")
    category = (
        "Read throttled"
        if status_code == 429 or "429" in lowered or "throttl" in lowered
        else "Read permission"
        if status_code in {401, 403}
        or any(
            value in lowered
            for value in ("permission", "authorization", "denied")
        )
        else "Read or network error"
        if isinstance(exc, AgentBuilderError)
        or any(
            value in lowered
            for value in ("timeout", "network", "read", "unavailable")
        )
        else "Invalid or incomplete phase input"
    )
    action = (
        "Honor Retry-After when present, then rerun only this command once."
        if category == "Read throttled"
        else "Restore the minimum required access and reauthenticate if needed."
        if category == "Read permission"
        else "Restore the current read path, then rerun only this command."
        if category == "Read or network error"
        else (
            "Correct only the field or evidence identified by the error using "
            "the authoritative values above."
        )
    )
    return _recovery_handoff(
        problem=message,
        category=category,
        owner=owner,
        where=where,
        values=values,
        action=action,
        success=success,
        recheck=(
            f"Rerun only `{getattr(args, 'command', command)}`. When it "
            f"succeeds, resume at the current {phase} step; do not replay "
            "earlier completed phases."
        ),
    )


AGENT_RULES = (
    "When chatMessage is present, send it verbatim as plain Markdown before "
    "any other tool call (no code fence around it unless it already has "
    "one); never reword it, write your own checklist or a Check/Status "
    "table, or print internal fields, JSON, or file paths. Terminal output "
    "is not shown to the maker. Without chatMessage, send renderBlock.text "
    "or the ordinaryReply/recovery text verbatim instead.",
    "If endTurn is true, END YOUR TURN right after sending chatMessage: the "
    "message asks the maker to reply, return, paste, send, or act outside "
    "chat, and the maker's reply arrives as the next message. Do not read "
    "the next document or run another command before that reply. When "
    "afterReply is present, follow it once the maker replies.",
    "If endTurn is false, do NOT stop and do NOT wait: right after sending "
    "chatMessage, do exactly what nextCommand says in the same turn.",
    "When pendingCard is present, ask it with one ask_user call using "
    "pendingCard.askUserArguments exactly as given: the card title is the "
    "question, so add no body text, examples, or notes to the card; all "
    "explanation was already sent in chatMessage. Option labels stay as "
    "given (Yes/No or very short).",
    "Run every command with the launcher resolved by /setup (py -3, "
    "python3, then python), never assuming bare `python`.",
    "Never edit lifecycle.json by hand; record results with "
    "record-checkpoint-results or the matching record-* command.",
    "Never hide command output (no `*> $null`, no `| Out-Null`); read the "
    "full JSON.",
    "If you have not read src/skills/connect/shared/lifecycle-runner.md in "
    "this chat, read it now.",
)

# Wording that asks the maker to reply or act: the turn must end there.
WAIT_CUE_PATTERN = re.compile(
    r"return here|come back|tell us|let us know|\breplies\b|\breply\b|"
    r"\bpaste\b|please send|\bsend (?:back|them|us|it|that|this|the)\b|"
    r"once you have|when you have|when they|full https base url|\?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_WAIT_RENDER_KINDS = frozenset({"waiting", "error", "final"})
_WAIT_STATUS_MARKERS = ("-required", "maker-action", "input-required")


def has_wait_cue(text: str) -> bool:
    """True when maker-facing text asks the maker to reply or act."""
    return bool(WAIT_CUE_PATTERN.search(text or ""))


def _is_raw_card(value: dict[str, Any]) -> bool:
    return (
        isinstance(value.get("header"), str)
        and isinstance(value.get("question"), str)
        and isinstance(value.get("allowFreeformInput"), bool)
    )


def _pending_cards(value: Any) -> list[dict[str, Any]]:
    """Canonical card questions this output asks, in order, without duplicates."""
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if _is_raw_card(node):
                found.append(node)
                return
            for key, item in node.items():
                if key == "canonicalQuestion" or str(key).startswith("manual"):
                    continue
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in found:
        key = json.dumps([card["header"], card["question"]])
        if key not in seen:
            seen.add(key)
            unique.append(card)
    return unique


_CLAIM_CONFIRMATION_AFTER_REPLY = (
    "When the maker returns, any message means they want to continue. "
    "Do not ask a Yes/No question. Record only the administrators' "
    "non-sensitive reply with the existing record-identity-direct "
    "commands; a proposed name, a name alone or a vague \"done\" is "
    "not confirmation, so keep waiting and ask only for what is "
    "still missing."
)


def claim_confirmation_handoff(
    *,
    custom_claim: bool = False,
    claim_name_given: bool = False,
    servicenow_confirmed: bool = False,
) -> dict[str, Any]:
    """Fixed reply for an identifier the Entra administrator has not confirmed.

    The Part 4 custom-claim instructions are sent only when the maker says a
    custom claim is wanted. The maker is never asked to pick a mapping, invent
    a claim name or fall back to email; only the missing confirmations are
    requested.
    """
    if not custom_claim:
        return {
            "status": "claim-confirmation-required",
            "decision": "claim-confirmation-required",
            "recordsNothing": True,
            "renderBlock": {
                "kind": "waiting",
                "text": (
                    "We need your Entra administrator to confirm which claim "
                    "the app sends for ServiceNow before we continue.\n\n"
                    "Ask them to reply with the exact claim name. Don't send "
                    "employee identifiers or secrets.\n\n"
                    "We'll keep the Client ID and tenant ID already supplied."
                ),
            },
            "afterReply": _CLAIM_CONFIRMATION_AFTER_REPLY,
        }
    paragraphs = [
        "We need the Entra administrator to confirm the custom claim before "
        "ServiceNow can use it to identify employees."
    ]
    if claim_name_given:
        paragraphs.append(
            "Ask them to complete the custom-claim work in Part 4 of their "
            "instructions. Bring back confirmation that the setup is complete, "
            "including the appropriate format and populated source attribute "
            "for every intended employee. You don't need to resend the claim "
            "name."
        )
    else:
        paragraphs.append(
            "Ask them to complete the custom-claim work in Part 4 of their "
            "instructions. Bring back the exact configured claim name and "
            "confirmation that the setup is complete, including the "
            "appropriate format and populated source attribute for every "
            "intended employee."
        )
    if not servicenow_confirmed:
        paragraphs.append(
            "Then ask your ServiceNow administrator to confirm that the "
            "supported configuration is saved, with the matching User Claim "
            "and User Field. Don't send employee identifiers or secrets."
        )
    paragraphs.append("We'll keep the Client ID and tenant ID already supplied.")
    return {
        "status": "claim-confirmation-required",
        "decision": "claim-confirmation-required",
        "recordsNothing": True,
        "renderBlock": {"kind": "waiting", "text": "\n\n".join(paragraphs)},
        "afterReply": _CLAIM_CONFIRMATION_AFTER_REPLY,
    }


_STANDARD_USER_CLAIMS = frozenset({"email", "upn"})

_V2_METADATA_URL_RE = re.compile(
    r"^https://login\.microsoftonline\.com/"
    r"(?P<tenant>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"/v2\.0/\.well-known/openid-configuration/?$",
    re.IGNORECASE,
)

_METADATA_URL_AFTER_REPLY = (
    "When the maker returns, any message means they want to continue. Do not "
    "ask a Yes/No question. Record only the administrators' non-sensitive "
    "reply with the existing record-identity-direct commands, then recheck "
    "the affected setup before the maker repeats the request in the Test "
    "pane. Run this diagnosis only when the maker reported the actual "
    "metadata URL; never infer it from a generic failure."
)


_SERVICE_AREAS_AFTER_REPLY = (
    "When the maker returns, any message means they want to continue. Do not "
    "ask a Yes/No question. Record only the administrator's non-sensitive "
    "reply with the existing commands, rerun the recheck of the affected "
    "setup, then ask the maker to repeat the HR request in the Test pane and "
    "tell us whether the service areas appear. Never claim the employee's "
    "roles were checked, never assign a role, and never treat the empty list "
    "alone as proof of the cause."
)

_HR_ACCESS_ROLES = (
    "`sn_hr_core.basic`, `sn_hr_core.manager`, or `sn_hr_core.admin`"
)


def empty_service_areas_handoff(realm: str = "dev") -> dict[str, Any]:
    """Fixed reply when the maker reports an empty HR service-area list.

    Used only for the HR agent. Nothing is recorded, no role is checked or
    assigned, and the empty list alone is not treated as proof of the cause.
    """
    if ACTIVE_PROFILE.key != "hrsd":
        return {
            "status": "no-diagnosis",
            "decision": "not-an-hr-agent",
            "recordsNothing": True,
            "note": (
                "HR service areas exist only for the HR agent, so this "
                "diagnosis does not apply. Continue the normal flow."
            ),
        }
    if realm == "dev":
        text = (
            "An empty HR service-area list can occur when the signed-in "
            "employee doesn't have the required ServiceNow HR access.\n\n"
            "Ask your ServiceNow administrator to review the access for the "
            "account used in this request through your organization's normal "
            "process. The administrator instructions identify the applicable "
            f"roles: {_HR_ACCESS_ROLES}.\n\n"
            "Return with their non-sensitive reply after any required access "
            "work is complete. We'll recheck the applicable setup. Then "
            "repeat the HR request in this agent's Test pane and tell us "
            "whether the service areas appear."
        )
    else:
        text = (
            "The HR service-area list is empty. Employees using HR scenarios "
            f"need one of the ServiceNow roles {_HR_ACCESS_ROLES}.\n\n"
            "Ask your ServiceNow administrator to review the access for the "
            "account used in this request. This skill doesn't check or "
            "assign those roles.\n\n"
            "Bring back their non-sensitive reply after any required access "
            "work is complete. We'll recheck the applicable setup before you "
            "repeat the request in the destination agent's Test pane."
        )
    return {
        "status": "service-access-review-required",
        "decision": "service-access-review-required",
        "recordsNothing": True,
        "renderBlock": {"kind": "waiting", "text": text},
        "afterReply": _SERVICE_AREAS_AFTER_REPLY,
    }


_TARGET_CHANGES = ("environment", "agent", "instance", "tenant", "user")
_TARGET_CHANGE_AFTER_REPLY = (
    "Send the message above, then follow nextCommand so the permission and "
    "applicability checks run again. For a promoted destination run "
    "discover-realm-target first; it proves the maker's permission there "
    "and reuses only setup information that still applies. Do not reuse "
    "evidence from the earlier target until those checks pass. Nothing is "
    "recorded by this command."
)
_FRIENDLY_NAME_BLOCKED_RE = re.compile(
    r"https?://|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def target_change_handoff(
    context: dict[str, Any],
    change: str,
    target: str | None = None,
) -> dict[str, Any]:
    """Fixed notice when the target, user, instance, or tenant changes.

    The message names the agent and environments the maker knows. It records
    nothing; earlier evidence is reused only after the permission and
    applicability checks pass.
    """
    name = (target or "").strip()
    if change in {"environment", "agent"} and not name:
        raise ServiceNowConnectError(
            "Pass --target with the new environment or agent name."
        )
    if name and _FRIENDLY_NAME_BLOCKED_RE.search(name):
        raise ServiceNowConnectError(
            "Pass the friendly name the maker used, not an ID or a URL."
        )
    agent = _display_agent_name(context)
    environment = _recorded_environment_name(context)
    if change == "environment":
        subject = f"{agent} in {name}"
        earlier = environment or "the earlier environment"
        headline = "That changes the target environment."
    elif change == "agent":
        subject = f"{name} in {environment}" if environment else name
        earlier = agent
        headline = "That changes the target agent."
    else:
        subject = f"{agent} in {environment}" if environment else agent
        headline, earlier = {
            "instance": (
                "That changes the ServiceNow instance.",
                "the earlier instance",
            ),
            "tenant": ("That changes the tenant.", "the earlier tenant"),
            "user": (
                "That changes the signed-in user.",
                "the earlier account",
            ),
        }[change]
    text = (
        f"{headline} We'll check your permission for **{subject}** and which "
        "earlier setup information still applies.\n\n"
        f"We won't reuse evidence from {earlier} without those checks."
    )
    return {
        "status": "target-change-notice",
        "decision": "revalidate-target",
        "recordsNothing": True,
        "change": change,
        "renderBlock": {"kind": "info", "text": text},
        "afterReply": _TARGET_CHANGE_AFTER_REPLY,
    }


_EXISTING_IDENTITY_KINDS: dict[str, dict[str, str]] = {
    "knowledge": {
        "along": "Knowledge",
        "uses": "ServiceNow Knowledge",
        "itself": "The Knowledge connection itself isn't the connection ESS needs.",
        "connector": (
            "The ServiceNow Knowledge connection is a different connector "
            "and can't replace it."
        ),
        "that_is": "That is the Knowledge connector",
        "leave": "Leave the Knowledge connector unchanged.",
        "retest": "ServiceNow Knowledge wasn't retested.",
    },
    "sso": {
        "along": "single sign-on",
        "uses": "ServiceNow single sign-on",
        "itself": (
            "The existing single sign-on setup itself isn't the connection "
            "ESS needs."
        ),
        "connector": (
            "A connection created for single sign-on is a different "
            "connector and can't replace it."
        ),
        "that_is": "That is a different connector",
        "leave": "Leave that connector unchanged.",
        "retest": "Existing single sign-on wasn't retested.",
    },
    "graph": {
        "along": "the Microsoft Graph connector",
        "uses": "the Microsoft Graph connector for ServiceNow",
        "itself": (
            "The Microsoft Graph connector itself isn't the connection ESS "
            "needs."
        ),
        "connector": (
            "The Microsoft Graph connector is a different connector and "
            "can't replace it."
        ),
        "that_is": "That is the Microsoft Graph connector",
        "leave": "Leave the Microsoft Graph connector unchanged.",
        "retest": "The Microsoft Graph connector wasn't retested.",
    },
}

_EXISTING_IDENTITY_SITUATIONS = (
    "disclosure",
    "setup-incomplete",
    "setup-complete",
    "entra-incomplete",
    "client-id-only",
    "two-client-ids",
    "servicenow-incomplete",
    "servicenow-fields-unnamed",
    "coexistence-conflict",
    "replace-configuration",
    "waiting",
    "resumed",
    "resolution-missing-mapping",
    "different-registration",
    "custom-claim",
    "knowledge-connector",
    "existing-connection",
    "connection-disconnected",
    "missing-consent",
    "metadata-url",
    "blocked-finish",
    "hr-prerequisite-self-confirmed",
)

_EXISTING_AFTER_REPLY_CONTINUE = (
    "When the maker returns, any message means they want to continue. Do "
    "not ask a Yes/No question. Record only the administrators' "
    "non-sensitive reply with the existing record-identity-direct "
    "commands (never secrets or employee identifiers). If a custom claim "
    "changed, run claim-confirmation-handoff --custom-claim (add "
    "--claim-name-given when the name was supplied) and ask only for the "
    "missing confirmations. Do not change an existing OIDC configuration "
    "serving SSO or the Microsoft Graph connector. Recheck the affected "
    "setup with resume-handoff before continuing."
)
_EXISTING_AFTER_REPLY_CONNECTION = (
    "When the maker returns and names the connection they used, record it "
    "with the existing connection commands and continue with "
    "resume-handoff so this agent's connection and link are rechecked. Do "
    "not change a shared connection or the shared sign-in configuration."
)
_EXISTING_AFTER_REPLY_VALUES = (
    "When the maker replies, record the confirmed values with the existing "
    "record-identity-direct commands, never secrets or employee "
    "identifiers, and continue with resume-handoff. Ask only for what is "
    "still missing."
)
_EXISTING_AFTER_REPLY_SETUP = (
    "Run basic ADK setup first. When it completes, continue with the "
    "setup-complete situation of this command, then resume-handoff."
)
_EXISTING_AFTER_REPLY_PREREQUISITE = (
    "When the maker replies, record the administrator's reply with the "
    "existing plugin-prerequisite commands and continue with "
    "resume-handoff."
)


def _existing_identity_kind(state: dict[str, Any] | None) -> str | None:
    marker = state.get("existingIdentity") if isinstance(state, dict) else None
    kind = marker.get("kind") if isinstance(marker, dict) else None
    return kind if kind in _EXISTING_IDENTITY_KINDS else None


def _state_instance_name(state: dict[str, Any] | None) -> str | None:
    setup = state.get("adminSetup") if isinstance(state, dict) else None
    preflight = setup.get("preflight") if isinstance(setup, dict) else None
    instance = (
        preflight.get("instanceName") if isinstance(preflight, dict) else None
    )
    if not isinstance(instance, str) or not instance.strip():
        return None
    try:
        return normalize_instance_name(instance)
    except ServiceNowConnectError:
        return None


def _existing_identity_purpose() -> str:
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    return f"create and track {copy_['audience']} {copy_['records']}"


def _existing_identity_opening(
    context: dict[str, Any],
    state: dict[str, Any] | None,
    kind: str,
) -> str:
    """Spec S3 step 1: the opening for a maker who reuses existing sign-in."""
    environment = _recorded_environment_name(context)
    in_bold = f" in **{environment}**" if environment else ""
    in_plain = f" in {environment}" if environment else ""
    lines = [
        f"We'll connect **{_spec_agent_name()}**{in_bold} so employees can "
        f"{_DEV_OPENING_PURPOSE[ACTIVE_PROFILE.key]}.",
        "",
        _existing_identity_notice(kind),
    ]
    instance = _state_instance_name(state)
    if instance:
        lines.extend(
            ["", f"**ServiceNow instance:** https://{instance}.service-now.com"]
        )
    lines.extend(
        [
            "",
            "We're checking whether your account can configure this agent"
            f"{in_plain} before setup begins.",
        ]
    )
    return "\n".join(lines)


def _existing_identity_notice(kind: str) -> str:
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    words = _EXISTING_IDENTITY_KINDS[kind]
    return (
        "Your administrators will confirm whether ESS can use the existing "
        f"sign-in setup alongside {words['along']}. {words['itself']}\n\n"
        "We won't change the shared sign-in configuration. After "
        "administrator confirmation, we'll configure the ESS connection and "
        f"test {copy_['article']} {copy_['audience']} request with your "
        "account."
    )


def _existing_identity_lead_in(
    stage: str,
    kind: str,
    *,
    claim_name: str | None = None,
) -> str:
    """Spec S3 steps 2, 4 and 5: lead-ins before the compatibility reviews."""
    if stage == "entra":
        text = (
            "Send this message to your Microsoft Entra administrator. It "
            "asks them to confirm compatibility with your ServiceNow "
            "administrator before setup proceeds.\n\n"
            "When they reply, paste their confirmation here without "
            "secrets. They'll identify the registration and settings ESS "
            "should use; you don't need to interpret them."
        )
        if ACTIVE_PROFILE.requires_hr_core:
            return (
                "The HR prerequisite is confirmed. Next, send the Entra "
                "handoff so your administrators can confirm a compatible "
                f"sign-in setup for ESS.\n\n{text}"
            )
        return text
    if claim_name and claim_name.casefold() not in {"email", "upn"}:
        confirmed = (
            "The Entra administrator has confirmed the registration for "
            "ESS, including its Client ID, tenant ID, and custom claim "
            f"`{claim_name}`."
        )
    else:
        confirmed = (
            "The Entra administrator has confirmed the registration for "
            "ESS, including its Client ID, tenant ID, and standard "
            f"{(claim_name or 'email').casefold()} claim."
        )
    return (
        f"{confirmed}\n\n"
        "Next, send this message to your ServiceNow administrator to "
        "confirm the saved sign-in setup and employee matching for ESS.\n\n"
        "It includes the Entra values just confirmed. Paste their reply "
        "here without secrets."
    )


_COEXISTENCE_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/declarative-agent-servicenow-hr-it"
    "#coexistence-with-the-microsoft-graph-connector-for-servicenow"
)
_KNOWLEDGE_GUIDANCE_LINK = (
    "https://learn.microsoft.com/en-us/microsoftsearch/"
    "servicenow-knowledge-connector"
)
_ESS_INTEGRATION_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/declarative-agent-servicenow-hr-it"
)
_CONNECTOR_SETUP_LINK = (
    "https://learn.microsoft.com/en-us/connectors/service-now/"
    "#how-to-set-up-a-servicenow-power-platform-connection-that-uses-"
    "microsoft-entra-id"
)
_JWT_CLAIMS_LINK = (
    "https://learn.microsoft.com/en-us/entra/identity-platform/"
    "jwt-claims-customization"
)
_EMIT_IDENTITY_KEY_LINK = _ESS_INTEGRATION_LINK + (
    "#configure-microsoft-entra-to-emit-the-identity-key"
)


def _existing_entra_packet(
    context: dict[str, Any],
    kind: str,
    instance_name: str,
) -> str:
    """Spec S3 step 3: compatibility review first, setup steps as reference."""
    words = _EXISTING_IDENTITY_KINDS[kind]
    url = f"https://{instance_name}.service-now.com"
    paragraphs = [
        f"We're connecting **{_spec_agent_name()}** to **{url}**, so "
        f"employees can {_existing_identity_purpose()} while signed in as "
        "themselves.",
        f"The maker reports that the organization already uses "
        f"{words['uses']}. Please confirm whether the identity setup can "
        "support ESS alongside the existing integration.",
        "This requires an app registration in Microsoft Entra ID that "
        "ServiceNow trusts to identify users. You need the **Global "
        "Administrator** or **Cloud Application Administrator** role.",
        "**Review compatibility before setup**\n\n"
        "1. Coordinate with the ServiceNow administrator to identify the "
        "registration and shared sign-in configuration relevant to this "
        "instance.\n"
        "2. Review the user claims, API scope, and authorized Microsoft "
        "ServiceNow connector described below. Decide whether the existing "
        "setup satisfies the ESS requirements alongside its current uses.\n"
        "3. If the requirements are already satisfied, confirm reuse "
        "without repeating completed steps. If work is missing or a "
        "conflict remains, agree on a supported resolution with the "
        "ServiceNow administrator before proceeding.",
        "ServiceNow allows only one OIDC configuration per Microsoft Entra "
        "tenant. Decide whether the existing identity setup can be reused "
        "through the supported ESS path. Do not treat the setup reference "
        "below as a request to overwrite an existing configuration serving "
        "SSO or the Microsoft Graph connector.",
        "If the existing configuration creates a conflict, resolve it "
        "manually with the ServiceNow administrator. The ESS connection "
        "skill cannot diagnose or resolve that conflict.",
        "Review [coexistence with the Microsoft Graph connector for "
        f"ServiceNow]({_COEXISTENCE_LINK}).",
        "**Please send back:** confirmation that the registration supports "
        "this ESS setup alongside the existing integration, the "
        "Application (client) ID, Directory (tenant) ID, and custom claim "
        "name if applicable. State whether the configuration was reused or "
        "newly created.",
        "**If compatibility is unresolved:** report what remains "
        "unresolved instead of confirming completion.",
        "**Do not send passwords, client secrets, tokens, or certificate "
        "material.**",
        "**Setup reference\u2014only for administrator-agreed work**",
        "These instructions describe the required setup; they are not a "
        "request to create or overwrite shared configuration. Use them only "
        "for work you and the ServiceNow administrator determine is needed "
        "and supported after compatibility is resolved.",
        "**Part 1: Register the app**\n\n"
        "1. Sign in to the [Microsoft Entra admin center]"
        "(https://entra.microsoft.com).\n"
        "2. Go to **App registrations > New registration**.\n"
        "3. Enter a purpose-specific name, such as **ESS ServiceNow "
        "sign-in**. Keep the default account type and leave **Redirect "
        "URI** empty.\n"
        "4. Select **Register**.\n"
        "5. On **Overview**, copy the **Application (client) ID** and "
        "**Directory (tenant) ID**.",
        "**Part 2: Add user claims**\n\n"
        "1. Select **Token configuration > Add optional claim**.\n"
        "2. Select token type **Access**, then select **aud**, **email**, "
        "and **upn**.\n"
        "3. Select **Add**. If prompted to enable Microsoft Graph email "
        "and profile permissions, select the check box and select **Add**.",
        "**Part 3: Allow the Microsoft ServiceNow connector to sign users "
        "in**\n\n"
        "1. Select **Expose an API**.\n"
        "2. Next to **Application ID URI**, select **Add**. Keep the "
        "generated default URI\u2014`api://` followed by this app's Client "
        "ID\u2014and select **Save**.\n"
        "3. Select **Add a scope**. Set:\n"
        "   - **Scope name:** `user_impersonation`\n"
        "   - **Who can consent:** Admins and users\n"
        "   - **Display names and descriptions:** wording identifying "
        "ServiceNow access, such as **Access ServiceNow**\n"
        "4. Select **Add scope**.\n"
        "5. Select **Add a client application**. Enter Microsoft's "
        "ServiceNow connector Client ID: "
        "`c26b24aa-7874-4e06-ad55-7d06b1f79b63`.\n"
        "6. Select the `user_impersonation` scope and select **Add "
        "application**.",
        "**Part 4: Only if ServiceNow identifies employees by something "
        "other than email or UPN**\n\n"
        "Coordinate the identifier with the ServiceNow administrator.\n\n"
        "1. Ensure the identifier\u2014for example, an employee or payroll "
        "ID\u2014is populated in a Microsoft Entra user attribute for every "
        "employee who will use ESS with ServiceNow.\n"
        "2. Configure the app to emit that attribute as a claim, "
        f"following [Configure Microsoft Entra to emit the identity key]"
        f"({_EMIT_IDENTITY_KEY_LINK}) and [Customize JWT claims]"
        f"({_JWT_CLAIMS_LINK}).\n"
        "3. Use a claim format appropriate to the identifier rather than "
        "the default email format.\n"
        "4. If Entra returns an error after adding the claim, follow the "
        "guidance for `acceptMappedClaims` on single-tenant apps or a "
        "custom signing key.",
        f"References: [ESS ServiceNow integration]({_ESS_INTEGRATION_LINK}) "
        f"and [ServiceNow connector setup]({_CONNECTOR_SETUP_LINK}).",
    ]
    return "\n\n".join(paragraphs)


def _existing_servicenow_packet(
    context: dict[str, Any],
    kind: str,
    *,
    instance_name: str,
    client_id: str,
    tenant_id: str,
    claim_name: str,
) -> str:
    """Spec S3 step 5: confirm the saved setup; setup steps are reference."""
    words = _EXISTING_IDENTITY_KINDS[kind]
    url = f"https://{instance_name}.service-now.com"
    custom = (
        f"`{claim_name}`"
        if claim_name.casefold() not in {"email", "upn"}
        else f"none; standard {claim_name.casefold()} claim confirmed"
    )
    hr_step = (
        "\n8. Employees who use HR scenarios need one of the roles "
        "`sn_hr_core.basic`, `sn_hr_core.manager`, or `sn_hr_core.admin`."
        if ACTIVE_PROFILE.requires_hr_core
        else ""
    )
    paragraphs = [
        f"We're connecting **{_spec_agent_name()}** to **{url}**, so "
        f"employees can {_existing_identity_purpose()} while signed in as "
        "themselves.",
        f"The maker reports that the organization already uses "
        f"{words['uses']}. Please confirm that the saved sign-in setup and "
        "employee mapping can support ESS alongside the existing "
        "integration.",
        "ServiceNow needs to trust Microsoft Entra sign-in and match each "
        "employee to their ServiceNow user record. You need the `admin` or "
        "`security_admin` role.",
        "**Entra values confirmed for this ESS setup**\n\n"
        f"- **Client ID:** `{client_id}`\n"
        f"- **Tenant ID:** `{tenant_id}`\n"
        f"- **Custom claim:** {custom}",
        "**Review compatibility before setup**\n\n"
        "1. Review the existing OIDC configuration against the Entra "
        "values confirmed for ESS.\n"
        "2. Confirm the User Claim and User Field that match the signed-in "
        "employee to their ServiceNow user record. Do not infer this "
        f"mapping from {words['along']} working.\n"
        "3. If the saved configuration satisfies the ESS requirements "
        "alongside its existing uses, confirm reuse without repeating "
        "completed steps.",
        "**Preserve the existing configuration**\n\n"
        "ServiceNow allows only one OIDC configuration per Microsoft Entra "
        "tenant. If an existing configuration serves SSO or the Microsoft "
        "Graph connector, **do not change it**.\n\n"
        "Coordinate with the Entra administrator to decide whether the "
        "existing setup can be reused. If it cannot support the ESS path "
        "without a conflict, resolve that manually before returning setup "
        "confirmation to the maker. The ESS connection skill will not "
        "change or resolve the existing configuration.\n\n"
        f"Review [coexistence guidance]({_COEXISTENCE_LINK}) and "
        f"[ServiceNow Knowledge connector guidance]({_KNOWLEDGE_GUIDANCE_LINK}).",
        "**Please send back:** confirmation that the configuration is saved "
        "and supports this ESS setup alongside the existing integration, "
        "the **User Claim**, and the **User Field**. State whether the "
        "configuration was reused or newly created.",
        "**If compatibility is unresolved:** report what remains "
        "unresolved instead of confirming completion.",
        "**Do not send secrets.**",
        "**Setup reference\u2014only for administrator-agreed work**",
        "These describe the supported configuration. Do not apply them as "
        "changes to an existing OIDC configuration serving SSO or the "
        "Graph connector.",
        f"1. Sign in to **{url}**.\n"
        "2. From the profile menu, select **Elevate role**, select "
        "`security_admin`, and select **Update**. If the **New** button is "
        "missing later, check that the role is elevated.\n"
        "3. Go to **All**, search for **OAuth**, and select **System OAuth "
        "> Application Registry**.\n"
        "4. Select **New > Configure an OIDC provider to verify ID "
        "tokens**.\n"
        "5. Complete the application registry form:\n"
        "   - **Name:** a purpose-specific name, such as **ESS Microsoft "
        "Entra ID**\n"
        f"   - **Client ID:** `{client_id}`\n"
        "   - **Client Secret:** any value; this field isn't used for this "
        "configuration. Do not return it to the maker.\n"
        "   - **Scope Restriction:** Broadly scoped\n"
        "6. Beside **OAuth OIDC Provider Configuration**, select the "
        "search icon, then **New**. Set:\n"
        "   - **OIDC Provider:** a name for this tenant, such as "
        "**Microsoft Entra ID \u2014 <your organization>**\n"
        "   - **OIDC Metadata URL:** "
        f"`https://login.microsoftonline.com/{tenant_id}/.well-known/"
        "openid-configuration`\n"
        "   - **OIDC Configuration Cache Life Span:** `120`\n"
        "   - **Application:** Global, if shown\n"
        "   - **User Claim:** `email` or `upn`, whichever matches how "
        "ServiceNow user records identify employees. If a custom "
        "identifier is required, coordinate its confirmed claim with the "
        "Entra administrator first.\n"
        "   - **User Field:** the user-record field holding that exact "
        "identifier\u2014for example, **Email** for the `email` claim\n"
        "   - **Enable JTI claim verification:** off\n"
        "7. Select **Submit**. Back on the application registry form, "
        "confirm that the configuration is selected and select "
        f"**Submit**.{hr_step}",
        "**Important:** Do not use the metadata URL containing `/v2.0` "
        "from Entra's Endpoints page.",
        f"References: [ESS ServiceNow integration]({_ESS_INTEGRATION_LINK}) "
        f"and [ServiceNow connector setup]({_CONNECTOR_SETUP_LINK}).",
    ]
    return "\n\n".join(paragraphs)


def _existing_credential_lead_in(state: dict[str, Any]) -> str:
    mapping = state.get("evidence", {}).get("identityMapping")
    claim = field = None
    if (
        isinstance(mapping, dict)
        and mapping.get("serviceNowAdministratorConfirmed") is True
    ):
        claim = mapping.get("tokenClaimName")
        field = mapping.get("serviceNowUserField")
    if isinstance(claim, str) and claim and isinstance(field, str) and field:
        return (
            "Your ServiceNow administrator has confirmed that the saved "
            f"setup supports ESS, with User Claim `{claim}` and User Field "
            f"**{field}**.\n\n"
        )
    return ""


def _existing_connection_guidance(
    context: dict[str, Any],
    state: dict[str, Any],
    kind: str,
    *,
    client_id: str | None,
    instance_name: str,
) -> str:
    """Spec S3 steps 6-7: select or create the ESS connection."""
    audience = _product_audience()
    words = _EXISTING_IDENTITY_KINDS[kind]
    return (
        _existing_credential_lead_in(state)
        + "Next, select or create a ServiceNow connection for "
        f"{_spec_agent_name()}. We'll then configure and test this agent "
        f"with your real {audience} data.\n\n"
        "Use a supported ESS ServiceNow connection if one is available; "
        f"otherwise, create one. {words['connector']}\n\n"
        "In Copilot Studio:\n\n"
        f"1. Open **{_display_agent_name(context)}** in "
        f"**{_display_environment_name(context)}**.\n"
        "2. Go to **Settings > Connection Settings > ServiceNow > "
        "Connect**.\n"
        "3. Select a supported ESS ServiceNow connection available for "
        "this agent, or select **Create new connection**.\n"
        "4. For a new connection, use:\n"
        "   - **Authentication type:** Microsoft Entra ID User Login\n"
        f"   - **Resource URI:** `{client_id or 'not yet confirmed'}`\n"
        f"   - **Instance name:** `{instance_name}`\n\n"
        "Return here and tell us which connection you used. You don't need "
        "to resend the administrator replies."
    )


def _second_agent_reuse(
    context: dict[str, Any],
    state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Spec S2: the other ServiceNow agent whose shared setup this run reuses.

    Returns None for the first agent, for a same-product agent, and when the
    existing-identity marker is set (the S3 wording owns that case).
    """
    if _existing_identity_kind(state):
        return None
    for source in _other_agent_reuse_sources(context, state):
        profile = source["profile"]
        if profile.key == ACTIVE_PROFILE.key:
            continue
        other_state = source["state"]
        setup = other_state.get("adminSetup")
        handoff = _completed_handoff(
            setup if isinstance(setup, dict) else {}, "entra-registration"
        )
        client_id = None
        raw_client_id = (
            handoff["evidence"].get("clientId") if handoff else None
        )
        if raw_client_id:
            try:
                client_id = normalize_client_id(str(raw_client_id))
            except ServiceNowConnectError:
                client_id = None
        evidence = other_state.get("evidence")
        mapping = (
            evidence.get("identityMapping")
            if isinstance(evidence, dict)
            else None
        )
        claim = field = None
        if isinstance(mapping, dict):
            raw_claim = mapping.get("tokenClaimName")
            raw_field = mapping.get("serviceNowUserField")
            if isinstance(raw_claim, str) and _SAFE_IDENTITY_NAME.fullmatch(
                raw_claim
            ):
                claim = raw_claim
            if isinstance(raw_field, str) and _SAFE_USER_FIELD.fullmatch(
                raw_field
            ):
                field = raw_field
        return {
            "audience": "HR" if profile.key == "hrsd" else "IT",
            "clientId": client_id,
            "claimName": claim,
            "userField": field,
        }
    return None


def _second_agent_audience(
    context: dict[str, Any],
    state: dict[str, Any] | None,
) -> str | None:
    reuse = _second_agent_reuse(context, state)
    return reuse["audience"] if reuse else None


def _second_agent_names(reuse: dict[str, Any]) -> tuple[str, str]:
    """Other agent's audience and this run's, from the single resolver."""
    return reuse["audience"], _product_audience()


def _second_agent_packet_tail(packet: str, marker: str) -> str:
    """The setup steps of an existing packet, from the marker onward."""
    tail = packet[packet.index(marker):]
    for old, new in (
        (
            "Coordinate the identifier with the ServiceNow administrator.",
            "Coordinate the identifier with your ServiceNow administrator.",
        ),
        ("Configure the app to emit", "Configure this app to emit"),
        (
            "whichever matches how ServiceNow user records",
            "whichever matches how your ServiceNow user records",
        ),
    ):
        tail = tail.replace(old, new)
    return tail


def _second_agent_claim_label(claim: str | None) -> str:
    if claim and claim.casefold() not in {"email", "upn"}:
        return f"custom claim `{claim}`"
    return f"standard {(claim or 'email').casefold()} claim"


def _second_agent_entra_lead_in(reuse: dict[str, Any]) -> str:
    """Spec S2 step 2: the Entra handoff lead-in for the second agent."""
    other, audience = _second_agent_names(reuse)
    prefix = (
        "The HR prerequisite is confirmed. "
        if ACTIVE_PROFILE.requires_hr_core
        else ""
    )
    return (
        f"{prefix}{other} is already using ServiceNow. Your administrators "
        "still need to confirm that the shared sign-in setup can also serve "
        f"{audience}. This doesn't necessarily mean creating or "
        "changing anything.\n\n"
        "Send this message to your Microsoft Entra administrator. It "
        f"includes the earlier {other} values for review.\n\n"
        "When they reply, paste their confirmation here without secrets. "
        "They'll coordinate reuse with your ServiceNow administrator; you "
        "don't need to interpret the settings."
    )


def _second_agent_servicenow_lead_in(
    reuse: dict[str, Any],
    claim_name: str | None,
) -> str:
    """Spec S2 step 4: acknowledge Entra, then ask for the ServiceNow review."""
    other, audience = _second_agent_names(reuse)
    return (
        f"The Entra administrator has confirmed that {audience} can use the "
        "existing registration, including its Client ID, tenant ID, and "
        f"{_second_agent_claim_label(claim_name)}.\n\n"
        "Next, send this message to your ServiceNow administrator to "
        f"confirm the saved sign-in setup and employee matching for "
        f"{audience}.\n\n"
        "It includes the Entra values just confirmed and the earlier "
        f"{other} mapping for review. Paste their reply here without "
        "secrets."
    )


def _second_agent_packet_intro(
    reuse: dict[str, Any],
    url: str,
) -> str:
    return (
        f"Employee Self-Service {reuse['audience']} already uses "
        f"**{url}**. We're adding **{_spec_agent_name()}** so employees can "
        f"{_existing_identity_purpose()} while signed in as themselves."
    )


def _second_agent_entra_packet(
    context: dict[str, Any],
    reuse: dict[str, Any],
    instance_name: str,
) -> str:
    """Spec S2 step 3: review the shared registration before any setup."""
    other, audience = _second_agent_names(reuse)
    url = f"https://{instance_name}.service-now.com"
    tenant_id = _normalize_directory_tenant_id(
        context["environment"]["tenant_id"]
    )
    values = []
    if reuse["clientId"]:
        values.append(f"- **Client ID:** `{reuse['clientId']}`")
    values.append(f"- **Tenant ID:** `{tenant_id}`")
    if reuse["claimName"]:
        claim = reuse["claimName"]
        values.append(
            "- **Claim setup:** standard email claim; no custom claim"
            if claim.casefold() in {"email", "upn"}
            else f"- **Claim setup:** custom claim `{claim}`"
        )
    base = _existing_entra_packet(
        context, next(iter(_EXISTING_IDENTITY_KINDS)), instance_name
    )
    paragraphs = [
        _second_agent_packet_intro(reuse, url),
        f"Please confirm whether the existing ESS app registration can also "
        f"serve {audience}. ServiceNow needs an app registration in "
        "Microsoft Entra ID that it can trust to identify users. You need "
        "the **Global Administrator** or **Cloud Application "
        "Administrator** role.",
        f"**Earlier {other} values\u2014review before using for "
        f"{audience}**\n\n" + "\n".join(values),
        f"These are the values confirmed for {other}, not yet confirmed for "
        f"{audience}.",
        "**Review the existing setup first**\n\n"
        "1. Coordinate with your ServiceNow administrator to confirm "
        f"whether this registration can serve {audience} on the same "
        "instance.\n"
        "2. Review the user claims, API scope, and authorized Microsoft "
        "ServiceNow connector described in the setup instructions below. "
        "Confirm which requirements the existing registration already "
        "satisfies.\n"
        "3. Confirm the Client ID, tenant ID, and custom claim name if "
        f"applicable for {audience}. If the existing setup meets the "
        "requirements, reuse it without repeating completed steps or "
        "creating another registration.",
        "ServiceNow allows only one OIDC configuration per Microsoft Entra "
        "tenant. If an app registration already supports ServiceNow "
        "Knowledge or single sign-on, coordinate with the ServiceNow "
        "administrator before creating another one.",
        "Review [coexistence with the Microsoft Graph connector for "
        f"ServiceNow]({_COEXISTENCE_LINK}).",
        "**Please send back:** confirmation whether the registration can "
        f"serve {audience}, the Application (client) ID, Directory "
        "(tenant) ID, and custom claim name if applicable. State whether "
        "the configuration was reused or newly created. If reuse is "
        "unresolved, tell us what remains to be agreed.",
        "**Do not send passwords, client secrets, tokens, or certificate "
        "material.**",
        "**Setup instructions\u2014only for work you determine is "
        "needed**",
        "You and the ServiceNow administrator decide which work is missing "
        "and agree on any changes before proceeding, accounting for "
        f"{other} and other existing uses. Do not repeat completed steps "
        f"solely to add {audience}.",
        _second_agent_packet_tail(base, "**Part 1: Register the app**"),
    ]
    return "\n\n".join(paragraphs)


def _second_agent_servicenow_packet(
    context: dict[str, Any],
    reuse: dict[str, Any],
    *,
    instance_name: str,
    client_id: str,
    tenant_id: str,
    claim_name: str,
) -> str:
    """Spec S2 steps 5-6: confirm the saved setup can also serve this agent."""
    other, audience = _second_agent_names(reuse)
    url = f"https://{instance_name}.service-now.com"
    custom = (
        f"`{claim_name}`"
        if claim_name.casefold() not in {"email", "upn"}
        else f"none; standard {claim_name.casefold()} claim confirmed"
    )
    paragraphs = [
        _second_agent_packet_intro(reuse, url),
        "Please confirm whether the saved ESS sign-in configuration and "
        f"employee mapping can also serve {audience}. ServiceNow needs to "
        "trust Microsoft Entra sign-in and match each employee to their "
        "ServiceNow user record. You need the `admin` or `security_admin` "
        "role.",
        f"**Entra values confirmed for {audience}**\n\n"
        f"- **Client ID:** `{client_id}`\n"
        f"- **Tenant ID:** `{tenant_id}`\n"
        f"- **Custom claim:** {custom}",
    ]
    if reuse["claimName"] and reuse["userField"]:
        paragraphs.extend(
            [
                f"**Earlier {other} mapping\u2014review before using for "
                f"{audience}**\n\n"
                f"- **User Claim:** `{reuse['claimName']}`\n"
                f"- **User Field:** **{reuse['userField']}**",
                f"This mapping was confirmed for {other}, not yet "
                f"confirmed for {audience}.",
            ]
        )
    base = _existing_servicenow_packet(
        context,
        next(iter(_EXISTING_IDENTITY_KINDS)),
        instance_name=instance_name,
        client_id=client_id,
        tenant_id=tenant_id,
        claim_name=claim_name,
    )
    paragraphs.extend(
        [
            "**Review the existing setup first**\n\n"
            "1. Review the saved ESS OIDC configuration against the Entra "
            f"values confirmed for {audience}.\n"
            "2. Confirm the User Claim and User Field that match the "
            "signed-in employee to their ServiceNow user record.\n"
            "3. If the saved setup can serve "
            f"{audience}, confirm its reuse without creating another "
            "configuration or repeating completed steps.",
            "ServiceNow allows only one OIDC configuration per Microsoft "
            "Entra tenant. If a configuration already serves single "
            "sign-on or the Microsoft Graph connector, **don't change "
            "it**. Coordinate the appropriate reuse or resolution with "
            "your Entra administrator.",
            f"See [coexistence guidance]({_COEXISTENCE_LINK}) and "
            f"[ServiceNow Knowledge connector guidance]"
            f"({_KNOWLEDGE_GUIDANCE_LINK}).",
            "**Please send back:** confirmation that the configuration is "
            f"saved and can serve {audience}, the **User Claim**, and the "
            "**User Field** used. State whether the configuration was "
            "reused or newly created. If reuse is unresolved, tell us what "
            "remains to be agreed.",
            "**Do not send secrets.**",
            "**Setup instructions\u2014only for work you determine is "
            "needed**",
            "If work is missing, coordinate the appropriate reuse or "
            "resolution with the Entra administrator before proceeding, "
            f"accounting for {other} and other existing uses. Do not "
            f"repeat completed steps solely to add {audience}.",
            "**Configure ServiceNow**",
            _second_agent_packet_tail(base, f"1. Sign in to **{url}**."),
        ]
    )
    return "\n\n".join(paragraphs)


def _second_agent_credential_lead_in(state: dict[str, Any]) -> str:
    """Spec S2 step 8: both administrators confirmed the shared setup."""
    audience = _product_audience()
    mapping = state.get("evidence", {}).get("identityMapping")
    claim = field = None
    if (
        isinstance(mapping, dict)
        and mapping.get("serviceNowAdministratorConfirmed") is True
    ):
        claim = mapping.get("tokenClaimName")
        field = mapping.get("serviceNowUserField")
    using = (
        f", using `{claim}` as the User Claim and **{field}** as the User "
        "Field"
        if isinstance(claim, str)
        and claim
        and isinstance(field, str)
        and field
        else ""
    )
    return (
        "Both administrators have confirmed the shared sign-in setup for "
        f"{audience}{using}.\n\n"
        f"Next, select a ServiceNow connection for {_spec_agent_name()}. "
        f"We'll then configure and test the {audience} agent.\n\n"
    )


def _second_agent_connection_guidance(
    context: dict[str, Any],
    state: dict[str, Any],
    reuse: dict[str, Any],
) -> str:
    """Spec S2 steps 8-9: select an existing connection; no duplicate."""
    other, audience = _second_agent_names(reuse)
    return (
        _second_agent_credential_lead_in(state)
        + "In Copilot Studio:\n\n"
        f"1. Open **{_display_agent_name(context)}** in "
        f"**{_display_environment_name(context)}**.\n"
        "2. Go to **Settings > Connection Settings > ServiceNow > "
        "Connect**.\n"
        "3. Select an existing ServiceNow connection available for this "
        "agent.\n\n"
        f"The connection may still have \"{other}\" in its name; you don't "
        "need to rename it or create a duplicate solely to add "
        f"{audience}.\n\n"
        "Return here and tell us which connection you selected. You won't "
        "need to resend the administrator replies."
    )


def _existing_plugin_prerequisite_guidance(
    instance_url: str,
) -> str:
    """Spec S3 Q: the HR prerequisite lead-in and ready-to-send message."""
    return (
        "Before the shared sign-in confirmation, your ServiceNow "
        "administrator needs to confirm that the HR Service Delivery Core "
        "plugin is installed and active.\n\n"
        "Send the message below and bring back their reply.\n\n"
    ) + _ready_to_send_block(
        f"We're connecting **{_spec_agent_name()}** to ServiceNow HR "
        f"Service Delivery on **{instance_url}**.\n\n"
        "Please confirm that **HR Service Delivery Core** "
        "(`com.sn_hr_core`) is installed and active.\n\n"
        "Go to **All > System Definition > Plugins** and search for "
        "**Human Resources Scoped App: Core**.\n\n"
        "**Please send back:** whether the plugin is installed and active."
    )


def _existing_identity_message(
    context: dict[str, Any],
    state: dict[str, Any],
    kind: str,
    situation: str,
    *,
    connection_name: str | None = None,
) -> tuple[str, str, str]:
    """Fixed S3 reply for one situation: (text, render kind, afterReply)."""
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    words = _EXISTING_IDENTITY_KINDS[kind]
    audience = copy_["audience"]
    agent = _spec_agent_name()
    environment = _recorded_environment_name(context)
    in_bold = f" in **{environment}**" if environment else ""
    agent_in_env = (
        f"**{agent} in {environment}**" if environment else f"**{agent}**"
    )
    instance = _state_instance_name(state) or "not confirmed"
    mapping_items = (
        "non-sensitive compatibility confirmation, saved-configuration "
        "confirmation, User Claim, User Field, and any changed registration "
        "or claim values"
    )
    waiting, info = "waiting", "info"
    if situation == "setup-incomplete":
        return (
            "Before we can add ESS alongside the existing integration, we "
            "need to finish basic ADK setup. We'll complete that first, "
            "then return here.",
            waiting,
            _EXISTING_AFTER_REPLY_SETUP,
        )
    if situation == "setup-complete":
        return (
            f"We'll continue with **{agent}**, the agent you just set up"
            f"{in_bold}. You can select another supported ESS agent before "
            "we continue.",
            info,
            "",
        )
    if situation == "entra-incomplete":
        return (
            "Ask your Entra administrator to confirm which registration "
            "supports ESS, including its **Client ID**, **tenant ID**, and "
            "any **custom claim name**.\n\n"
            "Paste their reply here without secrets, or send the confirmed "
            "values individually.",
            waiting,
            _EXISTING_AFTER_REPLY_VALUES,
        )
    if situation == "client-id-only":
        return (
            "We have the Client ID. Send the **tenant ID** your "
            "administrator confirmed so we can prepare the ServiceNow "
            "handoff. You don't need to resend the Client ID.",
            waiting,
            _EXISTING_AFTER_REPLY_VALUES,
        )
    if situation == "two-client-ids":
        return (
            "Ask your Entra administrator which **Client ID** ESS should "
            "use.\n\n"
            "Send that value here. We'll keep the other confirmed "
            "information already supplied.",
            waiting,
            _EXISTING_AFTER_REPLY_VALUES,
        )
    if situation == "servicenow-incomplete":
        return (
            "Ask your ServiceNow administrator to confirm that the "
            "configuration is saved and supports ESS, and name its **User "
            "Claim** and **User Field**.\n\n"
            "Paste their reply here without secrets, or send the missing "
            "items individually. You don't need to repeat the Entra values.",
            waiting,
            _EXISTING_AFTER_REPLY_VALUES,
        )
    if situation == "servicenow-fields-unnamed":
        return (
            "Ask your ServiceNow administrator which **User Claim** and "
            "**User Field** they confirmed for ESS. Send those values here.",
            waiting,
            _EXISTING_AFTER_REPLY_VALUES,
        )
    if situation == "coexistence-conflict":
        return (
            "Your Entra and ServiceNow administrators need to agree on a "
            "supported setup that accounts for the existing integration.\n\n"
            "Ask them to use the compatibility guidance in their messages. "
            "We won't change the shared configuration or troubleshoot the "
            "conflict.\n\n"
            f"Bring back their {mapping_items}. Don't include employee "
            "identifiers or secrets.\n\n"
            "We'll recheck the affected setup before continuing. Unchanged "
            "applicable information stays in place.",
            waiting,
            _EXISTING_AFTER_REPLY_CONTINUE,
        )
    if situation == "replace-configuration":
        return (
            "We can't replace the shared sign-in configuration. Your Entra "
            "and ServiceNow administrators need to agree on a supported "
            "setup that accounts for its existing uses.\n\n"
            "Ask them to coordinate using the guidance in their messages, "
            f"then bring back their {mapping_items}. We'll recheck the "
            "affected setup before continuing.",
            waiting,
            _EXISTING_AFTER_REPLY_CONTINUE,
        )
    if situation == "waiting":
        return _existing_waiting_text(), waiting, _EXISTING_AFTER_REPLY_CONTINUE
    if situation == "resumed":
        return (
            "We're continuing the ServiceNow setup for "
            f"{agent_in_env}.\n\n"
            "We're rechecking your permission before we continue. Next, "
            "we'll need your administrators' compatibility confirmation.",
            info,
            "",
        )
    if situation == "resolution-missing-mapping":
        return (
            "We have their resolution update. Ask your ServiceNow "
            "administrator to confirm that the configuration is saved and "
            "supports ESS, and name the **User Claim** and **User Field**.\n\n"
            "Send the missing confirmation and values here without employee "
            "identifiers or secrets. We'll recheck the affected setup "
            "before continuing to the ESS connection.",
            waiting,
            _EXISTING_AFTER_REPLY_VALUES,
        )
    if situation == "different-registration":
        return (
            "We'll check the setup information tied to the newly confirmed "
            "Client ID before continuing.\n\n"
            "Ask your ServiceNow administrator to confirm that the "
            "configuration for that registration is saved and supports ESS, "
            "and provide its **User Claim** and **User Field**. Bring back "
            "their non-sensitive reply and any other changed setup values. "
            "We won't carry forward confirmation tied to the earlier Client "
            "ID.",
            waiting,
            _EXISTING_AFTER_REPLY_CONTINUE,
        )
    if situation == "custom-claim":
        return (
            "We need the Entra administrator to confirm the exact claim "
            "before ServiceNow can use it for this setup.\n\n"
            "Ask them to complete the custom-claim work in Part 4 of their "
            "instructions. Bring back the exact configured claim name and "
            "confirmation that the setup is complete, including the "
            "appropriate format and populated source attribute for every "
            "intended employee.\n\n"
            "Then ask your ServiceNow administrator to confirm that the "
            "supported configuration is saved and supports ESS, with the "
            "matching User Claim and User Field. Don't send employee "
            "identifiers or secrets.\n\n"
            "The confirmed Client ID and tenant ID stay in place.",
            waiting,
            _EXISTING_AFTER_REPLY_CONTINUE,
        )
    if situation == "knowledge-connector":
        return (
            f"{words['that_is']}, not the ServiceNow connection used by the "
            f"ESS {audience} agent.\n\n"
            f"In **{agent} > Settings > Connection Settings > ServiceNow**, "
            "create the connection using **Microsoft Entra ID User Login**, "
            "the confirmed Client ID as **Resource URI**, and "
            f"`{instance}` as **Instance name**.\n\n"
            f"{words['leave']} Return here and tell us which ESS connection "
            "you used. We'll check this agent's connection and link before "
            "continuing.",
            waiting,
            _EXISTING_AFTER_REPLY_CONNECTION,
        )
    if situation == "existing-connection":
        return (
            "You can select that existing ESS ServiceNow connection "
            "instead of creating a duplicate.\n\n"
            "Return here and tell us which one you selected. We'll check "
            f"that {agent} can use it.",
            waiting,
            _EXISTING_AFTER_REPLY_CONNECTION,
        )
    if situation == "connection-disconnected":
        name = (connection_name or "").strip()
        if not name:
            raise ServiceNowConnectError(
                "Pass --connection-name with the friendly connection name "
                "the maker used."
            )
        if _FRIENDLY_NAME_BLOCKED_RE.search(name):
            raise ServiceNowConnectError(
                "Pass the friendly connection name the maker used, not an "
                "ID or a URL."
            )
        return (
            f"**{name} is disconnected**, so {agent} can't use it.\n\n"
            f"In Copilot Studio, open **{agent} > Settings > Connection "
            "Settings > ServiceNow**.\n\n"
            "Reconnect it only if you intend to act on that connection, "
            "including any shared uses. Otherwise, select another "
            "supported ESS connection or create a separate one using the "
            "connection instructions.\n\n"
            "Return here and tell us which connection you used. We'll "
            "check this agent's connection and link before you repeat the "
            f"{audience} request. The administrator replies and portal "
            "information already supplied stay in place.",
            waiting,
            _EXISTING_AFTER_REPLY_CONNECTION,
        )
    if situation == "missing-consent":
        return (
            "The setup check found that the required Microsoft ServiceNow "
            "connector consent is missing.\n\n"
            "Ask your Entra administrator to review Part 3 of their "
            "handoff with the ServiceNow administrator before any changes "
            "to the shared setup.\n\n"
            "Bring back their non-sensitive confirmation that the "
            "supported setup is complete and any changed values. We'll "
            "recheck the affected setup before continuing; if a test is "
            "needed, repeat the request in this agent's Test pane.",
            waiting,
            _EXISTING_AFTER_REPLY_CONTINUE,
        )
    if situation == "blocked-finish":
        return (
            "**Setup is paused:** your administrators haven't yet "
            f"confirmed a compatible setup for {agent_in_env}. ESS remains "
            "untested; setup isn't complete.\n\n"
            "Your progress is saved at their compatibility handoff. Bring "
            f"back their {mapping_items}. Don't include employee "
            "identifiers or secrets.",
            waiting,
            _EXISTING_AFTER_REPLY_CONTINUE,
        )
    if situation == "hr-prerequisite-self-confirmed":
        if not ACTIVE_PROFILE.requires_hr_core:
            raise ServiceNowConnectError(
                "The HR prerequisite applies only to Employee Self-Service HR."
            )
        return (
            "Ask your ServiceNow administrator to confirm that the plugin "
            "is installed and active. Paste their reply here or relay "
            "their explicit confirmation.",
            waiting,
            _EXISTING_AFTER_REPLY_PREREQUISITE,
        )
    raise ServiceNowConnectError("Unsupported existing-identity situation.")


def _existing_waiting_text() -> str:
    return (
        "We're waiting for your administrators to confirm a compatible "
        f"setup for **{_spec_agent_name()}**.\n\n"
        "When they reply, paste their non-sensitive compatibility "
        "confirmation and saved-configuration confirmation, including User "
        "Claim, User Field, and any changed registration or claim values. "
        "Don't include employee identifiers or secrets. You don't need to "
        "repeat unchanged confirmed information."
    )


def _ensure_lifecycle_state(context: dict[str, Any]) -> dict[str, Any]:
    root = Path(context["root"])
    if not _lifecycle_state_path(context).exists():
        contract = _load_json(root / CONTRACT_PATH)
        decision = decide_next_step(
            root,
            provider=ACTIVE_PROFILE.provider_key,
            agent_slug=_agent_slug(context),
            executed_actions=frozenset(),
            verified_phases=frozenset(),
        )
        _accept_connect_contract(context, contract, decision)
    return _load_lifecycle_state(context)


def existing_identity_handoff(
    context: dict[str, Any],
    kind: str,
    situation: str = "disclosure",
    *,
    connection_name: str | None = None,
    metadata_url: str | None = None,
) -> dict[str, Any]:
    """Fixed S3 reply when the maker reuses Knowledge, SSO or Graph sign-in.

    Records only the non-identity marker that keeps every later administrator
    message in the S3 compatibility-review wording; it never records identity
    values and never changes the shared sign-in configuration.
    """
    if kind not in _EXISTING_IDENTITY_KINDS:
        raise ServiceNowConnectError("Unsupported existing integration kind.")
    if situation not in _EXISTING_IDENTITY_SITUATIONS:
        raise ServiceNowConnectError("Unsupported existing-identity situation.")
    state = _ensure_lifecycle_state(context)
    marker = state.get("existingIdentity")
    if not (isinstance(marker, dict) and marker.get("kind") == kind):
        state["existingIdentity"] = {"kind": kind, "recordedAt": _utc_now()}
        _write_lifecycle_state(context, state)
    after_reply = ""
    if situation == "disclosure":
        if state.get("openingShown"):
            text, render_kind = _existing_identity_notice(kind), "info"
        else:
            text = _existing_identity_opening(context, state, kind)
            render_kind = "info"
            state["openingShown"] = {"shownAt": _utc_now()}
            _write_lifecycle_state(context, state)
    elif situation == "metadata-url":
        if not metadata_url:
            raise ServiceNowConnectError("Pass --metadata-url.")
        diagnosis = metadata_url_handoff(metadata_url)
        if "renderBlock" not in diagnosis:
            return {
                **diagnosis,
                "existingIdentity": kind,
                "recordsIdentityValues": False,
                "changesSharedConfiguration": False,
            }
        text = (
            "The supplied metadata URL contains `/v2.0`, which is not the "
            "URL used by this supported ESS setup.\n\n"
            "Ask your ServiceNow administrator to review that URL against "
            "the instructions in their handoff, coordinating compatibility "
            "with the Entra administrator.\n\n"
            "Bring back their non-sensitive confirmation that the "
            "supported configuration is saved and any changed values. "
            "We'll recheck the affected setup before you repeat the request "
            "in this agent's Test pane."
        )
        render_kind, after_reply = "waiting", _EXISTING_AFTER_REPLY_CONTINUE
    else:
        text, render_kind, after_reply = _existing_identity_message(
            context,
            state,
            kind,
            situation,
            connection_name=connection_name,
        )
    result: dict[str, Any] = {
        "status": "existing-identity-notice",
        "decision": f"existing-identity-{situation}",
        "existingIdentity": kind,
        "recordsIdentityValues": False,
        "changesSharedConfiguration": False,
        "renderBlock": {"kind": render_kind, "text": text},
    }
    if after_reply:
        result["afterReply"] = after_reply
    return result


_TEST_FAILURE_AFTER_REPLY_UNKNOWN = (
    "End your turn after sending the message; this is a plain chat "
    "question, not a card. Map the maker's typed reply: an error, record "
    "record-test --result fail without a failure category; an empty result, "
    "record-test --result empty (for an empty HR service-area list, run "
    "empty-service-areas-handoff instead); a reported saved metadata URL "
    "containing /v2.0, run metadata-url-handoff with that exact URL; a claim "
    "and User Field the administrators supplied, run this command again with "
    "--reported-claim and --reported-user-field. Never infer a shared "
    "identity failure, missing consent or a /v2.0 URL from a generic "
    "failure, and never ask for more than what is still missing."
)
_TEST_FAILURE_AFTER_REPLY_MISMATCH = (
    "When the maker returns, any message means they want to continue. Do "
    "not ask a Yes/No question. Record only the administrators' "
    "non-sensitive reply with the existing record-identity-direct "
    "commands. If a custom claim changed, run claim-confirmation-handoff "
    "--custom-claim (add --claim-name-given when the name was supplied) and "
    "ask only for the missing confirmations. Do not change an existing "
    "OIDC configuration serving SSO or the Microsoft Graph connector. Then "
    "recheck the affected setup before the maker repeats the request in "
    "the Test pane."
)


def test_failure_handoff(
    state: dict[str, Any] | None,
    reported_claim: str | None = None,
    reported_user_field: str | None = None,
) -> dict[str, Any]:
    """Fixed reply when this agent's test fails although another agent worked.

    The reply never assumes a shared identity failure. A claim and User Field
    mismatch is named only when the supplied claim and User Field differ from
    the saved mapping; otherwise the maker is asked for the specific error or
    result. Nothing is recorded.
    """
    copy_ = _DEV_TEST_COPY[ACTIVE_PROFILE.key]
    audience = copy_["audience"]
    other = "IT" if audience == "HR" else "HR"
    opening = (
        f"{audience} didn't return the expected {copy_['records']}. We'll "
        f"check the {audience} setup information already supplied to narrow "
        "down the problem."
    )
    more_info = (
        "If more information is needed, we'll ask for the specific error or "
        f"result\u2014not the whole {other} setup history."
    )
    mismatch = False
    if reported_claim is not None or reported_user_field is not None:
        if not reported_claim or not reported_user_field:
            raise ServiceNowConnectError(
                "Pass both --reported-claim and --reported-user-field."
            )
        claim = _safe_identity_name(reported_claim, "user_claim")
        field = _safe_identity_name(reported_user_field, "user_field")
        evidence = state.get("evidence") if isinstance(state, dict) else None
        saved = (
            evidence.get("identityMapping") if isinstance(evidence, dict) else None
        )
        if isinstance(saved, dict):
            saved_claim = str(saved.get("tokenClaimName") or "").casefold()
            saved_field = str(saved.get("serviceNowUserField") or "").casefold()
            mismatch = bool(saved_claim and saved_field) and (
                claim.casefold() != saved_claim
                or field.casefold() != saved_field
            )
    if mismatch:
        text = "\n\n".join(
            [
                opening,
                "The supplied evidence shows a mismatch between the sign-in "
                "claim and ServiceNow user field.",
                "Ask your ServiceNow administrator to review the mismatch "
                "with your Entra administrator and confirm a supported "
                "mapping that accounts for the shared setup's existing "
                "uses. Don't change an existing OIDC configuration serving "
                "SSO or the Microsoft Graph connector.",
                "Bring back their non-sensitive confirmation that the "
                f"configuration is saved and supports {audience}, the exact "
                "User Claim and User Field, and any changed registration or "
                "claim values. If a custom claim changed, also bring back "
                "its completed-setup confirmation for the intended "
                "employees.",
                "We'll recheck the affected setup before you repeat the "
                f"{audience} request in this agent's Test pane.",
            ]
        )
        decision = "identity-mapping-review-required"
        after_reply = _TEST_FAILURE_AFTER_REPLY_MISMATCH
    else:
        text = "\n\n".join(
            [
                opening,
                more_info,
                "We haven't identified the cause yet.",
                "Did the Test pane show an error, an empty result, or "
                "something else? If there was an error, send only its text "
                f"without {copy_['record']} contents, employee identifiers, "
                "tokens, or other secrets.",
            ]
        )
        decision = "test-failure-information-required"
        after_reply = _TEST_FAILURE_AFTER_REPLY_UNKNOWN
    return {
        "status": "test-failure-reply",
        "decision": decision,
        "recordsNothing": True,
        "renderBlock": {"kind": "waiting", "text": text},
        "afterReply": after_reply,
    }


def metadata_url_handoff(metadata_url: str) -> dict[str, Any]:
    """Fixed reply when the administrator reports a `/v2.0` metadata URL.

    Only an actual reported URL of the Microsoft sign-in authority with a
    `/v2.0` path is diagnosed. Nothing is recorded and no shared identity
    configuration is changed; the administrators repair it manually.
    """
    match = _V2_METADATA_URL_RE.match(str(metadata_url).strip().strip("`<>"))
    if match is None:
        return {
            "status": "no-diagnosis",
            "decision": "no-v2-metadata-url",
            "recordsNothing": True,
            "note": (
                "The reported value is not a /v2.0 metadata URL for this "
                "connection, so this diagnosis does not apply. Do not treat "
                "it as a known setup problem; continue the normal flow."
            ),
        }
    supported = (
        f"https://login.microsoftonline.com/{match.group('tenant')}"
        "/.well-known/openid-configuration"
    )
    return {
        "status": "metadata-url-review-required",
        "decision": "metadata-url-review-required",
        "recordsNothing": True,
        "renderBlock": {
            "kind": "waiting",
            "text": (
                "That metadata URL contains `/v2.0`, which is a known setup "
                "problem for this connection.\n\n"
                "Ask your ServiceNow administrator to review the saved URL "
                "against the supported ESS metadata URL below, coordinating "
                "compatibility with your Entra administrator before any "
                f"repair:\n\n`{supported}`\n\n"
                "Don't change an existing configuration serving SSO or the "
                "Microsoft Graph connector. If compatibility is unresolved, "
                "the administrators need to resolve it manually.\n\n"
                "Bring back their non-sensitive confirmation that the "
                "supported configuration is saved and any changed setup "
                "values. We'll recheck the affected setup before you repeat "
                "the request in this agent's Test pane."
            ),
        },
        "afterReply": _METADATA_URL_AFTER_REPLY,
    }


def claim_setup_confirmation_required(claim_name: str) -> dict[str, Any]:
    """Reply for a custom claim name stated without its setup confirmation.

    A name alone does not establish custom-claim readiness, so nothing is
    recorded and the already-supplied values stay in place.
    """
    name = _safe_identity_name(claim_name, "user_claim")
    return {
        "status": "claim-confirmation-required",
        "decision": "claim-confirmation-required",
        "recordsNothing": True,
        "renderBlock": {
            "kind": "waiting",
            "text": (
                f"We have the claim name `{name}`. Ask your Entra "
                "administrator to confirm that its setup is complete, "
                "including the appropriate format and populated source "
                "attribute for every intended employee, as requested in "
                "their message.\n\n"
                "Bring back their non-sensitive confirmation; you don't "
                "need to resend the name or the Client ID. Don't include "
                "employee identifiers or secrets."
            ),
        },
        "afterReply": _CLAIM_CONFIRMATION_AFTER_REPLY,
    }


def _chat_message(result: dict[str, Any]) -> str:
    """Build the one chat message the agent relays for this output.

    Card titles are the questions themselves, so the explanation that used to
    sit in the card body is sent here, before the card.
    """
    parts: list[str] = []

    def add(text: Any) -> None:
        if isinstance(text, str) and text.strip():
            cleaned = text.strip()
            if not any(cleaned in part for part in parts):
                parts.append(cleaned)

    render_block = result.get("renderBlock")
    if isinstance(render_block, dict):
        add(render_block.get("text"))
    ordinary = result.get("ordinaryReply")
    if isinstance(ordinary, dict):
        add(ordinary.get("text"))
    add(result.get("replyBeforeQuestion"))
    for card in _pending_cards(
        {
            key: item
            for key, item in result.items()
            if key not in {"renderBlock", "ordinaryReply"}
        }
    ):
        if card["question"].strip() != card["header"].strip():
            add(card["question"])
    return "\n\n".join(parts)


def _output_waits_for_maker(
    result: dict[str, Any],
    command: str | None,
) -> bool:
    """True when the maker must reply or act outside chat before the flow moves."""
    if result.get("status") == "error" or command in REALM_COMMANDS:
        return True
    if has_wait_cue(_chat_message(result)):
        return True
    if result.get("pendingInput"):
        return True
    render_block = result.get("renderBlock")
    if isinstance(render_block, dict) and render_block.get("kind") in (
        _WAIT_RENDER_KINDS
    ):
        return True
    status = result.get("status")
    decision = result.get("decision")
    if any(
        isinstance(marker_source, str)
        and any(marker in marker_source for marker in _WAIT_STATUS_MARKERS)
        for marker_source in (status, decision)
    ):
        return True
    if command == "resume-handoff":
        # Nothing runnable is left, so there is nothing to auto-continue to.
        return not (
            isinstance(result.get("checkpoints"), dict)
            or isinstance(result.get("action"), dict)
        )
    return False


def _next_command(
    result: dict[str, Any],
    command: str | None,
    args: Any,
) -> str:
    """Exact next step for an output that continues without the maker."""
    checkpoints = result.get("checkpoints")
    if isinstance(checkpoints, dict) and checkpoints.get("commands"):
        lines = [
            str(item["command"])
            for item in checkpoints["commands"]
            if isinstance(item, dict) and item.get("command")
        ]
        if lines:
            return (
                "Run each of these commands exactly (replace the leading "
                "python with the launcher from /setup), then run "
                "record-checkpoint-results with the results: "
                + " ; ".join(lines)
            )
    action = result.get("action")
    if isinstance(action, dict) and action.get("actionDoc"):
        return (
            f"Read {action['actionDoc']} now and follow it (apply the shared "
            "permission and rollback gates first). When the action is done, "
            f"continue with: {_resume_command(result, args, executed=_running_phase(result))}"
        )
    return _resume_command(result, args)


def _running_phase(result: dict[str, Any]) -> list[str]:
    lifecycle = result.get("lifecycle")
    if (
        isinstance(lifecycle, dict)
        and lifecycle.get("decision") == "run-action"
        and isinstance(lifecycle.get("phase"), dict)
        and isinstance(lifecycle["phase"].get("id"), str)
    ):
        return [lifecycle["phase"]["id"]]
    return []


def _resume_command(
    result: dict[str, Any],
    args: Any,
    *,
    executed: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """Exact resume-handoff command that carries this invocation's phase flags.

    The controller keeps no per-invocation memory: every phase that is already
    done must be passed again as ``--verified-phase`` or it is re-read.
    """
    slug = result.get("agentSlug") or getattr(args, "agent_slug", None)
    provider = result.get("provider") or getattr(args, "provider", None)
    parts = ["python scripts/connect_servicenow_da.py"]
    if provider:
        parts.append(f"--provider {provider}")
    if slug:
        parts.append(f"--agent-slug {slug}")
    parts.append("resume-handoff")
    flags: list[tuple[str, str]] = []
    for flag, carried, extra in (
        ("--executed-action", getattr(args, "executed_action", None), executed),
        ("--verified-phase", getattr(args, "verified_phase", None), None),
    ):
        for phase_id in [*(carried or []), *(extra or [])]:
            if (flag, phase_id) not in flags:
                flags.append((flag, phase_id))
    extra_list = list(extra_args or [])
    for index in range(0, len(extra_list) - 1, 2):
        pair = (extra_list[index], extra_list[index + 1])
        if pair not in flags:
            flags.append(pair)
    parts.extend(f"{flag} {value}" for flag, value in flags)
    return " ".join(parts)


_RECORD_COMMANDS = frozenset({"record-admin-phase", "record-checkpoint-results"})

_ASK_CARD_NEXT = (
    "Ask the question in pendingCard now with one ask_user call using "
    "pendingCard.askUserArguments exactly as given, then continue from the "
    "maker's answer."
)


def _with_agent_rules(
    result: Any,
    command: str | None = None,
    args: Any = None,
) -> Any:
    """Prepend rules to every command output; `adapt-question` output stays unchanged."""
    if not isinstance(result, dict) or command == "adapt-question":
        return result
    ordered: dict[str, Any] = {}
    chat_message = _chat_message(result)
    cards = _pending_cards(
        {
            key: item
            for key, item in result.items()
            if key not in {"renderBlock", "ordinaryReply"}
        }
    )
    if chat_message or cards:
        if chat_message:
            ordered["chatMessage"] = chat_message
        if cards:
            ordered["endTurn"] = False
            ordered["nextCommand"] = _ASK_CARD_NEXT
            ordered["pendingCard"] = adapt_question_to_ask_user(cards[0])
        elif _output_waits_for_maker(result, command):
            ordered["endTurn"] = True
            action = result.get("action")
            if isinstance(action, dict) and action.get("actionDoc"):
                ordered["afterReply"] = (
                    f"When the maker replies, read {action['actionDoc']} and "
                    "continue from its step that follows the maker's reply. "
                    "Do not repeat or reword the message above. Afterwards "
                    "continue with: "
                    + _resume_command(
                        result, args, executed=_running_phase(result)
                    )
                )
        else:
            ordered["endTurn"] = False
            ordered["nextCommand"] = _next_command(result, command, args)
    elif command in _RECORD_COMMANDS and result.get("resumeArguments"):
        ordered["endTurn"] = False
        ordered["nextCommand"] = (
            "Continue now with: "
            + _resume_command(
                result,
                args,
                extra_args=[str(item) for item in result["resumeArguments"]],
            )
        )
    if "renderBlock" in result:
        ordered["renderBlock"] = result["renderBlock"]
    ordered["agentRules"] = list(AGENT_RULES)
    for key, value in result.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context: dict[str, Any] | None = None
    try:
        profile = product_profile_for_provider(args.provider)
        if profile is None:  # pragma: no cover
            raise ServiceNowConnectError("Unsupported ServiceNow provider.")
        configure_product_profile(profile.key)
        if args.command == "adapt-question":
            raw_question = sys.stdin.read()
            if not raw_question.strip():
                raise ServiceNowConnectError(
                    "adapt-question requires one canonical question JSON "
                    "object on stdin."
                )
            parsed_question = json.loads(raw_question)
            if not isinstance(parsed_question, dict):
                raise ServiceNowConnectError(
                    "adapt-question stdin must be one JSON object."
                )
            result = adapt_question_to_ask_user(parsed_question)
        elif args.command == "list-agents":
            result = (
                list_agent_choices(maker_username=args.maker_username)
                if args.maker_username
                else list_agent_choices()
            )
        elif args.command == "agent-chooser":
            result = agent_chooser_handoff(
                selection_key=args.selection_key,
                agent_link=args.agent_link,
            )
        elif args.command == "claim-confirmation-handoff":
            result = claim_confirmation_handoff(
                custom_claim=args.custom_claim,
                claim_name_given=args.claim_name_given,
                servicenow_confirmed=args.servicenow_confirmed,
            )
        elif args.command == "metadata-url-handoff":
            result = metadata_url_handoff(args.metadata_url)
        elif args.command == "empty-service-areas-handoff":
            result = empty_service_areas_handoff(args.realm)
        else:
            context_kwargs: dict[str, Any] = {}
            if args.agent_id is not None or args.agent_slug is not None:
                context_kwargs = {
                    "agent_id": args.agent_id,
                    "agent_slug": args.agent_slug,
                }
            if args.maker_username:
                context_kwargs["maker_username"] = args.maker_username
            context = load_context(**context_kwargs)
        if args.command == "inspect":
            result = inspect(context, offline=args.offline)
        elif args.command == "inspect-portal-url":
            result = inspect_portal_configuration(
                context,
                offline=args.offline,
                expected_portal_url=args.expected_portal_url,
            )
        elif args.command == "inspect-admin-setup":
            print(
                "DA_ADMIN_PREFLIGHT_PROGRESS_JSON:"
                + json.dumps(
                    {
                        "stage": "authentication",
                        "state": "starting",
                        "mode": "read-only-preparation",
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            result = inspect_admin_setup(context)
        elif args.command == "shared-reuse-handoff":
            result = shared_reuse_handoff(
                context,
                source_key=args.source_key,
            )
        elif args.command == "record-shared-reuse":
            result = apply_shared_configuration_reuse(
                context,
                source_key=args.source_key,
                decision=args.decision,
            )
        elif args.command == "portal-reuse-handoff":
            result = portal_value_reuse_handoff(
                context,
                source_key=args.source_key,
            )
        elif args.command == "record-portal-reuse":
            result = record_portal_value_reuse(
                context,
                source_key=args.source_key,
                decision=args.decision,
            )
        elif args.command == "record-preflight":
            result = record_preflight_instance(
                context,
                instance_url=args.instance_url,
            )
        elif args.command == "identity-direct-handoff":
            result = identity_direct_handoff(
                context,
                stage=args.stage,
                captured_client_id=args.client_id,
                captured_user_field=args.user_field,
            )
        elif args.command == "record-identity-requirement":
            result = record_identity_requirement(
                context,
                choice=args.choice,
            )
        elif (
            args.command == "record-identity-direct"
            and args.stage == "entra"
            and args.claim_name
            and args.claim_name.strip().casefold()
            not in _STANDARD_USER_CLAIMS
            and not args.claim_setup_confirmed
        ):
            result = claim_setup_confirmation_required(args.claim_name)
        elif args.command == "record-identity-direct":
            result = record_identity_direct(
                context,
                stage=args.stage,
                client_id=args.client_id,
                directory_tenant_id=args.directory_tenant_id,
                claim_name=args.claim_name,
                user_field=args.user_field,
                confirmed=args.yes,
                saved_mapping_confirmed=(
                    True
                    if args.confirm_saved_mapping
                    else False
                    if args.reject_saved_mapping
                    else None
                ),
            )
        elif args.command == "record-admin-phase":
            result = record_admin_phase(
                context,
                phase=args.phase,
                status=args.status,
                client_id=args.client_id,
                application_registration_confirmed=(
                    args.confirm_application_registration
                ),
                claim_emission_confirmed=args.confirm_claim_emission,
                user_impersonation_scope_confirmed=(
                    args.confirm_user_impersonation_scope
                ),
                connector_preauthorization_confirmed=(
                    args.confirm_connector_preauthorization
                ),
                configuration_saved_confirmed=(
                    args.confirm_configuration_saved
                ),
                oidc_provider_confirmed=args.confirm_oidc_provider,
                claim_mapping_confirmed=args.confirm_claim_mapping,
                active_user_match_confirmed=(
                    args.confirm_active_user_match
                ),
            )
            result = {
                **result,
                "resumeArguments": [
                    "--executed-action",
                    args.phase,
                    *_verified_prefix_arguments(
                        context, args.phase, include_self=False
                    ),
                ],
            }
        elif args.command == "create":
            result = prepare_manual_connection(
                context,
                instance_name=args.instance_name,
                resource_uri=args.resource_uri,
                display_name=args.display_name,
            )
        elif args.command == "record-credential":
            result = record_credential_selection(
                context,
                args.connection_id,
            )
        elif args.command == "resolve-credential":
            result = resolve_credential_completion(
                context,
                selection_key=args.selection_key,
            )
        elif args.command == "set-topic-state":
            result = set_topic_state(
                context,
                args.topic_id,
                args.state.title(),
                confirmed=args.yes,
            )
        elif args.command == "enable-all-topics":
            result = enable_all_servicenow_topics(
                context,
                confirmed=args.yes,
            )
        elif args.command == "rollback-topics":
            result = rollback_topic_transaction(
                context,
                args.operation_id,
                confirmed=args.yes,
            )
        elif args.command == "record-topic-choice":
            result = record_keep_current_topic_choice(context)
        elif args.command == "topic-action-handoff":
            result = topic_action_handoff(context, offline=args.offline)
        elif args.command == "resume-handoff":
            result = resume_handoff(
                context,
                executed_actions=frozenset(args.executed_action),
                verified_phases=frozenset(args.verified_phase),
                roles_available=(
                    args.roles_available == "yes"
                    if args.roles_available is not None
                    else None
                ),
                availability_group_id=args.business_group_id,
                availability_context_sha256=(
                    args.availability_context_sha256
                ),
            )
        elif args.command == "record-checkpoint-results":
            result = record_checkpoint_results(
                context,
                phase_id=args.phase,
                results=list(args.result),
                maker_acknowledged=list(args.maker_acknowledged),
            )
        elif args.command == "portal-url-confirmation":
            result = portal_url_confirmation(context, args.portal_url)
        elif args.command == "set-portal-url":
            result = set_portal_url(
                context,
                args.portal_url,
                confirmed=args.yes,
                rollback_after_verify=args.rollback_after_verify,
            )
        elif args.command == "publish":
            result = publish(context, confirmed=args.yes)
        elif args.command == "inspect-publish":
            result = inspect_publish_state(context)
        elif args.command == "reconcile-publish-receipt":
            result = reconcile_publish_receipt(
                context,
                expected_component_hash=args.expected_component_hash,
                expected_last_published_at=args.expected_last_published_at,
                confirmed=args.yes,
            )
        elif args.command == "record-test":
            result = record_test_attestation(
                context,
                prompt_category=args.prompt_category,
                result=args.result,
                failure_category=args.failure_category,
            )
        elif args.command == "migrate-state":
            result = migrate_state(context)
        elif args.command == "initialize-state":
            result = initialize_lifecycle_state(
                context,
                contract_revision=args.contract_revision,
            )
        elif args.command == "target-change-handoff":
            result = target_change_handoff(context, args.change, args.target)
        elif args.command == "existing-identity-handoff":
            result = existing_identity_handoff(
                context,
                args.existing,
                args.situation,
                connection_name=args.connection_name,
                metadata_url=args.metadata_url,
            )
        elif args.command == "test-failure-handoff":
            result = test_failure_handoff(
                _load_lifecycle_state(context),
                args.reported_claim,
                args.reported_user_field,
            )
        elif args.command in REALM_COMMANDS:
            result = run_realm_command(context, args)
        elif args.command not in {
            "adapt-question",
            "list-agents",
            "agent-chooser",
            "claim-confirmation-handoff",
            "metadata-url-handoff",
            "empty-service-areas-handoff",
        }:  # pragma: no cover
            raise ServiceNowConnectError("Unsupported command.")
    except (ServiceNowConnectError, AgentBuilderError, ValueError) as exc:
        error = {"status": "error", "message": str(exc)}
        details = (
            copy.deepcopy(exc.details)
            if isinstance(exc, ServiceNowConnectError)
            and isinstance(exc.details, dict)
            else {}
        )
        recovery_commands = {
            "inspect",
            "inspect-portal-url",
            "inspect-admin-setup",
            "shared-reuse-handoff",
            "record-shared-reuse",
            "record-preflight",
            "identity-direct-handoff",
            "record-identity-requirement",
            "record-identity-direct",
            "record-admin-phase",
            "create",
            "record-credential",
            "resolve-credential",
            "set-topic-state",
            "enable-all-topics",
            "rollback-topics",
            "record-topic-choice",
            "topic-action-handoff",
            "resume-handoff",
            "record-checkpoint-results",
            "set-portal-url",
            "record-test",
            "migrate-state",
            "initialize-state",
        }
        if (
            context is not None
            and args.command in recovery_commands
            and not isinstance(
            details.get("recoveryHandoff"),
            dict,
            )
        ):
            details["recoveryHandoff"] = _command_error_recovery(
                context,
                args,
                exc,
            )
        if details:
            error["details"] = details
        print(json.dumps(_with_agent_rules(error, None, args), indent=2))
        return 1
    print(
        json.dumps(
            _with_agent_rules(result, args.command, args),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    from adk_telemetry import script_error_boundary

    with script_error_boundary("connect_servicenow_da"):
        raise SystemExit(main())
