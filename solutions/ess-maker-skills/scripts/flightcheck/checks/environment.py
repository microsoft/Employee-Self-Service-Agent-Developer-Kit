# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Environment Configuration Validation (ENV-xxx)

Checks Power Platform environment, Dataverse, DLP policies, and related config.
"""

import uuid

from ..runner import CheckResult, Priority, Role, Status
from ._da_connection_refs import (
    agent_bot_ids,
    read_all_agents_connection_references,
)
from ._dlp_utils import iter_effective_policies
from ._maker_urls import maker_solutions_url
from .licensing import (
    _CAPACITY_DOC,
    _CAPACITY_PORTAL,
    _env_mcs_allocation,
    classify_copilot_studio_capacity,
)
from auth import query_all, dataverse_get, AuthExpiredError  # scripts/auth.py, on path via cli.py

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


_ENV004_GRS_DESCRIPTION = "ESS agent GRS commit pin"
_ENV004_GRS_EXPECTED_COMMIT_KEYS = (
    "expectedGrsCommitSha",
    "grsExpectedCommitSha",
    "expectedMinimalBotsCommitSha",
    "expectedEssSolutionCommitSha",
)
_ENV004_GRS_REALM_KEYS = ("minimalBotsAlmRealm", "grsRealm", "almRealm")
_ENV004_GRS_DEFAULT_REALM = "Dev"
# Config realm string -> the numeric realm the AgentBuilder ALM configure API
# expects (mirrors agentbuilder.REALM_NAMES: 0=Dev, 1=Test, 2=Prod).
_ENV004_GRS_REALMS = {"dev": 0, "test": 1, "prod": 2, "production": 2}
_ENV004_REALM_DISPLAY = {0: "Dev", 1: "Test", 2: "Prod"}


def _env004_active_agent_config(config: dict) -> dict:
    """Return the active agent block from the setup config, if present."""
    if not isinstance(config, dict):
        return {}
    agent = config.get("agent")
    if isinstance(agent, dict) and agent:
        return agent

    agents = config.get("agents") or []
    active = config.get("activeAgent", "")
    if isinstance(agents, list):
        for candidate in agents:
            if isinstance(candidate, dict) and candidate.get("slug") == active:
                return candidate
        for candidate in agents:
            if isinstance(candidate, dict):
                return candidate
    return {}


def _env004_config_value(config: dict, keys: tuple[str, ...]) -> str:
    """Read a string setting from active-agent config first, then top-level."""
    active_agent = _env004_active_agent_config(config)
    for source in (active_agent, config):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _env004_grs_commit_pin_result(runner) -> CheckResult:
    """Validate the minimalBots ALM commit pin (ENV-004-GRS).

    Opt-in component-layer check: verifies the deployed Declarative Agent's ALM
    commit matches an expected GRS commit SHA when one is recorded in config.
    Validated-tier read (GET .../alm/{id}/configure?realm={int} -> ``commitSha``;
    cassette ``agentbuilder_readiness.yaml``). SKIPs when no expected SHA is
    configured (the pin is inert until an operator records the intended release
    commit), so this never blocks a run that does not use pinning.
    """
    config = getattr(runner, "config", None) or {}
    expected_commit = _env004_config_value(
        config, _ENV004_GRS_EXPECTED_COMMIT_KEYS
    )
    realm_raw = (
        _env004_config_value(config, _ENV004_GRS_REALM_KEYS)
        or _ENV004_GRS_DEFAULT_REALM
    )
    # 0 (Dev) is a valid realm and falsy, so test membership explicitly.
    realm = _ENV004_GRS_REALMS.get(realm_raw.lower())

    if not expected_commit:
        return CheckResult(
            roles=[Role.ESS_MAKER.value],
            checkpoint_id="ENV-004-GRS",
            category="Environment",
            priority=Priority.HIGH.value,
            status=Status.SKIPPED.value,
            description=_ENV004_GRS_DESCRIPTION,
            result=(
                "No expected GRS commit SHA is configured, so the minimalBots "
                "ALM commit pin was not judged."
            ),
            remediation=(
                "Record the expected ESS solution commit SHA in "
                ".local/config.json using expectedGrsCommitSha (top-level or on "
                "the active agent), then re-run FlightCheck."
            ),
        )

    if realm is None:
        return CheckResult(
            roles=[Role.ESS_MAKER.value],
            checkpoint_id="ENV-004-GRS",
            category="Environment",
            priority=Priority.HIGH.value,
            status=Status.FAILED.value,
            description=_ENV004_GRS_DESCRIPTION,
            result=(
                f"Configured minimalBots ALM realm '{realm_raw}' is invalid. "
                "Expected one of Dev, Test, or Prod."
            ),
            remediation=(
                "Set minimalBotsAlmRealm, grsRealm, or almRealm in "
                ".local/config.json to Dev, Test, or Prod."
            ),
        )

    realm_name = _ENV004_REALM_DISPLAY[realm]
    client = getattr(runner, "agentbuilder", None)
    bot_ids = agent_bot_ids(config)
    if client is None or not bot_ids:
        return CheckResult(
            roles=[Role.ESS_MAKER.value],
            checkpoint_id="ENV-004-GRS",
            category="Environment",
            priority=Priority.HIGH.value,
            status=Status.SKIPPED.value,
            description=_ENV004_GRS_DESCRIPTION,
            result=(
                "AgentBuilder client or agent botId not available, so the "
                "minimalBots ALM commit pin was not judged."
            ),
            remediation=(
                "Run /setup so .local/config.json records the agent botId, and "
                "ensure FlightCheck is signed in to Copilot Studio (AgentBuilder), "
                "then re-run FlightCheck."
            ),
        )

    mismatches: list[tuple[str, str]] = []
    missing_commit: list[str] = []
    for bot_id in bot_ids:
        try:
            data = client.get_realm_configuration(bot_id, realm)
        except Exception as e:  # noqa: BLE001 — surface a read failure as WARNING
            return CheckResult(
                roles=[Role.ESS_MAKER.value],
                checkpoint_id="ENV-004-GRS",
                category="Environment",
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=_ENV004_GRS_DESCRIPTION,
                result=(
                    f"Could not read minimalBots ALM configure for realm "
                    f"{realm_name}: {type(e).__name__}: {e}"
                ),
                remediation=(
                    "Ensure the agent is opted into minimalBots ALM for this realm "
                    "and that FlightCheck is signed in to Copilot Studio (AgentBuilder)."
                ),
            )
        observed_commit = (data or {}).get("commitSha") or ""
        if not observed_commit:
            missing_commit.append(bot_id)
        elif observed_commit.lower() != expected_commit.lower():
            mismatches.append((bot_id, observed_commit))

    if mismatches or missing_commit:
        parts = [
            f"botId {bot_id} has commitSha {observed}"
            for bot_id, observed in mismatches
        ]
        parts.extend(
            f"botId {bot_id} returned no commitSha" for bot_id in missing_commit
        )
        return CheckResult(
            roles=[Role.ESS_MAKER.value],
            checkpoint_id="ENV-004-GRS",
            category="Environment",
            priority=Priority.HIGH.value,
            status=Status.FAILED.value,
            description=_ENV004_GRS_DESCRIPTION,
            result=(
                f"Expected GRS commit SHA {expected_commit} for realm "
                f"{realm_name}, but " + "; ".join(parts)
            ),
            remediation=(
                "Publish or import the ESS agent solution built from the expected "
                "commit, or update expectedGrsCommitSha only after confirming the "
                "new commit is the intended release."
            ),
        )

    return CheckResult(
        roles=[Role.ESS_MAKER.value],
        checkpoint_id="ENV-004-GRS",
        category="Environment",
        priority=Priority.HIGH.value,
        status=Status.PASSED.value,
        description=_ENV004_GRS_DESCRIPTION,
        result=(
            f"minimalBots ALM configure for realm {realm_name} reports the "
            f"expected GRS commit SHA {expected_commit}."
        ),
    )


def run_environment_checks(runner) -> list[CheckResult]:
    """Execute all environment checks using the PP Admin client."""
    pp = runner.pp_admin
    env_id = runner.env_id
    results: list[CheckResult] = []

    if not env_id:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description="Power Platform environment exists",
            result="Could not derive environment ID from Dataverse URL",
            remediation="Verify the environment URL in .local/config.json.",
        ))
        return results

    # ---- ENV-001: Environment exists ----
    try:
        env = pp.get_environment(env_id)
        if "_error" in env:
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-001", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Power Platform environment exists",
                result=f"Unable to query environment: {env['_error']}",
                remediation="Requires Power Platform Administrator role.",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))
            return results

        props = env.get("properties", {})
        display_name = props.get("displayName", env_id)
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.PASSED.value,
            description="Power Platform environment exists",
            result=f"Environment: {display_name}",
            doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
        ))

        # ---- ENV-002: Dataverse provisioned ----
        db_state = (
            props.get("linkedEnvironmentMetadata", {})
            .get("resourceProvisioningState", "")
        )
        # Also check databaseType
        db_type = props.get("databaseType", "")
        if db_state.lower() == "succeeded" or db_type:
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-002", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Dataverse database provisioned",
                result=f"State: {db_state or 'Available'}, Type: {db_type or 'N/A'}",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))
        else:
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-002", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Dataverse database provisioned",
                result=f"Provisioning state: {db_state or 'Unknown'}",
                remediation="Enable Dataverse database for this environment.",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))

        # ---- ENV-003: Environment type ----
        env_type = props.get("environmentSku", "")
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-003", category="Environment",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Environment type",
            result=f"Type: {env_type}",
            doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
        ))

    except Exception as e:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Power Platform environment",
            result=f"Unable to check: {e}",
            remediation="Ensure Power Platform Admin permissions.",
        ))

    # ---- ENV-004: Connections & Connection References ----
    results.extend(_check_connections_and_refs(runner))

    # ---- ENV-CAPACITY-001: Copilot Studio capacity provisioned ----
    results.extend(_check_copilot_studio_capacity_provisioned(runner))

    # ---- ENV-008: DLP policies ----
    try:
        policies = iter_effective_policies(pp, env_id)
        if isinstance(policies, dict) and "_error" in policies:
            # The apiPolicies admin endpoint returned 401/403 — we could
            # NOT read DLP state. Report this honestly as a SKIP rather
            # than claiming "no DLP policies" (which would falsely imply
            # the environment is unrestricted).
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description="DLP policies configured",
                result="DLP policy check skipped — the apiPolicies admin endpoint returned a permissions error.",
                remediation="Re-run FlightCheck signed in with the Power Platform Administrator role so DLP policies can be read.",
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
        elif policies:
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="DLP policies configured",
                result=f"{len(policies)} policy/policies apply to this environment",
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
        else:
            # "No DLP policy" means the environment is currently
            # unrestricted — connectors are not blocked or grouped.
            # That's intentional in many tenants (especially dev), so
            # this is a Warning, not a Failure. The remediation walks
            # the operator through the actual fix when DLP IS required:
            # open the policies page, scope a policy to this env, and
            # put every connector the agent uses in the SAME group
            # (Business or Non-Business) — connectors in different
            # groups cannot be combined in a single flow/agent action,
            # so "allowlisting" really means group-coexistence, not
            # just "unblock".
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="DLP policies configured",
                result="No DLP policies found for this environment",
                remediation=(
                    "No DLP policy applies to this environment, so connector usage is currently unrestricted. "
                    "If your tenant requires DLP, open the [Power Platform admin center](https://admin.powerplatform.microsoft.com/) "
                    "and navigate to **Security \u2192 Data and privacy \u2192 Data policy**, then either create a new policy or edit an existing one so that: "
                    "(1) the policy's **Environments** scope includes this environment, "
                    "(2) every connector the agent uses (e.g. Workday, SharePoint, Microsoft 365, HTTP, custom connectors) is placed in the **same** group \u2014 Business or Non-Business \u2014 since connectors in different groups cannot be combined in a single flow or agent action, "
                    "and (3) none of those connectors are in the **Blocked** group. "
                    "If your tenant does not enforce DLP for this environment, no action is required."
                ),
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-008", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="DLP policies",
            result=f"Unable to check: {e}",
            remediation=(
                "Reading DLP policies requires the **Power Platform Administrator** role at the tenant level. "
                "Ask a tenant admin to either grant you the role or to review policies on your behalf at the "
                "[Power Platform admin center](https://admin.powerplatform.microsoft.com/) under **Security \u2192 Data and privacy \u2192 Data policy**."
            ),
        ))

    # ---- ENV-009: Maker has preferred customization solution selected ----
    results.extend(_check_preferred_solution(runner))

    return results


def run_preferred_solution_check(runner) -> list[CheckResult]:
    """Run ENV-009 independently for single-checkpoint setup validation."""
    return _check_preferred_solution(runner)


def run_capacity_check(runner) -> list[CheckResult]:
    """Run ENV-CAPACITY-001 without requiring other environment clients."""
    return _check_copilot_studio_capacity_provisioned(runner)


def _env_capacity(status: str, result: str, remediation: str = "") -> CheckResult:
    """Build an ENV-CAPACITY-001 row (every branch shares id/category/role)."""
    return CheckResult(
        roles=[Role.POWER_PLATFORM_ADMIN.value],
        checkpoint_id="ENV-CAPACITY-001", category="Environment",
        priority=Priority.CRITICAL.value, status=status,
        description="Copilot Studio capacity provisioned",
        result=result, remediation=remediation, doc_link=_CAPACITY_DOC,
    )


def _check_copilot_studio_capacity_provisioned(runner) -> list[CheckResult]:
    """ENV-CAPACITY-001 — Copilot Studio message capacity provisioned for THIS
    environment, the precondition skill-1 verifies before the ESS agent is
    installed.

    This is the "is capacity provisioned?" variant of the shared capacity
    verdict (``checks/licensing.py``). Unlike PRE-004 it runs **before** the
    agent exists, so there is no shared/published population to size against —
    it asks only whether the environment has any dedicated Copilot Studio
    capacity (``population=None``).

    Capacity is a hard setup gate. When allocation cannot be read
    programmatically or allocation is zero, the row fails rather than allowing
    a billing selection or manual attestation to bypass the check.
    """
    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return [_env_capacity(Status.FAILED.value,
            "Environment ID is unavailable, so Copilot Studio capacity could not be verified.",
            "Verify the environment identity, then rerun this checkpoint.")]

    allocated = _env_mcs_allocation(getattr(runner, "powerplatform", None), env_id)
    payg_flag = getattr(runner, "_payg_configured", None)
    status, reason = classify_copilot_studio_capacity(
        allocated, population=None, payg_flag=payg_flag)

    if reason == "unreadable":
        return [_env_capacity(Status.FAILED.value,
            "This environment's Copilot Studio message capacity allocation could not be verified because the Power Platform Licensing API was unavailable or permission was denied.",
            f"Sign in with the Power Platform Administrator role, verify capacity in {_CAPACITY_PORTAL}, then rerun this checkpoint. Setup cannot continue until the automated check succeeds.")]
    if reason == "covered":
        return [_env_capacity(Status.PASSED.value,
            f"{allocated} Copilot Studio message credit(s) are allocated to this environment.")]
    if reason == "zero_with_payg":
        return [_env_capacity(Status.FAILED.value,
            "No Copilot Studio message capacity is allocated to this environment. Pay-as-you-go billing does not satisfy the foundation setup capacity gate.",
            f"Allocate Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}, then rerun this checkpoint.")]
    if reason == "zero_payg_unknown":
        return [_env_capacity(Status.FAILED.value,
            "No Copilot Studio message capacity is allocated to this environment, and Pay-as-you-go status was not determined in this run.",
            f"Allocate Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}, then rerun this checkpoint. Setup cannot continue without allocated capacity.")]
    # reason == "zero_no_payg"
    return [_env_capacity(Status.FAILED.value,
        "No Copilot Studio message capacity is allocated to this environment and Pay-as-you-go billing is not configured, so the ESS agent will have no message capacity to consume at runtime.",
        f"Allocate Copilot Studio message capacity to this environment in {_CAPACITY_PORTAL}, then rerun this checkpoint.")]


# ---------------------------------------------------------------------------
# ENV-004: Connections & Connection References — binding + orphan detection
# ---------------------------------------------------------------------------

def _check_connections_and_refs(runner) -> list[CheckResult]:
    """Report the Declarative Agent's connection references, plus the GRS pin.

    Re-pointed from the Dataverse ``connectionreference`` table to the
    Declarative Agent minimalBots components API (validated tier; the same
    ``connectionReferenceChanges`` shape the shipped native ``DA-CONN-001``
    check consumes, read via ``_da_connection_refs``). The DA components
    changeset IS each agent's declared reference set, so this reads every
    configured agent's references and classifies each:

      - **Unbound reference** (FAIL) \u2014 a reference with no ``connectionId``.
        Topics/flows using it fail immediately at runtime.
      - **Bound reference** (PASS) \u2014 a reference with a ``connectionId`` set.

    Unlike the former Dataverse-backed check, the DA changeset carries no
    environment-wide connection inventory, so the orphan-reference,
    missing-reference, and unbound-connection branches are not applicable and
    are not emitted.

    A separate GRS commit-pin sub-check (``ENV-004-GRS``) verifies the deployed
    agent's ALM commit matches an expected SHA when one is configured; its
    verdict folds into the ENV-004 summary status and it is also emitted as a
    detail row (so a scope run shows it; a targeted ``--checkpoint ENV-004`` run
    filters the detail row out but still sees the folded verdict in the summary).

    Signal:
      SKIP  \u2014 no AgentBuilder client or no configured agent botId.
      PASS  \u2014 every reference is bound (and the GRS pin passed or was not judged).
      WARN  \u2014 the components read or GRS configure read errored.
      FAIL  \u2014 one or more unbound references (or the GRS pin failed).
    """
    results: list[CheckResult] = []
    roles = [Role.POWER_PLATFORM_ADMIN.value]
    description = "Connections & connection references"

    # Validated-tier read via the shared DA reader. Fail loudly: a malformed
    # changeset raises (degrade to WARNING) rather than reporting a confident
    # but wrong verdict; an unavailable client/botId returns None (SKIP).
    try:
        refs = read_all_agents_connection_references(runner)
    except Exception as e:  # noqa: BLE001 \u2014 fail loudly as a WARNING
        results.append(CheckResult(roles=roles,
            checkpoint_id="ENV-004", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=(
                f"Unable to read the agent's connection references: "
                f"{type(e).__name__}: {e}"
            ),
            remediation=(
                "Re-run FlightCheck; if this persists, ensure FlightCheck is "
                "signed in to Copilot Studio (AgentBuilder) and report the error above."
            ),
        ))
        return results

    if refs is None:
        results.append(CheckResult(roles=roles,
            checkpoint_id="ENV-004", category="Environment",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=description,
            result=(
                "AgentBuilder client or agent botId not available, so connection "
                "references were not judged."
            ),
            remediation=(
                "Run /setup so .local/config.json records the agent botId, and "
                "ensure FlightCheck is signed in to Copilot Studio (AgentBuilder), "
                "then re-run FlightCheck."
            ),
        ))
        return results

    unbound_refs = [r for r in refs if not (r.get("connectionid") or "")]
    bound_refs = [r for r in refs if (r.get("connectionid") or "")]

    # The GRS commit pin is a distinct ENV-004 sub-check; fold its verdict into
    # the summary status so a targeted run (which filters the detail row) still
    # surfaces a GRS failure.
    grs_result = _env004_grs_commit_pin_result(runner)

    if unbound_refs or grs_result.status == Status.FAILED.value:
        overall_status = Status.FAILED.value
    elif grs_result.status == Status.WARNING.value:
        overall_status = Status.WARNING.value
    else:
        overall_status = Status.PASSED.value

    summary_parts = [
        f"{len(refs)} reference(s) declared by the agent(s)",
        f"{len(bound_refs)} bound",
    ]
    if unbound_refs:
        summary_parts.append(f"{len(unbound_refs)} unbound")
    if grs_result.status != Status.SKIPPED.value:
        summary_parts.append(f"GRS commit pin: {grs_result.status}")

    env_id = getattr(runner, "env_id", None)
    solutions_url = maker_solutions_url(env_id) if env_id else None
    conn_ref_doc = (
        "https://learn.microsoft.com/en-us/power-apps/maker/"
        "data-platform/create-connection-reference"
    )

    if unbound_refs and solutions_url:
        remediation = (
            f"Bind the unbound connection reference(s): open [Power Apps \u2192 "
            f"Solutions]({solutions_url}) \u2192 open the solution that contains "
            f"your agent \u2192 in the left nav choose **Objects \u2192 Connection "
            f"references** \u2192 bind each unbound reference to a valid connection."
        )
    elif unbound_refs:
        remediation = (
            "Bind the unbound connection reference(s) in Power Apps \u2192 "
            "Solutions \u2192 your agent's solution \u2192 Objects \u2192 "
            "Connection references."
        )
    else:
        remediation = ""

    summary_doc_link = (
        conn_ref_doc
        if overall_status == Status.FAILED.value
        else f"{DOC_BASE}/prepare#set-up-your-power-platform-environment"
    )
    results.append(CheckResult(roles=roles,
        checkpoint_id="ENV-004", category="Environment",
        priority=Priority.HIGH.value, status=overall_status,
        description=description,
        result=" | ".join(summary_parts),
        remediation=remediation,
        doc_link=summary_doc_link,
    ))

    # --- Detail: unbound references (no connectionId set) ---
    for i, ref in enumerate(unbound_refs):
        ref_name = ref.get("connectionreferencelogicalname") or "Unknown"
        connector = ref.get("connectorid") or "?"
        results.append(CheckResult(roles=roles,
            checkpoint_id=f"ENV-004-UR-{i + 1:03d}", category="Environment",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=f"Unbound reference: {ref_name}",
            result=f"No connection bound to this reference (connector {connector})",
            remediation=(
                f"Open your agent's solution in Power Apps \u2192 Solutions \u2192 "
                f"**Objects \u2192 Connection references** \u2192 bind '{ref_name}' to "
                f"a valid connection."
            ),
            doc_link=conn_ref_doc,
        ))

    # --- Detail: GRS commit pin (also folded into the summary status above) ---
    results.append(grs_result)

    return results


# ---------------------------------------------------------------------------
# ENV-009: Maker has preferred customization solution selected
#
# Background: ESS install guidance (src/reference/ess-docs/deployment/install.md,
# lines 19-45) tells operators to create a customer-owned unmanaged solution and
# select it as their *preferred solution* so that new Copilot Studio / Maker
# portal customizations land in that solution instead of in the Default
# Solution. The preferred-solution selection is stored per user (on the
# `usersettings` table), not per environment, so this check validates the
# *current FlightCheck caller's* selection - it is honest about that scope in
# the description and result text.
#
# Signals (all GET, no writes):
#  1. Eligible unmanaged solutions
#     GET /solutions?$filter=ismanaged eq false and isvisible eq true
#         and uniquename ne 'Default' and uniquename ne 'Active'
#         and solutiontype eq 0 and _parentsolutionid_value eq null
#  2. Caller's preferred solution (single round-trip, bound to the caller
#     via the bearer token - no separate WhoAmI() lookup needed)
#     GET /GetPreferredSolution()
#     -> https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/getpreferredsolution
#
# UNCERTAINTY: the MS Learn reference for GetPreferredSolution() documents
# the return type as `crmbaseentity` but does not include an example
# response body. The code below treats the response defensively:
#  * A body that contains `solutionid` is the selected solution; we then
#    compare it against the eligible set above.
#  * A body that omits `solutionid` (or any decode/empty-body edge case
#    that bubbles up as an exception) is reported via the generic catch-all
#    WARNING with the HTTP status code surfaced (per PR #128 review).
#
# Verdict map (always exactly one CheckResult emitted):
#   * SKIPPED  - env_url or dv_token missing.
#   * FAILED   - signal (1) returns 0 candidate solutions.
#   * WARNING  - candidates exist but caller's selected preferred solution
#                does not match any candidate. Framed as a hardening
#                recommendation per AGENTS.md principle 9 (not a functional
#                blocker).
#   * PASSED   - candidates exist and caller's selected preferred solution is
#                one of them.
# ---------------------------------------------------------------------------

# Pinned to the current canonical MS Learn path. The module-level DOC_BASE
# points at /copilot/microsoft-365/employee-self-service which 301-redirects
# to /microsoft-365/copilot/employee-self-service; bypass the redirect here
# so this link stays stable without rewriting DOC_BASE (out of scope for this PR).
_PREFSOL_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install#set-up-a-preferred-solution"
)
_PREFSOL_DESCRIPTION = "Maker has preferred customization solution selected"

# OData filter that excludes Microsoft-installed and system solutions, leaving
# only customer-created unmanaged top-level solutions. Verified against a live
# tenant - it narrowed 3 raw matches down to 1 correct ESSCustomization row.
# Notes:
#  * `solutiontype eq 0` excludes patch/upgrade solutions.
#  * `_parentsolutionid_value eq null` further excludes any nested children.
#  * `_publisherid_value ne null` is intentionally NOT used - null comparisons
#    on lookup columns are inconsistently supported across Dataverse versions.
_ELIGIBLE_SOLUTION_FILTER = (
    "ismanaged eq false and isvisible eq true "
    "and uniquename ne 'Default' and uniquename ne 'Active' "
    "and solutiontype eq 0 and _parentsolutionid_value eq null"
)

# Fields fetched on each eligible solution. ``_publisherid_value`` is the
# lookup column needed to follow up with a /publishers({id}) GET when the
# preferred-solution match is found - it's the cheapest way to surface
# the publisher without changing the response shape via $expand (which
# would require new cassette evidence per AGENTS.md "What counts as the
# same endpoint").
_ELIGIBLE_SOLUTION_SELECT = "solutionid,uniquename,friendlyname,_publisherid_value"


def _is_default_publisher(uniquename: str | None) -> bool:
    """Return True when ``uniquename`` is the env's Default Publisher.

    Dataverse provisions every environment with a system publisher whose
    ``uniquename`` follows the pattern ``DefaultPublisher<orgsuffix>``
    (e.g. ``DefaultPublisherorgeeac24d0`` - one such value is observable
    in ``tests/fixtures/cassettes/island_gateway_botcomponents.yaml``).
    Customer-created publishers use customer-chosen unique names that do
    not start with the literal ``DefaultPublisher`` prefix, so a
    case-insensitive ``startswith`` is a reliable signal.

    A solution bound to the Default Publisher inherits the env's
    ``cr<NNN>`` customization prefix - the install guide explicitly says
    to use a publisher with a custom prefix so exported solutions don't
    collide across environments:
    https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/install#set-up-a-preferred-solution
    """
    if not isinstance(uniquename, str):
        return False
    return uniquename.lower().startswith("defaultpublisher")



def _try_parse_guid(value) -> uuid.UUID | None:
    """Return ``uuid.UUID(value)`` or ``None`` if value is not a parsable GUID.

    Used to normalise Dataverse-returned ``solutionid`` strings (which may
    differ in case or ``{braces}`` between endpoints) before equality
    comparison. Non-string / non-GUID inputs (including ``None`` and empty
    string) return ``None`` so callers can treat them as "no value".
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def _check_preferred_solution(runner) -> list[CheckResult]:
    """ENV-009: Validate the maker has selected a preferred customization solution.

    Always emits exactly one CheckResult (per principle 7 - bucket multi-resource
    findings). Never raises - all errors are caught and turned into WARNING
    results so a transient Dataverse failure does not abort the whole flightcheck
    run.
    """
    env_url = getattr(runner, "env_url", None)
    token = getattr(runner, "dv_token", None)

    if not env_url or not token:
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-009", category="Environment",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=_PREFSOL_DESCRIPTION,
            result="Dataverse URL or access token not available in this run.",
            doc_link=_PREFSOL_DOC_LINK,
        )]

    try:
        # Signal 1: eligible unmanaged customer solutions.
        solutions = query_all(
            env_url, token,
            "solutions",
            _ELIGIBLE_SOLUTION_SELECT,
            _ELIGIBLE_SOLUTION_FILTER,
        )
        if not solutions:
            return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="ENV-009", category="Environment",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description=_PREFSOL_DESCRIPTION,
                result=(
                    "No customer-created unmanaged solutions found in this "
                    "environment. Customizations made via the kit have nowhere "
                    "to land except the Default Solution, which is not "
                    "exportable as an ALM artifact."
                ),
                remediation=(
                    "Create an unmanaged solution in the Power Platform Maker "
                    "portal (Solutions -> + New solution) using a custom "
                    "publisher, then select it as your preferred solution. See "
                    "the ESS install guide for the recommended naming and "
                    "publisher conventions."
                ),
                doc_link=_PREFSOL_DOC_LINK,
            )]

        # Signal 2: caller's preferred solution in one round-trip. Bound to
        # the caller via the bearer token; no need to resolve UserId first.
        preferred = dataverse_get(env_url, token, "GetPreferredSolution()")
        selected_solution_id = (preferred or {}).get("solutionid")

        eligible_names = sorted(s.get("uniquename", "<unknown>") for s in solutions)
        eligible_summary = ", ".join(eligible_names)

        # Normalise GUIDs to uuid.UUID for the membership compare so casing
        # or `{braces}` differences between the two response sources never
        # cause a false WARNING. Defensive parse — malformed values fall
        # through to the WARNING branch below (treated as "no selection").
        selected_uuid = _try_parse_guid(selected_solution_id)

        if selected_uuid is not None:
            match = next(
                (
                    s for s in solutions
                    if _try_parse_guid(s.get("solutionid")) == selected_uuid
                ),
                None,
            )
            if match:
                matched_name = match.get("uniquename")
                # Publisher quality: a customer-owned unmanaged solution that
                # is bound to the env's Default Publisher inherits the
                # ``cr<NNN>`` prefix and is unsuitable for ALM export per the
                # install guide. Treat as a hardening WARNING - the preferred-
                # solution selection itself is correct, only the publisher
                # behind it is sub-optimal.
                publisher_id = match.get("_publisherid_value")
                if publisher_id:
                    try:
                        publisher = dataverse_get(
                            env_url, token,
                            f"publishers({publisher_id})",
                            params={
                                "$select": (
                                    "uniquename,customizationprefix,friendlyname"
                                ),
                            },
                        ) or {}
                    except Exception:
                        # Don't downgrade a good preferred-solution selection
                        # over a transient publisher-fetch failure. Fall
                        # through to PASS with the publisher field omitted;
                        # the operator still sees the matched solution name.
                        publisher = {}

                    publisher_uniquename = publisher.get("uniquename")
                    if _is_default_publisher(publisher_uniquename):
                        publisher_prefix = publisher.get(
                            "customizationprefix"
                        ) or "<unknown>"
                        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                            checkpoint_id="ENV-009", category="Environment",
                            priority=Priority.HIGH.value,
                            status=Status.WARNING.value,
                            description=_PREFSOL_DESCRIPTION,
                            result=(
                                f"Preferred solution '{matched_name}' is bound "
                                f"to the environment's Default Publisher "
                                f"('{publisher_uniquename}', prefix "
                                f"'{publisher_prefix}')."
                            ),
                            remediation=(
                                "Hardening recommendation (not a functional "
                                "blocker). The Default Publisher's "
                                f"'{publisher_prefix}' prefix is auto-generated "
                                "per environment and is shared by every "
                                "default-published artifact in that env, so "
                                "exported components collide across "
                                "environments and ALM provenance is unclear. "
                                "Create a publisher with your organization's "
                                "prefix (e.g. 'contoso') in the Power Platform "
                                "Maker portal -> Solutions -> + New publisher, "
                                "then either move existing customizations to a "
                                "new solution that uses it or change the "
                                "preferred solution to one already bound to "
                                "that publisher."
                            ),
                            doc_link=_PREFSOL_DOC_LINK,
                        )]

                    # PASSED with publisher annotation when available.
                    if publisher_uniquename:
                        publisher_suffix = (
                            f" (publisher: '{publisher_uniquename}'"
                            f", prefix: '"
                            f"{publisher.get('customizationprefix') or '<unknown>'}"
                            f"')"
                        )
                    else:
                        publisher_suffix = ""
                else:
                    publisher_suffix = ""

                return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                    checkpoint_id="ENV-009", category="Environment",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=_PREFSOL_DESCRIPTION,
                    result=(
                        f"Current maker has selected '{matched_name}'"
                        f"{publisher_suffix} as their preferred solution; it "
                        f"is one of {len(solutions)} eligible unmanaged "
                        f"solution(s) in this environment ({eligible_summary})."
                    ),
                    doc_link=_PREFSOL_DOC_LINK,
                )]

        # Either no preferred solution selected, or the selection points to a
        # solution outside the eligible set (e.g. a managed solution or
        # Default). Both collapse into the same hardening warning - the action
        # is identical.
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-009", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_PREFSOL_DESCRIPTION,
            result=(
                f"The current maker account has not selected any of the "
                f"{len(solutions)} eligible unmanaged solution(s) "
                f"({eligible_summary}) as their preferred solution."
            ),
            remediation=(
                "Hardening recommendation (not a functional blocker). "
                "Selecting a preferred solution ensures future Copilot Studio "
                "/ Maker portal customizations consistently land in a "
                "customer-owned, exportable solution rather than the Default "
                "Solution (which can't be exported between environments). "
                "Open the Power Platform Maker portal -> Solutions, select "
                "the intended unmanaged solution, and choose 'Set preferred "
                "solution'."
            ),
            doc_link=_PREFSOL_DOC_LINK,
        )]

    except AuthExpiredError as e:
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-009", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_PREFSOL_DESCRIPTION,
            result=str(e),
            remediation="Re-run FlightCheck to refresh the access token.",
            doc_link=_PREFSOL_DOC_LINK,
        )]
    except Exception as e:
        # Per principle 3 (fail loudly): surface unexpected Dataverse failures
        # as WARNING rather than silently passing. Surface the HTTP status
        # code when available so a 403 (insufficient privileges) is
        # distinguishable from a 5xx (transient) at a glance (PR #128 review).
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        status_hint = f" [HTTP {status_code}]" if status_code is not None else ""
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="ENV-009", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_PREFSOL_DESCRIPTION,
            result=(
                f"Unable to validate preferred solution: "
                f"{type(e).__name__}{status_hint}: {e}"
            ),
            remediation=(
                "Inspect the error above; common causes are insufficient "
                "Dataverse privileges on the solution / usersettings tables "
                "(typically surfaces as HTTP 403) or a transient platform "
                "error (HTTP 5xx)."
            ),
            doc_link=_PREFSOL_DOC_LINK,
        )]
