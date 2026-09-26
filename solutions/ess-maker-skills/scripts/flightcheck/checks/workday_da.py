# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS FlightCheck — Declarative Agent (DA) Workday validation.

Validates the DA Workday package, active-agent connection parameter sharing,
and the Workday V2 user-context redirect. DA and CEA ship distinct extension
packages and expose different agent state, so these checks remain separate
from the CEA checks in ``workday.py`` and ``workday_extension.py``.

The package check runs through the ``workdayda`` scope. Agent wiring checks are
individually runnable through their ``WD-DA-*`` checkpoint IDs.
"""

from ..runner import CheckResult, Priority, Role, Status
from ..agent_scope import validate_agent_slug
from auth import query_all, AuthExpiredError  # scripts/auth.py, on path via cli.py
from configure_workday_da_user_context import (
    SETUP_TOPIC_NAME,
    TARGET_TOPIC_NAME,
    WorkdayDAUserContextError,
    inspect_workday_da_user_context,
)
from flightcheck.checks._da_connection_refs import (
    WORKDAY_SOAP_CONNECTOR_SUFFIX,
    read_active_agent_connection_references,
    shared_connection_parameter_values,
)
from workday_da_contract import (
    architecture_for_agent_schema,
    assess_package_version,
    load_definition,
)


_WORKDAY_DEFINITION = load_definition()
_ARCHITECTURE_BY_ID = {
    architecture["id"]: architecture
    for architecture in _WORKDAY_DEFINITION["architectures"]
}
_DA_HR_PARENT_SCHEMA = _ARCHITECTURE_BY_ID["classic-da"]["agentSchemaNames"][0]
_NATIVE_DA_HR_SCHEMA = _ARCHITECTURE_BY_ID["native-da"]["agentSchemaNames"][0]
_DA_IT_PARENT_SCHEMA = _WORKDAY_DEFINITION["unsupportedAgentSchemaNames"][0]
_NATIVE_DA_IT_SCHEMA = _WORKDAY_DEFINITION["unsupportedAgentSchemaNames"][1]
_DA_HR_WORKDAY_CHILD_SCHEMA = _WORKDAY_DEFINITION["packages"]["legacy-da"][
    "solutionSchemaName"
]
_MOS_WORKDAY_RUNTIME_SCHEMA = _WORKDAY_DEFINITION["packages"]["runtime"][
    "solutionSchemaName"
]
_DA_HR_AGENT_SCHEMAS = {_DA_HR_PARENT_SCHEMA, _NATIVE_DA_HR_SCHEMA}
_DA_IT_AGENT_SCHEMAS = {_DA_IT_PARENT_SCHEMA, _NATIVE_DA_IT_SCHEMA}

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
_CONNECTION_DESCRIPTION = "Workday connection parameters shared by the DA agent"
_CONTEXT_DESCRIPTION = "Workday V2 user context configured for the DA agent"


def run_workday_da_checks(runner) -> list[CheckResult]:
    """Emit the broad DA Workday scope's package checkpoint."""
    return _check_workday_da_package_installed(runner)


def run_workday_da_package_checks(runner) -> list[CheckResult]:
    """Emit only the DA Workday package checkpoint."""
    return _check_workday_da_package_installed(runner)


def run_workday_da_connection_checks(runner) -> list[CheckResult]:
    """Emit only the DA agent parameter-sharing checkpoint."""
    return _check_workday_da_parameter_sharing(runner)


def run_workday_da_user_context_checks(runner) -> list[CheckResult]:
    """Emit only the DA user-context checkpoint."""
    return _check_workday_da_user_context(runner)


def _check_workday_da_parameter_sharing(runner) -> list[CheckResult]:
    """WD-DA-CONN-001: active-agent Workday parameters are shared."""
    try:
        refs = read_active_agent_connection_references(runner)
    except ValueError as exc:
        return [_result(
            Status.WARNING.value,
            f"Agent connection settings could not be interpreted: {exc}",
            remediation=(
                "Refresh the active agent in Copilot Studio and rerun this "
                "check. If the warning remains, validate Connection settings "
                "manually before continuing."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]
    except Exception as exc:  # noqa: BLE001 - surface external API failures
        return [_result(
            Status.WARNING.value,
            "Agent connection settings could not be read: "
            f"{type(exc).__name__}: {exc}",
            remediation=(
                "Confirm access to the active agent, refresh authentication, "
                "and rerun this check."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]

    if refs is None:
        return [_result(
            Status.SKIPPED.value,
            "AgentBuilder access or the active agent identity is unavailable.",
            remediation=(
                "Select the ESS HR agent, sign in to Copilot Studio, and rerun "
                "this check."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]

    workday_refs = [
        ref
        for ref in refs
        if str(ref.get("connectorid") or "").casefold().rstrip("/").endswith(
            WORKDAY_SOAP_CONNECTOR_SUFFIX
        )
    ]
    if not workday_refs:
        return [_result(
            Status.NOT_CONFIGURED.value,
            "The active agent has no Workday connection reference.",
            remediation=(
                "Open the active agent's Settings > Connection settings page, "
                "connect each Workday flow entry, and rerun this check."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]

    unbound = [ref for ref in workday_refs if not ref.get("connectionid")]
    if unbound:
        return [_result(
            Status.NOT_CONFIGURED.value,
            f"{len(unbound)} of {len(workday_refs)} Workday connection "
            "reference(s) are not connected.",
            remediation=(
                "Open the active agent's Settings > Connection settings page "
                "and connect every Workday flow entry before sharing its "
                "parameters."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]

    try:
        unshared = [
            ref
            for ref in workday_refs
            if not shared_connection_parameter_values(ref)
        ]
    except ValueError as exc:
        return [_result(
            Status.WARNING.value,
            f"Workday shared parameters could not be interpreted: {exc}",
            remediation=(
                "Open Connection parameters for the Workday connection, save "
                "the sharing setting again, then rerun this check."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]

    if unshared:
        return [_result(
            Status.FAILED.value,
            f"{len(unshared)} of {len(workday_refs)} connected Workday "
            "reference(s) do not contain shared connection parameters.",
            remediation=(
                "In the active agent, open Settings > Connection settings > "
                "the Workday connection > See details > Connection parameters. "
                "Turn on 'Allow permission to share parameters', save, and "
                "rerun this check."
            ),
            checkpoint_id="WD-DA-CONN-001",
            description=_CONNECTION_DESCRIPTION,
        )]

    return [_result(
        Status.PASSED.value,
        f"All {len(workday_refs)} connected Workday reference(s) in the "
        "active agent contain shared connection parameters.",
        checkpoint_id="WD-DA-CONN-001",
        description=_CONNECTION_DESCRIPTION,
    )]


def _check_workday_da_user_context(runner) -> list[CheckResult]:
    """WD-DA-CTX-001: setup redirects to an enabled Workday V2 topic."""
    env_url = getattr(runner, "env_url", None)
    token = getattr(runner, "dv_token", None)
    selected = _selected_agent(runner)
    bot_id = selected[1].get("botId") if selected else None
    if not env_url or not token or not bot_id:
        return [_result(
            Status.SKIPPED.value,
            "Dataverse access or the active agent bot ID is unavailable.",
            remediation=(
                "Select the ESS HR agent, refresh Dataverse authentication, "
                "and rerun this check."
            ),
            checkpoint_id="WD-DA-CTX-001",
            description=_CONTEXT_DESCRIPTION,
        )]

    try:
        inspection = inspect_workday_da_user_context(
            env_url,
            token,
            str(bot_id),
        )
    except WorkdayDAUserContextError as exc:
        return [_result(
            Status.FAILED.value,
            f"Workday V2 user-context topics could not be resolved: {exc}",
            remediation=(
                "Open the active ESS HR agent's Topics page and verify that "
                f"both '{SETUP_TOPIC_NAME}' and '{TARGET_TOPIC_NAME}' exist "
                "exactly once."
            ),
            checkpoint_id="WD-DA-CTX-001",
            description=_CONTEXT_DESCRIPTION,
        )]
    except AuthExpiredError as exc:
        return [_result(
            Status.WARNING.value,
            str(exc),
            remediation="Refresh Dataverse authentication and rerun this check.",
            checkpoint_id="WD-DA-CTX-001",
            description=_CONTEXT_DESCRIPTION,
        )]
    except Exception as exc:  # noqa: BLE001 - surface external API failures
        return [_result(
            Status.WARNING.value,
            "Workday V2 user context could not be read: "
            f"{type(exc).__name__}: {exc}",
            remediation=(
                "Verify Dataverse read access to the active agent's topics and "
                "rerun this check."
            ),
            checkpoint_id="WD-DA-CTX-001",
            description=_CONTEXT_DESCRIPTION,
        )]

    if not inspection["redirectConfigured"]:
        return [_result(
            Status.FAILED.value,
            f"'{SETUP_TOPIC_NAME}' does not redirect exclusively to "
            f"'{TARGET_TOPIC_NAME}'.",
            remediation=(
                "Open the setup topic, select its topic reference, choose "
                f"'Select a topic', select '{TARGET_TOPIC_NAME}', and save."
            ),
            checkpoint_id="WD-DA-CTX-001",
            description=_CONTEXT_DESCRIPTION,
        )]
    if not inspection["targetTopicActive"]:
        return [_result(
            Status.FAILED.value,
            f"'{TARGET_TOPIC_NAME}' exists and is selected, but it is disabled.",
            remediation=(
                "Enable the Workday V2 user-context topic in Copilot Studio, "
                "save the agent, and rerun this check."
            ),
            checkpoint_id="WD-DA-CTX-001",
            description=_CONTEXT_DESCRIPTION,
        )]
    return [_result(
        Status.PASSED.value,
        f"'{SETUP_TOPIC_NAME}' redirects to the enabled "
        f"'{TARGET_TOPIC_NAME}'.",
        checkpoint_id="WD-DA-CTX-001",
        description=_CONTEXT_DESCRIPTION,
    )]


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

    architecture = architecture_for_agent_schema(
        selected_schema,
        definition=_WORKDAY_DEFINITION,
    )
    package_flavor = architecture["packageFlavor"]
    required_schema = _WORKDAY_DEFINITION["packages"][package_flavor][
        "solutionSchemaName"
    ]
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

    assessment = assess_package_version(
        package_flavor,
        child.get("version"),
        definition=_WORKDAY_DEFINITION,
    )
    if assessment.outcome == "invalid":
        return [_result(
            Status.FAILED.value,
            f"The Workday package required by the ESS HR agent is installed, "
            f"but its version cannot be validated: {assessment.message}",
            remediation=(
                "Repair or upgrade the Workday package, confirm Dataverse "
                "reports a four-part numeric solution version, and rerun this "
                "checkpoint."
            ),
        )]
    if assessment.outcome == "unsupported":
        return [_result(
            Status.FAILED.value,
            assessment.message,
            remediation=(
                "Upgrade or repair the Workday package to a version supported "
                "by this kit, then rerun this checkpoint."
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


def _result(
    status: str,
    result: str,
    remediation: str = "",
    *,
    checkpoint_id: str = "WD-DA-PKG-001",
    description: str = _DESCRIPTION,
) -> CheckResult:
    return CheckResult(
        roles=[Role.ESS_MAKER.value],
        checkpoint_id=checkpoint_id,
        category="Workday DA",
        priority=(
            Priority.CRITICAL.value
            if checkpoint_id == "WD-DA-PKG-001"
            else Priority.HIGH.value
        ),
        status=status,
        description=description,
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK,
    )


def _describe_solution(sol: dict) -> str:
    """Render one solution row as ``uniquename (vX.Y.Z)`` for the result text."""
    name = sol.get("uniquename", "<unknown>")
    version = sol.get("version")
    return f"{name} (v{version})" if version else name
