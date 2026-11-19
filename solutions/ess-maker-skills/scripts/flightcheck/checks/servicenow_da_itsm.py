# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle checkpoints for the DA IT ServiceNow ITSM provider."""

from __future__ import annotations

from flightcheck.checks.servicenow_da_hrsd import (
    IT_CHECK_PROFILE,
    run_servicenow_da_hrsd_checks,
)
from flightcheck.runner import CheckResult


def run_servicenow_da_itsm_checks(runner) -> list[CheckResult]:
    return run_servicenow_da_hrsd_checks(runner, profile=IT_CHECK_PROFILE)
