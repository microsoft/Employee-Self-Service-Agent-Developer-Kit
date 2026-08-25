# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.mcp_client — the ``--ping`` diagnostic.

The 3.x ``get_project_plan`` tool requires ``{"projectId","planId"}``; ``--ping``
used to call it with an empty ``{}`` (always rejected). ``_ping_project_plan``
must first resolve the project/plan binding and then call the tool with those
ids. Exercised against a small in-memory fake — no network.
"""

from __future__ import annotations

import pytest

from planner import mcp_client
from planner.mcp_client import McpError


class _FakePingClient:
    def __init__(self, plan_doc: dict, projects: list[dict], plans: list[dict]) -> None:
        self.plan_doc = plan_doc
        self.projects = projects
        self.plans = plans
        self.calls: list[tuple[str, dict]] = []
        self.get_args: dict | None = None

    def call_tool(self, name: str, arguments: dict | None = None):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "list_agent_configuration_projects":
            return {"value": self.projects}
        if name == "get_agent_configuration_project":
            return self.projects[0]
        if name == "list_project_plans":
            return {"value": self.plans}
        if name == "get_project_plan":
            self.get_args = arguments
            return self.plan_doc
        raise McpError(f"unexpected tool {name}")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("PLANNER_MCP_PROJECT_ID", "PLANNER_MCP_PLAN_ID", "PLANNER_MCP_TENANT_ID"):
        monkeypatch.delenv(var, raising=False)


def test_ping_project_plan_resolves_ids_before_get():
    client = _FakePingClient(
        plan_doc={"PlanId": "pl-1", "ProjectId": "pr-1", "Context": [], "AcceptanceCriteria": []},
        projects=[{"ProjectId": "pr-1", "Name": "P", "ActivePlanId": "pl-1", "TenantId": "t"}],
        plans=[{"PlanId": "pl-1"}],
    )
    msg = mcp_client._ping_project_plan(client)
    # The tool was called WITH the resolved ids — not the old empty {}.
    assert client.get_args == {"projectId": "pr-1", "planId": "pl-1"}
    assert "get_project_plan OK" in msg
    assert "pr-1" in msg and "pl-1" in msg


def test_ping_project_plan_uses_env_binding(monkeypatch):
    # An explicit env binding is honored without any discovery calls.
    monkeypatch.setenv("PLANNER_MCP_PROJECT_ID", "pr-env")
    monkeypatch.setenv("PLANNER_MCP_PLAN_ID", "pl-env")
    client = _FakePingClient(
        plan_doc={"PlanId": "pl-env", "ProjectId": "pr-env", "Context": []},
        projects=[{"ProjectId": "pr-env", "Name": "P"}],
        plans=[],
    )
    mcp_client._ping_project_plan(client)
    assert client.get_args == {"projectId": "pr-env", "planId": "pl-env"}
    # With both ids pinned, no plan discovery is needed.
    assert not any(n == "list_project_plans" for n, _ in client.calls)


# -- identity: .env resolution + per-call injection ------------------------- #


def test_load_adk_identity_prefers_process_env(monkeypatch, tmp_path):
    """Process env (``PLANNER_MCP_USER_NAME`` + ``PLANNER_MCP_AAD_ID``) wins and no
    file is read."""
    monkeypatch.setenv("PLANNER_MCP_USER_NAME", "  envuser  ")
    monkeypatch.setenv("PLANNER_MCP_AAD_ID", "  env-aad  ")
    name, aad = mcp_client.load_adk_identity(tmp_path / ".vscode" / "mcp.json")
    assert (name, aad) == ("envuser", "env-aad")


def test_load_adk_identity_reads_env_file(monkeypatch, tmp_path):
    """Absent process env, the kit ``.env`` beside the config's parent is parsed;
    quoted / space-padded ``aadId`` + ``userName`` are unwrapped."""
    monkeypatch.delenv("PLANNER_MCP_USER_NAME", raising=False)
    monkeypatch.delenv("PLANNER_MCP_AAD_ID", raising=False)
    (tmp_path / ".env").write_text(
        'aadId= "3541af92-2c5d-4b4a-aad8-5f257de3244d"\n'
        'userName= "default"\n'
        'displayName= "default"\n',
        encoding="utf-8",
    )
    name, aad = mcp_client.load_adk_identity(tmp_path / ".vscode" / "mcp.json")
    assert aad == "3541af92-2c5d-4b4a-aad8-5f257de3244d"
    assert name == "default"


def test_load_adk_identity_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("PLANNER_MCP_USER_NAME", raising=False)
    monkeypatch.delenv("PLANNER_MCP_AAD_ID", raising=False)
    assert mcp_client.load_adk_identity(tmp_path / ".vscode" / "mcp.json") == (None, None)


class _RpcRecorder(mcp_client.McpClient):
    """An McpClient with its transport stubbed so ``call_tool``'s argument shaping
    can be asserted without a network."""

    def __init__(self, **kwargs) -> None:
        super().__init__("http://example", **kwargs)
        self._initialized = True
        self.sent: dict | None = None
        # Seed a live tool catalog so call_tool's schema lookup + identity
        # injection have a shape to validate against (no tools/list round-trip).
        self._tools_by_name = {
            name: {"name": name, "inputSchema": {
                "properties": {"callerId": {}, "userName": {}, "aadId": {}}}}
            for name in ("t", "list_project_plan_tasks_for_caller")
        }

    def _rpc(self, method, params=None):
        self.sent = {"method": method, "params": params}
        return {"content": [{"type": "text", "text": "{}"}]}


def test_call_tool_injects_env_identity_into_every_call():
    """The ``.env`` ``userName``/``aadId`` ride on every tool call so WeveNova
    knows the caller without a separate identity round-trip."""
    client = _RpcRecorder(user_name="default", aad_id="aad-1")
    client.call_tool("list_project_plan_tasks_for_caller", {"callerId": "c1"})
    args = client.sent["params"]["arguments"]
    assert args["callerId"] == "c1"
    assert args["userName"] == "default"
    assert args["aadId"] == "aad-1"


def test_call_tool_does_not_override_explicit_identity_args():
    client = _RpcRecorder(user_name="default", aad_id="aad-1")
    client.call_tool("t", {"aadId": "explicit", "userName": "override"})
    args = client.sent["params"]["arguments"]
    assert args["aadId"] == "explicit"
    assert args["userName"] == "override"


def test_call_tool_without_identity_sends_bare_arguments():
    client = _RpcRecorder()  # no .env identity resolved
    client.call_tool("t", {"callerId": "c1"})
    args = client.sent["params"]["arguments"]
    assert args == {"callerId": "c1"}
