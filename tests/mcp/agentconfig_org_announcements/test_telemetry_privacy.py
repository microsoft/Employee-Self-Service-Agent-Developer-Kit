# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Privacy and fail-open guards for Org Announcements telemetry.

The tightest constraint on this surface is that announcement content, audience
group identifiers, the tenant's API endpoint, tokens, claims, and the opener
request payload must never leave the machine. These tests assert that at the
emit boundary — the last point where a leak is still catchable — rather than by
reading the calling code, so a future caller that passes the wrong value is
caught here too.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

from _mcp_modules import load_org_announcements_modules  # noqa: E402

_ORG_MODULES = load_org_announcements_modules()
org_telemetry = _ORG_MODULES["telemetry"]
org_server = _ORG_MODULES["server"]
org_client = _ORG_MODULES["client"]


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
TENANT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
TITLE_ID = "secret-agent-title"

# Values that must never appear in any emitted field.
SECRET_TITLE = "Layoffs announcement do not leak"
SECRET_DESCRIPTION = "Confidential body text"
SECRET_GROUP_ID = "11111111-2222-3333-4444-555555555555"
SECRET_ENDPOINT = "https://substrate.office.com/weveb2/api/v1.1"
SECRET_TOKEN = "eyJhbGciOiJub25lIn0.payload.signature"  # noqa: S105 — fixture
SECRET_PROMPT = "Ask about the reorg"
SECRET_URL = "https://contoso.example/secret-plan"

FORBIDDEN = (
    TITLE_ID,
    TENANT_ID,
    OBJECT_ID,
    SECRET_TITLE,
    SECRET_DESCRIPTION,
    SECRET_GROUP_ID,
    SECRET_ENDPOINT,
    SECRET_TOKEN,
    SECRET_PROMPT,
    SECRET_URL,
)


@pytest.fixture
def emitted(monkeypatch) -> list[dict[str, Any]]:
    """Capture every event this module would hand to the ADK emitter."""
    events: list[dict[str, Any]] = []

    class _FakeAdkTelemetry:
        @staticmethod
        def emit_api_call(**fields: Any) -> dict[str, Any]:
            events.append(dict(fields))
            return {"sent": False}

    monkeypatch.setattr(
        org_telemetry, "_adk_telemetry", lambda: _FakeAdkTelemetry()
    )
    return events


def _flatten(event: dict[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in event.items())


# --------------------------------------------------------------------------
# Field shape
# --------------------------------------------------------------------------


def test_a_success_event_carries_only_operation_outcome_and_latency(
    emitted,
) -> None:
    org_telemetry.record_operation(
        "save_bulletin", outcome="success", latency_ms=42
    )

    assert emitted == [
        {
            "api_endpoint": "save_bulletin",
            "outcome": "success",
            "latency_ms": 42,
        }
    ]


def test_a_failure_event_adds_only_a_stable_code_and_broad_source(
    emitted,
) -> None:
    org_telemetry.record_operation(
        "save_bulletin",
        outcome="failure",
        latency_ms=7,
        error_code="AudienceRequired",
        error_source=org_telemetry.SOURCE_BACKEND,
    )

    assert emitted == [
        {
            "api_endpoint": "save_bulletin",
            "outcome": "failure",
            "latency_ms": 7,
            "error_code": "AudienceRequired",
            "error_category": "backend",
            # Never a message: backend text can echo the announcement back.
            "error_message": "",
        }
    ]


def test_the_endpoint_dimension_is_the_tool_name_not_a_url(emitted) -> None:
    org_telemetry.record_operation(
        "open_org_announcements", outcome="success", latency_ms=1
    )

    assert emitted[0]["api_endpoint"] == "open_org_announcements"
    assert "://" not in emitted[0]["api_endpoint"]


@pytest.mark.parametrize(
    "operation",
    [
        "open_org_announcements",
        "save_bulletin",
        "transition_bulletin",
        "duplicate_bulletin",
        "search_audience_groups",
    ],
)
def test_every_real_operation_is_reported_verbatim(emitted, operation) -> None:
    org_telemetry.record_operation(operation, outcome="success", latency_ms=1)

    assert emitted[0]["api_endpoint"] == operation


def test_an_unknown_operation_is_bucketed_rather_than_emitted(emitted) -> None:
    """A caller-controlled name must never mint a new dimension value."""
    org_telemetry.record_operation(
        SECRET_TITLE, outcome="success", latency_ms=1
    )

    assert emitted[0]["api_endpoint"] == org_telemetry.OPERATION_UNKNOWN


def test_an_unknown_error_source_is_bucketed(emitted) -> None:
    org_telemetry.record_operation(
        "save_bulletin",
        outcome="failure",
        latency_ms=1,
        error_code="X",
        error_source=SECRET_ENDPOINT,
    )

    assert emitted[0]["error_category"] == org_telemetry.SOURCE_MCP


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AudienceRequired", "AudienceRequired"),
        ("Committed_Refresh_Failed", "Committed_Refresh_Failed"),
        ("", ""),
        # A message masquerading as a code is replaced, not truncated: a
        # truncated message is still content.
        ("Announcement 'Layoffs' is invalid", "UnknownError"),
        ("https://contoso.example/x", "UnknownError"),
        ("a" * 200, "UnknownError"),
    ],
)
def test_only_identifier_shaped_error_codes_are_emitted(raw, expected) -> None:
    assert org_telemetry.normalize_error_code(raw) == expected


def test_a_negative_latency_is_clamped(emitted) -> None:
    org_telemetry.record_operation(
        "save_bulletin", outcome="success", latency_ms=-5
    )

    assert emitted[0]["latency_ms"] == 0


# --------------------------------------------------------------------------
# Fail open
# --------------------------------------------------------------------------


def test_a_missing_adk_telemetry_module_is_not_an_error(monkeypatch) -> None:
    monkeypatch.setattr(org_telemetry, "_adk_telemetry", lambda: None)

    org_telemetry.record_operation(
        "save_bulletin", outcome="success", latency_ms=1
    )


def test_an_emitter_exception_never_reaches_the_caller(monkeypatch) -> None:
    class _Exploding:
        @staticmethod
        def emit_api_call(**fields: Any) -> None:
            raise RuntimeError("collector unreachable")

    monkeypatch.setattr(org_telemetry, "_adk_telemetry", lambda: _Exploding())

    org_telemetry.record_operation(
        "save_bulletin", outcome="failure", latency_ms=1, error_code="X"
    )


def test_a_telemetry_failure_does_not_fail_the_tool_call(
    monkeypatch, emitted
) -> None:
    class _Exploding:
        @staticmethod
        def emit_api_call(**fields: Any) -> None:
            raise RuntimeError("collector unreachable")

    monkeypatch.setattr(org_telemetry, "_adk_telemetry", lambda: _Exploding())
    _install_fakes(monkeypatch)

    payload = _call(
        "open_org_announcements", {"view": "manager"}
    )

    assert payload["view"] == "manager"


# --------------------------------------------------------------------------
# End-to-end: nothing sensitive escapes a real tool call
# --------------------------------------------------------------------------


def _config(bulletin_id: str = "bulletin-1", *, status: str = "draft") -> dict:
    return {
        "titleId": TITLE_ID,
        "bulletin": {
            "id": bulletin_id,
            "type": "standard",
            "priority": 1,
            "title": SECRET_TITLE,
            "description": SECRET_DESCRIPTION,
            "startDate": "2026-09-01T00:00:00.000Z",
            "primaryAction": {
                "actionType": "externalLink",
                "label": "Read",
                "url": SECRET_URL,
            },
        },
        "audience": [SECRET_GROUP_ID],
        "status": status,
    }


class _FakeClient:
    tenant_id = TENANT_ID
    object_id = OBJECT_ID

    def __init__(self, *, save_error: Exception | None = None) -> None:
        self.save_error = save_error

    async def list_bulletins(self, title_id: str) -> list[dict]:
        return [_config()]

    async def get_bulletin(self, title_id: str, bulletin_id: str) -> dict:
        return _config(bulletin_id)

    async def save_bulletin(self, title_id: str, payload: dict) -> dict:
        if self.save_error is not None:
            raise self.save_error
        return _config(payload.get("id") or "created-1", status=payload["status"])

    async def transition_bulletin(self, title_id: str, bulletin_id: str, status: str) -> dict:
        return _config(bulletin_id, status=status)


class _FakeGraphClient:
    async def resolve_groups(self, group_ids) -> dict:
        return {
            SECRET_GROUP_ID: {
                "id": SECRET_GROUP_ID,
                "displayName": "Leadership",
                "mail": None,
                "isValid": True,
            }
        }

    async def search_groups(self, query: str) -> dict:
        return {"groups": [], "exhausted": True, "pagesExamined": 1}


def _install_fakes(monkeypatch, *, client=None) -> None:
    resolved = client or _FakeClient()

    async def _get_client():
        return resolved

    @asynccontextmanager
    async def _get_graph_client(tenant_id, object_id):
        assert tenant_id == resolved.tenant_id
        assert object_id == resolved.object_id
        yield _FakeGraphClient()

    monkeypatch.setattr(org_server, "get_client", _get_client)
    monkeypatch.setattr(org_server, "get_graph_client", _get_graph_client)
    monkeypatch.setattr(org_server, "_now", lambda: NOW)


def _call(tool: str, arguments: dict) -> dict:
    if tool != "search_audience_groups":
        arguments = {"titleId": TITLE_ID, **arguments}
    async def run():
        return await org_server.mcp.call_tool(tool, arguments)

    result = asyncio.run(run())
    return result[1] if isinstance(result, tuple) else result.structuredContent


def _save_arguments() -> dict:
    return {
        "bulletin": {
            "type": "standard",
            "title": SECRET_TITLE,
            "description": SECRET_DESCRIPTION,
            "primaryAction": {
                "actionType": "copilotChat",
                "label": "Ask",
                "prompt": SECRET_PROMPT,
            },
        },
        "audience": [SECRET_GROUP_ID],
        "status": "draft",
    }


def test_a_successful_save_emits_no_content_or_group_identifier(
    monkeypatch, emitted
) -> None:
    _install_fakes(monkeypatch)

    _call("save_bulletin", _save_arguments())

    assert emitted, "the save emitted no telemetry at all"
    for event in emitted:
        flat = _flatten(event)
        for secret in FORBIDDEN:
            assert secret not in flat, f"{secret!r} leaked into telemetry"


def test_a_failed_save_emits_only_the_stable_code(monkeypatch, emitted) -> None:
    _install_fakes(
        monkeypatch,
        client=_FakeClient(
            save_error=org_client.BulletinValidationError(
                [
                    {
                        "code": "AudienceGroupInvalid",
                        "field": "audience",
                        # A backend message can echo content straight back.
                        "message": f"Group {SECRET_GROUP_ID} is invalid for "
                        f"{SECRET_TITLE}.",
                    }
                ]
            )
        ),
    )

    _call("save_bulletin", _save_arguments())

    assert emitted
    event = emitted[-1]
    assert event["error_code"] == "AudienceGroupInvalid"
    assert event["error_message"] == ""
    for secret in FORBIDDEN:
        assert secret not in _flatten(event)


def test_the_opener_never_emits_the_suggested_draft(monkeypatch, emitted) -> None:
    """The opener request can carry suggested content and audience IDs."""
    _install_fakes(monkeypatch)

    _call(
        "open_org_announcements",
        {
            "view": "editor",
            "mode": "create",
            "suggestedDraft": {
                "title": SECRET_TITLE,
                "description": SECRET_DESCRIPTION,
                "audience": [SECRET_GROUP_ID],
                "primaryAction": {
                    "actionType": "externalLink",
                    "label": "Read",
                    "url": SECRET_URL,
                },
            },
        },
    )

    assert emitted
    for event in emitted:
        flat = _flatten(event)
        for secret in FORBIDDEN:
            assert secret not in flat


def test_search_telemetry_never_carries_the_query(monkeypatch, emitted) -> None:
    _install_fakes(monkeypatch)

    _call("search_audience_groups", {"query": SECRET_TITLE})

    assert emitted
    for event in emitted:
        assert SECRET_TITLE not in _flatten(event)


def test_a_transition_emits_no_identifier(monkeypatch, emitted) -> None:
    _install_fakes(monkeypatch)

    _call("transition_bulletin", {"id": "bulletin-1", "transition": "archive"})

    assert emitted
    for event in emitted:
        assert "bulletin-1" not in _flatten(event)


def test_no_event_field_is_outside_the_agreed_set(monkeypatch, emitted) -> None:
    """A new field is a new disclosure; it must be a deliberate change."""
    _install_fakes(monkeypatch)

    _call("open_org_announcements", {"view": "manager"})
    _call("save_bulletin", _save_arguments())
    _call("transition_bulletin", {"id": "bulletin-1", "transition": "archive"})
    _call("duplicate_bulletin", {"id": "bulletin-1"})
    _call("search_audience_groups", {"query": "finance"})

    allowed = {
        "api_endpoint",
        "outcome",
        "latency_ms",
        "error_code",
        "error_category",
        "error_message",
    }
    for event in emitted:
        assert set(event) <= allowed, set(event) - allowed
