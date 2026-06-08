# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Workday Deep Validation (WD-ENV-xxx, WD-CONN-xxx, WD-FLOW-xxx, WD-WF-xxx, WD-WF-CAT-xxx)

Validates Workday environment variables, connection references, flow status,
tests all 17 ESS SOAP workflows against the actual Workday API, and surfaces
a manual checklist for any Workday scenario referenced in customer topics
that is outside the OOTB scenario catalog (WD-WF-CAT-001).

The SOAP tests reuse the Kit's Workday MCP client (src/mcp/workday/client.py)
or, when running standalone, build SOAP envelopes directly with httpx.
"""

import getpass
import json
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# Use defusedxml everywhere we parse SOAP responses. Workday talks to us over
# the public internet via WS-Security; treat every response as untrusted, even
# the success path. defusedxml.ElementTree.ParseError is a subclass of stdlib
# ET.ParseError, so existing except-handlers still catch malformed XML, but
# attack-path constructs (entity expansion, external references, DTDs) raise
# DefusedXmlException subclasses instead - those need to be caught too or a
# hostile Workday payload would propagate as an unhandled exception out of
# FlightCheck instead of falling through to the structured "unparseable XML"
# result path.
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..runner import CheckResult, Status, Priority
from ._saml_utils import (
    WORKDAY_SAML_SP_FILTER,
    WORKDAY_SSO_TUTORIAL_DOC,
    saml_entity_ids,
)
from .connections import check_connector_connections, filter_connections_by_connector, get_connection_status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# The 3 critical Dataverse environment variables for Workday
ENV_VARS = {
    "EmployeeContextRequestAccountName": {
        "id": "WD-ENV-001",
        "critical": True,
        "default": None,  # Must be manually set
        "description": "ISU account name for RaaS",
    },
    "EmployeeContextRequestReportName": {
        "id": "WD-ENV-002",
        "critical": False,
        "default": "WD User Context",
        "description": "RaaS report name",
    },
    "EmployeeContextRequestReportInstanceName": {
        "id": "WD-ENV-003",
        "critical": False,
        "default": "Report2",
        "description": "Report instance name",
    },
}

# ─────────────────────────────────────────────────────────────────────────
# Workday install-flavor fingerprint (WD-PKG-001 / WD-CONN-012)
# ─────────────────────────────────────────────────────────────────────────
#
# Microsoft ships two different Workday installs:
#
#   * Simplified ("OOTB", workday-simplified-setup docs): one Workday
#     connection reference, used in OBO/invoker mode for the
#     signed-in user.
#   * Full / legacy SOAP+custom (workday docs): three Workday connection
#     references — OBO/OAuthUser + two ISU service-account refs that
#     drive the SOAP RaaS report lookups.
#
# Both install flavors use the SAME connector
# (`shared_workdaysoap`), so connector identity alone cannot
# distinguish them. The deterministic signal is the SET of
# `connectionreferencelogicalname` suffixes shipped inside the install
# solution — those suffixes are stamped at solution-build time by
# Microsoft and don't change across customers. Matching on the
# trailing 5-hex suffix (not the full logical name) keeps the check
# resilient to publisher-prefix changes (e.g. a customer who clones
# the solution under their own publisher would have a different
# prefix but the same suffix).
#
# Evidence cassettes (fingerprint values; the API contract itself is
# `documented`-tier per MS Learn):
#   tests/fixtures/cassettes/dataverse_workday_connection_refs_simplified.yaml
#   tests/fixtures/cassettes/dataverse_workday_connection_refs_full.yaml

# The final URL segment we look for on a connectionreference's
# `connectorid` to identify Workday-related refs. We match by
# normalized endswith() rather than equality so case variants or
# trailing-slash quirks don't drop legitimate matches.
WORKDAY_SOAP_CONNECTOR_SUFFIX = "/apis/shared_workdaysoap"

# Trailing `_<5-hex>` suffix on `connectionreferencelogicalname`
# (e.g. `new_sharedworkdaysoap_ff0df` -> "ff0df").
_REF_SUFFIX_RE = re.compile(r"_([0-9a-f]{5})$")

# Per-flavor fingerprint suffixes. A row in either set carries the
# stable Microsoft-shipped role identifier:
#   ff0df: OAuthUser (per-user OBO/invoker)
#   0786a: Generic User (ISU - read role)        [full / legacy only]
#   d6081: Context Generic User (ISU - context)  [full / legacy only]
SIMPLIFIED_REF_SUFFIXES = frozenset({"ff0df"})
LEGACY_REF_SUFFIXES = frozenset({"ff0df", "0786a", "d6081"})

# Human-readable role labels for diagnostics.
_REF_SUFFIX_ROLES = {
    "ff0df": "OAuthUser (OBO)",
    "0786a": "Generic User (ISU)",
    "d6081": "Context Generic User (ISU)",
}

# The 17 ESS Workday workflow definitions (ported from Test-WorkdayWorkflows.ps1)
WORKFLOWS = [
    # 15 Read workflows
    {
        "name": "Employee ID", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Reference>true</bsvc:Include_Reference>",
        "xpath": ".//*[@*='Employee_ID']",
    },
    {
        "name": "Company Code", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Organizations>true</bsvc:Include_Organizations>",
        "xpath": ".//{urn:com.workday/bsvc}Organization_Data",
    },
    {
        "name": "Cost Center", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Organizations>true</bsvc:Include_Organizations>",
        "xpath": ".//{urn:com.workday/bsvc}Organization_Type_Reference",
    },
    {
        "name": "Hire Date", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Hire_Date",
    },
    {
        "name": "Employment Info", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Employment_Data",
    },
    {
        "name": "Position Number", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Position_ID",
    },
    {
        "name": "Service Anniversary", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Employment_Information>true</bsvc:Include_Employment_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Continuous_Service_Date",
    },
    {
        "name": "National IDs", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}National_ID",
    },
    {
        "name": "Passports", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Passport_ID",
    },
    {
        "name": "Visas", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Visa_ID",
    },
    {
        "name": "Language Info", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Qualifications>true</bsvc:Include_Qualifications>",
        "xpath": ".//{urn:com.workday/bsvc}Language",
    },
    {
        "name": "Certifications", "service": "Human_Resources", "type": "Read",
        "response_group": "<bsvc:Include_Qualifications>true</bsvc:Include_Qualifications>",
        "xpath": ".//{urn:com.workday/bsvc}Certification",
    },
    {
        "name": "Base Compensation", "service": "Compensation", "type": "Read",
        "custom_operation": True,
        "xpath": ".//{urn:com.workday/bsvc}Compensation",
    },
    {
        "name": "Compensation Ratio", "service": "Compensation", "type": "Read",
        "custom_operation": True,
        "xpath": ".//{urn:com.workday/bsvc}Compa_Ratio",
    },
    {
        "name": "Emergency Contact", "service": "Human_Resources", "type": "Read", "pii": True,
        "response_group": "<bsvc:Include_Personal_Information>true</bsvc:Include_Personal_Information>",
        "xpath": ".//{urn:com.workday/bsvc}Emergency_Contact",
    },
    # 2 Write workflows (test capability only, no actual changes)
    {
        "name": "Update Email", "service": "Human_Resources", "type": "Write",
    },
    {
        "name": "Update Phone", "service": "Human_Resources", "type": "Write",
    },
]


def run_workday_checks(runner) -> list[CheckResult]:
    """Execute Workday-specific deep validation.

    WD-PKG-001 (package-flavor detection) is the new top-of-pipeline
    check: it runs whenever Dataverse credentials are available,
    independent of flow detection, because the connection references
    themselves are the install signal (refs may be installed before
    flows are deployed). The remaining workday checks are still gated
    on `_workday_flows` because they validate flow-deployed Workday
    configuration; if the customer has refs but no deployed flows, the
    package-detection result text flags that contradiction for the
    operator.

    WD-CONN-012 (package connection-reference binding completeness)
    runs at the end of the workday block when WD-PKG-001 detected a
    known flavor, so its diagnostic can list which Microsoft-shipped
    refs are bound vs. unbound for the detected flavor.

    WD-WF-CAT-001 (custom-workflow inventory checklist) runs after the
    SOAP tests. It walks `workspace/agents/*/topics/*.mcs.yml` for
    Workday scenario references that are NOT in the OOTB catalog
    (`scripts/flightcheck/data/workday_scenario_catalog.json`) and
    surfaces them as a MANUAL row with a 4-item operator checklist.
    WD-WF-CAT-LINK is the corresponding cross-link trailer emitted
    from inside `_check_workflows` so admins reading a green 17-row
    SOAP report don't miss the manual row.
    """
    results: list[CheckResult] = []

    wd_flows = getattr(runner, "_workday_flows", [])

    # WD-PKG-001 — runs whenever Dataverse is available, independent
    # of flow detection. Sets runner._workday_package_flavor and
    # runner._workday_connection_refs (cached for WD-CONN-012).
    pkg_results = _check_package_flavor(runner, wd_flows=wd_flows)
    results.extend(pkg_results)

    flavor = getattr(runner, "_workday_package_flavor", None)

    # WD-CONN-010 — Workday single-Entra-tenant federation alignment.
    # Runs BEFORE the no-Workday early-return gate below because the
    # conflict scenario (a second Entra tenant wired up against a
    # Workday tenant already federated to a different Entra tenant
    # silently breaks the existing federation) can apply pre-install
    # too — if there are Workday SAML enterprise apps in this Entra
    # tenant we want to surface the manual verification step even
    # when the kit-side Workday install isn't deployed yet.
    results.extend(_check_entra_workday_federation_alignment(runner))

    # If neither flows nor any Workday connection references are
    # present, this tenant has no Workday integration. Skip the
    # downstream Workday-specific checks (preserves the pre-existing
    # behavior of returning early when there's no Workday signal).
    if not wd_flows and flavor in (None, "none"):
        return results

    print("\n  Running Workday deep validation...")

    # --- Environment Variables ---
    results.extend(_check_env_vars(runner))

    # --- ISU username vs Entra UPN format alignment ---
    results.extend(_check_isu_username_format(runner))

    # --- Connection References ---
    results.extend(_check_connections(runner))
    results.extend(_check_connection_token_health(runner))

    # --- Flow Status ---
    results.extend(_check_flow_status(runner, wd_flows))

    # --- SOAP Workflow Tests (only if Workday MCP creds available) ---
    results.extend(_check_workflows(runner))

    # WD-CONN-012 — package-aware binding completeness; runs last so
    # the operator sees binding diagnostics in context with the other
    # connection checks above.
    results.extend(_check_package_connection_completeness(runner))

    # WD-WF-CAT-001 — Workday custom-workflow inventory checklist.
    # Runs after the SOAP tests so the WD-WF-CAT-LINK trailer that
    # `_check_workflows` emits inside its own returns has already
    # populated `runner._workday_unknown_scenarios` (the trailer
    # triggers the lazy discovery walk via _get_unknown_workday_scenarios).
    # Emitting WD-WF-CAT-001 here ensures the full manual checklist
    # appears in the per-Workday-block output even if there were no
    # SOAP tests run (e.g. credentials unavailable).
    results.extend(_check_custom_workflow_inventory(runner))

    return results


# ─────────────────────────────────────────────────────────────────────────
# WD-CONN-010 — Workday single-Entra-tenant federation alignment (MANUAL)
# ─────────────────────────────────────────────────────────────────────────
#
# Workday supports exactly ONE Entra-tenant SAML federation per Workday
# tenant. When a second Entra tenant is wired up against the same
# Workday tenant (e.g. an admin / test environment added on top of an
# existing production EmployeeHub tenant), the previously configured
# tenant's federation silently breaks — Workday switches its enabled
# IdP row to the new one and the old tenant's SAML SSO into Workday
# stops working without an explicit error.
#
# There is no Workday API surface that returns the configured SAML
# Identity Provider list — the 2026-05 capture attempts against the
# SOAP Identity_Management and REST authentication-policies endpoints
# all failed (see workday_config.yaml lines 200-336 + workday_rest_admin.yaml
# line 296-299). Per the FlightCheck cardinal rules
# (`solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md` design
# principle #2 — MANUAL status), this is exactly the case the MANUAL
# pattern was added for: gather everything programmatically observable
# on the Entra side and delegate the Workday-side comparison to the
# operator, using the same shape AUTH-006 established for SAML NameID
# alignment.
#
# What we observe (Entra side, via Graph v1.0 — validatable tier per
# `tests/fixtures/cassettes/INDEX.md` API tier registry):
#   * The current Entra tenant ID (runner.graph.tenant_id).
#   * Every federated Workday enterprise app in this Entra tenant
#     (servicePrincipals filtered on the same predicate AUTH-006 uses).
#   * Each app's SAML entity IDs from servicePrincipalNames — the
#     "Service Provider ID" join key Workday's SAML Identity Providers
#     screen exposes, so the operator can identify which Entra app the
#     Workday tenant is actually using.
#
# What we delegate (Workday side, MANUAL): the operator opens
# Workday's Edit Tenant Setup - Security, reads the enabled SAML
# Identity Provider row's issuer / federation metadata, and verifies
# the embedded Entra tenant ID matches the current tenant. If it
# references a different tenant, configuring an Entra Integrated
# Workday connection from this tenant would silently break the
# foreign tenant's federation.
#
# The SAML SP filter, the helper for extracting SAML entity IDs from
# servicePrincipalNames, and the MS Learn Workday SSO tutorial URL
# all live in ``checks/_saml_utils`` so AUTH-006 and WD-CONN-010
# share one source of truth.


def _check_entra_workday_federation_alignment(runner) -> list[CheckResult]:
    """WD-CONN-010 — Manual verification of Workday's single-Entra-tenant
    federation constraint.

    Enumerates federated Workday enterprise apps in the current Entra
    tenant, surfaces their SAML entity IDs and the current Entra tenant
    ID, and emits ONE coalesced MANUAL result instructing the operator
    to verify in Workday "Edit Tenant Setup - Security" that the
    enabled IdP issuer references the current Entra tenant — NOT a
    different one (which would mean a foreign Entra tenant owns the
    Workday federation today, and configuring an Entra Integrated
    Workday connection from this tenant would silently break it).
    """
    cp_id = "WD-CONN-010"
    category = "Workday"
    description = "Workday single-Entra-tenant federation alignment"
    doc_link = WORKDAY_SSO_TUTORIAL_DOC

    graph = getattr(runner, "graph", None)
    if graph is None:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=description,
            result="Microsoft Graph client unavailable — skipping.",
            remediation=(
                "Re-run FlightCheck after Graph authentication succeeds."
            ),
            doc_link=doc_link,
        )]

    # Filtered /servicePrincipals call with raise_on_permission_error=True
    # so a missing Application.Read.All consent surfaces as
    # PermissionError → WARNING. Without this kwarg, get_all() (which
    # get_service_principals wraps) silently swallows 401/403 into an
    # empty list — which would masquerade as "no Workday SAML app
    # exists" and emit a falsely reassuring NOT_CONFIGURED. Same
    # plumbing AUTH-006 uses.
    try:
        workday_sps = graph.get_service_principals(
            filter_expr=WORKDAY_SAML_SP_FILTER,
            raise_on_permission_error=True,
        )
    except PermissionError as e:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=(
                f"Cannot read Entra service principals: {e} "
                "(HTTP 403 typically means Application.Read.All "
                "is not consented)."
            ),
            remediation=(
                "Grant Application.Read.All (or Directory.Read.All) "
                "consent on the Graph app registration the kit uses, "
                "then re-run FlightCheck. Without this consent the "
                "check cannot enumerate Workday SAML enterprise apps "
                "to surface for the operator's manual Workday-side "
                "verification."
            ),
            doc_link=doc_link,
        )]
    except Exception as e:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=f"Unable to query Entra service principals: {e}",
            remediation=(
                "Requires Application.Read.All (or Directory.Read.All) "
                "consented on the Graph app registration."
            ),
            doc_link=doc_link,
        )]

    # The current Entra tenant ID is the ANCHOR for the manual check —
    # the operator compares the Workday-side IdP issuer against this
    # value. GraphClient stores tenant_id at construction time
    # (graph_client.py line 79); fall back gracefully if it's absent
    # so the rest of the result still ships.
    current_tenant_id = getattr(graph, "tenant_id", None) or "(unknown)"

    if not workday_sps:
        # IMPORTANT: do NOT say "the conflict scenario doesn't apply
        # here." We only know there's no LOCAL Workday SAML app — a
        # foreign Entra tenant could already own the Workday-side
        # federation, in which case wiring up Entra Integrated SSO
        # from this tenant would silently break that foreign tenant's
        # federation. Keep the manual verification advice on the
        # remediation path for the pre-install/foreign-tenant scenario.
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=description,
            result=(
                "No federated Workday SAML enterprise app was found in "
                f"this Entra tenant ({current_tenant_id}) using the "
                f"filter \"{WORKDAY_SAML_SP_FILTER}\". The kit cannot "
                "identify a local Workday SAML app to surface for "
                "manual Workday-side verification."
            ),
            remediation=(
                "If you are NOT planning to configure Entra Integrated "
                "Workday SSO from this tenant, this check is not "
                "applicable. If you ARE preparing to configure it "
                "(typical when standing up a new environment against "
                "an existing Workday tenant), manually inspect Workday "
                "before proceeding — see steps below.\n"
                "\n"
                "  a. Sign in to the Workday tenant ESS will connect to.\n"
                "  b. In the global search box, type 'Edit Tenant Setup "
                "- Security' and open the task.\n"
                "  c. Scroll to the 'SAML Identity Providers' section. "
                "Find any row whose 'Disabled' checkbox is unchecked "
                "and whose 'Used for Environments' covers the Workday "
                "environment ESS will connect to.\n"
                "  d. Open the active IdP row and read its 'Issuer' / "
                "federation metadata URL. The Entra-issued value is of "
                "the form 'https://sts.windows.net/{tenantId}/'.\n"
                "  e. If the embedded {tenantId} matches the current "
                f"Entra tenant ({current_tenant_id}), Entra Integrated "
                "SSO from this tenant is safe to configure. If it "
                "embeds a DIFFERENT tenant ID, configuring an Entra "
                "Integrated Workday connection from THIS tenant will "
                "silently break the existing federation — revert in "
                "the foreign tenant or coordinate with its admin "
                "before proceeding."
            ),
            doc_link=doc_link,
        )]

    # Build the per-app evidence list. Each entry surfaces the data the
    # operator needs to identify which Entra app the Workday tenant
    # has selected as its active IdP (entity IDs are the join key).
    app_entries: list[str] = []
    for sp in workday_sps:
        sp_name = sp.get("displayName", "(unknown)")
        app_id = sp.get("appId", "?")
        entity_ids = saml_entity_ids(sp.get("servicePrincipalNames") or [])
        entity_ids_str = ", ".join(entity_ids) if entity_ids else "(none surfaced)"
        app_entries.append(
            f"  - {sp_name} (appId={app_id}) — entity IDs: {entity_ids_str}"
        )

    intro_count = (
        "1 federated Workday SAML app"
        if len(workday_sps) == 1
        else f"{len(workday_sps)} federated Workday SAML apps"
    )

    result_text = (
        f"Current Entra tenant: {current_tenant_id}\n"
        f"\n"
        f"Found {intro_count} in this Entra tenant (filter: "
        f"\"{WORKDAY_SAML_SP_FILTER}\"). The kit cannot read "
        "Workday's tenant security configuration to determine which "
        "of these is the active IdP on the Workday side, or whether "
        "the enabled Workday IdP belongs to a different Entra tenant.\n"
        f"\n"
        f"Detected apps (display name → entity IDs are the Workday "
        f"'Service Provider ID' join key):\n"
        + "\n".join(app_entries)
    )

    return [CheckResult(
        checkpoint_id=cp_id, category=category,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=description,
        result=result_text,
        remediation=(
            "Manual verification required — Workday supports exactly "
            "one Entra-tenant SAML federation per Workday tenant. "
            "Confirm the Workday-side enabled IdP issuer references "
            "the current Entra tenant; if it references a different "
            "one, configuring (or recommending) an Entra Integrated "
            "Workday connection from this tenant will silently break "
            "the foreign tenant's federation.\n"
            "\n"
            "Step 1 — Identify the active Entra app from inside Workday:\n"
            "  a. Sign in to the Workday tenant ESS connects to.\n"
            "  b. In the global search box, type 'Edit Tenant Setup "
            "- Security' and open the task.\n"
            "  c. Scroll to the 'SAML Identity Providers' section. "
            "Find the row that is enabled (the 'Disabled' checkbox is "
            "unchecked) and whose 'Used for Environments' covers the "
            "environment ESS connects to.\n"
            "  d. Note that row's 'Service Provider ID' value (e.g. "
            "http://www.workday.com/contoso_prod).\n"
            "  e. Match that value against the 'entity IDs' in the "
            "result above. A match means the active IdP is one of "
            "this tenant's Entra apps; no match means a DIFFERENT "
            "Entra tenant currently owns the federation.\n"
            "\n"
            "Step 2 — Verify the IdP issuer's tenant ID:\n"
            "  a. On the same Workday IdP row, open the configuration "
            "and read the 'Issuer' / federation metadata URL. The "
            "Entra-issued value has the form "
            "'https://sts.windows.net/{tenantId}/'.\n"
            f"  b. Compare the embedded {{tenantId}} against the "
            f"current Entra tenant ({current_tenant_id}, listed in "
            "the result above).\n"
            "  c. If they match: Entra Integrated Workday SSO from "
            "this tenant is safely configured.\n"
            "  d. If they DIFFER: a foreign Entra tenant owns the "
            "Workday federation. Configuring or 'fixing' an Entra "
            "Integrated Workday connection from THIS tenant will "
            "silently break SSO for users in the foreign tenant. "
            "Either revert the conflicting integration in Workday "
            "via 'Edit Tenant Setup - Security' first, or coordinate "
            "with the foreign tenant's admin before proceeding.\n"
            "\n"
            "Note: this manual step exists because Workday does not "
            "expose tenant SAML Identity Provider configuration via "
            "any of its current public admin APIs (SOAP "
            "Identity_Management, REST authentication-policies, and "
            "WQL admin surfaces have all been verified empty for "
            "this data). MANUAL items do not fail readiness."
        ),
        doc_link=doc_link,
    )]


# ─────────────────────────────────────────────────────────────────────────
# WD-PKG-001 — Workday install-flavor detection
# ─────────────────────────────────────────────────────────────────────────

def _extract_ref_suffix(logical_name: str | None) -> str | None:
    """Return the trailing 5-hex suffix from a `connectionreferencelogicalname`,
    or None if the field is missing/empty/doesn't match the expected pattern."""
    if not logical_name:
        return None
    m = _REF_SUFFIX_RE.search(logical_name)
    return m.group(1) if m else None


def _is_workday_soap_connector(connectorid: str | None) -> bool:
    """Match a connectorid (from Dataverse connectionreferences) against the
    Workday SOAP connector path. Tolerates casing and trailing-slash quirks."""
    if not connectorid:
        return False
    normalized = connectorid.lower().rstrip("/")
    return normalized.endswith(WORKDAY_SOAP_CONNECTOR_SUFFIX)


def _check_package_flavor(runner, *, wd_flows: list) -> list[CheckResult]:
    """WD-PKG-001 — Detect Workday install flavor from connectionreferences.

    Queries Dataverse for all connectionreferences, filters to Workday SOAP
    rows, extracts the suffix set, and classifies against the known
    fingerprints. Sets `runner._workday_package_flavor` (string verdict) and
    `runner._workday_connection_refs` (list of dicts; the cached rows so
    WD-CONN-012 doesn't have to re-query).

    The verdict is one of:
      * ``simplified`` — exact match on {ff0df}
      * ``full``       — exact match on {ff0df, 0786a, d6081}
      * ``none``       — no Workday refs at all (no Workday integration)
      * ``partial``    — strict non-empty subset of LEGACY_REF_SUFFIXES that
                        doesn't equal either fingerprint (incomplete install)
      * ``unknown``    — Workday refs present but the suffix set includes
                        unrecognized values (customer-modified solution or a
                        Microsoft release we haven't taught the kit about yet)
      * ``skipped``    — no Dataverse credential available
    """
    results: list[CheckResult] = []
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)

    # Pre-populate the cache so downstream checks always have a defined value.
    runner._workday_connection_refs = []
    runner._workday_package_flavor = None

    doc_simplified = f"{DOC_BASE}/workday-simplified-setup"
    doc_legacy = f"{DOC_BASE}/workday"

    if not env_url or not dv_token:
        runner._workday_package_flavor = "skipped"
        results.append(CheckResult(
            checkpoint_id="WD-PKG-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday install flavor (simplified vs full / legacy)",
            result="Dataverse token not available — skipping package detection",
        ))
        return results

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        refs = query_all(
            env_url, dv_token,
            "connectionreferences",
            "connectionreferenceid,connectionreferencelogicalname,"
            "connectionreferencedisplayname,connectorid,connectionid,statuscode",
        )
    except Exception as e:
        runner._workday_package_flavor = "skipped"
        results.append(CheckResult(
            checkpoint_id="WD-PKG-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday install flavor (simplified vs full / legacy)",
            result=f"Unable to query connectionreferences: {e}",
            remediation="Confirm the FlightCheck identity has Dataverse read access on connectionreferences.",
        ))
        return results

    workday_refs = [r for r in refs if _is_workday_soap_connector(r.get("connectorid"))]
    runner._workday_connection_refs = workday_refs

    # Classify each Workday row's suffix (some may not match the
    # _<5hex> pattern — surface those rather than silently dropping them).
    known_suffixes: set[str] = set()
    unknown_format_names: list[str] = []
    unknown_suffixes: set[str] = set()
    for r in workday_refs:
        logical = r.get("connectionreferencelogicalname")
        suffix = _extract_ref_suffix(logical)
        if suffix is None:
            unknown_format_names.append(logical or "<missing>")
        elif suffix in LEGACY_REF_SUFFIXES:
            known_suffixes.add(suffix)
        else:
            unknown_suffixes.add(suffix)

    # 1. No Workday integration at all.
    if not workday_refs:
        runner._workday_package_flavor = "none"
        results.append(CheckResult(
            checkpoint_id="WD-PKG-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="Workday install flavor (simplified vs full / legacy)",
            result="No Workday connection references found in Dataverse",
            remediation=(
                "If this tenant is meant to use Workday, install one of the "
                "Microsoft-published Workday integration packages. See the "
                "documentation links for simplified vs full install."
            ),
            doc_link=doc_simplified,
        ))
        return results

    # 2. Exact simplified match.
    if known_suffixes == SIMPLIFIED_REF_SUFFIXES and not unknown_suffixes and not unknown_format_names:
        runner._workday_package_flavor = "simplified"
        # The `{ff0df}` suffix is shared between simplified and full
        # installs, so a 1-ref shape COULD also be a failed full
        # install whose ISU refs never deployed. Surface that
        # ambiguity in the result text rather than overclaiming.
        flow_note = ""
        if not wd_flows:
            flow_note = (
                " No Workday flows are deployed yet in this environment "
                "— the package is present but downstream flows have not run."
            )
        results.append(CheckResult(
            checkpoint_id="WD-PKG-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday install flavor (simplified vs full / legacy)",
            result=(
                "Detected simplified-install shape (1 Workday connection "
                "reference: OAuthUser/OBO). If this tenant was intended to "
                "use the full / legacy SOAP+custom integration, the two "
                "ISU connection references (Generic User, Context Generic "
                "User) are missing." + flow_note
            ),
            doc_link=doc_simplified,
        ))
        return results

    # 3. Exact full / legacy match.
    if known_suffixes == LEGACY_REF_SUFFIXES and not unknown_suffixes and not unknown_format_names:
        runner._workday_package_flavor = "full"
        flow_note = ""
        if not wd_flows:
            flow_note = (
                " No Workday flows are deployed yet in this environment "
                "— the package is present but downstream flows have not run."
            )
        results.append(CheckResult(
            checkpoint_id="WD-PKG-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday install flavor (simplified vs full / legacy)",
            result=(
                "Detected full / legacy SOAP+custom install shape "
                "(3 Workday connection references: OAuthUser/OBO + 2 ISU)." + flow_note
            ),
            doc_link=doc_legacy,
        ))
        return results

    # 4. Strict non-empty subset of legacy suffixes -> partial install.
    if known_suffixes and not unknown_suffixes and not unknown_format_names \
            and known_suffixes < LEGACY_REF_SUFFIXES:
        runner._workday_package_flavor = "partial"
        missing = LEGACY_REF_SUFFIXES - known_suffixes
        observed_roles = ", ".join(sorted(_REF_SUFFIX_ROLES[s] for s in known_suffixes))
        missing_roles = ", ".join(sorted(_REF_SUFFIX_ROLES[s] for s in missing))
        results.append(CheckResult(
            checkpoint_id="WD-PKG-001", category="Workday",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description="Workday install flavor (simplified vs full / legacy)",
            result=(
                f"Partial install detected — observed Workday roles: "
                f"{observed_roles}; missing roles relative to the full / "
                f"legacy install: {missing_roles}. Does not match either "
                "the simplified (1-ref) or full (3-ref) fingerprint."
            ),
            remediation=(
                "Re-import the chosen Microsoft Workday integration package; "
                "the install appears to have created some but not all of the "
                "expected connection references."
            ),
            doc_link=doc_legacy,
        ))
        return results

    # 5. Anything else: unrecognized suffix(es) and/or malformed
    #    logicalname(s) on Workday-connector rows.
    runner._workday_package_flavor = "unknown"
    diagnostics: list[str] = []
    if known_suffixes:
        diagnostics.append(
            "recognized: " + ", ".join(sorted(_REF_SUFFIX_ROLES[s] for s in known_suffixes))
        )
    if unknown_suffixes:
        diagnostics.append("unrecognized suffixes: " + ", ".join(sorted(unknown_suffixes)))
    if unknown_format_names:
        diagnostics.append(
            "rows with unexpected logical-name format: "
            + ", ".join(sorted(unknown_format_names))
        )
    results.append(CheckResult(
        checkpoint_id="WD-PKG-001", category="Workday",
        priority=Priority.HIGH.value, status=Status.WARNING.value,
        description="Workday install flavor (simplified vs full / legacy)",
        result=(
            "Workday connection references present but the shape does not "
            "match either the simplified (1-ref) or full / legacy (3-ref) "
            "fingerprint (" + "; ".join(diagnostics) + "). "
            "Downstream Workday-specific checks may produce unexpected results."
        ),
        remediation=(
            "If this tenant runs a customized Workday solution, this is "
            "informational. Otherwise re-import the Microsoft-published "
            "Workday integration package."
        ),
        doc_link=doc_legacy,
    ))
    return results


# ─────────────────────────────────────────────────────────────────────────
# WD-CONN-012 — Package-aware connection-reference binding completeness
# ─────────────────────────────────────────────────────────────────────────
#
# This is intentionally a Dataverse-side binding check (`connectionid`
# present and `statuscode` active), NOT a Power-Platform-side
# connection health check. The existing WD-CONN-001..NNN and WD-CONN-101
# checks already cover BAP-side connection status and OAuth token
# health. WD-CONN-012's value-add is to verify that for the detected
# install flavor, EVERY connection reference Microsoft shipped is
# bound to some connection — a deterministic completeness signal that
# the per-connection health checks can't give on their own.

def _check_package_connection_completeness(runner) -> list[CheckResult]:
    """WD-CONN-012 — Verify every Workday connection reference expected for
    the detected install flavor is bound to a connection.

    Uses the cached refs from `runner._workday_connection_refs` populated
    by WD-PKG-001, so we don't re-query Dataverse here.
    """
    flavor = getattr(runner, "_workday_package_flavor", None)
    refs = getattr(runner, "_workday_connection_refs", []) or []

    if flavor not in ("simplified", "full"):
        # WD-PKG-001 either didn't run (no Dataverse), found no
        # Workday refs (NOT_CONFIGURED), or found an unrecognized
        # shape (WARNING). In any of those cases this check can't add
        # signal beyond what WD-PKG-001 already reported.
        return [CheckResult(
            checkpoint_id="WD-CONN-012", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday package connection-reference binding completeness",
            result=(
                "Skipped — WD-PKG-001 did not detect a known Workday install "
                "flavor (current verdict: "
                f"{flavor if flavor else 'unavailable'})."
            ),
        )]

    expected = SIMPLIFIED_REF_SUFFIXES if flavor == "simplified" else LEGACY_REF_SUFFIXES

    # Map suffix -> ref dict so we can check each expected role.
    by_suffix: dict[str, dict] = {}
    for r in refs:
        suffix = _extract_ref_suffix(r.get("connectionreferencelogicalname"))
        if suffix in expected:
            by_suffix[suffix] = r

    unbound: list[str] = []
    inactive: list[str] = []
    missing: list[str] = []
    bound_roles: list[str] = []

    for suffix in expected:
        role = _REF_SUFFIX_ROLES.get(suffix, suffix)
        row = by_suffix.get(suffix)
        if row is None:
            # Shouldn't normally happen — WD-PKG-001 already classified
            # the install as matching `expected`. Guard anyway.
            missing.append(role)
            continue
        cid = row.get("connectionid")
        statuscode = row.get("statuscode")
        if not cid:
            unbound.append(role)
        elif statuscode != 1:
            inactive.append(f"{role} (statuscode={statuscode})")
        else:
            bound_roles.append(role)

    problems: list[str] = []
    if missing:
        problems.append("missing rows: " + ", ".join(sorted(missing)))
    if unbound:
        problems.append("unbound (connectionid=null): " + ", ".join(sorted(unbound)))
    if inactive:
        problems.append("inactive: " + ", ".join(sorted(inactive)))

    doc_link = (
        f"{DOC_BASE}/workday-simplified-setup" if flavor == "simplified"
        else f"{DOC_BASE}/workday"
    )

    if not problems:
        return [CheckResult(
            checkpoint_id="WD-CONN-012", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday package connection-reference binding completeness",
            result=(
                f"All {len(expected)} Workday connection reference(s) expected "
                f"for the {flavor} install are bound to active connections "
                f"({', '.join(sorted(bound_roles))})."
            ),
            doc_link=doc_link,
        )]

    return [CheckResult(
        checkpoint_id="WD-CONN-012", category="Workday",
        priority=Priority.HIGH.value, status=Status.FAILED.value,
        description="Workday package connection-reference binding completeness",
        result=(
            f"One or more Workday connection references expected for the "
            f"{flavor} install are not properly bound — "
            + "; ".join(problems) + "."
        ),
        remediation=(
            "In Power Platform admin center, open each affected connection "
            "reference and bind it to a connection of the same connector. "
            "If the connection itself was deleted, re-create it and re-bind."
        ),
        doc_link=doc_link,
    )]


# ─────────────────────────────────────────────────────────────────────────
# Install-flavor gating helper (see AGENTS.md design principle #11)
# ─────────────────────────────────────────────────────────────────────────
#
# Several Workday checks below are only meaningful on the full / legacy
# install (the one with the 2 ISU service-account refs + RaaS report
# env vars). On the simplified install, OBO uses the signed-in user's
# identity — no ISU, no RaaS — so these checks would false-FAIL with
# remediations pointing operators at the wrong setup path.
#
# We gate them on the WD-PKG-001 verdict cached on
# `runner._workday_package_flavor`. To avoid suppressing real bugs:
#
#   * We skip ONLY on a positive `"simplified"` verdict. Any other
#     verdict (None, "full", "partial", "unknown", "none", "skipped")
#     runs the existing logic — operators debugging a broken install
#     need maximum signal, not silence.
#   * Tests that build minimal runners without setting the attribute
#     get the default-None branch and observe the pre-gating behavior
#     (backwards-compatible).
#   * The SKIP remediation must acknowledge the `{ff0df}`-only
#     ambiguity: the same 1-ref shape WD-PKG-001 classifies as
#     "simplified" ALSO matches a broken full install where the 2 ISU
#     refs failed to deploy. An operator who intended the full install
#     needs to see this from the SKIP, not just from WD-PKG-001's
#     standalone diagnostic.

def _simplified_install_skip(
    *, checkpoint_id: str, description: str,
    priority: str = Priority.HIGH.value,
    category: str = "Workday",
) -> CheckResult:
    """Build a SKIPPED CheckResult for an ISU/RaaS check gated on
    `runner._workday_package_flavor == "simplified"`.

    `category` defaults to "Workday" but can be overridden for the
    workflow-test check, which uses the distinct "Workday Workflows"
    category in the report so SKIP / pass rows stay grouped with
    other WD-WF-* output.

    The message split follows the AGENTS.md `result` / `remediation`
    contract (principle #8): `result` reports the observation
    (WD-PKG-001's verdict); `remediation` carries the actionable
    contingency for an operator who intended the OTHER install flavor.
    """
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=category,
        priority=priority,
        status=Status.SKIPPED.value,
        description=description,
        result=(
            "WD-PKG-001 detected the simplified Workday install shape "
            "(1 connection reference, OBO/OAuthUser). This check is "
            "ISU/RaaS-specific and does not apply on the simplified "
            "install — OBO uses the signed-in user's identity."
        ),
        remediation=(
            "If you intended to install the full / legacy SOAP+custom "
            "integration, the same 1-ref shape also matches a broken "
            "full install where the 2 ISU connection references "
            "(Generic User, Context Generic User) failed to deploy. "
            "See WD-PKG-001's diagnostic to confirm your install "
            "intent before treating this SKIP as benign."
        ),
        doc_link=f"{DOC_BASE}/workday-simplified-setup",
    )


def _check_env_vars(runner) -> list[CheckResult]:
    """Validate Workday environment variables in Dataverse.

    Gated on `runner._workday_package_flavor`: skipped on
    `"simplified"` because the three env vars (ISU account name,
    RaaS report name, RaaS report instance) are only consumed by the
    full / legacy install's RaaS code path. See
    `_simplified_install_skip` for the SKIP message contract.
    """
    flavor = getattr(runner, "_workday_package_flavor", None)
    if flavor == "simplified":
        return [
            _simplified_install_skip(
                checkpoint_id=meta["id"],
                description=meta["description"],
                priority=(
                    Priority.CRITICAL.value if meta["critical"]
                    else Priority.HIGH.value
                ),
            )
            for meta in ENV_VARS.values()
        ]

    results = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-001", category="Workday",
            priority=Priority.CRITICAL.value, status=Status.SKIPPED.value,
            description="Workday environment variables",
            result="Dataverse token not available — skipping env var checks",
        ))
        return results

    try:
        # Import Dataverse query helper from auth.py
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        # Query environment variable definitions and values
        defs = query_all(
            env_url, dv_token,
            "environmentvariabledefinitions",
            "displayname,schemaname,environmentvariabledefinitionid",
            filter_expr="contains(schemaname,'EmployeeContext')",
        )
        vals = query_all(
            env_url, dv_token,
            "environmentvariablevalues",
            "value,schemaname,_environmentvariabledefinitionid_value",
        )

        # Build lookup of var name -> value
        def_map = {d["environmentvariabledefinitionid"]: d for d in defs}
        val_map = {}
        for v in vals:
            def_id = v.get("_environmentvariabledefinitionid_value")
            if def_id in def_map:
                schema = def_map[def_id].get("schemaname", "")
                val_map[schema] = v.get("value", "")

        for var_name, meta in ENV_VARS.items():
            actual_value = None
            # Find by partial match on schema name
            for k, v in val_map.items():
                if var_name.lower() in k.lower():
                    actual_value = v
                    break

            if actual_value:
                results.append(CheckResult(
                    checkpoint_id=meta["id"], category="Workday",
                    priority=Priority.CRITICAL.value if meta["critical"] else Priority.HIGH.value,
                    status=Status.PASSED.value,
                    description=meta["description"],
                    result=f"Set to: {actual_value}",
                    doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
                ))
            elif meta["critical"]:
                results.append(CheckResult(
                    checkpoint_id=meta["id"], category="Workday",
                    priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                    description=meta["description"],
                    result="Not configured — this must be set manually",
                    remediation=f"Set {var_name} in [Power Platform admin center](https://admin.powerplatform.microsoft.com) or run `/connect workday`.",
                    doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
                ))
            else:
                results.append(CheckResult(
                    checkpoint_id=meta["id"], category="Workday",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=meta["description"],
                    result=f"Using default: {meta['default']}",
                    doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
                ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-001", category="Workday",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Workday environment variables",
            result=f"Unable to check: {e}",
        ))

    return results


def _check_isu_username_format(runner) -> list[CheckResult]:
    """WD-ENV-101 — Workday ISU username alignment with Entra UPN format.

    Pulls the configured ISU username from
    `EmployeeContextRequestAccountName` (Dataverse env var) and compares
    its shape against the tenant's verified Entra domains. Federated
    tenants (Okta / Ping) frequently leave the ISU username in a legacy
    short-employee-id format that does not match the UPN claim ESS sends
    on each request, which prevents Workday from matching the request to
    a Worker.

    Heuristics:
      * No `@` in ISU → WARNING (legacy short-id format — the
        most-cited misconfiguration root cause). Reported even when
        Graph is unavailable, because this signal needs only the
        Dataverse env var.
      * `@` present but the domain part is not in the tenant's
        verified-domains list → WARNING (could be legitimate cross-tenant
        federation; surface for the operator to confirm).
      * `<localpart>@<verified-domain>` → PASSED.

    A scoped per-Worker comparison (Get_Workers User_ID == Entra UPN
    for a sample of expected ESS users) is intentionally out of scope
    for this check — it requires Workday SOAP credentials and a curated
    sample list, which `_check_workflows` already exercises against
    `WORKDAY_TEST_EMPLOYEE_ID`. Wire a future `WD-WF-NNN` against that
    surface when those inputs are formalised; this checkpoint covers
    the static format-alignment gap that can be detected without ISU
    credentials.

    Gated on `runner._workday_package_flavor`: skipped on
    `"simplified"` because the simplified install has no ISU service
    account (OBO uses the signed-in user's identity directly). See
    `_simplified_install_skip` for the SKIP message contract.
    """
    flavor = getattr(runner, "_workday_package_flavor", None)
    if flavor == "simplified":
        return [_simplified_install_skip(
            checkpoint_id="WD-ENV-101",
            description="ISU username vs Entra UPN format alignment",
        )]

    results: list[CheckResult] = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ISU username vs Entra UPN format alignment",
            result="Dataverse token not available — skipping ISU format check",
        ))
        return results

    # ── Step 1: read the ISU env var from Dataverse. We do this FIRST,
    # before consulting Graph, because the no-`@` legacy-format detection
    # (the most-cited misconfiguration root cause — legacy short-ID ISU
    # provisioning on federated tenants, common where the ISU was set
    # up before the tenant adopted UPN-shaped service-account naming)
    # can be reported off the Dataverse value alone.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        defs = query_all(
            env_url, dv_token,
            "environmentvariabledefinitions",
            "displayname,schemaname,environmentvariabledefinitionid",
            filter_expr="contains(schemaname,'EmployeeContext')",
        )
        vals = query_all(
            env_url, dv_token,
            "environmentvariablevalues",
            "value,schemaname,_environmentvariabledefinitionid_value",
        )

        def_map = {d["environmentvariabledefinitionid"]: d for d in defs}
        isu_value: str | None = None
        for v in vals:
            def_id = v.get("_environmentvariabledefinitionid_value")
            if def_id not in def_map:
                continue
            schema = def_map[def_id].get("schemaname", "")
            if "EmployeeContextRequestAccountName".lower() in schema.lower():
                isu_value = v.get("value", "") or None
                break
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=f"Unable to read ISU env var from Dataverse: {e}",
        ))
        return results

    if not isu_value:
        # WD-ENV-001 already covers the missing-value remediation; skip
        # here to avoid double-reporting the same root cause.
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ISU username vs Entra UPN format alignment",
            result="ISU env var not set — see WD-ENV-001 for the underlying gap",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    # ── Step 2: legacy short-id detection (no Graph required). This is
    # the most decisive failure mode and must be reported even when
    # Graph auth has failed.
    if "@" not in isu_value:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username '{isu_value}' does not contain '@' — does not match "
                f"the Entra UPN format ESS sends on each request"
            ),
            remediation=(
                "If the tenant federates identity (Okta, Ping, ADFS), set the "
                "Workday ISU username to the Entra UPN format (e.g. "
                "isu@<verified-tenant-domain>) so Workday can match incoming "
                "ESS requests to a Worker. Update "
                "`EmployeeContextRequestAccountName` in [Power Platform admin "
                "center](https://admin.powerplatform.microsoft.com)."
            ),
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    # ── Step 3: verified-domain comparison (requires Graph). If Graph
    # isn't available, we can't do this comparison — surface that as a
    # SKIP so the operator knows the deeper check wasn't performed.
    graph = getattr(runner, "graph", None)
    if not graph:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username '{isu_value}' is in UPN-style format but Microsoft "
                f"Graph client is unavailable — cannot verify the domain matches "
                f"a verified tenant domain"
            ),
            remediation="Re-run flightcheck and complete the Microsoft Graph sign-in prompt.",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    try:
        org = graph.get_organization()
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=f"Unable to fetch tenant verified domains from Graph: {e}",
            remediation="Ensure permissions to read Organization info via Graph (Organization.Read.All).",
        ))
        return results

    if not isinstance(org, dict) or not org:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                "Graph /organization returned no tenant record — likely "
                "insufficient permissions"
            ),
            remediation="Ensure permissions to read Organization info via Graph (Organization.Read.All).",
        ))
        return results

    verified = [
        (d.get("name") or "").lower()
        for d in org.get("verifiedDomains", [])
        if d.get("name")
    ]

    domain = isu_value.rsplit("@", 1)[1].lower()
    if not verified:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username '{isu_value}' contains '@{domain}' but Graph "
                f"returned no verified domains — cannot confirm alignment"
            ),
            remediation="Ensure permissions to read Organization info via Graph (Organization.Read.All).",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
        return results

    if domain in verified:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ISU username vs Entra UPN format alignment",
            result=f"ISU username '{isu_value}' matches verified tenant domain '{domain}'",
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))
    else:
        results.append(CheckResult(
            checkpoint_id="WD-ENV-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ISU username vs Entra UPN format alignment",
            result=(
                f"ISU username domain '{domain}' is not in the tenant's verified "
                f"domains ({', '.join(sorted(verified))}) — Workday may fail to "
                f"match ESS requests to a Worker if ESS sends UPN claims from a "
                f"verified domain"
            ),
            remediation=(
                "Confirm the ISU username matches the UPN claim ESS sends. If "
                "the tenant uses federated identity, update "
                "`EmployeeContextRequestAccountName` to use a verified-domain "
                "UPN, or document the cross-tenant scenario for the operator."
            ),
            doc_link=f"{DOC_BASE}/workday#step-4-environment-variables",
        ))

    return results


def _check_connections(runner) -> list[CheckResult]:
    """Validate Workday connection references in Power Platform."""
    # Legacy behavior: silently skip when env_id is unavailable
    if not runner.env_id:
        return []
    return check_connector_connections(
        runner,
        connector_keyword="workday",
        checkpoint_prefix="WD-CONN",
        category="Workday",
        not_found_remediation="Configure Workday SOAP connections in the environment.",
        doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
    )


# OAuth grant-expiry / token-health error codes the Power Platform
# connection layer surfaces when the connection creator's Entra OAuth
# grant has lapsed. There are two places to find them:
#
#   1. ``statuses[0].error.message`` — contains the actual Entra
#      ``AADSTSnnnnn`` token-failure code embedded in a longer prose
#      message, e.g. "Failed to refresh access token... AADSTS50173:
#      The provided grant has expired due to it being revoked..."
#      This is where the actionable code actually lives in production
#      (verified against ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``
#      lines 2661-2680).
#   2. ``statuses[0].error.code`` — a coarser Power-Platform-side
#      classification: typically ``Unauthorized`` (for token-refresh
#      failures including AADSTSnnnnn) or ``Unauthenticated`` (for a
#      connection that was never authenticated). These show up
#      regardless of whether an AADSTS code is present.
#
# WD-CONN-101 inspects (1) first via a regex on the message text, and
# falls back to (2) only if the message has no recognizable AADSTS
# code. That order matters: the message-level AADSTS code tells the
# operator *which* Entra failure mode they hit (grant expired vs MFA
# required vs refresh-token-too-old) and therefore *what specific
# action* to take; the code-level "Unauthorized" only tells them
# something is wrong with the token, generically.
#
# Codes sourced from MS Learn:
# https://learn.microsoft.com/entra/identity-platform/reference-error-codes
TOKEN_HEALTH_ERROR_CODES = {
    "AADSTS50173": "Auth grant expired (token revoked or password changed). Re-authenticate the connection in Power Platform.",
    "AADSTS70008": "Refresh token expired due to inactivity. Re-authenticate the connection in Power Platform.",
    "AADSTS50058": "Silent sign-in failed (no active Entra session). Have the connection owner re-authenticate.",
    "AADSTS700082": "Refresh token has expired due to inactivity. Re-authenticate the connection.",
    "AADSTS700084": "Refresh token used after revocation. Re-authenticate the connection.",
    "AADSTS50076": "MFA challenge required. Have the connection owner re-authenticate and complete MFA.",
    "Unauthorized": "Power Platform marked the credential unauthorized. Re-authenticate the connection.",
    "Unauthenticated": "Connection is not authenticated. Have the connection owner sign in to Power Platform.",
    "ConfigurationNeeded": "Connection was created but never fully configured (required parameter missing). Either finish setup in Power Platform or delete the unbound connection.",
}

# Error-code values from TOKEN_HEALTH_ERROR_CODES that indicate the
# connection was created but never configured (vs. lapsed auth on a
# previously-working connection). Used by _classify_token_health_error
# to set the severity/remediation class.
_CONFIG_ERROR_CODES = frozenset({"ConfigurationNeeded"})
# Error-code values that indicate a previously-working auth that has
# lapsed and needs the owner to re-authenticate.
_AUTH_ERROR_CODES = frozenset({"Unauthorized", "Unauthenticated"})

# Matches Entra error-code identifiers like "AADSTS50173" or "AADSTS700082"
# anywhere in a string. Anchored to a 5-7 digit AADSTS prefix to avoid
# matching unrelated digit sequences. Used by _classify_token_health_error
# to extract the specific failure code from the (often long, prose-y)
# ``statuses[0].error.message`` field.
_AADSTS_CODE_RE = re.compile(r"\b(AADSTS\d{5,7})\b")


def _classify_token_health_error(
    conn: dict,
) -> tuple[str | None, str | None, str, str]:
    """Inspect ``statuses[0].error`` on a connection record and return
    ``(reported_code, reported_message, hint, severity_class)`` for
    token-health classification.

    The PowerApps connections API includes a structured ``error`` block
    on non-Connected statuses (target, code, message). The actual
    actionable Entra failure code (e.g. ``AADSTS50173``) is embedded
    in ``error.message`` rather than ``error.code`` (which is the
    coarser Power-Platform-side classification — typically
    ``Unauthorized`` or ``Unauthenticated``). We:

      1. First try to extract an ``AADSTSnnnnn`` code from
         ``error.message``. If found, that becomes the reported code
         and we look its hint up in TOKEN_HEALTH_ERROR_CODES.
      2. Otherwise we report the ``error.code`` field verbatim and
         look that up.
      3. If neither resolves to a known entry, we fall back to a
         generic re-authenticate hint and still surface whatever
         code/message the API returned so the operator can search
         for it in MS Learn.

    ``severity_class`` is one of:
      - ``"config"`` — connection was never fully configured (e.g.
        ``ConfigurationNeeded`` with ``Parameter value missing``).
        Different remediation path: finish setup OR delete the
        orphan; "re-authenticate" doesn't apply to something that
        was never authenticated.
      - ``"auth"`` — auth grant on a previously-working connection
        has lapsed (any AADSTS code, ``Unauthorized``,
        ``Unauthenticated``). Owner must re-authenticate.
      - ``"unknown"`` — error block present but neither config nor
        auth shape recognized. Treated as auth-style in remediation
        but flagged as needing investigation.

    Returns ``(None, None, no-status-hint, "unknown")`` only when the
    entire ``statuses`` array is missing or empty.

    Cited consumer: ``_check_connection_token_health`` (this file).
    Source (validated): ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``
    lines 2661-2680 capture the live AADSTS50173-in-message shape;
    lines 2682-2700+ capture the ``Unauthenticated`` ("never signed in")
    shape; the production fields used (``status`` / ``target`` / ``code``
    / ``message``) all appear in the cassette. The ``ConfigurationNeeded``
    shape was observed live on 2026-05-21 in env
    ``PROD - ESS + WD + SNow`` on 3-of-7 Workday SOAP connections that
    were created but never had their ``sku`` parameter populated.
    """
    statuses = conn.get("properties", {}).get("statuses", [])
    if not isinstance(statuses, list) or not statuses:
        return None, None, "No status information returned by Power Platform.", "unknown"
    err = statuses[0].get("error") or {}
    raw_code = err.get("code")
    raw_message = err.get("message") or ""

    # Tier 1: extract AADSTS code from message (production shape).
    aadsts_match = _AADSTS_CODE_RE.search(raw_message)
    if aadsts_match:
        aadsts_code = aadsts_match.group(1)
        hint = TOKEN_HEALTH_ERROR_CODES.get(
            aadsts_code,
            "Unrecognized AADSTS error. Re-authenticate the connection in Power Platform.",
        )
        return aadsts_code, raw_message, hint, "auth"

    # Tier 2: fall back to the coarser error.code value.
    if raw_code:
        hint = TOKEN_HEALTH_ERROR_CODES.get(
            raw_code,
            "Unrecognized token-health error. Re-authenticate the connection in Power Platform.",
        )
        if raw_code in _CONFIG_ERROR_CODES:
            severity = "config"
        elif raw_code in _AUTH_ERROR_CODES:
            severity = "auth"
        else:
            severity = "unknown"
        return raw_code, raw_message or None, hint, severity

    # Tier 3: error block present but neither an AADSTS code nor a code field.
    return None, raw_message or None, (
        "Connection reported an error but Power Platform did not include a "
        "structured error code. Re-authenticate the connection."
    ), "unknown"


def _check_connection_token_health(runner) -> list[CheckResult]:
    """WD-CONN-101 — Workday connection token / grant health (deep).

    WD-CONN-001 reports whether each Workday connection is in
    ``Connected`` state. WD-CONN-101 goes one level deeper: for any
    Workday connection NOT in ``Connected`` state, it parses the
    structured ``statuses[0].error.{code,message}`` block the
    PowerApps connections API returns, classifies the failure into
    config-needed vs lapsed-auth vs unknown, cross-references each
    unhealthy connection against the env's flow connection-references
    to determine in-use vs orphan, and emits up to two CheckResults:

      - FAILED — connections that are unhealthy AND referenced by an
        active flow (these will break flow execution at runtime).
      - WARNING — connections that are unhealthy but not referenced by
        any flow (cleanup task: orphan leftovers from solution
        imports, abandoned manual creation attempts, etc.).

    Each entry in the results carries enough operator-actionable
    detail to fix the issue without leaving the FlightCheck output:

      - Connection display name + short id suffix (so operators can
        disambiguate between 7 connections all named "Workday").
      - Owner — falls back to ``createdBy.userPrincipalName`` /
        ``createdBy.displayName`` when ``accountName`` is null
        (frequently the case for admin-scope listings of connections
        owned by other users).
      - Creation date — helps the operator spot stale records.
      - Deep link to the maker portal connections page.
      - For config-needed orphans: the exact
        ``Remove-AdminPowerAppConnection`` PowerShell command,
        pre-filled with env id, connection name, and connector name.
      - For lapsed-auth connections: the maker URL the owner needs
        to visit to re-authenticate, plus the per-AADSTS-code hint
        from TOKEN_HEALTH_ERROR_CODES.

    Mock tier (validated): backed by ``tests/mocks/pp_admin.py``
    (MOCK_STATUS = "validated", cassette
    ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``). Same
    endpoint as WD-CONN-001 — ``GET /providers/Microsoft.PowerApps/
    scopes/admin/environments/{env_id}/connections`` — so no new
    cassette is required. The flow-listing step uses
    ``pp.get_flows(env_id)`` against the validated Flow admin
    endpoint (also in the cassette).

    Scope notes (intentionally narrower than the issue suggested):
      * The runtime ESS Workday integration uses WS-Security
        UsernameToken (Basic auth via ISU username + password), so
        there is no Workday-side OAuth/refresh token to inspect. The
        OAuth surface that DOES exist is the Power Platform
        connection's wrapper grant — the Entra token from the user
        who created the connection ref. That is what WD-CONN-101
        inspects.
      * The issue also suggested an active SOAP probe
        (Get_Server_Timestamp / Get_Workers count=1). That ground is
        already covered by the existing WD-WF-* checks, which call
        17 real ESS workflows against the live Workday tenant when
        ISU credentials are supplied. WD-CONN-101 deliberately stays
        offline-only against the BAP cassette to avoid duplicating
        WD-WF-001 and to keep the check fast in CI.
      * The PowerApps connections API does NOT expose a
        ``lastRefreshedTimestamp`` field on connection records (not
        present in the validated cassette), so the issue's
        "warn-if-token-older-than-IdP-lifetime" branch is not
        implementable from this surface. Documented as a follow-up.
    """
    results: list[CheckResult] = []
    pp = runner.pp_admin
    env_id = runner.env_id

    if not env_id or pp is None:
        return results

    try:
        all_conns = pp.get_connections(env_id)
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connection token health",
            result=f"Unable to check: {e}",
        ))
        return results

    if isinstance(all_conns, dict) and "_error" in all_conns:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connection token health",
            result=f"Unable to list connections: {all_conns['_error']}",
            remediation="Requires Power Platform Administrator role.",
        ))
        return results

    wd_conns = filter_connections_by_connector(all_conns, "workday")

    if not wd_conns:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="Workday connection token health",
            result="No Workday connections found",
            remediation="Configure Workday SOAP connections in the environment.",
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))
        return results

    unhealthy: list[dict] = []
    for c in wd_conns:
        if get_connection_status(c) == "Connected":
            continue
        code, message, hint, severity = _classify_token_health_error(c)
        unhealthy.append({
            "conn": c,
            "code": code,
            "message": message,
            "hint": hint,
            "severity": severity,
        })

    if not unhealthy:
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday connection token health",
            result=f"All {len(wd_conns)} Workday connection(s) report healthy auth state",
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))
        return results

    # In-use cross-reference. None ⇒ couldn't determine (treat all as
    # in-use for safety; better to over-report FAILED than to silently
    # demote a real flow-breaker to WARNING).
    in_use_names = _get_in_use_workday_connection_names(runner)

    failed_entries: list[dict] = []
    warning_entries: list[dict] = []
    for entry in unhealthy:
        conn_name = entry["conn"].get("name", "")
        if in_use_names is None:
            is_in_use = True
        else:
            is_in_use = conn_name in in_use_names
        entry["in_use"] = is_in_use
        entry["in_use_determined"] = in_use_names is not None
        if is_in_use:
            failed_entries.append(entry)
        else:
            warning_entries.append(entry)

    if failed_entries:
        details = [_format_unhealthy_detail(e) for e in failed_entries]
        remediations = [_format_unhealthy_remediation(e, env_id) for e in failed_entries]
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description="Workday connection token health",
            result=(
                f"{len(failed_entries)} of {len(wd_conns)} Workday connection(s) "
                f"have unhealthy auth state and are referenced by a flow: "
                + "; ".join(details)
            ),
            remediation=" | ".join(remediations),
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))

    if warning_entries:
        details = [_format_unhealthy_detail(e) for e in warning_entries]
        remediations = [_format_unhealthy_remediation(e, env_id) for e in warning_entries]
        results.append(CheckResult(
            checkpoint_id="WD-CONN-101", category="Workday",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Workday connection token health",
            result=(
                f"{len(warning_entries)} orphan Workday connection(s) "
                f"(unhealthy but not referenced by any flow — cleanup task): "
                + "; ".join(details)
            ),
            remediation=" | ".join(remediations),
            doc_link=f"{DOC_BASE}/workday#step-3-connection-references",
        ))

    return results


# ── Operator-actionable formatting helpers for WD-CONN-101 ────────────
#
# Each unhealthy connection emits two strings into the CheckResult:
#
#   1. detail   — short identifier line that goes into the ``result``
#                 (the "what's broken") field.
#   2. remediation — actionable hint that goes into the ``remediation``
#                    field (the "what to do about it") field, including
#                    deep links and pre-filled PowerShell commands.
#
# The split exists because in the FlightCheck report, ``result`` shows
# in the summary table and ``remediation`` shows in the expandable
# detail — operators scan the summary first to triage, then read the
# remediation when they're ready to act.


def _extract_conn_id_suffix(name: str) -> str:
    """Return a short stable identifier from a connection's full name.

    PowerApps connection names follow the shape
    ``shared-<connector>-<guid>``, e.g.
    ``shared-workdaysoap-ac42a2e7-2ebf-4217-a7d7-0488d0fd48da``. We
    return the first 8-hex-digit segment from the GUID (e.g.
    ``ac42a2e7``) so operators can disambiguate between connections
    that all share the display name "Workday".
    """
    match = re.search(r"\b([0-9a-f]{8})\b", name.lower())
    if match:
        return match.group(1)
    # Fallback: last 8 chars of whatever we got.
    return name[-8:] if len(name) >= 8 else name or "(no-id)"


def _resolve_owner(props: dict) -> str:
    """Return the most useful owner identity available on a connection.

    Admin-scope connection listings (the endpoint WD-CONN-101 uses)
    frequently return ``accountName: null`` even when the connection
    has a clear creator — observed live on 2026-05-21 across 7 Workday
    connections owned by ``lmoulet@EmployeeHub.onmicrosoft.com`` where
    ``accountName`` was null but ``createdBy.userPrincipalName`` was
    populated.

    Falls back through ``accountName`` → ``createdBy.userPrincipalName``
    → ``createdBy.displayName`` → ``"(unknown owner)"`` so the
    operator gets the most actionable identity available.
    """
    account = props.get("accountName")
    if account:
        return account
    created_by = props.get("createdBy") or {}
    upn = created_by.get("userPrincipalName")
    if upn:
        return upn
    display = created_by.get("displayName")
    if display:
        return display
    return "(unknown owner)"


def _format_created_date(props: dict) -> str:
    """Return the YYYY-MM-DD portion of ``createdTime`` for compact display."""
    ts = props.get("createdTime") or ""
    if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
        return ts[:10]
    return "(unknown date)"


def _extract_connector_name(conn: dict) -> str:
    """Extract the connector type name (e.g. ``shared_workdaysoap``)
    from the connection's ``apiId`` path. Used to build the
    ``-ConnectorName`` argument of the PowerShell delete command."""
    api_id = conn.get("properties", {}).get("apiId", "")
    match = re.search(r"/apis/([^/]+)/?$", api_id)
    return match.group(1) if match else "shared_workdaysoap"


def _maker_connections_url(env_id: str) -> str:
    """Direct link to the Power Automate maker connections page.

    We use make.powerautomate.com over make.powerapps.com because the
    PowerAutomate experience renders the env-scoped connections list
    more reliably across the multiple PPAC IA churns observed in
    2024-2026.
    """
    return f"https://make.powerautomate.com/environments/{env_id}/connections"


def _format_unhealthy_detail(entry: dict) -> str:
    """Single-connection detail line for the ``result`` field.

    Shape: ``'<display>' (id=<suffix>, owner=<owner>, created=<date>):
    <code> — <message>``
    """
    c = entry["conn"]
    props = c.get("properties", {})
    name = props.get("displayName", "(unnamed)")
    suffix = _extract_conn_id_suffix(c.get("name", ""))
    owner = _resolve_owner(props)
    date = _format_created_date(props)
    code = entry["code"] or "no-error-code"
    msg_excerpt = (entry["message"] or "").split("\n", 1)[0][:140]
    return (
        f"'{name}' (id={suffix}, owner={owner}, created={date}): "
        f"{code} — {msg_excerpt}"
    ).rstrip(" —")


def _format_unhealthy_remediation(entry: dict, env_id: str) -> str:
    """Single-connection remediation hint for the ``remediation`` field.

    Template varies by severity_class × in_use:
      - config + in-use:    owner must finish setup (flow depends on this)
      - config + orphan:    PowerShell delete command (never used, safe to remove)
      - auth + in-use:      owner must re-authenticate (admins can't re-auth others)
      - auth + orphan:      owner re-auth OR PowerShell delete
      - unknown + in-use:   owner investigates (we don't know what's wrong)
      - unknown + orphan:   owner investigates OR PowerShell delete
    """
    c = entry["conn"]
    props = c.get("properties", {})
    name = props.get("displayName", "(unnamed)")
    suffix = _extract_conn_id_suffix(c.get("name", ""))
    owner = _resolve_owner(props)
    severity = entry["severity"]
    hint = entry["hint"]
    in_use = entry["in_use"]
    conn_name = c.get("name", "")
    connector = _extract_connector_name(c)
    maker_url = _maker_connections_url(env_id)
    delete_cmd = (
        f"Remove-AdminPowerAppConnection -EnvironmentName {env_id} "
        f"-ConnectionName {conn_name} -ConnectorName {connector}"
    )
    prefix = f"'{name}' (id={suffix}, owner={owner}):"

    if severity == "config":
        if in_use:
            return (
                f"{prefix} {hint} Connection is referenced by an active flow — "
                f"owner ({owner}) must finish setup at {maker_url}; admins "
                f"cannot configure on owner's behalf."
            )
        return (
            f"{prefix} {hint} Connection is not referenced by any flow "
            f"(likely solution-import leftover). Delete as Power Platform "
            f"Admin: `{delete_cmd}`"
        )

    if severity == "auth":
        if in_use:
            return (
                f"{prefix} {hint} Connection is referenced by an active flow — "
                f"owner ({owner}) must re-authenticate at {maker_url}; admins "
                f"cannot re-auth on owner's behalf (would change the identity "
                f"the flow runs under)."
            )
        return (
            f"{prefix} {hint} Connection is not referenced by any flow. "
            f"Either owner re-authenticates at {maker_url} or delete as "
            f"orphan: `{delete_cmd}`"
        )

    # unknown
    if in_use:
        return (
            f"{prefix} {hint} Connection is referenced by an active flow — "
            f"owner ({owner}) should investigate at {maker_url}."
        )
    return (
        f"{prefix} {hint} Connection is not referenced by any flow. Either "
        f"owner investigates at {maker_url} or delete as orphan: `{delete_cmd}`"
    )


def _get_in_use_workday_connection_names(runner) -> set[str] | None:
    """Return the set of Workday connection names referenced by any
    flow in the environment, or ``None`` if we couldn't determine it.

    Each flow's ``properties.connectionReferences.{ref_key}`` carries
    the apiId of the connector and the bound connection's name. We
    collect every connection name where the apiId contains 'workday'.

    ``None`` ⇒ couldn't enumerate flows (flow API failed, returned
    insufficient_permissions, raised). The caller treats this as
    "unknown ⇒ assume in-use" so we don't silently demote real
    flow-breakers to WARNING.
    """
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    if not pp or not env_id:
        return None
    try:
        flows = pp.get_flows(env_id)
    except Exception:
        return None
    if isinstance(flows, dict) and "_error" in flows:
        return None
    if not isinstance(flows, list):
        return None
    in_use: set[str] = set()
    for f in flows:
        refs = (f.get("properties") or {}).get("connectionReferences") or {}
        if not isinstance(refs, dict):
            continue
        for _ref_key, ref in refs.items():
            if not isinstance(ref, dict):
                continue
            api_id = (
                ref.get("apiId")
                or (ref.get("api") or {}).get("name", "")
                or ""
            )
            if "workday" not in api_id.lower():
                continue
            conn_name = (
                ref.get("connectionName")
                or (ref.get("connection") or {}).get("name", "")
                or ""
            )
            if conn_name:
                in_use.add(conn_name)
    return in_use


def _check_flow_status(runner, wd_flows: list) -> list[CheckResult]:
    """Check whether Workday flows are enabled."""
    results = []

    enabled = 0
    disabled = 0
    for i, f in enumerate(wd_flows):
        props = f.get("properties", {})
        name = props.get("displayName", f.get("displayName", f"Flow {i+1}"))
        state = props.get("state", "")
        is_on = state.lower() in ("started", "on", "enabled")
        cid = f"WD-FLOW-{i+1:03d}"

        if is_on:
            enabled += 1
        else:
            disabled += 1

        results.append(CheckResult(
            checkpoint_id=cid, category="Workday",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if is_on else Status.FAILED.value,
            description=f"Flow: {name}",
            result=f"State: {'Enabled' if is_on else 'Disabled'}",
            remediation=f"Enable '{name}' in Power Automate." if not is_on else "",
            doc_link=f"{DOC_BASE}/workday#topics",
        ))

    return results


def _check_workflows(runner) -> list[CheckResult]:
    """Test all 17 Workday SOAP workflows.

    Resolves credentials from multiple sources (in priority order):
      1. Environment variables (if already set, e.g. from a parent process)
      2. .vscode/mcp.json (base URL + tenant are stored as plain strings)
      3. .local/config.json -> connections.Workday (tenant, base URL)
      4. Interactive prompt (username + password only - never cached to disk)
      5. .local/config.json -> workdayTestEmployeeId (cached after first prompt)

    Gated on `runner._workday_package_flavor`: skipped on
    `"simplified"`. The 17 workflows exercise Workday SOAP via ISU
    credentials, which the simplified install does not use (OBO via
    the signed-in user replaces the ISU code path). Without this gate
    the natural credential-missing skip path emits
    ``"Workday ISU credentials not provided"`` and asks the operator
    to provide ISU creds — actively misleading guidance on a tenant
    that intentionally has no ISU. See `_simplified_install_skip`
    for the SKIP message contract.
    """
    flavor = getattr(runner, "_workday_package_flavor", None)
    if flavor == "simplified":
        results = [_simplified_install_skip(
            checkpoint_id="WD-WF-000",
            description="Workday SOAP workflow tests",
            category="Workday Workflows",
        )]
        _append_wd_wf_cat_link_trailer(runner, results)
        return results

    results = []

    # --- Resolve non-sensitive metadata first (URL, tenant, employee). ---
    # CodeQL clear-text logging rule taints every output of any function that
    # also returns sensitive data. Splitting metadata from credentials keeps
    # the metadata path off the taint graph so we can safely print the tenant
    # name in status messages.
    wd_base_url, wd_tenant, test_employee = _resolve_workday_metadata(runner)

    if not wd_base_url or not wd_tenant:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="Workday not configured - skipping 17 workflow tests",
            remediation="Run /connect workday first, then re-run /flightcheck.",
        ))
        _append_wd_wf_cat_link_trailer(runner, results)
        return results

    if not test_employee:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="No test employee ID provided - skipping workflow tests",
            remediation="Re-run flightcheck and enter a test employee ID when prompted.",
        ))
        _append_wd_wf_cat_link_trailer(runner, results)
        return results

    # Safe to log here - tenant is from the metadata-only resolver, but we
    # do not interpolate it into the message because CodeQL classifies any
    # WORKDAY_* env var as private (clear-text logging rule).
    print("  Testing 17 Workday workflows...")

    try:
        import httpx  # noqa: F401  (used inside _soap_call)
    except ImportError:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="httpx not installed - skipping",
            remediation="pip install httpx",
        ))
        _append_wd_wf_cat_link_trailer(runner, results)
        return results

    # --- Now resolve credentials. From this point on the local scope holds
    # sensitive values; do not add print/log statements that reference any
    # local variable. ---
    wd_username, wd_password = _resolve_workday_credentials(runner, wd_tenant)
    if not wd_username or not wd_password:
        results.append(CheckResult(
            checkpoint_id="WD-WF-000", category="Workday Workflows",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="Workday SOAP workflow tests",
            result="Workday ISU credentials not provided - skipping workflow tests",
            remediation=(
                "Re-run flightcheck; when prompted, enter your ISU "
                "username and password to test the 17 workflows."
            ),
        ))
        _append_wd_wf_cat_link_trailer(runner, results)
        return results

    import datetime
    effective_date = datetime.date.today().isoformat()

    for i, wf in enumerate(WORKFLOWS):
        cid = f"WD-WF-{i+1:03d}"
        pii_tag = " [PII]" if wf.get("pii") else ""
        desc = f"Workflow: {wf['name']}{pii_tag} ({wf['type']})"

        if wf["type"] == "Write":
            # Write tests — check access to Change_Work_Contact_Information
            body = _build_write_test_body(test_employee)
            result = _soap_call(
                wd_base_url, wd_tenant, wd_username, wd_password,
                wf["service"], body,
            )
            if result["success"] or "permission" not in result.get("error", "").lower():
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=desc, result="API accessible",
                ))
            else:
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.FAILED.value,
                    description=desc, result="Permission denied",
                    remediation="Ask Workday Admin to grant Contact Information security domain.",
                ))
            continue

        # Read tests
        if wf.get("custom_operation"):
            body = _build_compensation_body(test_employee)
        else:
            body = _build_get_workers_body(test_employee, effective_date, wf["response_group"])

        result = _soap_call(
            wd_base_url, wd_tenant, wd_username, wd_password,
            wf["service"], body,
        )

        if result["success"]:
            # Check XPath for expected data
            try:
                root = ET.fromstring(result["response"])
                found = root.findall(wf["xpath"])
                if found:
                    results.append(CheckResult(
                        checkpoint_id=cid, category="Workday Workflows",
                        priority=Priority.HIGH.value, status=Status.PASSED.value,
                        description=desc, result="Data retrieved",
                    ))
                else:
                    results.append(CheckResult(
                        checkpoint_id=cid, category="Workday Workflows",
                        priority=Priority.HIGH.value, status=Status.PASSED.value,
                        description=desc,
                        result="API accessible (no data for this employee)",
                    ))
            except (ET.ParseError, DefusedXmlException):
                # ET.ParseError = malformed XML.
                # DefusedXmlException = attack-path construct rejected by
                # defusedxml (EntitiesForbidden, ExternalReferenceForbidden,
                # DTDForbidden, NotSupportedError). Both should fall through
                # to the structured "unparseable XML" result instead of
                # surfacing as an unhandled traceback to the user.
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.PASSED.value,
                    description=desc, result="API responded (unparseable XML)",
                ))
        else:
            error = result.get("error", "Unknown")
            if any(k in error.lower() for k in ("permission", "unauthorized", "not authorized")):
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.FAILED.value,
                    description=desc, result="Permission denied",
                    remediation="Ask Workday Admin to grant required security domain.",
                ))
            else:
                results.append(CheckResult(
                    checkpoint_id=cid, category="Workday Workflows",
                    priority=Priority.HIGH.value, status=Status.FAILED.value,
                    description=desc, result=f"Error: {error[:100]}",
                ))

    # Cross-link trailer (WD-WF-CAT-LINK) — surfaces the WD-WF-CAT-001
    # manual checklist from inside the SOAP-test output so admins
    # reading a clean 17-row pass don't miss the custom-scenario
    # inventory row. See `_append_wd_wf_cat_link_trailer` for why this
    # also fires on the credential-missing skip path.
    _append_wd_wf_cat_link_trailer(runner, results)

    return results


def _append_wd_wf_cat_link_trailer(runner, results: list[CheckResult]) -> None:
    """Append the WD-WF-CAT-LINK row to `results` if there are unknown
    Workday scenario references in customer topics.

    Called from EVERY exit path of `_check_workflows` (not just the
    SOAP-test-loop-completed path) so the cross-link surfaces even
    when SOAP tests are skipped for credential-missing reasons.
    AC2 ("Linked from Test-WorkdayWorkflows output when an unknown
    workflow name is referenced in customer topics") needs the link
    to appear regardless of whether the operator has configured ISU
    creds yet — the inventory of custom scenarios doesn't depend on
    Workday connectivity.

    The result text is deliberately worded "above" without naming
    "17 SOAP tests" because some exit paths emit zero SOAP rows.
    """
    unknown = _get_unknown_workday_scenarios(runner)
    if not unknown:
        return
    results.append(CheckResult(
        checkpoint_id="WD-WF-CAT-LINK", category="Workday Workflows",
        priority=Priority.MEDIUM.value, status=Status.MANUAL.value,
        description="Custom Workday scenarios outside the SOAP-test catalog",
        result=(
            f"{len(unknown)} Workday scenario reference(s) in customer "
            "topics are NOT covered by the automated SOAP tests in this "
            "Workday Workflows block."
        ),
        remediation=(
            "See WD-WF-CAT-001 for the per-scenario list and the "
            "manual verification checklist (ISU account, payload "
            "shape vs. Workday WSDL, evaluation test prompt, "
            "connection-ref auth health)."
        ),
    ))


# ─────────────────────────────────────────────────────────────────────────
# WD-WF-CAT-001 — Workday custom-workflow inventory checklist (MANUAL)
# ─────────────────────────────────────────────────────────────────────────
#
# The kit hard-codes a 17-workflow SOAP-test catalog (`WORKFLOWS`
# above). Customers wire up additional Workday scenarios two ways:
#
#   1. Template-config + topic — a topic calls
#      `dialog: msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetCommonExecution`
#      with a `scenarioName: msdyn_...` value. The shared flow reads
#      the matching template config row from Dataverse by ScenarioName
#      and executes the SOAP request.
#   2. Standalone topic + cloud flow — `kind: InvokeFlowAction`
#      pointing at a Power Automate flow bound to `shared_workdaysoap`.
#
# Both paths exit FlightCheck's automated validation surface. The
# kit cannot:
#   * Parse tenant-specific Workday WSDL to validate payload shape.
#   * Read template config XML field-by-field against the WSDL.
#   * Confirm the ISU used by the custom scenario has the right
#     Workday security domain.
#   * Tell whether an evaluation test exists for the custom scenario.
#
# Per AGENTS.md principle #2, this is the canonical MANUAL pattern:
# the kit observes one side (topic references scenario X), the
# operator verifies the other side (Workday-tenant configuration).
#
# Data sources:
#   * Local YAML walk (`workspace/agents/*/topics/*.mcs.yml`) —
#     no API call, no cassette required.
#   * Local JSON catalog (`scripts/flightcheck/data/`
#     `workday_scenario_catalog.json`) — the known-OOTB set.
#   * Cached `runner._workday_package_flavor` (from WD-PKG-001) for
#     the simplified-install gate per principle #11.
#
# Outputs:
#   * One PASSED row if every discovered scenario is in the catalog.
#   * One MANUAL row enumerating unknowns + the 4-item checklist
#     (Principle #7 — bucketed, not per-resource).
#   * One SKIPPED row on simplified install (no ISU/RaaS), missing
#     workspace, or zero Workday references.
# Caches discovered + unknown lists on the runner so the WD-WF-CAT-LINK
# trailer inside _check_workflows can reference them without re-walking.

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WORKDAY_SCENARIO_CATALOG_PATH = DATA_DIR / "workday_scenario_catalog.json"

# Marker for the shared Workday execution topic (Pattern A). The
# `dialog:` field is fully-qualified and always contains this suffix
# regardless of agent publisher prefix.
_WORKDAY_SYSTEM_DIALOG_SUFFIX = ".topic.WorkdaySystemGetCommonExecution"


def _load_workday_scenario_catalog() -> set[str]:
    """Read the JSON catalog and return the set of OOTB scenarioNames.

    Returns an empty set if the file is missing or unparseable so the
    check still runs (everything will look "unknown" — the operator's
    cue that the catalog file needs attention, not a check crash).
    """
    if not WORKDAY_SCENARIO_CATALOG_PATH.exists():
        return set()
    try:
        data = json.loads(WORKDAY_SCENARIO_CATALOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    scenarios = data.get("scenarios", [])
    return {s.get("scenarioName", "") for s in scenarios if s.get("scenarioName")}


def _is_workday_bound_workflow_json(workflow_json_path: Path) -> bool:
    """Return True if a Power Automate workflow.json references the
    Workday SOAP connector (`shared_workdaysoap`) anywhere in its
    `connectionReferences` block.

    Used to qualify Pattern B (InvokeFlowAction) references: a flow
    is "Workday-bound" if any of its connection references binds to
    the Workday SOAP connector. Conservative — a flow that touches
    both Workday and another connector still counts as Workday-bound
    so the operator gets surfaced for review.
    """
    if not workflow_json_path.exists():
        return False
    try:
        data = json.loads(workflow_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    conn_refs = data.get("properties", {}).get("connectionReferences", {})
    for ref in conn_refs.values():
        api_obj = ref.get("api", {})
        if api_obj.get("name", "") == "shared_workdaysoap":
            return True
        # Fallback for older flow JSON shapes that put it directly:
        if ref.get("apiId", "").lower().endswith(WORKDAY_SOAP_CONNECTOR_SUFFIX):
            return True
    return False


def _build_workflow_id_to_path_index(agent_dir: Path) -> dict[str, Path]:
    """Walk `agent_dir/workflows/*/metadata.yml`, parse the workflowId
    out of each, and return {workflowId(lowercase): workflow.json path}.

    Built once per agent so Pattern-B lookups are O(1) per topic
    reference. Metadata YAML format is documented in
    workspace/agents/{slug}/workflows/<dir>/metadata.yml — single key
    `workflowId:` plus `jsonFileName:` (always `workflow.json`).
    """
    index: dict[str, Path] = {}
    workflows_dir = agent_dir / "workflows"
    if not workflows_dir.exists():
        return index
    for sub in workflows_dir.iterdir():
        if not sub.is_dir():
            continue
        metadata = sub / "metadata.yml"
        if not metadata.exists():
            continue
        try:
            content = metadata.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^\s*workflowId\s*:\s*([0-9a-fA-F-]{36})\s*$", content, re.MULTILINE)
        if m:
            workflow_json = sub / "workflow.json"
            index[m.group(1).lower()] = workflow_json
    return index


def _scan_topic_for_workday_refs(
    topic_path: Path, agent_slug: str, workflow_index: dict[str, Path],
) -> list[dict]:
    """Scan a single topic YAML for Workday scenario references.

    Returns a list of dicts, one per reference found. Each dict has:
      agent:        the agent folder slug
      topic:        topic filename
      line:         1-based line number of the trigger line
      scenarioName: str | None  (None for Pattern B)
      pattern:      "system-common-execution" | "invoke-flow-action"
      flowId:       str | None  (set only for Pattern B)
    """
    try:
        lines = topic_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    refs: list[dict] = []

    # Pattern A: line ending in WorkdaySystemGetCommonExecution; walk
    # back to find the nearest scenarioName: above it (within ~30
    # lines — the typical BeginDialog block size).
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "dialog:" in stripped and _WORKDAY_SYSTEM_DIALOG_SUFFIX in stripped:
            scenario_line = None
            scenario_value = None
            for j in range(i - 1, max(-1, i - 31), -1):
                back = lines[j].strip()
                m = re.match(r"^scenarioName\s*:\s*=?\s*\"?([\w]+)\"?\s*$", back)
                if m:
                    scenario_line = j + 1
                    scenario_value = m.group(1)
                    break
            refs.append({
                "agent": agent_slug,
                "topic": topic_path.name,
                "line": scenario_line if scenario_line else i + 1,
                "scenarioName": scenario_value,
                "pattern": "system-common-execution",
                "flowId": None,
            })

    # Pattern B: InvokeFlowAction → flowId → workflow.json bound to
    # shared_workdaysoap. Pull every (kind:InvokeFlowAction, flowId)
    # pair, then qualify against the workflow index.
    in_invoke_block = False
    invoke_start_line = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^-?\s*kind\s*:\s*InvokeFlowAction\s*$", stripped):
            in_invoke_block = True
            invoke_start_line = i + 1
            continue
        if in_invoke_block:
            m = re.match(r"^flowId\s*:\s*([0-9a-fA-F-]{36})\s*$", stripped)
            if m:
                flow_id = m.group(1).lower()
                workflow_json = workflow_index.get(flow_id)
                if workflow_json and _is_workday_bound_workflow_json(workflow_json):
                    refs.append({
                        "agent": agent_slug,
                        "topic": topic_path.name,
                        "line": invoke_start_line,
                        "scenarioName": None,
                        "pattern": "invoke-flow-action",
                        "flowId": flow_id,
                    })
                in_invoke_block = False
                invoke_start_line = -1
            # Heuristic close: a new top-level `- kind:` line ends
            # the current InvokeFlowAction block without a flowId.
            elif re.match(r"^-\s*kind\s*:", stripped) and i > invoke_start_line - 1:
                in_invoke_block = False
                invoke_start_line = -1
    return refs


def _discover_customer_workday_scenarios(
    workspace_root: Path = Path("workspace/agents"),
) -> list[dict]:
    """Walk every agent under workspace_root and return all Workday
    scenario references (Pattern A + Pattern B). Returns [] when the
    workspace doesn't exist (callers should treat that as SKIPPED, not
    PASSED — see _check_custom_workflow_inventory).
    """
    if not workspace_root.exists():
        return []
    discovered: list[dict] = []
    for agent_dir in sorted(workspace_root.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("."):
            continue
        topics_dir = agent_dir / "topics"
        if not topics_dir.exists():
            continue
        workflow_index = _build_workflow_id_to_path_index(agent_dir)
        for topic_file in sorted(topics_dir.glob("*.mcs.yml")):
            discovered.extend(
                _scan_topic_for_workday_refs(
                    topic_file, agent_dir.name, workflow_index,
                )
            )
    return discovered


def _get_unknown_workday_scenarios(runner) -> list[dict]:
    """Return the cached list of unknown Workday refs, computing and
    caching it on first read.

    Used by both _check_custom_workflow_inventory and the
    WD-WF-CAT-LINK trailer inside _check_workflows so the topic walk
    runs at most once per flightcheck invocation regardless of which
    check the runner schedules first.
    """
    cached = getattr(runner, "_workday_unknown_scenarios", None)
    if cached is not None:
        return cached
    workspace_root_str = "workspace/agents"
    discovered = _discover_customer_workday_scenarios(Path(workspace_root_str))
    catalog = _load_workday_scenario_catalog()
    unknown = [
        ref for ref in discovered
        if ref["pattern"] == "invoke-flow-action"
        or (ref.get("scenarioName") and ref["scenarioName"] not in catalog)
    ]
    runner._workday_discovered_scenarios = discovered
    runner._workday_unknown_scenarios = unknown
    return unknown


def _format_unknown_scenarios(unknown: list[dict]) -> str:
    """Format the unknown-refs list for the result field. One block per
    reference, agent + topic + line cited verbatim per AGENTS.md
    principle #8 (result = what the kit observed).
    """
    lines: list[str] = []
    for ref in unknown:
        if ref["pattern"] == "system-common-execution":
            name = ref.get("scenarioName") or "(scenarioName not found in topic)"
            lines.append(f"  • {name}")
            lines.append(
                f"    Topic:    topics/{ref['topic']}:{ref['line']}"
            )
            lines.append("    Pattern:  WorkdaySystemGetCommonExecution + scenarioName")
        else:  # invoke-flow-action
            lines.append(f"  • <flow-bound, no scenarioName> ({ref.get('flowId', '')})")
            lines.append(
                f"    Topic:    topics/{ref['topic']}:{ref['line']}"
            )
            lines.append("    Pattern:  InvokeFlowAction → flow bound to shared_workdaysoap")
        lines.append(f"    Agent:    {ref['agent']}")
        lines.append("")
    return "\n".join(lines).rstrip()


_WD_WF_CAT_CHECKLIST = (
    "Manual verification required — the kit cannot validate custom "
    "Workday scenarios end-to-end. For EACH scenario listed above:\n"
    "\n"
    "  1. ISU account: Confirm which ISU registered in Workday is used "
    "by this scenario. Default is the account in environment variable "
    "EmployeeContextRequestAccountName (see WD-ENV-001 output). Custom "
    "scenarios may use a different ISU — verify in the template config "
    "XML in Dataverse (Power Platform Maker → Tables → "
    "msdyn_employeeselfservicetemplateconfigs → search ScenarioName).\n"
    "\n"
    "  2. Payload shape: Open the template config XML and confirm the "
    "SOAP request body matches the Workday WSDL for the named service. "
    "Field names, reference types, and required vs. optional elements "
    "MUST match the Workday contract. Mismatches surface at runtime as "
    "the 'Workflow Contract/Payload Mismatch' failure mode.\n"
    "\n"
    "  3. Test prompt: Add at least one evaluation test case to the "
    "agent's evaluations/ folder that exercises the scenario end-to-end "
    "with a known-good employee. Use /create-eval and tag the test set "
    "with the scenario name.\n"
    "\n"
    "  4. Auth health: Re-check the WD-CONN-* connection token health "
    "output for the connection reference this scenario uses. "
    "Intermittent auth failures usually trace to a stale OAuth token "
    "on one of the ISU refs — reauthenticate in Power Platform Maker "
    "→ Connections.\n"
    "\n"
    "Found a new pattern not in the kit's catalog? File an issue at "
    "https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/issues/new "
    "with title 'Workday scenario catalog gap: <scenarioName>' and "
    "include the topic snippet, the template config XML, and the ADO "
    "incident number if any. The catalog data file lives at "
    "scripts/flightcheck/data/workday_scenario_catalog.json — PRs "
    "adding new rows are welcome.\n"
    "\n"
    "Note: the kit's catalog seed is derived from the vendored ESS "
    "samples (~28 scenarios). Microsoft's full extension-pack catalog "
    "may include more — names above that look OOTB should be PR'd to "
    "the catalog file rather than left as recurring MANUAL noise."
)


def _check_custom_workflow_inventory(runner) -> list[CheckResult]:
    """WD-WF-CAT-001 — Manual checklist for custom Workday workflows.

    Gates:
      * `runner._workday_package_flavor == "simplified"` → SKIPPED
        (ISU/scenario inventory doesn't apply on the simplified
        install per AGENTS.md principle #11).
      * Missing `workspace/agents/` → SKIPPED.
      * Zero Workday references discovered → SKIPPED.

    Otherwise:
      * Every discovered scenario in the OOTB catalog → PASSED.
      * Any unknown / flow-bound reference → MANUAL with bucketed
        listing in `result` and the 4-item checklist in `remediation`.

    Caches results on `runner._workday_unknown_scenarios` and
    `runner._workday_discovered_scenarios` so the WD-WF-CAT-LINK
    trailer inside _check_workflows can read them without re-walking.
    """
    cp_id = "WD-WF-CAT-001"
    category = "Workday Workflows"
    description = "Workday custom-workflow inventory checklist"
    doc_link = f"{DOC_BASE}/workday-extensibility"

    flavor = getattr(runner, "_workday_package_flavor", None)
    if flavor == "simplified":
        return [_simplified_install_skip(
            checkpoint_id=cp_id,
            description=description,
            category=category,
        )]

    workspace_root = Path("workspace/agents")
    if not workspace_root.exists():
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=description,
            result="workspace/agents/ directory not found.",
            remediation=(
                "Run /setup to extract agent files before this check "
                "can enumerate Workday scenario references in topics."
            ),
            doc_link=doc_link,
        )]

    unknown = _get_unknown_workday_scenarios(runner)
    discovered = getattr(runner, "_workday_discovered_scenarios", [])

    if not discovered:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=description,
            result=(
                "No Workday scenario references found in any agent topic. "
                "Either Workday is not wired into the customer's agent yet, "
                "or its topics are not yet extracted to "
                "workspace/agents/*/topics/."
            ),
            remediation=(
                "If the customer intends to use Workday, run /create to add "
                "a Workday scenario topic, or /setup to re-extract topics "
                "if you expected references to be present."
            ),
            doc_link=doc_link,
        )]

    if not unknown:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=description,
            result=(
                f"Found {len(discovered)} Workday scenario reference(s) "
                "in customer topics. All are in the OOTB scenario catalog "
                "(scripts/flightcheck/data/workday_scenario_catalog.json) "
                "and require no manual review."
            ),
            doc_link=doc_link,
        )]

    body = _format_unknown_scenarios(unknown)
    return [CheckResult(
        checkpoint_id=cp_id, category=category,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=description,
        result=(
            f"Found {len(unknown)} Workday scenario reference(s) in "
            "customer topics that the kit cannot validate end-to-end "
            "(not in the OOTB catalog):\n\n"
            f"{body}"
        ),
        remediation=_WD_WF_CAT_CHECKLIST,
        doc_link=doc_link,
    )]


# ---- Credential Resolution ----

def _resolve_workday_metadata(runner) -> tuple[str, str, str]:
    """Resolve non-sensitive Workday metadata: (base_url, tenant, test_employee_id).

    Deliberately split from credential resolution so CodeQL's data-flow
    analysis does not taint the metadata via tuple-unpacking with sensitive
    return values (clear-text logging rule).
    """
    base_url = os.environ.get("WORKDAY_BASE_URL", "")
    tenant = os.environ.get("WORKDAY_TENANT", "")
    test_employee = os.environ.get("WORKDAY_TEST_EMPLOYEE_ID", "")

    # --- Source 2: .vscode/mcp.json (non-secret values only) ---
    if not base_url or not tenant:
        mcp_env = _read_mcp_workday_env()
        if not base_url:
            base_url = mcp_env.get("WORKDAY_BASE_URL", "")
        if not tenant:
            tenant = mcp_env.get("WORKDAY_TENANT", "")

    # --- Source 3: .local/config.json -> connections.Workday ---
    config = getattr(runner, "config", {})
    wd_config = config.get("connections", {}).get("Workday", {})
    if not base_url:
        base_url = wd_config.get("baseUrl", "")
    if not tenant:
        tenant = wd_config.get("tenant", "")
    if not test_employee:
        test_employee = config.get("workdayTestEmployeeId", "")

    # --- Source 5: Test employee ID (prompt + cache in config) ---
    if not test_employee and sys.stdin.isatty():
        test_employee = input("  Test Employee ID (e.g. 21508): ").strip()
        if test_employee:
            _cache_test_employee_id(test_employee)

    return base_url, tenant, test_employee


def _resolve_workday_credentials(runner, tenant: str) -> tuple[str, str]:
    """Resolve sensitive Workday credentials: (username, password).

    Reads from env first, then prompts interactively. Never returns metadata,
    so CodeQL won't propagate password taint into URL/tenant variables in
    the caller. Caller MUST NOT introduce print/log statements that
    reference local variables after calling this function.
    """
    username = os.environ.get("WORKDAY_USERNAME", "")
    password = os.environ.get("WORKDAY_PASSWORD", "")

    # --- Source 4: Interactive prompt for secrets ---
    if (not username or not password) and sys.stdin.isatty():
        print("\n  Workday SOAP workflow tests need ISU credentials.")
        print("  (Credentials are used for this run only - never saved to disk)\n")
        if not username:
            username = input("  ISU Username (without @tenant): ").strip()
            if username and "@" not in username:
                # Tenant suffix appended via concatenation - never logged.
                username = username + "@" + tenant
        if not password:
            password = getpass.getpass("  ISU Password: ")

    return username, password


def _resolve_workday_creds(runner) -> tuple[str, str, str, str, str]:
    """Compatibility shim: combine metadata + credentials in the legacy
    5-tuple shape. Prefer the split _resolve_workday_metadata /
    _resolve_workday_credentials pair in new code; this shim exists for
    callers (or tests) that still expect the old signature.
    """
    base_url, tenant, test_employee = _resolve_workday_metadata(runner)
    if not base_url or not tenant:
        return "", "", "", "", ""
    username, password = _resolve_workday_credentials(runner, tenant)
    return base_url, tenant, username, password, test_employee


def _read_mcp_workday_env() -> dict:
    """Read non-secret Workday env vars from .vscode/mcp.json."""
    mcp_path = os.path.join(".vscode", "mcp.json")
    if not os.path.exists(mcp_path):
        return {}

    try:
        with open(mcp_path, "r", encoding="utf-8") as f:
            mcp = json.load(f)

        servers = mcp.get("servers", {})
        wd_server = servers.get("Workday", {})
        env = wd_server.get("env", {})

        # Only return values that are actual strings (not ${input:...} refs)
        result = {}
        for key in ("WORKDAY_BASE_URL", "WORKDAY_TENANT"):
            val = env.get(key, "")
            if val and not val.startswith("${"):
                result[key] = val
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _cache_test_employee_id(employee_id: str):
    """Save the test employee ID to .local/config.json for future runs."""
    config_path = os.path.join(".local", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["workdayTestEmployeeId"] = employee_id
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except (OSError, json.JSONDecodeError):
        pass  # Non-critical — they'll just be prompted again next time


# ---- SOAP Envelope Builders (ported from Test-WorkdayWorkflows.ps1) ----

BSVC = "urn:com.workday/bsvc"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"


def _build_soap_envelope(username: str, password: str, body_xml: str) -> str:
    # Escape username/password so XML special characters in credentials
    # (notably & in passwords) do not produce malformed XML.
    safe_user = xml_escape(username)
    safe_pass = xml_escape(password)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="{SOAP}" xmlns:bsvc="{BSVC}">
  <env:Header>
    <wsse:Security env:mustUnderstand="1" xmlns:wsse="{WSSE}">
      <wsse:UsernameToken>
        <wsse:Username>{safe_user}</wsse:Username>
        <wsse:Password>{safe_pass}</wsse:Password>
      </wsse:UsernameToken>
    </wsse:Security>
  </env:Header>
  <env:Body>{body_xml}</env:Body>
</env:Envelope>"""


def _build_get_workers_body(employee_id: str, effective_date: str, response_group: str) -> str:
    # Defense-in-depth: escape the values that come from .local/config.json /
    # env vars. response_group is intentionally left raw - it is a static XML
    # fragment from the WORKFLOWS table by design (e.g.,
    # '<bsvc:Include_Reference>true</bsvc:Include_Reference>'); escaping it
    # would corrupt the envelope.
    employee_id = xml_escape(employee_id)
    effective_date = xml_escape(effective_date)
    return f"""
<bsvc:Get_Workers_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References bsvc:Skip_Non_Existing_Instances="false">
    <bsvc:Worker_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Worker_Reference>
  </bsvc:Request_References>
  <bsvc:Response_Filter>
    <bsvc:As_Of_Effective_Date>{effective_date}</bsvc:As_Of_Effective_Date>
  </bsvc:Response_Filter>
  <bsvc:Response_Group>
    {response_group}
  </bsvc:Response_Group>
</bsvc:Get_Workers_Request>"""


def _build_compensation_body(employee_id: str) -> str:
    employee_id = xml_escape(employee_id)
    return f"""
<bsvc:Get_Compensation_Plans_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References>
    <bsvc:Compensation_Plan_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Compensation_Plan_Reference>
  </bsvc:Request_References>
</bsvc:Get_Compensation_Plans_Request>"""


def _build_write_test_body(employee_id: str) -> str:
    employee_id = xml_escape(employee_id)
    return f"""
<bsvc:Get_Change_Work_Contact_Information_Event_Request xmlns:bsvc="{BSVC}" bsvc:version="v42.0">
  <bsvc:Request_References>
    <bsvc:Change_Work_Contact_Information_Event_Reference>
      <bsvc:ID bsvc:type="Employee_ID">{employee_id}</bsvc:ID>
    </bsvc:Change_Work_Contact_Information_Event_Reference>
  </bsvc:Request_References>
</bsvc:Get_Change_Work_Contact_Information_Event_Request>"""


def _redact_ws_security(xml_text: str) -> str:
    """Remove any WS-Security UsernameToken block from XML before logging.

    Workday occasionally echoes parts of the request envelope into responses
    (especially in error responses). The envelope contains the ISU password
    in the wsse:UsernameToken element. Strip the entire Security header
    block before any logging or return-to-caller path so the password
    cannot leak into FlightCheck reports or error messages.
    """
    if not xml_text or 'wsse:Security' not in xml_text and 'UsernameToken' not in xml_text:
        return xml_text
    import re
    # Drop any <*:Security>...</*:Security> block (any namespace prefix).
    xml_text = re.sub(
        r'<[^/>]*:?Security[^>]*>.*?</[^>]*:?Security>',
        '<Security>[REDACTED]</Security>',
        xml_text,
        flags=re.DOTALL,
    )
    # Belt-and-suspenders: also strip any standalone UsernameToken or Password tag.
    xml_text = re.sub(
        r'<[^/>]*:?UsernameToken[^>]*>.*?</[^>]*:?UsernameToken>',
        '<UsernameToken>[REDACTED]</UsernameToken>',
        xml_text,
        flags=re.DOTALL,
    )
    xml_text = re.sub(
        r'<[^/>]*:?Password[^>]*>.*?</[^>]*:?Password>',
        '<Password>[REDACTED]</Password>',
        xml_text,
    )
    return xml_text


def _summarize_soap_error(status_code: int, resp_text: str) -> str:
    """Extract a safe-to-log summary from an error SOAP response.

    Returns the SOAP faultstring if present (Workday faultstrings describe
    the error condition without echoing the request body), otherwise just
    the HTTP status code. Never returns raw response text - error responses
    can include echoed request content that contains the WS-Security
    UsernameToken (CodeQL: clear-text logging of sensitive information).
    """
    if not resp_text:
        return f"HTTP {status_code}"
    try:
        root = ET.fromstring(resp_text)
        # SOAP 1.1 faultstring (no namespace) and SOAP 1.2 fault Reason/Text
        for path in ('.//{*}faultstring', './/{*}Reason/{*}Text', './/faultstring'):
            el = root.find(path)
            if el is not None and el.text:
                return f"HTTP {status_code}: {el.text.strip()[:200]}"
    except Exception:
        pass
    return f"HTTP {status_code}"


def _soap_call(
    base_url: str, tenant: str, username: str, password: str,
    service: str, body_xml: str,
) -> dict:
    """Make a synchronous SOAP call to Workday. Returns {success, response|error}.

    Both the response and error returns are scrubbed of WS-Security
    UsernameToken content before being handed back to the caller, so the
    ISU password cannot end up in FlightCheck reports or stdout.
    """
    import httpx

    url = f"{base_url}/{tenant}/{service}/v42.0"
    full_user = username if "@" in username else f"{username}@{tenant}"
    envelope = _build_soap_envelope(full_user, password, body_xml)

    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            resp = client.post(
                url,
                content=envelope,
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
            if resp.status_code < 400:
                # Even on success, scrub WS-Security in case Workday echoes it
                # (defense-in-depth - the success body normally doesn't include it).
                return {"success": True, "response": _redact_ws_security(resp.text)}
            return {
                "success": False,
                "error": _summarize_soap_error(resp.status_code, resp.text),
            }
    except Exception as e:
        # Don't echo str(e) verbatim if it looks like it might contain the URL
        # with embedded credentials; httpx errors don't normally include them
        # but be cautious.
        msg = str(e)
        if password and password in msg:
            msg = msg.replace(password, '[REDACTED]')
        return {"success": False, "error": msg}
