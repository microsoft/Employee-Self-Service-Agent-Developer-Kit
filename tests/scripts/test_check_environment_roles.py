# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for selected-environment role validation."""

from __future__ import annotations

import check_environment_roles
from check_environment_roles import (
    DataverseEnvironmentRoleGateway,
    EnvironmentRoleAccessService,
    EnvironmentRoleGateway,
)
from http_errors import APIError


class FakeGateway(EnvironmentRoleGateway):
    def __init__(self, roles: list[dict]) -> None:
        self.roles = roles
        self.calls = []

    def get_current_user_id(self) -> str:
        self.calls.append("current-user")
        return "11111111-1111-1111-1111-111111111111"

    def get_directory_object_id(self, user_id: str) -> str:
        self.calls.append(("directory-object", user_id))
        return "22222222-2222-2222-2222-222222222222"

    def list_user_roles(self, directory_object_id: str) -> list[dict]:
        self.calls.append(("roles", directory_object_id))
        return self.roles


def test_dataverse_gateway_retrieves_direct_and_team_roles(monkeypatch) -> None:
    calls = []
    responses = [
        {"UserId": "11111111-1111-1111-1111-111111111111"},
        {
            "azureactivedirectoryobjectid":
                "22222222-2222-2222-2222-222222222222",
        },
        {"value": [{"name": "Environment Maker"}]},
    ]

    def fake_dataverse_get(env_url, token, path, params=None):
        calls.append((env_url, token, path, params))
        return responses.pop(0)

    monkeypatch.setattr(
        check_environment_roles,
        "dataverse_get",
        fake_dataverse_get,
    )
    gateway = DataverseEnvironmentRoleGateway(
        "https://org.crm.dynamics.com/",
        "token",
    )

    user_id = gateway.get_current_user_id()
    directory_object_id = gateway.get_directory_object_id(user_id)
    roles = gateway.list_user_roles(directory_object_id)

    assert roles == [{"name": "Environment Maker"}]
    assert calls == [
        (
            "https://org.crm.dynamics.com",
            "token",
            "WhoAmI()",
            None,
        ),
        (
            "https://org.crm.dynamics.com",
            "token",
            "systemusers(11111111-1111-1111-1111-111111111111)",
            {"$select": "azureactivedirectoryobjectid"},
        ),
        (
            "https://org.crm.dynamics.com",
            "token",
            (
                "RetrieveAadUserRoles"
                "(DirectoryObjectId=22222222-2222-2222-2222-222222222222)"
            ),
            {"$select": "name,roleid"},
        ),
    ]


def test_environment_maker_alone_cannot_use_environment() -> None:
    gateway = FakeGateway([{"name": "Environment Maker"}])

    result = EnvironmentRoleAccessService(gateway).inspect()

    assert result.eligible is False
    assert result.matched_roles == ()
    assert result.missing_roles == ("System Administrator",)


def test_system_administrator_alone_can_use_environment() -> None:
    gateway = FakeGateway([{"name": "System Administrator"}])

    result = EnvironmentRoleAccessService(gateway).inspect()

    assert result.eligible is True
    assert result.matched_roles == ("System Administrator",)
    assert result.missing_roles == ()


def test_required_role_allows_environment_use_case_insensitively() -> None:
    gateway = FakeGateway([
        {"name": "environment maker"},
        {"name": "SYSTEM ADMINISTRATOR"},
    ])

    result = EnvironmentRoleAccessService(gateway).inspect()

    assert result.eligible is True
    assert result.matched_roles == ("System Administrator",)
    assert result.missing_roles == ()
    assert result.to_dict()["missingRoles"] == []
    assert result.to_dict()["requiredRoles"] == ["System Administrator"]


def test_unrelated_roles_cannot_use_environment() -> None:
    gateway = FakeGateway([
        {"name": "Basic User"},
        {"name": "Bot Author"},
    ])

    result = EnvironmentRoleAccessService(gateway).inspect()

    assert result.eligible is False
    assert result.matched_roles == ()
    assert result.missing_roles == ("System Administrator",)
    assert gateway.calls == [
        "current-user",
        (
            "directory-object",
            "11111111-1111-1111-1111-111111111111",
        ),
        ("roles", "22222222-2222-2222-2222-222222222222"),
    ]


def test_main_handles_api_error_through_oserror_base(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        check_environment_roles,
        "authenticate",
        lambda _url: (_ for _ in ()).throw(
            APIError(status_code=401, message="Session expired")
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_environment_roles.py",
            "--url",
            "https://org.crm.dynamics.com",
        ],
    )

    assert check_environment_roles.main() == 1
    assert "ERROR: Session expired" in capsys.readouterr().out
