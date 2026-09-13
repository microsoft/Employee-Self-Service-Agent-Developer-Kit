# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Enable Dataverse workflow authorization for a hybrid Workday agent.

Cosmos-backed declarative agents do not have a Dataverse ``bot`` row. Flow-RP
instead resolves their workflow authorization through a provider-type MCSBot
``delegatedauthorization`` row, a linked access team, and workflow shares for
that team.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import (  # noqa: E402
    AuthExpiredError,
    authenticate,
    create_record,
    dataverse_get,
    execute_action,
    load_config,
    query_all,
)
from http_errors import APIError  # noqa: E402


PROVIDER_TYPE_MCSBOT = 3
TEAM_TYPE_ACCESS = 1
ACCESS_MASK = "ReadAccess,WriteAccess,AppendAccess,AppendToAccess,ShareAccess"
MAX_ERROR_DETAIL_LENGTH = 500


def normalize_guid(value: str, label: str) -> str:
    """Return a canonical GUID or raise a user-facing validation error."""
    try:
        return str(uuid.UUID(str(value).strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid GUID: {value!r}") from exc


def _records(response: dict | None) -> list[dict]:
    return list((response or {}).get("value") or [])


def _sanitize_error_detail(value: object) -> str:
    detail = " ".join(str(value or "").split())
    detail = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        detail,
    )
    detail = re.sub(
        r"(?i)(access[_-]?token\s*[:=]\s*)[\"']?[^,\s\"']+",
        r"\1[REDACTED]",
        detail,
    )
    if len(detail) > MAX_ERROR_DETAIL_LENGTH:
        return f"{detail[:MAX_ERROR_DETAIL_LENGTH - 3]}..."
    return detail


def _dataverse_error_detail(exc: requests.RequestException) -> str | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = _sanitize_error_detail(error.get("code"))
    message = _sanitize_error_detail(error.get("message"))
    if code and message:
        return f"{code}: {message}"
    return code or message or None


def format_request_error(exc: requests.RequestException) -> str:
    if isinstance(exc, APIError):
        lines = [exc.format_for_terminal().strip()]
    else:
        response = getattr(exc, "response", None)
        if response is None:
            lines = [
                "ERROR: Dataverse request failed: "
                f"{_sanitize_error_detail(exc)}"
            ]
        else:
            request = getattr(response, "request", None)
            method = str(getattr(request, "method", None) or "REQUEST").upper()
            url = str(getattr(request, "url", None) or "").split("?")[0]
            target = f" {method} {url}" if url else ""
            lines = [
                f"ERROR: Dataverse request failed: HTTP "
                f"{response.status_code}{target}"
            ]
            request_id = response.headers.get("x-ms-request-id")
            if request_id:
                lines.append(f"Request ID: {request_id}")

    detail = _dataverse_error_detail(exc)
    if detail:
        lines.append(f"Dataverse detail: {detail}")
    return "\n".join(lines)


def find_delegated_authorizations(env_url: str, token: str, bot_id: str) -> list[dict]:
    return query_all(
        env_url,
        token,
        "delegatedauthorizations",
        "delegatedauthorizationid,name,providertype",
        filter_expr=f"botid eq '{bot_id}'",
    )


def find_access_teams(env_url: str, token: str, bot_id: str) -> list[dict]:
    response = dataverse_get(
        env_url,
        token,
        "teams",
        params={
            "$select": "teamid,name,teamtype",
            "$expand": "delegatedauthorizationid",
            "$filter": f"delegatedauthorizationid/botid eq '{bot_id}'",
        },
    )
    return _records(response)


def retrieve_workflow_access(
    env_url: str,
    token: str,
    workflow_id: str,
) -> list[dict]:
    target = json.dumps(
        {"@odata.id": f"workflows({workflow_id})"},
        separators=(",", ":"),
    )
    response = dataverse_get(
        env_url,
        token,
        "RetrieveSharedPrincipalsAndAccess(Target=@tid)",
        params={"@tid": target},
    )
    return list((response or {}).get("PrincipalAccesses") or [])


def _team_access(principal_accesses: list[dict], team_id: str) -> dict | None:
    expected = team_id.lower()
    for item in principal_accesses:
        principal = item.get("Principal") or {}
        principal_type = str(principal.get("@odata.type") or "").lower()
        owner_id = str(principal.get("ownerid") or "").lower()
        if "team" in principal_type and owner_id == expected:
            return item
    return None


def ensure_delegated_authorization(
    env_url: str,
    token: str,
    bot_id: str,
    report,
) -> str:
    existing = find_delegated_authorizations(env_url, token, bot_id)
    if len(existing) > 1:
        raise RuntimeError(
            f"Found {len(existing)} delegated authorizations for bot {bot_id}; "
            "resolve the duplicates before continuing."
        )
    if existing:
        record = existing[0]
        if record.get("providertype") != PROVIDER_TYPE_MCSBOT:
            raise RuntimeError(
                "The existing delegated authorization has provider type "
                f"{record.get('providertype')}; expected {PROVIDER_TYPE_MCSBOT}."
            )
        record_id = normalize_guid(
            record.get("delegatedauthorizationid"),
            "delegatedauthorizationid",
        )
        report("REUSED", f"Delegated authorization {record_id}")
        return record_id

    record_id = create_record(
        env_url,
        token,
        "delegatedauthorizations",
        {
            "name": f"Workday hybrid agent authorization ({bot_id})",
            "providertype": PROVIDER_TYPE_MCSBOT,
            "botid": bot_id,
        },
    )
    if not record_id:
        raise RuntimeError("Dataverse created the delegated authorization without returning its ID.")
    record_id = normalize_guid(record_id, "delegatedauthorizationid")
    report("CREATED", f"Delegated authorization {record_id}")
    return record_id


def _current_user_context(env_url: str, token: str) -> tuple[str, str]:
    who = dataverse_get(env_url, token, "WhoAmI()")
    user_id = normalize_guid(who.get("UserId"), "WhoAmI UserId")
    user = dataverse_get(
        env_url,
        token,
        f"systemusers({user_id})",
        params={"$select": "_businessunitid_value"},
    )
    business_unit_id = normalize_guid(
        user.get("_businessunitid_value"),
        "current user's business unit",
    )
    return user_id, business_unit_id


def ensure_access_team(
    env_url: str,
    token: str,
    bot_id: str,
    delegated_authorization_id: str,
    report,
) -> str:
    existing = find_access_teams(env_url, token, bot_id)
    if len(existing) > 1:
        raise RuntimeError(
            f"Found {len(existing)} access teams for bot {bot_id}; "
            "Flow-RP expects exactly one."
        )
    if existing:
        team = existing[0]
        if team.get("teamtype") != TEAM_TYPE_ACCESS:
            raise RuntimeError(
                f"The existing team has type {team.get('teamtype')}; "
                f"expected access-team type {TEAM_TYPE_ACCESS}."
            )
        team_id = normalize_guid(team.get("teamid"), "teamid")
        report("REUSED", f"Access team {team_id}")
        return team_id

    administrator_id, business_unit_id = _current_user_context(env_url, token)
    team_id = create_record(
        env_url,
        token,
        "teams",
        {
            "name": f"Workday hybrid agent team ({bot_id})",
            "teamtype": TEAM_TYPE_ACCESS,
            "businessunitid@odata.bind": f"/businessunits({business_unit_id})",
            "administratorid@odata.bind": f"/systemusers({administrator_id})",
            "delegatedauthorizationid@odata.bind": (
                f"/delegatedauthorizations({delegated_authorization_id})"
            ),
        },
    )
    if not team_id:
        raise RuntimeError("Dataverse created the access team without returning its ID.")
    team_id = normalize_guid(team_id, "teamid")
    report("CREATED", f"Access team {team_id}")
    return team_id


def ensure_workflow_access(
    env_url: str,
    token: str,
    workflow_id: str,
    team_id: str,
    report,
) -> None:
    workflows = query_all(
        env_url,
        token,
        "workflows",
        "workflowid,name,statecode",
        filter_expr=f"workflowid eq {workflow_id}",
    )
    if len(workflows) != 1:
        raise RuntimeError(
            f"Expected one workflow for {workflow_id}; found {len(workflows)}."
        )
    workflow_name = workflows[0].get("name") or workflow_id

    current_access = _team_access(
        retrieve_workflow_access(env_url, token, workflow_id),
        team_id,
    )
    current_mask = str((current_access or {}).get("AccessMask") or "")
    if "WriteAccess" in current_mask:
        report("REUSED", f"Workflow '{workflow_name}' already has {current_mask}")
        return

    payload = {
        "Target": {
            "@odata.type": "Microsoft.Dynamics.CRM.workflow",
            "workflowid": workflow_id,
        },
        "PrincipalAccess": {
            "Principal": {
                "@odata.type": "Microsoft.Dynamics.CRM.team",
                "teamid": team_id,
            },
            "AccessMask": ACCESS_MASK,
        },
    }
    action = "ModifyAccess" if current_access else "GrantAccess"
    execute_action(env_url, token, action, payload)

    verified = _team_access(
        retrieve_workflow_access(env_url, token, workflow_id),
        team_id,
    )
    verified_mask = str((verified or {}).get("AccessMask") or "")
    if "WriteAccess" not in verified_mask:
        raise RuntimeError(
            f"Workflow '{workflow_name}' was updated but verification did not "
            "find WriteAccess for the access team."
        )
    report("UPDATED", f"Workflow '{workflow_name}' granted {verified_mask}")


def enable_authorization(
    env_url: str,
    token: str,
    bot_id: str,
    workflow_ids: list[str],
    report,
) -> None:
    delegated_authorization_id = ensure_delegated_authorization(
        env_url,
        token,
        bot_id,
        report,
    )
    team_id = ensure_access_team(
        env_url,
        token,
        bot_id,
        delegated_authorization_id,
        report,
    )
    for workflow_id in workflow_ids:
        ensure_workflow_access(
            env_url,
            token,
            workflow_id,
            team_id,
            report,
        )


def _print_report(status: str, message: str) -> None:
    print(f"[{status.lower():7s}] {message}")


def _confirm(env_url: str, bot_id: str, workflow_ids: list[str]) -> bool:
    print("This will create or reuse Dataverse authorization records and share:")
    print(f"  Environment: {env_url}")
    print(f"  Agent bot ID: {bot_id}")
    for workflow_id in workflow_ids:
        print(f"  Workflow:     {workflow_id}")
    try:
        answer = input("Continue? [y/N]: ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enable workflow authorization for a Cosmos-backed Workday "
            "hybrid declarative agent."
        ),
    )
    parser.add_argument(
        "--url",
        help="Dataverse environment URL. Defaults to .local/config.json.",
    )
    parser.add_argument("--bot-id", required=True, help="Cosmos agent bot GUID.")
    parser.add_argument(
        "--workflow-id",
        action="append",
        required=True,
        help="Workflow GUID. Repeat for each flow.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    parser.add_argument(
        "--interactive-auth",
        action="store_true",
        help="Always open the Microsoft account picker before accessing Dataverse.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate configuration and GUID arguments without authenticating or writing.",
    )
    args = parser.parse_args()

    try:
        config = load_config() if not args.url else {}
        env_url = str(
            args.url or config.get("dataverseEndpoint") or ""
        ).rstrip("/")
        if not env_url:
            raise ValueError(
                "No Dataverse environment is configured. Run /setup first."
            )
        bot_id = normalize_guid(args.bot_id, "Bot ID")
        workflow_ids = list(
            dict.fromkeys(
                normalize_guid(value, "Workflow ID")
                for value in args.workflow_id
            )
        )

        if args.validate_only:
            print(
                f"Validated bot ID and {len(workflow_ids)} unique workflow ID(s) "
                f"for {env_url}."
            )
            return

        if not args.yes and not _confirm(env_url, bot_id, workflow_ids):
            print("Cancelled. No Dataverse changes were made.")
            return

        print(f"Authenticating to Dataverse at {env_url}...")
        token = authenticate(
            env_url,
            force_interactive=args.interactive_auth,
        )
        print("Authenticated.")
        enable_authorization(
            env_url,
            token,
            bot_id,
            workflow_ids,
            _print_report,
        )
    except (AuthExpiredError, APIError) as exc:
        print(format_request_error(exc))
        raise SystemExit(1) from exc
    except requests.RequestException as exc:
        print(format_request_error(exc))
        raise SystemExit(1) from exc
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc

    print()
    print(
        f"Workday hybrid flow authorization is enabled for "
        f"{len(workflow_ids)} workflow(s)."
    )


if __name__ == "__main__":
    main()
