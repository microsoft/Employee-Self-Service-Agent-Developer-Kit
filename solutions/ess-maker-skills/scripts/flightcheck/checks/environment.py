# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Environment Configuration Validation (ENV-xxx)

Checks Power Platform environment, Dataverse, DLP policies, and related config.
"""

import uuid

from ..runner import CheckResult, Status, Priority
from .connections import get_connection_status
from auth import query_all, dataverse_get, AuthExpiredError  # scripts/auth.py, on path via cli.py

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def run_environment_checks(runner) -> list[CheckResult]:
    """Execute all environment checks using the PP Admin client."""
    pp = runner.pp_admin
    env_id = runner.env_id
    results: list[CheckResult] = []

    if not env_id:
        results.append(CheckResult(
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
            results.append(CheckResult(
                checkpoint_id="ENV-001", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description="Power Platform environment exists",
                result=f"Unable to query environment: {env['_error']}",
                remediation="Requires Power Platform Administrator role.",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))
            return results

        props = env.get("properties", {})
        display_name = props.get("displayName", env_id)
        results.append(CheckResult(
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
            results.append(CheckResult(
                checkpoint_id="ENV-002", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Dataverse database provisioned",
                result=f"State: {db_state or 'Available'}, Type: {db_type or 'N/A'}",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="ENV-002", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Dataverse database provisioned",
                result=f"Provisioning state: {db_state or 'Unknown'}",
                remediation="Enable Dataverse database for this environment.",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))

        # ---- ENV-003: Environment type ----
        env_type = props.get("environmentSku", "")
        results.append(CheckResult(
            checkpoint_id="ENV-003", category="Environment",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Environment type",
            result=f"Type: {env_type}",
            doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
        ))

    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Power Platform environment",
            result=f"Unable to check: {e}",
            remediation="Ensure Power Platform Admin permissions.",
        ))

    # ---- ENV-004: Connections & Connection References ----
    results.extend(_check_connections_and_refs(runner))

    # ---- ENV-008: DLP policies ----
    try:
        policies = pp.get_dlp_policies_for_env(env_id)
        if policies:
            results.append(CheckResult(
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="DLP policies configured",
                result=f"{len(policies)} policy/policies apply to this environment",
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="DLP policies configured",
                result="No DLP policies found for this environment",
                remediation="Review DLP policies in [PP admin center](https://admin.powerplatform.microsoft.com) to ensure connectors are allowlisted.",
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="ENV-008", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="DLP policies",
            result=f"Unable to check: {e}",
            remediation="Requires Power Platform Admin role.",
        ))

    # ---- ENV-009: Maker has preferred customization solution selected ----
    results.extend(_check_preferred_solution(runner))

    return results


# ---------------------------------------------------------------------------
# ENV-004: Connections & Connection References — binding + orphan detection
# ---------------------------------------------------------------------------

def _check_connections_and_refs(runner) -> list[CheckResult]:
    """Report all connections and connection references with binding state.

    Detects orphans in both directions:
      - Connection references pointing to a connection that doesn't exist
        (orphan reference).
      - Connections with no corresponding connection reference
        (unbound connection).

    Terminology:
      **Orphan reference** (FAIL) — A connection reference in the solution
      points to a connection ID that no longer exists in the environment.
      This occurs when a connection was deleted, the solution was imported
      from another environment, or a connection was recreated with a new ID.
      Topics/flows using this reference will fail at runtime with auth errors.

      **Unbound reference** (FAIL) — A connection reference exists in the
      solution but has no connection ID set (empty ``connectionid`` field).
      This occurs after a solution import where references were never
      configured, or a new reference was added but not bound. Topics/flows
      using this reference will fail immediately.

      **Unbound connection** (WARN) — A connection exists in the environment
      but no connection reference points to it. Common after troubleshooting
      (test connections), re-binding references to newer connections, or
      manual connection creation. No runtime impact, but adds clutter.

    Signal:
      PASS  — all references bound to existing, connected connections.
      WARN  — unbound connections exist (may be intentional).
      FAIL  — orphan or unbound references found (broken bindings).
    """

    results: list[CheckResult] = []
    pp = runner.pp_admin
    env_id = runner.env_id
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)

    if not pp or not env_id:
        results.append(CheckResult(
            checkpoint_id="ENV-004", category="Environment",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Connections & connection references",
            result="Power Platform Admin API not available — skipping",
            remediation="Requires Power Platform Administrator role.",
        ))
        return results

    if not env_url or not dv_token:
        results.append(CheckResult(
            checkpoint_id="ENV-004", category="Environment",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Connections & connection references",
            result="Dataverse token not available — cannot query connection references",
            remediation="Ensure Dataverse authentication is configured.",
        ))
        return results

    # --- Fetch connections from PP Admin API ---
    try:
        all_conns = pp.get_connections(env_id)
        if isinstance(all_conns, dict) and "_error" in all_conns:
            results.append(CheckResult(
                checkpoint_id="ENV-004", category="Environment",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Connections & connection references",
                result=f"Unable to list connections: {all_conns['_error']}",
                remediation="Requires Power Platform Admin role.",
            ))
            return results
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="ENV-004", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Connections & connection references",
            result=f"Error fetching connections: {e}",
        ))
        return results

    # --- Fetch connection references from Dataverse ---
    try:
        conn_refs = query_all(
            env_url, dv_token,
            "connectionreferences",
            "connectionreferenceid,connectionreferencelogicalname,"
            "connectorid,connectionid,connectionreferencedisplayname,statuscode",
        )
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="ENV-004", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Connections & connection references",
            result=f"Error querying connection references: {e}",
            remediation="Ensure Dataverse access permissions.",
        ))
        return results

    # --- Build lookup: connection name (GUID) → connection object ---
    conn_map = {}
    for c in all_conns:
        conn_name = c.get("name", "")
        if conn_name:
            conn_map[conn_name] = c

    # --- Analyze binding state ---
    bound_conn_ids = set()
    orphan_refs = []   # References pointing to non-existent connections
    unbound_refs = []  # References with no connectionid set

    for ref in conn_refs:
        conn_id = ref.get("connectionid") or ""
        if not conn_id:
            unbound_refs.append(ref)
        elif conn_id in conn_map:
            bound_conn_ids.add(conn_id)
        else:
            orphan_refs.append(ref)

    # Unbound connections: connections no reference points to
    unbound_conns = [
        c for c in all_conns
        if c.get("name", "") and c.get("name", "") not in bound_conn_ids
    ]

    # --- Determine overall status ---
    has_orphan_refs = len(orphan_refs) > 0 or len(unbound_refs) > 0
    has_unbound_conns = len(unbound_conns) > 0

    if has_orphan_refs:
        overall_status = Status.FAILED.value
    elif has_unbound_conns:
        overall_status = Status.WARNING.value
    else:
        overall_status = Status.PASSED.value

    # --- Summary ---
    bound_refs = len(conn_refs) - len(orphan_refs) - len(unbound_refs)
    summary_parts = [
        f"{len(all_conns)} connection(s)",
        f"{len(conn_refs)} reference(s)",
        f"{bound_refs} bound ({len(bound_conn_ids)} distinct conn(s))",
    ]
    if orphan_refs:
        summary_parts.append(f"{len(orphan_refs)} orphan ref(s)")
    if unbound_refs:
        summary_parts.append(f"{len(unbound_refs)} unbound ref(s)")
    if unbound_conns:
        summary_parts.append(f"{len(unbound_conns)} unbound conn(s)")

    remediation = ""
    if has_orphan_refs:
        remediation = (
            "Fix broken connection references: re-bind them to valid connections "
            "in Power Apps → Solutions → Connection References, or remove stale references."
        )
    elif has_unbound_conns:
        remediation = (
            "Unbound connections may be intentional (e.g., test connections). "
            "Review in Power Platform admin center and remove unused connections."
        )

    results.append(CheckResult(
        checkpoint_id="ENV-004", category="Environment",
        priority=Priority.HIGH.value, status=overall_status,
        description="Connections & connection references",
        result=" | ".join(summary_parts),
        remediation=remediation,
        doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
    ))

    # --- Detail: orphan references (point to missing connections) ---
    for i, ref in enumerate(orphan_refs):
        ref_name = ref.get("connectionreferencedisplayname") or ref.get(
            "connectionreferencelogicalname", "Unknown"
        )
        dead_conn_id = ref.get("connectionid", "?")
        results.append(CheckResult(
            checkpoint_id=f"ENV-004-OR-{i + 1:03d}", category="Environment",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=f"Orphan reference: {ref_name}",
            result=f"Points to missing connection '{dead_conn_id}'",
            remediation=f"Re-bind '{ref_name}' to an active connection or delete the reference.",
        ))

    # --- Detail: unbound references (no connectionid set) ---
    for i, ref in enumerate(unbound_refs):
        ref_name = ref.get("connectionreferencedisplayname") or ref.get(
            "connectionreferencelogicalname", "Unknown"
        )
        results.append(CheckResult(
            checkpoint_id=f"ENV-004-UR-{i + 1:03d}", category="Environment",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=f"Unbound reference: {ref_name}",
            result="No connection bound to this reference",
            remediation=f"Bind '{ref_name}' to a valid connection in Power Apps → Solutions → Connection References.",
        ))

    # --- Detail: unbound connections (no reference points to them) ---
    for i, conn in enumerate(unbound_conns):
        props = conn.get("properties", {})
        conn_name = props.get("displayName", conn.get("name", "Unknown"))
        api_id = props.get("apiId", "")
        connector_label = api_id.split("/")[-1] if api_id else "unknown"
        conn_status = get_connection_status(conn)
        results.append(CheckResult(
            checkpoint_id=f"ENV-004-UC-{i + 1:03d}", category="Environment",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description=f"Unbound connection: {conn_name}",
            result=f"Connector: {connector_label} | Status: {conn_status} | No reference uses this connection",
            remediation=f"If unused, remove '{conn_name}' from the environment to reduce clutter.",
        ))

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

_PREFSOL_DOC_LINK = f"{DOC_BASE}/install#set-up-a-preferred-solution"
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
        return [CheckResult(
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
            "solutionid,uniquename,friendlyname",
            _ELIGIBLE_SOLUTION_FILTER,
        )
        if not solutions:
            return [CheckResult(
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
                return [CheckResult(
                    checkpoint_id="ENV-009", category="Environment",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=_PREFSOL_DESCRIPTION,
                    result=(
                        f"Current maker has selected '{match.get('uniquename')}' "
                        f"as their preferred solution; it is one of "
                        f"{len(solutions)} eligible unmanaged solution(s) in "
                        f"this environment ({eligible_summary})."
                    ),
                    doc_link=_PREFSOL_DOC_LINK,
                )]

        # Either no preferred solution selected, or the selection points to a
        # solution outside the eligible set (e.g. a managed solution or
        # Default). Both collapse into the same hardening warning - the action
        # is identical.
        return [CheckResult(
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
        return [CheckResult(
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
        return [CheckResult(
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
