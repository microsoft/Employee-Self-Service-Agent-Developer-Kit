# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Declarative Agent (DA) Workday Extension Validation.

Verifies that the Workday extension package for the **Declarative Agent HR**
flavor of Employee Self-Service is installed into the target Power Platform
environment (``setup/workday-da`` skill, step DA1.1). DA and CEA
ship distinct extension packages under distinct schema names (see
``src/reference/solution-catalog.md``); this module never reuses or is
reused by ``checks/workday.py`` / ``checks/workday_extension.py``, which are
CEA-only (they key off Power Automate connection references and
``.mcs.yml`` topics that do not exist in a DA agent).

Runnable in isolation via ``--checkpoint WD-DA-PKG-001``.
"""

from ..runner import CheckResult, Priority, Role, Status
from ..agent_scope import validate_agent_slug
from auth import query_all, AuthExpiredError  # scripts/auth.py, on path via cli.py


_DA_HR_PARENT_SCHEMA = "msdyn_copilotforemployeeselfservicedahr"
_DA_IT_PARENT_SCHEMA = "msdyn_copilotforemployeeselfservicedait"
_DA_HR_WORKDAY_CHILD_SCHEMA = "msdyn_EssDAHRWorkday"
_MOS_WORKDAY_RUNTIME_SCHEMA = "msdyn_EssWorkdayRuntime"
_DA_HR_AGENT_SCHEMAS = {
    _DA_HR_PARENT_SCHEMA,
    "gptagent_copilotforemployeeselfservicehr",
}
_DA_IT_AGENT_SCHEMAS = {
    _DA_IT_PARENT_SCHEMA,
    "gptagent_copilotforemployeeselfserviceit",
}

_SOLN_SELECT = "solutionid,uniquename,friendlyname,ismanaged,version"

_ALL_TRACKED_SCHEMAS = (
    _DA_HR_PARENT_SCHEMA,
    _DA_IT_PARENT_SCHEMA,
    _DA_HR_WORKDAY_CHILD_SCHEMA,
    _MOS_WORKDAY_RUNTIME_SCHEMA,
)
_SOLN_FILTER = " or ".join(
    f"uniquename eq '{schema}'" for schema in _ALL_TRACKED_SCHEMAS
)

_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install"
)
_DESCRIPTION = "Workday extension package installed for the DA ESS HR agent"


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

    selected = _selected_agent(runner)
    if selected is None:
        return [_result(
            Status.FAILED.value,
            "The selected agent identity could not be resolved from the "
            "workspace configuration.",
            remediation=(
                "Select the intended ESS DA HR agent, refresh the local "
                "workspace configuration, and rerun this checkpoint with its "
                "--agent-slug value."
            ),
        )]

    selected_slug, selected_agent = selected
    selected_schema = str(
        selected_agent.get("schemaName")
        or selected_agent.get("schema_name")
        or ""
    ).casefold()
    if selected_schema in _DA_IT_AGENT_SCHEMAS:
        return [_result(
            Status.FAILED.value,
            f"The selected agent '{selected_slug}' is the ESS DA IT agent.",
            remediation=(
                "Workday integration with the ESS IT Agent is not supported "
                "in this release. Select the ESS HR Agent first."
            ),
        )]
    if selected_schema not in _DA_HR_AGENT_SCHEMAS:
        return [_result(
            Status.FAILED.value,
            f"The selected agent '{selected_slug}' is not a supported ESS DA "
            "HR agent.",
            remediation=(
                "Select the installed ESS DA HR agent and rerun this "
                "checkpoint. Do not use environment-wide package presence as "
                "a substitute for selected-agent identity."
            ),
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

    required_schema = (
        _MOS_WORKDAY_RUNTIME_SCHEMA
        if selected_schema == "gptagent_copilotforemployeeselfservicehr"
        else _DA_HR_WORKDAY_CHILD_SCHEMA
    )
    child = installed_names.get(required_schema.casefold())
    if not child:
        return [_result(
            Status.FAILED.value,
            "The Workday package required by the ESS HR agent is not "
            "installed.",
            remediation=(
                "Run /connect workday to install the required Workday package "
                "in this environment, then re-run this check."
            ),
        )]

    return [_result(
        Status.PASSED.value,
        f"Selected ESS HR agent '{selected_slug}' detected. Workday package "
        "installed: "
        f"{_describe_solution(child)}.",
    )]


def _selected_agent(runner) -> tuple[str, dict] | None:
    """Resolve the exact selected agent without environment-wide inference."""
    config = getattr(runner, "config", {}) or {}
    if not isinstance(config, dict):
        return None

    legacy_agent = config.get("agent")
    legacy_agent = legacy_agent if isinstance(legacy_agent, dict) else {}
    slug = (
        getattr(runner, "agent_slug", None)
        or config.get("activeAgent")
        or legacy_agent.get("slug")
    )
    if not slug:
        return None
    try:
        selected_slug = validate_agent_slug(str(slug))
    except ValueError:
        return None

    agents = config.get("agents")
    if isinstance(agents, list):
        for agent in agents:
            if (
                isinstance(agent, dict)
                and str(agent.get("slug") or "") == selected_slug
            ):
                return selected_slug, agent
    if str(legacy_agent.get("slug") or "") == selected_slug:
        return selected_slug, legacy_agent
    return None


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
