# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Org Announcements MCP server.

Announcements are scoped to the authenticated tenant and deployed ESS titleId.
The tenant comes exclusively from the AgentConfiguration access token; each
request carries its agent identity through every read, write, and refresh.

Tool visibility is deliberate:

* ``open_org_announcements`` is read-only and model/app-visible. It is the single
  entry point a maker turn may use, and the widget uses it for scoped navigation.
* ``save_bulletin``, ``transition_bulletin``, and ``duplicate_bulletin`` are
  app-visible only. Once the widget is open it owns the editing session, so the
  model must not issue a duplicate write.
* ``search_audience_groups`` is read-only and visible to both, because the skill
  needs it to resolve explicit audience names before an opener call.

Nothing here logs announcement content, group identifiers, group names, group
mail, tokens, claims, or the opener request payload.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from portalocker.exceptions import LockException
from pydantic import ValidationError

from client import (
    AgentConfigApiError,
    BulletinValidationError,
    IndeterminateWriteError,
    OrgAnnouncementsClient,
    build_manager_state,
    is_deleted_item,
    _validate_title_id,
    _validate_bulletin_id,
)
from drafts import (
    AnnouncementEditorDraft,
    AudienceGroup,
    EditorMode,
    SaveBulletinRequest,
    SuggestedBulletinDraft,
    OpenAnnouncementsRequest,
    build_create_draft,
    build_editor_draft_from_config,
    without_blank_schedule,
)
from graph_directory_client import (
    GraphDirectoryClient,
    GraphDirectoryError,
    build_audience_metadata,
    escape_search_value,
)
from telemetry import (
    SOURCE_BACKEND,
    SOURCE_GRAPH,
    SOURCE_MCP,
    record_operation,
)


DEFAULT_WIDGET_ORIGIN = "https://workforceinsights.m365.cloud.microsoft"
WIDGET_MIME_TYPE = "text/html;profile=mcp-app"
ORG_ANNOUNCEMENTS_RESOURCE_URI = (
    "ui://widget/org-announcements/OrgAnnouncements.html"
)

_LOGGER = logging.getLogger("ess-org-announcements")

_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_MUTATION_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
_DESTRUCTIVE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)

# Widget transition -> stored status. Publish now is intentionally absent: the
# scheduled row already holds canonical content and audience in the widget, so
# Vorpal calls save_bulletin with that complete state and only moves startDate
# to the current UTC instant. Routing it here would need a server-side
# GET-then-POST and would race a concurrent edit.
TRANSITION_STATUS = {
    "archive": "retired",
    "unarchive": "draft",
    "moveToDraft": "draft",
    "delete": "deleted",
}
TransitionName = Literal["archive", "unarchive", "moveToDraft", "delete"]

# Backend codes that mean the tenant's OrgAnnouncementsSettings gate is off or
# the authoring surface is not deployed. These are reported as a recoverable
# unavailable state; the server never falls back to mock persistence.
#
# The list is intentionally exact-match and conservative. A substring or prefix
# rule would swallow a genuine field-level validation code that merely mentions
# a feature, turning a fixable "this value is wrong" into a dead-end "your
# tenant is not enabled" that the maker cannot act on.
_FEATURE_DISABLED_CODES = frozenset(
    {
        "FeatureDisabled",
        "FeatureNotEnabled",
        "OrgAnnouncementsDisabled",
        "NotSupported",
    }
)

# The neutral client core synthesizes this code when a failing response carried
# no backend ``Code`` at all. It is a transport placeholder, NOT a backend
# validation code, so it must never be surfaced as one: the widget would look up
# localized copy for a code the backend never emitted, and a 500 would be
# reported to the maker as if they had typed something wrong.
_FALLBACK_BACKEND_CODE = "HttpError"

# Identity and audit fields the backend owns. A duplicate strips them from the
# copied content so the copy is created as a fresh Draft rather than silently
# updating its source or inheriting its history. The wrapper-level audit fields
# (createdBy/createdOn/modifiedDate/status) are never copied at all, because the
# duplicate payload is rebuilt from content and audience only.
_COPY_STRIPPED_FIELDS = frozenset(
    {"id", "createdBy", "createdOn", "modifiedDate", "status", "version", "etag"}
)


def _resolve_widget_origin(value: Optional[str] = None) -> str:
    origin = (
        value or os.environ.get("VORPAL_WIDGET_ORIGIN") or DEFAULT_WIDGET_ORIGIN
    ).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "VORPAL_WIDGET_ORIGIN must be an HTTPS origin without credentials, "
            "a path, a query, or a fragment."
        )
    return origin


WIDGET_ORIGIN = _resolve_widget_origin()


def _widget_tool_meta() -> dict[str, Any]:
    return {
        "ui": {
            "resourceUri": ORG_ANNOUNCEMENTS_RESOURCE_URI,
            "visibility": ["model", "app"],
        }
    }


def _app_only_tool_meta() -> dict[str, Any]:
    """Hide a mutation from the model so only the open widget can call it."""
    return {"ui": {"visibility": ["app"]}}


def _shared_tool_meta() -> dict[str, Any]:
    return {"ui": {"visibility": ["model", "app"]}}


def _widget_resource_meta() -> dict[str, Any]:
    return {
        "ui": {
            "domain": WIDGET_ORIGIN,
            "csp": {"resourceDomains": [WIDGET_ORIGIN], "connectDomains": []},
        }
    }


def _widget_shell() -> str:
    script_url = html.escape(
        f"{WIDGET_ORIGIN}/mcp-widget/org-announcements/widget.js", quote=True
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        "  </head>\n"
        "  <body>\n"
        '    <div id="mcp-root"></div>\n'
        f'    <script type="module" src="{script_url}"></script>\n'
        "  </body>\n"
        "</html>\n"
    )


mcp = FastMCP(
    "ess-org-announcements",
    instructions=(
        "Author ESS announcements for one deployed agent in the authenticated "
        "tenant. A required titleId selects the agent, not an author permission "
        "or an audience group. The current100/latest50 limits apply per tenant "
        "and agent. Open the management view or the editor "
        "through open_org_announcements; the widget owns every save, lifecycle "
        "action, and audience search after it opens."
    ),
)

_client: Optional[OrgAnnouncementsClient] = None
_graph_client: Optional[GraphDirectoryClient] = None
_graph_client_users: dict[GraphDirectoryClient, int] = {}

# Guards construction and invalidation of the process-global authoring client so
# concurrent tool calls share one sign-in instead of racing two browser prompts.
_client_lock = asyncio.Lock()


async def get_client() -> OrgAnnouncementsClient:
    """Return the authoring client, constructing it lazily off the event loop.

    ``OrgAnnouncementsClient.__init__`` resolves a delegated token through the
    shared core, which is synchronous and — on a cold cache — blocks for as long
    as a human takes to finish an interactive browser sign-in. Constructing it
    inline would run all of that *inside* the asyncio event loop, freezing every
    other in-flight request and the MCP stdio transport itself for the duration.

    So construction happens in a worker thread, behind a lock, exactly like the
    Graph client's token acquisition.
    """
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            try:
                _client = await asyncio.to_thread(OrgAnnouncementsClient)
            except (LockException, OSError) as error:
                # Cache details stay on the exception cause, not in tool payloads.
                raise _FailureResult(
                    "AuthenticationRequired",
                    "Organization announcement sign-in could not be completed. Try again.",
                    source=SOURCE_MCP,
                ) from error
    return _client


async def reset_client() -> None:
    """Drop the authoring client so the next call reauthenticates.

    The shared core resolves its token once, in ``__init__``, and holds it for
    the object's lifetime; there is no lazy re-acquisition inside it. Because
    this server keeps one process-global client, an expired token would
    otherwise fail every subsequent tool call until the MCP host was restarted.
    Dropping the object is therefore the reauthentication mechanism: the next
    ``get_client()`` builds a fresh one and re-runs silent-first MSAL, which
    normally refreshes from the shared cache with no prompt.
    """
    global _client
    async with _client_lock:
        client, _client = _client, None
    # Closed outside the lock so teardown never blocks a concurrent rebuild.
    if client is not None:
        await client.aclose()


@asynccontextmanager
async def get_graph_client(
    tenant_id: str, object_id: Optional[str]
) -> AsyncIterator[GraphDirectoryClient]:
    """Capture one tenant-and-account-bound directory client for an operation.

    Keep only the current tenant's idle client. Replaced clients are closed
    after their captured users finish, not while another request is using them.
    The account comes from the captured authoring client, never from tool input.
    """
    global _graph_client
    previous = _graph_client
    client = previous
    if (
        client is None
        or client.tenant_id != tenant_id
        or client.object_id != object_id
    ):
        client = GraphDirectoryClient(tenant_id=tenant_id, object_id=object_id)
    _graph_client = client
    _graph_client_users[client] = _graph_client_users.get(client, 0) + 1
    try:
        if (
            previous is not None
            and previous is not client
            and not _graph_client_users.get(previous)
        ):
            await previous.aclose()
        yield client
    finally:
        remaining = _graph_client_users[client] - 1
        if remaining:
            _graph_client_users[client] = remaining
        else:
            del _graph_client_users[client]
            if client is not _graph_client:
                await client.aclose()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _text_result(payload: dict[str, Any], message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structuredContent=payload,
    )


class _FailureResult(Exception):
    """Carries a stable discriminated failure back to the tool boundary.

    Every MCP-only failure is one of the documented codes so the widget can
    branch on ``code`` and ``retryable`` instead of parsing message text.
    ``errors`` carries a *structured backend validation* payload when there is
    one, so field-level codes survive intact instead of being flattened into a
    single message.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        field: Optional[str] = None,
        source: str = SOURCE_MCP,
        errors: Optional[list[dict[str, Any]]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.field = field
        self.source = source
        self.errors = errors

    def as_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "retryable": self.retryable,
        }

    def as_error_list(self) -> list[dict[str, Any]]:
        """Every error to report, preserving a structured backend payload."""
        if self.errors:
            return [
                {
                    "code": entry["code"],
                    "field": entry["field"],
                    "message": entry["message"],
                    "retryable": False,
                }
                for entry in self.errors
            ]
        return [self.as_error()]


def _validation_failure(error: BulletinValidationError) -> _FailureResult:
    """Adapt an HTTP-200 ``EssBulletinSaveResult`` rejection.

    The wrapper's ``errors`` are carried through verbatim. The summary ``code``
    is the *first* backend code so a caller that only reads ``code`` still gets
    a real backend code rather than a generic one, and ``field`` is that entry's
    field so single-error cases keep their input binding.
    """
    first = error.errors[0]
    return _FailureResult(
        first["code"],
        first["message"],
        field=first["field"],
        retryable=False,
        source=SOURCE_BACKEND,
        errors=error.errors,
    )


def _classify_api_error(error: AgentConfigApiError) -> _FailureResult:
    """Map a backend failure onto the documented discriminated results.

    Structured backend validation errors keep their own code and message: the
    widget renders localized copy for ``AudienceRequired``,
    ``AudienceGroupInvalid``, ``BulletinLimitExceeded``, and the field-level
    title/description/action/date/priority/lifecycle codes, so replacing them
    with a generic code would lose that mapping.

    The backend's own ``Code`` is inspected before the HTTP status so a
    feature-gated tenant is reported as ``FeatureUnavailable`` rather than being
    flattened into an authorization or not-found result — but only when the code
    is a *real* backend code. ``HttpError`` is the core's placeholder for "the
    response carried no code", so it is discarded before any code-based
    decision.
    """
    if isinstance(error, IndeterminateWriteError):
        return _FailureResult("IndeterminateWrite", str(error), retryable=False)
    if isinstance(error, BulletinValidationError):
        return _validation_failure(error)

    raw_code, _, detail = str(error).partition(": ")
    backend_code = "" if raw_code == _FALLBACK_BACKEND_CODE else raw_code
    status = error.http_status

    if backend_code in _FEATURE_DISABLED_CODES and backend_code:
        return _FailureResult(
            "FeatureUnavailable",
            "Organization announcements are not enabled for this tenant.",
            source=SOURCE_BACKEND,
        )
    if status == 401:
        return _FailureResult(
            "AuthenticationRequired",
            "Sign in again to author organization announcements.",
            source=SOURCE_BACKEND,
        )
    if status == 403:
        return _FailureResult(
            "AuthorizationDenied",
            "This account is not authorized to author organization "
            "announcements in this tenant.",
            source=SOURCE_BACKEND,
        )
    if status == 404:
        return _FailureResult(
            "NotFound",
            "The announcement was not found.",
            source=SOURCE_BACKEND,
        )
    if status in (400, 409, 422):
        # A real backend validation failure. Without a backend code there is
        # nothing to map, so report a generic invalid request rather than
        # inventing one; the detail is the service's own message.
        return _FailureResult(
            backend_code or "InvalidRequest",
            detail or str(error),
            source=SOURCE_BACKEND,
        )
    if status in (429, 502, 503, 504):
        return _FailureResult(
            "NetworkError",
            "The Org Announcements service is temporarily unavailable.",
            retryable=True,
            source=SOURCE_BACKEND,
        )
    if status in (405, 501):
        return _FailureResult(
            "FeatureUnavailable",
            "Organization announcements are not enabled for this tenant.",
            source=SOURCE_BACKEND,
        )
    # Everything left is a server-side failure (500) or a response this client
    # could not interpret. It is emphatically NOT a validation error the maker
    # can fix, and the raw text can echo internal detail, so it becomes one
    # stable, privacy-safe code. Non-retryable: the request reached the service
    # and was processed, so an automatic replay would risk a duplicate write
    # without any expectation of a different answer.
    return _FailureResult(
        "ServiceError",
        "The Org Announcements service could not complete the request.",
        retryable=False,
        source=SOURCE_BACKEND,
    )


def _classify_graph_error(error: GraphDirectoryError) -> _FailureResult:
    return _FailureResult(
        error.code,
        str(error),
        retryable=error.retryable,
        source=SOURCE_GRAPH,
    )


class _CommittedRefreshError(Exception):
    """The write committed; only the follow-up refresh failed.

    Raised *after* the authoring API has definitely acknowledged a save, so the
    announcement exists regardless of what happens next. It is deliberately a
    distinct type from :class:`_FailureResult` because the two demand opposite
    handling: a normal failure means "nothing was written, you may retry", and
    this means "it was written, do not retry".
    """

    def __init__(self, cause: _FailureResult):
        super().__init__(cause.message)
        self.cause = cause


def _committed_refresh_failure(cause: _FailureResult) -> _FailureResult:
    """Build the explicit partial-success contract for a committed write.

    Retrying here is not merely wasteful, it is unsafe: the create path is
    unkeyed, so a replay would create a *second* announcement. The result is
    therefore a stable, non-retryable ``CommittedRefreshFailed`` that states
    plainly that the write succeeded and only the refresh did not, and the
    original refresh failure is preserved as a second entry so the widget can
    still tell a Graph outage from a service outage.
    """
    summary_message = (
        "The change was saved, but the updated list could not be loaded. "
        "Refresh to see the current state — do not repeat the action."
    )
    return _FailureResult(
        "CommittedRefreshFailed",
        summary_message,
        retryable=False,
        source=cause.source,
        errors=[
            {
                "code": "CommittedRefreshFailed",
                "field": None,
                "message": summary_message,
            },
            {
                "code": cause.code,
                "field": cause.field,
                "message": cause.message,
            },
        ],
    )


async def _resolve_audience_metadata(
    graph_client: GraphDirectoryClient,
    audience_ids: list[str],
) -> list[AudienceGroup]:
    """Resolve one canonical audience list into ordered display metadata."""
    if not audience_ids:
        return []
    try:
        resolved = await graph_client.resolve_groups(audience_ids)
    except GraphDirectoryError as error:
        raise _FailureResult(
            "AudienceMetadataUnavailable",
            f"Audience group names could not be loaded. {error}",
            retryable=error.retryable,
            source=SOURCE_GRAPH,
        ) from error
    return [
        AudienceGroup.model_validate(item)
        for item in build_audience_metadata(audience_ids, resolved)
    ]


async def _resolve_manager_metadata(
    graph_client: GraphDirectoryClient,
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Resolve audience metadata for every listed bulletin in one Graph batch.

    Soft-deleted rows are skipped: the manager drops them, so resolving their
    audience would issue Graph lookups for groups nobody will see.

    Deduplication applies only to the lookup batch. Each bulletin's canonical
    audience list is re-expanded in its own order, so per-item multiplicity and
    ordering stay exact.
    """
    visible = [config for config in items if not is_deleted_item(config)]

    all_ids: list[str] = []
    for config in visible:
        audience = config.get("audience")
        if isinstance(audience, list):
            all_ids.extend(
                group_id for group_id in audience if isinstance(group_id, str)
            )

    if not all_ids:
        return {}

    try:
        resolved = await graph_client.resolve_groups(all_ids)
    except GraphDirectoryError as error:
        raise _FailureResult(
            "AudienceMetadataUnavailable",
            f"Audience group names could not be loaded. {error}",
            retryable=error.retryable,
            source=SOURCE_GRAPH,
        ) from error

    metadata: dict[str, list[dict[str, Any]]] = {}
    for config in visible:
        bulletin = config.get("bulletin")
        bulletin_id = bulletin.get("id") if isinstance(bulletin, dict) else None
        audience = config.get("audience")
        metadata[bulletin_id or ""] = build_audience_metadata(
            [group_id for group_id in audience if isinstance(group_id, str)]
            if isinstance(audience, list)
            else [],
            resolved,
        )
    return metadata


async def _manager_state(
    client: OrgAnnouncementsClient, scope: dict[str, str],
    graph_client: GraphDirectoryClient,
) -> dict[str, Any]:
    items = await client.list_bulletins(scope["titleId"])
    return build_manager_state(
        items,
        await _resolve_manager_metadata(graph_client, items),
        _now(),
        tenant_id=scope["tenantId"],
        title_id=scope["titleId"],
    )


def _editor_payload(
    mode: EditorMode,
    config: Optional[dict[str, Any]],
    draft: AnnouncementEditorDraft,
    scope: dict[str, str],
) -> dict[str, Any]:
    return {
        **scope,
        "view": "editor",
        "mode": mode,
        "config": config,
        "draft": draft.model_dump(
            mode="json", exclude={"id"} if draft.id is None else set()
        ),
    }


def _open_error_payload(
    request: dict[str, Any], failure: _FailureResult, scope: dict[str, str]
) -> CallToolResult:
    """Return a recoverable open error instead of a half-rendered editor.

    The request is response-only retry state, including the original suggestion.
    It is never logged or sent to telemetry.
    """
    payload = {
        **scope,
        "view": "error",
        "request": request,
        "code": failure.code,
        "message": failure.message,
        "retryable": failure.retryable,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=failure.message)],
        structuredContent=payload,
        isError=True,
    )


def _open_success(
    payload: dict[str, Any], message: str, started: float
) -> CallToolResult:
    record_operation(
        "open_org_announcements",
        outcome="success",
        latency_ms=_elapsed_ms(started),
    )
    return _text_result(payload, message)


def _open_failure(
    request: dict[str, Any],
    failure: _FailureResult,
    started: float,
    scope: dict[str, str],
) -> CallToolResult:
    _LOGGER.warning("open_org_announcements failed: %s", failure.code)
    record_operation(
        "open_org_announcements",
        outcome="failure",
        latency_ms=_elapsed_ms(started),
        error_code=failure.code,
        error_source=failure.source,
    )
    return _open_error_payload(request, failure, scope)


@mcp.resource(
    ORG_ANNOUNCEMENTS_RESOURCE_URI,
    name="Org announcements",
    title="Org announcements",
    description="Announcement manager and editor for the selected ESS agent.",
    mime_type=WIDGET_MIME_TYPE,
    meta=_widget_resource_meta(),
)
def org_announcements_widget() -> str:
    return _widget_shell()


@mcp.tool(
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def list_agent_configs() -> str:
    """List configured deployed ESS agents; never initialize configuration."""
    client = await get_client()
    return json.dumps(await client.list_agent_configs(), indent=2)


@mcp.tool(
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def search_agents(searchString: str) -> str:
    """Find deployed ESS agents by name to resolve their titleId."""
    client = await get_client()
    return json.dumps(await client.search_agents(searchString), indent=2)


@mcp.tool(
    meta=_widget_tool_meta(),
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def open_org_announcements(
    titleId: str,
    view: Literal["manager", "editor"],
    mode: Optional[Literal["create", "edit"]] = None,
    bulletinId: Optional[str] = None,
    suggestedDraft: Optional[SuggestedBulletinDraft] = None,
) -> CallToolResult:
    """Open announcements for the selected agent in the manager or editor.

    This tool only reads: it never creates, updates, or publishes. The model
    calls it at most once per maker turn; the widget uses it for navigation
    within the same tenant-and-agent scope. Manager takes no editor arguments.
    Editor requires mode=create without bulletinId, or mode=edit with bulletinId.
    suggestedDraft is supported only for create.
    """
    # The flat tool signature stays compatible with MCP callers. Validate the
    # combination before entering the recoverable widget-error path: an invalid
    # request is not safe retry state and cannot be rendered as an error view.
    try:
        _validate_title_id(titleId)
        if bulletinId is not None:
            _validate_bulletin_id(bulletinId)
        validated = OpenAnnouncementsRequest(
            titleId=titleId, view=view, mode=mode,
            bulletinId=bulletinId, suggestedDraft=suggestedDraft,
        )
    except ValidationError as error:
        messages = "; ".join(
            entry["msg"] for entry in error.errors(include_input=False)
        )
        raise ToolError(f"Invalid announcement opener: {messages}") from None
    except ValueError as error:
        raise ToolError(f"Invalid announcement opener: {error}") from None

    started = time.monotonic()
    scope = {"titleId": titleId}
    request = validated.model_dump(exclude_none=True, exclude={"suggestedDraft"})
    if suggestedDraft is not None:
        request["suggestedDraft"] = suggestedDraft.retry_payload()

    try:
        # Capture once even for an empty create. Subsequent reads and post-save
        # refreshes must never adopt a different global client's tenant.
        client = await get_client()
        scope = {"tenantId": client.tenant_id, "titleId": titleId}

        if view == "manager":
            async with get_graph_client(scope["tenantId"], client.object_id) as graph_client:
                state = await _manager_state(client, scope, graph_client)
            return _open_success(
                {"view": "manager", **state},
                "Opened announcements for the selected ESS agent.",
                started,
            )

        if mode == "create":
            async with get_graph_client(scope["tenantId"], client.object_id) as graph_client:
                audience_metadata = await _resolve_audience_metadata(
                    graph_client,
                    list(suggestedDraft.audience)
                    if suggestedDraft is not None and suggestedDraft.audience
                    else [],
                )
            draft = build_create_draft(suggestedDraft, audience_metadata)
            return _open_success(
                _editor_payload("create", None, draft, scope),
                "Opened a new organization announcement for review. Nothing is "
                "saved until you publish or save a draft in the editor.",
                started,
            )

        config = await client.get_bulletin(titleId, bulletinId)
        audience = config.get("audience")
        async with get_graph_client(scope["tenantId"], client.object_id) as graph_client:
            audience_metadata = await _resolve_audience_metadata(
                graph_client,
                [group_id for group_id in audience if isinstance(group_id, str)]
                if isinstance(audience, list)
                else [],
            )
        draft = build_editor_draft_from_config(config, audience_metadata)
        message = "Opened the announcement for editing."
        return _open_success(
            _editor_payload("edit", config, draft, scope), message, started
        )

    except _FailureResult as failure:
        return _open_failure(request, failure, started, scope)
    except AgentConfigApiError as error:
        return _open_failure(request, await _failure_from(error), started, scope)
    except httpx.RequestError:
        return _open_failure(
            request,
            _FailureResult(
                "NetworkError",
                "The Org Announcements service could not be reached.",
                retryable=True,
                source=SOURCE_BACKEND,
            ),
            started,
            scope,
        )
    except (ValidationError, ValueError) as error:
        return _open_failure(
            request, _FailureResult("InvalidRequest", str(error)), started, scope
        )


def _fail(
    operation: str, failure: _FailureResult, started: float, scope: dict[str, str]
) -> CallToolResult:
    """Emit the content-free failure event and build the tool result."""
    record_operation(
        operation,
        outcome="failure",
        latency_ms=_elapsed_ms(started),
        error_code=failure.code,
        error_source=failure.source,
    )
    return _mutation_failure(failure, scope)


def _mutation_failure(
    failure: _FailureResult, scope: dict[str, str]
) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=failure.message)],
        structuredContent={
            **scope, "status": "failure", "errors": failure.as_error_list()
        },
        isError=True,
    )


async def _failure_from(error: Exception) -> _FailureResult:
    """Classify a failure and reauthenticate the authoring client on a 401.

    A 401 from the authoring API means the cached delegated token is expired or
    revoked. The shared core holds its token for the client object's lifetime,
    so the stale credential is discarded by discarding the client; the next tool
    call then rebuilds it and re-runs silent-first MSAL.

    Only an *authoring-side* 401 resets the authoring client. The Graph client
    reports the same ``AuthenticationRequired`` code for its own expiry and
    handles that itself, so the source bucket is what distinguishes them —
    resetting on a Graph 401 would throw away a perfectly good WeveNova token.
    """
    failure = _to_failure(error)
    if failure.code == "AuthenticationRequired" and failure.source == SOURCE_BACKEND:
        await reset_client()
    return failure


def _to_failure(error: Exception) -> _FailureResult:
    if isinstance(error, _FailureResult):
        return error
    if isinstance(error, AgentConfigApiError):
        return _classify_api_error(error)
    if isinstance(error, GraphDirectoryError):
        return _classify_graph_error(error)
    if isinstance(error, httpx.RequestError):
        return _FailureResult(
            "NetworkError",
            "The Org Announcements service could not be reached.",
            retryable=True,
            source=SOURCE_BACKEND,
        )
    return _FailureResult("InvalidRequest", str(error))


# Everything a mutation can raise. Listed once so the write step and the
# post-commit refresh step cannot drift apart and let an exception escape one
# but not the other.
_MUTATION_ERRORS = (
    _FailureResult,
    AgentConfigApiError,
    GraphDirectoryError,
    httpx.RequestError,
    ValueError,
)


async def _saved_item_result(
    client: OrgAnnouncementsClient,
    scope: dict[str, str],
    config: dict[str, Any],
    message: str,
) -> CallToolResult:
    """Return the canonical saved item plus refreshed manager state.

    Called only after the write has been acknowledged, so any error raised here
    is a *refresh* failure over a committed record. It is wrapped in
    :class:`_CommittedRefreshError` so the caller cannot mistake it for a failed
    write and offer a retry that would duplicate the announcement.
    """
    try:
        audience = config.get("audience")
        async with get_graph_client(scope["tenantId"], client.object_id) as graph_client:
            audience_metadata = await _resolve_audience_metadata(
                graph_client,
                [group_id for group_id in audience if isinstance(group_id, str)]
                if isinstance(audience, list)
                else [],
            )
            manager = await _manager_state(client, scope, graph_client)
    except _MUTATION_ERRORS as error:
        raise _CommittedRefreshError(await _failure_from(error)) from error

    return _text_result(
        {
            **scope,
            "status": "success",
            "item": {
                "config": config,
                "audienceMetadata": [
                    group.model_dump(mode="json") for group in audience_metadata
                ],
            },
            "manager": manager,
        },
        message,
    )


@mcp.tool(
    meta=_app_only_tool_meta(),
    annotations=_MUTATION_ANNOTATIONS,
)
async def save_bulletin(
    titleId: str,
    bulletin: dict[str, Any],
    audience: list[str],
    status: Literal["draft", "published"],
    id: Optional[str] = None,  # noqa: A002 — the widget's wire field name
) -> CallToolResult:
    """Create or update an announcement with its complete authored state."""
    started = time.monotonic()
    scope = {"titleId": titleId}
    try:
        _validate_title_id(titleId)
        request = SaveBulletinRequest.model_validate(
            {
                "id": id,
                "bulletin": bulletin,
                "audience": audience,
                "status": status,
            }
        )
    except ValueError as error:
        return _fail(
            "save_bulletin",
            _FailureResult("InvalidRequest", str(error)),
            started,
            scope,
        )

    payload = request.model_dump(mode="json", exclude_none=True)
    try:
        client = await get_client()
        scope = {"tenantId": client.tenant_id, "titleId": titleId}
        saved = await client.save_bulletin(titleId, payload)
    except _MUTATION_ERRORS as error:
        failure = await _failure_from(error)
        _LOGGER.warning(
            "save_bulletin failed: %s (create=%s)", failure.code, id is None
        )
        return _fail("save_bulletin", failure, started, scope)

    try:
        result = await _saved_item_result(
            client,
            scope,
            saved,
            "Published the organization announcement."
            if status == "published"
            else "Saved the organization announcement draft.",
        )
    except _CommittedRefreshError as error:
        # The write is committed. Report the explicit partial success so the
        # widget tells the maker to refresh instead of offering a retry that
        # would create a second announcement.
        _LOGGER.warning(
            "save_bulletin refresh failed after commit: %s", error.cause.code
        )
        return _fail(
            "save_bulletin", _committed_refresh_failure(error.cause), started, scope
        )

    record_operation(
        "save_bulletin",
        outcome="success",
        latency_ms=_elapsed_ms(started),
    )
    return result


@mcp.tool(
    meta=_app_only_tool_meta(),
    annotations=_DESTRUCTIVE_ANNOTATIONS,
)
async def transition_bulletin(
    titleId: str,
    id: str,  # noqa: A002 — the widget's wire field name
    transition: TransitionName,
) -> CallToolResult:
    """Archive, unarchive, move to draft, or delete an announcement.

    The request carries only the identifier and the new status. The service
    loads the canonical record, preserves its authored content and audience, and
    validates the lifecycle change, so no client-side merge is performed.

    ``TransitionName`` lists exactly the four supported operations. Publish now
    is deliberately absent and is rejected at argument validation: it must go
    through ``save_bulletin`` with the row's complete canonical state so the new
    start instant cannot race a concurrent edit.

    KNOWN LIMITATION (Vorpal compatibility). A legacy client sending
    ``transition: "publishNow"`` is rejected by FastMCP's *schema* validation,
    before this function runs, so it surfaces as a protocol ``ToolError`` rather
    than this server's structured ``InvalidRequest`` result. Converting it would
    require widening ``transition`` to a free string, which would advertise
    ``publishNow`` as acceptable in the production schema and re-open the race
    that removing it closed — so the rollout prerequisite stands: ship a Vorpal
    build that routes publish-now through ``save_bulletin``. The current
    boundary is pinned by tests so it stays a known contract.
    """
    started = time.monotonic()
    scope = {"titleId": titleId}
    try:
        _validate_title_id(titleId)
        client = await get_client()
        scope = {"tenantId": client.tenant_id, "titleId": titleId}
        changed = await client.transition_bulletin(
            titleId, id, TRANSITION_STATUS[transition]
        )
    except _MUTATION_ERRORS as error:
        failure = await _failure_from(error)
        _LOGGER.warning(
            "transition_bulletin failed: %s (%s)", failure.code, transition
        )
        return _fail("transition_bulletin", failure, started, scope)

    # The transition is committed from here on. A refresh failure must never be
    # reported as a retryable normal failure, because the lifecycle change has
    # already been applied and re-issuing it could fail validation or move the
    # record again.
    try:
        async with get_graph_client(scope["tenantId"], client.object_id) as graph_client:
            manager = await _manager_state(client, scope, graph_client)
    except _MUTATION_ERRORS as error:
        cause = await _failure_from(error)
        _LOGGER.warning(
            "transition_bulletin refresh failed after commit: %s (%s)",
            cause.code,
            transition,
        )
        return _fail(
            "transition_bulletin", _committed_refresh_failure(cause), started, scope
        )

    record_operation(
        "transition_bulletin",
        outcome="success",
        latency_ms=_elapsed_ms(started),
    )
    # The canonical changed row is included alongside the manager state. It is
    # additive: the widget's existing manager-shaped contract is untouched, so a
    # host that strips unknown fields simply ignores ``item`` and still gets a
    # correct refresh.
    return _text_result(
        {
            **scope, "status": "success",
            "item": {"config": changed}, "manager": manager,
        },
        "Updated the organization announcement.",
    )


@mcp.tool(
    meta=_app_only_tool_meta(),
    annotations=_MUTATION_ANNOTATIONS,
)
async def duplicate_bulletin(
    titleId: str,
    id: str,  # noqa: A002 — the widget's wire field name
) -> CallToolResult:
    """Copy an existing announcement into a new Draft.

    Loads the canonical source, strips its identity and audit fields, and
    creates a new Draft. A missing source is a not-found failure, never a
    create: duplicating something that no longer exists must not invent a
    record.
    """
    started = time.monotonic()
    scope = {"titleId": titleId}
    try:
        _validate_title_id(titleId)
        client = await get_client()
        scope = {"tenantId": client.tenant_id, "titleId": titleId}
        source = await client.get_bulletin(titleId, id)
    except _MUTATION_ERRORS as error:
        failure = await _failure_from(error)
        _LOGGER.warning("duplicate_bulletin source load failed: %s", failure.code)
        return _fail("duplicate_bulletin", failure, started, scope)

    # Stored content is forwarded verbatim, so it never passes through
    # BulletinInput. The blank-schedule sentinel is stripped explicitly here for
    # the same reason it is coerced there: "" is not a DateTimeOffset, and
    # sending it would fail model binding on a copy the maker never edited.
    bulletin = without_blank_schedule(
        {
            key: value
            for key, value in source["bulletin"].items()
            if key not in _COPY_STRIPPED_FIELDS
        }
    )
    audience = source.get("audience")
    payload = {
        "bulletin": bulletin,
        "audience": [
            group_id
            for group_id in (audience if isinstance(audience, list) else [])
            if isinstance(group_id, str)
        ],
        "status": "draft",
    }

    try:
        created = await client.save_bulletin(titleId, payload)
    except _MUTATION_ERRORS as error:
        failure = await _failure_from(error)
        _LOGGER.warning("duplicate_bulletin failed: %s", failure.code)
        return _fail("duplicate_bulletin", failure, started, scope)

    try:
        result = await _saved_item_result(
            client, scope, created,
            "Created a draft copy of the organization announcement.",
        )
    except _CommittedRefreshError as error:
        # The copy exists. This is an unkeyed create, so a retry would produce a
        # second copy; report the committed partial success instead.
        _LOGGER.warning(
            "duplicate_bulletin refresh failed after commit: %s", error.cause.code
        )
        return _fail(
            "duplicate_bulletin", _committed_refresh_failure(error.cause), started, scope
        )

    record_operation(
        "duplicate_bulletin",
        outcome="success",
        latency_ms=_elapsed_ms(started),
    )
    return result


@mcp.tool(
    meta=_shared_tool_meta(),
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def search_audience_groups(query: str) -> CallToolResult:
    """Search eligible audience groups by display name.

    Returns at most 20 security groups, mail-enabled security groups, or classic
    distribution groups, deduplicated by ID and in a deterministic order.
    Microsoft 365 groups and dynamic-membership groups are not offered.

    ``exhausted`` and ``pagesExamined`` are reported so the caller can tell "no
    more matches exist" from "the page budget ran out". Without them a capped
    search looks identical to an exhausted one and the maker would be told a
    group does not exist when it simply was not reached.
    """
    started = time.monotonic()
    try:
        escape_search_value(query)
        authoring_client = await get_client()
        async with get_graph_client(
            authoring_client.tenant_id, authoring_client.object_id
        ) as graph_client:
            result = await graph_client.search_groups(query)
    except (_FailureResult, GraphDirectoryError, AgentConfigApiError, httpx.RequestError) as error:
        failure = await _failure_from(error)
        _LOGGER.warning("search_audience_groups failed: %s", failure.code)
        record_operation(
            "search_audience_groups",
            outcome="failure",
            latency_ms=_elapsed_ms(started),
            error_code=failure.code,
            error_source=failure.source,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=failure.message)],
            structuredContent={
                "status": "failure",
                "code": failure.code,
                "retryable": failure.retryable,
            },
            isError=True,
        )
    except ValueError as error:
        _LOGGER.warning("search_audience_groups rejected an invalid query")
        record_operation(
            "search_audience_groups",
            outcome="failure",
            latency_ms=_elapsed_ms(started),
            error_code="InvalidRequest",
            error_source=SOURCE_MCP,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=str(error))],
            structuredContent={
                "status": "failure",
                "code": "InvalidRequest",
                "retryable": False,
            },
            isError=True,
        )

    groups = result["groups"]
    record_operation(
        "search_audience_groups",
        outcome="success",
        latency_ms=_elapsed_ms(started),
    )
    return _text_result(
        {
            "status": "success",
            "groups": groups,
            "exhausted": result["exhausted"],
            "pagesExamined": result["pagesExamined"],
        },
        f"Found {len(groups)} eligible audience group(s).",
    )


if __name__ == "__main__":
    mcp.run()
