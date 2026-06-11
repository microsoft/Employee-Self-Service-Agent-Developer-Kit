# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the Cloud Policies / feedback checks (POL-FB-001 / POL-FB-002).

These checkpoints are ``Status.MANUAL``: the Office Cloud Policy Service has
no supported programmatic API for reading effective per-security-group
feedback policy state (no GA Graph endpoint; the admin-center backend rejects
a service-acquired bearer at the WAF). So FlightCheck surfaces the policies to
verify, the portal deep link, the role-aware deployment directive, and the
verbatim data-sharing notice, then defers the comparison to the operator —
mirroring the publishing checklist.

There is no external API call here, so these are pure-logic tests (no
cassette). The notice wording is mandated verbatim by the acceptance criteria
so customers can lift it into their privacy documentation; the exact substring
assertions are intentional and must not be loosened.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def _results_by_id() -> dict:
    from flightcheck.checks.cloud_policy import run_cloud_policy_checks

    runner = SimpleNamespace(config={})
    return {r.checkpoint_id: r for r in run_cloud_policy_checks(runner)}


# --------------------------------------------------------------------------
# Constants / pure helpers
# --------------------------------------------------------------------------


def test_checkpoint_and_category_constants():
    from flightcheck.checks import cloud_policy as cp

    assert cp.POL_FB_FEEDBACK == "POL-FB-001"
    assert cp.POL_FB_ATTACHMENTS == "POL-FB-002"
    assert cp.CATEGORY == "Cloud Policies / Telemetry & Feedback"


def test_policy_display_names_are_verbatim():
    from flightcheck.checks import cloud_policy as cp

    assert cp.POLICY_NAME_FEEDBACK == (
        "Allow users to send feedback to Microsoft about Microsoft 365 apps"
    )
    assert cp.POLICY_NAME_ATTACHMENTS == (
        "Allow users to include screenshots and attachments when they submit "
        "feedback to Microsoft"
    )


def test_maker_notice_is_verbatim():
    from flightcheck.checks import cloud_policy as cp

    assert cp.MAKER_NOTICE == (
        "End-user feedback collected from Copilot responses in this "
        "deployment \u2014 including any verbatim text, screenshots, and "
        "attachments the end user chooses to include \u2014 will be shared "
        "with Microsoft for product-quality and support improvement "
        "purposes. Confirm that your organization's privacy notice and "
        "end-user training cover this data flow before launch."
    )
    assert "will be shared with Microsoft" in cp.MAKER_NOTICE
    assert "product-quality and support improvement purposes" in cp.MAKER_NOTICE
    assert "privacy notice" in cp.MAKER_NOTICE


def test_render_directive_has_three_sections_in_order():
    from flightcheck.checks import cloud_policy as cp

    out = cp.render_directive(
        how_to_verify="open the admin center and confirm the setting.",
        scope_confidence="IT admin scope.",
        still_stuck="contact your tenant admin.",
    )
    # Leads with How to verify (not a 'probable cause' for an unseen symptom).
    assert out.startswith("**How to verify**")
    assert (
        out.index("How to verify")
        < out.index("Scope + confidence")
        < out.index("Still stuck?")
    )
    assert "Probable cause" not in out
    assert "Data-sharing notice" not in out


def test_render_directive_appends_notice_when_supplied():
    from flightcheck.checks import cloud_policy as cp

    out = cp.render_directive(
        how_to_verify="v",
        scope_confidence="s",
        still_stuck="ss",
        notice=cp.MAKER_NOTICE,
    )
    assert "**Data-sharing notice** \u2014 End-user feedback collected" in out
    assert out.rstrip().endswith("cover this data flow before launch.")


# --------------------------------------------------------------------------
# Check behavior — both checkpoints are MANUAL, HIGH, in the right category
# --------------------------------------------------------------------------


def test_emits_both_checkpoints():
    by_id = _results_by_id()
    assert set(by_id) == {"POL-FB-001", "POL-FB-002"}


def test_both_are_manual_high_and_correctly_categorized():
    for r in _results_by_id().values():
        assert r.status == "Manual"  # never fails readiness
        assert r.priority == "High"
        assert r.category == "Cloud Policies / Telemetry & Feedback"


def test_feedback_checkpoint_explains_why_and_how_with_notice():
    r = _results_by_id()["POL-FB-001"]
    # result = WHY it's worth verifying (impact + silent failure), no fix prose.
    assert "primary closed-loop quality signal" in r.result
    assert "no error" in r.result and "no log entry" in r.result
    assert "How to verify" not in r.result  # steps live in remediation
    # remediation = HOW to verify (leads with verification steps, not a cause).
    assert r.remediation.startswith("**How to verify**")
    assert "Probable cause" not in r.remediation
    assert "**Scope + confidence**" in r.remediation
    assert "**Still stuck?**" in r.remediation
    # names the exact policy display name...
    assert (
        "Allow users to send feedback to Microsoft about Microsoft 365 apps"
        in r.remediation
    )
    # ...IT-admin scope framing...
    assert "IT admin scope" in r.remediation
    # ...the portal deep link...
    assert "config.office.com" in r.remediation
    # ...and the verbatim data-sharing notice.
    assert "will be shared with Microsoft for product-quality" in r.remediation
    assert "privacy notice and end-user training" in r.remediation
    # Verified doc link, not fabricated.
    assert r.doc_link == (
        "https://learn.microsoft.com/en-us/microsoft-365-apps/admin-center/"
        "overview-cloud-policy"
    )


def test_attachments_checkpoint_explains_fidelity_why_and_how():
    r = _results_by_id()["POL-FB-002"]
    # result = WHY (fidelity rationale), framed as not a blocker.
    assert "diagnostic fidelity" in r.result
    assert "lower-fidelity" in r.result
    assert "not a feedback blocker" in r.result
    # remediation = HOW to verify.
    assert r.remediation.startswith("**How to verify**")
    assert (
        "Allow users to include screenshots and attachments when they submit "
        "feedback to Microsoft"
        in r.remediation
    )
    assert "config.office.com" in r.remediation


def test_attachments_does_not_duplicate_data_sharing_notice():
    # The verbatim MAKER_NOTICE belongs to POL-FB-001 only (POL-FB-002's
    # "Still stuck?" points back to it). Pin the absence so a future edit that
    # passes notice= to POL-FB-002's render_directive can't silently duplicate
    # the compliance string across two rows.
    r = _results_by_id()["POL-FB-002"]
    assert "Data-sharing notice" not in r.remediation
    assert "will be shared with Microsoft" not in r.remediation
