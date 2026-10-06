# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AgentBuilder-backed realm discovery for Workday ALM targets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
import uuid

from agentbuilder import (
    DEFAULT_API_VERSION,
    DEV_REALM,
    PROD_REALM,
    REALM_NAMES,
    TEST_REALM,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    authenticate_agent_inventory,
    derive_environment_host,
    environment_id_from_host,
    list_environments,
    validate_environment_host,
)
from workday_connect_model import load_catalog
from workday_connect_store import WorkdayConnectStore


REALM_VALUES = {
    "dev": DEV_REALM,
    "test": TEST_REALM,
    "prod": PROD_REALM,
}


class WorkdayConnectRealmError(RuntimeError):
    """Raised when a promoted Workday target cannot be proven safely."""


def _normalize_guid(value: Any, label: str) -> str:
    try:
        return str(uuid.UUID(str(value or "")))
    except ValueError as exc:
        raise WorkdayConnectRealmError(f"{label} must be a GUID.") from exc


def _matches_realm(value: Any, realm: int) -> bool:
    return (
        type(value) is int
        and value == realm
        or isinstance(value, str)
        and value.casefold() == REALM_NAMES[realm].casefold()
    )


def _normalize_environment_url(value: str) -> str:
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
        raise WorkdayConnectRealmError(
            "The target Dataverse environment URL must be a safe HTTPS URL."
        )
    return f"https://{parsed.hostname.casefold()}"


def _agent_id(agent: Mapping[str, Any], label: str) -> str:
    return _normalize_guid(
        agent.get("botId") or agent.get("cdsBotId") or agent.get("id"),
        label,
    )


def _environment_url_from_inventory(
    environments: list[dict[str, Any]],
    environment_id: str,
) -> str:
    matches = [
        environment
        for environment in environments
        if str(
            environment.get("id")
            or environment.get("environmentId")
            or ""
        ).casefold()
        == environment_id.casefold()
    ]
    if not matches:
        raise WorkdayConnectRealmError(
            "The target environment is not visible to the signed-in maker."
        )
    if len(matches) != 1:
        raise WorkdayConnectRealmError(
            "Environment inventory returned duplicate records for the target "
            "environment ID."
        )
    environment = matches[0]
    properties = environment.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}
    linked = properties.get("linkedEnvironmentMetadata")
    if not isinstance(linked, Mapping):
        linked = {}
    value = str(
        environment.get("url")
        or environment.get("instanceUrl")
        or linked.get("instanceApiUrl")
        or linked.get("instanceUrl")
        or ""
    ).strip()
    if not value:
        raise WorkdayConnectRealmError(
            "The target environment inventory does not contain a Dataverse "
            "URL."
        )
    return _normalize_environment_url(value)


def _environment_id(environment: Mapping[str, Any]) -> str:
    return str(
        environment.get("id")
        or environment.get("environmentId")
        or ""
    ).strip()


def _environment_display_name(environment: Mapping[str, Any]) -> str:
    properties = environment.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}
    return str(
        environment.get("displayName")
        or environment.get("name")
        or properties.get("displayName")
        or properties.get("environmentName")
        or ""
    ).strip()


def _environment_candidates(
    environments: list[dict[str, Any]],
    *,
    source_environment_id: str,
    environment_id: str | None,
    environment_url: str | None,
    environment_selector: str | None,
) -> list[tuple[str, str, str]]:
    requested_id = str(environment_id or "").strip()
    requested_url = (
        _normalize_environment_url(environment_url)
        if environment_url
        else ""
    )
    selector = str(environment_selector or "").strip().casefold()
    candidates: list[tuple[str, str, str]] = []
    for environment in environments:
        candidate_id = _environment_id(environment)
        if not candidate_id:
            continue
        normalized_id = _normalize_guid(
            candidate_id,
            "Visible environment ID",
        )
        if normalized_id.casefold() == source_environment_id.casefold():
            continue
        try:
            candidate_url = _environment_url_from_inventory(
                [environment],
                normalized_id,
            )
        except WorkdayConnectRealmError:
            continue
        display_name = _environment_display_name(environment)
        if requested_id and normalized_id.casefold() != _normalize_guid(
            requested_id,
            "Target environment ID",
        ).casefold():
            continue
        if requested_url and candidate_url != requested_url:
            continue
        if selector and selector not in {
            normalized_id.casefold(),
            candidate_url.casefold(),
            display_name.casefold(),
        }:
            continue
        candidates.append((normalized_id, candidate_url, display_name))
    return candidates


def _candidate_labels(
    candidates: list[tuple[str, str, str]],
) -> str:
    labels = [
        display_name or environment_url
        for _environment_id_value, environment_url, display_name in candidates
    ]
    return ", ".join(sorted(dict.fromkeys(labels), key=str.casefold))


def discover_realm_target(
    source_client: AgentBuilderClient,
    target_client: AgentBuilderClient,
    *,
    source_agent_id: str,
    source_agent_slug: str,
    realm: str,
    environment_id: str,
    environment_url: str,
    expected_source_family_id: str = "",
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    normalized_realm = str(realm or "").casefold()
    if normalized_realm not in {"test", "prod"}:
        raise WorkdayConnectRealmError(
            "Promoted Workday target discovery supports Test or Prod."
        )
    realm_value = REALM_VALUES[normalized_realm]
    normalized_source_id = _normalize_guid(
        source_agent_id,
        "Recorded Dev agent ID",
    )
    normalized_environment_id = _normalize_guid(
        environment_id,
        "Target environment ID",
    )
    normalized_environment_url = _normalize_environment_url(environment_url)

    realms = source_client.get_realms(normalized_source_id)
    if not _matches_realm(realms.get("routeRealm"), DEV_REALM):
        raise WorkdayConnectRealmError(
            "The recorded Workday source agent is not the Dev realm."
        )
    direct_source = source_client.get_agent(normalized_source_id)
    if (
        _agent_id(direct_source, "Direct Dev agent ID").casefold()
        != normalized_source_id.casefold()
    ):
        raise WorkdayConnectRealmError(
            "Direct Dev lookup returned a different agent identity."
        )
    siblings = realms.get("siblingRealms")
    if not isinstance(siblings, list):
        raise WorkdayConnectRealmError(
            "Agent realm discovery did not return sibling realms."
        )
    matches = [
        sibling
        for sibling in siblings
        if isinstance(sibling, Mapping)
        and _matches_realm(sibling.get("realm"), realm_value)
    ]
    if not matches:
        raise WorkdayConnectRealmError(
            f"The {REALM_NAMES[realm_value]} promotion is not visible yet."
        )
    if len(matches) != 1:
        raise WorkdayConnectRealmError(
            f"Agent realm discovery returned multiple {REALM_NAMES[realm_value]} "
            "targets."
        )
    target_agent_id = _normalize_guid(
        matches[0].get("botId"),
        f"Related {REALM_NAMES[realm_value]} agent ID",
    )

    source_configuration = source_client.get_realm_configuration(
        normalized_source_id,
        DEV_REALM,
    )
    if not _matches_realm(source_configuration.get("realm"), DEV_REALM):
        raise WorkdayConnectRealmError(
            "The recorded source configuration is not the Dev realm."
        )
    if (
        _normalize_guid(
            source_configuration.get("cdsBotId"),
            "Configured Dev agent ID",
        ).casefold()
        != normalized_source_id.casefold()
    ):
        raise WorkdayConnectRealmError(
            "Dev realm configuration returned a different agent identity."
        )
    source_family_id = str(
        source_configuration.get("grsRepositoryId") or ""
    ).strip()
    if not source_family_id:
        raise WorkdayConnectRealmError(
            "Dev realm configuration did not return an ALM-family identity."
        )
    if (
        expected_source_family_id
        and source_family_id.casefold()
        != expected_source_family_id.casefold()
    ):
        raise WorkdayConnectRealmError(
            "The recorded Dev target belongs to a different ALM family."
        )

    direct_target = target_client.get_agent(target_agent_id)
    if _agent_id(
        direct_target,
        f"Direct {REALM_NAMES[realm_value]} agent ID",
    ).casefold() != target_agent_id.casefold():
        raise WorkdayConnectRealmError(
            f"Direct {REALM_NAMES[realm_value]} lookup returned a different "
            "agent identity."
        )
    target_configuration = target_client.get_realm_configuration(
        target_agent_id,
        realm_value,
    )
    if not _matches_realm(target_configuration.get("realm"), realm_value):
        raise WorkdayConnectRealmError(
            f"Target configuration did not identify the "
            f"{REALM_NAMES[realm_value]} realm."
        )
    if (
        _normalize_guid(
            target_configuration.get("cdsBotId"),
            f"Configured {REALM_NAMES[realm_value]} agent ID",
        ).casefold()
        != target_agent_id.casefold()
    ):
        raise WorkdayConnectRealmError(
            f"{REALM_NAMES[realm_value]} configuration returned a different "
            "agent identity."
        )
    target_family_id = str(
        target_configuration.get("grsRepositoryId") or ""
    ).strip()
    if target_family_id.casefold() != source_family_id.casefold():
        raise WorkdayConnectRealmError(
            "The promoted target belongs to a different ALM family."
        )
    schema_name = str(
        target_configuration.get("schemaName")
        or direct_target.get("schemaName")
        or ""
    ).strip()
    supported_agents = (catalog or load_catalog())["supportedAgents"]
    if schema_name.casefold() not in supported_agents:
        raise WorkdayConnectRealmError(
            "The promoted target is not the supported ESS HR agent."
        )
    commit_sha = str(
        target_configuration.get("commitSha") or ""
    ).strip()
    if not commit_sha:
        raise WorkdayConnectRealmError(
            "The promoted target does not have deployed package evidence."
        )
    if (
        str(source_client.tenant_id).casefold()
        != str(target_client.tenant_id).casefold()
    ):
        raise WorkdayConnectRealmError(
            "The Dev and promoted target environments belong to different "
            "Microsoft Entra tenants."
        )
    if not source_agent_slug:
        raise WorkdayConnectRealmError(
            "The recorded Dev agent slug is required for target persistence."
        )

    return {
        "environmentId": normalized_environment_id,
        "environmentUrl": normalized_environment_url,
        "tenantId": str(target_client.tenant_id),
        "agentId": target_agent_id,
        "agentSchemaName": schema_name,
        "agentSlug": source_agent_slug,
        "almFamilyId": target_family_id,
        "commitSha": commit_sha,
        "sourceAgentId": normalized_source_id,
    }


def _read_foundation(root: Path) -> dict[str, Any]:
    path = root.resolve() / ".local" / "config.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkdayConnectRealmError(
            "Foundation setup state could not be read."
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectRealmError(
            "Foundation setup state must contain an object."
        )
    return document


def discover_and_record_realm_target(
    root: Path,
    store: WorkdayConnectStore,
    *,
    realm: str,
    environment_id: str | None = None,
    environment_url: str | None = None,
    environment_selector: str | None = None,
    account_hint: str | None = None,
    authenticator: Callable[..., tuple[str, str]] = authenticate_agent_inventory,
    client_factory: Callable[..., AgentBuilderClient] = AgentBuilderClient,
    environment_loader: Callable[..., list[dict[str, Any]]] = list_environments,
) -> dict[str, Any]:
    state = store.load()
    dev_target = state["targets"]["dev"]
    if not isinstance(dev_target, Mapping):
        raise WorkdayConnectRealmError(
            "Complete Dev Workday setup before configuring a promoted realm."
        )
    source_identity = dev_target["identity"]
    source_agent_id = str(
        source_identity.get("agentId")
        or ((state.get("scope") or {}).get("agent") or {}).get("botId")
        or ""
    )
    source_agent_slug = str(
        source_identity.get("agentSlug")
        or ((state.get("scope") or {}).get("agent") or {}).get("slug")
        or ""
    )
    foundation = _read_foundation(root)
    ring = str(foundation.get("ring") or "prod").casefold()
    source_environment_id = str(
        source_identity.get("environmentId")
        or foundation.get("environmentId")
        or ""
    )
    source_host_value = str(
        foundation.get("powerPlatformApiEndpoint") or ""
    ).strip()
    try:
        source_host = validate_environment_host(source_host_value, ring)
        if (
            environment_id_from_host(source_host, ring).casefold()
            != _normalize_guid(
                source_environment_id,
                "Recorded Dev environment ID",
            ).casefold()
        ):
            raise WorkdayConnectRealmError(
                "The recorded Dev AgentBuilder host does not match the "
                "recorded Dev environment ID."
            )
    except WorkdayConnectRealmError:
        raise
    except ValueError:
        source_host = derive_environment_host(source_environment_id, ring)
    maker = (state.get("operators") or {}).get("powerPlatformMaker") or {}
    try:
        token, tenant_id = authenticator(
            ring,
            account_hint=(
                account_hint
                or str(maker.get("username") or "")
                or None
            ),
            cache_path=root.resolve()
            / ".local"
            / ".agentbuilder_token_cache.bin",
        )
        recorded_source_tenant = str(
            source_identity.get("tenantId") or ""
        ).strip()
        if (
            recorded_source_tenant
            and recorded_source_tenant.casefold() != tenant_id.casefold()
        ):
            raise WorkdayConnectRealmError(
                "The signed-in Microsoft Entra tenant does not match the "
                "recorded Dev target."
            )
        api_version = str(
            foundation.get("agentBuilderApiVersion")
            or DEFAULT_API_VERSION
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
            tenant_id=tenant_id,
            api_version=api_version,
        )
        candidates = _environment_candidates(
            environments,
            source_environment_id=_normalize_guid(
                source_environment_id,
                "Recorded Dev environment ID",
            ),
            environment_id=environment_id,
            environment_url=environment_url,
            environment_selector=environment_selector,
        )
        explicit_selection = bool(
            environment_id or environment_url or environment_selector
        )
        if not candidates:
            if environment_id and environment_url:
                raise WorkdayConnectRealmError(
                    "The supplied Dataverse URL does not match the URL proven "
                    "for the target environment ID."
                )
            raise WorkdayConnectRealmError(
                "The promoted Workday target environment is not visible. "
                "Confirm maker access or select the environment by name or URL."
            )
        discovered: list[dict[str, str]] = []
        for candidate_id, candidate_url, _display_name in candidates:
            target_client = client_factory(
                derive_environment_host(candidate_id, ring),
                token,
                ring=ring,
                tenant_id=tenant_id,
                api_version=source_client.api_version,
            )
            try:
                discovered.append(
                    discover_realm_target(
                        source_client,
                        target_client,
                        source_agent_id=source_agent_id,
                        source_agent_slug=source_agent_slug,
                        realm=realm,
                        environment_id=candidate_id,
                        environment_url=candidate_url,
                        expected_source_family_id=str(
                            source_identity.get("almFamilyId") or ""
                        ),
                    )
                )
            except AgentBuilderHTTPError as exc:
                if not explicit_selection and exc.status_code == 404:
                    continue
                raise
        if len(discovered) != 1:
            labels = _candidate_labels(candidates)
            if not discovered:
                detail = (
                    " No matching promoted agent was found in the selected "
                    "environment."
                    if explicit_selection
                    else ""
                )
            else:
                detail = " More than one environment matched the promoted agent."
            choices = f" Available environments: {labels}." if labels else ""
            raise WorkdayConnectRealmError(
                "Automatic promoted-target discovery could not identify one "
                f"{str(realm).title()} environment.{detail}{choices} "
                "Select the environment by name or URL and retry."
            )
        identity = discovered[0]
    except WorkdayConnectRealmError:
        raise
    except (AgentBuilderError, ValueError) as exc:
        raise WorkdayConnectRealmError(
            "The promoted Workday target could not be verified. Confirm "
            "maker access, environment selection, and deployment state."
        ) from exc
    store.record_target_discovery(
        str(realm).casefold(),
        identity,
        ring=ring,
    )
    store.activate_target(str(realm).casefold())
    persisted, foundation_reused = (
        store.initialize_promoted_target_from_foundation()
    )
    return {
        "realm": str(realm).casefold(),
        "targetStatus": persisted["targets"][
            str(realm).casefold()
        ]["deploymentStatus"],
        "foundationReused": foundation_reused,
        "status": store.status(),
    }


def revalidate_active_realm_target(
    root: Path,
    store: WorkdayConnectStore,
    *,
    account_hint: str | None = None,
    authenticator: Callable[..., tuple[str, str]] = authenticate_agent_inventory,
    client_factory: Callable[..., AgentBuilderClient] = AgentBuilderClient,
    environment_loader: Callable[..., list[dict[str, Any]]] = list_environments,
) -> dict[str, Any]:
    """Reread the exact promoted target identity immediately before mutation."""
    state = store.load()
    realm = str(state.get("activeTargetRealm") or "dev").casefold()
    if realm == "dev":
        return {"realm": "dev", "revalidated": False}
    target = (state.get("targets") or {}).get(realm)
    identity = (
        target.get("identity")
        if isinstance(target, Mapping)
        and isinstance(target.get("identity"), Mapping)
        else {}
    )
    required = {
        "environmentId": str(identity.get("environmentId") or "").strip(),
        "environmentUrl": str(identity.get("environmentUrl") or "").strip(),
        "tenantId": str(identity.get("tenantId") or "").strip(),
        "agentId": str(identity.get("agentId") or "").strip(),
        "almFamilyId": str(identity.get("almFamilyId") or "").strip(),
        "commitSha": str(identity.get("commitSha") or "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise WorkdayConnectRealmError(
            f"The active {realm.title()} target identity is incomplete: "
            + ", ".join(sorted(missing))
        )
    discover_and_record_realm_target(
        root,
        store,
        realm=realm,
        environment_id=required["environmentId"],
        environment_url=required["environmentUrl"],
        account_hint=account_hint,
        authenticator=authenticator,
        client_factory=client_factory,
        environment_loader=environment_loader,
    )
    refreshed = store.load()["targets"][realm]["identity"]
    changed = [
        key
        for key, expected in required.items()
        if str(refreshed.get(key) or "").casefold() != expected.casefold()
    ]
    if changed:
        raise WorkdayConnectRealmError(
            f"The active {realm.title()} target changed after approval: "
            + ", ".join(sorted(changed))
            + ". Generate and approve a new runtime plan."
        )
    return {"realm": realm, "revalidated": True}
