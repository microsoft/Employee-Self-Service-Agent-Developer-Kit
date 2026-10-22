# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded environment provisioning, user-access, and cache-cleanup operations."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from agentbuilder import (
    DEFAULT_API_VERSION,
    ENVIRONMENT_ROLE_API_VERSION,
    ENVIRONMENT_ROLE_SCOPE,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate,
    authenticate_cached_account,
    authenticate_environment_roles,
    authenticate_selected_tenant,
    authenticated_user_identity,
    environment_role_request,
    forget_cached_account,
    list_provisioning_locations,
    is_environment_maker_assignment,
    provision_environment,
)


_LOCATIONS_MARKER = "DA_ENVIRONMENT_LOCATIONS"
_CREATE_MARKER = "DA_ENVIRONMENT_CREATE"
_FORGET_MARKER = "DA_AGENTBUILDER_FORGET_ACCOUNT"
_IDENTITY_MARKER = "DA_ENVIRONMENT_ACCOUNT"
_ROLES_MARKER = "DA_ENVIRONMENT_ROLES"
_GRANT_MARKER = "DA_ENVIRONMENT_MAKER_GRANT"
_CREATE_EVIDENCE_ROOT = Path(".local/setup/environment/create-requests")


class PowerPlatformEnvironmentSetupError(RuntimeError):
    """Raised when an environment setup operation cannot complete safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_path(kit_root: Path) -> Path:
    return kit_root.resolve() / ".local" / ".agentbuilder_token_cache.bin"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _response_body(response: requests.Response | None) -> Any:
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}


def _print_http_error(error: AgentBuilderHTTPError, marker: str) -> None:
    result = {
        "statusCode": error.status_code,
        "errorCode": error.error_code,
        "requestId": error.request_id,
        "authorizationFailure": error.status_code in (401, 403),
    }
    print(f"{marker}_ERROR_JSON:{json.dumps(result, ensure_ascii=True)}")
    body = _response_body(error.response)
    if body is not None:
        print(f"{marker}_ERROR_RESPONSE_JSON:{json.dumps(body, ensure_ascii=True)}")


def summarize_provisioning_locations(
    response: dict[str, Any],
) -> dict[str, Any]:
    """Project tenant-supported choices while preserving raw evidence elsewhere."""
    locations = []
    for item in response["collection"]:
        request_name = item.get("name")
        if not isinstance(request_name, str) or not request_name.strip():
            raise PowerPlatformEnvironmentSetupError(
                "Environment provisioning location is missing a valid request name."
            )
        request_name = request_name.strip()
        locations.append(
            {
                "value": request_name,
                "name": str(
                    item.get("displayName")
                    or request_name
                ).strip(),
                "isDefault": item.get("isDefault") is True,
                "isDisabled": item.get("isDisabled") is True,
            }
        )
    macro_regions = []
    for item in response["macroRegions"]:
        region_id = str(item.get("macroRegionId") or "").strip()
        if not region_id:
            continue
        macro_regions.append(
            {
                "value": region_id,
                "name": str(
                    item.get("displayName") or region_id
                ).strip(),
                "dataResidencyNote": str(
                    item.get("dataResidencyNote") or ""
                ).strip(),
            }
        )
    return {
        "selectionMode": response["locationSelectionMode"],
        "locations": sorted(
            locations,
            key=lambda item: (
                not item["isDefault"],
                item["name"].casefold(),
                item["value"],
            ),
        ),
        "macroRegions": sorted(
            macro_regions,
            key=lambda item: (item["name"].casefold(), item["value"]),
        ),
    }


def list_locations(args: argparse.Namespace) -> dict[str, Any]:
    kit_root = args.kit_root.resolve()
    cache_path = _cache_path(kit_root)
    if args.tenant_id:
        token = authenticate(
            args.tenant_id,
            args.ring,
            cache_path=cache_path,
            force_account_selection=args.select_account,
            account_hint=args.account,
        )
        tenant_id = args.tenant_id
    else:
        token, tenant_id = authenticate_selected_tenant(
            args.ring,
            cache_path=cache_path,
            force_account_selection=args.select_account,
            account_hint=args.account,
        )
    response = list_provisioning_locations(
        token,
        args.ring,
        api_version=args.api_version,
    )
    evidence_path = (
        kit_root
        / ".local"
        / "setup"
        / f"environment-locations-{args.ring}.json"
    )
    _write_json(
        evidence_path,
        {
            "tenantId": tenant_id,
            "ring": args.ring,
            "response": response,
        },
    )
    return {
        "tenantId": tenant_id,
        "ring": args.ring,
        **summarize_provisioning_locations(response),
        "evidencePath": str(evidence_path),
    }


def _create_evidence_path(
    kit_root: Path,
    client_request_id: str,
) -> Path:
    return (
        kit_root.resolve()
        / _CREATE_EVIDENCE_ROOT
        / f"{client_request_id}.json"
    )


def _reserve_request(
    path: Path,
    evidence: dict[str, Any],
    *,
    operation: str = "environment create",
    reconciliation: str = "environment listing",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as exc:
        raise PowerPlatformEnvironmentSetupError(
            f"This confirmed {operation} request was already submitted. "
            f"Inspect the retained evidence and reconcile through {reconciliation} "
            "before starting another request."
        ) from exc


def _environment_identity(response: Any) -> dict[str, str] | None:
    if not isinstance(response, dict):
        return None
    updated = response.get("updatedEnvironment")
    if not isinstance(updated, dict):
        return None
    environment_id = str(updated.get("environmentId") or "").strip()
    display_name = str(updated.get("displayName") or "").strip()
    if not environment_id:
        return None
    return {
        "id": environment_id,
        **({"name": display_name} if display_name else {}),
    }


def create_environment(args: argparse.Namespace) -> dict[str, Any]:
    kit_root = args.kit_root.resolve()
    try:
        client_request_id = str(uuid.UUID(args.client_request_id))
    except ValueError as exc:
        raise ValueError("Client request ID must be a GUID.") from exc
    display_name = str(args.display_name or "").strip()
    if not display_name:
        raise ValueError("Environment display name is required.")
    location_field = (
        "location" if args.location is not None else "macroRegion"
    )
    location_value = str(
        args.location
        if args.location is not None
        else args.macro_region
    ).strip()
    if not location_value:
        raise ValueError("Environment region is required.")
    request_body = {
        "displayName": display_name,
        "environmentSku": args.environment_type,
        location_field: location_value,
    }
    evidence_path = _create_evidence_path(
        kit_root,
        client_request_id,
    )
    evidence: dict[str, Any] = {
        "startedAt": _utc_now(),
        "ring": args.ring,
        "account": args.account,
        "request": request_body,
        "clientRequestId": client_request_id,
    }
    _reserve_request(evidence_path, evidence)
    try:
        token, tenant_id, account = authenticate_cached_account(
            args.ring,
            account_hint=args.account,
            tenant_id=args.tenant_id,
            cache_path=_cache_path(kit_root),
        )
        result = provision_environment(
            token,
            args.ring,
            request_body=request_body,
            client_request_id=client_request_id,
            api_version=args.api_version,
        )
    except AgentBuilderHTTPError as exc:
        evidence.update(
            {
                "completedAt": _utc_now(),
                "outcome": "service-rejected",
                "statusCode": exc.status_code,
                "errorCode": exc.error_code,
                "requestId": exc.request_id,
                "response": _response_body(exc.response),
            }
        )
        _write_json(evidence_path, evidence)
        raise
    except (AgentBuilderError, OSError, requests.RequestException, ValueError) as exc:
        evidence.update(
            {
                "completedAt": _utc_now(),
                "outcome": "uncertain",
                "errorType": type(exc).__name__,
                "error": str(exc),
            }
        )
        _write_json(evidence_path, evidence)
        raise

    response = result.get("response")
    operation_status = (
        str(response.get("status") or "").strip()
        if isinstance(response, dict)
        else ""
    )
    if operation_status in ("Failed", "ValidationFailed"):
        outcome = "failed"
    elif operation_status == "Succeeded":
        outcome = "created"
    else:
        outcome = "accepted"
    evidence.update(
        {
            "completedAt": _utc_now(),
            "tenantId": tenant_id,
            "authenticatedAccount": account,
            "outcome": outcome,
            **result,
        }
    )
    _write_json(evidence_path, evidence)
    return {
        "tenantId": tenant_id,
        "ring": args.ring,
        "account": account,
        "outcome": outcome,
        "statusCode": result["statusCode"],
        "requestId": result["requestId"],
        "operationLocation": result.get("operationLocation"),
        "operationStatus": operation_status or None,
        "environment": _environment_identity(response),
        "evidencePath": str(evidence_path),
    }


def forget_account(args: argparse.Namespace) -> dict[str, Any]:
    return forget_cached_account(
        args.account,
        cache_path=_cache_path(args.kit_root),
        shared_cache_path=args.kit_root / ".local" / ".token_cache.bin",
    )


def _confirmed_account_identity(
    args: argparse.Namespace,
    token: str,
    account: str,
) -> dict[str, str]:
    identity = authenticated_user_identity(
        token, account,
        audience=(
            ENVIRONMENT_ROLE_SCOPE.removesuffix("/.default")
            if args.command in ("list-roles", "grant-maker") else None
        ),
    )
    if identity["account"].casefold() != args.account.strip().casefold():
        raise PowerPlatformEnvironmentSetupError(
            "Authentication selected a different account; no access change was submitted."
        )
    if args.tenant_id and identity["tenantId"] != str(uuid.UUID(args.tenant_id)):
        raise PowerPlatformEnvironmentSetupError(
            "The authenticated tenant differs from the selected tenant."
        )
    return identity


def inspect_account(args: argparse.Namespace) -> dict[str, Any]:
    token, _tenant, account = authenticate_cached_account(
        args.ring,
        account_hint=args.account,
        tenant_id=args.tenant_id,
        cache_path=_cache_path(args.kit_root),
    )
    return {
        "ring": args.ring,
        **_confirmed_account_identity(args, token, account),
    }


def environment_roles(args: argparse.Namespace) -> dict[str, Any]:
    """Inspect roles or submit one approved grant; do not sequence readback."""
    grant = args.command == "grant-maker"
    if not args.account.strip():
        raise ValueError("Account sign-in name is required.")
    environment_id = str(uuid.UUID(args.environment_id))
    tenant_id = str(uuid.UUID(args.tenant_id))
    principal_id = str(uuid.UUID(args.principal_id)) if grant else None
    if grant and not args.principal_account.strip():
        raise ValueError("The receiving user's sign-in name is required.")
    if grant and str(uuid.UUID(args.principal_tenant_id)) != tenant_id:
        raise ValueError(
            "The receiving user's object ID must be established in the creation tenant."
        )
    request_id = str(uuid.UUID(args.client_request_id)) if grant else str(uuid.uuid4())
    if grant:
        token, _tenant, account = authenticate_cached_account(
            args.ring,
            account_hint=args.account,
            tenant_id=tenant_id,
            cache_path=_cache_path(args.kit_root),
            scopes=(ENVIRONMENT_ROLE_SCOPE,),
        )
    else:
        token, account = authenticate_environment_roles(
            tenant_id,
            args.ring,
            account_hint=args.account,
            cache_path=_cache_path(args.kit_root),
            force_account_selection=args.select_account,
        )
    identity = _confirmed_account_identity(args, token, account)
    evidence_path = (
        args.kit_root.resolve() / ".local" / "setup" / "environment"
        / ("role-grants" if grant else "role-inspections") / f"{request_id}.json"
    )
    evidence = {
        "startedAt": _utc_now(),
        "ring": args.ring,
        "environmentId": environment_id,
        "authenticatedIdentity": identity,
        "clientRequestId": request_id,
        "apiVersion": args.api_version,
        "operation": args.command,
        **({
            "principal": {
                "id": principal_id,
                "account": args.principal_account,
                "tenantId": tenant_id,
            },
        } if grant else {}),
    }
    if grant:
        _reserve_request(
            evidence_path, evidence,
            operation="Environment Maker grant",
            reconciliation="read-only role inspection",
        )
    try:
        response = environment_role_request(
            token, args.ring,
            environment_id=environment_id,
            principal_id=principal_id,
            principal_email=args.principal_account if grant else None,
            client_request_id=request_id,
            api_version=args.api_version,
        )
    except (AgentBuilderError, OSError, requests.RequestException, ValueError) as exc:
        evidence.update({
            "completedAt": _utc_now(),
            "outcome": "service-rejected" if isinstance(exc, AgentBuilderHTTPError) else "uncertain",
            "errorType": type(exc).__name__,
            "error": str(exc),
        })
        if isinstance(exc, AgentBuilderHTTPError):
            evidence.update({
                "statusCode": exc.status_code,
                "requestId": exc.request_id,
                "response": _response_body(exc.response),
            })
        try:
            _write_json(evidence_path, evidence)
        except OSError as write_error:
            exc.add_note(f"Role evidence could not be saved: {write_error}")
        raise
    body = _response_body(response)
    evidence.update({
        "completedAt": _utc_now(),
        "statusCode": response.status_code,
        "requestId": response.headers.get("x-ms-request-id")
        or response.headers.get("x-ms-service-request-id") or request_id,
        "response": body,
    })
    if grant:
        assert principal_id is not None
        added = body.get("add") if isinstance(body, dict) else None
        created = (
            isinstance(added, list) and len(added) == 1
            and isinstance(added[0], dict)
            and added[0].get("httpStatus") == "Created"
            and is_environment_maker_assignment(
                added[0].get("roleAssignment"),
                environment_id=environment_id,
                principal_id=principal_id,
                tenant_id=tenant_id,
            )
        )
        evidence["outcome"] = "created" if created else "unconfirmed"
    else:
        values = body.get("value") if isinstance(body, dict) else None
        evidence["outcome"] = (
            "read" if isinstance(values, list)
            and all(isinstance(value, dict) for value in values)
            else "invalid-response"
        )
    try:
        _write_json(evidence_path, evidence)
    except OSError as exc:
        exc.add_note(
            f"The role API responded with HTTP {response.status_code}; "
            "inspect roles before considering another grant."
        )
        exc.add_note(f"Role response JSON: {json.dumps(body, ensure_ascii=True)}")
        raise
    return {**evidence, "evidencePath": str(evidence_path)}


def _add_auth_arguments(
    parser: argparse.ArgumentParser,
    *,
    account_required: bool = False,
    tenant_required: bool = False,
    api_version: str = DEFAULT_API_VERSION,
) -> None:
    parser.add_argument(
        "--ring",
        choices=("prod", "preprod", "test"),
        required=True,
    )
    parser.add_argument("--tenant-id", required=tenant_required)
    parser.add_argument("--account", required=account_required)
    parser.add_argument(
        "--api-version",
        default=api_version,
    )
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=Path.cwd(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    locations = commands.add_parser(
        "list-locations",
        help="List tenant-supported environment provisioning locations.",
    )
    _add_auth_arguments(locations)
    locations.add_argument("--select-account", action="store_true")

    create = commands.add_parser(
        "create",
        help="Submit one confirmed Power Platform environment create request.",
    )
    _add_auth_arguments(create, account_required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument(
        "--environment-type",
        choices=("Sandbox", "Production", "Trial"),
        required=True,
    )
    location = create.add_mutually_exclusive_group(required=True)
    location.add_argument("--location")
    location.add_argument("--macro-region")
    create.add_argument("--client-request-id", required=True)

    forget = commands.add_parser(
        "forget-account",
        help="Remove one exact account's credentials from both toolkit token caches.",
    )
    forget.add_argument("--account", required=True)
    forget.add_argument(
        "--kit-root",
        type=Path,
        default=Path.cwd(),
    )

    identity = commands.add_parser(
        "inspect-account",
        help="Return one cached user's authenticated tenant-local object ID.",
    )
    _add_auth_arguments(identity, account_required=True)

    for command, help_text in (
        ("list-roles", "Inspect one exact environment's role assignments."),
        ("grant-maker", "Submit one approved Environment Maker grant for one user."),
    ):
        role = commands.add_parser(command, help=help_text)
        _add_auth_arguments(
            role, account_required=True, tenant_required=True,
            api_version=ENVIRONMENT_ROLE_API_VERSION,
        )
        role.add_argument("--environment-id", required=True)
        if command == "list-roles":
            role.add_argument("--select-account", action="store_true")
        else:
            role.add_argument("--principal-id", required=True)
            role.add_argument("--principal-account", required=True)
            role.add_argument("--principal-tenant-id", required=True)
            role.add_argument("--client-request-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect-account":
            result = inspect_account(args)
            print(f"{_IDENTITY_MARKER}_JSON:{json.dumps(result, ensure_ascii=True)}")
            return 0
        if args.command in ("list-roles", "grant-maker"):
            result = environment_roles(args)
            marker = _GRANT_MARKER if args.command == "grant-maker" else _ROLES_MARKER
            print(f"{marker}_JSON:{json.dumps(result, ensure_ascii=True)}")
            return 0 if result["outcome"] in ("created", "read") else 1
        if args.command == "list-locations":
            result = list_locations(args)
            print(
                f"{_LOCATIONS_MARKER}_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0
        if args.command == "forget-account":
            result = forget_account(args)
            print(
                f"{_FORGET_MARKER}_JSON:"
                f"{json.dumps(result, ensure_ascii=True)}"
            )
            return 0
        result = create_environment(args)
        print(
            f"{_CREATE_MARKER}_JSON:"
            f"{json.dumps(result, ensure_ascii=True)}"
        )
        return 1 if result["outcome"] == "failed" else 0
    except AgentBuilderHTTPError as exc:
        marker = {
            "list-locations": _LOCATIONS_MARKER,
            "list-roles": _ROLES_MARKER,
            "grant-maker": _GRANT_MARKER,
        }.get(args.command, _CREATE_MARKER)
        _print_http_error(exc, marker)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except (
        AgentBuilderError,
        OSError,
        PowerPlatformEnvironmentSetupError,
        requests.RequestException,
        ValueError,
    ) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(f"NOTE: {note}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
