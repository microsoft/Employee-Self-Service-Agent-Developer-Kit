# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for the prerequisites checks (PRE-001 Copilot
licenses, PRE-002 Copilot Studio licenses, PRE-003 Teams licenses,
PRE-008 Global Admin role, PRE-009 Power Platform Admin role).

Uses a real ``GraphClient`` with a fake token, mocking the Graph
``/subscribedSkus``, ``/directoryRoles`` and ``/directoryRoles/{id}/
members`` endpoints via the validatable ``graph`` mock builders.
"""

from __future__ import annotations

from types import SimpleNamespace

import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as gr

require_validated_mock(gr)

_GA_ID = "00000000-0000-0000-0000-0000000051a1"
_PP_ID = "00000000-0000-0000-0000-0000000051b2"


def _graph_client():
    from flightcheck.graph_client import GraphClient
    client = GraphClient(gr.MOCK_TENANT_ID)
    client._token = "REDACTED_TOKEN"  # noqa: S105 — test fixture
    return client


def _by_id(results, cid):
    matches = [r for r in results if r.checkpoint_id == cid]
    assert len(matches) == 1, [r.checkpoint_id for r in results]
    return matches[0]


@responses.activate
def test_all_prerequisites_pass():
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**gr.list_subscribed_skus(skus=[
        gr.subscribed_sku(sku_part_number="MICROSOFT_365_COPILOT",
                          consumed_units=5, enabled_units=10),
        gr.subscribed_sku(sku_part_number="ENTERPRISEPACK",  # Teams-bearing (O365 E3)
                          consumed_units=50, enabled_units=100),
    ]))
    responses.add(**gr.list_directory_roles(roles=[
        gr.directory_role(role_id=_GA_ID, display_name="Global Administrator"),
        gr.directory_role(role_id=_PP_ID, display_name="Power Platform Administrator"),
    ]))
    responses.add(**gr.list_role_members(role_id=_GA_ID, members=[gr.user()]))
    responses.add(**gr.list_role_members(role_id=_PP_ID, members=[gr.user()]))

    results = run_prerequisites_checks(SimpleNamespace(graph=_graph_client()))

    assert _by_id(results, "PRE-001").status == "Passed"
    assert _by_id(results, "PRE-002").status == "Passed"   # bundle covers Studio
    pre003 = _by_id(results, "PRE-003")
    assert pre003.status == "Passed"
    assert "50 users licensed for Teams" in pre003.result
    assert _by_id(results, "PRE-008").status == "Passed"
    assert _by_id(results, "PRE-009").status == "Passed"


@responses.activate
def test_missing_licenses_and_roles():
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**gr.list_subscribed_skus(skus=[]))
    responses.add(**gr.list_directory_roles(roles=[]))

    results = run_prerequisites_checks(SimpleNamespace(graph=_graph_client()))

    pre001 = _by_id(results, "PRE-001")
    assert pre001.status == "Failed"
    assert "No M365 Copilot licenses" in pre001.result

    assert _by_id(results, "PRE-002").status == "Failed"
    assert _by_id(results, "PRE-003").status == "Warning"

    pre008 = _by_id(results, "PRE-008")
    assert pre008.status == "Failed"
    assert "Global Administrator role not found" in pre008.result

    assert _by_id(results, "PRE-009").status == "Warning"
