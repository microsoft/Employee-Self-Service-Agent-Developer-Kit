# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Declarative Agent (DA) Workday Extension Validation.

Verifies that the Workday extension package for the **Declarative Agent**
(DA) flavor of Employee Self-Service is installed into the target Power
Platform environment (``setup/workday-da`` skill, step DA1.1). DA and CEA
ship distinct extension packages under distinct schema names (see
``src/reference/solution-catalog.md``); this module never reuses or is
reused by ``checks/workday.py`` / ``checks/workday_extension.py``, which are
CEA-only (they key off Power Automate connection references and
``.mcs.yml`` topics that do not exist in a DA agent).

Runnable in isolation via ``--checkpoint WD-DA-PKG-001``.
"""

from ..runner import CheckResult, Priority, Role, Status
from auth import query_all, AuthExpiredError  # scripts/auth.py, on path via cli.py


# Parent (base agent) schema names for the two DA verticals that ship a
# Workday child package. The DA Hub bundle has no Workday child of its own —
# Workday is installed against the HR or IT vertical (see
# src/reference/solution-catalog.md, "## Parents" / "## Child packages").
_DA_PARENT_SCHEMAS = {
    "hr": "msdyn_copilotforemployeeselfservicedahr",
    "it": "msdyn_copilotforemployeeselfservicedait",
}

# The Workday child package schema for each DA vertical (from
# src/reference/solution-catalog.md, "## Child packages, connection
# references, and flows").
_DA_WORKDAY_CHILD_SCHEMAS = {
    "hr": "msdyn_essdahrworkday",
    "it": "msdyn_essdaitworkday",
}

_VERTICAL_LABEL = {"hr": "HR", "it": "IT"}

_SOLN_SELECT = "solutionid,uniquename,friendlyname,ismanaged,version"

# All four fixed schema names this check ever needs to resolve in one
# round-trip: the two DA parents plus their two Workday children.
_ALL_TRACKED_SCHEMAS = tuple(_DA_PARENT_SCHEMAS.values()) + tuple(
    _DA_WORKDAY_CHILD_SCHEMAS.values()
)
_SOLN_FILTER = " or ".join(
    f"uniquename eq '{schema}'" for schema in _ALL_TRACKED_SCHEMAS
)

_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install"
)
_DESCRIPTION = "Workday extension package installed for the DA ESS agent"


def run_workday_da_checks(runner) -> list[CheckResult]:
    """Emit the WD-DA-PKG-xxx checkpoints.

    Currently a single check (``WD-DA-PKG-001``); kept as a category
    function so additional DA-Workday rows can be added later without
    changing the registry / cli wiring.
    """
    return _check_workday_da_package_installed(runner)


def _check_workday_da_package_installed(runner) -> list[CheckResult]:
    """WD-DA-PKG-001: the DA Workday extension package is installed.

    Always emits exactly one CheckResult (principle 7 — bucket multi-resource
    findings). Never raises — all errors are caught and turned into WARNING
    results so a transient Dataverse failure does not abort the whole
    flightcheck run.
    """
    env_url = getattr(runner, "env_url", None)
    token = getattr(runner, "dv_token", None)

    if not env_url or not token:
        return [_result(
            Status.SKIPPED.value,
            "Dataverse URL or access token not available in this run.",
        )]

    try:
        all_solutions = query_all(
            env_url, token,
            "solutions",
            _SOLN_SELECT,
            _SOLN_FILTER,
        )
    except AuthExpiredError as e:
        return [_result(
            Status.WARNING.value,
            str(e),
            remediation="Re-run FlightCheck to refresh the access token.",
        )]
    except Exception as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        status_hint = f" [HTTP {status_code}]" if status_code is not None else ""
        return [_result(
            Status.WARNING.value,
            f"Unable to verify the DA Workday package: "
            f"{type(e).__name__}{status_hint}: {e}",
            remediation=(
                "Inspect the error above; common causes are insufficient "
                "Dataverse privileges on the solutions table (typically "
                "surfaces as HTTP 403) or a transient platform error (HTTP 5xx)."
            ),
        )]

    installed_names = {
        s.get("uniquename", "").casefold(): s for s in all_solutions
    }

    installed_verticals = [
        vertical
        for vertical, parent_schema in _DA_PARENT_SCHEMAS.items()
        if parent_schema in installed_names
    ]
    installed_labels = ", ".join(
        _VERTICAL_LABEL[vertical] for vertical in installed_verticals
    )

    if not installed_verticals:
        return [_result(
            Status.FAILED.value,
            "No DA Employee Self-Service base agent (HR or IT) was found in "
            "this environment.",
            remediation=(
                "Run /setup to install the DA Employee Self-Service base "
                "agent first, then run /connect workday again."
            ),
        )]

    findings = []
    missing_verticals = []
    for vertical in installed_verticals:
        child_schema = _DA_WORKDAY_CHILD_SCHEMAS[vertical]
        label = _VERTICAL_LABEL[vertical]
        child = installed_names.get(child_schema)
        if child:
            findings.append(f"{label}: {_describe_solution(child)}")
        else:
            missing_verticals.append(vertical)

    if missing_verticals:
        missing_labels = ", ".join(_VERTICAL_LABEL[v] for v in missing_verticals)
        installed_summary = f" Already installed — {'; '.join(findings)}." if findings else ""
        return [_result(
            Status.FAILED.value,
            f"The Workday extension package is not installed for the "
            f"{missing_labels} edition of your DA Employee Self-Service "
            f"agent. Detected DA base agent editions: "
            f"{installed_labels}.{installed_summary}",
            remediation=(
                "Open AppSource (or the Microsoft 365 admin center), find "
                "the Workday extension for Employee Self-Service, and "
                "deploy it to this environment — the same place you "
                "installed the base agent. Wait for the install to finish, "
                "then re-run this check."
            ),
        )]

    return [_result(
        Status.PASSED.value,
        f"Detected DA base agent editions: {installed_labels}. "
        f"DA Workday extension package installed: {'; '.join(findings)}.",
    )]


def _result(status: str, result: str, remediation: str = "") -> CheckResult:
    return CheckResult(
        roles=[Role.ESS_MAKER.value],
        checkpoint_id="WD-DA-PKG-001",
        category="Workday DA",
        priority=Priority.CRITICAL.value,
        status=status,
        description=_DESCRIPTION,
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK,
    )


def _describe_solution(sol: dict) -> str:
    """Render one solution row as ``uniquename (vX.Y.Z)`` for the result text."""
    name = sol.get("uniquename", "<unknown>")
    version = sol.get("version")
    return f"{name} (v{version})" if version else name
