# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""List entitled MOS starter packages and create a fresh Dev agent from one.

This is the DA `/setup` fresh-install path for a maker with no existing
agent: exactly two normal-path commands (``list``, ``create``), nothing
else -- no ``resolve``/``status`` command and no persona/ISV/product
policy, which belongs to the maker and
``src/skills/foundation-setup/da-mos-starter.md``, not this script.

``src/reference/mos-starter-package.md`` is the canonical narrative: the
service-evidence table, every safety invariant, the fuse disposition
matrix, the redaction contract, and open validation gaps all live there,
not here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
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
    _normalize_environment_id,
    _utc_now,
    resolve_da_target,
)


FUSE_PATH = Path(".local/setup/mos-starter/create-attempted")
_CREATE_MARKER = "DA_MOS_STARTER_CREATE"
_LIST_MARKER = "DA_MOS_STARTER_LIST"
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
REDACTED = "<redacted>"
# An exact, normalized (casefolded, separators stripped) match only -- not a
# substring test -- so a benign lookalike field such as ``secretaryName``,
# ``cookiePolicy``, or ``authorizationStatus`` is never redacted merely for
# containing a marker word.
_SECRET_FIELD_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "setcookie",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "password",
        "secret",
        "clientsecret",
        "assertion",
        "apikey",
        "xapikey",
    }
)
_NON_FIELD_CHARACTERS = re.compile(r"[^a-z0-9]")
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
# Group 2 is the key's own closing quote (for a JSON-style ``"password":``),
# captured -- not merely consumed -- so the substitution can reproduce it
# and change only the value. Group 4 is the value's opening quote; \4
# requires the same character to close it.
_SECRET_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|password|client[_-]?secret|secret|"
    r"assertion|api[_-]?key)"
    r"(\"?)(\s*[:=]\s*)(\"?)[^\"&\r\n,}]*\4"
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
    light-annotation, redacted-evidence contract ``create`` uses, then
    re-raises so the CLI still fails without anything being discarded.
    """
    try:
        packages = client.list_starter_packages()
    except AgentBuilderHTTPError as exc:
        annotations: dict[str, Any] = {
            "targetEnvironmentId": environment_id,
            "httpStatus": exc.status_code,
            "requestId": exc.request_id,
        }
        if exc.response is None:
            _emit_annotations(annotations, marker=_LIST_MARKER)
        else:
            body, body_is_json = _parse_response_body(exc.response)
            _print_evidence(annotations, body, body_is_json, marker=_LIST_MARKER)
        raise
    return {
        "environmentId": environment_id,
        "packages": summarize_starter_packages(packages),
        "catalogWarnings": catalog_warnings(packages),
    }


# --- redaction -----------------------------------------------------------
def _is_secret_field(name: str) -> bool:
    return _NON_FIELD_CHARACTERS.sub("", name.casefold()) in _SECRET_FIELD_NAMES


def redact_json(value: Any) -> Any:
    """Recursively redact only secret-bearing fields, case-insensitively.

    A non-secret string value still passes through the same bounded
    credential-pattern text redactor used for a non-JSON body, so a
    benign key such as ``message`` cannot leak a credential embedded in
    its own text. Unknown, unfamiliar, and error-detail fields and
    messages are otherwise preserved verbatim.
    """
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and _is_secret_field(key)
                else redact_json(child)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    """Apply a bounded set of token/credential patterns to non-JSON text.

    A small, fixed pass over recognizable credential shapes -- not an
    open-ended scan -- so the rest of the body stays near-verbatim. The
    key's own quoting/punctuation (for example ``"password":``) is
    reproduced unchanged; only the value between the quotes is replaced.
    """
    redacted = _BEARER_TOKEN_PATTERN.sub(REDACTED, text)
    return _SECRET_KEY_VALUE_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}{match.group(3)}"
            f"{match.group(4)}{REDACTED}{match.group(4)}"
        ),
        redacted,
    )


# --- create (the sole mutating command) -----------------------------------
def _validate_empty_create_workspace(kit_root: Path) -> None:
    conflicts = (
        CANONICAL_SETUP_STATE,
        Path(".local/config.json"),
    )
    if any((kit_root / path).exists() for path in conflicts):
        raise MosStarterSetupError(
            "This workspace already contains agent setup state. Open a new "
            "workspace to install a fresh MOS starter package."
        )


def _fuse_content(context: dict[str, Any]) -> str:
    """Render plain-text fuse content -- an audit note, never parsed back."""
    return (
        f"startedAt: {_utc_now()}\n"
        f"environmentId: {context['targetEnvironmentId']}\n"
        f"packageId: {context['packageId']}\n"
        f"packageName: {context['packageName'] or ''}\n"
        f"packageVersion: {context['packageVersion'] or ''}\n"
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
            "commands) before trying again. This command will not start a "
            "second create."
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
                f"{redact_text(str(cleanup_error))}"
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
    """Extract a usable {cdsBotId, schemaName} pair when present.

    This only checks that both fields are non-empty strings. The existing
    attach command remains the authoritative Dev validation boundary.
    """
    if not isinstance(body, dict):
        return None
    agent_id = body.get("cdsBotId")
    schema_name = body.get("schemaName")
    if (
        not isinstance(agent_id, str)
        or not agent_id.strip()
        or not isinstance(schema_name, str)
        or not schema_name.strip()
    ):
        return None
    return {"cdsBotId": agent_id.strip(), "schemaName": schema_name.strip()}


def _emit_annotations(
    annotations: dict[str, Any],
    *,
    marker: str = _CREATE_MARKER,
) -> None:
    # Redacted like the response body: a transport/local exception message
    # (for example ``transportError``) is caller-supplied text, not a
    # trusted, pre-vetted value, so a credential pattern inside it must not
    # leak through annotations either.
    print(
        f"{marker}_ANNOTATIONS_JSON:"
        f"{json.dumps(redact_json(annotations), ensure_ascii=True)}"
    )


def _print_evidence(
    annotations: dict[str, Any],
    body: Any,
    body_is_json: bool,
    *,
    marker: str = _CREATE_MARKER,
) -> None:
    """Print light annotations, then the response body, redacted -- shared
    by ``list``'s failure evidence and every ``create`` disposition branch.
    """
    _emit_annotations(annotations, marker=marker)
    if body_is_json:
        print(f"{marker}_RESPONSE_JSON:{json.dumps(redact_json(body), ensure_ascii=True)}")
    else:
        print(f"{marker}_RESPONSE_TEXT:{redact_text(body)}")


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
        "packageVersion": package_version,
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
                "The attempt fuse was cleared; it is safe to retry after "
                "resolving the local, DNS, or connection issue."
            ) from exc
        annotations["fuseDisposition"] = "retained"
        annotations["outcome"] = "uncertain-transport"
        annotations["reason"] = "transport-ended-without-response"
        _emit_annotations(annotations)
        raise MosStarterSetupError(
            "The create request ended without a classified response. The "
            "attempt fuse was retained; do not retry. Reconcile the target "
            "environment read-only (the existing `list` and "
            "`setup_existing_da.py validate-agent` commands) before taking "
            "further action."
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
                "usable agent identity. The attempt fuse was retained; do "
                "not retry. Reconcile the target environment read-only "
                "before taking further action."
            )
        annotations["agentId"] = identity["cdsBotId"]
        annotations["schemaName"] = identity["schemaName"]
        annotations["fuseDisposition"] = "retained"
        annotations["outcome"] = "created"
        _print_evidence(annotations, body, body_is_json)
        return {
            "environmentId": normalized_environment_id,
            "agentId": identity["cdsBotId"],
            "schemaName": identity["schemaName"],
            "starterPackageId": package_id,
            "starterPackageName": package_name,
            "starterPackageVersion": package_version,
        }

    if status in DEFINITIVE_REJECTION_STATUSES:
        fuse_path.unlink(missing_ok=True)
        annotations["fuseDisposition"] = "removed"
        annotations["outcome"] = "collision" if status == 409 else "rejected"
        _print_evidence(annotations, body, body_is_json)
        if status == 409:
            raise MosStarterSetupError(
                "An agent from this package may already exist in the "
                "target environment (HTTP 409). The attempt fuse was "
                "cleared. Inspect the existing Dev agent (the existing "
                "`list-agents`/`validate-agent` commands) instead of "
                "retrying create."
            )
        raise MosStarterSetupError(
            f"The service rejected the create request (HTTP {status}). "
            "The attempt fuse was cleared; it is safe to retry after "
            "resolving the reported cause."
        )

    annotations["fuseDisposition"] = "retained"
    annotations["outcome"] = "uncertain-response"
    _print_evidence(annotations, body, body_is_json)
    raise MosStarterSetupError(
        f"The create response (HTTP {status}) is not a definitive outcome. "
        "The attempt fuse was retained; do not retry. Reconcile the target "
        "environment read-only before taking further action."
    )


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
        ValueError,
    ) as exc:
        details = "\n".join((str(exc), *getattr(exc, "__notes__", ())))
        print(f"ERROR: {redact_text(details)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
