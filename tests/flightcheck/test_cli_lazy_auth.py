# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for the cli.py lazy-auth scope gate.

The FlightCheck CLI authenticates to Dataverse / Graph / Power Platform
Admin before any check function runs. This is expensive (interactive
MSAL prompt) AND wrong for scopes that don't need Microsoft auth —
notably ``--scope network`` and the ``--export-firewall-requirements``
standalone mode.

``_requires_microsoft_auth(scope)`` is the single source of truth for
which scopes need the heavy auth path. These tests pin its current
behavior so a future scope addition can't silently regress the no-auth
path. If a new scope is added, either:

  * Add it to ``_NO_MS_AUTH_SCOPES`` and pin a ``False`` assertion here, or
  * Leave it auth-required (default) and pin a ``True`` assertion here.

Whichever it is — pin it. Don't let the question be implicit.
"""

from __future__ import annotations

import pytest

from flightcheck.cli import _NO_MS_AUTH_SCOPES, SCOPE_MAP, _requires_microsoft_auth


# ---------------------------------------------------------------------------
# Per-scope assertions — one per known scope key.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["full", "prerequisites", "environment",
                                    "authentication", "external", "workday",
                                    "local", "publishing"])
def test_auth_required_scopes(scope: str) -> None:
    """These scopes hit Microsoft APIs (Dataverse, Graph, PP Admin, PVA)."""
    assert _requires_microsoft_auth(scope) is True, (
        f"--scope {scope} should require Microsoft auth but the helper said no"
    )


def test_network_scope_does_not_require_microsoft_auth() -> None:
    """``--scope network`` is the original motivation for the lazy-auth gate.

    Vendor TCP/HTTPS reachability probing has no Microsoft API surface, so
    Dataverse / Graph / PP Admin auth would be both wasteful and a
    user-experience regression (interactive MSAL prompt before a probe
    that doesn't need it). Pin this hard.
    """
    assert _requires_microsoft_auth("network") is False


# ---------------------------------------------------------------------------
# Guard against silent regressions: every scope key must be classified.
# ---------------------------------------------------------------------------


def test_every_scope_key_is_classified() -> None:
    """If a new scope gets added to ``SCOPE_MAP``, this test fails until
    the author decides whether the new scope is auth-required and updates
    either the parametrize list above or ``_NO_MS_AUTH_SCOPES``.
    """
    auth_required = {"full", "prerequisites", "environment", "authentication",
                     "external", "workday", "local", "publishing"}
    classified = auth_required | set(_NO_MS_AUTH_SCOPES)

    all_scopes = {"full"} | set(SCOPE_MAP.keys())
    unclassified = all_scopes - classified
    assert not unclassified, (
        f"Scope(s) {unclassified} are in SCOPE_MAP but not classified in this test. "
        "Decide whether each needs Microsoft auth and update _NO_MS_AUTH_SCOPES or the "
        "auth_required set above."
    )


def test_no_ms_auth_scopes_subset_of_known() -> None:
    """``_NO_MS_AUTH_SCOPES`` should only name scopes that actually exist."""
    all_scopes = {"full"} | set(SCOPE_MAP.keys())
    stray = set(_NO_MS_AUTH_SCOPES) - all_scopes
    assert not stray, (
        f"_NO_MS_AUTH_SCOPES has {stray} that aren't in SCOPE_MAP. Remove them."
    )
