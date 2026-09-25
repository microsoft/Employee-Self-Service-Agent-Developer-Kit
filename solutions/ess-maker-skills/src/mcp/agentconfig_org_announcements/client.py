# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""WeveNova Org Announcements (EssBulletin) authoring client.

The shared client core — bearer-token acquisition, the JWT ``tid`` decode, the
httpx session, and the retrying ``_request`` — lives in the neutral
``agentconfig_core`` core (``base_client.AgentConfigBaseClient``). This module
keeps only what is specific to the Org Announcements authoring surface: the
v1.1 base URL, the three agent-qualified ``EssBulletins`` routes, and the
manager-state classification.

The collection is keyed by the authenticated tenant and deployed ESS titleId.
This new backend surface must never fall back to tenant-only routes.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx

# The AgentConfiguration MCP family lives at the ``src/mcp`` root as sibling
# folders sharing the neutral ``agentconfig_core`` client core. There is no
# package __init__.py, and each server launches with cwd set to its own folder
# on a flat sys.path, so make the sibling ``agentconfig_core`` folder importable.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core"
    ),
)

from _odata import (  # noqa: E402
    _require_odata_id,
    _validate_https_base_url,
    _validate_title_id,
)
from agent_discovery import AgentDiscoveryClient  # noqa: E402
from base_client import AgentConfigApiError  # noqa: E402


DEFAULT_ORG_ANNOUNCEMENTS_BASE_URL = "https://substrate.office.com/weveb2/api/v1.1"

# WeveNova returns every current item followed by at most this many archived
# items, with no envelope metadata. Hitting the cap means the archived window is
# truncated; it does not reveal an exact archived total.
ARCHIVED_WINDOW_SIZE = 50


class IndeterminateWriteError(AgentConfigApiError):
    """An unkeyed create may have committed but was never acknowledged.

    Raised only for writes that cannot be safely replayed: an unkeyed create or
    a duplicate that failed with an ambiguous network error or a 502/503/504
    gateway response. The caller must refresh canonical state before retrying so
    a committed-but-unacknowledged POST is never duplicated.
    """


class BulletinValidationError(AgentConfigApiError):
    """The save endpoint returned HTTP 200 carrying structured field errors.

    WeveNova's ``EssBulletinSaveResult`` reports validation failure *inside* a
    success response: ``Errors`` is non-empty and ``Id`` is absent. Every
    ``{code, field, message}`` entry is preserved verbatim so the widget can
    render its localized copy against the exact backend code and attach the
    message to the exact field. Flattening them into one generic message would
    silently destroy that mapping and leave the maker with no way to know which
    field to fix.
    """

    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__(
            "The Org Announcements service rejected the announcement.",
            http_status=200,
        )
        self.errors = errors


class CommittedCanonicalReloadError(Exception):
    """A Save committed, but its canonical keyed reload failed."""

    def __init__(self, cause: AgentConfigApiError | httpx.RequestError):
        super().__init__(
            "The announcement was saved, but its canonical state could not be reloaded."
        )
        self.cause = cause


def validate_title_id(title_id: str) -> str:
    """Validate the opaque Employee Agent route key."""
    return _validate_title_id(title_id)


def validate_bulletin_id(bulletin_id: str) -> str:
    """Validate and canonicalize the backend-assigned OData Guid key."""
    if not isinstance(bulletin_id, str) or not bulletin_id:
        raise ValueError("bulletinId must be a non-empty GUID string")
    if bulletin_id != bulletin_id.strip():
        raise ValueError("bulletinId must not have surrounding whitespace")
    try:
        parsed = UUID(bulletin_id)
    except (ValueError, AttributeError) as error:
        raise ValueError("bulletinId must be a valid GUID") from error
    if parsed.int == 0:
        raise ValueError("bulletinId must not be the empty GUID")
    return str(parsed)


_BULLETIN_FIELD_MAP = {
    "Type": "type",
    "Priority": "priority",
    "Title": "title",
    "Description": "description",
    "PrimaryAction": "primaryAction",
    "SecondaryAction": "secondaryAction",
    "StartDate": "startDate",
    "EndDate": "endDate",
}

_ACTION_FIELD_MAP = {
    "ActionType": "actionType",
    "Label": "label",
    "Url": "url",
    "Prompt": "prompt",
}


def _from_odata_action(payload: Any) -> Optional[dict[str, Any]]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise AgentConfigApiError(
            "Org Announcements API returned an invalid bulletin action"
        )
    return {
        target: payload[source]
        for source, target in _ACTION_FIELD_MAP.items()
        if source in payload
    }


def _from_odata_bulletin(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AgentConfigApiError(
            "Org Announcements API returned invalid bulletin content"
        )
    if "Id" in payload or "id" in payload:
        raise AgentConfigApiError(
            "Org Announcements API returned a duplicate id inside bulletin content"
        )

    result: dict[str, Any] = {}
    for source, target in _BULLETIN_FIELD_MAP.items():
        if source not in payload:
            continue
        value = payload[source]
        if source in ("PrimaryAction", "SecondaryAction"):
            value = _from_odata_action(value)
        result[target] = value
    return result


def _to_odata_action(payload: Any) -> Optional[dict[str, Any]]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("bulletin actions must be objects")
    return {
        source: payload[target]
        for source, target in _ACTION_FIELD_MAP.items()
        if target in payload
    }


def _to_odata_bulletin(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("bulletin must be an object")
    result: dict[str, Any] = {}
    for source, target in _BULLETIN_FIELD_MAP.items():
        if target not in payload:
            continue
        value = payload[target]
        if target in ("primaryAction", "secondaryAction"):
            value = _to_odata_action(value)
        result[source] = value
    return result


def _to_odata_save_input(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "id" in payload:
        result["Id"] = validate_bulletin_id(payload["id"])
    if "bulletin" in payload:
        result["Bulletin"] = _to_odata_bulletin(payload["bulletin"])
    if "audience" in payload:
        result["Audience"] = payload["audience"]
    if "status" not in payload:
        raise ValueError("status is required")
    result["Status"] = payload["status"]
    return result


def _parse_instant(value: Any) -> Optional[datetime]:
    """Parse a UTC ISO instant, returning ``None`` for absent or unparseable text.

    ``None`` means "no boundary", which the classifier treats as open-ended
    rather than as an error: an unscheduled published item is current.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_deleted_item(config: dict[str, Any]) -> bool:
    """Classify one stored configuration as soft-deleted.

    ``delete`` is a lifecycle transition, not a hard removal, so the list
    endpoint can still return the row. A deleted announcement is not a working
    item and is not an archived item the maker can restore, so it is excluded
    from the manager entirely rather than being counted in either bucket.
    """
    return config.get("status") == "deleted"


def is_archived_item(config: dict[str, Any], now: datetime) -> bool:
    """Classify one stored configuration as archived.

    Archived means Retired, or Published with an end instant already elapsed.
    Everything else — Draft, and Published without an elapsed end — is current.
    Position in the API response is not used, because the list carries no
    envelope metadata that would make position authoritative.
    """
    status = config.get("status")
    if status == "retired":
        return True
    if status != "published":
        return False

    bulletin = config.get("bulletin")
    end = _parse_instant(bulletin.get("endDate")) if isinstance(bulletin, dict) else None
    return end is not None and end < now


class OrgAnnouncementsClient(AgentDiscoveryClient):
    """Async client for the tenant-and-agent-scoped ``EssBulletins`` routes.

    Inherits auth, the token decode, the httpx session, and the retrying
    ``_request`` from ``AgentConfigBaseClient``; adds only the v1.1 base URL and
    the three authoring routes. WeveNova's OData properties are PascalCase;
    this client explicitly adapts them to the existing lower-camel MCP/widget
    contract at the HTTP boundary.
    """

    def __init__(self, *, transport: Optional[httpx.AsyncBaseTransport] = None):
        base_url = _validate_https_base_url(
            os.environ.get(
                "ORG_ANNOUNCEMENTS_BASE_URL", DEFAULT_ORG_ANNOUNCEMENTS_BASE_URL
            ),
            "ORG_ANNOUNCEMENTS_BASE_URL",
        )
        super().__init__(
            base_url=base_url,
            logger_name="ess-org-announcements",
            transport=transport,
        )

    def _collection_path(self, title_id: str) -> str:
        encoded = _require_odata_id(validate_title_id(title_id), "titleId")
        return f"tenants('{self.tenant_id}')/EmployeeAgents('{encoded}')/EssBulletins"

    @staticmethod
    def _require_config(payload: Any, title_id: str) -> dict[str, Any]:
        """Reject a success-shaped response that is not a canonical record.

        A malformed body must not become an empty default, because the widget
        would then render a blank editor over real stored content.
        """
        if not isinstance(payload, dict):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid bulletin configuration"
            )
        if payload.get("TitleId") != title_id:
            raise AgentConfigApiError(
                "Org Announcements API returned a configuration with missing "
                "or mismatched titleId"
            )
        raw_id = payload.get("Id")
        if not isinstance(raw_id, str):
            raise AgentConfigApiError(
                "Org Announcements API returned a configuration without a valid id"
            )
        try:
            bulletin_id = validate_bulletin_id(raw_id)
        except ValueError as error:
            raise AgentConfigApiError(
                "Org Announcements API returned a configuration without a valid id"
            ) from error
        audience = payload.get("Audience")
        if not isinstance(audience, list) or not all(
            isinstance(group_id, str) for group_id in audience
        ):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid audience"
            )
        status = payload.get("Status")
        if not isinstance(status, str) or not status:
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid status"
            )

        config = {
            "id": bulletin_id,
            "titleId": title_id,
            "bulletin": _from_odata_bulletin(payload.get("Bulletin")),
            "audience": audience,
            "status": status,
        }
        for source, target in (
            ("CreatedBy", "createdBy"),
            ("CreatedOn", "createdOn"),
            ("ModifiedDate", "modifiedDate"),
        ):
            if source in payload:
                config[target] = payload[source]
        return config

    @classmethod
    def _unwrap_collection(cls, payload: Any, title_id: str) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("value"), list):
            items = payload["value"]
        else:
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid collection response"
            )
        return [cls._require_config(item, title_id) for item in items]

    @staticmethod
    def _normalize_save_errors(raw: Any) -> list[dict[str, Any]]:
        """Project the wrapper's ``errors`` into ``{code, field, message}`` rows.

        Every entry is preserved — none are collapsed, deduplicated, or dropped
        — because the widget maps each backend ``code`` to localized copy and
        binds each ``field`` to an input. An entry that is not an object at all
        is still represented (with the raw text as its message) rather than
        discarded, so a schema drift surfaces as a visible error instead of a
        silently successful save.
        """
        normalized: list[dict[str, Any]] = []
        for entry in raw:
            if isinstance(entry, dict):
                code = entry.get("Code")
                field = entry.get("Field")
                message = entry.get("Message")
                normalized.append(
                    {
                        "code": (
                            code
                            if isinstance(code, str) and code
                            else "InvalidRequest"
                        ),
                        "field": field if isinstance(field, str) and field else None,
                        "message": (
                            message
                            if isinstance(message, str) and message
                            else "The Org Announcements service rejected this value."
                        ),
                    }
                )
            else:
                normalized.append(
                    {
                        "code": "InvalidRequest",
                        "field": None,
                        "message": str(entry),
                    }
                )
        return normalized

    @classmethod
    def _unwrap_save_result(
        cls, payload: Any, *, requested_id: Optional[str]
    ) -> str:
        """Validate and unwrap an ``EssBulletinSaveResult``.

        The OData action answers HTTP 200 with ``{Id, Errors}`` and reports
        validation failure inside a success status. Three outcomes are
        distinguished:

        * ``Errors`` non-empty → :class:`BulletinValidationError` carrying every
          entry, so field-level backend codes survive to the widget.
        * ``Errors`` empty and ``Id`` valid → the affected canonical key, after
          checking it agrees with the ID the caller asked to update.
        * anything else → :class:`AgentConfigApiError`, never an empty default:
          a blank record would render an empty editor over real stored content.
        """
        if not isinstance(payload, dict):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid save response"
            )

        errors = payload.get("Errors")
        if not isinstance(errors, list):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid save error list"
            )
        if errors:
            raise BulletinValidationError(cls._normalize_save_errors(errors))

        raw_id = payload.get("Id")
        if not isinstance(raw_id, str):
            raise AgentConfigApiError(
                "Org Announcements API returned a saved announcement without an id"
            )
        try:
            canonical_id = validate_bulletin_id(raw_id)
        except ValueError as error:
            raise AgentConfigApiError(
                "Org Announcements API returned a saved announcement without a valid id"
            ) from error
        if requested_id is not None and canonical_id != requested_id:
            raise AgentConfigApiError(
                "Org Announcements API returned a different announcement "
                "than the one that was updated"
            )
        return canonical_id

    async def list_bulletins(self, title_id: str) -> list[dict[str, Any]]:
        """List every current item plus the most recent archived window."""
        payload = await self._request(
            "GET",
            f"{self._collection_path(title_id)}/ManagementView()",
            transform_payload=False,
        )
        return self._unwrap_collection(payload, title_id)

    async def get_bulletin(self, title_id: str, bulletin_id: str) -> dict[str, Any]:
        """Load one canonical stored configuration."""
        path = (
            f"{self._collection_path(title_id)}"
            f"({validate_bulletin_id(bulletin_id)})"
        )
        return self._require_config(
            await self._request("GET", path, transform_payload=False), title_id
        )

    async def save_bulletin(
        self, title_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or update through the authoring ``save`` endpoint.

        Returns the canonical configuration from a keyed GET after validating
        the ``EssBulletinSaveResult`` receipt. A payload without ``id`` is an
        unkeyed create; replaying one after an ambiguous failure could duplicate
        a committed record, so ambiguous retries are disabled and surfaced as
        :class:`IndeterminateWriteError`.
        """
        requested_id = (
            validate_bulletin_id(payload["id"]) if payload.get("id") else None
        )
        is_create = not requested_id
        try:
            result = await self._request(
                "POST",
                f"{self._collection_path(title_id)}/Save",
                json={"input": _to_odata_save_input(payload)},
                transform_payload=False,
                idempotent=not is_create,
            )
        except (AgentConfigApiError, httpx.RequestError) as error:
            if is_create and _is_ambiguous_write_failure(error):
                raise IndeterminateWriteError(
                    "The announcement may have been created but the response was "
                    "never received. Refresh before retrying."
                ) from error
            raise
        saved_id = self._unwrap_save_result(
            result,
            requested_id=requested_id if not is_create else None,
        )
        try:
            return await self.get_bulletin(title_id, saved_id)
        except (AgentConfigApiError, httpx.RequestError) as error:
            raise CommittedCanonicalReloadError(error) from error

    async def transition_bulletin(
        self, title_id: str, bulletin_id: str, status: str
    ) -> Optional[dict[str, Any]]:
        """Apply a minimal lifecycle status change.

        WeveNova performs the transition inside ``SaveAsync``: it loads the
        canonical record server-side, preserves authored content and audience,
        validates the transition, and writes the new status. Sending only
        ``{id, status}`` therefore avoids a separate read/merge/write and cannot
        clobber content with stale client state.

        The response is the same ``EssBulletinSaveResult`` receipt the content
        save returns. Non-delete transitions are followed by a keyed GET;
        delete is a tombstone and therefore has no readable canonical resource.
        """
        validated_id = validate_bulletin_id(bulletin_id)
        saved_id = self._unwrap_save_result(
            await self._request(
                "POST",
                f"{self._collection_path(title_id)}/Save",
                json={
                    "input": {
                        "Id": validated_id,
                        "Status": status,
                    }
                },
                transform_payload=False,
                idempotent=True,
            ),
            requested_id=validated_id,
        )
        if status == "deleted":
            return None
        try:
            return await self.get_bulletin(title_id, saved_id)
        except (AgentConfigApiError, httpx.RequestError) as error:
            raise CommittedCanonicalReloadError(error) from error


def _is_ambiguous_write_failure(
    error: AgentConfigApiError | httpx.RequestError,
) -> bool:
    """Decide whether a write failure leaves the commit outcome unknown.

    A transport error never reached a response, and a 502/503/504 came from an
    intermediary that may have forwarded the request. A 4xx or a 500 from the
    service itself is a definite rejection, so it stays a normal error.
    """
    if isinstance(error, httpx.RequestError):
        return True
    return error.http_status in (502, 503, 504)


def build_manager_state(
    items: list[dict[str, Any]],
    audience_metadata: dict[str, list[dict[str, Any]]],
    now: datetime,
    *,
    tenant_id: str,
    title_id: str,
) -> dict[str, Any]:
    """Adapt the API list into the widget's manager state.

    Soft-deleted rows are dropped before any counting: they are neither a
    working item nor a restorable archived item, so including them would inflate
    ``workingSetCount`` or push ``archivedTruncated`` true off records the maker
    cannot see or act on.

    ``workingSetCount`` is the exact number of current items, computed from
    status and schedule rather than from list position. ``archivedTruncated``
    reports only that the archived window filled, matching the widget copy
    "Showing the 50 most recently archived announcements"; it never claims an
    exact archived total. API item order is preserved.
    """
    archived_count = 0
    working_set_count = 0
    view_models: list[dict[str, Any]] = []

    for config in items:
        if is_deleted_item(config):
            continue
        if is_archived_item(config, now):
            archived_count += 1
        else:
            working_set_count += 1
        bulletin_id = config.get("id", "")
        view_models.append(
            {
                "config": config,
                "audienceMetadata": audience_metadata.get(bulletin_id, []),
            }
        )

    return {
        "tenantId": tenant_id,
        "titleId": title_id,
        "items": view_models,
        "workingSetCount": working_set_count,
        "archivedTruncated": archived_count >= ARCHIVED_WINDOW_SIZE,
    }
