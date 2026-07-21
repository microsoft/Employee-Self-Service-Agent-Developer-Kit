# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline hygiene gate for URL hosts emitted by FlightCheck.

Purpose: catch a whole class of broken links *before* merge, without any
network access. A wrong or hallucinated host (``learn.microsft.com``,
``admin.powerplatfrom.microsoft.com``) or an ``http`` portal link sends
the operator nowhere. This test scans FlightCheck source for every
``http(s)`` URL and asserts each static host is deliberately registered
in ``url_registry.py`` and (for real fetchable hosts) uses https.

Scope and honesty about limits:
  * This is a HOST-level gate. It catches typo'd / unapproved domains and
    http-on-a-portal. It deterministically runs offline, so it is safe to
    gate CI on.
  * It does NOT verify a path is live. A well-formed
    ``https://learn.microsoft.com/<moved-article>`` that now 404s or
    redirects to the docs home passes this test. That "stale path"
    problem needs a live (networked) checker, which is intentionally kept
    OUT of the deterministic suite and can reuse ``url_registry.py``.

This test reads source as text (stdlib only) — no imports of the check
modules, no tokens, no network — so it is cheap to run in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.flightcheck.url_registry import (
    API_HOSTS,
    NAMESPACE_AND_EXAMPLE_HOSTS,
    PORTAL_AND_DOC_HOSTS,
    host_is_approved,
    requires_https,
)

# scheme + host, where host is either a normal domain or a whole {template}.
# The host run stops at the first '/', quote, whitespace, or bracket.
_URL_RE = re.compile(r'(https?)://([A-Za-z0-9._\-]+|\{[^}]*\})')

_FLIGHTCHECK_SRC = (
    Path(__file__).resolve().parents[2]
    / "solutions" / "ess-maker-skills" / "scripts" / "flightcheck"
)


def _iter_source_urls():
    """Yield (file, scheme, host) for every static http(s) URL in source.

    Dynamic hosts (``https://{url}``) are skipped — a fully variable host
    cannot be validated statically and is not an authored link.
    """
    for path in sorted(_FLIGHTCHECK_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for scheme, host in _URL_RE.findall(text):
            if "{" in host or "}" in host:
                continue  # dynamic host, nothing to validate
            if "." not in host:
                continue  # dotless placeholder (e.g. https://host/…), not a real domain
            yield path, scheme, host


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
    hosts = {host for _f, _s, host in _iter_source_urls()}
    assert len(hosts) >= 10, (
        f"Expected many distinct hosts in FlightCheck source, found "
        f"{len(hosts)}: {sorted(hosts)}. The scan is likely broken."
    )


def test_every_emitted_host_is_registered() -> None:
    """Every static host in FlightCheck source must be categorized in
    url_registry.py. An unknown host is a review signal: either a typo, a
    hallucinated domain, or a genuinely new host that needs deliberate
    categorization."""
    unknown: dict[str, str] = {}
    for path, _scheme, host in _iter_source_urls():
        if not host_is_approved(host):
            unknown.setdefault(host, path.name)
    assert not unknown, (
        "Unregistered URL host(s) found in FlightCheck source. If a host "
        "is legitimate, add it to the correct set in "
        "tests/flightcheck/url_registry.py; if it is a typo, fix the URL.\n"
        + "\n".join(f"  {h}  (first seen in {f})" for h, f in sorted(unknown.items()))
    )


def test_portal_and_api_hosts_use_https() -> None:
    """Real fetchable hosts (portals, docs, backend APIs) must be https.
    Namespace / example URIs are exempt (a namespace URI is an identifier,
    not an address to fetch)."""
    insecure: list[str] = []
    for path, scheme, host in _iter_source_urls():
        if scheme != "https" and requires_https(host):
            insecure.append(f"{host} (http) in {path.name}")
    assert not insecure, (
        "http:// used for a host that must be https:\n  "
        + "\n  ".join(sorted(set(insecure)))
    )


# --- registry self-consistency -------------------------------------------

def test_registry_categories_are_disjoint() -> None:
    """A host must live in exactly one category, else the intent (link vs
    API vs namespace) is ambiguous."""
    assert not (PORTAL_AND_DOC_HOSTS & API_HOSTS)
    assert not (PORTAL_AND_DOC_HOSTS & NAMESPACE_AND_EXAMPLE_HOSTS)
    assert not (API_HOSTS & NAMESPACE_AND_EXAMPLE_HOSTS)


def test_host_is_approved_matches_suffix() -> None:
    assert host_is_approved("orgb78b4a3b.crm.dynamics.com")
    assert host_is_approved("learn.microsoft.com")
    assert not host_is_approved("learn.microsft.com")  # typo not approved
    assert not host_is_approved("evil.example.com")


def test_namespace_hosts_exempt_from_https_requirement() -> None:
    assert not requires_https("schemas.xmlsoap.org")
    assert requires_https("learn.microsoft.com")
    assert requires_https("orgb78b4a3b.crm.dynamics.com")
