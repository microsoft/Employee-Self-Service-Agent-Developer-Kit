# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Cloud Policies / Telemetry & Feedback (POL-FB-xxx)

Validates the two Microsoft 365 Cloud Policies (Office Cloud Policy Service,
managed in the Microsoft 365 Apps admin center → Policy Management) that gate
end-user Copilot feedback for the ESS deployment:

  POL-FB-001  "Allow users to send feedback to Microsoft about Microsoft 365
              apps"            — must be Enabled for the ESS deployment group.
  POL-FB-002  "Allow users to include screenshots and attachments when they
              submit feedback to Microsoft"
                               — should be Enabled for high-fidelity capture.

When feedback is enabled, end users see the thumbs up/down control on Copilot
responses; that signal is the primary closed-loop source for the FlightCheck
Trend Miner, IcM correlation, and product-quality improvement. When the
"Allow feedback" policy is Disabled / Not Configured for the deployment group,
the control silently disappears — no error, no failed request, no log entry —
so a maker can be unaware their tenant opted out of the quality signal.

Why these are MANUAL (Status.MANUAL), not automated PASS/FAIL
-------------------------------------------------------------
The Office Cloud Policy Service (OCPS) has NO supported programmatic way for
FlightCheck to read EFFECTIVE per-security-group feedback policy state:

  * There is no GA / publicly-documented Microsoft Graph endpoint for OCPS
    policy assignments (verified 2026-06 against MS Learn; the Cloud Policy
    overview documents a UI + Entra-role-based service only, with no API).
  * The admin center's private backend (``config.office.com/policyadmin/...``)
    sits behind Azure Application Gateway and rejects a service-acquired
    bearer (HTTP 403) without the browser's session cookies + Origin — there
    is no documented service-principal / app-permission auth path.

Per FlightCheck's design rule "no misleading results," a check that can only
authenticate during a manual cassette capture but SKIP/ERROR on every real
customer run is worse than no check. So these checkpoints follow the same
``Status.MANUAL`` pattern as the publishing checklist (``checks/publishing.py``):
the kit surfaces WHY the policy is worth verifying, HOW to verify it (portal
steps + deep link), and the verbatim data-sharing notice, then the operator
confirms the state in the Microsoft 365 Apps admin center. MANUAL items route
to the "Needs manual verification" section of the report and never fail
readiness.

Output framing for a MANUAL verification checkpoint
---------------------------------------------------
Because the operator isn't looking at a symptom — they're being asked to
confirm a setting — the rows do NOT lead with a "probable cause." Instead:

  * ``result`` = WHY this is worth verifying (the impact + the silent failure
    mode), so the operator understands the stakes before acting.
  * ``remediation`` = HOW to verify it: the role-aware deployment directive
    rendered as "How to verify" steps + "Scope + confidence" + "Still stuck?"
    (+ the verbatim data-sharing notice on POL-FB-001).

If Microsoft ships a GA programmatic OCPS policy API (e.g. the preview Graph
Tenant Configuration Management API reaching GA), these can be promoted to
automated checks — register the API in ``tests/fixtures/cassettes/INDEX.md``,
add an OCPS client, and replace the MANUAL bodies with effective-per-group
PASS/FAIL/WARN logic.
"""

from ..runner import CheckResult, Priority, Role, Status

# Checkpoint identifiers.
POL_FB_FEEDBACK = "POL-FB-001"
POL_FB_ATTACHMENTS = "POL-FB-002"

# Report category for these checkpoints.
CATEGORY = "Cloud Policies / Telemetry & Feedback"

# Verbatim Cloud Policy display names (as shown in the Microsoft 365 Apps
# admin center). Output names the policy by this exact string so the operator
# can find it without ambiguity.
POLICY_NAME_FEEDBACK = (
    "Allow users to send feedback to Microsoft about Microsoft 365 apps"
)
POLICY_NAME_ATTACHMENTS = (
    "Allow users to include screenshots and attachments when they submit "
    "feedback to Microsoft"
)

# Microsoft 365 Apps admin center (Office Cloud Policy Service) portal root.
# The navigation path (Policy Management → the configuration assigned to the
# ESS deployment group) is spelled out in remediation text rather than a
# fabricated deep URL.
M365_APPS_ADMIN_URL = "https://config.office.com/"

# Verified Microsoft Learn reference for the Cloud Policy service.
DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365-apps/admin-center/"
    "overview-cloud-policy"
)

# --------------------------------------------------------------------------
# Maker-facing data-sharing notice — VERBATIM. Surfaced whenever feedback is
# (or should be) enabled so the maker can lift it directly into their privacy
# documentation. Acceptance criteria require this exact wording; do not
# paraphrase. The same constant is reproduced verbatim in the FlightCheck
# remediation guide (remediation-guide.md); validation-matrix.md references it.
# --------------------------------------------------------------------------
MAKER_NOTICE = (
    "End-user feedback collected from Copilot responses in this deployment "
    "\u2014 including any verbatim text, screenshots, and attachments the "
    "end user chooses to include \u2014 will be shared with Microsoft for "
    "product-quality and support improvement purposes. Confirm that your "
    "organization's privacy notice and end-user training cover this data "
    "flow before launch."
)


def render_directive(
    *,
    how_to_verify: str,
    scope_confidence: str,
    still_stuck: str,
    notice: str | None = None,
) -> str:
    """Render the role-aware deployment-directive block for a MANUAL check.

    These checkpoints ask the operator to confirm a setting, not to diagnose a
    symptom they're already seeing — so the directive leads with "How to
    verify" (the actionable steps), not a "probable cause." The remaining
    role-aware sections follow: Scope + confidence (IT-admin scope, since
    Cloud Policy is admin-controlled) and Still stuck. When ``notice`` is
    supplied, the verbatim data-sharing notice is appended as a final section
    so it travels with the directive output, not just the console.

    The WHY of acting lives in the ``CheckResult.result`` field (the impact +
    silent-failure mode), per the result-vs-remediation contract.

    Args:
        how_to_verify: The concrete verification steps + deep link / nav path.
        scope_confidence: Who owns the check + that this is a manual confirm.
        still_stuck: The fallback if the setting looks right but feedback
            still doesn't behave as expected.
        notice: Optional verbatim notice to append (pass ``MAKER_NOTICE``).

    Returns:
        A markdown block with one bolded label per section.
    """
    sections = [
        f"**How to verify** \u2014 {how_to_verify}",
        f"**Scope + confidence** \u2014 {scope_confidence}",
        f"**Still stuck?** \u2014 {still_stuck}",
    ]
    if notice:
        sections.append(f"**Data-sharing notice** \u2014 {notice}")
    return "\n\n".join(sections)


# Shared scope/confidence line — identical for both checkpoints (Cloud Policy
# is admin-controlled and the kit can't read OCPS state programmatically).
_SCOPE_CONFIDENCE = (
    "IT admin scope \u2014 Cloud Policy is admin-controlled (Office Apps "
    "Administrator). FlightCheck cannot read Office Cloud Policy Service "
    "state programmatically, so this is a manual confirmation rather than an "
    "automated verdict."
)


def check_feedback_enabled(runner) -> CheckResult:
    """POL-FB-001 — "Allow feedback" Cloud Policy enabled for the group."""
    # result = WHY this is worth verifying (impact + silent failure mode).
    why = (
        "Thumbs up / down feedback on Copilot responses is the primary "
        "closed-loop quality signal for this deployment \u2014 it feeds the "
        "FlightCheck Trend Miner, IcM correlation, and product-quality "
        "improvements. End users only see the feedback control when "
        f'"{POLICY_NAME_FEEDBACK}" is Enabled for the security group that owns '
        "the deployment. If that cloud policy is Disabled or Not Configured "
        "the control disappears with no error, no failed request, and no log "
        "entry \u2014 so the tenant can opt out of the signal without anyone "
        "noticing. Worth confirming before launch."
    )
    how_to_verify = (
        f"In the [Microsoft 365 Apps admin center]({M365_APPS_ADMIN_URL}) "
        "\u2192 Policy Management, open the policy configuration assigned to "
        "the security group that owns the ESS Agent deployment, search its "
        'settings for "feedback", and confirm '
        f'"{POLICY_NAME_FEEDBACK}" is set to Enabled. If no policy '
        "configuration targets that group, create one (or assign an existing "
        "one) with this policy Enabled."
    )
    still_stuck = (
        "If the setting already looks correct but users still don't see the "
        "feedback control, confirm the policy configuration is assigned to "
        "the right security group and isn't overridden by a higher-priority "
        f"configuration. See {DOC_LINK} for how Cloud Policy resolves "
        "effective settings per group."
    )
    return CheckResult(
        checkpoint_id=POL_FB_FEEDBACK,
        category=CATEGORY,
        priority=Priority.HIGH.value,
        status=Status.MANUAL.value,
        description=(
            f'Cloud Policy "{POLICY_NAME_FEEDBACK}" Enabled for the ESS '
            "deployment group"
        ),
        result=why,
        remediation=render_directive(
            how_to_verify=how_to_verify,
            scope_confidence=_SCOPE_CONFIDENCE,
            still_stuck=still_stuck,
            notice=MAKER_NOTICE,
        ),
        doc_link=DOC_LINK,
        roles=[Role.M365_ADMIN.value],
    )


def check_feedback_attachments(runner) -> CheckResult:
    """POL-FB-002 — "Allow attachments" Cloud Policy enabled for the group."""
    why = (
        "Screenshots and attachments give the feedback signal its diagnostic "
        f'fidelity. "{POLICY_NAME_ATTACHMENTS}" controls whether end users '
        "can include them. If it is Disabled while feedback itself is Enabled, "
        "feedback still flows but arrives without the diagnostic context "
        "attachments provide \u2014 a lower-fidelity Trend Miner signal. This "
        "is a fidelity consideration, not a feedback blocker. Worth confirming "
        "before launch."
    )
    how_to_verify = (
        f"In the [Microsoft 365 Apps admin center]({M365_APPS_ADMIN_URL}) "
        "\u2192 Policy Management, open the policy configuration assigned to "
        "the ESS deployment group and confirm "
        f'"{POLICY_NAME_ATTACHMENTS}" is set to Enabled (on the same '
        "configuration where you enabled the feedback policy)."
    )
    still_stuck = (
        "Confirm the attachments policy is set on the same configuration that "
        f"targets the deployment group. See {DOC_LINK}. The data-sharing "
        "notice on POL-FB-001 already covers the screenshots/attachments this "
        "policy enables."
    )
    return CheckResult(
        checkpoint_id=POL_FB_ATTACHMENTS,
        category=CATEGORY,
        priority=Priority.HIGH.value,
        status=Status.MANUAL.value,
        description=(
            f'Cloud Policy "{POLICY_NAME_ATTACHMENTS}" Enabled for the ESS '
            "deployment group"
        ),
        result=why,
        remediation=render_directive(
            how_to_verify=how_to_verify,
            scope_confidence=_SCOPE_CONFIDENCE,
            still_stuck=still_stuck,
        ),
        doc_link=DOC_LINK,
        roles=[Role.M365_ADMIN.value],
    )


def run_cloud_policy_checks(runner) -> list[CheckResult]:
    """Run the Cloud Policies / Telemetry & Feedback checks (POL-FB-xxx).

    Both checkpoints are ``Status.MANUAL`` (see module docstring): ``result``
    explains WHY the policy is worth verifying, ``remediation`` explains HOW to
    verify it (portal steps) and carries the verbatim data-sharing notice.
    They never fail readiness.
    """
    return [
        check_feedback_enabled(runner),
        check_feedback_attachments(runner),
    ]
