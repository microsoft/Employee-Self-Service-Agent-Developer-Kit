# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the WeveNova Org Announcements authoring client."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest


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

from _mcp_modules import load_org_announcements_client_modules  # noqa: E402

_ORG_MODULES = load_org_announcements_client_modules()

org_client = _ORG_MODULES["client"]


TENANT_ID = "11111111-2222-3333-4444-555555555555"
TITLE_ID = "title-1"
BASE_URL = "https://substrate.office.com/weveb2/api/v1.1"
COLLECTION_PATH = f"/weveb2/api/v1.1/tenants('{TENANT_ID}')/EmployeeAgents('{TITLE_ID}')/essbulletins"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
_UNSET = object()


def _token(tenant_id: str = TENANT_ID) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id}).encode("utf-8")
    ).rstrip(b"=")
    return f"header.{payload.decode('ascii')}.signature"


def _make_client(monkeypatch, handler, *, tenant_id=TENANT_ID) -> org_client.OrgAnnouncementsClient:
    monkeypatch.setenv("ORG_ANNOUNCEMENTS_BASE_URL", BASE_URL)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token(tenant_id))
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    return org_client.OrgAnnouncementsClient(
        transport=httpx.MockTransport(handler)
    )


def _config(
    bulletin_id: str,
    *,
    status: str = "draft",
    end_date: str | None = None,
    audience: list[str] | None = None,
    title_id: str = TITLE_ID,
) -> dict:
    return {
        "titleId": title_id,
        "bulletin": {
            "id": bulletin_id,
            "type": "standard",
            "priority": 1,
            "title": "Announcement",
            "description": "Body",
            "startDate": "2026-09-01T00:00:00.000Z",
            **({"endDate": end_date} if end_date else {}),
        },
        "audience": audience if audience is not None else ["group-a"],
        "status": status,
        "createdBy": "admin@contoso.com",
        "createdOn": "2026-08-01T12:00:00.000Z",
        "modifiedDate": "2026-09-02T12:00:00.000Z",
    }


def _save_result(
    bulletin_id: str,
    *,
    status: str = "draft",
    errors: list[dict] | None = None,
    config: dict | None = None,
    result_id: str | None = _UNSET,
) -> dict:
    """Build an ``EssBulletinSaveResult`` exactly as WeveNova returns it.

    Save answers HTTP 200 with ``{id, config, errors}`` — a different shape from
    the bare configs list/load return — so every save-path test speaks that
    envelope rather than the load shape.
    """
    envelope: dict = {
        "id": bulletin_id if result_id is _UNSET else result_id,
        "config": config if config is not None else _config(bulletin_id, status=status),
        "errors": errors if errors is not None else [],
    }
    return envelope


def test_uses_agent_qualified_v11_routes_with_tenant_from_token(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/save"):
            return httpx.Response(200, json=_save_result("new-1"))
        if request.url.path.endswith("/essbulletins"):
            return httpx.Response(200, json=[_config("a")])
        return httpx.Response(200, json=_config("a"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.list_bulletins(TITLE_ID)
        await client.get_bulletin(TITLE_ID, "a")
        await client.save_bulletin(TITLE_ID, {"bulletin": {}, "audience": [], "status": "draft"})
        await client.aclose()

    asyncio.run(run())

    assert client.tenant_id == TENANT_ID
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", COLLECTION_PATH),
        ("GET", f"{COLLECTION_PATH}/a"),
        ("POST", f"{COLLECTION_PATH}/save"),
    ]


def test_title_id_is_a_required_route_key_not_a_query_filter(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[_config("a")])

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.list_bulletins(TITLE_ID)
        await client.aclose()

    asyncio.run(run())

    assert captured[0].url.path == COLLECTION_PATH
    assert captured[0].url.query == b""


@pytest.mark.parametrize("bad_id", ["", " a", "a/b", "a\\b", "a?b", "a\x01b"])
def test_rejects_ids_that_could_reshape_the_route(monkeypatch, bad_id) -> None:
    client = _make_client(
        monkeypatch, lambda request: httpx.Response(200, json=_config("a"))
    )

    async def run() -> None:
        with pytest.raises(ValueError):
            await client.get_bulletin(TITLE_ID, bad_id)
        await client.aclose()

    asyncio.run(run())


def test_unkeyed_create_is_not_retried_and_reports_indeterminate(
    monkeypatch,
) -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(503, json={"Code": "Busy", "Message": "try later"})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.IndeterminateWriteError):
            await client.save_bulletin(TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "draft"}
            )
        await client.aclose()

    asyncio.run(run())

    assert len(attempts) == 1, "an unkeyed create must not be replayed"


def test_unkeyed_create_network_failure_reports_indeterminate(monkeypatch) -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection reset", request=request)

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.IndeterminateWriteError):
            await client.save_bulletin(TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "draft"}
            )
        await client.aclose()

    asyncio.run(run())

    assert len(attempts) == 1


def test_keyed_update_retries_a_transient_gateway_failure(monkeypatch) -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"Code": "Busy", "Message": "later"})
        return httpx.Response(200, json=_save_result("a"))

    client = _make_client(monkeypatch, handler)
    client.max_retries = 2

    async def run() -> None:
        result = await client.save_bulletin(TITLE_ID,
            {"id": "a", "bulletin": {}, "audience": [], "status": "draft"}
        )
        assert result["bulletin"]["id"] == "a"
        await client.aclose()

    asyncio.run(run())

    assert len(attempts) == 2


def test_definite_rejection_is_not_reported_as_indeterminate(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"Code": "AudienceRequired", "Message": "audience required"}
        )

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError) as caught:
            await client.save_bulletin(TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "draft"}
            )
        assert not isinstance(caught.value, org_client.IndeterminateWriteError)
        assert "AudienceRequired" in str(caught.value)
        await client.aclose()

    asyncio.run(run())


def test_transition_sends_only_identity_and_status(monkeypatch) -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=_save_result("a", status="retired"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        changed = await client.transition_bulletin(TITLE_ID, "a", "retired")
        # The envelope is unwrapped to the canonical config, not passed through.
        assert changed["bulletin"]["id"] == "a"
        assert changed["status"] == "retired"
        assert "config" not in changed
        await client.aclose()

    asyncio.run(run())

    assert captured == [{"id": "a", "status": "retired"}]
    assert "bulletin" not in captured[0]
    assert "audience" not in captured[0]


# --------------------------------------------------------------------------
# EssBulletinSaveResult envelope
# --------------------------------------------------------------------------


def test_save_unwraps_the_canonical_config_from_the_result_envelope(
    monkeypatch,
) -> None:
    """A successful save returns ``config``, never the wrapper itself."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_save_result("created-1"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        saved = await client.save_bulletin(TITLE_ID,
            {"bulletin": {}, "audience": [], "status": "draft"}
        )
        assert saved == _config("created-1")
        # The wrapper's own keys must not leak into canonical state.
        assert "config" not in saved
        assert "errors" not in saved
        await client.aclose()

    asyncio.run(run())


def test_http_200_with_errors_is_a_structured_validation_failure(
    monkeypatch,
) -> None:
    """Validation failure arrives inside a 200; every entry must survive."""
    reported = [
        {"code": "AudienceRequired", "field": "audience", "message": "Pick a group."},
        {"code": "TitleRequired", "field": "title", "message": "Add a title."},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": None, "config": None, "errors": reported}
        )

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.BulletinValidationError) as caught:
            await client.save_bulletin(TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "published"}
            )
        assert caught.value.errors == reported
        assert caught.value.http_status == 200
        await client.aclose()

    asyncio.run(run())


def test_a_partial_error_entry_keeps_its_field_and_gets_a_stable_code(
    monkeypatch,
) -> None:
    """A sparse entry is still reported; it is never dropped or merged."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": None,
                "config": None,
                "errors": [{"field": "title"}, "unstructured"],
            },
        )

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.BulletinValidationError) as caught:
            await client.save_bulletin(TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "draft"}
            )
        assert len(caught.value.errors) == 2
        assert caught.value.errors[0]["field"] == "title"
        assert caught.value.errors[0]["code"] == "InvalidRequest"
        assert caught.value.errors[1]["message"] == "unstructured"
        await client.aclose()

    asyncio.run(run())


def test_a_success_envelope_without_a_config_is_rejected(monkeypatch) -> None:
    """No errors and no config is malformed, never an empty announcement."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "a", "config": None, "errors": []})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.save_bulletin(TITLE_ID,
                {"id": "a", "bulletin": {}, "audience": [], "status": "draft"}
            )
        await client.aclose()

    asyncio.run(run())


def test_a_save_result_id_disagreeing_with_its_config_is_rejected(
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_save_result("a", config=_config("b"), result_id="a")
        )

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError) as caught:
            await client.save_bulletin(TITLE_ID,
                {"id": "a", "bulletin": {}, "audience": [], "status": "draft"}
            )
        assert "does not match" in str(caught.value)
        await client.aclose()

    asyncio.run(run())


def test_an_update_answered_with_a_different_record_is_rejected(
    monkeypatch,
) -> None:
    """Replacing canonical state with someone else's announcement is a bug."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_save_result("other-1"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError) as caught:
            await client.save_bulletin(TITLE_ID,
                {"id": "a", "bulletin": {}, "audience": [], "status": "draft"}
            )
        assert "different announcement" in str(caught.value)
        await client.aclose()

    asyncio.run(run())


def test_a_transition_answered_for_another_record_is_rejected(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_save_result("other-1", status="retired"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.transition_bulletin(TITLE_ID, "a", "retired")
        await client.aclose()

    asyncio.run(run())


def test_a_transition_rejected_by_validation_preserves_its_codes(
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "a",
                "config": None,
                "errors": [
                    {
                        "code": "InvalidLifecycleTransition",
                        "field": "status",
                        "message": "Cannot unarchive a deleted announcement.",
                    }
                ],
            },
        )

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.BulletinValidationError) as caught:
            await client.transition_bulletin(TITLE_ID, "a", "draft")
        assert caught.value.errors[0]["code"] == "InvalidLifecycleTransition"
        await client.aclose()

    asyncio.run(run())


def test_a_non_list_error_field_is_rejected(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "a", "config": None, "errors": "bad"})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.save_bulletin(TITLE_ID,
                {"id": "a", "bulletin": {}, "audience": [], "status": "draft"}
            )
        await client.aclose()

    asyncio.run(run())


def test_a_bare_config_save_response_is_rejected(monkeypatch) -> None:
    """The load shape is not the save shape; accepting it would mask drift."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_config("a"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.save_bulletin(TITLE_ID,
                {"id": "a", "bulletin": {}, "audience": [], "status": "draft"}
            )
        await client.aclose()

    asyncio.run(run())


def test_a_saved_record_without_an_id_is_rejected(monkeypatch) -> None:
    """An identity-less record could never be edited or transitioned again."""
    config = _config("placeholder")
    del config["bulletin"]["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"config": config, "errors": []})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError) as caught:
            await client.save_bulletin(TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "draft"}
            )
        assert "without an id" in str(caught.value)
        await client.aclose()

    asyncio.run(run())


def test_a_create_may_take_its_id_from_either_envelope_position(
    monkeypatch,
) -> None:
    """The wrapper id and the config id are both authoritative when they agree.

    A create has no requested id to compare against, so either position alone is
    enough as long as one is present.
    """
    config = _config("created-1")

    def handler(request: httpx.Request) -> httpx.Response:
        # Wrapper id omitted; the config still carries the canonical id.
        return httpx.Response(200, json={"config": config, "errors": []})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        saved = await client.save_bulletin(TITLE_ID,
            {"bulletin": {}, "audience": [], "status": "draft"}
        )
        assert saved["bulletin"]["id"] == "created-1"
        await client.aclose()

    asyncio.run(run())


def test_invalid_success_shaped_bodies_are_rejected(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/essbulletins"):
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json={"status": "draft"})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.list_bulletins(TITLE_ID)
        with pytest.raises(org_client.AgentConfigApiError):
            await client.get_bulletin(TITLE_ID, "a")
        await client.aclose()

    asyncio.run(run())


def test_collection_items_missing_content_are_rejected(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{"status": "draft"}]})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.list_bulletins(TITLE_ID)
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "end_date", "expected_archived"),
    [
        ("draft", None, False),
        ("draft", "2020-01-01T00:00:00.000Z", False),
        ("published", None, False),
        ("published", "2030-01-01T00:00:00.000Z", False),
        ("published", "2020-01-01T00:00:00.000Z", True),
        ("retired", None, True),
        ("retired", "2030-01-01T00:00:00.000Z", True),
    ],
)
def test_archive_classification_uses_status_and_schedule(
    status, end_date, expected_archived
) -> None:
    config = _config("a", status=status, end_date=end_date)
    assert org_client.is_archived_item(config, NOW) is expected_archived


def test_unparseable_end_date_keeps_a_published_item_current() -> None:
    config = _config("a", status="published", end_date="not-a-date")
    assert org_client.is_archived_item(config, NOW) is False


def test_manager_state_counts_current_items_and_preserves_order() -> None:
    items = [
        _config("current-1", status="published", end_date="2030-01-01T00:00:00.000Z"),
        _config("archived-1", status="retired"),
        _config("current-2", status="draft"),
    ]

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert state["workingSetCount"] == 2
    assert state["archivedTruncated"] is False
    assert [item["config"]["bulletin"]["id"] for item in state["items"]] == [
        "current-1",
        "archived-1",
        "current-2",
    ]


def test_manager_state_flags_a_full_archived_window() -> None:
    items = [_config("current", status="draft")]
    items.extend(
        _config(f"archived-{index}", status="retired")
        for index in range(org_client.ARCHIVED_WINDOW_SIZE)
    )

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert state["workingSetCount"] == 1
    assert state["archivedTruncated"] is True
    # The state never claims an exact archived total.
    assert "archivedCount" not in state
    assert "archivedTotal" not in state


def test_manager_state_excludes_deleted_rows_from_items_and_counts() -> None:
    """Delete is a status transition, so the list can still return the row.

    A deleted announcement is neither a working item nor a restorable archived
    one, so it must not appear and must not be counted in either bucket.
    """
    items = [
        _config("current-1", status="draft"),
        _config("deleted-1", status="deleted"),
        _config("archived-1", status="retired"),
    ]

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert [item["config"]["bulletin"]["id"] for item in state["items"]] == [
        "current-1",
        "archived-1",
    ]
    assert state["workingSetCount"] == 1
    assert state["archivedTruncated"] is False


def test_deleted_rows_do_not_fill_the_archived_window() -> None:
    """Deleted rows must not push archivedTruncated true on their own."""
    items = [
        _config(f"deleted-{index}", status="deleted")
        for index in range(org_client.ARCHIVED_WINDOW_SIZE)
    ]
    items.append(_config("current", status="draft"))

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert state["workingSetCount"] == 1
    assert state["archivedTruncated"] is False
    assert len(state["items"]) == 1


def test_deleted_classification_is_independent_of_schedule() -> None:
    assert org_client.is_deleted_item(_config("a", status="deleted")) is True
    assert org_client.is_deleted_item(_config("a", status="retired")) is False
    assert org_client.is_deleted_item(_config("a", status="draft")) is False


def test_manager_state_attaches_per_item_audience_metadata() -> None:
    items = [_config("a", audience=["g1", "g2"])]
    metadata = {
        "a": [
            {"id": "g1", "displayName": "Group One", "mail": None, "isValid": True},
            {"id": "g2", "displayName": "Group Two", "mail": None, "isValid": True},
        ]
    }

    state = org_client.build_manager_state(items, metadata, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert [group["id"] for group in state["items"][0]["audienceMetadata"]] == [
        "g1",
        "g2",
    ]


def test_base_url_must_be_https(monkeypatch) -> None:
    monkeypatch.setenv("ORG_ANNOUNCEMENTS_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token())

    with pytest.raises(ValueError):
        org_client.OrgAnnouncementsClient()


def test_default_base_url_is_the_agent_qualified_v11_surface(monkeypatch) -> None:
    monkeypatch.delenv("ORG_ANNOUNCEMENTS_BASE_URL", raising=False)
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token())

    client = org_client.OrgAnnouncementsClient()

    assert client.base_url == org_client.DEFAULT_ORG_ANNOUNCEMENTS_BASE_URL
    assert client.base_url == BASE_URL


def test_repr_never_exposes_the_token(monkeypatch) -> None:
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token())
    monkeypatch.setenv("ORG_ANNOUNCEMENTS_BASE_URL", BASE_URL)

    client = org_client.OrgAnnouncementsClient()

    assert _token() not in repr(client)


@pytest.mark.parametrize("operation", ["list", "get", "save", "transition"])
@pytest.mark.parametrize("title_id", ["", " ", " padded", "padded ", "a\x00b", "a\x7fb", "a" * 257])
def test_invalid_title_is_rejected_before_any_http_request(monkeypatch, operation, title_id) -> None:
    def handler(request):
        pytest.fail("invalid title reached the transport")

    client = _make_client(monkeypatch, handler)

    async def run():
        with pytest.raises(ValueError, match="titleId"):
            if operation == "list":
                await client.list_bulletins(title_id)
            elif operation == "get":
                await client.get_bulletin(title_id, "a")
            elif operation == "save":
                await client.save_bulletin(title_id, {"status": "draft"})
            else:
                await client.transition_bulletin(title_id, "a", "retired")
        await client.aclose()

    asyncio.run(run())


def test_title_key_uses_the_landing_page_odata_encoding(monkeypatch) -> None:
    requests = []
    title_id = "a'b/c"

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[_config("a", title_id=title_id)])

    client = _make_client(monkeypatch, handler)

    async def run():
        await client.list_bulletins(title_id)
        await client.aclose()

    asyncio.run(run())
    assert b"/EmployeeAgents('a%27%27b%2Fc')/essbulletins" in requests[0].url.raw_path
    assert requests[0].url.query == b""


def test_canonical_scope_cannot_be_embedded_in_bulletin_content(monkeypatch) -> None:
    config = _config("a")
    config["bulletin"]["titleId"] = TITLE_ID
    client = _make_client(monkeypatch, lambda r: httpx.Response(200, json=config))

    async def run():
        with pytest.raises(org_client.AgentConfigApiError, match="inside bulletin"):
            await client.get_bulletin(TITLE_ID, "a")
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["list", "get", "save", "transition"])
@pytest.mark.parametrize("response_title", [None, "", "another-title", "TITLE-1"])
def test_every_returned_config_must_echo_the_exact_title(monkeypatch, operation, response_title) -> None:
    config = _config("a")
    if response_title is None:
        config.pop("titleId")
    else:
        config["titleId"] = response_title
    requests = []

    def handler(request):
        requests.append(request)
        if operation == "list":
            body = [_config("valid"), config]
        elif operation == "get":
            body = config
        else:
            body = _save_result("a", config=config)
        return httpx.Response(200, json=body)

    client = _make_client(monkeypatch, handler)

    async def run():
        with pytest.raises(org_client.AgentConfigApiError, match="titleId"):
            if operation == "list":
                await client.list_bulletins(TITLE_ID)
            elif operation == "get":
                await client.get_bulletin(TITLE_ID, "a")
            elif operation == "save":
                await client.save_bulletin(TITLE_ID, {"id": "a", "status": "draft"})
            else:
                await client.transition_bulletin(TITLE_ID, "a", "retired")
        await client.aclose()

    asyncio.run(run())
    assert len(requests) == 1


def test_unavailable_agent_route_never_falls_back_to_tenant_collection(monkeypatch) -> None:
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(404, json={"Code": "NotFound", "Message": "not deployed"})

    client = _make_client(monkeypatch, handler)

    async def run():
        with pytest.raises(org_client.AgentConfigApiError):
            await client.list_bulletins(TITLE_ID)
        await client.aclose()

    asyncio.run(run())
    assert paths == [COLLECTION_PATH]


def test_collections_and_manager_limits_are_independent_per_tenant_and_agent(monkeypatch) -> None:
    other_tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    pairs = [(TENANT_ID, TITLE_ID, 100, 50), (TENANT_ID, "title-2", 1, 49),
             (other_tenant, TITLE_ID, 0, 0)]
    responses = {}
    for tenant, title, current, archived in pairs:
        path = f"/weveb2/api/v1.1/tenants('{tenant}')/EmployeeAgents('{title}')/essbulletins"
        responses[path] = [
            _config(f"same-id-{i}", title_id=title, status="draft" if i < current else "retired")
            for i in range(current + archived)
        ]
    clients = {
        tenant: _make_client(monkeypatch, lambda r: httpx.Response(200, json=responses[r.url.path]),
                             tenant_id=tenant)
        for tenant in (TENANT_ID, other_tenant)
    }

    async def run():
        for tenant, title, current, archived in pairs:
            items = await clients[tenant].list_bulletins(title)
            state = org_client.build_manager_state(
                items, {}, NOW, tenant_id=tenant, title_id=title
            )
            assert state["tenantId"] == tenant
            assert state["titleId"] == title
            assert state["workingSetCount"] == current
            assert state["archivedTruncated"] is (archived == 50)
            assert len(state["items"]) == current + archived
        for client in clients.values():
            await client.aclose()

    asyncio.run(run())
