# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ESS Solution Installation Validation (ESS-SOLN-xxx)

Verifies that the base ESS declarative agent package is present in the target
Power Platform environment (skill-2 ``install-ess``). The check reads the
Copilot Studio minimalBots ALM configure surface so it works after the
Declarative Agent re-point away from Dataverse solution-table state. Package
presence is proven by ``grsRepositoryId`` + ``commitSha``; package *identity*
(that the committed package is ESS, not some other product) is proven by the
configure ``schemaName`` carrying the ESS token ``copilotforemployeeselfservice``
-- the DA analogue of the CA solution-uniquename prefix
``msdyn_copilotforemployeeselfservice``.
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
from .. import agent_scope
from .da_baseline import manual_evidence_requirement

_ESS_SOLN_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/maker-journey-declarative-agent#install-an-employee-self-service-agent-template"
)
_ESS_SOLN_DESCRIPTION = "ESS base agent package present in the environment"
# The CA check proved ESS identity by the Dataverse solution uniquename prefix
# ``msdyn_copilotforemployeeselfservice``. The DA ALM configure surface exposes
# the committed package's ``schemaName`` (e.g. ``gptagent_copilotforemployee
# selfservicehr`` / ``...it``). The stable identity token shared by both the CA
# and DA schema conventions is ``copilotforemployeeselfservice``; match on it so
# the DA check confirms *which* package is installed, not merely that one exists.
_ESS_SCHEMA_IDENTITY_TOKEN = "copilotforemployeeselfservice"
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
    rows = _check_ess_solution_installed(runner)
    if getattr(runner, "da_full_assessment", False) is True:
        for row in rows:
            if row.status == Status.MANUAL.value:
                row.evidence.update(manual_evidence_requirement(
                    runner, ("packageOrigin", "packageRevision", "sourceArtifact"),
                ))
    return rows


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
            if getattr(runner, "da_full_assessment", False) is True:
                return [_result(
                    Status.MANUAL.value,
                    "The selected agent is not enrolled in ALM; repository provenance was not read.",
                    "Record target-bound package origin and revision evidence. "
                    "Enable ALM only if required by the approved promotion workflow.",
                )]
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
        if getattr(runner, "da_full_assessment", False) is True:
            return [_result(
                Status.BLOCKED.value,
                "ALM repository or commit metadata is unavailable; package provenance was not established.",
                "Obtain target-bound source artifact and revision evidence before accepting package provenance.",
            )]
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

    schema_name = str(config.get("schemaName") or "").strip()
    da_full = getattr(runner, "da_full_assessment", False) is True
    if da_full:
        selected = agent_scope.active_agent(
            getattr(runner, "config", None), getattr(runner, "agent_slug", None),
        )
        expected_schema = str(selected.get("schemaName") or "").strip()
        if not _alm_identity_matches(config, bot_id, realm, expected_schema):
            return [_result(
                Status.BLOCKED.value,
                "ALM metadata did not match the exact selected agent ID, schema and realm.",
                "Refresh the exact native target and resolve the ALM identity mismatch.",
            )]
        if any(
            not isinstance(config.get(key), str) or not config[key].strip()
            for key in ("grsRepositoryId", "commitSha")
        ):
            return [_result(
                Status.BLOCKED.value, "ALM package provenance fields are unavailable or invalid.",
                "Obtain the selected agent's repository and revision evidence before accepting package provenance.",
            )]
    if schema_name:
        if _ESS_SCHEMA_IDENTITY_TOKEN not in schema_name.casefold():
            return [
                _result(
                    Status.FAILED.value,
                    (
                        "AgentBuilder ALM configure returned package schema "
                        f"'{schema_name}', which is not the Employee Self "
                        "Service base package (an ESS agent schema contains "
                        f"'{_ESS_SCHEMA_IDENTITY_TOKEN}'). The agent's "
                        "committed GRS package is a different product."
                    ),
                    (
                        "Point this check's botId at the Employee Self Service "
                        "agent, or install/import the ESS base package for this "
                        "agent, then retry this check."
                    ),
                )
            ]
        result = _result(
                Status.PASSED.value,
                (
                    "Agent runs the ESS base package "
                    f"(schema {schema_name}, GRS repository "
                    f"{grs_repository_id}, commit {commit_sha}); exact "
                    "package revision match pending US 7792604."
                ),
            )
        if da_full:
            result.description = "Selected ESS package metadata"
            result.result = (
                f"Exact selected-agent ALM metadata identifies ESS schema {schema_name}, "
                f"repository {grs_repository_id}, commit {commit_sha}."
            )
            result.evidence = {
                "agentId": bot_id, "agentSchemaName": schema_name, "realm": realm,
                "repositoryId": grs_repository_id, "commitSha": commit_sha,
                "evidenceBoundary": "alm_metadata_not_package_signature_or_employee_execution",
            }
        return [result]

    return [
        _result(
            Status.WARNING.value,
            (
                "Agent has a committed GRS package "
                f"(repository {grs_repository_id}, commit {commit_sha}), but "
                "AgentBuilder ALM configure returned no schemaName, so ESS "
                "base-package identity could not be confirmed (a committed "
                "package of some product exists, but not provably ESS)."
            ),
            (
                "Re-run this read-only check once AgentBuilder ALM configure "
                "returns a schemaName for the agent; if it keeps returning "
                "none, confirm the agent's installed package via Copilot "
                "Studio before relying on ESS base-package presence."
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
    return agent_scope.active_agent_bot_id(
        getattr(runner, "config", None),
        str(getattr(runner, "agent_slug", "") or "").strip() or None,
    )


def _first_present(*values: Any) -> Any:
    """Return the first value that is actually set.

    Presence, not truthiness: an explicit Dev realm ``0`` must win over later
    candidates, which ``a or b`` would drop because ``0`` is falsy. Blank or
    whitespace-only strings are treated as unset so a later candidate supplies
    the realm.
    """
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _alm_realm(runner) -> int | None:
    if getattr(runner, "da_full_assessment", False) is True:
        realm = (getattr(runner, "validation_context", None) or {}).get("realm")
        return _ALM_REALMS.get(realm) if isinstance(realm, str) else None
    config = getattr(runner, "config", None) or {}
    single = config.get("agent") or {}
    raw = _first_present(
        config.get("minimalBotsAlmRealm"),
        config.get("grsRealm"),
        config.get("almRealm"),
        single.get("minimalBotsAlmRealm"),
        single.get("grsRealm"),
        single.get("almRealm"),
        single.get("realm"),
    )
    if raw is None:
        raw = _DEFAULT_ALM_REALM
    return _parse_alm_realm(raw)


def _alm_identity_matches(config: Any, bot_id: str, realm: int, expected_schema: str) -> bool:
    return (
        isinstance(config, dict)
        and isinstance(config.get("cdsBotId"), str)
        and config["cdsBotId"].casefold() == bot_id.casefold()
        and _parse_alm_realm(config.get("realm")) == realm
        and isinstance(expected_schema, str) and bool(expected_schema.strip())
        and isinstance(config.get("schemaName"), str)
        and config["schemaName"].strip().casefold() == expected_schema.strip().casefold()
    )


def _parse_alm_realm(raw: Any) -> int | None:
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
