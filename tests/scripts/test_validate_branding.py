# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for scripts/validate_branding.py."""

from __future__ import annotations

import json

import pytest

import validate_branding


def test_contrast_ratio_matches_vorpal_reference_values() -> None:
    assert validate_branding.contrast_ratio("#000000", "#FFFFFF") == 21
    assert validate_branding.contrast_ratio("#FFFFFF", "#FFFFFF") == 1


def test_main_validates_only_the_changed_theme(capsys) -> None:
    result = validate_branding.main(["--dark", "#FFFFFF"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passes"] is True
    assert [theme["theme"] for theme in payload["themes"]] == ["dark"]
    assert payload["themes"][0]["backgroundColor"] == "#242424"


def test_main_returns_advisory_failure_for_low_contrast(capsys) -> None:
    result = validate_branding.main(["--light", "#FFFFFF"])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passes"] is False
    assert payload["themes"][0]["ratio"] == 1
    assert payload["themes"][0]["required"] == 4.5


def test_main_rejects_invalid_hex(capsys) -> None:
    result = validate_branding.main(["--light", "#12345"])

    assert result == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["passes"] is False
    assert "six-digit hex" in payload["error"]


def test_main_requires_at_least_one_changed_theme() -> None:
    with pytest.raises(SystemExit) as error:
        validate_branding.main([])

    assert error.value.code == 2
