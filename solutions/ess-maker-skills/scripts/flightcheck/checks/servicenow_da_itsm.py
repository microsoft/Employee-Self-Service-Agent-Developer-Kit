# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle checkpoints for the DA IT ServiceNow ITSM provider."""

from __future__ import annotations

from typing import Any

import connect_servicenow_da as snow
from flightcheck.checks import servicenow_da_hrsd as shared
from flightcheck.runner import CheckResult


_HR_PREFIX = "SN-DA-HRSD"
_IT_PREFIX = "SN-DA-ITSM"


def _it_text(value: str) -> str:
    return (
        value.replace("ServiceNow HRSD", "ServiceNow ITSM")
        .replace("HRSD", "ITSM")
        .replace("ESS DA HR", "ESS DA IT")
        .replace("DA HR agent", "DA IT agent")
        .replace("HR agent", "IT agent")
        .replace("Employee Self-Service HR", "Employee Self-Service IT")
        .replace("HR cases", "IT tickets")
        .replace("HR case", "IT ticket")
    )


def _rewrite_result(result: CheckResult) -> CheckResult:
    result.checkpoint_id = result.checkpoint_id.replace(
        _HR_PREFIX,
        _IT_PREFIX,
    )
    result.category = "ServiceNow DA ITSM"
    result.description = _it_text(result.description)
    result.result = _it_text(result.result)
    result.remediation = _it_text(result.remediation)
    result.remediation_id = result.remediation_id.replace(
        _HR_PREFIX,
        _IT_PREFIX,
    )
    if result.checkpoint_id == "SN-DA-ITSM-PKG-001":
        result.remediation = result.remediation.replace(
            "Install the ServiceNow ITSM extension for this exact IT agent.",
            (
                "Verify the exact Employee Self-Service (IT) agent contains "
                "the built-in ServiceNow ITSM topics."
            ),
        )
    return result


def run_servicenow_da_itsm_checks(runner) -> list[CheckResult]:
    original_target = getattr(runner, "checkpoint_target", None)
    translated_target = (
        original_target.replace(_IT_PREFIX, _HR_PREFIX)
        if isinstance(original_target, str)
        else original_target
    )
    original_globals: dict[str, Any] = {
        "HR_SCHEMA_NAME": shared.HR_SCHEMA_NAME,
        "PROVIDER_KEY": shared.PROVIDER_KEY,
        "_CATEGORY": shared._CATEGORY,
        "_ENTRA_PREFIX": shared._ENTRA_PREFIX,
        "_TEST_PROMPT_CATEGORY": shared._TEST_PROMPT_CATEGORY,
    }
    try:
        runner.checkpoint_target = translated_target
        shared.HR_SCHEMA_NAME = snow.IT_SCHEMA_NAME
        shared.PROVIDER_KEY = snow.ITSM_PROFILE.provider_key
        shared._CATEGORY = "ServiceNow DA ITSM"
        shared._ENTRA_PREFIX = "SN-DA-HRSD-ENTRA"
        shared._TEST_PROMPT_CATEGORY = (
            snow.ITSM_PROFILE.test_prompt_category
        )
        with snow.product_profile_context("itsm"):
            results = shared.run_servicenow_da_hrsd_checks(runner)
    finally:
        runner.checkpoint_target = original_target
        for name, value in original_globals.items():
            setattr(shared, name, value)
    return [
        _rewrite_result(result)
        for result in results
        if result.checkpoint_id != "SN-DA-HRSD-PLUGIN-001"
    ]
