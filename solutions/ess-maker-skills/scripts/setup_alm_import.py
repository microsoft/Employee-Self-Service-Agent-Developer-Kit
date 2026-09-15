# Copyright (c) Microsoft Corporation. Licensed under the MIT License.

"""Import one native DA package and return a verified editable Dev identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
)
from agentbuilder_object_model import (
    ObjectModelConverterError,
    validate_object_model_runtime,
)
from setup_existing_da import (
    CANONICAL_SETUP_STATE,
    DA_CONNECTION_STATE,
    ExistingDASetupError,
    _add_agentbuilder_target_arguments,
    _client_from_args,
    _normalize_environment_id,
    _normalize_guid,
    _utc_now,
    _write_json,
    resolve_da_target,
    validate_existing_dev_connection,
)


IMPORT_RECORDS = Path(".local/setup/alm-import")
MAX_MANIFEST_BYTES = 1024 * 1024
UNRESOLVED_STATUSES = frozenset(
    {"prepared", "ambiguous", "invalid-success", "imported"}
)
SAFE_RETRY_STATUSES = frozenset({"pre-dispatch-failure", "rejected"})


class AlmImportSetupError(RuntimeError):
    """Raised when native package import cannot preserve setup invariants."""


@dataclass(frozen=True)
class AlmPackageInfo:
    """Safe package metadata used to guard and resume an import."""

    sha256: str
    package_type: str
    schema_name: str


def _safe_archive_name(name: str) -> bool:
    if not name or "\\" in name:
        return False
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_alm_package(package_path: Path) -> AlmPackageInfo:
    """Inspect required package metadata without extracting package content."""
    path = package_path.resolve()
    if not path.is_file() or path.suffix.casefold() != ".zip":
        raise AlmImportSetupError(
            "The native agent package must be an existing .zip file."
        )
    try:
        with zipfile.ZipFile(path) as archive:
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if not all(_safe_archive_name(entry.filename) for entry in files):
                raise AlmImportSetupError(
                    "The native agent package contains an unsafe archive path."
                )
            package_entries = [
                entry
                for entry in files
                if entry.filename == "Plugin/package.json"
            ]
            if len(package_entries) != 1:
                raise AlmImportSetupError(
                    "The native agent package must contain one "
                    "Plugin/package.json manifest."
                )
            package_entry = package_entries[0]
            if package_entry.file_size > MAX_MANIFEST_BYTES:
                raise AlmImportSetupError(
                    "The native agent package manifest is unexpectedly large."
                )
            try:
                manifest = json.loads(
                    archive.read(package_entry).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AlmImportSetupError(
                    "The native agent package manifest is invalid."
                ) from exc
            package_type = (
                manifest.get("packageType")
                if isinstance(manifest, dict)
                else None
            )
            if not isinstance(package_type, str) or not package_type.strip():
                raise AlmImportSetupError(
                    "The native agent package does not declare packageType."
                )
            schemas = {
                parts[2]
                for entry in files
                if len(parts := PurePosixPath(entry.filename).parts) == 4
                and parts[:2] == ("Plugin", "Agents")
                and parts[3] == "agent.yml"
                and parts[2]
            }
            if len(schemas) != 1:
                raise AlmImportSetupError(
                    "The native agent package must contain exactly one agent."
                )
            schema_name = next(iter(schemas))
    except (OSError, zipfile.BadZipFile) as exc:
        raise AlmImportSetupError(
            "The native agent package is not a readable ZIP archive."
        ) from exc
    return AlmPackageInfo(
        sha256=_sha256(path),
        package_type=package_type.strip(),
        schema_name=schema_name,
    )


def _operation_identity(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    package: AlmPackageInfo,
    replacement: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "environmentId": _normalize_environment_id(environment_id),
        "tenantId": client.tenant_id,
        "host": client.host,
        "ring": client.ring,
        "apiVersion": client.api_version,
        "packageSha256": package.sha256,
        "packageType": package.package_type,
        "packageSchemaName": package.schema_name,
        "mode": "replace" if replacement else "create",
        "replacementAgentId": (
            replacement["agent"]["id"] if replacement else None
        ),
        "replacementSchemaName": (
            replacement["agent"]["schemaName"] if replacement else None
        ),
    }


def _record_path(kit_root: Path, identity: dict[str, Any]) -> Path:
    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    operation_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return kit_root / IMPORT_RECORDS / f"{operation_id}.json"


def _read_record(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlmImportSetupError(
            "The native ALM import record is unreadable."
        ) from exc
    if not isinstance(record, dict) or (
        record.get("schemaVersion") != 1
        or record.get("input") != identity
    ):
        raise AlmImportSetupError(
            "The native ALM import record does not match this operation."
        )
    return record


def _write_record(
    path: Path,
    identity: dict[str, Any],
    *,
    status: str,
    outcome: dict[str, Any] | None = None,
    result: dict[str, str] | None = None,
) -> None:
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "status": status,
        "input": identity,
        "updatedAt": _utc_now(),
    }
    if outcome is not None:
        record["outcome"] = outcome
    if result is not None:
        record["result"] = result
    _write_json(path, record)


def _load_other_records(
    directory: Path,
    current_path: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not directory.is_dir():
        return records
    for path in directory.glob("*.json"):
        if path == current_path:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AlmImportSetupError(
                "A native ALM import record is unreadable."
            ) from exc
        if not isinstance(record, dict) or record.get("schemaVersion") != 1:
            raise AlmImportSetupError(
                "A native ALM import record has an unsupported shape."
            )
        records.append(record)
    return records


def _guard_other_operations(
    directory: Path,
    current_path: Path,
    *,
    mode: str,
) -> None:
    for record in _load_other_records(directory, current_path):
        status = record.get("status")
        if status in UNRESOLVED_STATUSES:
            raise AlmImportSetupError(
                "Another native ALM import has an unresolved outcome. "
                "Reconcile it before starting a new mutation."
            )
        other_input = record.get("input")
        if (
            mode == "create"
            and status == "verified"
            and isinstance(other_input, dict)
            and other_input.get("mode") == "create"
        ):
            raise AlmImportSetupError(
                "This workspace already contains a successful create import. "
                "Attach that identity before starting another create."
            )


def _validate_empty_create_workspace(kit_root: Path) -> None:
    conflicts = (
        CANONICAL_SETUP_STATE,
        DA_CONNECTION_STATE,
        Path(".local/config.json"),
    )
    if any((kit_root / path).exists() for path in conflicts):
        raise AlmImportSetupError(
            "This workspace already contains agent setup state. Use the "
            "existing agent or an explicitly confirmed replacement."
        )


def _validate_local_replacement_target(
    kit_root: Path,
    *,
    environment_id: str,
    agent_id: str,
) -> None:
    path = kit_root / DA_CONNECTION_STATE
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        state_environment = state["environment"]["id"]
        state_agent = state["agent"]["id"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise AlmImportSetupError(
            "The existing DA connection state is unreadable."
        ) from exc
    if (
        str(state_environment).casefold() != environment_id.casefold()
        or str(state_agent).casefold() != agent_id.casefold()
    ):
        raise AlmImportSetupError(
            "This workspace is connected to a different editable Dev agent."
        )


def _validate_replacement_result(
    result: dict[str, str],
    replacement: dict[str, Any],
) -> None:
    expected_agent = replacement["agent"]
    if (
        result["cdsBotId"].casefold()
        != str(expected_agent["id"]).casefold()
        or result["schemaName"].casefold()
        != str(expected_agent["schemaName"]).casefold()
    ):
        raise AlmImportSetupError(
            "Native ALM replacement returned a different agent identity."
        )


def _classify_import_outcome(
    outcome: dict[str, Any],
) -> tuple[dict[str, str] | None, str]:
    if not isinstance(outcome, dict):
        return None, "invalid-response"
    if outcome.get("responseStatus") != "valid":
        reason = outcome.get("reason")
        return None, reason if isinstance(reason, str) else "invalid-response"
    result = outcome.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("cdsBotId"), str)
        or not isinstance(result.get("schemaName"), str)
    ):
        return None, "invalid-agent-identity"
    return {
        "cdsBotId": result["cdsBotId"],
        "schemaName": result["schemaName"],
    }, ""


def _pre_dispatch_reason(error: BaseException) -> str | None:
    if isinstance(error, requests.ConnectTimeout):
        return "connect-timeout"
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return "name-resolution"
        if type(current).__name__ == "NameResolutionError":
            return "name-resolution"
        current = current.__cause__ or current.__context__
    return None


def _failure_outcome(
    identity: dict[str, Any],
    *,
    kind: str,
    status_code: int | None = None,
    error_code: str | None = None,
    request_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "kind": kind,
        "importMode": identity["mode"],
        "packageType": identity["packageType"],
        "environmentId": identity["environmentId"],
    }
    if status_code is not None:
        outcome["statusCode"] = status_code
    if error_code:
        outcome["errorCode"] = error_code
    if request_id:
        outcome["requestId"] = request_id
    if reason:
        outcome["reason"] = reason
    return outcome


def _verified_outcome(
    identity: dict[str, Any],
    result: dict[str, str],
    connection: dict[str, Any],
    *,
    resumed: bool,
) -> dict[str, Any]:
    agent = connection["agent"]
    environment = connection["environment"]
    return {
        "kind": "success",
        "importStatus": "resumed" if resumed else "imported",
        "importMode": identity["mode"],
        "packageType": identity["packageType"],
        "environmentId": identity["environmentId"],
        "tenantId": environment["tenantId"],
        "host": environment["powerPlatformApiEndpoint"],
        "ring": environment["ring"],
        "apiVersion": environment["apiVersion"],
        "agentId": result["cdsBotId"],
        "schemaName": result["schemaName"],
        "agentName": agent["name"],
        "setupSource": "alm-import",
    }


def import_package_once(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    package_path: Path,
    kit_root: Path,
    replacement_agent_id: str | None = None,
    confirmed_replacement_agent_id: str | None = None,
    retry_safe_failure: bool = False,
) -> dict[str, Any]:
    """Run or resume one guarded import without materializing a workspace."""
    package = inspect_alm_package(package_path)
    normalized_environment_id = _normalize_environment_id(environment_id)
    resolved_kit_root = kit_root.resolve()
    replacement: dict[str, Any] | None = None
    if replacement_agent_id:
        normalized_replacement_id = _normalize_guid(
            replacement_agent_id,
            "Replacement agent ID",
        )
        if not confirmed_replacement_agent_id:
            raise AlmImportSetupError(
                "Replacing an editable agent requires explicit confirmation."
            )
        normalized_confirmation = _normalize_guid(
            confirmed_replacement_agent_id,
            "Confirmed replacement agent ID",
        )
        if normalized_confirmation != normalized_replacement_id:
            raise AlmImportSetupError(
                "Replacement confirmation does not match the target agent."
            )
        _validate_local_replacement_target(
            resolved_kit_root,
            environment_id=normalized_environment_id,
            agent_id=normalized_replacement_id,
        )
        replacement = validate_existing_dev_connection(
            client,
            environment_id=normalized_environment_id,
            agent_id=normalized_replacement_id,
            selection_source="explicit-replacement",
            setup_source="alm-import",
        )
    elif confirmed_replacement_agent_id:
        raise AlmImportSetupError(
            "Replacement confirmation was supplied without a target agent."
        )

    identity = _operation_identity(
        client,
        environment_id=normalized_environment_id,
        package=package,
        replacement=replacement,
    )
    record_path = _record_path(resolved_kit_root, identity)
    existing = (
        _read_record(record_path, identity)
        if record_path.exists()
        else None
    )
    imported: dict[str, str] | None = None
    resumed = False
    if existing is not None:
        status = existing.get("status")
        if status == "verified":
            outcome = existing.get("outcome")
            if not isinstance(outcome, dict):
                raise AlmImportSetupError(
                    "The verified native ALM import record is incomplete."
                )
            return {**outcome, "importStatus": "resumed"}
        if status == "imported":
            result = existing.get("result")
            if not isinstance(result, dict):
                raise AlmImportSetupError(
                    "The native ALM import record is incomplete."
                )
            imported, reason = _classify_import_outcome(
                {"responseStatus": "valid", "result": result}
            )
            if imported is None:
                raise AlmImportSetupError(
                    f"The native ALM import record is invalid: {reason}."
                )
            resumed = True
        elif status in SAFE_RETRY_STATUSES and retry_safe_failure:
            existing = None
        elif status in {"conflict", *SAFE_RETRY_STATUSES}:
            outcome = existing.get("outcome")
            if not isinstance(outcome, dict):
                raise AlmImportSetupError(
                    "The native ALM import failure record is incomplete."
                )
            return {**outcome, "importStatus": "cached"}
        else:
            raise AlmImportSetupError(
                "This native ALM import has an unresolved outcome and will "
                "not be retried automatically."
            )
    elif retry_safe_failure:
        raise AlmImportSetupError(
            "No safely retryable native ALM import record was found."
        )

    if imported is None:
        _guard_other_operations(
            record_path.parent,
            record_path,
            mode=identity["mode"],
        )
        if replacement is None:
            _validate_empty_create_workspace(resolved_kit_root)
        _write_record(record_path, identity, status="prepared")
        try:
            raw_outcome = client.import_package(
                package_path.resolve(),
                replacement_schema_name=(
                    replacement["agent"]["schemaName"]
                    if replacement
                    else None
                ),
            )
        except AgentBuilderHTTPError as exc:
            kind = "conflict" if exc.status_code == 409 else "rejected"
            outcome = _failure_outcome(
                identity,
                kind=kind,
                status_code=exc.status_code,
                error_code=exc.error_code,
                request_id=exc.request_id,
            )
            _write_record(
                record_path,
                identity,
                status=kind,
                outcome=outcome,
            )
            return outcome
        except requests.RequestException as exc:
            reason = _pre_dispatch_reason(exc)
            kind = "pre-dispatch-failure" if reason else "ambiguous"
            outcome = _failure_outcome(
                identity,
                kind=kind,
                reason=reason or "transport-ended-without-response",
            )
            _write_record(
                record_path,
                identity,
                status=kind,
                outcome=outcome,
            )
            return outcome
        except OSError:
            outcome = _failure_outcome(
                identity,
                kind="pre-dispatch-failure",
                reason="local-io",
            )
            _write_record(
                record_path,
                identity,
                status="pre-dispatch-failure",
                outcome=outcome,
            )
            return outcome
        except AgentBuilderError:
            outcome = _failure_outcome(
                identity,
                kind="ambiguous",
                reason="request-ended-without-classified-response",
            )
            _write_record(
                record_path,
                identity,
                status="ambiguous",
                outcome=outcome,
            )
            return outcome

        imported, invalid_reason = _classify_import_outcome(raw_outcome)
        if imported is None:
            outcome = _failure_outcome(
                identity,
                kind="invalid-success",
                reason=invalid_reason,
            )
            _write_record(
                record_path,
                identity,
                status="invalid-success",
                outcome=outcome,
            )
            return outcome
        _write_record(
            record_path,
            identity,
            status="imported",
            result=imported,
        )

    if replacement:
        _validate_replacement_result(imported, replacement)
    connection = validate_existing_dev_connection(
        client,
        environment_id=normalized_environment_id,
        agent_id=imported["cdsBotId"],
        selection_source="alm-import-result",
        setup_source="alm-import",
    )
    verified_schema = str(connection["agent"]["schemaName"])
    if verified_schema.casefold() != imported["schemaName"].casefold():
        raise AlmImportSetupError(
            "The imported agent schema does not match direct Dev validation."
        )
    outcome = _verified_outcome(
        identity,
        imported,
        connection,
        resumed=resumed,
    )
    _write_record(
        record_path,
        identity,
        status="verified",
        outcome=outcome,
        result=imported,
    )
    return outcome


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_agentbuilder_target_arguments(parser)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--replace-agent-id")
    parser.add_argument("--confirm-replace-agent-id")
    parser.add_argument(
        "--retry-safe-failure",
        action="store_true",
        help=(
            "Retry only a recorded pre-dispatch failure or normal rejection "
            "after its cause was resolved and the maker approved another try."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_object_model_runtime()
        target = resolve_da_target(
            target_url=args.target_url,
            environment_id=args.environment_id,
            agent_id=None,
            ring=args.ring,
            require_agent=False,
        )
        client = _client_from_args(
            args,
            target["environmentId"],
            target["ring"],
        )
        result = import_package_once(
            client,
            environment_id=target["environmentId"],
            package_path=args.package,
            kit_root=args.kit_root,
            replacement_agent_id=args.replace_agent_id,
            confirmed_replacement_agent_id=(
                args.confirm_replace_agent_id
            ),
            retry_safe_failure=args.retry_safe_failure,
        )
    except (
        AgentBuilderError,
        AlmImportSetupError,
        ExistingDASetupError,
        ObjectModelConverterError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"DA_ALM_IMPORT_JSON:{json.dumps(result, ensure_ascii=True)}")
    return 0 if result["kind"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
