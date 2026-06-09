# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Publishing & QA Validation (PUB-xxx, QA-xxx)

These checks are organizational/process gates that the kit cannot
verify by reading an API (test sets live in Copilot Studio behind the
Analytics surface; managed-solution exports happen in the Power Apps
maker; UAT sign-off lives in the operator's change-management
system; M365 admin approval lives in the Microsoft 365 admin center).

Each check therefore emits ``Status.MANUAL`` — meaning "the kit has
nothing to check; the operator must confirm this themselves" — and
the remediation provides the concrete steps + best available deep
link for that specific action.

Bucketing: MANUAL routes to the "Needs manual verification" section
of the FlightCheck report. These checks never fail readiness.
"""

from ..runner import CheckResult, Status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
STUDIO_BASE = "https://copilotstudio.microsoft.com"
M365_INTEGRATED_APPS_URL = (
    "https://admin.microsoft.com/Adminportal/Home#/Settings/IntegratedApps"
)


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
    solutions = _maker_solutions_url(runner)
    publish_doc = f"{DOC_BASE}/publish"
    deploy_doc = f"{DOC_BASE}/deploy-overview-alm"
    evaluations_doc = f"{DOC_BASE}/evaluations"

    # Studio link as a markdown fragment ready to splice into prose,
    # or the literal phrase "Copilot Studio" when no deep link exists.
    studio_md = f"[Copilot Studio]({studio})" if studio else "Copilot Studio"
    solutions_md = (
        f"[Power Apps → Solutions]({solutions})"
        if solutions else "Power Apps → Solutions"
    )

    return [
        {
            "id": "QA-001",
            "p": "Critical",
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
            "desc": "Export your customization solution as a managed solution",
            "result": (
                "The kit can't inspect maker-portal solution exports — "
                "confirm a managed (.zip) export exists for promotion to test/UAT/prod."
            ),
            "remediation": (
                f"In {solutions_md} → select the solution that contains your "
                f"agent customizations → ⋯ → **Export solution** → **Publish** "
                f"(publish all customizations first) → **Next** → choose "
                f"**Managed** → **Export** → **Download**. Keep the .zip — "
                f"it's the artifact you import into test/UAT/prod. See the "
                f"[publish guide]({publish_doc}) for the full deployment flow."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-002",
            "p": "Critical",
            "desc": "Import the managed solution into a test environment",
            "result": (
                "The kit only sees the configured environment — "
                "confirm the managed solution was imported into a non-production environment and smoke-tested."
            ),
            "remediation": (
                "Switch to your test environment in the Power Apps maker → "
                "**Solutions** → **Import solution** → upload the managed .zip "
                "from PUB-001 → install any prompted dependencies (the ESS "
                "agent itself plus any connector solutions) → open the agent "
                f"and smoke-test a handful of representative prompts. See the "
                f"[publish guide]({publish_doc}) for the full deployment flow."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-003",
            "p": "Critical",
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
    """Return the publishing/QA checklist as MANUAL results.

    None of these checks reads an API — they're organizational gates
    or actions on portals the kit doesn't traverse. Emitting them as
    MANUAL (not NOT_CONFIGURED) keeps the report honest: nothing is
    misconfigured, the operator just has work the kit can't witness.
    """
    return [
        CheckResult(
            checkpoint_id=c["id"],
            category="Publishing",
            priority=c["p"],
            status=Status.MANUAL.value,
            description=c["desc"],
            result=c["result"],
            remediation=c["remediation"],
            doc_link=c["doc_link"],
        )
        for c in _build_checks(runner)
    ]
