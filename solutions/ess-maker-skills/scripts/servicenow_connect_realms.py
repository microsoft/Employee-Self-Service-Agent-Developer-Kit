# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Promoted Test and Prod realm support for ServiceNow Connect.

Discovery proves the exact sibling realm of the recorded Dev agent through
AgentBuilder. The registry records one verified target per realm, the values
its connection is expected to use, and the three target-specific stages:
Connections, Runtime configuration, and Maker validation. Each realm is
checked on its own: the Dev lifecycle record is only an optional reference
for the expected values. This module never mutates an agent; the controller
supplies live component and connection reads.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from agentbuilder import (
    DEV_REALM,
    PROD_REALM,
    REALM_NAMES,
    TEST_REALM,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate_agent_inventory,
    derive_environment_host,
    list_environments,
)
from connect_lifecycle import (
    STATE_INTEGRITY_KEY,
    state_integrity_digest,
    state_integrity_mismatch,
)

REGISTRY_SCHEMA_VERSION = 1
REALM_VALUES = {"dev": DEV_REALM, "test": TEST_REALM, "prod": PROD_REALM}
PROMOTED_REALMS = ("test", "prod")
STAGES = (
    ("connections", "Connections"),
    ("runtime-configuration", "Runtime configuration"),
    ("maker-validation", "Maker validation"),
)
STAGE_IDS = tuple(stage_id for stage_id, _label in STAGES)
TARGET_IDENTITY_FIELDS = (
    "environmentId",
    "environmentUrl",
    "tenantId",
    "agentId",
    "agentSchemaName",
    "almFamilyId",
    "commitSha",
    "sourceAgentId",
)
EXPECTED_AUTH_MODE = "entraIDUserLogin"
EXPECTED_KEYS = ("instanceName", "clientId")
EXPECTED_LABELS = {
    "instanceName": "ServiceNow instance",
    "clientId": "Entra application (client) ID",
}


class ServiceNowRealmError(RuntimeError):
    """Raised when a promoted target cannot be proven or used safely."""

    customer_remediation = (
        "Your existing ServiceNow setup progress is preserved. Confirm that "
        "promotion finished, then check again or choose the target "
        "environment by name or Dataverse URL using the recorded maker "
        "account."
    )

    def __init__(self, message: str, *, remediation: str | None = None) -> None:
        super().__init__(message)
        if remediation is not None:
            self.customer_remediation = remediation


def _access_failure(
    exc: Exception,
    realm: str | None,
    unproven: str,
) -> ServiceNowRealmError:
    """Split a denied read from one that could not be verified.

    A missing agent (404) is a target problem, not an access problem, so it
    keeps the caller's `unproven` message.
    """
    label = str(realm).title() if realm else "the promoted environment"
    status = getattr(exc, "status_code", None)
    if status == 404:
        return ServiceNowRealmError(unproven)
    if status in (401, 403):
        return ServiceNowRealmError(
            f"Your account doesn't have the required access to configure this "
            f"agent in {label}.",
            remediation=(
                "Ask a maker with the Environment Maker role and permission to "
                "edit this agent to run `/connect servicenow` using their own "
                "account. Your existing ServiceNow setup progress is preserved."
            ),
        )
    return ServiceNowRealmError(
        f"We couldn't verify whether your account can configure this agent in "
        f"{label}. Validation is paused; this doesn't mean your access was "
        "denied.",
        remediation=(
            "Retry the permission check to continue. If it keeps failing, confirm that "
            "promotion finished or choose the environment by name or "
            "Dataverse URL. Your existing ServiceNow setup progress is "
            "preserved."
        ),
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _guid(value: Any, label: str) -> str:
    try:
        return str(uuid.UUID(str(value or "")))
    except ValueError as exc:
        raise ServiceNowRealmError(f"{label} must be a GUID.") from exc


def _matches_realm(value: Any, realm: int) -> bool:
    return (
        type(value) is int
        and value == realm
        or isinstance(value, str)
        and value.casefold() == REALM_NAMES[realm].casefold()
    )


def _environment_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ServiceNowRealmError(
            "The target Dataverse environment URL must be a safe HTTPS URL."
        )
    return f"https://{parsed.hostname.casefold()}"


def _agent_id(agent: Mapping[str, Any], label: str) -> str:
    return _guid(
        agent.get("botId") or agent.get("cdsBotId") or agent.get("id"),
        label,
    )


def _inventory_environment(
    environment: Mapping[str, Any],
) -> tuple[str, str, str] | None:
    """Return (id, Dataverse URL, display name) or None when unusable."""
    raw_id = str(
        environment.get("id") or environment.get("environmentId") or ""
    ).strip()
    try:
        environment_id = str(uuid.UUID(raw_id))
    except ValueError:
        return None
    properties = environment.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    linked = properties.get("linkedEnvironmentMetadata")
    linked = linked if isinstance(linked, Mapping) else {}
    url = str(
        environment.get("url")
        or environment.get("instanceUrl")
        or linked.get("instanceApiUrl")
        or linked.get("instanceUrl")
        or ""
    ).strip()
    try:
        url = _environment_url(url)
    except ServiceNowRealmError:
        return None
    name = str(
        environment.get("displayName")
        or environment.get("name")
        or properties.get("displayName")
        or properties.get("environmentName")
        or ""
    ).strip()
    return environment_id, url, name


def _environment_candidates(
    environments: list[dict[str, Any]],
    selector: str | None,
) -> list[tuple[str, str, str]]:
    wanted = str(selector or "").strip().casefold()
    candidates: list[tuple[str, str, str]] = []
    for environment in environments:
        entry = _inventory_environment(environment)
        if entry is None:
            continue
        environment_id, url, name = entry
        if wanted and wanted not in {
            environment_id.casefold(),
            url.casefold(),
            name.casefold(),
        }:
            continue
        candidates.append(entry)
    ids = [entry[0] for entry in candidates]
    if len(ids) != len(set(ids)):
        raise ServiceNowRealmError(
            "Environment inventory returned duplicate records for one "
            "environment ID. Check again after the inventory issue is "
            "resolved."
        )
    return candidates


def discover_realm_target(
    source_client: Any,
    target_client: Any,
    *,
    source_agent_id: str,
    expected_schema_name: str,
    realm: str,
    environment_id: str,
    environment_url: str,
    expected_source_family_id: str = "",
    expected_target_agent_id: str = "",
) -> dict[str, str]:
    """Prove the exact sibling realm of the recorded Dev agent."""
    realm_name = str(realm or "").casefold()
    if realm_name not in PROMOTED_REALMS:
        raise ServiceNowRealmError("Promoted target discovery supports Test or Prod.")
    realm_value = REALM_VALUES[realm_name]
    label = REALM_NAMES[realm_value]
    source_id = _guid(source_agent_id, "Recorded Dev agent ID")

    realms = source_client.get_realms(source_id)
    if not _matches_realm(realms.get("routeRealm"), DEV_REALM):
        raise ServiceNowRealmError(
            "The recorded ServiceNow source agent is not the Dev realm."
        )
    direct_source = source_client.get_agent(source_id)
    if _agent_id(direct_source, "Direct Dev agent ID").casefold() != (
        source_id.casefold()
    ):
        raise ServiceNowRealmError(
            "Direct Dev lookup returned a different agent identity."
        )
    siblings = realms.get("siblingRealms")
    if not isinstance(siblings, list):
        raise ServiceNowRealmError(
            "Agent realm discovery did not return sibling realms."
        )
    matches = [
        sibling
        for sibling in siblings
        if isinstance(sibling, Mapping)
        and _matches_realm(sibling.get("realm"), realm_value)
    ]
    if not matches:
        raise ServiceNowRealmError(f"The {label} promotion is not visible yet.")
    if len(matches) != 1:
        raise ServiceNowRealmError(
            f"Agent realm discovery returned multiple {label} targets."
        )
    target_id = _guid(matches[0].get("botId"), f"Related {label} agent ID")
    if (
        expected_target_agent_id
        and target_id.casefold() != expected_target_agent_id.casefold()
    ):
        raise ServiceNowRealmError(
            f"The supplied agent link is not the {label} promotion of the "
            "recorded Dev agent."
        )

    source_configuration = source_client.get_realm_configuration(
        source_id,
        DEV_REALM,
    )
    if not _matches_realm(source_configuration.get("realm"), DEV_REALM):
        raise ServiceNowRealmError(
            "The recorded source configuration is not the Dev realm."
        )
    if (
        _guid(
            source_configuration.get("cdsBotId"),
            "Configured Dev agent ID",
        ).casefold()
        != source_id.casefold()
    ):
        raise ServiceNowRealmError(
            "Dev realm configuration returned a different agent identity."
        )
    family_id = str(source_configuration.get("grsRepositoryId") or "").strip()
    if not family_id:
        raise ServiceNowRealmError(
            "Dev realm configuration did not return an ALM-family identity."
        )
    if (
        expected_source_family_id
        and family_id.casefold() != expected_source_family_id.casefold()
    ):
        raise ServiceNowRealmError(
            "The recorded Dev target belongs to a different ALM family."
        )
    source_schema = (
        str(
            source_configuration.get("schemaName")
            or direct_source.get("schemaName")
            or ""
        )
        .strip()
        .casefold()
    )
    if source_schema != expected_schema_name.casefold():
        raise ServiceNowRealmError(
            "The recorded Dev source is not the supported ESS agent for "
            "this ServiceNow product."
        )

    direct_target = target_client.get_agent(target_id)
    if _agent_id(direct_target, f"Direct {label} agent ID").casefold() != (
        target_id.casefold()
    ):
        raise ServiceNowRealmError(
            f"Direct {label} lookup returned a different agent identity."
        )
    target_configuration = target_client.get_realm_configuration(
        target_id,
        realm_value,
    )
    if not _matches_realm(target_configuration.get("realm"), realm_value):
        raise ServiceNowRealmError(
            f"Target configuration did not identify the {label} realm."
        )
    if (
        _guid(
            target_configuration.get("cdsBotId"),
            f"Configured {label} agent ID",
        ).casefold()
        != target_id.casefold()
    ):
        raise ServiceNowRealmError(
            f"{label} configuration returned a different agent identity."
        )
    target_family = str(target_configuration.get("grsRepositoryId") or "").strip()
    if target_family.casefold() != family_id.casefold():
        raise ServiceNowRealmError(
            "The promoted target belongs to a different ALM family."
        )
    schema_name = str(
        target_configuration.get("schemaName") or direct_target.get("schemaName") or ""
    ).strip()
    if schema_name.casefold() not in {
        source_schema,
        f"{source_schema}_{realm_name}",
    }:
        raise ServiceNowRealmError(
            "The promoted target is not the supported ESS agent for this "
            "ServiceNow product."
        )
    commit_sha = str(target_configuration.get("commitSha") or "").strip()
    if not commit_sha:
        raise ServiceNowRealmError(
            "The promoted target does not have deployed package evidence."
        )
    if (
        str(source_client.tenant_id).casefold()
        != str(target_client.tenant_id).casefold()
    ):
        raise ServiceNowRealmError(
            "The Dev and promoted target environments belong to different "
            "Microsoft Entra tenants."
        )
    return {
        "environmentId": _guid(environment_id, "Target environment ID"),
        "environmentUrl": _environment_url(environment_url),
        "tenantId": str(target_client.tenant_id),
        "agentId": target_id,
        "agentSchemaName": schema_name,
        "almFamilyId": target_family,
        "commitSha": commit_sha,
        "sourceAgentId": source_id,
    }


def discover_promoted_realm(
    *,
    realm: str,
    source_client: Any,
    client_factory: Callable[..., Any],
    environments: list[dict[str, Any]],
    ring: str,
    token: str,
    tenant_id: str,
    api_version: str,
    source_agent_id: str,
    expected_schema_name: str,
    environment_selector: str | None = None,
    expected_source_family_id: str = "",
) -> dict[str, str]:
    """Find the one environment that holds the verified sibling realm."""
    candidates = _environment_candidates(environments, environment_selector)
    explicit = bool(str(environment_selector or "").strip())
    labels = ", ".join(
        sorted(
            {name or url for _id, url, name in candidates},
            key=str.casefold,
        )
    )
    if not candidates:
        raise ServiceNowRealmError(
            "The promoted target environment is not visible. Confirm maker "
            "access or select the environment by name or URL."
        )
    discovered: list[dict[str, str]] = []
    try:
        for candidate_id, candidate_url, _name in candidates:
            target_client = client_factory(
                derive_environment_host(candidate_id, ring),
                token,
                ring=ring,
                tenant_id=tenant_id,
                api_version=api_version,
            )
            try:
                discovered.append(
                    discover_realm_target(
                        source_client,
                        target_client,
                        source_agent_id=source_agent_id,
                        expected_schema_name=expected_schema_name,
                        realm=realm,
                        environment_id=candidate_id,
                        environment_url=candidate_url,
                        expected_source_family_id=expected_source_family_id,
                    )
                )
            except AgentBuilderHTTPError as exc:
                if not explicit and exc.status_code == 404:
                    continue
                raise
    except AgentBuilderError as exc:
        raise _access_failure(
            exc,
            realm,
            "The promoted target could not be verified. Confirm maker "
            "access, environment selection, and deployment state.",
        ) from exc
    if len(discovered) != 1:
        detail = (
            " More than one environment matched the promoted agent."
            if discovered
            else " No matching promoted agent was found in the checked environments."
        )
        choices = f" Available environments: {labels}." if labels else ""
        raise ServiceNowRealmError(
            "Automatic promoted-target discovery could not identify one "
            f"{str(realm).title()} environment.{detail}{choices} Select the "
            "environment by name or URL and retry."
        )
    return discovered[0]


def parse_agent_link(agent_link: str) -> dict[str, str]:
    """Extract the environment, agent, and ring from a Copilot Studio link."""
    from setup_existing_da import ExistingDASetupError, parse_da_target_url

    try:
        parsed = parse_da_target_url(agent_link)
    except ExistingDASetupError as exc:
        raise ServiceNowRealmError(
            "Paste the full Copilot Studio link for the Test or Prod agent."
        ) from exc
    if (
        parsed.get("source") != "copilot-studio-url"
        or not parsed.get("environmentId")
        or not parsed.get("agentId")
        or not parsed.get("ring")
    ):
        raise ServiceNowRealmError(
            "Paste the full Copilot Studio link for the Test or Prod agent. "
            "The link must include both the environment and agent."
        )
    return parsed


def discover_from_agent_link(
    *,
    agent_link: str,
    realm: str | None,
    source_client: Any,
    client_factory: Callable[..., Any],
    environments: list[dict[str, Any]],
    ring: str,
    token: str,
    tenant_id: str,
    api_version: str,
    source_agent_id: str,
    expected_schema_name: str,
    expected_source_family_id: str = "",
) -> tuple[str, dict[str, str]]:
    """Verify a supplied Test or Prod link as the promoted Dev sibling."""
    parsed = parse_agent_link(agent_link)
    if parsed["ring"] != ring:
        raise ServiceNowRealmError(
            "This agent link points to a different Copilot Studio ring than "
            "the recorded Dev agent."
        )
    agent_id = parsed["agentId"]
    if agent_id.casefold() == _guid(source_agent_id, "Dev agent ID").casefold():
        raise ServiceNowRealmError(
            "This link is the Dev agent. Paste the Test or Prod agent link, "
            "or say the agent was promoted and we'll find it."
        )
    candidates = [
        entry
        for entry in _environment_candidates(environments, parsed["environmentId"])
    ]
    if not candidates:
        raise ServiceNowRealmError(
            "The environment in this agent link is not visible to the "
            "recorded maker account."
        )
    environment_id, environment_url, _name = candidates[0]
    realm_name: str | None = None
    try:
        target_client = client_factory(
            derive_environment_host(environment_id, ring),
            token,
            ring=ring,
            tenant_id=tenant_id,
            api_version=api_version,
        )
        route_realm = target_client.get_realms(agent_id).get("routeRealm")
        realm_name = next(
            (
                name
                for name in PROMOTED_REALMS
                if _matches_realm(route_realm, REALM_VALUES[name])
            ),
            None,
        )
        if realm_name is None:
            raise ServiceNowRealmError(
                "This link is not a Test or Prod agent, so it cannot be "
                "used here. Paste the promoted agent link."
            )
        if realm and realm.casefold() != realm_name:
            raise ServiceNowRealmError(
                f"This link is the {realm_name.title()} agent, not {realm.title()}."
            )
        return realm_name, discover_realm_target(
            source_client,
            target_client,
            source_agent_id=source_agent_id,
            expected_schema_name=expected_schema_name,
            realm=realm_name,
            environment_id=environment_id,
            environment_url=environment_url,
            expected_source_family_id=expected_source_family_id,
            expected_target_agent_id=agent_id,
        )
    except AgentBuilderError as exc:
        raise _access_failure(
            exc,
            realm_name or realm,
            "The agent link could not be verified as the promoted sibling "
            "of the recorded Dev agent. Confirm maker access and that "
            "promotion finished.",
        ) from exc


def discover_realm(
    *,
    root: Path,
    ring: str,
    tenant_id: str,
    source_host: str,
    api_version: str,
    source_agent_id: str,
    expected_schema_name: str,
    realm: str | None = None,
    environment_selector: str | None = None,
    agent_link: str | None = None,
    account_hint: str | None = None,
    expected_source_family_id: str = "",
    authenticator: Callable[..., tuple[str, str]] = authenticate_agent_inventory,
    client_factory: Callable[..., Any] = AgentBuilderClient,
    environment_loader: Callable[..., list[dict[str, Any]]] = list_environments,
) -> tuple[str, dict[str, str]]:
    """Discover the promoted sibling by agent link or automatic proof."""
    try:
        token, signed_in_tenant = authenticator(
            ring,
            account_hint=account_hint,
            cache_path=Path(root).resolve()
            / ".local"
            / ".agentbuilder_token_cache.bin",
        )
        if str(signed_in_tenant).casefold() != str(tenant_id).casefold():
            raise ServiceNowRealmError(
                "The signed-in Microsoft Entra tenant does not match the "
                "recorded Dev target."
            )
        environments = environment_loader(
            token,
            ring,
            api_version=api_version,
        )
        source_client = client_factory(
            source_host,
            token,
            ring=ring,
            tenant_id=signed_in_tenant,
            api_version=api_version,
        )
        common = {
            "source_client": source_client,
            "client_factory": client_factory,
            "environments": environments,
            "ring": ring,
            "token": token,
            "tenant_id": signed_in_tenant,
            "api_version": api_version,
            "source_agent_id": source_agent_id,
            "expected_schema_name": expected_schema_name,
            "expected_source_family_id": expected_source_family_id,
        }
        if agent_link:
            return discover_from_agent_link(
                agent_link=agent_link,
                realm=realm,
                **common,
            )
        if realm not in PROMOTED_REALMS:
            raise ServiceNowRealmError("Realm must be test or prod.")
        return realm, discover_promoted_realm(
            realm=realm,
            environment_selector=environment_selector,
            **common,
        )
    except ServiceNowRealmError:
        raise
    except (AgentBuilderError, OSError, ValueError) as exc:
        raise _access_failure(
            exc,
            realm,
            "The promoted target could not be verified. Confirm maker "
            "access, environment selection, and deployment state.",
        ) from exc


def registry_path(root: Path, provider: str, agent_slug: str) -> Path:
    return (
        Path(root)
        / ".local"
        / "connect"
        / provider
        / "agents"
        / agent_slug
        / "realms.json"
    )


def new_registry(provider: str, agent_slug: str) -> dict[str, Any]:
    return {
        "schemaVersion": REGISTRY_SCHEMA_VERSION,
        "provider": provider,
        "agentSlug": agent_slug,
        "activeTargetRealm": "dev",
        "targets": {},
    }


def load_registry(root: Path, provider: str, agent_slug: str) -> dict[str, Any]:
    path = registry_path(root, provider, agent_slug)
    if not path.is_file():
        return new_registry(provider, agent_slug)
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceNowRealmError(
            "The Test/Prod realm record could not be read."
        ) from exc
    if (
        not isinstance(registry, dict)
        or registry.get("schemaVersion") != REGISTRY_SCHEMA_VERSION
        or registry.get("provider") != provider
        or registry.get("agentSlug") != agent_slug
        or not isinstance(registry.get("targets"), dict)
        or state_integrity_mismatch(registry)
    ):
        raise ServiceNowRealmError(
            "The Test/Prod realm record was modified outside the Connect "
            "controller. Ask the maker to approve deleting realms.json for "
            "this agent, then discover the realm again."
        )
    return registry


def save_registry(root: Path, registry: dict[str, Any]) -> None:
    path = registry_path(root, registry["provider"], registry["agentSlug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["updatedAt"] = _utc_now()
    registry[STATE_INTEGRITY_KEY] = state_integrity_digest(registry)
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix="realms.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(registry, stream, indent=2, sort_keys=True)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def dev_reference_from_state(state: Mapping[str, Any]) -> dict[str, str]:
    """Read whatever the Dev lifecycle recorded; every value is optional."""
    setup = state.get("adminSetup")
    setup = setup if isinstance(setup, Mapping) else {}
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, Mapping) else {}
    handoffs = setup.get("phaseHandoffs")
    handoffs = handoffs if isinstance(handoffs, Mapping) else {}
    entra = handoffs.get("entra-registration")
    entra = entra if isinstance(entra, Mapping) else {}
    evidence = entra.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    reference = {
        "instanceName": _normalize_instance(preflight.get("instanceName")),
        # Only an administrator-confirmed registration is reliable evidence.
        "clientId": (
            str(evidence.get("clientId") or "").strip().casefold()
            if entra.get("status") in ("completed", "reused")
            else ""
        ),
        "tenantId": str(state.get("tenantId") or "").strip().casefold(),
    }
    return {key: value for key, value in reference.items() if value}


def _normalize_instance(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.removeprefix("https://").removesuffix("/")
    return text.removesuffix(".service-now.com")


def _normalize_provided(provided: Mapping[str, Any] | None) -> dict[str, str]:
    provided = provided or {}
    values: dict[str, str] = {}
    instance = _normalize_instance(provided.get("instanceName"))
    if instance:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", instance):
            raise ServiceNowRealmError(
                "The ServiceNow instance must be the instance name, for "
                "example contoso, or its service-now.com address."
            )
        values["instanceName"] = instance
    if str(provided.get("clientId") or "").strip():
        values["clientId"] = _guid(
            provided["clientId"],
            "The Entra application (client) ID",
        ).casefold()
    return values


def resolve_expected(
    identity: Mapping[str, str],
    *,
    dev_reference: Mapping[str, str] | None,
    previous: Mapping[str, Any] | None,
    provided: Mapping[str, Any] | None,
    admin_confirmed: bool,
) -> dict[str, Any]:
    """Decide what this realm's connection is expected to use.

    Each value comes from the maker (provided), then the value already
    recorded for this realm, then the Dev record as an optional reference.
    Values the maker supplied need the ServiceNow administrator's
    confirmation before they are trusted.
    """
    reference = dict(dev_reference or {})
    reference_tenant = reference.pop("tenantId", "")
    if (
        reference_tenant
        and reference_tenant != str(identity.get("tenantId") or "").casefold()
    ):
        reference = {}
    given = _normalize_provided(provided)
    prior = previous if isinstance(previous, Mapping) else {}
    prior_values = (
        prior.get("values") if isinstance(prior.get("values"), Mapping) else {}
    )
    prior_sources = (
        prior.get("sources") if isinstance(prior.get("sources"), Mapping) else {}
    )
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for key in EXPECTED_KEYS:
        if key in given:
            values[key], sources[key] = given[key], "maker"
        elif prior_values.get(key):
            values[key] = str(prior_values[key])
            sources[key] = str(prior_sources.get(key) or "maker")
        elif reference.get(key):
            values[key], sources[key] = reference[key], "dev-record"
    maker_sourced = any(source == "maker" for source in sources.values())
    changed = any(given.get(key) != prior_values.get(key) for key in given)
    if not maker_sourced:
        confirmed = True
    elif changed:
        confirmed = admin_confirmed
    else:
        confirmed = admin_confirmed or bool(prior.get("adminConfirmed"))
    differences = [
        {
            "item": EXPECTED_LABELS[key],
            "dev": reference[key],
            "expected": value,
        }
        for key, value in values.items()
        if sources[key] == "maker" and reference.get(key) not in (None, value)
    ]
    return {
        "values": values,
        "sources": sources,
        "adminConfirmed": confirmed,
        "devRecordDifferences": differences,
    }


def expected_blocker(expected: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return why the expected values cannot be used yet, if they cannot."""
    values = expected.get("values", {})
    missing = [EXPECTED_LABELS[key] for key in EXPECTED_KEYS if not values.get(key)]
    if missing:
        return {
            "reason": "expected-values-missing",
            "missing": missing,
            "message": (
                "We still need administrator confirmation for: "
                + ", ".join(missing)
                + ". You don't need to resend earlier replies unless a "
                "specific confirmation is missing."
            ),
        }
    if not expected.get("adminConfirmed"):
        return {
            "reason": "expected-values-unconfirmed",
            "missing": [],
            "message": (
                "The ServiceNow administrator must confirm the values the "
                "maker provided before they are used to check this realm."
            ),
        }
    return None


def foundation_reused(expected: Mapping[str, Any]) -> bool:
    sources = expected.get("sources", {})
    return all(sources.get(key) == "dev-record" for key in EXPECTED_KEYS)


ADMIN_CASE_REUSE = "dev-reuse"
ADMIN_CASE_INDEPENDENT = "independent"
ADMIN_EXPLANATIONS = {
    ADMIN_CASE_REUSE: (
        "We'll retain the administrator-confirmed sign-in setup and employee "
        "mapping that still applies to this ServiceNow instance. We won't "
        "repeat completed administrator work. You don't need to resend "
        "earlier replies unless a specific confirmation is missing or no "
        "longer applies."
    ),
    ADMIN_CASE_INDEPENDENT: (
        "We couldn't find a completed Dev setup for this agent, so we'll run "
        "the full ServiceNow setup for {label}. We'll start with your "
        "administrators, then check the connection, topics, and portal."
    ),
}


def _confirmed_handoff(
    handoffs: Mapping[str, Any],
    phase: str,
) -> Mapping[str, Any]:
    record = handoffs.get(phase)
    if not isinstance(record, Mapping) or record.get("status") not in (
        "completed",
        "reused",
    ):
        return {}
    evidence = record.get("evidence")
    return evidence if isinstance(evidence, Mapping) else {}


def dev_admin_setup_complete(
    state: Mapping[str, Any],
    tenant_id: str | None = None,
) -> bool:
    """True only when Dev holds every administrator-confirmed value.

    The administrator-confirmed instance, the Entra Client ID with its User
    Claim, and the ServiceNow employee mapping (User Field) must all be
    recorded for the same tenant. Any gap means the full administrator flow.
    """
    if tenant_id is not None:
        recorded_tenant = str(state.get("tenantId") or "").strip().casefold()
        if recorded_tenant != str(tenant_id).strip().casefold():
            return False
    setup = state.get("adminSetup")
    setup = setup if isinstance(setup, Mapping) else {}
    preflight = setup.get("preflight")
    preflight = preflight if isinstance(preflight, Mapping) else {}
    handoffs = setup.get("phaseHandoffs")
    handoffs = handoffs if isinstance(handoffs, Mapping) else {}
    instance_confirmed = bool(_normalize_instance(preflight.get("instanceName"))) and (
        (
            preflight.get("instanceSource") == "maker-confirmed"
            and bool(preflight.get("recordedAt"))
        )
        or bool(_confirmed_handoff(handoffs, "preflight"))
    )
    entra = _confirmed_handoff(handoffs, "entra-registration")
    mapping = _confirmed_handoff(handoffs, "servicenow-oidc")
    try:
        _guid(entra.get("clientId"), "client ID")
    except ServiceNowRealmError:
        return False
    return (
        instance_confirmed
        and bool(str(entra.get("selectedClaimName") or "").strip())
        and bool(str(mapping.get("serviceNowUserField") or "").strip())
    )


def new_admin_setup(case: str) -> dict[str, Any]:
    if case == ADMIN_CASE_REUSE:
        return {"case": ADMIN_CASE_REUSE}
    return {
        "case": ADMIN_CASE_INDEPENDENT,
        "entra": {"status": "pending"},
        "servicenow": {"status": "pending"},
    }


def admin_case(target: Mapping[str, Any]) -> str:
    setup = target.get("adminSetup")
    if isinstance(setup, Mapping) and setup.get("case") in ADMIN_EXPLANATIONS:
        return str(setup["case"])
    return (
        ADMIN_CASE_REUSE
        if foundation_reused(target.get("expected", {}))
        else ADMIN_CASE_INDEPENDENT
    )


def _admin_setup(target: dict[str, Any]) -> dict[str, Any]:
    setup = target.get("adminSetup")
    if not isinstance(setup, dict) or setup.get("case") != ADMIN_CASE_INDEPENDENT:
        setup = new_admin_setup(ADMIN_CASE_INDEPENDENT)
        target["adminSetup"] = setup
    setup.setdefault("entra", {"status": "pending"})
    setup.setdefault("servicenow", {"status": "pending"})
    return setup


def independent_pending(target: Mapping[str, Any]) -> str | None:
    """First administrator step still open for an independent run."""
    if admin_case(target) != ADMIN_CASE_INDEPENDENT:
        return None
    setup = target.get("adminSetup")
    setup = setup if isinstance(setup, Mapping) else {}
    entra = setup.get("entra") if isinstance(setup.get("entra"), Mapping) else {}
    mapping = (
        setup.get("servicenow") if isinstance(setup.get("servicenow"), Mapping) else {}
    )
    if not setup.get("instanceName"):
        return "instance"
    if entra.get("status") != "confirmed":
        return "entra"
    if mapping.get("status") != "confirmed":
        return "servicenow"
    return None


def _reset_stages(target: dict[str, Any]) -> None:
    target["stages"] = {stage_id: {"status": "pending"} for stage_id in STAGE_IDS}


def sync_independent_expected(target: dict[str, Any]) -> None:
    """Derive the expected values from the administrator replies only."""
    setup = _admin_setup(target)
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    if setup.get("instanceName"):
        values["instanceName"] = str(setup["instanceName"])
        sources["instanceName"] = "maker"
    if setup["entra"].get("status") == "confirmed":
        values["clientId"] = str(setup["entra"]["clientId"])
        sources["clientId"] = "entra-administrator"
    previous = target.get("expected", {}).get("values")
    target["expected"] = {
        "values": values,
        "sources": sources,
        "adminConfirmed": setup["servicenow"].get("status") == "confirmed",
        "devRecordDifferences": [],
    }
    if previous != values:
        _reset_stages(target)


def set_independent_instance(target: dict[str, Any], instance: str) -> None:
    setup = _admin_setup(target)
    normalized = _normalize_provided({"instanceName": instance})["instanceName"]
    if setup.get("instanceName") != normalized:
        setup["instanceName"] = normalized
        setup["entra"] = {"status": "pending"}
        setup["servicenow"] = {"status": "pending"}
    sync_independent_expected(target)


def record_admin_entra(
    target: dict[str, Any],
    *,
    client_id: str,
    claim_name: str,
) -> None:
    setup = _admin_setup(target)
    if not setup.get("instanceName"):
        raise ServiceNowRealmError(
            "We need the ServiceNow instance name before the Microsoft Entra "
            "administrator's reply can be recorded."
        )
    normalized_id = _guid(client_id, "The Entra application (client) ID").casefold()
    previous = setup["entra"]
    if (
        previous.get("status") != "confirmed"
        or previous.get("clientId") != normalized_id
        or previous.get("claimName") != claim_name
    ):
        setup["servicenow"] = {"status": "pending"}
    setup["entra"] = {
        "status": "confirmed",
        "clientId": normalized_id,
        "claimName": claim_name,
        "recordedAt": _utc_now(),
    }
    sync_independent_expected(target)


def record_admin_servicenow(
    target: dict[str, Any],
    *,
    user_field: str,
    confirmed: bool,
) -> None:
    setup = _admin_setup(target)
    if setup["entra"].get("status") != "confirmed":
        raise ServiceNowRealmError(
            "The Microsoft Entra administrator's reply comes first; the "
            "ServiceNow administrator's mapping depends on it."
        )
    if not confirmed:
        raise ServiceNowRealmError(
            "We still need your ServiceNow administrator to confirm that the "
            "configuration is saved and that the User Field holds exactly "
            "the same value as the User Claim."
        )
    setup["servicenow"] = {
        "status": "confirmed",
        "userField": user_field,
        "recordedAt": _utc_now(),
    }
    sync_independent_expected(target)


def record_target(
    registry: dict[str, Any],
    realm: str,
    identity: Mapping[str, str],
    expected: Mapping[str, Any],
    admin_setup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    previous = registry["targets"].get(realm)
    same_identity = (
        isinstance(previous, dict)
        and previous.get("identity", {}).get("agentId") == identity["agentId"]
        and previous.get("identity", {}).get("environmentId")
        == identity["environmentId"]
    )
    same_target = same_identity and (
        previous.get("expected", {}).get("values") == expected.get("values")
    )
    target = {
        "identity": dict(identity),
        "expected": dict(expected),
        "discoveredAt": _utc_now(),
        "stages": (
            copy.deepcopy(previous["stages"])
            if same_target
            else {stage_id: {"status": "pending"} for stage_id in STAGE_IDS}
        ),
    }
    if admin_setup is not None:
        target["adminSetup"] = copy.deepcopy(dict(admin_setup))
    elif same_identity and isinstance(previous.get("adminSetup"), dict):
        target["adminSetup"] = copy.deepcopy(previous["adminSetup"])
    if same_identity:
        for key in ("repairs", "instancePause"):
            if previous.get(key):
                target[key] = copy.deepcopy(previous[key])
    registry["targets"][realm] = target
    registry["activeTargetRealm"] = realm
    return target


def update_expected(
    registry: dict[str, Any],
    realm: str,
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    target = registry["targets"][realm]
    return record_target(registry, realm, target["identity"], expected)


def _difference(label: str, expected: str | None, actual: str | None) -> dict[str, Any]:
    return {
        "item": label,
        "expected": expected or "not set",
        "actual": actual or "not set",
    }


def _same_connection_id(left: Any, right: Any) -> bool:
    try:
        return uuid.UUID(str(left)).hex == uuid.UUID(str(right)).hex
    except ValueError:
        return False


def _item(label: str, status: str, detail: str | None = None) -> dict[str, str]:
    item = {"item": label, "status": status}
    if detail:
        item["detail"] = detail
    return item


def connection_pause_text(
    reason: str,
    *,
    agent: str = "this agent",
    label: str = "this environment",
    kind: str | None = None,
    differences: list[Mapping[str, Any]] | None = None,
    untested: bool = False,
) -> str:
    """Spec pause text for a connection blocker; never names a menu path.

    The repair mechanism for the destination connection is an open
    engineering question, so the text only pauses and asks the maker to
    return once the supported repair is complete.
    """
    request = f"{kind} request" if kind else "request"
    agent_ref = f"the {kind} agent" if kind else "this agent"
    if reason == "connection-not-bound":
        finding = (
            f"a ServiceNow connection is available in {label}, but it isn't "
            f"linked to {agent}. That prevents this agent from using it."
        )
        repair = "Once the supported destination linking repair is complete"
        recheck = f"We'll recheck this agent's connection before you run the {request}."
        kept = "We won't repeat completed administrator work."
    elif reason == "connection-unhealthy":
        finding = (
            f"the ServiceNow connection in {label} is disconnected, so "
            f"{agent_ref} can't use it."
        )
        repair = "Once the supported destination repair is complete"
        recheck = f"We'll recheck the destination setup before you run the {request}."
        kept = "We won't restart completed administrator work."
    else:
        if reason == "connection-mismatch":
            finding = (
                f"the ServiceNow connection in {label} doesn't use the "
                f"expected sign-in values, so it can't make the {request} yet."
            )
        else:
            finding = (
                f"{agent} has no ServiceNow connection available for this "
                f"setup in {label}, so it can't make the {request} yet."
            )
        repair = "Once the supported destination repair is complete"
        recheck = f"We'll recheck the destination setup before you run the {request}."
        kept = "The applicable administrator-confirmed sign-in setup stays in place."
    if untested:
        bold_agent = f"**{agent} in {label}**"
        if reason == "connection-not-bound":
            finding = (
                f"a ServiceNow connection is available in {label}, but it "
                f"isn't linked to {bold_agent}."
            )
        elif reason == "connection-mismatch":
            finding = (
                f"the ServiceNow connection in {label} doesn't use the "
                "expected sign-in values."
            )
        elif reason != "connection-unhealthy":
            finding = (
                f"{bold_agent} has no ServiceNow connection available for "
                "this setup."
            )
        recheck = (
            "We'll recheck the destination setup before requesting your "
            f"{kind or 'real-data'} test."
        )
        return "\n\n".join(
            [
                f"**Validation is paused:** {finding} This destination "
                "remains untested; its setup isn't complete.",
                "Your progress is saved at the destination connection "
                "repair. Once the supported repair is complete, return here "
                f"and tell us. {recheck}",
            ]
        )
    lines = [f"**Validation is paused:** {finding}"]
    for difference in differences or []:
        lines.append(
            f"- **{difference['item']}:** expected `{difference['expected']}`, "
            f"found `{difference['actual']}`."
        )
    return "\n\n".join(
        [
            "\n".join(lines),
            f"{repair}, return here and tell us. {recheck}",
            kept,
        ]
    )


def _blocked_connection(
    reason: str,
    differences: list[Mapping[str, Any]] | None = None,
) -> str:
    return connection_pause_text(reason, differences=differences)


def evaluate_connections(
    expected: Mapping[str, Any],
    reference: Mapping[str, Any],
    connections: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Read-only check of this realm's own connection.

    Nothing here reads Dev: the connection must exist in this environment,
    be bound to this agent, be connected, and use the expected values.
    """
    values = expected.get("values", {})
    blocker = expected_blocker(expected)
    items: list[dict[str, str]] = []
    connection_id = reference.get("connectionId")
    match = None
    if connection_id:
        match = next(
            (
                item
                for item in connections
                if _same_connection_id(item.get("connectionId"), connection_id)
            ),
            None,
        )
    items.append(
        _item(
            "ServiceNow connection is bound to this agent",
            "pass" if connection_id else "fail",
        )
    )
    nothing_exists = not connections
    items.append(
        _item(
            "Connection exists in this environment",
            "pass"
            if match
            else ("fail" if connection_id or nothing_exists else "not-checked"),
        )
    )
    observed: dict[str, str] = {}
    differences: list[dict[str, Any]] = []
    connected = False
    if match is not None:
        parameters = match.get("parameterValues")
        parameters = parameters if isinstance(parameters, Mapping) else {}
        observed = {
            "instanceName": _normalize_instance(
                parameters.get("token:InstanceName")
                or parameters.get("instance")
                or reference.get("instanceName")
            ),
            "clientId": str(
                parameters.get("token:ResourceUri")
                or reference.get("resourceUri")
                or ""
            )
            .strip()
            .casefold(),
        }
        connected = match.get("status") == "Connected"
        if match.get("authMode") != EXPECTED_AUTH_MODE:
            differences.append(
                _difference(
                    "Authentication type",
                    "Microsoft Entra ID User Login",
                    str(match.get("authMode") or ""),
                )
            )
        for key in EXPECTED_KEYS:
            if values.get(key) and observed[key] != values[key]:
                differences.append(
                    _difference(EXPECTED_LABELS[key], values[key], observed[key])
                )
    mismatched = {entry["item"] for entry in differences}
    items.append(
        _item(
            "Connection is connected",
            "not-checked" if match is None else ("pass" if connected else "fail"),
        )
    )
    items.append(
        _item(
            "Authentication type is Microsoft Entra ID User Login",
            "not-checked"
            if match is None
            else ("fail" if "Authentication type" in mismatched else "pass"),
        )
    )
    for key in EXPECTED_KEYS:
        label = EXPECTED_LABELS[key]
        if match is None or not values.get(key):
            status = "not-checked"
        else:
            status = "fail" if label in mismatched else "pass"
        items.append(_item(f"{label} matches", status))
    result: dict[str, Any] = {"items": items}
    if observed:
        result["observed"] = observed
    if blocker is not None:
        result.update(
            status="needs-maker",
            reason=blocker["reason"],
            missing=blocker["missing"],
            message=blocker["message"],
        )
    elif not connection_id and connections:
        finding = (
            "A ServiceNow connection is available in this environment, "
            "but it isn't linked to this agent."
        )
        result.update(
            status="blocked",
            reason="connection-not-bound",
            finding=finding,
            message=_blocked_connection("connection-not-bound"),
        )
    elif match is None:
        finding = (
            "This agent has no ServiceNow connection available for this "
            "setup in this environment."
        )
        result.update(
            status="blocked",
            reason="connection-not-found",
            finding=finding,
            message=_blocked_connection("connection-not-found"),
        )
    elif differences:
        finding = (
            "The ServiceNow connection in this environment doesn't use "
            "the expected sign-in values."
        )
        result.update(
            status="blocked",
            reason="connection-mismatch",
            differences=differences,
            finding=finding,
            message=_blocked_connection("connection-mismatch", differences),
        )
    elif not connected:
        finding = "The ServiceNow connection in this environment is disconnected."
        result.update(
            status="blocked",
            reason="connection-unhealthy",
            finding=finding,
            message=_blocked_connection("connection-unhealthy"),
        )
    else:
        result.update(
            status="done",
            connectionId=str(connection_id),
            message="The ServiceNow connection in this realm is verified.",
        )
    return result


def evaluate_runtime(
    expected: Mapping[str, Any],
    target_topics: list[Mapping[str, Any]],
    target_portal: Mapping[str, Any],
) -> dict[str, Any]:
    """Read-only check of this realm's own topics and portal URL."""
    instance = expected.get("values", {}).get("instanceName")
    observations = []
    off = sorted(
        str(topic.get("schemaName") or "")
        for topic in target_topics
        if topic.get("state") != "Active" or topic.get("status") != "Active"
    )
    if not target_topics:
        observations.append("No ServiceNow topics were found in this realm.")
    for name in off:
        observations.append(f"Topic `{name}` is not turned on in this realm.")
    reason = target_portal.get("reason") or "missing"
    portal_ok = bool(target_portal.get("valid"))
    if not portal_ok:
        observations.append(
            "The portal URL is not set to a valid ServiceNow URL"
            + (f" for `{instance}`" if instance else "")
            + f" in this realm ({reason})."
        )
    items = [
        _item(
            "Required ServiceNow topics are turned on",
            "pass" if target_topics and not off else "fail",
        ),
        _item("Portal URL is set", "pass" if portal_ok else "fail", None),
    ]
    if observations:
        return {
            "status": "blocked",
            "reason": "promoted-configuration-differs",
            "items": items,
            "observations": observations,
            "offTopics": off,
            "noTopics": not target_topics,
            "portalReason": None if portal_ok else str(reason),
            "message": (
                "We'll enable the affected built-in topic and leave "
                "unrelated topics unchanged."
                if off
                else (
                    "We need the employee portal URL for this agent."
                    if target_topics and not portal_ok
                    else "We only read topics and the portal URL in Test and "
                    "Prod. Fix them in Dev, promote again through your own "
                    "deployment process, then check again."
                )
            ),
        }
    return {
        "status": "done",
        "items": items,
        "message": "Topics and the portal URL verified read-only.",
    }


def instance_pause_text() -> str:
    return "\n\n".join(
        [
            "That changes the shared-instance assumption behind this "
            "promotion path. We can't treat the earlier administrator setup "
            "as evidence for a different instance.",
            "This destination run is paused while support for the "
            "different-instance path is resolved. We'll retain the earlier "
            "result only for its original instance and identify which setup "
            "information needs review.",
        ]
    )


def _retained_instance(target: Mapping[str, Any]) -> str:
    setup = target.get("adminSetup") if isinstance(target, Mapping) else None
    if isinstance(setup, Mapping) and setup.get("instanceName"):
        return str(setup["instanceName"])
    expected = target.get("expected") if isinstance(target, Mapping) else None
    values = expected.get("values") if isinstance(expected, Mapping) else None
    return str((values or {}).get("instanceName") or "")


def request_instance_change(target: dict[str, Any], requested: str | None) -> bool:
    """Pause the destination when the maker names a different instance.

    Nothing about the retained instance is changed or reused for the new one.
    Naming the retained instance again lifts the pause.
    """
    if not requested:
        return bool(target.get("instancePause"))
    candidate = _normalize_provided({"instanceName": requested})["instanceName"]
    retained = _retained_instance(target)
    if retained and candidate != retained:
        target["instancePause"] = {
            "retainedInstance": retained,
            "requestedInstance": candidate,
            "requestedAt": _utc_now(),
        }
        return True
    target.pop("instancePause", None)
    return False


def record_portal_url_request(target: dict[str, Any], url: str) -> dict[str, Any]:
    """Record the portal URL the agent should save for this destination."""
    repairs = target.setdefault("repairs", {})
    repairs["portalUrl"] = {
        "status": "requested",
        "url": url,
        "requestedAt": _utc_now(),
    }
    return repairs["portalUrl"]


def _sync_repairs(target: dict[str, Any], runtime: Mapping[str, Any]) -> None:
    repairs = target.setdefault("repairs", {})
    off = [str(name) for name in runtime.get("offTopics") or []]
    if off:
        repairs["enableTopics"] = {
            "status": "requested",
            "topics": off,
            "requestedAt": _utc_now(),
        }
    elif "enableTopics" in repairs:
        repairs["enableTopics"]["status"] = "done"
    portal = repairs.get("portalUrl")
    if isinstance(portal, dict) and not runtime.get("portalReason"):
        if runtime.get("status") == "done":
            portal["status"] = "done"


def apply_checks(
    target: dict[str, Any],
    *,
    connections: dict[str, Any],
    runtime: dict[str, Any],
) -> bool:
    """Record this realm's stage results; no other realm is consulted.

    Returns True when the maker came back to a destination that was finished
    untested, so the caller can say validation is continuing.
    """
    stages = target["stages"]
    now = _utc_now()
    stages["connections"] = {**connections, "checkedAt": now}
    stages["runtime-configuration"] = {**runtime, "checkedAt": now}
    _sync_repairs(target, runtime)
    validation = stages.get("maker-validation") or {}
    ready = connections.get("status") == "done" and runtime.get("status") == "done"
    bound = (validation.get("binding") or {}).get("connectionId")
    same = _same_connection_id(bound, connections.get("connectionId"))
    status = validation.get("status")
    resumed = status == "untested"
    if status in {"done", "untested"} and ready and same:
        return resumed
    if status == "reported" and connections.get("status") == "done" and same:
        if ready:
            stages["maker-validation"] = {**validation, "status": "done"}
        return resumed
    if resumed and not ready and validation.get("blockedBy"):
        return resumed
    stages["maker-validation"] = (
        {
            "status": "needs-maker",
            "message": (
                "In Copilot Studio, run a request in this agent's Test pane "
                "that should return your real ServiceNow data. Use this "
                "environment's agent, not the Dev agent. Then tell us what "
                "happened and whether it matched what you expected. You "
                "don't need to paste record contents or employee identifiers."
            ),
        }
        if ready
        else {
            "status": "pending",
            "message": "Waiting for the earlier stages.",
        }
    )
    return resumed


def record_validation(
    target: dict[str, Any],
    *,
    prompt_category: str,
    allowed_prompt_category: str,
    result: str,
    failure_category: str | None,
) -> dict[str, Any]:
    if prompt_category != allowed_prompt_category:
        raise ServiceNowRealmError(
            "Unsupported privacy-safe Test pane prompt category."
        )
    if result not in {"pass", "fail", "untested"}:
        raise ServiceNowRealmError("Test pane result must be pass, fail, or untested.")
    if result == "pass" and failure_category is not None:
        raise ServiceNowRealmError(
            "A passing Test pane result cannot have a failure category."
        )
    if result == "untested" and failure_category is not None:
        raise ServiceNowRealmError("An untested finish cannot have a failure category.")
    stages = target["stages"]
    connections = stages["connections"]
    runtime = stages["runtime-configuration"]
    identity = target["identity"]
    status_by_result = {"pass": "done", "fail": "blocked", "untested": "untested"}
    stage_status = status_by_result[result]
    blocked_by = None
    if connections.get("status") != "done" or runtime.get("status") != "done":
        if result == "untested" and "blocked" in {
            connections.get("status"),
            runtime.get("status"),
        }:
            blocked_by = (
                connections.get("reason")
                if connections.get("status") == "blocked"
                else runtime.get("reason")
            )
        elif (
            result == "pass"
            and connections.get("status") == "done"
            and runtime.get("status") == "blocked"
            and not runtime.get("noTopics")
        ):
            stage_status = "reported"
        else:
            raise ServiceNowRealmError(
                "Complete Connections and Runtime configuration before "
                "recording the Test pane result."
            )
    stages["maker-validation"] = {
        "status": stage_status,
        "kind": "maker-attestation",
        "promptCategory": prompt_category,
        "result": result,
        "failureCategory": failure_category,
        "recordedAt": _utc_now(),
        "binding": {
            "environmentId": identity["environmentId"],
            "agentId": identity["agentId"],
            "connectionId": connections.get("connectionId"),
        },
    }
    if blocked_by:
        stages["maker-validation"]["blockedBy"] = blocked_by
    return stages["maker-validation"]


def target_status(registry: Mapping[str, Any], realm: str) -> str:
    target = registry["targets"].get(realm)
    if not isinstance(target, Mapping):
        return "not-discovered"
    stages = target.get("stages", {})
    statuses = [stages.get(stage_id, {}).get("status") for stage_id in STAGE_IDS]
    if all(status == "done" for status in statuses):
        return "ready"
    if "blocked" in statuses:
        return "blocked"
    if statuses[-1] == "untested" and all(status == "done" for status in statuses[:-1]):
        return "untested"
    return "in-progress"


def select_realm(registry: dict[str, Any], realm: str) -> None:
    if realm == "dev":
        registry["activeTargetRealm"] = "dev"
        return
    if realm not in PROMOTED_REALMS:
        raise ServiceNowRealmError("Realm must be dev, test, or prod.")
    if realm not in registry["targets"]:
        raise ServiceNowRealmError(
            f"The {realm.title()} realm has not been discovered yet."
        )
    registry["activeTargetRealm"] = realm


def expected_summary(expected: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "values": dict(expected.get("values", {})),
        "sources": dict(expected.get("sources", {})),
        "adminConfirmed": bool(expected.get("adminConfirmed")),
        "devRecordReused": foundation_reused(expected),
    }
    if expected.get("devRecordDifferences"):
        summary["devRecordDifferences"] = expected["devRecordDifferences"]
    return summary


def _agent_reference(context: Mapping[str, Any]) -> str:
    agent = str(context["agent"])
    url = context.get("agentUrl")
    return f"[**{agent}**]({url})" if url else f"**{agent}**"


def _connection_instruction(
    stage: Mapping[str, Any],
    label: str,
    context: Mapping[str, Any],
    *,
    untested: bool = False,
) -> str:
    """Pause text only: the destination repair mechanism is not invented."""
    return connection_pause_text(
        str(stage.get("reason") or ""),
        agent=str(context["agent"]),
        label=label,
        kind=str(context["kind"]),
        differences=stage.get("differences") or [],
        untested=untested,
    )


def _portal_question(context: Mapping[str, Any]) -> str:
    return (
        "What is the full HTTPS base URL employees should use for "
        f"{context['kind']} {context['record']}s?"
    )


def _portal_missing_instruction(
    runtime: Mapping[str, Any],
    label: str,
    context: Mapping[str, Any],
    request: Mapping[str, Any] | None,
) -> str:
    kind = context["kind"]
    if request and request.get("status") == "requested":
        return (
            f"We'll save that URL for the {kind} agent in {label}. The "
            "shared identity setup stays in place."
        )
    if runtime.get("portalReason") in {"missing", "portal-topic-missing"}:
        finding = (
            f"The {kind} agent in **{label}** is missing its employee portal "
            f"URL, so its {context['record']} links may not open correctly."
        )
    else:
        finding = (
            f"The employee portal URL for the {kind} agent in **{label}** "
            "isn't set to a valid ServiceNow URL, so its "
            f"{context['record']} links may not open correctly."
        )
    return f"{finding}\n\n{_portal_question(context)}"


def _portal_reported_instruction(
    runtime: Mapping[str, Any],
    label: str,
    context: Mapping[str, Any],
    request: Mapping[str, Any] | None,
) -> str:
    if request and request.get("status") == "requested":
        return _portal_missing_instruction(runtime, label, context, request)
    return (
        f"Your {context['kind']} request returned the expected data, but "
        f"the agent in **{label}** is missing its employee portal URL. We "
        "need to fix that before this setup can be called complete.\n\n"
        + _portal_question(context)
    )


def _topics_instruction(
    runtime: Mapping[str, Any],
    label: str,
    context: Mapping[str, Any],
    *,
    reported: bool = False,
) -> str | None:
    off = [str(name) for name in runtime.get("offTopics") or []]
    if not off:
        return None
    agent = str(context["agent"])
    product = str(context.get("product") or context["kind"])
    plural = len(off) > 1
    topic = (
        f"required ServiceNow {product} topics are"
        if plural
        else f"a required ServiceNow {product} topic is"
    )
    if reported:
        lead = (
            f"Your {context['kind']} request returned the expected data, "
            f"but {topic} off in **{agent} in {label}**. We need to fix that "
            "before this setup can be called complete."
        )
    else:
        lead = (
            f"{topic[0].upper()}{topic[1:]} off in **{agent} in {label}**, "
            "so the agent can't complete that request."
        )
    return (
        f"{lead}\n\nWe'll enable the affected built-in "
        f"{'topics' if plural else 'topic'} and leave unrelated topics "
        "unchanged."
    )


def _promoted_fix_instruction(
    finding: str,
    subject: str,
    label: str,
    agent: str,
) -> str:
    return "\n".join(
        [
            f"**Validation is paused:** {finding}",
            "",
            f"{label} is a managed environment, so {subject} can't be edited "
            "there. To fix this:",
            "",
            f"1. Go back to Dev and update {subject}: run `/connect servicenow` again.",
            "2. Publish the agent in Dev.",
            f"3. Deploy (promote) {agent} to {label} again through your own "
            "deployment process.",
            '4. Reply "Done" and we\'ll recheck this step only.',
        ]
    )


def _test_pane_request(label: str, context: Mapping[str, Any]) -> str:
    kind = str(context["kind"])
    article = "an"
    paragraphs = [
        f"In Copilot Studio, open {_agent_reference(context)} in {label} and "
        f"run {article} {kind} request in that agent's **Test pane** that "
        "should return your real ServiceNow data.",
        f'For example, use **"{context["example"]},"** if you have open '
        f"ones. Use the agent in {label}, not the Dev agent.",
    ]
    if label == "Prod":
        paragraphs.append(
            "The Test pane is where you try the Prod agent; it doesn't switch "
            "this run to the Test environment."
        )
    paragraphs.append(
        "Return here and tell us what happened and whether it matched what "
        f"you expected. You don't need to paste {context['record']} contents "
        "or employee identifiers."
    )
    paragraphs.append(
        "You can also finish without testing; the Prod integration will "
        "remain untested. Test it before employees use it."
        if label == "Prod"
        else f"You can also finish without testing; this integration in "
        f"{label} will remain untested."
    )
    return "\n\n".join(paragraphs)


def _admin_fallback(waiting: str) -> str:
    if waiting == "instance":
        return (
            "What is your ServiceNow instance name, for example `contoso`? "
            "We need it before we can prepare the Microsoft Entra "
            "administrator's message."
        )
    if waiting == "entra":
        return (
            "Send the Microsoft Entra administrator message to your "
            "administrator, then paste their reply here without secrets."
        )
    return (
        "Send the ServiceNow administrator message to your administrator, "
        "then paste their reply here without secrets."
    )


def render_realm_block(
    registry: Mapping[str, Any],
    realm: str,
    context: Mapping[str, Any],
) -> str | None:
    """Grouped step checklist for one promoted realm; reads recorded results.

    Rows follow the order of the checks and stop at the first failing one;
    later rows stay pending. Nothing here reads or writes any environment.
    """
    target = registry["targets"].get(realm)
    if realm not in PROMOTED_REALMS or not isinstance(target, Mapping):
        return None
    stages = target.get("stages", {})
    connections = stages.get("connections") or {}
    runtime = stages.get("runtime-configuration") or {}
    validation = stages.get("maker-validation") or {}
    label = realm.title()
    agent = str(context["agent"])

    pending = ("⬜", "Not checked yet")
    permission = ("✅", "Verified")
    connection = pending
    topics = pending
    portal = pending
    real_data = ("⬜", "Not started")
    instruction: str | None = None

    case = admin_case(target)
    admin_rows: list[tuple[str, tuple[str, str]]] = []
    if case == ADMIN_CASE_INDEPENDENT:
        waiting = independent_pending(target)
        entra = ("✅", "Confirmed")
        mapping = ("✅", "Confirmed")
        if waiting == "instance":
            entra = ("⏳", "Waiting for the ServiceNow instance name")
            mapping = ("⬜", "Not started")
        elif waiting == "entra":
            entra = ("⏳", "Waiting for the administrator's reply")
            mapping = ("⬜", "Not started")
        elif waiting == "servicenow":
            mapping = ("⏳", "Waiting for the administrator's reply")
        admin_rows = [
            ("Microsoft Entra administrator (Client ID and claim)", entra),
            (
                "ServiceNow administrator (employee mapping / User Field)",
                mapping,
            ),
        ]
        if waiting is not None:
            instruction = str(
                (context.get("adminInstruction") or {}).get(waiting)
                or _admin_fallback(waiting)
            )

    status = connections.get("status")
    if status == "done":
        connection = ("✅", "Exists, is connected, and is linked to this agent")
    elif status == "needs-maker":
        connection = ("⏳", "Waiting for the missing sign-in details")
        instruction = str(connections.get("message") or "")
    elif status == "blocked":
        connection = ("❌", "Needs attention")
        instruction = _connection_instruction(
            connections,
            label,
            context,
            untested=bool(
                validation.get("status") == "untested"
                and validation.get("blockedBy")
            ),
        )

    reported = validation.get("status") == "reported"
    repairs = target.get("repairs") or {}
    if status == "done":
        items = runtime.get("items") or []
        statuses = [entry.get("status") for entry in items]
        topics_ok = bool(statuses) and statuses[0] == "pass"
        portal_ok = len(statuses) > 1 and statuses[1] == "pass"
        if runtime.get("status") == "done":
            topics = ("✅", "Required topics are turned on")
            portal = ("✅", "Set")
        elif statuses and not topics_ok:
            topics = ("❌", "Needs attention")
            instruction = _topics_instruction(
                runtime, label, context, reported=reported
            )
            if instruction is None:
                instruction = _promoted_fix_instruction(
                    f"no ServiceNow topics were found in {label}, so {agent} "
                    "can't complete the request yet.",
                    "the topics",
                    label,
                    agent,
                )
        elif statuses and not portal_ok:
            topics = ("✅", "Required topics are turned on")
            portal = ("❌", "Needs attention")
            build = (
                _portal_reported_instruction if reported else _portal_missing_instruction
            )
            instruction = build(
                runtime, label, context, repairs.get("portalUrl")
            )

    if status == "done" and runtime.get("status") == "done":
        result = validation.get("status")
        if result == "done":
            real_data = ("✅", "Verified")
        elif result == "untested":
            real_data = ("⏳", "Untested; your progress is saved")
        elif result == "blocked":
            real_data = ("❌", "Needs attention")
        elif result == "needs-maker":
            real_data = ("⏳", "Waiting for you")
            instruction = _test_pane_request(label, context)
    elif status == "blocked" and validation.get("status") == "untested":
        real_data = ("⏳", "Untested; your progress is saved")
    elif reported:
        real_data = ("⏳", "Returned the expected data; setup isn't complete yet")

    if target.get("instancePause"):
        instruction = instance_pause_text()

    rows = [
        ("Permission to configure this agent", permission),
        *admin_rows,
        ("ServiceNow connection", connection),
        ("Topics", topics),
        ("Portal URL", portal),
        ("Real-data test in the Test pane", real_data),
    ]
    lines = []
    if context.get("resume"):
        lines += [
            f"We're continuing ServiceNow validation for **{agent} in "
            f"{label}**.",
            "",
            "We're rechecking your permission and the affected destination "
            "setup before we continue. If those checks find no blocking "
            "issue, the outstanding step is your real-data request in this "
            "agent's Test pane.",
            "",
        ]
    lines += [
        f"**ServiceNow validation: {agent} in {label}**",
        "",
        ADMIN_EXPLANATIONS[case].format(label=label),
        "",
    ]
    lines += [f"{icon} {name} — {text}" for name, (icon, text) in rows]
    footer = instruction or context.get("footer")
    if footer:
        lines += ["", str(footer)]
    return "\n".join(lines)


def realm_status(
    registry: Mapping[str, Any],
    render: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    active = str(registry.get("activeTargetRealm") or "dev")
    targets: dict[str, Any] = {}
    for realm in PROMOTED_REALMS:
        targets[realm] = {"deploymentStatus": target_status(registry, realm)}
        recorded = registry["targets"].get(realm)
        if isinstance(recorded, Mapping):
            targets[realm]["identity"] = {
                key: recorded["identity"][key]
                for key in ("environmentId", "agentId", "agentSchemaName")
            }
            targets[realm]["expected"] = expected_summary(recorded["expected"])
            targets[realm]["adminCase"] = admin_case(recorded)
            if recorded.get("repairs"):
                targets[realm]["repairs"] = dict(recorded["repairs"])
            if recorded.get("instancePause"):
                targets[realm]["instancePause"] = dict(recorded["instancePause"])
            if admin_case(recorded) == ADMIN_CASE_INDEPENDENT:
                targets[realm]["adminPending"] = independent_pending(recorded)
    phases: list[dict[str, Any]] = []
    next_phase = None
    recorded = registry["targets"].get(active)
    if isinstance(recorded, Mapping):
        for stage_id, label in STAGES:
            stage = recorded["stages"].get(stage_id, {})
            status = stage.get("status") or "pending"
            phase = {
                "id": stage_id,
                "label": label,
                "status": "complete" if status == "done" else status,
            }
            for key in (
                "message",
                "reason",
                "missing",
                "items",
                "observed",
                "differences",
                "observations",
            ):
                if key in stage:
                    phase[key] = stage[key]
            phases.append(phase)
            if next_phase is None and status != "done":
                next_phase = stage_id
    result: dict[str, Any] = {
        "schemaVersion": "servicenow.realm-status.v1",
        "activeTargetRealm": active,
        "targets": targets,
        "phases": phases,
        "nextPhaseId": next_phase,
    }
    if render is not None:
        text = render_realm_block(registry, active, render)
        if text is not None:
            result["renderBlock"] = {
                "kind": "realm-checklist",
                "case": admin_case(registry["targets"][active]),
                "text": text,
            }
    return result
