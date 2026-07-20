# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared SAML helpers for Workday-federation FlightCheck checks.

AUTH-006 (Authentication category) and WD-CONN-010 (Workday category)
both enumerate federated Workday enterprise apps in the current Entra
tenant via Microsoft Graph and surface their SAML entity IDs. Two
constants and one helper were originally duplicated between
``checks/authentication.py`` and ``checks/workday.py``; this module
holds the single source of truth so both checks stay in sync.

Consumers:
  * AUTH-006 (``checks/authentication._run_saml_nameid_check``)
  * WD-CONN-010 (``checks/workday._check_entra_workday_federation_alignment``)
  * WD-ENTRA-NAMEID-001 (``checks/entra_app`` — S3.5 setup NameID check)
"""

import json


# Most production tenants name the federated Workday app starting with
# "Workday" (e.g. "Workday", "Workday Prod", "Workday Implementation").
# Match server-side via $filter so callers don't pull every SP in the
# tenant. Both AUTH-006 and WD-CONN-010 join on this exact predicate.
WORKDAY_SAML_SP_FILTER = (
    "startswith(displayName,'Workday') and preferredSingleSignOnMode eq 'saml'"
)

# Authoritative reference for the Entra→Workday SAML mapping behavior.
# Step 6 + note: "You need to map the Name ID with actual User ID in
# your Workday account". Workday itself matches the incoming NameID
# against the Workday Username — there is NO Workday-side configurable
# "which attribute to match" field; the alignment work happens
# entirely on the Entra side. The same tutorial walks the operator
# through the Workday-side IdP configuration screen WD-CONN-010
# delegates to.
WORKDAY_SSO_TUTORIAL_DOC = (
    "https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial"
)


def saml_entity_ids(service_principal_names: list[str]) -> list[str]:
    """Filter ``servicePrincipalNames`` to entries that look like a SAML
    entity ID (URI form), excluding the raw appId GUID.

    Microsoft Graph returns ``servicePrincipalNames`` as a mix of the
    application's appId GUID and one or more identifier URIs (the SAML
    entity ID for SAML apps). The Workday "Service Provider ID" column
    only ever shows the URI form, so the GUIDs are noise here.

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="servicePrincipal" — Property
              servicePrincipalNames (Collection(Edm.String)).
      Docs:   https://learn.microsoft.com/graph/api/resources/serviceprincipal?view=graph-rest-1.0
    """
    out: list[str] = []
    for spn in service_principal_names:
        if not isinstance(spn, str):
            continue
        # A bare appId GUID is 32 hex chars + 4 dashes = 36 chars, no
        # scheme separator and no path/colon characters. Anything with
        # a URI-shaped marker is a SAML entity ID.
        if "://" in spn or "/" in spn or ":" in spn:
            out.append(spn)
    return out


def summarize_nameid(policies: list[dict]) -> str:
    """Reduce a list of claimsMappingPolicies to a one-line description
    of what Entra is sending for the SAML NameID claim.

    Entra's claimsMappingPolicy.definition is a list of JSON-encoded
    strings, each containing a ClaimsMappingPolicy object with a
    ClaimsSchema array. The NameID entry has SamlClaimType
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier".
    Source for the encoding format (verbatim example response):
    https://learn.microsoft.com/graph/api/serviceprincipal-list-claimsmappingpolicies?view=graph-rest-1.0
    """
    if not policies:
        return "default (NameID = user.userPrincipalName — no custom claimsMappingPolicy assigned)"

    nameid_marker = "nameidentifier"
    findings: list[str] = []
    for pol in policies:
        for raw in pol.get("definition", []) or []:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            schema = (
                parsed.get("ClaimsMappingPolicy", {}).get("ClaimsSchema") or []
            )
            for claim in schema:
                saml_type = (claim.get("SamlClaimType") or "").lower()
                if nameid_marker in saml_type:
                    source = claim.get("Source", "?")
                    cid = claim.get("ID", "?")
                    findings.append(
                        f"override (policy '{pol.get('displayName', '?')}': "
                        f"NameID = {source}.{cid})"
                    )

    if findings:
        return "; ".join(findings)
    # Policies exist but none override NameID specifically.
    names = ", ".join(p.get("displayName", "(unnamed)") for p in policies)
    return (
        f"default (NameID = user.userPrincipalName — "
        f"{len(policies)} claimsMappingPolicy assigned [{names}] "
        f"but none override the NameID claim)"
    )
