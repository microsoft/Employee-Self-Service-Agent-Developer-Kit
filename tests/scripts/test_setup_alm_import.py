# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

import agentbuilder
import setup_alm_import


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
TENANT_ID = "00000000-0000-4000-8000-000000009999"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)
SCHEMA = "gptagent_copilotforemployeeselfservicehr"


def _write_package(
    path: Path,
    *,
    package_type: str = "user",
    schema_name: str = SCHEMA,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Plugin/package.json",
            json.dumps(
                {
                    "formatVersion": "1.0",
                    "packageType": package_type,
                }
            ),
        )
        archive.writestr(
            f"Plugin/Agents/{schema_name}/agent.yml",
            "kind: DeclarativeAgent\n",
        )
    return path


class FakeClient:
    host = HOST
    ring = "test"
    api_version = "2024-10-01"
    tenant_id = TENANT_ID

    def __init__(
        self,
        *,
        result: dict[str, str] | None = None,
        error: Exception | None = None,
        outcome: dict[str, Any] | None = None,
    ) -> None:
        self.result = result or {
            "cdsBotId": AGENT_ID,
            "schemaName": SCHEMA,
        }
        self.error = error
        self.outcome = outcome
        self.import_calls: list[dict[str, Any]] = []

    def import_package(
        self,
        package_path: Path,
        *,
        replacement_schema_name: str | None = None,
    ) -> dict[str, Any]:
        self.import_calls.append(
            {
                "packagePath": package_path,
                "replacementSchemaName": replacement_schema_name,
            }
        )
        if self.error:
            raise self.error
        if self.outcome is not None:
            return self.outcome
        return {
            "responseStatus": "valid",
            "result": self.result,
        }


def _setup_result() -> dict[str, Any]:
    return {
        "status": "created",
        "connectionStatus": "workspace-ready",
        "setupStatus": "complete",
    }


def test_inspect_package_reads_only_required_metadata(
    tmp_path: Path,
) -> None:
    package = _write_package(
        tmp_path / "agent.zip",
        package_type="templated",
    )

    info = setup_alm_import.inspect_alm_package(package)

    assert info.package_type == "templated"
    assert info.schema_name == SCHEMA
    assert len(info.sha256) == 64
    assert not (tmp_path / "Plugin").exists()


@pytest.mark.parametrize(
    "entries, message",
    [
        (
            {"Plugin/Agents/example/agent.yml": "kind: DeclarativeAgent\n"},
            "Plugin/package.json",
        ),
        (
            {
                "Plugin/package.json": "{}",
                "Plugin/Agents/example/agent.yml": (
                    "kind: DeclarativeAgent\n"
                ),
            },
            "packageType",
        ),
        (
            {
                "Plugin/package.json": '{"packageType":"user"}',
                "../agent.yml": "kind: DeclarativeAgent\n",
            },
            "unsafe archive path",
        ),
    ],
)
def test_inspect_package_rejects_invalid_shape(
    tmp_path: Path,
    entries: dict[str, str],
    message: str,
) -> None:
    package = tmp_path / "agent.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)

    with pytest.raises(setup_alm_import.AlmImportSetupError, match=message):
        setup_alm_import.inspect_alm_package(package)


def test_create_receipts_before_attach_and_passes_closed_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    attach_calls: list[dict[str, Any]] = []

    def attach(
        _client: FakeClient,
        **kwargs: Any,
    ) -> dict[str, Any]:
        receipt_path = tmp_path / setup_alm_import.IMPORT_RECEIPT
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["status"] == "imported"
        attach_calls.append(kwargs)
        return _setup_result()

    monkeypatch.setattr(setup_alm_import, "attach_existing_dev", attach)

    result = setup_alm_import.import_and_attach(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )

    assert result["importStatus"] == "imported"
    assert result["importMode"] == "create"
    assert result["packageType"] == "user"
    assert client.import_calls[0]["replacementSchemaName"] is None
    assert attach_calls == [
        {
            "environment_id": ENVIRONMENT_ID,
            "agent_id": AGENT_ID,
            "kit_root": tmp_path,
            "refresh": False,
            "selection_source": "alm-import-result",
            "setup_source": "alm-import",
        }
    ]
    receipt = json.loads(
        (tmp_path / setup_alm_import.IMPORT_RECEIPT).read_text(
            encoding="utf-8"
        )
    )
    assert "packagePath" not in json.dumps(receipt)
    assert receipt["input"]["packageSha256"]
    assert receipt["input"]["mode"] == "create"


def test_same_receipt_resumes_without_second_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "attach_existing_dev",
        lambda *_args, **_kwargs: _setup_result(),
    )

    setup_alm_import.import_and_attach(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    result = setup_alm_import.import_and_attach(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )

    assert result["importStatus"] == "resumed"
    assert len(client.import_calls) == 1


def test_changed_package_cannot_reuse_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "attach_existing_dev",
        lambda *_args, **_kwargs: _setup_result(),
    )
    setup_alm_import.import_and_attach(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    _write_package(package, package_type="templated")

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="different native ALM import",
    ):
        setup_alm_import.import_and_attach(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )

    assert len(client.import_calls) == 1


def test_replacement_requires_matching_explicit_confirmation(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="requires explicit confirmation",
    ):
        setup_alm_import.import_and_attach(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            replacement_agent_id=AGENT_ID,
        )

    assert client.import_calls == []


def test_replacement_validates_dev_and_retained_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    validated: list[dict[str, Any]] = []

    def validate(
        _client: FakeClient,
        **kwargs: Any,
    ) -> dict[str, Any]:
        validated.append(kwargs)
        return {
            "agent": {
                "id": AGENT_ID,
                "schemaName": SCHEMA,
            }
        }

    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        validate,
    )
    monkeypatch.setattr(
        setup_alm_import,
        "attach_existing_dev",
        lambda *_args, **_kwargs: _setup_result(),
    )

    result = setup_alm_import.import_and_attach(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        replacement_agent_id=AGENT_ID.upper(),
        confirmed_replacement_agent_id=AGENT_ID,
    )

    assert result["importMode"] == "replace"
    assert validated[0]["agent_id"] == AGENT_ID
    assert client.import_calls[0]["replacementSchemaName"] == SCHEMA


def test_failed_import_writes_no_receipt_or_setup_state(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(error=agentbuilder.AgentBuilderError("failed"))

    with pytest.raises(agentbuilder.AgentBuilderError, match="failed"):
        setup_alm_import.import_and_attach(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )

    assert not (tmp_path / setup_alm_import.IMPORT_RECEIPT).exists()
    assert not (tmp_path / ".local" / "setup" / "config.json").exists()


def test_invalid_success_is_receipted_and_never_retried(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(
        outcome={
            "responseStatus": "invalid",
            "reason": "non-json-response",
        },
    )

    for _attempt in range(2):
        with pytest.raises(
            setup_alm_import.AlmImportSetupError,
            match="will not be retried automatically",
        ):
            setup_alm_import.import_and_attach(
                client,
                environment_id=ENVIRONMENT_ID,
                package_path=package,
                kit_root=tmp_path,
            )

    assert len(client.import_calls) == 1
    receipt = json.loads(
        (tmp_path / setup_alm_import.IMPORT_RECEIPT).read_text(
            encoding="utf-8"
        )
    )
    assert receipt["status"] == "response-invalid"
    assert "result" not in receipt


@pytest.mark.parametrize(
    "conflict",
    [
        Path(".local/setup/config.json"),
        Path(".local/setup/da-connection.json"),
        Path(".local/config.json"),
    ],
)
def test_existing_workspace_state_blocks_import_before_mutation(
    tmp_path: Path,
    conflict: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    path = tmp_path / conflict
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    client = FakeClient()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="already contains agent setup state",
    ):
        setup_alm_import.import_and_attach(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )

    assert client.import_calls == []


def test_replacement_identity_drift_is_receipted_before_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(
        result={
            "cdsBotId": "00000000-0000-4000-8000-000000007777",
            "schemaName": SCHEMA,
        }
    )
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: {
            "agent": {"id": AGENT_ID, "schemaName": SCHEMA}
        },
    )

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="different agent identity",
    ):
        setup_alm_import.import_and_attach(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            replacement_agent_id=AGENT_ID,
            confirmed_replacement_agent_id=AGENT_ID,
        )

    receipt = json.loads(
        (tmp_path / setup_alm_import.IMPORT_RECEIPT).read_text(
            encoding="utf-8"
        )
    )
    assert receipt["result"]["cdsBotId"] == client.result["cdsBotId"]
    assert not (tmp_path / ".local" / "setup" / "config.json").exists()
