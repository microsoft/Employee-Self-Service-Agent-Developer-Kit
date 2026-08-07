# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Rules for the offline URL hygiene gate (see ``test_url_hygiene.py``).

What this gate does (and deliberately does NOT do)
--------------------------------------------------
FlightCheck check code emits URLs into the HTML report (``doc_link``
buttons and remediation deep-links). This gate is a cheap, offline,
deterministic guard on the ONE property that can be checked without a
network: **a URL an operator is meant to fetch must use ``https``.**

Honest scope: the gate does NOT parse dataflow to isolate only the URLs
that actually reach the report. It scans the *text* of FlightCheck
source (string literals, docstrings, and comments alike) for every
``http(s)`` URL. It is **fail-closed on any insecure URL in scanned
source** -- an ``http://`` example written in a docstring will fail the
gate too. That is intentional: an insecure example URL should not live
in the source either, and a text scan cannot tell an emitted URL from an
illustrative one without full AST dataflow analysis (deliberately out of
scope as over-engineering for this guard).

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

Known blind spots (stated, not silently ignored)
------------------------------------------------
  * **Concatenated / fully-templated schemes.** A URL assembled at
    runtime such as ``"http://" + host`` or ``f"http://{sub}.example"``
    (where the *host* is a template) has no static host to read. The
    scan flags a templated *host* that is introduced with an ``http``
    scheme (``http://{...}``) because an insecure templated link is
    still wrong, but a scheme split across a concatenation (the literal
    ``"http://"`` sits apart from the host token) cannot be seen at all.
  * **Non-scanned file types.** Only ``.py`` and data files
    (``.yaml`` / ``.yml`` / ``.json``) under the FlightCheck source dir
    are scanned. Markdown docs are not -- they are documentation, not a
    source of report-rendered URLs.
  * **Exemption honesty.** Offline, we cannot prove a host is truly a
    non-fetchable namespace identifier rather than a real page. We
    mitigate two ways: exemptions are matched at URI granularity (not
    bare host, see below), and a test asserts every exemption actually
    corresponds to a namespace/identifier URI present in source, so a
    dead or lazily-added exemption fails the suite.

The https rule (fail-closed)
----------------------------
Every ``http(s)`` URL found in scanned source must be ``https``, UNLESS
the URL is a known namespace / identifier URI that is legitimately
``http``. A namespace URI (e.g. a SOAP or SAML namespace) is an
*identifier*, not an address to fetch, so it is exempt. Everything else
is required to be ``https`` by default, so a genuinely new fetchable host
is covered automatically with no registry edit.

Exemptions are matched at **URI granularity, not bare host.** Earlier
this exempted whole hosts, which created a blind spot: a host like
``www.workday.com`` is BOTH a SAML/SOAP issuer identifier
(``http://www.workday.com/<tenant>``) AND a real fetchable marketing
domain. Exempting the whole host would wave through a genuinely
fetchable ``http://www.workday.com/<page>`` an operator is meant to
click. So the Workday issuer is exempted only in its identifier shape
(host + exactly one tenant token), and a deeper/real page path on the
same host is still required to be ``https``.

To exempt a new identifier URI: confirm it is a namespace / issuer URI
that is never meant to be fetched, then add a prefix to
``HTTP_ALLOWED_URI_PREFIXES`` (for a pure-namespace host) or a shape
pattern to ``HTTP_ALLOWED_URI_PATTERNS`` (for a dual-use host), each
with a one-line reason. The exemption must correspond to an ``http``
URI that actually appears in source or the suite fails.
"""

from __future__ import annotations

import re

# Namespace / identifier URI *prefixes* that are legitimately ``http``.
# These hosts serve ONLY XML namespace / schema identifier URIs; nobody
# browses them, so ``http`` is correct and requiring ``https`` would be a
# false positive. Matched as a URL prefix, not a bare host.
HTTP_ALLOWED_URI_PREFIXES: tuple[str, ...] = (
    "http://schemas.xmlsoap.org/",  # SOAP 1.1 / WS-* / SAML claim XML namespace URIs
    "http://docs.oasis-open.org/",  # OASIS WS-Security / SAML XML namespace URIs
)

# Dual-use identifier *shape* patterns: the host is ALSO a real fetchable
# domain, so exempt only the specific identifier-URI shape rather than the
# whole host. The Workday SAML/SOAP issuer identifier is
# ``http://www.workday.com/<tenant>`` -- host plus exactly one tenant
# token (a literal like ``contoso_prod`` or a ``{WD_TENANT}`` template),
# no deeper path. A real fetchable Workday page (multi-segment path, or a
# path with a dot/filename) does NOT match and must be https.
HTTP_ALLOWED_URI_PATTERNS: tuple[re.Pattern[str], ...] = (
    # WD issuer identifier: one tenant segment, literal or {template}.
    re.compile(r"^http://www\.workday\.com/(?:\{[A-Za-z0-9_]+\}|[A-Za-z0-9_]+)$"),
)


def is_allowed_http_uri(url: str) -> bool:
    """Return True if ``url`` may legitimately use the ``http`` scheme.

    Fail-closed: an ``http`` URL is allowed ONLY when it is a known
    namespace / identifier URI, matched at URI granularity (a prefix in
    ``HTTP_ALLOWED_URI_PREFIXES`` or an exact shape in
    ``HTTP_ALLOWED_URI_PATTERNS``). Everything else must be ``https``.

    Matching at URI granularity (not bare host) is deliberate: a dual-use
    host that is both a namespace/issuer identifier and a real fetchable
    domain (e.g. ``www.workday.com``) is exempt only in its identifier
    shape, so a genuinely fetchable ``http`` page on the same host is
    still caught.
    """
    if url.startswith(HTTP_ALLOWED_URI_PREFIXES):
        return True
    return any(pattern.match(url) for pattern in HTTP_ALLOWED_URI_PATTERNS)


def looks_like_host(host: str) -> bool:
    """Return True if ``host`` is structurally a real DNS domain.

    A cheap sanity guard so a malformed capture (empty, no dot, stray
    scheme punctuation) is caught rather than silently treated as a valid
    host. Enforces DNS label rules the URL-scanning regex does not: each
    dot-separated label must be non-empty, contain only alphanumerics or
    hyphens (no underscores -- not valid in a DNS hostname), and not begin
    or end with a hyphen.
    """
    if not host or "." not in host:
        return False
    for label in host.split("."):
        if not label or label.startswith("-") or label.endswith("-"):
            return False
        if not all(c.isalnum() or c == "-" for c in label):
            return False
    return True
