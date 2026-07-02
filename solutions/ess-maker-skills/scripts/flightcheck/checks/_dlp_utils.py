# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared Data Loss Prevention (DLP) parsing + connector-classification helpers.

Single source of truth for reasoning about Power Platform DLP (data)
policies across FlightCheck checks:

  * ENV-008 (``checks/environment``) — *coverage*: does *a* policy apply
    to the environment at all?
  * INFRA-006 (``checks/infrastructure``) — *classification*: is every
    connector the agent depends on allowed and co-grouped, with none
    Blocked?

The apiPolicies (api-version 2021-04-01) endpoint returns a policy in one
of TWO shapes; this module parses both.

Legacy / documented shape — ``properties.connectorGroups``::

    policy["properties"]["connectorGroups"] = [
        {"classification": "Confidential" | "General" | "Blocked",
         "connectors": [
             {"id": "/providers/Microsoft.PowerApps/apis/shared_x", ...},
         ]},
        ...
    ]

The PowerShell/REST classification vocabulary is ``Confidential``
(= Business), ``General`` (= Non-Business), ``Blocked``. The Power
Platform admin center UI labels these Business / Non-Business / Blocked.
Both spellings are accepted defensively.

Modern shape — ``properties.definition.apiGroups`` (what real tenants
return; verified against a live apiPolicies response, 2026-06-30)::

    policy["properties"]["definition"] = {
        "apiGroups": {
            "hbi":     {"description": "Business data only",
                        "apis": [{"id": ".../shared_x", ...}, ...]},
            "lbi":     {"description": "No business data allowed",
                        "apis": [...]},
            "blocked": {"apis": [...]},
        },
        "defaultApiGroup": "lbi",   # group unlisted connectors inherit
        ...
    }

Here the group KEY is the classification: ``hbi`` = Business,
``lbi`` = Non-Business, ``blocked`` = Blocked. Unlike the legacy shape,
the modern shape reports ``defaultApiGroup``, so a connector absent from
every explicit group inherits a KNOWN group instead of being
indeterminate.

Multi-policy rule (Power Platform): when several policies apply to one
environment, the *most restrictive* policy wins. A connector Blocked in
ANY effective policy is effectively blocked, and connectors split across
groups in ANY policy can't be combined in a single app, flow, or agent
action.
Source: https://learn.microsoft.com/power-platform/guidance/adoption/dlp-strategy

Out of scope (v1, heritage INFRA-006 = classic data policies only):
advanced connector policies (ACP) and tenant-level custom-connector
URL-pattern rules — a different governance model the API also exposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auth import query_all  # scripts/auth.py, on path via cli.py


# ── Group labels (internal canonical form) ───────────────────────────────
BUSINESS = "business"
NON_BUSINESS = "nonbusiness"
BLOCKED = "blocked"

# Wire/UI classification token → canonical group. Accept both the
# PowerShell/REST vocabulary (Confidential/General) and the admin-center
# UI labels (Business/Non-Business) so the parser is robust to either.
_TOKEN_TO_GROUP = {
    "confidential": BUSINESS,
    "business": BUSINESS,
    "general": NON_BUSINESS,
    "nonbusiness": NON_BUSINESS,
    "non-business": NON_BUSINESS,
    "blocked": BLOCKED,
}

_GROUP_LABEL = {
    BUSINESS: "Business",
    NON_BUSINESS: "Non-Business",
    BLOCKED: "Blocked",
}

# Modern schema (properties.definition.apiGroups) uses the group KEY as the
# classification: hbi = Business, lbi = Non-Business, blocked = Blocked.
# The same keys appear in properties.definition.defaultApiGroup.
_APIGROUP_KEY_TO_GROUP = {
    "hbi": BUSINESS,
    "lbi": NON_BUSINESS,
    "blocked": BLOCKED,
}

# Power Platform admin center — Data policies area. There is no documented,
# stable per-policy/per-connector deep-link anchor in the PPAC SPA, so we
# link to the Data policies list and name the offending policy + connector
# in the remediation text.
_PPAC_DLP_POLICIES_URL = "https://admin.powerplatform.microsoft.com/dlp/policies"


def ppac_dlp_policies_url() -> str:
    """Deep link to the Power Platform admin center **Data policies** list."""
    return _PPAC_DLP_POLICIES_URL


def classify_token(token: str | None) -> str | None:
    """Map a DLP classification token to a canonical group, or ``None``.

    ``None`` means the token was absent or unrecognized — the connector is
    treated as not-explicitly-classified by that policy.
    """
    if not token:
        return None
    return _TOKEN_TO_GROUP.get(str(token).strip().lower())


def group_label(group: str | None) -> str:
    """Human-readable label for a canonical group (for report text)."""
    return _GROUP_LABEL.get(group or "", "Unclassified")


def normalize_connector_id(raw: str | None) -> str:
    """Reduce a connector id/path to its stable identity (the ``shared_x`` name).

    Dataverse ``connectionreferences.connectorid`` and DLP
    ``connectors[].id`` both use the
    ``/providers/Microsoft.PowerApps/apis/<name>`` shape, but casing and the
    provider prefix can vary between surfaces. Comparing on the lowercased
    last path segment makes the match robust.

    ASSUMPTION (locked by tests): the agent uses **certified** connectors
    whose api-name is stable across surfaces (``shared_commondataserviceforapps``,
    ``shared_workdaysoap``, ``shared_service-now``, ``shared_webcontents``).
    A **custom** connector is environment-scoped and may carry a GUID suffix
    that differs between the Dataverse and DLP surfaces; its last segment
    will not match, so it reads as 'absent from all groups' and degrades to
    a WARN (indeterminate) rather than matching. That is the safe direction
    for combinable/blocked detection EXCEPT it can mask a custom connector
    that is genuinely Blocked (reported as WARN, not FAIL). ESS ships
    certified connectors today; revisit if custom connectors enter scope.
    """
    if not raw:
        return ""
    return str(raw).strip().rstrip("/").rsplit("/", 1)[-1].lower()


def iter_effective_policies(pp, env_id: str):
    """Return the DLP policies effective on ``env_id``.

    Thin pass-through to the PP-Admin client so every check reads DLP state
    through one seam. Returns a ``list`` of policy dicts, or a
    ``{"_error": ...}`` dict when the admin endpoint denied access.
    """
    return pp.get_dlp_policies_for_env(env_id)


def policy_connector_groups(policy: dict | None) -> dict[str, str]:
    """Map ``normalized connector id → canonical group`` for one policy.

    Parses whichever schema the policy uses:

    * Legacy: ``properties.connectorGroups[].{classification, connectors[].id}``.
    * Modern: ``properties.definition.apiGroups.{hbi|lbi|blocked}.apis[].id``.

    A policy carries only one of the two shapes, so reading both is safe.
    Connectors whose group token/key is unrecognized are skipped (treated as
    not-explicitly-classified). Default-group fallthrough is resolved by
    ``policy_default_group`` at evaluation time, not here.
    """
    out: dict[str, str] = {}
    if not isinstance(policy, dict):
        return out
    props = policy.get("properties", {})
    if not isinstance(props, dict):
        return out

    # Legacy shape: properties.connectorGroups[]
    for grp in props.get("connectorGroups") or []:
        group = classify_token(grp.get("classification"))
        if group is None:
            continue
        for conn in grp.get("connectors", []) or []:
            cid = normalize_connector_id(conn.get("id") or conn.get("name"))
            if cid:
                out[cid] = group

    # Modern shape: properties.definition.apiGroups.{hbi|lbi|blocked}.apis[]
    definition = props.get("definition")
    if isinstance(definition, dict):
        api_groups = definition.get("apiGroups")
        if isinstance(api_groups, dict):
            for key, gval in api_groups.items():
                group = _APIGROUP_KEY_TO_GROUP.get(str(key).strip().lower())
                if group is None or not isinstance(gval, dict):
                    continue
                for api in gval.get("apis", []) or []:
                    cid = normalize_connector_id(api.get("id") or api.get("name"))
                    if cid:
                        out[cid] = group
    return out


def policy_default_group(policy: dict | None) -> str | None:
    """Canonical group unlisted connectors inherit, or ``None`` if unknown.

    Modern policies expose ``properties.definition.defaultApiGroup``
    (e.g. ``"lbi"``), so a connector absent from every explicit group still
    resolves to a KNOWN group. Legacy ``connectorGroups`` policies do not
    report a default — this returns ``None`` and the connector stays
    indeterminate (unchanged legacy behavior).
    """
    if not isinstance(policy, dict):
        return None
    definition = policy.get("properties", {}).get("definition")
    if not isinstance(definition, dict):
        return None
    key = definition.get("defaultApiGroup")
    if not key:
        return None
    return _APIGROUP_KEY_TO_GROUP.get(str(key).strip().lower())


def policy_label(policy: dict | None) -> str:
    """Display name for a policy (falls back to its id, then a generic label)."""
    if not isinstance(policy, dict):
        return "DLP policy"
    props = policy.get("properties", {})
    return props.get("displayName") or policy.get("name") or "DLP policy"


def agent_connector_ids(env_url: str, dv_token: str) -> set[str]:
    """Resolve the connectors the agent's solution depends on.

    Source of truth is the Dataverse ``connectionreferences.connectorid``
    column — the same table ENV-004 reads. Only **active** references
    (``statuscode`` 1, or absent/unknown) are treated as live dependencies;
    a disabled reference (``statuscode`` 2) is not invoked at runtime, so
    classifying it against DLP would produce a false positive. Returns a
    set of NORMALIZED connector ids.

    Raises on Dataverse failure; the caller maps that to a could-not-
    determine WARN rather than a false PASS.
    """
    refs = query_all(
        env_url,
        dv_token,
        "connectionreferences",
        "connectionreferenceid,connectorid,statuscode",
    )
    ids: set[str] = set()
    for ref in refs or []:
        # Skip references explicitly marked inactive; include active (1) and
        # unknown/missing statuscode (conservative — don't drop a dependency
        # we can't confirm is disabled).
        if ref.get("statuscode") not in (None, 1):
            continue
        cid = normalize_connector_id(ref.get("connectorid"))
        if cid:
            ids.add(cid)
    return ids


@dataclass
class DlpEvaluation:
    """Outcome of reconciling agent connectors against effective DLP policies.

    verdict:        "pass" | "fail" | "warn"
    blocked:        normalized ids Blocked in at least one effective policy
    cross_group:    True when allowed agent connectors are split across the
                    Business and Non-Business groups within some policy
    cross_group_policy: display name of the first policy that tripped
                    cross_group ("" when not cross_group)
    cross_group_groups: the conflicting group labels in that policy
    indeterminate:  normalized ids not explicitly classified by some policy
                    (default-group fallthrough — group cannot be proven)
    groups_seen:    normalized id → group label, for allowed connectors
    """

    verdict: str
    blocked: list[str] = field(default_factory=list)
    cross_group: bool = False
    cross_group_policy: str = ""
    cross_group_groups: list[str] = field(default_factory=list)
    indeterminate: list[str] = field(default_factory=list)
    groups_seen: dict[str, str] = field(default_factory=dict)


def evaluate_connector_classification(agent_ids, policies) -> DlpEvaluation:
    """Reconcile ``agent_ids`` against ``policies`` (most-restrictive wins).

    For each effective policy, classify each agent connector. A connector
    Blocked in ANY policy is blocked; agent connectors split across the
    Business and Non-Business groups within ANY single policy are
    cross-group (they can't be combined in one agent action). Connectors
    absent from a policy's explicit groups inherit that policy's
    ``defaultApiGroup`` when the modern schema reports one; only when no
    default is known (legacy ``connectorGroups`` policies) do they remain
    indeterminate — their effective grouping can't be proven.

    Verdict precedence: FAIL (blocked or cross-group) > WARN (indeterminate)
    > PASS.

    Raises ``ValueError`` when ``policies`` or ``agent_ids`` is empty: an
    empty input has no defensible verdict, and silently returning PASS
    would be a false all-clear. Callers must handle those cases before
    calling (INFRA-006 routes them to SKIPPED / WARN upstream).
    """
    agent_ids = set(agent_ids)
    if not policies:
        raise ValueError("evaluate_connector_classification requires at least one policy")
    if not agent_ids:
        raise ValueError("evaluate_connector_classification requires at least one connector")
    blocked: set[str] = set()
    indeterminate: set[str] = set()
    cross_group = False
    cross_group_policy = ""
    cross_group_groups: list[str] = []
    groups_seen: dict[str, str] = {}

    for policy in policies:
        cmap = policy_connector_groups(policy)
        default_group = policy_default_group(policy)
        allowed_groups_this_policy: set[str] = set()
        for cid in agent_ids:
            group = cmap.get(cid)
            if group is None:
                # Fall back to the policy's default group when the modern
                # schema reports one; otherwise the connector is unprovable.
                group = default_group
            if group is None:
                indeterminate.add(cid)
            elif group == BLOCKED:
                blocked.add(cid)
            else:
                allowed_groups_this_policy.add(group)
                groups_seen[cid] = _GROUP_LABEL[group]
        if len(allowed_groups_this_policy) > 1:
            cross_group = True
            # Capture the first offending policy + its conflicting groups so
            # the report can name the exact policy the operator must open,
            # rather than a union across all policies.
            if not cross_group_policy:
                cross_group_policy = policy_label(policy)
                cross_group_groups = sorted(
                    _GROUP_LABEL[g] for g in allowed_groups_this_policy
                )

    # A blocked connector is reported as blocked, not also indeterminate.
    indeterminate -= blocked

    if blocked or cross_group:
        verdict = "fail"
    elif indeterminate:
        verdict = "warn"
    else:
        verdict = "pass"

    return DlpEvaluation(
        verdict=verdict,
        blocked=sorted(blocked),
        cross_group=cross_group,
        cross_group_policy=cross_group_policy,
        cross_group_groups=cross_group_groups,
        indeterminate=sorted(indeterminate),
        groups_seen=groups_seen,
    )
