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
from uuid import NAMESPACE_URL, uuid5

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
org_validation = _ORG_MODULES["validation"]


TENANT_ID = "11111111-2222-3333-4444-555555555555"
TITLE_ID = "title-1"
BASE_URL = "https://substrate.office.com/weveb2/api/v1.1"
COLLECTION_PATH = f"/weveb2/api/v1.1/tenants('{TENANT_ID}')/EmployeeAgents('{TITLE_ID}')/EssBulletins"
MANAGEMENT_PATH = f"{COLLECTION_PATH}/ManagementView()"
BULLETIN_ID = "22222222-2222-2222-2222-222222222222"
OTHER_BULLETIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED_BULLETIN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
VALID_BULLETIN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
CONTRACT_FIXTURE = (
    Path(__file__).with_name("fixtures")
    / "wevenova_ess_bulletin_contract.json"
)
PROVIDER_CONTRACT = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))


def test_request_validators_are_shared_public_boundary_helpers() -> None:
    assert org_validation.validate_title_id(TITLE_ID) == TITLE_ID
    assert org_validation.validate_bulletin_id(BULLETIN_ID) == BULLETIN_ID

    with pytest.raises(ValueError, match="titleId"):
        org_validation.validate_title_id(" padded")
    with pytest.raises(ValueError, match="bulletinId"):
        org_validation.validate_bulletin_id("bad/id")


def test_provider_contract_fixture_records_authoritative_provenance() -> None:
    source = PROVIDER_CONTRACT["source"]
    identity = PROVIDER_CONTRACT["identity"]

    assert source == {
        "repository": "WeveNova",
        "branch": "users/sophiesong/essbulletin-api-tools",
        "commit": "fa4679cf74",
        "dto": "EssBulletinResource / EssBulletinContent / EssBulletinAction",
    }
    assert identity == {
        "resourceIdType": "Guid",
        "resourceIdLocation": "root",
        "contentHasId": False,
    }
    assert PROVIDER_CONTRACT["audience"]["nullable"] is False


def test_provider_contract_values_are_accepted_at_the_odata_boundary() -> None:
    for status in PROVIDER_CONTRACT["statusValues"]:
        assert _canonical_config(status=status)["status"] == status

    for bulletin_type in PROVIDER_CONTRACT["bulletinTypeValues"]:
        payload = _config()
        payload["Bulletin"]["Type"] = bulletin_type
        assert (
            org_client.OrgAnnouncementsClient._require_config(
                payload, TITLE_ID
            )["bulletin"]["type"]
            == bulletin_type
        )

    for priority in PROVIDER_CONTRACT["priorityValues"]:
        payload = _config()
        payload["Bulletin"]["Priority"] = priority
        assert (
            org_client.OrgAnnouncementsClient._require_config(
                payload, TITLE_ID
            )["bulletin"]["priority"]
            == priority
        )

    for action_type in PROVIDER_CONTRACT["actionTypeValues"]:
        payload = _config()
        payload["Bulletin"]["PrimaryAction"] = {
            "ActionType": action_type,
            "Label": "Open",
        }
        assert (
            org_client.OrgAnnouncementsClient._require_config(
                payload, TITLE_ID
            )["bulletin"]["primaryAction"]["actionType"]
            == action_type
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("Status",), "Draft", "invalid status"),
        (("Bulletin", "Type"), "Standard", "invalid bulletin type"),
        (("Bulletin", "Priority"), 2, "invalid bulletin priority"),
        (
            ("Bulletin", "PrimaryAction", "ActionType"),
            "ExternalLink",
            "invalid action type",
        ),
    ],
)
def test_unknown_provider_enum_values_are_rejected(
    path, value, message
) -> None:
    payload = _config()
    payload["Bulletin"]["PrimaryAction"] = {
        "ActionType": "externalLink",
        "Label": "Open",
    }
    target = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value

    with pytest.raises(org_client.AgentConfigApiError, match=message):
        org_client.OrgAnnouncementsClient._require_config(payload, TITLE_ID)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "Draft"},
        {"status": "draft", "bulletin": {"type": "Standard"}},
        {"status": "draft", "bulletin": {"priority": 2}},
        {
            "status": "draft",
            "bulletin": {
                "primaryAction": {
                    "actionType": "ExternalLink",
                    "label": "Open",
                }
            },
        },
    ],
)
def test_unknown_input_enum_values_are_rejected_before_post(payload) -> None:
    with pytest.raises(ValueError, match="unsupported value"):
        org_client._to_odata_save_input(payload)


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
    bulletin_id: str = BULLETIN_ID,
    *,
    status: str = "draft",
    end_date: str | None = None,
    audience: list[str] | None = None,
    title_id: str = TITLE_ID,
) -> dict:
    return {
        "Id": bulletin_id,
        "TitleId": title_id,
        "Bulletin": {
            "Type": "standard",
            "Priority": 1,
            "Title": "Announcement",
            "Description": "Body",
            "StartDate": "2026-09-01T00:00:00.000Z",
            **({"EndDate": end_date} if end_date else {}),
        },
        "Audience": audience if audience is not None else ["group-a"],
        "Status": status,
        "CreatedBy": "admin@contoso.com",
        "CreatedOn": "2026-08-01T12:00:00.000Z",
        "ModifiedDate": "2026-09-02T12:00:00.000Z",
    }


def _save_result(
    bulletin_id: str = BULLETIN_ID,
    *,
    errors: list[dict] | None = None,
    result_id: str | None = None,
) -> dict:
    return {
        "Id": bulletin_id if result_id is None else result_id,
        "Errors": errors if errors is not None else [],
    }


def _canonical_config(
    bulletin_id: str = BULLETIN_ID,
    *,
    status: str = "draft",
    end_date: str | None = None,
    audience: list[str] | None = None,
    title_id: str = TITLE_ID,
) -> dict:
    return org_client.OrgAnnouncementsClient._require_config(
        _config(
            bulletin_id,
            status=status,
            end_date=end_date,
            audience=audience,
            title_id=title_id,
        ),
        title_id,
    )


def _test_id(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"org-announcements-test:{label}"))


def test_uses_agent_qualified_v11_routes_with_tenant_from_token(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=_save_result(CREATED_BULLETIN_ID))
        if request.url.path == MANAGEMENT_PATH:
            return httpx.Response(200, json={"value": [_config()]})
        if request.url.path.endswith(f"({CREATED_BULLETIN_ID})"):
            return httpx.Response(200, json=_config(CREATED_BULLETIN_ID))
        return httpx.Response(200, json=_config())

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.list_bulletins(TITLE_ID)
        await client.get_bulletin(TITLE_ID, BULLETIN_ID)
        await client.save_bulletin(
            TITLE_ID,
            {"bulletin": {}, "audience": [], "status": "draft"},
        )
        await client.aclose()

    asyncio.run(run())

    assert client.tenant_id == TENANT_ID
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", MANAGEMENT_PATH),
        ("GET", f"{COLLECTION_PATH}({BULLETIN_ID})"),
        ("POST", f"{COLLECTION_PATH}/Save"),
        ("GET", f"{COLLECTION_PATH}({CREATED_BULLETIN_ID})"),
    ]
    assert json.loads(requests[2].content) == {
        "input": {
            "Bulletin": {},
            "Audience": [],
            "Status": "draft",
        }
    }


def test_title_id_is_a_required_route_key_not_a_query_filter(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": [_config()]})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        await client.list_bulletins(TITLE_ID)
        await client.aclose()

    asyncio.run(run())

    assert captured[0].url.path == MANAGEMENT_PATH
    assert captured[0].url.query == b""


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        f" {BULLETIN_ID}",
        ".",
        "..",
        "a/b",
        "a\\b",
        "a?b",
        "a#b",
        "a%2Fb",
        "a\x01b",
        "not-a-guid",
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_rejects_ids_that_could_reshape_the_route(monkeypatch, bad_id) -> None:
    client = _make_client(
        monkeypatch, lambda request: httpx.Response(200, json=_config())
    )

    async def run() -> None:
        with pytest.raises(ValueError):
            await client.get_bulletin(TITLE_ID, bad_id)
        await client.aclose()

    asyncio.run(run())


def test_keyed_get_rejects_a_response_for_a_different_bulletin(
    monkeypatch,
) -> None:
    different_id = _test_id("different-keyed-response")
    client = _make_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=_config(different_id)),
    )

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError, match="different"):
            await client.get_bulletin(TITLE_ID, BULLETIN_ID)
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
    post_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempts
        attempts.append(request)
        if request.method == "POST":
            post_attempts += 1
            if post_attempts == 1:
                return httpx.Response(
                    503, json={"Code": "Busy", "Message": "later"}
                )
            return httpx.Response(200, json=_save_result())
        return httpx.Response(200, json=_config())

    client = _make_client(monkeypatch, handler)
    client.max_retries = 2

    async def run() -> None:
        result = await client.save_bulletin(TITLE_ID,
            {
                "id": BULLETIN_ID,
                "bulletin": {},
                "audience": [],
                "status": "draft",
            }
        )
        assert result["id"] == BULLETIN_ID
        await client.aclose()

    asyncio.run(run())

    assert post_attempts == 2
    assert len(attempts) == 3


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
        if request.method == "POST":
            captured.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json=_save_result())
        return httpx.Response(200, json=_config(status="retired"))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        changed = await client.transition_bulletin(
            TITLE_ID, BULLETIN_ID, "retired"
        )
        assert changed["id"] == BULLETIN_ID
        assert changed["status"] == "retired"
        await client.aclose()

    asyncio.run(run())

    assert captured == [
        {"input": {"Id": BULLETIN_ID, "Status": "retired"}}
    ]


# --------------------------------------------------------------------------
# EssBulletinSaveResult envelope
# --------------------------------------------------------------------------


def test_save_reloads_the_canonical_resource_from_the_receipt(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=_save_result(CREATED_BULLETIN_ID))
        return httpx.Response(200, json=_config(CREATED_BULLETIN_ID))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        saved = await client.save_bulletin(
            TITLE_ID,
            {
                "bulletin": {
                    "type": "standard",
                    "priority": 0,
                    "title": "Title",
                    "description": "Body",
                    "primaryAction": {
                        "actionType": "externalLink",
                        "label": "Open",
                        "url": "https://contoso.com",
                    },
                },
                "audience": ["group-a"],
                "status": "draft",
            },
        )
        assert saved == _canonical_config(CREATED_BULLETIN_ID)
        await client.aclose()

    asyncio.run(run())

    assert [request.method for request in requests] == ["POST", "GET"]
    assert json.loads(requests[0].content) == {
        "input": {
            "Bulletin": {
                "Type": "standard",
                "Priority": 0,
                "Title": "Title",
                "Description": "Body",
                "PrimaryAction": {
                    "ActionType": "externalLink",
                    "Label": "Open",
                    "Url": "https://contoso.com",
                },
            },
            "Audience": ["group-a"],
            "Status": "draft",
        }
    }


def test_http_200_with_errors_is_a_structured_validation_failure(
    monkeypatch,
) -> None:
    reported = [
        {"Code": "AudienceRequired", "Field": "audience", "Message": "Pick a group."},
        {"Code": "TitleRequired", "Field": "title", "Message": "Add a title."},
    ]

    client = _make_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"Id": None, "Errors": reported}
        ),
    )

    async def run() -> None:
        with pytest.raises(org_client.BulletinValidationError) as caught:
            await client.save_bulletin(
                TITLE_ID,
                {"bulletin": {}, "audience": [], "status": "published"},
            )
        assert caught.value.errors == [
            {"code": "AudienceRequired", "field": "audience", "message": "Pick a group."},
            {"code": "TitleRequired", "field": "title", "message": "Add a title."},
        ]
        assert caught.value.http_status == 200
        await client.aclose()

    asyncio.run(run())


def test_a_partial_error_entry_keeps_its_field_and_gets_a_stable_code(
    monkeypatch,
) -> None:
    client = _make_client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "Id": None,
                "Errors": [{"Field": "title"}, "unstructured"],
            },
        ),
    )

    async def run() -> None:
        with pytest.raises(org_client.BulletinValidationError) as caught:
            await client.save_bulletin(
                TITLE_ID, {"bulletin": {}, "audience": [], "status": "draft"}
            )
        assert len(caught.value.errors) == 2
        assert caught.value.errors[0]["field"] == "title"
        assert caught.value.errors[0]["code"] == "InvalidRequest"
        assert caught.value.errors[1]["message"] == "unstructured"
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "body",
    [
        {"Id": BULLETIN_ID},
        {"Id": BULLETIN_ID, "Errors": "bad"},
        {"Id": None, "Errors": []},
        _config(),
    ],
)
def test_invalid_save_receipts_are_rejected(monkeypatch, body) -> None:
    client = _make_client(
        monkeypatch, lambda request: httpx.Response(200, json=body)
    )

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.save_bulletin(
                TITLE_ID,
                {"id": BULLETIN_ID, "status": "draft"},
            )
        await client.aclose()

    asyncio.run(run())


def test_an_update_answered_with_a_different_record_is_rejected(
    monkeypatch,
) -> None:
    client = _make_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=_save_result(OTHER_BULLETIN_ID)
        ),
    )

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError, match="different"):
            await client.save_bulletin(
                TITLE_ID,
                {"id": BULLETIN_ID, "status": "draft"},
            )
        await client.aclose()

    asyncio.run(run())


def test_a_transition_rejected_by_validation_preserves_its_codes(
    monkeypatch,
) -> None:
    client = _make_client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "Id": None,
                "Errors": [
                    {
                        "Code": "InvalidLifecycleTransition",
                        "Field": "status",
                        "Message": "Cannot unarchive a deleted announcement.",
                    }
                ],
            },
        ),
    )

    async def run() -> None:
        with pytest.raises(org_client.BulletinValidationError) as caught:
            await client.transition_bulletin(TITLE_ID, BULLETIN_ID, "draft")
        assert caught.value.errors[0]["code"] == "InvalidLifecycleTransition"
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["save", "transition"])
def test_keyed_reload_failure_is_reported_as_committed_refresh(
    monkeypatch, operation
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_save_result())
        return httpx.Response(
            503, json={"Code": "Busy", "Message": "try later"}
        )

    client = _make_client(monkeypatch, handler)
    client.max_retries = 1

    async def run() -> None:
        with pytest.raises(org_client.CommittedCanonicalReloadError):
            if operation == "save":
                await client.save_bulletin(
                    TITLE_ID,
                    {"id": BULLETIN_ID, "status": "draft"},
                )
            else:
                await client.transition_bulletin(
                    TITLE_ID, BULLETIN_ID, "retired"
                )
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["save", "transition"])
def test_committed_reload_retries_only_transient_keyed_get_404(
    monkeypatch, operation
) -> None:
    counts = {"post": 0, "get": 0}
    expected_status = "draft" if operation == "save" else "retired"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            counts["post"] += 1
            return httpx.Response(200, json=_save_result())
        counts["get"] += 1
        if counts["get"] < 3:
            return httpx.Response(
                404, json={"Code": "NotFound", "Message": "not visible yet"}
            )
        return httpx.Response(200, json=_config(status=expected_status))

    monkeypatch.setattr(org_client, "_COMMITTED_RELOAD_404_DELAYS", (0, 0))
    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        if operation == "save":
            result = await client.save_bulletin(
                TITLE_ID,
                {"id": BULLETIN_ID, "status": "draft"},
            )
        else:
            result = await client.transition_bulletin(
                TITLE_ID, BULLETIN_ID, "retired"
            )
        assert result["status"] == expected_status
        await client.aclose()

    asyncio.run(run())

    assert counts == {"post": 1, "get": 3}


@pytest.mark.parametrize("operation", ["save", "transition"])
def test_committed_reload_404_exhaustion_never_reposts(
    monkeypatch, operation
) -> None:
    counts = {"post": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            counts["post"] += 1
            return httpx.Response(200, json=_save_result())
        counts["get"] += 1
        return httpx.Response(
            404, json={"Code": "NotFound", "Message": "not visible yet"}
        )

    monkeypatch.setattr(org_client, "_COMMITTED_RELOAD_404_DELAYS", (0, 0))
    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(
            org_client.CommittedCanonicalReloadError
        ) as caught:
            if operation == "save":
                await client.save_bulletin(
                    TITLE_ID,
                    {"id": BULLETIN_ID, "status": "draft"},
                )
            else:
                await client.transition_bulletin(
                    TITLE_ID, BULLETIN_ID, "retired"
                )
        assert caught.value.cause.http_status == 404
        await client.aclose()

    asyncio.run(run())

    assert counts == {"post": 1, "get": 3}


@pytest.mark.parametrize("operation", ["save", "transition"])
def test_keyed_reload_identity_mismatch_is_reported_as_committed_refresh(
    monkeypatch, operation
) -> None:
    different_id = _test_id(f"different-{operation}-reload")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_save_result())
        return httpx.Response(200, json=_config(different_id))

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.CommittedCanonicalReloadError) as caught:
            if operation == "save":
                await client.save_bulletin(
                    TITLE_ID,
                    {"id": BULLETIN_ID, "status": "draft"},
                )
            else:
                await client.transition_bulletin(
                    TITLE_ID, BULLETIN_ID, "retired"
                )
        assert isinstance(caught.value.cause, org_client.AgentConfigApiError)
        assert "different" in str(caught.value.cause)
        await client.aclose()

    asyncio.run(run())


def test_delete_does_not_reload_a_tombstoned_resource(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_save_result())

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        assert (
            await client.transition_bulletin(
                TITLE_ID, BULLETIN_ID, "deleted"
            )
            is None
        )
        await client.aclose()

    asyncio.run(run())

    assert [request.method for request in requests] == ["POST"]


def test_invalid_success_shaped_bodies_are_rejected(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == MANAGEMENT_PATH:
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json={"Status": "draft"})

    client = _make_client(monkeypatch, handler)

    async def run() -> None:
        with pytest.raises(org_client.AgentConfigApiError):
            await client.list_bulletins(TITLE_ID)
        with pytest.raises(org_client.AgentConfigApiError):
            await client.get_bulletin(TITLE_ID, BULLETIN_ID)
        await client.aclose()

    asyncio.run(run())


def test_collection_items_missing_content_are_rejected(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{"Status": "draft"}]})

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
    config = _canonical_config(status=status, end_date=end_date)
    assert org_client.is_archived_item(config, NOW) is expected_archived


def test_unparseable_end_date_keeps_a_published_item_current() -> None:
    config = _canonical_config(status="published", end_date="not-a-date")
    assert org_client.is_archived_item(config, NOW) is False


def test_manager_state_counts_current_items_and_preserves_order() -> None:
    current_1 = _test_id("current-1")
    archived_1 = _test_id("archived-1")
    current_2 = _test_id("current-2")
    items = [
        _canonical_config(
            current_1,
            status="published",
            end_date="2030-01-01T00:00:00.000Z",
        ),
        _canonical_config(archived_1, status="retired"),
        _canonical_config(current_2, status="draft"),
    ]

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert state["workingSetCount"] == 2
    assert state["archivedTruncated"] is False
    assert [item["config"]["id"] for item in state["items"]] == [
        current_1, archived_1, current_2
    ]


def test_manager_state_flags_a_full_archived_window() -> None:
    items = [_canonical_config(_test_id("current"), status="draft")]
    items.extend(
        _canonical_config(_test_id(f"archived-{index}"), status="retired")
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
    current_id = _test_id("current-1")
    deleted_id = _test_id("deleted-1")
    archived_id = _test_id("archived-1")
    items = [
        _canonical_config(current_id, status="draft"),
        _canonical_config(deleted_id, status="deleted"),
        _canonical_config(archived_id, status="retired"),
    ]

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert [item["config"]["id"] for item in state["items"]] == [
        current_id, archived_id
    ]
    assert state["workingSetCount"] == 1
    assert state["archivedTruncated"] is False


def test_deleted_rows_do_not_fill_the_archived_window() -> None:
    """Deleted rows must not push archivedTruncated true on their own."""
    items = [
        _canonical_config(_test_id(f"deleted-{index}"), status="deleted")
        for index in range(org_client.ARCHIVED_WINDOW_SIZE)
    ]
    items.append(_canonical_config(_test_id("current"), status="draft"))

    state = org_client.build_manager_state(items, {}, NOW, tenant_id=TENANT_ID, title_id=TITLE_ID)

    assert state["workingSetCount"] == 1
    assert state["archivedTruncated"] is False
    assert len(state["items"]) == 1


def test_deleted_classification_is_independent_of_schedule() -> None:
    assert org_client.is_deleted_item(
        _canonical_config(status="deleted")
    ) is True
    assert org_client.is_deleted_item(
        _canonical_config(status="retired")
    ) is False
    assert org_client.is_deleted_item(
        _canonical_config(status="draft")
    ) is False


def test_manager_state_attaches_per_item_audience_metadata() -> None:
    items = [_canonical_config(audience=["g1", "g2"])]
    metadata = {
        BULLETIN_ID: [
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
                await client.get_bulletin(title_id, BULLETIN_ID)
            elif operation == "save":
                await client.save_bulletin(title_id, {"status": "draft"})
            else:
                await client.transition_bulletin(
                    title_id, BULLETIN_ID, "retired"
                )
        await client.aclose()

    asyncio.run(run())


def test_title_key_uses_the_landing_page_odata_encoding(monkeypatch) -> None:
    requests = []
    title_id = "a'b/c"

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"value": [_config(title_id=title_id)]}
        )

    client = _make_client(monkeypatch, handler)

    async def run():
        await client.list_bulletins(title_id)
        await client.aclose()

    asyncio.run(run())
    assert (
        b"/EmployeeAgents('a%27%27b%2Fc')/EssBulletins/ManagementView()"
        in requests[0].url.raw_path
    )
    assert requests[0].url.query == b""


def test_canonical_identity_cannot_be_duplicated_in_bulletin_content(
    monkeypatch,
) -> None:
    config = _config()
    config["Bulletin"]["Id"] = BULLETIN_ID
    client = _make_client(monkeypatch, lambda r: httpx.Response(200, json=config))

    async def run():
        with pytest.raises(org_client.AgentConfigApiError, match="duplicate id"):
            await client.get_bulletin(TITLE_ID, BULLETIN_ID)
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["list", "get", "save", "transition"])
@pytest.mark.parametrize("response_title", [None, "", "another-title", "TITLE-1"])
def test_every_returned_config_must_echo_the_exact_title(monkeypatch, operation, response_title) -> None:
    config = _config()
    if response_title is None:
        config.pop("TitleId")
    else:
        config["TitleId"] = response_title
    requests = []

    def handler(request):
        requests.append(request)
        if operation == "list":
            body = {"value": [_config(VALID_BULLETIN_ID), config]}
        elif operation == "get" or request.method == "GET":
            body = config
        else:
            body = _save_result()
        return httpx.Response(200, json=body)

    client = _make_client(monkeypatch, handler)

    async def run():
        expected_error = (
            org_client.CommittedCanonicalReloadError
            if operation in ("save", "transition")
            else org_client.AgentConfigApiError
        )
        with pytest.raises(expected_error) as caught:
            if operation == "list":
                await client.list_bulletins(TITLE_ID)
            elif operation == "get":
                await client.get_bulletin(TITLE_ID, BULLETIN_ID)
            elif operation == "save":
                await client.save_bulletin(
                    TITLE_ID, {"id": BULLETIN_ID, "status": "draft"}
                )
            else:
                await client.transition_bulletin(
                    TITLE_ID, BULLETIN_ID, "retired"
                )
        failure = (
            caught.value.cause
            if isinstance(
                caught.value, org_client.CommittedCanonicalReloadError
            )
            else caught.value
        )
        assert "titleId" in str(failure)
        await client.aclose()

    asyncio.run(run())
    assert len(requests) == (1 if operation in ("list", "get") else 2)


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
    assert paths == [MANAGEMENT_PATH]


def test_collections_and_manager_limits_are_independent_per_tenant_and_agent(monkeypatch) -> None:
    other_tenant = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    pairs = [(TENANT_ID, TITLE_ID, 100, 50), (TENANT_ID, "title-2", 1, 49),
             (other_tenant, TITLE_ID, 0, 0)]
    responses = {}
    for tenant, title, current, archived in pairs:
        path = (
            f"/weveb2/api/v1.1/tenants('{tenant}')/"
            f"EmployeeAgents('{title}')/EssBulletins/ManagementView()"
        )
        responses[path] = {
            "value": [
                _config(
                    _test_id(f"{tenant}:{title}:{index}"),
                    title_id=title,
                    status="draft" if index < current else "retired",
                )
                for index in range(current + archived)
            ]
        }
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
