# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Publishing & QA Validation (PUB-xxx, QA-xxx)

Mostly manual checklist items — presents as NotConfigured with remediation.
"""

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

PUBLISHING_CHECKS = [
    {"id": "QA-001", "desc": "Golden prompts library (50+ prompts)", "p": "Critical"},
    {"id": "QA-002", "desc": "Core functionality prompts tested", "p": "Critical"},
    {"id": "QA-012", "desc": "Accuracy validation completed", "p": "Critical"},
    {"id": "PUB-001", "desc": "Solution exported as managed", "p": "Critical"},
    {"id": "PUB-002", "desc": "Test environment deployment completed", "p": "Critical"},
    {"id": "PUB-003", "desc": "UAT testing completed with sign-off", "p": "Critical"},
    {"id": "PUB-006", "desc": "Microsoft 365 admin approval obtained", "p": "Critical"},
    {"id": "PUB-011", "desc": "Publishing delay expected (up to 48 hrs)", "p": "Medium"},
]


def run_publishing_checks(runner) -> list[CheckResult]:
    """Return manual-review publishing/QA checklist items."""
    results = []

    for check in PUBLISHING_CHECKS:
        results.append(CheckResult(
            checkpoint_id=check["id"],
            category="Publishing",
            priority=check["p"],
            status=Status.NOT_CONFIGURED.value,
            description=check["desc"],
            result="Manual verification required",
            remediation=f"Verify: {check['desc']} — [deployment guide](https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/deploy-overview-alm)",
            doc_link=f"{DOC_BASE}/deploy-overview-alm",
        ))

    return results
