# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Content-free diagnostics for Org Announcements operation telemetry.

Native MCP calls annotate the shared request-local operation; direct callers
emit a bounded ``adk.api.call`` record. Diagnostic codes and error sources use
fixed allowlists. Shared telemetry supplies correlation, HTTP accounting,
authenticated tenant context, and content-free usage measurements.

Announcement content, audience identifiers, credentials, endpoint URLs, and
request payloads are excluded. Every emit and shutdown path fails open.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional

from operation_telemetry import current_operation


_LOGGER = logging.getLogger("ess-org-announcements.telemetry")

# The MCP tool names this server exposes. An operation outside the allowlist is
# bucketed rather than emitted verbatim, so a future tool cannot silently mint a
# new dimension value (and cannot smuggle caller-controlled text into Aria).
_OPERATIONS = frozenset(
    {
        "resolve_agent_title_id",
        "open_org_announcements",
        "save_bulletin",
        "transition_bulletin",
        "duplicate_bulletin",
        "search_audience_groups",
    }
)
OPERATION_UNKNOWN = "unknown"

# Broad source buckets. Anything narrower would start describing the tenant's
# configuration.
SOURCE_BACKEND = "backend"
SOURCE_GRAPH = "graph"
SOURCE_MCP = "mcp"
_SOURCES = frozenset({SOURCE_BACKEND, SOURCE_GRAPH, SOURCE_MCP})

# Stable codes are short identifiers, never free text. This bound is a
# belt-and-braces guard so a malformed code can never carry a payload.
_MAX_CODE_LENGTH = 64
_ERROR_CODES = frozenset(
    {
        "AudienceMetadataUnavailable",
        "AuthenticationRequired",
        "AuthorizationDenied",
        "BackendValidationError",
        "CommittedRefreshFailed",
        "FeatureUnavailable",
        "IndeterminateWrite",
        "InvalidRequest",
        "NetworkError",
        "NotFound",
        "RegistrationRequired",
        "SearchUnavailable",
        "ServiceError",
    }
)

# Emitting is opt-out through the same switch the rest of the ADK honours; the
# module-level import is resolved lazily so a server started outside the kit
# layout still runs.
_ADK_TELEMETRY: Optional[Any] = None
_ADK_TELEMETRY_RESOLVED = False

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"
    )
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.append(_SCRIPTS_DIR)


def normalize_operation(operation: str) -> str:
    """Clamp an operation name to the allowlist."""
    if not isinstance(operation, str):
        return OPERATION_UNKNOWN
    return operation if operation in _OPERATIONS else OPERATION_UNKNOWN


def normalize_source(source: str) -> str:
    """Clamp an error source to the broad bucket allowlist."""
    if not isinstance(source, str):
        return SOURCE_MCP
    return source if source in _SOURCES else SOURCE_MCP


def normalize_error_code(error_code: str) -> str:
    """Clamp an error code to the fixed diagnostic allowlist.

    Backend values can be caller-controlled even when they look like short
    identifiers, so shape validation alone is not a privacy boundary.
    """
    if not isinstance(error_code, str):
        return ""
    candidate = error_code.strip()
    if not candidate:
        return ""
    if (
        len(candidate) > _MAX_CODE_LENGTH
        or not candidate.isascii()
        or not candidate.replace("_", "").isalnum()
        or candidate not in _ERROR_CODES
    ):
        return "UnknownError"
    return candidate


def _adk_telemetry() -> Optional[Any]:
    """Resolve ``scripts/adk_telemetry`` once, tolerating its absence."""
    global _ADK_TELEMETRY, _ADK_TELEMETRY_RESOLVED
    if _ADK_TELEMETRY_RESOLVED:
        return _ADK_TELEMETRY
    _ADK_TELEMETRY_RESOLVED = True
    try:
        if _SCRIPTS_DIR not in sys.path:
            sys.path.append(_SCRIPTS_DIR)
        import adk_telemetry  # noqa: PLC0415 — resolved lazily and optionally

        _ADK_TELEMETRY = adk_telemetry
    except Exception:  # noqa: BLE001 — telemetry must never break a tool call
        _ADK_TELEMETRY = None
    return _ADK_TELEMETRY


def record_operation(
    operation: str,
    *,
    outcome: str,
    latency_ms: int,
    error_code: str = "",
    error_source: str = SOURCE_MCP,
) -> None:
    """Emit one content-free ``adk.api.call`` event for a tool invocation.

    ``api_endpoint`` carries the *tool name*, not a URL: the tenant's API host
    is environment-specific and is never reported. Failure adds only the stable
    code and the broad source bucket; ``error_message`` is left empty on purpose.
    """
    if operation_context := current_operation.get():
        if outcome != "success":
            operation_context.error_code = normalize_error_code(error_code)
            operation_context.error_category = normalize_source(error_source)
        return

    telemetry = _adk_telemetry()
    if telemetry is None:
        return

    normalized_outcome = "success" if outcome == "success" else "failure"
    fields: dict[str, Any] = {
        "api_endpoint": normalize_operation(operation),
        "outcome": normalized_outcome,
        "latency_ms": max(0, int(latency_ms)),
    }
    if normalized_outcome == "failure":
        fields["error_code"] = normalize_error_code(error_code)
        fields["error_category"] = normalize_source(error_source)
        # Never a message: backend text can echo the announcement back.
        fields["error_message"] = ""

    try:
        telemetry.emit_api_call(**fields)
    except Exception:  # noqa: BLE001 — fail open, never break the tool call
        _LOGGER.debug("Org Announcements telemetry emit failed", exc_info=False)


def flush_telemetry() -> None:
    """Bound shutdown delivery without making telemetry availability mandatory."""
    telemetry = _adk_telemetry()
    if telemetry is not None:
        try:
            telemetry.flush(timeout=2.0)
        except Exception:
            _LOGGER.debug("Org Announcements telemetry flush failed", exc_info=False)


def initialize_telemetry_identity(tenant_id: str, *, local_dir: str) -> None:
    """Bind widget telemetry to the authenticated client's tenant."""
    telemetry = _adk_telemetry()
    if telemetry is not None:
        try:
            telemetry.initialize_tenant_identity(tenant_id, local_dir=local_dir)
        except Exception:
            _LOGGER.debug("Org Announcements telemetry identity unavailable", exc_info=False)
