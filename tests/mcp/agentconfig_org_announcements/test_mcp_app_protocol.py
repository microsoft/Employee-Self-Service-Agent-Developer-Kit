# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Protocol-level tests for the Org Announcements MCP App and its tools."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from portalocker.exceptions import LockException


REPO_ROOT = Path(__file__).parents[3]
ORG_ANNOUNCEMENTS_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_org_announcements"
)
# Sibling MCP servers share the top-level names ``client``/``server``, so the
# modules are loaded through the shared isolated importer rather than by a plain
# ``import`` off ``sys.path``. See tests/mcp/_mcp_modules.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import load_org_announcements_modules  # noqa: E402

_ORG_MODULES = load_org_announcements_modules()
org_server = _ORG_MODULES["server"]
org_client = _ORG_MODULES["client"]
GraphDirectoryError = _ORG_MODULES["graph_directory_client"].GraphDirectoryError


RESOURCE_URI = "ui://widget/org-announcements/OrgAnnouncements.html"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
TITLE_ID = "title-1"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)

MODEL_VISIBLE_TOOLS = {
    "open_org_announcements", "search_audience_groups",
    "list_agent_configs", "search_agents",
}
APP_ONLY_TOOLS = {"save_bulletin", "transition_bulletin", "duplicate_bulletin"}


def _config(
    bulletin_id: str = "bulletin-1",
    *,
    status: str = "draft",
    audience: list[str] | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    return {
        "titleId": TITLE_ID,
        "bulletin": {
            "id": bulletin_id,
            "type": "standard",
            "priority": 1,
            "title": "Quarterly update",
            "description": "Read this",
            "startDate": "2026-09-01T00:00:00.000Z",
            **({"endDate": end_date} if end_date else {}),
        },
        "audience": audience if audience is not None else ["g1"],
        "status": status,
        "createdBy": "admin@contoso.com",
        "createdOn": "2026-08-01T12:00:00.000Z",
        "modifiedDate": "2026-09-02T12:00:00.000Z",
    }


class _FakeClient:
    """Records every authoring request the server issues.

    Mirrors ``OrgAnnouncementsClient``'s *post-unwrap* contract: the real client
    validates and unwraps the ``EssBulletinSaveResult`` envelope, so what the
    server sees is a canonical config. Envelope handling itself is covered
    against the wire in ``test_authoring_client.py``.
    """

    def __init__(
        self,
        *,
        items: list[dict[str, Any]] | None = None,
        get_result: dict[str, Any] | None = None,
        save_error: Exception | None = None,
        get_error: Exception | None = None,
        list_error: Exception | None = None,
        transition_error: Exception | None = None,
    ) -> None:
        self.tenant_id = TENANT_ID
        self.object_id = OBJECT_ID
        self.title_ids: list[str] = []
        self.items = items if items is not None else [_config()]
        self.get_result = get_result if get_result is not None else _config()
        self.save_error = save_error
        self.get_error = get_error
        self.list_error = list_error
        self.transition_error = transition_error
        self.saves: list[dict[str, Any]] = []
        self.transitions: list[tuple[str, str]] = []
        self.gets: list[str] = []
        self.lists = 0

    async def list_bulletins(self, title_id: str) -> list[dict[str, Any]]:
        self.title_ids.append(title_id)
        self.lists += 1
        if self.list_error is not None:
            raise self.list_error
        return list(self.items)

    async def get_bulletin(self, title_id: str, bulletin_id: str) -> dict[str, Any]:
        self.title_ids.append(title_id)
        self.gets.append(bulletin_id)
        if self.get_error is not None:
            raise self.get_error
        return self.get_result

    async def save_bulletin(self, title_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.title_ids.append(title_id)
        self.saves.append(payload)
        if self.save_error is not None:
            raise self.save_error
        return _config(payload.get("id") or "created-1", status=payload["status"])

    async def transition_bulletin(
        self, title_id: str, bulletin_id: str, status: str
    ) -> dict[str, Any]:
        self.title_ids.append(title_id)
        self.transitions.append((bulletin_id, status))
        if self.transition_error is not None:
            raise self.transition_error
        return _config(bulletin_id, status=status)


class _StatefulFakeClient(_FakeClient):
    """A fake that actually stores records and applies transitions server-side.

    Needed to prove lifecycle preservation for real. A stateless fake can only
    show that the *client* sent no content; it cannot show that content
    survived, because there is nothing holding the content. This one keeps a
    canonical store keyed by ID and mutates only ``status`` on a transition —
    exactly what WeveNova's ``SaveAsync`` does — so a round trip that dropped
    content would be visible.
    """

    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        super().__init__(items=list(store.values()))
        self.store = store

    async def list_bulletins(self, title_id: str) -> list[dict[str, Any]]:
        self.title_ids.append(title_id)
        self.lists += 1
        return [copy.deepcopy(config) for config in self.store.values()]

    async def get_bulletin(self, title_id: str, bulletin_id: str) -> dict[str, Any]:
        self.title_ids.append(title_id)
        self.gets.append(bulletin_id)
        if bulletin_id not in self.store:
            raise org_client.AgentConfigApiError("missing", http_status=404)
        return copy.deepcopy(self.store[bulletin_id])

    async def transition_bulletin(
        self, title_id: str, bulletin_id: str, status: str
    ) -> dict[str, Any]:
        self.title_ids.append(title_id)
        self.transitions.append((bulletin_id, status))
        if bulletin_id not in self.store:
            raise org_client.AgentConfigApiError("missing", http_status=404)
        # Only the status changes; authored content and audience are untouched,
        # which is the behavior under test.
        self.store[bulletin_id]["status"] = status
        return copy.deepcopy(self.store[bulletin_id])


class _FakeGraphClient:
    def __init__(
        self,
        *,
        resolved: dict[str, dict[str, Any]] | None = None,
        search_groups_result: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.resolved = (
            resolved
            if resolved is not None
            else {
                "g1": {
                    "id": "g1",
                    "displayName": "Group One",
                    "mail": None,
                    "isValid": True,
                }
            }
        )
        self.search_groups_result = search_groups_result or []
        self.error = error
        self.resolve_calls: list[list[str]] = []
        self.search_calls: list[str] = []
        self.tenant_ids: list[str] = []
        self.object_ids: list[str] = []

    async def resolve_groups(self, group_ids) -> dict[str, dict[str, Any]]:
        ids = list(group_ids)
        self.resolve_calls.append(ids)
        if self.error is not None:
            raise self.error
        return {k: v for k, v in self.resolved.items() if k in ids}

    async def search_groups(self, query: str) -> dict[str, Any]:
        self.search_calls.append(query)
        if self.error is not None:
            raise self.error
        return {
            "groups": self.search_groups_result,
            "exhausted": True,
            "pagesExamined": 1,
        }


@pytest.fixture
def fake_clients(monkeypatch):
    def install(client=None, graph=None):
        client = client if client is not None else _FakeClient()
        graph = graph if graph is not None else _FakeGraphClient()
        # get_client is a coroutine: the real one constructs the authoring
        # client off the event loop, so the fake must be awaitable too.
        async def _get_client():
            return client

        @asynccontextmanager
        async def _get_graph_client(tenant_id, object_id):
            graph.tenant_ids.append(tenant_id)
            graph.object_ids.append(object_id)
            yield graph

        monkeypatch.setattr(org_server, "get_client", _get_client)
        monkeypatch.setattr(org_server, "get_graph_client", _get_graph_client)
        monkeypatch.setattr(org_server, "_now", lambda: NOW)
        return client, graph

    return install


def _call(tool: str, arguments: dict[str, Any], *, include_scope: bool = True) -> Any:
    if include_scope and tool != "search_audience_groups":
        arguments = {"titleId": TITLE_ID, **arguments}
    async def run() -> Any:
        return await org_server.mcp.call_tool(tool, arguments)

    return asyncio.run(run())


def _structured(result: Any) -> dict[str, Any]:
    # FastMCP returns (content, structured) for a CallToolResult-returning tool.
    if isinstance(result, tuple):
        return result[1]
    return result.structuredContent


# --------------------------------------------------------------------------
# Resource and tool metadata
# --------------------------------------------------------------------------


def test_widget_origin_uses_the_production_fallback() -> None:
    assert (
        org_server.DEFAULT_WIDGET_ORIGIN
        == "https://workforceinsights.m365.cloud.microsoft"
    )


def test_the_mcp_app_resource_is_registered_with_the_widget_profile() -> None:
    async def run():
        return await org_server.mcp.list_resources()

    resources = asyncio.run(run())
    matching = [
        resource for resource in resources if str(resource.uri) == RESOURCE_URI
    ]

    assert len(matching) == 1
    assert matching[0].mimeType == org_server.WIDGET_MIME_TYPE


def test_the_resource_shell_loads_the_hosted_bundle_from_the_origin() -> None:
    shell = org_server.org_announcements_widget()

    assert (
        f'src="{org_server.WIDGET_ORIGIN}/mcp-widget/org-announcements/widget.js"'
        in shell
    )


def test_widget_origin_override_is_validated() -> None:
    assert (
        org_server._resolve_widget_origin("https://localhost:4200")
        == "https://localhost:4200"
    )
    for bad in [
        "http://localhost:4200",
        "https://user:pw@example.com",
        "https://example.com/path",
        "https://example.com?query=1",
        "https://example.com#frag",
    ]:
        with pytest.raises(ValueError):
            org_server._resolve_widget_origin(bad)


def test_the_opener_is_read_only_and_visible_to_model_and_app() -> None:
    async def run():
        return await org_server.mcp.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}
    opener = tools["open_org_announcements"]

    assert opener.annotations.readOnlyHint is True
    assert opener.annotations.destructiveHint is False
    assert opener.meta["ui"]["visibility"] == ["model", "app"]
    assert opener.meta["ui"]["resourceUri"] == RESOURCE_URI


def test_mutation_tools_are_not_model_visible() -> None:
    async def run():
        return await org_server.mcp.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}

    assert APP_ONLY_TOOLS <= set(tools)
    for name in APP_ONLY_TOOLS:
        visibility = tools[name].meta["ui"]["visibility"]
        assert visibility == ["app"], f"{name} must not be model-visible"
        assert tools[name].annotations.readOnlyHint is False


def test_search_is_read_only_and_visible_to_both_surfaces() -> None:
    async def run():
        return await org_server.mcp.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}
    search = tools["search_audience_groups"]

    assert search.annotations.readOnlyHint is True
    assert set(search.meta["ui"]["visibility"]) == {"model", "app"}


def test_announcement_tools_require_title_id_but_directory_search_does_not() -> None:

    async def run():
        return await org_server.mcp.list_tools()

    for tool in asyncio.run(run()):
        properties = tool.inputSchema.get("properties", {})
        assert "tenantId" not in properties, tool.name
        if tool.name == "search_audience_groups":
            assert set(properties) == {"query"}
        elif tool.name == "list_agent_configs":
            assert properties == {}
        elif tool.name == "search_agents":
            assert set(properties) == {"searchString"}
        else:
            assert properties["titleId"]["type"] == "string"
            assert "titleId" in tool.inputSchema["required"]


def test_the_server_instructions_disclose_agent_scope() -> None:
    instructions = org_server.mcp.instructions.lower()

    assert "authenticated tenant" in instructions
    assert "required titleid" in instructions
    assert "per tenant and agent" in instructions


def test_opener_metadata_exposes_only_normal_create_and_edit_modes():
    tools = asyncio.run(org_server.mcp.list_tools())
    opener = next(tool for tool in tools if tool.name == "open_org_announcements")
    variants = opener.inputSchema["properties"]["mode"]["anyOf"]
    assert next(variant["enum"] for variant in variants if "enum" in variant) == ["create", "edit"]
    assert set(opener.inputSchema["required"]) == {"titleId", "view"}
    assert "Manager takes no editor arguments" in opener.description


# --------------------------------------------------------------------------
# Opener behavior
# --------------------------------------------------------------------------


def test_manager_open_returns_canonical_manager_state(fake_clients) -> None:
    client, _ = fake_clients(
        _FakeClient(
            items=[
                _config("a", status="draft"),
                _config("b", status="retired"),
            ]
        )
    )

    payload = _structured(_call("open_org_announcements", {"view": "manager"}))

    assert payload["view"] == "manager"
    assert payload["workingSetCount"] == 1
    assert payload["archivedTruncated"] is False
    assert [item["config"]["bulletin"]["id"] for item in payload["items"]] == [
        "a",
        "b",
    ]
    assert client.saves == []


def test_manager_open_message_discloses_agent_scope(fake_clients) -> None:
    fake_clients()

    result = _call("open_org_announcements", {"view": "manager"})
    text = result[0][0].text if isinstance(result, tuple) else result.content[0].text

    assert "selected ESS agent" in text


def test_empty_create_returns_the_editor_defaults_without_writing(
    fake_clients,
) -> None:
    client, _ = fake_clients()

    payload = _structured(
        _call("open_org_announcements", {"view": "editor", "mode": "create"})
    )

    assert payload["view"] == "editor"
    assert payload["mode"] == "create"
    assert payload["config"] is None
    assert "id" not in payload["draft"]
    assert payload["draft"]["type"] == "standard"
    assert payload["draft"]["standardPriority"] == 1
    assert payload["draft"]["audience"] == []
    assert client.saves == []
    assert client.transitions == []


def test_pre_hydrated_create_overlays_the_suggestion_and_writes_nothing(
    fake_clients,
) -> None:
    client, graph = fake_clients(
        graph=_FakeGraphClient(
            resolved={
                "g1": {
                    "id": "g1",
                    "displayName": "Group One",
                    "mail": "one@contoso.com",
                    "isValid": True,
                }
            }
        )
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {
                "view": "editor",
                "mode": "create",
                "suggestedDraft": {
                    "title": "Benefits enrollment",
                    "priority": 0,
                    "audience": ["g1"],
                    "secondaryAction": {
                        "actionType": "copilotChat",
                        "label": "Ask",
                        "prompt": "Explain benefits",
                    },
                },
            },
        )
    )

    draft = payload["draft"]
    assert draft["title"] == "Benefits enrollment"
    assert draft["standardPriority"] == 0
    assert draft["standardSecondaryAction"]["label"] == "Ask"
    assert draft["audience"] == [
        {
            "id": "g1",
            "displayName": "Group One",
            "mail": "one@contoso.com",
            "isValid": True,
        }
    ]
    # Untouched fields still hold the empty-editor defaults.
    assert draft["description"] == ""
    assert draft["startDate"] == ""
    assert draft["endDate"] == ""
    assert draft["primaryAction"] is None
    assert client.saves == []


def test_a_suggested_draft_carrying_canonical_metadata_is_rejected(
    fake_clients,
) -> None:
    """A draft that names a bulletin is rejected before the tool body runs."""
    client, _ = fake_clients()

    with pytest.raises(ToolError):
        _call(
            "open_org_announcements",
            {
                "view": "editor",
                "mode": "create",
                "suggestedDraft": {"title": "x", "id": "bulletin-1"},
            },
        )

    assert client.saves == []


def test_the_opener_schema_forbids_canonical_draft_fields() -> None:
    async def run():
        return await org_server.mcp.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}
    schema = tools["open_org_announcements"].inputSchema
    suggested = schema["$defs"]["SuggestedBulletinDraft"]

    assert suggested["additionalProperties"] is False
    assert set(suggested["properties"]) == {
        "type",
        "priority",
        "title",
        "description",
        "primaryAction",
        "secondaryAction",
        "startDate",
        "endDate",
        "audience",
    }


def test_edit_open_loads_the_canonical_record(fake_clients) -> None:
    client, _ = fake_clients(
        _FakeClient(get_result=_config("bulletin-1", status="published"))
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "bulletin-1"},
        )
    )

    assert client.gets == ["bulletin-1"]
    assert payload["mode"] == "edit"
    assert payload["config"]["bulletin"]["id"] == "bulletin-1"
    assert payload["draft"]["id"] == "bulletin-1"
    assert payload["draft"]["startDate"] == "2026-09-01T00:00:00.000Z"


def test_editing_an_expired_announcement_preserves_its_schedule(
    fake_clients,
) -> None:
    fake_clients(
        _FakeClient(
            get_result=_config(
                "bulletin-1", status="published", end_date="2026-08-01T00:00:00.000Z"
            )
        )
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "bulletin-1"},
        )
    )

    assert payload["mode"] == "edit"
    assert payload["draft"]["startDate"] == "2026-09-01T00:00:00.000Z"
    assert payload["draft"]["endDate"] == "2026-08-01T00:00:00.000Z"
    # Canonical state keeps its stored schedule.
    assert payload["config"]["bulletin"]["endDate"] == "2026-08-01T00:00:00.000Z"


@pytest.mark.parametrize(
    "arguments",
    [
        {"view": "manager", "mode": "create"},
        {"view": "manager", "bulletinId": "b"},
        {"view": "manager", "suggestedDraft": {"title": "private"}},
        {"view": "editor"},
        {"view": "editor", "mode": "create", "bulletinId": "b"},
        {"view": "editor", "mode": "edit"},
        {"view": "editor", "mode": "edit", "bulletinId": ""},
        {"view": "editor", "mode": "edit", "bulletinId": " padded "},
        {"view": "editor", "mode": "republish", "bulletinId": "b"},
        {
            "view": "editor",
            "mode": "edit",
            "bulletinId": "b",
            "suggestedDraft": {"title": "x"},
        },
    ],
)
def test_incoherent_opener_arguments_are_tool_errors_before_any_io(
    fake_clients, arguments
) -> None:
    client, directory = fake_clients()
    with pytest.raises(ToolError):
        _call("open_org_announcements", arguments)
    assert client.gets == []
    assert client.lists == 0
    assert directory.tenant_ids == []


def test_open_errors_preserve_the_scoped_request_for_retry(
    fake_clients,
) -> None:
    fake_clients(
        _FakeClient(get_error=org_client.AgentConfigApiError("nope", http_status=404))
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "secret-id"},
        )
    )

    assert payload["view"] == "error"
    assert payload["code"] == "NotFound"
    assert payload["request"] == {
        "titleId": TITLE_ID, "view": "editor", "mode": "edit", "bulletinId": "secret-id"
    }
    assert payload["tenantId"] == TENANT_ID
    assert payload["titleId"] == TITLE_ID


def test_audience_metadata_failure_returns_audience_metadata_unavailable(
    fake_clients,
) -> None:
    fake_clients(
        graph=_FakeGraphClient(
            error=GraphDirectoryError(
                "graph down", code="SearchUnavailable", retryable=True
            )
        )
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {
                "view": "editor",
                "mode": "create",
                "suggestedDraft": {"audience": ["g1"]},
            },
        )
    )

    assert payload["view"] == "error"
    assert payload["code"] == "AudienceMetadataUnavailable"
    assert payload["retryable"] is True


def test_saved_audiences_that_cannot_be_resolved_stay_present_but_invalid(
    fake_clients,
) -> None:
    fake_clients(
        _FakeClient(
            get_result=_config("bulletin-1", audience=["g1", "missing", "g1"])
        ),
        _FakeGraphClient(
            resolved={
                "g1": {
                    "id": "g1",
                    "displayName": "Group One",
                    "mail": None,
                    "isValid": True,
                }
            }
        ),
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "bulletin-1"},
        )
    )

    audience = payload["draft"]["audience"]
    assert [group["id"] for group in audience] == ["g1", "missing", "g1"]
    assert audience[1]["isValid"] is False
    assert audience[1]["displayName"] != "missing"
    assert payload["config"]["audience"] == ["g1", "missing", "g1"]


@pytest.mark.parametrize(
    ("http_status", "expected_code"),
    [
        (401, "AuthenticationRequired"),
        (403, "AuthorizationDenied"),
        (404, "NotFound"),
        (405, "FeatureUnavailable"),
        (503, "NetworkError"),
    ],
)
def test_backend_failures_map_to_discriminated_open_errors(
    fake_clients, http_status, expected_code
) -> None:
    fake_clients(
        _FakeClient(
            get_error=org_client.AgentConfigApiError(
                "boom", http_status=http_status
            )
        )
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "b"},
        )
    )

    assert payload["code"] == expected_code


@pytest.mark.parametrize("backend_code", ["FeatureDisabled", "FeatureNotEnabled"])
def test_a_feature_gated_tenant_reports_feature_unavailable(
    fake_clients, backend_code
) -> None:
    """A disabled tenant is a recoverable unavailable state, not a denial."""
    fake_clients(
        _FakeClient(
            get_error=org_client.AgentConfigApiError(
                f"{backend_code}: Org announcements are off.", http_status=403
            )
        )
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "b"},
        )
    )

    assert payload["code"] == "FeatureUnavailable"
    assert payload["retryable"] is False


def test_open_transport_failure_is_a_retryable_network_error(fake_clients) -> None:
    fake_clients(
        _FakeClient(
            get_error=httpx.ConnectError(
                "down", request=httpx.Request("GET", "https://example.invalid")
            )
        )
    )

    payload = _structured(
        _call(
            "open_org_announcements",
            {"view": "editor", "mode": "edit", "bulletinId": "b"},
        )
    )

    assert payload["code"] == "NetworkError"
    assert payload["retryable"] is True


# --------------------------------------------------------------------------
# save_bulletin
# --------------------------------------------------------------------------


def _save_arguments(**overrides) -> dict[str, Any]:
    arguments = {
        "bulletin": {
            "type": "standard",
            "priority": 1,
            "title": "Quarterly update",
            "description": "Read this",
            "startDate": "2026-09-01T00:00:00.000Z",
            "endDate": "2026-10-01T23:59:59.999Z",
        },
        "audience": ["g1"],
        "status": "draft",
    }
    arguments.update(overrides)
    return arguments


def test_create_sends_complete_content_without_an_identifier(fake_clients) -> None:
    client, _ = fake_clients()

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["status"] == "success"
    assert "id" not in client.saves[0]
    assert client.saves[0]["bulletin"]["title"] == "Quarterly update"
    assert client.saves[0]["audience"] == ["g1"]
    assert client.saves[0]["status"] == "draft"


def test_update_sends_the_identifier_and_complete_state(fake_clients) -> None:
    client, _ = fake_clients()

    _call("save_bulletin", _save_arguments(id="bulletin-1", status="published"))

    assert client.saves[0]["id"] == "bulletin-1"
    assert client.saves[0]["status"] == "published"
    assert client.saves[0]["audience"] == ["g1"]


def test_publish_now_is_expressed_as_a_save_with_the_current_instant(
    fake_clients,
) -> None:
    """Publish now is a save_bulletin call, not a transition."""
    client, _ = fake_clients()

    _call(
        "save_bulletin",
        _save_arguments(
            id="bulletin-1",
            status="published",
            bulletin={
                "type": "standard",
                "priority": 1,
                "title": "Quarterly update",
                "description": "Read this",
                "startDate": "2026-09-04T12:00:00.000Z",
                "endDate": "2026-10-01T23:59:59.999Z",
            },
        ),
    )

    assert client.saves[0]["status"] == "published"
    assert client.saves[0]["bulletin"]["startDate"] == "2026-09-04T12:00:00.000Z"
    assert client.transitions == []


def test_a_draft_with_blank_dates_sends_no_empty_string_to_the_api(
    fake_clients,
) -> None:
    """End-to-end: the widget's ``""`` sentinel never reaches the wire.

    ``EssBulletinInput.startDate``/``endDate`` are nullable ``DateTimeOffset``.
    An empty string fails the backend's model binding, which comes back as an
    opaque 400 rather than the field-bound validation error the widget renders —
    so an ordinary unscheduled Draft would simply be unsaveable.
    """
    client, _ = fake_clients()

    payload = _structured(
        _call(
            "save_bulletin",
            _save_arguments(
                bulletin={
                    "type": "standard",
                    "title": "Quarterly update",
                    "description": "Read this",
                    "startDate": "",
                    "endDate": "   ",
                }
            ),
        )
    )

    assert payload["status"] == "success"
    sent = client.saves[0]
    assert "startDate" not in sent["bulletin"]
    assert "endDate" not in sent["bulletin"]
    # Asserted against the serialized form too: the wire is what binds.
    assert '""' not in json.dumps(sent)


def test_a_published_save_with_blank_dates_still_reaches_the_backend(
    fake_clients,
) -> None:
    """Publish-time completeness stays WeveNova's call, not a contract error."""
    client, _ = fake_clients()

    _call(
        "save_bulletin",
        _save_arguments(
            bulletin={
                "type": "standard",
                "title": "Quarterly update",
                "description": "Read this",
                "startDate": "",
                "endDate": "",
            },
            status="published",
        ),
    )

    # The request was issued rather than rejected locally, so the backend can
    # answer with its own structured AudienceRequired/date codes.
    assert len(client.saves) == 1
    assert client.saves[0]["status"] == "published"
    assert "startDate" not in client.saves[0]["bulletin"]


def test_a_duplicate_of_a_dateless_source_sends_no_empty_string(
    fake_clients,
) -> None:
    """The duplicate path rebuilds the payload from stored content."""
    source = _config("bulletin-1")
    source["bulletin"]["startDate"] = ""
    source["bulletin"]["endDate"] = ""
    client, _ = fake_clients(_FakeClient(get_result=source))

    _call("duplicate_bulletin", {"id": "bulletin-1"})

    sent = client.saves[0]
    # Duplicate forwards stored content verbatim and so never passes through
    # BulletinInput; the sentinel must be stripped on this path explicitly.
    assert "startDate" not in sent["bulletin"]
    assert "endDate" not in sent["bulletin"]
    assert '""' not in json.dumps(sent)
    assert sent["status"] == "draft"
    # Real content is still copied.
    assert sent["bulletin"]["title"] == "Quarterly update"


def test_save_returns_the_canonical_item_and_refreshed_manager_state(
    fake_clients,
) -> None:
    fake_clients()

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["item"]["config"]["bulletin"]["id"] == "created-1"
    assert payload["item"]["audienceMetadata"][0]["id"] == "g1"
    assert "workingSetCount" in payload["manager"]
    assert "archivedTruncated" in payload["manager"]


def test_an_indeterminate_create_is_reported_and_not_retried(fake_clients) -> None:
    client, _ = fake_clients(
        _FakeClient(
            save_error=org_client.IndeterminateWriteError(
                "may have been created; refresh before retrying"
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["status"] == "failure"
    assert payload["errors"][0]["code"] == "IndeterminateWrite"
    assert payload["errors"][0]["retryable"] is False
    assert len(client.saves) == 1


def test_structured_backend_validation_errors_are_preserved(fake_clients) -> None:
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "AudienceRequired: At least one audience is required.",
                http_status=400,
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments(audience=["g1"])))

    assert payload["errors"][0]["code"] == "AudienceRequired"
    assert "At least one audience is required." in payload["errors"][0]["message"]


def test_backend_limit_errors_are_preserved(fake_clients) -> None:
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "BulletinLimitExceeded: Too many announcements.", http_status=409
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["errors"][0]["code"] == "BulletinLimitExceeded"


def test_http_200_validation_errors_are_reported_individually(fake_clients) -> None:
    """Every ``{code, field, message}`` entry survives to the widget."""
    fake_clients(
        _FakeClient(
            save_error=org_client.BulletinValidationError(
                [
                    {
                        "code": "AudienceRequired",
                        "field": "audience",
                        "message": "Pick at least one group.",
                    },
                    {
                        "code": "TitleRequired",
                        "field": "title",
                        "message": "Add a title.",
                    },
                ]
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["status"] == "failure"
    assert [error["code"] for error in payload["errors"]] == [
        "AudienceRequired",
        "TitleRequired",
    ]
    assert [error["field"] for error in payload["errors"]] == [
        "audience",
        "title",
    ]
    assert payload["errors"][1]["message"] == "Add a title."
    # Nothing is flattened into a single generic error.
    assert all(error["retryable"] is False for error in payload["errors"])


def test_a_server_failure_is_not_reported_as_a_validation_error(
    fake_clients,
) -> None:
    """A 500 must not surface the core's ``HttpError`` placeholder as a code."""
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "HttpError: HTTP 500", http_status=500
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    error = payload["errors"][0]
    assert error["code"] == "ServiceError"
    assert error["retryable"] is False
    # Privacy-safe: no raw backend text and no placeholder code leaks out.
    assert "HttpError" not in error["message"]
    assert "500" not in error["message"]


def test_a_400_without_a_backend_code_is_a_generic_invalid_request(
    fake_clients,
) -> None:
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "HttpError: HTTP 400", http_status=400
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["errors"][0]["code"] == "InvalidRequest"


def test_an_unclassified_backend_failure_is_a_stable_service_error(
    fake_clients,
) -> None:
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "Maximum retries exceeded: boom", http_status=None
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["errors"][0]["code"] == "ServiceError"
    assert "boom" not in payload["errors"][0]["message"]


def test_a_feature_code_on_a_server_failure_still_reports_unavailable(
    fake_clients,
) -> None:
    """A genuine backend feature code wins over the HTTP status."""
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "FeatureDisabled: not enabled", http_status=500
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["errors"][0]["code"] == "FeatureUnavailable"


# --------------------------------------------------------------------------
# Committed-write semantics
# --------------------------------------------------------------------------


def test_a_refresh_failure_after_a_committed_save_is_not_retryable(
    fake_clients,
) -> None:
    """The write landed. Retrying an unkeyed create would duplicate it."""
    client, _ = fake_clients(
        _FakeClient(
            list_error=org_client.AgentConfigApiError(
                "HttpError: HTTP 503", http_status=503
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["status"] == "failure"
    summary = payload["errors"][0]
    assert summary["code"] == "CommittedRefreshFailed"
    assert summary["retryable"] is False
    assert "saved" in summary["message"].lower()
    assert "do not repeat the action" in summary["message"].lower()
    # The underlying refresh failure is preserved for diagnosis.
    assert payload["errors"][1]["code"] == "NetworkError"
    # Exactly one write was issued; nothing replayed it.
    assert len(client.saves) == 1


def test_a_graph_failure_after_a_committed_save_is_not_retryable(
    fake_clients,
) -> None:
    client, _ = fake_clients(
        graph=_FakeGraphClient(
            error=GraphDirectoryError(
                "graph down", code="SearchUnavailable", retryable=True
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["errors"][0]["code"] == "CommittedRefreshFailed"
    assert payload["errors"][0]["retryable"] is False
    assert len(client.saves) == 1


def test_a_refresh_failure_after_a_committed_duplicate_is_not_retryable(
    fake_clients,
) -> None:
    """Duplicate is an unkeyed create; a retry would make a second copy."""
    client, _ = fake_clients(
        _FakeClient(
            list_error=org_client.AgentConfigApiError(
                "HttpError: HTTP 503", http_status=503
            )
        )
    )

    payload = _structured(_call("duplicate_bulletin", {"id": "bulletin-1"}))

    assert payload["errors"][0]["code"] == "CommittedRefreshFailed"
    assert payload["errors"][0]["retryable"] is False
    assert len(client.saves) == 1


def test_a_refresh_failure_after_a_committed_transition_is_not_retryable(
    fake_clients,
) -> None:
    client, _ = fake_clients(
        _FakeClient(
            list_error=org_client.AgentConfigApiError(
                "HttpError: HTTP 503", http_status=503
            )
        )
    )

    payload = _structured(
        _call("transition_bulletin", {"id": "bulletin-1", "transition": "archive"})
    )

    assert payload["errors"][0]["code"] == "CommittedRefreshFailed"
    assert payload["errors"][0]["retryable"] is False
    assert client.transitions == [("bulletin-1", "retired")]


def test_a_failed_write_stays_a_normal_retryable_failure(fake_clients) -> None:
    """Nothing committed, so the widget may legitimately offer a retry."""
    fake_clients(
        _FakeClient(
            save_error=org_client.AgentConfigApiError(
                "HttpError: HTTP 503", http_status=503
            )
        )
    )

    payload = _structured(_call("save_bulletin", _save_arguments()))

    assert payload["errors"][0]["code"] == "NetworkError"
    assert payload["errors"][0]["retryable"] is True


def test_save_rejects_an_unknown_content_field(fake_clients) -> None:
    client, _ = fake_clients()

    payload = _structured(
        _call(
            "save_bulletin",
            _save_arguments(
                bulletin={
                    "type": "standard",
                    "title": "t",
                    "description": "d",
                    "id": "sneaky",
                }
            ),
        )
    )

    assert payload["status"] == "failure"
    assert payload["errors"][0]["code"] == "InvalidRequest"
    assert client.saves == []


# --------------------------------------------------------------------------
# transition_bulletin
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("transition", "status"),
    [
        ("archive", "retired"),
        ("unarchive", "draft"),
        ("moveToDraft", "draft"),
        ("delete", "deleted"),
    ],
)
def test_transitions_map_to_minimal_status_payloads(
    fake_clients, transition, status
) -> None:
    client, _ = fake_clients()

    payload = _structured(
        _call("transition_bulletin", {"id": "bulletin-1", "transition": transition})
    )

    assert client.transitions == [("bulletin-1", status)]
    assert client.saves == []
    assert payload["status"] == "success"
    assert "manager" in payload
    # The canonical changed row is included alongside the manager state. It is
    # additive, so a host that strips unknown fields still gets the refresh.
    assert payload["item"]["config"]["bulletin"]["id"] == "bulletin-1"
    assert payload["item"]["config"]["status"] == status


def test_transition_success_keeps_the_manager_shape_intact(fake_clients) -> None:
    """The added item must not disturb the manager contract Vorpal reads."""
    fake_clients(_FakeClient(items=[_config("bulletin-1", audience=["g1"])]))

    payload = _structured(
        _call("transition_bulletin", {"id": "bulletin-1", "transition": "archive"})
    )

    manager = payload["manager"]
    assert set(manager) == {
        "tenantId", "titleId", "items", "workingSetCount", "archivedTruncated"
    }
    assert set(manager["items"][0]) == {"config", "audienceMetadata"}


def test_publish_now_is_not_a_transition_operation(fake_clients) -> None:
    """Publish now must route through save_bulletin, never a transition."""
    client, _ = fake_clients()

    with pytest.raises(ToolError):
        _call(
            "transition_bulletin",
            {"id": "bulletin-1", "transition": "publishNow"},
        )

    assert client.transitions == []
    assert client.saves == []


def test_a_legacy_publish_now_is_rejected_by_host_validation(fake_clients) -> None:
    """Documents where a legacy Vorpal build's ``publishNow`` is stopped.

    KNOWN LIMITATION — host-level, not tool-level. FastMCP validates arguments
    against the schema derived from the tool signature *before* the tool body
    runs, so a legacy ``publishNow`` surfaces as a protocol ``ToolError``, not
    as this server's structured ``InvalidRequest`` result. Converting it would
    mean widening ``transition`` from the four-value enum to a free string,
    which would advertise ``publishNow`` as acceptable in the production schema
    and re-open the concurrent-edit race that removing it closed.

    The mitigation is the rollout prerequisite: ship a Vorpal build that routes
    publish-now through ``save_bulletin``. This test pins the current boundary
    so the behavior is a known, tested contract rather than a surprise, and so
    the day a supported FastMCP pre-validation hook exists the change is
    visible here.
    """
    client, _ = fake_clients()

    with pytest.raises(ToolError) as caught:
        _call(
            "transition_bulletin",
            {"id": "bulletin-1", "transition": "publishNow"},
        )

    # The rejection names the field and the permitted values, so the failure is
    # at least diagnosable from the protocol error text.
    message = str(caught.value)
    assert "transition" in message
    assert "publishNow" in message
    for supported in ("archive", "unarchive", "moveToDraft", "delete"):
        assert supported in message
    # Nothing reached the backend.
    assert client.transitions == []
    assert client.saves == []


def test_title_id_reaches_the_client_but_never_the_save_body(
    fake_clients,
) -> None:
    client, _ = fake_clients()

    payload = _structured(
        _call("save_bulletin", {**_save_arguments(), "titleId": TITLE_ID})
    )

    assert payload["status"] == "success"
    assert len(client.saves) == 1
    assert client.title_ids == [TITLE_ID, TITLE_ID]
    assert payload["tenantId"] == TENANT_ID
    assert payload["titleId"] == TITLE_ID
    assert "titleId" not in client.saves[0]
    assert "titleId" not in client.saves[0]["bulletin"]


def test_the_transition_schema_lists_only_the_supported_operations() -> None:
    async def run():
        return await org_server.mcp.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}
    transition = tools["transition_bulletin"].inputSchema["properties"][
        "transition"
    ]

    assert set(transition["enum"]) == {
        "archive",
        "unarchive",
        "moveToDraft",
        "delete",
    }
    assert "publishNow" not in transition["enum"]


def test_archive_then_unarchive_preserves_content_and_audience(
    fake_clients,
) -> None:
    """Content and audience survive a full Archive -> Unarchive round trip.

    Proven against a *stateful* fake that stores the canonical record and, like
    WeveNova's ``SaveAsync``, mutates only ``status`` on a transition. The
    earlier version of this test asserted only that the client sent no content,
    which cannot distinguish "the backend preserved it" from "there was never
    any content to lose".

    Limitation: this simulates the documented backend behavior. That WeveNova
    genuinely preserves content through these transitions is a live check in the
    target ring — see the backend alignment gate in the dev spec.
    """
    original = _config(
        "bulletin-1", status="published", audience=["g1", "g2", "g1"]
    )
    original["bulletin"]["title"] = "Benefits enrollment"
    original["bulletin"]["description"] = "Enroll before Friday."
    store = {"bulletin-1": copy.deepcopy(original)}
    client, _ = fake_clients(_StatefulFakeClient(store))

    archived = _structured(
        _call("transition_bulletin", {"id": "bulletin-1", "transition": "archive"})
    )
    unarchived = _structured(
        _call("transition_bulletin", {"id": "bulletin-1", "transition": "unarchive"})
    )

    assert client.transitions == [
        ("bulletin-1", "retired"),
        ("bulletin-1", "draft"),
    ]
    # No client-side read/merge/write: the payload carried only {id, status}.
    assert client.saves == []
    assert client.gets == []

    assert archived["item"]["config"]["status"] == "retired"
    assert unarchived["item"]["config"]["status"] == "draft"

    # Everything except status is byte-identical to the original record.
    restored = store["bulletin-1"]
    assert restored["bulletin"] == original["bulletin"]
    # Order and multiplicity are preserved exactly, duplicates included.
    assert restored["audience"] == ["g1", "g2", "g1"]


def test_published_to_draft_preserves_content_through_a_stateful_backend(
    fake_clients,
) -> None:
    original = _config("bulletin-1", status="published", audience=["g1"])
    original["bulletin"]["title"] = "Quarterly all-hands"
    store = {"bulletin-1": copy.deepcopy(original)}
    client, _ = fake_clients(_StatefulFakeClient(store))

    payload = _structured(
        _call(
            "transition_bulletin", {"id": "bulletin-1", "transition": "moveToDraft"}
        )
    )

    assert client.transitions == [("bulletin-1", "draft")]
    assert client.saves == []
    assert payload["item"]["config"]["status"] == "draft"
    assert store["bulletin-1"]["bulletin"] == original["bulletin"]
    assert store["bulletin-1"]["audience"] == ["g1"]


def test_deleted_rows_are_excluded_from_the_manager(fake_clients) -> None:
    fake_clients(
        _FakeClient(
            items=[
                _config("keep-1", status="draft"),
                _config("gone-1", status="deleted"),
            ]
        )
    )

    payload = _structured(_call("open_org_announcements", {"view": "manager"}))

    assert [item["config"]["bulletin"]["id"] for item in payload["items"]] == [
        "keep-1"
    ]
    assert payload["workingSetCount"] == 1


# --------------------------------------------------------------------------
# duplicate_bulletin
# --------------------------------------------------------------------------


def test_duplicate_strips_identity_and_audit_fields_and_creates_a_draft(
    fake_clients,
) -> None:
    source = _config("bulletin-1", status="published", audience=["g1", "g2"])
    source["bulletin"]["modifiedDate"] = "2026-09-02T12:00:00.000Z"
    client, _ = fake_clients(_FakeClient(get_result=source))

    payload = _structured(_call("duplicate_bulletin", {"id": "bulletin-1"}))

    assert client.gets == ["bulletin-1"]
    saved = client.saves[0]
    assert "id" not in saved
    assert "id" not in saved["bulletin"]
    assert "modifiedDate" not in saved["bulletin"]
    assert saved["status"] == "draft"
    assert saved["audience"] == ["g1", "g2"]
    assert saved["bulletin"]["title"] == "Quarterly update"
    assert payload["status"] == "success"


def test_duplicate_of_a_missing_source_is_not_a_create(fake_clients) -> None:
    client, _ = fake_clients(
        _FakeClient(
            get_error=org_client.AgentConfigApiError("gone", http_status=404)
        )
    )

    payload = _structured(_call("duplicate_bulletin", {"id": "bulletin-1"}))

    assert payload["status"] == "failure"
    assert payload["errors"][0]["code"] == "NotFound"
    assert client.saves == []


def test_duplicate_reports_an_indeterminate_write(fake_clients) -> None:
    client, _ = fake_clients(
        _FakeClient(
            save_error=org_client.IndeterminateWriteError(
                "may have been created; refresh before retrying"
            )
        )
    )

    payload = _structured(_call("duplicate_bulletin", {"id": "bulletin-1"}))

    assert payload["errors"][0]["code"] == "IndeterminateWrite"
    assert len(client.saves) == 1


# --------------------------------------------------------------------------
# search_audience_groups
# --------------------------------------------------------------------------


def test_search_returns_eligible_groups(fake_clients) -> None:
    _, graph = fake_clients(
        graph=_FakeGraphClient(
            search_groups_result=[
                {
                    "id": "g1",
                    "displayName": "Finance",
                    "mail": "fin@contoso.com",
                    "isValid": True,
                }
            ]
        )
    )

    payload = _structured(_call("search_audience_groups", {"query": "Finance"}))

    assert payload["status"] == "success"
    assert payload["groups"][0]["id"] == "g1"
    assert graph.search_calls == ["Finance"]


def test_search_reports_exhaustion_and_pages_examined(fake_clients) -> None:
    """A capped search must be distinguishable from an exhausted one.

    Without these fields the caller cannot tell "there are no more matching
    groups" from "the page budget ran out", and would tell the maker a group
    does not exist when it simply was not reached.
    """

    class _CappedGraphClient(_FakeGraphClient):
        async def search_groups(self, query: str) -> dict[str, Any]:
            self.search_calls.append(query)
            return {"groups": [], "exhausted": False, "pagesExamined": 3}

    fake_clients(graph=_CappedGraphClient())

    payload = _structured(_call("search_audience_groups", {"query": "Eng"}))

    assert payload["exhausted"] is False
    assert payload["pagesExamined"] == 3


def test_search_reports_an_exhausted_result_set(fake_clients) -> None:
    fake_clients(graph=_FakeGraphClient())

    payload = _structured(_call("search_audience_groups", {"query": "Eng"}))

    assert payload["exhausted"] is True
    assert payload["pagesExamined"] == 1


def test_search_failures_return_a_discriminated_failure(fake_clients) -> None:
    fake_clients(
        graph=_FakeGraphClient(
            error=GraphDirectoryError(
                "consent required", code="AuthorizationDenied", retryable=False
            )
        )
    )

    payload = _structured(_call("search_audience_groups", {"query": "Finance"}))

    assert payload["status"] == "failure"
    assert payload["code"] == "AuthorizationDenied"
    assert payload["retryable"] is False


def test_search_rejects_an_invalid_query(fake_clients) -> None:
    fake_clients(graph=_FakeGraphClient(error=ValueError("query must be non-empty")))

    payload = _structured(_call("search_audience_groups", {"query": "  "}))

    assert payload["status"] == "failure"
    assert payload["code"] == "InvalidRequest"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_org_announcements", {"view": "manager"}),
        ("save_bulletin", _save_arguments()),
        ("transition_bulletin", {"id": "a", "transition": "archive"}),
        ("duplicate_bulletin", {"id": "a"}),
    ],
)
def test_missing_title_is_a_host_error_before_any_client_call(monkeypatch, tool, arguments) -> None:
    async def forbidden_client():
        pytest.fail("missing title attempted authentication")

    monkeypatch.setattr(org_server, "get_client", forbidden_client)
    with pytest.raises(ToolError, match="titleId"):
        _call(tool, arguments, include_scope=False)


@pytest.mark.parametrize("title_id", ["", " padded ", "\x01", "x" * 257])
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_org_announcements", {"view": "editor", "mode": "create"}),
        ("save_bulletin", _save_arguments()),
        ("transition_bulletin", {"id": "a", "transition": "archive"}),
        ("duplicate_bulletin", {"id": "a"}),
    ],
)
def test_invalid_title_never_acquires_a_client(monkeypatch, title_id, tool, arguments) -> None:
    async def forbidden_client():
        pytest.fail("invalid title attempted authentication")

    monkeypatch.setattr(org_server, "get_client", forbidden_client)
    if tool == "open_org_announcements":
        with pytest.raises(ToolError, match="titleId"):
            _call(tool, {**arguments, "titleId": title_id})
        return
    payload = _structured(_call(tool, {**arguments, "titleId": title_id}))
    assert payload["titleId"] == title_id
    assert "tenantId" not in payload
    assert "item" not in payload
    assert "manager" not in payload
    assert payload.get("code") == "InvalidRequest" or payload["errors"][0]["code"] == "InvalidRequest"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_org_announcements", {"view": "manager"}),
        ("open_org_announcements", {"view": "editor", "mode": "create"}),
        ("open_org_announcements", {"view": "editor", "mode": "edit", "bulletinId": "bulletin-1"}),
        ("save_bulletin", _save_arguments()),
        ("transition_bulletin", {"id": "bulletin-1", "transition": "archive"}),
        ("duplicate_bulletin", {"id": "bulletin-1"}),
    ],
)
def test_success_envelopes_and_reusable_managers_carry_scope(fake_clients, tool, arguments) -> None:
    fake_clients()
    payload = _structured(_call(tool, arguments))
    assert payload["titleId"] == TITLE_ID
    assert payload["tenantId"] == TENANT_ID
    if "manager" in payload:
        assert payload["manager"]["tenantId"] == TENANT_ID
        assert payload["manager"]["titleId"] == TITLE_ID
    if payload.get("config") is not None:
        assert payload["config"]["titleId"] == TITLE_ID
    if "item" in payload:
        assert payload["item"]["config"]["titleId"] == TITLE_ID


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_org_announcements", {"view": "editor", "mode": "create"}),
        ("save_bulletin", _save_arguments()),
        ("transition_bulletin", {"id": "a", "transition": "archive"}),
        ("duplicate_bulletin", {"id": "a"}),
    ],
)
def test_auth_failure_before_tenant_resolution_omits_tenant(monkeypatch, tool, arguments) -> None:
    async def unavailable():
        raise org_client.AgentConfigApiError("Sign in", http_status=401)

    monkeypatch.setattr(org_server, "get_client", unavailable)
    payload = _structured(_call(tool, arguments))
    assert payload["titleId"] == TITLE_ID
    assert "tenantId" not in payload
    assert "manager" not in payload
    assert "item" not in payload
    assert payload.get("code") == "AuthenticationRequired" or payload["errors"][0]["code"] == "AuthenticationRequired"


def test_empty_create_acquires_scope_but_never_reads_or_writes(fake_clients, monkeypatch) -> None:
    client, graph = fake_clients()
    calls = []

    async def get_client():
        calls.append(True)
        return client

    monkeypatch.setattr(org_server, "get_client", get_client)
    payload = _structured(_call("open_org_announcements", {"view": "editor", "mode": "create"}))
    assert calls == [True]
    assert payload["tenantId"] == TENANT_ID
    assert payload["config"] is None
    assert "id" not in payload["draft"]
    assert client.lists == 0
    assert client.gets == client.saves == client.transitions == []
    assert graph.resolve_calls == []


def test_original_suggestion_and_scope_survive_retry_without_logging(fake_clients, caplog) -> None:
    _, graph = fake_clients(graph=_FakeGraphClient(
        error=GraphDirectoryError("unavailable", code="SearchUnavailable", retryable=True)
    ))
    request = {
        "titleId": TITLE_ID,
        "view": "editor",
        "mode": "create",
        "suggestedDraft": {
            "title": "Private retry proposal",
            "startDate": "2026-09-12",
            "audience": ["private-audience"],
        },
    }
    failure = _structured(_call("open_org_announcements", request))
    assert failure["request"] == request
    assert failure["tenantId"] == TENANT_ID
    assert "config" not in failure and "draft" not in failure
    assert "Private retry proposal" not in caplog.text
    assert "private-audience" not in caplog.text
    graph.error = None
    retry = _structured(_call("open_org_announcements", failure["request"]))
    assert retry["titleId"] == TITLE_ID
    assert retry["draft"]["startDate"] == "2026-09-12T00:00:00.000Z"


def test_postcommit_refresh_keeps_the_captured_client_and_scope(fake_clients, monkeypatch) -> None:
    replacement = _FakeClient()
    replacement.tenant_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    async def replacement_client():
        return replacement

    class SwitchingClient(_FakeClient):
        async def save_bulletin(self, title_id, payload):
            saved = await super().save_bulletin(title_id, payload)
            monkeypatch.setattr(org_server, "get_client", replacement_client)
            return saved

    original = SwitchingClient()
    fake_clients(original)
    payload = _structured(_call("save_bulletin", _save_arguments()))
    assert payload["tenantId"] == payload["manager"]["tenantId"] == TENANT_ID
    assert payload["titleId"] == payload["manager"]["titleId"] == TITLE_ID
    assert original.title_ids == [TITLE_ID, TITLE_ID]
    assert replacement.lists == 0


def test_caller_cannot_override_the_token_tenant(fake_clients) -> None:
    fake_clients()
    payload = _structured(_call("open_org_announcements", {
        "view": "manager", "tenantId": "arbitrary-tenant"
    }))
    assert payload["tenantId"] == TENANT_ID


@pytest.mark.parametrize("operation", ["manager", "edit", "duplicate", "save", "transition"])
@pytest.mark.parametrize("response_title", [None, "wrong-agent"])
def test_wrong_scope_is_rejected_before_audience_hydration(
    monkeypatch, fake_clients, operation, response_title
) -> None:
    import base64

    token_payload = base64.urlsafe_b64encode(json.dumps({"tid": TENANT_ID}).encode()).rstrip(b"=")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", f"header.{token_payload.decode()}.signature")
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    config = _config()
    if response_title is None:
        config.pop("titleId")
    else:
        config["titleId"] = response_title
    requests = []

    def handler(request):
        requests.append(request)
        if operation == "manager":
            body = [config]
        elif operation in ("save", "transition"):
            body = {"id": "bulletin-1", "config": config, "errors": []}
        else:
            body = config
        return httpx.Response(200, json=body)

    client = org_client.OrgAnnouncementsClient(transport=httpx.MockTransport(handler))
    _, graph = fake_clients(client)
    tool, arguments = {
        "duplicate": ("duplicate_bulletin", {"id": "bulletin-1"}),
        "manager": ("open_org_announcements", {"view": "manager"}),
        "edit": ("open_org_announcements", {
            "view": "editor", "mode": "edit", "bulletinId": "bulletin-1"
        }),
        "save": ("save_bulletin", {**_save_arguments(), "id": "bulletin-1"}),
        "transition": ("transition_bulletin", {
            "id": "bulletin-1", "transition": "archive"
        }),
    }[operation]
    payload = _structured(_call(tool, arguments))
    assert payload.get("code") == "ServiceError" or payload["errors"][0]["code"] == "ServiceError"
    assert payload["titleId"] == TITLE_ID
    assert "config" not in payload and "item" not in payload and "manager" not in payload
    assert graph.resolve_calls == []
    assert len(requests) == 1
    asyncio.run(client.aclose())


def test_overlapping_opens_do_not_share_an_active_title(fake_clients) -> None:
    class ScopedClient(_FakeClient):
        async def list_bulletins(self, title_id):
            self.title_ids.append(title_id)
            await asyncio.sleep(0)
            return [{**_config("shared-id", audience=[]), "titleId": title_id}]

    client = ScopedClient()
    fake_clients(client)

    async def run():
        return await asyncio.gather(*(
            org_server.mcp.call_tool("open_org_announcements", {
                "titleId": title, "view": "manager"
            })
            for title in ("first-agent", "second-agent")
        ))

    results = asyncio.run(run())
    for title, result in zip(("first-agent", "second-agent"), results):
        payload = _structured(result)
        assert payload["tenantId"] == TENANT_ID
        assert payload["titleId"] == title
        assert payload["items"][0]["config"]["titleId"] == title
    assert client.title_ids == ["first-agent", "second-agent"]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_org_announcements", {"view": "manager"}),
        ("open_org_announcements", {"view": "editor", "mode": "create"}),
        ("open_org_announcements", {
            "view": "editor", "mode": "create", "suggestedDraft": {"audience": ["g1"]}
        }),
        ("open_org_announcements", {
            "view": "editor", "mode": "edit", "bulletinId": "bulletin-1"
        }),
        ("save_bulletin", _save_arguments()),
        ("transition_bulletin", {"id": "bulletin-1", "transition": "archive"}),
        ("duplicate_bulletin", {"id": "bulletin-1"}),
        ("search_audience_groups", {"query": "finance"}),
    ],
)
def test_directory_work_uses_the_captured_authoring_tenant(fake_clients, tool, arguments) -> None:
    client, directory = fake_clients()
    payload = _structured(_call(tool, arguments))
    assert payload.get("status") != "failure"
    assert payload.get("view") != "error"
    assert directory.tenant_ids == [client.tenant_id]
    assert directory.object_ids == [client.object_id]
    if tool == "search_audience_groups":
        assert set(payload) == {"status", "groups", "exhausted", "pagesExamined"}


def test_post_save_directory_refresh_keeps_the_original_authoring_tenant(
    fake_clients, monkeypatch
) -> None:
    replacement = _FakeClient()
    replacement.tenant_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    replacement.object_id = "00000000-0000-0000-0000-000000004444"

    async def replacement_client():
        return replacement

    class SwitchingClient(_FakeClient):
        async def save_bulletin(self, title_id, payload):
            saved = await super().save_bulletin(title_id, payload)
            monkeypatch.setattr(org_server, "get_client", replacement_client)
            return saved

    original = SwitchingClient()
    _, directory = fake_clients(original)
    payload = _structured(_call("save_bulletin", _save_arguments()))
    assert payload["tenantId"] == TENANT_ID
    assert directory.tenant_ids == [TENANT_ID]
    assert directory.object_ids == [OBJECT_ID]
    assert replacement.lists == 0
    assert len(directory.resolve_calls) == 2


def test_search_requires_authoring_context_without_changing_its_result_schema(
    fake_clients, monkeypatch
) -> None:
    _, directory = fake_clients()

    async def unavailable():
        raise org_client.AgentConfigApiError("Sign in", http_status=401)

    monkeypatch.setattr(org_server, "get_client", unavailable)
    payload = _structured(_call("search_audience_groups", {"query": "finance"}))
    assert payload == {
        "status": "failure", "code": "AuthenticationRequired", "retryable": False
    }
    assert directory.tenant_ids == []


@pytest.mark.parametrize("change", ["tenant", "account"])
def test_graph_client_replacement_preserves_inflight_users_and_bounds_idle_state(
    monkeypatch, change
) -> None:
    other_tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" if change == "tenant" else TENANT_ID
    other_object = "00000000-0000-0000-0000-000000004444" if change == "account" else OBJECT_ID
    actual_type = org_server.GraphDirectoryClient
    created = []
    closed = []

    class TrackingClient(actual_type):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created.append(self)

        async def aclose(self):
            closed.append(self)
            await super().aclose()

    monkeypatch.setattr(org_server, "GraphDirectoryClient", TrackingClient)
    monkeypatch.setattr(org_server, "_graph_client", None)
    monkeypatch.setattr(org_server, "_graph_client_users", {})

    async def run():
        async with org_server.get_graph_client(TENANT_ID, OBJECT_ID) as original:
            original._metadata_cache.put("g1", {"id": "g1", "displayName": "tenant A"})
            async with org_server.get_graph_client(TENANT_ID, OBJECT_ID) as same:
                assert same is original
            async with org_server.get_graph_client(other_tenant, other_object) as replacement:
                assert replacement is not original
                assert original.tenant_id == TENANT_ID
                assert replacement.tenant_id == other_tenant
                assert original.object_id == OBJECT_ID
                assert replacement.object_id == other_object
                assert replacement._metadata_cache.get("g1") is None
                replacement._metadata_cache.put("g1", {"id": "g1", "displayName": "tenant B"})
                assert original not in closed
            assert original not in closed
            assert original._metadata_cache.get("g1")["displayName"] == "tenant A"
        assert closed == [original]
        async with org_server.get_graph_client(other_tenant, other_object) as reused:
            assert reused is replacement
            assert reused._metadata_cache.get("g1")["displayName"] == "tenant B"
        assert len(created) == 2
        assert org_server._graph_client_users == {}
        await replacement.aclose()

    asyncio.run(run())


def test_directory_tenant_binding_does_not_add_mcp_arguments() -> None:
    tools = asyncio.run(org_server.mcp.list_tools())
    for tool in tools:
        properties = tool.inputSchema["properties"]
        assert "tenantId" not in properties
        assert "expectedTenantId" not in properties
        assert "objectId" not in properties
        assert "accountId" not in properties
        if tool.name == "search_audience_groups":
            assert set(properties) == {"query"}


_PRIVATE_CACHE_DETAIL = "/private/msal-cache PRIVATE_CREDENTIAL_DETAIL"


def _install_failing_graph_acquisition(monkeypatch, error, *, before_failure=None):
    directory = org_server.GraphDirectoryClient(tenant_id=TENANT_ID, object_id=OBJECT_ID)
    acquisitions = []

    def acquire(tenant_id, object_id):
        acquisitions.append(tenant_id)
        assert object_id == OBJECT_ID
        if before_failure is not None:
            before_failure()
        raise error

    @asynccontextmanager
    async def get_graph_client(tenant_id, object_id):
        assert tenant_id == TENANT_ID
        assert object_id == OBJECT_ID
        try:
            yield directory
        finally:
            await directory.aclose()

    monkeypatch.setattr(
        _ORG_MODULES["graph_directory_client"], "acquire_graph_token", acquire
    )
    monkeypatch.setattr(org_server, "get_graph_client", get_graph_client)
    return acquisitions


def _assert_no_private_cache_detail(result, caplog) -> None:
    content = result[0] if isinstance(result, tuple) else result.content
    for fragment in _PRIVATE_CACHE_DETAIL.split():
        assert fragment not in json.dumps(_structured(result))
        assert all(fragment not in item.text for item in content)
        assert fragment not in caplog.text


@pytest.mark.parametrize("error_type", [LockException, PermissionError])
@pytest.mark.parametrize("tool", ["save_bulletin", "duplicate_bulletin", "transition_bulletin"])
def test_graph_cache_failure_after_commit_preserves_no_repeat_semantics(
    fake_clients, monkeypatch, caplog, error_type, tool
) -> None:
    client, _ = fake_clients()
    arguments = {
        "save_bulletin": _save_arguments(),
        "duplicate_bulletin": {"id": "bulletin-1"},
        "transition_bulletin": {"id": "bulletin-1", "transition": "archive"},
    }[tool]

    def already_committed():
        assert len(client.saves) + len(client.transitions) == 1

    acquisitions = _install_failing_graph_acquisition(
        monkeypatch, error_type(_PRIVATE_CACHE_DETAIL),
        before_failure=already_committed,
    )
    result = _call(tool, arguments)
    payload = _structured(result)
    assert payload["status"] == "failure"
    assert payload["tenantId"] == TENANT_ID
    assert payload["titleId"] == TITLE_ID
    assert payload["errors"][0]["code"] == "CommittedRefreshFailed"
    assert payload["errors"][1]["code"] == "AudienceMetadataUnavailable"
    assert all(error["retryable"] is False for error in payload["errors"])
    assert "do not repeat" in payload["errors"][0]["message"]
    assert len(client.saves) + len(client.transitions) == 1
    assert acquisitions == [TENANT_ID]
    _assert_no_private_cache_detail(result, caplog)


@pytest.mark.parametrize("error_type", [LockException, PermissionError])
@pytest.mark.parametrize(
    ("tool", "arguments", "expected_code"),
    [
        ("search_audience_groups", {"query": "finance"}, "AuthenticationRequired"),
        ("open_org_announcements", {"view": "manager"}, "AudienceMetadataUnavailable"),
        ("open_org_announcements", {
            "view": "editor", "mode": "create", "suggestedDraft": {"audience": ["g1"]}
        }, "AudienceMetadataUnavailable"),
        ("open_org_announcements", {
            "view": "editor", "mode": "edit", "bulletinId": "bulletin-1"
        }, "AudienceMetadataUnavailable"),
    ],
)
def test_graph_cache_failure_preserves_open_and_search_envelopes(
    fake_clients, monkeypatch, caplog, error_type, tool, arguments, expected_code
) -> None:
    client, _ = fake_clients()
    acquisitions = _install_failing_graph_acquisition(
        monkeypatch, error_type(_PRIVATE_CACHE_DETAIL)
    )
    result = _call(tool, arguments)
    payload = _structured(result)
    assert payload["code"] == expected_code
    assert payload["retryable"] is False
    assert "items" not in payload and "config" not in payload
    if tool == "search_audience_groups":
        assert set(payload) == {"status", "code", "retryable"}
        assert payload["status"] == "failure"
    else:
        assert payload["view"] == "error"
        assert payload["tenantId"] == TENANT_ID
        assert payload["request"] == {"titleId": TITLE_ID, **arguments}
    assert client.saves == client.transitions == []
    assert acquisitions == [TENANT_ID]
    _assert_no_private_cache_detail(result, caplog)


@pytest.mark.parametrize("error_type", [LockException, PermissionError])
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("open_org_announcements", {"view": "editor", "mode": "create"}),
        ("save_bulletin", _save_arguments()),
        ("duplicate_bulletin", {"id": "bulletin-1"}),
        ("transition_bulletin", {"id": "bulletin-1", "transition": "archive"}),
        ("search_audience_groups", {"query": "finance"}),
    ],
)
def test_authoring_cache_failure_preserves_feature_envelopes(
    monkeypatch, caplog, error_type, tool, arguments
) -> None:
    attempts = []

    def construct():
        attempts.append(True)
        raise error_type(_PRIVATE_CACHE_DETAIL)

    monkeypatch.setattr(org_server, "_client", None)
    monkeypatch.setattr(org_server, "OrgAnnouncementsClient", construct)
    result = _call(tool, arguments)
    payload = _structured(result)
    assert attempts == [True]
    assert org_server._client is None
    assert not org_server._client_lock.locked()
    assert "tenantId" not in payload
    assert "manager" not in payload and "item" not in payload
    if tool in ("open_org_announcements", "search_audience_groups"):
        assert payload["code"] == "AuthenticationRequired"
        assert payload["retryable"] is False
    else:
        assert payload["status"] == "failure"
        assert payload["errors"][0]["code"] == "AuthenticationRequired"
        assert payload["errors"][0]["retryable"] is False
    if tool != "search_audience_groups":
        assert payload["titleId"] == TITLE_ID
    _assert_no_private_cache_detail(result, caplog)


@pytest.mark.parametrize("error_type", [LockException, PermissionError])
def test_authoring_cache_failure_preserves_its_private_cause(monkeypatch, error_type) -> None:
    original = error_type(_PRIVATE_CACHE_DETAIL)

    def construct():
        raise original

    monkeypatch.setattr(org_server, "_client", None)
    monkeypatch.setattr(org_server, "OrgAnnouncementsClient", construct)

    async def run():
        with pytest.raises(org_server._FailureResult) as caught:
            await org_server.get_client()
        assert caught.value.__cause__ is original
        assert caught.value.code == "AuthenticationRequired"
        assert _PRIVATE_CACHE_DETAIL not in caught.value.message

    asyncio.run(run())
