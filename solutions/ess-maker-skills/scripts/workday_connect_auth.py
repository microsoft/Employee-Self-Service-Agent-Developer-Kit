# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Identity continuity and authentication planning for Workday connect."""

from __future__ import annotations

import base64
import json
from typing import Any


class WorkdayConnectIdentityError(RuntimeError):
    """Raised when an authenticated account does not match the intended user."""


def authentication_plan() -> list[dict[str, Any]]:
    """Describe credential stores without pretending one token serves all."""
    return [
        {
            "store": "azure-cli-graph",
            "role": "Microsoft Entra administrator",
            "purpose": "Discover, configure, and verify the Workday application",
        },
        {
            "store": "pac",
            "role": "Power Platform Environment Maker",
            "purpose": "Install the Workday package and inspect connections",
        },
        {
            "store": "dataverse-msal",
            "role": "Power Platform Environment Maker",
            "purpose": "Verify and configure Workday runtime resources",
        },
        {
            "store": "workday-connector",
            "role": "Workday employee",
            "purpose": "Create the signed-in employee Workday connection",
        },
    ]


def token_identity(access_token: str) -> dict[str, str]:
    """Read safe identity claims from an access token without storing it."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkdayConnectIdentityError(
            "The authenticated Dataverse token did not contain readable "
            "identity claims."
        ) from exc
    username = str(
        claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("unique_name")
        or ""
    ).strip()
    tenant_id = str(claims.get("tid") or "").strip()
    if not username or not tenant_id:
        raise WorkdayConnectIdentityError(
            "The authenticated Dataverse token did not identify both the "
            "account and Microsoft Entra tenant."
        )
    return {"username": username, "tenantId": tenant_id}


def require_identity(
    access_token: str,
    *,
    preferred_username: str | None,
) -> dict[str, str]:
    identity = token_identity(access_token)
    if preferred_username and (
        identity["username"].casefold() != preferred_username.casefold()
    ):
        raise WorkdayConnectIdentityError(
            "Dataverse authentication used a different account from the "
            "selected Environment Maker."
        )
    return identity
