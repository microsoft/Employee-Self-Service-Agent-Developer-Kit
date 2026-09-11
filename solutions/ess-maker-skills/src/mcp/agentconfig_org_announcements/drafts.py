# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed Org Announcements draft and payload models.

Two families live here:

``SuggestedBulletinDraft``
    The *input* contract for a pre-hydrated create. It mirrors Vorpal's
    ``suggestedBulletinDraftSchema`` exactly and is deliberately narrower than
    the canonical record: it cannot carry a bulletin ID, a persisted lifecycle
    status, creator/modifier identity, audit timestamps, or any backend version
    or storage field. A suggestion is unpublished client state, never an
    authorization to write.

``AnnouncementEditorDraft`` and the ``open_org_announcements`` payloads
    The *output* contract consumed by the widget. ``build_create_draft``
    overlays a validated suggestion onto the editor defaults so an omitted
    field keeps the exact value the empty editor would have shown.

Field mapping between the two families is intentional and one-directional:
suggested ``priority`` becomes ``standardPriority`` and suggested
``secondaryAction`` becomes ``standardSecondaryAction``, matching the widget's
Standard-only editor fields.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    ModelWrapValidatorHandler,
    PrivateAttr,
    model_validator,
)


AnnouncementType = Literal["standard", "alert"]
AnnouncementPriority = Literal[0, 1]
AnnouncementStatus = Literal["draft", "published", "retired", "deleted"]
EditorMode = Literal["create", "edit", "duplicate"]
BulletinActionType = Literal["externalLink", "copilotChat"]

# The values the empty Vorpal editor shows before a maker types anything. An
# omitted suggested field must land on exactly these, so they are named rather
# than repeated inline.
DEFAULT_TYPE: AnnouncementType = "standard"
DEFAULT_TITLE = ""
DEFAULT_DESCRIPTION = ""
DEFAULT_PRIMARY_ACTION = None
DEFAULT_START_DATE = ""
DEFAULT_END_DATE = ""
DEFAULT_STANDARD_PRIORITY: AnnouncementPriority = 1
DEFAULT_STANDARD_SECONDARY_ACTION = None

# ``EssBulletinInput.startDate``/``endDate`` are nullable ``DateTimeOffset``
# UTC instants. The widget's DatePicker exchanges instants as
# ``YYYY-MM-DDTHH:MM:SS.mmmZ``, so every accepted suggested value is normalized
# into exactly that shape before it reaches the editor draft.
_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"
_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _format_instant(moment: datetime) -> str:
    """Render an aware datetime as a UTC instant with millisecond precision."""
    utc = moment.astimezone(timezone.utc)
    # ``%f`` is microseconds; truncate (never round) so a normalized instant is
    # always at or before the value the maker supplied.
    return f"{utc.strftime(_INSTANT_FORMAT)[:-3]}Z"


def normalize_suggested_instant(value: str, *, boundary: str) -> str:
    """Normalize one suggested schedule boundary to a UTC millisecond instant.

    Three inputs are accepted, and nothing else:

    * ``""`` — an explicit "unset" that the DatePicker renders as empty. It is
      preserved rather than defaulted so the widget shows its own validation.
    * ``YYYY-MM-DD`` — a date-only value. A start becomes the first instant of
      that UTC day and an end becomes the last, so a single-day announcement
      spans the whole day instead of collapsing to midnight-to-midnight.
    * A timezone-aware ISO-8601 instant — converted to UTC.

    A timezone-naive datetime is rejected rather than assumed to be UTC: the
    maker's local day boundary is not knowable here, and silently guessing would
    schedule an announcement at the wrong time. Natural language ("next
    Monday") and any other unparseable text are rejected for the same reason —
    a suggestion the model invented must never become a schedule nobody
    reviewed.
    """
    if not isinstance(value, str):
        raise ValueError(f"{boundary} must be a string")
    text = value.strip()
    if not text:
        return ""

    if _DATE_ONLY_PATTERN.match(text):
        try:
            day = date.fromisoformat(text)
        except ValueError as error:
            raise ValueError(
                f"{boundary} must be a calendar date (YYYY-MM-DD) or a UTC instant"
            ) from error
        moment = (
            datetime(day.year, day.month, day.day, 0, 0, 0, 0, tzinfo=timezone.utc)
            if boundary == "startDate"
            else datetime(
                day.year, day.month, day.day, 23, 59, 59, 999000, tzinfo=timezone.utc
            )
        )
        return _format_instant(moment)

    candidate = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError(
            f"{boundary} must be an empty string, a calendar date "
            f"(YYYY-MM-DD), or a timezone-aware ISO-8601 instant"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"{boundary} must carry a timezone offset; a local datetime is "
            f"ambiguous and is not assumed to be UTC"
        )
    return _format_instant(parsed)


class StrictModel(BaseModel):
    """Reject any field the contract does not name."""

    model_config = ConfigDict(extra="forbid")


class BulletinAction(StrictModel):
    """A primary or secondary announcement action.

    ``url`` belongs to ``externalLink`` and ``prompt`` to ``copilotChat``. A
    payload carrying the *wrong* target for its type is malformed at the
    contract level, so it is rejected here rather than forwarded.

    A *missing or blank* target is deliberately still accepted. A Draft is
    allowed to be incomplete — the maker can add the URL later — and WeveNova
    owns publish-time completeness validation, so rejecting it here would make
    ``save_bulletin`` refuse drafts the backend accepts and would replace the
    backend's field-level error code with a generic contract error.
    """

    actionType: BulletinActionType
    label: str
    url: Optional[str] = None
    prompt: Optional[str] = None

    @model_validator(mode="after")
    def require_matching_target(self) -> "BulletinAction":
        if self.actionType == "externalLink":
            if self.prompt is not None:
                raise ValueError("externalLink actions must not carry a prompt")
        elif self.url is not None:
            raise ValueError("copilotChat actions must not carry a url")
        return self


class SuggestedBulletinAction(BulletinAction):
    """An action inside a *pre-hydrated* create suggestion.

    Stricter than :class:`BulletinAction` on purpose. A stored Draft may hold a
    half-finished action the maker is still editing, but a suggestion is
    content the model proposed and the maker has not typed: hydrating the
    editor with an ``externalLink`` that has no URL, or a ``copilotChat`` with
    no prompt, presents an action that cannot work as if it were reviewed
    state. The suggestion is rejected so the maker gets an explicit opener
    error instead of a silently broken button.
    """

    @model_validator(mode="after")
    def require_actionable_target(self) -> "SuggestedBulletinAction":
        if self.actionType == "externalLink":
            if not (self.url or "").strip():
                raise ValueError(
                    "a suggested externalLink action requires a non-blank url"
                )
        elif not (self.prompt or "").strip():
            raise ValueError(
                "a suggested copilotChat action requires a non-blank prompt"
            )
        return self


class SuggestedBulletinDraft(StrictModel):
    """A partial, reviewable proposal for a new announcement.

    Every field is optional; omitted fields fall back to the editor defaults in
    :func:`build_create_draft`. An explicit empty string is a real draft value
    and is preserved so the widget surfaces its normal validation instead of
    silently substituting a default.
    """

    type: Optional[AnnouncementType] = None
    priority: Optional[AnnouncementPriority] = None
    title: Optional[str] = None
    description: Optional[str] = None
    primaryAction: Optional[SuggestedBulletinAction] = None
    secondaryAction: Optional[SuggestedBulletinAction] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    audience: Optional[list[str]] = None

    _retry_input: dict[str, Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def preserve_retry_input(
        cls, value: Any, handler: ModelWrapValidatorHandler["SuggestedBulletinDraft"]
    ) -> "SuggestedBulletinDraft":
        # Keep the validated original proposal for retries; date normalization
        # belongs to editor hydration, not to the maker's original request.
        original = deepcopy(value) if isinstance(value, dict) else None
        draft = handler(value)
        if original is not None:
            draft._retry_input = original
        return draft

    def retry_payload(self) -> dict[str, Any]:
        return deepcopy(self._retry_input)

    @model_validator(mode="after")
    def normalize_schedule(self) -> "SuggestedBulletinDraft":
        """Coerce every accepted schedule value into a UTC millisecond instant.

        Normalizing here — rather than in ``build_create_draft`` — means the
        opener rejects an unusable suggestion before any Graph audience lookup
        is issued, and the editor only ever receives instants the DatePicker
        can render.
        """
        if self.startDate is not None:
            self.startDate = normalize_suggested_instant(
                self.startDate, boundary="startDate"
            )
        if self.endDate is not None:
            self.endDate = normalize_suggested_instant(
                self.endDate, boundary="endDate"
            )
        return self

    @model_validator(mode="after")
    def reject_alert_incompatible_fields(self) -> "SuggestedBulletinDraft":
        """An Alert has no priority control and no secondary action.

        Only an *explicit* incompatible value is rejected. Omitted Standard
        fields still receive their required editor defaults, because the widget
        keeps them in the draft even while they are hidden.
        """
        if self.type != "alert":
            return self
        if self.priority is not None:
            raise ValueError("alert announcements do not support priority")
        if self.secondaryAction is not None:
            raise ValueError(
                "alert announcements do not support a secondary action"
            )
        if (
            self.primaryAction is not None
            and self.primaryAction.actionType != "externalLink"
        ):
            raise ValueError("alert actions must be externalLink actions")
        return self

    @model_validator(mode="after")
    def reject_blank_audience_ids(self) -> "SuggestedBulletinDraft":
        if self.audience is None:
            return self
        for group_id in self.audience:
            if not group_id or not group_id.strip():
                raise ValueError("audience group IDs must be non-empty")
        return self


class OpenAnnouncementsRequest(StrictModel):
    """Validate flat opener arguments before they can become widget retry state."""

    titleId: str
    view: Literal["manager", "editor"]
    mode: Optional[Literal["create", "edit"]] = None
    bulletinId: Optional[str] = None
    suggestedDraft: Optional[SuggestedBulletinDraft] = None

    @model_validator(mode="after")
    def require_valid_editor_intent(self) -> "OpenAnnouncementsRequest":
        if self.view == "manager":
            if any(
                value is not None
                for value in (self.mode, self.bulletinId, self.suggestedDraft)
            ):
                raise ValueError("manager does not take editor arguments")
        elif self.mode is None:
            raise ValueError("editor requires explicit create or edit mode")
        elif self.mode == "create":
            if self.bulletinId is not None:
                raise ValueError("create must not supply bulletinId")
        elif self.bulletinId is None:
            raise ValueError("edit requires bulletinId")
        elif self.suggestedDraft is not None:
            raise ValueError("suggestedDraft applies only to create")
        return self


class AudienceGroup(StrictModel):
    """Display metadata for one canonical audience group ID.

    ``isValid`` is false when the ID could not be resolved through Graph or
    resolved to a group category this kit does not author. The ID is always
    retained so the widget can require removal or replacement instead of losing
    stored state.
    """

    id: str
    displayName: str
    mail: Optional[str] = None
    isValid: bool = True


class AnnouncementEditorDraft(StrictModel):
    """The complete editor draft the widget renders."""

    id: Optional[str] = None
    type: AnnouncementType
    title: str
    description: str
    primaryAction: Optional[BulletinAction] = None
    startDate: str
    endDate: str
    audience: list[AudienceGroup]
    standardPriority: AnnouncementPriority
    standardSecondaryAction: Optional[BulletinAction] = None


def build_create_draft(
    suggestion: Optional[SuggestedBulletinDraft],
    audience_metadata: Optional[list[AudienceGroup]] = None,
) -> AnnouncementEditorDraft:
    """Overlay a validated suggestion onto the empty-editor defaults.

    ``audience_metadata`` is the resolved, order-preserving metadata for
    ``suggestion.audience``; the caller resolves it because resolution needs the
    Graph client. A create draft never carries an ID.
    """
    if suggestion is None:
        suggestion = SuggestedBulletinDraft()

    return AnnouncementEditorDraft(
        type=suggestion.type if suggestion.type is not None else DEFAULT_TYPE,
        title=suggestion.title if suggestion.title is not None else DEFAULT_TITLE,
        description=(
            suggestion.description
            if suggestion.description is not None
            else DEFAULT_DESCRIPTION
        ),
        primaryAction=(
            suggestion.primaryAction
            if suggestion.primaryAction is not None
            else DEFAULT_PRIMARY_ACTION
        ),
        startDate=(
            suggestion.startDate
            if suggestion.startDate is not None
            else DEFAULT_START_DATE
        ),
        endDate=(
            suggestion.endDate
            if suggestion.endDate is not None
            else DEFAULT_END_DATE
        ),
        audience=list(audience_metadata or []),
        standardPriority=(
            suggestion.priority
            if suggestion.priority is not None
            else DEFAULT_STANDARD_PRIORITY
        ),
        standardSecondaryAction=(
            suggestion.secondaryAction
            if suggestion.secondaryAction is not None
            else DEFAULT_STANDARD_SECONDARY_ACTION
        ),
    )


def build_editor_draft_from_config(
    config: dict[str, Any],
    audience_metadata: list[AudienceGroup],
) -> AnnouncementEditorDraft:
    """Project canonical content into the normal editor, preserving its schedule."""
    bulletin = config.get("bulletin")
    if not isinstance(bulletin, dict):
        raise ValueError("bulletin configuration is missing its bulletin content")

    bulletin_id = bulletin.get("id")
    if not isinstance(bulletin_id, str) or not bulletin_id:
        raise ValueError("bulletin configuration is missing its id")

    primary_action = bulletin.get("primaryAction")
    secondary_action = bulletin.get("secondaryAction")
    priority = bulletin.get("priority")

    return AnnouncementEditorDraft(
        id=bulletin_id,
        type=bulletin.get("type") or DEFAULT_TYPE,
        title=bulletin.get("title") or DEFAULT_TITLE,
        description=bulletin.get("description") or DEFAULT_DESCRIPTION,
        primaryAction=(
            BulletinAction.model_validate(primary_action)
            if isinstance(primary_action, dict)
            else DEFAULT_PRIMARY_ACTION
        ),
        startDate=bulletin.get("startDate") or DEFAULT_START_DATE,
        endDate=bulletin.get("endDate") or DEFAULT_END_DATE,
        audience=list(audience_metadata),
        standardPriority=(
            priority if priority in (0, 1) else DEFAULT_STANDARD_PRIORITY
        ),
        standardSecondaryAction=(
            BulletinAction.model_validate(secondary_action)
            if isinstance(secondary_action, dict)
            else DEFAULT_STANDARD_SECONDARY_ACTION
        ),
    )


_SCHEDULE_FIELDS = ("startDate", "endDate")


def is_blank_schedule_value(value: Any) -> bool:
    """Report whether a schedule value is the widget's "unset" sentinel.

    The single definition of the rule, shared by the validated save path and the
    duplicate path, so the two cannot drift into disagreeing about what "unset"
    means.
    """
    return isinstance(value, str) and not value.strip()


def without_blank_schedule(bulletin: dict[str, Any]) -> dict[str, Any]:
    """Drop schedule keys holding a blank sentinel from a raw content dict.

    Used by the duplicate path, which forwards *stored* content verbatim and so
    never passes through :class:`BulletinInput`. Without this, duplicating a
    source whose schedule is blank would put ``""`` on the wire and fail the
    backend's model binding, even though the equivalent ordinary save is fine.
    """
    return {
        key: value
        for key, value in bulletin.items()
        if not (key in _SCHEDULE_FIELDS and is_blank_schedule_value(value))
    }


class BulletinInput(StrictModel):
    """The authored content a mutation sends to the authoring API.

    ``startDate``/``endDate`` map to nullable ``DateTimeOffset`` on
    ``EssBulletinInput``. The widget's DatePicker represents "unset" as the
    empty string, so a blank arriving here is coerced to ``None`` and then
    dropped entirely by ``exclude_none=True`` at serialization. Sending ``""``
    instead would fail the backend's *model binding* — a JSON string is not a
    DateTimeOffset — which surfaces as an opaque 400 rather than as the
    field-level validation error the widget knows how to render, and would make
    a perfectly ordinary unscheduled Draft unsaveable.
    """

    type: AnnouncementType
    priority: Optional[AnnouncementPriority] = None
    title: str
    description: str
    primaryAction: Optional[BulletinAction] = None
    secondaryAction: Optional[BulletinAction] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None

    @model_validator(mode="after")
    def blank_schedule_means_unset(self) -> "BulletinInput":
        """Treat a blank or whitespace-only boundary as absent, not as a value.

        Only blanks are touched. A real instant is passed through byte-for-byte:
        the backend owns the canonical schedule, and silently rewriting an
        instant here could shift a schedule the maker already reviewed.
        """
        if self.startDate is not None and is_blank_schedule_value(self.startDate):
            self.startDate = None
        if self.endDate is not None and is_blank_schedule_value(self.endDate):
            self.endDate = None
        return self


class SaveBulletinRequest(StrictModel):
    """A complete create-or-update of authored content and audience.

    ``id`` present means update, ``id`` absent means create. The widget always
    sends the whole authored state, so this model never merges with server
    state. Agent identity belongs to the route, never to this HTTP body.
    """

    id: Optional[str] = None
    bulletin: BulletinInput
    audience: list[str]
    status: Literal["draft", "published"]

    @model_validator(mode="after")
    def reject_blank_identifiers(self) -> "SaveBulletinRequest":
        if self.id is not None and not self.id.strip():
            raise ValueError("id must be a non-empty string when provided")
        for group_id in self.audience:
            if not group_id or not group_id.strip():
                raise ValueError("audience group IDs must be non-empty")
        return self
