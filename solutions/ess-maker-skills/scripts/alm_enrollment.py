# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Enable ALM for one exact native agent and verify persisted state."""

from __future__ import annotations

import copy
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderHTTPError,
)


ALM_MARKER = "DA_ALM_ENROLLMENT"
ALM_VERIFY_MARKER = "DA_ALM_ENROLLMENT_VERIFY"
_REDACTED = "[REDACTED]"
_SENSITIVE_FIELD_NAMES = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientassertion",
    "clientsecret",
    "cookie",
    "idtoken",
    "password",
    "refreshtoken",
    "sas",
    "sastoken",
    "secret",
    "setcookie",
    "sharedaccesssignature",
    "subscriptionkey",
    "token",
}
_AUTH_VALUE = re.compile(
    r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]+"
)
_NAMED_SECRET = re.compile(
    r"""(?ix)
    \b(
        authorization
        |access[_-]?token
        |refresh[_-]?token
        |id[_-]?token
        |client[_-]?secret
        |client[_-]?assertion
        |password
        |api[_-]?key
        |subscription[_-]?key
        |sas[_-]?token
    )
    (\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|(?:bearer|basic)\s+[^\s,;]+|[^\s,;]+)
    """
)


class AlmEnrollmentError(RuntimeError):
    """Raised when bounded ALM enrollment cannot preserve its invariants."""


def _normalize_guid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise AlmEnrollmentError(f"{label} must be a GUID.") from exc


def _normalize_environment_id(value: str) -> str:
    candidate = value.strip()
    if candidate.casefold().startswith("default-"):
        candidate = candidate[len("Default-") :]
    return _normalize_guid(candidate, "Environment ID")


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _redact_text(value: str) -> str:
    redacted = _AUTH_VALUE.sub(
        lambda match: f"{match.group(1)} {_REDACTED}",
        value,
    )
    return _NAMED_SECRET.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
        redacted,
    )


def _redact_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if _normalized_field_name(key) in _SENSITIVE_FIELD_NAMES
                else _redact_evidence(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_evidence(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _extract_request_id(response: Any) -> str | None:
    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        return None
    for name in (
        "x-ms-request-id",
        "request-id",
        "x-ms-correlation-request-id",
    ):
        value = headers.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_response_body(response: Any) -> tuple[Any, bool]:
    try:
        return _redact_evidence(response.json()), True
    except ValueError:
        return _redact_text(str(getattr(response, "text", ""))), False


def _service_error_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    error = body.get("error") or body.get("Error")
    if not isinstance(error, dict):
        return None
    code = error.get("code") or error.get("Code")
    return code.strip() if isinstance(code, str) and code.strip() else None


def _exception_chain(error: BaseException) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(
            {
                "type": type(current).__name__,
                "message": _redact_text(str(current)),
            }
        )
        current = current.__cause__ or current.__context__
    return chain


def _emit_annotations(
    annotations: dict[str, Any],
    *,
    marker: str,
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
    marker: str,
) -> None:
    _emit_annotations(annotations, marker=marker)
    suffix = "JSON" if body_is_json else "TEXT"
    rendered = (
        json.dumps(body, ensure_ascii=True)
        if body_is_json
        else str(body)
    )
    print(f"{marker}_RESPONSE_{suffix}:{rendered}")


def _fetched_bot_and_alm_value(
    changeset: dict[str, Any],
    *,
    agent_id: str,
) -> tuple[dict[str, Any], Any]:
    bot = changeset.get("bot")
    if not isinstance(bot, dict):
        raise AlmEnrollmentError(
            "Component fetch did not return a BotEntity; ALM was not changed."
        )
    fetched_agent_id = bot.get("cdsBotId")
    if (
        not isinstance(fetched_agent_id, str)
        or fetched_agent_id.casefold() != agent_id.casefold()
    ):
        raise AlmEnrollmentError(
            "The fetched BotEntity identity does not match the requested "
            "agent; ALM was not changed."
        )
    configuration = bot.get("configuration")
    if not isinstance(configuration, dict):
        raise AlmEnrollmentError(
            "The fetched BotEntity has no usable configuration; "
            "ALM was not changed."
        )
    settings = configuration.get("settings")
    if settings is not None and not isinstance(settings, dict):
        raise AlmEnrollmentError(
            "The fetched BotEntity settings are not an object; "
            "ALM was not changed."
        )
    copied_bot = copy.deepcopy(bot)
    alm_value = (
        settings.get("alm.isAlmEnabled")
        if settings is not None
        else None
    )
    return copied_bot, alm_value


def _fetch_alm_components(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    verification: bool,
) -> dict[str, Any]:
    marker = ALM_VERIFY_MARKER if verification else ALM_MARKER
    phase = "verification" if verification else "precondition"
    try:
        return client.fetch_components(agent_id)
    except AgentBuilderHTTPError as exc:
        annotations: dict[str, Any] = {
            "targetEnvironmentId": environment_id,
            "agentId": agent_id,
            "outcome": f"{phase}-rejected",
            "httpStatus": exc.status_code,
            "errorCode": exc.error_code,
            "requestId": exc.request_id,
        }
        if exc.response is None:
            _emit_annotations(annotations, marker=marker)
        else:
            body, body_is_json = _parse_response_body(exc.response)
            _print_evidence(
                annotations,
                body,
                body_is_json,
                marker=marker,
            )
        raise AlmEnrollmentError(
            f"The ALM {phase} fetch was rejected by the service. "
            + (
                "Verification did not complete."
                if verification
                else "ALM was not changed."
            )
        ) from exc
    except (requests.exceptions.RequestException, OSError) as exc:
        annotations = {
            "targetEnvironmentId": environment_id,
            "agentId": agent_id,
            "outcome": f"{phase}-transport-failure",
            "transportErrorType": type(exc).__name__,
            "transportError": _redact_text(str(exc)),
            "transportErrorChain": _exception_chain(exc),
        }
        _emit_annotations(annotations, marker=marker)
        raise AlmEnrollmentError(
            f"The ALM {phase} fetch ended without a response. "
            + (
                "Verification did not complete."
                if verification
                else "No update was attempted."
            )
        ) from exc


def ensure_alm(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Enable ALM through one fetched-BotEntity update and verify read-back."""
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
        annotations["transportError"] = _redact_text(str(exc))
        annotations["transportErrorChain"] = _exception_chain(exc)
        _emit_annotations(annotations, marker=ALM_MARKER)
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
        persisted = persisted_value is True
        result = {
            "environmentId": normalized_environment_id,
            "agentId": normalized_agent_id,
            "outcome": "enabled" if persisted else "uncertain",
            "updateOutcome": "uncertain-transport",
            "beforeBotVersion": before_version,
            "afterBotVersion": after_bot.get("version"),
            "previousValue": previous_value,
            "persistedValue": persisted,
        }
        print(
            f"{ALM_VERIFY_MARKER}_JSON:"
            f"{json.dumps(result, ensure_ascii=True)}"
        )
        if persisted:
            return result
        raise AlmEnrollmentError(
            "The ALM update ended without a classified response. "
            "Read-back did not establish that the setting persisted, so "
            "the outcome remains uncertain."
        ) from exc

    status = response.status_code
    annotations["httpStatus"] = status
    annotations["requestId"] = _extract_request_id(response)
    body, body_is_json = _parse_response_body(response)
    error_code = _service_error_code(body)
    if error_code is not None:
        annotations["errorCode"] = error_code
    if not 200 <= status < 300:
        annotations["outcome"] = "rejected"
        _print_evidence(
            annotations,
            body,
            body_is_json,
            marker=ALM_MARKER,
        )
        raise AlmEnrollmentError(
            f"The service rejected the ALM update (HTTP {status}). "
            "No component changes were requested."
        )

    annotations["outcome"] = "update-accepted"
    _print_evidence(
        annotations,
        body,
        body_is_json,
        marker=ALM_MARKER,
    )
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
            f"{ALM_VERIFY_MARKER}_JSON:"
            f"{json.dumps(result, ensure_ascii=True)}"
        )
        raise AlmEnrollmentError(
            "The ALM update was accepted, but read-back did not show "
            "`alm.isAlmEnabled: true`. Do not continue to attachment."
        )
    return result
