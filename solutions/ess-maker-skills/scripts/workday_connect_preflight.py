# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Identity-aware preflight for the Workday connect lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from auth import authenticate, query_all
from install_workday_da_extension import install_workday_package
from workday_connect_auth import (
    WorkdayConnectIdentityError,
    authentication_plan,
    require_identity,
)
from workday_connect_model import load_catalog
from workday_connect_store import WorkdayConnectStore


class WorkdayConnectPreflightError(RuntimeError):
    """Raised when the Workday target cannot be proven safely."""


@dataclass(frozen=True)
class PreflightTarget:
    agent: dict[str, Any]
    environment_id: str | None
    architecture: str
    package_flavor: str
    dataverse_url: str
    foundation_ring: str
    pac_ring: str


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkdayConnectPreflightError(
            f"Required workspace state could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectPreflightError(
            f"Required workspace state must contain an object: {path}"
        )
    return document


def _active_agent(config: dict[str, Any]) -> dict[str, Any]:
    active_slug = str(config.get("activeAgent") or "").strip()
    candidates = config.get("agents")
    if isinstance(candidates, list) and active_slug:
        matches = [
            agent
            for agent in candidates
            if isinstance(agent, dict)
            and str(agent.get("slug") or "") == active_slug
        ]
        if len(matches) == 1:
            return matches[0]
    legacy = config.get("agent")
    if (
        isinstance(legacy, dict)
        and str(legacy.get("slug") or "") == active_slug
    ):
        return legacy
    raise WorkdayConnectPreflightError(
        "Select one setup-complete ESS HR agent before connecting Workday."
    )


def _require_materialized_workspace(
    setup_state: dict[str, Any],
    agent: dict[str, Any],
) -> None:
    if setup_state.get("schema_version") != 4:
        raise WorkdayConnectPreflightError(
            "The selected agent workspace is not on the supported setup schema."
        )
    bot_id = str(agent.get("botId") or "").casefold()
    slug = str(agent.get("slug") or "")
    agents = setup_state.get("agents")
    if not bot_id or not slug or not isinstance(agents, dict):
        raise WorkdayConnectPreflightError(
            "The selected agent is missing canonical workspace identity."
        )
    candidate = next(
        (
            value
            for key, value in agents.items()
            if isinstance(value, dict)
            and (
                str(key).casefold() == bot_id
                or str((value.get("agent") or {}).get("id") or "").casefold()
                == bot_id
            )
            and str(
                (value.get("agent") or {}).get("workspace_slug") or ""
            )
            == slug
        ),
        None,
    )
    if not isinstance(candidate, dict):
        raise WorkdayConnectPreflightError(
            "The selected agent does not have canonical workspace evidence."
        )
    steps = candidate.get("steps")
    setup_07 = steps.get("SETUP-07") if isinstance(steps, dict) else None
    if not isinstance(setup_07, dict) or setup_07.get("state") != "done":
        raise WorkdayConnectPreflightError(
            "Finish the selected agent's workspace setup before connecting "
            "Workday."
        )


def _pac_ring(foundation_ring: str) -> str:
    normalized = str(foundation_ring or "prod").casefold()
    if normalized in {"test", "preprod"}:
        return "preprod"
    if normalized == "prod":
        return "prod"
    raise WorkdayConnectPreflightError(
        f"Unsupported Power Platform ring: {foundation_ring!r}."
    )


def resolve_target(
    workspace_root: Path,
    *,
    dataverse_url: str | None,
    state: dict[str, Any],
    catalog: dict[str, Any] | None = None,
) -> PreflightTarget:
    active_catalog = catalog or load_catalog()
    foundation = _read_json(workspace_root / ".local" / "config.json")
    setup_state = _read_json(
        workspace_root / ".local" / "setup" / "config.json"
    )
    agent = _active_agent(foundation)
    schema = str(agent.get("schemaName") or "").casefold()
    supported = active_catalog["supportedAgents"].get(schema)
    if supported is None:
        if schema in set(active_catalog["unsupportedAgents"]):
            raise WorkdayConnectPreflightError(
                "This Workday lifecycle supports the native ESS HR agent "
                "only. Classic DA and ESS IT agents are not supported."
            )
        raise WorkdayConnectPreflightError(
            "The selected agent is not a supported ESS HR architecture."
        )
    _require_materialized_workspace(setup_state, agent)

    exact_url = (
        str(foundation.get("dataverseEndpoint") or "").strip()
        or str(state.get("scope", {}).get("dataverseUrl") or "").strip()
        or str(dataverse_url or "").strip()
    ).rstrip("/")
    if not exact_url:
        raise WorkdayConnectPreflightError(
            "Select the Dataverse environment that will host the Workday "
            "runtime package."
        )
    if not exact_url.startswith("https://"):
        raise WorkdayConnectPreflightError(
            "The Workday Dataverse environment URL must use HTTPS."
        )
    foundation_ring = str(foundation.get("ring") or "prod").casefold()
    environment_id = str(
        foundation.get("environmentId")
        or (setup_state.get("environment") or {}).get("id")
        or ""
    ).strip()
    return PreflightTarget(
        agent={
            key: agent[key]
            for key in ("slug", "botId", "schemaName", "name")
            if agent.get(key)
        },
        environment_id=environment_id or None,
        architecture=supported["architecture"],
        package_flavor=supported["packageFlavor"],
        dataverse_url=exact_url,
        foundation_ring=foundation_ring,
        pac_ring=_pac_ring(foundation_ring),
    )


def _installed_solutions(
    environment_url: str,
    token: str,
    *,
    query: Callable[..., list[dict[str, Any]]],
    catalog: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    schemas = [
        package["solutionSchemaName"]
        for package in catalog["packages"].values()
    ]
    filter_expression = " or ".join(
        f"uniquename eq '{schema}'" for schema in schemas
    )
    rows = query(
        environment_url,
        token,
        "solutions",
        "solutionid,uniquename,friendlyname,ismanaged,version",
        filter_expression,
    )
    return {
        str(row.get("uniquename") or "").casefold(): row
        for row in rows
        if isinstance(row, dict)
    }


def run_preflight(
    workspace_root: Path,
    *,
    dataverse_url: str | None,
    maker_username: str | None,
    store: WorkdayConnectStore | None = None,
    token_provider: Callable[..., str] = authenticate,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    installer: Callable[..., dict[str, Any]] = install_workday_package,
    identity_provider: Callable[..., dict[str, str]] = require_identity,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_catalog = catalog or load_catalog()
    state_store = store or WorkdayConnectStore(workspace_root)
    state = state_store.initialize()
    stored_maker = str(
        (
            state.get("operators", {}).get("powerPlatformMaker") or {}
        ).get("username")
        or ""
    ).strip()
    intended_maker = str(maker_username or stored_maker or "").strip() or None
    target = resolve_target(
        workspace_root,
        dataverse_url=dataverse_url,
        state=state,
        catalog=active_catalog,
    )
    token = token_provider(
        target.dataverse_url,
        preferred_username=intended_maker,
    )
    try:
        identity = identity_provider(
            token,
            preferred_username=intended_maker,
        )
    except WorkdayConnectIdentityError as exc:
        raise WorkdayConnectPreflightError(str(exc)) from exc
    installed = _installed_solutions(
        target.dataverse_url,
        token,
        query=query,
        catalog=active_catalog,
    )
    package = active_catalog["packages"][target.package_flavor]
    required_schema = package["solutionSchemaName"]
    package_action = "unchanged"
    pac_identity = None
    if required_schema.casefold() not in installed:
        install_result = installer(
            target.dataverse_url,
            target.package_flavor,
            ring=target.pac_ring,
            preferred_username=identity["username"],
        )
        pac_identity = install_result.get("authenticatedAccount")
        if not pac_identity or (
            pac_identity.casefold() != identity["username"].casefold()
        ):
            raise WorkdayConnectPreflightError(
                "PAC package installation did not prove the intended "
                "Environment Maker account."
            )
        installed = _installed_solutions(
            target.dataverse_url,
            token,
            query=query,
            catalog=active_catalog,
        )
        if required_schema.casefold() not in installed:
            raise WorkdayConnectPreflightError(
                "PAC completed, but the required Workday package was not "
                "found during post-install verification."
            )
        package_action = "installed"

    state_store.merge_section(
        "scope",
        {
            "agent": target.agent,
            "dataverseUrl": target.dataverse_url,
            "environmentId": target.environment_id,
            "architecture": target.architecture,
            "packageFlavor": target.package_flavor,
            "ring": target.foundation_ring,
            "vertical": "hr",
        },
    )
    state_store.merge_section(
        "operators",
        {
            "powerPlatformMaker": {
                "username": identity["username"],
                "tenantId": identity["tenantId"],
                "credentialStores": {
                    "dataverse-msal": "verified",
                    "pac": "verified" if pac_identity else "not-required",
                },
            }
        },
    )
    state_store.complete_action(
        "preflight",
        "verify-target",
        evidence={
            "outcome": "passed",
            "environmentUrl": target.dataverse_url,
            "account": identity["username"],
        },
    )
    state_store.complete_action(
        "preflight",
        "verify-package",
        evidence={
            "outcome": "passed",
            "packageSchema": required_schema,
            "packageAction": package_action,
            "pacAccount": pac_identity,
        },
    )
    final_state = state_store.set_phase_status("preflight", "complete")
    return {
        "scope": final_state["scope"],
        "operator": final_state["operators"]["powerPlatformMaker"],
        "package": {
            "flavor": target.package_flavor,
            "schemaName": required_schema,
            "action": package_action,
        },
        "authenticationPlan": authentication_plan(),
        "status": state_store.status(),
    }
