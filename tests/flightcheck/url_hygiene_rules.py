# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Rules for the offline URL hygiene gate (see ``test_url_hygiene.py``).

What this gate does (and deliberately does NOT do)
--------------------------------------------------
FlightCheck check code emits URLs into the HTML report (``doc_link``
buttons and remediation deep-links). This gate is a cheap, offline,
deterministic guard on the ONE property that can be checked without a
network: **a URL an operator is meant to fetch must use ``https``.**

It is intentionally NOT an allowlist of every host FlightCheck may emit.
An earlier design required every host appearing anywhere in FlightCheck
source to be registered in a curated set. That was dropped because:

  * It was self-referential. The same author who writes a URL also edits
    the registry, so a typo that is copied into the registry passes. It
    only caught the narrow case of "typo the URL but forget the
    registry", while adding an every-PR maintenance tax (each new
    legitimate host was a red build until someone hand-registered it,
    including hosts that only appear in docstrings and never reach a
    report).
  * The class of bug it targeted (a typo'd or hallucinated host) is rare
    and is already covered by human review plus the repo's "No fabricated
    URLs" rule.

Clickability of report links is handled separately in the report
renderer (PR #208). Verifying that a well-formed link is still *live*
(not a moved article that now 404s or redirects to the docs home) needs
real network access and is a separate, scheduled concern, kept out of
this deterministic gate.

The https rule (fail-closed)
----------------------------
Every ``http(s)`` URL found in FlightCheck source must be ``https``,
UNLESS its host is a known namespace / identifier that is legitimately
``http``. A namespace URI (e.g. a SOAP or SAML namespace) is an
*identifier*, not an address to fetch, so it is exempt. Everything else
is required to be ``https`` by default, so a genuinely new fetchable host
is covered automatically with no registry edit.

To exempt a new identifier host: confirm it is a namespace / example URI
that is never meant to be clicked, then add it to
``HTTP_ALLOWED_IDENTIFIER_HOSTS`` below with a one-line reason.
"""

from __future__ import annotations

# Hosts that legitimately appear with an ``http`` scheme because they are
# namespace / identifier URIs, NOT fetchable addresses. A namespace URI
# identifies a schema; nobody browses it, so requiring https on it would
# be a false positive. Keep this set small and justify every entry.
HTTP_ALLOWED_IDENTIFIER_HOSTS: frozenset[str] = frozenset({
    "schemas.xmlsoap.org",   # SOAP 1.1 / WS-* XML namespace URIs
    "docs.oasis-open.org",   # OASIS SAML 2.0 XML namespace URIs
    "www.workday.com",       # Workday SOAP/SAML namespace + example issuer
    "sts.windows.net",       # example Entra issuer URI (an identifier, not a page)
})


def requires_https(host: str) -> bool:
    """Return True if ``host`` must appear only with an ``https`` scheme.

    Fail-closed: every host requires https EXCEPT the known namespace /
    identifier hosts in ``HTTP_ALLOWED_IDENTIFIER_HOSTS``. This means a
    new, unlisted host is required to be https by default (no registry
    edit needed to cover it).
    """
    return host not in HTTP_ALLOWED_IDENTIFIER_HOSTS


def looks_like_host(host: str) -> bool:
    """Return True if ``host`` is structurally a real domain.

    A cheap sanity guard so a malformed capture (empty, no dot, stray
    scheme punctuation) is caught rather than silently treated as a
    valid host. The URL-scanning regex already restricts the character
    set; this adds the "has a dot and non-empty labels" shape check.
    """
    if not host or "." not in host:
        return False
    labels = host.split(".")
    return all(labels) and all(
        c.isalnum() or c in "-_" for label in labels for c in label
    )
