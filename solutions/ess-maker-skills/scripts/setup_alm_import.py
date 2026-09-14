# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Import a native DA package through the guarded foundation setup path."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agentbuilder import AgentBuilderClient, AgentBuilderError
from setup_existing_da import (
    CANONICAL_SETUP_STATE,
    ExistingDASetupError,
    _add_agentbuilder_target_arguments,
    _client_from_args,
    _normalize_environment_id,
    _normalize_guid,
    _utc_now,
    _write_json,
    attach_existing_dev,
    resolve_da_target,
    validate_existing_dev_connection,
)


IMPORT_RECEIPT = Path(".local/setup/da-alm-import.json")
MAX_MANIFEST_BYTES = 1024 * 1024


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
            agent_manifests: list[tuple[zipfile.ZipInfo, str]] = []
            for entry in files:
                parts = PurePosixPath(entry.filename).parts
                if (
                    len(parts) == 4
                    and parts[:2] == ("Plugin", "Agents")
                    and parts[3] == "agent.yml"
                    and parts[2]
                ):
                    agent_manifests.append((entry, parts[2]))
            if len(agent_manifests) != 1:
                raise AlmImportSetupError(
                    "The native agent package must contain exactly one agent."
                )
            schema_name = agent_manifests[0][1]
    except (OSError, zipfile.BadZipFile) as exc:
        raise AlmImportSetupError(
            "The native agent package is not a readable ZIP archive."
        ) from exc
    return AlmPackageInfo(
        sha256=_sha256(path),
        package_type=package_type.strip(),
        schema_name=schema_name,
    )


def _receipt_identity(
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


def _load_receipt(
    path: Path,
    expected_identity: dict[str, Any],
) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlmImportSetupError(
            "The native ALM import receipt is unreadable."
        ) from exc
    if not isinstance(receipt, dict) or (
        receipt.get("schemaVersion") != 1
        or receipt.get("input") != expected_identity
    ):
        raise AlmImportSetupError(
            "This workspace contains a receipt for a different native ALM "
            "import. Use a new workspace for another import."
        )
    if receipt.get("status") == "response-invalid":
        raise AlmImportSetupError(
            "The environment accepted the import request but returned an "
            "invalid result. The operation will not be retried automatically."
        )
    if receipt.get("status") != "imported":
        raise AlmImportSetupError(
            "The native ALM import receipt has an unsupported status."
        )
    result = receipt.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("cdsBotId"), str)
        or not isinstance(result.get("schemaName"), str)
    ):
        raise AlmImportSetupError(
            "The native ALM import receipt is incomplete."
        )
    return {
        "cdsBotId": result["cdsBotId"],
        "schemaName": result["schemaName"],
    }


def _validate_empty_import_workspace(kit_root: Path) -> None:
    conflicts = (
        CANONICAL_SETUP_STATE,
        Path(".local/config.json"),
    )
    if any((kit_root / path).exists() for path in conflicts):
        raise AlmImportSetupError(
            "This workspace already contains agent setup state. Use a new "
            "workspace before importing another agent."
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


def import_and_attach(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    package_path: Path,
    kit_root: Path,
    replacement_agent_id: str | None = None,
    confirmed_replacement_agent_id: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Import or resume one package, then materialize the returned Dev agent."""
    package = inspect_alm_package(package_path)
    normalized_environment_id = _normalize_environment_id(environment_id)
    resolved_kit_root = kit_root.resolve()
    receipt_path = resolved_kit_root / IMPORT_RECEIPT
    if not receipt_path.exists():
        _validate_empty_import_workspace(resolved_kit_root)
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
        replacement = validate_existing_dev_connection(
            client,
            environment_id=normalized_environment_id,
            agent_id=normalized_replacement_id,
            selection_source="explicit-replacement",
        )
    elif confirmed_replacement_agent_id:
        raise AlmImportSetupError(
            "Replacement confirmation was supplied without a target agent."
        )

    identity = _receipt_identity(
        client,
        environment_id=normalized_environment_id,
        package=package,
        replacement=replacement,
    )
    imported = _load_receipt(receipt_path, identity)
    resumed = imported is not None
    if imported is None:
        outcome = client.import_package(
            package_path.resolve(),
            replacement_schema_name=(
                replacement["agent"]["schemaName"]
                if replacement
                else None
            ),
        )
        imported, invalid_reason = _classify_import_outcome(outcome)
        if imported is None:
            _write_json(
                receipt_path,
                {
                    "schemaVersion": 1,
                    "status": "response-invalid",
                    "input": identity,
                    "responseClassification": invalid_reason,
                    "receivedAt": _utc_now(),
                },
            )
            raise AlmImportSetupError(
                "The environment accepted the import request but returned an "
                "invalid result. The operation will not be retried "
                "automatically."
            )
        _write_json(
            receipt_path,
            {
                "schemaVersion": 1,
                "status": "imported",
                "input": identity,
                "result": imported,
                "importedAt": _utc_now(),
            },
        )
    if replacement:
        _validate_replacement_result(imported, replacement)

    setup = attach_existing_dev(
        client,
        environment_id=normalized_environment_id,
        agent_id=imported["cdsBotId"],
        kit_root=resolved_kit_root,
        refresh=refresh,
        selection_source="alm-import-result",
        setup_source="alm-import",
    )
    return {
        **setup,
        "importStatus": "resumed" if resumed else "imported",
        "importMode": identity["mode"],
        "packageType": package.package_type,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_agentbuilder_target_arguments(parser)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--replace-agent-id")
    parser.add_argument("--confirm-replace-agent-id")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Checkpoint and replace a changed existing workspace.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
        result = import_and_attach(
            client,
            environment_id=target["environmentId"],
            package_path=args.package,
            kit_root=args.kit_root,
            replacement_agent_id=args.replace_agent_id,
            confirmed_replacement_agent_id=(
                args.confirm_replace_agent_id
            ),
            refresh=args.refresh,
        )
    except (
        AgentBuilderError,
        AlmImportSetupError,
        ExistingDASetupError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "DA_ALM_IMPORT_SETUP_JSON:"
        f"{json.dumps(result, ensure_ascii=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
