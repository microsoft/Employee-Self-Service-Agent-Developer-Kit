# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Identity-aware preflight for the Workday connect lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from auth import authenticate, query_all
from install_workday_da_extension import (
    PacCliError,
    install_workday_package,
    resolve_pac_executable,
)
from workday_connect_auth import (
    WorkdayConnectIdentityError,
    authentication_plan,
    require_identity,
)
from workday_connect_model import load_catalog, plan_hash
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


def _cached_dataverse_url(
    workspace_root: Path,
    *,
    environment_id: str,
    ring: str,
) -> str:
    if not environment_id:
        return ""
    inventory = _read_json(
        workspace_root
        / ".local"
        / "setup"
        / f"environment-list-{ring}.json"
    )
    environments = inventory.get("environments")
    if not isinstance(environments, list):
        return ""
    matches = [
        environment
        for environment in environments
        if isinstance(environment, dict)
        and str(environment.get("id") or "").casefold()
        == environment_id.casefold()
    ]
    if len(matches) > 1:
        raise WorkdayConnectPreflightError(
            "Setup environment inventory contains duplicate records for "
            f"environment {environment_id}."
        )
    if not matches:
        return ""
    match = matches[0]
    properties = match.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    linked = properties.get("linkedEnvironmentMetadata")
    if not isinstance(linked, dict):
        linked = {}
    return str(
        match.get("url")
        or match.get("instanceUrl")
        or linked.get("instanceApiUrl")
        or linked.get("instanceUrl")
        or ""
    ).strip()


def _pac_dataverse_url(
    environment_id: str,
    *,
    pac_resolver: Callable[[], Path],
    runner: Callable[..., subprocess.CompletedProcess],
) -> str:
    if not environment_id:
        return ""
    try:
        pac = pac_resolver()
    except PacCliError:
        return ""
    try:
        result = runner(
            [
                str(pac),
                "org",
                "who",
                "--environment",
                environment_id,
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkdayConnectPreflightError(
            "PAC did not resolve the setup environment within one minute."
        ) from exc
    if result.returncode != 0:
        return ""
    try:
        identity = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise WorkdayConnectPreflightError(
            "PAC returned invalid environment identity JSON."
        ) from exc
    if not isinstance(identity, dict):
        raise WorkdayConnectPreflightError(
            "PAC returned an invalid environment identity result."
        )
    observed_id = str(identity.get("EnvironmentId") or "").strip()
    if observed_id.casefold() != environment_id.casefold():
        raise WorkdayConnectPreflightError(
            "PAC resolved a different environment than setup recorded."
        )
    return str(identity.get("OrgUrl") or "").strip()


def _normalize_dataverse_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def resolve_target(
    workspace_root: Path,
    *,
    dataverse_url: str | None,
    state: dict[str, Any],
    catalog: dict[str, Any] | None = None,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    pac_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
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

    foundation_ring = str(foundation.get("ring") or "prod").casefold()
    foundation_environment_id = str(
        foundation.get("environmentId") or ""
    ).strip()
    setup_environment_id = str(
        (setup_state.get("environment") or {}).get("id") or ""
    ).strip()
    if (
        foundation_environment_id
        and setup_environment_id
        and foundation_environment_id.casefold()
        != setup_environment_id.casefold()
    ):
        raise WorkdayConnectPreflightError(
            "Foundation and setup state record different Power Platform "
            "environment IDs. Refresh setup before continuing."
        )
    environment_id = foundation_environment_id or setup_environment_id
    if not environment_id:
        raise WorkdayConnectPreflightError(
            "The setup state does not contain an exact Power Platform "
            "environment ID."
        )

    foundation_url = str(
        foundation.get("dataverseEndpoint") or ""
    ).strip()
    inventory_url = _cached_dataverse_url(
        workspace_root,
        environment_id=environment_id,
        ring=foundation_ring,
    )
    state_scope = state.get("scope") or {}
    stored_environment_id = str(
        state_scope.get("environmentId") or ""
    ).strip()
    stored_url = (
        str(state_scope.get("dataverseUrl") or "").strip()
        if stored_environment_id.casefold() == environment_id.casefold()
        else ""
    )
    supplied_url = str(dataverse_url or "").strip()

    authoritative_urls = [
        value for value in (foundation_url, inventory_url) if value
    ]
    if len(
        {_normalize_dataverse_url(value) for value in authoritative_urls}
    ) > 1:
        raise WorkdayConnectPreflightError(
            "Foundation setup and environment inventory disagree on the "
            "Dataverse URL for the recorded environment ID. Refresh setup "
            "before continuing."
        )
    exact_url = foundation_url or inventory_url
    if not exact_url:
        pac_url = _pac_dataverse_url(
            environment_id,
            pac_resolver=pac_resolver,
            runner=pac_runner,
        )
        if not pac_url:
            raise WorkdayConnectPreflightError(
                "PAC could not prove the Dataverse URL for the recorded "
                "environment ID. Refresh Power Platform authentication and "
                "try again."
            )
        exact_url = pac_url
    for candidate, source in (
        (stored_url, "stored Workday state"),
        (supplied_url, "supplied Dataverse URL"),
    ):
        if candidate and (
            _normalize_dataverse_url(candidate)
            != _normalize_dataverse_url(exact_url)
        ):
            raise WorkdayConnectPreflightError(
                f"The {source} does not match the URL proven for the setup "
                "environment ID."
            )
    exact_url = exact_url.rstrip("/")
    if not exact_url:
        raise WorkdayConnectPreflightError(
            "The setup environment does not have a resolved Dataverse URL. "
            "Refresh environment inventory for the recorded environment ID "
            "or provide that environment's exact Dataverse URL."
        )
    if not exact_url.casefold().startswith("https://"):
        raise WorkdayConnectPreflightError(
            "The Workday Dataverse environment URL must use HTTPS."
        )
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
    identity_provider: Callable[..., dict[str, str]] = require_identity,
    catalog: dict[str, Any] | None = None,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    pac_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    defer_completion: bool = False,
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
    intended_maker = str(
        maker_username or stored_maker or ""
    ).strip() or None
    target = resolve_target(
        workspace_root,
        dataverse_url=dataverse_url,
        state=state,
        catalog=active_catalog,
        pac_resolver=pac_resolver,
        pac_runner=pac_runner,
    )
    try:
        token = token_provider(
            target.dataverse_url,
            preferred_username=intended_maker,
        )
    except SystemExit as exc:
        raise WorkdayConnectPreflightError(
            "Dataverse authentication did not complete."
        ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkdayConnectPreflightError(
            f"Dataverse authentication failed: {exc}"
        ) from exc
    try:
        identity = identity_provider(
            token,
            preferred_username=intended_maker,
        )
    except WorkdayConnectIdentityError as exc:
        raise WorkdayConnectPreflightError(str(exc)) from exc
    try:
        installed = _installed_solutions(
            target.dataverse_url,
            token,
            query=query,
            catalog=active_catalog,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkdayConnectPreflightError(
            f"Dataverse package discovery failed: {exc}"
        ) from exc
    package = active_catalog["packages"][target.package_flavor]
    required_schema = package["solutionSchemaName"]
    package_installed = required_schema.casefold() in installed

    existing_operator = (
        state_store.load().get("operators", {}).get("powerPlatformMaker") or {}
    )
    existing_credential_stores = (
        existing_operator.get("credentialStores") or {}
        if isinstance(existing_operator, dict)
        else {}
    )
    pac_status = existing_credential_stores.get("pac") or "not-required"
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
            "entraTenantId": identity["tenantId"],
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
                    "pac": pac_status,
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
    state_store.record_lifecycle_event(
        "roles-attested",
        phase="preflight",
        outcome="success",
        once_per_lifecycle=True,
    )
    if not defer_completion:
        state_store.set_phase_status("preflight", "complete")
    final_state = state_store.load()
    return {
        "scope": final_state["scope"],
        "operator": final_state["operators"]["powerPlatformMaker"],
        "package": {
            "flavor": target.package_flavor,
            "schemaName": required_schema,
            "installed": package_installed,
            "action": "unchanged" if package_installed else "deferred",
        },
        "verificationChecks": [
            {
                "name": "Selected ESS HR agent and Power Platform environment",
                "status": "verified",
            },
            {
                "name": "Dataverse access, maker account, and Entra tenant",
                "status": "verified",
            },
        ],
        "authenticationPlan": authentication_plan(),
        "status": state_store.status(),
    }


def prepare_connections_package(
    workspace_root: Path,
    *,
    store: WorkdayConnectStore | None = None,
    approved_install_hash: str | None = None,
    plan_verifier: Callable[[dict[str, Any], str], Any] | None = None,
    token_provider: Callable[..., str] = authenticate,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    installer: Callable[..., dict[str, Any]] = install_workday_package,
    identity_provider: Callable[..., dict[str, str]] = require_identity,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Install and verify the selected package at the start of Connections."""
    active_catalog = catalog or load_catalog()
    state_store = store or WorkdayConnectStore(workspace_root)
    state = state_store.load()
    if state["phases"]["workday-admin"]["status"] != "complete":
        raise WorkdayConnectPreflightError(
            "Complete the Microsoft Entra and Workday administrator phases "
            "before installing the Workday package."
        )
    scope = state.get("scope") or {}
    maker = (
        (state.get("operators") or {}).get("powerPlatformMaker") or {}
    )
    environment_url = str(scope.get("dataverseUrl") or "").strip().rstrip("/")
    environment_id = str(scope.get("environmentId") or "").strip()
    package_flavor = str(scope.get("packageFlavor") or "").strip()
    ring = str(scope.get("ring") or "prod").casefold()
    maker_username = str(maker.get("username") or "").strip()
    if not all(
        (
            environment_url,
            environment_id,
            package_flavor,
            maker_username,
        )
    ):
        raise WorkdayConnectPreflightError(
            "Preflight target evidence is incomplete. Rerun Preflight before "
            "preparing Connections."
        )
    package = active_catalog["packages"].get(package_flavor)
    if not isinstance(package, dict):
        raise WorkdayConnectPreflightError(
            f"Unsupported Workday package flavor: {package_flavor}."
        )
    required_schema = str(package["solutionSchemaName"])
    try:
        token = token_provider(
            environment_url,
            preferred_username=maker_username,
        )
    except SystemExit as exc:
        raise WorkdayConnectPreflightError(
            "Dataverse authentication did not complete."
        ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkdayConnectPreflightError(
            f"Dataverse authentication failed: {exc}"
        ) from exc
    try:
        identity = identity_provider(
            token,
            preferred_username=maker_username,
        )
        installed = _installed_solutions(
            environment_url,
            token,
            query=query,
            catalog=active_catalog,
        )
    except WorkdayConnectIdentityError as exc:
        raise WorkdayConnectPreflightError(str(exc)) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkdayConnectPreflightError(
            f"Dataverse package discovery failed: {exc}"
        ) from exc

    install_plan = {
        "phase": "connections",
        "scope": {
            "environmentId": environment_id,
            "dataverseUrl": environment_url,
            "agent": {
                key: (scope.get("agent") or {}).get(key)
                for key in ("slug", "botId", "schemaName")
            },
            "makerUsername": identity["username"],
        },
        "package": {
            "flavor": package_flavor,
            "schemaName": required_schema,
        },
        "actions": [
            "Install the supported Workday runtime package",
            "Reread Dataverse to verify the package installation",
        ],
    }
    package_action = "unchanged"
    pac_identity = None
    if required_schema.casefold() not in installed:
        if not approved_install_hash:
            return {
                "requiresApproval": True,
                "plan": {
                    **install_plan,
                    "planHash": plan_hash(install_plan),
                },
                "approvalSummary": {
                    "environmentUrl": environment_url,
                    "agent": (
                        (scope.get("agent") or {}).get("name")
                        or (scope.get("agent") or {}).get("slug")
                    ),
                    "makerAccount": identity["username"],
                    "packageSchema": required_schema,
                    "actions": install_plan["actions"],
                },
                "status": state_store.status(),
            }
        if plan_verifier is None:
            raise WorkdayConnectPreflightError(
                "Package installation requires a stored approved plan."
            )
        plan_verifier(install_plan, approved_install_hash)
        try:
            install_result = installer(
                environment_url,
                package_flavor,
                ring=("preprod" if ring in {"test", "preprod"} else "prod"),
                preferred_username=identity["username"],
            )
        except (OSError, PacCliError, RuntimeError) as exc:
            raise WorkdayConnectPreflightError(
                f"Workday package installation failed: {exc}"
            ) from exc
        pac_identity = str(
            install_result.get("authenticatedAccount") or ""
        ).strip()
        if pac_identity.casefold() != identity["username"].casefold():
            raise WorkdayConnectPreflightError(
                "PAC package installation did not prove the intended "
                "Environment Maker account."
            )
        try:
            installed = _installed_solutions(
                environment_url,
                token,
                query=query,
                catalog=active_catalog,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkdayConnectPreflightError(
                f"Post-install package verification failed: {exc}"
            ) from exc
        if required_schema.casefold() not in installed:
            raise WorkdayConnectPreflightError(
                "PAC completed, but the required Workday package was not "
                "found during post-install verification."
            )
        package_action = "installed"

    if pac_identity:
        state_store.record_operator_credential_store(
            "powerPlatformMaker",
            "pac",
            "verified",
        )
    state_store.complete_action(
        "connections",
        "verify-package",
        evidence={
            "outcome": "passed",
            "packageSchema": required_schema,
            "packageInstalled": True,
            "pacAccount": pac_identity or None,
        },
    )
    return {
        "requiresApproval": False,
        "verified": True,
        "package": {
            "flavor": package_flavor,
            "schemaName": required_schema,
            "action": package_action,
        },
        "status": state_store.status(),
    }
