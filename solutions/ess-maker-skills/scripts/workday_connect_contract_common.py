# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared primitives for Workday Connect evidence contracts."""

from __future__ import annotations

from typing import Any, Mapping

from workday_connect_model import WorkdayConnectModelError


class WorkdayConnectContractError(WorkdayConnectModelError):
    """Raised when a Workday Connect evidence contract is invalid."""


def required_text(
    document: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(document.get(key) or "").strip()
    if not value:
        raise WorkdayConnectContractError(f"{label} is required.")
    return value
