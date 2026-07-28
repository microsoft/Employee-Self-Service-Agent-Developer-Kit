# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Flow licensing pre-flight (LIC-FLOW-xxx)

Surfaces a licensing risk that the Copilot Studio authoring experience does
not warn about: when an ESS agent invokes a Power Automate cloud flow that
binds a **premium**, **custom**, or **on-premises data gateway** connector,
every end user who triggers that flow must hold a Power Automate Premium (or
Power Apps Premium) license. The seeded Power Automate for Microsoft 365
entitlement is NOT sufficient for premium / custom / on-prem connectors. When
a shared-with user lacks the license, the Power Automate runtime returns a
generic authorization error and the agent surface shows a generic "something
went wrong" reply — a failure that is silent to the maker (never paged) and
only visible to the affected end user. FlightCheck is the realistic detection
point.

Two checks:

* **LIC-FLOW-001** (this module) classifies every flow the agent references
  (topic ``InvokeFlowAction``) by the connector tier its connection
  references bind, and WARNs when any referenced flow binds a premium /
  custom connector.

* **LIC-FLOW-002** (added alongside) enumerates the principals the agent is
  shared with (Dataverse ``RetrieveSharedPrincipalsAndAccess`` on the bot
  record), resolves them to Entra users, and checks each user's assigned
  license SKUs against the required minimum — escalating to FAIL
  (publish-with-caveat) when shared users are demonstrably unlicensed.

Why connector tier and not flow type
-------------------------------------
The Story framed this as "agent flow vs traditional flow". In practice the
native-agent-flow (Copilot Studio capacity / credits) vs cloud-flow (per-user
Power Automate license) distinction is NOT cleanly determinable from the flow
definition — both can present with an agent-invocation trigger and both are
Dataverse ``workflow`` category 5. The connector *tier*, by contrast, is an
unambiguous, documented signal carried inline on each flow's connection
references, and the premium-connector licensing requirement is authoritative:

  * Power Automate licensing FAQ — premium / custom / on-prem-gateway
    connectors require a standalone Power Automate (Premium per-user or
    per-flow) plan; seeded plans cover standard connectors only.
    https://learn.microsoft.com/power-platform/admin/power-automate-licensing/faqs
  * Copilot Studio flows run on Copilot Studio capacity (credits) only when
    they are native agent flows — a cloud flow invoked by the agent still
    follows Power Automate licensing.
    https://learn.microsoft.com/microsoft-copilot-studio/flows-overview

So LIC-FLOW-001 warns on the connector signal and tells the maker, in the
remediation, that a native agent flow billed via Copilot Studio capacity may
be exempt — rather than the check hard-claiming a flow-type it cannot verify.

Data contract (validated cassette: flightcheck_flow_licensing.yaml)
-------------------------------------------------------------------
``pp_admin.get_flow(env_id, flow_id)`` returns a flow with::

    properties.connectionReferences.<refKey> = {
        "apiName": "shared_workdaysoap",
        "connectionReferenceLogicalName": "...",
        "tier": "Premium",                       # ref-level
        "apiDefinition": {"properties": {
            "displayName": "...",
            "tier": "Premium" | "Standard",      # connector-level (authoritative)
            "isCustomApi": false,                # custom connector => premium-licensed
        }},
    }

Connector tiers observed in the capture: shared_workdaysoap=Premium,
shared_commondataserviceforapps=Premium, shared_conversionservice=Standard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path

import yaml

from auth import (
    AuthExpiredError,
    query_all,
    retrieve_shared_principals_and_access,
)

from ..runner import CheckResult, Priority, Role, Status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
PA_LICENSING_FAQ = (
    "https://learn.microsoft.com/power-platform/admin/power-automate-licensing/faqs"
)
M365_LICENSES_URL = "https://admin.microsoft.com/Adminportal/Home#/licenses"

# LIC-FLOW-002 caps (Story acceptance criteria).
MAX_MEMBERS_PER_GROUP = 2000
# How many named users to list inline in a result before summarizing.
_MAX_NAMED_USERS = 12

_SKU_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "flow_licensing_skus.yaml"
_sku_table_cache: dict | None = None

# A topic action that invokes a flow carries the flow's GUID on a `flowId:`
# line (Copilot Studio export format — see samples/.../topic.yaml and the
# kit's extracted workspace/agents/<slug>/topics/*.mcs.yml). Matching the
# literal key is resilient to the surrounding nesting depth.
_FLOWID_RE = re.compile(r"flowId:\s*['\"]?([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})", re.MULTILINE)

AGENTS_ROOT = Path("workspace/agents")


def _referenced_flow_ids(agent_path: Path) -> set[str]:
    """Return the set of flow GUIDs referenced by an agent's topics.

    Scans ``<agent>/topics/*.mcs.yml`` for ``flowId:`` values emitted by
    ``InvokeFlowAction`` topic actions. Returns lowercased GUIDs.
    """
    ids: set[str] = set()
    topics_dir = agent_path / "topics"
    if not topics_dir.exists():
        return ids
    for tf in sorted(topics_dir.glob("*.mcs.yml")):
        try:
            text = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _FLOWID_RE.finditer(text):
            ids.add(m.group(1).lower())
    return ids


def _premium_connectors_in_flow(flow_detail: dict) -> list[dict]:
    """Return the premium / custom connectors a flow's connection
    references bind.

    Each entry: ``{"apiName", "display", "tier"}`` where ``tier`` is
    "Premium" or "Custom". Reads the connector-level
    ``apiDefinition.properties.tier`` / ``isCustomApi`` (authoritative),
    falling back to the ref-level ``tier`` when the inline apiDefinition
    is absent.
    """
    props = (flow_detail or {}).get("properties", {}) or {}
    crefs = props.get("connectionReferences") or {}
    out: list[dict] = []
    for ref_key, ref in crefs.items():
        if not isinstance(ref, dict):
            continue
        api_props = ((ref.get("apiDefinition") or {}).get("properties") or {})
        tier = api_props.get("tier") or ref.get("tier")
        is_custom = bool(api_props.get("isCustomApi"))
        api_name = (
            ref.get("apiName")
            or (ref.get("apiDefinition") or {}).get("name")
            or ref_key
        )
        display = api_props.get("displayName") or ref.get("displayName") or api_name
        if is_custom:
            out.append({"apiName": api_name, "display": display, "tier": "Custom"})
        elif tier == "Premium":
            out.append({"apiName": api_name, "display": display, "tier": "Premium"})
    return out


def _flow_display_name(flow_detail: dict, fallback: str) -> str:
    name = ((flow_detail or {}).get("properties", {}) or {}).get("displayName")
    return name or fallback


def _check_traditional_flow_licensing(runner) -> list[CheckResult]:
    """LIC-FLOW-001 — warn when agent-referenced flows bind premium/custom
    connectors that require per-invoking-user Power Automate licensing.

    Sets ``runner._lic_flow_premium_present`` (bool) so LIC-FLOW-002 can
    gate its (more expensive) shared-user license verification on whether
    a premium-connector flow actually exists.
    """
    runner._lic_flow_premium_present = False
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)

    # Discover referenced flow IDs across all agents on disk.
    refs_by_agent: dict[str, set[str]] = {}
    if AGENTS_ROOT.exists():
        for agent_path in sorted(p for p in AGENTS_ROOT.iterdir() if p.is_dir()):
            ids = _referenced_flow_ids(agent_path)
            if ids:
                refs_by_agent[agent_path.name] = ids
    all_flow_ids = {fid for ids in refs_by_agent.values() for fid in ids}

    if not all_flow_ids:
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="LIC-FLOW-001", category="Licensing",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Agent flow licensing",
            result="No agent topics invoke a Power Automate flow (no InvokeFlowAction references found).",
            doc_link=PA_LICENSING_FAQ,
        )]

    if not pp or not env_id:
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="LIC-FLOW-001", category="Licensing",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Agent flow licensing",
            result=(
                f"{len(all_flow_ids)} flow reference(s) found in agent topics, but "
                "connector tiers can't be resolved without Power Platform Admin access."
            ),
            remediation=(
                "Re-run FlightCheck with a Power Platform Administrator account so the "
                "connector tier of each agent-invoked flow can be read."
            ),
            doc_link=PA_LICENSING_FAQ,
        )]

    # Resolve each referenced flow's connectors.
    premium_flows: list[dict] = []   # {flow_id, name, connectors:[...]}
    not_found: list[str] = []        # 404 / None — flow genuinely absent
    auth_blocked: list[str] = []     # 401/403 — permission or expired token
    standard_count = 0
    for flow_id in sorted(all_flow_ids):
        try:
            detail = pp.get_flow(env_id, flow_id)
        except Exception:
            detail = None
        # pp_admin maps 401/403 to {"_error", "_status"} (it does not raise),
        # so an unprivileged or expired session leaves every flow unreadable.
        # That must NOT read as a clean PASS — distinguish it from a flow that
        # is simply not in the environment.
        if isinstance(detail, dict) and detail.get("_status") in (401, 403):
            auth_blocked.append(flow_id)
            continue
        if not detail or (isinstance(detail, dict) and detail.get("_error")):
            not_found.append(flow_id)
            continue
        premium = _premium_connectors_in_flow(detail)
        if premium:
            premium_flows.append({
                "flow_id": flow_id,
                "name": _flow_display_name(detail, flow_id),
                "connectors": premium,
            })
        else:
            standard_count += 1

    if not premium_flows:
        # Every flow was unreadable due to permission/token and nothing
        # resolved — we can't assert anything, so SKIP (mirrors the
        # no-pp_admin branch) rather than falsely PASS.
        if auth_blocked and standard_count == 0:
            return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="LIC-FLOW-001", category="Licensing",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description="Agent flow licensing",
                result=(
                    f"{len(auth_blocked)} agent-invoked flow(s) could not be read "
                    "(insufficient Power Platform admin rights or an expired token)."
                ),
                remediation=(
                    "Re-run FlightCheck signed in with a Power Platform Administrator "
                    "account so each agent-invoked flow's connector tier can be read."
                ),
                doc_link=PA_LICENSING_FAQ,
            )]
        detail_bits = [f"{len(all_flow_ids)} agent-invoked flow(s) checked"]
        if standard_count:
            detail_bits.append(f"{standard_count} bind only standard connectors")
        if not_found:
            detail_bits.append(f"{len(not_found)} not found in the environment")
        # Some flows were readable but others were auth-blocked — a
        # premium-connector flow may be hidden among the unreadable ones, so
        # this can't be a clean PASS.
        if auth_blocked:
            return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="LIC-FLOW-001", category="Licensing",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Agent flow licensing",
                result=(
                    "; ".join(detail_bits)
                    + f"; {len(auth_blocked)} could not be read (permission/token)."
                ),
                remediation=(
                    "A premium-connector flow may be hidden among the flow(s) that "
                    "could not be read. Re-run FlightCheck with Power Platform "
                    "Administrator rights to confirm the licensing exposure."
                ),
                doc_link=PA_LICENSING_FAQ,
            )]
        return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="LIC-FLOW-001", category="Licensing",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Agent flow licensing",
            result="; ".join(detail_bits) + ".",
            doc_link=PA_LICENSING_FAQ,
        )]

    # Build the WARNING — one row, listing every premium-binding flow.
    runner._lic_flow_premium_present = True
    lines = []
    for pf in premium_flows:
        conns = ", ".join(f"{c['display']} ({c['tier']})" for c in pf["connectors"])
        lines.append(f"'{pf['name']}' → {conns}")
    result = (
        f"{len(premium_flows)} agent-invoked flow(s) bind a premium or custom "
        f"connector: " + "; ".join(lines)
    )
    if not_found:
        result += f" ({len(not_found)} referenced flow(s) not found in the environment)"
    if auth_blocked:
        result += (
            f" ({len(auth_blocked)} referenced flow(s) could not be read — "
            "permission/token; more premium flows may be unlisted)"
        )

    remediation = (
        "Premium, custom, and on-premises data gateway connectors require every end "
        "user who triggers the flow to hold a Power Automate Premium (per-user or "
        "per-flow) or Power Apps Premium license — the seeded Power Automate for "
        "Microsoft 365 entitlement does NOT cover them, so unlicensed users get a "
        "silent runtime failure. Either (1) confirm the listed flow(s) are native "
        "Copilot Studio agent flows (which run on Copilot Studio capacity / credits "
        "and are exempt — see the flows overview doc), or (2) ensure every shared-with "
        f"user is assigned the required license in the [Microsoft 365 admin center → "
        f"Licenses]({M365_LICENSES_URL}). Review each flow in "
        "[Power Automate](https://make.powerautomate.com/). LIC-FLOW-002 verifies the "
        "shared-with users' licenses."
    )
    return [CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
        checkpoint_id="LIC-FLOW-001", category="Licensing",
        priority=Priority.HIGH.value, status=Status.WARNING.value,
        description="Agent flow licensing",
        result=result,
        remediation=remediation,
        doc_link=PA_LICENSING_FAQ,
    )]


def _load_sku_table() -> dict:
    """Load (and cache) the required-license catalog YAML.

    Returns ``{"skus": set[str], "plans": set[str]}``. On any load error
    falls back to a minimal built-in set so the check degrades to "can't
    confirm" rather than crashing.
    """
    global _sku_table_cache
    if _sku_table_cache is not None:
        return _sku_table_cache
    skus: set[str] = set()
    plans: set[str] = set()
    try:
        data = yaml.safe_load(_SKU_TABLE_PATH.read_text(encoding="utf-8")) or {}
        skus = {str(s) for s in (data.get("sku_part_numbers") or [])}
        plans = {str(s) for s in (data.get("service_plan_names") or [])}
    except (OSError, yaml.YAMLError):
        skus = {"FLOW_PER_USER", "POWERAPPS_PER_USER", "FLOW_PER_BUSINESS_PROCESS"}
        plans = {"FLOW_PER_USER", "POWERAPPS_PER_USER"}
    _sku_table_cache = {"skus": skus, "plans": plans}
    return _sku_table_cache


def _bot_ids(runner) -> list[str]:
    """Configured agent bot IDs (multi- and single-agent config shapes)."""
    config = getattr(runner, "config", None) or {}
    ids: list[str] = []
    for agent in config.get("agents", []) or []:
        bid = agent.get("botId")
        if bid and bid not in ids:
            ids.append(bid)
    single = (config.get("agent") or {}).get("botId")
    if single and single not in ids:
        ids.append(single)
    return ids


def _principal_type_and_id(principal: dict) -> tuple[str, str | None]:
    """Extract (type, id) from a RetrieveSharedPrincipalsAndAccess principal.

    The id attribute name is ``ownerid`` (both systemuser and team are
    owner entities); fall back to the entity-specific keys defensively.
    """
    ptype = (principal.get("@odata.type") or "").rsplit(".", 1)[-1].lower()
    pid = (
        principal.get("ownerid")
        or principal.get("systemuserid")
        or principal.get("teamid")
        or principal.get("id")
    )
    return ptype, pid


def _resolve_systemuser(env_url, token, user_id, entra, undetermined):
    """Map a Dataverse systemuser to its Entra object id (or record why not)."""
    rows = query_all(
        env_url, token, entity_set="systemusers",
        select="systemuserid,azureactivedirectoryobjectid,domainname,isdisabled,applicationid",
        filter_expr=f"systemuserid eq {user_id}",
    )
    if not rows:
        undetermined.append(f"system user {user_id} not found")
        return
    u = rows[0]
    # Application (service) users and disabled users don't consume an
    # interactive license and won't invoke flows as an end user — skip.
    if u.get("applicationid") or u.get("isdisabled"):
        return
    aad = u.get("azureactivedirectoryobjectid")
    name = u.get("domainname") or user_id
    if not aad:
        undetermined.append(f"user '{name}' has no Entra mapping")
        return
    entra.setdefault(aad, name)


def _resolve_team(runner, team_id, entra, undetermined, notes):
    """Expand a Dataverse team (Entra-group team via Graph, else owner/access
    team via teammembership) into Entra users."""
    env_url, token, graph = runner.env_url, runner.dv_token, getattr(runner, "graph", None)
    rows = query_all(
        env_url, token, entity_set="teams",
        select="teamid,name,teamtype,azureactivedirectoryobjectid",
        filter_expr=f"teamid eq {team_id}",
    )
    if not rows:
        undetermined.append(f"team {team_id} not found")
        return
    t = rows[0]
    name = t.get("name") or team_id
    aad = t.get("azureactivedirectoryobjectid")
    if aad:
        # Microsoft Entra group-backed team — expand the group in Graph.
        if not graph:
            undetermined.append(f"group-backed team '{name}' needs Graph to expand")
            return
        try:
            members = graph.get_group_transitive_members(aad)
        except Exception:
            undetermined.append(f"could not expand group '{name}'")
            return
        if len(members) >= MAX_MEMBERS_PER_GROUP:
            notes.append(
                f"group '{name}' has >= {MAX_MEMBERS_PER_GROUP} members; only the "
                f"first {MAX_MEMBERS_PER_GROUP} were checked"
            )
        added = 0
        licensable = 0
        for m in members[:MAX_MEMBERS_PER_GROUP]:
            upn = m.get("userPrincipalName")
            mid = m.get("id")
            # users carry a UPN (nested groups/devices don't); skip explicitly
            # disabled accounts — they can't trigger the flow, mirroring the
            # isdisabled skip in _resolve_systemuser.
            if upn and mid and m.get("accountEnabled") is not False:
                # Count every licensable member the Graph response returned,
                # independent of dedup, so we can distinguish "group empty /
                # access denied" from "members already counted via an
                # overlapping group".
                licensable += 1
                if mid not in entra:
                    added += 1
                entra.setdefault(mid, upn)
        if added == 0 and licensable == 0:
            # No licensable members at all from an Entra group-backed share is
            # ambiguous: the group may be genuinely empty, OR
            # get_group_transitive_members returned [] on a 401/403 (it does not
            # raise on permission denial). Either way the audience is UNVERIFIED,
            # so record it as undetermined — otherwise a caller sharing ONLY with
            # this group sees an empty population and a false "not shared with
            # anyone" all-clear.
            #
            # When added == 0 but licensable > 0, every member was already
            # counted via an earlier overlapping group; that is expected in
            # enterprise setups and must NOT be flagged.
            undetermined.append(
                f"shared group '{name}' resolved to 0 members "
                f"(verify GroupMember.Read.All / that the group is non-empty)"
            )
        elif added > 0:
            # Acknowledge that licensing for these users was verified through
            # their membership in the shared group (their licenseDetails reflects
            # any group-based SKU assignment transitively).
            notes.append(
                f"resolved {added} licensable user(s) via shared group '{name}'"
            )
        return
    # Owner / access team — resolve members via Dataverse teammembership.
    tm = query_all(
        env_url, token, entity_set="teammemberships",
        select="systemuserid", filter_expr=f"teamid eq {team_id}",
    )
    for row in tm:
        suid = row.get("systemuserid")
        if suid:
            _resolve_systemuser(env_url, token, suid, entra, undetermined)


def _user_license_state(graph, entra_id, required_skus, required_plans):
    """Return True (licensed) / False (no qualifying SKU) / None (couldn't read)."""
    try:
        details = graph.get_user_license_details(entra_id)
    except Exception:
        return None
    for d in details:
        if d.get("skuPartNumber") in required_skus:
            return True
        for sp in d.get("servicePlans", []) or []:
            if sp.get("servicePlanName") in required_plans:
                return True
    return False


def _summarize_users(names: list[str]) -> str:
    if len(names) <= _MAX_NAMED_USERS:
        return ", ".join(names)
    shown = ", ".join(names[:_MAX_NAMED_USERS])
    return f"{shown} (+{len(names) - _MAX_NAMED_USERS} more)"


@dataclass
class SharedPrincipalResolution:
    """The distinct population an agent is shared with / published to.

    Produced by :func:`resolve_shared_with_users`; consumed by LIC-FLOW-002
    (per-user license verification) and PRE-004 (Copilot Studio capacity
    sufficiency). Centralizing the enumeration keeps both checks counting the
    same population the same way.

    ``users`` maps Entra object id -> display (UPN / Dataverse domainname).
    ``available`` is False when the enumeration could not even start (missing
    Graph/Dataverse access or no configured botId); ``reason`` then carries
    ``"graph_dataverse"`` or ``"no_bot_id"`` so each caller can word its own
    skip/guidance.
    """
    users: dict[str, str] = field(default_factory=dict)
    undetermined: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    enumerate_failed: bool = False
    available: bool = True
    reason: str = ""


def resolve_shared_with_users(runner) -> SharedPrincipalResolution:
    """Enumerate the distinct Entra users an agent is shared with / published to.

    Reads each configured agent bot's sharing via the Dataverse
    ``RetrieveSharedPrincipalsAndAccess`` function, then resolves every
    principal to Entra users: system users directly, and teams / security
    groups by expansion (Entra group-backed teams via Graph transitive
    membership capped at ``MAX_MEMBERS_PER_GROUP``; owner/access teams via
    Dataverse ``teammemberships``). Application and disabled users are skipped
    — they don't consume an interactive seat or invoke flows as an end user.

    Requires a Graph client, a Dataverse env URL + token, and at least one
    configured ``botId``; when any is missing the result is marked
    ``available=False`` with a ``reason`` the caller maps to its own skip
    message. ``AuthExpiredError`` propagates (an expired Dataverse token is a
    blocking condition, not a soft note).
    """
    graph = getattr(runner, "graph", None)
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    bot_ids = _bot_ids(runner)

    if not graph or not env_url or not dv_token:
        return SharedPrincipalResolution(available=False, reason="graph_dataverse")
    if not bot_ids:
        return SharedPrincipalResolution(available=False, reason="no_bot_id")

    res = SharedPrincipalResolution()
    for bot_id in bot_ids:
        try:
            resp = retrieve_shared_principals_and_access(env_url, dv_token, bot_id)
        except AuthExpiredError:
            # An expired/invalid Dataverse token must surface as a blocking
            # ERROR (via the runner), not a benign per-bot WARNING — and it
            # must behave the same whichever Dataverse call hits it first
            # (_resolve_systemuser/_resolve_team let it propagate too).
            raise
        except Exception as e:
            res.undetermined.append(f"could not read sharing for agent {bot_id}: {e}")
            res.enumerate_failed = True
            continue
        for pa in (resp.get("PrincipalAccesses") or []):
            ptype, pid = _principal_type_and_id(pa.get("Principal") or {})
            if not pid:
                continue
            if ptype == "systemuser":
                _resolve_systemuser(env_url, dv_token, pid, res.users, res.undetermined)
            elif ptype == "team":
                _resolve_team(runner, pid, res.users, res.undetermined, res.notes)
            else:
                res.undetermined.append(f"unsupported principal type '{ptype or 'unknown'}'")
    return res


def _check_shared_user_licensing(runner) -> list[CheckResult]:
    """LIC-FLOW-002 — verify the agent's shared-with users hold the license
    required to run its premium-connector flows.

    Only runs when LIC-FLOW-001 found a premium/custom-connector flow
    (no risk ⇒ nothing to verify). Enumerates principals via the Dataverse
    ``RetrieveSharedPrincipalsAndAccess`` function on each agent's bot
    record, resolves them to Entra users (expanding teams/groups under
    documented caps), and checks each user's assigned SKUs against the
    data-driven required-license catalog.
    """
    if not getattr(runner, "_lic_flow_premium_present", False):
        return []  # no premium-connector flow ⇒ no licensing exposure to verify

    resolution = resolve_shared_with_users(runner)
    if not resolution.available:
        if resolution.reason == "no_bot_id":
            return [CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="LIC-FLOW-002", category="Licensing",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description="Shared-user flow licensing",
                result="No agent botId in config; can't resolve who the agent is shared with.",
                remediation="Run /setup so the agent's botId is recorded in .local/config.json.",
                doc_link=PA_LICENSING_FAQ,
            )]
        return [CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="LIC-FLOW-002", category="Licensing",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Shared-user flow licensing",
            result=(
                "A premium-connector flow is present, but shared-user licenses can't "
                "be verified without Microsoft Graph + Dataverse access."
            ),
            remediation=(
                "Re-run FlightCheck signed in with Graph (Directory.Read.All / "
                "User.Read.All) and Dataverse access so each shared-with user's "
                "license can be checked."
            ),
            doc_link=PA_LICENSING_FAQ,
        )]

    graph = getattr(runner, "graph", None)  # used for the per-user license lookups below
    table = _load_sku_table()
    required_skus, required_plans = table["skus"], table["plans"]

    # Shared population resolved once (shared helper, also used by PRE-004).
    entra = resolution.users        # entra_id -> display (UPN / domainname)
    undetermined = resolution.undetermined
    notes = resolution.notes
    enumerate_failed = resolution.enumerate_failed

    if not entra:
        # Nobody resolvable. If enumeration itself failed, that's a SKIP;
        # otherwise the agent simply isn't shared with any user yet.
        if enumerate_failed or undetermined:
            return [CheckResult(roles=[Role.M365_ADMIN.value],
                checkpoint_id="LIC-FLOW-002", category="Licensing",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Shared-user flow licensing",
                result=(
                    "Could not resolve any shared-with users: "
                    + _summarize_users(undetermined)
                ),
                remediation=(
                    "Verify FlightCheck has Dataverse + Graph read access, then re-run "
                    "so premium-connector flow licensing can be confirmed for shared users."
                ),
                doc_link=PA_LICENSING_FAQ,
            )]
        return [CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="LIC-FLOW-002", category="Licensing",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Shared-user flow licensing",
            result="The agent is not yet shared with any user; no licenses to verify.",
            doc_link=PA_LICENSING_FAQ,
        )]

    # ---- Check each resolved user's license ----
    licensed: list[str] = []
    missing: list[str] = []
    for entra_id, display in entra.items():
        state = _user_license_state(graph, entra_id, required_skus, required_plans)
        if state is True:
            licensed.append(display)
        elif state is False:
            missing.append(display)
        else:
            undetermined.append(f"could not read license for '{display}'")

    base = (
        f"{len(entra)} shared-with user(s): {len(licensed)} licensed, "
        f"{len(missing)} missing the required SKU, {len(undetermined)} undetermined"
    )
    if notes:
        base += ". " + ". ".join(notes)

    remediation_assign = (
        "Assign a qualifying license (Power Automate Premium per-user/per-flow, or "
        f"Power Apps Premium) to the user(s) above in the [Microsoft 365 admin center "
        f"→ Licenses]({M365_LICENSES_URL}); the seeded Power Automate for Microsoft 365 "
        "plan does not cover premium/custom connectors. Alternatively, confirm the "
        "flow(s) flagged by LIC-FLOW-001 are native Copilot Studio agent flows (billed "
        "via Copilot Studio capacity), or stop sharing the agent with users who don't "
        "need it."
    )

    # Escalation logic. FAIL only when we have positive proof the license
    # lookup works (>=1 licensed) AND specific users lack the SKU — this
    # avoids a mass false-FAIL when the kit's token simply can't read
    # licenseDetails (which would make every user look unlicensed).
    if missing and licensed:
        return [CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="LIC-FLOW-002", category="Licensing",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description="Shared-user flow licensing",
            result=base + f". Missing: {_summarize_users(missing)}",
            remediation="Publish-with-caveat — the agent can publish, but these users "
                        "will hit silent runtime failures until licensed. " + remediation_assign,
            doc_link=PA_LICENSING_FAQ,
        )]
    if missing and not licensed:
        # Everyone looks unlicensed — more likely a permission gap than a
        # tenant with zero premium licenses. Don't FAIL; flag to verify.
        return [CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="LIC-FLOW-002", category="Licensing",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Shared-user flow licensing",
            result=base + f". Possibly unlicensed: {_summarize_users(missing)}",
            remediation=(
                "No shared-with user showed a qualifying license. Confirm FlightCheck's "
                "sign-in has Graph User.Read.All/Directory.Read.All (so licenseDetails is "
                "readable) and re-run. If the permission is present, " + remediation_assign
            ),
            doc_link=PA_LICENSING_FAQ,
        )]
    if undetermined:
        return [CheckResult(roles=[Role.M365_ADMIN.value],
            checkpoint_id="LIC-FLOW-002", category="Licensing",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Shared-user flow licensing",
            result=base + f". Undetermined: {_summarize_users(undetermined)}",
            remediation=(
                "Some shared-with principals couldn't be resolved or read. Review them "
                "manually in the Copilot Studio sharing pane and the Microsoft 365 admin "
                "center to confirm each has the required license. " + remediation_assign
            ),
            doc_link=PA_LICENSING_FAQ,
        )]
    return [CheckResult(roles=[Role.M365_ADMIN.value],
        checkpoint_id="LIC-FLOW-002", category="Licensing",
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description="Shared-user flow licensing",
        result=base + ". All shared-with users hold a qualifying license.",
        doc_link=PA_LICENSING_FAQ,
    )]


def run_licensing_checks(runner) -> list[CheckResult]:
    """Run the flow-licensing pre-flight checks (LIC-FLOW-xxx)."""
    results: list[CheckResult] = []
    results.extend(_check_traditional_flow_licensing(runner))
    results.extend(_check_shared_user_licensing(runner))
    return results


# ---------------------------------------------------------------------------
# Copilot Studio message capacity — shared helpers.
#
# These are reused by BOTH the Prerequisites surface (PRE-004 sufficiency check,
# which sizes the shared/published population) and the skill-1 Environment
# surface (ENV-CAPACITY-001 "is capacity provisioned?" check, which runs before
# the agent exists and therefore has no population to size against). The
# allocation read and the PayG-aware status decision live here so the two
# callers can't drift; each caller still owns its own human-readable result /
# remediation phrasing (population-aware vs provisioned-only).
# ---------------------------------------------------------------------------

# Copilot Studio message capacity in the Power Platform Licensing
# "currency allocation" API (ExternalCurrencyType enum). The Sept 2025 rename
# to "Copilot Credits" did not change this API contract value.
_MCS_MESSAGES_CURRENCY = "MCSMessages"

# Capacity remediation anchors shared by PRE-004/PRE-006 and ENV-CAPACITY-001.
# The prepaid-capacity / message-credit model is documented on the Copilot
# Studio "messages management" page; the ESS prerequisites doc links there for
# "Set up Copilot Studio capacity".
_CAPACITY_DOC = (
    "https://learn.microsoft.com/en-us/microsoft-copilot-studio/"
    "requirements-messages-management?tabs=new#prepaid-capacity"
)
_CAPACITY_PORTAL = (
    "[Power Platform Admin Center > Licensing > Copilot Studio > Manage capacity]"
    "(https://admin.powerplatform.microsoft.com/billing/licenses/copilotStudio/overview)"
)
_M365_ADMIN_CENTER = "[Microsoft 365 admin center](https://admin.microsoft.com)"


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


def classify_copilot_studio_capacity(
    allocated: int | None,
    *,
    population: int | None = None,
    payg_flag: bool | None = None,
) -> tuple[str | None, str]:
    """Pure capacity verdict shared by PRE-004 and ENV-CAPACITY-001.

    Encodes the PayG-aware tri-state so the two callers can't diverge.
    Inputs are already-computed signals; this function does NO I/O.

    Args:
      allocated: MCSMessages units allocated to the environment, or ``None``
        when the allocation could not be read.
      population: the shared/published user count to size against
        (PRE-004 sufficiency mode), or ``None`` for the "is capacity
        provisioned?" mode (ENV-CAPACITY-001), where the
        allocation-vs-users comparison is skipped.
      payg_flag: Pay-as-you-go cross-check — ``True`` configured,
        ``False`` provably absent, ``None`` undetermined (e.g. PRE-005 did
        not run this pass).

    Returns ``(status, reason)``. ``status`` is a ``Status`` value for every
    reason except ``"unreadable"``, where it is ``None`` so the caller decides
    WARNING (PRE-004) vs MANUAL attestation (ENV-CAPACITY-001). ``reason`` is a
    stable code the caller maps to its own result/remediation text:

      - ``"unreadable"``       — allocation could not be read.
      - ``"covered"``          — allocation > 0 (and >= population when sized).
      - ``"under_provisioned"``— 0 < allocation < population (sufficiency mode).
      - ``"zero_with_payg"``   — allocation == 0 but PayG configured.
      - ``"zero_payg_unknown"``— allocation == 0 and PayG undetermined.
      - ``"zero_no_payg"``     — allocation == 0 and provably no PayG.
    """
    if allocated is None:
        return (None, "unreadable")
    if allocated > 0:
        if population is not None and allocated < population:
            return (Status.WARNING.value, "under_provisioned")
        return (Status.PASSED.value, "covered")
    # allocated == 0
    if payg_flag is True:
        return (Status.WARNING.value, "zero_with_payg")
    if payg_flag is None:
        return (Status.WARNING.value, "zero_payg_unknown")
    return (Status.FAILED.value, "zero_no_payg")
