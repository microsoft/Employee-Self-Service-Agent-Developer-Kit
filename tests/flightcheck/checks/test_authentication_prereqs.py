# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the tenant-prerequisite authentication checks that
lacked coverage: AUTH-001 (Entra ID configured), AUTH-002 (Conditional
Access policies), AUTH-004 (user identity synchronization).

The Workday-app sub-checks (AUTH-005/006) are covered by
``test_authentication.py`` / ``test_authentication_saml.py``; here a fake
Graph client returns no service principals so those sub-checks no-op
while AUTH-001/002/004 are exercised. Data shapes come from the
validatable ``graph`` mock builders.
"""

from __future__ import annotations

from types import SimpleNamespace


from tests.conftest import require_validated_mock
from tests.mocks import graph as gr

require_validated_mock(gr)


class _FakeGraph:
    """Returns canned (validatable-builder-shaped) responses for the
    Graph methods the authentication checks call. Service-principal
    methods return empty so AUTH-005/006 short-circuit."""

    def __init__(self, *, org=None, policies=None, users=None):
        self._org = org
        self._policies = policies if policies is not None else []
        self._users = users if users is not None else []

    def get_organization(self):
        return self._org

    def get_conditional_access_policies(self):
        return self._policies

    def get_users_sample(self, top: int = 10):
        return self._users

    def get_service_principals(self, *a, **kw):
        return []

    def get_application_templates(self, *a, **kw):
        return []

    def get_app_role_assignments(self, *a, **kw):
        return []

    def get_claims_mapping_policies(self, *a, **kw):
        return []

    def get(self, *a, **kw):
        return {}


def _run(graph):
    from flightcheck.checks.authentication import run_authentication_checks
    return run_authentication_checks(SimpleNamespace(graph=graph))


def _by_id(results, cid):
    matches = [r for r in results if r.checkpoint_id == cid]
    assert len(matches) == 1, [r.checkpoint_id for r in results]
    return matches[0]


def test_auth_001_002_004_pass():
    graph = _FakeGraph(
        org=gr.organization(display_name="Contoso"),
        policies=[gr.conditional_access_policy(state="enabled")],
        users=[gr.user(), gr.user(user_id="u2")],
    )
    results = _run(graph)

    auth001 = _by_id(results, "AUTH-001")
    assert auth001.status == "Passed"
    assert "Contoso" in auth001.result

    auth002 = _by_id(results, "AUTH-002")
    assert auth002.status == "Passed"
    assert "1 enabled" in auth002.result

    auth004 = _by_id(results, "AUTH-004")
    assert auth004.status == "Passed"
    assert "2 sample users" in auth004.result


def test_auth_001_fails_without_org():
    auth001 = _by_id(_run(_FakeGraph(org=None)), "AUTH-001")
    assert auth001.status == "Failed"
    assert "Unable to retrieve organization info" in auth001.result
    assert "Entra ID is properly configured" in auth001.remediation


def test_auth_002_warns_without_policies():
    auth002 = _by_id(_run(_FakeGraph(org=gr.organization(), policies=[])), "AUTH-002")
    assert auth002.status == "Warning"
    assert "No Conditional Access policies" in auth002.result


def test_auth_004_fails_without_users():
    auth004 = _by_id(_run(_FakeGraph(org=gr.organization(), users=[])), "AUTH-004")
    assert auth004.status == "Failed"
    assert "No users found in Entra ID" in auth004.result
