# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the typed suggested-draft schema and editor-draft projection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


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

drafts = _ORG_MODULES["drafts"]


EMPTY_EDITOR_DRAFT = {
    "id": None,
    "type": "standard",
    "title": "",
    "description": "",
    "primaryAction": None,
    "startDate": "",
    "endDate": "",
    "audience": [],
    "standardPriority": 1,
    "standardSecondaryAction": None,
}


# --------------------------------------------------------------------------
# Canonical metadata can never enter a suggestion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        {"id": "bulletin-1"},
        {"bulletinId": "bulletin-1"},
        {"status": "published"},
        {"createdBy": "admin@contoso.com"},
        {"createdOn": "2026-08-01T12:00:00.000Z"},
        {"modifiedDate": "2026-09-02T12:00:00.000Z"},
        {"modifiedBy": "admin@contoso.com"},
        {"archivedOn": "2026-09-02T12:00:00.000Z"},
        {"version": 3},
        {"etag": 'W/"3"'},
        {"titleId": "title-1"},
        {"standardPriority": 0},
        {"standardSecondaryAction": None},
    ],
)
def test_suggested_drafts_reject_canonical_and_unknown_fields(forbidden) -> None:
    with pytest.raises(ValidationError):
        drafts.SuggestedBulletinDraft.model_validate({"title": "Hi", **forbidden})


def test_a_suggested_draft_accepts_only_the_agreed_contract_fields() -> None:
    assert set(drafts.SuggestedBulletinDraft.model_fields) == {
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


# --------------------------------------------------------------------------
# Defaults and field mapping
# --------------------------------------------------------------------------


def test_no_suggestion_produces_the_empty_editor_defaults() -> None:
    assert drafts.build_create_draft(None).model_dump(mode="json") == EMPTY_EDITOR_DRAFT


def test_every_omitted_field_keeps_its_editor_default() -> None:
    suggestion = drafts.SuggestedBulletinDraft(title="Only a title")

    result = drafts.build_create_draft(suggestion).model_dump(mode="json")

    assert result == {**EMPTY_EDITOR_DRAFT, "title": "Only a title"}


def test_priority_maps_to_standard_priority() -> None:
    suggestion = drafts.SuggestedBulletinDraft(priority=0)

    assert drafts.build_create_draft(suggestion).standardPriority == 0


def test_secondary_action_maps_to_standard_secondary_action() -> None:
    suggestion = drafts.SuggestedBulletinDraft(
        secondaryAction={
            "actionType": "copilotChat",
            "label": "Ask",
            "prompt": "Tell me more",
        }
    )

    result = drafts.build_create_draft(suggestion)

    assert result.standardSecondaryAction is not None
    assert result.standardSecondaryAction.label == "Ask"
    assert "secondaryAction" not in result.model_dump(mode="json")


def test_explicit_empty_strings_stay_explicit_draft_values() -> None:
    suggestion = drafts.SuggestedBulletinDraft(
        title="", description="", startDate="", endDate=""
    )

    result = drafts.build_create_draft(suggestion).model_dump(mode="json")

    assert result["title"] == ""
    assert result["description"] == ""
    assert result["startDate"] == ""
    assert result["endDate"] == ""


def test_a_create_draft_never_carries_an_identifier() -> None:
    suggestion = drafts.SuggestedBulletinDraft(title="New")

    assert drafts.build_create_draft(suggestion).id is None


def test_resolved_audience_metadata_is_attached_in_order() -> None:
    metadata = [
        drafts.AudienceGroup(id="g2", displayName="Two"),
        drafts.AudienceGroup(id="g1", displayName="One"),
    ]

    result = drafts.build_create_draft(
        drafts.SuggestedBulletinDraft(audience=["g2", "g1"]), metadata
    )

    assert [group.id for group in result.audience] == ["g2", "g1"]


# --------------------------------------------------------------------------
# Alert compatibility
# --------------------------------------------------------------------------


def test_alert_with_explicit_priority_is_rejected() -> None:
    with pytest.raises(ValidationError):
        drafts.SuggestedBulletinDraft.model_validate(
            {"type": "alert", "priority": 0}
        )


def test_alert_with_explicit_secondary_action_is_rejected() -> None:
    with pytest.raises(ValidationError):
        drafts.SuggestedBulletinDraft.model_validate(
            {
                "type": "alert",
                "secondaryAction": {
                    "actionType": "externalLink",
                    "label": "More",
                    "url": "https://contoso.com",
                },
            }
        )


def test_alert_with_a_copilot_chat_action_is_rejected() -> None:
    with pytest.raises(ValidationError):
        drafts.SuggestedBulletinDraft.model_validate(
            {
                "type": "alert",
                "primaryAction": {
                    "actionType": "copilotChat",
                    "label": "Ask",
                    "prompt": "Explain",
                },
            }
        )


def test_alert_still_receives_the_hidden_standard_defaults() -> None:
    suggestion = drafts.SuggestedBulletinDraft(type="alert", title="Outage")

    result = drafts.build_create_draft(suggestion)

    assert result.type == "alert"
    assert result.standardPriority == drafts.DEFAULT_STANDARD_PRIORITY
    assert result.standardSecondaryAction is None


# --------------------------------------------------------------------------
# Action payloads
# --------------------------------------------------------------------------


def test_external_link_actions_must_not_carry_a_prompt() -> None:
    with pytest.raises(ValidationError):
        drafts.BulletinAction.model_validate(
            {
                "actionType": "externalLink",
                "label": "Go",
                "url": "https://contoso.com",
                "prompt": "Explain",
            }
        )


def test_copilot_chat_actions_must_not_carry_a_url() -> None:
    with pytest.raises(ValidationError):
        drafts.BulletinAction.model_validate(
            {
                "actionType": "copilotChat",
                "label": "Ask",
                "prompt": "Explain",
                "url": "https://contoso.com",
            }
        )


def test_blank_audience_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        drafts.SuggestedBulletinDraft.model_validate({"audience": ["g1", "  "]})


# --------------------------------------------------------------------------
# Canonical config projection
# --------------------------------------------------------------------------


def _config(**overrides) -> dict:
    bulletin = {
        "id": "bulletin-1",
        "type": "standard",
        "priority": 0,
        "title": "Quarterly update",
        "description": "Read this",
        "startDate": "2026-09-01T00:00:00.000Z",
        "endDate": "2026-10-01T23:59:59.999Z",
        "primaryAction": {
            "actionType": "externalLink",
            "label": "Read",
            "url": "https://contoso.com",
        },
        "secondaryAction": {
            "actionType": "copilotChat",
            "label": "Ask",
            "prompt": "Summarize",
        },
    }
    bulletin.update(overrides)
    return {
        "bulletin": bulletin,
        "audience": ["g1"],
        "status": "published",
        "createdBy": "admin@contoso.com",
        "createdOn": "2026-08-01T12:00:00.000Z",
        "modifiedDate": "2026-09-02T12:00:00.000Z",
    }


def test_edit_projection_preserves_canonical_content_and_identity() -> None:
    metadata = [drafts.AudienceGroup(id="g1", displayName="One")]

    result = drafts.build_editor_draft_from_config(_config(), metadata)

    assert result.id == "bulletin-1"
    assert result.startDate == "2026-09-01T00:00:00.000Z"
    assert result.endDate == "2026-10-01T23:59:59.999Z"
    assert result.standardPriority == 0
    assert result.standardSecondaryAction is not None
    assert result.standardSecondaryAction.actionType == "copilotChat"


def test_missing_stored_schedule_uses_empty_strings_not_null() -> None:
    metadata = [drafts.AudienceGroup(id="g1", displayName="One")]

    result = drafts.build_editor_draft_from_config(
        _config(startDate=None, endDate=None), metadata
    )

    assert result.startDate == ""
    assert result.endDate == ""
    assert result.id == "bulletin-1"
    assert result.title == "Quarterly update"


def test_missing_optional_content_falls_back_to_editor_defaults() -> None:
    config = {
        "bulletin": {"id": "bulletin-1", "type": "standard", "title": "Only title"},
        "audience": [],
        "status": "draft",
    }

    result = drafts.build_editor_draft_from_config(config, [])

    assert result.description == ""
    assert result.primaryAction is None
    assert result.standardPriority == drafts.DEFAULT_STANDARD_PRIORITY
    assert result.standardSecondaryAction is None
    assert result.audience == []


@pytest.mark.parametrize(
    "config",
    [
        {"audience": [], "status": "draft"},
        {"bulletin": "not-an-object"},
        {"bulletin": {"type": "standard"}},
        {"bulletin": {"id": "", "type": "standard"}},
    ],
)
def test_malformed_configurations_are_rejected(config) -> None:
    with pytest.raises(ValueError):
        drafts.build_editor_draft_from_config(config, [])


# --------------------------------------------------------------------------
# Save request contract
# --------------------------------------------------------------------------


def test_save_requests_accept_an_absent_id_as_a_create() -> None:
    request = drafts.SaveBulletinRequest.model_validate(
        {
            "bulletin": {"type": "standard", "title": "t", "description": "d"},
            "audience": ["g1"],
            "status": "draft",
        }
    )

    assert request.id is None
    assert "id" not in request.model_dump(mode="json", exclude_none=True)


@pytest.mark.parametrize("field", ["titleId", "tenantId"])
@pytest.mark.parametrize("nested", [False, True])
def test_http_save_body_and_authored_content_reject_scope(field, nested) -> None:
    body = {
        "bulletin": {"type": "standard", "title": "t", "description": "d"},
        "audience": ["g1"],
        "status": "draft",
    }
    target = body["bulletin"] if nested else body
    target[field] = "not-authored-content"
    with pytest.raises(ValidationError, match=field):
        drafts.SaveBulletinRequest.model_validate(body)


def test_retry_input_preserves_original_values_without_exposing_private_fields() -> None:
    original = {"startDate": "2026-09-12", "title": "Review me"}
    suggestion = drafts.SuggestedBulletinDraft.model_validate(original)
    assert suggestion.startDate == "2026-09-12T00:00:00.000Z"
    assert suggestion.retry_payload() == original
    assert "_retry_input" not in suggestion.model_dump()
    assert "_retry_input" not in drafts.SuggestedBulletinDraft.model_json_schema()["properties"]
    retry = suggestion.retry_payload()
    retry["title"] = "changed"
    assert suggestion.retry_payload() == original


def test_save_requests_reject_blank_identity_and_audience_values() -> None:
    with pytest.raises(ValidationError):
        drafts.SaveBulletinRequest.model_validate(
            {
                "id": "   ",
                "bulletin": {"type": "standard", "title": "t", "description": "d"},
                "audience": [],
                "status": "draft",
            }
        )
    with pytest.raises(ValidationError):
        drafts.SaveBulletinRequest.model_validate(
            {
                "bulletin": {"type": "standard", "title": "t", "description": "d"},
                "audience": [""],
                "status": "draft",
            }
        )


def test_save_requests_reject_a_non_authoring_status() -> None:
    for status in ("retired", "deleted", "archived"):
        with pytest.raises(ValidationError):
            drafts.SaveBulletinRequest.model_validate(
                {
                    "bulletin": {"type": "standard", "title": "t", "description": "d"},
                    "audience": ["g1"],
                    "status": status,
                }
            )


def test_save_requests_reject_audit_fields_on_the_content() -> None:
    with pytest.raises(ValidationError):
        drafts.SaveBulletinRequest.model_validate(
            {
                "bulletin": {
                    "type": "standard",
                    "title": "t",
                    "description": "d",
                    "modifiedDate": "2026-09-02T12:00:00.000Z",
                },
                "audience": ["g1"],
                "status": "draft",
            }
        )


# --------------------------------------------------------------------------
# Suggested schedule normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Explicit "unset" is preserved so the DatePicker shows its own state.
        ("", ""),
        ("   ", ""),
        # Date-only start anchors to the first instant of the UTC day.
        ("2026-09-01", "2026-09-01T00:00:00.000Z"),
        ("2026-12-31", "2026-12-31T00:00:00.000Z"),
        # Aware instants normalize to UTC milliseconds.
        ("2026-09-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z"),
        ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00.000Z"),
        ("2026-09-01T00:00:00z", "2026-09-01T00:00:00.000Z"),
        ("2026-09-01T08:30:00+02:00", "2026-09-01T06:30:00.000Z"),
        ("2026-09-01T00:00:00-05:00", "2026-09-01T05:00:00.000Z"),
        ("2026-09-01T12:34:56.789Z", "2026-09-01T12:34:56.789Z"),
        # Sub-millisecond precision truncates rather than rounding up, so the
        # normalized instant is never later than what the maker supplied.
        ("2026-09-01T12:34:56.789999Z", "2026-09-01T12:34:56.789Z"),
    ],
)
def test_suggested_start_dates_normalize_to_utc_instants(raw, expected) -> None:
    result = drafts.build_create_draft(
        drafts.SuggestedBulletinDraft(startDate=raw)
    )

    assert result.startDate == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        # A date-only END covers the whole day, so a single-day announcement
        # does not collapse to a zero-length midnight-to-midnight window.
        ("2026-09-01", "2026-09-01T23:59:59.999Z"),
        ("2026-12-31", "2026-12-31T23:59:59.999Z"),
        ("2026-10-01T23:59:59.999Z", "2026-10-01T23:59:59.999Z"),
        ("2026-09-01T08:30:00+02:00", "2026-09-01T06:30:00.000Z"),
    ],
)
def test_suggested_end_dates_normalize_to_utc_instants(raw, expected) -> None:
    result = drafts.build_create_draft(drafts.SuggestedBulletinDraft(endDate=raw))

    assert result.endDate == expected


@pytest.mark.parametrize(
    "raw",
    [
        # Natural language the model might invent.
        "next Monday",
        "tomorrow",
        "in two weeks",
        "Sept 1 2026",
        "09/01/2026",
        # Timezone-naive: the maker's local day boundary is not knowable here,
        # and guessing UTC would schedule the announcement at the wrong time.
        "2026-09-01T00:00:00",
        "2026-09-01T08:30:00.000",
        "2026-09-01 08:30:00",
        # Structurally invalid.
        "2026-13-01",
        "2026-02-30",
        "2026-09-01T25:00:00Z",
        "not-a-date",
        "Z",
    ],
)
@pytest.mark.parametrize("field", ["startDate", "endDate"])
def test_unparseable_or_naive_schedule_values_are_rejected(raw, field) -> None:
    with pytest.raises(ValidationError):
        drafts.SuggestedBulletinDraft(**{field: raw})


def test_both_schedule_boundaries_normalize_independently() -> None:
    result = drafts.build_create_draft(
        drafts.SuggestedBulletinDraft(
            startDate="2026-09-01", endDate="2026-09-01"
        )
    )

    assert result.startDate == "2026-09-01T00:00:00.000Z"
    assert result.endDate == "2026-09-01T23:59:59.999Z"


def test_normalization_is_idempotent() -> None:
    """A normalized instant fed back in must not drift."""
    once = drafts.normalize_suggested_instant("2026-09-01", boundary="endDate")
    twice = drafts.normalize_suggested_instant(once, boundary="endDate")

    assert once == twice == "2026-09-01T23:59:59.999Z"


def test_an_omitted_schedule_keeps_the_editor_default() -> None:
    result = drafts.build_create_draft(drafts.SuggestedBulletinDraft())

    assert result.startDate == drafts.DEFAULT_START_DATE
    assert result.endDate == drafts.DEFAULT_END_DATE


def test_stored_schedules_are_not_re_normalized() -> None:
    """A canonical stored instant is passed through untouched.

    Normalization is an *input* guard on model-authored suggestions. The backend
    already owns the canonical instant, so rewriting it here could silently
    change a stored schedule.
    """
    config = {
        "bulletin": {
            "id": "b1",
            "type": "standard",
            "title": "t",
            "description": "d",
            "startDate": "2026-09-01T00:00:00.0000000+00:00",
            "endDate": "2026-10-01T23:59:59.999Z",
        },
        "audience": [],
        "status": "published",
    }

    result = drafts.build_editor_draft_from_config(config, [])

    assert result.startDate == "2026-09-01T00:00:00.0000000+00:00"
    assert result.endDate == "2026-10-01T23:59:59.999Z"


# --------------------------------------------------------------------------
# Suggested action targets
# --------------------------------------------------------------------------


def test_a_suggested_external_link_requires_a_non_blank_url() -> None:
    """A suggestion is unreviewed model output, not a half-typed draft."""
    for url in (None, "", "   "):
        with pytest.raises(ValidationError):
            drafts.SuggestedBulletinDraft(
                primaryAction={
                    "actionType": "externalLink",
                    "label": "Open",
                    **({} if url is None else {"url": url}),
                }
            )


def test_a_suggested_copilot_chat_requires_a_non_blank_prompt() -> None:
    for prompt in (None, "", "   "):
        with pytest.raises(ValidationError):
            drafts.SuggestedBulletinDraft(
                secondaryAction={
                    "actionType": "copilotChat",
                    "label": "Ask",
                    **({} if prompt is None else {"prompt": prompt}),
                }
            )


def test_complete_suggested_actions_are_accepted() -> None:
    result = drafts.build_create_draft(
        drafts.SuggestedBulletinDraft(
            primaryAction={
                "actionType": "externalLink",
                "label": "Open",
                "url": "https://contoso.example/benefits",
            },
            secondaryAction={
                "actionType": "copilotChat",
                "label": "Ask",
                "prompt": "Explain the benefits change",
            },
        )
    )

    assert result.primaryAction.url == "https://contoso.example/benefits"
    assert result.standardSecondaryAction.prompt == "Explain the benefits change"


@pytest.mark.parametrize(
    "action",
    [
        {"actionType": "externalLink", "label": "Open"},
        {"actionType": "externalLink", "label": "Open", "url": ""},
        {"actionType": "copilotChat", "label": "Ask"},
        {"actionType": "copilotChat", "label": "Ask", "prompt": "   "},
    ],
)
def test_ordinary_saves_still_accept_incomplete_draft_actions(action) -> None:
    """A Draft may be unfinished; WeveNova owns publish-time completeness.

    Rejecting these here would make ``save_bulletin`` refuse drafts the backend
    accepts and would replace the backend's field-level code with a generic
    contract error the widget cannot bind to an input.
    """
    request = drafts.SaveBulletinRequest.model_validate(
        {
            "bulletin": {
                "type": "standard",
                "title": "",
                "description": "",
                "primaryAction": action,
            },
            "audience": [],
            "status": "draft",
        }
    )

    assert request.bulletin.primaryAction.actionType == action["actionType"]


def test_a_stored_incomplete_action_still_projects_into_the_editor() -> None:
    """Opening an existing unfinished Draft must not fail validation."""
    config = {
        "bulletin": {
            "id": "b1",
            "type": "standard",
            "title": "t",
            "description": "d",
            "primaryAction": {"actionType": "externalLink", "label": "Open"},
        },
        "audience": [],
        "status": "draft",
    }

    result = drafts.build_editor_draft_from_config(config, [])

    assert result.primaryAction.actionType == "externalLink"
    assert result.primaryAction.url is None


def test_mismatched_action_targets_are_still_rejected_everywhere() -> None:
    """Wrong-target actions are malformed at the contract level, not merely
    incomplete, so both the strict and the permissive model reject them."""
    with pytest.raises(ValidationError):
        drafts.SaveBulletinRequest.model_validate(
            {
                "bulletin": {
                    "type": "standard",
                    "title": "t",
                    "description": "d",
                    "primaryAction": {
                        "actionType": "externalLink",
                        "label": "Open",
                        "prompt": "nope",
                    },
                },
                "audience": [],
                "status": "draft",
            }
        )


# --------------------------------------------------------------------------
# Blank date sentinel on the save path
# --------------------------------------------------------------------------


def _save_request(**bulletin_overrides) -> drafts.SaveBulletinRequest:
    bulletin = {
        "type": "standard",
        "title": "Quarterly update",
        "description": "Read this",
        **bulletin_overrides,
    }
    return drafts.SaveBulletinRequest.model_validate(
        {"bulletin": bulletin, "audience": [], "status": "draft"}
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", " \t\n "])
def test_a_blank_schedule_boundary_becomes_unset(blank) -> None:
    """The widget's DatePicker writes ``""`` for unset.

    ``EssBulletinInput.startDate``/``endDate`` are nullable ``DateTimeOffset``,
    so an empty string fails the backend's *model binding* rather than its
    validation — an opaque 400 instead of a renderable field error.
    """
    request = _save_request(startDate=blank, endDate=blank)

    assert request.bulletin.startDate is None
    assert request.bulletin.endDate is None


def test_a_draft_with_both_dates_blank_serializes_without_them() -> None:
    """This is the exact payload ``save_bulletin`` sends to the API."""
    request = _save_request(startDate="", endDate="")

    payload = request.model_dump(mode="json", exclude_none=True)

    assert "startDate" not in payload["bulletin"]
    assert "endDate" not in payload["bulletin"]


def test_no_empty_string_reaches_the_save_json() -> None:
    """Checked against the serialized JSON, not just the model.

    A model-level assertion would still pass if serialization reintroduced the
    sentinel, and the wire format is what the backend binds.
    """
    request = _save_request(startDate="   ", endDate="")

    encoded = json.dumps(request.model_dump(mode="json", exclude_none=True))
    bulletin = json.loads(encoded)["bulletin"]

    assert "startDate" not in bulletin
    assert "endDate" not in bulletin
    assert '""' not in encoded


def test_omitted_dates_and_blank_dates_produce_the_same_payload() -> None:
    """"Cleared in the editor" and "never set" must be indistinguishable."""
    blank = _save_request(startDate="", endDate="").model_dump(
        mode="json", exclude_none=True
    )
    omitted = _save_request().model_dump(mode="json", exclude_none=True)

    assert blank == omitted


def test_valid_instants_survive_the_blank_coercion_untouched() -> None:
    """The backend owns the canonical schedule; never rewrite a real instant."""
    request = _save_request(
        startDate="2026-09-01T00:00:00.000Z",
        endDate="2026-10-01T23:59:59.999Z",
    )

    payload = request.model_dump(mode="json", exclude_none=True)

    assert payload["bulletin"]["startDate"] == "2026-09-01T00:00:00.000Z"
    assert payload["bulletin"]["endDate"] == "2026-10-01T23:59:59.999Z"


@pytest.mark.parametrize(
    "instant",
    [
        "2026-09-01T08:30:00+02:00",
        "2026-09-01T00:00:00Z",
        "2026-09-01T00:00:00.0000000+00:00",
    ],
)
def test_aware_instants_are_passed_through_byte_for_byte(instant) -> None:
    request = _save_request(startDate=instant)

    assert request.bulletin.startDate == instant


def test_only_one_blank_boundary_is_coerced_independently() -> None:
    """An open-ended schedule (start set, no end) is legitimate."""
    request = _save_request(startDate="2026-09-01T00:00:00.000Z", endDate="")

    payload = request.model_dump(mode="json", exclude_none=True)

    assert payload["bulletin"]["startDate"] == "2026-09-01T00:00:00.000Z"
    assert "endDate" not in payload["bulletin"]


def test_a_published_save_with_blank_dates_still_reaches_the_backend() -> None:
    """Missing dates on publish stay a *backend* validation concern.

    The contract layer must not pre-empt it: WeveNova owns publish-time
    completeness and returns a structured, field-bound code the widget can
    render. Rejecting here would replace that with a generic contract error, and
    sending ``""`` would turn it into a JSON binding failure instead.
    """
    request = drafts.SaveBulletinRequest.model_validate(
        {
            "bulletin": {
                "type": "standard",
                "title": "Quarterly update",
                "description": "Read this",
                "startDate": "",
                "endDate": "",
            },
            "audience": ["group-a"],
            "status": "published",
        }
    )

    payload = request.model_dump(mode="json", exclude_none=True)

    assert payload["status"] == "published"
    assert "startDate" not in payload["bulletin"]
    assert "endDate" not in payload["bulletin"]


def test_the_editor_draft_keeps_the_empty_string_representation() -> None:
    """Coercion is a *save-path* concern only.

    The editor draft is what the DatePicker renders, and it treats ``""`` — not
    ``null`` — as unset, so the two directions must not be conflated.
    """
    draft = drafts.build_create_draft(drafts.SuggestedBulletinDraft(startDate=""))

    assert draft.startDate == ""
    assert draft.endDate == ""


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_without_blank_schedule_drops_only_blank_schedule_keys(blank) -> None:
    """The duplicate path's coercion, which bypasses BulletinInput entirely."""
    cleaned = drafts.without_blank_schedule(
        {
            "type": "standard",
            "title": "Keep me",
            "description": blank,
            "startDate": blank,
            "endDate": "2026-10-01T23:59:59.999Z",
        }
    )

    assert "startDate" not in cleaned
    assert cleaned["endDate"] == "2026-10-01T23:59:59.999Z"
    # Only the two schedule keys are in scope; a blank description is real
    # authored state the backend validates.
    assert cleaned["description"] == blank
    assert cleaned["title"] == "Keep me"


def test_without_blank_schedule_leaves_non_string_values_alone() -> None:
    """A null from the backend is already 'unset' and must round-trip."""
    cleaned = drafts.without_blank_schedule({"startDate": None, "endDate": None})

    assert cleaned == {"startDate": None, "endDate": None}


def test_the_two_blank_schedule_paths_agree() -> None:
    """One rule, two call sites; they must not drift."""
    for value in ("", "   ", "\t\n", "2026-09-01T00:00:00.000Z", None):
        via_helper = "startDate" not in drafts.without_blank_schedule(
            {"startDate": value}
        )
        via_model = drafts.is_blank_schedule_value(value)
        assert via_helper == via_model, value
