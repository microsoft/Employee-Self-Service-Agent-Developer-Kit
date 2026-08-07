# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Verify that the signed-in maker can use the selected ESS environment."""

from __future__ import annotations

import argparse
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from auth import authenticate, dataverse_get


RESULT_MARKER = "ENVIRONMENT_ROLE_ACCESS_JSON:"
REQUIRED_ROLE_NAMES = ("System Administrator",)


@dataclass(frozen=True)
class EnvironmentRoleAccess:
    eligible: bool
    matched_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "matchedRoles": list(self.matched_roles),
            "missingRoles": list(self.missing_roles),
            "requiredRoles": list(REQUIRED_ROLE_NAMES),
        }


class EnvironmentRoleGateway(ABC):
    """Dataverse boundary for current-user environment role discovery."""

    @abstractmethod
    def get_current_user_id(self) -> str:
        """Return the signed-in Dataverse system user ID."""

    @abstractmethod
    def get_directory_object_id(self, user_id: str) -> str:
        """Return the user's Microsoft Entra object ID."""

    @abstractmethod
    def list_user_roles(self, directory_object_id: str) -> list[dict]:
        """Return roles assigned directly or through team membership."""


class DataverseEnvironmentRoleGateway(EnvironmentRoleGateway):
    """Dataverse implementation of environment role discovery."""

    def __init__(self, env_url: str, token: str) -> None:
        self._env_url = env_url.rstrip("/")
        self._token = token

    def get_current_user_id(self) -> str:
        response = dataverse_get(
            self._env_url,
            self._token,
            "WhoAmI()",
        )
        user_id = (response or {}).get("UserId")
        if not user_id:
            raise RuntimeError("Dataverse did not return the signed-in user ID.")
        return str(user_id)

    def get_directory_object_id(self, user_id: str) -> str:
        normalized_user_id = str(uuid.UUID(user_id))
        response = dataverse_get(
            self._env_url,
            self._token,
            f"systemusers({normalized_user_id})",
            params={"$select": "azureactivedirectoryobjectid"},
        )
        directory_object_id = (response or {}).get(
            "azureactivedirectoryobjectid"
        )
        if not directory_object_id:
            raise RuntimeError(
                "Dataverse did not return the signed-in user's Entra object ID."
            )
        return str(directory_object_id)

    def list_user_roles(self, directory_object_id: str) -> list[dict]:
        normalized_object_id = str(uuid.UUID(directory_object_id))
        response = dataverse_get(
            self._env_url,
            self._token,
            (
                "RetrieveAadUserRoles"
                f"(DirectoryObjectId={normalized_object_id})"
            ),
            params={"$select": "name,roleid"},
        )
        roles = (response or {}).get("value")
        if not isinstance(roles, list):
            raise RuntimeError("Dataverse did not return the user's roles.")
        return roles


class EnvironmentRoleAccessService:
    """Determine whether the current user has the required environment role."""

    def __init__(self, gateway: EnvironmentRoleGateway) -> None:
        self._gateway = gateway

    def inspect(self) -> EnvironmentRoleAccess:
        user_id = self._gateway.get_current_user_id()
        directory_object_id = self._gateway.get_directory_object_id(user_id)
        roles = self._gateway.list_user_roles(directory_object_id)
        role_names = {
            str(role.get("name") or "").strip().casefold()
            for role in roles
            if str(role.get("name") or "").strip()
        }
        matched_roles = tuple(
            role_name
            for role_name in REQUIRED_ROLE_NAMES
            if role_name.casefold() in role_names
        )
        missing_roles = tuple(
            role_name
            for role_name in REQUIRED_ROLE_NAMES
            if role_name.casefold() not in role_names
        )
        return EnvironmentRoleAccess(
            eligible=not missing_roles,
            matched_roles=matched_roles,
            missing_roles=missing_roles,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    try:
        env_url = args.url.rstrip("/")
        token = authenticate(env_url)
        result = EnvironmentRoleAccessService(
            DataverseEnvironmentRoleGateway(env_url, token)
        ).inspect()
        print(f"{RESULT_MARKER}{json.dumps(result.to_dict())}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
