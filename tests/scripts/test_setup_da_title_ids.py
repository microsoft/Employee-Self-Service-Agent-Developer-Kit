# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA setup must preserve registration caches only for the same bot/environment."""

from __future__ import annotations

import copy
import json
from collections import Counter

import pytest

import setup_existing_da as setup


BOT_ID = "aaaaaaaa-0000-4000-8000-000000004444"
OTHER_BOT_ID = "bbbbbbbb-0000-4000-8000-000000005555"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)
PAIR = {"titleId": "regular-title", "lobTitleId": "lob-title"}


def _write(path, bot_id=BOT_ID, environment_id=ENVIRONMENT_ID):
    setup._write_config(
        path,
        agent_entry={
            "botId": bot_id, "slug": "selected", "name": "Selected",
            "environmentId": environment_id, "powerPlatformApiEndpoint": HOST,
        },
        environment_id=environment_id, host=HOST, ring="test",
        api_version="2024-10-01", component_counts=Counter(),
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("pair", [PAIR, {"titleId": None, "lobTitleId": "lob-title"}])
def test_setup_preserves_pair_and_selected_lob_with_normalized_guid(tmp_path, legacy, pair):
    previous = {
        "botId": "{" + BOT_ID.upper() + "}", "slug": "selected",
        "titleId": "lob-title", "registrationTitleIds": pair,
        "environmentId": ENVIRONMENT_ID, "powerPlatformApiEndpoint": HOST,
    }
    other = {"botId": OTHER_BOT_ID, "slug": "other", "custom": {"keep": [1]}}
    original = {
        "environmentId": ENVIRONMENT_ID, "powerPlatformApiEndpoint": HOST,
        "activeAgent": "selected", "agent": previous,
        "agents": [other] if legacy else [previous, other],
        "custom": {"keep": [2]},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    result = _write(path)
    matches = [item for item in result["agents"] if item["botId"] == BOT_ID]
    assert len(matches) == 1
    assert matches[0]["registrationTitleIds"] == pair
    assert matches[0]["titleId"] == "lob-title"
    assert result["agent"] == matches[0]
    assert result["activeAgent"] == "selected"
    assert result["custom"] == original["custom"]
    assert other in result["agents"]


@pytest.mark.parametrize("change", ["bot", "environment"])
def test_setup_does_not_transfer_registration_cache_to_a_different_identity(tmp_path, change):
    previous = {
        "botId": BOT_ID, "slug": "selected", "titleId": "lob-title",
        "registrationTitleIds": copy.deepcopy(PAIR),
        "environmentId": ENVIRONMENT_ID, "powerPlatformApiEndpoint": HOST,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": [previous], "agent": previous}), encoding="utf-8")
    result = _write(
        path, bot_id=OTHER_BOT_ID if change == "bot" else BOT_ID,
        environment_id=OTHER_BOT_ID if change == "environment" else ENVIRONMENT_ID,
    )
    assert "titleId" not in result["agent"]
    assert "registrationTitleIds" not in result["agent"]


def test_setup_rejects_duplicate_guid_matches_without_rewriting(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": [
        {"botId": BOT_ID, "slug": "one"},
        {"botId": BOT_ID.upper(), "slug": "two"},
    ]}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(setup.ExistingDASetupError, match="duplicate entries"):
        _write(path)
    assert path.read_bytes() == before
