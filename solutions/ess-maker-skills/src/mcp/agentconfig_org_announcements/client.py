# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""WeveNova Org Announcements (EssBulletin) authoring client.

The shared client core — bearer-token acquisition, the JWT ``tid`` decode, the
httpx session, and the retrying ``_request`` — lives in the neutral
``agentconfig_core`` core (``base_client.AgentConfigBaseClient``). This module
keeps only what is specific to the Org Announcements authoring surface: the
v1.1 base URL, the three agent-qualified ``essbulletins`` routes, and the
manager-state classification.

The collection is keyed by the authenticated tenant and deployed ESS titleId.
This new backend surface must never fall back to tenant-only routes.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

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

_MAX_BULLETIN_ID_LENGTH = 256


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
    success response: ``errors`` is non-empty and ``config`` is absent. Every
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


def _validate_bulletin_id(bulletin_id: str) -> str:
    """Validate a path-bound bulletin ID.

    The ID is a backend-assigned opaque identifier, so this rejects anything
    that could reshape the route (empty, padded, control characters, or a path
    separator) rather than trying to canonicalize it.
    """
    if not isinstance(bulletin_id, str) or not bulletin_id:
        raise ValueError("bulletinId must be a non-empty string")
    if bulletin_id != bulletin_id.strip():
        raise ValueError("bulletinId must not have surrounding whitespace")
    if len(bulletin_id) > _MAX_BULLETIN_ID_LENGTH:
        raise ValueError(
            f"bulletinId must not exceed {_MAX_BULLETIN_ID_LENGTH} characters"
        )
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in bulletin_id
    ):
        raise ValueError("bulletinId must not contain control characters")
    if "/" in bulletin_id or "\\" in bulletin_id or "?" in bulletin_id:
        raise ValueError("bulletinId must not contain path or query separators")
    return bulletin_id


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
    """Async client for the tenant-and-agent-scoped ``essbulletins`` routes.

    Inherits auth, the token decode, the httpx session, and the retrying
    ``_request`` from ``AgentConfigBaseClient``; adds only the v1.1 base URL and
    the three authoring routes. Response bodies are already lower-camel on this
    surface, so no key transform is applied.
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
        encoded = _require_odata_id(_validate_title_id(title_id), "titleId")
        return f"tenants('{self.tenant_id}')/EmployeeAgents('{encoded}')/essbulletins"

    @staticmethod
    def _require_config(payload: Any, title_id: str) -> dict[str, Any]:
        """Reject a success-shaped response that is not a canonical record.

        A malformed body must not become an empty default, because the widget
        would then render a blank editor over real stored content.
        """
        if not isinstance(payload, dict) or not isinstance(
            payload.get("bulletin"), dict
        ):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid bulletin configuration"
            )
        if payload.get("titleId") != title_id:
            raise AgentConfigApiError(
                "Org Announcements API returned a configuration with missing "
                "or mismatched titleId"
            )
        if "titleId" in payload["bulletin"]:
            raise AgentConfigApiError(
                "Org Announcements API returned titleId inside bulletin content"
            )
        return payload

    @classmethod
    def _unwrap_collection(cls, payload: Any, title_id: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("value"), list):
            items = payload["value"]
        else:
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid collection response"
            )
        for item in items:
            cls._require_config(item, title_id)
        return items

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
                code = entry.get("code")
                field = entry.get("field")
                message = entry.get("message")
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
        cls, payload: Any, *, requested_id: Optional[str], title_id: str
    ) -> dict[str, Any]:
        """Validate and unwrap an ``EssBulletinSaveResult``.

        The save endpoint answers HTTP 200 with ``{id, config, errors}`` — a
        shape that list/load do *not* use, and that reports validation failure
        inside a success status. Three outcomes are distinguished:

        * ``errors`` non-empty → :class:`BulletinValidationError` carrying every
          entry, so field-level backend codes survive to the widget.
        * ``errors`` empty and ``config`` canonical → the canonical record,
          after checking the wrapper ``id`` agrees with the config's own ID and
          with the ID the caller asked to update.
        * anything else → :class:`AgentConfigApiError`, never an empty default:
          a blank record would render an empty editor over real stored content.

        ``requested_id`` is checked because an update that silently comes back
        keyed to a *different* record means the caller is about to replace its
        canonical state with someone else's announcement.
        """
        if not isinstance(payload, dict):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid save response"
            )

        errors = payload.get("errors")
        if errors is not None and not isinstance(errors, list):
            raise AgentConfigApiError(
                "Org Announcements API returned an invalid save error list"
            )
        if errors:
            raise BulletinValidationError(cls._normalize_save_errors(errors))

        config = cls._require_config(payload.get("config"), title_id)

        config_id = config["bulletin"].get("id")
        wrapper_id = payload.get("id")
        canonical_id = (
            wrapper_id
            if isinstance(wrapper_id, str) and wrapper_id
            else config_id if isinstance(config_id, str) and config_id else None
        )
        if canonical_id is None:
            # A saved record with no identity cannot be edited, transitioned, or
            # duplicated afterwards. Failing here is far better than handing the
            # widget a row whose every subsequent action would 404.
            raise AgentConfigApiError(
                "Org Announcements API returned a saved announcement without an id"
            )
        if (
            isinstance(wrapper_id, str)
            and wrapper_id
            and isinstance(config_id, str)
            and config_id
            and wrapper_id != config_id
        ):
            raise AgentConfigApiError(
                "Org Announcements API returned a save result whose id does not "
                "match the saved configuration"
            )
        if requested_id is not None and canonical_id != requested_id:
            raise AgentConfigApiError(
                "Org Announcements API returned a different announcement "
                "than the one that was updated"
            )
        return config

    async def list_bulletins(self, title_id: str) -> list[dict[str, Any]]:
        """List every current item plus the most recent archived window."""
        payload = await self._request(
            "GET", self._collection_path(title_id), transform_payload=False
        )
        return self._unwrap_collection(payload, title_id)

    async def get_bulletin(self, title_id: str, bulletin_id: str) -> dict[str, Any]:
        """Load one canonical stored configuration."""
        path = f"{self._collection_path(title_id)}/{_validate_bulletin_id(bulletin_id)}"
        return self._require_config(
            await self._request("GET", path, transform_payload=False), title_id
        )

    async def save_bulletin(
        self, title_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or update through the authoring ``save`` endpoint.

        Returns the canonical configuration unwrapped from the endpoint's
        ``EssBulletinSaveResult`` envelope. A payload without ``id`` is an
        unkeyed create; replaying one after an ambiguous failure could duplicate
        a committed record, so ambiguous retries are disabled and the failure is
        re-raised as :class:`IndeterminateWriteError` for the caller to surface.
        """
        requested_id = payload.get("id")
        is_create = not requested_id
        try:
            result = await self._request(
                "POST",
                f"{self._collection_path(title_id)}/save",
                json=payload,
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
        return self._unwrap_save_result(
            result,
            requested_id=requested_id if not is_create else None,
            title_id=title_id,
        )

    async def transition_bulletin(
        self, title_id: str, bulletin_id: str, status: str
    ) -> dict[str, Any]:
        """Apply a minimal lifecycle status change.

        WeveNova performs the transition inside ``SaveAsync``: it loads the
        canonical record server-side, preserves authored content and audience,
        validates the transition, and writes the new status. Sending only
        ``{id, status}`` therefore avoids a separate read/merge/write and cannot
        clobber content with stale client state.

        The response is the same ``EssBulletinSaveResult`` envelope the content
        save returns, so it is unwrapped identically — including the ID check
        that proves the transition landed on the requested record.
        """
        validated_id = _validate_bulletin_id(bulletin_id)
        return self._unwrap_save_result(
            await self._request(
                "POST",
                f"{self._collection_path(title_id)}/save",
                json={"id": validated_id, "status": status},
                transform_payload=False,
                idempotent=True,
            ),
            requested_id=validated_id,
            title_id=title_id,
        )


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
        bulletin_id = config["bulletin"].get("id", "")
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
