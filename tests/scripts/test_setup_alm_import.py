# Copyright (c) Microsoft Corporation. Licensed under the MIT License.

from __future__ import annotations

import json
import socket
import zipfile
from pathlib import Path
from typing import Any

import pytest
import requests

import agentbuilder
import agentbuilder_object_model
import setup_alm_import
import setup_existing_da


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
OTHER_ENVIRONMENT_ID = "00000000-0000-4000-8000-000000003333"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
OTHER_AGENT_ID = "00000000-0000-4000-8000-000000004444"
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


def _connection(
    *,
    environment_id: str = ENVIRONMENT_ID,
    agent_id: str = AGENT_ID,
    schema_name: str = SCHEMA,
) -> dict[str, Any]:
    return {
        "environment": {
            "id": environment_id,
            "tenantId": TENANT_ID,
            "powerPlatformApiEndpoint": HOST,
            "ring": "test",
            "apiVersion": "2024-10-01",
        },
        "agent": {
            "id": agent_id,
            "name": "Employee Self-Service HR",
            "schemaName": schema_name,
            "almFamilyId": "family-id",
        },
    }


def _write_setup_state(
    root: Path,
    *,
    environment_id: str = ENVIRONMENT_ID,
    agent_id: str = AGENT_ID,
) -> None:
    connection = _connection(
        environment_id=environment_id,
        agent_id=agent_id,
    )
    connection["setupSource"] = "existing-dev"
    connection["agent"].update(
        {
            "realm": "dev",
            "almFamilyId": "family-id",
            "workspaceSlug": "employee-self-service-hr",
        }
    )
    setup_existing_da._record_canonical_setup_progress(
        root,
        connection,
        None,
    )
    setup_existing_da._record_canonical_setup_ready(
        root,
        connection,
        {
            "folder": "workspace/agents/employee-self-service-hr",
            "agentPath": "agent.mcs.yml",
            "topicCount": 0,
            "variableCount": 0,
            "projectedComponentKinds": [],
            "unprojectedComponentKinds": {},
        },
    )


def _records(root: Path) -> list[Path]:
    return sorted((root / setup_alm_import.IMPORT_RECORDS).glob("*.json"))


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


def test_create_persists_verified_identity_without_attaching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    validations: list[dict[str, Any]] = []

    def validate(_client: FakeClient, **kwargs: Any) -> dict[str, Any]:
        validations.append(kwargs)
        return _connection()

    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        validate,
    )

    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        expected_alm_family_id="family-id",
    )

    assert result == {
        "kind": "success",
        "importStatus": "imported",
        "importMode": "create",
        "packageType": "user",
        "environmentId": ENVIRONMENT_ID,
        "tenantId": TENANT_ID,
        "host": HOST,
        "ring": "test",
        "apiVersion": "2024-10-01",
        "agentId": AGENT_ID,
        "schemaName": SCHEMA,
        "agentName": "Employee Self-Service HR",
        "almFamilyId": "family-id",
        "setupSource": "alm-import",
    }
    assert client.import_calls[0]["replacementSchemaName"] is None
    assert validations == [
        {
            "environment_id": ENVIRONMENT_ID,
            "agent_id": AGENT_ID,
            "selection_source": "alm-import-result",
            "setup_source": "alm-import",
        }
    ]
    assert not (tmp_path / setup_alm_import.CANONICAL_SETUP_STATE).exists()
    record = json.loads(_records(tmp_path)[0].read_text(encoding="utf-8"))
    assert record["status"] == "verified"
    assert record["input"]["expectedAlmFamilyId"] == "family-id"
    assert "packagePath" not in json.dumps(record)


def test_verified_operation_resumes_after_package_cleanup_without_second_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        expected_alm_family_id="family-id",
    )
    package.unlink()
    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        resume_create_after_cleanup=True,
        expected_alm_family_id="family-id",
    )

    assert result["kind"] == "success"
    assert result["importStatus"] == "resumed"
    assert result["agentId"] == AGENT_ID
    assert len(client.import_calls) == 1


def test_missing_package_does_not_resume_without_explicit_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        expected_alm_family_id="family-id",
    )
    package.unlink()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="existing .zip file",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            expected_alm_family_id="family-id",
        )

    assert len(client.import_calls) == 1


def test_verified_create_recovery_requires_matching_alm_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        expected_alm_family_id="family-id",
    )
    package.unlink()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="target and ALM family",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            resume_create_after_cleanup=True,
            expected_alm_family_id="different-family",
        )

    assert len(client.import_calls) == 1


def test_verified_create_recovery_rejects_existing_package(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="only after its disposable package was removed",
    ):
        setup_alm_import.import_package_once(
            FakeClient(),
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            resume_create_after_cleanup=True,
            expected_alm_family_id="family-id",
        )


def test_imported_identity_resumes_verification_without_second_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    calls = 0

    def validate(_client: FakeClient, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise agentbuilder.AgentBuilderError("read failed")
        return _connection()

    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        validate,
    )

    with pytest.raises(agentbuilder.AgentBuilderError, match="read failed"):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            expected_alm_family_id="family-id",
        )

    record = json.loads(_records(tmp_path)[0].read_text(encoding="utf-8"))
    assert record["status"] == "imported"
    package.unlink()

    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        resume_create_after_cleanup=True,
        expected_alm_family_id="family-id",
    )

    assert result["importStatus"] == "resumed"
    assert len(client.import_calls) == 1


def test_create_rejects_verified_agent_from_different_alm_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        expected_alm_family_id="different-family",
    )
    record = json.loads(_records(tmp_path)[0].read_text(encoding="utf-8"))

    assert result["kind"] == "invalid-success"
    assert result["reason"] == "alm-family-mismatch"
    assert record["status"] == "invalid-success"
    assert len(client.import_calls) == 1


def test_conflict_is_cached_and_replacement_is_a_distinct_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    conflict = agentbuilder.AgentBuilderHTTPError(
        "Native ALM import",
        409,
        error_code="DuplicateItemError",
        request_id="request-1",
    )
    client = FakeClient(error=conflict)
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    first = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    second = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )

    assert first["kind"] == "conflict"
    assert first["statusCode"] == 409
    assert first["requestId"] == "request-1"
    assert second["importStatus"] == "cached"
    assert len(client.import_calls) == 1

    client.error = None
    replaced = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        replacement_agent_id=AGENT_ID,
        confirmed_replacement_agent_id=AGENT_ID,
    )

    assert replaced["kind"] == "success"
    assert replaced["importMode"] == "replace"
    assert len(client.import_calls) == 2
    assert client.import_calls[1]["replacementSchemaName"] == SCHEMA
    assert len(_records(tmp_path)) == 2


def test_replacement_requires_matching_explicit_confirmation(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="requires explicit confirmation",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            replacement_agent_id=AGENT_ID,
        )

    assert client.import_calls == []


def test_replacement_allows_matching_managed_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    _write_setup_state(tmp_path)
    client = FakeClient()
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        replacement_agent_id=AGENT_ID,
        confirmed_replacement_agent_id=AGENT_ID,
    )

    assert result["kind"] == "success"
    assert result["importMode"] == "replace"


def test_replacement_rejects_different_managed_workspace(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    _write_setup_state(
        tmp_path,
        environment_id=OTHER_ENVIRONMENT_ID,
        agent_id=OTHER_AGENT_ID,
    )
    client = FakeClient()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="connected to a different",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            replacement_agent_id=AGENT_ID,
            confirmed_replacement_agent_id=AGENT_ID,
        )

    assert client.import_calls == []


def test_replacement_identity_drift_is_recorded_before_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(
        result={
            "cdsBotId": OTHER_AGENT_ID,
            "schemaName": SCHEMA,
        }
    )
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="different agent identity",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
            replacement_agent_id=AGENT_ID,
            confirmed_replacement_agent_id=AGENT_ID,
        )

    record = json.loads(_records(tmp_path)[0].read_text(encoding="utf-8"))
    assert record["status"] == "imported"
    assert record["result"]["cdsBotId"] == OTHER_AGENT_ID


def test_invalid_success_is_recorded_and_never_retried(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(
        outcome={
            "responseStatus": "invalid",
            "reason": "non-json-response",
        },
    )

    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    assert result["kind"] == "invalid-success"

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="unresolved outcome",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )

    assert len(client.import_calls) == 1


def test_dns_failure_is_pre_dispatch_and_cached(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    error = requests.ConnectionError("dns")
    error.__cause__ = socket.gaierror("not found")
    client = FakeClient(error=error)

    first = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    second = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )

    assert first["kind"] == "pre-dispatch-failure"
    assert first["reason"] == "name-resolution"
    assert second["importStatus"] == "cached"
    assert len(client.import_calls) == 1


def test_safe_failure_requires_explicit_retry_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(
        error=agentbuilder.AgentBuilderHTTPError(
            "Native ALM import",
            400,
            error_code="InvalidUserRequest",
        )
    )
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    rejected = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    cached = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )
    client.error = None
    retried = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
        retry_safe_failure=True,
    )

    assert rejected["kind"] == "rejected"
    assert cached["importStatus"] == "cached"
    assert retried["kind"] == "success"
    assert len(client.import_calls) == 2


def test_unclassified_transport_failure_is_ambiguous(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(error=requests.ReadTimeout("lost response"))

    result = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=package,
        kit_root=tmp_path,
    )

    assert result["kind"] == "ambiguous"
    assert result["errorType"] == "ReadTimeout"
    assert result["errorMessage"] == "lost response"
    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="unresolved outcome",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )
    assert len(client.import_calls) == 1


def test_record_failure_preserves_primary_operation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    client = FakeClient(error=requests.ReadTimeout("lost response"))
    original_write_record = setup_alm_import._write_record

    def fail_ambiguous_record(
        path: Path,
        identity: dict[str, Any],
        *,
        status: str,
        outcome: dict[str, Any] | None = None,
        result: dict[str, str] | None = None,
    ) -> None:
        if status == "ambiguous":
            raise OSError("record write denied")
        original_write_record(
            path,
            identity,
            status=status,
            outcome=outcome,
            result=result,
        )

    monkeypatch.setattr(
        setup_alm_import,
        "_write_record",
        fail_ambiguous_record,
    )

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="could not be persisted",
    ) as raised:
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )

    assert raised.value.__notes__ == [
        "Primary operation evidence: ReadTimeout: lost response"
    ]
    assert len(client.import_calls) == 1


def test_unrelated_record_does_not_lock_a_distinct_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_package = _write_package(tmp_path / "first.zip")
    second_package = _write_package(
        tmp_path / "second.zip",
        package_type="templated",
    )
    client = FakeClient(error=requests.ReadTimeout("lost response"))
    monkeypatch.setattr(
        setup_alm_import,
        "validate_existing_dev_connection",
        lambda *_args, **_kwargs: _connection(),
    )

    first = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=first_package,
        kit_root=tmp_path,
    )
    client.error = None
    second = setup_alm_import.import_package_once(
        client,
        environment_id=ENVIRONMENT_ID,
        package_path=second_package,
        kit_root=tmp_path,
    )

    assert first["kind"] == "ambiguous"
    assert second["kind"] == "success"
    assert len(client.import_calls) == 2


def test_existing_workspace_state_blocks_create_before_mutation(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    _write_setup_state(tmp_path)
    client = FakeClient()

    with pytest.raises(
        setup_alm_import.AlmImportSetupError,
        match="already contains agent setup state",
    ):
        setup_alm_import.import_package_once(
            client,
            environment_id=ENVIRONMENT_ID,
            package_path=package,
            kit_root=tmp_path,
        )

    assert client.import_calls == []


def test_main_preflights_projection_before_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _write_package(tmp_path / "agent.zip")
    authenticated = False

    def fail_preflight() -> None:
        raise agentbuilder_object_model.ObjectModelConverterError("missing")

    def authenticate(*_args: Any, **_kwargs: Any) -> FakeClient:
        nonlocal authenticated
        authenticated = True
        return FakeClient()

    monkeypatch.setattr(
        setup_alm_import,
        "validate_object_model_runtime",
        fail_preflight,
    )
    monkeypatch.setattr(setup_alm_import, "_client_from_args", authenticate)

    result = setup_alm_import.main(
        [
            "--target-url",
            "https://copilotstudio.test.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}",
            "--package",
            str(package),
            "--kit-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    assert authenticated is False
