# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Prerequisites Validation (PRE-xxx)

Checks Microsoft 365 Copilot licenses, Copilot Studio licenses, Teams
licenses, role assignments, and capacity.
"""

from auth import AuthExpiredError

from ..runner import CheckResult, Priority, Role, Status
from .licensing import resolve_shared_with_users

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def _sku_matches(sku: dict, patterns: tuple[str, ...]) -> bool:
    """Case-insensitive substring match against `skuPartNumber`.

    Graph returns `skuPartNumber` in mixed case (e.g. ``Microsoft_365_Copilot``)
    for many SKUs, while Microsoft's documented part numbers and most
    operator-facing references use UPPER_SNAKE_CASE (e.g.
    ``MICROSOFT_365_COPILOT``). A naive case-sensitive ``in`` check
    silently misses every license on tenants whose Graph response uses
    mixed case, which was the original behavior of these PRE-xxx
    checks and produced false-negative "No <X> licenses found" results
    even on properly-licensed tenants.
    """
    part = (sku.get("skuPartNumber") or "").upper()
    return any(p.upper() in part for p in patterns)


# Microsoft 365 Copilot SKU part numbers (and historical aliases).
M365_COPILOT_SKUS: tuple[str, ...] = (
    "MICROSOFT_365_COPILOT",
)

# Copilot Studio SKU part numbers. The M365 Copilot bundle also
# includes Copilot Studio message capacity, so it counts as a source
# of Copilot Studio entitlement for prerequisite-check purposes.
COPILOT_STUDIO_SKUS: tuple[str, ...] = (
    "COPILOT_STUDIO",                  # forward-compatible Studio SKUs
    "MICROSOFT_COPILOT_STUDIO",        # alternate naming convention
    "POWER_VIRTUAL_AGENTS",            # legacy PVA SKUs (PVA_VIRAL, etc.)
    "CCIBOTS_PRIVPREV_VIRAL",          # original PVA preview SKU
    "MICROSOFT_365_COPILOT",           # M365 Copilot bundle includes Studio messages
)

# SKUs that carry Microsoft Teams entitlement, including bundles
# whose part numbers do not literally contain "TEAMS".
TEAMS_BEARING_SKUS: tuple[str, ...] = (
    "TEAMS",                           # standalone Teams SKUs (TEAMS_EXPLORATORY, TEAMS_FREE_*, etc.)
    "O365_BUSINESS_PREMIUM",           # M365 Business Standard
    "O365_BUSINESS_ESSENTIALS",        # M365 Business Basic
    "SPB",                             # M365 Business Premium
    "M365_BUSINESS_PREMIUM",
    "ENTERPRISEPACK",                  # Office 365 E3
    "ENTERPRISEPREMIUM",               # Office 365 E5
    "SPE_E3",                          # Microsoft 365 E3
    "SPE_E5",                          # Microsoft 365 E5
    "DEVELOPERPACK_E5",                # M365 E5 Developer
)


def _env_ids_match(a: str | None, b: str | None) -> bool:
    """Case-insensitive match of two Power Platform environment ids.

    The billing-policy-environment API returns ``environmentId`` and the
    runner carries ``env_id``; both name the same BAP environment but may
    differ only in casing across surfaces.
    """
    if not a or not b:
        return False
    return str(a).strip().lower() == str(b).strip().lower()


def _has_prepaid_messages(graph) -> bool | None:
    """Whether the tenant has Copilot Studio message capacity (prepaid model).

    PRE-005's pass criterion is "PayG OR prepaid messages present" (at least
    one billing model configured). The prepaid model for ESS is Copilot
    Studio message capacity: either a Copilot Studio plan (which includes a
    monthly message allotment) or prepaid capacity packs, both of which are
    tenant licenses surfaced by Microsoft Graph ``subscribedSkus``. We reuse
    the same ``COPILOT_STUDIO_SKUS`` signal PRE-002 uses rather than the
    undocumented ``$expand=capacity`` environment shape (which the heritage
    spec flagged as unreliable). Deep prepaid-balance validation is left to
    PRE-006.

    Returns:
      - ``True``  — at least one Copilot Studio message-bearing SKU is present.
      - ``False`` — Graph is reachable and no such SKU exists.
      - ``None``  — could not determine (no Graph client, or the call failed);
        the caller must not treat this as either present or absent.
    """
    if graph is None:
        return None
    try:
        skus = graph.get_subscribed_skus()
    except Exception:
        return None
    return any(_sku_matches(s, COPILOT_STUDIO_SKUS) for s in skus)


# Copilot Studio message capacity in the Power Platform Licensing
# "currency allocation" API (ExternalCurrencyType enum). The Sept 2025 rename
# to "Copilot Credits" did not change this API contract value.
_MCS_MESSAGES_CURRENCY = "MCSMessages"


def _env_mcs_allocation(powerplatform, env_id) -> int | None:
    """Copilot Studio message capacity allocated to *this* environment.

    ``_has_prepaid_messages`` is tenant-wide (Graph ``subscribedSkus``), so it
    cannot tell whether the *target* environment actually has capacity — only
    that the tenant owns some. This reads the per-environment prepaid
    allocation via the Power Platform Licensing currency-allocation API so
    PRE-005 can catch the case where a tenant holds capacity but none is
    allocated to the environment under test.

    Returns:
      - ``int``  — MCSMessages units allocated to the environment. ``0`` means
        the read succeeded and this environment has no dedicated allocation.
      - ``None`` — could not determine (no client, no env id, permission
        denied, or the call failed); the caller must fall back to the
        tenant-wide signal.
    """
    if powerplatform is None or not env_id:
        return None
    try:
        allocations = powerplatform.get_currency_allocations(env_id)
    except Exception:
        return None
    if isinstance(allocations, dict):  # {"_error": ...} sentinel
        return None
    total = 0
    for allocation in allocations:
        currency = str(allocation.get("currencyType") or "").strip().lower()
        if currency == _MCS_MESSAGES_CURRENCY.lower():
            try:
                total += int(allocation.get("allocated") or 0)
            except (TypeError, ValueError):
                continue
    return total


# The documented billing-policy API exposes a plan's linkage + bound
# subscription, but NOT which product meters the plan covers. So FlightCheck
# can confirm an environment is attached to a Pay-as-you-go plan and that the
# plan's subscription is healthy, but it cannot confirm the plan actually
# meters Copilot Studio agent messages. Stated verbatim so PRE-005 never
# implies more than the API proves.
PAYG_METER_CAVEAT = (
    "Note: the billing API doesn't expose plan meters, so this confirms the "
    "linkage and subscription health, not that the plan bills Copilot Studio "
    "agent messages."
)


def _payg_plan_scope(name: str, env_count: int) -> str:
    """Describe a PayG plan's linkage without implying per-environment intent.

    A plan linked to many environments is typically a tenant-wide admin
    setup, not something the maker configured for this one environment. The
    earlier wording ("linked to this environment") read as deliberate per-env
    intent and surprised operators whose environment was swept into a broad
    tenant plan, so we surface the breadth instead.
    """
    if env_count and env_count > 1:
        return (
            f"one of {env_count} environments linked to the tenant-level "
            f"Pay-as-you-go plan '{name}'"
        )
    return f"linked to the Pay-as-you-go plan '{name}'"


# Graph-dependent prerequisites, each as (checkpoint_id, description, role,
# doc anchor). Used to emit consistent SKIPPED results when the Microsoft
# Graph client is unavailable (see run_prerequisites_checks).
_GRAPH_PREREQ_CHECKS = (
    ("PRE-001", "Microsoft 365 Copilot licenses", Role.M365_ADMIN.value, "licensing"),
    ("PRE-002", "Copilot Studio licenses", Role.M365_ADMIN.value, "licensing"),
    ("PRE-003", "Microsoft Teams licenses", Role.M365_ADMIN.value, "licensing"),
    ("PRE-008", "Global Admin role assigned", Role.ENTRA_ADMIN.value, "required-roles"),
    ("PRE-009", "Power Platform Admin role assigned", Role.ENTRA_ADMIN.value, "required-roles"),
)


def _run_graph_prereq_checks(graph) -> list[CheckResult]:
    """Run the Graph-dependent prerequisites (PRE-001/002/003/008/009).

    Split out so run_prerequisites_checks can dispatch on Graph availability:
    when runner.graph is None these are reported as SKIPPED instead, mirroring
    AUTH-006 and PRE-005's other-client guards. Callers must pass a non-None,
    authenticated Graph client.
    """
    results: list[CheckResult] = []

    # ---- PRE-001: Microsoft 365 Copilot licenses ----
    try:
        skus = graph.get_subscribed_skus()
        copilot_skus = [s for s in skus if _sku_matches(s, M365_COPILOT_SKUS)]
        consumed = sum(s.get("consumedUnits", 0) for s in copilot_skus)
        enabled = sum(
            s.get("prepaidUnits", {}).get("enabled", 0) for s in copilot_skus
        )
        if copilot_skus and consumed > 0:
            results.append(CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="PRE-001", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft 365 Copilot licenses",
                result=f"Found {consumed} consumed / {enabled} enabled",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
        else:
            results.append(CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="PRE-001", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Microsoft 365 Copilot licenses",
                result="No M365 Copilot licenses found or none consumed",
                remediation="Purchase and assign M365 Copilot licenses in the [M365 admin center](https://admin.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="PRE-001", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Microsoft 365 Copilot licenses",
            result=f"Unable to check: {e}",
            remediation="Ensure permissions to read license info via Graph.",
            doc_link=f"{DOC_BASE}/prerequisites#licensing",
        ))

    # ---- PRE-002: Copilot Studio licenses ----
    try:
        skus = graph.get_subscribed_skus()
        cs_skus = [s for s in skus if _sku_matches(s, COPILOT_STUDIO_SKUS)]
        if cs_skus:
            names = ", ".join(s.get("skuPartNumber", "") for s in cs_skus)
            results.append(CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="PRE-002", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Copilot Studio licenses",
                result=f"Found: {names}",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
        else:
            results.append(CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="PRE-002", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Copilot Studio licenses",
                result="No Copilot Studio licenses found",
                remediation="Assign Copilot Studio licenses to admins/makers in the [M365 admin center](https://admin.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="PRE-002", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Copilot Studio licenses",
            result=f"Unable to check: {e}",
            remediation="Ensure Graph license read permissions.",
        ))

    # ---- PRE-003: Microsoft Teams licenses ----
    try:
        skus = graph.get_subscribed_skus()
        teams_skus = [s for s in skus if _sku_matches(s, TEAMS_BEARING_SKUS)]
        consumed = sum(s.get("consumedUnits", 0) for s in teams_skus)
        if teams_skus and consumed > 0:
            results.append(CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="PRE-003", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft Teams licenses",
                result=f"{consumed} users licensed for Teams",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
        else:
            results.append(CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="PRE-003", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description="Microsoft Teams licenses",
                result="No Teams licenses found or none consumed",
                remediation="Assign Teams licenses in the [M365 admin center](https://admin.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="PRE-003", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Microsoft Teams licenses",
            result=f"Unable to check: {e}",
        ))

    # ---- PRE-008: Global Admin role ----
    try:
        roles = graph.get_directory_roles()
        ga_role = next(
            (r for r in roles if r.get("displayName") == "Global Administrator"),
            None,
        )
        if ga_role:
            members = graph.get_role_members(ga_role["id"])
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="PRE-008", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Global Admin role assigned",
                result=f"Assigned to {len(members)} user(s)",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
        else:
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="PRE-008", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Global Admin role assigned",
                result="Global Administrator role not found",
                remediation="Assign Global Admin to at least one user.",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
            checkpoint_id="PRE-008", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Global Admin role assigned",
            result=f"Unable to check: {e}",
        ))

    # ---- PRE-009: Power Platform Admin role ----
    try:
        roles = graph.get_directory_roles()
        pp_role = next(
            (r for r in roles if "Power Platform" in r.get("displayName", "")),
            None,
        )
        if pp_role:
            members = graph.get_role_members(pp_role["id"])
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="PRE-009", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Power Platform Admin role assigned",
                result=f"Assigned to {len(members)} user(s)",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
        else:
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="PRE-009", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description="Power Platform Admin role assigned",
                result="Power Platform Administrator role not activated",
                remediation="Assign Power Platform Admin role in [Entra admin center](https://entra.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
            checkpoint_id="PRE-009", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Power Platform Admin role assigned",
            result=f"Unable to check: {e}",
        ))

    return results


# PRE-004 — Copilot Studio capacity. The prepaid-capacity / message-credit
# model is documented on the Copilot Studio "messages management" page; the ESS
# prerequisites doc links there for "Set up Copilot Studio capacity".
_CAPACITY_DOC = (
    "https://learn.microsoft.com/en-us/microsoft-copilot-studio/"
    "requirements-messages-management?tabs=new#prepaid-capacity"
)
_CAPACITY_PORTAL = (
    "[Power Platform Admin Center > Licensing > Copilot Studio > Manage capacity]"
    "(https://admin.powerplatform.microsoft.com/licensing)"
)
_M365_ADMIN_CENTER = "[Microsoft 365 admin center](https://admin.microsoft.com)"


def _pre004(status: str, result: str, remediation: str = "") -> CheckResult:
    """Build a PRE-004 row (every branch shares id / category / priority / role)."""
    return CheckResult(
        roles=[Role.POWER_PLATFORM_ADMIN.value],
        checkpoint_id="PRE-004", category="Prerequisites",
        priority=Priority.CRITICAL.value, status=status,
        description="Copilot Studio capacity configured",
        result=result, remediation=remediation, doc_link=_CAPACITY_DOC,
    )


def _check_copilot_studio_capacity(runner) -> CheckResult:
    """PRE-004 — Copilot Studio message capacity provisioned for the
    environment's shared/published user population.

    Heritage check (ESS Pre-flight Validator): ensure the target environment
    has Copilot Studio message capacity so ESS agent invocations have credits to
    consume. Ported with a per-environment *sufficiency* model rather than a
    bare non-zero check — it compares the message credits allocated to THIS
    environment against the number of users the agent is shared with / published
    to (resolved via the same Dataverse sharing enumeration LIC-FLOW-002 uses,
    expanding security groups to distinct Entra users).

    No Monthly-Active-User estimate is involved: the comparison is purely the
    per-environment allocation vs. the shared/published population. The repo
    carries no per-user message-consumption model, so the sufficiency floor is
    deliberately conservative — at least one Copilot Studio message credit per
    shared user. Real sufficiency depends on each user's message volume, which
    FlightCheck cannot predict, so a passing row reports the per-user ratio
    instead of asserting the allocation is enough for production traffic.

    Cross-checks PRE-005 via ``runner._payg_configured`` (set earlier in this
    same run): when Pay-as-you-go is configured, a zero/low allocation is a
    surprise-billing WARNING rather than a hard failure, because PayG still
    bills the usage. When neither prepaid capacity nor PayG covers the
    population, the row is a FAIL.

    Deliberate divergence from PRE-005: PRE-005 treats a zero per-env allocation
    with no PayG as a WARNING because a tenant-level "Draw from the available
    capacity in my tenant" overage *might* cover it (a toggle no API exposes).
    PRE-004 is stricter by design — it asserts capacity is actually provisioned
    *for the shared population*, so zero allocation with no PayG is a FAIL (the
    agent has users but no dedicated billing path).
    """
    try:
        # 1) Who is the agent shared with / published to in this environment?
        resolution = resolve_shared_with_users(runner)
        if not resolution.available:
            if resolution.reason == "no_bot_id":
                return _pre004(Status.SKIPPED.value,
                    "No agent botId is recorded in config, so FlightCheck can't determine who the agent is shared with — capacity sufficiency can't be assessed.",
                    "Run /setup so the agent's botId is recorded, then re-run FlightCheck.")
            return _pre004(Status.SKIPPED.value,
                "Determining the agent's shared/published user population needs Microsoft Graph + Dataverse access, which is unavailable.",
                "Re-run FlightCheck signed in with Microsoft Graph (Directory.Read.All) and Dataverse access so the shared user count can be read.")

        m = len(resolution.users)
        if m == 0:
            if resolution.enumerate_failed or resolution.undetermined:
                return _pre004(Status.WARNING.value,
                    "Could not determine the agent's shared/published user population: "
                    + "; ".join(resolution.undetermined[:6]) + ".",
                    "Verify FlightCheck has Dataverse + Graph read access, then re-run so Copilot Studio capacity sufficiency can be confirmed.")
            return _pre004(Status.PASSED.value,
                "The agent is not yet shared with or published to any users, so no Copilot Studio message capacity is required for this environment yet. (Counts users the agent is explicitly shared with; broad channel publishing may not be reflected — allocate capacity before a wide rollout.)")

        # 2) How much Copilot Studio message capacity is allocated to THIS env?
        allocated = _env_mcs_allocation(
            getattr(runner, "powerplatform", None), getattr(runner, "env_id", None))
        if allocated is None:
            return _pre004(Status.WARNING.value,
                f"The agent is shared/published to {m} user(s), but this environment's Copilot Studio message capacity allocation could not be read (Power Platform API unavailable or permission denied).",
                f"Grant the Power Platform Admin role (or sign in to the Power Platform API when prompted) so FlightCheck can read this environment's capacity allocation, then re-run. Review capacity in {_CAPACITY_PORTAL}.")

        # PRE-005 cross-check is read per-branch below (tri-state).

        if allocated > 0:
            if allocated >= m:
                return _pre004(Status.PASSED.value,
                    f"{allocated} Copilot Studio message credits are allocated to this environment for the {m} user(s) the agent is shared/published to (~{allocated // m} per user). Every shared user is backed by allocated capacity; actual sufficiency depends on per-user message volume.")
            # 0 < allocated < m: fewer credits than users breaches the one-per-user floor.
            return _pre004(Status.WARNING.value,
                f"Only {allocated} Copilot Studio message credit(s) are allocated to this environment for the {m} user(s) the agent is shared/published to — fewer than one credit per user, so the environment is under-provisioned and overflow will draw on overage or Pay-as-you-go (surprise-billing risk).",
                f"Allocate more Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}, or purchase additional prepaid message packs in the {_M365_ADMIN_CENTER}.")

        # allocated == 0: read succeeded; this environment has no dedicated credits.
        # PRE-005 cross-check is tri-state: True (PayG bills) / False (provably no
        # PayG) / None (PRE-005 did not run this pass — unknown, never assume).
        payg_flag = getattr(runner, "_payg_configured", None)
        if payg_flag is True:
            return _pre004(Status.WARNING.value,
                f"No prepaid Copilot Studio message capacity is allocated to this environment, but Pay-as-you-go billing is configured, so messages from all {m} shared/published user(s) bill directly to Azure (surprise-billing risk).",
                f"To cap spend, allocate prepaid Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}, or confirm a spending budget is in place for the Pay-as-you-go subscription (see PRE-005).")
        if payg_flag is None:
            # PRE-005 sets _payg_configured earlier in the run; None means it did
            # not run (PRE-004 invoked in isolation or reordered). An undetermined
            # PayG state must not become a hard FAIL -> WARN and point at the gap.
            return _pre004(Status.WARNING.value,
                f"No Copilot Studio message capacity is allocated to this environment for the {m} shared/published user(s), and Pay-as-you-go status could not be determined in this pass.",
                f"Run the full prerequisites scope so PRE-005 evaluates Pay-as-you-go, or allocate Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}.")
        # payg_flag is False: provably no PayG. Strict AC2 -> FAIL.
        # Surface the tenant-level pool too (the heritage check enumerates tenant
        # AND environment capacity): when the tenant owns capacity, the only way
        # this env runs is the "Draw from tenant capacity" overage — a toggle no
        # API exposes — so the FAIL stands (relying on an unreadable toggle for
        # production billing is the risk) but says so. This is the one state where
        # PRE-004 (FAIL) is intentionally stricter than PRE-005 (WARN).
        tenant_pool = _has_prepaid_messages(getattr(runner, "graph", None))
        tenant_note = (
            " The tenant holds Copilot Studio capacity, so the agent will run only if "
            "'Draw from the available capacity in my tenant' (Capacity overages) is "
            "enabled, which FlightCheck cannot read."
            if tenant_pool is True else ""
        )
        return _pre004(Status.FAILED.value,
            f"No Copilot Studio message capacity is allocated to this environment and Pay-as-you-go billing is not configured, so the {m} user(s) the agent is shared/published to have no message capacity to consume — agent invocations will fail at runtime.{tenant_note}",
            f"Allocate Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}, or purchase prepaid message packs in the {_M365_ADMIN_CENTER}; alternatively configure Pay-as-you-go billing (see PRE-005).")
    except AuthExpiredError:
        # Distinct, actionable failure — don't fold an expired session into the
        # generic "couldn't check" bucket. Kept non-fatal to PRE-004's siblings
        # (PRE-001..005); LIC-FLOW-002 re-raises the same error to hard-stop the
        # run when a blocking surface needs it.
        return _pre004(Status.WARNING.value,
            "The Dataverse session expired before Copilot Studio capacity could be checked.",
            "Re-run FlightCheck and sign in when prompted to refresh the session, then retry.")
    except Exception as e:
        # Mirror the PRE-001..003 per-check convention: a check that raises
        # degrades to its own WARNING row rather than bubbling up and turning the
        # whole Prerequisites category into a single ERROR (which would discard
        # PRE-001..005). Include the exception type so a genuine code bug isn't
        # hidden behind an environmental-looking warning during triage.
        return _pre004(Status.WARNING.value,
            f"Unable to check Copilot Studio capacity: {type(e).__name__}: {e}",
            "Ensure Power Platform Admin and Dataverse/Graph access, then re-run.")


def run_prerequisites_checks(runner) -> list[CheckResult]:
    """Execute all prerequisites checks using the Graph client."""
    graph = runner.graph
    results: list[CheckResult] = []

    # PRE-001/002/003/008/009 all require an authenticated Microsoft Graph
    # client. When Graph auth failed upstream (runner.graph is None), emit a
    # clean SKIPPED for each instead of letting the Graph calls raise
    # "Call authenticate() first" — the same convention AUTH-006 and PRE-005's
    # pp_admin/azure_arm guards use. PRE-005 below still runs: its only Graph
    # use (_has_prepaid_messages) already treats a missing client as
    # "could not determine".
    if graph is None:
        for cp_id, desc, role, doc_anchor in _GRAPH_PREREQ_CHECKS:
            results.append(CheckResult(roles=[role],
                checkpoint_id=cp_id, category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.SKIPPED.value,
                description=desc,
                result="Microsoft Graph client unavailable — skipping.",
                remediation="Re-run FlightCheck after Graph authentication succeeds.",
                doc_link=f"{DOC_BASE}/prerequisites#{doc_anchor}",
            ))
    else:
        results.extend(_run_graph_prereq_checks(graph))

    # ---- PRE-005: Pay-As-You-Go (PayG) configured if needed ----
    # Heritage pass criterion: at least one billing model is configured —
    # PayG OR prepaid Copilot Studio message capacity. Deterministic matrix
    # (no MANUAL), conservative on unknowns so we never emit a false WARN/FAIL:
    #   - PayG linked + Azure sub Enabled + budget present -> PASS
    #   - PayG linked + sub Enabled + NO budget -> WARN (no spending guardrail)
    #   - PayG linked + sub Enabled + budget unverifiable -> WARN (guardrail unknown)
    #   - PayG linked + sub Warned/PastDue/unverifiable -> WARN
    #   - PayG linked + sub Disabled/Deleted -> FAIL
    #   - No PayG linked + env has Copilot Studio capacity allocated -> PASS
    #   - No PayG linked + env allocation 0 + tenant has/unknown capacity -> WARN
    #     (may draw from tenant pool via Capacity overages; flag not in the API)
    #   - No PayG linked + no tenant capacity at all -> FAIL (AC2 neither)
    #   - No PayG linked + per-env allocation unreadable + tenant capacity -> PASS (caveat)
    #   - Could-not-determine (perm denied / Graph down) -> WARN
    # Backed by documented APIs: Power Platform billing policies
    # (runner.powerplatform), Azure subscription health + Consumption budgets
    # (runner.azure_arm), and Graph subscribedSkus (runner.graph, prepaid).
    payg_doc = (
        f"{DOC_BASE}/prerequisites"
        "#configure-pay-as-you-go-in-the-power-platform-administration-center-ppac"
    )
    payg_portal = (
        "[Power Platform Admin Center > Billing > Pay-as-you-go]"
        "(https://admin.powerplatform.microsoft.com/billing/payg)"
    )
    prepaid = _has_prepaid_messages(graph)
    payg_configured = False
    pp = getattr(runner, "powerplatform", None)
    payg_result: CheckResult | None = None
    if pp is None:
        if prepaid is True:
            payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="PRE-005", category="Prerequisites",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="Pay-as-you-go billing configured (if needed)",
                result="The Power Platform API was unavailable, so PayG linkage could not be read, but the tenant has Copilot Studio message capacity (a prepaid billing model is configured).",
                doc_link=payg_doc,
            )
        else:
            payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="PRE-005", category="Prerequisites",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description="Pay-as-you-go billing configured (if needed)",
                result="Power Platform API client unavailable; PayG billing-policy check skipped.",
                remediation="Sign in to the Power Platform API when prompted so FlightCheck can read billing policies, then re-run.",
                doc_link=payg_doc,
            )
    else:
        try:
            perm_error = False
            linked_policy = None
            linked_sub_id = None
            linked_env_count = 0
            linked_without_sub = False

            policies = pp.list_billing_policies()
            if isinstance(policies, dict) and "_error" in policies:
                perm_error = True
            else:
                # Status is a documented enum string; compare case-insensitively
                # for resilience (consistent with the env-id / currency-type
                # matching elsewhere in this check).
                enabled = [
                    p for p in policies
                    if (p.get("status") or "").strip().casefold() == "enabled"
                ]
                for p in enabled:
                    envs = pp.list_policy_environments(p.get("id"))
                    if isinstance(envs, dict) and "_error" in envs:
                        perm_error = True
                        break
                    if any(
                        _env_ids_match(e.get("environmentId"), getattr(runner, "env_id", None))
                        for e in envs
                    ):
                        sub_id = (p.get("billingInstrument") or {}).get("subscriptionId")
                        if sub_id:
                            linked_policy = p
                            linked_sub_id = sub_id
                            linked_env_count = len([e for e in envs if e.get("environmentId")])
                            break
                        linked_without_sub = True

            if perm_error:
                payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                    checkpoint_id="PRE-005", category="Prerequisites",
                    priority=Priority.HIGH.value, status=Status.WARNING.value,
                    description="Pay-as-you-go billing configured (if needed)",
                    result="Unable to determine Pay-as-you-go billing configuration (permission denied).",
                    remediation="Reading billing policies requires the Power Platform Admin role. Grant it (or run FlightCheck as an admin) and re-run.",
                    doc_link=payg_doc,
                )
            elif linked_policy is not None:
                name = linked_policy.get("name") or linked_policy.get("id") or "(unnamed)"
                arm = getattr(runner, "azure_arm", None)
                if arm is None:
                    payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                        checkpoint_id="PRE-005", category="Prerequisites",
                        priority=Priority.HIGH.value, status=Status.WARNING.value,
                        description="Pay-as-you-go billing configured (if needed)",
                        result=f"This environment is {_payg_plan_scope(name, linked_env_count)}, bound to Azure subscription {linked_sub_id}, but the subscription's health could not be verified (no Azure access).",
                        remediation=f"PayG appears configured. Confirm subscription {linked_sub_id} is Enabled in the [Azure portal](https://portal.azure.com); FlightCheck needs Reader on it to verify automatically.",
                        doc_link=payg_doc,
                    )
                else:
                    sub = arm.get_subscription(linked_sub_id)
                    if isinstance(sub, dict) and "_error" in sub:
                        payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                            checkpoint_id="PRE-005", category="Prerequisites",
                            priority=Priority.HIGH.value, status=Status.WARNING.value,
                            description="Pay-as-you-go billing configured (if needed)",
                            result=f"This environment is {_payg_plan_scope(name, linked_env_count)}, bound to Azure subscription {linked_sub_id}, but the subscription's health could not be verified (permission denied).",
                            remediation=f"PayG appears configured. Grant Reader on subscription {linked_sub_id} (or sign in to Azure when prompted) so FlightCheck can confirm it is Enabled, then re-run.",
                            doc_link=payg_doc,
                        )
                    else:
                        state = (sub.get("state") or "").strip()
                        # ARM returns canonical PascalCase states; normalize so a
                        # casing change can't silently flip the branch. The
                        # original `state` is kept for display in messages.
                        state_norm = state.casefold()
                        if state_norm == "enabled":
                            payg_configured = True
                            # PayG bills directly to Azure with no cap, so the
                            # spending guardrail (Azure budget) is the focus
                            # here. A tenant-wide prepaid balance is NOT cited:
                            # it does not help THIS environment unless the "draw
                            # from tenant capacity" overage is on (not readable
                            # via API), so mentioning it would be misleading.
                            # When the guardrail cannot be read, that is an
                            # unknown -> WARN (consistent with the rest of
                            # PRE-005), not a silent PASS.
                            budgets = arm.list_budgets(linked_sub_id)
                            if isinstance(budgets, list) and budgets:
                                payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                                    checkpoint_id="PRE-005", category="Prerequisites",
                                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                                    description="Pay-as-you-go billing configured (if needed)",
                                    result=f"This environment is {_payg_plan_scope(name, linked_env_count)} (Enabled), bound to a healthy Azure subscription {linked_sub_id}; a spending guardrail (Azure budget) is configured. {PAYG_METER_CAVEAT}",
                                    doc_link=payg_doc,
                                )
                            elif isinstance(budgets, list):
                                payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                                    checkpoint_id="PRE-005", category="Prerequisites",
                                    priority=Priority.HIGH.value, status=Status.WARNING.value,
                                    description="Pay-as-you-go billing configured (if needed)",
                                    result=f"This environment is {_payg_plan_scope(name, linked_env_count)} (Enabled, healthy subscription {linked_sub_id}), but no Azure spending budget is configured.",
                                    remediation=f"Hardening recommendation (not a functional blocker): PayG usage bills directly to Azure with no cap, so a runaway consumption spike goes unbilled-checked. Configure a budget/cost alert on subscription {linked_sub_id} in the [Azure Cost Management portal](https://portal.azure.com/#view/Microsoft_Azure_CostManagement), then re-run.",
                                    doc_link=payg_doc,
                                )
                            else:
                                payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                                    checkpoint_id="PRE-005", category="Prerequisites",
                                    priority=Priority.HIGH.value, status=Status.WARNING.value,
                                    description="Pay-as-you-go billing configured (if needed)",
                                    result=f"This environment is {_payg_plan_scope(name, linked_env_count)} (Enabled, healthy subscription {linked_sub_id}), but FlightCheck could not verify whether an Azure spending budget (spending guardrail) is configured.",
                                    remediation=f"PayG usage bills directly to Azure with no cap. Grant Cost Management Reader on subscription {linked_sub_id} so FlightCheck can confirm a spending budget, or verify/configure one in the [Azure Cost Management portal](https://portal.azure.com/#view/Microsoft_Azure_CostManagement), then re-run.",
                                    doc_link=payg_doc,
                                )
                        elif state_norm in ("warned", "pastdue"):
                            payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                                checkpoint_id="PRE-005", category="Prerequisites",
                                priority=Priority.HIGH.value, status=Status.WARNING.value,
                                description="Pay-as-you-go billing configured (if needed)",
                                result=f"This environment is {_payg_plan_scope(name, linked_env_count)}, bound to Azure subscription {linked_sub_id}, but the subscription state is '{state}'.",
                                remediation=f"Functional risk: a '{state}' subscription can be suspended, which would stop PayG billing for this environment. Resolve the billing/payment issue on subscription {linked_sub_id} in the [Azure portal](https://portal.azure.com), then re-run.",
                                doc_link=payg_doc,
                            )
                        elif state_norm in ("disabled", "deleted"):
                            payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                                checkpoint_id="PRE-005", category="Prerequisites",
                                priority=Priority.HIGH.value, status=Status.FAILED.value,
                                description="Pay-as-you-go billing configured (if needed)",
                                result=f"This environment is {_payg_plan_scope(name, linked_env_count)} but its Azure subscription {linked_sub_id} is in state '{state}'.",
                                remediation=f"A PayG environment whose Azure subscription is '{state}' cannot bill agent message consumption, so agent runs fail or silently fall back to prepaid capacity. Re-enable or replace the subscription, then re-link it in {payg_portal}.",
                                doc_link=payg_doc,
                            )
                        else:
                            payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                                checkpoint_id="PRE-005", category="Prerequisites",
                                priority=Priority.HIGH.value, status=Status.WARNING.value,
                                description="Pay-as-you-go billing configured (if needed)",
                                result=f"This environment is {_payg_plan_scope(name, linked_env_count)}, bound to Azure subscription {linked_sub_id}, but the subscription returned an unrecognized state '{state or '(empty)'}'.",
                                remediation=f"Confirm subscription {linked_sub_id} is Enabled in the [Azure portal](https://portal.azure.com), then re-run.",
                                doc_link=payg_doc,
                            )
            elif linked_without_sub:
                payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                    checkpoint_id="PRE-005", category="Prerequisites",
                    priority=Priority.HIGH.value, status=Status.WARNING.value,
                    description="Pay-as-you-go billing configured (if needed)",
                    result="An Enabled billing policy is linked to this environment but has no Azure subscription bound (billingInstrument.subscriptionId is empty).",
                    remediation=f"Finish the PayG setup by linking an Azure subscription to the billing policy in {payg_portal}.",
                    doc_link=payg_doc,
                )
            else:
                # No PayG plan linked. The authoritative question is whether
                # THIS environment has prepaid Copilot Studio capacity, not
                # whether the tenant owns some. Prefer the per-environment
                # allocation API; fall back to the tenant-wide subscribedSkus
                # signal only when the per-env read is unavailable.
                env_alloc = _env_mcs_allocation(pp, getattr(runner, "env_id", None))
                capacity_portal = (
                    "[Power Platform Admin Center > Licensing > Copilot Studio > Manage capacity]"
                    "(https://admin.powerplatform.microsoft.com/licensing)"
                )
                if env_alloc is not None and env_alloc > 0:
                    payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                        checkpoint_id="PRE-005", category="Prerequisites",
                        priority=Priority.HIGH.value, status=Status.PASSED.value,
                        description="Pay-as-you-go billing configured (if needed)",
                        result=f"No Pay-as-you-go billing plan is linked to this environment, but it has {env_alloc} Copilot Studio message credits allocated (a prepaid billing model). PayG is not required.",
                        doc_link=payg_doc,
                    )
                elif prepaid is False:
                    payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                        checkpoint_id="PRE-005", category="Prerequisites",
                        priority=Priority.HIGH.value, status=Status.FAILED.value,
                        description="Pay-as-you-go billing configured (if needed)",
                        result="Neither Pay-as-you-go billing nor Copilot Studio message capacity is configured for this environment, so agent message consumption cannot be billed and agent runs will fail.",
                        remediation=f"Configure at least one billing model: either link an Azure subscription for Pay-as-you-go in {payg_portal} (and choose Copilot Studio as the product), or purchase Copilot Studio prepaid message capacity in the [Microsoft 365 admin center](https://admin.microsoft.com).",
                        doc_link=payg_doc,
                    )
                elif env_alloc == 0:
                    # Per-env read succeeded: this environment has zero
                    # dedicated allocation. This is NOT a hard fail. If "Draw
                    # from the available capacity in my tenant" is enabled under
                    # Capacity overages and the tenant pool has headroom, agents
                    # still run (hard enforcement only triggers at 125% of the
                    # tenant's prepaid capacity). That overage flag is not
                    # exposed by the allocations API, so FlightCheck cannot
                    # confirm it -> WARN, not FAIL. (The prepaid-False case, no
                    # tenant capacity at all, already failed in the branch
                    # above.)
                    tenant_note = (
                        " The tenant holds Copilot Studio capacity, so this environment may still run by drawing from the tenant pool."
                        if prepaid is True else ""
                    )
                    payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                        checkpoint_id="PRE-005", category="Prerequisites",
                        priority=Priority.HIGH.value, status=Status.WARNING.value,
                        description="Pay-as-you-go billing configured (if needed)",
                        result=f"No Pay-as-you-go billing plan is linked to this environment and no Copilot Studio message capacity is allocated to it.{tenant_note} It will only bill if 'Draw from the available capacity in my tenant' is enabled under Capacity overages (and tenant capacity remains), which FlightCheck cannot read.",
                        remediation=f"Confirm 'Draw from the available capacity in my tenant' is enabled (Capacity overages) or allocate Copilot Studio message capacity to this environment in {capacity_portal}; alternatively, link an Azure subscription for Pay-as-you-go in {payg_portal}.",
                        doc_link=payg_doc,
                    )
                elif prepaid is True:
                    # Per-env allocation unreadable (None), but the tenant owns
                    # capacity. Soft PASS with an explicit caveat so per-env
                    # allocation setups still get a nudge to verify.
                    payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                        checkpoint_id="PRE-005", category="Prerequisites",
                        priority=Priority.HIGH.value, status=Status.PASSED.value,
                        description="Pay-as-you-go billing configured (if needed)",
                        result="No Pay-as-you-go billing plan is linked to this environment, but the tenant has Copilot Studio prepaid message capacity. FlightCheck could not read this environment's allocation; if your tenant allocates capacity per environment, confirm this environment has an allocation.",
                        doc_link=payg_doc,
                    )
                else:
                    payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                        checkpoint_id="PRE-005", category="Prerequisites",
                        priority=Priority.HIGH.value, status=Status.WARNING.value,
                        description="Pay-as-you-go billing configured (if needed)",
                        result="No Pay-as-you-go billing plan is linked to this environment, and prepaid Copilot Studio message capacity could not be determined (Microsoft Graph was unavailable).",
                        remediation="Sign in to Microsoft Graph when prompted (or grant directory read) so FlightCheck can confirm Copilot Studio message capacity, then re-run.",
                        doc_link=payg_doc,
                    )
        except Exception as e:
            payg_result = CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="PRE-005", category="Prerequisites",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Pay-as-you-go billing configured (if needed)",
                result=f"Unable to check PayG configuration: {e}",
                remediation="Ensure Power Platform Admin access and retry.",
                doc_link=payg_doc,
            )

    if payg_result is not None:
        # Forward-compat flag for the PayG/prepaid/capacity cross-checks.
        # True only when PayG is genuinely linked + healthy (NOT when the
        # check passed on the prepaid arm), so the capacity/prepaid checks can
        # read it via getattr(runner, "_payg_configured", None) and treat True
        # as "PayG covers billing" (AGENTS.md principle #11). PRE-004 (capacity)
        # consumes it immediately below; PRE-006 (prepaid) will too.
        runner._payg_configured = payg_configured
        results.append(payg_result)

    # ---- PRE-004: Copilot Studio capacity for the shared/published population ----
    # Runs after PRE-005 so it can read runner._payg_configured (the PayG
    # cross-check). The report sorts by priority then id, so append order is
    # cosmetic — PRE-004 still renders in numeric order.
    results.append(_check_copilot_studio_capacity(runner))

    return results
