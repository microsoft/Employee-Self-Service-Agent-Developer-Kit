# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline hygiene gate for URLs emitted by FlightCheck.

Purpose: catch, before merge and without any network access, a URL an
operator is meant to click that is served over insecure ``http``. The
check scans FlightCheck source for every ``http(s)`` URL and asserts each
fetchable host uses ``https``. Known namespace / identifier hosts (SOAP /
SAML namespace URIs) are exempt because they are identifiers, not
addresses to fetch.

Scope and honesty about limits:
  * This is an offline, deterministic gate on link *scheme* and basic
    host shape. It is safe to gate CI on.
  * It does NOT allowlist every host (an earlier design did; that was
    self-referential and high-maintenance -- see ``url_hygiene_rules``).
  * It does NOT make links clickable -- the report renderer does that
    (PR #208).
  * It does NOT verify a path is live. A well-formed
    ``https://learn.microsoft.com/<moved-article>`` that now 404s or
    redirects to the docs home passes this test. That "stale path"
    problem needs a live (networked) checker, kept OUT of this
    deterministic suite.

This test reads source as text (stdlib only) -- no imports of the check
modules, no tokens, no network -- so it is cheap to run in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.flightcheck.url_hygiene_rules import (
    HTTP_ALLOWED_IDENTIFIER_HOSTS,
    looks_like_host,
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

    Dynamic hosts (``https://{url}``) are skipped -- a fully variable host
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


def test_fetchable_urls_use_https() -> None:
    """Every fetchable URL must be https. Only known namespace / identifier
    hosts (SOAP / SAML namespace URIs) may be http, because a namespace URI
    is an identifier, not an address to fetch.

    Fail-closed: a new, unlisted host is required to be https by default,
    so a genuinely new fetchable host is covered with no registry edit."""
    insecure: list[str] = []
    for path, scheme, host in _iter_source_urls():
        if scheme != "https" and requires_https(host):
            insecure.append(f"{host} (http) in {path.name}")
    assert not insecure, (
        "http:// used for a host that should be https. If the host is a "
        "namespace / identifier URI that is never fetched, add it to "
        "HTTP_ALLOWED_IDENTIFIER_HOSTS in tests/flightcheck/"
        "url_hygiene_rules.py; otherwise change the URL to https:\n  "
        + "\n  ".join(sorted(set(insecure)))
    )


def test_every_host_is_structurally_valid() -> None:
    """Every scanned host must look like a real domain. Catches a malformed
    capture (empty label, stray punctuation) rather than letting it pass as
    a valid host."""
    malformed: list[str] = []
    for path, _scheme, host in _iter_source_urls():
        if not looks_like_host(host):
            malformed.append(f"{host} in {path.name}")
    assert not malformed, (
        "Malformed URL host(s) found in FlightCheck source:\n  "
        + "\n  ".join(sorted(set(malformed)))
    )


# --- rule helpers self-consistency ---------------------------------------

def test_identifier_hosts_are_exempt_from_https() -> None:
    for host in HTTP_ALLOWED_IDENTIFIER_HOSTS:
        assert not requires_https(host), (
            f"{host} is listed as an http-allowed identifier but "
            f"requires_https() still demands https for it."
        )


def test_unlisted_fetchable_hosts_require_https() -> None:
    # Fail-closed: anything not in the identifier exemption needs https.
    assert requires_https("learn.microsoft.com")
    assert requires_https("admin.powerplatform.microsoft.com")
    assert requires_https("some-brand-new-host.microsoft.com")


def test_looks_like_host_rejects_malformed() -> None:
    assert looks_like_host("learn.microsoft.com")
    assert looks_like_host("orgb78b4a3b.crm.dynamics.com")
    assert not looks_like_host("")
    assert not looks_like_host("localhost")   # no dot
    assert not looks_like_host("a..b")         # empty label
