# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ESS Solution Installation Validation (ESS-SOLN-xxx)

Verifies that the base ESS agent solution has been installed into the target
Power Platform environment (skill-2 ``install-ess``). The install itself is a
manual AppSource / admin-center action; this module supplies the *programmatic
verification* that the solution landed, runnable in isolation via
``--checkpoint ESS-SOLN-001``.
"""

from ..runner import CheckResult, Priority, Role, Status
from auth import query_all, AuthExpiredError  # scripts/auth.py, on path via cli.py


# The AppSource "Employee Self Service" offer installs a managed solution whose
# unique name starts with this prefix. Three variants ship today — the base
# agent plus IT and HR editions — and skill-6 references the same namespace:
#   msdyn_copilotforemployeeselfservice     (base)
#   msdyn_copilotforemployeeselfserviceit   (IT)
#   msdyn_copilotforemployeeselfservicehr   (HR)
# A ``startswith`` match accepts whichever edition the tenant deployed (and any
# future variant) in a single round-trip.
_ESS_SOLUTION_PREFIX = "msdyn_copilotforemployeeselfservice"
_ESS_SOLN_FILTER = f"startswith(uniquename,'{_ESS_SOLUTION_PREFIX}')"
_ESS_SOLN_SELECT = "solutionid,uniquename,friendlyname,ismanaged,version"

_ESS_SOLN_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install"
)
_ESS_SOLN_DESCRIPTION = "ESS base agent solution installed in the environment"


def run_solution_checks(runner) -> list[CheckResult]:
    """Emit the ESS-SOLN-xxx solution-installation checkpoints.

    Currently a single check (``ESS-SOLN-001``); kept as a category function so
    additional ESS-SOLN-* rows can be added without changing the registry /
    cli wiring.
    """
    return _check_ess_solution_installed(runner)


def _check_ess_solution_installed(runner) -> list[CheckResult]:
    """ESS-SOLN-001: the base ESS solution is installed in the target env.

    Always emits exactly one CheckResult (principle 7 — bucket multi-resource
    findings). Never raises — all errors are caught and turned into WARNING
    results so a transient Dataverse failure does not abort the whole
    flightcheck run.
    """
    env_url = getattr(runner, "env_url", None)
    token = getattr(runner, "dv_token", None)

    if not env_url or not token:
        return [CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="ESS-SOLN-001", category="Solution",
            priority=Priority.CRITICAL.value, status=Status.SKIPPED.value,
            description=_ESS_SOLN_DESCRIPTION,
            result="Dataverse URL or access token not available in this run.",
            doc_link=_ESS_SOLN_DOC_LINK,
        )]

    try:
        solutions = query_all(
            env_url, token,
            "solutions",
            _ESS_SOLN_SELECT,
            _ESS_SOLN_FILTER,
        )

        if not solutions:
            return [CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="ESS-SOLN-001", category="Solution",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description=_ESS_SOLN_DESCRIPTION,
                result=(
                    "No solution whose unique name starts with "
                    f"'{_ESS_SOLUTION_PREFIX}' is installed in this "
                    "environment. The base ESS agent is not present."
                ),
                remediation=(
                    "Install the Employee Self Service agent from AppSource "
                    "into this environment (Microsoft 365 admin center / "
                    "AppSource -> get 'Employee Self Service' -> deploy to the "
                    "target environment), wait for the solution import to "
                    "finish, then re-run this check."
                ),
                doc_link=_ESS_SOLN_DOC_LINK,
            )]

        installed = ", ".join(
            _describe_solution(s)
            for s in sorted(solutions, key=lambda s: s.get("uniquename", ""))
        )
        return [CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="ESS-SOLN-001", category="Solution",
            priority=Priority.CRITICAL.value, status=Status.PASSED.value,
            description=_ESS_SOLN_DESCRIPTION,
            result=f"ESS base agent solution installed: {installed}.",
            doc_link=_ESS_SOLN_DOC_LINK,
        )]

    except AuthExpiredError as e:
        return [CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="ESS-SOLN-001", category="Solution",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description=_ESS_SOLN_DESCRIPTION,
            result=str(e),
            remediation="Re-run FlightCheck to refresh the access token.",
            doc_link=_ESS_SOLN_DOC_LINK,
        )]
    except Exception as e:
        # Per principle 3 (fail loudly): surface unexpected Dataverse failures
        # as WARNING rather than silently passing. Surface the HTTP status
        # code when available so a 403 (insufficient privileges) is
        # distinguishable from a 5xx (transient) at a glance.
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        status_hint = f" [HTTP {status_code}]" if status_code is not None else ""
        return [CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="ESS-SOLN-001", category="Solution",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description=_ESS_SOLN_DESCRIPTION,
            result=(
                f"Unable to verify the ESS solution: "
                f"{type(e).__name__}{status_hint}: {e}"
            ),
            remediation=(
                "Inspect the error above; common causes are insufficient "
                "Dataverse privileges on the solutions table (typically "
                "surfaces as HTTP 403) or a transient platform error (HTTP 5xx)."
            ),
            doc_link=_ESS_SOLN_DOC_LINK,
        )]


def _describe_solution(sol: dict) -> str:
    """Render one solution row as ``uniquename (vX.Y.Z)`` for the result text."""
    name = sol.get("uniquename", "<unknown>")
    version = sol.get("version")
    return f"{name} (v{version})" if version else name
