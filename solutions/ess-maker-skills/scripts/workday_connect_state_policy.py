# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure classification policy for persisted Workday Connect state."""

from __future__ import annotations

import re
from typing import Any, Mapping

from workday_connect_model import LIFECYCLE_BLOCKER_CATEGORIES


_BLOCKER_CATEGORY_KEYWORDS = (
    ("timeout", ("timeout", "timedout")),
    (
        "permissions",
        (
            "permission",
            "access",
            "authorization",
            "unauthorized",
            "consent",
            "forbidden",
            "role",
        ),
    ),
    (
        "auth",
        ("auth", "credential", "signin", "sign-in", "token", "entra"),
    ),
    (
        "connection",
        ("connection", "network", "endpoint", "dns", "ssl", "http"),
    ),
    (
        "validation",
        ("validation", "contract", "evidence", "invalid"),
    ),
    ("state", ("state", "store", "schema", "migration", "planchanged")),
    (
        "platform",
        ("platform", "preflight", "dataverse", "package", "solution"),
    ),
    ("runtime", ("runtime", "flow", "topic", "agent")),
)

_BLOCKER_CATEGORY_EXACT = {
    "employee-authentication": "auth",
    "workday-connection": "connection",
    "runtime-flow": "runtime",
    "employee-context": "validation",
    "network": "connection",
    "workday-access": "permissions",
    "publish-or-agent": "runtime",
    "unknown": "unknown",
}

_REMEDIATION_ID_RE = re.compile(r"^WD-E2E-\d{3}$")


def blocker_category(blocker: Mapping[str, Any] | None) -> str:
    if not blocker:
        return ""
    raw = str(
        blocker.get("category")
        or blocker.get("failureCategory")
        or blocker.get("errorType")
        or "unknown"
    ).strip().casefold()
    if raw in LIFECYCLE_BLOCKER_CATEGORIES:
        return raw
    if raw in _BLOCKER_CATEGORY_EXACT:
        return _BLOCKER_CATEGORY_EXACT[raw]
    compact = "".join(character for character in raw if character.isalnum())
    for category, keywords in _BLOCKER_CATEGORY_KEYWORDS:
        if any(
            "".join(character for character in keyword if character.isalnum())
            in compact
            for keyword in keywords
        ):
            return category
    return "unknown"


def remediation_id(blocker: Mapping[str, Any] | None) -> str:
    if not blocker:
        return ""
    value = str(blocker.get("remediationId") or "").strip().upper()
    return value if _REMEDIATION_ID_RE.fullmatch(value) else ""
