# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for clickable-link rendering in the FlightCheck report.

Context: report ``remediation`` text can carry links in two forms —
markdown ``[label](url)`` and bare ``https://…`` URLs. Historically only
the markdown form was turned into a clickable ``<a>``; a bare URL was
escaped to plain text, so it rendered but could not be clicked. Because
different checks authored URLs differently, operators saw links that
"worked sometimes but not others" — worst on MANUAL / NotConfigured rows,
where the remediation URL is the only path to the fix.

These tests pin the fix: BOTH forms must render as clickable anchors,
markdown anchors must not be double-wrapped, and trailing sentence
punctuation must stay outside the link. They exercise the pure-logic
renderers (no network), so no cassette/mock tier applies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Ensure scripts/ is on sys.path so `from flightcheck...` resolves."""
    scripts_dir = (
        Path(__file__).resolve().parents[1]
        / "solutions" / "ess-maker-skills" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


# --- bare-URL autolinking -------------------------------------------------

def test_bare_url_becomes_clickable_anchor() -> None:
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html(
        "Open https://learn.microsoft.com/ess/setup to continue."
    )
    assert (
        '<a href="https://learn.microsoft.com/ess/setup" '
        'target="_blank">https://learn.microsoft.com/ess/setup</a>' in html
    )


def test_bare_url_trailing_period_stays_outside_link() -> None:
    """"see https://aka.ms/x." must not swallow the period into href."""
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html("See https://aka.ms/ess-docs.")
    assert '<a href="https://aka.ms/ess-docs" target="_blank">' in html
    # The period renders as text after the closing tag, not inside href.
    assert "</a>." in html
    assert 'href="https://aka.ms/ess-docs."' not in html


def test_bare_url_trailing_paren_excluded() -> None:
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html("(details at https://aka.ms/ess)")
    assert '<a href="https://aka.ms/ess" target="_blank">' in html
    assert 'href="https://aka.ms/ess)"' not in html
    assert "</a>)" in html


def test_bare_url_with_query_string_is_html_safe() -> None:
    """`&` in a bare URL is escaped to `&amp;` and still linkified."""
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html("Go to https://host/x?a=1&b=2 now")
    assert '<a href="https://host/x?a=1&amp;b=2" target="_blank">' in html


# --- markdown links keep working (no double-wrap) -------------------------

def test_markdown_link_still_renders() -> None:
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html("Open the [admin center](https://admin.example.com).")
    assert '<a href="https://admin.example.com" target="_blank">admin center</a>' in html


def test_markdown_link_is_not_double_wrapped() -> None:
    """The URL inside a markdown anchor must not be linkified a 2nd time."""
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html("[docs](https://learn.microsoft.com/ess)")
    # Exactly one anchor; no nested <a> around the href value.
    assert html.count("<a ") == 1
    assert html.count("</a>") == 1
    assert '<a href="https://learn.microsoft.com/ess" target="_blank">docs</a>' == html


def test_mixed_markdown_and_bare_urls() -> None:
    from flightcheck.runner import _md_links_to_html

    html = _md_links_to_html(
        "First [portal](https://make.example.com), then https://aka.ms/x."
    )
    assert '<a href="https://make.example.com" target="_blank">portal</a>' in html
    assert '<a href="https://aka.ms/x" target="_blank">https://aka.ms/x</a>' in html
    assert html.count("<a ") == 2


def test_plain_text_without_urls_is_untouched_except_escaping() -> None:
    from flightcheck.runner import _md_links_to_html

    assert _md_links_to_html("no links here") == "no links here"
    # Angle brackets are still escaped (no accidental markup injection).
    assert _md_links_to_html("a < b") == "a &lt; b"


def test_multiline_html_linkifies_bare_url_and_keeps_breaks() -> None:
    from flightcheck.runner import _multiline_html

    html = _multiline_html("Step 1\nOpen https://aka.ms/ess")
    assert "<br>" in html
    assert '<a href="https://aka.ms/ess" target="_blank">' in html


# --- end-to-end through the check card renderers --------------------------

def test_manual_check_bare_url_renders_clickable() -> None:
    """MANUAL remediation with a bare URL must render a clickable link.

    This is the exact case behind the bug report: MANUAL rows route
    remediation through the checklist renderer, which used to leave bare
    URLs as plain text.
    """
    from flightcheck.runner import (
        CheckResult, Priority, Status, _render_check_card,
    )

    res = CheckResult(
        checkpoint_id="SN-SEC-001",
        category="ServiceNow",
        priority=Priority.HIGH.value,
        status=Status.MANUAL.value,
        description="Verify ServiceNow ACLs",
        result="Kit observed the OAuth app registration.",
        remediation="Confirm ACLs in ServiceNow: https://aka.ms/ess-servicenow-acl",
    )
    html = _render_check_card(res)
    assert '<a href="https://aka.ms/ess-servicenow-acl" target="_blank">' in html


def test_not_configured_check_bare_url_renders_clickable() -> None:
    """Non-MANUAL actionable rows (the 'Next step' path) also autolink."""
    from flightcheck.runner import (
        CheckResult, Priority, Status, _render_check_card,
    )

    res = CheckResult(
        checkpoint_id="ENV-099",
        category="Environment",
        priority=Priority.MEDIUM.value,
        status=Status.NOT_CONFIGURED.value,
        description="DLP policy review",
        result="No DLP policy applies.",
        remediation="Review policy at https://admin.powerplatform.microsoft.com/dlp/policies",
    )
    html = _render_check_card(res)
    assert (
        '<a href="https://admin.powerplatform.microsoft.com/dlp/policies" '
        'target="_blank">' in html
    )
