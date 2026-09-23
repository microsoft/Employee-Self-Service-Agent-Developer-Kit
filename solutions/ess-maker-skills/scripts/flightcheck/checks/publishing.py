# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Publishing & QA Validation (PUB-xxx, QA-xxx)

Most checks are organizational/process gates that the kit cannot
verify by reading an API (test sets live in Copilot Studio behind the
Analytics surface; UAT sign-off lives in the operator's
change-management system; M365 admin approval lives in the Microsoft
365 admin center). PUB-001 and PUB-002 use the Copilot Studio
AgentBuilder ALM APIs when the required client is available.

Rows that the kit cannot verify still emit ``Status.MANUAL`` — meaning
"the operator must confirm this themselves" — and the remediation provides
the concrete steps plus best available deep link for that specific action.

Bucketing: MANUAL routes to the "Needs manual verification" section
of the FlightCheck report. PUB-001/PUB-002 can pass or fail readiness
when their API probes run.
"""

import tempfile
import zipfile
from pathlib import Path

from agentbuilder import AgentBuilderHTTPError

from ..runner import CheckResult, Role, Status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
STUDIO_BASE = "https://copilotstudio.microsoft.com"
M365_INTEGRATED_APPS_URL = (
    "https://admin.microsoft.com/Adminportal/Home#/Settings/IntegratedApps"
)
ALM_NOT_OPTED_IN_CODE = "4003"


def _studio_agent_url(runner) -> str | None:
    """Build a deep link to the first configured agent's Studio page.

    The publishing/QA checks are agent-scoped in spirit (the maker
    runs evaluations against a specific agent), but the result rows
    themselves are emitted once per checklist item — not per agent.
    We pick the first configured agent so the deep link lands on a
    real Studio surface rather than the generic homepage; if a tenant
    runs multi-agent the operator can switch from the agent picker.
    """
    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return None
    config = getattr(runner, "config", None) or {}
    bot_id = None
    for agent in config.get("agents", []) or []:
        bot_id = agent.get("botId")
        if bot_id:
            break
    if not bot_id:
        bot_id = (config.get("agent") or {}).get("botId")
    if not bot_id:
        return None
    return f"{STUDIO_BASE}/environments/{env_id}/bots/{bot_id}/overview"


def _maker_solutions_url(runner) -> str | None:
    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return None
    return f"https://make.powerapps.com/environments/{env_id}/solutions"


def _configured_bot_id(runner) -> str | None:
    config = getattr(runner, "config", None) or {}
    for agent in config.get("agents", []) or []:
        bot_id = agent.get("botId")
        if bot_id:
            return str(bot_id)
    bot_id = (config.get("agent") or {}).get("botId")
    return str(bot_id) if bot_id else None


def _api_result(
    *,
    checkpoint_id: str,
    row: dict,
    status: Status,
    result: str,
    remediation: str,
) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category="Publishing",
        priority=row["p"],
        status=status.value,
        description=row["desc"],
        result=result,
        remediation=remediation,
        doc_link=row["doc_link"],
        roles=row["roles"],
    )


def _agentbuilder_unavailable(checkpoint_id: str, row: dict) -> CheckResult:
    fallback = (
        f" Manual fallback: {row['remediation']}"
        if row.get("remediation")
        else ""
    )
    return _api_result(
        checkpoint_id=checkpoint_id,
        row=row,
        status=Status.SKIPPED,
        result="Copilot Studio AgentBuilder ALM client is unavailable for this run.",
        remediation=(
            "Re-run FlightCheck in a scope that authenticates the Copilot Studio "
            "AgentBuilder Power Platform API client, and make sure the "
            f"environment ID can be resolved.{fallback}"
        ),
    )


def _bot_id_missing(checkpoint_id: str, row: dict) -> CheckResult:
    return _api_result(
        checkpoint_id=checkpoint_id,
        row=row,
        status=Status.SKIPPED,
        result="No configured agent botId was found in .local/config.json.",
        remediation=(
            "Run /setup or update .local/config.json so the active ESS agent has "
            "a botId, then re-run FlightCheck."
        ),
    )


def _is_alm_not_opted_in(error: Exception) -> bool:
    if not isinstance(error, AgentBuilderHTTPError):
        return False
    code = str(error.error_code or "").strip()
    if code == ALM_NOT_OPTED_IN_CODE:
        return True
    response = error.response
    if response is None:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return ALM_NOT_OPTED_IN_CODE in str(body)


def _invalid_archive_reason(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if not names:
                return "the package archive has no entries"
            for name in names:
                entry = Path(name)
                if (
                    name.startswith(("/", "\\"))
                    or entry.is_absolute()
                    or ".." in entry.parts
                ):
                    return f"the package archive contains unsafe entry {name!r}"
            first_bad = archive.testzip()
            if first_bad is not None:
                return f"CRC validation failed for {first_bad!r}"
    except zipfile.BadZipFile:
        return "the response is not a valid zip archive"
    return None


def _check_pub_001_export(runner, row: dict) -> CheckResult:
    client = getattr(runner, "agentbuilder", None)
    if client is None:
        return _agentbuilder_unavailable("PUB-001", row)

    bot_id = _configured_bot_id(runner)
    if not bot_id:
        return _bot_id_missing("PUB-001", row)

    with tempfile.TemporaryDirectory(prefix="flightcheck-pub001-") as tmp:
        package_path = Path(tmp) / "agent.zip"
        try:
            client.export_package(bot_id, package_path)
        except Exception as exc:  # noqa: BLE001 - report as a verdict row
            if _is_alm_not_opted_in(exc):
                return _api_result(
                    checkpoint_id="PUB-001",
                    row=row,
                    status=Status.FAILED,
                    result=(
                        f"AgentBuilder ALM export returned {ALM_NOT_OPTED_IN_CODE} "
                        f"for configured agent {bot_id}; the agent is not enrolled "
                        "in ALM."
                    ),
                    remediation=(
                        "Open the agent in Copilot Studio, go to Settings > ALM, "
                        "enroll the agent, then re-run PUB-001."
                    ),
                )
            return _api_result(
                checkpoint_id="PUB-001",
                row=row,
                status=Status.WARNING,
                result=(
                    f"AgentBuilder ALM export failed for configured agent {bot_id}: "
                    f"{exc}"
                ),
                remediation=(
                    "Confirm the signed-in maker can export this agent through "
                    "Copilot Studio ALM, then re-run PUB-001."
                ),
            )

        if not package_path.exists() or package_path.stat().st_size == 0:
            return _api_result(
                checkpoint_id="PUB-001",
                row=row,
                status=Status.FAILED,
                result=(
                    f"AgentBuilder ALM export returned an empty package for {bot_id}."
                ),
                remediation=(
                    "Open the agent in Copilot Studio and confirm it can be "
                    "exported. If export still returns no bytes, fix the "
                    "agent/package issue before promotion."
                ),
            )

        invalid_reason = _invalid_archive_reason(package_path)
        if invalid_reason is not None:
            return _api_result(
                checkpoint_id="PUB-001",
                row=row,
                status=Status.FAILED,
                result=(
                    f"AgentBuilder ALM export returned {package_path.stat().st_size} "
                    f"bytes for {bot_id}, but {invalid_reason}."
                ),
                remediation=(
                    "Re-run export from Copilot Studio. The promotion artifact "
                    "must be a readable .zip package whose central directory and "
                    "CRC checks pass."
                ),
            )

        return _api_result(
            checkpoint_id="PUB-001",
            row=row,
            status=Status.PASSED,
            result=(
                f"AgentBuilder ALM export returned a valid zip package for {bot_id} "
                f"({package_path.stat().st_size} bytes)."
            ),
            remediation="",
        )


def _pub_002_requires_opt_in(row: dict) -> CheckResult:
    return _api_result(
        checkpoint_id="PUB-002",
        row=row,
        status=Status.SKIPPED,
        result=(
            "PUB-002 did not run because the AgentBuilder ALM import probe was "
            "not explicitly enabled. FlightCheck stayed read-only and did not "
            "create anything."
        ),
        remediation=(
            "Run PUB-002 only against a throwaway environment where ALM import "
            "is safe, then enable the import probe in the caller. Manual "
            f"fallback: {row['remediation']}"
        ),
    )


def _check_pub_002_import(runner, row: dict) -> CheckResult:
    if not bool(getattr(runner, "alm_import_probe", False)):
        return _pub_002_requires_opt_in(row)

    client = getattr(runner, "agentbuilder", None)
    if client is None:
        return _agentbuilder_unavailable("PUB-002", row)

    bot_id = _configured_bot_id(runner)
    if not bot_id:
        return _bot_id_missing("PUB-002", row)

    with tempfile.TemporaryDirectory(prefix="flightcheck-pub002-") as tmp:
        package_path = Path(tmp) / "agent.zip"
        try:
            client.export_package(bot_id, package_path)
        except Exception as exc:  # noqa: BLE001 - report as a verdict row
            if _is_alm_not_opted_in(exc):
                return _api_result(
                    checkpoint_id="PUB-002",
                    row=row,
                    status=Status.FAILED,
                    result=(
                        f"AgentBuilder ALM export returned {ALM_NOT_OPTED_IN_CODE} "
                        f"for configured agent {bot_id}; PUB-002 could not obtain "
                        "an import package."
                    ),
                    remediation=(
                        "Open the source agent in Copilot Studio, go to "
                        "Settings > ALM, enroll the agent, then re-run PUB-002 "
                        "against a throwaway environment."
                    ),
                )
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.WARNING,
                result=(
                    f"AgentBuilder ALM export failed before import for {bot_id}: "
                    f"{exc}"
                ),
                remediation=(
                    "Fix PUB-001 first. PUB-002 needs the source agent's exported "
                    ".zip package before it can test import."
                ),
            )

        invalid_reason = _invalid_archive_reason(package_path)
        if invalid_reason is not None:
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=(
                    f"PUB-002 could not use the exported ALM package because "
                    f"{invalid_reason}."
                ),
                remediation=(
                    "Fix PUB-001 first. PUB-002 imports the same exported .zip "
                    "package and requires the archive validation to pass."
                ),
            )

        try:
            outcome = client.import_package(package_path)
        except Exception as exc:  # noqa: BLE001 - report as a verdict row
            if _is_alm_not_opted_in(exc):
                return _api_result(
                    checkpoint_id="PUB-002",
                    row=row,
                    status=Status.FAILED,
                    result=(
                        f"AgentBuilder ALM import returned {ALM_NOT_OPTED_IN_CODE}; "
                        "the target agent/environment is not enrolled in ALM."
                    ),
                    remediation=(
                        "Use a throwaway environment with ALM enabled, then "
                        "re-run PUB-002. Do not run the import probe against a "
                        "production environment."
                    ),
                )
            if isinstance(exc, AgentBuilderHTTPError) and exc.status_code == 409:
                return _api_result(
                    checkpoint_id="PUB-002",
                    row=row,
                    status=Status.FAILED,
                    result=(
                        "AgentBuilder ALM import returned HTTP 409. The package "
                        "appears to conflict with an agent/schema already present "
                        "in the target environment."
                    ),
                    remediation=(
                        "Run PUB-002 in a throwaway environment that does not "
                        "already contain this exported agent, or clear the "
                        "conflicting test import before retrying."
                    ),
                )
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.WARNING,
                result=f"AgentBuilder ALM import failed: {exc}",
                remediation=(
                    "Confirm the maker has import permission and the target "
                    "throwaway environment has AgentBuilder ALM enabled."
                ),
            )

        if not isinstance(outcome, dict):
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result="AgentBuilder ALM import returned a non-object response.",
                remediation=(
                    "Retry the import after confirming the AgentBuilder ALM API "
                    "is returning the documented import response shape."
                ),
            )

        if outcome.get("responseStatus") != "valid":
            reason = str(outcome.get("reason") or "unknown")
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=f"AgentBuilder ALM import returned invalid response: {reason}.",
                remediation=(
                    "Treat the import as failed. The API must return a valid "
                    "imported agent identity before promotion."
                ),
            )

        imported = outcome.get("result")
        if not isinstance(imported, dict):
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result="AgentBuilder ALM import did not return imported agent details.",
                remediation=(
                    "Treat the import as failed. The API must return cdsBotId "
                    "and schemaName for the imported agent."
                ),
            )
        imported_bot_id = str(imported.get("cdsBotId") or "").strip()
        schema_name = str(imported.get("schemaName") or "").strip()
        if not imported_bot_id or not schema_name:
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=(
                    "AgentBuilder ALM import did not return both cdsBotId and "
                    "schemaName for the imported agent."
                ),
                remediation=(
                    "Treat the import as failed. The API must return the "
                    "imported agent identity before promotion."
                ),
            )

        return _api_result(
            checkpoint_id="PUB-002",
            row=row,
            status=Status.PASSED,
            result=(
                f"AgentBuilder ALM import created agent {imported_bot_id} "
                f"with schema {schema_name}."
            ),
            remediation="",
        )


def _qa_remediation(runner, action: str, doc_anchor: str) -> str:
    """Build a QA-* remediation that points at Copilot Studio Analytics
    when the deep link is available, falling back to documentation."""
    studio = _studio_agent_url(runner)
    if studio:
        return (
            f"{action} Open the agent in [Copilot Studio]({studio}) → "
            f"**Analytics → Evaluations**. "
            f"See [{doc_anchor}]({DOC_BASE}/evaluations) for guidance on "
            f"building test sets and interpreting results."
        )
    return (
        f"{action} In Copilot Studio open your agent → **Analytics → "
        f"Evaluations**. See [{doc_anchor}]({DOC_BASE}/evaluations) for "
        f"guidance on building test sets and interpreting results."
    )


def _build_checks(runner) -> list[dict]:
    """Per-check authored content. Constructed at call-time so deep
    links can incorporate the runner's environment / agent IDs."""
    studio = _studio_agent_url(runner)
    publish_doc = f"{DOC_BASE}/publish"
    deploy_doc = f"{DOC_BASE}/deploy-overview-alm"
    evaluations_doc = f"{DOC_BASE}/evaluations"

    # Studio link as a markdown fragment ready to splice into prose,
    # or the literal phrase "Copilot Studio" when no deep link exists.
    studio_md = f"[Copilot Studio]({studio})" if studio else "Copilot Studio"

    return [
        {
            "id": "QA-001",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Build a library of ≥50 evaluation prompts (golden queries)",
            "result": (
                "The kit can't inspect Copilot Studio evaluation test sets — "
                "confirm a library of ≥50 representative prompts exists for this agent."
            ),
            "remediation": _qa_remediation(
                runner,
                action=(
                    "Create at least one test set covering your top intents (PTO, "
                    "payroll, benefits, IT password reset, common policy lookups, "
                    "etc.) with ≥50 prompts in total."
                ),
                doc_anchor="ESS evaluations guide",
            ),
            "doc_link": evaluations_doc,
        },
        {
            "id": "QA-002",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Run the evaluation test set against the agent",
            "result": (
                "The kit can't read evaluation runs — "
                "confirm the golden-prompt test set was executed against this agent at least once."
            ),
            "remediation": _qa_remediation(
                runner,
                action=(
                    "Select your test set, click **Run evaluation**, wait for "
                    "the run to finish, and verify every prompt produced a "
                    "response (no agent errors / timeouts)."
                ),
                doc_anchor="ESS evaluations guide",
            ),
            "doc_link": evaluations_doc,
        },
        {
            "id": "QA-012",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Review evaluation scores against an accuracy target",
            "result": (
                "The kit can't measure response accuracy — "
                "confirm evaluation scores were reviewed against a target agreed with stakeholders."
            ),
            "remediation": _qa_remediation(
                runner,
                action=(
                    "Open the latest run, review per-prompt scores (groundedness, "
                    "relevance, completeness), record the accept rate, and confirm "
                    "it meets the target you agreed with business stakeholders "
                    "before promoting the agent."
                ),
                doc_anchor="ESS evaluations guide",
            ),
            "doc_link": evaluations_doc,
        },
        {
            "id": "PUB-001",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Export the agent's ALM package as a .zip from AgentBuilder",
            "result": (
                "The kit can't inspect AgentBuilder ALM package downloads — "
                "confirm the agent's ALM package .zip exists for promotion to test/UAT/prod."
            ),
            "remediation": (
                f"In {studio_md}, open the agent → **Settings** → **ALM**. "
                f"Enroll the agent if prompted, then export and download the "
                f"agent's ALM package .zip. Keep the .zip — it's the artifact "
                f"you import into test/UAT/prod. See the [publish guide]"
                f"({publish_doc}) for the full deployment flow."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-002",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            "desc": "Import the agent's ALM package into a test environment",
            "result": (
                "The kit only sees the configured environment — "
                "confirm the agent's ALM package was imported into a non-production environment and smoke-tested."
            ),
            "remediation": (
                "Switch to your test environment in Copilot Studio, open "
                "**Settings** → **ALM**, then import the agent's ALM package "
                ".zip from PUB-001. Install any prompted dependencies, open "
                "the imported agent, and smoke-test a handful of representative "
                f"prompts. See the [publish guide]({publish_doc}) for the full "
                f"deployment flow."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-003",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Complete UAT and capture business sign-off",
            "result": (
                "The kit can't track sign-off — "
                "confirm business stakeholders ran user-acceptance testing and recorded a pass decision."
            ),
            "remediation": (
                "Run a pilot with the business stakeholders who own the use "
                "cases the agent answers. Capture pass/fail decisions on the "
                "representative prompts you tested and record sign-off in "
                "your change-management system (release ticket, ADO work "
                "item, ServiceNow change, etc.) before promoting to "
                "production. This is an organizational gate — no portal link applies."
            ),
            "doc_link": deploy_doc,
        },
        {
            "id": "PUB-006",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value, Role.M365_ADMIN.value],
            "desc": "Obtain Microsoft 365 admin approval for the agent",
            "result": (
                "The kit can't read the Microsoft 365 admin center — "
                "confirm a tenant admin approved the publish request in Integrated apps."
            ),
            "remediation": (
                f"In {studio_md} → **Channels** → **Microsoft Teams** → "
                f"**Submit for admin approval** (the maker does this). Then a "
                f"tenant admin opens the "
                f"[Microsoft 365 admin center → Settings → Integrated apps]"
                f"({M365_INTEGRATED_APPS_URL}) → **Review request** for the "
                f"agent → approves and deploys to the chosen user audience. "
                f"Until both steps complete the agent won't appear in users' "
                f"Microsoft 365 Copilot."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-011",
            "p": "Medium",
            "roles": [Role.M365_ADMIN.value],
            "desc": "Allow up to 48 hours for rollout to Microsoft 365 Copilot",
            "result": (
                "Informational — after admin approval, Teams/Microsoft 365 Copilot "
                "rollout to end users can take up to 48 hours."
            ),
            "remediation": (
                f"No action required at publish time. If the agent still isn't "
                f"visible to users in Microsoft 365 Copilot 48 hours after admin "
                f"approval, return to the "
                f"[Microsoft 365 admin center → Integrated apps]"
                f"({M365_INTEGRATED_APPS_URL}) and check the deployment status "
                f"for this agent."
            ),
            "doc_link": publish_doc,
        },
    ]


def run_publishing_checks(runner) -> list[CheckResult]:
    """Return publishing/QA checks, using AgentBuilder ALM where available.

    PUB-001 validates export without mutating the environment. PUB-002 is
    explicitly gated because import creates an agent in the target environment.
    """
    results: list[CheckResult] = []
    for c in _build_checks(runner):
        if c["id"] == "PUB-001":
            results.append(_check_pub_001_export(runner, c))
            continue
        if c["id"] == "PUB-002":
            results.append(_check_pub_002_import(runner, c))
            continue
        results.append(
            CheckResult(
                checkpoint_id=c["id"],
                category="Publishing",
                priority=c["p"],
                status=Status.MANUAL.value,
                description=c["desc"],
                result=c["result"],
                remediation=c["remediation"],
                doc_link=c["doc_link"],
                roles=c["roles"],
            )
        )
    return results
