# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Promoted Test and Prod realm support for ServiceNow Connect.

Discovery proves the exact sibling realm of the recorded Dev agent through
AgentBuilder. The registry records one verified target per realm and the
three target-specific stages: Connections, Runtime configuration, and Maker
validation. This module never mutates an agent; the controller supplies live
component and connection reads.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
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


class ServiceNowRealmError(RuntimeError):
    """Raised when a promoted target cannot be proven or used safely."""

    customer_remediation = (
        "Your existing ServiceNow setup progress is preserved. Confirm that "
        "promotion finished, then check again or choose the target "
        "environment by name or Dataverse URL using the recorded maker "
        "account. If access is denied, ask the Power Platform environment "
        "administrator to grant that maker access before checking again."
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
        raise ServiceNowRealmError(
            "The promoted target could not be verified. Confirm maker "
            "access, environment selection, and deployment state."
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
            "or say the agent was promoted and Connect will find it."
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
        raise ServiceNowRealmError(
            "The agent link could not be verified as the promoted sibling "
            "of the recorded Dev agent. Confirm maker access and that "
            "promotion finished."
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
        raise ServiceNowRealmError(
            "The promoted target could not be verified. Confirm maker "
            "access, environment selection, and deployment state."
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


def foundation_from_dev_state(state: Mapping[str, Any]) -> dict[str, str]:
    """Read the reusable tenant foundation recorded by the Dev lifecycle."""
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
    foundation = {
        "instanceName": str(preflight.get("instanceName") or "").casefold(),
        "clientId": str(evidence.get("clientId") or "").casefold(),
        "tenantId": str(state.get("tenantId") or "").casefold(),
    }
    missing = [key for key, value in foundation.items() if not value]
    if missing:
        raise ServiceNowRealmError(
            "The Dev tenant foundation is incomplete ("
            + ", ".join(missing)
            + "). Finish the Dev lifecycle before configuring Test or Prod."
        )
    return foundation


def require_realm_prerequisite(
    registry: Mapping[str, Any],
    realm: str,
    *,
    dev_ready: bool,
) -> None:
    if realm not in PROMOTED_REALMS:
        raise ServiceNowRealmError("Realm must be test or prod.")
    if not dev_ready:
        raise ServiceNowRealmError(
            "Finish the Dev lifecycle, including the Test pane validation, "
            "before configuring a promoted realm."
        )
    if realm == "prod" and target_status(registry, "test") != "ready":
        raise ServiceNowRealmError(
            "Test must be Ready before Prod. Finish Test Maker validation first."
        )


def record_target(
    registry: dict[str, Any],
    realm: str,
    identity: Mapping[str, str],
    foundation: Mapping[str, str],
) -> dict[str, Any]:
    if str(identity.get("tenantId") or "").casefold() != foundation["tenantId"]:
        raise ServiceNowRealmError(
            "The promoted target's Microsoft Entra tenant differs from the "
            "Dev foundation, so the foundation cannot be reused."
        )
    previous = registry["targets"].get(realm)
    same_target = (
        isinstance(previous, dict)
        and previous.get("identity", {}).get("agentId") == identity["agentId"]
        and previous.get("identity", {}).get("environmentId")
        == identity["environmentId"]
    )
    target = {
        "identity": dict(identity),
        "foundation": dict(foundation),
        "foundationReused": True,
        "discoveredAt": _utc_now(),
        "stages": (
            copy.deepcopy(previous["stages"])
            if same_target
            else {stage_id: {"status": "pending"} for stage_id in STAGE_IDS}
        ),
    }
    registry["targets"][realm] = target
    registry["activeTargetRealm"] = realm
    return target


def _difference(label: str, dev: str | None, target: str | None) -> dict[str, Any]:
    return {"item": label, "dev": dev or "not set", "target": target or "not set"}


def _same_connection_id(left: Any, right: Any) -> bool:
    try:
        return uuid.UUID(str(left)).hex == uuid.UUID(str(right)).hex
    except ValueError:
        return False


def evaluate_connections(
    foundation: Mapping[str, str],
    reference: Mapping[str, Any],
    connections: list[Mapping[str, Any]],
) -> dict[str, Any]:
    connection_id = reference.get("connectionId")
    if not connection_id:
        return {
            "status": "needs-maker",
            "reason": "connection-not-bound",
            "message": (
                "No ServiceNow connection is bound to this agent in this realm yet."
            ),
        }
    match = next(
        (
            item
            for item in connections
            if _same_connection_id(item.get("connectionId"), connection_id)
        ),
        None,
    )
    if match is None:
        return {
            "status": "needs-maker",
            "reason": "connection-not-found",
            "message": (
                "The bound ServiceNow connection is not available in this "
                "environment. Create or share it for this maker."
            ),
        }
    values = match.get("parameterValues")
    values = values if isinstance(values, Mapping) else {}
    instance = str(
        values.get("token:InstanceName")
        or values.get("instance")
        or reference.get("instanceName")
        or ""
    ).strip()
    instance = instance.removesuffix(".service-now.com").casefold()
    resource = (
        str(values.get("token:ResourceUri") or reference.get("resourceUri") or "")
        .strip()
        .casefold()
    )
    differences = []
    if match.get("authMode") != EXPECTED_AUTH_MODE:
        differences.append(
            _difference(
                "Authentication type",
                "Microsoft Entra ID User Login",
                str(match.get("authMode") or ""),
            )
        )
    if instance != foundation["instanceName"]:
        differences.append(
            _difference("ServiceNow instance", foundation["instanceName"], instance)
        )
    if resource != foundation["clientId"]:
        differences.append(
            _difference(
                "Entra application (client) ID", foundation["clientId"], resource
            )
        )
    if differences:
        return {
            "status": "blocked",
            "reason": "foundation-mismatch",
            "differences": differences,
            "message": (
                "The connection in this realm does not match the Dev "
                "foundation, so the Dev administrator setup is not reused."
            ),
        }
    if match.get("status") != "Connected":
        return {
            "status": "needs-maker",
            "reason": "connection-unhealthy",
            "message": (
                "The ServiceNow connection in this realm is not connected. "
                "Repair or sign in again."
            ),
        }
    return {
        "status": "done",
        "connectionId": str(connection_id),
        "message": "The ServiceNow connection matches the Dev foundation.",
    }


def evaluate_runtime(
    foundation: Mapping[str, str],
    dev_topics: list[Mapping[str, Any]],
    target_topics: list[Mapping[str, Any]],
    target_portal: Mapping[str, Any],
) -> dict[str, Any]:
    def states(topics: list[Mapping[str, Any]]) -> dict[str, tuple[Any, Any]]:
        return {
            str(topic.get("schemaName") or "").casefold(): (
                topic.get("state"),
                topic.get("status"),
            )
            for topic in topics
        }

    dev_states = states(dev_topics)
    target_states = states(target_topics)
    observations = []
    if not target_states:
        observations.append("No ServiceNow topics were promoted to this realm.")
    for schema, expected in sorted(dev_states.items()):
        if schema not in target_states:
            observations.append(f"Topic `{schema}` was not promoted.")
        elif target_states[schema] != expected:
            observations.append(
                f"Topic `{schema}` is {target_states[schema][0]} here but "
                f"{expected[0]} in Dev."
            )
    if not target_portal.get("valid"):
        observations.append(
            "The portal URL is not valid for the Dev ServiceNow instance "
            f"`{foundation['instanceName']}` ("
            f"{target_portal.get('reason') or 'missing'})."
        )
    if observations:
        return {
            "status": "blocked",
            "reason": "promoted-configuration-differs",
            "observations": observations,
            "message": (
                "Connect only reads topic states and the portal URL in Test "
                "and Prod. Fix the configuration in Dev, promote again, then "
                "check again."
            ),
        }
    return {
        "status": "done",
        "message": "Promoted topic states and portal URL verified read-only.",
    }


def apply_checks(
    target: dict[str, Any],
    *,
    connections: dict[str, Any],
    runtime: dict[str, Any] | None,
) -> None:
    stages = target["stages"]
    now = _utc_now()
    stages["connections"] = {**connections, "checkedAt": now}
    if connections["status"] != "done" or runtime is None:
        stages["runtime-configuration"] = {
            "status": "pending",
            "message": "Waiting for the Connections stage.",
        }
    else:
        stages["runtime-configuration"] = {**runtime, "checkedAt": now}
    validation = stages.get("maker-validation", {})
    bound = (validation.get("binding") or {}).get("connectionId")
    stale = validation.get("status") == "done" and (
        connections.get("status") != "done"
        or stages["runtime-configuration"]["status"] != "done"
        or not _same_connection_id(bound, connections.get("connectionId"))
    )
    if stale or validation.get("status") not in {"done", "needs-maker"}:
        stages["maker-validation"] = {
            "status": "pending",
            "message": "Waiting for the earlier stages.",
        }
    elif validation.get("status") != "done":
        stages["maker-validation"] = {"status": "pending"}
    previous = stages["maker-validation"]
    if (
        previous.get("status") == "pending"
        and stages["runtime-configuration"]["status"] == "done"
    ):
        stages["maker-validation"] = {
            "status": "needs-maker",
            "message": "Run the Test pane scenario in this realm.",
        }


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
    if result not in {"pass", "fail"}:
        raise ServiceNowRealmError("Test pane result must be pass or fail.")
    if result == "pass" and failure_category is not None:
        raise ServiceNowRealmError(
            "A passing Test pane result cannot have a failure category."
        )
    stages = target["stages"]
    if (
        stages["connections"].get("status") != "done"
        or stages["runtime-configuration"].get("status") != "done"
    ):
        raise ServiceNowRealmError(
            "Complete Connections and Runtime configuration before "
            "recording the Test pane result."
        )
    identity = target["identity"]
    stages["maker-validation"] = {
        "status": "done" if result == "pass" else "blocked",
        "kind": "maker-attestation",
        "promptCategory": prompt_category,
        "result": result,
        "failureCategory": failure_category,
        "recordedAt": _utc_now(),
        "binding": {
            "environmentId": identity["environmentId"],
            "agentId": identity["agentId"],
            "connectionId": stages["connections"].get("connectionId"),
        },
    }
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
    return "in-progress"


def select_realm(
    registry: dict[str, Any],
    realm: str,
    *,
    dev_ready: bool,
) -> None:
    if realm == "dev":
        registry["activeTargetRealm"] = "dev"
        return
    if realm not in PROMOTED_REALMS:
        raise ServiceNowRealmError("Realm must be dev, test, or prod.")
    require_realm_prerequisite(registry, realm, dev_ready=dev_ready)
    if realm not in registry["targets"]:
        raise ServiceNowRealmError(
            f"The {realm.title()} realm has not been discovered yet."
        )
    registry["activeTargetRealm"] = realm


def realm_status(
    registry: Mapping[str, Any],
    *,
    dev_ready: bool,
) -> dict[str, Any]:
    active = str(registry.get("activeTargetRealm") or "dev")
    targets: dict[str, Any] = {
        "dev": {"deploymentStatus": "ready" if dev_ready else "in-progress"}
    }
    for realm in PROMOTED_REALMS:
        targets[realm] = {"deploymentStatus": target_status(registry, realm)}
        recorded = registry["targets"].get(realm)
        if isinstance(recorded, Mapping):
            targets[realm]["identity"] = {
                key: recorded["identity"][key]
                for key in ("environmentId", "agentId", "agentSchemaName")
            }
            targets[realm]["foundationReused"] = recorded["foundationReused"]
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
                "differences",
                "observations",
            ):
                if key in stage:
                    phase[key] = stage[key]
            phases.append(phase)
            if next_phase is None and status != "done":
                next_phase = stage_id
    return {
        "schemaVersion": "servicenow.realm-status.v1",
        "activeTargetRealm": active,
        "targets": targets,
        "phases": phases,
        "nextPhaseId": next_phase,
    }
