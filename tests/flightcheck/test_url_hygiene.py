# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline hygiene gate for URLs in FlightCheck source.

Purpose: catch, before merge and without any network access, a URL an
operator is meant to fetch that is served over insecure ``http``. The
gate scans FlightCheck source for every ``http(s)`` URL and asserts each
fetchable URL uses ``https``. Known namespace / identifier URIs (SOAP /
SAML namespace URIs, the Workday issuer identifier) are exempt because
they are identifiers, not addresses to fetch.

Scope and honesty about limits (see ``url_hygiene_rules`` for detail):
  * This is an offline, deterministic gate on link *scheme* and basic
    host shape. It is safe to gate CI on.
  * It scans the *text* of source (``.py`` plus ``.yaml`` / ``.yml`` /
    ``.json`` data files), not only URLs proven to reach the report. It
    is fail-closed: any insecure ``http`` URL in scanned source fails,
    including one written in a docstring or comment. That is intentional
    -- distinguishing an emitted URL from an illustrative one needs full
    AST dataflow analysis, out of scope for this guard.
  * Exemptions are matched at URI granularity (namespace / issuer
    identifier), NOT bare host, so a dual-use host such as
    ``www.workday.com`` gets an http pass only in its issuer-identifier
    shape and a real fetchable page on it is still required to be https.
  * It does NOT allowlist every host (an earlier design did; that was
    self-referential and high-maintenance -- see ``url_hygiene_rules``).
  * It does NOT make links clickable -- the report renderer does that
    (PR #208).
  * It does NOT verify a path is live. A well-formed
    ``https://learn.microsoft.com/<moved-article>`` that now 404s or
    redirects to the docs home passes this test. That "stale path"
    problem needs a live (networked) checker, kept OUT of this
    deterministic suite.
  * Blind spot: a scheme split across a concatenation (``"http://" +
    host``) cannot be seen. A templated *host* introduced with ``http``
    (``http://{...}``) IS caught. Markdown docs are not scanned.

This test reads source as text (stdlib only) -- no imports of the check
modules, no tokens, no network -- so it is cheap to run in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.flightcheck.url_hygiene_rules import (
    HTTP_ALLOWED_URI_PATTERNS,
    HTTP_ALLOWED_URI_PREFIXES,
    is_allowed_http_uri,
    looks_like_host,
)

# scheme + host + optional path. Host uses the restrictive domain charset
# (or a whole ``{template}``) so a placeholder like ``https://host:8443``
# or HTML-escaped noise does not leak into the host token. The path runs
# up to the first delimiter (whitespace, quote, backtick, backslash, angle
# bracket, or a closing paren/bracket); brace chars stay IN the path so a
# templated path segment (``{WD_TENANT}``) is captured whole.
#
# The host is a run of literal domain chars and/or ``{template}`` segments,
# so a templated *host* with a real dotted suffix
# (``http://{org}.crm.dynamics.com``) is captured as one host token and
# still evaluated -- an insecure templated link is still insecure. A bare
# placeholder (``https://host:8443``, ``https://x``) has no dot and is
# dropped downstream, so it does not leak into the host token.
_URL_RE = re.compile(
    r"""(https?)://((?:[A-Za-z0-9._\-]+|\{[^}]*\})+)(/[^\s"'`\\<>)\]]*)?"""
)

# File types scanned. ``.py`` is the check source; data files can carry
# URLs that get rendered into the report. Markdown docs are excluded --
# they are documentation, not a report-rendering source.
_SCAN_GLOBS = ("*.py", "*.yaml", "*.yml", "*.json")

_FLIGHTCHECK_SRC = (
    Path(__file__).resolve().parents[2]
    / "solutions" / "ess-maker-skills" / "scripts" / "flightcheck"
)

# Trailing sentence punctuation that a URL written in prose may pick up.
_TRIM = ".,;:!?"


def _urls_in_text(text: str):
    """Yield (scheme, host, url) for every static http(s) URL in ``text``.

    Shared extraction used by the file scan and by tests. Trailing
    sentence punctuation is trimmed so a URL written in prose is not
    treated as malformed. A dotless host (``https://host``,
    ``https://localhost``, ``https://x``) is skipped -- it is a
    placeholder/example, not a real fetchable domain. A templated host
    with a dotted domain suffix (``http://{org}.crm.dynamics.com``) has a
    dot, so it is kept and still evaluated -- an insecure templated link
    is still insecure.
    """
    for scheme, host, rel in _URL_RE.findall(text):
        host = host.rstrip(_TRIM)
        rel = rel.rstrip(_TRIM)
        if not host:
            continue
        if "." not in host:
            continue  # dotless placeholder (host, localhost, x), not a domain
        yield scheme, host, f"{scheme}://{host}{rel}"


def _iter_source_urls():
    """Yield (path, scheme, host, url) for every static http(s) URL.

    ``url`` is the full captured URL (scheme + host + path); ``host`` is
    the authority component (may be a ``{template}`` for a dynamic host).
    See ``_urls_in_text`` for the per-text extraction and skip rules.
    """
    for glob in _SCAN_GLOBS:
        for path in sorted(_FLIGHTCHECK_SRC.rglob(glob)):
            text = path.read_text(encoding="utf-8")
            for scheme, host, url in _urls_in_text(text):
                yield path, scheme, host, url


def _is_dynamic(host: str) -> bool:
    """True if the host component is a template (e.g. ``{WD_TENANT}``),
    i.e. not a statically-known domain."""
    return "{" in host or "}" in host


def test_flightcheck_source_dir_exists() -> None:
    """Guard: if the source moves, fail loudly instead of scanning nothing
    and silently passing."""
    assert _FLIGHTCHECK_SRC.is_dir(), (
        f"FlightCheck source not found at {_FLIGHTCHECK_SRC}; update the "
        f"path in this test."
    )


def test_scan_actually_finds_urls() -> None:
    """Sanity: the scan must find a meaningful number of URLs, otherwise a
    broken regex/path would make the gate vacuously pass."""
    hosts = {
        host
        for _f, _s, host, _u in _iter_source_urls()
        if not _is_dynamic(host)
    }
    assert len(hosts) >= 10, (
        f"Expected many distinct hosts in FlightCheck source, found "
        f"{len(hosts)}: {sorted(hosts)}. The scan is likely broken."
    )


def test_fetchable_urls_use_https() -> None:
    """Every fetchable URL must be https. Only known namespace / identifier
    URIs (SOAP / SAML namespaces, the Workday issuer identifier) may be
    http, because a namespace URI is an identifier, not an address to
    fetch.

    Fail-closed: a new, unlisted URL is required to be https by default,
    so a genuinely new fetchable host is covered with no registry edit.
    A templated host introduced with an http scheme (``http://{...}``) is
    caught here too -- an insecure templated link is still insecure."""
    insecure: list[str] = []
    for path, scheme, _host, url in _iter_source_urls():
        if scheme != "https" and not is_allowed_http_uri(url):
            insecure.append(f"{url} in {path.name}")
    assert not insecure, (
        "http:// used for a URL that should be https. If it is a "
        "namespace / identifier URI that is never fetched, add a prefix "
        "or shape pattern to url_hygiene_rules.py (HTTP_ALLOWED_URI_"
        "PREFIXES / HTTP_ALLOWED_URI_PATTERNS); otherwise change the URL "
        "to https:\n  " + "\n  ".join(sorted(set(insecure)))
    )


def test_every_static_host_is_structurally_valid() -> None:
    """Every scanned static host must look like a real domain. Catches a
    malformed capture (empty label, underscore, leading/trailing hyphen)
    rather than letting it pass as a valid host. Dynamic ``{template}``
    hosts are skipped -- they are not static domains to shape-check."""
    malformed: list[str] = []
    for path, _scheme, host, _url in _iter_source_urls():
        if _is_dynamic(host):
            continue
        if not looks_like_host(host):
            malformed.append(f"{host} in {path.name}")
    assert not malformed, (
        "Malformed URL host(s) found in FlightCheck source:\n  "
        + "\n  ".join(sorted(set(malformed)))
    )


# --- rule helpers self-consistency ---------------------------------------

def test_namespace_prefix_uris_are_exempt_from_https() -> None:
    # A namespace URI under an exempted prefix is an identifier, not a page.
    assert is_allowed_http_uri("http://schemas.xmlsoap.org/soap/envelope/")
    assert is_allowed_http_uri(
        "http://docs.oasis-open.org/wss/2004/01/"
        "oasis-200401-wss-wssecurity-secext-1.0.xsd"
    )


def test_workday_issuer_is_exempt_but_real_pages_are_not() -> None:
    # Issuer identifier shape (host + one tenant token) is exempt ...
    assert is_allowed_http_uri("http://www.workday.com/contoso_prod")
    # ... but a genuinely fetchable page on the same host is NOT (this is
    # the coarse-host blind spot the URI-granular exemption closes).
    assert not is_allowed_http_uri("http://www.workday.com/en-us/pricing")
    assert not is_allowed_http_uri("http://www.workday.com/a/b")
    assert not is_allowed_http_uri("http://www.workday.com/page.html")


def test_unlisted_and_dynamic_http_uris_require_https() -> None:
    # Fail-closed: anything not an exempted identifier URI needs https.
    assert not is_allowed_http_uri("http://learn.microsoft.com/x")
    assert not is_allowed_http_uri("http://admin.powerplatform.microsoft.com/")
    assert not is_allowed_http_uri("http://some-brand-new-host.microsoft.com")
    # A templated host over http is not an exempt identifier either.
    assert not is_allowed_http_uri("http://{sub}.evil.com")


def test_every_http_exemption_is_used_and_justified() -> None:
    """Each exemption must correspond to a namespace / identifier http URI
    actually present in source. Closes the honor-system hole: a dead
    exemption, or a fetchable host lazily added to silence a failure,
    fails here because it matches no real namespace/identifier URI in the
    scanned source."""
    http_urls = [
        url for _p, scheme, _h, url in _iter_source_urls() if scheme == "http"
    ]
    for prefix in HTTP_ALLOWED_URI_PREFIXES:
        assert any(u.startswith(prefix) for u in http_urls), (
            f"Exemption prefix {prefix!r} matches no http URI in source; "
            f"remove the dead exemption from HTTP_ALLOWED_URI_PREFIXES."
        )
    for pattern in HTTP_ALLOWED_URI_PATTERNS:
        assert any(pattern.match(u) for u in http_urls), (
            f"Exemption pattern {pattern.pattern!r} matches no http URI in "
            f"source; remove the dead exemption from "
            f"HTTP_ALLOWED_URI_PATTERNS."
        )


def test_looks_like_host_rejects_malformed() -> None:
    assert looks_like_host("learn.microsoft.com")
    assert looks_like_host("orgb78b4a3b.crm.dynamics.com")
    assert not looks_like_host("")
    assert not looks_like_host("localhost")      # no dot
    assert not looks_like_host("a..b")            # empty label
    assert not looks_like_host("host_name.com")   # underscore not DNS-valid
    assert not looks_like_host("-a.b")            # leading hyphen
    assert not looks_like_host("a-.b")            # trailing hyphen


def test_scan_captures_templated_host_and_skips_placeholders() -> None:
    """Scan-level proof for the templated-host claim and the placeholder
    skip. A templated *host* with a dotted domain suffix over http is
    captured whole (host token includes the ``{...}`` segment) so the
    https gate still evaluates it; a bare placeholder (``host:port``,
    dotless ``x``) does not leak into a host token."""
    # Templated host with a real dotted suffix is captured, host kept whole.
    got = list(_urls_in_text("deep link http://{org}.crm.dynamics.com/report"))
    assert got == [
        ("http", "{org}.crm.dynamics.com", "http://{org}.crm.dynamics.com/report")
    ]
    # And it is treated as insecure (not an exempt identifier URI).
    assert not is_allowed_http_uri("http://{org}.crm.dynamics.com/report")
    # A literal host with a templated path is still captured too.
    assert list(_urls_in_text("iss http://www.workday.com/{WD_TENANT} x")) == [
        ("http", "www.workday.com", "http://www.workday.com/{WD_TENANT}")
    ]
    # Placeholders do not produce a host token.
    assert list(_urls_in_text("try https://host:8443/x and https://x here")) == []
