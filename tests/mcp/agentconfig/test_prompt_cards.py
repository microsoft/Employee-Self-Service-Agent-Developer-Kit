# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline adapter/protocol tests grounded in PromptCardDefinitionsController.

Source contract: WeveNova services/app/Controllers/V1_1/Tenant/
PromptCardDefinitionsController.cs and core/compute/PromptCards/
PromptCardDefinitionValidation.cs. These are not live-deployment/FlightCheck tests.
"""

import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import warnings

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning
from portalocker.exceptions import LockException


ROOT = Path(__file__).parents[3]
MODULE_DIR = ROOT / "solutions" / "ess-maker-skills" / "src" / "mcp" / "agentconfig_prompt_cards"
sys.path.insert(0, str(MODULE_DIR))

from prompt_cards_client import AgentConfigApiError, PromptCardsClient  # noqa: E402
from prompt_cards_models import (  # noqa: E402
    PromptCardCreate, PromptCardDefinition, PromptCardPatch, PromptCardReorder,
)
import base_client  # noqa: E402

spec = importlib.util.spec_from_file_location("prompt_cards_server", MODULE_DIR / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
with warnings.catch_warnings():
    warnings.simplefilter("ignore", IncompleteFieldDefinitionWarning)
    spec.loader.exec_module(server)

TENANT = "00000000-0000-0000-0000-000000001111"
OTHER_TENANT = "00000000-0000-0000-0000-000000002222"
ID = "00000000-0000-0000-0000-000000003333"
TITLE = "test-title"
COLLECTION = f"/weveb2/api/v1.1/tenants('{TENANT}')/EmployeeAgents('{TITLE}')/PromptCardDefinitions"
API_DEFINITION = {
    "DefinitionId": ID, "DefinitionName": "Card prompt", "DataPrompt": "Employee question",
    "PresentationGuidance": None, "Audience": [], "IsDisabled": True, "SortOrder": 0,
}


@pytest.fixture(autouse=True)
def isolate_auth_and_telemetry(monkeypatch):
    claims = base64.urlsafe_b64encode(json.dumps({"tid": TENANT}).encode()).decode().rstrip("=")
    monkeypatch.setattr(base_client, "_resolve_token", lambda: f"header.{claims}.signature")
    monkeypatch.delenv("AGENTCONFIG_BASE_URL", raising=False)
    monkeypatch.setattr(server.adk_telemetry, "emit_api_call", lambda **kwargs: None)
    monkeypatch.setattr(server.adk_telemetry, "initialize_tenant_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_client", None)
    monkeypatch.setattr(server, "_graph_client", None)
    monkeypatch.setattr(server, "_graph_client_users", {})
    monkeypatch.setattr(server, "_client_auth_lock", asyncio.Lock())


def run(awaitable):
    return asyncio.run(awaitable)


def test_routes_and_canonical_payloads():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "PATCH" and request.url.path == COLLECTION:
            return httpx.Response(200, json={"value": [{**API_DEFINITION, "SortOrder": 4}]})
        if request.method == "GET" or (request.method == "PATCH" and request.url.path == COLLECTION):
            return httpx.Response(200, json={"value": [API_DEFINITION]})
        return httpx.Response(201 if request.method == "POST" else 200, json=API_DEFINITION)

    async def scenario():
        client = PromptCardsClient(transport=httpx.MockTransport(handle))
        try:
            baseline = await client.list_definitions(TITLE)
            assert baseline[0].isDisabled is True
            assert baseline[0].audience == []
            await client.create_definition(
                TITLE, PromptCardCreate(definitionName="Card prompt", dataPrompt="Employee question"),
            )
            await client.update_definition(
                TITLE, ID, PromptCardPatch(presentationGuidance=None, audience=None),
            )
            await client.reorder_definitions(
                TITLE, PromptCardReorder(definitions=[{"definitionId": ID, "sortOrder": 4}]),
            )
            await client.delete_definition(TITLE, ID)
        finally:
            await client.aclose()
    run(scenario())
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", f"{COLLECTION}/GetAllDefinitions()"),
        ("POST", COLLECTION), ("PATCH", f"{COLLECTION}('{ID}')"),
        ("PATCH", COLLECTION), ("DELETE", f"{COLLECTION}('{ID}')"),
    ]
    assert all(not request.url.query for request in requests)
    assert json.loads(requests[1].content)["IsDisabled"] is False
    assert json.loads(requests[2].content) == {"PresentationGuidance": None, "Audience": None}
    assert json.loads(requests[3].content) == {"Definitions": [{"DefinitionId": ID, "SortOrder": 4}]}


@pytest.mark.parametrize("changes", [
    {"definitionName": " "}, {"definitionName": "a" * 81},
    {"dataPrompt": " "}, {"dataPrompt": "a" * 2001},
    {"presentationGuidance": "a" * 1001},
    {"audience": ["not-a-guid"]}, {"audience": ["00000000-0000-0000-0000-000000000000"]},
    {"audience": [ID] * 16}, {"sortOrder": -1}, {"sortOrder": True},
    {"sortOrder": "1"}, {"isDisabled": "false"}, {"definitionId": ID},
    {"action": "unsupported"}, {"followUpPrompt": "unsupported"},
    {"definitionName": "\U0001f600" * 41},
])
def test_create_rejects_invalid_authored_contract(changes):
    with pytest.raises(ValidationError):
        PromptCardCreate.model_validate({"definitionName": "Card prompt", "dataPrompt": "Question", **changes})


@pytest.mark.parametrize("patch", [{}, {"definitionId": ID}, {"dataPrompt": None}, {"isDisabled": None}, {"sortOrder": None}])
def test_patch_rejects_empty_immutable_or_null_required_fields(patch):
    with pytest.raises(ValidationError):
        PromptCardPatch.model_validate(patch)


@pytest.mark.parametrize("definitions", [
    [], [{"definitionId": ID, "sortOrder": 0}] * 2,
    [{"definitionId": ID, "sortOrder": 0}] * 101,
    [{"definitionId": ID, "sortOrder": 0}, {"definitionId": OTHER_TENANT, "sortOrder": -1}],
    [{"definitionId": ID, "sortOrder": 0, "isDisabled": True}],
])
def test_entire_reorder_is_validated_before_writes(definitions):
    with pytest.raises(ValidationError):
        PromptCardReorder(definitions=definitions)


@pytest.mark.parametrize("failure", ["network", "gateway"])
def test_create_and_nonatomic_reorder_do_not_replay_ambiguous_failures(failure, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(base_client.asyncio, "sleep", sleep)

    async def scenario():
        for operation in ("create", "reorder"):
            calls = []

            def handle(request):
                calls.append(request)
                if failure == "network":
                    raise httpx.ReadTimeout("response lost", request=request)
                return httpx.Response(503)

            client = PromptCardsClient(transport=httpx.MockTransport(handle))
            try:
                with pytest.raises((httpx.RequestError, AgentConfigApiError)):
                    if operation == "create":
                        await client.create_definition(
                            TITLE, PromptCardCreate(definitionName="Card prompt", dataPrompt="Question"),
                        )
                    else:
                        await client.reorder_definitions(
                            TITLE, PromptCardReorder(definitions=[{"definitionId": ID, "sortOrder": 1}]),
                        )
                assert len(calls) == 1
            finally:
                await client.aclose()
    run(scenario())
    sleep.assert_not_awaited()


def test_escaped_title_and_invalid_definition_id():
    client = PromptCardsClient()
    assert "O%27%27Brien%2Ftitle" in client._definitions_path("O'Brien/title")
    with pytest.raises(ValidationError):
        client._definition_path(TITLE, "not-a-guid")


def test_protocol_tools_visibility_schemas_and_resource():
    tools = {tool.name: tool for tool in run(server.mcp.list_tools())}
    assert set(tools) == {
        "open_prompt_cards", "list_prompt_card_definitions", "create_prompt_card_definition",
        "update_prompt_card_definition", "reorder_prompt_card_definitions", "delete_prompt_card_definition",
        "report_client_events", "search_audience_groups", "resolve_audience_groups",
    }
    assert tools["open_prompt_cards"].meta["ui"]["resourceUri"] == server.RESOURCE_URI
    assert tools["open_prompt_cards"].annotations.readOnlyHint
    assert "Open Card Prompts" in tools["open_prompt_cards"].description
    assert "Save for later" in tools["create_prompt_card_definition"].description
    search = tools["search_audience_groups"]
    assert search.annotations.readOnlyHint
    assert search.annotations.idempotentHint
    assert search.meta["ui"]["visibility"] == ["model", "app"]
    assert search.inputSchema["required"] == ["query"]
    resolve = tools["resolve_audience_groups"]
    assert resolve.annotations.readOnlyHint
    assert resolve.annotations.idempotentHint
    assert resolve.meta["ui"]["visibility"] == ["app"]
    assert resolve.inputSchema["required"] == ["groupIds"]
    for name in set(tools) - {
        "open_prompt_cards", "list_prompt_card_definitions", "report_client_events",
        "search_audience_groups", "resolve_audience_groups",
    }:
        assert tools[name].meta["ui"]["visibility"] == ["app"]
        assert {"tenantId", "titleId"} <= set(tools[name].inputSchema["required"])
    create_schema = tools["create_prompt_card_definition"].inputSchema
    assert create_schema["$defs"]["PromptCardCreate"]["additionalProperties"] is False
    assert "definitionId" not in create_schema["$defs"]["PromptCardCreate"]["properties"]
    resources = run(server.mcp.list_resources())
    assert str(resources[0].uri) == server.RESOURCE_URI
    assert resources[0].name == "Card Prompts"
    assert resources[0].title == "Card Prompts"
    assert resources[0].meta["ui"]["csp"]["connectDomains"] == []
    assert "/mcp-widget/prompt-cards/widget.js" in server.prompt_cards_widget()


def test_resource_read_remains_responsive_during_shared_authoring_sign_in(monkeypatch):
    started = Event()
    release = Event()
    client = SimpleNamespace(
        tenant_id=TENANT, object_id=ID, validate_scope=lambda *args: None,
        list_definitions=AsyncMock(return_value=[]),
    )

    def authenticate():
        started.set()
        release.wait(timeout=5)
        return client

    constructor = Mock(side_effect=authenticate)
    monkeypatch.setattr(server, "PromptCardsClient", constructor)
    graph = Mock(
        tenant_id=TENANT, object_id=ID,
        search_groups=AsyncMock(return_value={
            "groups": [], "exhausted": True, "pagesExamined": 1,
        }),
    )
    monkeypatch.setattr(server, "GraphDirectoryClient", lambda **kwargs: graph)

    async def scenario():
        opened = asyncio.create_task(server.mcp.call_tool("open_prompt_cards", {"titleId": TITLE}))
        searched = asyncio.create_task(server.mcp.call_tool("search_audience_groups", {"query": "group"}))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            resource = await server.mcp.read_resource(server.RESOURCE_URI)
            assert "mcp-root" in resource[0].content
            assert not opened.done()
            assert not searched.done()
        finally:
            release.set()
            results = await asyncio.gather(opened, searched)
        assert all(not result.isError for result in results)
        constructor.assert_called_once()

    run(scenario())


def test_audience_dispatch_reuses_announcements_group_policy_and_authenticated_scope(monkeypatch):
    claims = base64.urlsafe_b64encode(
        json.dumps({"tid": TENANT, "oid": ID}).encode(),
    ).decode().rstrip("=")
    token = f"header.{claims}.signature"
    monkeypatch.setattr(base_client, "_resolve_token", lambda: token)
    client = PromptCardsClient()
    monkeypatch.setattr(server, "get_client", lambda: client)
    requests = []
    distribution_id = "00000000-0000-0000-0000-000000005555"

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.headers["ConsistencyLevel"] == "eventual"
        assert request.url.params["$search"] == '"displayName:Finance" OR "mail:Finance"'
        return httpx.Response(200, json={"value": [
            {"id": ID, "displayName": "Finance security", "groupTypes": [], "securityEnabled": True},
            {"id": distribution_id, "displayName": "Finance distribution", "groupTypes": [], "mailEnabled": True},
            {"id": ID, "displayName": "Duplicate", "groupTypes": [], "securityEnabled": True},
            {"id": OTHER_TENANT, "displayName": "Unified", "groupTypes": ["Unified"], "mailEnabled": True},
            {"id": OTHER_TENANT, "displayName": "Dynamic", "groupTypes": ["DynamicMembership"], "securityEnabled": True},
        ]})

    graph_client = server.GraphDirectoryClient(
        tenant_id=TENANT, object_id=ID, access_token=token,
        transport=httpx.MockTransport(handle),
    )
    monkeypatch.setattr(server, "_graph_client", graph_client)

    async def scenario():
        try:
            result = await server.mcp.call_tool("search_audience_groups", {"query": "Finance"})
            payload = result.structuredContent
            assert payload == {
                "status": "success",
                "groups": [
                    {"id": ID, "displayName": "Finance security", "mail": None, "isValid": True},
                    {"id": distribution_id, "displayName": "Finance distribution", "mail": None, "isValid": True},
                ],
                "exhausted": True, "pagesExamined": 1,
            }
            assert len(requests) == 1
            assert requests[0].url.host == "graph.microsoft.com"
        finally:
            await graph_client.aclose()
            await client.aclose()
    run(scenario())


def test_saved_audience_names_use_authenticated_directory_metadata_and_preserve_missing_ids(monkeypatch):
    claims = base64.urlsafe_b64encode(
        json.dumps({"tid": TENANT, "oid": ID}).encode(),
    ).decode().rstrip("=")
    token = f"header.{claims}.signature"
    monkeypatch.setattr(server, "get_client", lambda: SimpleNamespace(tenant_id=TENANT, object_id=ID))
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.url.params["$filter"] == f"id eq '{OTHER_TENANT}' or id eq '{ID}'"
        return httpx.Response(200, json={"value": [
            {"id": ID, "displayName": "Engineering", "groupTypes": [], "securityEnabled": True},
            {"id": OTHER_TENANT, "displayName": "Unified", "groupTypes": ["Unified"], "mailEnabled": True},
        ]})

    graph_client = server.GraphDirectoryClient(
        tenant_id=TENANT, object_id=ID, access_token=token,
        transport=httpx.MockTransport(handle),
    )
    monkeypatch.setattr(server, "_graph_client", graph_client)

    async def scenario():
        try:
            result = await server.mcp.call_tool("resolve_audience_groups", {"groupIds": [OTHER_TENANT, ID]})
            assert not result.isError
            assert result.structuredContent == {
                "status": "success",
                "groups": [
                    {"id": OTHER_TENANT, "displayName": "Unavailable group", "mail": None, "isValid": False},
                    {"id": ID, "displayName": "Engineering", "mail": None, "isValid": True},
                ],
            }
            await server.mcp.call_tool("resolve_audience_groups", {"groupIds": [ID]})
            assert len(requests) == 1
        finally:
            await graph_client.aclose()
    run(scenario())


@pytest.mark.parametrize("group_ids", [
    [], [ID] * 16, ["not-a-guid"], ["00000000-0000-0000-0000-000000000000"],
])
def test_invalid_saved_audience_ids_are_rejected_before_authentication(group_ids, monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda: pytest.fail("Invalid IDs must be rejected before authentication"))
    with pytest.raises(ToolError, match="validation"):
        run(server.mcp.call_tool("resolve_audience_groups", {"groupIds": group_ids}))


@pytest.mark.parametrize("query", ["", " ", "a" * 257, "private\nquery"])
def test_audience_invalid_query_does_not_authenticate(query, monkeypatch):
    def fail():
        pytest.fail("Invalid queries must be rejected before authentication")
    monkeypatch.setattr(server, "get_client", fail)
    result = run(server.search_audience_groups(query))
    assert result.isError
    assert result.structuredContent == {"status": "failure", "code": "InvalidRequest", "retryable": False}
    if query.strip():
        assert query not in result.model_dump_json()


@pytest.mark.parametrize("tool_name, argument, operation", [
    ("search_audience_groups", "private query", "searchAudienceGroups"),
    ("resolve_audience_groups", [ID], "resolveAudienceGroups"),
])
def test_audience_failures_preserve_contract_and_content_free_telemetry(tool_name, argument, operation, monkeypatch):
    client = SimpleNamespace(tenant_id=TENANT, object_id=ID)
    monkeypatch.setattr(server, "get_client", lambda: client)
    telemetry = []
    monkeypatch.setattr(server.adk_telemetry, "emit_api_call", lambda **kwargs: telemetry.append(kwargs))
    graph_client = Mock(
        tenant_id=TENANT, object_id=ID,
        search_groups=AsyncMock(side_effect=server.GraphDirectoryError(
            "private group and query", code="AuthorizationDenied", retryable=False,
        )),
        resolve_groups=AsyncMock(side_effect=server.GraphDirectoryError(
            "private group and query", code="AuthorizationDenied", retryable=False,
        )),
    )
    monkeypatch.setattr(server, "_graph_client", graph_client)
    result = run(getattr(server, tool_name)(argument))
    assert result.isError
    assert result.structuredContent == {"status": "failure", "code": "AuthorizationDenied", "retryable": False}
    assert "private" not in result.model_dump_json()
    assert telemetry[0]["api_endpoint"] == f"PromptCardDefinitions.{operation}"
    assert telemetry[0]["outcome"] == "failure"
    assert set(telemetry[0]) == {"api_endpoint", "outcome", "latency_ms"}


def test_audience_missing_identity_returns_authentication_failure(monkeypatch):
    client = SimpleNamespace(tenant_id=TENANT, object_id=None)
    monkeypatch.setattr(server, "get_client", lambda: client)
    result = run(server.search_audience_groups("Finance"))
    assert result.isError
    assert result.structuredContent == {"status": "failure", "code": "AuthenticationRequired", "retryable": False}


@pytest.mark.parametrize("error", [
    ValueError("private credential details"), LockException("private cache path"),
    PermissionError("private token file"),
])
def test_audience_authentication_failures_are_sanitized(error, monkeypatch):
    def fail():
        raise error
    monkeypatch.setattr(server, "get_client", fail)
    result = run(server.search_audience_groups("Finance"))
    assert result.isError
    assert result.structuredContent == {"status": "failure", "code": "AuthenticationRequired", "retryable": False}
    assert "private" not in result.model_dump_json()


def test_audience_identity_switch_keeps_captured_client_until_lease_completes(monkeypatch):
    def make_client(**identity):
        return Mock(**identity, aclose=AsyncMock())

    monkeypatch.setattr(server, "GraphDirectoryClient", make_client)

    async def scenario():
        async with server.get_graph_client(TENANT, ID) as first:
            async with server.get_graph_client(OTHER_TENANT, ID) as second:
                first.aclose.assert_not_awaited()
                assert second is not first
                assert second.tenant_id == OTHER_TENANT
            first.aclose.assert_not_awaited()
        first.aclose.assert_awaited_once()
        second.aclose.assert_not_awaited()
        assert server._graph_client_users == {}
    run(scenario())


def test_open_list_scope_and_tenant_mismatch(monkeypatch):
    client = PromptCardsClient()
    client.list_definitions = AsyncMock(return_value=[
        PromptCardDefinition.model_validate({
            "definitionId": ID, "definitionName": "Card prompt", "dataPrompt": "Question", "isDisabled": True,
            "sortOrder": 0,
        }),
    ])
    monkeypatch.setattr(server, "get_client", lambda: client)
    opened = run(server.open_prompt_cards(TITLE))
    assert opened.structuredContent["tenantId"] == TENANT
    assert opened.structuredContent["titleId"] == TITLE
    assert opened.structuredContent["definitions"][0]["isDisabled"] is True
    assert opened.content[0].text == "Card prompts loaded."
    mismatch = run(server.list_prompt_card_definitions(OTHER_TENANT, TITLE))
    assert mismatch.isError
    assert mismatch.structuredContent["tenantId"] == TENANT
    assert mismatch.structuredContent["errors"][0]["code"] == "InvalidRequest"
    assert "card prompt fields" in mismatch.structuredContent["errors"][0]["message"]
    assert client.list_definitions.await_count == 1


def test_save_for_later_and_submit_persist_disabled_state(monkeypatch):
    stored = PromptCardDefinition(
        definitionId=ID, definitionName="Card prompt", dataPrompt="Question",
        isDisabled=False, sortOrder=0,
    )
    client = SimpleNamespace(
        tenant_id=TENANT, validate_scope=lambda *args: None,
        create_definition=AsyncMock(return_value=stored),
        update_definition=AsyncMock(return_value=stored),
    )
    monkeypatch.setattr(server, "get_client", lambda: client)
    for disabled in (True, False):
        result = run(server.create_prompt_card_definition(
            TENANT, TITLE,
            PromptCardCreate(definitionName="Card prompt", dataPrompt="Question", isDisabled=disabled),
        ))
        assert not result.isError
        assert result.content[0].text == "Card prompts saved."
        assert client.create_definition.await_args.args[1].isDisabled is disabled
        run(server.update_prompt_card_definition(
            TENANT, TITLE, ID, PromptCardPatch(isDisabled=disabled),
        ))
        assert client.update_definition.await_args.args[2].model_dump(exclude_unset=True) == {"isDisabled": disabled}


@pytest.mark.parametrize("operation", ["create", "reorder", "delete"])
def test_failures_preserve_scope_and_require_reconciliation_without_leaking_content(monkeypatch, operation):
    error = AgentConfigApiError("secret prompt and group-id", http_status=503)
    client = SimpleNamespace(
        tenant_id=TENANT, validate_scope=lambda *args: None,
        create_definition=AsyncMock(side_effect=error),
        reorder_definitions=AsyncMock(side_effect=error),
        delete_definition=AsyncMock(side_effect=error),
    )
    telemetry = []
    monkeypatch.setattr(server, "get_client", lambda: client)
    monkeypatch.setattr(server.adk_telemetry, "emit_api_call", lambda **kwargs: telemetry.append(kwargs))
    if operation == "create":
        call = server.create_prompt_card_definition(
            TENANT, TITLE, PromptCardCreate(definitionName="Card prompt", dataPrompt="secret prompt"),
        )
    elif operation == "reorder":
        call = server.reorder_prompt_card_definitions(
            TENANT, TITLE, [{"definitionId": ID, "sortOrder": 1}],
        )
    else:
        call = server.delete_prompt_card_definition(TENANT, TITLE, ID)
    result = run(call)
    assert result.isError
    assert result.structuredContent["outcome"] == ("partial" if operation == "reorder" else "unknown")
    assert result.structuredContent["errors"][0]["retryable"] is False
    assert result.structuredContent["tenantId"] == TENANT
    assert result.structuredContent["titleId"] == TITLE
    assert "secret prompt" not in result.model_dump_json()
    assert "group-id" not in result.model_dump_json()
    assert telemetry[0]["api_endpoint"] == f"PromptCardDefinitions.{operation}"
    assert set(telemetry[0]) == {"api_endpoint", "outcome", "latency_ms"}


def test_client_events_bridge_uses_shared_validation_and_preserves_verdict(monkeypatch):
    seen = []

    def report(envelope):
        seen.append(envelope)
        return {"status": "accepted", "acceptedEventCount": 1}

    monkeypatch.setattr(server.adk_telemetry, "report_client_events", report)
    result = run(server.report_client_events(appName="PromptCards", events=[{"name": "mount"}]))
    assert not result.isError
    assert result.structuredContent["status"] == "accepted"
    assert seen[0]["appName"] == "PromptCards"
    assert "toolCallId" not in seen[0]
    monkeypatch.setattr(server.adk_telemetry, "report_client_events", lambda _: {"status": "rejected"})
    assert run(server.report_client_events()).isError


def test_sdk_tool_dispatch_preserves_partial_patch_and_scoped_results(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"value": [API_DEFINITION]})
        return httpx.Response(200, json=API_DEFINITION)

    client = PromptCardsClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(server, "get_client", lambda: client)

    async def scenario():
        try:
            result = await server.mcp.call_tool("open_prompt_cards", {"titleId": TITLE})
            assert result.structuredContent["tenantId"] == TENANT
            result = await server.mcp.call_tool("update_prompt_card_definition", {
                "tenantId": TENANT, "titleId": TITLE, "definitionId": ID,
                "patch": {"presentationGuidance": None, "isDisabled": False},
            })
            assert not result.isError
            assert result.structuredContent["definition"]["definitionId"] == ID
            result = await server.mcp.call_tool("reorder_prompt_card_definitions", {
                "tenantId": TENANT, "titleId": TITLE,
                "definitions": [{"definitionId": ID, "sortOrder": 3}],
            })
            # The mock deliberately returns an item, not the collection contract.
            assert result.isError
            assert result.structuredContent["outcome"] == "partial"
            resource = await server.mcp.read_resource(server.RESOURCE_URI)
            assert "mcp-root" in resource[0].content
        finally:
            await client.aclose()
    run(scenario())
    assert json.loads(requests[1].content) == {"PresentationGuidance": None, "IsDisabled": False}
    assert json.loads(requests[2].content) == {"Definitions": [{"DefinitionId": ID, "SortOrder": 3}]}


def test_malformed_success_response_is_ambiguous_not_invalid_input(monkeypatch):
    client = PromptCardsClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(201, content=b"not JSON"),
    ))
    monkeypatch.setattr(server, "get_client", lambda: client)

    async def scenario():
        try:
            return await server.create_prompt_card_definition(
                TENANT, TITLE, PromptCardCreate(definitionName="Card prompt", dataPrompt="Question"),
            )
        finally:
            await client.aclose()
    result = run(scenario())
    assert result.isError
    assert result.structuredContent["outcome"] == "unknown"
    assert result.structuredContent["errors"][0]["code"] == "PromptCardsApiError"


@pytest.mark.parametrize("audience", [None, []])
def test_response_audience_is_always_an_array(audience):
    stored = PromptCardDefinition.model_validate({
        "definitionId": ID, "definitionName": "Card prompt", "dataPrompt": "Question",
        "audience": audience, "isDisabled": False, "sortOrder": 0,
    })
    assert stored.model_dump()["audience"] == []
    assert PromptCardPatch(audience=None).model_dump(exclude_unset=True) == {"audience": None}


@pytest.mark.parametrize("operation", ["update", "reorder"])
def test_mismatched_response_identity_is_not_success(operation):
    async def scenario():
        client = PromptCardsClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=(
                {**API_DEFINITION, "DefinitionId": OTHER_TENANT} if operation == "update"
                else {"value": [API_DEFINITION]}
            )),
        ))
        try:
            with pytest.raises(AgentConfigApiError, match="does not match"):
                if operation == "update":
                    await client.update_definition(TITLE, ID, PromptCardPatch(isDisabled=False))
                else:
                    await client.reorder_definitions(
                        TITLE, PromptCardReorder(definitions=[{"definitionId": ID, "sortOrder": 5}]),
                    )
        finally:
            await client.aclose()
    run(scenario())


def test_authorization_failure_does_not_suggest_automatic_retry(monkeypatch):
    client = SimpleNamespace(
        tenant_id=TENANT, validate_scope=lambda *args: None,
        list_definitions=AsyncMock(side_effect=AgentConfigApiError("Forbidden", http_status=403)),
    )
    monkeypatch.setattr(server, "get_client", lambda: client)
    result = run(server.list_prompt_card_definitions(TENANT, TITLE))
    assert result.isError
    assert result.structuredContent["errors"][0]["retryable"] is False


def test_unresolved_authentication_does_not_echo_untrusted_tenant(monkeypatch):
    def fail():
        raise ValueError("No matching token")
    monkeypatch.setattr(server, "get_client", fail)
    result = run(server.list_prompt_card_definitions(OTHER_TENANT, TITLE))
    assert result.isError
    assert result.structuredContent["tenantId"] is None
