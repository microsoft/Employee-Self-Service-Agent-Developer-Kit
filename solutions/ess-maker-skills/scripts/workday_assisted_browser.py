# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Run the ephemeral VS Code companion for native DA Workday setup.

The helper owns a constrained local guidance service. In VS Code mode, the
maker opens and shares the Integrated Browser page while the agent uses its
built-in browser tools only after row-scoped authorization. The maker owns every
portal mutation, sign-in, consent, and Test-pane interaction. Workday lifecycle
state remains exclusively owned by workday_connect.py.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from cdp_driver import is_cdp_up, launch_browser
from drive_topic import test_pane_url
from workday_connect_entra_contracts import (
    ENTRA_WORKSHEET_LABEL_ALIASES,
    ENTRA_WORKSHEET_LABELS,
    entra_capture_instruction,
)
from workday_connect_store import (
    WorkdayConnectStore,
    WorkdayConnectStoreError,
)


RESULT_MARKER = "WORKDAY_ASSIST_RESULT_JSON="
ERROR_MARKER = "WORKDAY_ASSIST_ERROR_JSON="
DEFAULT_CDP = "http://localhost:9237"
SESSION_PATH = Path(".local/connect/workday-da/assisted-browser.json")
WORKSHEET_DRAFT_PATH = Path(
    ".local/connect/workday-da/entra-companion-draft.json"
)
ASSET_ROOT = Path(__file__).with_name("workday_assisted_browser_assets")
_TOKEN_ENV = "ESS_WORKDAY_ASSIST_TOKEN"
_BROWSER_MODE_ENV = "ESS_WORKDAY_ASSIST_BROWSER_MODE"
_EDGE_BROWSER_MODE = "edge"
_VSCODE_BROWSER_MODE = "vscode"
_MAX_BODY_BYTES = 64 * 1024
_MAX_SHARED_CAPTURE_BYTES = 1024 * 1024
_MAX_SHARED_CAPTURE_BODY_BYTES = 2 * 1024 * 1024
_MAX_VIEW_FIELDS = 16
_CONNECTED_WINDOW_SECONDS = 6.0
_ENTRA_OVERVIEW_URL = (
    "https://entra.microsoft.com/"
    "#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/Overview"
)
_ENTRA_ENTERPRISE_APPLICATIONS_URL = (
    "https://entra.microsoft.com/"
    "#view/Microsoft_AAD_IAM/StartboardApplicationsMenuBlade/"
    "~/AppAppsPreview"
)
_ENTRA_USERS_AND_GROUPS_URL_TEMPLATE = (
    "https://entra.microsoft.com/"
    "#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/~/Users/"
    "objectId/{SERVICE_PRINCIPAL_OBJECT_ID}/"
    "appId/{APPLICATION_ID}/preferredSingleSignOnMode/saml/"
    "servicePrincipalType/Application/fromNav/"
)
_SURFACES = (
    "entra-configuration",
    "dataverse-connection",
    "workday-connection",
    "agent-connections",
    "workday-topics",
    "maker-validation",
)
_STATUSES = {"info", "waiting", "checking", "success", "error"}
_VIEW_KEYS = {
    "schemaVersion",
    "phase",
    "title",
    "status",
    "summary",
    "steps",
    "fields",
    "waitingFor",
    "action",
    "actions",
    "confirmation",
    "entry",
    "visualHelp",
}
_FIELD_KEYS = {"label", "value"}
_ACTION_KEYS = {"label", "operation", "mode", "disclaimer"}
_ACTION_MODES = {"navigate-only", "navigate-and-capture"}
_CONFIRMATION_KEYS = {
    "operation",
    "prompt",
    "confirmLabel",
    "rejectLabel",
}
_ENTRY_KEYS = {
    "operation",
    "label",
    "placeholder",
    "submitLabel",
    "options",
    "inputs",
}
_ENTRY_INPUT_KEYS = {"key", "label", "placeholder"}
_VISUAL_HELP_KEYS = {"operation", "label"}
_COLLECTION_OPERATION_DEFINITIONS = {
    "entra-directory-display-name": {
        "url": _ENTRA_OVERVIEW_URL,
        "worksheetRow": "Directory name",
        "worksheetField": "selectedDirectoryDisplayName",
        "sensitive": False,
    },
    "entra-enterprise-application-display-name": {
        "url": _ENTRA_ENTERPRISE_APPLICATIONS_URL,
        "worksheetRow": "Enterprise application",
        "worksheetField": "applicationDisplayName",
        "worksheetRows": [
            "Enterprise application",
            "Application ID",
        ],
        "combinedSummary": (
            "Collect the Enterprise application name and Application ID from "
            "the same Overview page."
        ),
        "combinedSteps": [
            (
                "Record the read-only Name field as Enterprise "
                "application."
            ),
            (
                "Record the read-only Application ID field as Application "
                "ID."
            ),
        ],
        "sensitive": False,
    },
    "entra-application-id": {
        "url": None,
        "worksheetRow": "Application ID",
        "worksheetField": "applicationId",
        "sensitive": False,
    },
    "entra-reply-url": {
        "url": None,
        "worksheetRow": "Selected Reply URL",
        "worksheetField": "replyUrl",
        "sensitive": False,
    },
    "entra-name-id-source": {
        "url": None,
        "worksheetRow": "NameID source",
        "worksheetField": "nameIdSource",
        "sensitive": False,
    },
    "entra-saml-signing-option": {
        "url": None,
        "worksheetRow": "SAML signing",
        "worksheetField": "samlSigningOption",
        "worksheetRows": [
            "SAML signing",
            "Certificate expiration date (active certificate row)",
        ],
        "combinedSummary": (
            "Collect the SAML signing option and active certificate "
            "expiration from the same SAML page."
        ),
        "combinedSteps": [
            "Record the selected SAML signing option.",
            "Record the active certificate expiration date.",
        ],
        "sensitive": False,
    },
    "entra-certificate-thumbprint": {
        "url": _ENTRA_ENTERPRISE_APPLICATIONS_URL,
        "worksheetRow": "Certificate thumbprint (active certificate row)",
        "worksheetField": "certificateThumbprint",
        "sensitive": False,
    },
    "entra-certificate-expiration": {
        "url": None,
        "worksheetRow": (
            "Certificate expiration date (active certificate row)"
        ),
        "worksheetField": "certificateValidTo",
        "sensitive": False,
    },
    "entra-saml-configuration": {
        "url": None,
        "worksheetRow": "SAML configuration",
        "worksheetField": "entraChecks.samlMode",
        "sensitive": False,
    },
    "entra-signing-certificate-check": {
        "url": None,
        "worksheetRow": "Signing certificate",
        "worksheetField": "entraChecks.signingCertificate",
        "sensitive": False,
    },
    "entra-authorized-connector": {
        "url": None,
        "worksheetRow": "Authorized connector",
        "worksheetField": "entraChecks.connectorPreauthorized",
        "sensitive": False,
    },
    "entra-permissions-consent": {
        "url": None,
        "worksheetRow": "Permissions and consent",
        "worksheetField": (
            "entraChecks.graphDelegatedPermissions,entraChecks.adminConsent"
        ),
        "sensitive": False,
    },
    "entra-employee-assignment": {
        "url": None,
        "worksheetRow": "Employee assignment",
        "worksheetField": "entraChecks.userAssignment",
        "sensitive": False,
    },
}
_PRESERVATION_OPERATION = "entra-existing-configuration"
_PRESERVATION_WORKSHEET_ROW = "Existing configuration"
_MULTI_INPUT_ENTRY_KEYS = {
    "entra-enterprise-application-display-name": {
        "Enterprise application",
        "Application ID",
    },
    "entra-saml-signing-option": {
        "SAML signing",
        "Certificate expiration date (active certificate row)",
    },
}
_ENTRA_NAVIGATION_HINTS = {
    "entra-directory-display-name": {
        "portalPath": "Microsoft Entra admin center -> Microsoft Entra ID -> Overview",
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-directory-name.js"
        ),
        "observedHints": [
            'getByText("{DIRECTORY_DISPLAY_NAME}", { exact: true })',
        ],
        "fallbackHints": [],
    },
    "entra-enterprise-application-display-name": {
        "portalPath": (
            "Microsoft Entra ID -> Enterprise applications -> the exact "
            "Workday application -> Overview"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-enterprise-application.js"
        ),
        "observedHints": [
            'getByRole("searchbox", { name: "Search box", exact: true })',
            'getByRole("link", { name: "{APPLICATION_DISPLAY_NAME}", exact: true })',
            'getByRole("heading", { name: "{APPLICATION_DISPLAY_NAME} | Overview", exact: true })',
        ],
        "fallbackHints": [],
    },
    "entra-application-id": {
        "portalPath": (
            "Microsoft Entra ID -> Enterprise applications -> the exact "
            "Workday application -> Overview"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-application-id.js"
        ),
        "observedHints": [
            'locator(\'input[aria-label="Application ID"]\')',
        ],
        "fallbackHints": [],
    },
    "entra-reply-url": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> Basic SAML Configuration"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-reply-url.js"
        ),
        "observedHints": [
            'getByText("{EXPECTED_REPLY_URL}", { exact: true })',
        ],
        "fallbackHints": [],
    },
    "entra-name-id-source": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> Attributes & Claims -> Unique User "
            "Identifier (Name ID)"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-name-id-source.js"
        ),
        "observedHints": [
            'getByText("{EXPECTED_NAME_ID_SOURCE}", { exact: true })',
        ],
        "fallbackHints": [],
    },
    "entra-saml-signing-option": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> SAML Signing Certificate card -> "
            "Edit pencil -> Signing Option"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-saml-signing-option.js"
        ),
        "observedHints": [
            "Sign SAML response and assertion",
            'getByRole("combobox", { name: "Signing Option", exact: true })',
        ],
        "fallbackHints": [],
    },
    "entra-certificate-thumbprint": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> SAML Signing Certificate -> active "
            "certificate row"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-certificate-thumbprint.js"
        ),
        "observedHints": [
            "Thumbprint",
            "Active",
        ],
        "fallbackHints": [],
    },
    "entra-certificate-expiration": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> SAML Signing Certificate -> active "
            "certificate row"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-certificate-expiration.js"
        ),
        "observedHints": [
            "Expiration",
            "Active",
        ],
        "fallbackHints": [],
    },
    "entra-saml-configuration": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> Set up Workday -> Login URL"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-saml-configuration.js"
        ),
        "observedHints": ["Login URL"],
        "fallbackHints": [],
    },
    "entra-signing-certificate-check": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Single sign-on -> SAML -> SAML Signing Certificate -> "
            "Certificate (Base64) -> Download"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-signing-certificate-check.js"
        ),
        "observedHints": [
            "Certificate (Base64)",
            "Download",
        ],
        "fallbackHints": [],
    },
    "entra-authorized-connector": {
        "portalPath": (
            "App registrations -> the exact Workday registration -> Expose "
            "an API -> Application ID URI, Scopes defined by this API, and "
            "Authorized client applications"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-authorized-connector.js"
        ),
        "observedHints": [
            "Application ID URI",
            "user_impersonation",
            "Authorized client applications",
            "4e4707ca-5f53-46a6-a819-f7765446e6ff",
        ],
        "fallbackHints": [],
    },
    "entra-permissions-consent": {
        "portalPath": (
            "App registrations -> the exact Workday registration -> API "
            "permissions -> Microsoft Graph delegated permissions"
        ),
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-permissions-consent.js"
        ),
        "observedHints": [
            'getByText("User.Read", { exact: true })',
            "openid",
            "profile",
            "Delegated",
            "Admin consent",
        ],
        "fallbackHints": [],
    },
    "entra-employee-assignment": {
        "portalPath": (
            "Enterprise applications -> the exact Workday application -> "
            "Users and groups"
        ),
        "lastKnownUrlTemplate": _ENTRA_USERS_AND_GROUPS_URL_TEMPLATE,
        "baselineScript": (
            "scripts/workday_assisted_browser_playwright/"
            "entra-employee-assignment.js"
        ),
        "observedHints": ["Users and groups"],
        "fallbackHints": [],
    },
}
_COLLECTION_OPERATIONS = set(_COLLECTION_OPERATION_DEFINITIONS)
_WORKSHEET_OPERATION_ORDER = tuple(_COLLECTION_OPERATION_DEFINITIONS)
_ENTRY_OPERATIONS = _COLLECTION_OPERATIONS | {_PRESERVATION_OPERATION}
_PRESENT_OPERATIONS = _ENTRY_OPERATIONS
_FINAL_WORKSHEET_CONFIRMATION_OPERATION = "entra-final-worksheet"
_CONFIRMATION_OPERATIONS = _COLLECTION_OPERATIONS | {
    _FINAL_WORKSHEET_CONFIRMATION_OPERATION
}
_WAIT_OPERATIONS = _CONFIRMATION_OPERATIONS | {_PRESERVATION_OPERATION}
_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)


class AssistedBrowserError(RuntimeError):
    """A safe, actionable assisted-browser failure."""


def _now_iso() -> str:
    """Use timezone-aware timestamps so browser and companion events can be ordered across processes."""
    return datetime.now(timezone.utc).isoformat()


def sanitize_browser_url(value: str) -> str:
    """Keep target identity useful without exposing query or fragment secrets."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return parsed.scheme + ":" if parsed.scheme else ""
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            "",
            "",
        )
    )


def sanitize_browser_evidence_text(value: Any) -> str | None:
    """Remove unrelated account identity from browser evidence before it enters companion state or output."""
    if value is None:
        return None
    text = str(value)
    if "currently signed in as" in text.casefold() or text.casefold().startswith(
        "account menu"
    ):
        return "[REDACTED_ACCOUNT_CONTEXT]"
    return _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)


def normalize_shared_browser_targets(raw: Any) -> list[dict[str, Any]]:
    """Validate semantic target positions reported by the shared VS Code browser adapter."""
    if not isinstance(raw, list) or not raw:
        raise AssistedBrowserError(
            "targets must contain at least one application target."
        )
    if len(raw) > _MAX_VIEW_FIELDS:
        raise AssistedBrowserError(
            f"targets may contain at most {_MAX_VIEW_FIELDS} application targets."
        )
    normalized: list[dict[str, Any]] = []
    for index, target in enumerate(raw):
        if not isinstance(target, Mapping):
            raise AssistedBrowserError(f"targets[{index}] must be an object.")
        if set(target) - {"centered", "label", "positionRatio"}:
            raise AssistedBrowserError(f"targets[{index}] fields are invalid.")
        ratio = target.get("positionRatio")
        if ratio is None:
            ratio = (index + 1) / (len(raw) + 1)
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not 0 <= float(ratio) <= 1
        ):
            raise AssistedBrowserError(
                f"targets[{index}].positionRatio must be between 0 and 1."
            )
        centered = target.get("centered", len(raw) == 1)
        if not isinstance(centered, bool):
            raise AssistedBrowserError(f"targets[{index}].centered must be boolean.")
        normalized.append(
            {
                "label": _required_text(
                    target.get("label"),
                    f"targets[{index}].label",
                    maximum=120,
                ),
                "positionRatio": round(
                    min(max(float(ratio), 0.05), 0.95),
                    4,
                ),
                "centered": centered,
            }
        )
    return normalized


def decode_shared_browser_capture(value: Any) -> bytes:
    """Decode one bounded PNG supplied by the shared VS Code browser adapter."""
    encoded = _required_text(
        value,
        "imageBase64",
        maximum=_MAX_SHARED_CAPTURE_BODY_BYTES,
    )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AssistedBrowserError(
            "Shared browser capture must be valid Base64."
        ) from exc
    if not content or len(content) > _MAX_SHARED_CAPTURE_BYTES:
        raise AssistedBrowserError("Shared browser capture size is invalid.")
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssistedBrowserError("Shared browser capture must be a PNG image.")
    return content


def validate_search_control(evidence: Mapping[str, Any]) -> None:
    """Limit automated text entry to controls that present as search or filter inputs."""
    tag = str(evidence.get("tag") or "").casefold()
    input_type = str(evidence.get("type") or "").casefold()
    role = str(evidence.get("role") or "").casefold()
    descriptor = " ".join(
        str(evidence.get(key) or "")
        for key in ("ariaLabel", "placeholder", "title")
    ).casefold()
    if tag != "input" or input_type not in {"", "search", "text"}:
        raise AssistedBrowserError(
            "Authorized search fill requires a visible text or search input."
        )
    if role != "searchbox" and not any(
        token in descriptor for token in ("search", "filter")
    ):
        raise AssistedBrowserError(
            "Authorized search fill requires an inspected search or filter input."
        )


def validate_search_value(value: Any) -> str:
    """Bound search text to a short single-line value so fill operations cannot carry structured payloads."""
    normalized = _required_text(value, "search value", maximum=100)
    if "\n" in normalized or "\r" in normalized:
        raise AssistedBrowserError("Search value must be a single line.")
    return normalized


def _required_text(
    value: Any,
    label: str,
    *,
    maximum: int,
) -> str:
    """Centralize strict text validation for all untrusted CLI and loopback inputs."""
    if not isinstance(value, str):
        raise AssistedBrowserError(f"{label} must be text.")
    normalized = value.strip()
    if not normalized:
        raise AssistedBrowserError(f"{label} must not be empty.")
    if len(normalized) > maximum:
        raise AssistedBrowserError(
            f"{label} must be at most {maximum} characters."
        )
    return normalized


def validate_view(raw: Any) -> dict[str, Any]:
    """Validate and normalize the only JSON shape the companion can render."""
    if not isinstance(raw, Mapping):
        raise AssistedBrowserError("Companion view must be a JSON object.")
    unknown = set(raw) - _VIEW_KEYS
    if unknown:
        raise AssistedBrowserError(
            "Companion view contains unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    if raw.get("schemaVersion") != 1:
        raise AssistedBrowserError("Companion view schemaVersion must be 1.")
    status = _required_text(raw.get("status"), "status", maximum=20)
    if status not in _STATUSES:
        raise AssistedBrowserError(
            "status must be one of: " + ", ".join(sorted(_STATUSES))
        )

    steps_raw = raw.get("steps", [])
    if not isinstance(steps_raw, list) or len(steps_raw) > 12:
        raise AssistedBrowserError("steps must be an array with at most 12 items.")
    steps = [
        _required_text(value, f"steps[{index}]", maximum=300)
        for index, value in enumerate(steps_raw)
    ]

    fields_raw = raw.get("fields", [])
    if not isinstance(fields_raw, list) or len(fields_raw) > _MAX_VIEW_FIELDS:
        raise AssistedBrowserError(
            f"fields must be an array with at most {_MAX_VIEW_FIELDS} items."
        )
    fields = []
    for index, value in enumerate(fields_raw):
        if not isinstance(value, Mapping):
            raise AssistedBrowserError(f"fields[{index}] must be an object.")
        unknown_field_keys = set(value) - _FIELD_KEYS
        if unknown_field_keys:
            raise AssistedBrowserError(
                f"fields[{index}] contains unsupported fields: "
                + ", ".join(sorted(unknown_field_keys))
            )
        fields.append(
            {
                "label": _required_text(
                    value.get("label"),
                    f"fields[{index}].label",
                    maximum=100,
                ),
                "value": _required_text(
                    value.get("value"),
                    f"fields[{index}].value",
                    maximum=500,
                ),
            }
        )

    normalized = {
        "schemaVersion": 1,
        "phase": _required_text(raw.get("phase"), "phase", maximum=80),
        "title": _required_text(raw.get("title"), "title", maximum=120),
        "status": status,
        "summary": _required_text(
            raw.get("summary"),
            "summary",
            maximum=500,
        ),
        "steps": steps,
        "fields": fields,
    }
    waiting_for = raw.get("waitingFor")
    if waiting_for is not None:
        normalized["waitingFor"] = _required_text(
            waiting_for,
            "waitingFor",
            maximum=250,
        )
    def normalize_action(action_raw: Any, label: str) -> dict[str, str]:
        """Normalize one row-scoped action into the fixed capability shape accepted by the companion."""
        if not isinstance(action_raw, Mapping):
            raise AssistedBrowserError(f"{label} must be an object.")
        unknown_action_keys = set(action_raw) - _ACTION_KEYS
        if unknown_action_keys:
            raise AssistedBrowserError(
                f"{label} contains unsupported fields: "
                + ", ".join(sorted(unknown_action_keys))
            )
        operation = _required_text(
            action_raw.get("operation"),
            f"{label}.operation",
            maximum=80,
        )
        if operation not in _COLLECTION_OPERATIONS:
            raise AssistedBrowserError(
                f"{label}.operation is not a supported collection operation."
            )
        mode = action_raw.get("mode", "navigate-and-capture")
        if mode not in _ACTION_MODES:
            raise AssistedBrowserError(
                f"{label}.mode must be navigate-only or navigate-and-capture."
            )
        normalized_action = {
            "label": _required_text(
                action_raw.get("label"),
                f"{label}.label",
                maximum=80,
            ),
            "operation": operation,
            "mode": mode,
        }
        disclaimer = action_raw.get("disclaimer")
        if disclaimer is not None:
            normalized_action["disclaimer"] = _required_text(
                disclaimer,
                f"{label}.disclaimer",
                maximum=300,
            )
        return normalized_action

    action_raw = raw.get("action")
    actions_raw = raw.get("actions")
    if action_raw is not None and actions_raw is not None:
        raise AssistedBrowserError(
            "A companion view may not contain both action and actions."
        )
    if action_raw is not None:
        normalized["action"] = normalize_action(action_raw, "action")
    if actions_raw is not None:
        if not isinstance(actions_raw, list) or not 1 <= len(actions_raw) <= 3:
            raise AssistedBrowserError(
                "actions must be an array with one through three items."
            )
        actions = [
            normalize_action(value, f"actions[{index}]")
            for index, value in enumerate(actions_raw)
        ]
        if len({action["operation"] for action in actions}) != 1:
            raise AssistedBrowserError(
                "All companion actions must target the same worksheet row."
            )
        if len({action["mode"] for action in actions}) != len(actions):
            raise AssistedBrowserError(
                "Companion action modes must be unique."
            )
        normalized["actions"] = actions
    confirmation_raw = raw.get("confirmation")
    if confirmation_raw is not None:
        if (
            action_raw is not None
            or actions_raw is not None
            or raw.get("entry") is not None
        ):
            raise AssistedBrowserError(
                "A companion view may contain only one interaction."
            )
        if not isinstance(confirmation_raw, Mapping):
            raise AssistedBrowserError("confirmation must be an object.")
        unknown_confirmation_keys = (
            set(confirmation_raw) - _CONFIRMATION_KEYS
        )
        if unknown_confirmation_keys:
            raise AssistedBrowserError(
                "confirmation contains unsupported fields: "
                + ", ".join(sorted(unknown_confirmation_keys))
            )
        operation = _required_text(
            confirmation_raw.get("operation"),
            "confirmation.operation",
            maximum=80,
        )
        if operation not in _CONFIRMATION_OPERATIONS:
            raise AssistedBrowserError(
                "confirmation.operation is not a supported confirmation operation."
            )
        normalized["confirmation"] = {
            "operation": operation,
            "prompt": _required_text(
                confirmation_raw.get("prompt"),
                "confirmation.prompt",
                maximum=250,
            ),
            "confirmLabel": _required_text(
                confirmation_raw.get("confirmLabel"),
                "confirmation.confirmLabel",
                maximum=80,
            ),
            "rejectLabel": _required_text(
                confirmation_raw.get("rejectLabel"),
                "confirmation.rejectLabel",
                maximum=80,
            ),
        }
    entry_raw = raw.get("entry")
    if entry_raw is not None:
        if (
            action_raw is not None
            or actions_raw is not None
            or confirmation_raw is not None
        ):
            raise AssistedBrowserError(
                "A companion view may contain only one interaction."
            )
        if not isinstance(entry_raw, Mapping):
            raise AssistedBrowserError("entry must be an object.")
        unknown_entry_keys = set(entry_raw) - _ENTRY_KEYS
        if unknown_entry_keys:
            raise AssistedBrowserError(
                "entry contains unsupported fields: "
                + ", ".join(sorted(unknown_entry_keys))
            )
        operation = _required_text(
            entry_raw.get("operation"),
            "entry.operation",
            maximum=80,
        )
        if operation not in _ENTRY_OPERATIONS:
            raise AssistedBrowserError(
                "entry.operation is not a supported worksheet entry operation."
            )
        normalized_entry = {
            "operation": operation,
            "label": _required_text(
                entry_raw.get("label"),
                "entry.label",
                maximum=120,
            ),
        }
        options_raw = entry_raw.get("options")
        inputs_raw = entry_raw.get("inputs")
        if (
            operation == _PRESERVATION_OPERATION
            and options_raw is None
        ):
            raise AssistedBrowserError(
                "Existing configuration requires its canonical choices."
            )
        if options_raw is not None and inputs_raw is not None:
            raise AssistedBrowserError(
                "An entry may not define both options and inputs."
            )
        if inputs_raw is not None:
            expected_keys = _MULTI_INPUT_ENTRY_KEYS.get(operation)
            if expected_keys is None:
                raise AssistedBrowserError(
                    "Multiple worksheet inputs are not supported for this "
                    "operation."
                )
            if entry_raw.get("placeholder") is not None:
                raise AssistedBrowserError(
                    "A multiple-input entry may not define placeholder."
                )
            if not isinstance(inputs_raw, list) or len(inputs_raw) != 2:
                raise AssistedBrowserError(
                    "entry.inputs must contain the two overview values."
                )
            inputs = []
            for index, input_raw in enumerate(inputs_raw):
                if not isinstance(input_raw, Mapping):
                    raise AssistedBrowserError(
                        f"entry.inputs[{index}] must be an object."
                    )
                unknown_input_keys = set(input_raw) - _ENTRY_INPUT_KEYS
                if unknown_input_keys:
                    raise AssistedBrowserError(
                        f"entry.inputs[{index}] contains unsupported fields: "
                        + ", ".join(sorted(unknown_input_keys))
                    )
                inputs.append(
                    {
                        "key": _required_text(
                            input_raw.get("key"),
                            f"entry.inputs[{index}].key",
                            maximum=80,
                        ),
                        "label": _required_text(
                            input_raw.get("label"),
                            f"entry.inputs[{index}].label",
                            maximum=120,
                        ),
                        "placeholder": _required_text(
                            input_raw.get("placeholder"),
                            f"entry.inputs[{index}].placeholder",
                            maximum=160,
                        ),
                    }
                )
            if {entry_input["key"] for entry_input in inputs} != expected_keys:
                raise AssistedBrowserError(
                    "entry.inputs do not match the operation's worksheet rows."
                )
            normalized_entry["inputs"] = inputs
            normalized_entry["submitLabel"] = _required_text(
                entry_raw.get("submitLabel"),
                "entry.submitLabel",
                maximum=80,
            )
        elif options_raw is None:
            normalized_entry["placeholder"] = _required_text(
                entry_raw.get("placeholder"),
                "entry.placeholder",
                maximum=160,
            )
            normalized_entry["submitLabel"] = _required_text(
                entry_raw.get("submitLabel"),
                "entry.submitLabel",
                maximum=80,
            )
        else:
            if (
                entry_raw.get("placeholder") is not None
                or entry_raw.get("submitLabel") is not None
            ):
                raise AssistedBrowserError(
                    "A constrained entry may not define placeholder or submitLabel."
                )
            if (
                not isinstance(options_raw, list)
                or not 1 <= len(options_raw) <= 4
            ):
                raise AssistedBrowserError(
                    "entry.options must contain one through four choices."
                )
            options = [
                _required_text(
                    option,
                    f"entry.options[{index}]",
                    maximum=160,
                )
                for index, option in enumerate(options_raw)
            ]
            if len(set(options)) != len(options):
                raise AssistedBrowserError(
                    "entry.options choices must be unique."
                )
            if operation == _PRESERVATION_OPERATION:
                expected_options = entra_capture_instruction(
                    _PRESERVATION_WORKSHEET_ROW
                ).get("acceptedValues", [])
                if options != expected_options:
                    raise AssistedBrowserError(
                        "Existing configuration choices must match the "
                        "worksheet contract."
                    )
            normalized_entry["options"] = options
        normalized["entry"] = normalized_entry
    visual_help_raw = raw.get("visualHelp")
    if visual_help_raw is not None:
        constrained_entry = normalized.get("entry")
        if confirmation_raw is None and not (
            isinstance(constrained_entry, Mapping)
            and constrained_entry.get("options")
        ):
            raise AssistedBrowserError(
                "visualHelp requires a detected-value confirmation or "
                "constrained entry."
            )
        if not isinstance(visual_help_raw, Mapping):
            raise AssistedBrowserError("visualHelp must be an object.")
        unknown_visual_help_keys = set(visual_help_raw) - _VISUAL_HELP_KEYS
        if unknown_visual_help_keys:
            raise AssistedBrowserError(
                "visualHelp contains unsupported fields: "
                + ", ".join(sorted(unknown_visual_help_keys))
            )
        operation = _required_text(
            visual_help_raw.get("operation"),
            "visualHelp.operation",
            maximum=80,
        )
        if operation not in _COLLECTION_OPERATIONS:
            raise AssistedBrowserError(
                "visualHelp.operation is not a supported collection operation."
            )
        review_interaction = (
            normalized.get("confirmation") or constrained_entry
        )
        if review_interaction["operation"] != operation:
            raise AssistedBrowserError(
                "visualHelp and the review interaction must target the same "
                "worksheet row."
            )
        normalized["visualHelp"] = {
            "operation": operation,
            "label": _required_text(
                visual_help_raw.get("label"),
                "visualHelp.label",
                maximum=120,
            ),
        }
    return normalized


class CompanionState:
    """In-memory revision and render evidence for one ephemeral companion."""

    def __init__(self) -> None:
        """Initialize isolated revision, interaction, render, and visual-guidance state for one companion session."""
        self._lock = threading.Lock()
        self._revision = 0
        self._view: dict[str, Any] | None = None
        self._published_at: str | None = None
        self._fetched_revision: int | None = None
        self._fetched_at: str | None = None
        self._rendered_revision: int | None = None
        self._rendered_at: str | None = None
        self._heartbeat_at: float | None = None
        self._visible = False
        self._collection: dict[str, Any] | None = None
        self._confirmation: dict[str, Any] | None = None
        self._entry: dict[str, Any] | None = None
        self._visual_help: dict[str, Any] | None = None
        self._evidence_image: bytes | None = None
        self._evidence_image_metadata: dict[str, Any] | None = None
        self._target_pointers: list[dict[str, Any]] = []
        self._target_pointers_status: dict[str, Any] | None = None

    def publish(self, view: Any) -> dict[str, Any]:
        """Advance the displayed revision while preserving only same-operation authorization and visual context."""
        normalized = validate_view(view)
        with self._lock:
            previous_collection = self._collection
            previous_image = self._evidence_image
            previous_image_metadata = self._evidence_image_metadata
            previous_target_pointers = self._target_pointers
            entry = normalized.get("entry")
            visual_help = normalized.get("visualHelp")
            constrained_entry = (
                isinstance(entry, Mapping) and bool(entry.get("options"))
            )
            preservation_entry = (
                isinstance(entry, Mapping)
                and entry.get("operation") == _PRESERVATION_OPERATION
            )
            allowed_entry_statuses = (
                {"authorized", "navigated"}
                if constrained_entry
                else {"navigated"}
            )
            if (
                isinstance(entry, Mapping)
                and not preservation_entry
                and (
                    previous_collection is None
                    or previous_collection.get("status")
                    not in allowed_entry_statuses
                    or previous_collection.get("operation") != entry["operation"]
                )
            ):
                if constrained_entry:
                    raise AssistedBrowserError(
                        "Constrained worksheet entry is available only after "
                        "the same row reaches its review page."
                    )
                raise AssistedBrowserError(
                    "Manual entry is available only after Navigate only "
                    "completes for the same worksheet row. Report completion with "
                    f"`shared-browser-result --operation {entry['operation']} "
                    "--status navigated`, then retry the entry presentation."
                )
            if isinstance(visual_help, Mapping):
                if (
                    previous_collection is None
                    or previous_collection.get("status")
                    not in {"authorized", "navigated"}
                    or previous_collection.get("operation")
                    != visual_help["operation"]
                ):
                    raise AssistedBrowserError(
                        "Visual help is available only after the same worksheet "
                        "row is authorized."
                    )
            self._revision += 1
            self._view = normalized
            self._published_at = _now_iso()
            interaction = (
                normalized.get("action")
                or (
                    normalized["actions"][0]
                    if normalized.get("actions")
                    else None
                )
                or normalized.get("confirmation")
                or normalized.get("entry")
                or visual_help
            )
            operation = (
                interaction.get("operation")
                if isinstance(interaction, Mapping)
                else None
            )
            if (
                previous_collection is not None
                and previous_collection.get("status")
                in {"authorized", "navigated"}
                and previous_collection.get("operation") == operation
            ):
                self._collection = previous_collection
                if (
                    previous_image_metadata is not None
                    and previous_image_metadata.get("operation") == operation
                ):
                    self._evidence_image = previous_image
                    self._evidence_image_metadata = previous_image_metadata
                else:
                    self._evidence_image = None
                    self._evidence_image_metadata = None
                if (
                    previous_target_pointers
                    and not isinstance(visual_help, Mapping)
                    and all(
                        pointer.get("operation") == operation
                        for pointer in previous_target_pointers
                    )
                ):
                    self._target_pointers = previous_target_pointers
                else:
                    self._target_pointers = []
            else:
                self._collection = None
                self._evidence_image = None
                self._evidence_image_metadata = None
                self._target_pointers = []
            confirmation = normalized.get("confirmation")
            if isinstance(confirmation, Mapping):
                self._confirmation = {
                    "operation": confirmation["operation"],
                    "status": "waiting",
                    "revision": self._revision,
                    "requestedAt": self._published_at,
                }
            else:
                self._confirmation = None
            if isinstance(entry, Mapping):
                self._entry = {
                    "operation": entry["operation"],
                    "status": "waiting",
                    "revision": self._revision,
                    "requestedAt": self._published_at,
                }
            else:
                self._entry = None
            if isinstance(visual_help, Mapping):
                self._target_pointers = []
                self._target_pointers_status = {
                    "operation": visual_help["operation"],
                    "revision": self._revision,
                    "status": "pending",
                    "updatedAt": self._published_at,
                }
                self._visual_help = {
                    "operation": visual_help["operation"],
                    "label": visual_help["label"],
                    "status": "waiting",
                    "revision": self._revision,
                    "availableAt": self._published_at,
                }
            else:
                self._target_pointers_status = None
                self._visual_help = None
            return {
                "revision": self._revision,
                "publishedAt": self._published_at,
            }

    def reset(self) -> dict[str, Any]:
        """Clear the current worksheet interaction while keeping the companion session connected."""
        with self._lock:
            self._revision += 1
            reset_at = _now_iso()
            self._view = None
            self._published_at = None
            self._fetched_revision = None
            self._fetched_at = None
            self._rendered_revision = None
            self._rendered_at = None
            self._collection = None
            self._confirmation = None
            self._entry = None
            self._visual_help = None
            self._evidence_image = None
            self._evidence_image_metadata = None
            self._target_pointers = []
            self._target_pointers_status = None
            return {
                "revision": self._revision,
                "resetAt": reset_at,
            }

    def fetch(self) -> dict[str, Any] | None:
        """Return the current render payload and mark the revision as fetched by the browser."""
        with self._lock:
            if self._view is None:
                return None
            self._fetched_revision = self._revision
            self._fetched_at = _now_iso()
            return {
                "revision": self._revision,
                "view": self._view,
                "collection": self._collection,
                "confirmation": self._confirmation,
                "entry": self._entry,
                "visualHelp": self._visual_help,
                "evidenceImage": self._evidence_image_metadata,
                "targetPointer": (
                    self._target_pointers[-1]
                    if self._target_pointers
                    else None
                ),
                "targetPointers": list(self._target_pointers),
                "targetPointersStatus": self._target_pointers_status,
            }

    def begin_collection(
        self,
        *,
        revision: int,
        operation: str,
        mode: str = "navigate-and-capture",
    ) -> dict[str, Any]:
        """Bind a browser action click to the matching revision, operation, and assistance mode."""
        with self._lock:
            view = self._view or {}
            actions = view.get("actions")
            if not isinstance(actions, list):
                action = view.get("action")
                actions = [action] if isinstance(action, Mapping) else []
            selected = next(
                (
                    action
                    for action in actions
                    if action.get("operation") == operation
                    and action.get("mode", "navigate-and-capture") == mode
                ),
                None,
            )
            if revision != self._revision or selected is None:
                raise AssistedBrowserError(
                    "The collection request does not match the current guidance."
                )
            if (
                self._collection is not None
                and self._collection.get("status") == "collecting"
            ):
                raise AssistedBrowserError(
                    "The authorized collection operation is already running."
                )
            self._collection = {
                "operation": operation,
                "mode": mode,
                "status": "collecting",
                "startedAt": _now_iso(),
            }
            return dict(self._collection)

    def complete_collection(self, result: Mapping[str, Any]) -> dict[str, Any]:
        """Replace in-flight collection state with the helper's terminal authorization result."""
        with self._lock:
            self._collection = dict(result)
            return dict(self._collection)

    def complete_shared_browser_operation(
        self,
        *,
        operation: str,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Record the result of an authorized operation performed through the shared Integrated Browser."""
        if status not in {"navigated", "failed"}:
            raise AssistedBrowserError(
                "Shared browser status must be navigated or failed."
            )
        with self._lock:
            if (
                status == "navigated"
                and self._collection is not None
                and self._collection.get("operation") == operation
                and self._collection.get("status") == "navigated"
            ):
                return dict(self._collection)
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status") != "authorized"
            ):
                raise AssistedBrowserError(
                    "The shared browser result does not match an authorized "
                    "worksheet operation."
                )
            if status == "failed":
                normalized_error = _required_text(
                    error,
                    "error",
                    maximum=400,
                )
                self._collection = {
                    **self._collection,
                    "status": "failed",
                    "error": normalized_error,
                    "failedAt": _now_iso(),
                }
            else:
                self._collection = {
                    **self._collection,
                    "status": "navigated",
                    "navigatedAt": _now_iso(),
                }
            return dict(self._collection)

    def require_authorized_collection(
        self,
        operation: str,
    ) -> dict[str, Any]:
        """Gate candidate-producing reads on explicit navigate-and-capture authorization."""
        with self._lock:
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status") != "authorized"
            ):
                raise AssistedBrowserError(
                    "The requested Playwright read has not been authorized "
                    "through the current companion action."
                )
            return dict(self._collection)

    def require_navigation_collection(
        self,
        operation: str,
    ) -> dict[str, Any]:
        """Gate non-mutating navigation assistance on either supported authorization mode."""
        with self._lock:
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status")
                not in {"authorized", "navigated"}
            ):
                raise AssistedBrowserError(
                    "The requested navigation assistance has not been "
                    "authorized through the current companion action."
                )
            return dict(self._collection)

    def require_reveal_disclaimer(
        self,
        operation: str,
        control_label: str,
    ) -> None:
        """Require the current view to disclose the exact reveal-only Edit action before it can run."""
        with self._lock:
            view = self._view or {}
            actions = view.get("actions")
            if not isinstance(actions, list):
                action = view.get("action")
                actions = [action] if isinstance(action, Mapping) else []
            disclaimers = [
                str(action.get("disclaimer") or "")
                for action in actions
                if action.get("operation") == operation
            ]
            if not any(
                control_label.casefold() in disclaimer.casefold()
                and any(
                    token in disclaimer.casefold()
                    for token in ("display", "reveal", "view")
                )
                for disclaimer in disclaimers
            ):
                raise AssistedBrowserError(
                    "The companion must disclose the row-specific Edit action "
                    "before navigation can reveal the values."
                )

    def fail_collection(
        self,
        *,
        operation: str,
        error: str,
    ) -> dict[str, Any]:
        """Record an actionable terminal failure for the active row without discarding the view."""
        with self._lock:
            self._collection = {
                "operation": operation,
                "status": "failed",
                "error": error,
                "failedAt": _now_iso(),
            }
            return dict(self._collection)

    def decide_confirmation(
        self,
        *,
        revision: int,
        operation: str,
        decision: str,
    ) -> dict[str, Any]:
        """Accept one idempotent human decision for the confirmation in the current revision."""
        if decision not in {"confirmed", "rejected"}:
            raise AssistedBrowserError(
                "Confirmation decision must be confirmed or rejected."
            )
        with self._lock:
            requested = (self._view or {}).get("confirmation")
            if (
                revision != self._revision
                or not isinstance(requested, Mapping)
                or requested.get("operation") != operation
            ):
                raise AssistedBrowserError(
                    "The confirmation request does not match the current guidance."
                )
            if self._confirmation is None:
                raise AssistedBrowserError(
                    "The current guidance is not waiting for confirmation."
                )
            current_status = self._confirmation.get("status")
            if current_status != "waiting":
                if current_status == decision:
                    return dict(self._confirmation)
                raise AssistedBrowserError(
                    "The current candidate already has a different decision."
                )
            self._confirmation = {
                **self._confirmation,
                "status": decision,
                "decidedAt": _now_iso(),
            }
            definition = _COLLECTION_OPERATION_DEFINITIONS.get(operation)
            accepted_values = (
                entra_capture_instruction(
                    definition["worksheetRow"]
                ).get("acceptedValues", [])
                if definition is not None
                else []
            )
            if decision == "confirmed" and len(accepted_values) == 1:
                self._confirmation["value"] = accepted_values[0]
            return dict(self._confirmation)

    def _review_interaction_status(
        self,
        *,
        operation: str,
        revision: int,
    ) -> str | None:
        for interaction in (self._confirmation, self._entry):
            if (
                interaction is not None
                and interaction.get("operation") == operation
                and interaction.get("revision") == revision
            ):
                status = interaction.get("status")
                return status if isinstance(status, str) else None
        return None

    def _review_revision_allows_pointer(
        self,
        *,
        operation: str,
        revision: int,
    ) -> bool:
        """Bind pointer guidance to the current row interaction, independently of screenshots."""
        if revision != self._revision:
            return False
        view = self._view or {}
        interaction = view.get("confirmation") or view.get("entry")
        return (
            isinstance(interaction, Mapping)
            and interaction.get("operation") == operation
            and self._review_interaction_status(
                operation=operation,
                revision=revision,
            )
            in {"waiting", "confirmed", "submitted"}
        )

    def request_visual_help(
        self,
        *,
        revision: int,
        operation: str,
    ) -> dict[str, Any]:
        """Record one human screenshot request without changing row authorization."""
        with self._lock:
            requested = (self._view or {}).get("visualHelp")
            if (
                revision != self._revision
                or not isinstance(requested, Mapping)
                or requested.get("operation") != operation
            ):
                raise AssistedBrowserError(
                    "The visual-help request does not match the current guidance."
                )
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status")
                not in {"authorized", "navigated"}
            ):
                raise AssistedBrowserError(
                    "The screenshot target is not authorized by the current row."
                )
            if self._visual_help is None:
                raise AssistedBrowserError(
                    "The current guidance is not offering visual help."
                )
            if self._review_interaction_status(
                operation=operation,
                revision=revision,
            ) not in {"waiting", "confirmed", "submitted"}:
                raise AssistedBrowserError(
                    "The current worksheet review is no longer active."
                )
            pointer_status = self._target_pointers_status
            if (
                not isinstance(pointer_status, Mapping)
                or pointer_status.get("operation") != operation
                or pointer_status.get("revision") != revision
                or pointer_status.get("status") != "ready"
                or not self._target_pointers
            ):
                if (
                    isinstance(pointer_status, Mapping)
                    and pointer_status.get("status") == "failed"
                ):
                    raise AssistedBrowserError(
                        "Visual guidance is unavailable for this candidate."
                    )
                raise AssistedBrowserError(
                    "Visual guidance is still being prepared."
                )
            current_status = self._visual_help.get("status")
            if current_status in {"requested", "succeeded"}:
                return dict(self._visual_help)
            if current_status not in {"waiting", "failed"}:
                raise AssistedBrowserError(
                    "The visual-help request is not available."
                )
            self._visual_help = {
                "operation": operation,
                "label": requested["label"],
                "status": "requested",
                "revision": revision,
                "requestedAt": _now_iso(),
            }
            self._evidence_image = None
            self._evidence_image_metadata = None
            return dict(self._visual_help)

    def fail_visual_help(
        self,
        *,
        operation: str,
        error: str,
    ) -> dict[str, Any]:
        """Report a safe screenshot failure while keeping visual help retriable."""
        normalized_error = _required_text(
            error,
            "error",
            maximum=400,
        )
        with self._lock:
            if (
                self._visual_help is None
                or self._visual_help.get("operation") != operation
                or self._visual_help.get("status") != "requested"
            ):
                raise AssistedBrowserError(
                    "The screenshot failure does not match a requested visual-help operation."
                )
            self._visual_help = {
                **self._visual_help,
                "status": "failed",
                "error": normalized_error,
                "failedAt": _now_iso(),
            }
            return dict(self._visual_help)

    def set_evidence_image(
        self,
        *,
        operation: str,
        content: bytes,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Attach one authorized contextual screenshot to the active worksheet operation."""
        with self._lock:
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status")
                not in {"authorized", "navigated"}
            ):
                raise AssistedBrowserError(
                    "The screenshot target is not authorized by the current row."
                )
            if (
                self._visual_help is None
                or self._visual_help.get("operation") != operation
                or self._visual_help.get("status") != "requested"
            ):
                raise AssistedBrowserError(
                    "A screenshot may be captured only after the human requests visual help."
                )
            self._evidence_image = content
            self._evidence_image_metadata = {
                "id": secrets.token_urlsafe(12),
                "operation": operation,
                **metadata,
            }
            self._visual_help = {
                **self._visual_help,
                "status": "succeeded",
                "completedAt": _now_iso(),
            }
            return dict(self._evidence_image_metadata)

    def evidence_image(self) -> bytes:
        """Expose the contextual screenshot only after an authorized capture has supplied one."""
        with self._lock:
            if self._evidence_image is None:
                raise AssistedBrowserError(
                    "No contextual screenshot is available."
                )
            return self._evidence_image

    def set_target_pointer(
        self,
        *,
        operation: str,
        revision: int | None = None,
        metadata: Mapping[str, Any],
        append: bool = False,
    ) -> dict[str, Any]:
        """Publish one target location, optionally preserving earlier same-row pointers."""
        with self._lock:
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status")
                not in {"authorized", "navigated"}
            ):
                raise AssistedBrowserError(
                    "The target pointer is not authorized by the current row."
                )
            if revision is not None and not self._review_revision_allows_pointer(
                operation=operation,
                revision=revision,
            ):
                raise AssistedBrowserError(
                    "The target pointer does not match the current review."
                )
            pointer = {
                "id": secrets.token_urlsafe(12),
                "operation": operation,
                **metadata,
            }
            if append:
                self._target_pointers.append(pointer)
            else:
                self._target_pointers = [pointer]
            if revision is not None or (
                self._visual_help is not None
                and self._visual_help.get("operation") == operation
            ):
                self._target_pointers_status = {
                    "operation": operation,
                    "revision": self._revision,
                    "status": "ready",
                    "updatedAt": _now_iso(),
                }
            return dict(pointer)

    def set_target_pointers(
        self,
        *,
        operation: str,
        revision: int | None = None,
        metadata: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Atomically replace rail guidance with a coherent target set for the active row."""
        with self._lock:
            if (
                self._collection is None
                or self._collection.get("operation") != operation
                or self._collection.get("status")
                not in {"authorized", "navigated"}
            ):
                raise AssistedBrowserError(
                    "The target pointers are not authorized by the current row."
                )
            if not metadata:
                raise AssistedBrowserError(
                    "At least one application target is required."
                )
            if revision is not None and not self._review_revision_allows_pointer(
                operation=operation,
                revision=revision,
            ):
                raise AssistedBrowserError(
                    "The target pointers do not match the current review."
                )
            self._target_pointers = [
                {
                    "id": secrets.token_urlsafe(12),
                    "operation": operation,
                    **item,
                }
                for item in metadata
            ]
            if revision is not None or (
                self._visual_help is not None
                and self._visual_help.get("operation") == operation
            ):
                self._target_pointers_status = {
                    "operation": operation,
                    "revision": self._revision,
                    "status": "ready",
                    "updatedAt": _now_iso(),
                }
            return [dict(pointer) for pointer in self._target_pointers]

    def fail_target_pointers(
        self,
        *,
        operation: str,
        revision: int,
        error: str,
    ) -> dict[str, Any]:
        """Mark optional pointer guidance unavailable without blocking confirmation."""
        normalized_error = _required_text(
            error,
            "error",
            maximum=400,
        )
        with self._lock:
            if not self._review_revision_allows_pointer(
                operation=operation,
                revision=revision,
            ):
                raise AssistedBrowserError(
                    "The target pointer failure does not match the current review."
                )
            self._target_pointers = []
            self._target_pointers_status = {
                "operation": operation,
                "revision": revision,
                "status": "failed",
                "error": normalized_error,
                "updatedAt": _now_iso(),
            }
            return dict(self._target_pointers_status)

    def clear_target_pointer(self, *, operation: str) -> None:
        """Discard stale target positions after navigation changes page geometry."""
        with self._lock:
            if any(
                pointer.get("operation") == operation
                for pointer in self._target_pointers
            ):
                self._target_pointers = []
                if (
                    self._target_pointers_status is not None
                    and self._target_pointers_status.get("operation")
                    == operation
                ):
                    self._target_pointers_status = {
                        "operation": operation,
                        "revision": self._revision,
                        "status": "pending",
                        "updatedAt": _now_iso(),
                    }

    def submit_entry(
        self,
        *,
        revision: int,
        operation: str,
        value: str | None = None,
        values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Accept a bounded row entry or final preservation attestation."""
        with self._lock:
            requested = (self._view or {}).get("entry")
            if (
                revision != self._revision
                or not isinstance(requested, Mapping)
                or requested.get("operation") != operation
            ):
                raise AssistedBrowserError(
                    "The manual entry does not match the current guidance."
                )
            requested_inputs = requested.get("inputs")
            normalized_value = None
            normalized_values = None
            if isinstance(requested_inputs, list):
                if value is not None or not isinstance(values, Mapping):
                    raise AssistedBrowserError(
                        "The Enterprise application overview requires both "
                        "worksheet values."
                    )
                expected_keys = {
                    entry_input["key"]
                    for entry_input in requested_inputs
                }
                if set(values) != expected_keys:
                    raise AssistedBrowserError(
                        "The submitted overview values do not match the "
                        "displayed worksheet inputs."
                    )
                normalized_values = {}
                for key in expected_keys:
                    normalized = _required_text(
                        values.get(key),
                        f"entry values.{key}",
                        maximum=500,
                    )
                    if "\n" in normalized or "\r" in normalized:
                        raise AssistedBrowserError(
                            "Manual worksheet entries must be single lines."
                        )
                    normalized_values[key] = normalized
            else:
                if values is not None or not isinstance(value, str):
                    raise AssistedBrowserError(
                        "Manual worksheet entry value must be text."
                    )
                normalized_value = _required_text(
                    value,
                    "entry value",
                    maximum=500,
                )
                if "\n" in normalized_value or "\r" in normalized_value:
                    raise AssistedBrowserError(
                        "Manual worksheet entry must be a single line."
                    )
            options = requested.get("options")
            constrained_entry = isinstance(options, list)
            if constrained_entry and normalized_value not in options:
                raise AssistedBrowserError(
                    "The worksheet response is not one of the allowed choices."
                )
            if operation != _PRESERVATION_OPERATION:
                allowed_collection_statuses = (
                    {"authorized", "navigated"}
                    if constrained_entry
                    else {"navigated"}
                )
                if (
                    self._collection is None
                    or self._collection.get("status")
                    not in allowed_collection_statuses
                    or self._collection.get("operation") != operation
                ):
                    if constrained_entry:
                        raise AssistedBrowserError(
                            "Constrained worksheet entry requires the current "
                            "row's review page."
                        )
                    raise AssistedBrowserError(
                        "Manual entry requires a completed Navigate only "
                        "operation for this row."
                    )
            self._entry = {
                "operation": operation,
                "status": "submitted",
                "revision": revision,
                "submittedAt": _now_iso(),
            }
            if normalized_values is not None:
                self._entry["values"] = normalized_values
            else:
                self._entry["value"] = normalized_value
            return dict(self._entry)

    def event(self, raw: Any) -> None:
        """Track render acknowledgement, visibility, and heartbeat without treating events as user decisions."""
        if not isinstance(raw, Mapping):
            raise AssistedBrowserError("Companion event must be a JSON object.")
        event_type = raw.get("type")
        if event_type not in {"rendered", "heartbeat"}:
            raise AssistedBrowserError("Unsupported companion event type.")
        revision = raw.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise AssistedBrowserError("Companion event revision must be an integer.")
        visible = raw.get("visible")
        if not isinstance(visible, bool):
            raise AssistedBrowserError("Companion event visible must be boolean.")
        with self._lock:
            self._heartbeat_at = time.monotonic()
            self._visible = visible
            if event_type == "rendered" and revision == self._revision:
                self._rendered_revision = revision
                self._rendered_at = _now_iso()

    def status(self) -> dict[str, Any]:
        """Return a consistent snapshot for readiness checks and interaction correlation."""
        with self._lock:
            connected = (
                self._heartbeat_at is not None
                and time.monotonic() - self._heartbeat_at
                <= _CONNECTED_WINDOW_SECONDS
            )
            return {
                "revision": self._revision,
                "publishedAt": self._published_at,
                "fetchedRevision": self._fetched_revision,
                "fetchedAt": self._fetched_at,
                "renderedRevision": self._rendered_revision,
                "renderedAt": self._rendered_at,
                "visible": self._visible if connected else False,
                "connected": connected,
                "collection": self._collection,
                "confirmation": self._confirmation,
                "entry": self._entry,
                "visualHelp": self._visual_help,
                "evidenceImage": self._evidence_image_metadata,
                "targetPointer": (
                    self._target_pointers[-1]
                    if self._target_pointers
                    else None
                ),
                "targetPointers": list(self._target_pointers),
                "targetPointersStatus": self._target_pointers_status,
            }


class _Server(ThreadingHTTPServer):
    """Carry authenticated companion state and browser-session context on the loopback HTTP server."""

    token: str
    companion_state: CompanionState
    root: Path
    cdp_endpoint: str
    browser_mode: str


class CompanionHandler(BaseHTTPRequestHandler):
    """Serve static companion assets and authenticated loopback APIs."""

    server: _Server

    def log_message(self, _format: str, *_args: object) -> None:
        """Suppress default request logging so loopback tokens and browser paths do not reach console output."""
        return

    def _host_is_loopback(self) -> bool:
        """Reject Host-header confusion by accepting only this server's loopback authorities."""
        host = self.headers.get("Host", "")
        return host in {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }

    def _authorized(self) -> bool:
        """Authenticate private API calls with constant-time bearer-token comparison."""
        return secrets.compare_digest(
            self.headers.get("Authorization", ""),
            "Bearer " + self.server.token,
        )

    def _origin_is_safe(self) -> bool:
        """Limit browser-originated requests to the companion's own loopback origins."""
        origin = self.headers.get("Origin")
        return origin in {
            None,
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }

    def _headers(
        self,
        status: int,
        content_type: str,
        content_length: int,
    ) -> None:
        """Apply no-cache and browser-hardening headers uniformly to every response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' blob:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
    ) -> None:
        """Write a complete binary response through the hardened header path."""
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _send_json(self, status: int, value: Any) -> None:
        """Serialize API responses deterministically through the common response path."""
        body = json.dumps(value, sort_keys=True).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _reject_if_unsafe(self, *, require_auth: bool) -> bool:
        """Enforce loopback origin and optional bearer authentication before route handling."""
        if not self._host_is_loopback() or not self._origin_is_safe():
            self._send_json(403, {"error": "Request origin is not allowed."})
            return True
        if require_auth and not self._authorized():
            self._send_json(401, {"error": "Authorization is required."})
            return True
        return False

    def _read_json(self, *, maximum: int = _MAX_BODY_BYTES) -> Any:
        """Read a bounded UTF-8 JSON body to prevent memory abuse and validation bypass."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AssistedBrowserError("Invalid Content-Length.") from exc
        if length <= 0 or length > maximum:
            raise AssistedBrowserError("Request body size is invalid.")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssistedBrowserError("Request body must be valid UTF-8 JSON.") from exc

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        """Serve static assets and read-only session data from the authenticated loopback surface."""
        static_assets = {
            "/": ("companion.html", "text/html; charset=utf-8"),
            "/companion.js": (
                "companion.js",
                "application/javascript; charset=utf-8",
            ),
            "/companion.css": ("companion.css", "text/css; charset=utf-8"),
        }
        if self.path in static_assets:
            if self._reject_if_unsafe(require_auth=False):
                return
            filename, content_type = static_assets[self.path]
            self._send_bytes(
                200,
                (ASSET_ROOT / filename).read_bytes(),
                content_type,
            )
            return
        if self.path == "/api/view":
            if self._reject_if_unsafe(require_auth=True):
                return
            payload = self.server.companion_state.fetch()
            if payload is None:
                self._send_json(200, {"revision": 0, "view": None})
            else:
                self._send_json(200, payload)
            return
        if self.path == "/api/status":
            if self._reject_if_unsafe(require_auth=True):
                return
            self._send_json(200, self.server.companion_state.status())
            return
        if self.path == "/api/evidence-image":
            if self._reject_if_unsafe(require_auth=True):
                return
            try:
                content = self.server.companion_state.evidence_image()
            except AssistedBrowserError as exc:
                self._send_json(404, {"error": str(exc)})
            else:
                self._send_bytes(200, content, "image/png")
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        """Route validated interaction and browser-assistance commands through capability checks."""
        if self._reject_if_unsafe(require_auth=True):
            return
        try:
            if self.path == "/api/present":
                self._send_json(
                    200,
                    self.server.companion_state.publish(self._read_json()),
                )
                return
            if self.path == "/api/event":
                self.server.companion_state.event(self._read_json())
                self._send_json(200, {"accepted": True})
                return
            if self.path == "/api/action":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Collection request must be a JSON object."
                    )
                if set(raw) not in (
                    {"operation", "revision"},
                    {"mode", "operation", "revision"},
                ):
                    raise AssistedBrowserError(
                        "Collection request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                revision = raw.get("revision")
                if not isinstance(revision, int) or revision < 1:
                    raise AssistedBrowserError(
                        "Collection revision must be a positive integer."
                    )
                mode = raw.get("mode", "navigate-and-capture")
                if mode not in _ACTION_MODES:
                    raise AssistedBrowserError(
                        "Collection mode must be navigate-only or "
                        "navigate-and-capture."
                    )
                self.server.companion_state.begin_collection(
                    revision=revision,
                    operation=operation,
                    mode=mode,
                )
                try:
                    result = _authorize_collection_operation(
                        self.server.root,
                        operation,
                        mode=mode,
                    )
                except AssistedBrowserError as exc:
                    result = self.server.companion_state.fail_collection(
                        operation=operation,
                        error=str(exc),
                    )
                else:
                    result = self.server.companion_state.complete_collection(
                        result
                    )
                self._send_json(200, {"collection": result})
                return
            if self.path == "/api/confirmation":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Confirmation request must be a JSON object."
                    )
                if set(raw) != {"decision", "operation", "revision"}:
                    raise AssistedBrowserError(
                        "Confirmation request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                decision = _required_text(
                    raw.get("decision"),
                    "decision",
                    maximum=20,
                )
                revision = raw.get("revision")
                if not isinstance(revision, int) or revision < 1:
                    raise AssistedBrowserError(
                        "Confirmation revision must be a positive integer."
                    )
                result = self.server.companion_state.decide_confirmation(
                    revision=revision,
                    operation=operation,
                    decision=decision,
                )
                self._send_json(200, {"confirmation": result})
                return
            if self.path == "/api/entry":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Manual entry request must be a JSON object."
                    )
                valid_fields = (
                    {"operation", "revision", "value"},
                    {"operation", "revision", "values"},
                )
                if set(raw) not in valid_fields:
                    raise AssistedBrowserError(
                        "Manual entry request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                revision = raw.get("revision")
                if not isinstance(revision, int) or revision < 1:
                    raise AssistedBrowserError(
                        "Manual entry revision must be a positive integer."
                    )
                value = raw.get("value")
                values = raw.get("values")
                if "value" in raw and not isinstance(value, str):
                    raise AssistedBrowserError(
                        "Manual entry value must be text."
                    )
                if "values" in raw and not isinstance(values, Mapping):
                    raise AssistedBrowserError(
                        "Manual entry values must be an object."
                    )
                result = self.server.companion_state.submit_entry(
                    revision=revision,
                    operation=operation,
                    value=value,
                    values=values,
                )
                self._send_json(200, {"entry": result})
                return
            if self.path == "/api/visual-help":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Visual-help request must be a JSON object."
                    )
                if set(raw) != {"operation", "revision"}:
                    raise AssistedBrowserError(
                        "Visual-help request fields are invalid."
                    )
                revision = raw.get("revision")
                if not isinstance(revision, int) or revision < 1:
                    raise AssistedBrowserError(
                        "Visual-help revision must be a positive integer."
                    )
                result = self.server.companion_state.request_visual_help(
                    revision=revision,
                    operation=_required_text(
                        raw.get("operation"),
                        "operation",
                        maximum=80,
                    ),
                )
                self._send_json(200, {"visualHelp": result})
                return
            if self.path == "/api/visual-help-result":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Visual-help result must be a JSON object."
                    )
                if set(raw) != {"error", "operation", "status"}:
                    raise AssistedBrowserError(
                        "Visual-help result fields are invalid."
                    )
                status = _required_text(
                    raw.get("status"),
                    "status",
                    maximum=20,
                )
                if status != "failed":
                    raise AssistedBrowserError(
                        "Visual-help result status must be failed."
                    )
                result = self.server.companion_state.fail_visual_help(
                    operation=_required_text(
                        raw.get("operation"),
                        "operation",
                        maximum=80,
                    ),
                    error=_required_text(
                        raw.get("error"),
                        "error",
                        maximum=400,
                    ),
                )
                self._send_json(200, {"visualHelp": result})
                return
            if self.path == "/api/shared-browser-result":
                if self.server.browser_mode != _VSCODE_BROWSER_MODE:
                    raise AssistedBrowserError(
                        "Shared browser results apply only to VS Code sessions."
                    )
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Shared browser result must be a JSON object."
                    )
                if set(raw) - {"error", "operation", "status"}:
                    raise AssistedBrowserError(
                        "Shared browser result fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                if operation not in _COLLECTION_OPERATIONS:
                    raise AssistedBrowserError(
                        "Unsupported collection operation."
                    )
                status = _required_text(
                    raw.get("status"),
                    "status",
                    maximum=20,
                )
                result = (
                    self.server.companion_state
                    .complete_shared_browser_operation(
                        operation=operation,
                        status=status,
                        error=raw.get("error"),
                    )
                )
                self._send_json(200, {"collection": result})
                return
            if self.path == "/api/inspect":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Inspection request must be a JSON object."
                    )
                if set(raw) != {"limit", "operation", "selector"}:
                    raise AssistedBrowserError(
                        "Inspection request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                selector = _required_text(
                    raw.get("selector"),
                    "selector",
                    maximum=500,
                )
                limit = raw.get("limit")
                if not isinstance(limit, int) or not 1 <= limit <= 50:
                    raise AssistedBrowserError(
                        "Inspection limit must be an integer from 1 through 50."
                    )
                authorization = (
                    self.server.companion_state.require_navigation_collection(
                        operation
                    )
                )
                result = _inspect_authorized_selector(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    limit=limit,
                    navigation_only=(
                        authorization.get("status") == "navigated"
                    ),
                )
                self._send_json(
                    200,
                    {
                        "authorization": authorization,
                        "inspection": result,
                    },
                )
                return
            if self.path == "/api/follow":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Follow request must be a JSON object."
                    )
                if set(raw) != {
                    "frameIndex",
                    "matchIndex",
                    "operation",
                    "selector",
                }:
                    raise AssistedBrowserError(
                        "Follow request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                selector = _required_text(
                    raw.get("selector"),
                    "selector",
                    maximum=500,
                )
                frame_index = raw.get("frameIndex")
                match_index = raw.get("matchIndex")
                if not isinstance(frame_index, int) or frame_index < 0:
                    raise AssistedBrowserError(
                        "Follow frameIndex must be a non-negative integer."
                    )
                if not isinstance(match_index, int) or match_index < 0:
                    raise AssistedBrowserError(
                        "Follow matchIndex must be a non-negative integer."
                    )
                authorization = (
                    self.server.companion_state.require_navigation_collection(
                        operation
                    )
                )
                result = _follow_authorized_link(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    frame_index=frame_index,
                    match_index=match_index,
                )
                self._send_json(
                    200,
                    {
                        "authorization": authorization,
                        "navigation": result,
                    },
                )
                return
            if self.path == "/api/capture":
                raw = self._read_json(
                    maximum=(
                        _MAX_SHARED_CAPTURE_BODY_BYTES
                        if self.server.browser_mode == _VSCODE_BROWSER_MODE
                        else _MAX_BODY_BYTES
                    )
                )
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Screenshot request must be a JSON object."
                    )
                if self.server.browser_mode == _VSCODE_BROWSER_MODE:
                    if set(raw) != {"imageBase64", "label", "operation"}:
                        raise AssistedBrowserError(
                            "Shared browser screenshot fields are invalid."
                        )
                    operation = _required_text(
                        raw.get("operation"),
                        "operation",
                        maximum=80,
                    )
                    self.server.companion_state.require_navigation_collection(operation)
                    result = self.server.companion_state.set_evidence_image(
                        operation=operation,
                        content=decode_shared_browser_capture(raw.get("imageBase64")),
                        metadata={
                            "label": _required_text(
                                raw.get("label"),
                                "label",
                                maximum=120,
                            ),
                            "capturedAt": _now_iso(),
                        },
                    )
                    self._send_json(200, {"evidenceImage": result})
                    return
                if set(raw) != {
                    "frameIndex",
                    "matchIndex",
                    "operation",
                    "selector",
                }:
                    raise AssistedBrowserError(
                        "Screenshot request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                selector = _required_text(
                    raw.get("selector"),
                    "selector",
                    maximum=500,
                )
                frame_index = raw.get("frameIndex")
                match_index = raw.get("matchIndex")
                if not isinstance(frame_index, int) or frame_index < 0:
                    raise AssistedBrowserError(
                        "Screenshot frameIndex must be a non-negative integer."
                    )
                if not isinstance(match_index, int) or match_index < 0:
                    raise AssistedBrowserError(
                        "Screenshot matchIndex must be a non-negative integer."
                    )
                self.server.companion_state.require_navigation_collection(
                    operation
                )
                content, metadata = _capture_authorized_element(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    frame_index=frame_index,
                    match_index=match_index,
                )
                result = self.server.companion_state.set_evidence_image(
                    operation=operation,
                    content=content,
                    metadata=metadata,
                )
                self._send_json(200, {"evidenceImage": result})
                return
            if self.path == "/api/fill-search":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Search fill request must be a JSON object."
                    )
                if set(raw) != {
                    "frameIndex",
                    "matchIndex",
                    "operation",
                    "selector",
                    "value",
                }:
                    raise AssistedBrowserError(
                        "Search fill request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                selector = _required_text(
                    raw.get("selector"),
                    "selector",
                    maximum=500,
                )
                frame_index = raw.get("frameIndex")
                match_index = raw.get("matchIndex")
                if not isinstance(frame_index, int) or frame_index < 0:
                    raise AssistedBrowserError(
                        "Search fill frameIndex must be a non-negative integer."
                    )
                if not isinstance(match_index, int) or match_index < 0:
                    raise AssistedBrowserError(
                        "Search fill matchIndex must be a non-negative integer."
                    )
                self.server.companion_state.require_navigation_collection(
                    operation
                )
                result = _fill_navigation_search(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    frame_index=frame_index,
                    match_index=match_index,
                    value=raw.get("value"),
                )
                self._send_json(200, {"search": result})
                return
            if self.path == "/api/point":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Target pointer request must be a JSON object."
                    )
                required_fields = {
                    "frameIndex",
                    "matchIndex",
                    "operation",
                    "revision",
                    "selector",
                }
                if not required_fields.issubset(raw) or (
                    set(raw) - required_fields != {"append"}
                    and set(raw) != required_fields
                ):
                    raise AssistedBrowserError(
                        "Target pointer request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                selector = _required_text(
                    raw.get("selector"),
                    "selector",
                    maximum=500,
                )
                frame_index = raw.get("frameIndex")
                match_index = raw.get("matchIndex")
                revision = raw.get("revision")
                if not isinstance(frame_index, int) or frame_index < 0:
                    raise AssistedBrowserError(
                        "Target pointer frameIndex must be a non-negative integer."
                    )
                if not isinstance(match_index, int) or match_index < 0:
                    raise AssistedBrowserError(
                        "Target pointer matchIndex must be a non-negative integer."
                    )
                if (
                    isinstance(revision, bool)
                    or not isinstance(revision, int)
                    or revision < 1
                ):
                    raise AssistedBrowserError(
                        "Target pointer revision must be a positive integer."
                    )
                append = raw.get("append", False)
                if not isinstance(append, bool):
                    raise AssistedBrowserError(
                        "Target pointer append must be boolean."
                    )
                self.server.companion_state.require_navigation_collection(
                    operation
                )
                metadata = _position_authorized_target(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    frame_index=frame_index,
                    match_index=match_index,
                )
                result = self.server.companion_state.set_target_pointer(
                    operation=operation,
                    revision=revision,
                    metadata=metadata,
                    append=append,
                )
                self._send_json(
                    200,
                    {
                        "targetPointer": result,
                        "targetPointers": self.server.companion_state.status()[
                            "targetPointers"
                        ],
                    },
                )
                return
            if self.path == "/api/point-targets":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Target pointers request must be a JSON object."
                    )
                allowed_fields = {"error", "operation", "revision", "targets"}
                if set(raw) - allowed_fields or not {
                    "operation",
                    "revision",
                }.issubset(raw):
                    raise AssistedBrowserError(
                        "Target pointers request fields are invalid."
                    )
                has_targets = "targets" in raw
                has_error = "error" in raw
                if has_targets == has_error:
                    raise AssistedBrowserError(
                        "Target pointers require either targets or an error."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                revision = raw.get("revision")
                if (
                    isinstance(revision, bool)
                    or not isinstance(revision, int)
                    or revision < 1
                ):
                    raise AssistedBrowserError(
                        "Target pointers revision must be a positive integer."
                    )
                if has_error:
                    result = self.server.companion_state.fail_target_pointers(
                        operation=operation,
                        revision=revision,
                        error=raw.get("error"),
                    )
                    self._send_json(
                        200,
                        {"targetPointersStatus": result},
                    )
                    return
                target_specs = raw.get("targets")
                if self.server.browser_mode == _VSCODE_BROWSER_MODE:
                    self.server.companion_state.require_navigation_collection(
                        operation
                    )
                    result = self.server.companion_state.set_target_pointers(
                        operation=operation,
                        revision=revision,
                        metadata=normalize_shared_browser_targets(target_specs),
                    )
                    self._send_json(
                        200,
                        {
                            "targetPointers": result,
                            "targetPointersStatus": (
                                self.server.companion_state.status()[
                                    "targetPointersStatus"
                                ]
                            ),
                        },
                    )
                    return
                if not isinstance(target_specs, list) or not target_specs:
                    raise AssistedBrowserError(
                        "targets must contain at least one application target."
                    )
                normalized_targets = []
                for index, target_spec in enumerate(target_specs):
                    if not isinstance(target_spec, Mapping):
                        raise AssistedBrowserError(
                            f"targets[{index}] must be an object."
                        )
                    if not set(target_spec).issubset(
                        {"frameIndex", "label", "matchIndex", "selector"}
                    ) or not {
                        "frameIndex",
                        "matchIndex",
                        "selector",
                    }.issubset(target_spec):
                        raise AssistedBrowserError(
                            f"targets[{index}] fields are invalid."
                        )
                    frame_index = target_spec.get("frameIndex")
                    match_index = target_spec.get("matchIndex")
                    if not isinstance(frame_index, int) or frame_index < 0:
                        raise AssistedBrowserError(
                            f"targets[{index}].frameIndex must be non-negative."
                        )
                    if not isinstance(match_index, int) or match_index < 0:
                        raise AssistedBrowserError(
                            f"targets[{index}].matchIndex must be non-negative."
                        )
                    normalized_target = {
                        "selector": _required_text(
                            target_spec.get("selector"),
                            f"targets[{index}].selector",
                            maximum=500,
                        ),
                        "frameIndex": frame_index,
                        "matchIndex": match_index,
                    }
                    if target_spec.get("label") is not None:
                        normalized_target["label"] = _required_text(
                            target_spec.get("label"),
                            f"targets[{index}].label",
                            maximum=120,
                        )
                    normalized_targets.append(normalized_target)
                self.server.companion_state.require_navigation_collection(
                    operation
                )
                metadata = _position_authorized_targets(
                    self.server.root,
                    operation=operation,
                    target_specs=normalized_targets,
                )
                result = self.server.companion_state.set_target_pointers(
                    operation=operation,
                    revision=revision,
                    metadata=metadata,
                )
                self._send_json(
                    200,
                    {
                        "targetPointers": result,
                        "targetPointersStatus": (
                            self.server.companion_state.status()[
                                "targetPointersStatus"
                            ]
                        ),
                    },
                )
                return
            if self.path == "/api/reveal":
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Reveal request must be a JSON object."
                    )
                if set(raw) != {
                    "frameIndex",
                    "matchIndex",
                    "operation",
                    "selector",
                }:
                    raise AssistedBrowserError(
                        "Reveal request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                selector = _required_text(
                    raw.get("selector"),
                    "selector",
                    maximum=500,
                )
                frame_index = raw.get("frameIndex")
                match_index = raw.get("matchIndex")
                if not isinstance(frame_index, int) or frame_index < 0:
                    raise AssistedBrowserError(
                        "Reveal frameIndex must be a non-negative integer."
                    )
                if not isinstance(match_index, int) or match_index < 0:
                    raise AssistedBrowserError(
                        "Reveal matchIndex must be a non-negative integer."
                    )
                self.server.companion_state.require_navigation_collection(
                    operation
                )
                evidence = _inspect_reveal_control(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    frame_index=frame_index,
                    match_index=match_index,
                )
                self.server.companion_state.require_reveal_disclaimer(
                    operation,
                    str(evidence["label"]),
                )
                result = _reveal_authorized_values(
                    self.server.root,
                    operation=operation,
                    selector=selector,
                    frame_index=frame_index,
                    match_index=match_index,
                )
                self.server.companion_state.clear_target_pointer(
                    operation=operation
                )
                self._send_json(200, {"reveal": result})
                return
            if self.path == "/api/reset":
                if self._read_json() != {}:
                    raise AssistedBrowserError(
                        "Companion reset request must be an empty object."
                    )
                self._send_json(
                    200,
                    self.server.companion_state.reset(),
                )
                return
            if self.path == "/api/stop":
                self._send_json(200, {"stopping": True})
                threading.Thread(
                    target=self.server.shutdown,
                    daemon=True,
                ).start()
                return
            self._send_json(404, {"error": "Not found."})
        except AssistedBrowserError as exc:
            self._send_json(400, {"error": str(exc)})


def _session_path(root: Path) -> Path:
    """Keep process rendezvous metadata in the workspace-scoped local state directory."""
    return root.resolve() / SESSION_PATH


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Persist session metadata atomically so readers never observe a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_session(root: Path) -> dict[str, Any]:
    """Load and validate the minimum metadata required to address the active helper session."""
    path = _session_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssistedBrowserError(
            "No assisted-browser session is running. Start one first."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AssistedBrowserError(
            "Assisted-browser session metadata is unreadable."
        ) from exc
    if not isinstance(raw, dict):
        raise AssistedBrowserError(
            "Assisted-browser session metadata is invalid."
        )
    for key in ("port", "token", "pid"):
        if not raw.get(key):
            raise AssistedBrowserError(
                "Assisted-browser session metadata is incomplete."
            )
    browser_mode = raw.get("browserMode", _EDGE_BROWSER_MODE)
    if browser_mode not in {_EDGE_BROWSER_MODE, _VSCODE_BROWSER_MODE}:
        raise AssistedBrowserError(
            "Assisted-browser session metadata has an invalid browser mode."
        )
    raw["browserMode"] = browser_mode
    if browser_mode == _EDGE_BROWSER_MODE and not raw.get("cdpEndpoint"):
        raise AssistedBrowserError(
            "Assisted-browser session metadata is incomplete."
        )
    return raw


def _api_request(
    session: Mapping[str, Any],
    path: str,
    *,
    value: Any | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Provide one authenticated JSON transport for CLI-to-companion loopback calls."""
    body = None
    method = "GET"
    headers = {"Authorization": "Bearer " + str(session["token"])}
    if value is not None:
        body = json.dumps(value).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/json"
    request = Request(
        f"http://127.0.0.1:{int(session['port'])}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        raise AssistedBrowserError(
            str(detail or f"Companion request failed with HTTP {exc.code}.")
        ) from exc
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise AssistedBrowserError(
            "The assisted-browser companion is not responding."
        ) from exc
    if not isinstance(decoded, dict):
        raise AssistedBrowserError(
            "The assisted-browser companion returned an invalid response."
        )
    return decoded


def _session_is_alive(session: Mapping[str, Any]) -> bool:
    """Probe the authenticated status endpoint instead of trusting stale process metadata."""
    try:
        _api_request(session, "/api/status", timeout=1.0)
        return True
    except AssistedBrowserError:
        return False


def _serve(root: Path) -> None:
    """Run the loopback companion server and publish its rendezvous metadata."""
    token = os.environ.get(_TOKEN_ENV, "")
    if not token:
        raise AssistedBrowserError("Companion token was not supplied.")
    server = _Server(("127.0.0.1", 0), CompanionHandler)
    server.token = token
    server.companion_state = CompanionState()
    server.root = root
    server.browser_mode = os.environ.get(
        _BROWSER_MODE_ENV,
        _EDGE_BROWSER_MODE,
    )
    server.cdp_endpoint = os.environ.get(
        "ESS_WORKDAY_ASSIST_CDP",
        "",
    )
    session_path = _session_path(root)
    session = {
        "schemaVersion": 1,
        "port": server.server_port,
        "token": token,
        "pid": os.getpid(),
        "startedAt": _now_iso(),
        "browserMode": server.browser_mode,
    }
    if server.browser_mode == _EDGE_BROWSER_MODE:
        session["cdpEndpoint"] = server.cdp_endpoint or DEFAULT_CDP
    _write_json(
        session_path,
        session,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


def _start_server(
    root: Path,
    cdp_endpoint: str | None,
    browser_mode: str,
) -> tuple[dict[str, Any], bool]:
    """Reuse a live session-owned server or launch a new detached loopback server."""
    path = _session_path(root)
    if path.exists():
        try:
            existing = _load_session(root)
        except AssistedBrowserError:
            existing = {}
        if existing and _session_is_alive(existing):
            if existing.get("browserMode") != browser_mode:
                raise AssistedBrowserError(
                    "The active assisted-browser session uses a different "
                    "browser mode. Stop it before starting another."
                )
            if (
                browser_mode == _EDGE_BROWSER_MODE
                and existing.get("cdpEndpoint") != cdp_endpoint
            ):
                raise AssistedBrowserError(
                    "The active assisted-browser session uses a different "
                    "CDP endpoint. Stop it before starting another."
                )
            return existing, False
        path.unlink(missing_ok=True)

    token = secrets.token_urlsafe(32)
    environment = os.environ.copy()
    environment[_TOKEN_ENV] = token
    environment[_BROWSER_MODE_ENV] = browser_mode
    if cdp_endpoint is not None:
        environment["ESS_WORKDAY_ASSIST_CDP"] = cdp_endpoint
    else:
        environment.pop("ESS_WORKDAY_ASSIST_CDP", None)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--root",
        str(root.resolve()),
        "_serve",
    ]
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": environment,
        "cwd": str(root.resolve()),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(command, **popen_kwargs)  # noqa: S603 - trusted interpreter/script

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if path.exists():
            session = _load_session(root)
            if _session_is_alive(session):
                return session, True
        time.sleep(0.1)
    raise AssistedBrowserError("The assisted-browser companion did not start.")


def _parse_cdp_endpoint(value: str) -> tuple[str, int]:
    """Restrict browser attachment to an explicit localhost HTTP debugging endpoint."""
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AssistedBrowserError(
            "CDP endpoint must be an HTTP localhost URL with an explicit port."
        )
    return parsed.hostname, parsed.port


def _require_edge_browser(session: Mapping[str, Any]) -> str:
    """Return the CDP endpoint only for sessions that own or attach to Edge."""
    if session.get("browserMode", _EDGE_BROWSER_MODE) != _EDGE_BROWSER_MODE:
        raise AssistedBrowserError(
            "This session uses the VS Code Integrated Browser. Use the "
            "shared browser tools for page inspection and navigation."
        )
    endpoint = session.get("cdpEndpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise AssistedBrowserError(
            "The assisted Edge session is missing its CDP endpoint."
        )
    return endpoint


def _active_scope(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the established Workday target needed to derive bounded browser surfaces."""
    state = WorkdayConnectStore(root).load()
    scope = state.get("scope")
    if not isinstance(scope, dict):
        raise AssistedBrowserError(
            "Connect Workday has not recorded an active target yet."
        )
    agent = scope.get("agent")
    if not isinstance(agent, dict):
        raise AssistedBrowserError(
            "Connect Workday has not recorded the active agent yet."
        )
    return scope, agent


def surface_url(root: Path, surface: str) -> str:
    """Resolve a bounded browser surface from authoritative Workday state."""
    if surface not in _SURFACES:
        raise AssistedBrowserError("Unsupported assisted-browser surface.")
    scope, agent = _active_scope(root)
    if surface == "entra-configuration":
        _required_text(
            scope.get("entraTenantId"),
            "Recorded Microsoft Entra tenant ID",
            maximum=100,
        )
        return "https://entra.microsoft.com/"
    environment_id = _required_text(
        scope.get("environmentId"),
        "Recorded environment ID",
        maximum=100,
    )
    if surface in {"dataverse-connection", "workday-connection"}:
        ring = _required_text(
            scope.get("ring"),
            "Recorded service ring",
            maximum=20,
        ).casefold()
        origins = {
            "prod": "https://make.powerautomate.com",
            "preprod": "https://make.preprod.powerautomate.com",
            "test": "https://make.test.powerautomate.com",
        }
        try:
            origin = origins[ring]
        except KeyError as exc:
            raise AssistedBrowserError(
                f"Recorded service ring {ring!r} is not supported."
            ) from exc
        connector = (
            "shared_commondataserviceforapps"
            if surface == "dataverse-connection"
            else "shared_workdaysoap"
        )
        return (
            f"{origin}/environments/{environment_id}/connections/available/"
            f"{connector}"
        )
    bot_id = _required_text(
        agent.get("botId"),
        "Recorded agent ID",
        maximum=100,
    )
    return test_pane_url(environment_id, bot_id)


def _playwright() -> tuple[Any, type[Exception]]:
    """Load Playwright lazily so missing browser support produces a focused dependency error."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AssistedBrowserError(
            "Python Playwright is required for assisted browsing. Install the "
            "script requirements and retry."
        ) from exc
    return sync_playwright, PlaywrightError


def _target_record(page: Any) -> dict[str, Any]:
    """Capture sanitized target identity and geometry for pane discovery and layout checks."""
    client = page.context.new_cdp_session(page)
    try:
        target = client.send("Target.getTargetInfo")["targetInfo"]
        window = client.send(
            "Browser.getWindowForTarget",
            {"targetId": target["targetId"]},
        )
        bounds = client.send(
            "Browser.getWindowBounds",
            {"windowId": window["windowId"]},
        )["bounds"]
        metrics = page.evaluate(
            """() => ({
                visibility: document.visibilityState,
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight
            })"""
        )
        return {
            "targetId": target["targetId"],
            "windowId": window["windowId"],
            "url": sanitize_browser_url(page.url),
            "visibility": metrics["visibility"],
            "innerWidth": metrics["innerWidth"],
            "innerHeight": metrics["innerHeight"],
            "windowWidth": bounds.get("width"),
            "windowHeight": bounds.get("height"),
        }
    finally:
        client.detach()


def classify_layout(
    application: Mapping[str, Any] | None,
    companion: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Classify whether two normal pages are visibly paired in one Edge window."""
    if application is None or companion is None:
        return {
            "sameWindow": False,
            "bothVisible": False,
            "splitScreenReady": False,
            "reason": "application-or-companion-target-missing",
        }
    same_window = application.get("windowId") == companion.get("windowId")
    both_visible = (
        application.get("visibility") == "visible"
        and companion.get("visibility") == "visible"
    )
    window_width = companion.get("windowWidth") or application.get("windowWidth")
    widths = (application.get("innerWidth"), companion.get("innerWidth"))
    sized_for_split = (
        isinstance(window_width, (int, float))
        and window_width > 0
        and all(isinstance(width, (int, float)) and width >= 280 for width in widths)
        and all(width <= window_width * 0.8 for width in widths)
        and sum(widths) >= window_width * 0.7
    )
    ready = bool(same_window and both_visible and sized_for_split)
    if ready:
        reason = "paired"
    elif not same_window:
        reason = "different-windows"
    elif not both_visible:
        reason = "one-pane-not-visible"
    else:
        reason = "pages-not-sized-for-split-screen"
    return {
        "sameWindow": same_window,
        "bothVisible": both_visible,
        "splitScreenReady": ready,
        "reason": reason,
    }


@dataclass
class _BrowserTargets:
    """Pair the session-owned application and companion target records discovered in Edge."""
    application: dict[str, Any] | None
    companion: dict[str, Any] | None


def _find_targets(browser: Any, session: Mapping[str, Any]) -> _BrowserTargets:
    """Resolve recorded target IDs with a bounded same-window fallback for initial recovery."""
    application = None
    companion = None
    expected_application = session.get("applicationTargetId")
    expected_companion = session.get("companionTargetId")
    records: list[tuple[Any, dict[str, Any]]] = []
    for context in browser.contexts:
        for page in context.pages:
            try:
                records.append((page, _target_record(page)))
            except Exception:
                continue
    for _page, record in records:
        if record["targetId"] == expected_application:
            application = record
        if record["targetId"] == expected_companion:
            companion = record
    if companion is None:
        companion_origin = f"http://127.0.0.1:{int(session['port'])}/"
        companion = next(
            (
                record
                for _page, record in records
                if str(record.get("url") or "").startswith(companion_origin)
            ),
            None,
        )
    if application is None and companion is not None:
        application = next(
            (
                record
                for _page, record in records
                if record["targetId"] != companion["targetId"]
                and record.get("windowId") == companion.get("windowId")
                and str(record.get("url") or "").startswith(("http://", "https://"))
            ),
            None,
        )
    return _BrowserTargets(application=application, companion=companion)


def _open_initial_pages(
    session: dict[str, Any],
    application_url: str,
    *,
    pages_launched: bool,
) -> dict[str, Any]:
    """Ensure one application page and one tokenized companion page exist in the attached browser."""
    companion_url = (
        f"http://127.0.0.1:{int(session['port'])}/#token={session['token']}"
    )
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        if not browser.contexts:
            raise AssistedBrowserError(
                "The CDP browser has no attachable browser context."
            )
        companion_origin = f"http://127.0.0.1:{int(session['port'])}/"
        deadline = time.monotonic() + 5.0
        application_page = None
        companion_page = None
        while time.monotonic() < deadline:
            pages = [
                page
                for context in browser.contexts
                for page in context.pages
            ]
            companion_page = next(
                (
                    page
                    for page in pages
                    if page.url.startswith(companion_origin)
                ),
                None,
            )
            application_page = next(
                (page for page in pages if page.url == application_url),
                None,
            )
            if application_page is None and pages_launched and companion_page:
                application_page = next(
                    (
                        page
                        for page in companion_page.context.pages
                        if page != companion_page
                        and page.url.startswith(("http://", "https://"))
                    ),
                    None,
                )
            if application_page is not None and companion_page is not None:
                break
            time.sleep(0.1)
        if application_page is None:
            context = browser.contexts[0]
            application_page = next(iter(context.pages), None)
            if application_page is None:
                raise AssistedBrowserError(
                    "The isolated Edge window has no page to navigate."
                )
            application_page.goto(application_url, wait_until="domcontentloaded")
        if companion_page is None:
            context = application_page.context
            with context.expect_page() as page_info:
                application_page.evaluate(
                    "(url) => window.open(url, '_blank')",
                    companion_url,
                )
            companion_page = page_info.value
            companion_page.wait_for_load_state("domcontentloaded")
        application = _target_record(application_page)
        companion = _target_record(companion_page)
        return {
            "applicationTargetId": application["targetId"],
            "companionTargetId": companion["targetId"],
        }
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Could not open the Workday application and companion pages."
        ) from exc
    finally:
        playwright.stop()


def _navigate_application(
    session: dict[str, Any],
    application_url: str,
) -> dict[str, Any]:
    """Navigate only the session-owned application target to a precomputed surface."""
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted application pane is no longer open."
            )
        expected_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                record = _target_record(page)
                if record["targetId"] == expected_id:
                    page.goto(application_url, wait_until="domcontentloaded")
                    return {"applicationTargetId": expected_id}
        raise AssistedBrowserError(
            "The assisted application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Could not navigate the assisted application pane."
        ) from exc
    finally:
        playwright.stop()


def _authorize_collection_operation(
    root: Path,
    operation: str,
    *,
    mode: str = "navigate-and-capture",
) -> dict[str, Any]:
    """Bind a human-approved worksheet operation to the current application target and mode."""
    try:
        definition = _COLLECTION_OPERATION_DEFINITIONS[operation]
    except KeyError as exc:
        raise AssistedBrowserError("Unsupported collection operation.") from exc
    session = _load_session(root)
    target_url = definition["url"]
    if session.get("browserMode") == _VSCODE_BROWSER_MODE:
        return {
            "operation": operation,
            "mode": mode,
            "status": "authorized",
            "worksheetRow": definition["worksheetRow"],
            "worksheetField": definition["worksheetField"],
            "targetUrl": target_url,
            "sharedBrowserRequired": True,
            "authorizedAt": _now_iso(),
        }
    if target_url is not None:
        target = _navigate_application(session, str(target_url))
    else:
        sync_playwright, playwright_error = _playwright()
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.connect_over_cdp(
                _require_edge_browser(session)
            )
            targets = _find_targets(browser, session)
            if targets.application is None or not str(
                targets.application.get("url") or ""
            ).startswith("https://entra.microsoft.com/"):
                raise AssistedBrowserError(
                    "The assisted Entra application pane is no longer open."
                )
            target = {
                "applicationTargetId": targets.application["targetId"]
            }
        except playwright_error as exc:
            raise AssistedBrowserError(
                "Could not authorize reads on the current Entra pane."
            ) from exc
        finally:
            playwright.stop()
    session.update(
        {
            **target,
            "surface": "entra-configuration",
            **(
                {"applicationUrl": target_url}
                if target_url is not None
                else {}
            ),
        }
    )
    _write_json(_session_path(root), session)
    return {
        "operation": operation,
        "mode": mode,
        "status": (
            "navigated" if mode == "navigate-only" else "authorized"
        ),
        "worksheetRow": definition["worksheetRow"],
        "worksheetField": definition["worksheetField"],
        "authorizedAt": _now_iso(),
    }


def _inspect_authorized_selector(
    root: Path,
    *,
    operation: str,
    selector: str,
    limit: int,
    navigation_only: bool = False,
) -> dict[str, Any]:
    """Collect bounded, sanitized, visible selector evidence from the authorized application page."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                record = _target_record(page)
                if record["targetId"] != expected_target_id:
                    continue
                matches = []
                frames = []
                for frame_index, frame in enumerate(page.frames):
                    frame_result = {
                        "index": frame_index,
                        "name": frame.name,
                        "url": sanitize_browser_url(frame.url),
                        "matchCount": 0,
                    }
                    try:
                        locator = frame.locator(selector)
                        frame_result["matchCount"] = locator.count()
                        for match_index in range(frame_result["matchCount"]):
                            if len(matches) >= limit:
                                break
                            match = locator.nth(match_index)
                            if not match.is_visible(timeout=500):
                                continue
                            evidence = match.evaluate(
                                """(element) => {
                                    const clean = (value) => (value || "")
                                        .replace(/\\s+/g, " ")
                                        .replace(/[\\uE000-\\uF8FF]/g, "")
                                        .trim();
                                    return {
                                        tag: element.tagName.toLowerCase(),
                                        role: element.getAttribute("role"),
                                        text: clean(
                                            element.innerText || element.textContent
                                        ).slice(0, 300),
                                        parentText: clean(
                                            element.parentElement?.innerText
                                        ).slice(0, 500),
                                        ariaLabel: element.getAttribute("aria-label"),
                                        title: element.getAttribute("title")
                                    };
                                }"""
                            )
                            sanitized = {
                                key: sanitize_browser_evidence_text(value)
                                for key, value in evidence.items()
                            }
                            if (
                                "[REDACTED_ACCOUNT_CONTEXT]"
                                in sanitized.values()
                            ):
                                continue
                            matches.append(
                                {
                                    "frameIndex": frame_index,
                                    "matchIndex": match_index,
                                    **sanitized,
                                }
                            )
                            if len(matches) >= limit:
                                break
                    except playwright_error as exc:
                        frame_result["errorType"] = type(exc).__name__
                        frame_result["error"] = str(exc)[:300]
                    frames.append(frame_result)
                    if len(matches) >= limit:
                        break
                return {
                    "operation": operation,
                    "selector": selector,
                    "limit": limit,
                    "pageUrl": sanitize_browser_url(page.url),
                    "frames": frames,
                    "matches": matches,
                    "inspectedAt": _now_iso(),
                    "truncated": len(matches) >= limit,
                    "navigationOnly": navigation_only,
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    finally:
        playwright.stop()


def validate_navigation_url(base_url: str, href: str) -> str:
    """Resolve inspected links while requiring a secure absolute destination."""
    destination = urljoin(base_url, href)
    parsed = urlparse(destination)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AssistedBrowserError(
            "Authorized navigation requires an absolute HTTPS destination."
        )
    return destination


def _follow_authorized_link(
    root: Path,
    *,
    operation: str,
    selector: str,
    frame_index: int,
    match_index: int,
) -> dict[str, Any]:
    """Follow one inspected visible link and return sanitized navigation evidence."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                record = _target_record(page)
                if record["targetId"] != expected_target_id:
                    continue
                if frame_index >= len(page.frames):
                    raise AssistedBrowserError(
                        "The inspected Entra frame is no longer available."
                    )
                frame = page.frames[frame_index]
                locator = frame.locator(selector)
                if match_index >= locator.count():
                    raise AssistedBrowserError(
                        "The inspected Entra link is no longer available."
                    )
                link = locator.nth(match_index)
                if not link.is_visible(timeout=500):
                    raise AssistedBrowserError(
                        "The inspected Entra link is no longer visible."
                    )
                link_evidence = link.evaluate(
                    """(element) => ({
                        tag: element.tagName.toLowerCase(),
                        href: element.getAttribute("href"),
                        text: (
                            element.innerText || element.textContent || ""
                        ).replace(/\\s+/g, " ").trim()
                    })"""
                )
                if link_evidence.get("tag") != "a" or not link_evidence.get(
                    "href"
                ):
                    raise AssistedBrowserError(
                        "Authorized navigation requires a visible link."
                    )
                destination = validate_navigation_url(
                    frame.url or page.url,
                    str(link_evidence["href"]),
                )
                link.click()
                page.wait_for_timeout(1500)
                return {
                    "operation": operation,
                    "followedText": sanitize_browser_evidence_text(
                        link_evidence.get("text")
                    ),
                    "pageUrl": sanitize_browser_url(page.url),
                    "validatedDestination": sanitize_browser_url(destination),
                    "navigatedAt": _now_iso(),
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not follow the authorized Entra link."
        ) from exc
    finally:
        playwright.stop()


def _capture_authorized_element(
    root: Path,
    *,
    operation: str,
    selector: str,
    frame_index: int,
    match_index: int,
) -> tuple[bytes, dict[str, Any]]:
    """Capture a bounded contextual crop around one inspected visible target."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                record = _target_record(page)
                if record["targetId"] != expected_target_id:
                    continue
                if frame_index >= len(page.frames):
                    raise AssistedBrowserError(
                        "The inspected Entra frame is no longer available."
                    )
                frame = page.frames[frame_index]
                locator = frame.locator(selector)
                if match_index >= locator.count():
                    raise AssistedBrowserError(
                        "The inspected Entra control is no longer available."
                    )
                target = locator.nth(match_index)
                if not target.is_visible(timeout=500):
                    raise AssistedBrowserError(
                        "The inspected Entra control is no longer visible."
                    )
                box = target.bounding_box()
                if box is None:
                    raise AssistedBrowserError(
                        "The inspected Entra control has no visible bounds."
                    )
                viewport = page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                left = max(0.0, box["x"] - 180.0)
                top = max(0.0, box["y"] - 110.0)
                right = min(
                    float(viewport["width"]),
                    box["x"] + box["width"] + 180.0,
                )
                bottom = min(
                    float(viewport["height"]),
                    box["y"] + box["height"] + 110.0,
                )
                content = page.screenshot(
                    type="png",
                    clip={
                        "x": left,
                        "y": top,
                        "width": max(1.0, right - left),
                        "height": max(1.0, bottom - top),
                    },
                )
                evidence = target.evaluate(
                    """(element) => ({
                        text: (element.innerText || element.textContent || "")
                            .replace(/\\s+/g, " ")
                            .trim(),
                        ariaLabel: element.getAttribute("aria-label"),
                        title: element.getAttribute("title")
                    })"""
                )
                label = next(
                    (
                        sanitize_browser_evidence_text(evidence.get(key))
                        for key in ("ariaLabel", "title", "text")
                        if evidence.get(key)
                    ),
                    "Inspected portal control",
                )
                return content, {
                    "label": label,
                    "capturedAt": _now_iso(),
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not capture the inspected Entra control."
        ) from exc
    finally:
        playwright.stop()


def _fill_navigation_search(
    root: Path,
    *,
    operation: str,
    selector: str,
    frame_index: int,
    match_index: int,
    value: Any,
) -> dict[str, Any]:
    """Fill only an inspected search control without submitting or choosing a result."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    search_value = validate_search_value(value)
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                record = _target_record(page)
                if record["targetId"] != expected_target_id:
                    continue
                if frame_index >= len(page.frames):
                    raise AssistedBrowserError(
                        "The inspected Entra frame is no longer available."
                    )
                frame = page.frames[frame_index]
                locator = frame.locator(selector)
                if match_index >= locator.count():
                    raise AssistedBrowserError(
                        "The inspected search input is no longer available."
                    )
                search = locator.nth(match_index)
                if not search.is_visible(timeout=500):
                    raise AssistedBrowserError(
                        "The inspected search input is no longer visible."
                    )
                evidence = search.evaluate(
                    """(element) => ({
                        tag: element.tagName.toLowerCase(),
                        type: element.getAttribute("type"),
                        role: element.getAttribute("role"),
                        ariaLabel: element.getAttribute("aria-label"),
                        placeholder: element.getAttribute("placeholder"),
                        title: element.getAttribute("title")
                    })"""
                )
                validate_search_control(evidence)
                search.fill(search_value)
                page.wait_for_timeout(500)
                return {
                    "operation": operation,
                    "value": sanitize_browser_evidence_text(search_value),
                    "filledAt": _now_iso(),
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not fill the inspected Entra search input."
        ) from exc
    finally:
        playwright.stop()


def target_pointer_position(
    box: Mapping[str, Any],
    viewport_height: float,
) -> dict[str, Any]:
    """Map application viewport geometry into a stable companion-rail position."""
    if viewport_height <= 0:
        raise AssistedBrowserError(
            "Application viewport height must be positive."
        )
    center = float(box["y"]) + float(box["height"]) / 2.0
    ratio = min(max(center / viewport_height, 0.05), 0.95)
    centered = abs(center - viewport_height / 2.0) <= max(
        24.0,
        float(box["height"]) / 2.0,
    )
    return {
        "positionRatio": round(ratio, 4),
        "centered": centered,
    }


def validate_reveal_control(
    operation: str,
    evidence: Mapping[str, Any],
) -> str:
    """Constrain reveal navigation to a visibly named Edit button for a supported row."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    label = next(
        (
            str(evidence.get(key) or "").strip()
            for key in ("ariaLabel", "title", "text")
            if str(evidence.get(key) or "").strip()
        ),
        "",
    )
    role = str(evidence.get("role") or "").casefold()
    tag = str(evidence.get("tag") or "").casefold()
    if role != "button" and tag != "button":
        raise AssistedBrowserError(
            "Reveal navigation requires an inspected Edit button."
        )
    if not label.casefold().startswith("edit "):
        raise AssistedBrowserError(
            "Reveal navigation requires an Edit control named by the row instructions."
        )
    return label


def _inspect_reveal_control(
    root: Path,
    *,
    operation: str,
    selector: str,
    frame_index: int,
    match_index: int,
) -> dict[str, Any]:
    """Revalidate the exact visible Edit control before the reveal action is offered."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                if _target_record(page)["targetId"] != expected_target_id:
                    continue
                if frame_index >= len(page.frames):
                    raise AssistedBrowserError(
                        "The inspected Entra frame is no longer available."
                    )
                locator = page.frames[frame_index].locator(selector)
                if match_index >= locator.count():
                    raise AssistedBrowserError(
                        "The inspected Edit control is no longer available."
                    )
                control = locator.nth(match_index)
                if not control.is_visible(timeout=500):
                    raise AssistedBrowserError(
                        "The inspected Edit control is no longer visible."
                    )
                evidence = control.evaluate(
                    """(element) => ({
                        tag: element.tagName.toLowerCase(),
                        role: element.getAttribute("role"),
                        text: (element.innerText || element.textContent || "")
                            .replace(/\\s+/g, " ")
                            .trim(),
                        ariaLabel: element.getAttribute("aria-label"),
                        title: element.getAttribute("title")
                    })"""
                )
                label = validate_reveal_control(operation, evidence)
                return {
                    **evidence,
                    "label": label,
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not inspect the Entra Edit control."
        ) from exc
    finally:
        playwright.stop()


def _reveal_authorized_values(
    root: Path,
    *,
    operation: str,
    selector: str,
    frame_index: int,
    match_index: int,
) -> dict[str, Any]:
    """Activate the disclosed reveal-only Edit control without saving or confirming changes."""
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                if _target_record(page)["targetId"] != expected_target_id:
                    continue
                if frame_index >= len(page.frames):
                    raise AssistedBrowserError(
                        "The inspected Entra frame is no longer available."
                    )
                control = page.frames[frame_index].locator(selector).nth(
                    match_index
                )
                evidence = control.evaluate(
                    """(element) => ({
                        tag: element.tagName.toLowerCase(),
                        role: element.getAttribute("role"),
                        text: (element.innerText || element.textContent || "")
                            .replace(/\\s+/g, " ")
                            .trim(),
                        ariaLabel: element.getAttribute("aria-label"),
                        title: element.getAttribute("title")
                    })"""
                )
                label = validate_reveal_control(operation, evidence)
                control.click()
                page.wait_for_timeout(750)
                return {
                    "operation": operation,
                    "control": label,
                    "revealedAt": _now_iso(),
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not activate the allowed Entra Edit control."
        ) from exc
    finally:
        playwright.stop()


def _position_authorized_target(
    root: Path,
    *,
    operation: str,
    selector: str,
    frame_index: int,
    match_index: int,
) -> dict[str, Any]:
    """Scroll one authorized target into view and derive its rail-guidance metadata."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                record = _target_record(page)
                if record["targetId"] != expected_target_id:
                    continue
                if frame_index >= len(page.frames):
                    raise AssistedBrowserError(
                        "The inspected Entra frame is no longer available."
                    )
                frame = page.frames[frame_index]
                locator = frame.locator(selector)
                if match_index >= locator.count():
                    raise AssistedBrowserError(
                        "The inspected Entra target is no longer available."
                    )
                target = locator.nth(match_index)
                if not target.is_visible(timeout=500):
                    raise AssistedBrowserError(
                        "The inspected Entra target is no longer visible."
                    )
                reduced_motion = bool(
                    page.evaluate(
                        "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
                    )
                )
                target.evaluate(
                    """(element, behavior) => element.scrollIntoView({
                        block: "center",
                        inline: "nearest",
                        behavior
                    })""",
                    "auto" if reduced_motion else "smooth",
                )
                page.wait_for_timeout(50 if reduced_motion else 450)
                box = target.bounding_box()
                if box is None:
                    raise AssistedBrowserError(
                        "The inspected Entra target has no visible bounds."
                    )
                viewport_height = float(
                    page.evaluate("() => window.innerHeight")
                )
                position = target_pointer_position(box, viewport_height)
                evidence = target.evaluate(
                    """(element) => ({
                        text: (element.innerText || element.textContent || "")
                            .replace(/\\s+/g, " ")
                            .trim(),
                        ariaLabel: element.getAttribute("aria-label"),
                        title: element.getAttribute("title"),
                        placeholder: element.getAttribute("placeholder")
                    })"""
                )
                label = next(
                    (
                        sanitize_browser_evidence_text(evidence.get(key))
                        for key in ("ariaLabel", "title", "placeholder", "text")
                        if evidence.get(key)
                    ),
                    "the visible target",
                )
                return {
                    **position,
                    "label": label,
                    "positionedAt": _now_iso(),
                }
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not position the inspected Entra target."
        ) from exc
    finally:
        playwright.stop()


def _position_authorized_targets(
    root: Path,
    *,
    operation: str,
    target_specs: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Center related targets together and produce coherent rail positions."""
    if operation not in _COLLECTION_OPERATIONS:
        raise AssistedBrowserError("Unsupported collection operation.")
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            _require_edge_browser(session)
        )
        targets = _find_targets(browser, session)
        if targets.application is None:
            raise AssistedBrowserError(
                "The assisted Entra application pane is no longer open."
            )
        expected_target_id = targets.application["targetId"]
        for context in browser.contexts:
            for page in context.pages:
                if _target_record(page)["targetId"] != expected_target_id:
                    continue
                resolved = []
                for index, target_spec in enumerate(target_specs):
                    frame_index = int(target_spec["frameIndex"])
                    match_index = int(target_spec["matchIndex"])
                    if frame_index >= len(page.frames):
                        raise AssistedBrowserError(
                            f"Application target {index + 1} frame is unavailable."
                        )
                    target = page.frames[frame_index].locator(
                        str(target_spec["selector"])
                    ).nth(match_index)
                    if not target.is_visible(timeout=500):
                        raise AssistedBrowserError(
                            f"Application target {index + 1} is not visible."
                        )
                    box = target.bounding_box()
                    if box is None:
                        raise AssistedBrowserError(
                            f"Application target {index + 1} has no visible bounds."
                        )
                    resolved.append((target_spec, target, box))
                viewport_height = float(
                    page.evaluate("() => window.innerHeight")
                )
                first_top = min(float(item[2]["y"]) for item in resolved)
                last_bottom = max(
                    float(item[2]["y"]) + float(item[2]["height"])
                    for item in resolved
                )
                reduced_motion = bool(
                    page.evaluate(
                        "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
                    )
                )
                page.evaluate(
                    """([top, bottom, viewportHeight, behavior]) => {
                        window.scrollBy({
                            top: (top + bottom) / 2 - viewportHeight / 2,
                            left: 0,
                            behavior
                        });
                    }""",
                    [
                        first_top,
                        last_bottom,
                        viewport_height,
                        "auto" if reduced_motion else "smooth",
                    ],
                )
                page.wait_for_timeout(50 if reduced_motion else 450)
                metadata = []
                for index, (target_spec, target, _box) in enumerate(resolved):
                    box = target.bounding_box()
                    if box is None:
                        raise AssistedBrowserError(
                            f"Application target {index + 1} has no visible bounds."
                        )
                    evidence = target.evaluate(
                        """(element) => ({
                            text: (element.innerText || element.textContent || "")
                                .replace(/\\s+/g, " ")
                                .trim(),
                            ariaLabel: element.getAttribute("aria-label"),
                            title: element.getAttribute("title"),
                            placeholder: element.getAttribute("placeholder")
                        })"""
                    )
                    label = target_spec.get("label") or next(
                        (
                            sanitize_browser_evidence_text(evidence.get(key))
                            for key in (
                                "ariaLabel",
                                "title",
                                "placeholder",
                                "text",
                            )
                            if evidence.get(key)
                        ),
                        f"application target {index + 1}",
                    )
                    metadata.append(
                        {
                            **target_pointer_position(box, viewport_height),
                            "label": label,
                            "positionedAt": _now_iso(),
                        }
                    )
                return metadata
        raise AssistedBrowserError(
            "The assisted Entra application pane is no longer open."
        )
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Playwright could not position the application targets."
        ) from exc
    finally:
        playwright.stop()


def _stop_server_after_failed_start(
    root: Path,
    session: Mapping[str, Any],
    server_started: bool,
) -> str | None:
    """Roll back browser and server resources created by an unsuccessful start."""
    errors = []
    try:
        _close_owned_browser(session)
    except AssistedBrowserError as exc:
        errors.append(str(exc))
    if errors:
        return "; ".join(errors)
    if server_started:
        try:
            _api_request(session, "/api/stop", value={})
        except AssistedBrowserError as exc:
            errors.append(str(exc))
        else:
            try:
                _session_path(root).unlink(missing_ok=True)
            except OSError as exc:
                errors.append(
                    f"Companion stopped, but session cleanup failed: {exc}"
                )
    return "; ".join(errors) or None


def _start(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Establish or reuse the session-owned server and isolated browser pages for a named surface."""
    application_url = surface_url(root, args.surface)
    if args.vscode:
        if args.launch or args.attach_existing:
            raise AssistedBrowserError(
                "--vscode cannot be combined with --launch or "
                "--attach-existing."
            )
        session, server_started = _start_server(
            root,
            None,
            _VSCODE_BROWSER_MODE,
        )
        session.update(
            {
                "surface": args.surface,
                "applicationUrl": application_url,
                "browserMode": _VSCODE_BROWSER_MODE,
            }
        )
        _write_json(_session_path(root), session)
        return {
            "started": True,
            "serverStarted": server_started,
            "browserLaunched": False,
            "surface": args.surface,
            "browserMode": _VSCODE_BROWSER_MODE,
            "applicationUrl": application_url,
            "manualBrowserRequired": True,
            "shareWithAgentRequired": True,
        }

    _parse_cdp_endpoint(args.cdp)
    session, server_started = _start_server(
        root,
        args.cdp,
        _EDGE_BROWSER_MODE,
    )
    browser_launched = False
    try:
        if not is_cdp_up(args.cdp):
            if not args.launch:
                raise AssistedBrowserError(
                    "No isolated Edge browser is listening on this CDP endpoint. "
                    "Start with --launch or use the endpoint of this session's "
                    "isolated browser."
                )
            profile = root / ".local/connect/workday-da/edge-profile"
            profile.mkdir(parents=True, exist_ok=True)
            _host, port = _parse_cdp_endpoint(args.cdp)
            process = launch_browser(
                start_url=application_url,
                debug_port=port,
                user_data_dir=str(profile),
                additional_urls=(
                    f"http://127.0.0.1:{int(session['port'])}/"
                    f"#token={session['token']}",
                ),
            )
            if not is_cdp_up(args.cdp):
                raise AssistedBrowserError(
                    "Edge started but its CDP endpoint did not become ready."
                )
            browser_launched = True
            session["browserPid"] = process.pid
        elif server_started and not args.attach_existing:
            raise AssistedBrowserError(
                "The requested CDP endpoint was already in use by a browser that "
                "does not belong to this assisted session. Choose another port or "
                "pass --attach-existing after verifying the browser."
            )

        if (
            not server_started
            and not browser_launched
            and session.get("companionTargetId")
        ):
            target = _navigate_application(session, application_url)
            targets = {
                **target,
                "companionTargetId": session["companionTargetId"],
            }
        else:
            targets = _open_initial_pages(
                session,
                application_url,
                pages_launched=browser_launched,
            )
    except (AssistedBrowserError, OSError, RuntimeError) as exc:
        cleanup_error = _stop_server_after_failed_start(
            root,
            session,
            server_started,
        )
        if cleanup_error:
            raise AssistedBrowserError(
                f"{exc} Cleanup also failed: {cleanup_error}"
            ) from exc
        raise
    session.update(
        {
            **targets,
            "surface": args.surface,
            "applicationUrl": application_url,
            "cdpEndpoint": args.cdp,
            "browserMode": _EDGE_BROWSER_MODE,
        }
    )
    _write_json(_session_path(root), session)
    return {
        "started": True,
        "serverStarted": server_started,
        "browserLaunched": browser_launched,
        "surface": args.surface,
        "browserMode": _EDGE_BROWSER_MODE,
        "cdpEndpoint": args.cdp,
        "manualPairingRequired": True,
    }


def _open(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Retarget the existing session-owned application pane without rebuilding the companion."""
    session = _load_session(root)
    if not _session_is_alive(session):
        raise AssistedBrowserError(
            "The assisted-browser companion is no longer running."
        )
    application_url = surface_url(root, args.surface)
    if session.get("browserMode") == _VSCODE_BROWSER_MODE:
        session.update(
            {
                "surface": args.surface,
                "applicationUrl": application_url,
            }
        )
        _write_json(_session_path(root), session)
        return {
            "opened": True,
            "surface": args.surface,
            "applicationUrl": application_url,
            "manualBrowserRequired": True,
            "shareWithAgentRequired": True,
        }
    target = _navigate_application(session, application_url)
    session.update(
        {
            **target,
            "surface": args.surface,
            "applicationUrl": application_url,
        }
    )
    _write_json(_session_path(root), session)
    return {
        "opened": True,
        "surface": args.surface,
        "manualPairingRequired": False,
    }


def _present(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Validate a view locally before publishing it as the next companion revision."""
    session = _load_session(root)
    if str(args.view_file) == "-":
        raw = json.load(sys.stdin)
    else:
        raw = json.loads(
            Path(args.view_file).read_text(encoding="utf-8")
        )
    normalized = validate_view(raw)
    result = _api_request(session, "/api/present", value=normalized)
    return {"presented": True, **result}


def _worksheet_collection_view(operation: str) -> dict[str, Any]:
    """Build the canonical action view for one unresolved worksheet row."""
    definition = _COLLECTION_OPERATION_DEFINITIONS[operation]
    hints = _ENTRA_NAVIGATION_HINTS[operation]
    worksheet_row = definition["worksheetRow"]
    worksheet_rows = definition.get("worksheetRows", [worksheet_row])
    combined_overview = len(worksheet_rows) > 1
    capture_instruction = entra_capture_instruction(worksheet_row)
    accepted_values = capture_instruction.get("acceptedValues", [])
    portal_path = hints["portalPath"]
    actions = [
        {
            "label": "Navigate only",
            "operation": operation,
            "mode": "navigate-only",
            "disclaimer": (
                f"Navigate toward {' and '.join(worksheet_rows)} without "
                "collecting their application values. You remain responsible "
                "for sign-in and "
                "all portal changes."
            ),
        }
    ]
    if not definition["sensitive"]:
        actions.append(
            {
                "label": "Navigate and capture",
                "operation": operation,
                "mode": "navigate-and-capture",
                "disclaimer": (
                    f"Navigate toward {' and '.join(worksheet_rows)} and "
                    "inspect only the visible non-sensitive worksheet values. "
                    "You remain "
                    "responsible for sign-in and all portal changes."
                ),
            }
        )
    return {
        "schemaVersion": 1,
        "phase": "Microsoft Entra",
        "title": (
            (
                "Collect Enterprise application overview"
                if operation
                == "entra-enterprise-application-display-name"
                else "Collect SAML signing and certificate expiration"
            )
            if combined_overview
            else f"Review {worksheet_row}"
            if accepted_values
            else f"Collect {worksheet_row}"
        ),
        "status": "waiting",
        "summary": (
            definition["combinedSummary"]
            if combined_overview
            else
            capture_instruction["instruction"]
            if accepted_values
            else (
                f"Locate and verify {worksheet_row} for the Microsoft Entra "
                "worksheet."
            )
        ),
        "steps": [
            f"Open {portal_path}.",
            *(
                list(definition["combinedSteps"])
                if combined_overview
                else [capture_instruction["instruction"]]
            ),
            "Choose how the browser companion should assist with this row.",
        ],
        "fields": [
            {
                "label": "Portal location",
                "value": portal_path,
            }
        ],
        "waitingFor": (
            "Choose Navigate only or Navigate and capture in the browser "
            "companion."
        ),
        "actions": actions,
    }


def _worksheet_confirmation_view(
    operation: str,
    *,
    value: str,
    target_label: str,
) -> dict[str, Any]:
    """Build the canonical review interaction for one worksheet row."""
    if operation == "entra-enterprise-application-display-name":
        try:
            values = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AssistedBrowserError(
                "The Enterprise application overview result must be JSON."
            ) from exc
        if not isinstance(values, Mapping) or set(values) != {
            "Enterprise application",
            "Application ID",
        }:
            raise AssistedBrowserError(
                "The Enterprise application overview result must contain "
                "Enterprise application and Application ID."
            )
        enterprise_application = _required_text(
            values.get("Enterprise application"),
            "Enterprise application",
            maximum=500,
        )
        application_id = _required_text(
            values.get("Application ID"),
            "Application ID",
            maximum=500,
        )
        return {
            "schemaVersion": 1,
            "phase": "Microsoft Entra",
            "title": "Confirm Enterprise application overview",
            "status": "waiting",
            "summary": (
                "Confirm the two values detected on the Enterprise "
                "application Overview page."
            ),
            "steps": [],
            "fields": [
                {
                    "label": "Detected Enterprise application",
                    "value": enterprise_application,
                },
                {
                    "label": "Detected Application ID",
                    "value": application_id,
                },
            ],
            "waitingFor": (
                "Confirm whether to record both values in the worksheet."
            ),
            "confirmation": {
                "operation": operation,
                "prompt": (
                    "Record this Enterprise application name and Application "
                    "ID in their separate worksheet rows?"
                ),
                "confirmLabel": "Record both worksheet values",
                "rejectLabel": "Search again",
            },
            "visualHelp": {
                "operation": operation,
                "label": target_label,
            },
        }
    if operation == "entra-saml-signing-option":
        try:
            values = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AssistedBrowserError(
                "The SAML signing result must be JSON."
            ) from exc
        if not isinstance(values, Mapping) or set(values) != {
            "SAML signing",
            "Certificate expiration date (active certificate row)",
        }:
            raise AssistedBrowserError(
                "The SAML signing result must contain the signing option and "
                "certificate expiration."
            )
        signing_option = _required_text(
            values.get("SAML signing"),
            "SAML signing",
            maximum=500,
        )
        expiration = _required_text(
            values.get(
                "Certificate expiration date (active certificate row)"
            ),
            "Certificate expiration date",
            maximum=500,
        )
        return {
            "schemaVersion": 1,
            "phase": "Microsoft Entra",
            "title": "Confirm SAML signing and certificate expiration",
            "status": "waiting",
            "summary": (
                "Confirm the signing option and active certificate "
                "expiration detected on the SAML page."
            ),
            "steps": [],
            "fields": [
                {
                    "label": "Detected SAML signing",
                    "value": signing_option,
                },
                {
                    "label": "Detected certificate expiration",
                    "value": expiration,
                },
            ],
            "waitingFor": (
                "Confirm whether to record both values in the worksheet."
            ),
            "confirmation": {
                "operation": operation,
                "prompt": (
                    "Record this SAML signing option and certificate "
                    "expiration in their separate worksheet rows?"
                ),
                "confirmLabel": "Record both worksheet values",
                "rejectLabel": "Review again",
            },
            "visualHelp": {
                "operation": operation,
                "label": target_label,
            },
        }
    worksheet_row = _COLLECTION_OPERATION_DEFINITIONS[operation][
        "worksheetRow"
    ]
    capture_instruction = entra_capture_instruction(worksheet_row)
    accepted_values = capture_instruction.get("acceptedValues", [])
    visual_help = {
        "operation": operation,
        "label": target_label,
    }
    if accepted_values:
        fields = [
            {
                "label": "Observed evidence",
                "value": value,
            }
        ]
        if len(accepted_values) == 1:
            fields.append(
                {
                    "label": "Worksheet response",
                    "value": accepted_values[0],
                }
            )
            return {
                "schemaVersion": 1,
                "phase": "Microsoft Entra",
                "title": f"Confirm {worksheet_row}",
                "status": "waiting",
                "summary": capture_instruction["instruction"],
                "steps": [capture_instruction["instruction"]],
                "fields": fields,
                "waitingFor": (
                    "Confirm the canonical worksheet response after reviewing "
                    "the visible Microsoft Entra evidence."
                ),
                "confirmation": {
                    "operation": operation,
                    "prompt": capture_instruction["instruction"],
                    "confirmLabel": "Confirm and record",
                    "rejectLabel": "Review again",
                },
                "visualHelp": visual_help,
            }
        return {
            "schemaVersion": 1,
            "phase": "Microsoft Entra",
            "title": f"Choose {worksheet_row}",
            "status": "waiting",
            "summary": capture_instruction["instruction"],
            "steps": [capture_instruction["instruction"]],
            "fields": fields,
            "waitingFor": "Choose the canonical worksheet response.",
            "entry": {
                "operation": operation,
                "label": "Worksheet response",
                "options": accepted_values,
            },
            "visualHelp": visual_help,
        }
    return {
        "schemaVersion": 1,
        "phase": "Microsoft Entra",
        "title": f"Confirm {worksheet_row}",
        "status": "waiting",
        "summary": (
            f"Confirm the detected {worksheet_row} value before recording it."
        ),
        "steps": [],
        "fields": [
            {
                "label": f"Detected {worksheet_row}",
                "value": value,
            }
        ],
        "waitingFor": (
            "Confirm whether to record this value in the worksheet."
        ),
        "confirmation": {
            "operation": operation,
            "prompt": (
                f"This is the value detected for {worksheet_row}. "
                "Record it in the worksheet?"
            ),
            "confirmLabel": "Record worksheet value",
            "rejectLabel": "Search again",
        },
        "visualHelp": {
            "operation": operation,
            "label": target_label,
        },
    }


def _worksheet_entry_view(operation: str) -> dict[str, Any]:
    """Build the canonical manual-entry fallback after Navigate only."""
    definition = _COLLECTION_OPERATION_DEFINITIONS[operation]
    worksheet_row = definition["worksheetRow"]
    capture_instruction = entra_capture_instruction(worksheet_row)
    accepted_values = capture_instruction.get("acceptedValues", [])
    portal_path = _ENTRA_NAVIGATION_HINTS[operation]["portalPath"]
    if operation == "entra-enterprise-application-display-name":
        return {
            "schemaVersion": 1,
            "phase": "Microsoft Entra",
            "title": "Enter Enterprise application overview",
            "status": "waiting",
            "summary": (
                "Enter the Enterprise application name and Application ID "
                "shown on the same Overview page."
            ),
            "steps": [
                f"Review {portal_path}.",
                (
                    "Enter the read-only Name field as Enterprise "
                    "application."
                ),
                (
                    "Enter the read-only Application ID field as Application "
                    "ID."
                ),
            ],
            "fields": [
                {
                    "label": "Portal location",
                    "value": portal_path,
                }
            ],
            "waitingFor": (
                "Enter both Overview values, then submit them together."
            ),
            "entry": {
                "operation": operation,
                "label": "Enterprise application Overview values",
                "inputs": [
                    {
                        "key": "Enterprise application",
                        "label": "Enterprise application",
                        "placeholder": "Enter the read-only Name field",
                    },
                    {
                        "key": "Application ID",
                        "label": "Application ID",
                        "placeholder": (
                            "00000000-0000-0000-0000-000000000000"
                        ),
                    },
                ],
                "submitLabel": "Record both worksheet values",
            },
        }
    if operation == "entra-saml-signing-option":
        return {
            "schemaVersion": 1,
            "phase": "Microsoft Entra",
            "title": "Enter SAML signing and certificate expiration",
            "status": "waiting",
            "summary": (
                "Enter the selected signing option and active certificate "
                "expiration shown on the SAML page."
            ),
            "steps": [
                f"Review {portal_path}.",
                "Enter the selected SAML signing option.",
                "Enter the active certificate expiration date.",
            ],
            "fields": [
                {
                    "label": "Portal location",
                    "value": portal_path,
                }
            ],
            "waitingFor": (
                "Enter both SAML values, then submit them together."
            ),
            "entry": {
                "operation": operation,
                "label": "SAML signing values",
                "inputs": [
                    {
                        "key": "SAML signing",
                        "label": "SAML signing",
                        "placeholder": "Enter the selected signing option",
                    },
                    {
                        "key": (
                            "Certificate expiration date "
                            "(active certificate row)"
                        ),
                        "label": "Certificate expiration date",
                        "placeholder": "Enter the active expiration date",
                    },
                ],
                "submitLabel": "Record both worksheet values",
            },
        }
    if accepted_values:
        fields = [
            {
                "label": "Portal location",
                "value": portal_path,
            }
        ]
        if len(accepted_values) == 1:
            fields.append(
                {
                    "label": "Worksheet response",
                    "value": accepted_values[0],
                }
            )
            return {
                "schemaVersion": 1,
                "phase": "Microsoft Entra",
                "title": f"Confirm {worksheet_row}",
                "status": "waiting",
                "summary": capture_instruction["instruction"],
                "steps": [
                    f"Review {portal_path}.",
                    capture_instruction["instruction"],
                ],
                "fields": fields,
                "waitingFor": (
                    "Confirm the canonical worksheet response after reviewing "
                    "the Microsoft Entra configuration."
                ),
                "confirmation": {
                    "operation": operation,
                    "prompt": capture_instruction["instruction"],
                    "confirmLabel": "Confirm and record",
                    "rejectLabel": "Review again",
                },
            }
        return {
            "schemaVersion": 1,
            "phase": "Microsoft Entra",
            "title": f"Choose {worksheet_row}",
            "status": "waiting",
            "summary": capture_instruction["instruction"],
            "steps": [
                f"Review {portal_path}.",
                capture_instruction["instruction"],
            ],
            "fields": fields,
            "waitingFor": "Choose the canonical worksheet response.",
            "entry": {
                "operation": operation,
                "label": "Worksheet response",
                "options": accepted_values,
            },
        }
    return {
        "schemaVersion": 1,
        "phase": "Microsoft Entra",
        "title": f"Enter {worksheet_row}",
        "status": "waiting",
        "summary": capture_instruction["instruction"],
        "steps": [
            f"Review {portal_path}.",
            capture_instruction["instruction"],
        ],
        "fields": [
            {
                "label": "Portal location",
                "value": portal_path,
            }
        ],
        "waitingFor": (
            f"Enter the {worksheet_row} value described in What to do."
        ),
        "entry": {
            "operation": operation,
            "label": worksheet_row,
            "placeholder": f"Enter {worksheet_row}",
            "submitLabel": "Record worksheet value",
        },
    }


def _worksheet_summary_view(root: Path) -> dict[str, Any]:
    """Build the final 13-row review with the required preservation choices."""
    draft = _load_worksheet_draft(root)
    missing_rows = [
        _COLLECTION_OPERATION_DEFINITIONS[operation]["worksheetRow"]
        for operation in _WORKSHEET_OPERATION_ORDER
        if _COLLECTION_OPERATION_DEFINITIONS[operation]["worksheetRow"]
        not in draft
    ]
    if missing_rows:
        raise AssistedBrowserError(
            "The final worksheet summary requires all interactive rows: "
            + ", ".join(missing_rows)
        )
    accepted_values = entra_capture_instruction(
        _PRESERVATION_WORKSHEET_ROW
    ).get("acceptedValues", [])
    if len(accepted_values) != 2:
        raise AssistedBrowserError(
            "The Existing configuration contract must define two outcomes."
        )
    return {
        "schemaVersion": 1,
        "phase": "Microsoft Entra",
        "title": "Review final Microsoft Entra worksheet",
        "status": "waiting",
        "summary": (
            "Review the 13 collected worksheet values, then choose how "
            "unrelated scopes, authorized clients, and permissions were "
            "preserved."
        ),
        "steps": [
            "Confirm each displayed value reflects the completed setup.",
            (
                "Choose whether existing configuration was preserved without "
                "changes or remediated without replacing unrelated settings."
            ),
        ],
        "fields": [
            {
                "label": _COLLECTION_OPERATION_DEFINITIONS[operation][
                    "worksheetRow"
                ],
                "value": draft[
                    _COLLECTION_OPERATION_DEFINITIONS[operation][
                        "worksheetRow"
                    ]
                ],
            }
            for operation in _WORKSHEET_OPERATION_ORDER
        ],
        "waitingFor": (
            "Choose the Existing configuration outcome to complete the worksheet."
        ),
        "entry": {
            "operation": _PRESERVATION_OPERATION,
            "label": _PRESERVATION_WORKSHEET_ROW,
            "options": accepted_values,
        },
    }


def _worksheet_present(
    args: argparse.Namespace,
    root: Path,
) -> dict[str, Any]:
    """Build and publish one canonical worksheet interaction."""
    session = _load_session(root)
    if session.get("surface") != "entra-configuration":
        raise AssistedBrowserError(
            "worksheet-present requires the entra-configuration companion surface."
        )
    if args.operation == _PRESERVATION_OPERATION:
        if args.stage != "summary":
            raise AssistedBrowserError(
                "Existing configuration is available only on the final summary."
            )
        if args.value_file is not None or args.target_label is not None:
            raise AssistedBrowserError(
                "Summary presentation does not accept candidate value arguments."
            )
        view = _worksheet_summary_view(root)
        normalized = validate_view(view)
        result = _api_request(session, "/api/present", value=normalized)
        return {
            "presented": True,
            "operation": args.operation,
            "interaction": "entry",
            **result,
        }
    if args.stage == "summary":
        raise AssistedBrowserError(
            "Summary presentation requires the Existing configuration operation."
        )
    if (
        args.stage != "collection"
        and session.get("browserMode") == _VSCODE_BROWSER_MODE
    ):
        live = _api_request(session, "/api/status")
        collection = live.get("collection")
        if (
            not isinstance(collection, Mapping)
            or collection.get("operation") != args.operation
            or collection.get("status") != "navigated"
        ):
            raise AssistedBrowserError(
                "The row interaction is available only after browser navigation "
                "completes for the same worksheet row. Report completion with "
                f"`shared-browser-result --operation {args.operation} "
                "--status navigated`, then retry the presentation."
            )
    if args.stage == "collection":
        draft = _load_worksheet_draft(root)
        expected_operation = next(
            (
                operation
                for operation in _WORKSHEET_OPERATION_ORDER
                if _COLLECTION_OPERATION_DEFINITIONS[operation][
                    "worksheetRow"
                ]
                not in draft
            ),
            None,
        )
        if args.operation != expected_operation:
            raise AssistedBrowserError(
                "Collection presentation must target the first unresolved "
                "worksheet row."
            )
        if args.value_file is not None or args.target_label is not None:
            raise AssistedBrowserError(
                "Collection presentation does not accept candidate value arguments."
            )
        view = _worksheet_collection_view(args.operation)
        interaction = "collection"
    elif args.stage == "confirmation":
        if args.value_file is None or args.target_label is None:
            raise AssistedBrowserError(
                "Confirmation presentation requires --value-file and --target-label."
            )
        try:
            raw_value = (
                sys.stdin.read()
                if str(args.value_file) == "-"
                else args.value_file.read_text(encoding="utf-8")
            )
        except OSError as exc:
            raise AssistedBrowserError(
                "The worksheet candidate value file is unreadable."
            ) from exc
        view = _worksheet_confirmation_view(
            args.operation,
            value=_required_text(
                raw_value.strip(),
                "worksheet candidate value",
                maximum=500,
            ),
            target_label=_required_text(
                args.target_label,
                "target label",
                maximum=120,
            ),
        )
        interaction = (
            "confirmation" if "confirmation" in view else "entry"
        )
    else:
        if args.value_file is not None or args.target_label is not None:
            raise AssistedBrowserError(
                "Entry presentation does not accept candidate value arguments."
            )
        view = _worksheet_entry_view(args.operation)
        interaction = (
            "confirmation" if "confirmation" in view else "entry"
        )
    normalized = validate_view(view)
    result = _api_request(session, "/api/present", value=normalized)
    return {
        "presented": True,
        "operation": args.operation,
        "interaction": interaction,
        **result,
    }


def _load_worksheet_draft(root: Path) -> dict[str, str]:
    """Load the existing session-owned worksheet draft without exposing its values."""
    path = root.resolve() / WORKSHEET_DRAFT_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise AssistedBrowserError(
            "The Entra companion worksheet draft is unreadable."
        ) from exc
    if not isinstance(raw, Mapping):
        raise AssistedBrowserError(
            "The Entra companion worksheet draft must be a JSON object."
        )
    known_rows = set(ENTRA_WORKSHEET_LABELS)
    normalized_rows = {
        row: ENTRA_WORKSHEET_LABEL_ALIASES.get(row, row) for row in raw
    }
    unknown_rows = {
        row for row, normalized in normalized_rows.items() if normalized not in known_rows
    }
    if unknown_rows:
        raise AssistedBrowserError(
            "The Entra companion worksheet draft contains unsupported rows: "
            + ", ".join(sorted(unknown_rows))
        )
    if len(set(normalized_rows.values())) != len(normalized_rows):
        raise AssistedBrowserError(
            "The Entra companion worksheet draft contains duplicate row aliases."
        )
    return {
        normalized_rows[row]: _required_text(
            value,
            f"worksheet draft value for {row}",
            maximum=4000,
        )
        for row, value in raw.items()
    }


def _load_entra_controller_projection(root: Path) -> dict[str, Any]:
    """Read only the Entra lifecycle fields needed by companion orchestration."""
    try:
        raw = WorkdayConnectStore(root).load()
    except WorkdayConnectStoreError as exc:
        raise AssistedBrowserError(
            "Connect Workday state is unreadable."
        ) from exc
    phases = raw.get("phases") if isinstance(raw, Mapping) else None
    entra = phases.get("entra") if isinstance(phases, Mapping) else None
    if not isinstance(entra, Mapping):
        raise AssistedBrowserError(
            "Connect Workday state does not contain the Entra phase."
        )
    administrator = entra.get("administrator")
    return {
        "phase": "entra",
        "status": _required_text(
            entra.get("status"),
            "Entra phase status",
            maximum=40,
        ),
        "administratorSubstage": (
            _required_text(
                administrator.get("substage"),
                "Entra administrator substage",
                maximum=80,
            )
            if isinstance(administrator, Mapping)
            and administrator.get("substage") is not None
            else None
        ),
        "updatedAt": entra.get("updatedAt"),
    }


def _current_view_operation(status: Mapping[str, Any]) -> str | None:
    """Resolve the operation named by the current primary interaction."""
    view = status.get("view")
    if not isinstance(view, Mapping):
        return None
    for key in ("confirmation", "entry", "visualHelp", "action"):
        interaction = view.get(key)
        if isinstance(interaction, Mapping):
            operation = interaction.get("operation")
            if isinstance(operation, str):
                return operation
    actions = view.get("actions")
    if isinstance(actions, list) and actions:
        operation = actions[0].get("operation")
        if isinstance(operation, str):
            return operation
    return None


def _worksheet_stage(
    status: Mapping[str, Any],
    operation: str,
) -> tuple[str, str | None]:
    """Classify the current row stage from revision-bound interaction state."""
    confirmation = status.get("confirmation")
    if (
        isinstance(confirmation, Mapping)
        and confirmation.get("operation") == operation
    ):
        confirmation_status = confirmation.get("status")
        stages = {
            "waiting": "awaiting-confirmation",
            "confirmed": "candidate-confirmed",
            "rejected": "candidate-rejected",
        }
        if confirmation_status not in stages:
            raise AssistedBrowserError(
                "The companion confirmation state is unsupported."
            )
        return stages[confirmation_status], "confirmation"
    entry = status.get("entry")
    if isinstance(entry, Mapping) and entry.get("operation") == operation:
        entry_status = entry.get("status")
        stages = {
            "waiting": "awaiting-entry",
            "submitted": "entry-submitted",
        }
        if entry_status not in stages:
            raise AssistedBrowserError(
                "The companion entry state is unsupported."
            )
        return stages[entry_status], "entry"
    collection = status.get("collection")
    if (
        isinstance(collection, Mapping)
        and collection.get("operation") == operation
    ):
        collection_status = collection.get("status")
        stages = {
            "collecting": "authorizing",
            "authorized": "authorized",
            "navigated": "navigation-complete",
            "failed": "navigation-failed",
        }
        if collection_status not in stages:
            raise AssistedBrowserError(
                "The companion collection state is unsupported."
            )
        return stages[collection_status], "collection"
    return "awaiting-action", "action"


def _worksheet_row_contract(operation: str) -> dict[str, Any]:
    """Project one compact row contract without exposing worksheet values."""
    definition = _COLLECTION_OPERATION_DEFINITIONS[operation]
    hints = _ENTRA_NAVIGATION_HINTS[operation]
    return {
        "operation": operation,
        "worksheetRow": definition["worksheetRow"],
        "sensitive": definition["sensitive"],
        "navigationHints": {
            "startUrl": definition["url"],
            "portalPath": hints["portalPath"],
            **(
                {"lastKnownUrlTemplate": hints["lastKnownUrlTemplate"]}
                if hints.get("lastKnownUrlTemplate")
                else {}
            ),
            **(
                {"baselineScript": hints["baselineScript"]}
                if hints.get("baselineScript")
                else {}
            ),
            **(
                {"baselineSupportsNavigateOnly": True}
                if hints.get("baselineScript")
                else {}
            ),
            "observedHints": list(hints["observedHints"]),
            "fallbackHints": list(hints["fallbackHints"]),
        },
    }


def _worksheet_status(
    _args: argparse.Namespace,
    root: Path,
) -> dict[str, Any]:
    """Project existing worksheet authorities into one compact orchestration result."""
    session = _load_session(root)
    if session.get("surface") != "entra-configuration":
        raise AssistedBrowserError(
            "worksheet-status requires the entra-configuration companion surface."
        )
    live = _api_request(session, "/api/view")
    draft = _load_worksheet_draft(root)
    controller = _load_entra_controller_projection(root)
    recorded_rows = [
        operation
        for operation in _WORKSHEET_OPERATION_ORDER
        if _COLLECTION_OPERATION_DEFINITIONS[operation]["worksheetRow"] in draft
    ]
    next_operation = next(
        (
            operation
            for operation in _WORKSHEET_OPERATION_ORDER
            if operation not in recorded_rows
        ),
        None,
    )
    operation = _current_view_operation(live)
    active_row = None
    final_review = None
    preservation_attestation = None
    if operation == _FINAL_WORKSHEET_CONFIRMATION_OPERATION:
        stage, interaction = _worksheet_stage(live, operation)
        final_review = {
            "stage": stage,
            "pendingInteraction": interaction,
            "viewRevision": live.get("revision"),
        }
    elif operation == _PRESERVATION_OPERATION:
        stage, interaction = _worksheet_stage(live, operation)
        preservation_attestation = {
            "stage": stage,
            "pendingInteraction": interaction,
            "recorded": _PRESERVATION_WORKSHEET_ROW in draft,
            "viewRevision": live.get("revision"),
        }
    elif operation is not None:
        definition = _COLLECTION_OPERATION_DEFINITIONS.get(operation)
        if definition is None:
            raise AssistedBrowserError(
                "The current companion operation is not a worksheet row."
            )
        stage, interaction = _worksheet_stage(live, operation)
        collection = live.get("collection")
        collection_status = (
            collection.get("status")
            if isinstance(collection, Mapping)
            and collection.get("operation") == operation
            else None
        )
        visual_help = live.get("visualHelp")
        target_pointers = live.get("targetPointers")
        target_pointers_status = live.get("targetPointersStatus")
        active_row = {
            **_worksheet_row_contract(operation),
            "stage": stage,
            "pendingInteraction": interaction,
            "viewRevision": live.get("revision"),
            "mode": (
                collection.get("mode")
                if isinstance(collection, Mapping)
                and collection.get("operation") == operation
                else None
            ),
            "authorized": collection_status in {"authorized", "navigated"},
            "recorded": definition["worksheetRow"] in draft,
            "targetPointed": (
                isinstance(target_pointers, list)
                and bool(target_pointers)
                and all(
                    isinstance(pointer, Mapping)
                    and pointer.get("operation") == operation
                    for pointer in target_pointers
                )
            ),
            "visualHelpStatus": (
                visual_help.get("status")
                if isinstance(visual_help, Mapping)
                and visual_help.get("operation") == operation
                else None
            ),
            "targetPointersStatus": (
                target_pointers_status.get("status")
                if isinstance(target_pointers_status, Mapping)
                and target_pointers_status.get("operation") == operation
                else None
            ),
        }
    next_row = (
        _worksheet_row_contract(next_operation)
        if next_operation is not None
        and (
            active_row is None
            or active_row["operation"] != next_operation
        )
        else None
    )
    return {
        "schemaVersion": 1,
        "surface": session.get("surface"),
        "browserMode": session.get("browserMode", _EDGE_BROWSER_MODE),
        "controller": controller,
        "worksheet": {
            "requiredCount": len(_WORKSHEET_OPERATION_ORDER),
            "recordedCount": len(recorded_rows),
            "complete": len(recorded_rows) == len(_WORKSHEET_OPERATION_ORDER),
            "submissionReady": (
                len(recorded_rows) == len(_WORKSHEET_OPERATION_ORDER)
                and _PRESERVATION_WORKSHEET_ROW in draft
            ),
            "recordedRows": recorded_rows,
            "nextOperation": next_operation,
            "nextRow": next_row,
        },
        "activeRow": active_row,
        "finalReview": final_review,
        "preservationAttestation": preservation_attestation,
    }


def _worksheet_reset(
    _args: argparse.Namespace,
    root: Path,
) -> dict[str, Any]:
    """Reset only Entra worksheet collection state and preserve lifecycle state."""
    session = _load_session(root)
    if session.get("surface") != "entra-configuration":
        raise AssistedBrowserError(
            "worksheet-reset requires the entra-configuration companion surface."
        )
    reset_result = _api_request(session, "/api/reset", value={})
    draft_path = root.resolve() / WORKSHEET_DRAFT_PATH
    draft_cleared = draft_path.exists()
    try:
        draft_path.unlink(missing_ok=True)
    except OSError as exc:
        raise AssistedBrowserError(
            "The Entra companion worksheet draft could not be cleared."
        ) from exc
    status = _worksheet_status(argparse.Namespace(), root)
    return {
        "reset": True,
        "draftCleared": draft_cleared,
        "companion": reset_result,
        "status": status,
    }


def _status(_args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Combine persisted session identity with live companion state for orchestration decisions."""
    session = _load_session(root)
    result = _api_request(session, "/api/status")
    return {
        "running": True,
        "surface": session.get("surface"),
        "browserMode": session.get("browserMode", _EDGE_BROWSER_MODE),
        **(
            {"cdpEndpoint": session["cdpEndpoint"]}
            if session.get("cdpEndpoint")
            else {}
        ),
        **result,
    }


def _interaction_completed_after_publication(
    status: Mapping[str, Any],
    *,
    operation: str,
    interaction: str,
    revision: int,
) -> dict[str, Any] | None:
    """Recognize only terminal interaction results for the requested operation and revision."""
    if status.get("revision") != revision:
        return None
    status_key = "visualHelp" if interaction == "visual-help" else interaction
    current = status.get(status_key)
    if not isinstance(current, Mapping) or current.get("operation") != operation:
        return None
    current_status = current.get("status")
    if interaction == "collection":
        if current_status not in {"authorized", "navigated", "failed"}:
            return None
        event_at = (
            current.get("authorizedAt")
            or current.get("failedAt")
            or current.get("startedAt")
        )
        published_at = status.get("publishedAt")
        if not isinstance(event_at, str) or not isinstance(published_at, str):
            return None
        try:
            if datetime.fromisoformat(event_at) < datetime.fromisoformat(
                published_at
            ):
                return None
        except ValueError:
            return None
    elif interaction == "confirmation":
        if (
            current.get("revision") != revision
            or current_status not in {"confirmed", "rejected"}
        ):
            return None
    elif interaction == "entry":
        if (
            current.get("revision") != revision
            or current_status != "submitted"
        ):
            return None
    elif interaction == "visual-help":
        if (
            current.get("revision") != revision
            or current_status != "requested"
        ):
            return None
    else:
        raise AssistedBrowserError("Unsupported companion interaction.")
    return dict(current)


def _wait(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Bridge browser interactions back to the caller while rejecting stale revisions and bounding wait time."""
    if args.timeout < 1 or args.timeout > 600:
        raise AssistedBrowserError(
            "Wait timeout must be from 1 through 600 seconds."
        )
    session = _load_session(root)
    started = time.monotonic()
    deadline = started + args.timeout
    latest: dict[str, Any] | None = None
    while True:
        latest = _api_request(session, "/api/status")
        if latest.get("revision") != args.revision:
            raise AssistedBrowserError(
                "Companion guidance changed while waiting for the "
                "administrator response."
            )
        interactions = (
            ("visual-help", "confirmation", "entry", "collection")
            if args.interaction == "any"
            else (args.interaction,)
        )
        for interaction in interactions:
            completed = _interaction_completed_after_publication(
                latest,
                operation=args.operation,
                interaction=interaction,
                revision=args.revision,
            )
            if completed is not None:
                return {
                    "completed": True,
                    "interaction": interaction,
                    "operation": args.operation,
                    "result": completed,
                    "revision": args.revision,
                    "waitedSeconds": round(time.monotonic() - started, 3),
                }
        if time.monotonic() >= deadline:
            return {
                "completed": False,
                "interaction": args.interaction,
                "operation": args.operation,
                "revision": args.revision,
                "timedOut": True,
                "waitedSeconds": round(time.monotonic() - started, 3),
            }
        time.sleep(0.25)


def _inspect(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Forward a bounded selector inspection through the authenticated companion API."""
    session = _load_session(root)
    return _api_request(
        session,
        "/api/inspect",
        value={
            "operation": args.operation,
            "selector": args.selector,
            "limit": args.limit,
        },
        timeout=30.0,
    )


def _follow(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Forward one inspected-link navigation through the authenticated companion API."""
    session = _load_session(root)
    return _api_request(
        session,
        "/api/follow",
        value={
            "operation": args.operation,
            "selector": args.selector,
            "frameIndex": args.frame_index,
            "matchIndex": args.match_index,
        },
        timeout=30.0,
    )


def _capture(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Request a contextual screenshot for one inspected target."""
    session = _load_session(root)
    if session.get("browserMode") == _VSCODE_BROWSER_MODE:
        if args.image_file is None or not args.label:
            raise AssistedBrowserError(
                "VS Code capture requires --image-file and --label."
            )
        if any(
            value is not None
            for value in (
                args.selector,
                args.frame_index,
                args.match_index,
            )
        ):
            raise AssistedBrowserError(
                "VS Code capture does not accept selector or match arguments."
            )
        try:
            content = args.image_file.read_bytes()
        except OSError as exc:
            raise AssistedBrowserError(
                "Shared browser capture could not be read."
            ) from exc
        decode_shared_browser_capture(base64.b64encode(content).decode("ascii"))
        return _api_request(
            session,
            "/api/capture",
            value={
                "operation": args.operation,
                "imageBase64": base64.b64encode(content).decode("ascii"),
                "label": args.label,
            },
            timeout=30.0,
        )
    if args.selector is None or args.frame_index is None or args.match_index is None:
        raise AssistedBrowserError(
            "Edge capture requires selector, frame index, and match index."
        )
    if args.image_file is not None or args.label is not None:
        raise AssistedBrowserError(
            "Edge capture does not accept shared browser image arguments."
        )
    return _api_request(
        session,
        "/api/capture",
        value={
            "operation": args.operation,
            "selector": args.selector,
            "frameIndex": args.frame_index,
            "matchIndex": args.match_index,
            "append": args.append,
        },
        timeout=30.0,
    )


def _screenshot_result(
    args: argparse.Namespace,
    root: Path,
) -> dict[str, Any]:
    """Report a safe screenshot failure for a requested visual-help operation."""
    session = _load_session(root)
    return _api_request(
        session,
        "/api/visual-help-result",
        value={
            "operation": args.operation,
            "status": args.status,
            "error": args.error,
        },
        timeout=30.0,
    )


def _fill_search(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Request bounded text entry into one inspected search or filter control."""
    session = _load_session(root)
    return _api_request(
        session,
        "/api/fill-search",
        value={
            "operation": args.operation,
            "selector": args.selector,
            "frameIndex": args.frame_index,
            "matchIndex": args.match_index,
            "value": args.value,
        },
        timeout=30.0,
    )


def _point(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Request companion-rail guidance for one inspected target."""
    session = _load_session(root)
    return _api_request(
        session,
        "/api/point",
        value={
            "operation": args.operation,
            "revision": args.revision,
            "selector": args.selector,
            "frameIndex": args.frame_index,
            "matchIndex": args.match_index,
        },
        timeout=30.0,
    )


def _point_targets(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Load a target set and request atomic multi-target rail guidance."""
    value: dict[str, Any] = {
        "operation": args.operation,
        "revision": args.revision,
    }
    if args.error is not None:
        value["error"] = args.error
    elif str(args.targets_file) == "-":
        value["targets"] = json.load(sys.stdin)
    else:
        value["targets"] = json.loads(
            Path(args.targets_file).read_text(encoding="utf-8")
        )
    session = _load_session(root)
    return _api_request(
        session,
        "/api/point-targets",
        value=value,
        timeout=30.0,
    )


def _reveal(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Request activation of one inspected and disclosed reveal-only Edit control."""
    session = _load_session(root)
    return _api_request(
        session,
        "/api/reveal",
        value={
            "operation": args.operation,
            "selector": args.selector,
            "frameIndex": args.frame_index,
            "matchIndex": args.match_index,
        },
        timeout=30.0,
    )


def _shared_browser_result(
    args: argparse.Namespace,
    root: Path,
) -> dict[str, Any]:
    """Record whether the authorized shared-browser operation reached its intended page state."""
    session = _load_session(root)
    value = {
        "operation": args.operation,
        "status": args.status,
    }
    if args.error:
        value["error"] = args.error
    return _api_request(
        session,
        "/api/shared-browser-result",
        value=value,
    )


def _inspect_layout(_args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Report whether session-owned pages are visibly arranged for side-by-side assistance."""
    session = _load_session(root)
    cdp_endpoint = _require_edge_browser(session)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        targets = _find_targets(browser, session)
        classification = classify_layout(
            targets.application,
            targets.companion,
        )
        return {
            **classification,
            "surface": session.get("surface"),
            "application": targets.application,
            "companion": targets.companion,
        }
    except playwright_error as exc:
        raise AssistedBrowserError(
            "Could not inspect the assisted-browser layout."
        ) from exc
    finally:
        playwright.stop()


def _close_owned_browser(session: Mapping[str, Any]) -> bool:
    """Terminate only the browser process launched and recorded by this helper session."""
    pid = session.get("browserPid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise AssistedBrowserError(
            "Could not close the helper-owned Edge browser."
        ) from exc
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not is_cdp_up(str(session["cdpEndpoint"])):
            return True
        time.sleep(0.2)
    raise AssistedBrowserError(
        "The helper-owned Edge browser did not close; session metadata was "
        "preserved so cleanup can be retried."
    )


def _stop(_args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Stop the companion server, close owned Edge, and preserve attached user-owned browsers."""
    session = _load_session(root)
    browser_closed = _close_owned_browser(session)
    _api_request(session, "/api/stop", value={})
    _session_path(root).unlink(missing_ok=True)
    return {
        "stopped": True,
        "browserClosed": browser_closed,
        "attachedBrowserLeftOpen": not browser_closed,
    }


def _redact_error_text(value: str, root: Path) -> str:
    """Remove session tokens and secret-like URL parameters before emitting CLI errors."""
    redacted = value
    path = _session_path(root)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            token = raw.get("token") if isinstance(raw, Mapping) else None
            if isinstance(token, str) and token:
                redacted = redacted.replace(token, "[REDACTED]")
        except (OSError, json.JSONDecodeError):
            pass
    return re.sub(
        r"(?i)\b(code|token|secret|password)=([^&\s]+)",
        r"\1=[REDACTED]",
        redacted,
    )


def build_parser() -> argparse.ArgumentParser:
    """Define the fixed command and argument surface for assisted-browser capabilities."""
    parser = argparse.ArgumentParser(
        description="Guide native DA Workday browser handoffs in VS Code."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root containing .local state.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--surface", choices=_SURFACES, required=True)
    start.add_argument("--cdp", default=DEFAULT_CDP)
    start.add_argument("--launch", action="store_true")
    start.add_argument("--attach-existing", action="store_true")
    start.add_argument("--vscode", action="store_true")

    open_surface = commands.add_parser("open")
    open_surface.add_argument("--surface", choices=_SURFACES, required=True)

    present = commands.add_parser("present")
    present.add_argument("--view-file", type=Path, required=True)

    commands.add_parser("status")
    commands.add_parser("worksheet-status")
    commands.add_parser("worksheet-reset")
    worksheet_present = commands.add_parser("worksheet-present")
    worksheet_present.add_argument(
        "--operation",
        choices=sorted(_PRESENT_OPERATIONS),
        required=True,
    )
    worksheet_present.add_argument(
        "--stage",
        choices=("collection", "confirmation", "entry", "summary"),
        required=True,
    )
    worksheet_present.add_argument("--value-file", type=Path)
    worksheet_present.add_argument("--target-label")
    wait = commands.add_parser("wait")
    wait.add_argument(
        "--operation",
        choices=sorted(_WAIT_OPERATIONS),
        required=True,
    )
    wait.add_argument(
        "--interaction",
        choices=("any", "collection", "confirmation", "entry", "visual-help"),
        required=True,
    )
    wait.add_argument("--revision", type=int, required=True)
    wait.add_argument("--timeout", type=float, default=600)
    inspect = commands.add_parser("inspect")
    inspect.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    inspect.add_argument("--selector", required=True)
    inspect.add_argument("--limit", type=int, default=20)
    follow = commands.add_parser("follow")
    follow.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    follow.add_argument("--selector", required=True)
    follow.add_argument("--frame-index", type=int, required=True)
    follow.add_argument("--match-index", type=int, required=True)
    for command in ("capture", "screenshot"):
        capture = commands.add_parser(command)
        capture.add_argument(
            "--operation",
            choices=sorted(_COLLECTION_OPERATIONS),
            required=True,
        )
        capture.add_argument("--selector")
        capture.add_argument("--frame-index", type=int)
        capture.add_argument("--match-index", type=int)
        capture.add_argument("--image-file", type=Path)
        capture.add_argument("--label")
        capture.add_argument("--append", action="store_true")
    screenshot_result = commands.add_parser("screenshot-result")
    screenshot_result.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    screenshot_result.add_argument("--status", choices=("failed",), required=True)
    screenshot_result.add_argument("--error", required=True)
    fill_search = commands.add_parser("fill-search")
    fill_search.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    fill_search.add_argument("--selector", required=True)
    fill_search.add_argument("--frame-index", type=int, required=True)
    fill_search.add_argument("--match-index", type=int, required=True)
    fill_search.add_argument("--value", required=True)
    point = commands.add_parser("point")
    point.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    point.add_argument("--selector", required=True)
    point.add_argument("--revision", type=int, required=True)
    point.add_argument("--frame-index", type=int, required=True)
    point.add_argument("--match-index", type=int, required=True)
    point.add_argument("--append", action="store_true")
    point_targets = commands.add_parser("point-targets")
    point_targets.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    point_targets.add_argument("--revision", type=int, required=True)
    point_targets_payload = point_targets.add_mutually_exclusive_group(
        required=True
    )
    point_targets_payload.add_argument("--targets-file", type=Path)
    point_targets_payload.add_argument("--error")
    reveal = commands.add_parser("reveal")
    reveal.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    reveal.add_argument("--selector", required=True)
    reveal.add_argument("--frame-index", type=int, required=True)
    reveal.add_argument("--match-index", type=int, required=True)
    shared_result = commands.add_parser("shared-browser-result")
    shared_result.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    shared_result.add_argument(
        "--status",
        choices=("navigated", "failed"),
        required=True,
    )
    shared_result.add_argument("--error")
    commands.add_parser("inspect-layout")
    commands.add_parser("stop")
    commands.add_parser("_serve", help=argparse.SUPPRESS)
    return parser


_HANDLERS = {
    "start": _start,
    "open": _open,
    "present": _present,
    "status": _status,
    "worksheet-status": _worksheet_status,
    "worksheet-reset": _worksheet_reset,
    "worksheet-present": _worksheet_present,
    "wait": _wait,
    "inspect": _inspect,
    "follow": _follow,
    "capture": _capture,
    "screenshot": _capture,
    "screenshot-result": _screenshot_result,
    "fill-search": _fill_search,
    "point": _point,
    "point-targets": _point_targets,
    "reveal": _reveal,
    "shared-browser-result": _shared_browser_result,
    "inspect-layout": _inspect_layout,
    "stop": _stop,
}


def main() -> None:
    """Dispatch one CLI command and emit one machine-readable success or redacted error record."""
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "_serve":
            _serve(root)
            return
        handler = _HANDLERS[args.command]
        result = handler(args, root)
        print(RESULT_MARKER + json.dumps(result, sort_keys=True))
    except (
        AssistedBrowserError,
        json.JSONDecodeError,
        OSError,
        socket.error,
    ) as exc:
        cause = exc.__cause__
        print(
            ERROR_MARKER
            + json.dumps(
                {
                    "operation": args.command,
                    "error": _redact_error_text(str(exc), root),
                    "errorType": type(exc).__name__,
                    **(
                        {
                            "causeType": type(cause).__name__,
                            "cause": _redact_error_text(str(cause), root),
                        }
                        if cause is not None
                        else {}
                    ),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
