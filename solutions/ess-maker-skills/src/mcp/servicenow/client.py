# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ServiceNow REST API client with env-based auth, retry, and pagination."""

import asyncio
import logging
import os
import random
import re

import httpx

logger = logging.getLogger("servicenow-mcp")

# Silence httpx and httpcore loggers - if a downstream operator turns on global
# DEBUG logging they would otherwise echo full HTTP requests including
# Authorization headers (Basic auth credentials).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Tables and sys_ids appear in URL paths. Validate before interpolating so a
# malformed value cannot escape into a different REST endpoint.
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SYS_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")

# Tables that the LLM tools must never touch directly via the generic CRUD
# tools. delete_record / update_record / create_record on these would let
# prompt-injection mutate audit logs, identity, or system configuration.
_DENYLIST_TABLES = frozenset({
    "sys_user",
    "sys_user_group",
    "sys_user_role",
    "sys_audit",
    "sys_audit_delete",
    "sys_log",
    "sys_log_transaction",
    "sys_security_acl",
    "sys_properties",
    "oauth_entity",
    "oauth_entity_profile",
    "sys_certificate",
})


def _validate_table(table: str, *, allow_denylist: bool = False) -> str:
    """Reject malformed table names and (optionally) sensitive tables."""
    if not isinstance(table, str) or not _TABLE_NAME_RE.match(table):
        raise ValueError(f"Invalid ServiceNow table name: {table!r}")
    if not allow_denylist and table in _DENYLIST_TABLES:
        raise ValueError(
            f"Refusing to operate on protected table {table!r}. Use a typed "
            "tool or extend allow_denylist with team review."
        )
    return table


def _validate_sys_id(sys_id: str) -> str:
    """sys_id is always a 32-hex-char identifier."""
    if not isinstance(sys_id, str) or not _SYS_ID_RE.match(sys_id):
        raise ValueError(f"Invalid ServiceNow sys_id: {sys_id!r}")
    return sys_id


class ServiceNowClient:
    """Async HTTP client for the ServiceNow Table API.

    Reads credentials from environment variables (set in .vscode/mcp.json
    via ${input:...} prompts so credentials never touch disk).
    """

    def __init__(self):
        instance_url = os.environ.get("SERVICENOW_INSTANCE_URL", "")
        username = os.environ.get("SERVICENOW_USERNAME", "")
        password = os.environ.get("SERVICENOW_PASSWORD", "")

        if not instance_url:
            raise ValueError("SERVICENOW_INSTANCE_URL environment variable is required")
        if not instance_url.lower().startswith("https://"):
            raise ValueError(
                "SERVICENOW_INSTANCE_URL must use https:// - refusing to send"
                " credentials over an unencrypted channel."
            )
        if not username or not password:
            raise ValueError(
                "SERVICENOW_USERNAME and SERVICENOW_PASSWORD are required in env"
            )

        self.base_url = instance_url.rstrip("/")
        self._username = username
        self._password = password
        self.max_retries = 3
        self.timeout = 30.0
        self._auth = httpx.BasicAuth(username, password)

    def __repr__(self) -> str:
        return f"<ServiceNowClient base_url={self.base_url!r} user={self._username!r}>"

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=self._auth,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
            # Disable redirect-following so a 302 cannot replay the
            # Authorization header to an attacker-controlled host.
            follow_redirects=False,
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Execute an HTTP request with retry on 429."""
        last_error = None
        for attempt in range(self.max_retries):
            async with self._build_client() as client:
                try:
                    resp = await client.request(method, path, **kwargs)

                    if resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait = int(retry_after) if retry_after else 2 ** attempt
                        # Add jitter to avoid thundering-herd retries.
                        wait += random.uniform(0, 1)
                        last_error = Exception(
                            f"Rate limited (429), Retry-After={retry_after}"
                        )
                        logger.warning(
                            "Rate limited (attempt %d/%d), waiting %.1fs",
                            attempt + 1,
                            self.max_retries,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    resp.raise_for_status()

                    if resp.status_code == 204:
                        return {"success": True}

                    return resp.json()

                except httpx.HTTPStatusError as e:
                    # Don't surface the response body verbatim - it can contain
                    # PII or internal field metadata. Only the status code +
                    # high-level error.message field if present.
                    try:
                        body = e.response.json()
                        error_msg = body.get("error", {}).get("message", "")
                    except Exception:
                        error_msg = ""
                    if not error_msg:
                        error_msg = f"HTTP {e.response.status_code}"
                    logger.debug(
                        "ServiceNow HTTP error body (operator-only): %s",
                        getattr(e.response, "text", ""),
                    )
                    raise Exception(
                        f"ServiceNow API error ({e.response.status_code}): {error_msg}"
                    ) from e

                except httpx.RequestError as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                        continue
                    raise

        raise Exception(f"Max retries exceeded: {last_error}")

    # ── Table CRUD ──────────────────────────────────────────────

    async def query_table(
        self,
        table: str,
        query: str = "",
        fields: str = "",
        limit: int = 10,
        offset: int = 0,
        order_by: str = "",
        display_value: str = "true",
    ) -> dict:
        """Query records from a ServiceNow table."""
        # Allow protected tables for read-only queries (otherwise we couldn't
        # ever look up sys_user records, etc.) but still validate the name shape.
        _validate_table(table, allow_denylist=True)
        params: dict = {
            "sysparm_limit": limit,
            "sysparm_offset": offset,
            "sysparm_display_value": display_value,
        }
        if query:
            params["sysparm_query"] = query
        if fields:
            params["sysparm_fields"] = fields
        if order_by:
            q = params.get("sysparm_query", "")
            params["sysparm_query"] = (
                f"{q}^ORDERBY{order_by}" if q else f"ORDERBY{order_by}"
            )

        return await self._request("GET", f"/api/now/table/{table}", params=params)

    async def get_record(self, table: str, sys_id: str, fields: str = "") -> dict:
        """Get a single record by sys_id."""
        _validate_table(table, allow_denylist=True)
        _validate_sys_id(sys_id)
        params: dict = {"sysparm_display_value": "true"}
        if fields:
            params["sysparm_fields"] = fields
        return await self._request(
            "GET", f"/api/now/table/{table}/{sys_id}", params=params
        )

    async def create_record(self, table: str, data: dict) -> dict:
        """Create a new record."""
        _validate_table(table)  # mutating - apply denylist
        return await self._request("POST", f"/api/now/table/{table}", json=data)

    async def update_record(self, table: str, sys_id: str, data: dict) -> dict:
        """Update an existing record by sys_id."""
        _validate_table(table)  # mutating - apply denylist
        _validate_sys_id(sys_id)
        return await self._request(
            "PATCH", f"/api/now/table/{table}/{sys_id}", json=data
        )

    async def delete_record(self, table: str, sys_id: str) -> dict:
        """Delete a record by sys_id."""
        _validate_table(table)  # mutating - apply denylist
        _validate_sys_id(sys_id)
        return await self._request("DELETE", f"/api/now/table/{table}/{sys_id}")

    async def get_stats(self, table: str, query: str = "") -> dict:
        """Get aggregate stats (count) for a table query."""
        _validate_table(table, allow_denylist=True)
        params: dict = {"sysparm_count": "true"}
        if query:
            params["sysparm_query"] = query
        return await self._request("GET", f"/api/now/stats/{table}", params=params)
