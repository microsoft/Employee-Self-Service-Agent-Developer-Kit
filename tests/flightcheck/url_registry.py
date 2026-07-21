# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Curated registry of URL hosts FlightCheck is allowed to emit.

FlightCheck check code produces URLs in three shapes:

1. **Portal / documentation links** — user-facing links that land in the
   HTML report (``doc_link`` buttons and remediation deep-links). These
   are what the operator clicks to fix a finding, so a wrong host here
   (typo, or a hallucinated domain) sends them nowhere.
2. **Backend API / auth / telemetry hosts** — base URLs the kit's HTTP
   clients call (Graph, BAP, ARM, login.microsoftonline.com, …). Never
   browsed by a human, but still must be a real, intended Microsoft host.
3. **XML namespace / example URIs** — SOAP/SAML namespace identifiers
   (``schemas.xmlsoap.org``) and documented example values
   (``http://www.workday.com/contoso_prod``). These are *not* links; they
   must never be treated as clickable and are allowed to be ``http``.

The offline hygiene test (``test_url_hygiene.py``) asserts that every
host appearing in FlightCheck source is present in exactly one of the
sets below. That turns "someone added a new / misspelled host" into a
review signal: the test fails until the host is deliberately categorized
here. It is a *host*-level gate — it deliberately does NOT verify that a
path is live (that a learn.microsoft.com article still exists). Stale
paths that 404 or redirect to the docs home are a separate concern for a
future scheduled liveness checker, which can reuse these same sets.

To add a new host: decide which category it belongs to and add it to the
matching set (or ``APPROVED_HOST_SUFFIXES`` for per-tenant subdomains),
after confirming the host is a real Microsoft / team-owned domain.
"""

from __future__ import annotations

# 1. User-facing portal + documentation link hosts. These reach the
#    report as clickable links, so they MUST be https.
PORTAL_AND_DOC_HOSTS: frozenset[str] = frozenset({
    "learn.microsoft.com",
    "admin.powerplatform.microsoft.com",
    "admin.microsoft.com",
    "copilotstudio.microsoft.com",
    "portal.azure.com",
    "entra.microsoft.com",
    "config.office.com",
    "make.powerapps.com",
    "make.powerautomate.com",
    "github.com",
})

# 2. Backend API / auth / telemetry hosts the kit's clients call. Real
#    Microsoft endpoints, not human-browsable; still enforced to https.
API_HOSTS: frozenset[str] = frozenset({
    "graph.microsoft.com",
    "management.azure.com",
    "login.microsoftonline.com",
    "api.bap.microsoft.com",
    "api.powerplatform.com",
    "api.powerapps.com",
    "service.powerapps.com",
    "api.flow.microsoft.com",
    "service.flow.microsoft.com",
    "mobile.events.data.microsoft.com",
})

# 3. XML namespace identifiers and documented example values. NOT links;
#    allowed to be http because a namespace URI is an identifier, not an
#    address to fetch.
NAMESPACE_AND_EXAMPLE_HOSTS: frozenset[str] = frozenset({
    "schemas.xmlsoap.org",
    "docs.oasis-open.org",
    "www.workday.com",       # Workday SOAP/SAML namespace + example issuer
    "sts.windows.net",       # example Entra issuer format in remediation
})

# Per-tenant / per-org subdomains where the leftmost label varies (e.g.
# a Dataverse org host ``org<hash>.crm.dynamics.com``). Matched by suffix.
APPROVED_HOST_SUFFIXES: tuple[str, ...] = (
    ".crm.dynamics.com",
)

# Hosts that must be reached over https (everything that is a real
# address to fetch, as opposed to a namespace identifier).
HTTPS_REQUIRED_HOSTS: frozenset[str] = PORTAL_AND_DOC_HOSTS | API_HOSTS

# Every approved exact host, across all categories.
APPROVED_HOSTS: frozenset[str] = (
    PORTAL_AND_DOC_HOSTS | API_HOSTS | NAMESPACE_AND_EXAMPLE_HOSTS
)


def host_is_approved(host: str) -> bool:
    """Return True if ``host`` is an approved exact host or matches an
    approved per-tenant suffix (e.g. ``org123.crm.dynamics.com``)."""
    if host in APPROVED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in APPROVED_HOST_SUFFIXES)


def requires_https(host: str) -> bool:
    """Return True if ``host`` must only ever appear with an https scheme.

    Namespace / example hosts are exempt (a namespace URI is an
    identifier, not a fetchable address). Per-tenant API subdomains
    (``*.crm.dynamics.com``) are treated as API hosts and require https.
    """
    if host in HTTPS_REQUIRED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in APPROVED_HOST_SUFFIXES)
