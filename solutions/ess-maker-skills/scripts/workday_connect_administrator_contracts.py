# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Cross-phase administrator evidence contracts for Workday Connect."""

from __future__ import annotations

from typing import Any, Mapping

from workday_connect_contract_common import (
    WorkdayConnectContractError,
    _absolute_https_url,
    _certificate_thumbprint,
    _date_only,
    _https_url,
    _normalized_uri,
    _reject_secret_like_value,
    _require_endpoint_path,
    _safe_nonsecret_text,
    _safe_string_list,
    required_text as _required_text,
)
from workday_connect_entra_contracts import (
    ENTRA_PRESERVATION_OUTCOMES,
    _ENTRA_CHECKS,
    _normalize_entra_check,
)
from workday_connect_model import (
    ADMINISTRATOR_PARTIAL_FIELDS,
    ADMINISTRATOR_PHASES,
    workday_saml_entity_id,
)
from workday_connect_workday_admin_contracts import (
    WORKDAY_API_CLIENT_OUTCOMES,
    WORKDAY_AUTHENTICATION_POLICY_OUTCOMES,
    WORKDAY_DOMAIN_PERMISSION_OUTCOMES,
    WORKDAY_NETWORK_READINESS_OUTCOMES,
    WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES,
    WORKDAY_ROLLOUT_TYPES,
    _optional_domains,
)


def validate_administrator_partial_evidence(
    state: Mapping[str, Any],
    phase_id: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate independent safe fields without discarding sibling values."""
    if phase_id not in ADMINISTRATOR_PHASES:
        raise WorkdayConnectContractError(
            "Administrator partial evidence is supported only for Entra and "
            "Workday administrator phases."
        )
    if not isinstance(fields, Mapping):
        raise WorkdayConnectContractError(
            "Administrator partial evidence fields must contain an object."
        )
    unexpected = sorted(set(fields) - ADMINISTRATOR_PARTIAL_FIELDS[phase_id])
    if unexpected:
        raise WorkdayConnectContractError(
            "Administrator partial evidence contains unsupported fields: "
            + ", ".join(unexpected)
        )
    scope = state.get("scope") or {}
    administrator = ((state.get("phases") or {}).get(phase_id) or {}).get(
        "administrator"
    ) or {}
    available_fields = {
        **dict(administrator.get("partialEvidence") or {}),
        **dict(fields),
    }
    valid_fields: dict[str, Any] = {}
    field_errors: dict[str, str] = {}

    def validate_field(name: str, value: Any) -> Any:
        _reject_secret_like_value(value, name)
        if phase_id == "entra":
            if name == "selectedDirectoryId":
                observed = str(value or "").strip()
                expected = _required_text(
                    scope,
                    "entraTenantId",
                    "Microsoft Entra tenant ID",
                )
                if observed.casefold() != expected.casefold():
                    raise WorkdayConnectContractError(
                        "Selected directory does not match the preflight tenant."
                    )
                return observed
            if name in {
                "applicationId",
                "applicationDisplayName",
                "applicationObjectId",
                "servicePrincipalId",
                "scopeGuid",
                "selectedDirectoryDisplayName",
                "nameIdSource",
                "samlSigningOption",
            }:
                return _safe_nonsecret_text(value, name)
            if name == "applicationIdentifierUris":
                return _safe_string_list(
                    value,
                    "Entra applicationIdentifierUris",
                    allow_empty=False,
                )
            if name == "applicationReplyUrls":
                reply_urls = _safe_string_list(
                    value,
                    "Entra applicationReplyUrls",
                    allow_empty=False,
                )
                return [
                    _absolute_https_url(item, "Entra application Reply URL")
                    for item in reply_urls
                ]
            if name == "entraChecks":
                if not isinstance(value, Mapping):
                    raise WorkdayConnectContractError(
                        "entraChecks must contain an object."
                    )
                unexpected_checks = sorted(set(value) - _ENTRA_CHECKS)
                if unexpected_checks:
                    raise WorkdayConnectContractError(
                        "entraChecks contains unsupported checks: "
                        + ", ".join(unexpected_checks)
                    )
                return {
                    check_name: _normalize_entra_check(
                        check_name,
                        check_value,
                    )
                    for check_name, check_value in value.items()
                }
            if name in {
                "replyUrl",
                "microsoftEntraIdentifier",
                "loginUrl",
            }:
                normalized = _absolute_https_url(value, name)
                tenant_id = _required_text(
                    scope,
                    "entraTenantId",
                    "Microsoft Entra tenant ID",
                )
                expected = {
                    "microsoftEntraIdentifier": (
                        f"https://sts.windows.net/{tenant_id}/"
                    ),
                    "loginUrl": (
                        f"https://login.microsoftonline.com/{tenant_id}/saml2"
                    ),
                }.get(name)
                if expected and _normalized_uri(normalized) != _normalized_uri(
                    expected
                ):
                    raise WorkdayConnectContractError(
                        f"{name} does not match the selected directory."
                    )
                if name == "replyUrl":
                    reply_urls = available_fields.get("applicationReplyUrls")
                    if (
                        isinstance(reply_urls, list)
                        and reply_urls
                        and (
                            _normalized_uri(normalized)
                            not in {_normalized_uri(item) for item in reply_urls}
                        )
                    ):
                        raise WorkdayConnectContractError(
                            "replyUrl is not present in the "
                            "administrator-provided application evidence."
                        )
                return normalized
            if name in {
                "scopePreservationOutcome",
                "authorizedClientPreservationOutcome",
                "permissionPreservationOutcome",
            }:
                normalized = str(value or "").strip()
                if normalized not in ENTRA_PRESERVATION_OUTCOMES:
                    raise WorkdayConnectContractError(
                        f"{name} must be preserved or remediated."
                    )
                return normalized
            if name in {"certificateValidFrom", "certificateValidTo"}:
                return _date_only(str(value or ""), name)
            if name == "certificateThumbprint":
                return _certificate_thumbprint(
                    value,
                    "certificateThumbprint",
                )
            return _safe_nonsecret_text(value, name)

        tenant = _required_text(scope, "workdayTenant", "Workday tenant")
        if name == "enabledServiceProviderId":
            observed = _required_text({name: value}, name, name)
            expected = workday_saml_entity_id(tenant)
            if _normalized_uri(observed) != _normalized_uri(expected):
                raise WorkdayConnectContractError(
                    "Enabled Service Provider ID does not match the Workday tenant."
                )
            return expected
        if name == "oauthTokenUrl":
            normalized = _https_url(value, "Workday OAuth token URL")
            _require_endpoint_path(
                normalized,
                f"/ccx/oauth2/{tenant}/token",
                "Workday OAuth token URL",
            )
            return normalized
        if name == "restBaseUrl":
            normalized = _https_url(value, "Workday REST base URL")
            _require_endpoint_path(
                normalized,
                "/ccx/api",
                "Workday REST base URL",
            )
            return normalized
        if name == "soapBaseUrl":
            normalized = _https_url(value, "Workday SOAP base URL")
            _require_endpoint_path(
                normalized,
                "/ccx/service",
                "Workday SOAP base URL",
            )
            return normalized
        if name == "identityProviderOutcome":
            normalized = str(value or "").strip()
            if normalized != "verified-entra-issuer":
                raise WorkdayConnectContractError(
                    "identityProviderOutcome must verify the Entra issuer."
                )
            return normalized
        if name == "certificateSelectionOutcome":
            normalized = str(value or "").strip()
            if normalized != "entra-signing-certificate-selected":
                raise WorkdayConnectContractError(
                    "certificateSelectionOutcome must verify the Entra "
                    "signing certificate."
                )
            return normalized
        if name == "certificateValidityOutcome":
            normalized = str(value or "").strip()
            if normalized != "matches-verified-entra-certificate":
                raise WorkdayConnectContractError(
                    "certificateValidityOutcome must verify the Entra "
                    "certificate dates."
                )
            return normalized
        if name == "authenticationPolicyOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_AUTHENTICATION_POLICY_OUTCOMES:
                raise WorkdayConnectContractError(
                    "authenticationPolicyOutcome is unsupported."
                )
            return normalized
        if name == "networkReadinessOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_NETWORK_READINESS_OUTCOMES:
                raise WorkdayConnectContractError(
                    "networkReadinessOutcome is unsupported."
                )
            return normalized
        if name == "apiClientOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_API_CLIENT_OUTCOMES:
                raise WorkdayConnectContractError(
                    "apiClientOutcome must verify an approved existing client "
                    "or a newly registered client."
                )
            return normalized
        if name == "clientGrantType":
            normalized = str(value or "").strip().casefold()
            if normalized != "saml-bearer":
                raise WorkdayConnectContractError(
                    "clientGrantType must be saml-bearer."
                )
            return normalized
        if name == "includeWorkdayOwnedScope":
            normalized = str(value or "").strip().casefold()
            if normalized != "yes":
                raise WorkdayConnectContractError(
                    "includeWorkdayOwnedScope must be yes."
                )
            return normalized
        if name in {
            "identityProviderSsoServiceUrl",
            "signOnRedirectUrl",
        }:
            normalized = _absolute_https_url(value, name)
            expected_key = (
                "entraLoginUrl"
                if name == "identityProviderSsoServiceUrl"
                else "replyUrl"
            )
            expected = _required_text(
                state.get("identifiers") or {},
                expected_key,
                expected_key,
            )
            if _normalized_uri(normalized) != _normalized_uri(expected):
                raise WorkdayConnectContractError(
                    f"{name} does not match the verified Entra value."
                )
            return normalized
        if name == "rolloutType":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_ROLLOUT_TYPES:
                raise WorkdayConnectContractError("rolloutType is unsupported.")
            return normalized
        if name in {
            "publicWorkerReportsOutcome",
            "integrationPermissionsGetOutcome",
        }:
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_DOMAIN_PERMISSION_OUTCOMES:
                raise WorkdayConnectContractError(f"{name} must verify Get permission.")
            return normalized
        if name == "functionalAreaScopes":
            supplied = _safe_string_list(
                value,
                "Workday functionalAreaScopes",
                allow_empty=False,
            )
            expected = {
                item.casefold() for item in WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES
            }
            if {item.casefold() for item in supplied} != expected:
                raise WorkdayConnectContractError(
                    "functionalAreaScopes must contain exactly Core Payroll, "
                    "Organizations and Roles, Staffing, and Time Off and "
                    "Leave."
                )
            return list(WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES)
        if name == "optionalDomains":
            return _optional_domains(value)
        return _safe_nonsecret_text(value, name)

    for name, value in fields.items():
        try:
            valid_fields[name] = validate_field(name, value)
        except WorkdayConnectContractError as exc:
            field_errors[name] = str(exc)
    combined = {
        **dict(administrator.get("partialEvidence") or {}),
        **valid_fields,
    }
    if combined.get("rolloutType") == "limited-or-test" and str(
        combined.get("employeeSecurityGroup") or ""
    ).strip().casefold() in {"all employees", "all workers"}:
        valid_fields.pop("employeeSecurityGroup", None)
        field_errors["employeeSecurityGroup"] = (
            "A limited or test rollout cannot use All Employees."
        )
    return {
        "validFields": valid_fields,
        "fieldErrors": field_errors,
    }
