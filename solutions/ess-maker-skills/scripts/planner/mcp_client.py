# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: a minimal MCP client for the WeveNova plan store.

The planner can persist the Plan to a **WeveNova project plan** through an MCP
server (the ``weve-plan`` server) instead of the local ``plan.json``. This module
speaks just enough of the MCP *Streamable HTTP* transport to:

  * ``initialize`` the session,
  * list tools, and
  * ``tools/call`` the ``weve-plan`` project-plan / task tools.

It reads the server endpoint from the same ``.vscode/mcp.json`` the kit already
uses for its MCP servers (so there is one runtime config, never committed), with
``PLANNER_MCP_URL`` / ``PLANNER_MCP_HEADERS`` env overrides for tests/CI.

Stdlib only (``urllib``) — no third-party dependency. Handles both a plain JSON
response and an SSE (``text/event-stream``) response, and echoes an
``Mcp-Session-Id`` when the server issues one.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_MCP_CONFIG = os.path.join(".vscode", "mcp.json")
DEFAULT_SERVER_NAME = "weve-plan"
PROTOCOL_VERSION = "2025-03-26"


class McpError(RuntimeError):
    """An MCP transport, protocol, or tool-level error."""


def _extract_result(body: str, content_type: str) -> dict[str, Any]:
    """Return the last JSON-RPC message from a JSON or SSE response body."""
    if "text/event-stream" in (content_type or ""):
        last: dict[str, Any] | None = None
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    last = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        if last is None:
            raise McpError("no data frames in SSE response")
        return last
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise McpError(f"non-JSON response: {body[:200]!r}") from exc


class McpClient:
    """A tiny JSON-RPC-over-HTTP MCP client for a single server."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 90.0,
        user_name: str | None = None,
        aad_id: str | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.user_name = user_name
        self.aad_id = aad_id
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._session_id: str | None = None
        self._next_id = 0
        self._initialized = False
        self._tools_by_name: dict[str, dict[str, Any]] | None = None
        self._lifecycle_rules: dict[str, Any] | None = None
        self.server_instructions = ""
        self.server_version = ""

    # -- transport ------------------------------------------------------- #

    def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                raw = resp.read().decode("utf-8", errors="replace")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise McpError(f"HTTP {exc.code} from MCP server: {detail}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"cannot reach MCP server {self.url}: {exc.reason}") from exc
        if "id" not in payload:  # a notification — no response body expected
            return None
        msg = _extract_result(raw, ctype)
        if isinstance(msg, dict) and msg.get("error"):
            err = msg["error"]
            raise McpError(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
        return msg

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}})
        return (msg or {}).get("result")

    # -- MCP surface ----------------------------------------------------- #

    def initialize(self) -> dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ess-planner", "version": "1.0"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        result = result or {}
        self.server_instructions = result.get("instructions", "")
        self.server_version = (result.get("serverInfo") or {}).get("version", "")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        if not self._initialized:
            self.initialize()
        tools = (self._rpc("tools/list") or {}).get("tools", [])
        self._tools_by_name = {
            tool["name"]: tool
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
        return tools

    def lifecycle_rules(self) -> dict[str, Any]:
        """Return the live WeveNova lifecycle/concurrency contract once per client."""
        if self._lifecycle_rules is None:
            payload = self.call_tool("get_wevenova_lifecycle_rules", {})
            if not isinstance(payload, dict):
                raise McpError(
                    "get_wevenova_lifecycle_rules returned an unexpected payload"
                )
            self._lifecycle_rules = payload
        return self._lifecycle_rules

    def _tool(self, name: str) -> dict[str, Any]:
        if self._tools_by_name is None:
            self.list_tools()
        tool = (self._tools_by_name or {}).get(name)
        if tool is None:
            raise McpError(
                f"MCP tool {name!r} is not present in the live catalog; reconnect "
                "or refresh the configured weve-plan server."
            )
        return tool

    @staticmethod
    def _validate_arguments(name: str, schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [key for key in required if key not in arguments]
        if missing:
            raise McpError(
                f"tool {name} missing required argument(s): {', '.join(missing)}"
            )
        if schema.get("additionalProperties") is False:
            unexpected = [key for key in arguments if key not in properties]
            if unexpected:
                raise McpError(
                    f"tool {name} does not accept argument(s): {', '.join(unexpected)}. "
                    "The live tool catalog may have changed."
                )

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool and return its parsed payload.

        The ``weve-plan`` tools return one text content block that is a JSON
        entity (or an upstream error string). Returns the parsed JSON object when
        possible, else the raw text. Raises :class:`McpError` when the tool
        reports ``isError`` or the upstream proxied an HTTP error.
        """
        if not self._initialized:
            self.initialize()
        tool = self._tool(name)
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        tool_arguments = dict(arguments or {})
        if self.user_name and "userName" in properties and "userName" not in tool_arguments:
            tool_arguments["userName"] = self.user_name
        if self.aad_id and "aadId" in properties and "aadId" not in tool_arguments:
            tool_arguments["aadId"] = self.aad_id
        if self.user_name and "userName" not in properties:
            raise McpError(
                f"tool {name} does not expose userName in the live schema; refusing "
                "to call it with the wrong token profile."
            )
        if self.aad_id and "aadId" not in properties:
            raise McpError(
                f"tool {name} does not expose aadId in the live schema; refusing "
                "to call it with the wrong identity."
            )
        self._validate_arguments(name, schema, tool_arguments)
        result = self._rpc("tools/call", {"name": name, "arguments": tool_arguments}) or {}
        blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        text = "\n".join(blocks).strip()
        if result.get("isError"):
            raise McpError(f"tool {name} failed: {text[:4000]}")
        # The proxy surfaces upstream failures as a plain "Upstream ... returned NNN ..." string.
        if text.startswith("Upstream ") and "returned" in text[:120]:
            raise McpError(f"tool {name}: {text[:4000]}")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


# -- config ------------------------------------------------------------- #

def load_mcp_server(
    name: str = DEFAULT_SERVER_NAME,
    config_path: str | os.PathLike[str] = DEFAULT_MCP_CONFIG,
) -> dict[str, Any]:
    """Read a server's ``{url, headers}`` from a ``.vscode/mcp.json``-shaped file.

    ``PLANNER_MCP_URL`` (and optional JSON ``PLANNER_MCP_HEADERS``) override the
    file, so tests/CI need no config file on disk.
    """
    env_url = os.environ.get("PLANNER_MCP_URL")
    if env_url:
        headers = json.loads(os.environ.get("PLANNER_MCP_HEADERS", "{}"))
        return {"url": env_url, "headers": headers}
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise McpError(
            f"no MCP config at {config_path} and PLANNER_MCP_URL unset — add the "
            f"'{name}' server to .vscode/mcp.json"
        ) from exc
    server = (cfg.get("servers") or {}).get(name)
    if not server or not server.get("url"):
        raise McpError(f"server {name!r} not found in {config_path}")
    return {"url": server["url"], "headers": server.get("headers") or {}}

def load_adk_identity(config_path: str | os.PathLike[str] = DEFAULT_MCP_CONFIG) -> tuple[str | None, str | None]:
    """Load the MCP token profile and AAD ID from process env or the kit's .env."""
    user_name = os.environ.get("PLANNER_MCP_USER_NAME")
    aad_id = os.environ.get("PLANNER_MCP_AAD_ID")
    if user_name and aad_id:
        return user_name.strip(), aad_id.strip()

    env_path = os.path.abspath(
        os.path.join(os.path.dirname(os.fspath(config_path)) or ".", "..", ".env")
    )
    values: dict[str, str] = {}
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass

    return (
        (user_name or values.get("userName") or values.get("displayName") or "").strip() or None,
        (aad_id or values.get("aadId") or "").strip() or None,
    )


def client_from_config(
    name: str = DEFAULT_SERVER_NAME,
    config_path: str | os.PathLike[str] = DEFAULT_MCP_CONFIG,
    timeout: float = 90.0,
) -> McpClient:
    server = load_mcp_server(name, config_path)
    user_name, aad_id = load_adk_identity(config_path)
    return McpClient(
        server["url"],
        server.get("headers"),
        timeout=timeout,
        user_name=user_name,
        aad_id=aad_id,
    )


def _ping_project_plan(client: McpClient) -> str:
    """Resolve the WeveNova project/plan binding, then read the plan back — the
    ``get_project_plan`` tool requires ``{"projectId","planId"}`` (the 3.x surface
    rejects an empty ``{}``), so ``--ping`` must discover the ids the same way the
    store does rather than calling the tool with no arguments. ``resolve_plan_binding``
    is imported lazily because ``planner.plan_store`` imports this module at import
    time — a top-level import here would be a cycle."""
    from planner.plan_store import resolve_plan_binding

    project_id, plan_id, _tenant = resolve_plan_binding(client)
    plan = client.call_tool("get_project_plan", {"projectId": project_id, "planId": plan_id})
    keys = list(plan.keys()) if isinstance(plan, dict) else type(plan).__name__
    return f"get_project_plan OK (project {project_id}, plan {plan_id}) — keys: {keys}"


def main(argv: list[str] | None = None) -> int:
    """`python -m planner.mcp_client --ping` — verify connectivity + list tools."""
    import argparse

    parser = argparse.ArgumentParser(description="Ping the planner's WeveNova MCP server.")
    parser.add_argument("--server", default=DEFAULT_SERVER_NAME)
    parser.add_argument("--config", default=DEFAULT_MCP_CONFIG)
    parser.add_argument(
        "--ping",
        action="store_true",
        help="initialize + list tools + read get_project_plan (auto-resolves projectId/planId)",
    )
    args = parser.parse_args(argv)

    try:
        client = client_from_config(args.server, args.config)
        info = client.initialize()
        print(f"connected: {info.get('serverInfo', {}).get('name')} {info.get('serverInfo', {}).get('version')}")
        tools = client.list_tools()
        print(f"tools ({len(tools)}): " + ", ".join(t.get("name", "") for t in tools))
        if args.ping:
            try:
                print(_ping_project_plan(client))
            except Exception as exc:  # McpError, or a PlanStoreError from binding
                print(f"get_project_plan unavailable: {exc}")
                return 1
        return 0
    except McpError as exc:
        print(f"MCP error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
