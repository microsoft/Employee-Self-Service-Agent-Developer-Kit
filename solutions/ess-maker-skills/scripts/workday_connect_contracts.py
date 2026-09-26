# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact Entra and Workday administrator contracts for Workday connect."""

from __future__ import annotations

from typing import Any, Mapping

from workday_connect_model import (
    PhaseStatus,
    WorkdayConnectModelError,
    plan_hash,
    workday_saml_entity_id,
)


WORKDAY_CONNECTOR_APP_ID = "4e4707ca-5f53-46a6-a819-f7765446e6ff"
GRAPH_DELEGATED_PERMISSIONS = ("openid", "profile", "User.Read")


class WorkdayConnectContractError(WorkdayConnectModelError):
    """Raised when an exact Entra or Workday contract cannot be produced."""


def _required_text(
    document: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(document.get(key) or "").strip()
    if not value:
        raise WorkdayConnectContractError(f"{label} is required.")
    return value


def _normalized_uri(value: Any) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise WorkdayConnectContractError(
            "Every discovered Entra application must be an object."
        )
    identifier_uris = candidate.get("identifierUris") or []
    if not isinstance(identifier_uris, list):
        raise WorkdayConnectContractError(
            "Discovered Entra identifierUris must be an array."
        )
    return {
        "displayName": _required_text(
            candidate, "displayName", "Entra app display name"
        ),
        "appId": _required_text(candidate, "appId", "Entra app ID"),
        "objectId": _required_text(
            candidate, "objectId", "Entra app object ID"
        ),
        "servicePrincipalId": _required_text(
            candidate,
            "servicePrincipalId",
            "Entra service principal ID",
        ),
        "identifierUris": [
            str(value).strip()
            for value in identifier_uris
            if str(value).strip()
        ],
    }


def _require_preflight(state: Mapping[str, Any]) -> None:
    phases = state.get("phases")
    if not isinstance(phases, Mapping):
        raise WorkdayConnectContractError(
            "Initialize Workday connect before building an Entra plan."
        )
    preflight = phases.get("preflight")
    if (
        not isinstance(preflight, Mapping)
        or preflight.get("status") != PhaseStatus.COMPLETE.value
    ):
        raise WorkdayConnectContractError(
            "Complete Workday preflight before planning Entra changes."
        )


def build_entra_plan(
    state: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one approval-ready Entra plan after exact app discovery."""
    _require_preflight(state)
    if not isinstance(discovery, Mapping):
        raise WorkdayConnectContractError(
            "Entra discovery must contain a JSON object."
        )
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    entity_id = workday_saml_entity_id(tenant)
    entra_tenant_id = _required_text(
        scope, "entraTenantId", "Microsoft Entra tenant ID"
    )
    candidates = [
        _candidate(value) for value in (discovery.get("applications") or [])
    ]
    matches = [
        value
        for value in candidates
        if _normalized_uri(entity_id)
        in {_normalized_uri(uri) for uri in value["identifierUris"]}
    ]
    if len(matches) > 1:
        raise WorkdayConnectContractError(
            "More than one Entra application has the exact Workday SAML "
            "Service Provider ID. Resolve the duplicate before continuing."
        )
    allow_create = discovery.get("allowCreate") is True
    if not matches and not allow_create:
        raise WorkdayConnectContractError(
            "No exact Entra application was found and application creation "
            "was not authorized for planning."
        )

    app = matches[0] if matches else None
    target = (
        {
            "mode": "reuse",
            **app,
        }
        if app
        else {
            "mode": "create",
            "displayName": str(
                discovery.get("newDisplayName") or "Workday (ESS Copilot)"
            ).strip(),
            "galleryTemplate": "Workday",
        }
    )
    app_id_uri = f"api://{app['appId']}" if app else None
    plan = {
        "phase": "entra",
        "scope": {
            "entraTenantId": entra_tenant_id,
            "workdayTenant": tenant,
            "workdaySamlEntityId": entity_id,
        },
        "target": target,
        "identifiers": {
            "workdaySamlEntityId": entity_id,
            "entraAppIdUri": app_id_uri,
        },
        "permissions": {
            "connectorAppId": WORKDAY_CONNECTOR_APP_ID,
            "graphDelegated": list(GRAPH_DELEGATED_PERMISSIONS),
            "scope": "user_impersonation",
        },
        "actions": [
            (
                "Reuse the exact Workday SAML application"
                if app
                else "Instantiate the Workday gallery application"
            ),
            "Configure SAML mode, the signing certificate, and the exact "
            f"Service Provider ID {entity_id}",
            "Expose the user_impersonation scope at the Entra application ID "
            "URI and pre-authorize the Workday connector",
            "Add openid, profile, and User.Read delegated permissions",
            "Grant administrator consent and verify the final configuration",
        ],
    }
    return {**plan, "planHash": plan_hash(plan)}


def build_workday_admin_packet(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one compact handoff packet for the Workday administrator."""
    scope = state.get("scope") or {}
    identifiers = state.get("identifiers") or {}
    endpoints = state.get("endpoints") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    expected_entity_id = workday_saml_entity_id(tenant)
    entity_id = _required_text(
        identifiers,
        "workdaySamlEntityId",
        "Workday SAML Service Provider ID",
    )
    if _normalized_uri(entity_id) != _normalized_uri(expected_entity_id):
        raise WorkdayConnectContractError(
            "The Workday SAML Service Provider ID does not match the selected "
            "Workday tenant."
        )
    entra_app_id_uri = _required_text(
        identifiers,
        "entraAppIdUri",
        "Entra application ID URI",
    )
    if _normalized_uri(entity_id) == _normalized_uri(entra_app_id_uri):
        raise WorkdayConnectContractError(
            "The Workday SAML Service Provider ID and Entra application ID URI "
            "must remain distinct."
        )

    packet = {
        "phase": "workday-admin",
        "scope": {
            "workdayTenant": tenant,
            "workdaySamlEntityId": entity_id,
        },
        "referenceValues": {
            "serviceProviderId": entity_id,
            "entraApplicationIdUri": entra_app_id_uri,
            "oauthTokenUrl": endpoints.get("oauthTokenUrl"),
        },
        "actions": [
            "Confirm the existing enabled SAML identity-provider row belongs "
            "to this tenant before changing it",
            "Upload the active Entra SAML signing certificate",
            f"Set the Workday Service Provider ID to {entity_id}",
            "Enable OAuth 2.0 Clients and SAML in Tenant Setup - Security",
            "Register the signed-in employee API client with the required "
            "functional areas and Include Workday Owned Scope",
            "Verify an active authentication policy allows SAML for the "
            "intended employee population",
        ],
        "responseForm": {
            "required": [
                "enabledServiceProviderId",
                "certificateValidFrom",
                "certificateValidTo",
                "oauthClientId",
                "oauthTokenUrl",
                "authenticationPolicyOutcome",
            ],
            "note": (
                "Return configuration evidence only. Do not paste passwords, "
                "client secrets, tokens, cookies, or certificate private keys."
            ),
        },
    }
    return {**packet, "planHash": plan_hash(packet)}
