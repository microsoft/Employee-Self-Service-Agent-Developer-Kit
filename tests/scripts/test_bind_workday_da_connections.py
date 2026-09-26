# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for deterministic Workday DA runtime connection binding."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _connection(name: str, connector: str, *, connected: bool = True) -> dict:
    return {
        "name": name,
        "properties": {
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector}",
            "displayName": connector,
            "statuses": [
                {"status": "Connected" if connected else "Error"}
            ],
        },
    }


def _reference(
    record_id: str,
    logical_name: str,
    connection_id: str | None = None,
) -> dict:
    return {
        "connectionreferenceid": record_id,
        "connectionreferencelogicalname": logical_name,
        "connectionreferencedisplayname": logical_name,
        "connectionid": connection_id,
        "statuscode": 1,
    }


def _pac_runner(connections: list[dict]):
    def runner(command, *, timeout):
        assert command[1:4] == [
            "connectivity",
            "list-connections",
            "--environment",
        ]
        assert command[-1] == "--json"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"value": connections}),
            stderr="",
        )

    return runner


def _references(module, bindings: dict[str, str | None]) -> list[dict]:
    return [
        _reference("workday-ref", module.WORKDAY_LOGICAL_NAME, bindings["wd"]),
        _reference(
            "dataverse-ref",
            module.DATAVERSE_LOGICAL_NAME,
            bindings["dv"],
        ),
    ]


def test_preview_reports_both_required_bindings_without_mutating() -> None:
    import bind_workday_da_connections as module

    bindings = {"wd": None, "dv": None}
    updates = []
    result = module.bind_runtime_connections(
        "https://org.crm.dynamics.com",
        ring="prod",
        apply=False,
        pac_resolver=lambda: Path("pac.exe"),
        pac_auth=lambda *args, **kwargs: None,
        runner=_pac_runner(
            [
                _connection("wd-connection", module.WORKDAY_CONNECTOR),
                _connection("dv-connection", module.DATAVERSE_CONNECTOR),
            ]
        ),
        token_provider=lambda *args, **kwargs: "token",
        query=lambda *args, **kwargs: _references(module, bindings),
        updater=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert result["mode"] == "preview"
    assert [change["action"] for change in result["changes"]] == [
        "bind",
        "bind",
    ]
    assert updates == []


def test_apply_updates_and_reverifies_both_references() -> None:
    import bind_workday_da_connections as module

    bindings = {"wd": None, "dv": None}
    pac_auth_calls = []

    def update(_url, _token, _entity, record_id, data):
        bindings["wd" if record_id == "workday-ref" else "dv"] = data[
            "connectionid"
        ]
        return True

    result = module.bind_runtime_connections(
        "https://org.crm10.dynamics.com/",
        ring="preprod",
        apply=True,
        preferred_username="maker@example.com",
        pac_resolver=lambda: Path("pac.exe"),
        pac_auth=lambda *args, **kwargs: pac_auth_calls.append(
            (args, kwargs)
        ),
        runner=_pac_runner(
            [
                _connection("wd-connection", module.WORKDAY_CONNECTOR),
                _connection("dv-connection", module.DATAVERSE_CONNECTOR),
            ]
        ),
        token_provider=lambda *args, **kwargs: "token",
        query=lambda *args, **kwargs: _references(module, bindings),
        updater=update,
    )

    assert result["mode"] == "apply"
    assert result["verified"] is True
    assert bindings == {"wd": "wd-connection", "dv": "dv-connection"}
    assert pac_auth_calls[0][1]["preferred_username"] == "maker@example.com"


def test_apply_is_idempotent_when_bindings_already_match() -> None:
    import bind_workday_da_connections as module

    bindings = {"wd": "wd-connection", "dv": "dv-connection"}
    updates = []
    result = module.bind_runtime_connections(
        "https://org.crm.dynamics.com",
        ring="prod",
        apply=True,
        pac_resolver=lambda: Path("pac.exe"),
        pac_auth=lambda *args, **kwargs: None,
        runner=_pac_runner(
            [
                _connection("wd-connection", module.WORKDAY_CONNECTOR),
                _connection("dv-connection", module.DATAVERSE_CONNECTOR),
            ]
        ),
        token_provider=lambda *args, **kwargs: "token",
        query=lambda *args, **kwargs: _references(module, bindings),
        updater=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert result["verified"] is True
    assert all(change["action"] == "unchanged" for change in result["changes"])
    assert updates == []


def test_multiple_connected_workday_connections_fail_closed() -> None:
    import bind_workday_da_connections as module

    with pytest.raises(
        module.WorkdayDABindingError,
        match="Expected exactly one connected shared_workdaysoap connection",
    ):
        module.bind_runtime_connections(
            "https://org.crm.dynamics.com",
            ring="prod",
            apply=False,
            pac_resolver=lambda: Path("pac.exe"),
            pac_auth=lambda *args, **kwargs: None,
            runner=_pac_runner(
                [
                    _connection("wd-one", module.WORKDAY_CONNECTOR),
                    _connection("wd-two", module.WORKDAY_CONNECTOR),
                    _connection("dv-one", module.DATAVERSE_CONNECTOR),
                ]
            ),
            token_provider=lambda *args, **kwargs: "token",
            query=lambda *args, **kwargs: [],
        )


def test_duplicate_runtime_reference_fails_closed() -> None:
    import bind_workday_da_connections as module

    rows = [
        _reference("wd-one", module.WORKDAY_LOGICAL_NAME),
        _reference("wd-two", module.WORKDAY_LOGICAL_NAME),
        _reference("dv-one", module.DATAVERSE_LOGICAL_NAME),
    ]
    with pytest.raises(
        module.WorkdayDABindingError,
        match="Expected exactly one installed runtime connection reference",
    ):
        module.bind_runtime_connections(
            "https://org.crm.dynamics.com",
            ring="prod",
            apply=False,
            pac_resolver=lambda: Path("pac.exe"),
            pac_auth=lambda *args, **kwargs: None,
            runner=_pac_runner(
                [
                    _connection("wd-one", module.WORKDAY_CONNECTOR),
                    _connection("dv-one", module.DATAVERSE_CONNECTOR),
                ]
            ),
            token_provider=lambda *args, **kwargs: "token",
            query=lambda *args, **kwargs: rows,
        )
