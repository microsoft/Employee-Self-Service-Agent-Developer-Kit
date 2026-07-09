# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared Workday Enterprise App user-assignment assessment.

The Workday SSO gallery enterprise app must require user assignment AND
have at least one user/group assigned, or the OBO/OAuth handshake at first
agent access fails for end users (Sev 2 — issue
microsoft/Employee-Self-Service-Agent-Developer-Kit#79).

Two checkpoints assert exactly this, against the *same* Entra enterprise
app (discovered by ``applicationTemplateId`` so a tenant-side rename can't
hide it), and therefore share this one implementation so they never drift:

  * ``AUTH-005`` (Authentication category — runtime-readiness framing),
    ``checks/authentication._check_workday_app_user_assignment``.
  * ``WD-ASSIGN-001`` (Entra App category — S3.4 setup framing),
    ``checks/entra_app``.

``build_assignment_results`` renders identical verdict logic under whichever
``checkpoint_id`` / ``category`` / ``priority`` / ``roles`` / ``doc_link``
the caller supplies.
"""

import json
import os

from ..runner import CheckResult, Role, Status

# Entra gallery applicationTemplate displayName prefix we use to
# resolve the immutable templateId(s) for the Workday SSO gallery
# entries. The /applicationTemplates catalog is tenant-independent
# Microsoft-curated metadata, so this prefix matches a small fixed
# set of templates (e.g. "Workday", "Workday to Active Directory User
# Provisioning"); we then filter the result by the SSO mode field
# (``supportedSingleSignOnModes`` contains ``saml`` or ``oidc``) to
# keep only the federated-SSO templates and exclude provisioning-only
# entries.
#
# We discover Workday Enterprise App service principals by
# ``servicePrincipal.applicationTemplateId`` rather than by
# ``displayName`` so the check survives a tenant-side rename of the
# SP (e.g. customer renames it to "ESS SSO Provider"). The
# applicationTemplateId is set by Entra at provisioning time and is
# immutable thereafter.
_WORKDAY_TEMPLATE_NAME_PREFIX = "Workday"
# Per Microsoft Graph CSDL the ``applicationTemplate.categories`` array
# uses values like "Human resources", "Productivity", "Collaboration" —
# there is NO "Single sign-on" category. The SSO discriminator is the
# ``supportedSingleSignOnModes`` array, whose documented values are
# ``saml``, ``oidc``, ``password``, and ``notSupported`` (the gallery
# Workday entry uses ``saml``). We accept any federated mode.
# Docs: https://learn.microsoft.com/graph/api/resources/applicationtemplate
_SSO_MODES: frozenset[str] = frozenset({"saml", "oidc"})


def resolve_workday_template_ids(graph) -> list[str]:
    """Resolve the Entra gallery template id(s) for the Workday SSO app.

    Returns the list of ``applicationTemplate.id`` values whose
    ``displayName`` starts with "Workday" AND whose
    ``supportedSingleSignOnModes`` array contains a federated SSO mode
    (``saml`` or ``oidc``). An empty list means the
    /applicationTemplates lookup returned no matching SSO templates
    (treated by the caller as "Workday SSO not resolvable" — surfaces
    a WARNING rather than silently skipping the whole check).
    """
    templates = graph.get_application_templates(
        filter_expr=f"startswith(displayName,'{_WORKDAY_TEMPLATE_NAME_PREFIX}')"
    )
    ids: list[str] = []
    for t in templates:
        modes = t.get("supportedSingleSignOnModes") or []
        if any(m in _SSO_MODES for m in modes):
            tid = t.get("id")
            if isinstance(tid, str) and tid:
                ids.append(tid)
    return ids


def _workday_hints(config) -> tuple[str, str]:
    """Return ``(entraAppId, entraAppObjectId)`` for the configured Workday app.

    ``entraAppId`` is what disambiguates / scopes the Workday service
    principal (see ``_select_workday_sp`` and ``build_assignment_results``)
    and ``entraAppObjectId`` steers the application lookup. The config-schema
    documents both as top-level keys of ``.local/config.json`` — the file
    FlightCheck loads into ``runner.config`` — so that source wins. In
    practice the connect / setup playbooks currently persist them to
    ``.local/connect/workday/config.json`` instead, which the runner never
    loads; without a fallback the hint is always empty at runtime and the
    consent / assignment / NameID checks silently validate ``sps[0]`` (an
    arbitrary sibling Workday app). We therefore fall back to that connect
    config. Any read/parse error degrades to empty hints (→ unscoped /
    ``sps[0]`` behavior), never raising — FlightCheck emitters must not throw.
    """
    cfg = config or {}
    app_id = str(cfg.get("entraAppId") or "").strip()
    obj_id = str(cfg.get("entraAppObjectId") or "").strip()
    if app_id and obj_id:
        return app_id, obj_id
    try:
        connect_path = os.path.join(".local", "connect", "workday", "config.json")
        with open(connect_path, encoding="utf-8") as f:
            connect = json.load(f)
        if isinstance(connect, dict):
            app_id = app_id or str(connect.get("entraAppId") or "").strip()
            obj_id = obj_id or str(connect.get("entraAppObjectId") or "").strip()
    except Exception:  # noqa: BLE001 — missing/invalid connect config → no hint
        pass
    return app_id, obj_id


def _select_workday_sp(sps: list[dict], app_id_hint: str) -> dict | None:
    """Pick the operator's Workday SP from the template-filtered candidates.

    A single tenant routinely has *several* service principals provisioned
    from the same Workday SSO gallery template (dev / test / prod instances,
    demos, Okta trials, ...). They all share ``applicationTemplateId``, so
    the template filter returns every one of them. Blindly taking ``sps[0]``
    validates whichever the directory happens to return first — which may
    not be the app this ESS deployment configured. That mis-selection makes
    a correctly-consented app report FAILED because an unrelated sibling
    lacks admin consent (issue observed live: 6 Workday SPs, ``sps[0]`` had
    only ``user_impersonation`` while the configured app had the full
    openid/profile/User.Read grant).

    When the skill-3 playbook has recorded ``entraAppId`` we disambiguate by
    matching ``servicePrincipal.appId`` to it (appId is shared by an app
    registration and its enterprise-app service principal). Absent a hint,
    or when no candidate matches it, we fall back to the first candidate so
    behavior is unchanged for un-configured / single-SP tenants.
    """
    if not sps:
        return None
    hint = app_id_hint.strip().lower()
    if hint:
        for sp in sps:
            if str(sp.get("appId", "")).strip().lower() == hint:
                return sp
    return sps[0]


def build_assignment_results(
    graph,
    *,
    cp_id: str,
    category: str,
    description: str,
    priority: str,
    doc_link: str,
    roles: list[str] | None = None,
    app_id_hint: str = "",
) -> list[CheckResult]:
    """Assess the Workday Enterprise App's user-assignment posture and
    render one-or-more CheckResults under the caller's checkpoint identity.

    Validation logic (per issue #79):

      1. Resolve the Workday SSO Entra gallery template id(s) via
         ``GET /applicationTemplates?$filter=startswith(displayName,'Workday')``
         filtered to ``supportedSingleSignOnModes`` containing ``saml``
         or ``oidc``.
      2. Locate the Workday Enterprise Application service principal(s)
         via ``GET /servicePrincipals?$filter=applicationTemplateId in (...)``.
         Matching by ``applicationTemplateId`` (rather than displayName)
         catches SPs that the customer renamed.
      3. For each, read ``appRoleAssignmentRequired`` (Edm.Boolean).
         - ``False`` → WARNING (deploy-time check cannot guarantee per-user
           access at runtime; recommend setting it to Yes and assigning an
           ESS group).
         - ``True`` → query
           ``GET /servicePrincipals/{id}/appRoleAssignedTo``:
           * No assignments → FAILED (OBO will fail for all users).
           * At least one Group assignment → PASSED.
           * Only User-typed assignments → WARNING (works, but a security
             group is the supportable pattern).

    If no Workday SP is found, return SKIPPED — the customer tenant doesn't
    have the Workday SSO app provisioned yet, so this gate isn't
    applicable until they install it.

    ``app_id_hint`` (the operator's configured ``entraAppId``) scopes the
    assessment to a single service principal: when it matches one of the
    template-provisioned candidates, only that app is assessed; when it
    matches none, return SKIPPED (rather than assessing unrelated sibling
    Workday apps and reporting their posture as this deployment's). An empty
    hint preserves the original behavior of assessing every Workday SSO SP.
    """
    roles = roles if roles is not None else [Role.ENTRA_ADMIN.value]

    if not graph:
        return [CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.SKIPPED.value,
            description=description,
            result="Microsoft Graph client not available (auth skipped).",
        )]

    try:
        template_ids = resolve_workday_template_ids(graph)
    except Exception as e:
        return [CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.WARNING.value,
            description=description,
            result=(
                "Unable to resolve Workday SSO gallery template id from "
                f"/applicationTemplates: {e}"
            ),
            remediation=(
                "Re-run FlightCheck with a Graph token that can read "
                "/applicationTemplates (no extra consent required for "
                "tenant-independent gallery metadata)."
            ),
        )]

    if not template_ids:
        return [CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.WARNING.value,
            description=description,
            result=(
                "No federated-SSO Workday applicationTemplate found in "
                "the Entra gallery catalog (no template whose "
                "supportedSingleSignOnModes contains 'saml' or 'oidc'). "
                f"{cp_id} cannot identify the Workday Enterprise App "
                "without it."
            ),
            remediation=(
                "This is unexpected — Microsoft ships at least one "
                "Workday SSO template in the gallery. Please file an "
                "issue against FlightCheck so the lookup can be updated."
            ),
        )]

    try:
        # Match SPs by applicationTemplateId — immutable and rename-proof.
        # Expand the in() set to explicit ORs since v1.0 $filter does
        # not support the `in` operator on applicationTemplateId.
        template_clause = " or ".join(
            f"applicationTemplateId eq '{tid}'" for tid in template_ids
        )
        filter_clause = f"({template_clause})"
        sps = graph.get_service_principals(filter_expr=filter_clause)
    except Exception as e:
        return [CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.WARNING.value,
            description=description,
            result=f"Unable to query Workday Enterprise App: {e}",
            remediation=(
                "Requires Application.Read.All or Directory.Read.All on the "
                "Graph token. Re-run FlightCheck with an account that holds "
                "those permissions."
            ),
        )]

    if not sps:
        return [CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.SKIPPED.value,
            description=description,
            result=(
                "No Enterprise Application provisioned from the Workday "
                f"SSO gallery template(s) ({', '.join(template_ids)}) "
                "found in this tenant. The Workday SSO app must be "
                "provisioned before this check applies."
            ),
            remediation=(
                "Install the Workday Enterprise Application from the Entra "
                "gallery and re-run FlightCheck. See the ESS Workday "
                "prerequisites: " + doc_link
            ),
        )]

    # Scope to the configured Workday app when the operator has recorded
    # its ``entraAppId`` (via ``app_id_hint``). A tenant routinely has
    # several service principals from the same Workday SSO gallery template
    # (dev / test / prod, demos, Okta trials, ...); evaluating siblings the
    # ESS deployment never configured produces false FAILEDs driven by apps
    # nobody assigned. When the hint matches one of the candidates we assess
    # only that app; when it matches none we SKIP with a clear message
    # rather than reverting to the noisy all-SPs assessment. Without a hint
    # (un-configured tenant) we keep the original behavior of assessing
    # every Workday SSO SP.
    hint = app_id_hint.strip().lower()
    if hint:
        scoped = [
            sp for sp in sps
            if str(sp.get("appId", "")).strip().lower() == hint
        ]
        if scoped:
            sps = scoped
        else:
            return [CheckResult(roles=roles,
                checkpoint_id=cp_id, category=category,
                priority=priority, status=Status.SKIPPED.value,
                description=description,
                result=(
                    f"The configured Workday app (entraAppId={app_id_hint}) "
                    "was not found among the "
                    f"{len(sps)} Enterprise Application(s) provisioned from "
                    f"the Workday SSO gallery template(s) "
                    f"({', '.join(template_ids)}) in this tenant. Assignment "
                    "posture cannot be assessed for it."
                ),
                remediation=(
                    "Confirm the Workday Enterprise Application referenced by "
                    "entraAppId is provisioned from the Workday SSO gallery "
                    "template, or update the configured entraAppId to match "
                    "the intended app, then re-run FlightCheck. See the ESS "
                    "Workday prerequisites: " + doc_link
                ),
            )]

    # Classify each Workday SP into a status bucket. We emit at most
    # one CheckResult per status so the report doesn't get a separate
    # row for every SP — see issue: per-SP rows make the readiness
    # summary unreadable when a tenant has multiple Workday apps
    # (SSO + OAuth + Implementation tenant, etc.).
    #
    # Per-SP tuples are (sp_name, current_state, fix_action). The
    # current_state describes what we observed for THIS SP and goes
    # into the row's result. The fix_action describes how to fix the
    # status and goes into the row's remediation; it must NOT embed
    # the SP name so identical fixes across multiple SPs collapse to
    # a single de-duplicated remediation line.
    failed_items: list[tuple[str, str, str]] = []
    warning_items: list[tuple[str, str, str]] = []
    passed_items: list[tuple[str, str]] = []

    for sp in sps:
        sp_id = sp.get("id", "")
        sp_name = sp.get("displayName", "(unnamed)")
        required = sp.get("appRoleAssignmentRequired")

        if not sp_id:
            # Should not happen — Graph always returns id on /servicePrincipals
            # — but guard rather than crash if a future schema change drops it.
            warning_items.append((
                sp_name,
                "service principal returned without an id field",
                "Re-run FlightCheck; if this persists, file an issue.",
            ))
            continue

        if required is False:
            warning_items.append((
                sp_name,
                "'Assignment required?' is set to No — any licensed user in "
                "the tenant can obtain a Workday SSO token regardless of "
                "group membership; the Users and groups list is "
                "informational only when this is No",
                "Hardening recommendation (not a functional blocker — ESS "
                "works with this set to No). Setting 'Assignment required?' "
                "to Yes restricts Workday token issuance to explicitly "
                "assigned users/groups, shrinks the OBO impersonation "
                "surface, and gives you deploy-time provable group-based "
                "access control. In Entra → Enterprise Applications, open "
                "the app(s) above → Properties → set 'Assignment required?' "
                "to Yes, then under Users and groups assign the ESS user "
                "security group.",
            ))
            continue

        # appRoleAssignmentRequired is True or absent (Graph defaults to
        # False, but the schema lets it be omitted; we conservatively
        # continue to the assignment check when missing).
        try:
            assignments = graph.get_app_role_assignments(sp_id)
        except PermissionError as e:
            # Distinct from the generic Exception arm below: a 401/403
            # on /appRoleAssignedTo would otherwise look identical to
            # a legitimately empty list (get_all swallows the status
            # code into []), so get_app_role_assignments raises here
            # explicitly. We route to WARNING with a permission-
            # specific remediation, NOT to the FAILED 'no assignments'
            # branch — false-alarming a Sev-2-shaped finding on a
            # tenant whose only problem is the kit's own token scope
            # is exactly the wrong direction for a check whose intro
            # says it was filed to catch a real Sev 2 (issue #79).
            warning_items.append((
                sp_name,
                "insufficient permission to list assigned users/groups "
                f"({e})",
                "Re-run FlightCheck with a Graph token that holds "
                "Application.Read.All or Directory.Read.All, and "
                "confirm no Conditional Access policy or scoped "
                "directory role denies access to this service "
                "principal's appRoleAssignedTo endpoint. Without "
                "this, the check cannot distinguish 'no assignments' "
                "(a real Sev 2 misconfiguration) from 'we can't see "
                "the assignments' (a kit-token problem).",
            ))
            continue
        except Exception as e:
            warning_items.append((
                sp_name,
                f"unable to list assigned users/groups ({e})",
                "Re-run FlightCheck with a Graph token that holds "
                "Application.Read.All or Directory.Read.All.",
            ))
            continue

        if not assignments:
            failed_items.append((
                sp_name,
                "user assignment required, 0 users/groups assigned",
                "In Entra → Enterprise Applications, open the app(s) above → "
                "Users and groups → assign the ESS user security group "
                "(preferred over individual users) before deploying. "
                "Without this, the OBO/OAuth handshake on first agent "
                "access fails for ALL end users.",
            ))
            continue

        groups = [a for a in assignments if a.get("principalType") == "Group"]
        users_only = all(a.get("principalType") == "User" for a in assignments)

        if groups:
            group_names = ", ".join(
                a.get("principalDisplayName", "?") for a in groups[:3]
            )
            extra = "" if len(groups) <= 3 else f" (+{len(groups) - 3} more)"
            passed_items.append((
                sp_name,
                f"user assignment required, {len(assignments)} principal(s) "
                f"assigned including {len(groups)} group(s) — "
                f"{group_names}{extra}",
            ))
        elif users_only:
            warning_items.append((
                sp_name,
                f"user assignment required, {len(assignments)} individual "
                "user(s) assigned but no security groups",
                "Assign an ESS user security group to the app(s) above "
                "(in addition to or instead of individual users) so new ESS "
                "users get access automatically.",
            ))
        else:
            # Mix of types we didn't categorize (e.g. ServicePrincipal-only).
            passed_items.append((
                sp_name,
                f"user assignment required, {len(assignments)} principal(s) "
                "assigned",
            ))

    results: list[CheckResult] = []

    # Emit at most one row per status, in priority order so the most
    # urgent finding appears first in the report.
    #
    # NOTE: All three buckets below share ``checkpoint_id=cp_id`` by
    # design — the operator sees up to three rows with the same id,
    # one per status bucket, each enumerating the SPs in that bucket.
    # This pattern depends on the report renderer being a FLAT LIST
    # over ``RunResult.results`` (no keying or dedup by checkpoint_id):
    #   * ``runner._generate_html_report`` emits one ``<tr>`` per
    #     ``r.results`` entry (runner.py).
    #   * ``runner.run`` aggregates category counts by iterating, not
    #     by indexing by checkpoint_id.
    #   * ``cli.py`` prints summaries by iteration.
    # The regression guard for the renderer side lives in
    # ``tests/flightcheck/test_runner.py`` —
    # ``test_html_report_preserves_multiple_results_with_same_checkpoint_id``.
    # If you change either the renderer keying or the buckets here,
    # update both ends together.
    if failed_items:
        results.append(CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.FAILED.value,
            description=description,
            result=_format_sp_state(failed_items),
            remediation=_format_sp_remediations(failed_items),
            doc_link=doc_link,
        ))

    if warning_items:
        results.append(CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.WARNING.value,
            description=description,
            result=_format_sp_state(warning_items),
            remediation=_format_sp_remediations(warning_items),
            doc_link=doc_link,
        ))

    if passed_items:
        results.append(CheckResult(roles=roles,
            checkpoint_id=cp_id, category=category,
            priority=priority, status=Status.PASSED.value,
            description=description,
            result=_format_sp_state(passed_items),
            doc_link=doc_link,
        ))

    return results


def _format_sp_state(items: list[tuple]) -> str:
    """Render per-SP current-state phrases into one result string.

    Single SP → ``"Workday SP 'X': <state>."`` (preserves the historical
    one-line format the operator is used to).
    Multiple SPs → header + one bullet per SP. The HTML report
    preserves whitespace in result cells (``cell-text`` class added in
    PR #113), so the bullets render on separate lines.

    Tuples may be ``(name, state)`` for the passed bucket or
    ``(name, state, _fix)`` for the failed/warning buckets — only the
    first two elements are read here.
    """
    if len(items) == 1:
        name, state = items[0][0], items[0][1]
        return f"Workday SP '{name}': {state}."
    lines = [f"{len(items)} Workday Enterprise App(s):"]
    for item in items:
        name, state = item[0], item[1]
        lines.append(f"  • '{name}': {state}")
    return "\n".join(lines)


def _format_sp_remediations(items: list[tuple[str, str, str]]) -> str:
    """Render per-SP fix actions into one remediation string.

    Fix actions never embed SP names (the result already lists the
    affected apps), so identical fixes across SPs collapse to one line.
    When SPs in the same status bucket need different fixes (e.g. one
    has Assignment Required=No and another has only individual users),
    we emit each distinct fix on its own bulleted line.
    """
    distinct = list(dict.fromkeys(item[2] for item in items if item[2]))
    if not distinct:
        return ""
    if len(distinct) == 1:
        return distinct[0]
    return "\n".join(f"  • {fix}" for fix in distinct)
