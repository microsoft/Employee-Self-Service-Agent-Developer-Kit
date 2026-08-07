# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for automatic Dataverse MCP allowlist inspection."""

from __future__ import annotations

import pytest

from check_dataverse_mcp import (
    DataverseMcpStatusService,
    GITHUB_COPILOT_APPLICATION_ID,
    McpClientGateway,
)


class FakeGateway(McpClientGateway):
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.application_ids = []

    def find_client(self, application_id: str) -> list[dict]:
        self.application_ids.append(application_id)
        return self.records


def test_enabled_client_advances_without_user_input() -> None:
    gateway = FakeGateway([{
        "allowedmcpclientid": "record-id",
        "applicationid": GITHUB_COPILOT_APPLICATION_ID,
        "name": "Microsoft GitHub Copilot",
        "isenabled": True,
        "statecode": 0,
        "statuscode": 1,
    }])

    result = DataverseMcpStatusService(gateway).inspect()

    assert result.status == "enabled"
    assert result.enabled is True
    assert result.active is True
    assert result.record_id == "record-id"
    assert gateway.application_ids == [GITHUB_COPILOT_APPLICATION_ID]


@pytest.mark.parametrize(
    ("isenabled", "statecode"),
    [(False, 0), (True, 1), (False, 1)],
)
def test_disabled_or_inactive_client_requires_admin_action(
    isenabled: bool,
    statecode: int,
) -> None:
    gateway = FakeGateway([{
        "allowedmcpclientid": "record-id",
        "name": "Microsoft GitHub Copilot",
        "isenabled": isenabled,
        "statecode": statecode,
    }])

    result = DataverseMcpStatusService(gateway).inspect()

    assert result.status == "disabled"


def test_missing_client_requires_admin_action() -> None:
    result = DataverseMcpStatusService(FakeGateway([])).inspect()

    assert result.status == "missing"
    assert result.enabled is False
    assert result.active is False


def test_duplicate_client_records_fail_loudly() -> None:
    gateway = FakeGateway([{"isenabled": True}, {"isenabled": True}])

    with pytest.raises(RuntimeError, match="multiple"):
        DataverseMcpStatusService(gateway).inspect()
