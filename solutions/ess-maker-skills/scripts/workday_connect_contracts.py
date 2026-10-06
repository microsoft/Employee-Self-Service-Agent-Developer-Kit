# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Compatibility exports for Workday Connect evidence contracts."""

from workday_connect_administrator_contracts import (
    validate_administrator_partial_evidence,
)
from workday_connect_entra_contracts import (
    _normalize_entra_check as _normalize_entra_check,
    build_entra_handoff,
    parse_entra_return_worksheet,
    validate_entra_verification,
)
from workday_connect_evidence_contracts import (
    EMPLOYEE_VALIDATION_FAILURE_SURFACE_CHOICES,
    EMPLOYEE_VALIDATION_FAILURE_SURFACES,
    EMPLOYEE_VALIDATION_REMEDIATIONS,
    EMPLOYEE_VALIDATION_RESULT_IDS,
    WorkdayConnectContractError,
    validate_agent_binding_evidence,
    validate_employee_evidence,
    validate_employee_failure_evidence,
)
from workday_connect_workday_admin_contracts import (
    build_workday_admin_packet,
    parse_workday_admin_return_worksheet,
    validate_workday_admin_response,
)


__all__ = [
    "EMPLOYEE_VALIDATION_FAILURE_SURFACE_CHOICES",
    "EMPLOYEE_VALIDATION_FAILURE_SURFACES",
    "EMPLOYEE_VALIDATION_REMEDIATIONS",
    "EMPLOYEE_VALIDATION_RESULT_IDS",
    "WorkdayConnectContractError",
    "build_entra_handoff",
    "build_workday_admin_packet",
    "parse_entra_return_worksheet",
    "parse_workday_admin_return_worksheet",
    "validate_administrator_partial_evidence",
    "validate_agent_binding_evidence",
    "validate_employee_evidence",
    "validate_employee_failure_evidence",
    "validate_entra_verification",
    "validate_workday_admin_response",
]
