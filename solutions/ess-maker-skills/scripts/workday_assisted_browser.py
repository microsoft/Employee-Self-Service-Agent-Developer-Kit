# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Run the ephemeral split-screen companion for native DA Workday setup.

The helper owns browser preparation, a constrained local guidance page, and
read-only layout evidence. The maker owns every portal mutation, sign-in,
consent, and Test-pane interaction. Workday lifecycle state remains exclusively
owned by workday_connect.py.
"""

from __future__ import annotations

import argparse
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
from workday_connect_store import WorkdayConnectStore


RESULT_MARKER = "WORKDAY_ASSIST_RESULT_JSON="
ERROR_MARKER = "WORKDAY_ASSIST_ERROR_JSON="
DEFAULT_CDP = "http://localhost:9237"
SESSION_PATH = Path(".local/connect/workday-da/assisted-browser.json")
ASSET_ROOT = Path(__file__).with_name("workday_assisted_browser_assets")
_TOKEN_ENV = "ESS_WORKDAY_ASSIST_TOKEN"
_MAX_BODY_BYTES = 64 * 1024
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
}
_COLLECTION_OPERATION_DEFINITIONS = {
    "entra-directory-display-name": {
        "url": _ENTRA_OVERVIEW_URL,
        "worksheetRow": "Directory name",
        "worksheetField": "selectedDirectoryDisplayName",
    },
    "entra-enterprise-application-display-name": {
        "url": _ENTRA_ENTERPRISE_APPLICATIONS_URL,
        "worksheetRow": "Enterprise application",
        "worksheetField": "applicationDisplayName",
    },
    "entra-application-id": {
        "url": None,
        "worksheetRow": "Application ID",
        "worksheetField": "applicationId",
    },
    "entra-reply-url": {
        "url": None,
        "worksheetRow": "Selected Reply URL",
        "worksheetField": "replyUrl",
    },
    "entra-name-id-source": {
        "url": None,
        "worksheetRow": "NameID source",
        "worksheetField": "nameIdSource",
    },
    "entra-saml-signing-option": {
        "url": None,
        "worksheetRow": "SAML signing",
        "worksheetField": "samlSigningOption",
    },
    "entra-certificate-thumbprint": {
        "url": _ENTRA_ENTERPRISE_APPLICATIONS_URL,
        "worksheetRow": "Certificate thumbprint (active certificate row)",
        "worksheetField": "certificateThumbprint",
    },
    "entra-certificate-expiration": {
        "url": None,
        "worksheetRow": (
            "Certificate expiration date (active certificate row)"
        ),
        "worksheetField": "certificateValidTo",
    },
    "entra-saml-configuration": {
        "url": None,
        "worksheetRow": "SAML configuration",
        "worksheetField": "entraChecks.samlMode",
    },
    "entra-signing-certificate-check": {
        "url": None,
        "worksheetRow": "Signing certificate",
        "worksheetField": "entraChecks.signingCertificate",
    },
    "entra-authorized-connector": {
        "url": None,
        "worksheetRow": "Authorized connector",
        "worksheetField": "entraChecks.connectorPreauthorized",
    },
    "entra-permissions-consent": {
        "url": None,
        "worksheetRow": "Permissions and consent",
        "worksheetField": (
            "entraChecks.graphDelegatedPermissions,entraChecks.adminConsent"
        ),
    },
    "entra-employee-assignment": {
        "url": None,
        "worksheetRow": "Employee assignment",
        "worksheetField": "entraChecks.userAssignment",
    },
    "entra-existing-configuration": {
        "url": None,
        "worksheetRow": "Existing configuration",
        "worksheetField": (
            "entraChecks.existingScopesPreserved,"
            "entraChecks.authorizedClientsPreserved,"
            "entraChecks.permissionsPreserved"
        ),
    },
}
_COLLECTION_OPERATIONS = set(_COLLECTION_OPERATION_DEFINITIONS)
_FINAL_WORKSHEET_CONFIRMATION_OPERATION = "entra-final-worksheet"
_CONFIRMATION_OPERATIONS = _COLLECTION_OPERATIONS | {
    _FINAL_WORKSHEET_CONFIRMATION_OPERATION
}
_WAIT_OPERATIONS = _CONFIRMATION_OPERATIONS
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
        if operation not in _COLLECTION_OPERATIONS:
            raise AssistedBrowserError(
                "entry.operation is not a supported collection operation."
            )
        normalized["entry"] = {
            "operation": operation,
            "label": _required_text(
                entry_raw.get("label"),
                "entry.label",
                maximum=120,
            ),
            "placeholder": _required_text(
                entry_raw.get("placeholder"),
                "entry.placeholder",
                maximum=160,
            ),
            "submitLabel": _required_text(
                entry_raw.get("submitLabel"),
                "entry.submitLabel",
                maximum=80,
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
        self._evidence_image: bytes | None = None
        self._evidence_image_metadata: dict[str, Any] | None = None
        self._target_pointers: list[dict[str, Any]] = []

    def publish(self, view: Any) -> dict[str, Any]:
        """Advance the displayed revision while preserving only same-operation authorization and visual context."""
        normalized = validate_view(view)
        with self._lock:
            previous_collection = self._collection
            previous_image = self._evidence_image
            previous_image_metadata = self._evidence_image_metadata
            previous_target_pointers = self._target_pointers
            entry = normalized.get("entry")
            if isinstance(entry, Mapping) and (
                previous_collection is None
                or previous_collection.get("status") != "navigated"
                or previous_collection.get("operation") != entry["operation"]
            ):
                raise AssistedBrowserError(
                    "Manual entry is available only after Navigate only "
                    "completes for the same worksheet row."
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
            return {
                "revision": self._revision,
                "publishedAt": self._published_at,
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
                "evidenceImage": self._evidence_image_metadata,
                "targetPointer": (
                    self._target_pointers[-1]
                    if self._target_pointers
                    else None
                ),
                "targetPointers": list(self._target_pointers),
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
            return dict(self._confirmation)

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
            self._evidence_image = content
            self._evidence_image_metadata = {
                "id": secrets.token_urlsafe(12),
                "operation": operation,
                **metadata,
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
            pointer = {
                "id": secrets.token_urlsafe(12),
                "operation": operation,
                **metadata,
            }
            if append:
                self._target_pointers.append(pointer)
            else:
                self._target_pointers = [pointer]
            return dict(pointer)

    def set_target_pointers(
        self,
        *,
        operation: str,
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
            self._target_pointers = [
                {
                    "id": secrets.token_urlsafe(12),
                    "operation": operation,
                    **item,
                }
                for item in metadata
            ]
            return [dict(pointer) for pointer in self._target_pointers]

    def clear_target_pointer(self, *, operation: str) -> None:
        """Discard stale target positions after navigation changes page geometry."""
        with self._lock:
            if any(
                pointer.get("operation") == operation
                for pointer in self._target_pointers
            ):
                self._target_pointers = []

    def submit_entry(
        self,
        *,
        revision: int,
        operation: str,
        value: str,
    ) -> dict[str, Any]:
        """Accept a bounded manual fallback only after navigate-only assistance for the current row."""
        normalized_value = _required_text(
            value,
            "entry value",
            maximum=500,
        )
        if "\n" in normalized_value or "\r" in normalized_value:
            raise AssistedBrowserError(
                "Manual worksheet entry must be a single line."
            )
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
            if (
                self._collection is None
                or self._collection.get("status") != "navigated"
                or self._collection.get("operation") != operation
            ):
                raise AssistedBrowserError(
                    "Manual entry requires a completed Navigate only "
                    "operation for this row."
                )
            self._entry = {
                "operation": operation,
                "status": "submitted",
                "revision": revision,
                "value": normalized_value,
                "submittedAt": _now_iso(),
            }
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
                "evidenceImage": self._evidence_image_metadata,
                "targetPointer": (
                    self._target_pointers[-1]
                    if self._target_pointers
                    else None
                ),
                "targetPointers": list(self._target_pointers),
            }


class _Server(ThreadingHTTPServer):
    """Carry authenticated companion state and browser-session context on the loopback HTTP server."""
    token: str
    companion_state: CompanionState
    root: Path
    cdp_endpoint: str


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

    def _read_json(self) -> Any:
        """Read a bounded UTF-8 JSON body to prevent memory abuse and validation bypass."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AssistedBrowserError("Invalid Content-Length.") from exc
        if length <= 0 or length > _MAX_BODY_BYTES:
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
                if set(raw) != {"operation", "revision", "value"}:
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
                if not isinstance(value, str):
                    raise AssistedBrowserError(
                        "Manual entry value must be text."
                    )
                result = self.server.companion_state.submit_entry(
                    revision=revision,
                    operation=operation,
                    value=value,
                )
                self._send_json(200, {"entry": result})
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
                raw = self._read_json()
                if not isinstance(raw, Mapping):
                    raise AssistedBrowserError(
                        "Screenshot request must be a JSON object."
                    )
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
                if not isinstance(frame_index, int) or frame_index < 0:
                    raise AssistedBrowserError(
                        "Target pointer frameIndex must be a non-negative integer."
                    )
                if not isinstance(match_index, int) or match_index < 0:
                    raise AssistedBrowserError(
                        "Target pointer matchIndex must be a non-negative integer."
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
                if not isinstance(raw, Mapping) or set(raw) != {
                    "operation",
                    "targets",
                }:
                    raise AssistedBrowserError(
                        "Target pointers request fields are invalid."
                    )
                operation = _required_text(
                    raw.get("operation"),
                    "operation",
                    maximum=80,
                )
                target_specs = raw.get("targets")
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
                    metadata=metadata,
                )
                self._send_json(200, {"targetPointers": result})
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
    for key in ("port", "token", "pid", "cdpEndpoint"):
        if not raw.get(key):
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
    server.cdp_endpoint = os.environ.get(
        "ESS_WORKDAY_ASSIST_CDP",
        DEFAULT_CDP,
    )
    session_path = _session_path(root)
    _write_json(
        session_path,
        {
            "schemaVersion": 1,
            "port": server.server_port,
            "token": token,
            "pid": os.getpid(),
            "startedAt": _now_iso(),
            "cdpEndpoint": os.environ.get("ESS_WORKDAY_ASSIST_CDP", DEFAULT_CDP),
        },
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


def _start_server(root: Path, cdp_endpoint: str) -> tuple[dict[str, Any], bool]:
    """Reuse a live session-owned server or launch a new detached loopback server."""
    path = _session_path(root)
    if path.exists():
        try:
            existing = _load_session(root)
        except AssistedBrowserError:
            existing = {}
        if existing and _session_is_alive(existing):
            if existing.get("cdpEndpoint") != cdp_endpoint:
                raise AssistedBrowserError(
                    "The active assisted-browser session uses a different "
                    "CDP endpoint. Stop it before starting another."
                )
            return existing, False
        path.unlink(missing_ok=True)

    token = secrets.token_urlsafe(32)
    environment = os.environ.copy()
    environment[_TOKEN_ENV] = token
    environment["ESS_WORKDAY_ASSIST_CDP"] = cdp_endpoint
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
    if target_url is not None:
        target = _navigate_application(session, str(target_url))
    else:
        sync_playwright, playwright_error = _playwright()
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.connect_over_cdp(
                session["cdpEndpoint"]
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
    _parse_cdp_endpoint(args.cdp)
    application_url = surface_url(root, args.surface)
    session, server_started = _start_server(root, args.cdp)
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
        }
    )
    _write_json(_session_path(root), session)
    return {
        "started": True,
        "serverStarted": server_started,
        "browserLaunched": browser_launched,
        "surface": args.surface,
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


def _status(_args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Combine persisted session identity with live companion state for orchestration decisions."""
    session = _load_session(root)
    result = _api_request(session, "/api/status")
    return {
        "running": True,
        "surface": session.get("surface"),
        "cdpEndpoint": session["cdpEndpoint"],
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
    current = status.get(interaction)
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
        completed = _interaction_completed_after_publication(
            latest,
            operation=args.operation,
            interaction=args.interaction,
            revision=args.revision,
        )
        if completed is not None:
            return {
                "completed": True,
                "interaction": args.interaction,
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
            "selector": args.selector,
            "frameIndex": args.frame_index,
            "matchIndex": args.match_index,
        },
        timeout=30.0,
    )


def _point_targets(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Load a target set and request atomic multi-target rail guidance."""
    if str(args.targets_file) == "-":
        targets = json.load(sys.stdin)
    else:
        targets = json.loads(
            Path(args.targets_file).read_text(encoding="utf-8")
        )
    session = _load_session(root)
    return _api_request(
        session,
        "/api/point-targets",
        value={
            "operation": args.operation,
            "targets": targets,
        },
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


def _inspect_layout(_args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Report whether session-owned pages are visibly arranged for side-by-side assistance."""
    session = _load_session(root)
    sync_playwright, playwright_error = _playwright()
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(session["cdpEndpoint"])
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
        description="Guide native DA Workday browser handoffs in split screen."
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

    open_surface = commands.add_parser("open")
    open_surface.add_argument("--surface", choices=_SURFACES, required=True)

    present = commands.add_parser("present")
    present.add_argument("--view-file", type=Path, required=True)

    commands.add_parser("status")
    wait = commands.add_parser("wait")
    wait.add_argument(
        "--operation",
        choices=sorted(_WAIT_OPERATIONS),
        required=True,
    )
    wait.add_argument(
        "--interaction",
        choices=("collection", "confirmation", "entry"),
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
    capture = commands.add_parser("capture")
    capture.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    capture.add_argument("--selector", required=True)
    capture.add_argument("--frame-index", type=int, required=True)
    capture.add_argument("--match-index", type=int, required=True)
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
    point.add_argument("--frame-index", type=int, required=True)
    point.add_argument("--match-index", type=int, required=True)
    point.add_argument("--append", action="store_true")
    point_targets = commands.add_parser("point-targets")
    point_targets.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    point_targets.add_argument("--targets-file", type=Path, required=True)
    reveal = commands.add_parser("reveal")
    reveal.add_argument(
        "--operation",
        choices=sorted(_COLLECTION_OPERATIONS),
        required=True,
    )
    reveal.add_argument("--selector", required=True)
    reveal.add_argument("--frame-index", type=int, required=True)
    reveal.add_argument("--match-index", type=int, required=True)
    commands.add_parser("inspect-layout")
    commands.add_parser("stop")
    commands.add_parser("_serve", help=argparse.SUPPRESS)
    return parser


_HANDLERS = {
    "start": _start,
    "open": _open,
    "present": _present,
    "status": _status,
    "wait": _wait,
    "inspect": _inspect,
    "follow": _follow,
    "capture": _capture,
    "fill-search": _fill_search,
    "point": _point,
    "point-targets": _point_targets,
    "reveal": _reveal,
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
