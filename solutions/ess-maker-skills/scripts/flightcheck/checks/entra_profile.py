# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded Microsoft 365 profile coverage for FlightCheck."""

import requests
from time import monotonic

from ..entra_profile import (
    ATTRIBUTES, TIME_BUDGET_SECONDS, check_attributes, check_own_profile, permission_unavailable_report,
)
from ..graph_client import GraphConsentError, GraphPermissionError
from ..runner import CheckResult, Priority, Role


def _read_attributes(runner) -> dict:
    started = None
    try:
        executor = getattr(runner, "da_executor", None)
        client = executor.graph() if executor is not None else runner.graph
        if client is None:
            availability = getattr(runner, "client_availability", {}).get("graph", {})
            if availability.get("permissionUnavailable") is True:
                raise GraphPermissionError("Graph permission is unavailable.")
            raise RuntimeError("Graph authentication is unavailable; coverage was not checked.")
        client.verify_identity(getattr(runner, "authenticated_account", None))
        started = monotonic()
        return check_attributes(client, "tenant", list(ATTRIBUTES))
    except (GraphPermissionError, GraphConsentError):
        remaining = TIME_BUDGET_SECONDS - (monotonic() - started if started is not None else 0)
        if remaining <= 0:
            raise TimeoutError("The coverage budget expired; no partial coverage is reported.")
        try:
            client = runner.self_profile_graph()
            return check_own_profile(client, time_budget=remaining)
        except GraphPermissionError:
            report = permission_unavailable_report()
            report.update(
                profileVerified=False,
                message=(
                    "Not checked: tenant-wide directory access and self-profile read permission "
                    "were unavailable. Neither profile availability nor tenant coverage was verified."
                ),
            )
            return report


def run_entra_profile_checks(runner) -> list[CheckResult]:
    roles = [Role.ENTRA_ADMIN.value]
    try:
        report = _read_attributes(runner)
        if report.get("profileVerified") is True:
            summary = "\n".join(f"{row['attribute']}: {row['availability']}" for row in report["results"])
            return [CheckResult(
                checkpoint_id="AUTH-PROFILE-001", category="Authentication",
                priority=Priority.MEDIUM.value, status="Warning",
                description="Microsoft 365 profile attribute coverage (beta)",
                result=f"{report['message']}\n{summary}",
                remediation=(
                    "Personalization opportunity, not a deployment blocker. Review missing fields "
                    "in your own Microsoft 365 profile through the configured source: Entra, "
                    "Organizational Data Service, people-data connectors or profile editing. "
                    "Only enrich fields relevant to the ESS experiences you intend to support. "
                    "Do not populate placeholder values. If tenant coverage is needed, rerun "
                    "AUTH-PROFILE-001 with existing approved User.Read.All access."
                ),
                roles=roles, evidence=report,
                doc_link="https://learn.microsoft.com/en-us/graph/people-data-sources",
            )]
        if report.get("reason") == "permission_unavailable":
            return [CheckResult(
                checkpoint_id="AUTH-PROFILE-001", category="Authentication",
                priority=Priority.MEDIUM.value, status="Warning",
                description="Microsoft 365 profile attribute coverage (beta)",
                result=report["message"],
                remediation=(
                    "Access limitation, not a deployment blocker. Use an account with approved "
                    "User.Read access to check your own profile, or existing approved User.Read.All "
                    "access for tenant coverage, then rerun AUTH-PROFILE-001. Unavailable access "
                    "is not evidence that profile attributes are empty."
                ),
                roles=roles, evidence=report,
            )]
    except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        if isinstance(exc, requests.RequestException):
            code = exc.response.status_code if exc.response is not None else "unavailable"
            message = f"Graph read failed ({type(exc).__name__}; HTTP {code})."
        else:
            message = str(exc)
        return [CheckResult(
            checkpoint_id="AUTH-PROFILE-001", category="Authentication",
            priority=Priority.MEDIUM.value, status="Error",
            description="Microsoft 365 profile attribute coverage (beta)",
            result=message,
            remediation=(
                "Restore the Graph read and rerun AUTH-PROFILE-001. Tenant coverage requires "
                "admin-consented User.Read.All. A timeout does not establish missing attributes."
            ),
            roles=roles, evidence={"executionError": True},
        )]
    lines = []
    for row in report["results"]:
        coverage = f"{row['coveragePercent']:.2f}%" if row["coveragePercent"] is not None else "Unverified"
        lines.append(
            f"{row['attribute']}: {coverage} "
            f"({row['available']}/{report['usersChecked']} populated; {row['empty']} empty; "
            f"{row['notReturned']} not returned; {row['unverified']} ambiguous or incomplete)"
        )
    summary = "\n".join(lines)
    warning = report["status"] == "Warning"
    return [CheckResult(
        checkpoint_id="AUTH-PROFILE-001", category="Authentication",
        priority=Priority.MEDIUM.value, status=report["status"],
        description="Microsoft 365 profile attribute coverage (beta)",
        result=f"{report['coverageLabel']}.\n"
        + ("Data-quality concern: one or more attributes have low or unavailable coverage.\n" if warning else "")
        + summary,
        remediation=(
            "Personalization opportunity, not a deployment blocker. Where ESS uses these fields, "
            "enriching missing Microsoft 365 profile data can improve personalization. Review "
            "the configured source: Entra, Organizational Data Service, people-data connectors "
            "or profile editing, then rerun AUTH-PROFILE-001. Unverified fields are not evidence "
            "of missing data. Optional fields need not be populated; do not use placeholder values."
        ) if warning else "",
        roles=roles, evidence=report,
        doc_link="https://learn.microsoft.com/en-us/graph/people-data-sources",
    )]
