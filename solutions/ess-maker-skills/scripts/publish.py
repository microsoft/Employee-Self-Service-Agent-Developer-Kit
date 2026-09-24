# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Publish Script

Publishes the active Copilot Studio agent so pushed topic (botcomponent)
changes go live in the test pane and runtime. Dataverse writes alone do not
take effect until the bot is published; flow ``clientdata`` edits are the
exception (live immediately, no publish needed).

This is a standalone capability — it is NOT run automatically by push.py. A
maker (or the agent, on the maker's behalf) invokes it explicitly when they
want their pushed topic changes to go live.

Usage:
    python scripts/publish.py           — Publish the active agent (interactive)
    python scripts/publish.py --yes     — Publish without the confirmation prompt
    python scripts/publish.py --account user@example.com
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import sys as _sys
    if _sys.stdout.encoding and _sys.stdout.encoding.lower() != "utf-8" \
            and hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 — console reconfig is best-effort
    pass

# Add scripts/ to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import (  # noqa: E402
    authenticate,
    load_config,
    publish_bot,
)
from agentbuilder import (  # noqa: E402
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate as authenticate_agentbuilder,
)

NATIVE_SETUP_STATE = Path(".local/setup/config.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish the active Copilot Studio agent."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Publish without the confirmation prompt.",
    )
    parser.add_argument(
        "--account",
        help="Prefer this cached AgentBuilder sign-in for native publication.",
    )
    parser.add_argument(
        "--select-account",
        action="store_true",
        help="Always show the AgentBuilder account picker.",
    )
    return parser


def _is_native_config(config: dict[str, Any]) -> bool:
    agent = config.get("agent")
    return config.get("releaseLine") == "da" or (
        isinstance(agent, dict) and agent.get("releaseLine") == "da"
    )


def _load_native_setup_state() -> dict[str, Any]:
    if not NATIVE_SETUP_STATE.exists():
        raise AgentBuilderError(
            "Native setup state is missing. Run /setup before publishing."
        )
    try:
        state = json.loads(NATIVE_SETUP_STATE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentBuilderError(
            "Native setup state could not be read. Run /setup again."
        ) from exc
    if not isinstance(state, dict):
        raise AgentBuilderError(
            "Native setup state is malformed. Run /setup again."
        )
    return state


def _native_context(
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, str]:
    environment = state.get("environment")
    agents = state.get("agents")
    active_slug = config.get("activeAgent")
    if (
        not isinstance(environment, dict)
        or not isinstance(agents, dict)
        or not isinstance(active_slug, str)
        or not active_slug.strip()
    ):
        raise AgentBuilderError(
            "Native setup state is incomplete. Run /setup again."
        )
    agent = next(
        (
            candidate.get("agent")
            for candidate in agents.values()
            if isinstance(candidate, dict)
            and isinstance(candidate.get("agent"), dict)
            and candidate["agent"].get("workspace_slug") == active_slug
        ),
        None,
    )
    if not isinstance(agent, dict):
        raise AgentBuilderError(
            "The active agent is missing from native setup state. Run /setup "
            "again."
        )
    values = {
        "environment_id": environment.get("id"),
        "tenant_id": environment.get("tenant_id"),
        "host": environment.get("power_platform_api_endpoint"),
        "ring": environment.get("ring"),
        "api_version": environment.get("api_version"),
        "agent_id": agent.get("id"),
        "agent_name": agent.get("name") or agent.get("id"),
    }
    if not all(isinstance(value, str) and value.strip()
               for value in values.values()):
        raise AgentBuilderError(
            "Native setup state is incomplete. Run /setup again."
        )
    return {key: value.strip() for key, value in values.items()}


def _response_body(error: AgentBuilderHTTPError) -> dict[str, Any]:
    if error.response is None:
        return {}
    try:
        body = error.response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _server_error_fields(
    error: AgentBuilderHTTPError,
) -> tuple[str | None, str | None, Any]:
    body = _response_body(error)
    nested = body.get("Error")
    if not isinstance(nested, dict):
        nested = body.get("error")
    if not isinstance(nested, dict):
        nested = {}
    code = (
        body.get("ErrorCode")
        or nested.get("Code")
        or nested.get("code")
        or error.error_code
    )
    message = (
        body.get("ErrorMessage")
        or nested.get("Message")
        or nested.get("message")
    )
    properties = nested.get("Properties")
    if not isinstance(properties, dict):
        properties = nested.get("properties")
    diagnostics = (
        properties.get("Diagnostics")
        if isinstance(properties, dict)
        else None
    )
    return (
        str(code).strip() if code else None,
        str(message).strip() if message else None,
        diagnostics,
    )


def _diagnostic_rows(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for group in raw:
        if not isinstance(group, dict):
            continue
        reference = group.get("reference")
        if not isinstance(reference, dict):
            reference = {}
        dialog_id = str(reference.get("dialogId") or "").strip()
        action_id = str(reference.get("actionId") or "").strip()
        diagnostic_list = group.get("diagnosticList")
        if not isinstance(diagnostic_list, list):
            continue
        for diagnostic in diagnostic_list:
            if not isinstance(diagnostic, dict):
                continue
            code = str(diagnostic.get("errorCode") or "").strip()
            message = str(diagnostic.get("errorMessage") or "").strip()
            if not message and not code:
                continue
            identity = (dialog_id, action_id, code, message)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(
                {
                    "dialog_id": dialog_id,
                    "action_id": action_id,
                    "code": code,
                    "message": message,
                }
            )
    return rows


def _print_native_error(error: AgentBuilderHTTPError) -> None:
    code, message, raw_diagnostics = _server_error_fields(error)
    print(
        "  ❌ Copilot Studio rejected the native publish request "
        f"(HTTP {error.status_code})."
    )
    if code:
        print(f"  Code: {code}")
    if message:
        print(f"  Message: {message}")
    rows = _diagnostic_rows(raw_diagnostics)
    if rows:
        print(f"  Validation details ({len(rows)} distinct):")
        for row in rows:
            location = " / ".join(
                value
                for value in (row["dialog_id"], row["action_id"])
                if value
            )
            prefix = f"[{row['code']}] " if row["code"] else ""
            text = row["message"] or row["code"]
            print(f"    - {prefix}{text}")
            if location:
                print(f"      {location}")
    if error.request_id:
        print(f"  Request ID: {error.request_id}")


def _confirm(agent_name: str, environment: str, auto_yes: bool) -> bool:
    print(f"Agent:       {agent_name}")
    print(f"Environment: {environment}")
    if auto_yes:
        return True
    response = input(
        "\nPublish this agent so pushed topic changes go live? (yes/no): "
    ).strip().lower()
    if response in ("yes", "y"):
        return True
    print("Publish cancelled.")
    return False


def _publish_native(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> int:
    try:
        context = _native_context(_load_native_setup_state(), config)
    except AgentBuilderError as error:
        print(f"ERROR: {error}")
        return 2
    if not _confirm(
        context["agent_name"],
        context["host"],
        args.yes,
    ):
        return 0

    print("\nAuthenticating to AgentBuilder...")
    try:
        token = authenticate_agentbuilder(
            context["tenant_id"],
            context["ring"],
            account_hint=args.account,
            force_account_selection=args.select_account,
        )
        client = AgentBuilderClient(
            context["host"],
            token,
            ring=context["ring"],
            tenant_id=context["tenant_id"],
            api_version=context["api_version"],
        )
        print("Authenticated.\n")
        print("Publishing... (this can take a minute)")
        result = client.publish_agent(context["agent_id"])
    except AgentBuilderHTTPError as error:
        _print_native_error(error)
        return 1
    except AgentBuilderError as error:
        print(f"  ❌ Publish failed: {error}")
        return 1

    validation_pending = result.get(
        "ValidationPending",
        result.get("validationPending"),
    )
    if validation_pending is True:
        print(
            "  ✅ Publish request accepted. Copilot Studio validation is "
            "still running."
        )
    else:
        print("  ✅ Published. Pushed topic changes are now live.")
    _emit_telemetry()
    return 0


def _publish_classic(config: dict[str, Any], auto_yes: bool) -> int:
    env_url = config["dataverseEndpoint"]
    agent = config["agent"]
    bot_id = agent["botId"]
    agent_name = agent.get("name", bot_id)

    if not _confirm(agent_name, env_url, auto_yes):
        return 0

    print("\nAuthenticating to Dataverse...")
    token = authenticate(env_url)
    print("Authenticated.\n")

    print("Publishing... (this can take a minute)")
    try:
        publish_bot(env_url, token, bot_id)
    except Exception as e:  # noqa: BLE001 — surface a clean message + exit code
        print(f"  ❌ Publish failed: {e}")
        return 1

    print("  ✅ Published. Pushed topic changes are now live.")
    _emit_telemetry()
    return 0


def _emit_telemetry() -> None:
    # Best-effort usage telemetry — never fails the command.
    try:
        import subprocess
        subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "emit_capability.py"),
             "publishing"],
            check=False, capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config()
    if _is_native_config(config):
        return _publish_native(args, config)
    return _publish_classic(config, args.yes)


if __name__ == "__main__":
    sys.exit(main())
