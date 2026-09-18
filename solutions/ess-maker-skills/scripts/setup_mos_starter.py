# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""List MOS starters, create a fresh Dev agent, and enable ALM when requested.

This is the DA `/setup` fresh-install path for a maker with no existing
agent. It exposes three independently observable operations: read-only
``list``, guarded ``create``, and replacement-safe ``enable-alm``. It has no
``resolve``/``status`` command and no persona/ISV/product policy, which belongs
to the maker and
``src/skills/foundation-setup/da-mos-starter.md``, not this script.

``src/reference/mos-starter-package.md`` is the canonical narrative: the
service-evidence table, every safety invariant, the fuse disposition
matrix, the response-evidence contract, and open validation gaps all live there,
not here.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import socket
from pathlib import Path
from typing import Any

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
)
from setup_existing_da import (
    CANONICAL_SETUP_STATE,
    ExistingDASetupError,
    _add_agentbuilder_target_arguments,
    _client_from_args,
    _normalize_guid,
    _normalize_environment_id,
    _print_exception,
    _utc_now,
    resolve_da_target,
)


FUSE_PATH = Path(".local/setup/mos-starter/create-attempted")
_CREATE_MARKER = "DA_MOS_STARTER_CREATE"
_LIST_MARKER = "DA_MOS_STARTER_LIST"
_ALM_MARKER = "DA_MOS_STARTER_ALM"
_ALM_VERIFY_MARKER = "DA_MOS_STARTER_ALM_VERIFY"
# The fuse-disposition matrix for every status bucket lives in
# src/reference/mos-starter-package.md; only these definitive rejections
# clear the fuse (the create never happened), everything else keeps it.
DEFINITIVE_REJECTION_STATUSES = frozenset({400, 401, 403, 404, 409, 412, 422})
_SAFE_PACKAGE_FIELDS = (
    "packageId",
    "name",
    "shortDescription",
    "description",
    "developerName",
    "version",
    "manifestVersion",
)
class MosStarterSetupError(RuntimeError):
    """Raised when MOS-starter listing or create cannot preserve invariants."""


# --- list (read-only) -------------------------------------------------
def summarize_starter_packages(
    packages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return safe catalog fields for entries with a non-empty packageId.

    A row with a missing or blank ``packageId`` is excluded here -- it can
    never be a selectable, passable identity -- but it is not silently
    discarded overall: ``catalog_warnings`` reports it separately so the
    caller can tell the maker the listing was incomplete.
    """
    valid = [
        package
        for package in packages
        if isinstance(package, dict)
        and isinstance(package.get("packageId"), str)
        and package["packageId"].strip()
    ]
    return sorted(
        (
            {field: package.get(field) for field in _SAFE_PACKAGE_FIELDS}
            for package in valid
        ),
        key=lambda item: (
            str(item.get("name") or "").casefold(),
            str(item["packageId"]),
        ),
    )


def catalog_warnings(packages: list[Any]) -> list[dict[str, Any]]:
    """Report each catalog row excluded from ``summarize_starter_packages``.

    Each warning carries only its row index, an exclusion reason, and the
    same safe-field projection already used for a valid row (when the row
    is at least an object) -- never unknown or raw fields from a malformed
    row.
    """
    warnings: list[dict[str, Any]] = []
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            warnings.append({"index": index, "reason": "not-an-object"})
            continue
        package_id = package.get("packageId")
        if isinstance(package_id, str) and package_id.strip():
            continue
        warnings.append(
            {
                "index": index,
                "reason": "missing-package-id",
                "package": {
                    field: package.get(field) for field in _SAFE_PACKAGE_FIELDS
                },
            }
        )
    return warnings


def list_starter_packages(
    client: AgentBuilderClient,
    *,
    environment_id: str,
) -> dict[str, Any]:
    """List the catalog, never silently discarding a malformed row.

    Selectable packages and a separate ``catalogWarnings`` collection for
    every excluded row are both returned. A failed listing prints the same
    light-annotation and response-evidence contract ``create`` uses, then
    re-raises so the CLI still fails without anything being discarded.
    """
    try:
        packages = client.list_starter_packages()
    except AgentBuilderHTTPError as exc:
        annotations: dict[str, Any] = {
            "targetEnvironmentId": environment_id,
            "outcome": "service-rejected",
            "httpStatus": exc.status_code,
            "requestId": exc.request_id,
        }
        if exc.response is None:
            _emit_annotations(annotations, marker=_LIST_MARKER)
        else:
            body, body_is_json = _parse_response_body(exc.response)
            _print_evidence(annotations, body, body_is_json, marker=_LIST_MARKER)
        raise
    except (requests.exceptions.RequestException, OSError) as exc:
        _emit_annotations(
            {
                "targetEnvironmentId": environment_id,
                "outcome": "transport-failure",
                "transportErrorType": type(exc).__name__,
                "transportError": str(exc),
            },
            marker=_LIST_MARKER,
        )
        raise
    except AgentBuilderError as exc:
        _emit_annotations(
            {
                "targetEnvironmentId": environment_id,
                "outcome": "invalid-response",
                "errorType": type(exc).__name__,
                "error": str(exc),
            },
            marker=_LIST_MARKER,
        )
        raise
    return {
        "environmentId": environment_id,
        "packages": summarize_starter_packages(packages),
        "catalogWarnings": catalog_warnings(packages),
    }


# --- create ---------------------------------------------------------------
def _validate_empty_create_workspace(kit_root: Path) -> None:
    conflicts = (
        CANONICAL_SETUP_STATE,
        Path(".local/config.json"),
    )
    if any((kit_root / path).exists() for path in conflicts):
        raise MosStarterSetupError(
            "This Developer Kit folder already contains agent setup state. "
            "To install a fresh MOS product, open a separate copy of the "
            "Developer Kit in a new VS Code window."
        )


def _fuse_content(context: dict[str, Any]) -> str:
    """Render plain-text fuse content -- an audit note, never parsed back."""
    return (
        f"startedAt: {_utc_now()}\n"
        f"environmentId: {context['targetEnvironmentId']}\n"
        f"packageId: {context['packageId']}\n"
        f"packageName: {context['packageName'] or ''}\n"
        f"catalogPackageVersion: {context['catalogPackageVersion'] or ''}\n"
    )


def _create_fuse(path: Path, content: str) -> None:
    """Create the single attempt fuse atomically, refusing a second create.

    ``O_CREAT | O_EXCL`` makes existence-check-and-create one atomic
    operation, not a check-then-write race, and the write is fsynced
    before this returns so the fuse is durable before the POST is sent. If
    the write, flush, or fsync itself fails, the partial fuse (already
    closed by the ``with`` block) is removed best-effort before the
    original failure is re-raised, so a half-written fuse never blocks
    every later create attempt.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MosStarterSetupError(
            "A MOS starter create was already attempted for this "
            f"workspace ({path.as_posix()}). Inspect this session's "
            "persistent transcript for the prior response, then "
            "reconcile by read-only inspecting the target environment "
            "(the existing `list` and `setup_existing_da.py validate-agent` "
            "commands). This command will not start a second create."
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            exc.add_note(
                "The partial attempt fuse could not be removed: "
                f"{cleanup_error}"
            )
        raise


def _pre_dispatch_reason(error: BaseException) -> str | None:
    """Return a reason only when transport proves nothing was ever sent.

    A connect timeout, DNS failure, or refused connection all happen
    before any bytes reach the service. A generic timeout, reset, or
    other connection error is ambiguous, so it stays uncertain (``None``).
    """
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return "connect-timeout"
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (socket.gaierror, ConnectionRefusedError)):
            return (
                "name-resolution"
                if isinstance(current, socket.gaierror)
                else "connection-refused"
            )
        if type(current).__name__ == "NameResolutionError":
            return "name-resolution"
        current = current.__cause__ or current.__context__
    return None


def _extract_request_id(response: requests.Response) -> str | None:
    for name in (
        "x-ms-service-request-id",
        "x-ms-request-id",
        "request-id",
        "x-ms-correlation-id",
        "x-correlation-id",
    ):
        value = response.headers.get(name)
        if value:
            return value
    return None


def _parse_response_body(response: requests.Response) -> tuple[Any, bool]:
    try:
        return response.json(), True
    except ValueError:
        return response.text, False


def _extract_identity(body: Any) -> dict[str, str] | None:
    """Extract a usable botId and source-package identity when present.

    This only checks that both fields are non-empty strings. The existing
    attach command remains the authoritative Dev validation boundary.
    """
    if not isinstance(body, dict):
        return None
    agent_id = body.get("botId")
    source_package = body.get("sourcePackage")
    source_package_id = (
        source_package.get("packageId")
        if isinstance(source_package, dict)
        else None
    )
    schema_name = (
        source_package.get("schemaName")
        if isinstance(source_package, dict)
        else None
    )
    template_version = (
        source_package.get("version")
        if isinstance(source_package, dict)
        else None
    )
    if (
        not isinstance(agent_id, str)
        or not agent_id.strip()
        or not isinstance(source_package_id, str)
        or not source_package_id.strip()
        or not isinstance(schema_name, str)
        or not schema_name.strip()
        or not isinstance(template_version, str)
        or not template_version.strip()
    ):
        return None
    return {
        "botId": agent_id.strip(),
        "sourcePackageId": source_package_id.strip(),
        "schemaName": schema_name.strip(),
        "templateVersion": template_version.strip(),
    }


def _emit_annotations(
    annotations: dict[str, Any],
    *,
    marker: str = _CREATE_MARKER,
) -> None:
    print(
        f"{marker}_ANNOTATIONS_JSON:"
        f"{json.dumps(annotations, ensure_ascii=True)}"
    )


def _print_evidence(
    annotations: dict[str, Any],
    body: Any,
    body_is_json: bool,
    *,
    marker: str = _CREATE_MARKER,
) -> None:
    """Print annotations followed by the response body."""
    _emit_annotations(annotations, marker=marker)
    if body_is_json:
        print(f"{marker}_RESPONSE_JSON:{json.dumps(body, ensure_ascii=True)}")
    else:
        print(f"{marker}_RESPONSE_TEXT:{body}")


def create_from_starter_package(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    package_id: str,
    kit_root: Path,
    package_name: str | None = None,
    package_version: str | None = None,
) -> dict[str, Any]:
    """Create one fresh Dev agent from the exact, maker-confirmed package.

    ``package_name``/``package_version`` are diagnostic annotations only --
    they are never sent to the service and never change routing. There is
    exactly one non-retried, non-redirected POST. See the module docstring
    and ``src/reference/mos-starter-package.md`` for the full fuse
    disposition matrix.
    """
    if not isinstance(package_id, str) or not package_id.strip():
        raise MosStarterSetupError(
            "The exact maker-confirmed starter package ID is required."
        )
    normalized_environment_id = _normalize_environment_id(environment_id)
    resolved_kit_root = kit_root.resolve()
    _validate_empty_create_workspace(resolved_kit_root)

    annotations: dict[str, Any] = {
        "targetEnvironmentId": normalized_environment_id,
        "packageId": package_id,
        "packageName": package_name,
        "catalogPackageVersion": package_version,
    }
    fuse_path = resolved_kit_root / FUSE_PATH
    _create_fuse(fuse_path, _fuse_content(annotations))

    try:
        response = client.create_agent_from_starter_package(package_id)
    except (requests.exceptions.RequestException, OSError) as exc:
        annotations["transportErrorType"] = type(exc).__name__
        annotations["transportError"] = str(exc)
        reason = _pre_dispatch_reason(exc)
        if reason is not None:
            fuse_path.unlink(missing_ok=True)
            annotations["fuseDisposition"] = "removed"
            annotations["outcome"] = "pre-dispatch-failure"
            annotations["reason"] = reason
            _emit_annotations(annotations)
            raise MosStarterSetupError(
                f"The create request did not reach the service ({reason}). "
                "The attempt fuse was cleared. The operation is complete."
            ) from exc
        annotations["fuseDisposition"] = "retained"
        annotations["outcome"] = "uncertain-transport"
        annotations["reason"] = "transport-ended-without-response"
        _emit_annotations(annotations)
        raise MosStarterSetupError(
            "The create request ended without a classified response. The "
            "attempt fuse was retained and the outcome is uncertain."
        ) from exc

    status = response.status_code
    annotations["httpStatus"] = status
    annotations["requestId"] = _extract_request_id(response)
    body, body_is_json = _parse_response_body(response)

    if 200 <= status < 300:
        identity = _extract_identity(body) if body_is_json else None
        if identity is None:
            annotations["fuseDisposition"] = "retained"
            annotations["outcome"] = "malformed-success"
            _print_evidence(annotations, body, body_is_json)
            raise MosStarterSetupError(
                f"The create response returned HTTP {status} without a "
                "usable agent identity. The attempt fuse was retained."
            )
        if identity["sourcePackageId"] != package_id:
            annotations["returnedPackageId"] = identity["sourcePackageId"]
            annotations["fuseDisposition"] = "retained"
            annotations["outcome"] = "source-package-mismatch"
            _print_evidence(annotations, body, body_is_json)
            raise MosStarterSetupError(
                "The create response identified a different source package "
                "than the request. The attempt fuse was retained."
            )
        annotations["agentId"] = identity["botId"]
        annotations["schemaName"] = identity["schemaName"]
        annotations["templateVersion"] = identity["templateVersion"]
        annotations["fuseDisposition"] = "retained"
        annotations["outcome"] = "created"
        _print_evidence(annotations, body, body_is_json)
        return {
            "environmentId": normalized_environment_id,
            "agentId": identity["botId"],
            "schemaName": identity["schemaName"],
            "starterPackageId": package_id,
            "starterPackageName": package_name,
            "catalogPackageVersion": package_version,
            "templateVersion": identity["templateVersion"],
        }

    if status in DEFINITIVE_REJECTION_STATUSES:
        fuse_path.unlink(missing_ok=True)
        annotations["fuseDisposition"] = "removed"
        annotations["outcome"] = "collision" if status == 409 else "rejected"
        _print_evidence(annotations, body, body_is_json)
        if status == 409:
            raise MosStarterSetupError(
                "The service reported a starter-package collision (HTTP 409). "
                "The attempt fuse was cleared."
            )
        raise MosStarterSetupError(
            f"The service rejected the create request (HTTP {status}). "
            "The attempt fuse was cleared. The operation is complete."
        )

    annotations["fuseDisposition"] = "retained"
    annotations["outcome"] = "uncertain-response"
    _print_evidence(annotations, body, body_is_json)
    raise MosStarterSetupError(
        f"The create response (HTTP {status}) is not a definitive outcome. "
        "The attempt fuse was retained."
    )


# --- ALM opt-in -----------------------------------------------------------
def _fetched_bot_and_alm_value(
    changeset: dict[str, Any],
    *,
    agent_id: str,
) -> tuple[dict[str, Any], Any]:
    """Validate and copy one exact fetched BotEntity with its ALM value."""
    bot = changeset.get("bot")
    if not isinstance(bot, dict):
        raise MosStarterSetupError(
            "Component fetch did not return a BotEntity; ALM was not changed."
        )
    fetched_agent_id = bot.get("cdsBotId")
    if (
        not isinstance(fetched_agent_id, str)
        or fetched_agent_id.casefold() != agent_id.casefold()
    ):
        raise MosStarterSetupError(
            "The fetched BotEntity identity does not match the requested "
            "agent; ALM was not changed."
        )
    configuration = bot.get("configuration")
    if not isinstance(configuration, dict):
        raise MosStarterSetupError(
            "The fetched BotEntity has no usable configuration; ALM was not changed."
        )
    settings = configuration.get("settings")
    if settings is not None and not isinstance(settings, dict):
        raise MosStarterSetupError(
            "The fetched BotEntity settings are not an object; ALM was not changed."
        )
    copied_bot = copy.deepcopy(bot)
    alm_value = settings.get("alm.isAlmEnabled") if settings is not None else None
    return copied_bot, alm_value


def _fetch_alm_components(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    verification: bool,
) -> dict[str, Any]:
    """Fetch ALM state while preserving service or transport failure evidence."""
    marker = _ALM_VERIFY_MARKER if verification else _ALM_MARKER
    phase = "verification" if verification else "precondition"
    try:
        return client.fetch_components(agent_id)
    except AgentBuilderHTTPError as exc:
        annotations: dict[str, Any] = {
            "targetEnvironmentId": environment_id,
            "agentId": agent_id,
            "outcome": f"{phase}-rejected",
            "httpStatus": exc.status_code,
            "requestId": exc.request_id,
        }
        if exc.response is None:
            _emit_annotations(annotations, marker=marker)
        else:
            body, body_is_json = _parse_response_body(exc.response)
            _print_evidence(annotations, body, body_is_json, marker=marker)
        raise MosStarterSetupError(
            f"The ALM {phase} fetch was rejected by the service. "
            + ("Verification did not complete." if verification else "ALM was not changed.")
        ) from exc
    except (requests.exceptions.RequestException, OSError) as exc:
        annotations = {
            "targetEnvironmentId": environment_id,
            "agentId": agent_id,
            "outcome": f"{phase}-transport-failure",
            "transportErrorType": type(exc).__name__,
            "transportError": str(exc),
        }
        _emit_annotations(annotations, marker=marker)
        raise MosStarterSetupError(
            f"The ALM {phase} fetch ended without a response. "
            + (
                "Verification did not complete."
                if verification
                else "No update was attempted."
            )
        ) from exc


def enable_alm(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Enable ALM through a full fetched-BotEntity replacement and verify it."""
    normalized_environment_id = _normalize_environment_id(environment_id)
    normalized_agent_id = _normalize_guid(agent_id, "Agent ID")
    before = _fetch_alm_components(
        client,
        environment_id=normalized_environment_id,
        agent_id=normalized_agent_id,
        verification=False,
    )
    update_bot, previous_value = _fetched_bot_and_alm_value(
        before,
        agent_id=normalized_agent_id,
    )
    before_version = update_bot.get("version")
    if previous_value is True:
        return {
            "environmentId": normalized_environment_id,
            "agentId": normalized_agent_id,
            "outcome": "already-enabled",
            "beforeBotVersion": before_version,
            "afterBotVersion": before_version,
            "previousValue": True,
            "persistedValue": True,
        }

    update_settings = update_bot["configuration"].get("settings")
    if update_settings is None:
        update_settings = {}
        update_bot["configuration"]["settings"] = update_settings
    update_settings["alm.isAlmEnabled"] = True

    annotations: dict[str, Any] = {
        "targetEnvironmentId": normalized_environment_id,
        "agentId": normalized_agent_id,
        "beforeBotVersion": before_version,
        "previousValue": previous_value,
    }
    try:
        response = client.update_bot_entity(normalized_agent_id, update_bot)
    except (requests.exceptions.RequestException, OSError) as exc:
        annotations["outcome"] = "uncertain-transport"
        annotations["transportErrorType"] = type(exc).__name__
        annotations["transportError"] = str(exc)
        _emit_annotations(annotations, marker=_ALM_MARKER)
        raise MosStarterSetupError(
            "The ALM update ended without a classified response. The setting "
            "outcome is uncertain."
        ) from exc

    status = response.status_code
    annotations["httpStatus"] = status
    annotations["requestId"] = _extract_request_id(response)
    body, body_is_json = _parse_response_body(response)
    if not 200 <= status < 300:
        annotations["outcome"] = "rejected"
        _print_evidence(annotations, body, body_is_json, marker=_ALM_MARKER)
        raise MosStarterSetupError(
            f"The service rejected the ALM update (HTTP {status}). No component "
            "changes were requested."
        )

    annotations["outcome"] = "update-accepted"
    _print_evidence(annotations, body, body_is_json, marker=_ALM_MARKER)
    after = _fetch_alm_components(
        client,
        environment_id=normalized_environment_id,
        agent_id=normalized_agent_id,
        verification=True,
    )
    after_bot, persisted_value = _fetched_bot_and_alm_value(
        after,
        agent_id=normalized_agent_id,
    )
    after_version = after_bot.get("version")
    persisted = persisted_value is True
    result = {
        "environmentId": normalized_environment_id,
        "agentId": normalized_agent_id,
        "outcome": "enabled" if persisted else "verification-failed",
        "beforeBotVersion": before_version,
        "afterBotVersion": after_version,
        "previousValue": previous_value,
        "persistedValue": persisted,
    }
    if not persisted:
        print(
            f"{_ALM_VERIFY_MARKER}_JSON:"
            f"{json.dumps(result, ensure_ascii=True)}"
        )
        raise MosStarterSetupError(
            "The ALM update was accepted, but read-back did not show "
            "`alm.isAlmEnabled: true`. Do not continue to attachment."
        )
    return result


# --- CLI --------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    list_command = commands.add_parser(
        "list",
        help="List entitled MOS starter packages. Read-only.",
    )
    _add_agentbuilder_target_arguments(list_command)

    create_command = commands.add_parser(
        "create",
        help=(
            "Create a fresh Dev agent from one exact, maker-confirmed "
            "starter package."
        ),
    )
    _add_agentbuilder_target_arguments(create_command)
    create_command.add_argument(
        "--package-id",
        required=True,
        help="Exact maker-confirmed starter package ID from `list`.",
    )
    create_command.add_argument(
        "--package-name",
        help="Diagnostic-only package name annotation.",
    )
    create_command.add_argument(
        "--package-version",
        help="Diagnostic-only package version annotation.",
    )
    enable_alm_command = commands.add_parser(
        "enable-alm",
        help="Enable ALM for one exact agent and verify the persisted setting.",
    )
    _add_agentbuilder_target_arguments(enable_alm_command)
    enable_alm_command.add_argument(
        "--agent-id",
        help="Exact created Dev agent ID. Optional when present in --target-url.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = resolve_da_target(
            target_url=args.target_url,
            environment_id=args.environment_id,
            agent_id=getattr(args, "agent_id", None),
            ring=args.ring,
            require_agent=args.command == "enable-alm",
        )
        client = _client_from_args(args, target["environmentId"], target["ring"])

        if args.command == "list":
            result = list_starter_packages(
                client,
                environment_id=target["environmentId"],
            )
            print(
                f"DA_MOS_STARTER_PACKAGES_JSON:{json.dumps(result, ensure_ascii=True)}"
            )
            return 0

        if args.command == "enable-alm":
            result = enable_alm(
                client,
                environment_id=target["environmentId"],
                agent_id=target["agentId"],
            )
            print(f"DA_MOS_STARTER_ALM_JSON:{json.dumps(result, ensure_ascii=True)}")
            return 0

        result = create_from_starter_package(
            client,
            environment_id=target["environmentId"],
            package_id=args.package_id,
            kit_root=args.kit_root.resolve(),
            package_name=args.package_name,
            package_version=args.package_version,
        )
        print(f"DA_MOS_STARTER_CREATE_JSON:{json.dumps(result, ensure_ascii=True)}")
        return 0
    except (
        AgentBuilderError,
        ExistingDASetupError,
        MosStarterSetupError,
        OSError,
        requests.exceptions.RequestException,
        ValueError,
    ) as exc:
        _print_exception(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
