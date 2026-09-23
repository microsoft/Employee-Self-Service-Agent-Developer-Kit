# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ESS Solution Installation Validation (ESS-SOLN-xxx)

Verifies that the base ESS declarative agent package is present in the target
Power Platform environment (skill-2 ``install-ess``). The check reads the
Copilot Studio minimalBots ALM configure surface so it works after the
Declarative Agent re-point away from Dataverse solution-table state.
"""

from __future__ import annotations

from typing import Any

from agentbuilder import (
    DEV_REALM,
    PROD_REALM,
    REALM_NAMES,
    TEST_REALM,
    AgentBuilderHTTPError,
)

from ..runner import CheckResult, Priority, Role, Status

_ESS_SOLN_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install"
)
_ESS_SOLN_DESCRIPTION = "ESS base agent package present in the environment"
_DEFAULT_ALM_REALM = DEV_REALM
_ALM_NOT_OPTED_IN_ERROR_CODE = "4003"
_ALM_REALMS = {
    "dev": DEV_REALM,
    "development": DEV_REALM,
    "test": TEST_REALM,
    "prod": PROD_REALM,
    "production": PROD_REALM,
}


def run_solution_checks(runner) -> list[CheckResult]:
    """Emit the ESS-SOLN-xxx solution-installation checkpoints.

    Currently a single check (``ESS-SOLN-001``); kept as a category function so
    additional ESS-SOLN-* rows can be added without changing the registry /
    cli wiring.
    """
    return _check_ess_solution_installed(runner)


def _check_ess_solution_installed(runner) -> list[CheckResult]:
    """ESS-SOLN-001: the base ESS agent package is installed in the target env."""
    agentbuilder = getattr(runner, "agentbuilder", None)
    bot_id = _active_agent_bot_id(runner)
    realm = _alm_realm(runner)

    if agentbuilder is None:
        return [
            _result(
                Status.SKIPPED.value,
                "AgentBuilder client not available in this run.",
                (
                    "Run FlightCheck with native AgentBuilder authentication "
                    "configured, then retry this check."
                ),
            )
        ]
    if not bot_id:
        return [
            _result(
                Status.SKIPPED.value,
                "No agent botId is recorded in .local/config.json.",
                "Run setup so the agent botId is recorded, then retry this check.",
            )
        ]
    if realm is None:
        return [
            _result(
                Status.FAILED.value,
                "The configured ALM realm is not Dev, Test, or Prod.",
                (
                    "Set almRealm, grsRealm, or minimalBotsAlmRealm to Dev, "
                    "Test, or Prod, then retry this check."
                ),
            )
        ]

    try:
        config = agentbuilder.get_realm_configuration(bot_id, realm)
    except AgentBuilderHTTPError as exc:
        if _is_not_opted_into_alm_error(exc):
            return [_not_opted_into_alm_result(bot_id)]
        return [
            _result(
                Status.WARNING.value,
                (
                    "Unable to verify ESS package state from AgentBuilder ALM "
                    f"configure: {exc}"
                ),
                (
                    "Retry the read-only ALM configure check after verifying "
                    "Copilot Studio AgentBuilder access and service availability."
                ),
            )
        ]
    except Exception as exc:
        return [
            _result(
                Status.WARNING.value,
                (
                    "Unable to verify ESS package state from AgentBuilder ALM "
                    f"configure: {type(exc).__name__}: {exc}"
                ),
                (
                    "Retry the read-only ALM configure check after verifying "
                    "Copilot Studio AgentBuilder access and service availability."
                ),
            )
        ]

    grs_repository_id = str(config.get("grsRepositoryId") or "").strip()
    commit_sha = str(config.get("commitSha") or "").strip()
    if not grs_repository_id or not commit_sha:
        return [
            _result(
                Status.FAILED.value,
                (
                    "AgentBuilder ALM configure did not return both "
                    "grsRepositoryId and commitSha. The ESS base package is "
                    "not present in the agent's GRS package state."
                ),
                (
                    "Install or import the Employee Self Service base package "
                    "for this agent, confirm the ALM configure response has "
                    "a repository and commit, then retry this check."
                ),
            )
        ]

    return [
        _result(
            Status.PASSED.value,
            (
                "Agent has a committed GRS package "
                f"(repository {grs_repository_id}, commit {commit_sha}); "
                "ESS base-package identity match pending US 7792604."
            ),
        )
    ]


def _result(
    status: str,
    result: str,
    remediation: str = "",
) -> CheckResult:
    return CheckResult(
        checkpoint_id="ESS-SOLN-001",
        category="Solution",
        priority=Priority.CRITICAL.value,
        status=status,
        description=_ESS_SOLN_DESCRIPTION,
        result=result,
        remediation=remediation,
        doc_link=_ESS_SOLN_DOC_LINK,
        roles=[Role.ESS_MAKER.value],
    )


def _active_agent_bot_id(runner) -> str | None:
    config = getattr(runner, "config", None) or {}
    agents = config.get("agents") or []
    active_slug = config.get("activeAgent") or (config.get("agent") or {}).get(
        "slug"
    )
    if active_slug:
        for agent in agents:
            if isinstance(agent, dict) and agent.get("slug") == active_slug:
                bot_id = str(agent.get("botId") or "").strip()
                if bot_id:
                    return bot_id
    single = config.get("agent") or {}
    bot_id = str(single.get("botId") or "").strip()
    if bot_id:
        return bot_id
    for agent in agents:
        if isinstance(agent, dict):
            bot_id = str(agent.get("botId") or "").strip()
            if bot_id:
                return bot_id
    return None


def _alm_realm(runner) -> int | None:
    config = getattr(runner, "config", None) or {}
    single = config.get("agent") or {}
    raw = (
        config.get("minimalBotsAlmRealm")
        or config.get("grsRealm")
        or config.get("almRealm")
        or single.get("minimalBotsAlmRealm")
        or single.get("grsRealm")
        or single.get("almRealm")
        or single.get("realm")
        or _DEFAULT_ALM_REALM
    )
    if type(raw) is int and raw in REALM_NAMES:
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            realm = int(text)
            return realm if realm in REALM_NAMES else None
        return _ALM_REALMS.get(text.casefold())
    return None


def _is_not_opted_into_alm_error(error: AgentBuilderHTTPError) -> bool:
    if _error_code_matches(getattr(error, "error_code", None)):
        return True
    response = getattr(error, "response", None)
    if response is None:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return _payload_is_not_opted_into_alm(body)


def _payload_is_not_opted_into_alm(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    candidates = [
        payload.get("ErrorCode"),
        payload.get("errorCode"),
        payload.get("code"),
    ]
    for key in ("error", "Error"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.extend(
                [nested.get("code"), nested.get("Code"), nested.get("ErrorCode")]
            )
        else:
            candidates.append(nested)
    return any(_error_code_matches(candidate) for candidate in candidates)


def _error_code_matches(value: Any) -> bool:
    return str(value).strip() == _ALM_NOT_OPTED_IN_ERROR_CODE


def _not_opted_into_alm_result(bot_id: str) -> CheckResult:
    return _result(
        Status.NOT_CONFIGURED.value,
        (
            f"Agent {bot_id} is not opted into ALM. AgentBuilder ALM configure "
            "returned error code 4003, so FlightCheck cannot read its GRS "
            "package state."
        ),
        (
            "Opt the agent into Application Lifecycle Management (ALM) in "
            "Copilot Studio, then retry this check."
        ),
    )
