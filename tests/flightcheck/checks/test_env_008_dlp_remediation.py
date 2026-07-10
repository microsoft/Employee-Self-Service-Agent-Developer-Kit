# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ENV-008 (DLP policies) remediation text.

The original remediation was a one-liner pointing at the PP admin center
homepage with a vague "ensure connectors are allowlisted" — operators
reported they had no idea what concrete steps to take. These tests pin
the actionable remediation prose now produced for each ENV-008 path:

  * Warning (no DLP policies cover this env) — walks the operator
    through scoping a policy, the same-group constraint, and the
    "no-action-needed if DLP isn't enforced" exit.
  * Warning (permission/API failure) — names the role required and
    deep-links to the policies page so a tenant admin can review.

These tests intentionally assert on the *substance* of the remediation
(URL, role name, key concepts like 'same group', 'Blocked') rather than
exact wording, so harmless prose tweaks don't churn them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
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


_ADMIN_URL = "https://admin.powerplatform.microsoft.com/"
_NAV_PATH = "Security \u2192 Data and privacy \u2192 Data policy"


class _FakePPAdmin:
    """Minimal PP Admin stub exposing only the methods environment
    checks call. Each method takes a callable so tests can simulate
    success or raise."""

    def __init__(
        self,
        *,
        env_props: dict | None = None,
        dlp_policies=None,
        dlp_raises: Exception | None = None,
    ):
        self._env_props = env_props if env_props is not None else {
            "displayName": "Test Env",
            "linkedEnvironmentMetadata": {"resourceProvisioningState": "Succeeded"},
            "databaseType": "CommonDataService",
            "environmentSku": "Production",
        }
        self._dlp_policies = dlp_policies if dlp_policies is not None else []
        self._dlp_raises = dlp_raises

    def get_environment(self, _env_id):
        return {"properties": self._env_props}

    def get_dlp_policies_for_env(self, _env_id):
        if self._dlp_raises:
            raise self._dlp_raises
        return self._dlp_policies

    def get_connections(self, _env_id):
        # ENV-004 also runs as part of run_environment_checks; return
        # an empty list so it produces a clean PASSED row and doesn't
        # interfere with ENV-008 assertions.
        return []


def _make_runner(pp_admin):
    return SimpleNamespace(
        pp_admin=pp_admin,
        env_id="env-deeplinks",
        env_url="https://example.crm.dynamics.com",
        dv_token="fake-token",
    )


def _get_env_008(results):
    """ENV-004 emits a summary row too — filter precisely to ENV-008."""
    return next(r for r in results if r.checkpoint_id == "ENV-008")


# ---------------------------------------------------------------------------
# Warning path: no DLP policies cover this environment.
# ---------------------------------------------------------------------------


def test_env_008_no_policies_remediation_links_to_admin_center(monkeypatch):
    """The remediation must link to the admin center root + spell out
    the **Security \u2192 Data and privacy \u2192 Data policy** nav path
    explicitly. We deliberately do NOT deep-link to a sub-path like
    /policies or /dlp because Microsoft does not publish a stable
    public URL for those routes (they 404 outside the SPA shell), and
    Microsoft's own docs walk users through the same nav path from the
    root."""
    from flightcheck.checks import environment as env_mod

    # Suppress the connection-ref Dataverse query that runs as part of
    # the same check function.
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])

    runner = _make_runner(_FakePPAdmin(dlp_policies=[]))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    assert env008.status == "Warning"
    rem = env008.remediation or ""
    assert _ADMIN_URL in rem, rem
    # Must NOT use any of the URL paths we've previously tried that
    # turned out to 404; pin them so the link doesn't regress.
    for broken in ("/policies", "/dlp", "/datapolicies"):
        assert _ADMIN_URL + broken.lstrip("/") not in rem, rem
    # And the nav path must be there so the operator knows where to go
    # after the link drops them on the admin center home.
    assert _NAV_PATH in rem, rem


def test_env_008_no_policies_remediation_names_same_group_constraint(monkeypatch):
    """'Allowlisting' in DLP terms means putting every connector the
    agent uses in the SAME group (Business or Non-Business) — connectors
    in different groups cannot be combined in a single flow or agent
    action. That's the constraint operators most often miss, so it must
    be spelled out in the remediation."""
    from flightcheck.checks import environment as env_mod

    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])
    runner = _make_runner(_FakePPAdmin(dlp_policies=[]))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    rem = env008.remediation or ""
    assert "same" in rem.lower(), rem
    # Both group names should appear so the operator knows what to pick.
    assert "Business" in rem, rem
    assert "Non-Business" in rem, rem
    # And the Blocked group must be called out — putting a needed
    # connector there is the other common misconfiguration.
    assert "Blocked" in rem, rem


def test_env_008_no_policies_remediation_explains_scoping_to_environment(monkeypatch):
    """A DLP policy only takes effect on an env if that env is in the
    policy's Environments scope. Operators frequently miss this and
    create a policy that does nothing for the env in question."""
    from flightcheck.checks import environment as env_mod

    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])
    runner = _make_runner(_FakePPAdmin(dlp_policies=[]))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    rem = env008.remediation or ""
    # Must mention that the policy must include this environment.
    assert "Environments" in rem or "environment" in rem.lower(), rem
    assert "scope" in rem.lower() or "include" in rem.lower(), rem


def test_env_008_no_policies_remediation_acknowledges_no_dlp_is_valid(monkeypatch):
    """Many tenants intentionally don't enforce DLP, especially in dev.
    The remediation must give those operators an explicit 'no action
    required' exit so they don't waste time chasing a non-issue."""
    from flightcheck.checks import environment as env_mod

    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])
    runner = _make_runner(_FakePPAdmin(dlp_policies=[]))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    rem = env008.remediation or ""
    assert "no action" in rem.lower(), rem


# ---------------------------------------------------------------------------
# Passed path: at least one policy covers the environment.
# ---------------------------------------------------------------------------


def test_env_008_with_policies_passes_with_validated_note(monkeypatch):
    """When at least one DLP policy applies, ENV-008 passes and its
    remediation describes what was validated."""
    from flightcheck.checks import environment as env_mod

    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])
    runner = _make_runner(_FakePPAdmin(dlp_policies=[{"policyDefinition": {}}]))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    assert env008.status == "Passed"
    assert env008.remediation.startswith("Validated:")
    assert "DLP" in env008.remediation


# ---------------------------------------------------------------------------
# Warning path: API/permission failure.
# ---------------------------------------------------------------------------


def test_env_008_permission_error_remediation_names_role_and_links(monkeypatch):
    """When the DLP query fails (typically because the caller lacks
    PP Administrator), the remediation must name the exact role required
    AND link to the policies page so a tenant admin can review without
    extra back-and-forth."""
    from flightcheck.checks import environment as env_mod

    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])
    runner = _make_runner(_FakePPAdmin(dlp_raises=RuntimeError("403 Forbidden")))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    assert env008.status == "Warning"
    rem = env008.remediation or ""
    assert "Power Platform Administrator" in rem, rem
    assert _ADMIN_URL in rem, rem
    assert _NAV_PATH in rem, rem
    for broken in ("/policies", "/dlp", "/datapolicies"):
        assert _ADMIN_URL + broken.lstrip("/") not in rem, rem


def test_env_008_skips_when_apipolicies_returns_permission_error(monkeypatch):
    """When the apiPolicies admin endpoint returns 401/403, the client
    surfaces a structured ``{"_error": ...}`` dict. ENV-008 must report
    this as a SKIP ("requires Power Platform Administrator") rather than
    a false "No DLP policies found" — the kit must not claim the
    environment is unrestricted when it could not actually read DLP."""
    from flightcheck.checks import environment as env_mod

    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])
    runner = _make_runner(_FakePPAdmin(
        dlp_policies={"_error": "insufficient_permissions", "_status": 403},
    ))
    results = env_mod.run_environment_checks(runner)
    env008 = _get_env_008(results)

    assert env008.status == "Skipped"
    assert "permissions error" in env008.result
    assert "No DLP policies found" not in env008.result  # no false "all clear"
    assert "Power Platform Administrator" in env008.remediation
