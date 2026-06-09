# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Environment Configuration Validation (ENV-xxx)

Checks Power Platform environment, Dataverse, DLP policies, and related config.
"""

from ..runner import CheckResult, Status, Priority
from ._maker_urls import (
    maker_connections_url,
    maker_solution_url,
    maker_solutions_url,
)
from .connections import get_connection_status
from auth import query_all  # scripts/auth.py, on path via cli.py

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def _resolve_ref_solutions(
    *, env_url: str, dv_token: str, env_id: str, refs: list[dict],
) -> dict[str, dict[str, str]]:
    """Resolve the containing solutions for a set of connection refs.

    Returns a map ``{connectionreferenceid: {"url": <maker url>, "label": <name>}}``
    so each ENV-004 detail row can deep-link to the specific solution
    that holds its broken ref, instead of dumping the operator on the
    env-wide solutions list.

    Two Dataverse round-trips are required because the
    ``connectionreference`` entity carries no solution column — solution
    membership is only exposed via the ``solutioncomponent`` intersect:
      1. ``solutioncomponents`` filtered only by ``objectid eq <ref-guid>``
         → maps each ref GUID to its owning ``_solutionid_value``. We
         deliberately omit a ``componenttype`` filter because Microsoft's
         published enum does not document a stable value for Connection
         Reference (earlier guesses such as 10047 returned empty in real
         environments). A GUID is universally unique, so filtering on
         ``objectid`` alone cannot collide with another component kind.
      2. ``solutions`` filtered by the distinct solution GUIDs from
         step 1 *and* ``uniquename eq 'Default'`` → resolves
         friendlyname/ismanaged for ranking, and ensures we always know
         the Default Solution's GUID for the managed-only fallback.

    Link selection prefers (in order): a named unmanaged solution
    containing the ref → the Default Solution (always unmanaged, always
    present, can edit any component as customization) → no link. We
    never link to a managed solution because Power Apps blocks edits
    with "You cannot directly edit the objects within a managed
    solution.", which is a dead end for the maker.

    Best-effort: any Dataverse failure returns ``{}`` so callers cleanly
    fall back to the env-wide solutions URL.
    """
    ref_ids = {
        ref.get("connectionreferenceid") for ref in refs
        if ref.get("connectionreferenceid")
    }
    if not ref_ids:
        return {}

    # Step 1: ref-guid -> solution-guid via solutioncomponents.
    # No componenttype filter — see docstring above for rationale.
    sc_filter = " or ".join(f"objectid eq {rid}" for rid in ref_ids)
    try:
        components = query_all(
            env_url, dv_token,
            "solutioncomponents",
            "objectid,_solutionid_value",
            filter_expr=sc_filter,
        )
    except Exception:
        return {}

    # A single ref typically appears in multiple solution layers (the
    # base managed solution that defined it plus any unmanaged layer
    # that customized it). Collect every solution per ref so step 2 can
    # pick the one the maker can actually edit in the portal.
    ref_to_solutions: dict[str, list[str]] = {}
    for comp in components:
        oid = comp.get("objectid")
        sid = comp.get("_solutionid_value")
        if oid and sid:
            ref_to_solutions.setdefault(oid, []).append(sid)
    if not ref_to_solutions:
        return {}

    # Step 2: solution-guid -> {friendlyname, ismanaged} via solutions.
    # We also unconditionally include the **Default Solution** (uniquename
    # 'Default'), which is the unmanaged customization layer that always
    # exists in every Dataverse environment. It's the only place a maker
    # can edit a connection reference that was defined in a managed
    # solution — Power Apps refuses direct edits there with "You cannot
    # directly edit the objects within a managed solution." So when a ref
    # only lives in managed solutions, we fall back to Default Solution.
    distinct_sids = {sid for sids in ref_to_solutions.values() for sid in sids}
    sid_clauses = [f"solutionid eq {sid}" for sid in distinct_sids]
    sol_filter = "(" + " or ".join(sid_clauses) + ") or uniquename eq 'Default'"
    try:
        solutions = query_all(
            env_url, dv_token,
            "solutions",
            "solutionid,uniquename,friendlyname,ismanaged",
            filter_expr=sol_filter,
        )
    except Exception:
        return {}

    sid_to_info: dict[str, dict] = {}
    default_sid: str | None = None
    for sol in solutions:
        sid = sol.get("solutionid")
        if not sid:
            continue
        uname = sol.get("uniquename") or ""
        sid_to_info[sid] = {
            "label": (
                sol.get("friendlyname") or uname or sid
            ),
            "uniquename": uname,
            "ismanaged": bool(sol.get("ismanaged")),
        }
        if uname == "Default":
            default_sid = sid

    # Internal/system solutions a maker never opens in the portal — skip
    # them when ranking. (Note: 'Default' is the user-facing Default
    # Solution and IS editable, so it's NOT in this set.)
    SYSTEM_UNIQUENAMES = {"Active", "Basic", "System"}

    def _solution_rank(sid: str) -> tuple[int, int, int, str]:
        info = sid_to_info.get(sid, {})
        uname = info.get("uniquename", "")
        is_system = uname in SYSTEM_UNIQUENAMES
        is_managed = info.get("ismanaged", False)
        is_default = uname == "Default"
        # Lowest tuple wins. Prefer (in order):
        #   1. not-system over system,
        #   2. unmanaged over managed (maker can edit directly),
        #   3. a named unmanaged solution over Default (more focused
        #      view; Default is the catch-all),
        #   4. alphabetical for stability.
        return (
            1 if is_system else 0,
            1 if is_managed else 0,
            1 if is_default else 0,
            uname,
        )

    out: dict[str, dict[str, str]] = {}
    for rid, sids in ref_to_solutions.items():
        # Only consider sids we successfully resolved in step 2.
        known = [sid for sid in sids if sid in sid_to_info]
        if known:
            best = sorted(known, key=_solution_rank)[0]
            # If the best candidate is still managed (i.e. every solution
            # containing this ref is managed), redirect the link to the
            # Default Solution so the maker actually has somewhere to
            # edit. The label changes too so the report doesn't mislead
            # the maker into clicking through to a read-only solution.
            if sid_to_info[best].get("ismanaged"):
                if default_sid:
                    out[rid] = {
                        "url": maker_solution_url(env_id, default_sid),
                        "label": sid_to_info[default_sid]["label"],
                    }
                # Else: nothing editable to link to. Skip so the caller
                # falls back to the env-wide URL — better to give the
                # maker the solutions list than dump them on a managed
                # solution page that refuses edits.
                continue
            out[rid] = {
                "url": maker_solution_url(env_id, best),
                "label": sid_to_info[best]["label"],
            }
        elif default_sid:
            # No containing solution resolved — Default Solution is still
            # the right editable fallback (better than the env-wide list).
            out[rid] = {
                "url": maker_solution_url(env_id, default_sid),
                "label": sid_to_info[default_sid]["label"],
            }
    return out


def _solution_link_parts(
    ref: dict, solution_info: dict[str, dict[str, str]], fallback_url: str,
) -> tuple[str, str]:
    """Pick the best (url, label) for the solution containing a ref.

    Returns a deep link to the specific solution when we resolved its
    metadata; otherwise falls back to the env-wide solutions list so
    the remediation never produces a 404.
    """
    rid = ref.get("connectionreferenceid")
    if rid and rid in solution_info:
        info = solution_info[rid]
        return info["url"], f"Power Apps \u2192 Solutions \u2192 {info['label']}"
    return fallback_url, "Power Apps \u2192 Solutions"


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
            results.append(CheckResult(
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
        results.append(CheckResult(
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
    #
    # `connectionreference` carries no solution column — solution
    # membership is only exposed via the `solutioncomponent` intersect.
    # The deep-link resolution (`_resolve_ref_solutions`) does the
    # extra round-trip downstream, only for the broken refs we need
    # to remediate, not for every ref in the env.
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
    solutions_url = maker_solutions_url(env_id)
    connections_url = maker_connections_url(env_id)
    # Microsoft's official walkthrough for binding / editing a
    # connection reference. We surface this as doc_link so the
    # operator can follow the canonical flow if the abbreviated
    # in-remediation instructions aren't enough.
    conn_ref_doc = (
        "https://learn.microsoft.com/en-us/power-apps/maker/"
        "data-platform/create-connection-reference"
    )

    # --- Resolve containing solution for each problematic ref ---
    #
    # The env-wide solutions list dumps every first-party + ISV solution
    # in the env on the operator and leaves them guessing which one
    # holds the broken ref. Query the `solutioncomponent` intersect
    # (componenttype 10047 = Connection Reference) to map each broken
    # ref's GUID to its owning solution, then look up the friendly
    # display name + solution GUID so the per-row remediation can
    # deep-link straight to the right solution's detail page.
    #
    # The lookup is best-effort: any failure (Dataverse error, missing
    # field, missing solution) cleanly falls back to the env-wide
    # solutions list URL so the remediation never silently 404s.
    problematic_refs = orphan_refs + unbound_refs
    solution_info = _resolve_ref_solutions(
        env_url=env_url, dv_token=dv_token,
        env_id=env_id, refs=problematic_refs,
    )

    if has_orphan_refs:
        # Build the most specific summary remediation we can:
        #   - All broken refs in ONE resolved solution → deep-link to it
        #   - Broken refs span MULTIPLE resolved solutions → name them
        #     all, but the link has to fall back to the env-wide list
        #     (no single deep link covers multiple solutions)
        #   - Lookup didn't resolve any solution → generic prose
        distinct_solutions = {
            (info["url"], info["label"])
            for info in solution_info.values()
        }
        if len(distinct_solutions) == 1:
            sol_url, sol_label = next(iter(distinct_solutions))
            remediation = (
                f"Fix broken connection references: open [Power Apps \u2192 Solutions "
                f"\u2192 {sol_label}]({sol_url}) \u2192 in the left nav choose "
                f"**Objects \u2192 Connection references** \u2192 re-bind each broken "
                f"reference to a valid connection, or remove stale references."
            )
        elif len(distinct_solutions) > 1:
            names = ", ".join(sorted(label for _, label in distinct_solutions))
            remediation = (
                f"Fix broken connection references (spread across solutions: {names}). "
                f"Open [Power Apps \u2192 Solutions]({solutions_url}), open each "
                f"affected solution, and in the left nav choose **Objects \u2192 "
                f"Connection references** to re-bind each broken reference or remove "
                f"stale ones. See the ENV-004-OR-* / ENV-004-UR-* detail rows below "
                f"for per-reference deep links."
            )
        else:
            remediation = (
                f"Fix broken connection references: open [Power Apps \u2192 Solutions]({solutions_url}) "
                f"\u2192 click the solution that contains your agent \u2192 in the left nav choose "
                f"**Objects \u2192 Connection references** \u2192 re-bind each broken reference to a "
                f"valid connection, or remove stale references."
            )
    elif has_unbound_conns:
        remediation = (
            f"Unbound connections may be intentional (e.g. test connections). "
            f"Review them in [the environment connections list]({connections_url}) and remove unused entries."
        )

    # When the summary is FAILED, the operator needs to fix connection
    # references; surface Microsoft's canonical walkthrough as doc_link
    # so they have the full reference next to the abbreviated steps.
    summary_doc_link = (
        conn_ref_doc
        if overall_status == Status.FAILED.value
        else f"{DOC_BASE}/prepare#set-up-your-power-platform-environment"
    )
    results.append(CheckResult(
        checkpoint_id="ENV-004", category="Environment",
        priority=Priority.HIGH.value, status=overall_status,
        description="Connections & connection references",
        result=" | ".join(summary_parts),
        remediation=remediation,
        doc_link=summary_doc_link,
    ))

    # --- Detail: orphan references (point to missing connections) ---
    for i, ref in enumerate(orphan_refs):
        ref_name = ref.get("connectionreferencedisplayname") or ref.get(
            "connectionreferencelogicalname", "Unknown"
        )
        dead_conn_id = ref.get("connectionid", "?")
        sol_url, sol_label = _solution_link_parts(ref, solution_info, solutions_url)
        results.append(CheckResult(
            checkpoint_id=f"ENV-004-OR-{i + 1:03d}", category="Environment",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=f"Orphan reference: {ref_name}",
            result=f"Points to missing connection '{dead_conn_id}'",
            remediation=(
                f"Open [{sol_label}]({sol_url}) \u2192 in the left nav choose **Objects "
                f"\u2192 Connection references** \u2192 re-bind '{ref_name}' to an active "
                f"connection, or delete the reference."
            ),
            doc_link=conn_ref_doc,
        ))

    # --- Detail: unbound references (no connectionid set) ---
    for i, ref in enumerate(unbound_refs):
        ref_name = ref.get("connectionreferencedisplayname") or ref.get(
            "connectionreferencelogicalname", "Unknown"
        )
        sol_url, sol_label = _solution_link_parts(ref, solution_info, solutions_url)
        results.append(CheckResult(
            checkpoint_id=f"ENV-004-UR-{i + 1:03d}", category="Environment",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=f"Unbound reference: {ref_name}",
            result="No connection bound to this reference",
            remediation=(
                f"Open [{sol_label}]({sol_url}) \u2192 in the left nav choose **Objects "
                f"\u2192 Connection references** \u2192 bind '{ref_name}' to a valid connection."
            ),
            doc_link=conn_ref_doc,
        ))

    # --- Detail: unbound connections (no reference in THIS agent's solution
    # points to them). ``unbound`` here is scoped to the agent under check:
    # the connection might still be in use by another agent, a Power Automate
    # flow that connects directly without a connection reference, or a
    # canvas/model-driven app. We don't query env-wide to confirm true
    # disuse, so the remediation MUST be explicit about that limitation
    # and walk the maker through verifying before deletion. Deleting a
    # connection that something else depends on breaks that resource
    # silently \u2014 the platform does not warn.
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
            result=(
                f"Connector: {connector_label} | Status: {conn_status} | "
                f"Not referenced by this agent's solution"
            ),
            remediation=(
                f"This connection is not referenced by THIS agent's solution, "
                f"but it may still be used by another agent, a Power Automate "
                f"flow, or an app in this environment. **Verify it is unused "
                f"before deleting** \u2014 the platform does not warn if you "
                f"delete a connection that something else depends on. "
                f"To verify: "
                f"(1) open [Power Automate \u2192 Connections]({connections_url}) "
                f"and click '{conn_name}' \u2014 the detail page lists apps "
                f"that depend on it; "
                f"(2) open [Power Automate \u2192 My flows]"
                f"(https://make.powerautomate.com/environments/{runner.env_id}/flows) "
                f"and check whether any flow authenticates via the "
                f"'{connector_label}' connector; "
                f"(3) open other [solutions in this environment]"
                f"(https://make.powerapps.com/environments/{runner.env_id}/solutions) "
                f"and check their **Objects \u2192 Connection references**. "
                f"If nothing depends on '{conn_name}', delete it from the "
                f"Power Automate Connections list."
            ),
        ))

    return results
