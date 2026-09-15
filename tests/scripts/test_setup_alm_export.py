# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import setup_alm_export
from agentbuilder import DEV_REALM, PROD_REALM, AgentBuilderError


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
SOURCE_AGENT_ID = "00000000-0000-4000-8000-000000002222"
RELATED_DEV_AGENT_ID = "00000000-0000-4000-8000-000000003333"
TENANT_ID = "00000000-0000-4000-8000-000000009999"
FAMILY_ID = "00000000-0000-4000-8000-000000004444"
SOURCE_URL = (
    "https://copilotstudio.test.microsoft.com/environments/"
    f"{ENVIRONMENT_ID}/copilots/{SOURCE_AGENT_ID}/details"
)


class FakeClient:
    tenant_id = TENANT_ID
    ring = "test"
    api_version = "2024-10-01"
    host = (
        "https://0000000000004000800000000000111."
        "1.environment.api.test.powerplatform.com"
    )

    def __init__(self, *, route_realm: Any = PROD_REALM) -> None:
        self.route_realm = route_realm
        self.calls: list[str] = []
        self.exported_path: Path | None = None

    def get_realms(self, _agent_id: str) -> dict[str, Any]:
        self.calls.append("realms")
        return {
            "routeRealm": self.route_realm,
            "siblingRealms": [
                {
                    "realm": DEV_REALM,
                    "botId": RELATED_DEV_AGENT_ID,
                }
            ],
        }

    def get_realm_configuration(
        self,
        _agent_id: str,
        realm: int,
    ) -> dict[str, Any]:
        self.calls.append(f"configure:{realm}")
        return {
            "realm": "Prod",
            "cdsBotId": SOURCE_AGENT_ID,
            "grsRepositoryId": FAMILY_ID,
        }

    def export_package(self, _agent_id: str, path: Path) -> None:
        self.calls.append("export")
        self.exported_path = path
        path.write_bytes(b"PK\x03\x04package")


def _run(
    client: FakeClient,
    command: str,
    kit_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    monkeypatch.setattr(
        setup_alm_export,
        "_client_from_args",
        lambda *_args: client,
    )
    return setup_alm_export.main(
        [
            command,
            "--source-url",
            SOURCE_URL,
            "--kit-root",
            str(kit_root),
        ]
    )


def test_inspect_validates_prod_and_returns_related_dev_without_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient()

    result = _run(client, "inspect", tmp_path, monkeypatch)

    payload = json.loads(
        capsys.readouterr().out.split(
            "DA_ALM_EXPORT_INSPECTION_JSON:",
            1,
        )[1]
    )
    assert result == 0
    assert payload["sourceAgentId"] == SOURCE_AGENT_ID
    assert payload["almFamilyId"] == FAMILY_ID
    assert payload["relatedDevAgentId"] == RELATED_DEV_AGENT_ID
    assert client.calls == ["realms", f"configure:{PROD_REALM}"]


def test_inspect_rejects_non_prod_route_before_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient(route_realm=DEV_REALM)

    result = _run(client, "inspect", tmp_path, monkeypatch)

    assert result == 1
    assert client.calls == ["realms"]
    assert "not the native Prod realm" in capsys.readouterr().err


def test_inspect_requires_recognized_copilot_studio_agent_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_export,
        "_client_from_args",
        lambda *_args: client,
    )

    result = setup_alm_export.main(
        [
            "inspect",
            "--source-url",
            "https://example.invalid/environments/"
            f"{ENVIRONMENT_ID}/copilots/{SOURCE_AGENT_ID}/details",
            "--kit-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert client.calls == []
    assert "recognized Copilot Studio agent URL" in capsys.readouterr().err


def test_export_uses_os_temp_outside_kit_and_returns_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient()
    kit_root = tmp_path / "kit"
    kit_root.mkdir()
    os_temp = tmp_path / "os-temp"
    os_temp.mkdir()
    monkeypatch.setattr(setup_alm_export.tempfile, "tempdir", str(os_temp))

    result = _run(client, "export", kit_root, monkeypatch)

    payload = json.loads(
        capsys.readouterr().out.split("DA_ALM_EXPORT_JSON:", 1)[1]
    )
    package_path = Path(payload["packagePath"])
    record = json.loads(
        (kit_root / setup_alm_export.ACTIVE_EXPORT_RECORD).read_text(
            encoding="utf-8"
        )
    )

    assert result == 0
    assert package_path.parent == os_temp
    assert kit_root not in package_path.parents
    assert package_path.read_bytes() == b"PK\x03\x04package"
    assert payload["tenantId"] == TENANT_ID
    assert payload["host"] == client.host
    assert payload["ring"] == client.ring
    assert payload["apiVersion"] == client.api_version
    assert record == {
        "schemaVersion": 1,
        "packagePath": str(package_path),
    }

    setup_alm_export.cleanup_active_export(kit_root)


def test_export_failure_removes_partial_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient(FakeClient):
        def export_package(self, _agent_id: str, path: Path) -> None:
            self.exported_path = path
            path.write_bytes(b"partial")
            raise AgentBuilderError("export failed")

    client = FailingClient()
    kit_root = tmp_path / "kit"
    kit_root.mkdir()
    os_temp = tmp_path / "os-temp"
    os_temp.mkdir()
    monkeypatch.setattr(setup_alm_export.tempfile, "tempdir", str(os_temp))

    result = _run(client, "export", kit_root, monkeypatch)

    assert result == 1
    assert client.exported_path is not None
    assert not client.exported_path.exists()
    assert not (kit_root / setup_alm_export.ACTIVE_EXPORT_RECORD).exists()


def test_inspect_removes_stale_recorded_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    kit_root = tmp_path / "kit"
    kit_root.mkdir()
    os_temp = tmp_path / "os-temp"
    os_temp.mkdir()
    monkeypatch.setattr(setup_alm_export.tempfile, "tempdir", str(os_temp))

    assert _run(client, "export", kit_root, monkeypatch) == 0
    package_path = client.exported_path
    assert package_path is not None and package_path.exists()

    assert _run(client, "inspect", kit_root, monkeypatch) == 0

    assert not package_path.exists()
    assert not (kit_root / setup_alm_export.ACTIVE_EXPORT_RECORD).exists()


def test_cleanup_command_removes_active_export_and_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeClient()
    kit_root = tmp_path / "kit"
    kit_root.mkdir()
    os_temp = tmp_path / "os-temp"
    os_temp.mkdir()
    monkeypatch.setattr(setup_alm_export.tempfile, "tempdir", str(os_temp))

    assert _run(client, "export", kit_root, monkeypatch) == 0
    package_path = client.exported_path
    capsys.readouterr()

    result = setup_alm_export.main(
        ["cleanup", "--kit-root", str(kit_root)]
    )
    payload = json.loads(
        capsys.readouterr().out.split(
            "DA_ALM_EXPORT_CLEANUP_JSON:",
            1,
        )[1]
    )

    assert result == 0
    assert payload == {"status": "removed"}
    assert package_path is not None and not package_path.exists()
    assert not (kit_root / setup_alm_export.ACTIVE_EXPORT_RECORD).exists()
