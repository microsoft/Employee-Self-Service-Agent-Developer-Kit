# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Check whether Microsoft GitHub Copilot is allowed for Dataverse MCP."""

from __future__ import annotations

import argparse
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from auth import authenticate, query_all


RESULT_MARKER = "DATAVERSE_MCP_STATUS_JSON:"
GITHUB_COPILOT_APPLICATION_ID = "aebc6443-996d-45c2-90f0-388ff96faa56"
CLIENT_SELECT = (
    "allowedmcpclientid,applicationid,name,uniquename,isenabled,"
    "statecode,statuscode"
)


@dataclass(frozen=True)
class McpClientStatus:
    status: str
    application_id: str
    name: str | None
    enabled: bool
    active: bool
    record_id: str | None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "applicationId": self.application_id,
            "name": self.name,
            "enabled": self.enabled,
            "active": self.active,
            "recordId": self.record_id,
        }


class McpClientGateway(ABC):
    """Persistence boundary for Dataverse MCP client allowlisting."""

    @abstractmethod
    def find_client(self, application_id: str) -> list[dict]:
        """Return allowlist records for the application ID."""


class DataverseMcpClientGateway(McpClientGateway):
    """Dataverse implementation of the MCP client boundary."""

    def __init__(self, env_url: str, token: str) -> None:
        self._env_url = env_url.rstrip("/")
        self._token = token

    def find_client(self, application_id: str) -> list[dict]:
        escaped_id = application_id.replace("'", "''")
        return query_all(
            self._env_url,
            self._token,
            "allowedmcpclients",
            CLIENT_SELECT,
            f"applicationid eq '{escaped_id}'",
        )


class DataverseMcpStatusService:
    """Application service for deterministic MCP allowlist inspection."""

    def __init__(self, gateway: McpClientGateway) -> None:
        self._gateway = gateway

    def inspect(
        self,
        application_id: str = GITHUB_COPILOT_APPLICATION_ID,
    ) -> McpClientStatus:
        records = self._gateway.find_client(application_id)
        if not records:
            return McpClientStatus(
                status="missing",
                application_id=application_id,
                name="Microsoft GitHub Copilot",
                enabled=False,
                active=False,
                record_id=None,
            )
        if len(records) != 1:
            raise RuntimeError(
                "Dataverse returned multiple Allowed MCP Client records for "
                "Microsoft GitHub Copilot."
            )

        record = records[0]
        enabled = record.get("isenabled") is True
        active = record.get("statecode") == 0
        return McpClientStatus(
            status="enabled" if enabled and active else "disabled",
            application_id=application_id,
            name=record.get("name") or "Microsoft GitHub Copilot",
            enabled=enabled,
            active=active,
            record_id=record.get("allowedmcpclientid"),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    try:
        env_url = args.url.rstrip("/")
        token = authenticate(env_url)
        status = DataverseMcpStatusService(
            DataverseMcpClientGateway(env_url, token)
        ).inspect()
        print(f"{RESULT_MARKER}{json.dumps(status.to_dict())}")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
