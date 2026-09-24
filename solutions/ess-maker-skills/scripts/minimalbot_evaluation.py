# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""MinimalBot (Dataverse-free) evaluation transport for the ESS Maker Kit.

Copilot Studio agents that run on Cosmos-backed "MinimalBot" environments do
not have a linked Dataverse database, so the classic Dataverse Web API used by
``push.py`` / ``evaluation_runs.py`` cannot reach them. This module speaks the
Test Power Platform MinimalBot components API instead:

  * push  -> POST (read + changeToken) -> PUT (BotComponentInsert change set)
             -> POST (verify) against
             ``{env-host}/copilotstudio/minimalBots/api/{botId}/components``
  * run   -> discover the shared_microsoftcopilotstudio connection, then POST
             ``.../makerevaluation/testsets/{id}/run``.

Detection (see :func:`is_minimalbot`) requires the *explicit* native DA-GA
markers ``releaseLine == "da"`` or ``powerPlatformApiEndpoint`` plus an
``environmentId`` and no ``dataverseEndpoint``. The Power Platform ring
(test / preprod / prod) is derived per-agent from ``powerPlatformApiEndpoint``
(see :func:`ring_for_config`), so a prod agent talks to the prod data plane
rather than a hardcoded TEST ring.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

try:
    import msal
except ImportError:  # pragma: no cover - dependency guard mirrors siblings
    raise SystemExit("ERROR: 'msal' package not found. Run: pip install msal")

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover - dependency guard mirrors siblings
    raise SystemExit("ERROR: 'requests' package not found. Run: pip install requests")

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard mirrors siblings
    raise SystemExit(
        "ERROR: 'PyYAML' package not found. Run: pip install -r scripts/requirements.txt"
    )

from agentbuilder import RING_CONFIG, ring_from_environment_host


# Shared public client ID used across the ADK's MSAL flows (matches auth.py).
CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
# Default ring for a hand-constructed client. Real flows derive the ring from
# the agent's ``powerPlatformApiEndpoint`` (see :func:`ring_for_config`), so a
# prod agent talks to the prod data plane instead of always the TEST ring.
DEFAULT_RING = "test"
# Retained for backward compatibility; prefer the per-ring helpers below.
PPAPI_SCOPE = f"{RING_CONFIG[DEFAULT_RING]['audience']}/.default"
PPAPI_BASE = str(RING_CONFIG[DEFAULT_RING]["audience"])
COMPONENTS_API_VERSION = "2022-03-01-preview"
MAKEREVAL_API_VERSION = "2024-10-01"
MCS_CONNECTOR = "shared_microsoftcopilotstudio"
_TOKEN_CACHE_PATH = os.path.join(".local", ".token_cache.bin")
_EVAL_KINDS = {"EvaluationSet", "EvaluationData"}

# Shared session with bounded retry-with-backoff, mirroring auth.py /
# powerplatform_client.py. Unlike those read-only clients this path also issues
# mutating PUT (component insert) and POST (run) verbs, so retry safety matters:
#   * status retries (429/5xx) are safe for every verb — the server returned a
#     definitive "did not act" response, so replaying can't duplicate work.
#   * connect retries are safe — the request never reached the server.
#   * read retries are DISABLED (read=0): once a request is on the wire we must
#     not replay it, because a lost response after a successful insert/run would
#     otherwise duplicate the mutation. The component insert is additionally
#     guarded by an optimistic-concurrency changeToken.
_RETRY = Retry(
    total=3,
    connect=3,
    read=0,
    status=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=None,  # apply the above to every verb, incl. POST/PUT
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


class MinimalBotEvaluationError(RuntimeError):
    """Raised when a MinimalBot evaluation operation cannot be completed."""


def is_minimalbot(config: dict[str, Any]) -> bool:
    """Return True when the agent uses the Dataverse-free (MinimalBot) transport.

    Detection keys on the *explicit* native DA-GA markers written by
    ``setup_existing_da.py`` — ``releaseLine == "da"`` or a
    ``powerPlatformApiEndpoint`` — combined with the absence of a usable
    ``dataverseEndpoint`` and the presence of an ``environmentId``.

    Keying on an explicit marker (rather than merely "no ``dataverseEndpoint``")
    means a classic Dataverse agent whose config is momentarily missing its
    endpoint is never misrouted to the MinimalBot data plane, and the transport
    can target the ring named by ``powerPlatformApiEndpoint`` instead of a
    hardcoded ring.
    """
    if not isinstance(config, dict):
        return False
    if str(config.get("dataverseEndpoint") or "").strip():
        return False
    if not _environment_id(config):
        return False
    return _is_native_da(config)


def _is_native_da(config: dict[str, Any]) -> bool:
    """True when the config carries an explicit native DA-GA transport marker."""
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    if str(config.get("releaseLine") or "").strip().casefold() == "da":
        return True
    if str(agent.get("releaseLine") or "").strip().casefold() == "da":
        return True
    return bool(str(config.get("powerPlatformApiEndpoint") or "").strip())


def ring_for_config(config: dict[str, Any]) -> str:
    """Return the Power Platform ring (test/preprod/prod) for this agent.

    Derived from ``powerPlatformApiEndpoint`` via the same suffix map
    ``agentbuilder`` uses. Falls back to ``prod`` when the endpoint is absent
    or unrecognised so a real agent is never assumed to be on the TEST ring.
    """
    if not isinstance(config, dict):
        return "prod"
    endpoint = str(config.get("powerPlatformApiEndpoint") or "").strip()
    if not endpoint:
        return "prod"
    try:
        return ring_from_environment_host(endpoint)
    except ValueError:
        return "prod"


def _api_base_for_ring(ring: str) -> str:
    config = RING_CONFIG.get(ring) or RING_CONFIG[DEFAULT_RING]
    return str(config["audience"])


def _scope_for_ring(ring: str) -> str:
    return f"{_api_base_for_ring(ring)}/.default"


def _agent_backend_for_ring(ring: str) -> str | None:
    """Cosmos is the Dataverse-free MinimalBot backend on the TEST ring."""
    return "cosmos" if ring == "test" else None


def _environment_id(config: dict[str, Any]) -> str:
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    # Prefer the active agent's own environmentId over the top-level value so a
    # stale global carried forward from a previously onboarded agent cannot
    # mask the environment the active agent actually lives in. This matches the
    # precedence used by fetch_and_setup._resolve_refresh_target.
    return str(
        agent.get("environmentId")
        or config.get("environmentId")
        or ""
    ).strip()


def _tenant_id(config: dict[str, Any]) -> str:
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    return str(
        config.get("tenantId")
        or agent.get("tenantId")
        or "organizations"
    ).strip() or "organizations"


def _claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _environment_host(environment_id: str, ring: str = DEFAULT_RING) -> str:
    """Derive the environment API host from an environment GUID for ``ring``.

    Copilot Studio addresses each environment at
    ``https://{split-guid}.{host_suffix}`` where ``host_suffix`` and the split
    index are ring-specific (see ``agentbuilder.RING_CONFIG``). Needs no
    Dataverse instance URL.
    """
    config = RING_CONFIG.get(ring) or RING_CONFIG[DEFAULT_RING]
    suffix = str(config["host_suffix"])
    primary = int(config["primary_split"])
    compact = environment_id.replace("-", "")
    return f"https://{compact[:primary]}.{compact[primary:]}.{suffix}"


def _wire_kinds(value: Any) -> Any:
    """Convert workspace ``kind`` discriminators to JSON ``$kind``."""
    if isinstance(value, dict):
        return {
            "$kind" if key == "kind" else key: _wire_kinds(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_wire_kinds(child) for child in value]
    return value


def _folder_matches_globs(folder: Path, root: Path, only_globs: list[str]) -> bool:
    """True if any ``*.mcs.yml`` in ``folder`` matches one of ``only_globs``.

    ``only_globs`` are agent-root-relative, forward-slash patterns (the same
    ones ``push.py --only`` builds and ``push.matches_only`` consumes), so the
    folder's files are compared as forward-slash paths relative to ``root``.
    """
    for path in folder.glob("*.mcs.yml"):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        if any(fnmatch.fnmatch(rel, glob) for glob in only_globs):
            return True
    return False


def _safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return name or fallback


def _schema_name(stem: str, component_id: str) -> str:
    safe_stem = re.sub(r"[^a-z0-9]+", "_", stem.casefold()).strip("_")
    safe_stem = safe_stem or "evaluation"
    suffix = component_id.replace("-", "")[:8]
    return f"mspva_{safe_stem[:70]}_{suffix}"


def _component_id(change: dict[str, Any]) -> str:
    return str((change.get("component") or {}).get("id") or "")


def _component_name(component: dict[str, Any]) -> str:
    definition = component.get("definition") or {}
    return str(
        definition.get("displayName")
        or component.get("displayName")
        or component.get("schemaName")
        or component.get("id")
        or "evaluation"
    )


def _connection_id(connection: dict[str, Any]) -> str:
    return str(
        connection.get("name")
        or connection.get("connectionId")
        or connection.get("id")
        or ""
    ).rstrip("/").rsplit("/", 1)[-1]


def acquire_test_pp_token(
    tenant_id: str, scope: str | None = None
) -> tuple[str, str]:
    """Acquire a Power Platform token, reusing the shared MSAL cache.

    Returns ``(access_token, signed_in_username)``. ``scope`` selects the ring
    (defaults to the TEST ring for backward compatibility); real flows pass the
    ring-appropriate ``.default`` scope. Shared by the MinimalBot evaluation and
    install transports so both speak Power Platform through a single MSAL
    implementation (interactive fallback + cache persistence).
    """
    tenant_id = tenant_id or "organizations"
    scope = scope or _scope_for_ring(DEFAULT_RING)
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    cache = msal.SerializableTokenCache()
    if os.path.exists(_TOKEN_CACHE_PATH):
        with open(_TOKEN_CACHE_PATH, "r", encoding="utf-8") as handle:
            cache.deserialize(handle.read())

    app = msal.PublicClientApplication(
        CLIENT_ID, authority=authority, token_cache=cache
    )
    accounts = app.get_accounts()
    selected_account = accounts[0] if accounts else None
    result = None
    if selected_account:
        result = app.acquire_token_silent([scope], account=selected_account)
    if not result or "access_token" not in result:
        print("Opening browser for Power Platform sign-in...")
        result = app.acquire_token_interactive(
            [scope], prompt="select_account"
        )
    if "access_token" not in result:
        # Don't echo error_description (CWE-209); mirror auth.py.
        error = result.get("error", "unknown_error")
        raise MinimalBotEvaluationError(
            f"Power Platform authentication failed ({error})."
        )

    if cache.has_state_changed:
        os.makedirs(".local", exist_ok=True)
        try:
            os.chmod(".local", 0o700)
        except OSError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(_TOKEN_CACHE_PATH, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(cache.serialize())

    token = result["access_token"]
    claims = result.get("id_token_claims") or {}
    username = str(
        claims.get("preferred_username")
        or claims.get("upn")
        or (selected_account or {}).get("username")
        or (_claims(token).get("preferred_username") if token else "")
        or ""
    )
    return token, username


class MinimalBotEvaluationClient:
    """Push and run Copilot Studio evaluations without Dataverse.

    Construct from ``.local/config.json`` via :meth:`from_config`, call
    :meth:`authenticate`, then :meth:`push_agent_evaluations`,
    :meth:`list_test_sets`, or :meth:`run_test_set`.
    """

    def __init__(
        self,
        environment_id: str,
        bot_id: str,
        tenant_id: str,
        *,
        ring: str = DEFAULT_RING,
        host: str | None = None,
        api_base: str | None = None,
        scope: str | None = None,
        agent_backend: str | None = None,
    ):
        if not environment_id:
            raise MinimalBotEvaluationError(
                "environmentId is missing from .local/config.json."
            )
        if not bot_id:
            raise MinimalBotEvaluationError(
                "agent.botId is missing from .local/config.json."
            )
        self.environment_id = environment_id
        self.bot_id = bot_id
        self.tenant_id = tenant_id or "organizations"
        self.ring = ring
        self.host = host or _environment_host(environment_id, ring)
        self.api_base = api_base or _api_base_for_ring(ring)
        self.scope = scope or _scope_for_ring(ring)
        self.agent_backend = (
            agent_backend if agent_backend is not None
            else _agent_backend_for_ring(ring)
        )
        self._token: str | None = None
        self.signed_in_username: str | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MinimalBotEvaluationClient":
        agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
        return cls(
            environment_id=_environment_id(config),
            bot_id=str(agent.get("botId") or "").strip(),
            tenant_id=_tenant_id(config),
            ring=ring_for_config(config),
        )

    # -- auth ---------------------------------------------------------------
    def authenticate(self) -> str:
        """Acquire a Power Platform token for this ring, reusing the MSAL cache."""
        self._token, self.signed_in_username = acquire_test_pp_token(
            self.tenant_id, scope=self.scope
        )
        return self._token

    def _require_token(self) -> str:
        if not self._token:
            raise MinimalBotEvaluationError("Call authenticate() first.")
        return self._token

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        operation: str = "request",
    ) -> tuple[requests.Response, Any]:
        auth_value = " ".join(("Bearer", self._require_token()))
        try:
            response = _SESSION.request(
                method,
                url,
                headers={
                    "Authorization": auth_value,
                    "Content-Type": "application/json",
                },
                json=body,
                params=params,
                timeout=120,
            )
        except requests.RequestException as exc:
            # Translate transport failures (timeout, DNS, connection reset,
            # exhausted retries on a transient 429/5xx) into the module's error
            # type so callers get operation context instead of a raw traceback.
            raise MinimalBotEvaluationError(
                f"MinimalBot {operation} failed (transport error): {exc}"
            ) from exc
        try:
            content = response.json()
        except ValueError:
            content = {"raw": response.text[:2000]}
        return response, content

    @property
    def _components_url(self) -> str:
        return (
            f"{self.host}/copilotstudio/minimalBots/api/{self.bot_id}/components"
            f"?api-version={COMPONENTS_API_VERSION}"
        )

    def read_components(self) -> dict[str, Any]:
        """Read all bot components (and the current changeToken)."""
        response, body = self._request(
            "POST", self._components_url, body={}, operation="component read")
        if response.status_code != 200:
            raise MinimalBotEvaluationError(
                f"MinimalBot component read failed (HTTP {response.status_code})."
            )
        if not isinstance(body, dict):
            raise MinimalBotEvaluationError(
                "MinimalBot component read returned an unexpected payload."
            )
        return body

    # -- push ---------------------------------------------------------------
    def push_agent_evaluations(
        self,
        agent_folder: Path,
        *,
        dry_run: bool = False,
        only_globs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Push ``evaluations/<set>/`` folders under ``agent_folder``.

        Mirrors the POC's fresh-insert model: each push inserts a brand-new
        copy of every evaluation set (new component IDs, timestamped display
        name) so repeated pushes never collide with optimistic concurrency.

        ``only_globs`` (from ``push.py --only``) restricts the push to the
        evaluation sets whose files match at least one glob. Because each push
        mints fresh component IDs, honouring the scope is a correctness
        requirement — pushing unscoped sets would duplicate every unrelated
        deployed set on a targeted update.
        """
        eval_root = Path(agent_folder) / "evaluations"
        if not eval_root.is_dir():
            raise MinimalBotEvaluationError(
                f"No evaluations folder found at {eval_root}."
            )
        set_folders = sorted(
            path for path in eval_root.iterdir()
            if path.is_dir() and any(path.glob("*.mcs.yml"))
        )
        if not set_folders:
            raise MinimalBotEvaluationError(
                f"No evaluation sets found under {eval_root}."
            )

        if only_globs:
            root = Path(agent_folder)
            scoped = [
                folder for folder in set_folders
                if _folder_matches_globs(folder, root, only_globs)
            ]
            if not scoped:
                raise MinimalBotEvaluationError(
                    "No evaluation sets matched the requested --only/--only-from "
                    f"scope: {only_globs}. Refusing to fall back to a broader "
                    "push (an unscoped MinimalBot push would duplicate every "
                    "deployed set)."
                )
            set_folders = scoped

        changes: list[dict[str, Any]] = []
        pushed_sets: list[dict[str, str]] = []
        for folder in set_folders:
            folder_changes, parent_id, display_name = self._folder_changes(folder)
            changes.extend(folder_changes)
            pushed_sets.append({
                "folder": folder.name,
                "testSetId": parent_id,
                "displayName": display_name,
                "cases": str(len(folder_changes) - 1),
            })

        if dry_run:
            return {
                "dryRun": True,
                "sets": pushed_sets,
                "componentCount": len(changes),
            }

        before = self.read_components()
        change_token = str(before.get("changeToken") or "")
        if not change_token:
            raise MinimalBotEvaluationError(
                "MinimalBot component read did not return a changeToken."
            )

        payload = {
            "changeToken": change_token,
            "botComponentChanges": changes,
            "connectionReferenceChanges": [],
            "connectorDefinitionChanges": [],
        }

        response, _ = self._request(
            "PUT", self._components_url, body=payload, operation="push")
        if response.status_code != 200:
            raise MinimalBotEvaluationError(
                f"MinimalBot push failed (HTTP {response.status_code})."
            )

        verify = self.read_components()
        expected = {_component_id(change) for change in changes}
        actual = {
            _component_id(change)
            for change in verify.get("botComponentChanges", [])
        }
        missing = sorted(expected - actual)
        if missing:
            raise MinimalBotEvaluationError(
                f"MinimalBot verification failed; missing components: {missing}"
            )
        return {
            "dryRun": False,
            "sets": pushed_sets,
            "componentCount": len(changes),
            "verifiedComponents": len(expected),
        }

    def _folder_changes(
        self,
        folder: Path,
    ) -> tuple[list[dict[str, Any]], str, str]:
        """Build the BotComponentInsert change set for one evaluation folder."""
        documents = []
        for path in sorted(folder.glob("*.mcs.yml")):
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise MinimalBotEvaluationError(
                    f"Unable to read evaluation YAML {path}: {exc}"
                ) from exc
            if not isinstance(document, dict):
                raise MinimalBotEvaluationError(
                    f"Evaluation YAML must contain an object: {path}"
                )
            documents.append((path, document))

        parents = [item for item in documents if item[1].get("kind") == "EvaluationSet"]
        cases = [item for item in documents if item[1].get("kind") == "EvaluationData"]
        # Never silently omit authored files. Any document whose kind this
        # transport can't convert (e.g. MultiTurnEvaluationCase, which is a
        # supported authored child elsewhere in the kit) must fail the push
        # rather than deploy a set that differs from local source.
        unsupported = [
            item for item in documents
            if item[1].get("kind") not in _EVAL_KINDS
        ]
        if unsupported:
            details = ", ".join(
                f"{path.name} (kind={doc.get('kind') or 'missing'})"
                for path, doc in unsupported
            )
            raise MinimalBotEvaluationError(
                f"Evaluation folder {folder.name} contains file(s) the "
                "Dataverse-free (MinimalBot) push does not support: "
                f"{details}. This transport only converts EvaluationSet and "
                "EvaluationData; multi-turn cases (MultiTurnEvaluationCase) "
                "cannot be pushed this way yet. Remove or relocate the "
                "unsupported file(s), or push this set through a "
                "Dataverse-backed agent."
            )
        if len(parents) != 1:
            raise MinimalBotEvaluationError(
                f"Evaluation folder {folder.name} must contain exactly one "
                "EvaluationSet."
            )
        if not cases:
            raise MinimalBotEvaluationError(
                f"Evaluation folder {folder.name} must contain at least one "
                "EvaluationData file."
            )
        if len(cases) > 100:
            raise MinimalBotEvaluationError(
                f"Evaluation set {folder.name} exceeds the 100-case limit."
            )

        parent_path, parent_document = parents[0]
        parent_id = str(uuid.uuid4())
        parent_definition = _wire_kinds(parent_document)
        display_name = (
            f"{parent_definition.get('displayName') or parent_path.stem} "
            f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        )
        parent_definition["displayName"] = display_name
        changes = [{
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "TestCaseComponent",
                "id": parent_id,
                "schemaName": _schema_name(parent_path.stem, parent_id),
                "definition": parent_definition,
                "extensionData": {"UseProvidedBotComponentId": True},
            },
        }]

        for case_path, case_document in cases:
            case_id = str(uuid.uuid4())
            case_definition = _wire_kinds(case_document)
            rows = case_definition.get("rows")
            if not isinstance(rows, list) or not rows:
                raise MinimalBotEvaluationError(
                    f"EvaluationData must contain at least one row: {case_path}"
                )
            for row in rows:
                if not isinstance(row, dict):
                    raise MinimalBotEvaluationError(
                        f"EvaluationData rows must be objects: {case_path}"
                    )
                row.setdefault("$kind", "SimpleEvaluationCase")
            changes.append({
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "TestCaseComponent",
                    "id": case_id,
                    "parentBotComponentId": parent_id,
                    "schemaName": _schema_name(case_path.stem, case_id),
                    "definition": case_definition,
                    "extensionData": {"UseProvidedBotComponentId": True},
                },
            })
        return changes, parent_id, display_name

    # -- run ----------------------------------------------------------------
    def list_test_sets(self) -> list[dict[str, Any]]:
        """List the EvaluationSet components available on the agent."""
        components = self.read_components()
        sets = []
        for change in components.get("botComponentChanges", []):
            component = change.get("component") if isinstance(change, dict) else None
            if not isinstance(component, dict):
                continue
            definition = component.get("definition") or {}
            if definition.get("$kind") != "EvaluationSet":
                continue
            sets.append({
                "id": str(component.get("id") or ""),
                "displayName": _component_name(component),
                "schemaName": str(component.get("schemaName") or ""),
                "runnable": True,
            })
        return sets

    def _connected(self, connector_id: str) -> list[dict[str, Any]]:
        response, body = self._request(
            "GET",
            f"{self.host}/connectivity/apis/{connector_id}/connections",
            params={
                "api-version": "1",
                "$filter": f"environment eq '{self.environment_id}'",
            },
            operation="connection discovery",
        )
        if response.status_code != 200:
            raise MinimalBotEvaluationError(
                f"Connection discovery failed for {connector_id} "
                f"(HTTP {response.status_code})."
            )
        result = []
        for connection in body.get("value", []):
            properties = connection.get("properties") or {}
            statuses = properties.get("statuses") or connection.get("statuses") or []
            if statuses and not any(
                str(item.get("status", "")).casefold() == "connected"
                for item in statuses
                if isinstance(item, dict)
            ):
                continue
            if _connection_id(connection):
                result.append(connection)
        return result

    def _select_one(
        self,
        connections: list[dict[str, Any]],
        connector_id: str,
    ) -> dict[str, Any]:
        if len(connections) != 1:
            raise MinimalBotEvaluationError(
                f"Expected exactly one connected {connector_id} profile for "
                f"the signed-in account; found {len(connections)}."
            )
        return connections[0]

    def _tool_bindings(
        self,
        bot_schema_name: str,
        references: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        bindings = []
        for change in references:
            reference = change.get("connectionReference") or change
            connector_path = str(reference.get("connectorId") or "")
            connector_id = connector_path.rstrip("/").rsplit("/", 1)[-1]
            reference_name = str(
                reference.get("connectionReferenceLogicalName") or ""
            )
            if not connector_id or not reference_name:
                continue
            connection = self._select_one(
                self._connected(connector_id), connector_id
            )
            bindings.append({
                "connectorId": connector_id,
                "connectionId": _connection_id(connection),
                "connectionReferenceName": reference_name,
            })
        if not bindings:
            return []
        return [{
            "botId": self.bot_id,
            "botSchemaName": bot_schema_name,
            "connections": bindings,
        }]

    def run_test_set(
        self,
        test_set_id: str,
        *,
        run_name: str | None = None,
        run_on_published_bot: bool = False,
        mcs_connection_id: str | None = None,
    ) -> dict[str, Any]:
        """Start a maker evaluation run for ``test_set_id`` on the agent's ring."""
        if not test_set_id:
            raise MinimalBotEvaluationError("A test set ID is required to run.")
        components = self.read_components()
        mcs_id = mcs_connection_id or _connection_id(
            self._select_one(self._connected(MCS_CONNECTOR), MCS_CONNECTOR)
        )
        bot = components.get("bot") or {}
        tools_connections = self._tool_bindings(
            str(bot.get("schemaName") or ""),
            components.get("connectionReferenceChanges") or [],
        )
        now = datetime.now(timezone.utc)
        body = {
            "evaluationRunName": (
                run_name or f"MinimalBot run {now:%Y-%m-%d %H:%M UTC}"
            ),
            "runOnPublishedBot": run_on_published_bot,
            "mcsConnectionId": mcs_id,
            "toolsConnections": tools_connections,
        }
        run_url = (
            f"{self.api_base}/copilotstudio/environments/{self.environment_id}"
            f"/bots/{self.bot_id}/api/makerevaluation/testsets/{test_set_id}/run"
            f"?api-version={MAKEREVAL_API_VERSION}"
        )
        response, result = self._request(
            "POST", run_url, body=body, operation="evaluation run")
        service_request_id = (
            response.headers.get("x-ms-service-request-id")
            or response.headers.get("x-ms-request-id")
        )
        if response.status_code != 202:
            raise MinimalBotEvaluationError(
                f"MinimalBot evaluation run failed (HTTP {response.status_code}): "
                f"{result}"
            )
        run_id = ""
        if isinstance(result, dict):
            run_id = str(result.get("runId") or result.get("id") or "")
        if not run_id:
            # A 202 with no run identifier is unusable: the run cannot be
            # tracked or queried afterwards. Fail loudly rather than reporting
            # a phantom success with an empty ID.
            raise MinimalBotEvaluationError(
                "MinimalBot evaluation run was accepted (HTTP 202) but the "
                "response contained no runId/id, so the run cannot be tracked. "
                f"Response: {result}"
            )
        return {
            "runId": run_id,
            "testSetId": test_set_id,
            "runName": body["evaluationRunName"],
            "status": response.status_code,
            "serviceRequestId": service_request_id,
            "correlationId": response.headers.get("x-ms-correlation-id"),
            "startedAt": now.isoformat(),
            "response": result,
        }

    # -- run history / results ---------------------------------------------
    @property
    def _makereval_base(self) -> str:
        return (
            f"{self.api_base}/copilotstudio/environments/{self.environment_id}"
            f"/bots/{self.bot_id}/api/makerevaluation"
        )

    def list_test_runs(self) -> list[dict[str, Any]]:
        """List prior maker-evaluation runs for the bot via the PPAPI.

        Uses the standard ``makerevaluation/testruns`` Power Platform endpoint
        (the same surface the Dataverse path calls), not the MinimalBot
        components API.
        """
        url = (
            f"{self._makereval_base}/testruns"
            f"?api-version={MAKEREVAL_API_VERSION}"
        )
        response, body = self._request("GET", url, operation="run-history read")
        if response.status_code != 200:
            raise MinimalBotEvaluationError(
                f"MinimalBot run-history read failed (HTTP {response.status_code})."
            )
        if isinstance(body, dict):
            runs = body.get("value")
            if isinstance(runs, list):
                return runs
            return [body]
        if isinstance(body, list):
            return body
        raise MinimalBotEvaluationError(
            "MinimalBot run-history returned an unexpected payload."
        )

    def get_test_run(self, run_id: str) -> dict[str, Any]:
        """Get status/results for a single run via the PPAPI.

        Uses ``makerevaluation/testruns/{runId}`` on the TEST ring.
        """
        if not run_id:
            raise MinimalBotEvaluationError("A run ID is required to get results.")
        url = (
            f"{self._makereval_base}/testruns/{run_id}"
            f"?api-version={MAKEREVAL_API_VERSION}"
        )
        response, body = self._request("GET", url, operation="run results read")
        if response.status_code != 200:
            raise MinimalBotEvaluationError(
                f"MinimalBot run results read failed (HTTP {response.status_code})."
            )
        if not isinstance(body, dict):
            raise MinimalBotEvaluationError(
                "MinimalBot run results returned an unexpected payload."
            )
        return body
