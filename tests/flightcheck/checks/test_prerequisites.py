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

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as gr
from tests.mocks import powerplatform as pp
from tests.mocks import azure_arm as arm

require_validated_mock(gr)
require_validated_mock(pp)
require_validated_mock(arm)

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


# ---------------------------------------------------------------------------
# PRE-005 — Pay-As-You-Go (PayG) configured if needed
#
# Heritage pass criterion: at least one billing model (PayG OR prepaid Copilot
# Studio message capacity). Prepaid is detected via Graph subscribedSkus, so
# tests that exercise the prepaid arm wire a real GraphClient + the validatable
# subscribedSkus builder; tests where prepaid is irrelevant pass graph=None
# (PRE-001..003/008/009 then degrade to WARNING without network). Every test
# asserts only the single PRE-005 row.
# ---------------------------------------------------------------------------

# A Copilot Studio message-bearing SKU (legacy PVA naming) — matches
# COPILOT_STUDIO_SKUS, so it signals "prepaid messages present".
PREPAID_SKU = "POWER_VIRTUAL_AGENTS"


def _pp_client():
    from flightcheck.powerplatform_client import PowerPlatformClient
    client = PowerPlatformClient("tenant")
    client._token = "REDACTED_TOKEN"  # noqa: S105 — test fixture
    return client


def _arm_client():
    from flightcheck.azure_arm_client import AzureArmClient
    client = AzureArmClient("tenant")
    client._token = "REDACTED_TOKEN"  # noqa: S105 — test fixture
    return client


def _graph_with_skus(*part_numbers):
    """Register a /subscribedSkus response and return a real GraphClient.

    Must be called inside an ``@responses.activate`` test. Pass no arguments
    to model a tenant with no Copilot Studio capacity (prepaid absent).
    """
    responses.add(**gr.list_subscribed_skus(skus=[
        gr.subscribed_sku(sku_part_number=p, consumed_units=1, enabled_units=1)
        for p in part_numbers
    ]))
    return _graph_client()


def _payg_runner(*, powerplatform, azure_arm=None, graph=None, env_id=pp.MOCK_ENV_ID):
    return SimpleNamespace(
        graph=graph, env_id=env_id,
        powerplatform=powerplatform, azure_arm=azure_arm,
    )


@responses.activate
def test_pre005_payg_plus_prepaid_passes():
    # PayG bound + healthy sub + spending guardrail -> PASS. The tenant also
    # holds prepaid capacity, but that is NOT cited in the PayG path (it does
    # not help this environment unless the tenant-draw overage is on), so the
    # result must stay focused on PayG and the budget.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(budgets=[arm.budget()]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert "spending guardrail" in r.result
    assert "prepaid" not in r.result.lower()
    assert "doesn't expose plan meters" in r.result
    assert runner._payg_configured is True


@responses.activate
def test_pre005_payg_plus_prepaid_no_guardrails_warns():
    # PayG linked + healthy sub but NO Azure spending budget -> WARN. Tenant
    # prepaid is present but must not appear in the result (misleading in the
    # PayG path).
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(budgets=[]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "no Azure spending budget" in r.result
    assert "prepaid" not in r.result.lower()
    assert "Hardening recommendation" in r.remediation
    assert runner._payg_configured is True


@responses.activate
def test_pre005_payg_budget_unverifiable_warns():
    # PayG linked + healthy sub, but the budget read is denied (no Cost
    # Management Reader) -> WARN. An uncapped PayG path with an unconfirmed
    # spending guardrail is a could-not-determine, not a silent PASS.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(status=403))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "could not verify" in r.result
    assert "Cost Management Reader" in r.remediation
    assert runner._payg_configured is True


@responses.activate
def test_pre005_multi_env_tenant_plan_wording():
    # Reproduces the real reported tenant: an org-wide plan linked to many
    # environments. The result must surface the breadth ("one of N
    # environments ... tenant-level") instead of implying per-env intent.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)
    other_envs = [
        pp.billing_policy_environment(environment_id=f"env-{i}") for i in range(14)
    ]
    linked = other_envs + [pp.billing_policy_environment()]  # 15 total, target last
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(name="ESSCopilotCapacity", status="Enabled",
                          subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=linked))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(budgets=[arm.budget()]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert "one of 15 environments" in r.result
    assert "tenant-level" in r.result


@responses.activate
def test_pre005_payg_only_bound_with_guardrails_passes():
    # AC6 "PayG-only-bound" PASS: PayG healthy, no prepaid, spending budget set.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(budgets=[arm.budget()]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert "guardrail" in r.result
    assert runner._payg_configured is True


@responses.activate
def test_pre005_policy_status_and_subscription_state_are_case_insensitive():
    # Both the billing-policy status and the Azure subscription state are
    # documented enum strings; FlightCheck must match them case-insensitively
    # so a casing change on the API side cannot silently flip the branch.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="ENABLED"))
    responses.add(**arm.list_budgets(budgets=[arm.budget()]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert runner._payg_configured is True


@responses.activate
def test_pre005_payg_only_no_guardrails_warns():
    # AC3: PayG is the only billing model AND no spending guardrails -> WARN.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(budgets=[]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "no Azure spending budget" in r.result
    assert "Hardening recommendation" in r.remediation
    assert runner._payg_configured is True


@responses.activate
def test_pre005_prepaid_only_passes():
    # AC4 / AC6 prepaid-only: no PayG plan linked, but this environment has
    # Copilot Studio message capacity allocated -> PASS (authoritative per-env).
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(allocations=[
        pp.currency_allocation(currency_type="MCSMessages", allocated=25000),
    ]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert "25000" in r.result
    assert "credits allocated" in r.result
    assert runner._payg_configured is False


@responses.activate
def test_pre005_env_zero_allocation_with_tenant_capacity_warns():
    # Zero per-env allocation + no PayG, but the tenant holds capacity. This is
    # not a hard fail: agents can draw from the tenant pool when "Draw from the
    # available capacity in my tenant" overage is enabled (a setting the API
    # does not expose) -> WARN.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)  # tenant has capacity
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(allocations=[
        pp.currency_allocation(currency_type="MCSMessages", allocated=0),
    ]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "no Copilot Studio message capacity is allocated" in r.result
    assert "drawing from the tenant pool" in r.result
    assert "Draw from the available capacity in my tenant" in r.result
    assert runner._payg_configured is False


@responses.activate
def test_pre005_env_zero_allocation_no_tenant_capacity_fails():
    # Zero per-env allocation AND no tenant capacity, no PayG -> FAIL (neither).
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(allocations=[]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Failed"
    assert "Neither" in r.result
    assert runner._payg_configured is False


@responses.activate
def test_pre005_allocation_unreadable_falls_back_to_tenant_prepaid():
    # Per-env allocation read denied -> fall back to the tenant-wide prepaid
    # signal: tenant has capacity -> soft PASS with a verify-allocation caveat.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(status=403))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert "could not read this environment's allocation" in r.result
    assert runner._payg_configured is False


@responses.activate
def test_pre005_neither_fails():
    # AC2 / AC6: neither PayG nor prepaid configured -> FAIL.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(status=404))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Failed"
    assert "Neither" in r.result
    assert runner._payg_configured is False


@responses.activate
def test_pre005_disabled_policy_is_ignored_then_neither_fails():
    # A Disabled policy linked to the env is filtered out; with no prepaid the
    # environment has no billing model -> FAIL.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Disabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.get_currency_allocations(status=404))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Failed"


@responses.activate
def test_pre005_bound_to_disabled_subscription_fails():
    # AC6: PayG bound to a Disabled subscription -> FAIL (prepaid irrelevant).
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Disabled"))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Failed"
    assert "Disabled" in r.result
    assert runner._payg_configured is False


@responses.activate
def test_pre005_could_not_determine_permission_denied_warns():
    # AC6 could-not-determine: Power Platform billing API 403 -> WARN.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(status=403))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "permission denied" in r.result.lower()


@responses.activate
def test_pre005_subscription_warned_is_warning():
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Warned"))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "Warned" in r.result


@responses.activate
def test_pre005_azure_subscription_unverifiable_is_warning():
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(status=403))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "could not be verified" in r.result


@responses.activate
def test_pre005_azure_client_unavailable_is_warning():
    # PayG linked but no Azure client -> health unverifiable -> WARN, not PASS.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=None, graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "could not be verified" in r.result


@responses.activate
def test_pre005_linked_policy_without_subscription_is_warning():
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=None),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "no Azure subscription bound" in r.result


@responses.activate
def test_pre005_no_payg_prepaid_unknown_is_warning():
    # No PayG linked and Graph unavailable (prepaid unknown) -> WARN, not FAIL.
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    responses.add(**pp.list_billing_policies(policies=[]))

    runner = _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Warning"
    assert "could not be determined" in r.result


@responses.activate
def test_pre005_pp_unavailable_but_prepaid_present_passes():
    # No Power Platform client, but prepaid present -> PASS (prepaid arm).
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    graph = _graph_with_skus(PREPAID_SKU)

    runner = _payg_runner(powerplatform=None, azure_arm=None, graph=graph)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Passed"
    assert runner._payg_configured is False


def test_pre005_skipped_when_pp_unavailable_and_no_prepaid():
    from flightcheck.checks.prerequisites import run_prerequisites_checks

    runner = _payg_runner(powerplatform=None, azure_arm=None, graph=None)
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == "Skipped"
    assert runner._payg_configured is False


def _setup_pre005_pass():
    graph = _graph_with_skus(PREPAID_SKU)
    responses.add(**pp.list_billing_policies(policies=[
        pp.billing_policy(status="Enabled", subscription_id=pp.MOCK_SUBSCRIPTION_ID),
    ]))
    responses.add(**pp.list_policy_environments(
        policy_id=pp.MOCK_POLICY_ID, environments=[pp.billing_policy_environment()]))
    responses.add(**arm.get_subscription(state="Enabled"))
    responses.add(**arm.list_budgets(budgets=[arm.budget()]))
    return _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)


def _setup_pre005_warn():
    graph = _graph_with_skus(PREPAID_SKU)  # tenant has capacity
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(allocations=[
        pp.currency_allocation(currency_type="MCSMessages", allocated=0),
    ]))
    return _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)


def _setup_pre005_fail():
    graph = _graph_with_skus()  # prepaid absent
    responses.add(**pp.list_billing_policies(policies=[]))
    responses.add(**pp.get_currency_allocations(allocations=[]))
    return _payg_runner(powerplatform=_pp_client(), azure_arm=_arm_client(), graph=graph)


@pytest.mark.parametrize("setup, expected_status", [
    (_setup_pre005_pass, "Passed"),
    (_setup_pre005_warn, "Warning"),
    (_setup_pre005_fail, "Failed"),
])
@responses.activate
def test_pre005_result_schema_and_owning_role(setup, expected_status):
    # AC5 contract: every PRE-005 row carries the shared-step schema
    # (status / description / result / remediation) and is addressed to the
    # Power Platform admin. remediation is intentionally empty on PASS rows
    # (no action needed) and populated on WARN/FAIL. Assert this explicitly so
    # a future refactor cannot silently drop a field or the owning role.
    from flightcheck.checks.prerequisites import run_prerequisites_checks
    from flightcheck.runner import Role

    runner = setup()
    r = _by_id(run_prerequisites_checks(runner), "PRE-005")

    assert r.status == expected_status
    assert isinstance(r.description, str) and r.description
    assert isinstance(r.result, str) and r.result
    assert isinstance(r.remediation, str)
    assert (r.remediation == "") is (expected_status == "Passed")
    assert r.roles == [Role.POWER_PLATFORM_ADMIN.value]
    assert r.doc_link

