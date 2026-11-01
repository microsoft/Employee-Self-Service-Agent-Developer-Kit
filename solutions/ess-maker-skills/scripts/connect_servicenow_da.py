# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Connect the DA-GA HR agent to ServiceNow HRSD without Dataverse."""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import socket
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING
from urllib.parse import quote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from connect_lifecycle import decide_next_step
from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    DEV_REALM,
    PROD_REALM,
    RING_CONFIG,
    TEST_REALM,
    authenticate,
    derive_environment_host,
    list_environments,
    validate_environment_host,
)
from flightcheck.checks.solution import run_solution_checks
from servicenow_connect_telemetry import (
    emit_lifecycle_event as emit_servicenow_lifecycle_event,
    prepare_lifecycle_projection,
)

if TYPE_CHECKING:
    from openpyxl.styles import PatternFill


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
LIFECYCLE_SCHEMA_VERSION = 8
ADMIN_SETUP_SCHEMA_VERSION = 4
AUTH_MODE = "entraIDUserLogin"
ENTRA_CHECKPOINT_SUFFIXES = (
    "APP",
    "CLAIMS",
    "SCOPE",
    "PREAUTH",
)
RETIRED_ENTRA_CHECKPOINT_SUFFIXES = (
    "PERMISSIONS",
    "CONSENT",
)
IDENTITY_WORKBOOK_STEPS_SHEET = "Steps"
IDENTITY_WORKBOOK_SHEET = "Worksheet"
IDENTITY_WORKBOOK_METADATA_SHEET = "_metadata"
IDENTITY_ENTRA_HANDOFF_SHEET = "Entra Handoff"
IDENTITY_ENTRA_HANDOFF_HEADERS = (
    "Instructions",
    "Client ID",
    "User Claim",
)
IDENTITY_ENTRA_HANDOFF_FORMAT = "servicenow.entra-handoff.v2"
IDENTITY_SERVICENOW_CSV_FORMAT = "servicenow.servicenow-handoff.v2"
IDENTITY_ENTRA_METADATA_KEYS = (
    "format_version",
    "purpose",
    "target_agent",
    "tenant_id",
    "environment_id",
    "servicenow_instance",
    "application_client_id",
    "stage",
    "owner",
    "admin_instruction",
    "privacy_note",
    "provider",
    "profile",
    "agent_slug",
    "agent_id",
    "binding_sha256",
)
IDENTITY_CSV_BINDING_HEADERS = (
    "Tenant ID",
    "Environment ID",
    "ServiceNow Instance",
    "Provider",
    "Profile",
    "Target Agent Slug",
    "Target Agent ID",
    "Binding SHA256",
)
IDENTITY_ENTRA_CSV_HEADERS = (
    "Format Version",
    "Instructions",
    "Client ID",
    "User Claim",
    *IDENTITY_CSV_BINDING_HEADERS,
)
IDENTITY_SERVICENOW_CSV_HEADERS = (
    "Format Version",
    "Record",
    "Content",
    "Client ID",
    "User Claim",
    "ServiceNow User Field",
    *IDENTITY_CSV_BINDING_HEADERS,
    "Candidate Set SHA256",
)
IDENTITY_WORKBOOK_STEPS_HEADER_ROW = 1
IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW = 2
IDENTITY_WORKBOOK_TABLE_HEADER_ROW = 12
IDENTITY_WORKBOOK_FIRST_DATA_ROW = 13
IDENTITY_WORKBOOK_VISIBLE_CONTEXT = (
    ("Target Agent", "target_agent"),
    ("Tenant ID", "tenant_id"),
    ("Environment ID", "environment_id"),
    ("ServiceNow Instance", "servicenow_instance"),
    ("Application Client ID", "application_client_id"),
    ("Administrator", "owner"),
)
IDENTITY_WORKBOOK_COLUMNS = (
    "record_type",
    "context_key",
    "context_value",
    "token_claim_name",
    "servicenow_user_field",
    "token_claim_editable",
    "servicenow_user_field_editable",
)
IDENTITY_WORKBOOK_CONTEXT_FIELDS = (
    "purpose",
    "target_agent",
    "tenant_id",
    "environment_id",
    "servicenow_instance",
    "application_client_id",
    "stage",
    "owner",
    "admin_instruction",
    "privacy_note",
)
IDENTITY_WORKBOOK_BOUND_CONTEXT_FIELDS = (
    "target_agent",
    "tenant_id",
    "environment_id",
    "servicenow_instance",
    "application_client_id",
    "stage",
)
IDENTITY_WORKBOOK_PENDING_CLIENT_ID = "not-yet-available"
IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID = "<provided-by-entra-admin>"
IDENTITY_WORKBOOK_MAX_CANDIDATES = 20
IDENTITY_WORKBOOK_TEMPLATE_ENTRA = Path(
    "src/skills/connect/shared/templates/"
    "servicenow-identity-claims-entra.xlsx"
)
IDENTITY_WORKBOOK_TEMPLATE_SERVICENOW = Path(
    "src/skills/connect/shared/templates/"
    "servicenow-identity-mapping-servicenow.xlsx"
)
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
CUSTOM_IDENTITY_REFERENCE_URLS = (
    (
        "HR provisioning reference",
        "https://review.learn.microsoft.com/en-us/entra/identity/"
        "app-provisioning/plan-cloud-hr-provision",
    ),
    (
        "Directory sync reference",
        "https://review.learn.microsoft.com/en-us/entra/identity/"
        "hybrid/connect/reference-connect-sync-attributes-synchronized",
    ),
    (
        "JWT claims reference",
        "https://review.learn.microsoft.com/en-us/entra/identity-platform/"
        "jwt-claims-customization",
    ),
)
SERVICENOW_ENTRA_SETUP_INSTRUCTIONS_URL = (
    "https://review.learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/declarative-agent-servicenow-hr-it"
    "?branch=main#task-1-register-an-application-in-microsoft-entra-id-"
    "for-oidc-integration-with-servicenow"
)
SERVICENOW_OIDC_SETUP_INSTRUCTIONS_URL = (
    "https://review.learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/declarative-agent-servicenow-hr-it"
    "?branch=main#task-2-register-oidc-provider-in-servicenow"
)
SERVICENOW_NON_EMAIL_USER_MATCH_URL = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/declarative-agent-servicenow-hr-it"
    "?branch=main#match-users-when-the-servicenow-user-id-isnt-an-email-or-upn"
)
IDENTITY_WORKBOOK_TEMP_PREFIX = ".identity-"
IDENTITY_WORKBOOK_TEMP_SUFFIX = ".tmp.xlsx"
WINDOWS_LEGACY_MAX_PATH = 260
SERVICENOW_CONNECTOR_APP_ID = "c26b24aa-7874-4e06-ad55-7d06b1f79b63"
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


def _identity_workbook_openpyxl():
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Protection

    return (
        Workbook,
        load_workbook,
        Alignment,
        Font,
        PatternFill,
        Protection,
    )
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
    test_prompt="List my open HR cases",
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
    test_prompt="List my open IT tickets",
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
                f"Open {ACTIVE_PROFILE.agent_display_name} in Copilot Studio"
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


def _identity_workbook_context_values(
    context: dict[str, Any],
    expected_identity: dict[str, str],
    *,
    application_client_id: str | None,
    stage: str,
) -> dict[str, str]:
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity workbook stage is invalid.")
    return {
        "purpose": (
            "Confirm employee identity token claims and map one selected "
            "claim to a ServiceNow user field"
        ),
        "target_agent": ACTIVE_PROFILE.agent_display_name,
        "tenant_id": expected_identity["tenantId"],
        "environment_id": expected_identity["environmentId"],
        "servicenow_instance": expected_identity["instanceName"],
        "application_client_id": (
            application_client_id or IDENTITY_WORKBOOK_PENDING_CLIENT_ID
        ),
        "stage": stage,
        "owner": (
            "Microsoft Entra administrator"
            if stage == "entra"
            else "ServiceNow admin or security_admin"
        ),
        "admin_instruction": (
            "Enter one employee-identity token claim per editable claim cell."
            if stage == "entra"
            else (
                "Enter the matching ServiceNow user field on exactly one "
                "candidate row."
            )
        ),
        "privacy_note": (
            "Do not add employee values, tokens, secrets, passwords, "
            "or free-form notes."
        ),
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agent_slug": _agent_slug(context),
        "agent_id": str(context["agent"]["id"]),
    }


def _identity_file_binding(context_values: dict[str, str]) -> dict[str, str]:
    return {
        "tenantId": context_values["tenant_id"],
        "environmentId": context_values["environment_id"],
        "instanceName": context_values["servicenow_instance"],
        "provider": context_values.get("provider", PROVIDER_KEY),
        "profile": context_values.get("profile", PROFILE_KEY),
        "agentSlug": context_values.get(
            "agent_slug",
            context_values.get("target_agent", ""),
        ),
        "agentId": context_values.get("agent_id", ""),
    }


def _identity_file_binding_sha256(
    context_values: dict[str, str],
) -> str:
    return _canonical_json_hash(_identity_file_binding(context_values))


def _entra_admin_instruction() -> str:
    instruction = (
        "1. Sign into the Microsoft Entra admin center as a Global "
        "Administrator or Cloud App Administrator. "
        "2. Go to **Applications** then **App registrations**. "
        "3. If an Entra app already exists: "
        "3.1 The Entra administrator needs to share the Application (client) "
        "ID and one selected User Claim name with the maker. "
        "4. If a new app should be created: "
        "4.1 The Entra administrator needs to register the app and add user "
        "claims. "
        "4.1.1 Select **New registration.** "
        "4.1.2 In the new registration form, fill in the following fields: "
        "4.1.2.1 **Name:** Any name that represents the purpose of the app "
        "registration. "
        "4.1.2.2 **Redirect URL:** Not needed. "
        "4.1.3 Choose **Register** to complete creation of the new app "
        "registration. "
        "4.1.4 Select **Token configuration** then **Add optional claim** to "
        "add claims settings. "
        "4.1.5 Select **Token type** as **Access** and choose the following "
        "claims: "
        "4.1.5.1 *Aud* - for audience validation. "
        "4.1.5.2 *Email* - addressable email for the user. "
        "4.1.5.3 *UPN* - an identifier for the user. "
        "4.1.6 Select **Add** to complete adding the claims. "
        "4.1.7 If this is the first time OpenID Connect is being set up using "
        "claims such as email or UPN, a confirmation screen may ask to enable "
        "Microsoft Graph permissions. If shown, check the box and select "
        "**Add**. "
        "4.2 Then share the Application (client) ID and one selected User "
        "Claim name with the maker. "
        "4.3 If the selected User Claim is not email or Microsoft Entra UPN: "
        "4.3.1 The Entra administrator needs to perform the extra work "
        "documented at "
        f"{SERVICENOW_NON_EMAIL_USER_MATCH_URL}. "
        "4.3.2 The Entra administrator needs to share the Application "
        "(client) ID and one selected User Claim name with the maker. "
        "The User Claim field accepts a claim name only, never a personal "
        "identifier or claim value. The *Aud* claim is only for access-token "
        "audience validation and must not be entered as the selected User "
        "Claim."
    )
    if "\r" in instruction or "\n" in instruction or "<br>" in instruction.lower():
        raise ServiceNowConnectError(
            "The Entra administrator instruction must be a single line."
        )
    return instruction


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


def _identity_requirement_question() -> dict[str, Any]:
    return {
        "header": "Which identifier should ServiceNow use?",
        "question": (
            "**Purpose**\n"
            "Choose the type of employee identifier ServiceNow uses to match "
            "a signed-in user. Do not provide an employee value.\n\n"
            "**Owner**\n"
            "Maker, with the Entra or ServiceNow admin if needed.\n\n"
            "**Action**\n"
            "Select the identifier type already intended for this ServiceNow "
            "integration. If it is not known, ask the Entra or ServiceNow "
            "admin and choose `Not sure` for now.\n\n"
            "**Expected result**\n"
            "A routing choice only. The Entra workbook is generated after a "
            "specific identifier type is confirmed."
        ),
        "options": [
            {"label": config["label"]}
            for config in IDENTITY_REQUIREMENT_CHOICES.values()
        ],
        "allowFreeformInput": False,
    }


def _identity_requirement_choices() -> list[dict[str, str]]:
    return [
        {
            "label": config["label"],
            "choice": choice,
        }
        for choice, config in IDENTITY_REQUIREMENT_CHOICES.items()
    ]


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
            "immutable for this lifecycle; preserve any issued workbook and "
            "start an explicit fresh lifecycle before changing it."
        )
    legacy_workbook = _identity_workbook_path(context, stage="entra")
    if legacy_workbook.exists():
        raise ServiceNowConnectError(
            "An Entra handoff workbook already exists for this lifecycle. "
            "Continue that frozen legacy handoff; do not attach a new routing "
            "choice or rewrite the issued workbook."
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


def _identity_requirement_category(
    requirement: dict[str, Any] | None,
) -> str:
    if not isinstance(requirement, dict):
        return "standard"
    category = str(requirement.get("category") or "")
    return category if category in {"standard", "custom", "template"} else "standard"


def _identity_workbook_path(
    context: dict[str, Any],
    *,
    stage: str,
) -> Path:
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity workbook stage is invalid.")
    return (
        _lifecycle_state_path(context).parent
        / (
            "servicenow-identity-mapping-servicenow.xlsx"
            if stage == "servicenow"
            else "servicenow-identity-claims-entra.xlsx"
        )
    )


def _identity_csv_path(
    context: dict[str, Any],
    *,
    stage: str,
) -> Path:
    return _identity_workbook_path(context, stage=stage).with_suffix(".csv")


def _identity_workbook_template_sha256(stage: str) -> str:
    template = SOLUTION_ROOT / (
        IDENTITY_WORKBOOK_TEMPLATE_ENTRA
        if stage == "entra"
        else IDENTITY_WORKBOOK_TEMPLATE_SERVICENOW
    )
    if not template.is_file():
        raise ServiceNowConnectError(
            f"Required identity workbook template is missing: {template}"
        )
    return hashlib.sha256(template.read_bytes()).hexdigest().upper()


def _identity_workbook_versioned_path(
    canonical_path: Path,
    *,
    template_sha256: str,
) -> Path:
    return canonical_path.with_name(
        f"{canonical_path.stem}.template-"
        f"{template_sha256[:12].lower()}{canonical_path.suffix}"
    )


def _identity_workbook_template_marker(path: Path) -> str | None:
    _Workbook, load_workbook, *_styles = _identity_workbook_openpyxl()
    try:
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except Exception:
        return None
    try:
        identifier = str(workbook.properties.identifier or "")
    finally:
        workbook.close()
    prefix = "ess-servicenow-template-sha256:"
    if not identifier.casefold().startswith(prefix):
        return None
    value = identifier[len(prefix) :].strip().upper()
    return value if re.fullmatch(r"[0-9A-F]{64}", value) else None


def _identity_workbook_has_admin_values(
    path: Path,
    *,
    stage: str,
) -> bool:
    _Workbook, load_workbook, *_styles = _identity_workbook_openpyxl()
    try:
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except Exception:
        return True
    try:
        if (
            stage == "entra"
            and IDENTITY_ENTRA_HANDOFF_SHEET in workbook.sheetnames
        ):
            sheet = workbook[IDENTITY_ENTRA_HANDOFF_SHEET]
            return bool(
                str(sheet["B2"].value or "").strip()
                or str(sheet["C2"].value or "").strip()
            )
        if IDENTITY_WORKBOOK_SHEET not in workbook.sheetnames:
            return True
        sheet = workbook[IDENTITY_WORKBOOK_SHEET]
        if stage == "entra":
            client_id_cell = sheet.cell(6, 2)
            client_id_value = str(client_id_cell.value or "").strip()
            if (
                not client_id_cell.protection.locked
                and client_id_value
                not in {
                    "",
                    IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
                    IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
                }
            ):
                return True
        for row in range(
            IDENTITY_WORKBOOK_FIRST_DATA_ROW,
            sheet.max_row + 1,
        ):
            column = 1 if stage == "entra" else 2
            if str(sheet.cell(row, column).value or "").strip():
                return True
        return False
    finally:
        workbook.close()


def _identity_workbook_fill(editable: bool) -> PatternFill:
    *_workbook_types, PatternFill, _Protection = (
        _identity_workbook_openpyxl()
    )
    return PatternFill(
        fill_type="solid",
        fgColor="FFF2CC" if editable else "E7E6E6",
    )


def _universal_entra_workbook_steps(
    context_values: dict[str, str],
) -> list[tuple[str, str]]:
    instance = context_values["servicenow_instance"]
    return [
        (
            "Before you start",
            "Use the tenant, ServiceNow instance, Application Client ID, and "
            "Maker-confirmed identifier type "
            "`<identity-requirement-label>` shown here. "
            "Follow the if/go-to branches below; verify first and change only "
            "settings that are missing or incorrect.",
        ),
        (
            "Security",
            "Return this workbook with the non-secret Application (client) ID "
            "when requested and actual claim names only. Do not include "
            "employee values, tokens, passwords, secrets, certificates, or "
            "keys.",
        ),
        (
            "Setup instructions",
            SERVICENOW_ENTRA_SETUP_INSTRUCTIONS_URL,
        ),
        (
            "1",
            "Open https://entra.microsoft.com/ and sign in to the Worksheet "
            "tenant with an authorized admin account.",
        ),
        (
            "2",
            "Go to Entra ID -> Applications -> App registrations. If "
            "Worksheet has a read-only Application Client ID, find the exact "
            f"app with that ID for `{instance}`. If the cell is yellow, search "
            "the tenant and instance for the correct existing app before "
            "creating a duplicate. If the intended app cannot be identified, "
            "choose Not yet.",
        ),
        (
            "3",
            "Choose the current-state branch. If the exact existing app and "
            "the intended identity-claim configuration are already correct, "
            "go to 4A. If the app exists but any Task 1 app or claim setting "
            "needs repair, go to 4B. If no correct app exists, go to 4C.1. If "
            "the state cannot be determined, choose Not yet.",
        ),
        (
            "4A",
            "Existing healthy app: if the Worksheet Application Client ID cell "
            "is yellow, copy this app's exact Overview Application (client) ID "
            "into that cell. If the cell is read-only, verify it matches "
            "exactly and do not change it. Do not rename or reconfigure the "
            "app. If a read-only ID has no exact app, choose Not yet. Go to "
            "Step 7 for final actual-issuance verification.",
        ),
        (
            "4B",
            "Existing app needs repair: if the Worksheet Application Client ID "
            "cell is yellow, copy this app's exact Overview Application "
            "(client) ID into that cell. If the cell is read-only, verify it "
            "matches exactly and do not change it. Repair only missing or "
            "incorrect applicable Task 1 settings in Steps 5-6; do not create a "
            "duplicate. If a read-only ID has no exact app, choose Not yet. Go "
            "to Step 5.",
        ),
        (
            "4C.1",
            "New app: use this branch only when the Worksheet Application "
            "Client ID cell is yellow and no correct app exists. Select New "
            "registration. If the ID is read-only and no exact app exists, "
            "choose Not yet instead of creating a replacement.",
        ),
        (
            "4C.2",
            f"In Name, enter a purposeful name such as `ServiceNow OIDC - "
            f"{instance}`.",
        ),
        (
            "4C.3",
            "For Supported account types, select Accounts in this "
            "organizational directory only (Single tenant).",
        ),
        (
            "4C.4",
            "Leave Redirect URI blank for this app registration.",
        ),
        (
            "4C.5",
            "Select Register.",
        ),
        (
            "4C.6",
            "On Overview, copy Application (client) ID into the yellow "
            "Worksheet Application Client ID cell. Do not use Object ID or "
            "Directory (tenant) ID. Continue to Step 5.",
        ),
        (
            "5",
            "Use the visible Maker-confirmed identifier type from Before you "
            "start. Email or UPN -> go to 6A. Pay ID / employee ID or Other "
            "non-email identifier -> go to 6B. If the admin determines the "
            "real type differs from the visible confirmed type, or the type is "
            "still unknown, choose Not yet and coordinate with the Maker; do "
            "not silently switch branches or guess.",
        ),
        (
            "6A",
            "Standard Email/UPN: review Token configuration and the current "
            "Access-token optional claims. If the approved Email/UPN and "
            "audience configuration is already correct, go to 6A.3. `aud` is "
            "for audience validation only and is never entered as an employee "
            "identity claim. Step 7 performs final actual issuance verification.",
        ),
        (
            "6A.1",
            "Only if the required standard claim is missing and tenant policy "
            "allows it, open Token configuration -> Add optional claim, select "
            "Access, choose the applicable `email` or `upn` claim and the "
            "approved audience option when required, then select Add.",
        ),
        (
            "6A.2",
            "If a permission prompt appears from the Step 6A.1 change, review "
            "the required Microsoft Graph permissions, select the required "
            "checkbox, and select Add.",
        ),
        (
            "6A.3",
            "Standard branch complete: go to Step 7. Do not perform the custom "
            "6B branch.",
        ),
        (
            "6B",
            "Custom/non-email identifier: confirm the approved directory "
            "attribute already exists and is populated for every intended "
            "ServiceNow user. Only if population is missing, use the "
            "customer's approved existing provisioning, directory sync, or "
            "direct administration method.",
        ),
        (
            "6B.1",
            "If the customer uses cloud HR provisioning, open "
            "https://learn.microsoft.com/en-us/entra/identity/"
            "app-provisioning/plan-cloud-hr-provision and use that approved "
            "method only when population is missing. Do not require it when "
            "another approved method supplies the attribute.",
        ),
        (
            "6B.2",
            "If the customer uses directory sync, open "
            "https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/"
            "reference-connect-sync-attributes-synchronized and confirm the "
            "chosen attribute is synchronized. Do not require directory sync "
            "when another approved method supplies the attribute.",
        ),
        (
            "6B.3",
            "Review the real ServiceNow resource app's custom-claim "
            "configuration and prior evidence. Only if the claim is missing, "
            "open https://learn.microsoft.com/en-us/entra/identity-platform/"
            "jwt-claims-customization and configure the applicable approved "
            "claim policy. Preserve the required non-email representation, "
            "including leading zeros or case. Step 7 performs the final "
            "actual issuance verification.",
        ),
        (
            "6B.4",
            "If the custom claim needs `acceptMappedClaims`, use it only for a "
            "single-tenant app with tenant and security approval. Otherwise "
            "use the approved custom-signing route when required. Confirm "
            "ServiceNow validation metadata/JWKS, issuer, and token version "
            "compatibility; application-specific metadata may require an "
            "`appid` query. Do not blindly change metadata, token version, "
            "keys, or policy.",
        ),
        (
            "6B.5",
            "Custom branch complete: go to Step 7. Do not perform the standard "
            "6A Add optional claim branch.",
        ),
        (
            "7",
            "Using an organization-approved method, verify actual claim "
            "issuance for this ServiceNow resource app, not Microsoft Graph. "
            "Verify `aud` identifies this app, but do not enter `aud` as an "
            "employee identity candidate or return the token. If issuance or "
            "format cannot be confirmed, choose Not yet.",
        ),
        (
            "8",
            "On Worksheet, enter each actual verified employee-identity claim "
            "name in one yellow Token Claim Name cell. Do not enter employee "
            "values or guess a claim name.",
        ),
        (
            "Return",
            "Check that Worksheet contains the requested Application Client "
            "ID and at least one actual Token Claim Name. Save and return this "
            "one workbook.",
        ),
    ]


def _checked_in_entra_workbook_steps() -> list[tuple[str, str]]:
    template = SOLUTION_ROOT / IDENTITY_WORKBOOK_TEMPLATE_ENTRA
    if not template.is_file():
        raise ServiceNowConnectError(
            f"Required identity workbook template is missing: {template}"
        )
    _Workbook, load_workbook, *_styles = _identity_workbook_openpyxl()
    try:
        workbook = load_workbook(
            template,
            read_only=False,
            data_only=False,
            keep_links=False,
        )
    except Exception as exc:
        raise ServiceNowConnectError(
            f"The checked-in Entra identity workbook template could not be "
            f"read: {template}"
        ) from exc
    try:
        if workbook.sheetnames == [
            IDENTITY_ENTRA_HANDOFF_SHEET,
            IDENTITY_WORKBOOK_METADATA_SHEET,
        ]:
            handoff = workbook[IDENTITY_ENTRA_HANDOFF_SHEET]
            instruction = str(handoff["A2"].value or "")
            if instruction != _entra_admin_instruction():
                raise ServiceNowConnectError(
                    "The checked-in Entra handoff instruction changed."
                )
            return [("1", instruction)]
        if workbook.sheetnames != [
            IDENTITY_WORKBOOK_STEPS_SHEET,
            IDENTITY_WORKBOOK_SHEET,
            IDENTITY_WORKBOOK_METADATA_SHEET,
        ]:
            raise ServiceNowConnectError(
                "The checked-in Entra identity workbook template sheet "
                "contract changed."
            )
        steps = workbook[IDENTITY_WORKBOOK_STEPS_SHEET]
        return [
            (
                str(steps.cell(row, 1).value or ""),
                str(steps.cell(row, 2).value or ""),
            )
            for row in range(
                IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW,
                steps.max_row + 1,
            )
        ]
    finally:
        workbook.close()


def _identity_workbook_steps(
    *,
    stage: str,
    context_values: dict[str, str],
    missing_items: list[tuple[str, str]],
    identity_requirement: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    instance = context_values["servicenow_instance"]
    client_id = context_values["application_client_id"]
    requirement_category = _identity_requirement_category(
        identity_requirement
    )
    if stage == "entra":
        return _checked_in_entra_workbook_steps()
        known_client_id = client_id not in {
            IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
            IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
        }
        steps = [
            (
                "Before you start",
                "Use the tenant and ServiceNow instance shown on Worksheet. "
                "Reuse the correct single-tenant ServiceNow OIDC app when it "
                "exists. Create one only when no correct app exists. Complete "
                "only the numbered actions below.",
            ),
            (
                "Security",
                "Return this workbook with claim names and, only if requested, "
                "the non-secret Application (client) ID. Do not include "
                "tokens, employee values, passwords, secrets, certificates, "
                "or keys.",
            ),
        ]
        missing_suffixes = {suffix for suffix, _label in missing_items}
        if missing_suffixes:
            steps.append(
                (
                    "Additional setup",
                    "Only the actions that still need verification are listed "
                    "below. Items already verified are intentionally omitted.",
                )
            )
        steps.append(
            (
                "Setup instructions",
                SERVICENOW_ENTRA_SETUP_INSTRUCTIONS_URL,
            )
        )
        action_number = 1

        def add_action(action: str) -> None:
            nonlocal action_number
            steps.append((str(action_number), action))
            action_number += 1

        if client_id == IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID:
            add_action(
                "Open https://entra.microsoft.com/ and sign in to the "
                "Worksheet tenant with an authorized admin account. Go to "
                "Entra ID -> "
                "Applications -> App registrations and look for the correct "
                "ServiceNow OIDC app for `<service-now-instance>`. If the "
                "Worksheet Application Client ID is read-only and no exact ID "
                "matches, stop and ask the Maker."
            )
        elif known_client_id:
            add_action(
                "Open https://entra.microsoft.com/ and sign in to the "
                "Worksheet tenant with an authorized admin account. Go to "
                "Entra ID -> "
                "Applications -> App registrations and verify the read-only "
                f"Application Client ID `{client_id}` matches the correct "
                f"ServiceNow OIDC app for `{instance}`. If no exact ID matches, "
                "stop and ask the Maker."
            )
        else:
            add_action(
                "Open https://entra.microsoft.com/ and sign in to the "
                "Worksheet tenant with an authorized admin account. Go to "
                "Entra ID -> "
                "Applications -> App registrations and look for the correct "
                f"ServiceNow OIDC app for `{instance}` before creating a "
                "duplicate."
            )
        if "APP" in missing_suffixes and not known_client_id:
            add_action(
                "Only when no correct existing app is found, select New "
                "registration."
            )
            add_action(
                "In Name, enter a purposeful name, for example "
                "`ServiceNow OIDC - <service-now-instance>`. Do not rename a "
                "healthy existing app."
            )
            add_action(
                "For Supported account types, select Accounts in this "
                "organizational directory only (Single tenant)."
            )
            add_action(
                "Leave Redirect URI blank for this app registration."
            )
            add_action("Select Register.")
            add_action(
                "On Overview, copy Application (client) ID into the yellow "
                "Worksheet Application Client ID cell. Do not use Object ID or "
                "Directory (tenant) ID."
            )
        custom_identity_needed = (
            "CLAIMS" in missing_suffixes
            and requirement_category in {"custom", "template"}
        )
        if custom_identity_needed:
            steps.extend(
                [
                    (
                        "Custom task 1",
                        "Confirm the intended non-email ServiceNow identifier "
                        "and the approved Entra directory attribute that "
                        "supplies it. Verify the attribute already exists and "
                        "is populated for every intended ServiceNow user. Only "
                        "if it is missing, use the customer's approved existing "
                        "provisioning, directory sync, or direct administration "
                        "method. Do not return values.",
                    ),
                    (
                        "Custom provisioning reference",
                        "If the customer uses cloud HR provisioning, open "
                        "https://learn.microsoft.com/en-us/entra/identity/"
                        "app-provisioning/plan-cloud-hr-provision and use that "
                        "approved existing method only when population is "
                        "missing. Do not require this method when the customer "
                        "uses directory sync or approved direct administration.",
                    ),
                    (
                        "Custom directory sync reference",
                        "If the customer uses directory sync, open "
                        "https://learn.microsoft.com/en-us/entra/identity/"
                        "hybrid/connect/reference-connect-sync-attributes-"
                        "synchronized and confirm the chosen attribute is "
                        "synchronized. Do not require directory sync when "
                        "another approved method already supplies the attribute.",
                    ),
                    (
                        "Custom task 2",
                        "Verify the real ServiceNow resource app already emits "
                        "the approved attribute as a JWT claim. Only if the "
                        "claim is missing, open "
                        "https://learn.microsoft.com/en-us/entra/"
                        "identity-platform/jwt-claims-customization and "
                        "configure the applicable approved claim policy. "
                        "Preserve the required non-email representation, "
                        "including leading zeros or case when applicable. "
                        "Return only the actual claim name in the workbook.",
                    ),
                    (
                        "Custom identity safety",
                        "If this claim needs `acceptMappedClaims`, use it only "
                        "for a single-tenant app with tenant and security "
                        "approval. Otherwise use the approved custom-signing "
                        "route when required. Confirm the ServiceNow validation "
                        "metadata/JWKS, issuer, and token version are compatible "
                        "before completion; application-specific metadata may "
                        "require an `appid` query. Do not blindly change "
                        "metadata, token version, keys, or policy. Choose Not "
                        "yet until the compatible route is confirmed.",
                    ),
                ]
            )
        if "SCOPE" in missing_suffixes:
            application_id_uri = (
                f"`api://{client_id}`"
                if known_client_id
                else "`api://<client-id>`"
            )
            add_action(
                "In Expose an API, set Application ID URI to "
                f"{application_id_uri}. "
                + (
                    ""
                    if known_client_id
                    else (
                        "Replace `<client-id>` with the real GUID in the "
                        "Worksheet Application Client ID cell. "
                    )
                )
                + "Ensure the delegated `user_impersonation` scope is enabled."
            )
        if "PREAUTH" in missing_suffixes:
            add_action(
                "Under Authorized client applications, add ServiceNow "
                "connector ID `c26b24aa-7874-4e06-ad55-7d06b1f79b63` and "
                "select `user_impersonation`."
            )
        new_app_claim_configuration = (
            "CLAIMS" in missing_suffixes
            and "APP" in missing_suffixes
            and not known_client_id
            and requirement_category != "custom"
        )
        if new_app_claim_configuration:
            add_action(
                "Open Token configuration -> Add optional claim. For Token "
                "type, select Access."
            )
            add_action(
                "Select the appropriate employee identity claim, such as "
                "`email` or `upn` when applicable, then select Add. For a "
                "custom employee claim, use the tenant-approved claims policy."
            )
            add_action(
                "If a permission prompt appears, review the required Microsoft "
                "Graph permissions, select the required checkbox, and select "
                "Add."
            )
        if "CLAIMS" in missing_suffixes:
            if (
                requirement_category != "custom"
                and (
                    not new_app_claim_configuration
                    or client_id == IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID
                )
            ):
                add_action(
                    "For an existing app, open Token configuration -> "
                    "Optional claims and review the Access claim names. Review "
                    "the tenant-approved policy for custom claims. Do not "
                    "change configuration unless a specific missing setting "
                    "is confirmed."
                )
            add_action(
                "Using an organization-approved method, verify actual issuance "
                "for this ServiceNow OIDC app, not Microsoft Graph. Verify "
                "`aud` identifies this app, but do not enter `aud` as an "
                "employee identity candidate. Do not copy or return the token."
            )
            add_action(
                "On Worksheet, enter each verified employee-identity claim "
                "name in one yellow Token Claim Name cell. Do not enter `aud` "
                "or employee values."
            )
            steps.append(
                (
                    "Return",
                    "Check that Worksheet contains the requested Application "
                    "Client ID and at least one Token Claim Name. Save and "
                    "return this one workbook. If actual claim issuance cannot "
                    "be verified, choose Not yet instead of guessing.",
                )
            )
        else:
            steps.append(
                (
                    "Return",
                    "Save and return this workbook after the listed actions "
                    "are complete. Return no token, secret, password, or "
                    "employee value.",
                )
            )
        return steps
    steps = [
        (
            "Before you start",
            "Use the ServiceNow instance, tenant, Application Client ID, and "
            "locked Entra-confirmed claim names shown on Worksheet. Reuse or "
            "repair only the registry entry for this exact client ID.",
        ),
        (
            "Security",
            "Return only this workbook with one ServiceNow internal field "
            "name. Do not return employee values, tokens, passwords, client "
            "secrets, certificates, or private keys.",
        ),
        (
            "Setup instructions",
            SERVICENOW_OIDC_SETUP_INSTRUCTIONS_URL,
        ),
        (
            "1",
            "Open https://<service-now-instance>.service-now.com/ and sign in "
            "to the ServiceNow instance shown on Worksheet.",
        ),
        (
            "2",
            "From the profile menu, select Elevate roles, select "
            "`security_admin`, and select Update. If this role is unavailable "
            "or unauthorized, stop and choose Not yet.",
        ),
        (
            "3",
            "Select All in the top navigation bar.",
        ),
        (
            "4",
            "Search for `OAuth` in the dropdown navigation menu.",
        ),
        (
            "5",
            "Select System OAuth -> Application Registry. If Application "
            "Registry is absent after authorized elevation, stop and choose "
            "Not yet.",
        ),
        (
            "6",
            "Look for an existing Application Registry entry whose Client ID "
            "is `<application-client-id>`. Reuse or repair only that exact "
            "entry; do not update an unrelated provider or create a duplicate.",
        ),
        (
            "7",
            "If no registry entry has this exact Client ID, select New.",
        ),
        (
            "8",
            "Only when creating a new registry entry, select Configure an OIDC "
            "provider to verify ID tokens. For the exact existing registry "
            "entry, open its existing form.",
        ),
        (
            "9",
            "In Name, enter a meaningful ESS provider name, for example "
            "`Microsoft Entra ID - ESS Copilot`.",
        ),
        (
            "10",
            "Set Client ID to `<application-client-id>`, the Application "
            "(client) ID confirmed in Task 1.",
        ),
        (
            "11",
            "Client secret is unused for this flow. If ServiceNow requires a "
            "value, enter a tenant-approved non-secret unused placeholder "
            "locally. Never create or return an Entra client secret.",
        ),
        (
            "12",
            "Set Entity state to Active.",
        ),
        (
            "13",
            "Set Scope Restriction to Broadly scoped.",
        ),
        (
            "14",
            "In OAuth OIDC Provider Configuration, select the lookup/search "
            "icon and inspect the existing provider configurations. Select the "
            "one for this integration. Select New only when no suitable "
            "configuration exists and the instance's reuse or uniqueness "
            "rules allow it. Do not duplicate or modify another integration.",
        ),
        (
            "15",
            "Set OIDC Provider (Provider Name) to a name representing the "
            "Microsoft Entra tenant shown on Worksheet.",
        ),
        (
            "16",
            "Set Metadata URL to "
            "`https://login.microsoftonline.com/<customer-tenant-id>/"
            ".well-known/openid-configuration`.",
        ),
        (
            "17",
            "Set Cache lifespan to `120`.",
        ),
        (
            "18",
            "Set Application to Global.",
        ),
        (
            "19",
            "On Worksheet, review the locked Token Claim Name candidates. "
            "These are claim names, not claim IDs, GUIDs, or employee values.",
        ),
        (
            "20",
            "In a separate browser tab, open User Administration -> Users "
            "(`sys_user`) and verify which candidate has a matching value on "
            "an Active user. Keep the OIDC form open. Do not copy an employee "
            "value into the workbook.",
        ),
        (
            "21",
            "In the same lookup tab, use Dictionary or Configure Dictionary to "
            "read the matching `sys_user` internal column name, such as "
            "`email`, `user_name`, `employee_number`, or an approved custom "
            "`u_*` column. Do not use a display label or dotted `table.field` "
            "name.",
        ),
        (
            "22",
            "Fill the yellow ServiceNow User Field cell beside exactly one "
            "locked claim. Leave every other User Field cell blank.",
        ),
        (
            "23",
            "If no candidate safely matches one `sys_user` internal column, "
            "choose Not yet and ask the Entra administrator to confirm an "
            "approved custom employee claim. Do not guess or edit claim cells.",
        ),
        (
            "24",
            "Return to the OIDC configuration tab. Set User Claim to the exact "
            "selected locked Token Claim Name and User Field to the exact "
            "adjacent ServiceNow internal column name, preserving case.",
        ),
        (
            "25",
            "Disable JTI verification.",
        ),
        (
            "26",
            "Submit the OIDC provider configuration, select it on the parent "
            "registry entry, then save or update the parent entry.",
        ),
        (
            "27",
            "Verify one real signed-in user resolves to one matching Active "
            "`sys_user` record. Do not create a user for this validation.",
        ),
        (
            "28",
            "Confirm with the Maker that Task 1 already preauthorized the "
            "ServiceNow connector application "
            "`c26b24aa-7874-4e06-ad55-7d06b1f79b63`. If not, choose Not yet; "
            "the ServiceNow admin does not add this cloud permission.",
        ),
        (
            "Return",
            "Save and return this one workbook after the registry, provider, "
            "selected mapping, and one Active-user resolution are verified.",
        ),
    ]
    if requirement_category in {"custom", "template"}:
        custom_warning = (
            "Custom identity validation",
            "This integration uses a custom or non-email identity claim. If "
            "the Entra policy uses custom signing, the ServiceNow and Entra "
            "admins must confirm a compatible validation metadata/JWKS route, "
            "issuer, and token version before completion. Application-specific "
            "metadata may require an `appid` query. Do not assume the default "
            "tenant metadata works, automatically switch token versions, "
            "enable keys, or change policy. Choose Not yet until the supported "
            "route is confirmed.",
        )
        insert_at = next(
            index
            for index, (label, _action) in enumerate(steps)
            if label == "17"
        )
        steps.insert(insert_at, custom_warning)
    return steps


def _validate_identity_workbook_path_budget(
    path: Path,
    *,
    platform_name: str | None = None,
) -> None:
    platform = platform_name or os.name
    if platform != "nt":
        return
    absolute_path = Path(os.path.abspath(path))
    if len(str(absolute_path)) >= WINDOWS_LEGACY_MAX_PATH:
        raise ServiceNowConnectError(
            "The identity workbook target path is too long for supported "
            "Windows file APIs. Move the workspace to a shorter path before "
            f"retrying: {absolute_path}"
        )
    temporary_candidate = absolute_path.parent / (
        f"{IDENTITY_WORKBOOK_TEMP_PREFIX}"
        f"{'x' * 8}{IDENTITY_WORKBOOK_TEMP_SUFFIX}"
    )
    if len(str(temporary_candidate)) >= WINDOWS_LEGACY_MAX_PATH:
        raise ServiceNowConnectError(
            "The identity workbook temporary path is too long for supported "
            "Windows file APIs. Move the workspace to a shorter path before "
            f"retrying: {absolute_path.parent}"
        )


def _author_identity_workbook(
    path: Path,
    *,
    context_values: dict[str, str],
    stage: str,
    candidates: list[str],
    steps: list[tuple[str, str]],
) -> Path:
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity workbook stage is invalid.")
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_identity_workbook_path_budget(path)
    (
        Workbook,
        _load_workbook,
        Alignment,
        Font,
        PatternFill,
        Protection,
    ) = _identity_workbook_openpyxl()
    workbook = Workbook()
    steps_sheet = workbook.active
    steps_sheet.title = IDENTITY_WORKBOOK_STEPS_SHEET
    for column, header in enumerate(
        ("Step", "Action"),
        start=1,
    ):
        cell = steps_sheet.cell(
            IDENTITY_WORKBOOK_STEPS_HEADER_ROW,
            column,
        )
        cell.value = header
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(fill_type="solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.protection = Protection(locked=True)
    for row_number, step in enumerate(
        steps,
        start=IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW,
    ):
        for column, value in enumerate(step, start=1):
            cell = steps_sheet.cell(row_number, column)
            cell.value = value
            urls = (
                [
                    url.rstrip(".,;")
                    for url in re.findall(r"https://[^\s`]+", value)
                ]
                if column == 2 and isinstance(value, str)
                else []
            )
            if len(urls) == 1:
                cell.hyperlink = urls[0]
                cell.style = "Hyperlink"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.protection = Protection(locked=True)
        action_text = str(step[1] if len(step) > 1 else "")
        steps_sheet.row_dimensions[row_number].height = max(
            30,
            min(105, 18 * (1 + len(action_text) // 95)),
        )
    steps_sheet.freeze_panes = (
        f"A{IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW}"
    )
    steps_sheet.auto_filter.ref = (
        f"A{IDENTITY_WORKBOOK_STEPS_HEADER_ROW}:"
        f"B{IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW + len(steps) - 1}"
    )
    steps_sheet.column_dimensions["A"].width = 18
    steps_sheet.column_dimensions["B"].width = 105
    steps_sheet.protection.sheet = True
    steps_sheet.protection.formatCells = True
    steps_sheet.protection.formatColumns = True
    steps_sheet.protection.formatRows = True
    steps_sheet.protection.insertColumns = True
    steps_sheet.protection.insertRows = True
    steps_sheet.protection.deleteColumns = True
    steps_sheet.protection.deleteRows = True
    steps_sheet.protection.sort = True
    steps_sheet.protection.autoFilter = False
    steps_sheet.protection.selectLockedCells = False
    steps_sheet.protection.selectUnlockedCells = False

    sheet = workbook.create_sheet(IDENTITY_WORKBOOK_SHEET)
    sheet.merge_cells("A1:B1")
    sheet["A1"] = (
        "Microsoft Entra administrator handoff"
        if stage == "entra"
        else "ServiceNow administrator handoff"
    )
    sheet["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    sheet["A1"].fill = PatternFill(fill_type="solid", fgColor="1F4E78")
    sheet["A1"].protection = Protection(locked=True)
    for row_number, (label, key) in enumerate(
        IDENTITY_WORKBOOK_VISIBLE_CONTEXT,
        start=2,
    ):
        sheet.cell(row_number, 1).value = label
        sheet.cell(row_number, 2).value = context_values[key]
        sheet.cell(row_number, 1).font = Font(bold=True)
        for column in (1, 2):
            editable_context = (
                stage == "entra"
                and key == "application_client_id"
                and context_values[key]
                in {
                    IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
                    IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
                }
                and column == 2
            )
            sheet.cell(row_number, column).fill = _identity_workbook_fill(
                editable_context
            )
            sheet.cell(row_number, column).protection = Protection(
                locked=not editable_context
            )
    sheet.merge_cells("A9:B10")
    sheet["A9"] = (
        "Edit only the yellow cells. Locked cells were supplied by the "
        "previous stage or by the skill."
    )
    sheet["A9"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet["A9"].font = Font(italic=True)
    sheet["A9"].fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
    sheet["A9"].protection = Protection(locked=True)
    sheet.cell(
        IDENTITY_WORKBOOK_TABLE_HEADER_ROW,
        1,
    ).value = "Token Claim Name"
    sheet.cell(
        IDENTITY_WORKBOOK_TABLE_HEADER_ROW,
        2,
    ).value = "ServiceNow User Field"
    for cell in sheet[IDENTITY_WORKBOOK_TABLE_HEADER_ROW]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(fill_type="solid", fgColor="1F4E78")
        cell.protection = Protection(locked=True)
    candidate_count = (
        IDENTITY_WORKBOOK_MAX_CANDIDATES
        if stage == "entra"
        else len(candidates)
    )
    for index in range(candidate_count):
        claim = candidates[index] if index < len(candidates) else ""
        claim_editable = stage == "entra"
        field_editable = stage == "servicenow"
        row = IDENTITY_WORKBOOK_FIRST_DATA_ROW + index
        sheet.cell(row, 1).value = claim
        sheet.cell(row, 2).value = ""
        for column, editable in (
            (1, claim_editable),
            (2, field_editable),
        ):
            sheet.cell(row, column).protection = Protection(
                locked=not editable
            )
            sheet.cell(row, column).fill = _identity_workbook_fill(editable)
    sheet.freeze_panes = f"A{IDENTITY_WORKBOOK_FIRST_DATA_ROW}"
    sheet.auto_filter.ref = (
        f"A{IDENTITY_WORKBOOK_TABLE_HEADER_ROW}:"
        f"B{IDENTITY_WORKBOOK_FIRST_DATA_ROW + candidate_count - 1}"
    )
    sheet.column_dimensions["A"].width = 36
    sheet.column_dimensions["B"].width = 38
    sheet.row_dimensions[9].height = 36
    sheet.protection.sheet = True
    sheet.protection.formatCells = True
    sheet.protection.formatColumns = True
    sheet.protection.formatRows = True
    sheet.protection.insertColumns = True
    sheet.protection.insertRows = True
    sheet.protection.deleteColumns = True
    sheet.protection.deleteRows = True
    sheet.protection.sort = True
    sheet.protection.autoFilter = False
    sheet.protection.selectLockedCells = True
    sheet.protection.selectUnlockedCells = False

    metadata = workbook.create_sheet(IDENTITY_WORKBOOK_METADATA_SHEET)
    metadata.sheet_state = "hidden"
    metadata.append(list(IDENTITY_WORKBOOK_COLUMNS))
    for key in IDENTITY_WORKBOOK_CONTEXT_FIELDS:
        metadata.append(
            [
                "context",
                key,
                context_values[key],
                "",
                "",
                "no",
                "no",
            ]
        )
    for index in range(candidate_count):
        claim = candidates[index] if index < len(candidates) else ""
        metadata.append(
            [
                "candidate",
                "",
                "",
                claim,
                "",
                "yes" if stage == "entra" else "no",
                "yes" if stage == "servicenow" else "no",
            ]
        )
    for row in metadata.iter_rows():
        for cell in row:
            cell.protection = Protection(locked=True)
    metadata.protection.sheet = True
    workbook.calculation.fullCalcOnLoad = False
    workbook.calculation.forceFullCalc = False
    workbook.calculation.calcMode = "manual"
    temporary_path: Path | None = None
    try:
        try:
            handle, temporary = tempfile.mkstemp(
                prefix=IDENTITY_WORKBOOK_TEMP_PREFIX,
                suffix=IDENTITY_WORKBOOK_TEMP_SUFFIX,
                dir=path.parent,
            )
        except OSError as exc:
            raise ServiceNowConnectError(
                "Could not create the identity workbook temporary file in "
                f"the target directory: {path.parent}"
            ) from exc
        os.close(handle)
        temporary_path = Path(temporary)
        workbook.save(temporary_path)
        os.replace(temporary_path, path)
    finally:
        workbook.close()
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return path


def _ensure_identity_workbook(
    context: dict[str, Any],
    *,
    context_values: dict[str, str],
    stage: str,
    candidates: list[str],
    steps: list[tuple[str, str]],
    missing_items: list[tuple[str, str]],
    identity_requirement: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    path = _identity_workbook_path(context, stage=stage)
    template_sha256 = _identity_workbook_template_sha256(stage)
    if path.is_file():
        if _identity_workbook_has_admin_values(
            path,
            stage=stage,
        ):
            if (
                _identity_workbook_template_marker(path)
                == template_sha256
            ):
                return path, "preserved-existing"
            versioned_path = _identity_workbook_versioned_path(
                path,
                template_sha256=template_sha256,
            )
            if versioned_path.is_file():
                if (
                    _identity_workbook_template_marker(versioned_path)
                    == template_sha256
                ):
                    return versioned_path, "preserved-versioned"
                if _identity_workbook_has_admin_values(
                    versioned_path,
                    stage=stage,
                ):
                    raise ServiceNowConnectError(
                        "The current-template versioned identity workbook has "
                        "administrator values but invalid template provenance. "
                        "Preserve both workbooks and return the expected "
                        "versioned file after resolving the mismatch."
                    )
            elif versioned_path.exists():
                raise ServiceNowConnectError(
                    "The versioned identity workbook path is not a regular "
                    "file."
                )
            _write_identity_workbook(
                versioned_path,
                context_values=context_values,
                stage=stage,
                candidates=candidates,
                steps=steps,
                missing_items=missing_items,
                identity_requirement=identity_requirement,
            )
            return versioned_path, "generated-versioned"
    elif path.exists():
        raise ServiceNowConnectError(
            "The identity mapping workbook path is not a regular file."
        )
    _write_identity_workbook(
        path,
        context_values=context_values,
        stage=stage,
        candidates=candidates,
        steps=steps,
        missing_items=missing_items,
        identity_requirement=identity_requirement,
    )
    return path, "generated"


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


def _existing_known_entra_client_id(
    context: dict[str, Any],
    state: dict[str, Any],
) -> str | None:
    lifecycle_client_id = _known_entra_client_id(state)
    receipt_client_id = None
    receipt = state.get("evidence", {}).get("identityClaimCandidates")
    if isinstance(receipt, dict):
        try:
            validated = _validated_claim_candidates(context, state)
            receipt_client_id = normalize_client_id(
                str(validated.get("applicationClientId") or "")
            )
        except ServiceNowConnectError:
            receipt_client_id = None
    if (
        lifecycle_client_id
        and receipt_client_id
        and lifecycle_client_id != receipt_client_id
    ):
        raise ServiceNowConnectError(
            "The confirmed Application client IDs in the active lifecycle "
            "and identity workbook receipt disagree."
        )
    return lifecycle_client_id or receipt_client_id


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


def _has_historical_entra_graph_pass(
    state: dict[str, Any],
) -> bool:
    outcomes = _entra_checkpoint_outcomes(state)
    return all(
        outcomes.get(suffix) == "Passed"
        for suffix in ENTRA_CHECKPOINT_SUFFIXES
    )


def _entra_handoff_mode(
    outcomes: dict[str, str],
) -> str:
    required = set(ENTRA_CHECKPOINT_SUFFIXES)
    missing = {
        suffix
        for suffix in required
        if outcomes.get(suffix) not in {"Passed", "Manual"}
    }
    if not missing:
        return "complete"
    if missing == {"CLAIMS"}:
        return "claim-only"
    if missing and missing != required:
        return "delta"
    return "full-setup"


def _entra_missing_items(
    outcomes: dict[str, str],
) -> list[tuple[str, str]]:
    labels = {
        "APP": "Entra application registration",
        "CLAIMS": (
            "employee identity claim workbook and actual claim emission"
        ),
        "SCOPE": "Application ID URI and `user_impersonation` scope",
        "PREAUTH": "ServiceNow connector pre-authorization",
    }
    return [
        (suffix, labels[suffix])
        for suffix in ENTRA_CHECKPOINT_SUFFIXES
        if outcomes.get(suffix) not in {"Passed", "Manual"}
    ]


def _entra_admin_guide_path() -> Path:
    return (
        SOLUTION_ROOT
        / CONTRACT_PATH.parent
        / "actions"
        / "guide-entra-registration.md"
    ).resolve()


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


def _copy_template_cell(source, target) -> None:
    target.value = source.value
    if source.has_style:
        target._style = copy.copy(source._style)
    target.number_format = source.number_format
    target.font = copy.copy(source.font)
    target.fill = copy.copy(source.fill)
    target.border = copy.copy(source.border)
    target.alignment = copy.copy(source.alignment)
    target.protection = copy.copy(source.protection)
    if source.hyperlink is not None:
        target.hyperlink = copy.copy(source.hyperlink)


def _save_identity_workbook_atomic(workbook, path: Path) -> None:
    temporary_path: Path | None = None
    try:
        try:
            handle, temporary = tempfile.mkstemp(
                prefix=IDENTITY_WORKBOOK_TEMP_PREFIX,
                suffix=IDENTITY_WORKBOOK_TEMP_SUFFIX,
                dir=path.parent,
            )
        except OSError as exc:
            raise ServiceNowConnectError(
                "Could not create the identity workbook temporary file in "
                f"the target directory: {path.parent}"
            ) from exc
        os.close(handle)
        temporary_path = Path(temporary)
        workbook.save(temporary_path)
        os.replace(temporary_path, path)
    finally:
        workbook.close()
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _template_steps(
    steps_sheet,
    *,
    stage: str,
    context_values: dict[str, str],
    missing_items: list[tuple[str, str]],
    identity_requirement: dict[str, Any] | None = None,
) -> list[tuple[str, str, Any]]:
    rows = [
        (
            str(steps_sheet.cell(row, 1).value or ""),
            str(steps_sheet.cell(row, 2).value or ""),
            steps_sheet.cell(row, 2).hyperlink,
        )
        for row in range(
            IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW,
            steps_sheet.max_row + 1,
        )
    ]
    requirement_category = _identity_requirement_category(
        identity_requirement
    )
    if stage == "servicenow":
        if len(rows) not in {3, 33}:
            raise ServiceNowConnectError(
                "The checked-in ServiceNow identity workbook template has an "
                "unsupported Steps contract."
            )
        if len(rows) == 3 and [row[0] for row in rows] != [
            "Overview",
            "Entra handoff",
            "1",
        ]:
            raise ServiceNowConnectError(
                "The checked-in ServiceNow identity workbook template "
                "opening rows changed."
            )
        if not context_values.get("confirmed_user_claim_name"):
            if len(rows) == 3:
                raise ServiceNowConnectError(
                    "ServiceNow workbook generation requires one confirmed "
                    "User Claim name."
                )
            replacements = {
                "<service-now-instance>": context_values[
                    "servicenow_instance"
                ],
                "<customer-tenant-id>": context_values["tenant_id"],
                "<application-client-id>": context_values[
                    "application_client_id"
                ],
            }
            result = []
            for label, action, hyperlink in rows:
                if (
                    label == "Custom identity validation"
                    and requirement_category != "custom"
                ):
                    continue
                for placeholder, value in replacements.items():
                    action = action.replace(placeholder, value)
                if hyperlink is not None:
                    hyperlink = copy.copy(hyperlink)
                    target = str(hyperlink.target or "")
                    for placeholder, value in replacements.items():
                        target = target.replace(placeholder, value)
                    hyperlink.target = target
                result.append((label, action, hyperlink))
            return result
        confirmed_claim_name = _safe_identity_name(
            context_values.get("confirmed_user_claim_name"),
            "confirmed_user_claim_name",
        )
        return [
            (
                "Overview",
                "ServiceNow administrator handoff",
                None,
            ),
            (
                "Entra handoff",
                _servicenow_entra_handoff_summary(
                    application_client_id=context_values[
                        "application_client_id"
                    ],
                    confirmed_claim_name=confirmed_claim_name,
                ),
                None,
            ),
            (
                "1",
                _servicenow_admin_instruction(
                    application_client_id=context_values[
                        "application_client_id"
                    ],
                    confirmed_claim_name=confirmed_claim_name,
                    tenant_id=context_values["tenant_id"],
                ),
                None,
            )
        ]
    if len(rows) != 26:
        raise ServiceNowConnectError(
            "The checked-in Entra identity workbook template has an "
            "unsupported Steps contract."
        )
    client_id = context_values["application_client_id"]
    known_client_id = client_id not in {
        IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
        IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
    }
    replacements = {
        "<service-now-instance>": context_values["servicenow_instance"],
        "<application-client-id>": client_id,
        "<client-id>": client_id if known_client_id else "<client-id>",
    }
    result = []
    for label, action, hyperlink in rows:
        for placeholder, value in replacements.items():
            action = action.replace(placeholder, value)
        if hyperlink is not None:
            hyperlink = copy.copy(hyperlink)
            target = str(hyperlink.target or "")
            for placeholder, value in replacements.items():
                target = target.replace(placeholder, value)
            hyperlink.target = target
        result.append((label, action, hyperlink))
    return result

    if len(rows) != 27:
        raise ServiceNowConnectError(
            "The checked-in Entra identity workbook template has an "
            "unsupported Steps contract."
        )
    missing = {suffix for suffix, _label in missing_items}
    selected_indexes = [0, 1]
    if missing:
        selected_indexes.append(2)
    selected_indexes.extend((3, 4))
    client_id = context_values["application_client_id"]
    known_client_id = client_id not in {
        IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
        IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
    }
    if "APP" in missing and not known_client_id:
        selected_indexes.extend((5, 6, 7, 8, 9, 10))
    if "CLAIMS" in missing and requirement_category == "custom":
        selected_indexes.extend((11, 12, 13, 14, 15))
    category_indexes = {
        "SCOPE": 16,
        "PREAUTH": 17,
    }
    for suffix in ("SCOPE", "PREAUTH"):
        if suffix in missing:
            selected_indexes.append(category_indexes[suffix])
    new_app_claim_configuration = (
        "CLAIMS" in missing
        and "APP" in missing
        and not known_client_id
        and requirement_category != "custom"
    )
    if new_app_claim_configuration:
        selected_indexes.extend((18, 19, 20))
    if "CLAIMS" in missing:
        if (
            requirement_category != "custom"
            and not new_app_claim_configuration
        ):
            selected_indexes.append(23)
        selected_indexes.extend((24, 25))
    selected_indexes.append(26)
    instance = context_values["servicenow_instance"]
    result: list[tuple[str, str, Any]] = []
    number = 1
    for index in selected_indexes:
        label, action, hyperlink = rows[index]
        action = (
            action.replace("<service-now-instance>", instance)
            .replace("<application-client-id>", client_id)
            .replace("<client-id>", client_id if known_client_id else "<client-id>")
        )
        if 4 <= index <= 10 or 16 <= index <= 25:
            label = str(number)
            number += 1
        result.append((label, action, hyperlink))
    return result


def _servicenow_admin_instruction(
    *,
    application_client_id: str,
    confirmed_claim_name: str,
    tenant_id: str,
) -> str:
    instruction = (
        "ServiceNow administrator configuration steps (PM-spec flowchart): "
        "1. Sign in to the ServiceNow instance that needs to be integrated "
        "with the Employee Self-Service agent. "
        "2. Elevate access permissions using **Elevate role**. "
        "3. Select **All** in the top navigation bar. "
        "4. Search for \"OAuth\" in the search box within the dropdown "
        "navigation menu. "
        "5. Select **System OAuth -> Application Registry** from the search "
        "results; if this option is not visible, you do not have sufficient "
        "privileges. "
        "6. Check whether an OAuth provider already exists with the "
        "auto-supplied confirmed Application (client) ID "
        f"`{application_client_id}`. "
        "6.1 YES - Reuse the existing provider: "
        "6.1.1 Verify that the existing provider Client ID is "
        f"`{application_client_id}`. "
        "6.1.2 Ensure the user claim is the same as that configured by Entra "
        "(Entra-confirmed User Claim: "
        f"`{confirmed_claim_name}`). "
        "6.1.3 Identify the ServiceNow User Field that stores the same "
        "identity key. Do not apply the new-provider settings below to this "
        "YES/reuse branch. "
        "6.2 NO - Create a new OAuth provider app: "
        "6.2.1 Check whether an OAuth OIDC Provider Configuration exists. "
        "6.2.1.1 YES - Reuse it. "
        "6.2.1.2 NO - Create a new one. "
        "6.2.2 New-provider application configuration: "
        "Name: Enter a meaningful name that identifies this OIDC provider as "
        "created for the Employee Self-Service agent; "
        "Client ID: Auto-populated from the confirmed Microsoft Entra "
        f"administrator result: `{application_client_id}`; "
        "Client secret: This value is not used and can be any value; "
        "Scope Restriction: Broadly scoped; "
        "OAuth OIDC provider configuration: When a new configuration is "
        "required, select the search icon, choose **New** in the search "
        "popup, and complete these fields: "
        "OIDC Provider: Enter a name that represents the Microsoft Entra "
        "tenant from Task 1 above; "
        "OIDC Metadata URL: "
        f"`login.microsoftonline.com/{tenant_id}/"
        ".well-known/openid-configuration`; "
        "use the Microsoft Entra tenant ID from Task 1 above; "
        "OIDC Configuration Cache Life Span: 120; "
        "Application: Global; "
        "User Claim: Auto-populated from the confirmed Entra administrator "
        f"result: `{confirmed_claim_name}`; "
        "User Field: The ServiceNow administrator must confirm and enter the "
        "actual `sys_user` field that stores the same identity key; do not "
        "use a default; "
        "Enable JTI claim verification: disabled; "
        "select **Submit** and update the OIDC Entity form. "
        "7. Final identity-key checks for the selected or created provider: "
        "ii. Ensure the user claim is the same as that configured by Entra "
        "(Entra-confirmed User Claim: "
        f"`{confirmed_claim_name}`). "
        "iii. Confirm the ServiceNow User Field stores the same identity key."
    )
    if "\r" in instruction or "\n" in instruction or "<br>" in instruction.lower():
        raise ServiceNowConnectError(
            "The ServiceNow administrator instruction must be a single line."
        )
    return instruction


def _servicenow_entra_handoff_summary(
    *,
    application_client_id: str,
    confirmed_claim_name: str,
) -> str:
    return (
        "Entra handoff - Client ID: "
        f"`{application_client_id}`  "
        "User Claim: "
        f"`{confirmed_claim_name}`"
    )


def _entra_handoff_metadata_values(
    context_values: dict[str, str],
) -> dict[str, str]:
    return {
        "format_version": IDENTITY_ENTRA_HANDOFF_FORMAT,
        **{
            key: context_values[key]
            for key in IDENTITY_WORKBOOK_CONTEXT_FIELDS
        },
        "provider": context_values.get("provider", PROVIDER_KEY),
        "profile": context_values.get("profile", PROFILE_KEY),
        "agent_slug": context_values.get(
            "agent_slug",
            context_values.get("target_agent", ""),
        ),
        "agent_id": context_values.get("agent_id", ""),
        "binding_sha256": _identity_file_binding_sha256(context_values),
    }


def _write_entra_handoff_workbook(
    workbook,
    *,
    template: Path,
    path: Path,
    context_values: dict[str, str],
) -> None:
    if workbook.sheetnames != [
        IDENTITY_ENTRA_HANDOFF_SHEET,
        IDENTITY_WORKBOOK_METADATA_SHEET,
    ]:
        raise ServiceNowConnectError(
            "The checked-in Entra handoff template sheet contract changed."
        )
    handoff = workbook[IDENTITY_ENTRA_HANDOFF_SHEET]
    metadata = workbook[IDENTITY_WORKBOOK_METADATA_SHEET]
    headers = tuple(
        str(handoff.cell(1, column).value or "")
        for column in range(1, 4)
    )
    if headers != IDENTITY_ENTRA_HANDOFF_HEADERS:
        raise ServiceNowConnectError(
            "The checked-in Entra handoff headers changed."
        )
    if handoff.max_row != 2 or handoff.max_column != 3:
        raise ServiceNowConnectError(
            "The checked-in Entra handoff visible shape changed."
        )
    instruction_cell = handoff["A2"]
    instruction_cell.value = _entra_admin_instruction()
    instruction_cell.hyperlink = SERVICENOW_NON_EMAIL_USER_MATCH_URL
    application_client_id = context_values["application_client_id"]
    handoff["B2"] = (
        ""
        if application_client_id
        in {
            IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
            IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
        }
        else application_client_id
    )
    handoff["C2"] = ""
    *_unused, Protection = _identity_workbook_openpyxl()
    for cell in (handoff["B2"], handoff["C2"]):
        cell.fill = _identity_workbook_fill(True)
        cell.protection = Protection(locked=False)
    metadata_values = _entra_handoff_metadata_values(context_values)
    if (
        metadata.max_row != len(IDENTITY_ENTRA_METADATA_KEYS) + 1
        or metadata.max_column != 2
        or tuple(
            str(metadata.cell(1, column).value or "")
            for column in range(1, 3)
        )
        != ("key", "value")
    ):
        raise ServiceNowConnectError(
            "The checked-in Entra handoff metadata shape changed."
        )
    for row_number, key in enumerate(
        IDENTITY_ENTRA_METADATA_KEYS,
        start=2,
    ):
        if str(metadata.cell(row_number, 1).value or "") != key:
            raise ServiceNowConnectError(
                "The checked-in Entra handoff metadata keys changed."
            )
        metadata.cell(row_number, 2).value = metadata_values[key]
    workbook.properties.identifier = (
        "ess-servicenow-template-sha256:"
        + hashlib.sha256(template.read_bytes()).hexdigest().upper()
    )
    workbook.active = handoff
    _save_identity_workbook_atomic(workbook, path)


def _write_identity_workbook(
    path: Path,
    *,
    context_values: dict[str, str],
    stage: str,
    candidates: list[str],
    steps: list[tuple[str, str]],
    missing_items: list[tuple[str, str]] | None = None,
    identity_requirement: dict[str, Any] | None = None,
) -> Path:
    del steps
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity workbook stage is invalid.")
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_identity_workbook_path_budget(path)
    template = SOLUTION_ROOT / (
        IDENTITY_WORKBOOK_TEMPLATE_ENTRA
        if stage == "entra"
        else IDENTITY_WORKBOOK_TEMPLATE_SERVICENOW
    )
    if not template.is_file():
        raise ServiceNowConnectError(
            f"Required identity workbook template is missing: {template}"
        )
    try:
        with zipfile.ZipFile(template) as archive:
            if any(
                name.startswith("xl/externalLinks/")
                or name.endswith("vbaProject.bin")
                for name in archive.namelist()
            ):
                raise ServiceNowConnectError(
                    "The checked-in identity workbook template contains "
                    "unsupported external links or macros."
                )
    except zipfile.BadZipFile as exc:
        raise ServiceNowConnectError(
            "The checked-in identity workbook template is not a valid XLSX "
            f"file: {template}"
        ) from exc
    _Workbook, load_workbook, *_styles = _identity_workbook_openpyxl()
    try:
        workbook = load_workbook(
            template,
            read_only=False,
            data_only=False,
            keep_links=False,
        )
    except Exception as exc:
        raise ServiceNowConnectError(
            f"The checked-in identity workbook template could not be read: "
            f"{template}"
        ) from exc
    try:
        if (
            stage == "entra"
            and workbook.sheetnames
            == [
                IDENTITY_ENTRA_HANDOFF_SHEET,
                IDENTITY_WORKBOOK_METADATA_SHEET,
            ]
        ):
            _write_entra_handoff_workbook(
                workbook,
                template=template,
                path=path,
                context_values=context_values,
            )
            workbook.close()
            workbook = None
            return path
        if workbook.sheetnames != [
            IDENTITY_WORKBOOK_STEPS_SHEET,
            IDENTITY_WORKBOOK_SHEET,
            IDENTITY_WORKBOOK_METADATA_SHEET,
        ]:
            raise ServiceNowConnectError(
                "The checked-in identity workbook template sheet contract "
                "changed."
            )
        steps_sheet = workbook[IDENTITY_WORKBOOK_STEPS_SHEET]
        sheet = workbook[IDENTITY_WORKBOOK_SHEET]
        metadata = workbook[IDENTITY_WORKBOOK_METADATA_SHEET]
        selected_steps = _template_steps(
            steps_sheet,
            stage=stage,
            context_values=context_values,
            missing_items=missing_items or [],
            identity_requirement=identity_requirement,
        )
        step_styles = [
            (
                copy.copy(steps_sheet.cell(row, 1)._style),
                copy.copy(steps_sheet.cell(row, 2)._style),
            )
            for row in range(
                IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW,
                steps_sheet.max_row + 1,
            )
        ]
        base_styles = step_styles[0]
        steps_sheet.delete_rows(
            IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW,
            steps_sheet.max_row
            - IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW
            + 1,
        )
        for offset, (label, action, hyperlink) in enumerate(selected_steps):
            row = IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW + offset
            steps_sheet.cell(row, 1).value = label
            steps_sheet.cell(row, 2).value = action
            steps_sheet.cell(row, 1)._style = copy.copy(base_styles[0])
            steps_sheet.cell(row, 2)._style = copy.copy(base_styles[1])
            if hyperlink is not None:
                steps_sheet.cell(row, 2).hyperlink = copy.copy(hyperlink)
            height_cap = 105
            if (
                stage == "servicenow"
                and action.startswith(
                    "ServiceNow administrator configuration steps"
                )
            ):
                height_cap = 409.5
            steps_sheet.row_dimensions[row].height = max(
                30,
                min(height_cap, 18 * (1 + len(action) // 95)),
            )
        steps_sheet.auto_filter.ref = (
            f"A{IDENTITY_WORKBOOK_STEPS_HEADER_ROW}:"
            f"B{IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW + len(selected_steps) - 1}"
        )
        if (
            stage == "servicenow"
            and context_values.get("confirmed_user_claim_name")
        ):
            steps_sheet.freeze_panes = (
                f"A{IDENTITY_WORKBOOK_STEPS_FIRST_DATA_ROW + 2}"
            )
        for row_number, (_label, key) in enumerate(
            IDENTITY_WORKBOOK_VISIBLE_CONTEXT,
            start=2,
        ):
            sheet.cell(row_number, 2).value = context_values[key]
        *_unused, Protection = _identity_workbook_openpyxl()
        client_id_cell = sheet.cell(6, 2)
        client_id_editable = (
            stage == "entra"
            and context_values["application_client_id"]
            in {
                IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
                IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
            }
        )
        client_id_cell.fill = _identity_workbook_fill(client_id_editable)
        client_id_cell.protection = Protection(locked=not client_id_editable)
        first_candidate = IDENTITY_WORKBOOK_FIRST_DATA_ROW
        template_candidate_count = max(0, sheet.max_row - first_candidate + 1)
        desired_count = (
            IDENTITY_WORKBOOK_MAX_CANDIDATES
            if stage == "entra"
            else len(candidates)
        )
        if desired_count <= 0:
            raise ServiceNowConnectError(
                "ServiceNow identity mapping requires at least one candidate."
            )
        candidate_style = [
            copy.copy(sheet.cell(first_candidate, column)._style)
            for column in (1, 2)
        ]
        if desired_count > template_candidate_count:
            sheet.insert_rows(
                first_candidate + template_candidate_count,
                desired_count - template_candidate_count,
            )
        elif desired_count < template_candidate_count:
            sheet.delete_rows(
                first_candidate + desired_count,
                template_candidate_count - desired_count,
            )
        for index in range(desired_count):
            row = first_candidate + index
            sheet.cell(row, 1).value = (
                candidates[index] if index < len(candidates) else ""
            )
            sheet.cell(row, 2).value = ""
            for column in (1, 2):
                sheet.cell(row, column)._style = copy.copy(
                    candidate_style[column - 1]
                )
        sheet.auto_filter.ref = (
            f"A{IDENTITY_WORKBOOK_TABLE_HEADER_ROW}:"
            f"B{first_candidate + desired_count - 1}"
        )
        for row_number, key in enumerate(
            IDENTITY_WORKBOOK_CONTEXT_FIELDS,
            start=2,
        ):
            metadata.cell(row_number, 3).value = context_values[key]
        metadata_first = 2 + len(IDENTITY_WORKBOOK_CONTEXT_FIELDS)
        template_metadata_candidates = max(
            0,
            metadata.max_row - metadata_first + 1,
        )
        metadata_style = [
            copy.copy(metadata.cell(metadata_first, column)._style)
            for column in range(1, len(IDENTITY_WORKBOOK_COLUMNS) + 1)
        ]
        if desired_count > template_metadata_candidates:
            metadata.insert_rows(
                metadata_first + template_metadata_candidates,
                desired_count - template_metadata_candidates,
            )
        elif desired_count < template_metadata_candidates:
            metadata.delete_rows(
                metadata_first + desired_count,
                template_metadata_candidates - desired_count,
            )
        for index in range(desired_count):
            row = metadata_first + index
            values = [
                "candidate",
                "",
                "",
                candidates[index] if index < len(candidates) else "",
                "",
                "yes" if stage == "entra" else "no",
                "yes" if stage == "servicenow" else "no",
            ]
            for column, value in enumerate(values, start=1):
                metadata.cell(row, column).value = value
                metadata.cell(row, column)._style = copy.copy(
                    metadata_style[column - 1]
                )
        workbook.properties.identifier = (
            "ess-servicenow-template-sha256:"
            + hashlib.sha256(template.read_bytes()).hexdigest().upper()
        )
        workbook.active = workbook[IDENTITY_WORKBOOK_STEPS_SHEET]
        _save_identity_workbook_atomic(workbook, path)
        workbook = None
    finally:
        if workbook is not None:
            workbook.close()
    return path


def _identity_csv_binding_values(
    context_values: dict[str, str],
) -> dict[str, str]:
    return {
        "Tenant ID": context_values["tenant_id"],
        "Environment ID": context_values["environment_id"],
        "ServiceNow Instance": context_values["servicenow_instance"],
        "Provider": context_values["provider"],
        "Profile": context_values["profile"],
        "Target Agent Slug": context_values["agent_slug"],
        "Target Agent ID": context_values["agent_id"],
        "Binding SHA256": _identity_file_binding_sha256(context_values),
    }


def _write_identity_csv(
    path: Path,
    *,
    context_values: dict[str, str],
    stage: str,
    candidates: list[str],
    candidate_set_sha256: str | None = None,
) -> Path:
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity CSV stage is invalid.")
    path.parent.mkdir(parents=True, exist_ok=True)
    binding_values = _identity_csv_binding_values(context_values)
    if stage == "entra":
        client_id = context_values["application_client_id"]
        row = {
            "Format Version": IDENTITY_ENTRA_HANDOFF_FORMAT,
            "Instructions": _entra_admin_instruction(),
            "Client ID": (
                ""
                if client_id
                in {
                    IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
                    IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
                }
                else client_id
            ),
            "User Claim": "",
            **binding_values,
        }
        headers = IDENTITY_ENTRA_CSV_HEADERS
        rows = [row]
    else:
        if len(candidates) != 1:
            raise ServiceNowConnectError(
                "ServiceNow CSV generation requires exactly one confirmed "
                "User Claim name."
            )
        claim_name = _safe_identity_name(
            candidates[0],
            "confirmed_user_claim_name",
        )
        client_id = normalize_client_id(
            context_values["application_client_id"]
        )
        candidate_hash = str(candidate_set_sha256 or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", candidate_hash):
            raise ServiceNowConnectError(
                "ServiceNow CSV generation requires the confirmed candidate "
                "set hash."
            )
        common = {
            "Format Version": IDENTITY_SERVICENOW_CSV_FORMAT,
            "Client ID": client_id,
            "User Claim": claim_name,
            **binding_values,
            "Candidate Set SHA256": candidate_hash,
        }
        rows = [
            {
                **common,
                "Record": "Entra handoff",
                "Content": _servicenow_entra_handoff_summary(
                    application_client_id=client_id,
                    confirmed_claim_name=claim_name,
                ),
                "ServiceNow User Field": "",
            },
            {
                **common,
                "Record": "Steps",
                "Content": _servicenow_admin_instruction(
                    application_client_id=client_id,
                    confirmed_claim_name=claim_name,
                    tenant_id=context_values["tenant_id"],
                ),
                "ServiceNow User Field": "",
            },
        ]
        headers = IDENTITY_SERVICENOW_CSV_HEADERS
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        with temporary_path.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=list(headers),
                lineterminator="\r\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return path


def _identity_csv_has_admin_values(
    path: Path,
    *,
    stage: str,
) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error):
        return True
    if stage == "entra":
        return bool(
            rows
            and (
                str(rows[0].get("Client ID") or "").strip()
                or str(rows[0].get("User Claim") or "").strip()
            )
        )
    return any(
        str(row.get("ServiceNow User Field") or "").strip()
        for row in rows
    )


def _ensure_identity_csv(
    context: dict[str, Any],
    *,
    context_values: dict[str, str],
    stage: str,
    candidates: list[str],
    candidate_set_sha256: str | None = None,
) -> tuple[Path, str]:
    path = _identity_csv_path(context, stage=stage)
    if path.is_file() and _identity_csv_has_admin_values(
        path,
        stage=stage,
    ):
        return path, "preserved-existing"
    if path.exists() and not path.is_file():
        raise ServiceNowConnectError(
            "The identity CSV path is not a regular file."
        )
    _write_identity_csv(
        path,
        context_values=context_values,
        stage=stage,
        candidates=candidates,
        candidate_set_sha256=candidate_set_sha256,
    )
    return path, "generated"


def _validate_identity_csv_binding(
    row: dict[str, str],
    *,
    expected_context: dict[str, str],
) -> None:
    expected = _identity_csv_binding_values(expected_context)
    if any(str(row.get(key) or "").strip() != value for key, value in expected.items()):
        raise ServiceNowConnectError(
            "The identity CSV binding does not match the active tenant, "
            "environment, instance, provider, profile, or agent."
        )


def _parse_identity_csv(
    path: Path,
    *,
    stage: str,
    expected_context: dict[str, str],
    expected_candidates: list[str] | None = None,
    expected_candidate_set_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            expected_headers = (
                IDENTITY_ENTRA_CSV_HEADERS
                if stage == "entra"
                else IDENTITY_SERVICENOW_CSV_HEADERS
            )
            if tuple(reader.fieldnames or ()) != expected_headers:
                raise ServiceNowConnectError(
                    "The identity CSV headers changed."
                )
            rows = list(reader)
    except ServiceNowConnectError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ServiceNowConnectError(
            "The identity CSV could not be read safely."
        ) from exc
    if any(
        "\r" in str(value or "") or "\n" in str(value or "")
        for row in rows
        for value in row.values()
    ):
        raise ServiceNowConnectError(
            "Identity CSV fields must not contain embedded line breaks."
        )
    if stage == "entra":
        if len(rows) != 1:
            raise ServiceNowConnectError(
                "The Entra identity CSV must contain exactly one data record."
            )
        row = rows[0]
        if (
            row["Format Version"] != IDENTITY_ENTRA_HANDOFF_FORMAT
            or row["Instructions"] != _entra_admin_instruction()
        ):
            raise ServiceNowConnectError(
                "The Entra identity CSV format or instructions changed."
            )
        _validate_identity_csv_binding(
            row,
            expected_context=expected_context,
        )
        visible_client_id = row["Client ID"].strip()
        expected_client_id = expected_context["application_client_id"]
        if not visible_client_id:
            raise ServiceNowConnectError(
                "Enter the exact Application (client) ID in the Entra "
                "CSV Client ID field."
            )
        else:
            resolved_client_id = normalize_client_id(visible_client_id)
            if (
                expected_client_id
                != IDENTITY_WORKBOOK_PENDING_CLIENT_ID
                and resolved_client_id
                != normalize_client_id(expected_client_id)
            ):
                raise ServiceNowConnectError(
                    "The Entra CSV Client ID does not match the active "
                    "lifecycle."
                )
        claim_name = _safe_identity_name(
            row["User Claim"],
            "user_claim",
        )
        if claim_name.casefold() == "aud":
            raise ServiceNowConnectError(
                "The aud audience claim cannot be selected as the "
                "user-matching User Claim."
            )
        return {
            "candidates": [claim_name],
            "applicationClientId": resolved_client_id,
            "selection": None,
            "sheetProtected": False,
        }
    if len(rows) != 2 or [row["Record"] for row in rows] != [
        "Entra handoff",
        "Steps",
    ]:
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV must contain exactly one Entra "
            "handoff record and one Steps record."
        )
    for row in rows:
        if row["Format Version"] != IDENTITY_SERVICENOW_CSV_FORMAT:
            raise ServiceNowConnectError(
                "The ServiceNow identity CSV format changed."
            )
        _validate_identity_csv_binding(
            row,
            expected_context=expected_context,
        )
    client_ids = {
        normalize_client_id(row["Client ID"])
        for row in rows
    }
    if len(client_ids) != 1:
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV contains conflicting Client IDs."
        )
    resolved_client_id = client_ids.pop()
    if resolved_client_id != normalize_client_id(
        expected_context["application_client_id"]
    ):
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV Client ID does not match the active "
            "lifecycle."
        )
    claims = {
        _safe_identity_name(row["User Claim"], "user_claim")
        for row in rows
    }
    if len(claims) != 1:
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV contains conflicting User Claims."
        )
    claim_name = claims.pop()
    if claim_name.casefold() == "aud":
        raise ServiceNowConnectError(
            "The aud audience claim cannot be selected as the user-matching "
            "User Claim."
        )
    if expected_candidates != [claim_name]:
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV User Claim does not match the "
            "Entra-confirmed selection."
        )
    candidate_hashes = {
        str(row["Candidate Set SHA256"] or "").strip()
        for row in rows
    }
    if candidate_hashes != {str(expected_candidate_set_sha256 or "")}:
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV candidate receipt is stale."
        )
    if rows[0]["Content"] != _servicenow_entra_handoff_summary(
        application_client_id=resolved_client_id,
        confirmed_claim_name=claim_name,
    ):
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV Entra handoff changed."
        )
    if rows[1]["Content"] != _servicenow_admin_instruction(
        application_client_id=resolved_client_id,
        confirmed_claim_name=claim_name,
        tenant_id=expected_context["tenant_id"],
    ):
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV instructions changed."
        )
    if rows[0]["ServiceNow User Field"].strip():
        raise ServiceNowConnectError(
            "The ServiceNow identity CSV handoff record must not contain a "
            "User Field."
        )
    user_field = str(rows[1]["ServiceNow User Field"] or "").strip()
    if not _SAFE_USER_FIELD.fullmatch(user_field):
        raise ServiceNowConnectError(
            "ServiceNow User Field must be one explicit safe sys_user field "
            "name."
        )
    return {
        "candidates": [claim_name],
        "applicationClientId": resolved_client_id,
        "selection": {
            "tokenClaimName": claim_name,
            "serviceNowUserField": user_field,
        },
        "sheetProtected": False,
    }


def _parse_identity_handoff_file(
    path: Path,
    *,
    stage: str,
    expected_context: dict[str, str],
    expected_candidates: list[str] | None = None,
    expected_candidate_set_sha256: str | None = None,
    allow_pending_client_id_fallback: bool = False,
) -> dict[str, Any]:
    if not path.is_file():
        raise ServiceNowConnectError(
            "The identity handoff path does not exist or is not a local file."
        )
    if path.suffix.casefold() == ".csv":
        return _parse_identity_csv(
            path,
            stage=stage,
            expected_context=expected_context,
            expected_candidates=expected_candidates,
            expected_candidate_set_sha256=(
                expected_candidate_set_sha256
            ),
        )
    return _parse_identity_workbook(
        path,
        stage=stage,
        expected_context=expected_context,
        expected_candidates=expected_candidates,
        allow_pending_client_id_fallback=(
            allow_pending_client_id_fallback
        ),
    )


def _parse_entra_handoff_workbook(
    workbook,
    *,
    expected_context: dict[str, str],
) -> dict[str, Any]:
    handoff = workbook[IDENTITY_ENTRA_HANDOFF_SHEET]
    metadata = workbook[IDENTITY_WORKBOOK_METADATA_SHEET]
    if (
        handoff.sheet_state != "visible"
        or metadata.sheet_state != "hidden"
    ):
        raise ServiceNowConnectError(
            "The Entra handoff sheet visibility changed."
        )
    if not handoff.protection.sheet or not metadata.protection.sheet:
        raise ServiceNowConnectError(
            "The Entra handoff workbook protection changed."
        )
    if handoff.max_row != 2 or handoff.max_column != 3:
        raise ServiceNowConnectError(
            "The Entra handoff visible shape changed."
        )
    if tuple(
        str(handoff.cell(1, column).value or "")
        for column in range(1, 4)
    ) != IDENTITY_ENTRA_HANDOFF_HEADERS:
        raise ServiceNowConnectError(
            "The Entra handoff headers changed."
        )
    if str(handoff["A2"].value or "") != _entra_admin_instruction():
        raise ServiceNowConnectError(
            "The Entra administrator instructions changed."
        )
    hyperlink = handoff["A2"].hyperlink
    if (
        hyperlink is None
        or str(hyperlink.target or "")
        != SERVICENOW_NON_EMAIL_USER_MATCH_URL
    ):
        raise ServiceNowConnectError(
            "The Entra administrator instruction link changed."
        )
    if (
        not handoff["A2"].protection.locked
        or handoff["B2"].protection.locked
        or handoff["C2"].protection.locked
    ):
        raise ServiceNowConnectError(
            "The Entra handoff editable ownership changed."
        )
    for worksheet in (handoff, metadata):
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.data_type == "f" or (
                    isinstance(cell.value, str)
                    and cell.value.lstrip().startswith("=")
                ):
                    raise ServiceNowConnectError(
                        "The Entra handoff workbook must not contain formulas."
                    )
    if (
        metadata.max_row != len(IDENTITY_ENTRA_METADATA_KEYS) + 1
        or metadata.max_column != 2
        or tuple(
            str(metadata.cell(1, column).value or "")
            for column in range(1, 3)
        )
        != ("key", "value")
    ):
        raise ServiceNowConnectError(
            "The Entra handoff metadata shape changed."
        )
    metadata_values: dict[str, str] = {}
    for row_number, key in enumerate(
        IDENTITY_ENTRA_METADATA_KEYS,
        start=2,
    ):
        if str(metadata.cell(row_number, 1).value or "") != key:
            raise ServiceNowConnectError(
                "The Entra handoff metadata keys changed."
            )
        metadata_values[key] = str(
            metadata.cell(row_number, 2).value or ""
        ).strip()
    expected_metadata = _entra_handoff_metadata_values(expected_context)
    for key in IDENTITY_ENTRA_METADATA_KEYS:
        if key == "application_client_id":
            continue
        if metadata_values[key] != expected_metadata[key]:
            raise ServiceNowConnectError(
                "The Entra handoff metadata does not match the active "
                "tenant, environment, instance, provider, profile, or agent."
            )
    visible_client_id = str(handoff["B2"].value or "").strip()
    expected_client_id = expected_context["application_client_id"]
    metadata_client_id = metadata_values["application_client_id"]
    if metadata_client_id in {
        IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
        IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
    }:
        if not visible_client_id:
            raise ServiceNowConnectError(
                "Enter the exact Application (client) ID in the Entra "
                "handoff Client ID cell."
            )
        else:
            resolved_client_id = normalize_client_id(visible_client_id)
            if (
                expected_client_id
                != IDENTITY_WORKBOOK_PENDING_CLIENT_ID
                and resolved_client_id
                != normalize_client_id(expected_client_id)
            ):
                raise ServiceNowConnectError(
                    "The Entra handoff Client ID does not match the supplied "
                    "Application client ID."
                )
    else:
        if not visible_client_id:
            raise ServiceNowConnectError(
                "The Entra handoff Client ID is blank."
            )
        if expected_client_id == IDENTITY_WORKBOOK_PENDING_CLIENT_ID:
            raise ServiceNowConnectError(
                "The Application client ID in this Entra handoff is not "
                "bound to the active lifecycle. Import it once with the "
                "matching --client-id, or generate a current handoff from "
                "the active lifecycle."
            )
        resolved_client_id = normalize_client_id(visible_client_id)
        if (
            resolved_client_id != normalize_client_id(metadata_client_id)
            or resolved_client_id != normalize_client_id(expected_client_id)
        ):
            raise ServiceNowConnectError(
                "The Entra handoff Client ID does not match the active "
                "lifecycle."
            )
    claim_name = _safe_identity_name(
        handoff["C2"].value,
        "user_claim",
    )
    if claim_name.casefold() == "aud":
        raise ServiceNowConnectError(
            "The aud audience claim cannot be selected as the user-matching "
            "User Claim."
        )
    return {
        "candidates": [claim_name],
        "applicationClientId": resolved_client_id,
        "selection": None,
        "sheetProtected": True,
    }


def _parse_identity_workbook(
    path: Path,
    *,
    stage: str,
    expected_context: dict[str, str],
    expected_candidates: list[str] | None = None,
    allow_pending_client_id_fallback: bool = False,
) -> dict[str, Any]:
    _Workbook, load_workbook, *_styles = _identity_workbook_openpyxl()
    if not path.is_file():
        raise ServiceNowConnectError(
            "The identity workbook path does not exist or is not a local "
            "file. Save or download the completed .xlsx locally, then provide "
            "that exact local path."
        )
    if path.suffix.casefold() != ".xlsx":
        raise ServiceNowConnectError(
            "The identity mapping return must be an .xlsx workbook."
        )
    try:
        with zipfile.ZipFile(path) as archive:
            if any(
                name.startswith("xl/externalLinks/")
                or name.endswith("vbaProject.bin")
                for name in archive.namelist()
            ):
                raise ServiceNowConnectError(
                    "The identity mapping workbook must not contain external "
                    "links or macros."
                )
    except zipfile.BadZipFile as exc:
        raise ServiceNowConnectError(
            "The identity mapping workbook is not a valid XLSX file."
        ) from exc
    try:
        workbook = load_workbook(
            path,
            read_only=False,
            data_only=False,
            keep_links=False,
        )
    except Exception as exc:
        raise ServiceNowConnectError(
            "The identity mapping workbook could not be read safely."
        ) from exc
    try:
        if (
            stage == "entra"
            and workbook.sheetnames
            == [
                IDENTITY_ENTRA_HANDOFF_SHEET,
                IDENTITY_WORKBOOK_METADATA_SHEET,
            ]
        ):
            return _parse_entra_handoff_workbook(
                workbook,
                expected_context=expected_context,
            )
        if workbook.sheetnames != [
            IDENTITY_WORKBOOK_STEPS_SHEET,
            IDENTITY_WORKBOOK_SHEET,
            IDENTITY_WORKBOOK_METADATA_SHEET,
        ]:
            raise ServiceNowConnectError(
                "The identity mapping workbook sheet structure changed."
            )
        if getattr(workbook, "_external_links", []):
            raise ServiceNowConnectError(
                "The identity mapping workbook must not contain external "
                "links."
            )
        steps_sheet = workbook[IDENTITY_WORKBOOK_STEPS_SHEET]
        sheet = workbook[IDENTITY_WORKBOOK_SHEET]
        metadata = workbook[IDENTITY_WORKBOOK_METADATA_SHEET]
        if (
            steps_sheet.sheet_state != "visible"
            or sheet.sheet_state != "visible"
        ):
            raise ServiceNowConnectError(
                "The Steps and Worksheet sheets must remain visible."
            )
        if metadata.sheet_state != "hidden":
            raise ServiceNowConnectError(
                "The identity mapping metadata sheet visibility changed."
            )
        headers = tuple(
            str(metadata.cell(1, column).value or "")
            for column in range(1, len(IDENTITY_WORKBOOK_COLUMNS) + 1)
        )
        if headers != IDENTITY_WORKBOOK_COLUMNS:
            raise ServiceNowConnectError(
                "The identity mapping workbook columns were changed."
            )
        expected_rows = (
            1
            + len(IDENTITY_WORKBOOK_CONTEXT_FIELDS)
            + (
                IDENTITY_WORKBOOK_MAX_CANDIDATES
                if stage == "entra"
                else len(expected_candidates or [])
            )
        )
        if metadata.max_row != expected_rows or metadata.max_column != len(
            IDENTITY_WORKBOOK_COLUMNS
        ):
            raise ServiceNowConnectError(
                "The identity mapping workbook row or column shape changed."
            )
        visible_expected_rows = (
            IDENTITY_WORKBOOK_FIRST_DATA_ROW
            + expected_rows
            - 1
            - len(IDENTITY_WORKBOOK_CONTEXT_FIELDS)
            - 1
        )
        if sheet.max_row != visible_expected_rows or sheet.max_column != 2:
            raise ServiceNowConnectError(
                "The visible identity mapping form shape changed."
            )
        if (
            sheet.cell(IDENTITY_WORKBOOK_TABLE_HEADER_ROW, 1).value
            != "Token Claim Name"
            or sheet.cell(IDENTITY_WORKBOOK_TABLE_HEADER_ROW, 2).value
            != "ServiceNow User Field"
        ):
            raise ServiceNowConnectError(
                "The visible identity mapping headers changed."
            )
        for worksheet in (steps_sheet, sheet, metadata):
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f" or (
                        isinstance(cell.value, str)
                        and cell.value.lstrip().startswith("=")
                    ):
                        raise ServiceNowConnectError(
                            "The identity mapping workbook must not contain "
                            "formulas."
                        )
        visible_context: dict[str, str] = {}
        for row_number, (_, key) in enumerate(
            IDENTITY_WORKBOOK_VISIBLE_CONTEXT,
            start=2,
        ):
            visible_context[key] = str(
                sheet.cell(row_number, 2).value or ""
            ).strip()
        context_rows: dict[str, str] = {}
        for row_number, key in enumerate(
            IDENTITY_WORKBOOK_CONTEXT_FIELDS,
            start=2,
        ):
            values = [
                str(metadata.cell(row_number, column).value or "").strip()
                for column in range(
                    1,
                    len(IDENTITY_WORKBOOK_COLUMNS) + 1,
                )
            ]
            if (
                values[0] != "context"
                or values[1] != key
                or values[3:]
                != ["", "", "no", "no"]
            ):
                raise ServiceNowConnectError(
                    f"The identity mapping context row {key!r} was changed."
                )
            context_rows[key] = values[2]
        visible_client_id = visible_context["application_client_id"]
        metadata_client_id = context_rows["application_client_id"]
        expected_client_id = expected_context["application_client_id"]
        pending_client_binding = (
            stage == "entra"
            and metadata_client_id == IDENTITY_WORKBOOK_PENDING_CLIENT_ID
        )
        if pending_client_binding:
            if visible_client_id in {
                "",
                IDENTITY_WORKBOOK_PENDING_CLIENT_ID,
                IDENTITY_WORKBOOK_TEMPLATE_CLIENT_ID,
            }:
                if (
                    expected_client_id == IDENTITY_WORKBOOK_PENDING_CLIENT_ID
                    or not allow_pending_client_id_fallback
                ):
                    raise ServiceNowConnectError(
                        "Enter the Application (client) ID from the app's "
                        "Overview page in the yellow workbook cell."
                    )
                resolved_client_id = normalize_client_id(expected_client_id)
            else:
                resolved_client_id = normalize_client_id(visible_client_id)
                if (
                    expected_client_id
                    != IDENTITY_WORKBOOK_PENDING_CLIENT_ID
                    and resolved_client_id
                    != normalize_client_id(expected_client_id)
                ):
                    raise ServiceNowConnectError(
                        "The Application client ID in the workbook does not "
                        "match the supplied ID."
                    )
        else:
            if visible_client_id != metadata_client_id:
                raise ServiceNowConnectError(
                    "The visible and hidden Application client ID context "
                    "changed."
                )
            if expected_client_id == IDENTITY_WORKBOOK_PENDING_CLIENT_ID:
                raise ServiceNowConnectError(
                    "The Application client ID in this workbook is not bound "
                    "to the active lifecycle. For a previously generated "
                    "workbook, import it once with the matching --client-id, "
                    "or generate a current workbook from the active lifecycle."
                )
            resolved_client_id = normalize_client_id(metadata_client_id)
            if resolved_client_id != normalize_client_id(expected_client_id):
                raise ServiceNowConnectError(
                    "The Application client ID does not match the active "
                    "lifecycle."
                )
        for key in IDENTITY_WORKBOOK_BOUND_CONTEXT_FIELDS:
            if key == "application_client_id":
                continue
            expected_value = expected_context[key]
            metadata_value = context_rows[key]
            visible_value = visible_context.get(key)
            if metadata_value != expected_value:
                raise ServiceNowConnectError(
                    "The identity mapping workbook context does not match the "
                    "active lifecycle."
                )
            if (
                visible_value is not None
                and visible_value != expected_value
            ):
                raise ServiceNowConnectError(
                    "The visible identity mapping context changed."
                )
        candidates: list[str] = []
        selections: list[tuple[str, str]] = []
        first_candidate_row = 2 + len(IDENTITY_WORKBOOK_CONTEXT_FIELDS)
        for index, row_number in enumerate(
            range(first_candidate_row, expected_rows + 1)
        ):
            metadata_values = [
                str(metadata.cell(row_number, column).value or "").strip()
                for column in range(
                    1,
                    len(IDENTITY_WORKBOOK_COLUMNS) + 1,
                )
            ]
            visible_row = IDENTITY_WORKBOOK_FIRST_DATA_ROW + index
            claim_name = str(sheet.cell(visible_row, 1).value or "").strip()
            user_field = str(sheet.cell(visible_row, 2).value or "").strip()
            expected_claim_editable = "yes" if stage == "entra" else "no"
            expected_field_editable = (
                "yes" if stage == "servicenow" else "no"
            )
            if (
                metadata_values[:3] != ["candidate", "", ""]
                or metadata_values[5] != expected_claim_editable
                or metadata_values[6] != expected_field_editable
            ):
                raise ServiceNowConnectError(
                    "The identity mapping workbook editable ownership or "
                    "candidate row metadata was changed."
                )
            if stage == "entra":
                if user_field:
                    raise ServiceNowConnectError(
                        "The Entra administrator must not fill a ServiceNow "
                        "user field."
                    )
                if not claim_name:
                    continue
            else:
                frozen = (expected_candidates or [])[index]
                if metadata_values[3] != frozen or claim_name != frozen:
                    raise ServiceNowConnectError(
                        "The Entra-confirmed candidate claims were changed, "
                        "added, deleted, or reordered."
                    )
            safe_claim = _safe_identity_name(
                claim_name,
                "token_claim_name",
            )
            if safe_claim.casefold() == "aud":
                raise ServiceNowConnectError(
                    "The aud audience claim is not an employee identity "
                    "candidate."
                )
            candidates.append(safe_claim)
            if user_field:
                if not _SAFE_USER_FIELD.fullmatch(user_field):
                    raise ServiceNowConnectError(
                        "servicenow_user_field must be an explicit safe "
                        "ServiceNow field name."
                    )
                selections.append((safe_claim, user_field))
        folded = [candidate.casefold() for candidate in candidates]
        if not candidates:
            raise ServiceNowConnectError(
                "At least one employee identity token claim candidate is "
                "required."
            )
        if len(set(folded)) != len(folded):
            raise ServiceNowConnectError(
                "Token claim candidates must be unique."
            )
        if stage == "servicenow" and len(selections) != 1:
            raise ServiceNowConnectError(
                "The ServiceNow administrator must fill exactly one "
                "servicenow_user_field cell."
            )
        return {
            "candidates": candidates,
            "applicationClientId": resolved_client_id,
            "selection": (
                {
                    "tokenClaimName": selections[0][0],
                    "serviceNowUserField": selections[0][1],
                }
                if selections
                else None
            ),
            "sheetProtected": bool(sheet.protection.sheet),
        }
    finally:
        workbook.close()


def record_identity_mapping(
    context: dict[str, Any],
    *,
    stage: str,
    workbook_path: Path,
    client_id: str | None,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ServiceNowConnectError(
            "Importing the identity workbook requires explicit Maker "
            "confirmation that the responsible administrator completed this "
            "stage."
        )
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity workbook stage is invalid.")
    state = _load_lifecycle_state(context)
    expected_identity = _required_context_identity(context, state)
    candidate_receipt = state.get("evidence", {}).get(
        "identityClaimCandidates"
    )
    if stage == "entra":
        supplied_client_id = (
            normalize_client_id(client_id) if client_id else None
        )
        known_client_id = _existing_known_entra_client_id(context, state)
        if (
            supplied_client_id
            and known_client_id
            and supplied_client_id != known_client_id
        ):
            raise ServiceNowConnectError(
                "The explicitly supplied Application client ID conflicts "
                "with the active lifecycle."
            )
        expected_client_id = known_client_id or supplied_client_id
        expected_candidates = None
    else:
        if not isinstance(candidate_receipt, dict):
            raise ServiceNowConnectError(
                "Import the Entra-confirmed candidate claims before the "
                "ServiceNow mapping stage."
            )
        application_client_id = normalize_client_id(
            str(candidate_receipt.get("applicationClientId") or "")
        )
        if client_id and normalize_client_id(client_id) != application_client_id:
            raise ServiceNowConnectError(
                "The Application client ID changed between administrator "
                "stages."
            )
        expected_candidates = list(
            candidate_receipt.get("candidates") or []
        )
    expected_context = _identity_workbook_context_values(
        context,
        expected_identity,
        application_client_id=(
            expected_client_id if stage == "entra" else application_client_id
        ),
        stage=stage,
    )
    parsed = _parse_identity_handoff_file(
        workbook_path,
        stage=stage,
        expected_context=expected_context,
        expected_candidates=expected_candidates,
        expected_candidate_set_sha256=(
            candidate_receipt.get("candidateSetSha256")
            if stage == "servicenow"
            and isinstance(candidate_receipt, dict)
            else None
        ),
        allow_pending_client_id_fallback=(
            stage == "entra" and supplied_client_id is not None
        ),
    )
    if stage == "entra":
        application_client_id = parsed["applicationClientId"]
    recorded_at = _utc_now()
    binding = {
        **expected_identity,
        "applicationClientId": application_client_id,
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
    }
    workbook_hash = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    evidence = state.setdefault("evidence", {})
    if stage == "entra":
        candidates = parsed["candidates"]
        candidate_hash = _identity_candidate_set_hash(
            application_client_id=application_client_id,
            candidates=candidates,
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
        result = {
            "kind": "administrator-confirmed-claim-candidates",
            "status": "entra-confirmed",
            "currentSource": "local-handoff",
            "applicationClientId": application_client_id,
            "candidates": candidates,
            "candidateSetSha256": candidate_hash,
            "entraAdministratorConfirmed": True,
            "tokenClaimEmissionConfirmed": True,
            "binding": binding,
            "importedWorkbookSha256": workbook_hash,
            "importedFileFormat": workbook_path.suffix.casefold().lstrip("."),
            "sheetProtected": parsed["sheetProtected"],
            "recordedAt": recorded_at,
        }
        evidence["identityClaimCandidates"] = result
    else:
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
        selected = parsed["selection"]
        result = {
            "kind": "administrator-confirmed-identity-mapping",
            "status": "servicenow-confirmed",
            "applicationClientId": application_client_id,
            "tokenClaimName": selected["tokenClaimName"],
            "serviceNowUserField": selected["serviceNowUserField"],
            "candidateSetSha256": candidate_receipt[
                "candidateSetSha256"
            ],
            "entraAdministratorConfirmed": True,
            "tokenClaimEmissionConfirmed": True,
            "serviceNowAdministratorConfirmed": True,
            "binding": binding,
            "importedWorkbookSha256": workbook_hash,
            "importedFileFormat": workbook_path.suffix.casefold().lstrip("."),
            "sheetProtected": parsed["sheetProtected"],
            "recordedAt": recorded_at,
        }
        result["relationshipSha256"] = (
            _identity_mapping_relationship_hash(result)
        )
        existing = evidence.get("identityMapping")
        if not (
            isinstance(existing, dict)
            and existing.get("relationshipSha256")
            == result["relationshipSha256"]
        ):
            _invalidate_oidc_handoff(state)
        evidence["identityMapping"] = result
    _write_lifecycle_state(context, state)
    return copy.deepcopy(result)


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
                "tokenClaimEmissionConfirmed": True,
                "candidateSetSha256": candidates["candidateSetSha256"],
            }
        else:
            derived_values = {
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
            and validated_evidence.get("tokenClaimEmissionConfirmed") is True
            and validated_evidence.get("candidateSetSha256")
            == candidates.get("candidateSetSha256")
            and validated_evidence.get("mappingWorkbookSha256")
            == candidates.get("importedWorkbookSha256")
            and validated_evidence.get("currentSource")
            == "administrator-confirmed"
            and validated_evidence.get("entraAdministratorConfirmed") is True
            and validated_evidence.get(
                "applicationRegistrationConfirmed"
            )
            is True
            and validated_evidence.get("userImpersonationScopeConfirmed")
            is True
            and validated_evidence.get(
                "connectorPreauthorizationConfirmed"
            )
            is True
            and len(candidates.get("candidates") or []) == 1
            and validated_evidence.get("selectedClaimName")
            == candidates["candidates"][0]
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
            and validated_evidence.get("oidcCapabilityConfirmed") is True
            and validated_evidence.get("runbookCompleted") is True
            and validated_evidence.get("mappingDetailsCollected") is True
            and validated_evidence.get("claimMappingConfirmed") is True
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


def _identity_no_action_handoff(
    context: dict[str, Any],
    state: dict[str, Any],
    *,
    stage: str,
    application_client_id: str | None,
    candidate_receipt: dict[str, Any] | None,
    final_mapping: dict[str, Any] | None,
    checkpoint_outcomes: dict[str, str],
    admin_guide_path: Path,
) -> dict[str, Any]:
    return {
        "schemaVersion": "servicenow.identity-mapping-handoff.v1",
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "decision": "no-action",
        "workbookPath": None,
        "workbookUri": None,
        "entraWorkbookUri": None,
        "serviceNowWorkbookUri": None,
        "workbookFileStatus": "not-generated",
        "stage": stage,
        "handoffMode": "complete",
        "applicationClientId": application_client_id,
        "candidates": (
            list(candidate_receipt.get("candidates") or [])
            if isinstance(candidate_receipt, dict)
            else []
        ),
        "checkpointOutcomes": checkpoint_outcomes,
        "missingItems": _entra_missing_items(checkpoint_outcomes)
        if stage == "entra"
        else [],
        "adminGuidePath": str(admin_guide_path),
        "adminGuideUri": admin_guide_path.as_uri(),
        "portalLinks": maker_portal_links(
            context,
            instance_name=_required_context_identity(
                context,
                state,
            )["instanceName"],
        ),
        "checkedInTemplatePath": str(
            (
                SOLUTION_ROOT
                / (
                    IDENTITY_WORKBOOK_TEMPLATE_ENTRA
                    if stage == "entra"
                    else IDENTITY_WORKBOOK_TEMPLATE_SERVICENOW
                )
            ).resolve()
        ),
        "expectedIdentity": _required_context_identity(context, state),
        "status": (
            candidate_receipt.get("status")
            if stage == "entra" and candidate_receipt
            else final_mapping.get("status")
            if stage == "servicenow" and final_mapping
            else "missing"
        ),
        "candidateReceipt": copy.deepcopy(candidate_receipt),
        "mapping": copy.deepcopy(final_mapping),
        "identityRequirement": copy.deepcopy(
            _validated_identity_requirement(context, state)
        ),
        "secretsAccepted": False,
        "employeeValuesAccepted": False,
        "editableFields": [],
        "workbookColumns": list(IDENTITY_WORKBOOK_COLUMNS),
        "instructionTitle": None,
        "instruction": None,
        "question": None,
        "clientIdQuestion": None,
    }


def identity_mapping_handoff(
    context: dict[str, Any],
    *,
    stage: str = "entra",
    client_id: str | None = None,
) -> dict[str, Any]:
    if stage not in {"entra", "servicenow"}:
        raise ServiceNowConnectError("Identity workbook stage is invalid.")
    state = _load_lifecycle_state(context)
    expected_identity = _required_context_identity(context, state)
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    candidate_receipt = evidence.get("identityClaimCandidates")
    candidate_receipt = (
        candidate_receipt if isinstance(candidate_receipt, dict) else None
    )
    validated_candidate_receipt = None
    if candidate_receipt is not None:
        try:
            validated_candidate_receipt = _validated_claim_candidates(
                context,
                state,
            )
        except ServiceNowConnectError as exc:
            if stage == "servicenow":
                raise ServiceNowConnectError(
                    "The ServiceNow identity handoff is not ready. The Entra "
                    "claim evidence is missing, unconfirmed, stale, or bound "
                    "to a different tenant, environment, instance, or target "
                    "agent. Resume the Entra stage and import a current "
                    f"administrator-confirmed workbook. {exc}"
                ) from exc
    candidate_receipt = validated_candidate_receipt
    final_mapping = evidence.get("identityMapping")
    final_mapping = (
        final_mapping if isinstance(final_mapping, dict) else None
    )
    existing_servicenow_handoff_ready = (
        stage == "servicenow"
        and _identity_admin_handoff_is_ready(
            context,
            state,
            phase="servicenow-oidc",
        )
    )
    confirmed_user_claim_name: str | None = None
    if stage == "servicenow":
        if candidate_receipt is None:
            raise ServiceNowConnectError(
                "The ServiceNow identity handoff is not ready. Import a "
                "current Entra administrator-confirmed Application client ID "
                "and selected User Claim name first."
            )
        raw_application_client_id = str(
            candidate_receipt.get("applicationClientId") or ""
        ).strip()
        if not raw_application_client_id:
            raise ServiceNowConnectError(
                "The ServiceNow identity handoff is not ready. The confirmed "
                "Microsoft Entra Application client ID is missing."
            )
        application_client_id = normalize_client_id(
            raw_application_client_id
        )
        candidates = list(candidate_receipt.get("candidates") or [])
        if len(candidates) != 1 and not existing_servicenow_handoff_ready:
            raise ServiceNowConnectError(
                "The ServiceNow identity handoff is not ready. The Entra "
                "administrator must confirm exactly one selected User Claim "
                "name for this tenant, environment, instance, and target "
                "agent; multiple unselected candidates cannot be guessed."
            )
        if len(candidates) == 1:
            confirmed_user_claim_name = _safe_identity_name(
                candidates[0],
                "confirmed_user_claim_name",
            )
    else:
        application_client_id = (
            normalize_client_id(client_id)
            if client_id is not None
            else (
                normalize_client_id(
                    str(candidate_receipt.get("applicationClientId"))
                )
                if candidate_receipt
                and candidate_receipt.get("applicationClientId")
                else _known_entra_client_id(state)
            )
        )
        candidates = []
    identity_requirement = _validated_identity_requirement(context, state)
    admin_guide_path = (
        _entra_admin_guide_path()
        if stage == "entra"
        else (
            SOLUTION_ROOT
            / CONTRACT_PATH.parent
            / "actions"
            / "guide-servicenow-oidc.md"
        ).resolve()
    )
    admin_guide_uri = admin_guide_path.as_uri()
    if stage == "entra":
        checkpoint_outcomes = _entra_checkpoint_outcomes(state)
        missing_items = _entra_missing_items(checkpoint_outcomes)
        handoff_mode = _entra_handoff_mode(checkpoint_outcomes)
    else:
        handoff_mode = "servicenow-selection"
        checkpoint_outcomes = {}
        missing_items = []
    phase = (
        "entra-registration"
        if stage == "entra"
        else "servicenow-oidc"
    )
    if _identity_admin_handoff_is_ready(
        context,
        state,
        phase=phase,
    ):
        validated_mapping = (
            _validated_identity_mapping(context, state)
            if stage == "servicenow"
            else final_mapping
        )
        return _identity_no_action_handoff(
            context,
            state,
            stage=stage,
            application_client_id=application_client_id,
            candidate_receipt=candidate_receipt,
            final_mapping=validated_mapping,
            checkpoint_outcomes=checkpoint_outcomes,
            admin_guide_path=admin_guide_path,
        )
    existing_entra_workbook = _identity_workbook_path(
        context,
        stage="entra",
    )
    if (
        stage == "entra"
        and identity_requirement is None
        and candidate_receipt is not None
        and handoff_mode == "complete"
        and not existing_entra_workbook.exists()
    ):
        return {
            "schemaVersion": "servicenow.identity-mapping-handoff.v1",
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "decision": "no-action",
            "workbookPath": None,
            "workbookUri": None,
            "workbookFileStatus": "not-generated",
            "stage": stage,
            "handoffMode": "complete",
            "applicationClientId": application_client_id,
            "candidates": [],
            "checkpointOutcomes": checkpoint_outcomes,
            "missingItems": [],
            "adminGuidePath": str(admin_guide_path),
            "adminGuideUri": admin_guide_uri,
            "checkedInTemplatePath": str(
                (
                    SOLUTION_ROOT
                    / IDENTITY_WORKBOOK_TEMPLATE_ENTRA
                ).resolve()
            ),
            "expectedIdentity": expected_identity,
            "status": candidate_receipt.get("status"),
            "candidateReceipt": copy.deepcopy(candidate_receipt),
            "mapping": copy.deepcopy(final_mapping),
            "identityRequirement": None,
            "routingOnly": False,
            "legacyRequirementBypass": "completed-candidate-receipt",
            "secretsAccepted": False,
            "employeeValuesAccepted": False,
            "editableFields": [],
            "workbookColumns": list(IDENTITY_WORKBOOK_COLUMNS),
            "instructionTitle": None,
            "instruction": None,
            "question": None,
            "clientIdQuestion": None,
        }
    context_values = _identity_workbook_context_values(
        context,
        expected_identity,
        application_client_id=application_client_id,
        stage=stage,
    )
    if confirmed_user_claim_name is not None:
        context_values["confirmed_user_claim_name"] = (
            confirmed_user_claim_name
        )
        context_values["admin_instruction"] = (
            "Use the locked Entra-confirmed User Claim name and enter the "
            "matching ServiceNow sys_user field in the editable User Field "
            "cell."
        )
    workbook_steps = _identity_workbook_steps(
        stage=stage,
        context_values=context_values,
        missing_items=missing_items,
        identity_requirement=identity_requirement,
    )
    generated_path, file_status = _ensure_identity_workbook(
        context,
        context_values=context_values,
        stage=stage,
        candidates=candidates,
        steps=workbook_steps,
        missing_items=missing_items,
        identity_requirement=identity_requirement,
    )
    generated_csv_path, csv_file_status = _ensure_identity_csv(
        context,
        context_values=context_values,
        stage=stage,
        candidates=candidates,
        candidate_set_sha256=(
            candidate_receipt.get("candidateSetSha256")
            if stage == "servicenow"
            and isinstance(candidate_receipt, dict)
            else None
        ),
    )
    generated_path = generated_path.resolve()
    generated_uri = generated_path.as_uri()
    generated_csv_path = generated_csv_path.resolve()
    generated_csv_uri = generated_csv_path.as_uri()
    entra_target_summary = (
        f"- Tenant: `{context['environment'].get('tenant_id')}`\n"
        f"- Environment: `{context['environment']['id']}`\n"
        f"- Agent: {ACTIVE_PROFILE.agent_display_name} "
        f"(`{_agent_slug(context)}`; `{context['agent']['id']}`)\n"
        f"- ServiceNow instance: "
        f"`{expected_identity['instanceName']}`"
    )
    if stage == "entra":
        instruction_title = (
            "Step 1 of 2 — Entra: list employee identity options"
        )
        instruction_text = (
            "**Purpose**\n"
            "Complete the Entra application and identity-claim handoff.\n\n"
            "**Owner**\n"
            "Application Administrator or Cloud Application Administrator.\n\n"
            "**Known target**\n"
            f"{entra_target_summary}\n\n"
            "**Action**\n"
            "1. Open [Microsoft Entra admin center]"
            "(https://entra.microsoft.com/).\n"
            f"2. Open [the protected Entra workbook]({generated_uri}) "
            f"or use `{generated_path}`. Alternatively use [the equivalent "
            f"Entra CSV]({generated_csv_uri}) or `{generated_csv_path}`.\n"
            "3. In either file, enter the exact Application (client) ID and "
            "one selected User Claim name. Do not enter `aud`, a personal "
            "claim value, Object ID, token, secret, or user identifier.\n"
            "4. For XLSX, keep the protected `Entra Handoff` and hidden "
            "`_metadata` sheets intact. Save and return exactly one completed "
            "XLSX or CSV file."
        )
        maker_question = (
            "Please enter the returned Entra admin handoff workbook URL."
        )
    else:
        instruction_title = (
            "Step 2 of 2 — ServiceNow: choose the matching user field"
        )
        service_now_target_summary = (
            f"- Environment: `{context['environment']['id']}`\n"
            f"- Agent: {ACTIVE_PROFILE.agent_display_name} "
            f"(`{_agent_slug(context)}`; `{context['agent']['id']}`)\n"
            f"- ServiceNow instance: "
            f"`{expected_identity['instanceName']}`\n"
            f"- Application client ID: `{application_client_id}`"
        )
        instruction_text = (
            "**Purpose**\n"
            "Map an Entra-confirmed claim to the matching ServiceNow user "
            "field.\n\n"
            "**Owner**\n"
            "ServiceNow administrator authorized to elevate to "
            "`security_admin`.\n\n"
            "**Known target**\n"
            f"{service_now_target_summary}\n\n"
            "**Action**\n"
            f"1. Open [the confirmed ServiceNow instance]"
            f"(https://{expected_identity['instanceName']}.service-now.com) "
            "and elevate to `security_admin` when authorized.\n"
            f"2. Open [the protected ServiceNow workbook]({generated_uri}) "
            f"or use `{generated_path}`. Alternatively use [the equivalent "
            f"ServiceNow CSV]({generated_csv_uri}) or "
            f"`{generated_csv_path}`.\n"
            "3. Follow the generated instructions. In XLSX, fill the one "
            "yellow User Field cell on `Worksheet`; in CSV, fill the "
            "`ServiceNow User Field` on the `Steps` record.\n"
            "4. Configure and verify the OIDC User Claim/User Field mapping and "
            "one matching Active user, without returning employee values.\n"
            "5. Preserve the locked claim rows, `Steps`, `Worksheet`, hidden "
            "`_metadata`, and workbook protection. Save the completed workbook."
        )
        maker_question = (
            "Please enter the returned ServiceNow admin handoff workbook URL."
        )
    return {
        "schemaVersion": "servicenow.identity-mapping-handoff.v1",
        "provider": PROVIDER_KEY,
        "profile": PROFILE_KEY,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "decision": "no-action" if handoff_mode == "complete" else "question-required",
        "workbookPath": str(generated_path),
        "workbookUri": generated_uri,
        "csvPath": str(generated_csv_path),
        "csvUri": generated_csv_uri,
        "csvFileStatus": csv_file_status,
        "entraWorkbookUri": generated_uri if stage == "entra" else None,
        "serviceNowWorkbookUri": (
            generated_uri if stage == "servicenow" else None
        ),
        "workbookFileStatus": file_status,
        "stage": stage,
        "handoffMode": handoff_mode,
        "applicationClientId": application_client_id,
        "candidates": candidates,
        "checkpointOutcomes": checkpoint_outcomes,
        "missingItems": [
            {
                "checkpoint": suffix,
                "label": label,
                "status": checkpoint_outcomes.get(suffix, "unknown"),
            }
            for suffix, label in missing_items
        ],
        "adminGuidePath": str(admin_guide_path),
        "adminGuideUri": admin_guide_uri,
        "portalLinks": maker_portal_links(
            context,
            instance_name=expected_identity["instanceName"],
        ),
        "checkedInTemplatePath": str(
            (
                SOLUTION_ROOT
                / (
                    IDENTITY_WORKBOOK_TEMPLATE_ENTRA
                    if stage == "entra"
                    else IDENTITY_WORKBOOK_TEMPLATE_SERVICENOW
                )
            ).resolve()
        ),
        "expectedIdentity": expected_identity,
        "status": (
            candidate_receipt.get("status")
            if stage == "entra" and candidate_receipt
            else final_mapping.get("status")
            if stage == "servicenow" and final_mapping
            else "missing"
        ),
        "candidateReceipt": copy.deepcopy(candidate_receipt),
        "mapping": copy.deepcopy(final_mapping),
        "identityRequirement": copy.deepcopy(identity_requirement),
        "secretsAccepted": False,
        "employeeValuesAccepted": False,
        "editableFields": (
            ["application_client_id", "user_claim"]
            if stage == "entra"
            else ["servicenow_user_field"]
        ),
        "workbookColumns": list(IDENTITY_WORKBOOK_COLUMNS),
        "instructionTitle": (
            None if handoff_mode == "complete" else instruction_title
        ),
        "instruction": (
            None if handoff_mode == "complete" else instruction_text
        ),
        "question": (
            None
            if handoff_mode == "complete"
            else {
                "header": maker_question,
                "question": maker_question,
                "allowFreeformInput": True,
            }
        ),
        "clientIdQuestion": None,
    }


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
        and canonical.get("authoring_ready") is True
        and isinstance(workspace, dict)
        and bool(workspace.get("folder"))
        and bool(workspace.get("agent_path"))
        and isinstance(operational, dict)
        and agent.get("workspace_slug") == operational.get("slug")
        and bool(operational.get("agentBuilderChangeSetPath"))
    )
    return profile, ready


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


def list_agent_choices(root: Path = Path(".")) -> dict[str, Any]:
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
    account = _validate_discovery_binding(environment, config)
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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
        if profile is None or not ready or not isinstance(operational, dict):
            continue
        canonical_agent = canonical.get("agent")
        if not isinstance(canonical_agent, dict):
            continue
        display_name = str(
            canonical_agent.get("display_name")
            or canonical_agent.get("name")
            or operational.get("name")
            or profile.agent_display_name
        )
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
    return environment, sorted(
        choices,
        key=lambda item: (
            str(item["name"]).casefold(),
            str(item["id"]),
        ),
    )


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
        "header": "Use another agent",
        "question": (
            "Paste the full Copilot Studio link for the existing agent you "
            "want to use."
        ),
        "options": [],
        "allowFreeformInput": True,
    }


def _resolve_explicit_agent_link(
    *,
    agent_link: str,
    environment: dict[str, Any],
    prepared_choices: list[dict[str, Any]],
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
        target = resolve_da_target(
            target_url=agent_link,
            environment_id=str(environment.get("id") or ""),
            ring=str(environment.get("ring") or ""),
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
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "setup-required",
        "branch": "explicit-agent-link",
        "message": (
            "This existing agent is not prepared in this workspace. Run "
            "/setup and use the same Copilot Studio link. Setup must confirm "
            "the environment and account before changing the workspace."
        ),
        "setupHandoff": {
            "command": "/setup",
            "targetUrl": agent_link.strip(),
            "environmentId": target["environmentId"],
            "agentId": agent_id,
            "ring": target["ring"],
            "requiresEnvironmentConfirmation": True,
            "requiresAccountConfirmation": True,
        },
        "stateChanged": False,
    }


def agent_chooser_handoff(
    root: Path = Path("."),
    *,
    selection_key: str | None = None,
    agent_link: str | None = None,
) -> dict[str, Any]:
    environment, prepared_choices = _prepared_agent_choices(root)
    if agent_link is not None:
        if selection_key not in (None, "another-agent"):
            raise ServiceNowConnectError(
                "An agent link can be supplied only for Use another agent."
            )
        return _resolve_explicit_agent_link(
            agent_link=agent_link,
            environment=environment,
            prepared_choices=prepared_choices,
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
            raise ServiceNowConnectError(
                "The selected prepared agent is no longer available in this "
                "workspace. Choose again."
            )
        return _prepared_agent_result(prepared)

    options = [
        {
            "label": f"{choice['name']} — {choice['product']}",
            "selectionKey": f"prepared:{choice['id']}",
        }
        for choice in prepared_choices
    ]
    options.append(
        {
            "label": "Use another agent (paste link)",
            "selectionKey": "another-agent",
        }
    )
    question_text = (
        "Choose the Employee Self-Service agent you want to set up for "
        "ServiceNow.\n\nThe listed agents are prepared in this workspace. "
        "This is not a list of every agent in the environment."
        if prepared_choices
        else (
            "Choose the Employee Self-Service agent you want to set up for "
            "ServiceNow.\n\nNo Employee Self-Service agents are prepared in "
            "this workspace. Use another agent by pasting its Copilot Studio "
            "link."
        )
    )
    return {
        "schemaVersion": "servicenow.agent-chooser.v1",
        "status": "choice-required",
        "branch": "choose-agent",
        "environmentId": environment.get("id"),
        "agents": prepared_choices,
        "question": {
            "header": "Choose agent",
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
    if canonical.get("authoring_ready") is not True:
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
    return {
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


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _component_schema(change: dict[str, Any]) -> str:
    component = change.get("component")
    if not isinstance(component, dict):
        return ""
    return str(component.get("schemaName") or "")


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
            "agentDisplayName": ACTIVE_PROFILE.agent_display_name,
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

    def get_connector(self) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/connectivity/connectors/{CONNECTOR_NAME}",
        )

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
    environment = context["environment"]
    return authenticate(
        environment["tenant_id"],
        environment["ring"],
        cache_path=TOKEN_CACHE,
        force_account_selection=force_account_selection,
        account_hint=context.get("account"),
    )


def _agentbuilder_client_for_environment(
    context: dict[str, Any],
    *,
    environment_id: str,
    token: str,
    require_resolved_host: bool = False,
) -> AgentBuilderClient:
    environment = context["environment"]
    host = (
        _derive_resolved_environment_host(
            environment_id,
            environment["ring"],
        )
        if require_resolved_host
        else derive_environment_host(environment_id, environment["ring"])
    )
    return AgentBuilderClient(
        host,
        token,
        ring=environment["ring"],
        tenant_id=environment["tenant_id"],
        api_version=environment.get("api_version", "2024-10-01"),
    )


def _derive_resolved_environment_host(
    environment_id: str,
    ring: str,
) -> str:
    attempted: list[str] = []
    resolved: list[str] = []

    def resolver(hostname: str, port: int) -> Any:
        attempted.append(hostname)
        value = socket.getaddrinfo(hostname, port)
        resolved.append(hostname)
        return value

    host = derive_environment_host(
        environment_id,
        ring,
        resolver=resolver,
    )
    if not resolved:
        raise OSError(
            "No supported AgentBuilder environment host resolved; attempted "
            + ", ".join(attempted)
        )
    return host


def _connectivity_client(
    context: dict[str, Any],
    *,
    force_account_selection: bool = False,
) -> ConnectivityClient:
    environment = context["environment"]
    token = authenticate(
        environment["tenant_id"],
        environment["ring"],
        cache_path=TOKEN_CACHE,
        force_account_selection=force_account_selection,
        account_hint=context.get("account"),
        scopes=tuple(connectivity_scopes(environment["ring"])),
    )
    return ConnectivityClient(
        environment["power_platform_api_endpoint"],
        environment["id"],
        token,
        ring=environment["ring"],
    )


def _connectivity_client_for_environment(
    context: dict[str, Any],
    *,
    environment_id: str,
) -> ConnectivityClient:
    environment = context["environment"]
    token = authenticate(
        environment["tenant_id"],
        environment["ring"],
        cache_path=TOKEN_CACHE,
        account_hint=context.get("account"),
        scopes=tuple(connectivity_scopes(environment["ring"])),
    )
    return ConnectivityClient(
        derive_environment_host(environment_id, environment["ring"]),
        environment_id,
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
        state["schemaVersion"] = LIFECYCLE_SCHEMA_VERSION
        migration["schemaV8"] = {
            "from": 7 if version <= 7 else version,
            "to": LIFECYCLE_SCHEMA_VERSION,
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
    return state


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
            and _agent_connection_attestation_current(state, components)
        ):
            state["connectionBindingHash"] = _connection_binding_hash(
                context,
                state,
                components,
            )
        else:
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
    state.setdefault("transactions", {}).setdefault("topics", {})
    state.setdefault("migration", {})
    return state


def _write_lifecycle_state(
    context: dict[str, Any],
    state: dict[str, Any],
) -> None:
    path = _lifecycle_state_path(context)
    existing = _load_json(path) if path.exists() else None
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
                if target.endswith("ENTRA-*"):
                    allowed_remediation_ids.update(
                        f"{target[:-1]}{suffix}-001"
                        for suffix in ENTRA_CHECKPOINT_SUFFIXES
                    )
                elif "*" not in target:
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
        attestation.get("makerAttested") is True
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
            "status": "done" if connected else "pending",
            "message": (
                f"{len(connected)} Connected Entra user-login ServiceNow "
                "credential(s) found."
            ),
        },
        "agentConnection": {
            "status": (
                "confirmation-required"
                if connected
                else "pending"
            ),
            "message": (
                "A prior maker attestation is recorded and the selected "
                "credential is still Connected, but the current agent UI "
                "binding requires maker confirmation."
                if agent_connection_done
                else (
                    "Maker confirmation of the agent's ServiceNow row is "
                    "required."
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
    agent_label = (
        f"{ACTIVE_PROFILE.agent_display_name} (`{_agent_slug(context)}`)"
    )
    environment_id = context["environment"]["id"]
    realm = str(context["agent"].get("realm") or "dev").title()
    error_text = ""
    if discovery_error is not None:
        error_text = (
            "\n\nAutomatic connection discovery failed: "
            f"{discovery_error['message']}. This is not an empty inventory. "
            "You can still provide the intended public ServiceNow URL; later "
            "credential verification must succeed."
        )
    manual_question = {
        "header": "ServiceNow instance URL",
        "question": (
            f"For {agent_label} in environment `{environment_id}` and "
            f"{realm} realm, enter the intended public ServiceNow HTTPS root "
            "URL.\n\nExample: `https://dev184242.service-now.com`\n\n"
            "Use only the instance root (`https://<instance>.service-now.com`). "
            "Do not enter a portal or module path such as `/sp`, `/esc`, or "
            "`/now/...`. Do not enter a username, password, credential, token, "
            "secret, or certificate. If you do not know the URL, ask your "
            f"ServiceNow administrator for the public instance root.{error_text}"
        ),
        "allowFreeformInput": True,
    }
    if candidates:
        choices = {
            f"Use https://{candidate}.service-now.com": (
                f"https://{candidate}.service-now.com"
            )
            for candidate in candidates
        }
        choices["Provide another ServiceNow instance URL"] = "manual"
        question = {
            "header": "Confirm ServiceNow instance",
            "question": (
                f"We found ServiceNow instance candidate"
                f"{'s' if len(candidates) != 1 else ''} in existing connection "
                f"metadata for {agent_label} in environment "
                f"`{environment_id}` and {realm} realm. Which instance should "
                "this agent use for the current connection setup?\n\n"
                "Choose one discovered public root URL below, or choose "
                "**Provide another ServiceNow instance URL** to enter a "
                f"different public HTTPS root URL.{error_text}"
            ),
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
                "label": (
                    f"Use {candidate['portalUrl']} "
                    f"({len(candidate['sources'])} saved source"
                    f"{'s' if len(candidate['sources']) != 1 else ''})"
                ),
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
                "header": "Choose a saved portal URL",
                "question": (
                    "Compatible administrator-confirmed ServiceNow employee "
                    "portal URLs were saved for other agents in this workspace. "
                    "Which value should this agent use?"
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
        {"label": "Reuse saved portal URL", "decision": "accept"},
        {"label": "Enter separately", "decision": "decline"},
        {"label": "Not now", "decision": "not-now"},
    ]
    return {
        "schemaVersion": "servicenow.portal-value-reuse.v1",
        "decision": "question-required",
        "candidate": copy.deepcopy(selected),
        "portalDecisionChoices": decision_choices,
        "question": {
            "header": "Reuse saved portal URL",
            "question": (
                "**Current target**\n"
                f"- Agent: {ACTIVE_PROFILE.agent_display_name} "
                f"(`{_agent_slug(context)}`)\n"
                f"- Environment: `{context['environment']['id']}`\n"
                f"- Confirmed ServiceNow instance: "
                f"`{_admin_setup(state)['preflight']['instanceName']}`\n\n"
                "**Saved value**\n"
                f"- Employee portal URL: `{selected['portalUrl']}`\n"
                f"- Source: {', '.join(selected['sourceLabels'])}\n\n"
                "Reuse this confirmed value for the current agent? The current "
                "agent still receives its own guarded readback, update when "
                "needed, and lifecycle validation."
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
        or candidates.get("tokenClaimEmissionConfirmed") is not True
        or not isinstance(candidates.get("candidates"), list)
        or not candidates["candidates"]
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
                and source_entra["evidence"].get(
                    "tokenClaimEmissionConfirmed"
                )
                is True
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
                and source_oidc["evidence"].get("claimMappingConfirmed")
                is True
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
                            "ServiceNow administrator-confirmed OIDC and user "
                            f"mapping for token claim "
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
            "label": "Reuse shared identity",
            "decision": "accept",
        },
        {
            "label": "Configure separately",
            "decision": "decline",
        },
        {
            "label": "Not now",
            "decision": "not-now",
        },
    ]
    return {
        "schemaVersion": "servicenow.shared-reuse-handoff.v1",
        "decision": "question-required",
        "candidate": copy.deepcopy(candidate),
        "reuseDecisionChoices": decision_choices,
        "question": {
            "header": "Reuse shared identity",
            "question": (
                "**Current target**\n"
                f"- Agent: {ACTIVE_PROFILE.agent_display_name} "
                f"(`{_agent_slug(context)}`)\n"
                f"- Environment: `{context['environment']['id']}`\n"
                f"- Realm: `{str(context['agent'].get('realm') or 'dev')}`\n"
                f"- Confirmed ServiceNow instance: "
                f"`{candidate['instanceName']}`\n\n"
                "**Reusable source**\n"
                f"- {candidate['sourceProfile'].upper()} agent "
                f"`{candidate['sourceAgentSlug']}`\n\n"
                "**Eligible recorded items**\n"
                f"{item_lines}\n\n"
                "Reuse avoids repeating compatible administrator setup, but "
                "each owning readiness check still runs for this agent.\n\n"
                "What would you like to do?"
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
            "Entra application details are verified by the phase's Microsoft "
            "Graph checkpoints after a client ID is supplied.",
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
    return {
        "status": "not-ready",
        "expected": resolution["expected"],
        "unhealthyExactCount": resolution["unhealthyExactCount"],
        "remediation": (
            "No exact healthy Connected Microsoft Entra ID User Login "
            "ServiceNow connection is currently visible. Finish creation or "
            "repair in the same environment, then choose Completed so the "
            "read-only inventory can verify it again."
        ),
    }


def _validated_claim_candidates(
    context: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    receipt = state.get("evidence", {}).get("identityClaimCandidates")
    if (
        not isinstance(receipt, dict)
        or receipt.get("kind")
        != "administrator-confirmed-claim-candidates"
        or receipt.get("entraAdministratorConfirmed") is not True
        or receipt.get("tokenClaimEmissionConfirmed") is not True
        or not isinstance(receipt.get("candidates"), list)
        or not receipt["candidates"]
    ):
        raise ServiceNowConnectError(
            "A Maker-confirmed Entra claim-candidate workbook is required."
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
) -> dict[str, Any]:
    if phase not in ADMIN_PHASES:
        raise ServiceNowConnectError("Unsupported ServiceNow admin phase.")
    if status not in {"completed", "reused"}:
        raise ServiceNowConnectError(
            "Admin operation status must be completed or reused."
        )
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)

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
        candidates = _validated_claim_candidates(context, state)
        workbook_client_id = normalize_client_id(
            str(candidates.get("applicationClientId") or "")
        )
        normalized_client_id = (
            normalize_client_id(client_id)
            if client_id is not None
            else workbook_client_id
        )
        if workbook_client_id != normalized_client_id:
            raise ServiceNowConnectError(
                "The explicitly supplied Application client ID conflicts "
                "with the Entra-confirmed workbook."
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
                "applicationRegistrationConfirmed": True,
                "clientId": normalized_client_id,
                "tokenClaimCandidates": copy.deepcopy(
                    selected_claims
                ),
                "selectedClaimName": selected_claims[0],
                "tokenClaimEmissionConfirmed": True,
                "userImpersonationScopeConfirmed": True,
                "connectorPreauthorizationConfirmed": True,
                "candidateSetSha256": candidates["candidateSetSha256"],
                "mappingWorkbookSha256": candidates[
                    "importedWorkbookSha256"
                ],
            }
        )
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
        mapping = _validated_identity_mapping(context, state)
        evidence.update(
            {
                "oidcCapabilityConfirmed": True,
                "runbookCompleted": True,
                "mappingDetailsCollected": True,
                "claimMappingConfirmed": True,
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


def _latest_requested_portal_url(state: dict[str, Any]) -> str | None:
    transactions = state.get("transactions")
    transactions = transactions if isinstance(transactions, dict) else {}
    portal_transactions = transactions.get("portal")
    portal_transactions = (
        portal_transactions if isinstance(portal_transactions, dict) else {}
    )
    candidates = [
        transaction
        for transaction in portal_transactions.values()
        if isinstance(transaction, dict)
        and transaction.get("status")
        in {"committed", "failed-unchanged", "reconciliation-required"}
        and isinstance(transaction.get("requestedPortalUrl"), str)
        and transaction["requestedPortalUrl"]
    ]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda transaction: str(transaction.get("preparedAt") or ""),
    )
    return str(latest["requestedPortalUrl"])


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
        if not validated_instance:
            missing_fields.append("instanceName")
        if not validated_resource:
            missing_fields.append("resourceUri")
        return {
            "status": "input-required",
            "creationMode": "manual",
            "agentId": context["agent"]["id"],
            "environmentId": context["environment"]["id"],
            "missingFields": missing_fields,
            "knownValues": {
                "instanceName": validated_instance,
                "resourceUri": validated_resource,
            },
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
        "instanceName": instance_name,
        "resourceUri": resource_uri,
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
        "instructions": [
            "Open https://copilotstudio.microsoft.com and select the target environment.",
            f"Open the {ACTIVE_PROFILE.agent_display_name} agent.",
            "Select Settings, then Connection settings.",
            "Find the ServiceNow connection and select its status link.",
            "Open the connection configuration and select Create new connection.",
            "Use the search box in the upper-right to search ServiceNow.",
            (
                "Select the Microsoft-published ServiceNow connector by "
                "choosing its + action."
            ),
            "Choose Microsoft Entra ID User Login.",
            "Enter the Instance Name and Resource URI shown in this output.",
            "Select Sign in, complete authentication, then select Submit.",
            "Wait until the credential status is Connected.",
            "Return to Connection settings and select Connect for ServiceNow.",
            "Choose the new connection and save the agent connection.",
            "Return to VS Code after the ServiceNow row shows Connected.",
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
    state.setdefault("evidence", {})["credential"] = evidence
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


def record_agent_connection_attestation(
    context: dict[str, Any],
    connection_id: str,
) -> dict[str, Any]:
    physical = _healthy_connection(context, connection_id)
    components = _agentbuilder_client(context).fetch_components(
        context["agent"]["id"]
    )

    normalized_connection_id = uuid.UUID(connection_id).hex
    state = _load_lifecycle_state(context, components)
    result = {
        "kind": "maker-attestation",
        "status": "completed",
        "mode": "maker-ui",
        "connectionId": normalized_connection_id,
        "displayName": physical.get("displayName"),
        "physicalStatus": physical.get("status"),
        "authMode": physical.get("authMode"),
        "makerAttested": True,
        "recordedAt": _utc_now(),
        "physicalVerifiedAt": _utc_now(),
        "binding": {
            "connectionId": normalized_connection_id,
            "environmentId": context["environment"]["id"],
            "agentId": context["agent"]["id"],
            "agentSlug": _agent_slug(context),
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "componentHash": _component_hash(components),
            "draftSemanticHash": _draft_semantic_hash(components),
        },
    }
    evidence = state.setdefault("evidence", {})
    selected = evidence.get("credential")
    if (
        isinstance(selected, dict)
        and selected.get("connectionId")
        and str(selected["connectionId"]).casefold()
        != normalized_connection_id.casefold()
    ):
        raise ServiceNowConnectError(
            "The attested Agent Connect credential differs from the selected "
            "lifecycle credential. Record the intended credential first."
        )
    evidence["agentConnection"] = result
    evidence.setdefault(
        "credential",
        {
            "connectionId": normalized_connection_id,
            "displayName": physical.get("displayName"),
            "connectorId": CONNECTOR_ID,
            "physicalStatus": physical.get("status"),
            "authMode": physical.get("authMode"),
            "environmentId": context["environment"]["id"],
            "selectedAt": _utc_now(),
            "lastVerifiedAt": _utc_now(),
        },
    )
    _write_lifecycle_state(context, state)
    return result


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


def _agent_connection_attestation_current(
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
    return not (
        not isinstance(attestation, dict)
        or attestation.get("kind") != "maker-attestation"
        or attestation.get("status") != "completed"
        or attestation.get("makerAttested") is not True
        or attestation.get("physicalStatus") != "Connected"
        or str(attestation.get("connectionId") or "").replace("-", "")
        != normalized_connection_id
        or not isinstance(attestation_binding, dict)
        or attestation_binding.get("draftSemanticHash")
        != _draft_semantic_hash(components)
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
    attestation_current = _agent_connection_attestation_current(
        state,
        components,
    )
    if require_agent_attestation and not attestation_current:
        raise ServiceNowConnectError(
            "Record a current Agent Connect observation for this saved draft "
            "and selected credential before recording Test evidence."
        )
    summary = summarize_components(components)
    reference = summary["reference"]
    return _canonical_json_hash(
        {
            "provider": PROVIDER_KEY,
            "profile": PROFILE_KEY,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "environmentId": context["environment"]["id"],
            "connectionId": credential["connectionId"],
            "agentConnectionRecordedAt": (
                attestation.get("recordedAt")
                if isinstance(attestation, dict)
                else None
            ),
            "reference": {
                "id": reference.get("id"),
                "logicalName": reference.get("logicalName"),
                "authMode": reference.get("authMode"),
                "instanceName": reference.get("instanceName"),
                "resourceUri": reference.get("resourceUri"),
            },
            "serviceNowInvokeConnectorActionCount": summary[
                "serviceNowInvokeConnectorActionCount"
            ],
            "serviceNowInvokeFlowActionCount": summary[
                "serviceNowInvokeFlowActionCount"
            ],
        }
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
    state = _load_lifecycle_state(context)
    return _rollback_topic_transaction(
        context,
        _agentbuilder_client(context),
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
    state = _load_lifecycle_state(context)
    setup = _admin_setup(state)
    expected_instance = setup["preflight"].get("instanceName")
    if not isinstance(expected_instance, str) or not expected_instance:
        raise ServiceNowConnectError(
            "The lifecycle has no confirmed ServiceNow instance."
        )
    agentbuilder = _agentbuilder_client(context)
    before = agentbuilder.fetch_components(context["agent"]["id"])
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
    before_summary = summarize_components(before)
    inactive = [
        topic
        for topic in before_summary["serviceNowTopics"]
        if topic.get("state") != "Active"
        or topic.get("status") != "Active"
    ]
    if inactive:
        payload = build_enable_all_topics_payload(before)
    state = _load_lifecycle_state(context, before)
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
    state = _load_lifecycle_state(context, components)
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

    links = maker_portal_links(context)
    agent_url = links["copilotStudioAgent"]["url"]
    inactive_names = [
        str(topic.get("displayName") or topic.get("schemaName") or "")
        for topic in inactive
    ]
    question = (
        f"Purpose: prepare the {ACTIVE_PROFILE.product_name} topics for this "
        f"exact agent.\n\nOwner: ESS Maker / Agent Developer.\n\n"
        f"Open {ACTIVE_PROFILE.agent_display_name}: {agent_url}\n\n"
        f"Current topic inventory: {total} {ACTIVE_PROFILE.product_name} "
        f"topics; {active} active and {len(inactive)} inactive.\n\n"
        f"Inactive {ACTIVE_PROFILE.product_name} topics:\n"
        + "\n".join(f"- {name}" for name in inactive_names)
        + (
            "\n\nEnable all inactive ServiceNow topics, or explicitly keep "
            "their current states? Only topics in this exact inventory are "
            "in scope; unrelated topics remain unchanged."
        )
    )
    return {
        **base,
        "decision": "question-required",
        "actionResult": None,
        "question": {
            "header": "ServiceNow topics",
            "question": question,
            "choices": [
                "Enable all topics",
                "Keep current states",
                "Not now",
            ],
            "allowFreeformInput": False,
        },
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


def _phase_customer_label(
    phase_id: str,
    contract_label: str,
) -> str:
    labels = {
        "preflight": "Check existing setup",
        "plugin-prerequisites": "Confirm HR ServiceNow prerequisite",
        "entra-registration": "Confirm Entra identity options",
        "servicenow-oidc": "Confirm ServiceNow user mapping",
        "credential": "Check ServiceNow connection",
        "topics": "Prepare agent topics",
        "portal-url": "Set employee portal URL",
        "agent-connection": "Connect this agent",
        "test": "Test ServiceNow",
        "publish": "Publish agent",
    }
    return labels.get(phase_id, contract_label)


def _build_phase_progress(
    contract: dict[str, Any],
    state: dict[str, Any] | None,
    decision: dict[str, Any],
    *,
    executed_actions: frozenset[str],
    verified_phases: frozenset[str],
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
    items: list[dict[str, str]] = []
    for phase in phases:
        if not isinstance(phase, dict):
            raise ServiceNowConnectError(
                "ServiceNow lifecycle contract has an invalid progress phase."
            )
        phase_id = phase.get("id")
        label = phase.get("label")
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
    display_name = str(contract.get("displayName") or "ServiceNow")
    icon_by_status = {
        "complete-checked": "✅",
        "complete-manual": "✅",
        "complete-reused": "✅",
        "rechecking": "🔄",
        "checking": "🔄",
        "current": "🔄",
        "pending": "⬜",
        "needs-attention": "❌",
    }

    def render_checklist(
        *,
        current_status: tuple[str, str] | None = None,
    ) -> str:
        lines = []
        for item in items:
            icon = icon_by_status[item["status"]]
            text = item["text"]
            if current_status is not None and item["id"] == current_id:
                icon, text = current_status
            lines.append(f"- {icon} {item['customerLabel']} — {text}")
        return "Connection progress:\n\n" + "\n".join(lines)

    checklist = render_checklist()
    final_message = (
        f"Complete — every {display_name} step was checked in this run."
        if decision.get("decision") == "complete"
        and completed_count == len(items)
        else None
    )
    progress: dict[str, Any] = {
        "schemaVersion": "servicenow.phase-progress.v1",
        "mode": "resume" if has_prior_progress else "fresh",
        "headline": (
            f"Resuming {display_name} connection."
            if has_prior_progress
            else f"Starting {display_name} connection."
        ),
        "completedCount": completed_count,
        "totalCount": len(items),
        "items": items,
        "checklistText": checklist,
        "currentPhase": None,
        "finalText": (
            f"{checklist}\n\n{final_message}"
            if final_message is not None
            else None
        ),
    }
    if current_item is not None:
        label = current_item["customerLabel"]
        start_verb = {
            "rechecking": "Rechecking",
            "checking": "Checking",
            "needs-attention": "Needs attention",
        }.get(current_item["status"], "Starting")
        progress["currentPhase"] = {
            **current_item,
            "startText": f"{start_verb}: {label}",
            "questionText": (
                "**Progress**\n\n"
                + render_checklist(current_status=("⏳", "Waiting"))
            ),
            "waitingChecklistText": render_checklist(
                current_status=("⏳", "Waiting")
            ),
            "errorChecklistText": render_checklist(
                current_status=("❌", "Needs attention")
            ),
            "waitingText": f"Waiting — {label}: your input is needed.",
            "actionFinishedText": (
                f"Action finished — checking: {label}"
            ),
            "needsAttentionText": f"Needs attention — {label}.",
        }
    return progress


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


def resume_handoff(
    context: dict[str, Any],
    *,
    executed_actions: frozenset[str] = frozenset(),
    verified_phases: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    state_path = _lifecycle_state_path(context)
    state = None
    if state_path.exists():
        state = _load_lifecycle_state(context)
        _write_lifecycle_state(context, state)
    decision = decide_next_step(
        Path(context["root"]),
        provider=ACTIVE_PROFILE.provider_key,
        agent_slug=_agent_slug(context),
        executed_actions=executed_actions,
        verified_phases=verified_phases,
    )
    result: dict[str, Any] = {
        "schemaVersion": "servicenow.resume-handoff.v1",
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "lifecycle": decision,
        "progress": _resume_progress(
            context,
            decision,
            executed_actions=executed_actions,
            verified_phases=verified_phases,
        ),
    }
    pending_input = _pending_preflight_input(state, decision)
    if pending_input is not None:
        result["pendingInput"] = pending_input
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
            "commands": commands,
        }
    return result


_VALIDATION_REALMS = {
    "dev": DEV_REALM,
    "test": TEST_REALM,
    "prod": PROD_REALM,
}


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
            expected_family = (
                {
                    f"{prefix}{suffix}-001"
                    for suffix in ENTRA_CHECKPOINT_SUFFIXES
                }
                if phase_contract.get("id") == "entra-registration"
                else None
            )
            if expected_family is not None:
                if not expected_family.issubset(results):
                    return False
            elif not any(key.startswith(prefix) for key in results):
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


def _dev_connect_completion(
    context: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    state_path = _lifecycle_state_path(context)
    if not state_path.exists():
        return False, {"reason": "no-dev-lifecycle"}
    state = _load_lifecycle_state(context)
    contract = _load_json(Path(context["root"]) / CONTRACT_PATH)
    revision = contract.get("contractRevision")
    if (
        state.get("attested") is not True
        or state.get("acceptedContractRevision") != revision
    ):
        return False, {
            "reason": "contract-reapproval-required",
            "acceptedContractRevision": state.get(
                "acceptedContractRevision"
            ),
            "contractRevision": revision,
        }
    phases = contract.get("phases")
    state_phases = state.get("phases")
    if not isinstance(phases, list) or not isinstance(state_phases, dict):
        return False, {"reason": "invalid-phase-state"}
    phase_failures = []
    for phase_contract in phases:
        if not isinstance(phase_contract, dict):
            return False, {"reason": "invalid-phase-contract"}
        phase_id = phase_contract.get("id")
        if not _phase_contract_complete(state, phase_contract):
            phase_failures.append(str(phase_id or "<invalid>"))
    if phase_failures:
        return False, {
            "reason": "required-phases-incomplete",
            "phases": phase_failures,
        }

    evidence = state.get("evidence")
    test_record = evidence.get("test") if isinstance(evidence, dict) else None
    binding = (
        test_record.get("binding")
        if isinstance(test_record, dict)
        else None
    )
    credential = (
        evidence.get("credential") if isinstance(evidence, dict) else None
    )
    expected_binding = {
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "connectionId": (
            credential.get("connectionId")
            if isinstance(credential, dict)
            else None
        ),
        "draftSemanticHash": state.get("draftSemanticHash"),
        "connectionBindingHash": state.get("connectionBindingHash"),
    }
    binding_matches = isinstance(binding, dict) and all(
        binding.get(key) == value and value
        for key, value in expected_binding.items()
    )
    if (
        not isinstance(test_record, dict)
        or test_record.get("status") != "completed"
        or test_record.get("result") != "pass"
        or test_record.get("failureCategory") is not None
        or test_record.get("promptCategory")
        != ACTIVE_PROFILE.test_prompt_category
        or not binding_matches
    ):
        return False, {"reason": "current-test-evidence-missing"}
    return True, {
        "reason": "complete",
        "contractRevision": revision,
        "phaseCount": len(phases),
        "testBinding": copy.deepcopy(expected_binding),
    }


def validation_realm_handoff(
    context: dict[str, Any],
) -> dict[str, Any]:
    complete, evidence = _dev_connect_completion(context)
    if not complete:
        reason = str(evidence.get("reason") or "current Dev Connect is incomplete")
        problem = (
            "Test/Prod validation is locked because this exact agent does not "
            f"have a complete current Dev Connect record ({reason})."
        )
        links = maker_portal_links(context)
        recovery = _recovery_handoff(
            problem=problem,
            category="Dev prerequisite incomplete",
            owner="ESS Maker / Agent Developer",
            where=links["copilotStudioAgent"]["url"],
            values=(
                f"Provider: {ACTIVE_PROFILE.agent_display_name}; agent: "
                f"{_agent_slug(context)}; environment: the currently bound Dev "
                "environment. Use the existing lifecycle's validated values; "
                "do not copy Test/Prod values into Dev."
            ),
            action=(
                "Resume the normal Dev ServiceNow Connect lifecycle at its "
                "first incomplete or regressed phase."
            ),
            success=(
                "Every required Dev phase is currently complete and the "
                "bounded Test pane result is Pass for the current saved draft "
                "and selected connection."
            ),
            recheck=(
                "Rerun `validation-realm-handoff` only after Dev Connect "
                "completes; then choose Test or Prod."
            ),
        )
        return {
            "schemaVersion": "servicenow.realm-validation-handoff.v1",
            "status": "dev-connect-required",
            "provider": ACTIVE_PROFILE.provider_key,
            "profile": ACTIVE_PROFILE.key,
            "agentSlug": _agent_slug(context),
            "agentId": context["agent"]["id"],
            "devCompletion": evidence,
            "recoveryHandoff": recovery,
            "question": None,
            "stateChanged": False,
        }
    return {
        "schemaVersion": "servicenow.realm-validation-handoff.v1",
        "status": "choice-required",
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "devCompletion": evidence,
        "question": {
            "header": "Choose validation environment",
            "question": (
                "This exact agent has a complete current Dev Connect record. "
                "Which environment do you want to validate? Test and Prod "
                "validation is read-only and never promotes, imports, "
                "configures, tests with employee data, or publishes the agent."
            ),
            "options": [
                {"label": "Dev"},
                {"label": "Test"},
                {"label": "Prod"},
            ],
            "allowFreeformInput": False,
        },
        "stateChanged": False,
    }


def _realm_deployment_record(
    state: dict[str, Any],
    realm: str,
) -> dict[str, Any] | None:
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    records = evidence.get("realmDeployments")
    records = records if isinstance(records, dict) else {}
    record = records.get(realm)
    return record if isinstance(record, dict) else None


def _realm_deployment_question(
    context: dict[str, Any],
    *,
    realm: str,
) -> dict[str, Any]:
    realm_label = realm.title()
    source_url = maker_portal_links(context)["copilotStudioAgent"]["url"]
    return {
        "header": f"Deploy this agent to {realm_label}",
        "question": (
            f"**Purpose**\nCreate the missing {realm_label} target for the "
            f"current {ACTIVE_PROFILE.agent_display_name} source agent. This "
            "is a customer-controlled prerequisite; read-only validation will "
            "not deploy, promote, import, publish, or change the target.\n\n"
            "**Owner**\nCopilot Studio / Power Platform ALM owner for this "
            "agent family.\n\n"
            f"**Source agent**\n{ACTIVE_PROFILE.agent_display_name} "
            f"(`{_agent_slug(context)}`), requested realm `{realm}`.\n\n"
            f"**Open**\n{source_url}\n\n"
            "**Action**\n"
            f"1. On the source agent management page, select **Deploy to "
            f"{realm_label}** in the upper-right.\n"
            "2. Select **Save** in the lower-left.\n"
            "3. Select **Deploy**.\n"
            "4. Wait for deployment to complete, then select **Open Agent** "
            f"to open the {realm_label} agent.\n\n"
            "**Already deployed**\nIf this exact target already opens from a "
            "prior deployment, do not deploy it again; choose Completed so "
            "the kit can perform exact read-only validation.\n\n"
            "**If unavailable**\nIf the deployment button is unavailable or "
            "you do not have deployment permission, stop and give these steps "
            "to the actual ALM owner. Do not choose another button, elevate "
            "your own permissions, or recreate the agent.\n\n"
            "**Success**\nThe requested target agent opens in Copilot Studio. "
            "This does not prove validation passed. After you choose "
            "Completed, the kit must still prove the exact realm, family, "
            "environment, agent ID, and schema through read-only APIs, then "
            "the Maker must run the bounded Test pane check."
        ),
        "options": [
            {"label": "Completed"},
            {"label": "Not yet"},
        ],
        "allowFreeformInput": False,
    }


def record_realm_deployment(
    context: dict[str, Any],
    *,
    realm: str,
    status: str,
) -> dict[str, Any]:
    if realm not in {"test", "prod"}:
        raise ServiceNowConnectError(
            "Realm deployment evidence is supported only for Test or Prod."
        )
    if status not in {"not-deployed", "deployment-completed"}:
        raise ServiceNowConnectError(
            "Realm deployment status must be not-deployed or "
            "deployment-completed."
        )
    complete, dev_evidence = _dev_connect_completion(context)
    if not complete:
        raise ServiceNowConnectError(
            "Realm deployment guidance requires a complete current Dev "
            "Connect record.",
            details=dev_evidence,
        )
    state = _load_lifecycle_state(context)
    recorded_at = _utc_now()
    record = {
        "kind": "maker-attestation",
        "status": status,
        "realm": realm,
        "recordedAt": recorded_at,
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "sourceAgentId": context["agent"]["id"],
        "sourceEnvironmentId": context["environment"]["id"],
    }
    state.setdefault("evidence", {}).setdefault(
        "realmDeployments",
        {},
    )[realm] = record
    _write_lifecycle_state(context, state)
    question = (
        _realm_deployment_question(context, realm=realm)
        if status == "not-deployed"
        else None
    )
    return {
        "schemaVersion": "servicenow.realm-deployment.v1",
        "status": (
            "deployment-required"
            if status == "not-deployed"
            else "validation-required"
        ),
        "realm": realm,
        "deploymentEvidence": copy.deepcopy(record),
        "question": question,
        "remoteMutationCount": 0,
        "next": (
            {
                "action": "maker-deploys-target",
                "instruction": (
                    "Show the returned deployment question exactly and wait "
                    "for the Maker."
                ),
            }
            if status == "not-deployed"
            else {
                "action": "rerun-read-only-realm-validation",
                "command": (
                    "python scripts/connect_servicenow_da.py "
                    f"--provider {ACTIVE_PROFILE.provider_key} "
                    f"--agent-slug {_agent_slug(context)} validate-realm "
                    f"--realm {realm}"
                ),
                "instruction": (
                    "Maker-reported deployment is not validation evidence. "
                    "Rerun exact read-only target discovery and checks."
                ),
            }
        ),
    }


def _realm_matches(value: Any, realm: int) -> bool:
    if type(value) is int:
        return value == realm
    return (
        isinstance(value, str)
        and value.casefold()
        == {DEV_REALM: "dev", TEST_REALM: "test", PROD_REALM: "prod"}[
            realm
        ]
    )


def _realm_schema_names(base_schema: str, realm: str) -> set[str]:
    normalized = str(base_schema).strip().casefold()
    if not normalized:
        return set()
    return {
        normalized,
        f"{normalized}_{realm.casefold()}",
    }


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
        f"**Recheck and resume**\n{recheck}"
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


def _target_agent_validation_url(
    context: dict[str, Any],
    *,
    environment_id: str | None,
    agent_id: str | None,
) -> str:
    origin = PORTAL_ORIGINS[context["environment"]["ring"]][
        "copilotStudio"
    ]
    if not environment_id or not agent_id:
        return origin
    return (
        f"{origin}/environments/{environment_id}/bots/{agent_id}/overview"
    )


def _target_realm_discovery_recovery(
    context: dict[str, Any],
    *,
    realm: str,
    problem: str,
    category: str,
    action: str,
    environment_id: str | None = None,
    agent_id: str | None = None,
    retry_after: str | None = None,
) -> dict[str, str]:
    where = _target_agent_validation_url(
        context,
        environment_id=environment_id,
        agent_id=agent_id,
    )
    retry = (
        f" Wait at least the returned Retry-After interval ({retry_after})"
        " before the next read."
        if retry_after
        else ""
    )
    return _recovery_handoff(
        problem=problem,
        category=category,
        owner="Power Platform Maker/Admin",
        where=where,
        values=(
            f"Target realm: {realm.title()}. Use only the native ALM target "
            "identity returned for this exact agent family. Do not copy Dev "
            "environment, agent, instance, or App A values into this target."
        ),
        action=action + retry,
        success=(
            f"Exactly one {realm.title()} environment and exact target agent "
            "are proved from native ALM plus environment inventory."
        ),
        recheck=(
            f"Rerun only `{realm.title()}` read-only validation. Continue to "
            "target checks only after exact target discovery succeeds."
        ),
    )


def _normalize_inventory_environment_id(value: str) -> str:
    candidate = str(value).strip()
    if candidate.casefold().startswith("default-"):
        candidate = candidate[len("Default-") :]
    return str(uuid.UUID(candidate))


def _transport_error_evidence(exc: BaseException) -> dict[str, Any]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    text = " | ".join(str(item) for item in chain if str(item))
    lowered = text.casefold()
    errno = next(
        (
            value
            for item in chain
            for value in (getattr(item, "errno", None),)
            if isinstance(value, int)
        ),
        None,
    )
    if any(isinstance(item, requests.exceptions.ConnectTimeout) for item in chain):
        category = "connect-timeout"
    elif any(isinstance(item, requests.exceptions.SSLError) for item in chain):
        category = "tls"
    elif (
        "nameresolution" in lowered
        or "getaddrinfo" in lowered
        or "name or service not known" in lowered
    ):
        category = "dns"
    elif errno in {61, 10061} or "connection refused" in lowered:
        category = "connection-refused"
    elif any(
        isinstance(item, requests.exceptions.ConnectionError)
        for item in chain
    ):
        category = "connection"
    elif isinstance(exc, OSError):
        category = "os-transport"
    else:
        category = "read-error"
    return {
        "transportCategory": category,
        "errorTypeChain": [type(item).__name__ for item in chain],
        "errno": errno,
        "detail": text or type(exc).__name__,
    }


def _no_retry_session() -> requests.Session:
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=0,
                connect=0,
                read=0,
                redirect=0,
                status=0,
                respect_retry_after_header=True,
            )
        ),
    )
    return session


def _without_automatic_retries(client: Any) -> Any:
    session = getattr(client, "session", None)
    if isinstance(session, requests.Session):
        session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=0,
                    connect=0,
                    read=0,
                    redirect=0,
                    status=0,
                    respect_retry_after_header=True,
                )
            ),
        )
    return client


def _resolve_target_realm(
    context: dict[str, Any],
    *,
    realm: str,
) -> dict[str, Any]:
    realm_value = _VALIDATION_REALMS[realm]
    token = _agentbuilder_token(context)
    dev_client = _without_automatic_retries(_agentbuilder_client(context))
    dev_agent_id = _normalize_agent_id(context["agent"]["id"])
    realms = dev_client.get_realms(dev_agent_id)
    configuration = dev_client.get_realm_configuration(
        dev_agent_id,
        realm_value,
    )
    if not _realm_matches(configuration.get("realm"), realm_value):
        problem = (
            f"Native ALM configuration did not identify the {realm.title()} "
            "realm."
        )
        raise ServiceNowConnectError(
            problem,
            details={
                "realm": realm,
                "recoveryHandoff": _target_realm_discovery_recovery(
                    context,
                    realm=realm,
                    problem=problem,
                    category="Target identity mismatch",
                    action=(
                        "Have the ALM/Power Platform owner correct the native "
                        "realm association for this exact agent family."
                    ),
                ),
            },
        )
    target_agent_id = _normalize_agent_id(
        str(configuration.get("cdsBotId") or "")
    )
    family_id = str(configuration.get("grsRepositoryId") or "").strip()
    if not family_id:
        problem = f"The {realm.title()} realm has no ALM-family identity."
        raise ServiceNowConnectError(
            problem,
            details={
                "realm": realm,
                "recoveryHandoff": _target_realm_discovery_recovery(
                    context,
                    realm=realm,
                    problem=problem,
                    category="Missing target configuration",
                    action=(
                        "Have the ALM/Power Platform owner restore the exact "
                        "agent-family association."
                    ),
                    agent_id=target_agent_id,
                ),
            },
        )
    schema_name = str(configuration.get("schemaName") or "").strip()
    commit_sha = str(configuration.get("commitSha") or "").strip()
    expected_schema = str(context["agent"]["schema_name"])
    accepted_schema_names = _realm_schema_names(expected_schema, realm)
    if (
        schema_name
        and schema_name.casefold()
        not in accepted_schema_names
    ):
        problem = (
            f"The {realm.title()} realm identifies a different agent schema. "
            f"Expected `{expected_schema}` or "
            f"`{expected_schema}_{realm}` for the selected "
            f"{ACTIVE_PROFILE.agent_display_name} agent, but native ALM "
            f"returned `{schema_name}` for target agent `{target_agent_id}`."
        )
        recovery = _target_realm_discovery_recovery(
            context,
            realm=realm,
            problem=problem,
            category="Target identity mismatch",
            action=(
                "In the Power Platform ALM/deployment configuration for this "
                "exact agent family, verify that the target realm points to "
                "the intended ITSM/HRSD agent. Correct the binding only after "
                "the owner confirms which target agent is intended; do not "
                "select a different agent automatically."
            ),
            agent_id=target_agent_id,
        )
        recovery["owner"] = (
            "Copilot Studio / Power Platform ALM owner for this agent family"
        )
        recovery["where"] = (
            f"{PORTAL_ORIGINS[context['environment']['ring']]['copilotStudio']}"
            " -> the native ALM realm configuration for the selected agent "
            "family. The exact Test environment link is not available because "
            "environment discovery has not run."
        )
        recovery["values"] = (
            f"Selected source: {ACTIVE_PROFILE.agent_display_name}; slug: "
            f"`{_agent_slug(context)}`; Dev agent ID: "
            f"`{context['agent']['id']}`; Dev environment: "
            f"`{context['environment']['id']}`; requested realm: "
            f"`{realm}`. Expected schema: `{expected_schema}`. Native ALM "
            f"configured target agent ID: `{target_agent_id}`; configured "
            f"schema: `{schema_name}`; ALM family: `{family_id}`; commit SHA: "
            f"`{commit_sha or 'not returned'}`. Observed target environment, "
            "fetched target agent ID, and observed target schema: not reached "
            "and unknown because the identity guard stopped before "
            "environment inventory."
        )
        recovery["message"] = _recovery_handoff(
            problem=recovery["problem"],
            category=recovery["category"],
            owner=recovery["owner"],
            where=recovery["where"],
            values=recovery["values"],
            action=recovery["action"],
            success=recovery["success"],
            recheck=recovery["recheck"],
        )["message"]
        raise ServiceNowConnectError(
            problem,
            details={
                "realm": realm,
                "expectedSchemaName": expected_schema,
                "expectedSchemaNames": sorted(accepted_schema_names),
                "configuredSchemaName": schema_name,
                "targetAgentId": target_agent_id,
                "targetEnvironmentId": None,
                "almFamilyId": family_id,
                "commitSha": commit_sha or None,
                "observedTargetAgentId": None,
                "observedSchemaName": None,
                "recoveryHandoff": recovery,
            },
        )

    try:
        environments = list_environments(
            token,
            context["environment"]["ring"],
            api_version=context["environment"].get(
                "api_version",
                "2024-10-01",
            ),
            session=_no_retry_session(),
        )
    except AgentBuilderHTTPError as exc:
        problem = (
            "Could not list the environments needed to prove the exact "
            f"{realm.title()} target."
        )
        category = (
            "Read throttled"
            if exc.status_code == 429
            else "Read permission"
            if exc.status_code in {401, 403}
            else "Read or network error"
        )
        raise ServiceNowConnectError(
            problem,
            details={
                "realm": realm,
                "httpStatus": exc.status_code,
                "errorCode": exc.error_code,
                "recoveryHandoff": _target_realm_discovery_recovery(
                    context,
                    realm=realm,
                    problem=problem,
                    category=category,
                    action=(
                        "Restore the minimum environment-inventory read access "
                        "for the current account and reauthenticate if needed."
                    ),
                    retry_after=exc.retry_after,
                ),
            },
        ) from exc
    except AgentBuilderError as exc:
        problem = (
            "Could not read the environment inventory needed to prove the "
            f"exact {realm.title()} target."
        )
        raise ServiceNowConnectError(
            problem,
            details={
                "realm": realm,
                "error": type(exc).__name__,
                "recoveryHandoff": _target_realm_discovery_recovery(
                    context,
                    realm=realm,
                    problem=problem,
                    category="Read or network error",
                    action=(
                        "Restore the current environment-inventory read path "
                        "without changing target configuration."
                    ),
                ),
            },
        ) from exc
    matches: list[dict[str, Any]] = []
    discovery_errors: list[dict[str, Any]] = []
    for environment in environments:
        raw_environment_id = environment.get("id") or environment.get("name")
        if not isinstance(raw_environment_id, str):
            continue
        environment_id: str | None = None
        client: Any = None
        try:
            environment_id = _normalize_inventory_environment_id(
                raw_environment_id
            )
            client = _without_automatic_retries(
                _agentbuilder_client_for_environment(
                    context,
                    environment_id=environment_id,
                    token=token,
                    require_resolved_host=True,
                )
            )
            agent = client.get_agent(target_agent_id)
            returned_id = _normalize_agent_id(str(agent.get("botId") or ""))
            observed_schema = str(
                agent.get("schemaName")
                or agent.get("schema_name")
                or ""
            ).strip()
            if returned_id != target_agent_id:
                discovery_errors.append(
                    {
                        "environmentId": environment_id,
                        "inventoryEnvironmentId": raw_environment_id,
                        "error": "TargetAgentIdMismatch",
                        "expectedAgentId": target_agent_id,
                        "observedAgentId": returned_id,
                    }
                )
                continue
            if not _realm_matches(agent.get("realm"), realm_value):
                discovery_errors.append(
                    {
                        "environmentId": environment_id,
                        "inventoryEnvironmentId": raw_environment_id,
                        "error": "TargetRealmMismatch",
                        "expectedRealm": realm,
                        "observedRealm": agent.get("realm"),
                        "targetAgentId": target_agent_id,
                    }
                )
                continue
            if (
                observed_schema
                and observed_schema.casefold()
                not in accepted_schema_names
            ):
                discovery_errors.append(
                    {
                        "environmentId": environment_id,
                        "inventoryEnvironmentId": raw_environment_id,
                        "error": "TargetSchemaMismatch",
                        "expectedSchemaName": expected_schema,
                        "expectedSchemaNames": sorted(
                            accepted_schema_names
                        ),
                        "configuredSchemaName": schema_name or None,
                        "observedSchemaName": observed_schema,
                        "targetAgentId": target_agent_id,
                    }
                )
                continue
            if not schema_name and not observed_schema:
                discovery_errors.append(
                    {
                        "environmentId": environment_id,
                        "inventoryEnvironmentId": raw_environment_id,
                        "error": "TargetSchemaUnknown",
                        "expectedSchemaName": expected_schema,
                        "configuredSchemaName": None,
                        "observedSchemaName": None,
                        "targetAgentId": target_agent_id,
                    }
                )
                continue
            matches.append(
                {
                    "environmentId": environment_id,
                    "inventoryEnvironmentId": raw_environment_id,
                    "environmentName": environment.get("displayName"),
                    "agentId": target_agent_id,
                    "schemaName": schema_name or observed_schema,
                    "observedSchemaName": observed_schema or None,
                    "almFamilyId": family_id,
                    "commitSha": commit_sha,
                    "client": client,
                }
            )
        except AgentBuilderHTTPError as exc:
            if exc.status_code in {401, 403, 429}:
                problem = (
                    "Target-realm agent discovery cannot continue after an "
                    f"authorization or throttling response in environment "
                    f"{environment_id}."
                )
                raise ServiceNowConnectError(
                    problem,
                    details={
                        "realm": realm,
                        "environmentId": environment_id,
                        "statusCode": exc.status_code,
                        "errorCode": exc.error_code,
                        "requestId": exc.request_id,
                        "correlationId": exc.correlation_id,
                        "retryAfter": exc.retry_after,
                        "mutationMayHaveOccurred": False,
                        "recoveryHandoff": _target_realm_discovery_recovery(
                            context,
                            realm=realm,
                            problem=problem,
                            category=(
                                "Read throttled"
                                if exc.status_code == 429
                                else "Read permission"
                            ),
                            action=(
                                "Restore read access to this candidate target "
                                "environment; do not skip it or select another "
                                "environment as a fallback."
                            ),
                            environment_id=environment_id,
                            agent_id=target_agent_id,
                            retry_after=exc.retry_after,
                        ),
                    },
                ) from exc
            discovery_errors.append(
                {
                    "environmentId": environment_id,
                    "inventoryEnvironmentId": raw_environment_id,
                    "error": type(exc).__name__,
                    "statusCode": exc.status_code,
                    "requestPath": (
                        "/copilotstudio/minimalBots/api/"
                        f"{target_agent_id}"
                    ),
                }
            )
        except (AgentBuilderError, OSError, ValueError) as exc:
            transport = _transport_error_evidence(exc)
            discovery_errors.append(
                {
                    "environmentId": environment_id,
                    "inventoryEnvironmentId": raw_environment_id,
                    "error": type(exc).__name__,
                    "requestPath": (
                        "/copilotstudio/minimalBots/api/"
                        f"{target_agent_id}"
                    ),
                    "requestHost": getattr(client, "host", None),
                    "environmentIdSource": (
                        "default-prefix-tenant-guid"
                        if raw_environment_id.casefold().startswith("default-")
                        else "inventory-guid"
                    ),
                    **transport,
                }
            )
    unknown_discovery_errors = [
        row
        for row in discovery_errors
        if row.get("error")
        not in {
            "TargetAgentIdMismatch",
            "TargetRealmMismatch",
            "TargetSchemaMismatch",
            "TargetSchemaUnknown",
        }
        and row.get("statusCode") != 404
    ]
    if len(matches) != 1:
        problem = (
            f"Could not prove one exact {realm.title()} environment and agent "
            "target from native ALM and environment inventory."
        )
        recovery = _target_realm_discovery_recovery(
            context,
            realm=realm,
            problem=problem,
            category="Ambiguous or missing exact target",
            action=(
                "Have the ALM/Power Platform owner correct the native "
                "target association or restore read access to every "
                "candidate environment. Do not choose a partial match."
            ),
            agent_id=target_agent_id,
        )
        not_found_errors = [
            row
            for row in discovery_errors
            if row.get("statusCode") == 404
        ]
        read_errors = unknown_discovery_errors
        if read_errors:
            recovery["category"] = "Candidate environment read unavailable"
            recovery["owner"] = "Power Platform environment owner"
            recovery["action"] = (
                "Restore the supported AgentBuilder read endpoint for each "
                "unreadable candidate environment, then rerun only target "
                "discovery. Do not repair ALM binding, deploy a different "
                "agent, or grant permissions based only on an endpoint or "
                "network failure."
            )
            recovery["values"] = (
                "Unreadable candidate lookups: "
                + "; ".join(
                    (
                        f"inventory ID `{row.get('inventoryEnvironmentId')}`, "
                        f"normalized ID `{row.get('environmentId') or 'unknown'}`, "
                        f"host `{row.get('requestHost') or 'unresolved'}`, "
                        f"path `{row.get('requestPath') or 'not reached'}`, "
                        f"transport `{row.get('transportCategory') or 'unknown'}`, "
                        f"errno `{row.get('errno') if row.get('errno') is not None else 'none'}`, "
                        f"error `{row.get('error')}`"
                    )
                    for row in read_errors
                )
                + ". Target presence in these environments remains unknown."
            )
            recovery["message"] = _recovery_handoff(
                problem=recovery["problem"],
                category=recovery["category"],
                owner=recovery["owner"],
                where=recovery["where"],
                values=recovery["values"],
                action=recovery["action"],
                success=recovery["success"],
                recheck=recovery["recheck"],
            )["message"]
        elif discovery_errors and len(not_found_errors) == len(discovery_errors):
            recovery["category"] = "Target agent not found"
            recovery["owner"] = (
                "Copilot Studio / Power Platform ALM deployment owner"
            )
            recovery["action"] = (
                f"Verify that the {realm.title()} deployment exists in the "
                "intended target environment and that native realm metadata "
                "returns the deployed target agent identity. HTTP 404 means "
                "the requested agent resource was not found at that candidate "
                "endpoint; it does not by itself prove missing permission or "
                "a broken binding. Do not grant access or choose another agent "
                "without target evidence."
            )
            recovery["values"] = (
                f"Native realm target agent ID: `{target_agent_id}`. "
                "Candidate lookups: "
                + "; ".join(
                    (
                        f"environment `{row.get('environmentId')}`, path "
                        f"`{row.get('requestPath')}`, HTTP "
                        f"{row.get('statusCode')}"
                    )
                    for row in not_found_errors
                )
                + ". Expected realm and schemas remain bound to the selected "
                f"agent: `{realm}` and "
                f"`{context['agent']['schema_name']}` or "
                f"`{context['agent']['schema_name']}_{realm}`."
            )
            recovery["message"] = _recovery_handoff(
                problem=recovery["problem"],
                category=recovery["category"],
                owner=recovery["owner"],
                where=recovery["where"],
                values=recovery["values"],
                action=recovery["action"],
                success=recovery["success"],
                recheck=recovery["recheck"],
            )["message"]
        schema_evidence = [
            row
            for row in discovery_errors
            if row.get("error")
            in {"TargetSchemaMismatch", "TargetSchemaUnknown"}
        ]
        if schema_evidence and not read_errors:
            rendered = "; ".join(
                (
                    f"environment `{row.get('environmentId')}`: expected "
                    f"`{row.get('expectedSchemaName')}`, configured "
                    f"`{row.get('configuredSchemaName') or 'unknown'}`, "
                    f"observed "
                    f"`{row.get('observedSchemaName') or 'unknown'}`"
                )
                for row in schema_evidence
            )
            recovery["values"] = (
                f"Accepted selected-agent schemas for {realm.title()}: "
                f"`{context['agent']['schema_name']}` or "
                f"`{context['agent']['schema_name']}_{realm}`. Native ALM target agent "
                f"ID: `{target_agent_id}`. Candidate schema evidence: "
                f"{rendered}. Do not accept an unknown or mismatched schema."
            )
            recovery["message"] = _recovery_handoff(
                problem=recovery["problem"],
                category=recovery["category"],
                owner=recovery["owner"],
                where=recovery["where"],
                values=recovery["values"],
                action=recovery["action"],
                success=recovery["success"],
                recheck=recovery["recheck"],
            )["message"]
        raise ServiceNowConnectError(
            problem,
            details={
                "realm": realm,
                "targetAgentId": target_agent_id,
                "matchCount": len(matches),
                "discoveryErrors": discovery_errors,
                "recoveryHandoff": recovery,
            },
        )
    target = matches[0]
    target["discoveryWarnings"] = copy.deepcopy(unknown_discovery_errors)
    target["ignoredNotFoundCandidates"] = copy.deepcopy(
        [
            row
            for row in discovery_errors
            if row.get("statusCode") == 404
        ]
    )
    target["realms"] = {
        "routeRealm": realms.get("routeRealm"),
        "siblingRealmCount": (
            len(realms.get("siblingRealms"))
            if isinstance(realms.get("siblingRealms"), list)
            else None
        ),
    }
    return target


def _flightcheck_result_dict(result: Any) -> dict[str, Any]:
    return {
        "checkpoint": result.checkpoint_id,
        "status": result.status,
        "automationType": result.automation_type,
        "description": result.description,
        "result": result.result,
        "remediation": result.remediation,
        "roles": list(result.roles),
    }


def _target_credential_check(
    context: dict[str, Any],
    *,
    target_environment_id: str,
    expected_instance: str | None,
    expected_client_id: str | None,
) -> dict[str, Any]:
    connections_url = (
        f"{PORTAL_ORIGINS[context['environment']['ring']]['powerAutomate']}"
        f"/environments/{target_environment_id}/connections"
    )
    expected_values = (
        "Authentication Type: Microsoft Entra ID User Login "
        "(`entraIDUserLogin`). "
        + (
            f"Instance Name: `{expected_instance}`. Resource URI: "
            f"`{expected_client_id}`."
            if expected_instance and expected_client_id
            else (
                "The target Instance Name and App A Application client ID are "
                "not yet confirmed. The ServiceNow and Entra administrators "
                "must provide both non-secret target values; do not copy Dev "
                "or stale connection values."
            )
        )
    )
    base = {
        "checkpoint": "SN-REALM-CREDENTIAL-001",
        "description": "Exact target-realm ServiceNow physical credential",
        "roles": [
            "ESS Maker / Agent Developer",
            "ServiceNow Admin",
        ],
    }
    if not expected_instance or not expected_client_id:
        problem = (
            "The target realm's expected ServiceNow instance and "
            "application client ID were not explicitly confirmed, so "
            "credential health cannot be judged."
        )
        recovery = _recovery_handoff(
            problem=problem,
            category="Missing target confirmation",
            owner=(
                "Power Platform Maker/Admin with ServiceNow Admin and "
                "Microsoft Entra Application Administrator input"
            ),
            where=connections_url,
            values=expected_values,
            action=(
                "Confirm both target values together, then rerun read-only "
                "validation. Do not repair or create a connection from this "
                "read-only flow."
            ),
            success=(
                "The target Instance Name and App A client ID are explicitly "
                "confirmed for this exact target environment."
            ),
            recheck=(
                "Rerun only the target credential check, then continue to the "
                "target Test pane when no automatic blocker remains."
            ),
        )
        return {
            **base,
            "status": "Manual",
            "automationType": "manual",
            "result": problem,
            "remediation": recovery["message"],
            "recoveryHandoff": recovery,
        }
    client = _connectivity_client_for_environment(
        context,
        environment_id=target_environment_id,
    )
    try:
        connections = [
            connection_summary(record)
            for record in client.list_connections()
        ]
    except ServiceNowConnectError as exc:
        problem = str(exc)
        details = exc.details if isinstance(exc.details, dict) else {}
        status_code = details.get("statusCode")
        category = (
            "Read throttled"
            if status_code == 429
            else "Read permission"
            if status_code in {401, 403}
            else "Read or network error"
        )
        recovery = _recovery_handoff(
            problem=problem,
            category=category,
            owner="Power Platform Maker/Admin",
            where=connections_url,
            values=expected_values,
            action=(
                "Restore read access to the target environment's Connectivity "
                "API and reauthenticate if needed. Respect Retry-After when "
                "present; do not treat this read error as missing "
                "configuration."
            ),
            success=(
                "Connector-scoped inventory can be read for the exact target "
                "environment without authorization, throttling, or network "
                "failure."
            ),
            recheck=(
                "Rerun only target credential inventory, then resume target "
                "validation at this check."
            ),
        )
        return {
            **base,
            "status": "Error",
            "automationType": "automated",
            "result": problem,
            "remediation": recovery["message"],
            "recoveryHandoff": recovery,
        }
    exact = [
        connection
        for connection in connections
        if _connection_matches_expected_credential(
            connection,
            expected_instance=str(expected_instance),
            expected_client_id=str(expected_client_id),
        )
    ]
    healthy = [
        connection
        for connection in exact
        if connection.get("status") == "Connected"
    ]
    if len(healthy) == 1 and len(exact) == 1:
        return {
            **base,
            "status": "Passed",
            "automationType": "automated",
            "result": (
                "One exact Connected Entra user-login ServiceNow credential "
                "matches the target-confirmed instance and application client ID "
                "in the target environment."
            ),
            "remediation": "",
            "evidence": {
                "connectionId": healthy[0].get("connectionId"),
                "authMode": healthy[0].get("authMode"),
                "instanceName": expected_instance,
                "resourceUri": expected_client_id,
            },
        }
    if len(exact) > 1:
        problem = (
            f"{len(exact)} exact target-realm ServiceNow credentials "
            "match; the validation cannot choose one safely."
        )
        recovery = _recovery_handoff(
            problem=problem,
            category="Ambiguous exact target",
            owner="Power Platform Maker/Admin",
            where=connections_url,
            values=expected_values,
            action=(
                "Identify the intended current-maker connection or remove the "
                "ambiguity outside this read-only validation. Do not return or "
                "manually enter connection IDs."
            ),
            success=(
                "Exactly one current-maker target connection matches all "
                "validated values and is Connected."
            ),
            recheck=(
                "Rerun only target credential inventory, then resume target "
                "validation at this check."
            ),
        )
        return {
            **base,
            "status": "Blocked",
            "automationType": "automated",
            "result": problem,
            "remediation": recovery["message"],
            "recoveryHandoff": recovery,
        }
    if exact:
        problem = (
            "The exact target-realm ServiceNow credential exists but is "
            "not Connected."
        )
        recovery = _recovery_handoff(
            problem=problem,
            category="Repairable target connection",
            owner="Power Platform Maker/Admin who owns the connection",
            where=connections_url,
            values=expected_values,
            action=(
                "The owning maker repairs or signs in to that exact connection "
                "with their own Microsoft account. Do not request or display "
                "passwords, secrets, tokens, PFX files, browser artifacts, or "
                "another owner's credentials."
            ),
            success=(
                "Fresh target inventory shows the exact connection Connected "
                "with all validated values."
            ),
            recheck=(
                "Rerun only target credential inventory, then resume target "
                "validation at this check."
            ),
        )
        return {
            **base,
            "status": "Failed",
            "automationType": "automated",
            "result": problem,
            "remediation": recovery["message"],
            "recoveryHandoff": recovery,
        }
    problem = (
        "No target-realm ServiceNow credential matches the exact "
        "target-confirmed instance, Entra user-login mode, and application "
        "client ID."
    )
    recovery = _recovery_handoff(
        problem=problem,
        category="Missing target connection",
        owner="Power Platform Maker/Admin",
        where=connections_url,
        values=expected_values,
        action=(
            "Outside this read-only flow, create or repair one exact "
            "current-maker ServiceNow connection only after confirming the "
            "target values. The maker signs in with their own Microsoft "
            "account."
        ),
        success=(
            "Fresh target inventory shows exactly one matching Connected "
            "connection."
        ),
        recheck=(
            "Rerun only target credential inventory, then resume target "
            "validation at this check."
        ),
    )
    return {
        **base,
        "status": "NotConfigured",
        "automationType": "automated",
        "result": problem,
        "remediation": recovery["message"],
        "recoveryHandoff": recovery,
    }


def _target_automated_recovery(
    context: dict[str, Any],
    *,
    realm: str,
    target: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("status") == "Passed":
        return result
    remediation = str(result.get("remediation") or "")
    if all(
        heading in remediation
        for heading in (
            "**Problem**",
            "**Owner**",
            "**Where**",
            "**Values to use**",
            "**Success**",
            "**Recheck and resume**",
        )
    ):
        return result
    problem = str(result.get("result") or "Target validation did not pass.")
    status = str(result.get("status") or "")
    lowered = problem.casefold()
    category = (
        "Read throttled"
        if status == "Error" and ("429" in lowered or "throttl" in lowered)
        else "Read permission"
        if status == "Error"
        and any(
            token in lowered
            for token in ("401", "403", "permission", "authorization", "denied")
        )
        else "Read or network error"
        if status == "Error"
        else "Ambiguous or blocked target"
        if status == "Blocked"
        else "Verified mismatch or failed validation"
        if status == "Failed"
        else "Missing or repairable target configuration"
    )
    target_url = _target_agent_validation_url(
        context,
        environment_id=str(target.get("environmentId") or ""),
        agent_id=str(target.get("agentId") or ""),
    )
    owner = ", ".join(
        str(value)
        for value in result.get("roles") or []
        if isinstance(value, str) and value
    ) or "ESS Maker / Agent Developer"
    action = remediation or (
        "Have the listed owner correct only this target-realm check."
    )
    recovery = _recovery_handoff(
        problem=problem,
        category=category,
        owner=owner,
        where=target_url,
        values=(
            f"Target realm: {realm.title()}; exact target agent and environment "
            "are the values encoded by the returned target link. Use target-"
            "realm administrator-confirmed settings only; do not copy Dev "
            "values or return employee data, tokens, or secrets."
        ),
        action=action,
        success=(
            f"The `{result.get('description')}` check returns Passed for the "
            "same exact target identity."
        ),
        recheck=(
            f"Rerun only {realm.title()} read-only validation. Continue to the "
            "Test pane only when no automatic blocker remains."
        ),
    )
    return {
        **result,
        "remediation": recovery["message"],
        "recoveryHandoff": recovery,
    }


def _customer_facing_realm_check(result: dict[str, Any]) -> dict[str, Any]:
    rendered = copy.deepcopy(result)
    status = str(result.get("status") or "")
    if status == "Passed":
        rendered["customerStatus"] = "Verified automatically"
        rendered["customerExplanation"] = str(result.get("result") or "")
    elif status == "Manual":
        rendered["customerStatus"] = "Not automatically verified"
        rendered["customerExplanation"] = (
            str(result.get("result") or "")
            + " This does not mean a Maker or administrator has already "
            "finished or confirmed the step."
        )
    else:
        rendered["customerStatus"] = status or "Needs attention"
        rendered["customerExplanation"] = str(result.get("result") or "")
    return rendered


def _realm_functional_test_question(
    *,
    realm: str,
    test_pane_url: str,
) -> dict[str, Any]:
    realm_label = realm.title()
    return {
        "header": f"Validate the {realm_label} ServiceNow target",
        "question": (
            "**Current status**\nAutomatic target prechecks are complete. "
            "Functional and end-to-end ServiceNow validation are still "
            "pending.\n\n"
            f"**Open target**\n{test_pane_url}\n\n"
            f"**Example prompt**\n`{ACTIVE_PROFILE.test_prompt}`\n\n"
            "**Action**\n"
            "1. Open the exact target agent link and use its Test pane.\n"
            "2. Enter the example prompt exactly as shown. Do not add an "
            "employee name, ticket/case ID, secret, token, or other personal "
            "value.\n"
            "3. Judge whether the expected ServiceNow capability completes "
            "correctly for data you are authorized to access.\n"
            "4. Return only Pass or Not pass. Do not paste the response, "
            "ticket/case content, or employee data.\n\n"
            "**How to judge**\nA generic conversational answer is not "
            "automatically Pass. An empty list is not automatically Not pass; "
            "it can be valid when no records exist. Use the visible "
            "authentication, connection, permission, and expected capability "
            "behavior. If you choose Not pass, the kit records that result and "
            "directs you back to the Dev agent to rerun `/connect servicenow`."
        ),
        "options": [
            {"label": "Pass"},
            {"label": "Not pass"},
        ],
        "allowFreeformInput": False,
    }


def validate_realm(
    context: dict[str, Any],
    *,
    realm: str,
    target_instance: str | None = None,
    target_client_id: str | None = None,
) -> dict[str, Any]:
    if realm not in _VALIDATION_REALMS:
        raise ServiceNowConnectError("Validation realm must be Dev, Test, or Prod.")
    complete, dev_evidence = _dev_connect_completion(context)
    if not complete:
        reason = str(
            dev_evidence.get("reason") or "current Dev Connect is incomplete"
        )
        problem = (
            "Realm validation requires a complete current Dev Connect record "
            f"for this exact agent ({reason})."
        )
        recovery = _recovery_handoff(
            problem=problem,
            category="Dev prerequisite incomplete",
            owner="ESS Maker / Agent Developer",
            where=maker_portal_links(context)["copilotStudioAgent"]["url"],
            values=(
                "Use the currently bound Dev agent and the existing lifecycle's "
                "validated target values. Do not copy Test/Prod settings into "
                "Dev."
            ),
            action=(
                "Resume only the first incomplete or regressed Dev phase and "
                "complete the current bounded Dev Test."
            ),
            success=(
                "The exact Dev lifecycle and its current Test binding are "
                "complete."
            ),
            recheck=(
                "Rerun `validation-realm-handoff`; proceed to target realm "
                "validation only when it returns `choice-required`."
            ),
        )
        raise ServiceNowConnectError(
            problem,
            details={
                **dev_evidence,
                "recoveryHandoff": recovery,
            },
        )
    state = _load_lifecycle_state(context)
    selection = {
        "realm": realm,
        "provider": ACTIVE_PROFILE.provider_key,
        "profile": ACTIVE_PROFILE.key,
        "agentSlug": _agent_slug(context),
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "tenantId": context["environment"]["tenant_id"],
        "recordedAt": _utc_now(),
    }
    if realm == "dev":
        state.setdefault("evidence", {})["validationRealmSelection"] = selection
        _write_lifecycle_state(context, state)
        return {
            "schemaVersion": "servicenow.realm-validation.v1",
            "status": "dev-resume",
            "selection": selection,
            "remoteMutationCount": 0,
            "next": {
                "action": "resume-dev-connect",
                "command": (
                    "python scripts/connect_servicenow_da.py "
                    f"--provider {ACTIVE_PROFILE.provider_key} "
                    f"--agent-slug {_agent_slug(context)} resume-handoff"
                ),
            },
        }

    deployment_record = _realm_deployment_record(state, realm)
    if (
        isinstance(deployment_record, dict)
        and deployment_record.get("status") == "not-deployed"
    ):
        return {
            "schemaVersion": "servicenow.realm-validation.v1",
            "status": "deployment-required",
            "selection": selection,
            "deploymentEvidence": copy.deepcopy(deployment_record),
            "question": _realm_deployment_question(context, realm=realm),
            "remoteMutationCount": 0,
            "next": {
                "action": "maker-deploys-target",
                "instruction": (
                    "Show the returned deployment question exactly and wait "
                    "for the Maker. Do not call target APIs until the Maker "
                    "reports deployment completed."
                ),
            },
        }

    if bool(target_instance) != bool(target_client_id):
        raise ServiceNowConnectError(
            "Target ServiceNow instance and application client ID must be "
            "provided together."
        )
    normalized_target_instance = (
        normalize_instance_name(target_instance)
        if target_instance
        else None
    )
    normalized_target_client_id = (
        normalize_client_id(target_client_id)
        if target_client_id
        else None
    )
    state.setdefault("evidence", {})["validationRealmSelection"] = selection
    _write_lifecycle_state(context, state)
    target = _resolve_target_realm(context, realm=realm)
    target_client = target.pop("client")
    realm_value = _VALIDATION_REALMS[realm]
    runner = SimpleNamespace(
        agentbuilder=target_client,
        agent_slug=_agent_slug(context),
        config={
            "activeAgent": _agent_slug(context),
            "minimalBotsAlmRealm": realm_value,
            "agents": [
                {
                    "slug": _agent_slug(context),
                    "botId": target["agentId"],
                    "schemaName": target["schemaName"],
                    "realm": realm,
                }
            ],
        },
    )
    results = [
        _flightcheck_result_dict(result)
        for result in run_solution_checks(runner)
    ]
    results.append(
        _target_credential_check(
            context,
            target_environment_id=target["environmentId"],
            expected_instance=normalized_target_instance,
            expected_client_id=normalized_target_client_id,
        )
    )
    results = [
        _target_automated_recovery(
            context,
            realm=realm,
            target=target,
            result=result,
        )
        for result in results
    ]
    manual_checks = [
        result for result in results if result["automationType"] == "manual"
    ]
    manual_checks.extend(
        [
            {
                "checkpoint": "SN-REALM-OIDC-MANUAL",
                "status": "Manual",
                "automationType": "manual",
                "description": "Target-realm ServiceNow OIDC and user mapping",
                "result": (
                    "No supported read API proves the target realm's "
                    "ServiceNow OIDC provider, User Claim, and User Field."
                ),
                "remediation": (
                    "Check these settings only if the target Test pane result "
                    "fails in an identity or authorization category."
                ),
                "roles": ["ServiceNow Admin"],
            },
            {
                "checkpoint": "SN-REALM-AGENT-BINDING-MANUAL",
                "status": "Manual",
                "automationType": "manual",
                "description": "Exact target agent UI connection binding",
                "result": (
                    "Connection inventory does not prove that the exact "
                    "target agent UI is bound to the intended credential."
                ),
                "remediation": (
                    "Check the target agent's Connection settings only if "
                    "the Test pane result fails in a binding or connection "
                    "category."
                ),
                "roles": ["ESS Maker / Agent Developer"],
            },
        ]
    )
    manual_checks = [
        _customer_facing_realm_check(result)
        for result in manual_checks
    ]
    automated_checks = [
        _customer_facing_realm_check(result)
        for result in results
        if result["automationType"] != "manual"
    ]
    blocking_statuses = {
        "Failed",
        "Error",
        "Blocked",
        "NotConfigured",
    }
    automated_blockers = [
        result
        for result in automated_checks
        if result["status"] in blocking_statuses
    ]
    all_passed = bool(automated_checks) and all(
        result["status"] == "Passed" for result in automated_checks
    )
    validation = {
        **selection,
        "targetAgentId": target["agentId"],
        "targetEnvironmentId": target["environmentId"],
        "almFamilyId": target["almFamilyId"],
        "targetCommitSha": target["commitSha"],
        "targetConfigurationSha256": _canonical_json_hash(
            {
                "realm": realm,
                "environmentId": target["environmentId"],
                "agentId": target["agentId"],
                "schemaName": target["schemaName"],
                "almFamilyId": target["almFamilyId"],
                "commitSha": target["commitSha"],
            }
        ),
        "sourceDevTestBinding": copy.deepcopy(
            dev_evidence["testBinding"]
        ),
        "targetCredentialExpectation": {
            "source": (
                "explicit-target-realm-confirmation"
                if normalized_target_instance
                else "not-confirmed"
            ),
            "instanceName": normalized_target_instance,
            "applicationClientId": normalized_target_client_id,
        },
        "deploymentEvidence": copy.deepcopy(deployment_record),
        "automatedChecks": automated_checks,
        "manualChecks": manual_checks,
        "results": automated_checks + manual_checks,
        "allAutomatedChecksPassed": all_passed,
        "blockingAutomatedCheckCount": len(automated_blockers),
    }
    state["evidence"].setdefault("realmValidations", {})[realm] = validation
    _write_lifecycle_state(context, state)
    studio_origin = PORTAL_ORIGINS[context["environment"]["ring"]][
        "copilotStudio"
    ]
    test_pane_url = (
        f"{studio_origin}/environments/"
        f"{target['environmentId']}/bots/{target['agentId']}/overview"
    )
    ready_for_test = not automated_blockers
    return {
        "schemaVersion": "servicenow.realm-validation.v1",
        "status": (
            "ready-for-test-pane"
            if ready_for_test
            else "needs-configuration"
        ),
        "selection": selection,
        "target": target,
        "automatedChecks": automated_checks,
        "manualChecks": manual_checks,
        "deploymentEvidence": copy.deepcopy(deployment_record),
        "allAutomatedChecksPassed": all_passed,
        "blockingAutomatedChecks": automated_blockers,
        "readinessSummary": {
            "automaticPrechecks": (
                "Complete" if ready_for_test else "Needs attention"
            ),
            "functionalTest": "Pending",
            "endToEndValidation": "Not yet verified",
        },
        "question": (
            _realm_functional_test_question(
                realm=realm,
                test_pane_url=test_pane_url,
            )
            if ready_for_test
            else None
        ),
        "remoteMutationCount": 0,
        "next": (
            {
                "action": "customer-test-pane-validation",
                "url": test_pane_url,
                "instruction": (
                    "Open this exact target agent and use the Test pane with "
                    "real data you are authorized to access. Do not return "
                    "employee values, ticket content, tokens, or secrets."
                ),
            }
            if ready_for_test
            else {
                "action": "configure-and-rerun",
                "instruction": (
                    "Have the listed owner correct each non-Passed checkpoint "
                    "in the exact target environment, then rerun validation."
                ),
            }
        ),
    }


def record_realm_test(
    context: dict[str, Any],
    *,
    realm: str,
    result: str,
    failure_category: str | None,
) -> dict[str, Any]:
    if realm not in {"test", "prod"}:
        raise ServiceNowConnectError(
            "Manual realm Test pane evidence is supported only for Test or Prod."
        )
    if result not in {"pass", "fail"}:
        raise ServiceNowConnectError("Realm Test pane result must be pass or fail.")
    allowed_failures = {
        "authentication",
        "permission",
        "connection",
        "binding",
        "identity-mapping",
        "unexpected",
    }
    if result == "pass" and failure_category is not None:
        raise ServiceNowConnectError(
            "A passing realm Test pane result cannot include a failure category."
        )
    if (
        result == "fail"
        and failure_category is not None
        and failure_category not in allowed_failures
    ):
        raise ServiceNowConnectError(
            "A provided realm Test pane failure category is unsupported."
        )
    state = _load_lifecycle_state(context)
    evidence = state.setdefault("evidence", {})
    validations = evidence.get("realmValidations")
    validation = (
        validations.get(realm) if isinstance(validations, dict) else None
    )
    if not isinstance(validation, dict):
        raise ServiceNowConnectError(
            f"No scoped {realm.title()} realm validation exists for this "
            "exact agent."
        )
    if validation.get("blockingAutomatedCheckCount") not in {0, None}:
        raise ServiceNowConnectError(
            "Resolve the blocking automated target-realm checks before "
            "recording a Test pane result."
        )
    target_environment_id = validation.get("targetEnvironmentId")
    target_agent_id = validation.get("targetAgentId")
    target_configuration_sha = validation.get(
        "targetConfigurationSha256"
    )
    if not all(
        isinstance(value, str) and value
        for value in (
            target_environment_id,
            target_agent_id,
            target_configuration_sha,
        )
    ):
        raise ServiceNowConnectError(
            "The scoped realm validation has incomplete target identity."
        )
    recorded_at = _utc_now()
    record = {
        "kind": "maker-attestation",
        "status": "completed",
        "realm": realm,
        "result": result,
        "failureCategory": failure_category,
        "recordedAt": recorded_at,
        "binding": {
            "provider": ACTIVE_PROFILE.provider_key,
            "profile": ACTIVE_PROFILE.key,
            "agentSlug": _agent_slug(context),
            "sourceDevAgentId": context["agent"]["id"],
            "sourceDevEnvironmentId": context["environment"]["id"],
            "targetAgentId": target_agent_id,
            "targetEnvironmentId": target_environment_id,
            "targetConfigurationSha256": target_configuration_sha,
        },
    }
    validation["functionalTest"] = record
    validation.pop("recovery", None)
    _write_lifecycle_state(context, state)
    dev_agent_url = maker_portal_links(context)["copilotStudioAgent"]["url"]
    return {
        "schemaVersion": "servicenow.realm-test-evidence.v1",
        "status": "recorded",
        "realm": realm,
        "result": result,
        "failureCategory": failure_category,
        "binding": copy.deepcopy(record["binding"]),
        "manualChecks": copy.deepcopy(validation.get("manualChecks") or []),
        "targetedManualCheckpoints": [],
        "targetedRecoveryHandoffs": [],
        "question": None,
        "next": (
            {
                "action": "realm-functional-validation-complete",
                "instruction": (
                    "The customer confirmed the exact target connection works "
                    "in the Test pane. Unobserved Manual rows remain Manual."
                ),
            }
            if result == "pass"
            else {
                "action": "return-to-dev-connect",
                "url": dev_agent_url,
                "instruction": (
                    "Not pass recorded; return to the Dev agent and rerun "
                    "`/connect servicenow` to recheck the connection setup "
                    "step by step."
                ),
            }
        ),
    }


def _publish_validation_pending(response: dict[str, Any]) -> bool | None:
    upper = response.get("ValidationPending")
    lower = response.get("validationPending")
    if (
        upper is not None
        and lower is not None
        and upper is not lower
        and upper != lower
    ):
        raise ServiceNowConnectError(
            "Publish response returned conflicting ValidationPending values."
        )
    value = lower if lower is not None else upper
    if value is not None and not isinstance(value, bool):
        raise ServiceNowConnectError(
            "Publish response returned an invalid ValidationPending value."
        )
    return value


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
    if not confirmed:
        raise ServiceNowConnectError(
            "Publishing requires explicit confirmation (--yes)."
        )
    agentbuilder = _agentbuilder_client(context)
    components = agentbuilder.fetch_components(context["agent"]["id"])
    requested_component_hash = _component_hash(components)
    tested_draft_semantic_hash = _draft_semantic_hash(components)
    state = _load_lifecycle_state(context, components)
    current_connection_binding_hash = _connection_binding_hash(
        context,
        state,
        components,
    )
    test_record = state.get("evidence", {}).get("test")
    credential = state.get("evidence", {}).get("credential")
    if (
        not isinstance(test_record, dict)
        or test_record.get("status") != "completed"
        or test_record.get("result") != "pass"
        or not isinstance(test_record.get("binding"), dict)
        or test_record["binding"].get("draftSemanticHash")
        != tested_draft_semantic_hash
        or test_record["binding"].get("connectionBindingHash")
        != current_connection_binding_hash
        or not isinstance(credential, dict)
        or test_record["binding"].get("connectionId")
        != credential.get("connectionId")
    ):
        raise ServiceNowConnectError(
            "The current draft content and selected connection have not "
            f"passed the privacy-safe {ACTIVE_PROFILE.product_name} Test "
            "pane check. Test this exact "
            "draft before publishing."
        )
    requested_at = _utc_now()
    try:
        response = agentbuilder.publish_agent(context["agent"]["id"])
    except Exception as exc:
        publish_error = {
            "requestedAt": requested_at,
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "componentHash": requested_component_hash,
            "errorCode": type(exc).__name__,
            "recordedAt": _utc_now(),
        }
        detail = str(exc)
        if isinstance(exc, AgentBuilderHTTPError):
            publish_error.update(
                {
                    "httpStatus": exc.status_code,
                    "serviceErrorCode": exc.error_code,
                    "requestId": exc.request_id,
                }
            )
        state.setdefault("evidence", {})["publish"] = publish_error
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(
            f"Publish outcome is ambiguous: {detail}. Review Copilot Studio "
            "publish details before retrying; automatic unpublish is not "
            "available."
        ) from exc
    validation_pending = _publish_validation_pending(response)
    try:
        published_components = agentbuilder.fetch_components(
            context["agent"]["id"]
        )
    except Exception as exc:
        publish_error = {
            "requestedAt": requested_at,
            "acceptedAt": _utc_now(),
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "requestedComponentHash": requested_component_hash,
            "componentHash": requested_component_hash,
            "errorCode": type(exc).__name__,
            "response": {
                "validationPending": validation_pending,
                "responseKeys": sorted(response.keys()),
            },
            "remediation": (
                "Publish was accepted, but the post-publish component "
                "revision could not be read. Do not republish blindly; "
                "reconcile the current remote publish state first."
            ),
            "recordedAt": _utc_now(),
        }
        if isinstance(exc, AgentBuilderHTTPError):
            publish_error.update(
                {
                    "httpStatus": exc.status_code,
                    "serviceErrorCode": exc.error_code,
                    "requestId": exc.request_id,
                }
            )
        state.setdefault("evidence", {})["publish"] = publish_error
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(publish_error["remediation"]) from exc
    published_component_hash = _component_hash(published_components)
    published_semantic_hash = _draft_semantic_hash(published_components)
    if published_semantic_hash != tested_draft_semantic_hash:
        publish_error = {
            "kind": "maker-attestation",
            "requestedAt": requested_at,
            "acceptedAt": _utc_now(),
            "status": "needs_remediation",
            "mutationMayHaveOccurred": True,
            "requestedComponentHash": requested_component_hash,
            "publishedComponentHash": published_component_hash,
            "testedDraftSemanticHash": tested_draft_semantic_hash,
            "publishedSemanticHash": published_semantic_hash,
            "connectionBindingHash": current_connection_binding_hash,
            "response": {
                "validationPending": validation_pending,
                "responseKeys": sorted(response.keys()),
            },
            "remediation": (
                "Publish changed authored semantic content relative to the "
                "tested draft. Do not republish blindly; inspect the current "
                "draft and run Test again."
            ),
            "recordedAt": _utc_now(),
        }
        state.setdefault("evidence", {})["publish"] = publish_error
        state["componentHash"] = published_component_hash
        _write_lifecycle_state(context, state)
        raise ServiceNowConnectError(publish_error["remediation"])
    completed_at = _utc_now()
    publish_record = {
        "kind": "maker-attestation",
        "requestedAt": requested_at,
        "completedAt": completed_at,
        "recordedAt": completed_at,
        "agentId": context["agent"]["id"],
        "environmentId": context["environment"]["id"],
        "requestedComponentHash": requested_component_hash,
        "publishedComponentHash": published_component_hash,
        "componentHash": published_component_hash,
        "testedDraftSemanticHash": tested_draft_semantic_hash,
        "publishedSemanticHash": published_semantic_hash,
        "connectionBindingHash": current_connection_binding_hash,
        "response": {
            "validationPending": validation_pending,
            "responseKeys": sorted(response.keys()),
        },
        "status": (
            "completed"
            if validation_pending is False
            else "confirmation-required"
        ),
        "mutationMayHaveOccurred": True,
    }
    state.setdefault("evidence", {})["publish"] = publish_record
    state["componentHash"] = published_component_hash
    state["draftSemanticHash"] = published_semantic_hash
    state["connectionBindingHash"] = current_connection_binding_hash
    _write_lifecycle_state(context, state)
    return state


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
    if result not in {"pass", "fail"}:
        raise ServiceNowConnectError(
            "Test pane result must be pass or fail."
        )
    if result == "pass" and failure_category is not None:
        raise ServiceNowConnectError(
            "A passing Test pane result cannot have a failure category."
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
        "status": "completed" if result == "pass" else "failed",
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
    mapping_handoff_parser = subparsers.add_parser(
        "identity-mapping-handoff",
        help=(
            "Generate the protected Entra-candidate or ServiceNow-selection "
            "workbook and return the scoped administrator handoff."
        ),
    )
    mapping_handoff_parser.add_argument(
        "--stage",
        choices=("entra", "servicenow"),
        required=True,
    )
    mapping_handoff_parser.add_argument("--client-id")
    requirement_parser = subparsers.add_parser(
        "record-identity-requirement",
        help=(
            "Record the Maker-confirmed ServiceNow user identifier type as "
            "routing intent before generating a new Entra workbook."
        ),
    )
    requirement_parser.add_argument(
        "--choice",
        choices=tuple(IDENTITY_REQUIREMENT_CHOICES),
        required=True,
    )
    mapping_parser = subparsers.add_parser(
        "record-identity-mapping",
        help=(
            "Import a completed protected identity XLSX or equivalent CSV "
            "after explicit Maker confirmation."
        ),
    )
    mapping_parser.add_argument(
        "--stage",
        choices=("entra", "servicenow"),
        required=True,
    )
    mapping_parser.add_argument(
        "--workbook-file",
        type=Path,
        required=True,
        help="Path to the completed .xlsx or .csv handoff file.",
    )
    mapping_parser.add_argument("--client-id")
    mapping_parser.add_argument("--yes", action="store_true")
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

    agent_connection_parser = subparsers.add_parser(
        "record-agent-connection",
        help="Record the maker's manual Connect action after health validation.",
    )
    agent_connection_parser.add_argument("--connection-id", required=True)
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
    subparsers.add_parser(
        "validation-realm-handoff",
        help=(
            "Offer Dev/Test/Prod validation only after this exact agent has a "
            "complete current Dev Connect record."
        ),
    )
    validate_realm_parser = subparsers.add_parser(
        "validate-realm",
        help=(
            "Run bounded read-only validation for the selected exact Dev, "
            "Test, or Prod realm."
        ),
    )
    validate_realm_parser.add_argument(
        "--realm",
        choices=("dev", "test", "prod"),
        required=True,
    )
    validate_realm_parser.add_argument(
        "--target-instance",
        help=(
            "Administrator-confirmed ServiceNow instance for this exact Test "
            "or Prod realm."
        ),
    )
    validate_realm_parser.add_argument(
        "--target-client-id",
        help=(
            "Administrator-confirmed Entra application client ID for this "
            "exact Test or Prod realm."
        ),
    )
    realm_deployment_parser = subparsers.add_parser(
        "record-realm-deployment",
        help=(
            "Record the Maker-confirmed Test/Prod deployment prerequisite "
            "without changing the target."
        ),
    )
    realm_deployment_parser.add_argument(
        "--realm",
        choices=("test", "prod"),
        required=True,
    )
    realm_deployment_parser.add_argument(
        "--status",
        choices=("not-deployed", "deployment-completed"),
        required=True,
    )
    realm_test_parser = subparsers.add_parser(
        "record-realm-test",
        help=(
            "Record the customer's privacy-safe Test pane result for an "
            "already scoped Test or Prod target."
        ),
    )
    realm_test_parser.add_argument(
        "--realm",
        choices=("test", "prod"),
        required=True,
    )
    realm_test_parser.add_argument(
        "--result",
        choices=("pass", "fail"),
        required=True,
    )
    realm_test_parser.add_argument(
        "--failure-category",
        choices=(
            "authentication",
            "permission",
            "connection",
            "binding",
            "identity-mapping",
            "unexpected",
        ),
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
        choices=("pass", "fail"),
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
            "identity-mapping-handoff",
            "record-identity-requirement",
            "entra-registration",
        }
        or (
            command == "record-identity-mapping"
            and getattr(args, "stage", "") == "entra"
        )
        else "servicenow-oidc"
        if command in {"servicenow-oidc"}
        or (
            command == "record-identity-mapping"
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
            "portal-reuse-handoff",
            "record-portal-reuse",
        }
        else "agent-connection"
        if command == "record-agent-connection"
        else "test"
        if command == "record-test"
        else "realm-validation"
        if command
        in {
            "validation-realm-handoff",
            "validate-realm",
            "record-realm-deployment",
            "record-realm-test",
        }
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
        "agent-connection",
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
            "Power Platform Maker/Admin",
            links["powerAutomateConnections"]["url"],
            (
                "Authentication Type: Microsoft Entra ID User Login. "
                + (
                    f"Instance Name: `{instance_name}`. "
                    if instance_name
                    else "Instance Name must come from preflight. "
                )
                + (
                    f"Resource URI: `{client_id}`."
                    if client_id
                    else "Resource URI must come from verified App A evidence."
                )
            ),
            "Fresh inventory shows one exact Connected current-maker connection.",
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
        "agent-connection": (
            "ESS Maker / Agent Developer",
            links["copilotStudioAgent"]["url"] + " -> Settings -> Connection settings",
            (
                "Bind the current maker's exact healthy connection. Do not "
                "return a connection ID or impersonate another owner."
            ),
            "The ServiceNow row is Connected for the current saved draft.",
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
        "realm-validation": (
            "Power Platform Maker/Admin",
            links["copilotStudioAgent"]["url"],
            (
                "Use only native ALM target identity and target-confirmed "
                "values. Do not copy Dev values or mutate Test/Prod here."
            ),
            "The exact target is proved and read-only validation can continue.",
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
            "agent-connection",
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context: dict[str, Any] | None = None
    try:
        profile = product_profile_for_provider(args.provider)
        if profile is None:  # pragma: no cover
            raise ServiceNowConnectError("Unsupported ServiceNow provider.")
        configure_product_profile(profile.key)
        if args.command == "list-agents":
            result = list_agent_choices()
        elif args.command == "agent-chooser":
            result = agent_chooser_handoff(
                selection_key=args.selection_key,
                agent_link=args.agent_link,
            )
        else:
            context = (
                load_context()
                if args.agent_id is None and args.agent_slug is None
                else load_context(
                    agent_id=args.agent_id,
                    agent_slug=args.agent_slug,
                )
            )
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
        elif args.command == "identity-mapping-handoff":
            result = identity_mapping_handoff(
                context,
                stage=args.stage,
                client_id=args.client_id,
            )
        elif args.command == "record-identity-requirement":
            result = record_identity_requirement(
                context,
                choice=args.choice,
            )
        elif args.command == "record-identity-mapping":
            result = record_identity_mapping(
                context,
                stage=args.stage,
                workbook_path=args.workbook_file,
                client_id=args.client_id,
                confirmed=args.yes,
            )
        elif args.command == "record-admin-phase":
            result = record_admin_phase(
                context,
                phase=args.phase,
                status=args.status,
                client_id=args.client_id,
            )
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
        elif args.command == "record-agent-connection":
            result = record_agent_connection_attestation(
                context,
                args.connection_id,
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
            )
        elif args.command == "validation-realm-handoff":
            result = validation_realm_handoff(context)
        elif args.command == "validate-realm":
            result = validate_realm(
                context,
                realm=args.realm,
                target_instance=args.target_instance,
                target_client_id=args.target_client_id,
            )
        elif args.command == "record-realm-deployment":
            result = record_realm_deployment(
                context,
                realm=args.realm,
                status=args.status,
            )
        elif args.command == "record-realm-test":
            result = record_realm_test(
                context,
                realm=args.realm,
                result=args.result,
                failure_category=args.failure_category,
            )
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
        elif args.command not in {
            "list-agents",
            "agent-chooser",
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
            "identity-mapping-handoff",
            "record-identity-requirement",
            "record-identity-mapping",
            "record-admin-phase",
            "create",
            "record-credential",
            "resolve-credential",
            "record-agent-connection",
            "set-topic-state",
            "enable-all-topics",
            "rollback-topics",
            "record-topic-choice",
            "topic-action-handoff",
            "resume-handoff",
            "validation-realm-handoff",
            "validate-realm",
            "record-realm-deployment",
            "record-realm-test",
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
        print(json.dumps(error, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
