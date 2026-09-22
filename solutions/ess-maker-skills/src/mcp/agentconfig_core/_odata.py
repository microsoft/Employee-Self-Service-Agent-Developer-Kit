# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared OData / URL helpers for the AgentConfiguration surfaces.

Part of the neutral ``agentconfig_core`` package: used by the planner (projects/plans/tasks),
the role-attestation module, and the landing-page client. They intentionally
depend on nothing else in the core, so any module can import them without an
import cycle.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Optional


_DEFAULT_AGENTCONFIG_PROJECTS_BASE_URL = (
    "https://substrate.office.com/weveb2/api/beta"
)
_TENANTS_COLLECTION = "tenants"

_QUERY_OPTION_MAP = {
    "select": "$select",
    "expand": "$expand",
    "filter": "$filter",
    "orderby": "$orderby",
    "top": "$top",
    "skip": "$skip",
    "count": "$count",
    "skiptoken": "$skiptoken",
}


def _validate_https_base_url(url: str, env_name: str) -> str:
    """Validate an HTTPS base URL without credentials, query, or fragment."""
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{env_name} must be an HTTPS URL without credentials, a query, "
            "or a fragment"
        )
    return url.rstrip("/")


def _validate_odata_string(value: str, name: str) -> str:
    """Validate a non-empty, control-char-free string bound for OData use.

    Shared by ``_escape_odata_literal`` and ``_require_odata_id``; the only
    difference between those two is whether the escaped result is URL-quoted.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"{name} must be a non-empty string without surrounding whitespace"
        )
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _escape_odata_literal(value: str, name: str) -> str:
    """Validate and single-quote-escape a value for an OData ``$filter`` literal."""
    return _validate_odata_string(value, name).replace("'", "''")


def _require_odata_id(value: str, name: str) -> str:
    """Validate a non-empty, control-char-free id and encode it as an OData key."""
    return urllib.parse.quote(_escape_odata_literal(value, name), safe="")


def _mutation_headers(
    etag: Optional[str] = None, idempotency_key: Optional[str] = None
) -> dict[str, str]:
    """Build optional If-Match / Idempotency-Key headers for a mutation."""
    headers: dict[str, str] = {}
    if etag is not None:
        if not isinstance(etag, str) or not etag.strip():
            raise ValueError("etag must be a non-empty string when provided")
        headers["If-Match"] = etag
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError(
                "idempotencyKey must be a non-empty string when provided"
            )
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _normalize_etag(value: Optional[str]) -> Optional[str]:
    """Normalize an ETag for equality comparison only.

    Strips a weak-validator ``W/`` prefix and surrounding quotes so that the
    same version rendered as ``W/"3"``, ``"3"``, or ``3`` compares equal. This
    is used to decide whether a re-read entity's ETag actually moved; it is not
    the value sent back on the wire (the caller's original ETag string is).
    """
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if trimmed[:2].lower() == "w/":
        trimmed = trimmed[2:].strip()
    return trimmed.strip('"')


def _entity_scalar(entity: Any, *names: str) -> Optional[str]:
    """Case-insensitively read the first present non-empty string field.

    AgentConfiguration renders entity bodies in PascalCase (``ETag``, ``Status``) while
    OData also permits the ``@odata.etag`` annotation; callers pass every
    accepted spelling and get back the first non-empty match.
    """
    if not isinstance(entity, dict):
        return None
    lowered = {
        key.lower(): item for key, item in entity.items() if isinstance(key, str)
    }
    for name in names:
        item = lowered.get(name.lower())
        if isinstance(item, str) and item:
            return item
    return None


def _build_query_params(query: Optional[dict[str, Any]]) -> dict[str, str]:
    """Map friendly OData option names (filter/top/...) to ``$``-prefixed params."""
    if query is None:
        return {}
    if not isinstance(query, dict):
        raise ValueError("query must be an object of OData options")
    params: dict[str, str] = {}
    for key, value in query.items():
        if value is None:
            continue
        option = _QUERY_OPTION_MAP.get(key.lower())
        if option is None:
            raise ValueError(f"Unsupported query option: {key}")
        params[option] = (
            "true" if value is True else "false" if value is False else str(value)
        )
    return params
