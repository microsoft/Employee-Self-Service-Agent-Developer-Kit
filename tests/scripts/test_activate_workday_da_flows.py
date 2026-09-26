# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for deterministic Workday DA cloud-flow activation."""

from __future__ import annotations

from copy import deepcopy

import pytest


FLOW_NAMES = [
    "ESS Workday Runtime References",
    "ESS Workday Runtime REST Execution",
    "ESS Workday Runtime",
]


def _definition() -> dict:
    return {
        "packages": {
            "runtime": {
                "flowNames": FLOW_NAMES,
            },
            "legacy-da": {},
        }
    }


def _reference(logical_name: str, connection_id: str | None) -> dict:
    return {
        "connectionreferencelogicalname": logical_name,
        "connectionreferenceid": logical_name,
        "connectionid": connection_id,
    }


def _flow(name: str, index: int, *, active: bool = False) -> dict:
    return {
        "workflowid": f"00000000-0000-0000-0000-{index:012d}",
        "name": name,
        "statecode": 1 if active else 0,
        "statuscode": 2 if active else 1,
        "category": 5,
    }


def _query(module, flows: list[dict], *, bound: bool = True):
    references = [
        _reference(
            module.WORKDAY_LOGICAL_NAME,
            "workday-connection" if bound else None,
        ),
        _reference(
            module.DATAVERSE_LOGICAL_NAME,
            "dataverse-connection" if bound else None,
        ),
    ]

    def query(_url, _token, entity_set, _select, _filter):
        if entity_set == "connectionreferences":
            return deepcopy(references)
        if entity_set == "workflows":
            return deepcopy(flows)
        raise AssertionError(f"Unexpected entity set: {entity_set}")

    return query


def test_preview_lists_reviewed_flows_without_mutating() -> None:
    import activate_workday_da_flows as module

    flows = [_flow(name, index) for index, name in enumerate(FLOW_NAMES, 1)]
    updates = []
    result = module.activate_workday_flows(
        "https://org.crm.dynamics.com",
        "runtime",
        apply=False,
        definition=_definition(),
        token_provider=lambda *args, **kwargs: "token",
        query=_query(module, flows),
        updater=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert result["mode"] == "preview"
    assert [change["name"] for change in result["changes"]] == FLOW_NAMES
    assert all(change["action"] == "activate" for change in result["changes"])
    assert updates == []


def test_apply_activates_draft_flows_and_reverifies() -> None:
    import activate_workday_da_flows as module

    flows = [_flow(FLOW_NAMES[0], 1, active=True)] + [
        _flow(name, index)
        for index, name in enumerate(FLOW_NAMES[1:], 2)
    ]
    updates = []

    def update(_url, _token, entity_set, record_id, data):
        assert entity_set == "workflows"
        updates.append(record_id)
        for flow in flows:
            if flow["workflowid"] == record_id:
                flow.update(data)
                return True
        raise AssertionError(f"Unknown workflow: {record_id}")

    result = module.activate_workday_flows(
        "https://org.crm.dynamics.com/",
        "runtime",
        apply=True,
        preferred_username="maker@example.com",
        definition=_definition(),
        token_provider=lambda *args, **kwargs: "token",
        query=_query(module, flows),
        updater=update,
    )

    assert result["verified"] is True
    assert len(updates) == 2
    assert all(
        flow["statecode"] == 1 and flow["statuscode"] == 2
        for flow in flows
    )


def test_apply_is_idempotent_when_all_flows_are_active() -> None:
    import activate_workday_da_flows as module

    flows = [
        _flow(name, index, active=True)
        for index, name in enumerate(FLOW_NAMES, 1)
    ]
    updates = []
    result = module.activate_workday_flows(
        "https://org.crm.dynamics.com",
        "runtime",
        apply=True,
        definition=_definition(),
        token_provider=lambda *args, **kwargs: "token",
        query=_query(module, flows),
        updater=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert result["verified"] is True
    assert all(change["action"] == "unchanged" for change in result["changes"])
    assert updates == []


def test_unbound_runtime_reference_fails_closed() -> None:
    import activate_workday_da_flows as module

    flows = [_flow(name, index) for index, name in enumerate(FLOW_NAMES, 1)]
    with pytest.raises(
        module.WorkdayDAFlowActivationError,
        match="must be bound before flow activation",
    ):
        module.activate_workday_flows(
            "https://org.crm.dynamics.com",
            "runtime",
            apply=False,
            definition=_definition(),
            token_provider=lambda *args, **kwargs: "token",
            query=_query(module, flows, bound=False),
        )


def test_duplicate_or_non_cloud_flow_fails_closed() -> None:
    import activate_workday_da_flows as module

    duplicate = [_flow(name, index) for index, name in enumerate(FLOW_NAMES, 1)]
    duplicate.append(_flow(FLOW_NAMES[0], 99))
    with pytest.raises(
        module.WorkdayDAFlowActivationError,
        match="Expected exactly one installed Workday flow",
    ):
        module.activate_workday_flows(
            "https://org.crm.dynamics.com",
            "runtime",
            apply=False,
            definition=_definition(),
            token_provider=lambda *args, **kwargs: "token",
            query=_query(module, duplicate),
        )

    non_cloud = [
        _flow(name, index)
        for index, name in enumerate(FLOW_NAMES, 1)
    ]
    non_cloud[0]["category"] = 0
    with pytest.raises(
        module.WorkdayDAFlowActivationError,
        match="Refusing to activate non-cloud workflow",
    ):
        module.activate_workday_flows(
            "https://org.crm.dynamics.com",
            "runtime",
            apply=False,
            definition=_definition(),
            token_provider=lambda *args, **kwargs: "token",
            query=_query(module, non_cloud),
        )


def test_package_without_reviewed_flow_catalog_requires_manual_activation() -> None:
    import activate_workday_da_flows as module

    with pytest.raises(
        module.WorkdayDAFlowActivationError,
        match="has no reviewed flow catalog",
    ):
        module.activate_workday_flows(
            "https://org.crm.dynamics.com",
            "legacy-da",
            apply=False,
            definition=_definition(),
            token_provider=lambda *args, **kwargs: "token",
        )
