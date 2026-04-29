# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ServiceNow REST API client with env-based auth, retry, and pagination."""

import asyncio
import logging
import os

import httpx

logger = logging.getLogger("servicenow-mcp")


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
        if not username or not password:
            raise ValueError(
                "SERVICENOW_USERNAME and SERVICENOW_PASSWORD are required in env"
            )

        self.base_url = instance_url.rstrip("/")
        self.max_retries = 3
        self.timeout = 30.0
        self._auth = httpx.BasicAuth(username, password)

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=self._auth,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Execute an HTTP request with retry on 429."""
        last_error = None
        for attempt in range(self.max_retries):
            async with self._build_client() as client:
                try:
                    resp = await client.request(method, path, **kwargs)

                    if resp.status_code == 429:
                        wait = int(resp.headers.get("Retry-After", str(2**attempt)))
                        logger.warning(
                            "Rate limited (attempt %d/%d), waiting %ds",
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
                    try:
                        body = e.response.json()
                        error_msg = body.get("error", {}).get("message", str(e))
                    except Exception:
                        error_msg = str(e)
                    raise Exception(
                        f"ServiceNow API error ({e.response.status_code}): {error_msg}"
                    ) from e

                except httpx.RequestError as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2**attempt)
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
        params: dict = {"sysparm_display_value": "true"}
        if fields:
            params["sysparm_fields"] = fields
        return await self._request(
            "GET", f"/api/now/table/{table}/{sys_id}", params=params
        )

    async def create_record(self, table: str, data: dict) -> dict:
        """Create a new record."""
        return await self._request("POST", f"/api/now/table/{table}", json=data)

    async def update_record(self, table: str, sys_id: str, data: dict) -> dict:
        """Update an existing record by sys_id."""
        return await self._request(
            "PATCH", f"/api/now/table/{table}/{sys_id}", json=data
        )

    async def delete_record(self, table: str, sys_id: str) -> dict:
        """Delete a record by sys_id."""
        return await self._request("DELETE", f"/api/now/table/{table}/{sys_id}")

    async def get_stats(self, table: str, query: str = "") -> dict:
        """Get aggregate stats (count) for a table query."""
        params: dict = {"sysparm_count": "true"}
        if query:
            params["sysparm_query"] = query
        return await self._request("GET", f"/api/now/stats/{table}", params=params)
