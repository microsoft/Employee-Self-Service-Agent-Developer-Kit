# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for deterministic Workday DA user-context configuration."""

from __future__ import annotations

import pytest


BOT_ID = "11111111-2222-3333-4444-555555555555"
SETUP_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TARGET_ID = "99999999-8888-7777-6666-555555555555"
SETUP_SCHEMA = "gptagent_copilotforemployeeselfservicehr.topic.Setusercontext"
TARGET_SCHEMA = (
    "gptagent_copilotforemployeeselfservicehr.topic."
    "WorkdaySystemGetUserContextV2"
)


def _topics(*, setup_data: str = "", target_active: bool = True) -> list[dict]:
    return [
        {
            "botcomponentid": SETUP_ID,
            "name": "[Admin] - User Context - Setup",
            "schemaname": SETUP_SCHEMA,
            "data": setup_data,
            "statecode": 0,
        },
        {
            "botcomponentid": TARGET_ID,
            "name": "Workday [System] - 1: Set User Context V2",
            "schemaname": TARGET_SCHEMA,
            "data": "kind: AdaptiveDialog\n",
            "statecode": 0 if target_active else 1,
        },
    ]


def _bare_setup() -> str:
    return (
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRedirect\n"
        "  id: main\n"
        "  priority: 0\n"
    )


def _configured_setup(module) -> str:
    return module._redirect_yaml(TARGET_SCHEMA)


def test_preview_reports_safe_configuration_without_mutating() -> None:
    import configure_workday_da_user_context as module

    rows = _topics(setup_data=_bare_setup(), target_active=False)
    updates = []
    result = module.configure_workday_da_user_context(
        "https://org.crm.dynamics.com/",
        BOT_ID,
        apply=False,
        token_provider=lambda *args, **kwargs: "token",
        query=lambda *args, **kwargs: rows,
        updater=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert result["mode"] == "preview"
    assert result["action"] == "configure"
    assert result["redirectConfigured"] is False
    assert result["targetTopicActive"] is False
    assert updates == []


def test_apply_updates_and_verifies_the_exact_redirect() -> None:
    import configure_workday_da_user_context as module

    rows = _topics(setup_data=_bare_setup())

    def update(_url, _token, entity_set, record_id, data):
        assert entity_set == "botcomponents"
        assert record_id == SETUP_ID
        rows[0]["data"] = data["data"]
        return True

    result = module.configure_workday_da_user_context(
        "https://org.crm.dynamics.com",
        BOT_ID,
        apply=True,
        preferred_username="maker@example.com",
        token_provider=lambda *args, **kwargs: "token",
        query=lambda *args, **kwargs: rows,
        updater=update,
    )

    assert result["verified"] is True
    assert result["action"] == "configured"
    assert result["redirectConfigured"] is True
    assert f"dialog: {TARGET_SCHEMA}" in rows[0]["data"]


def test_apply_is_idempotent_when_redirect_is_already_correct() -> None:
    import configure_workday_da_user_context as module

    rows = _topics(setup_data=_configured_setup(module))
    updates = []
    result = module.configure_workday_da_user_context(
        "https://org.crm.dynamics.com",
        BOT_ID,
        apply=True,
        token_provider=lambda *args, **kwargs: "token",
        query=lambda *args, **kwargs: rows,
        updater=lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    assert result["verified"] is True
    assert result["action"] == "unchanged"
    assert updates == []


def test_custom_setup_content_is_never_overwritten() -> None:
    import configure_workday_da_user_context as module

    rows = _topics(
        setup_data=(
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: OnRedirect\n"
            "  actions:\n"
            "    - kind: SendActivity\n"
            "      activity: Keep me\n"
        )
    )
    with pytest.raises(
        module.WorkdayDAUserContextError,
        match="contains custom actions",
    ):
        module.configure_workday_da_user_context(
            "https://org.crm.dynamics.com",
            BOT_ID,
            apply=True,
            token_provider=lambda *args, **kwargs: "token",
            query=lambda *args, **kwargs: rows,
        )


def test_duplicate_target_topics_fail_closed() -> None:
    import configure_workday_da_user_context as module

    rows = _topics()
    rows.append({**rows[1], "botcomponentid": "duplicate"})
    with pytest.raises(
        module.WorkdayDAUserContextError,
        match="found 2",
    ):
        module.inspect_workday_da_user_context(
            "https://org.crm.dynamics.com",
            "token",
            BOT_ID,
            query=lambda *args, **kwargs: rows,
        )


def test_invalid_bot_id_fails_before_query() -> None:
    import configure_workday_da_user_context as module

    with pytest.raises(
        module.WorkdayDAUserContextError,
        match="invalid bot ID",
    ):
        module.inspect_workday_da_user_context(
            "https://org.crm.dynamics.com",
            "token",
            "not-a-guid",
            query=lambda *args, **kwargs: pytest.fail("query must not run"),
        )
