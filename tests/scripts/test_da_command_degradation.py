# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA-GA commands fail before entering retired Dataverse implementations."""

from __future__ import annotations

import sys

import pytest

import auth
import plant_debug
import publish
import strip_debug


def _agentbuilder_config() -> dict:
    return {
        "transport": "agentbuilder",
        "agent": {
            "transport": "agentbuilder",
            "botId": "00000000-0000-4000-8000-000000000001",
        },
    }


def test_publish_reports_da_ga_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(publish, "load_config", _agentbuilder_config)
    monkeypatch.setattr(sys, "argv", ["publish.py", "--yes"])

    with pytest.raises(SystemExit, match="2"):
        publish.main()

    assert "not yet available" in capsys.readouterr().out


def test_plant_debug_reports_da_ga_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(auth, "load_config", _agentbuilder_config)

    result = plant_debug.main(
        [
            "--topic",
            "test-topic",
            "--after",
            "action",
            "--activity",
            "DBG value",
            "--yes",
        ]
    )

    assert result == 2
    assert "not yet available" in capsys.readouterr().out


def test_strip_debug_reports_da_ga_unavailable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provenance = tmp_path / "provenance.json"
    provenance.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(strip_debug, "PROVENANCE_PATH", provenance)
    monkeypatch.setattr(strip_debug, "load_provenance", object)
    monkeypatch.setattr(auth, "load_config", _agentbuilder_config)

    result = strip_debug.main(["--yes"])

    assert result == 2
    assert "not yet available" in capsys.readouterr().out
