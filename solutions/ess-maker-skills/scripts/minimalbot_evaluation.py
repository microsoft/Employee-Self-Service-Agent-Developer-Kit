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
import copy
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
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
from evaluation_method_policy import (
    EvaluationMethodError,
    document_kind,
    validate_evaluation_documents,
    validate_evaluation_folder,
)


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
NATIVE_REVIEW_LOCAL_ONLY_WARNING = (
    "Existing native Push uploads evaluation YAML only. review.json stays local "
    "and is not published as shared review state."
)
_TOKEN_CACHE_PATH = os.path.join(".local", ".token_cache.bin")
_EVAL_KINDS = {"EvaluationSet", "EvaluationData"}
_REVIEWED_WORKDAY_TOPIC_SUFFIXES = {
    "gptagent_copilotforemployeeselfservicehr": frozenset(
        {
            "EmployeeUpdatePhoneNumber",
            "GetReferenceData",
            "WorkdayCompanyCode",
            "WorkdayEmployeeID",
            "WorkdayGetBaseCompensation",
            "WorkdayGetCertifications",
            "WorkdayGetCostCenter",
            "WorkdayGetEmergencyContact",
            "WorkdayGetEmploymentInformation",
            "WorkdayGetLanguageInformation",
            "WorkdayGetNationalIDs",
            "WorkdayGetPassports",
            "WorkdayGetVisas",
            "WorkdayManagerCheck",
            "WorkdayOnError",
            "WorkdaySystemAccessCheck",
            "WorkdaySystemGetCommonExecution",
            "WorkdaySystemGetRESTExecution",
            "WorkdaySystemGetUserContextV2",
            "WorkdaySystemRefreshReferenceData",
            "WorkdaySystemSetRuntimeTemplateConfigurations",
            "Workdayemployeeupdateemail",
            "Workdayserviceanniversary",
        }
    ),
}


def reviewed_workday_topic_schemas(agent_schema: str) -> frozenset[str]:
    """Return the reviewed OOB Workday topic schemas for one agent."""
    schema = str(agent_schema or "").strip()
    suffixes = _REVIEWED_WORKDAY_TOPIC_SUFFIXES.get(schema.casefold())
    if suffixes is None:
        return frozenset()
    return frozenset(
        f"{schema}.topic.{suffix}" for suffix in suffixes
    )


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


def _without_server_generated_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_server_generated_fields(child)
            for key, child in value.items()
            if key not in {"diagnostics", "structuredCondition"}
        }
    if isinstance(value, list):
        return [_without_server_generated_fields(child) for child in value]
    return value


_MISSING = object()


class _DialogMergeConflict(ValueError):
    """Raised when a local dialog delta overlaps newer remote content."""


def _merge_values_equal(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    return left == right


def _longest_common_subsequence(
    expected: list[str],
    desired: list[str],
) -> list[str]:
    """Return one deterministic LCS for unique component action IDs."""
    rows = len(expected) + 1
    columns = len(desired) + 1
    lengths = [[0] * columns for _ in range(rows)]
    for expected_index in range(len(expected) - 1, -1, -1):
        for desired_index in range(len(desired) - 1, -1, -1):
            if expected[expected_index] == desired[desired_index]:
                lengths[expected_index][desired_index] = (
                    lengths[expected_index + 1][desired_index + 1] + 1
                )
            else:
                lengths[expected_index][desired_index] = max(
                    lengths[expected_index + 1][desired_index],
                    lengths[expected_index][desired_index + 1],
                )

    result: list[str] = []
    expected_index = 0
    desired_index = 0
    while (
        expected_index < len(expected)
        and desired_index < len(desired)
    ):
        if expected[expected_index] == desired[desired_index]:
            result.append(expected[expected_index])
            expected_index += 1
            desired_index += 1
        elif (
            lengths[expected_index + 1][desired_index]
            >= lengths[expected_index][desired_index + 1]
        ):
            expected_index += 1
        else:
            desired_index += 1
    return result


def _keyed_list(
    value: list[Any],
    *,
    path: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    ids: list[str] = []
    items: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise _DialogMergeConflict(
                f"{path}[{index}] has no stable object identity"
            )
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise _DialogMergeConflict(
                f"{path}[{index}] has no stable action ID"
            )
        if item_id in items:
            raise _DialogMergeConflict(
                f"{path} contains duplicate action ID {item_id!r}"
            )
        ids.append(item_id)
        items[item_id] = item
    return ids, items


def _merge_keyed_lists(
    expected: list[Any],
    desired: list[Any],
    remote: list[Any],
    *,
    path: str,
) -> list[Any]:
    expected_ids, expected_items = _keyed_list(expected, path=path)
    desired_ids, desired_items = _keyed_list(desired, path=path)
    remote_ids, remote_items = _keyed_list(remote, path=path)

    expected_set = set(expected_ids)
    desired_set = set(desired_ids)
    remote_set = set(remote_ids)
    added = desired_set - expected_set
    removed = expected_set - desired_set
    common = expected_set & desired_set
    stable = set(_longest_common_subsequence(expected_ids, desired_ids))
    moved = common - stable
    content_changed = {
        item_id
        for item_id in common
        if desired_items[item_id] != expected_items[item_id]
    }

    # An empty scaffold is an explicit compatibility boundary. A remote action
    # that is not the locally requested action is customer content, not an
    # insertion point the kit may silently repurpose.
    if not expected and remote:
        remote_only = remote_set - desired_set
        if remote_only:
            raise _DialogMergeConflict(
                f"{path} contains newer actions not present in the reviewed "
                "empty scaffold"
            )

    merged_by_id: dict[str, Any] = {}
    result_ids: list[str] = []
    for item_id in remote_ids:
        if item_id in removed:
            if remote_items[item_id] != expected_items[item_id]:
                raise _DialogMergeConflict(
                    f"{path} action {item_id!r} changed remotely while the "
                    "local edit removed it"
                )
            continue
        if item_id in desired_set:
            expected_item = expected_items.get(item_id, _MISSING)
            merged_by_id[item_id] = _merge_dialog_value(
                expected_item,
                desired_items[item_id],
                remote_items[item_id],
                path=f"{path}[id={item_id!r}]",
            )
        else:
            merged_by_id[item_id] = copy.deepcopy(remote_items[item_id])
        result_ids.append(item_id)

    locally_positioned = added | moved
    locally_touched = locally_positioned | content_changed
    for item_id in desired_ids:
        if item_id in merged_by_id:
            continue
        if item_id in locally_touched:
            merged_by_id[item_id] = copy.deepcopy(desired_items[item_id])
            result_ids.append(item_id)

    # Apply only local insert/move operations. Remote-only actions keep their
    # relative order, while a required local adjacency (for example immediately
    # before User Context Validate) is restored around the latest live content.
    for item_id in desired_ids:
        if item_id not in locally_positioned or item_id not in merged_by_id:
            continue
        if item_id in result_ids:
            result_ids.remove(item_id)
        desired_index = desired_ids.index(item_id)
        next_anchor = next(
            (
                candidate
                for candidate in desired_ids[desired_index + 1 :]
                if candidate in result_ids
            ),
            None,
        )
        if next_anchor is not None:
            result_ids.insert(result_ids.index(next_anchor), item_id)
            continue
        previous_anchor = next(
            (
                candidate
                for candidate in reversed(desired_ids[:desired_index])
                if candidate in result_ids
            ),
            None,
        )
        if previous_anchor is None:
            result_ids.append(item_id)
        else:
            result_ids.insert(result_ids.index(previous_anchor) + 1, item_id)

    return [merged_by_id[item_id] for item_id in result_ids]


def _merge_dialog_value(
    expected: Any,
    desired: Any,
    remote: Any,
    *,
    path: str,
) -> Any:
    """Apply the local expected-to-desired delta to the latest remote value."""
    if _merge_values_equal(expected, desired):
        return (
            _MISSING
            if remote is _MISSING
            else copy.deepcopy(remote)
        )
    if _merge_values_equal(remote, expected):
        return (
            _MISSING
            if desired is _MISSING
            else copy.deepcopy(desired)
        )
    if _merge_values_equal(remote, desired):
        return (
            _MISSING
            if desired is _MISSING
            else copy.deepcopy(desired)
        )

    if all(
        isinstance(value, dict)
        for value in (expected, desired, remote)
    ):
        merged: dict[str, Any] = {}
        keys = set(expected) | set(desired) | set(remote)
        for key in keys:
            child = _merge_dialog_value(
                expected.get(key, _MISSING),
                desired.get(key, _MISSING),
                remote.get(key, _MISSING),
                path=f"{path}.{key}",
            )
            if child is not _MISSING:
                merged[key] = child
        return merged

    if all(
        isinstance(value, list)
        for value in (expected, desired, remote)
    ):
        return _merge_keyed_lists(
            expected,
            desired,
            remote,
            path=path,
        )

    raise _DialogMergeConflict(
        f"{path} was changed both locally and remotely"
    )


def _reconcile_dialog_update(
    expected: dict[str, Any],
    desired: dict[str, Any],
    remote: dict[str, Any],
) -> dict[str, Any]:
    merged = _merge_dialog_value(
        _without_server_generated_fields(expected),
        _without_server_generated_fields(desired),
        _without_server_generated_fields(remote),
        path="$",
    )
    if not isinstance(merged, dict):
        raise _DialogMergeConflict(
            "The reconciled dialog is not an Object Model object"
        )
    return merged


def blocking_diagnostics(
    value: Any,
    *,
    path: str = "$",
) -> list[dict[str, str]]:
    """Return only error diagnostics from a component Object Model tree."""
    findings: list[dict[str, str]] = []
    if isinstance(value, dict):
        diagnostics = value.get("diagnostics")
        if isinstance(diagnostics, list):
            for index, diagnostic in enumerate(diagnostics):
                if not isinstance(diagnostic, dict):
                    continue
                kind = str(diagnostic.get("$kind") or "")
                code = str(diagnostic.get("errorCode") or "")
                if not code and not kind.casefold().endswith("error"):
                    continue
                findings.append(
                    {
                        "path": f"{path}.diagnostics[{index}]",
                        "kind": kind,
                        "errorCode": code,
                        "message": str(
                            diagnostic.get("errorMessage") or ""
                        ),
                        "referenceType": str(
                            diagnostic.get("referenceType") or ""
                        ),
                        "referenceId": str(
                            diagnostic.get("referenceId") or ""
                        ),
                    }
                )
        for key, child in value.items():
            if key != "diagnostics":
                findings.extend(
                    blocking_diagnostics(child, path=f"{path}.{key}")
                )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(
                blocking_diagnostics(child, path=f"{path}[{index}]")
            )
    return findings


def resolve_workday_dialogs(
    agent_folder: str | Path,
    agent_schema: str,
) -> list[dict[str, str]]:
    """Resolve the complete mapped Workday dialog set for one agent."""
    root = Path(agent_folder).resolve()
    schema = str(agent_schema or "").strip()
    if not schema:
        raise MinimalBotEvaluationError(
            "The active agent schema name is required for Workday activation."
        )
    map_path = root / ".component-map.json"
    try:
        component_map = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MinimalBotEvaluationError(
            f"Could not read the active agent component map: {map_path}: {exc}"
        ) from exc
    if not isinstance(component_map, dict):
        raise MinimalBotEvaluationError(
            "The active agent component map must contain a JSON object."
        )

    reviewed = reviewed_workday_topic_schemas(schema)
    reviewed_schemas = (
        {value.casefold() for value in reviewed}
        if reviewed
        else None
    )
    schema_prefix = f"{schema}.topic.Workday".casefold()
    entries: list[dict[str, str]] = []
    component_ids: set[str] = set()
    schema_names: set[str] = set()
    for raw_path, raw_entry in component_map.items():
        if not isinstance(raw_path, str) or not isinstance(raw_entry, dict):
            continue
        component_schema = str(raw_entry.get("schemaName") or "").strip()
        display_name = str(raw_entry.get("displayName") or "").strip()
        normalized_component_schema = component_schema.casefold()
        is_workday_topic = (
            normalized_component_schema in reviewed_schemas
            if reviewed_schemas is not None
            else (
                normalized_component_schema.startswith(schema_prefix)
                and display_name.startswith("Workday")
            )
        )
        if (
            raw_entry.get("componentKind") != "DialogComponent"
            or not is_workday_topic
        ):
            continue
        if not display_name.startswith("Workday"):
            raise MinimalBotEvaluationError(
                "A reviewed Workday topic has an unexpected display name: "
                f"{component_schema}."
            )
        relative_path = raw_path.replace("\\", "/")
        safe_path = PurePosixPath(relative_path)
        if (
            safe_path.is_absolute()
            or ".." in safe_path.parts
            or not safe_path.parts
            or safe_path.parts[0] != "topics"
            or not relative_path.endswith(".mcs.yml")
        ):
            raise MinimalBotEvaluationError(
                f"Unsafe Workday topic path in component map: {raw_path}"
            )
        local_path = root.joinpath(*safe_path.parts)
        if not local_path.is_file():
            raise MinimalBotEvaluationError(
                f"Mapped Workday topic is missing: {relative_path}"
            )
        component_id = str(raw_entry.get("componentId") or "").strip()
        if not component_id or not component_schema:
            raise MinimalBotEvaluationError(
                f"Mapped Workday topic has incomplete identity: {relative_path}"
            )
        normalized_id = component_id.casefold()
        normalized_schema = component_schema.casefold()
        if normalized_id in component_ids or normalized_schema in schema_names:
            raise MinimalBotEvaluationError(
                "The Workday topic map contains duplicate component identity."
            )
        component_ids.add(normalized_id)
        schema_names.add(normalized_schema)
        entries.append(
            {
                "path": relative_path,
                "componentId": component_id,
                "schemaName": component_schema,
                "displayName": display_name,
            }
        )
    if not entries:
        raise MinimalBotEvaluationError(
            "No mapped Workday dialog topics were found for the active agent."
        )
    if reviewed_schemas is not None:
        observed_schemas = {
            entry["schemaName"].casefold() for entry in entries
        }
        missing_schemas = sorted(reviewed_schemas - observed_schemas)
        unexpected_schemas = sorted(observed_schemas - reviewed_schemas)
        if missing_schemas or unexpected_schemas:
            details = []
            if missing_schemas:
                details.append(
                    "missing=" + ", ".join(missing_schemas)
                )
            if unexpected_schemas:
                details.append(
                    "unexpected=" + ", ".join(unexpected_schemas)
                )
            raise MinimalBotEvaluationError(
                "The active ESS HR component map does not match the reviewed "
                "23-topic Workday inventory ("
                + "; ".join(details)
                + "). Refresh the workspace before activation."
            )
    expected_count = len(reviewed_schemas) if reviewed_schemas is not None else None
    if expected_count is not None and len(entries) != expected_count:
        raise MinimalBotEvaluationError(
            "The active ESS HR component map contains "
            f"{len(entries)} Workday topics; expected {expected_count}. "
            "Refresh the workspace before activation."
        )
    return sorted(entries, key=lambda entry: entry["path"])


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
    tenant_id: str,
    scope: str | None = None,
    preferred_username: str | None = None,
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
    preferred = str(preferred_username or "").casefold()
    selected_account = next(
        (
            account
            for account in accounts
            if str(account.get("username") or "").casefold() == preferred
        ),
        None,
    )
    if selected_account is None and not preferred:
        selected_account = accounts[0] if accounts else None
    result = None
    if selected_account:
        result = app.acquire_token_silent([scope], account=selected_account)
    if not result or "access_token" not in result:
        print("Opening browser for Power Platform sign-in...")
        interactive_options = (
            {"login_hint": preferred_username}
            if preferred_username
            else {"prompt": "select_account"}
        )
        result = app.acquire_token_interactive([scope], **interactive_options)
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
    def authenticate(self, preferred_username: str | None = None) -> str:
        """Acquire a Power Platform token for this ring, reusing the MSAL cache."""
        self._token, self.signed_in_username = acquire_test_pp_token(
            self.tenant_id,
            scope=self.scope,
            preferred_username=preferred_username,
        )
        if preferred_username and (
            str(self.signed_in_username or "").casefold()
            != preferred_username.casefold()
        ):
            raise MinimalBotEvaluationError(
                "Power Platform authentication used a different account from "
                "the selected Environment Maker."
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

    def update_dialog_components(
        self,
        updates: list[dict[str, Any]],
        *,
        _retry_on_conflict: bool = True,
    ) -> dict[str, Any]:
        """Update existing dialog components with drift and identity checks."""
        if not updates:
            raise MinimalBotEvaluationError(
                "No MinimalBot dialog updates were requested."
            )

        before = self.read_components()
        change_token = str(before.get("changeToken") or "")
        if not change_token:
            raise MinimalBotEvaluationError(
                "MinimalBot component read did not return a changeToken."
            )
        remote_changes = before.get("botComponentChanges")
        if not isinstance(remote_changes, list):
            raise MinimalBotEvaluationError(
                "MinimalBot component read returned no component changes."
            )

        changes: list[dict[str, Any]] = []
        verification_updates: list[dict[str, Any]] = []
        reconciled_components = 0
        for update in updates:
            component_id = str(update.get("componentId") or "")
            schema_name = str(update.get("schemaName") or "")
            matches = [
                change.get("component")
                for change in remote_changes
                if isinstance(change, dict)
                and isinstance(change.get("component"), dict)
                and str(change["component"].get("id") or "").casefold()
                == component_id.casefold()
            ]
            if len(matches) != 1:
                raise MinimalBotEvaluationError(
                    "The selected MinimalBot dialog component is no longer "
                    "unique."
                )
            component = matches[0]
            if (
                component.get("$kind") != "DialogComponent"
                or str(component.get("schemaName") or "").casefold()
                != schema_name.casefold()
            ):
                raise MinimalBotEvaluationError(
                    "The selected MinimalBot dialog identity changed after "
                    "local extraction."
                )
            has_dialog_update = "dialog" in update
            desired_dialog = update.get("dialog")
            expected_dialog = update.get("expectedDialog")
            if has_dialog_update and (
                not isinstance(expected_dialog, dict)
                or not isinstance(desired_dialog, dict)
            ):
                raise MinimalBotEvaluationError(
                    "MinimalBot dialog content updates require expected and "
                    "desired Object Model payloads."
                )
            desired_state = update.get("state")
            desired_status = update.get("status")
            if (
                not has_dialog_update
                and desired_state is None
                and desired_status is None
            ):
                raise MinimalBotEvaluationError(
                    "MinimalBot dialog update did not request content or state "
                    "changes."
                )
            remote_dialog = _without_server_generated_fields(
                component.get("dialog")
            )
            effective_dialog = desired_dialog
            if has_dialog_update:
                expected_clean = _without_server_generated_fields(
                    expected_dialog
                )
                desired_clean = _without_server_generated_fields(
                    desired_dialog
                )
                if remote_dialog not in (expected_clean, desired_clean):
                    try:
                        effective_dialog = _reconcile_dialog_update(
                            expected_clean,
                            desired_clean,
                            remote_dialog,
                        )
                    except _DialogMergeConflict as exc:
                        raise MinimalBotEvaluationError(
                            "The selected MinimalBot dialog has newer remote "
                            "content that overlaps this scoped edit. No remote "
                            f"content was overwritten: {exc}."
                        ) from exc
                    reconciled_components += 1
                else:
                    effective_dialog = desired_clean
            effective_update = dict(update)
            if has_dialog_update:
                effective_update["dialog"] = effective_dialog
            verification_updates.append(effective_update)
            dialog_is_desired = (
                not has_dialog_update
                or remote_dialog
                == _without_server_generated_fields(effective_dialog)
            )
            state_is_desired = (
                desired_state is None
                or component.get("state") == desired_state
            )
            status_is_desired = (
                desired_status is None
                or component.get("status") == desired_status
            )
            if dialog_is_desired and state_is_desired and status_is_desired:
                continue
            updated_component = copy.deepcopy(component)
            if has_dialog_update:
                updated_component["dialog"] = effective_dialog
            if desired_state is not None:
                updated_component["state"] = desired_state
            if desired_status is not None:
                updated_component["status"] = desired_status
            changes.append(
                {
                    "$kind": "BotComponentUpdate",
                    "component": updated_component,
                }
            )

        if changes:
            payload = {
                "changeToken": change_token,
                "botComponentChanges": changes,
                "cloudFlowDefinitionChanges": [],
                "connectionReferenceChanges": [],
                "connectorDefinitionChanges": [],
                "environmentVariableChanges": [],
                "aIPluginOperationChanges": [],
                "componentCollectionChanges": [],
                "dataverseTableSearchChanges": [],
                "connectedAgentDefinitionChanges": [],
            }
            response, _ = self._request(
                "PUT",
                self._components_url,
                body=payload,
                operation="dialog update",
            )
            if (
                response.status_code in {409, 412}
                and _retry_on_conflict
            ):
                # The live change token advanced after the read. Re-read once:
                # if another attempt already applied this exact mapping the
                # idempotent reconciliation returns success without another
                # PUT; otherwise it reapplies the same scoped delta to the
                # newer live topic.
                return self.update_dialog_components(
                    updates,
                    _retry_on_conflict=False,
                )
            if response.status_code != 200:
                raise MinimalBotEvaluationError(
                    "MinimalBot dialog update failed "
                    f"(HTTP {response.status_code})."
                )

        verified = self.read_components()
        verification = self._verify_dialog_components_payload(
            verification_updates,
            verified,
        )
        return {
            "updatedComponents": len(changes),
            "reconciledComponents": reconciled_components,
            **verification,
        }

    def verify_dialog_components(
        self,
        expectations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Reread and verify existing dialog identity, state, and diagnostics."""
        if not expectations:
            raise MinimalBotEvaluationError(
                "No MinimalBot dialog verification was requested."
            )
        return self._verify_dialog_components_payload(
            expectations,
            self.read_components(),
        )

    @staticmethod
    def _verify_dialog_components_payload(
        updates: list[dict[str, Any]],
        verified: dict[str, Any],
    ) -> dict[str, Any]:
        verified_changes = verified.get("botComponentChanges")
        if not isinstance(verified_changes, list):
            raise MinimalBotEvaluationError(
                "MinimalBot dialog verification returned no component changes."
            )
        verified_by_id: dict[str, list[dict[str, Any]]] = {}
        for change in verified_changes:
            if not isinstance(change, dict):
                continue
            component = change.get("component")
            if not isinstance(component, dict):
                continue
            component_id = str(component.get("id") or "").casefold()
            if component_id:
                verified_by_id.setdefault(component_id, []).append(component)
        all_diagnostics: list[dict[str, str]] = []
        for update in updates:
            component_id = str(update["componentId"])
            matches = verified_by_id.get(component_id.casefold()) or []
            if len(matches) != 1:
                raise MinimalBotEvaluationError(
                    "MinimalBot dialog verification found a missing or "
                    f"duplicate component ID: {component_id}."
                )
            component = matches[0]
            expected_schema = str(update.get("schemaName") or "")
            verified_update = (
                component.get("$kind") == "DialogComponent"
                and str(component.get("schemaName") or "").casefold()
                == expected_schema.casefold()
            )
            if verified_update and "dialog" in update:
                verified_update = _without_server_generated_fields(
                    component.get("dialog")
                ) == _without_server_generated_fields(update["dialog"])
            if verified_update and update.get("state") is not None:
                verified_update = (
                    component.get("state") == update["state"]
                )
            if verified_update and update.get("status") is not None:
                verified_update = (
                    component.get("status") == update["status"]
                )
            diagnostics = (
                blocking_diagnostics(component)
                if component is not None
                else []
            )
            for diagnostic in diagnostics:
                all_diagnostics.append(
                    {
                        **diagnostic,
                        "componentId": component_id,
                        "schemaName": str(update.get("schemaName") or ""),
                    }
                )
            if (
                diagnostics
                and update.get("requireCleanDiagnostics") is True
            ):
                first = diagnostics[0]
                detail = first["errorCode"] or first["kind"] or "error"
                raise MinimalBotEvaluationError(
                    "MinimalBot dialog has blocking diagnostics after "
                    f"verification ({update.get('schemaName')}): {detail}."
                )
            if not verified_update:
                raise MinimalBotEvaluationError(
                    "MinimalBot dialog verification failed for component "
                    f"{component_id}."
                )
        return {
            "verifiedComponents": len(updates),
            "activeComponents": sum(
                1
                for update in updates
                if update.get("state") == "Active"
                and update.get("status") == "Active"
            ),
            "blockingDiagnostics": all_diagnostics,
        }

    # -- push ---------------------------------------------------------------
    def push_agent_evaluations(
        self,
        agent_folder: Path,
        *,
        dry_run: bool = False,
        only_globs: list[str] | None = None,
        plan: dict[str, Any] | None = None,
        source_folder: Path | None = None,
    ) -> dict[str, Any]:
        """Push ``evaluations/<set>/`` folders under ``agent_folder``.

        New or changed sets use the existing fresh-copy insert contract.
        Confirmed unchanged sets reuse their IDs. Review sidecars are retained
        locally; this API uploads evaluation YAML, not shared review metadata.
        """
        root = Path(agent_folder)
        eval_root = root / "evaluations"
        if source_folder is not None and not dry_run:
            raise MinimalBotEvaluationError("Alternate source folders are preview-only.")
        if source_folder is None and not eval_root.is_dir():
            raise MinimalBotEvaluationError(
                f"No evaluations folder found at {eval_root}."
            )
        set_folders = [Path(source_folder)] if source_folder is not None else sorted(
            path for path in eval_root.iterdir()
            if path.is_dir() and any(path.glob("*.mcs.yml"))
        )
        if not set_folders:
            raise MinimalBotEvaluationError(
                f"No evaluation sets found under {eval_root}."
            )

        if only_globs and source_folder is None:
            scoped = [
                folder for folder in set_folders
                if _folder_matches_globs(folder, root, only_globs)
            ]
            if not scoped:
                raise MinimalBotEvaluationError(
                    "No evaluation sets matched the requested --only/--only-from "
                    f"scope: {only_globs}. Refusing to fall back to a broader "
                    "push affecting unselected sets."
                )
            set_folders = scoped

        files: dict[str, str] = {}
        for folder in set_folders:
            if any(path.parent != folder for path in folder.rglob("*.mcs.yml")):
                raise MinimalBotEvaluationError(
                    "Nested evaluation documents are not supported in a selected set."
                )
            try:
                validate_evaluation_folder(folder)
            except EvaluationMethodError as exc:
                raise MinimalBotEvaluationError(str(exc)) from exc
            paths = sorted(folder.glob("*.mcs.yml"))
            if (folder / "review.json").is_file():
                paths.append(folder / "review.json")
            for path in paths:
                files[f"evaluations/{folder.name}/{path.name}"] = path.read_text(
                    encoding="utf-8"
                )
        review_outcome: dict[str, Any] = {"reviewMetadataPersisted": False}
        if any(path.endswith("/review.json") for path in files):
            review_outcome["reviewWarning"] = NATIVE_REVIEW_LOCAL_ONLY_WARNING

        target = {
            "environmentId": self.environment_id,
            "botId": self.bot_id,
            "ring": self.ring,
        }
        fingerprint = hashlib.sha256(
            json.dumps(files, sort_keys=True).encode("utf-8")
        ).hexdigest()
        pending_path = root / ".evaluation-pending.json"
        pending = self._read_tracking(pending_path)
        component_map = self._read_tracking(root / ".component-map.json")
        prefixes = tuple(f"evaluations/{folder.name}/" for folder in set_folders)
        tracking = {
            "entries": {
                path: entry for path, entry in component_map.items()
                if path.startswith(prefixes)
            },
            "baseline": {
                f"evaluations/{folder.name}/{path.name}": path.read_text(encoding="utf-8")
                for folder in set_folders
                for path in (root / ".baseline" / "evaluations" / folder.name).glob("*")
                if path.is_file() and (path.name.endswith(".mcs.yml") or path.name == "review.json")
            },
        }
        if pending:
            if pending.get("target") != target or pending.get("fingerprint") != fingerprint:
                raise MinimalBotEvaluationError(
                    "An unresolved native deployment has a different target or "
                    "source. Reconcile that deployment before pushing again."
                )
            plan = pending
        if plan is not None and (
            plan.get("target") != target or plan.get("fingerprint") != fingerprint
        ):
            raise MinimalBotEvaluationError(
                "The selected native deployment changed after preview. Preview again."
            )
        if plan is not None and not pending and plan.get("tracking") != tracking:
            raise MinimalBotEvaluationError(
                "Native tracking changed after preview. Preview again instead of inserting a duplicate."
            )
        if plan is None:
            changes = []
            entries = {}
            pushed_sets = []
            for folder in set_folders:
                paths = sorted(folder.glob("*.mcs.yml"))
                relative_paths = [f"evaluations/{folder.name}/{path.name}" for path in paths]
                tracked = [path for path in relative_paths if path in component_map]
                baseline = root / ".baseline" / "evaluations" / folder.name
                baseline_files = {
                    path.relative_to(root / ".baseline").as_posix():
                    path.read_text(encoding="utf-8")
                    for path in baseline.glob("*.mcs.yml")
                }
                selected_files = {path: files[path] for path in relative_paths}
                reuse = baseline_files == selected_files and len(tracked) == len(paths)
                if reuse:
                    folder_changes = []
                    for relative in relative_paths:
                        entry = component_map[relative]
                        if (
                            not isinstance(entry, dict)
                            or entry.get("nativeTarget") != target
                            or not isinstance(entry.get("nativeDefinition"), dict)
                            or not entry.get("botcomponentid") or not entry.get("name")
                        ):
                            raise MinimalBotEvaluationError(
                                "Native deployment tracking is incomplete or "
                                "belongs to a different target. Reconcile it first."
                            )
                        folder_changes.append({"component": {
                            "id": entry["botcomponentid"],
                            "parentBotComponentId": entry.get("parentbotcomponentid"),
                            "definition": entry["nativeDefinition"],
                        }})
                        entries[relative] = entry
                    parents = [
                        entry for entry in (component_map[path] for path in relative_paths)
                        if not entry.get("parentbotcomponentid")
                    ]
                    if len(parents) != 1:
                        raise MinimalBotEvaluationError("Native parent identity is ambiguous.")
                    parent_id = parents[0]["botcomponentid"]
                    display_name = parents[0]["name"]
                else:
                    folder_changes, parent_id, display_name = self._folder_changes(folder)
                    parents = [
                        path for path in paths
                        if document_kind(yaml.safe_load(
                            files[f"evaluations/{folder.name}/{path.name}"]
                        ), context=str(path))
                        == "EvaluationSet"
                    ]
                    ordered = parents + [path for path in paths if path not in parents]
                    for path, change in zip(ordered, folder_changes):
                        component = change["component"]
                        entries[f"evaluations/{folder.name}/{path.name}"] = {
                            "botcomponentid": component["id"],
                            "parentbotcomponentid": component.get("parentBotComponentId"),
                            "componenttype": 19,
                            "schemaname": component["schemaName"],
                            "name": display_name if path in parents else path.stem,
                            "description": "",
                            "nativeDefinition": component["definition"],
                            "nativeTarget": target,
                        }
                    changes.extend(folder_changes)
                pushed_sets.append({
                    "folder": folder.name,
                    "testSetId": parent_id,
                    "displayName": display_name,
                    "cases": str(len(paths) - 1),
                })
            plan = {
                "target": target, "fingerprint": fingerprint, "files": files,
                "changes": changes, "entries": entries, "sets": pushed_sets,
                "componentCount": len(changes),
                "tracking": tracking,
            }
        if set(plan.get("files", {})) != set(files) or plan.get("files") != files:
            raise MinimalBotEvaluationError("The native plan does not match selected files.")
        if dry_run:
            return {**plan, "dryRun": True, "status": "ready", **review_outcome}

        before = self.read_components()
        expected = self._expected_components(plan)
        inserted_ids = {_component_id(change) for change in plan["changes"]}
        actual = self._remote_components(before)
        existing_ids = set(expected) - inserted_ids
        self._verify_components(expected, actual, existing_ids)
        present_new = inserted_ids & set(actual)
        if present_new:
            self._verify_components(expected, actual, inserted_ids)
        elif pending and inserted_ids:
            raise MinimalBotEvaluationError(
                "The prior native write has an uncertain outcome and its IDs "
                "are not visible. No automatic replay was performed."
            )
        if inserted_ids and not present_new:
            change_token = str(before.get("changeToken") or "")
            if not change_token:
                raise MinimalBotEvaluationError(
                    "MinimalBot component read did not return a changeToken."
                )
            self._write_tracking(pending_path, plan, exclusive=True)
            response, _ = self._request(
                "PUT", self._components_url,
                body={
                    "changeToken": change_token,
                    "botComponentChanges": plan["changes"],
                    "connectionReferenceChanges": [],
                    "connectorDefinitionChanges": [],
                },
                operation="push",
            )
            if response.status_code != 200:
                raise MinimalBotEvaluationError(
                    f"MinimalBot push failed (HTTP {response.status_code}); "
                    "pending IDs retained for reconciliation."
                )
            actual = self._remote_components(self.read_components())
        self._verify_components(expected, actual, set(expected))
        current = {}
        for folder in set_folders:
            for path in folder.rglob("*.mcs.yml"):
                if path.parent != folder:
                    raise MinimalBotEvaluationError(
                        "Source changed during deployment: nested evaluation document added."
                    )
                current[f"evaluations/{folder.name}/{path.name}"] = path.read_text(
                    encoding="utf-8"
                )
            if (folder / "review.json").is_file():
                current[f"evaluations/{folder.name}/review.json"] = (
                    (folder / "review.json").read_text(encoding="utf-8")
                )
        if current != plan["files"]:
            raise MinimalBotEvaluationError(
                "Source changed during native deployment. Remote state may be "
                "committed; local synchronization was not recorded."
            )
        self._commit_tracking(root, plan)
        if inserted_ids and pending_path.exists():
            saved_pending = self._read_tracking(pending_path)
            if saved_pending.get("fingerprint") != fingerprint or saved_pending.get("target") != target:
                raise MinimalBotEvaluationError(
                    "Pending deployment ownership changed; refusing to clear another deployment."
                )
            pending_path.unlink()
        return {
            "dryRun": False,
            "status": "pushed" if inserted_ids else "up_to_date",
            "sets": plan["sets"],
            "componentCount": len(plan["changes"]),
            "verifiedComponents": len(expected),
            **review_outcome,
        }

    @staticmethod
    def _read_tracking(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MinimalBotEvaluationError(f"Unable to read native tracking {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise MinimalBotEvaluationError(f"Invalid native tracking object: {path}")
        return value

    @staticmethod
    def _write_tracking(
        path: Path, value: dict[str, Any], *, exclusive: bool = False,
    ) -> None:
        from push import _atomic_write_text
        try:
            content = json.dumps(value, indent=2)
            if exclusive:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            else:
                _atomic_write_text(str(path), content)
        except OSError as exc:
            raise MinimalBotEvaluationError(
                f"Unable to persist native tracking {path}: {exc}"
            ) from exc

    def verify_deployed_components(
        self, plan: dict[str, Any], response: dict[str, Any],
    ) -> None:
        """Verify every component tracked by a deployment plan."""
        expected = self._expected_components(plan)
        self._verify_components(
            expected, self._remote_components(response), set(expected),
        )

    @staticmethod
    def _expected_components(plan: dict[str, Any]) -> dict[str, Any]:
        entries = plan.get("entries")
        if not isinstance(entries, dict) or not entries or any(
            not isinstance(entry, dict) or not entry.get("botcomponentid")
            or not isinstance(entry.get("nativeDefinition"), dict)
            for entry in entries.values()
        ):
            raise MinimalBotEvaluationError("Invalid native identity/definition tracking.")
        expected = {
            entry["botcomponentid"]: {
                "definition": entry["nativeDefinition"],
                "parentBotComponentId": entry.get("parentbotcomponentid"),
            }
            for entry in entries.values()
        }
        if len(expected) != len(entries):
            raise MinimalBotEvaluationError("Duplicate native tracked component identities.")
        return expected

    @staticmethod
    def _remote_components(response: dict[str, Any]) -> dict[str, Any]:
        changes = response.get("botComponentChanges")
        if not isinstance(changes, list):
            raise MinimalBotEvaluationError("Native component response has no change list.")
        components = {}
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("component"), dict):
                raise MinimalBotEvaluationError("Malformed native component response.")
            component = change["component"]
            component_id = str(component.get("id") or "")
            if not component_id or component_id in components:
                raise MinimalBotEvaluationError("Missing or duplicate native component identity.")
            components[component_id] = component
        return components

    @staticmethod
    def _verify_components(expected, actual, ids) -> None:
        for component_id in ids:
            remote = actual.get(component_id)
            wanted = expected[component_id]
            if (
                remote is None
                or remote.get("definition") != wanted["definition"]
                or remote.get("parentBotComponentId") != wanted.get("parentBotComponentId")
            ):
                raise MinimalBotEvaluationError(
                    f"Native verification failed for component {component_id}: "
                    "missing component, different definition, or parent mismatch."
                )
        for parent_id in ids:
            if expected[parent_id].get("parentBotComponentId"):
                continue
            expected_children = {
                component_id for component_id, component in expected.items()
                if component.get("parentBotComponentId") == parent_id
            }
            actual_children = {
                component_id for component_id, component in actual.items()
                if component.get("parentBotComponentId") == parent_id
            }
            if expected_children != actual_children:
                raise MinimalBotEvaluationError(
                    f"Native verification failed for {parent_id}: different child identities."
                )

    def _commit_tracking(self, root: Path, plan: dict[str, Any]) -> None:
        from push import _atomic_write_text
        prefixes = tuple(f"evaluations/{item['folder']}/" for item in plan["sets"])
        component_map = {
            path: entry
            for path, entry in self._read_tracking(root / ".component-map.json").items()
            if not path.startswith(prefixes)
        }
        component_map.update(plan["entries"])
        try:
            for item in plan["sets"]:
                baseline = root / ".baseline" / "evaluations" / item["folder"]
                for path in baseline.glob("*"):
                    if (
                        path.is_file()
                        and (path.name.endswith(".mcs.yml") or path.name == "review.json")
                        and (
                            path.name == "review.json"
                            or path.relative_to(root / ".baseline").as_posix() not in plan["files"]
                        )
                    ):
                        path.unlink()
            # Only uploaded YAML belongs in the deployed baseline; sidecars stay local.
            for relative, content in plan["files"].items():
                if relative.endswith("/review.json"):
                    continue
                path = root / ".baseline" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(str(path), content)
            self._write_tracking(root / ".component-map.json", component_map)
        except OSError as exc:
            raise MinimalBotEvaluationError(
                "Native deployment verified remotely, but local synchronization "
                f"failed. Reconcile the pending deployment before continuing: {exc}"
            ) from exc

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

        parents = [
            item for item in documents
            if document_kind(item[1], context=str(item[0])) == "EvaluationSet"
        ]
        cases = [
            item for item in documents
            if document_kind(item[1], context=str(item[0])) == "EvaluationData"
        ]
        # Never silently omit authored files. Any document whose kind this
        # transport can't convert (e.g. MultiTurnEvaluationCase, which is a
        # supported authored child elsewhere in the kit) must fail the push
        # rather than deploy a set that differs from local source.
        unsupported = [
            item for item in documents
            if document_kind(item[1], context=str(item[0])) not in _EVAL_KINDS
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
        """Bind tool profiles that can be resolved without blocking the run."""
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
            connections = self._connected(connector_id)
            if len(connections) != 1:
                continue
            connection = connections[0]
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
        deployed = self._remote_components(components)
        parent = deployed.get(test_set_id)
        if parent is None or parent.get("parentBotComponentId"):
            raise MinimalBotEvaluationError(
                "The selected deployed evaluation parent was not found on this agent."
            )
        children = [
            component.get("definition")
            for component in deployed.values()
            if component.get("parentBotComponentId") == test_set_id
        ]
        try:
            validate_evaluation_documents(
                parent.get("definition"), children,
                context=f"Deployed test set {test_set_id}",
            )
        except EvaluationMethodError as exc:
            raise MinimalBotEvaluationError(str(exc)) from exc
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
                run_name
                or f"{_component_name(parent)} - {now:%Y-%m-%d %H:%M UTC}"
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
