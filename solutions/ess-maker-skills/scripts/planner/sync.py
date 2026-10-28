"""Pure mapping seam between the local ``plan.json`` document and the planner
service's wire shape (the "sync seam").

The planner CLI never talks to the network — it only ever reads and writes the
local plan document. The *skill* orchestrates the remote calls (through the
planner tools) and shuttles JSON in and out of this module:

* **export** — :func:`to_remote_plan_body` turns the local plan into the single
  create body the service expects (``configuringAgentName`` + inline tasks), so
  a freshly designed plan can be pushed "as one object".
* **import** — :func:`hydrate_from_remote` rebuilds the local cache from the
  entities the service returns, so the service stays the source of truth and the
  local file is just a durable mirror.

Everything here is pure: dict in, dict out. No I/O, no network, no clock reads
except the ``syncedAt`` stamp. That keeps the mapping exhaustively unit-testable
and keeps the two vocabularies (local vs. service) from leaking into each other.

Vocabulary bridges handled here:

* Task state — the local model has ``Blocked`` where the service has
  ``Cancelled``; every other state is shared verbatim. ``Cancelled`` is only ever
  set server-side by the plan-archive cascade, so export never emits it.
* Acceptance criteria — local plans keep them as ordinary Context entries under
  the ``acceptanceCriteria`` group (one open bag); the service models them as a
  first-class ``acceptanceCriteria`` list. This module promotes them on export
  and demotes them back into the group on import.
* Assignee — the local ``assignedTo`` Principal is flattened to the service's
  ``assignedToId`` / ``assignedToType`` / ``assignedToRoleId`` triple on export
  and reconstructed on import.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from planner_payload import (
    PLAN_STORAGE_LIMIT_BYTES,
    ensure_plan_payload_fits,
    measure_plan_payload,
)
from planner.attestable import ATTESTABLE_ROLE_WIRE_NAMES, resolve_attestable_role_id
from planner.plan_model import (
    ACCEPTANCE_GROUP,
    CONFIGURING_AGENT_NAMES,
    PLAN_STATES,
    SCHEMA_VERSION,
    STREAM_GROUP,
    STREAM_MAP_GROUP,
    Limits,
    Plan,
    assignee_role_id,
    assignee_user_oid,
    context_entry,
    new_task,
    now_iso,
    plan_artifact,
    principal_person,
    principal_pool,
)

# The service task schema has no ``stream`` field, so ``to_remote_plan_body``
# round-trips each streamed task's label as a Context entry under ``STREAM_GROUP``,
# keyed by ``"<prefix><task title>"``. The title is the join key because the service
# reassigns task ids on push (``to_remote_task_body`` drops the local id), so the
# title is the only task identity that survives the round-trip; ``to_remote_plan_body``
# refuses ambiguous titles. When individual carriers exceed the export budget,
# versioned scalar maps preserve the same labels with fewer server-stamped entries.
# Both forms hydrate by title; older clients preserve the unfamiliar map group as
# ordinary context, which this exporter can recover on a later round-trip.
_STREAM_KEY_PREFIX = "stream:"
_STREAM_MAP_KEY_PREFIX = "streams.v1."


def _merge_streams(destination: dict[str, str], streams: dict[str, str]) -> None:
    for title, stream in streams.items():
        if title in destination and destination[title] != stream:
            raise ValueError("Conflicting workstream metadata for the same task title.")
        destination[title] = stream


def _decode_stream_map(key: str, value: Any) -> dict[str, str]:
    if not isinstance(key, str) or not key.startswith(_STREAM_MAP_KEY_PREFIX):
        raise ValueError("Unsupported workstream map version; update the kit before editing this plan.")
    if not isinstance(value, str):
        raise ValueError("Workstream map must be a JSON string.")

    def unique_pairs(pairs):
        result = {}
        for title, stream in pairs:
            if title in result:
                raise ValueError("Duplicate task title in workstream map.")
            result[title] = stream
        return result

    try:
        streams = json.loads(value, object_pairs_hook=unique_pairs)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid workstream map JSON; the plan was not replaced.") from exc
    if not isinstance(streams, dict) or not streams or any(
        not isinstance(title, str) or not title.strip()
        or not isinstance(stream, str) or not stream.strip()
        for title, stream in streams.items()
    ):
        raise ValueError("Workstream map must contain non-empty task titles and stream labels.")
    return streams


def _packed_stream_context(streams: dict[str, str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    chunk: dict[str, str] = {}

    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def emit():
        entries.append({
            "key": f"{_STREAM_MAP_KEY_PREFIX}{len(entries)}",
            "value": encode(chunk),
            "group": STREAM_MAP_GROUP,
        })

    for title, stream in sorted(streams.items()):
        candidate = {**chunk, title: stream}
        if len(encode(candidate)) > Limits.MAX_VALUE_LEN:
            if not chunk:
                raise ValueError("Workstream metadata is too long; shorten the task title or stream label.")
            emit()
            candidate = {title: stream}
            if len(encode(candidate)) > Limits.MAX_VALUE_LEN:
                raise ValueError("Workstream metadata is too long; shorten the task title or stream label.")
        chunk = candidate
    if chunk:
        emit()
    return entries


def _validate_export_context(context: list[dict[str, Any]]) -> None:
    if len(context) > Limits.MAX_CONTEXT_ENTRIES:
        raise ValueError(
            f"Shared export exceeds the kit's {Limits.MAX_CONTEXT_ENTRIES}-entry context budget "
            "after generated metadata. Consolidate redundant context without dropping requirements."
        )
    seen: set[str] = set()
    for entry in context:
        key = entry.get("key")
        if not isinstance(key, str) or not key or key in seen or len(key) > Limits.MAX_KEY_LEN:
            raise ValueError("Shared context keys must be unique, non-empty, and within the key limit.")
        seen.add(key)
        value = entry.get("value")
        if isinstance(value, (dict, list)) or len(str(value)) > Limits.MAX_VALUE_LEN:
            raise ValueError("Shared context values must be scalar and within the value limit.")

# The service's PlanTaskState enum, in declaration order (so an integer wire
# value can be resolved positionally). Only ``Cancelled`` differs from the local
# vocabulary — see the state-bridge helpers below.
_REMOTE_TASK_STATES = ("NotStarted", "InProgress", "Completed", "Cancelled")


# --------------------------------------------------------------------------- #
# Vocabulary bridges (state + status).
# --------------------------------------------------------------------------- #

def local_to_remote_state(state: str) -> str:
    """Map a local task state onto the service vocabulary (``Blocked`` →
    ``Cancelled``; everything else is shared).

    Export never actually sends state — new tasks always start ``NotStarted`` —
    but the bridge is exposed for completeness and symmetry with the importer.
    """
    return "Cancelled" if state == "Blocked" else state


def remote_task_state(raw: Any) -> str:
    """Map a service task state (name or ordinal) onto the local vocabulary.

    ``Cancelled`` becomes the local ``Blocked``; unknown values fall back to
    ``NotStarted`` so a partial/garbled read never corrupts the cache.
    """
    value: str | None = None
    if isinstance(raw, str) and raw:
        for state in _REMOTE_TASK_STATES:
            if state.lower() == raw.lower():
                value = state
                break
        else:
            value = raw
    elif isinstance(raw, bool):  # bool is an int subclass — guard before int.
        value = "NotStarted"
    elif isinstance(raw, int) and 0 <= raw < len(_REMOTE_TASK_STATES):
        value = _REMOTE_TASK_STATES[raw]
    if not value:
        value = "NotStarted"
    return "Blocked" if value == "Cancelled" else value


def remote_plan_status(raw: Any) -> str:
    """Map a service plan status (name or ordinal) onto the local vocabulary.

    The two vocabularies are identical (``Draft``/``Active``/``Completed``/
    ``Archived``); this only normalises case and resolves integers, defaulting to
    ``Draft`` for anything unrecognised.
    """
    if isinstance(raw, str) and raw:
        for status in PLAN_STATES:
            if status.lower() == raw.lower():
                return status
        return raw
    if isinstance(raw, bool):
        return "Draft"
    if isinstance(raw, int) and 0 <= raw < len(PLAN_STATES):
        return PLAN_STATES[raw]
    return "Draft"


# --------------------------------------------------------------------------- #
# Export — local plan  ->  service create body.
# --------------------------------------------------------------------------- #

def _to_wire_role(role_label: str | None) -> str | None:
    """Canonicalize a role label to the backend **wire display name** for export.

    The service stores attestation grants under the wire display name (that is
    what :func:`attest_plan_role` posts), but the local plan and ``model.md`` key
    roles by the compact id. A role-pooled task only surfaces to its attested
    holders when its ``assignedToId`` matches the grant verbatim (the service
    compares with Ordinal equality), so fold the compact id to the wire name on
    the way out. A non-attestable label — which the service would reject anyway —
    passes through unchanged so no maker intent is silently dropped.
    """
    if not role_label:
        return role_label
    compact = resolve_attestable_role_id(role_label)
    if compact is None:
        return role_label
    return ATTESTABLE_ROLE_WIRE_NAMES.get(compact, role_label)


def _to_compact_role(role_label: str | None) -> str | None:
    """Canonicalize a role label back to the local **compact id** on import.

    Symmetric to :func:`_to_wire_role`: the service returns the wire display name,
    but local role matching is an exact string compare against the compact ids the
    agent and ``model.md`` use, so fold the wire name home. Non-attestable labels
    pass through unchanged.
    """
    if not role_label:
        return role_label
    return resolve_attestable_role_id(role_label) or role_label


def to_remote_task_body(task: dict[str, Any]) -> dict[str, Any]:
    """Flatten one local task into the service's task-create shape.

    Only the fields the service accepts are emitted — ``title`` (required),
    optional ``description`` / ``produces`` / ``consumes``, and a flattened
    assignee. Local-only fields (``id``, ``state``, ``checklist``, ``remoteId``,
    ``etag``) are dropped: the service assigns its own ids and new tasks always
    start ``NotStarted``.
    """
    body: dict[str, Any] = {"title": task.get("title", "")}

    description = task.get("description")
    if description:
        body["description"] = description

    assigned_to = task.get("assignedTo") or {}
    ptype = assigned_to.get("type")
    role_id = assignee_role_id(assigned_to)
    oid = assignee_user_oid(assigned_to)
    if ptype == "Role":
        # Open pool: anyone holding the role may claim it. Send the role as the
        # backend **wire display name** so it matches the attestation grant (which
        # ``attest_plan_role`` also stores under the wire name) — otherwise the
        # service's caller-task expansion compares a compact id against a display
        # name with Ordinal equality and the task never surfaces to its holders.
        body["assignedToType"] = "Role"
        body["assignedToId"] = _to_wire_role(assigned_to.get("id") or role_id or "")
        if role_id:
            body["assignedToRoleId"] = _to_wire_role(role_id)
    elif ptype == "User" and oid:
        # Owned by a person (default type User is left implicit). A retained role
        # rides along as the grounding ``assignedToRoleId`` — wire-named for parity
        # with attestation and the pooled case.
        body["assignedToId"] = oid
        if role_id:
            body["assignedToRoleId"] = _to_wire_role(role_id)
    # Otherwise unassigned — emit no assignee fields.

    produces = task.get("produces")
    if produces:
        body["produces"] = list(produces)
    consumes = task.get("consumes")
    if consumes:
        body["consumes"] = list(consumes)
    return body


def to_remote_output(artifact: dict[str, Any]) -> dict[str, Any]:
    """Map one local output artifact onto the service completion shape consumed by
    ``complete_project_plan_task(outputs=[...])``.

    The local model stores attributes as a flat ``{key: value}`` dict; the service
    (and the planner MCP's ``_normalize_completion_outputs``) wants a typed
    ``[{key, value}]`` list. Only the fields the tool accepts are emitted — ``key``,
    ``kind``, ``attributes`` and an optional ``inventoryRef`` — so the payload this
    produces can be handed straight to the tool. Local-only provenance (``source``,
    ``producedByTaskId``, ``state``) is dropped; the service stamps its own.
    """
    attributes = artifact.get("attributes") or {}
    kind = artifact.get("kind", "Custom")
    if kind in ("Agent", "EntraApp"):
        attributes = {**attributes, "artifactType": kind}
        kind = "Custom"
    wire: dict[str, Any] = {
        "key": artifact.get("key", ""),
        "kind": kind,
        "attributes": [{"key": k, "value": v} for k, v in attributes.items()],
    }
    inventory_ref = artifact.get("inventoryRef")
    if inventory_ref:
        wire["inventoryRef"] = inventory_ref
    return wire


def to_remote_plan_body(
    plan: Plan,
    *,
    configuring_agent_name: str | None = None,
) -> dict[str, Any]:
    """Turn the local plan into the single service create body.

    The service requires ``configuringAgentName`` and rejects unknown fields, so
    this emits *exactly* the allowed keys and omits every empty optional:

    * ``configuringAgentName`` — from the ``configuring_agent_name`` argument, or
      the plan's stored value. Required: raises :class:`ValueError` if neither is
      set or the value is not a known agent.
    * ``acceptanceCriteria`` — promoted from Context entries in the
      ``acceptanceCriteria`` group (their scalar values, in order).
    * ``context`` — every *other* Context entry as ``{key, value, group?,
      description?}`` (provenance is server-stamped, never sent).
    * ``tasks`` — the plan's tasks, each via :func:`to_remote_task_body`.
    """
    name = configuring_agent_name or plan.configuring_agent_name
    if not name:
        raise ValueError(
            "configuringAgentName is required to push a plan — set it first "
            "(one of " + ", ".join(CONFIGURING_AGENT_NAMES) + ")"
        )
    if name not in CONFIGURING_AGENT_NAMES:
        raise ValueError(
            f"invalid configuringAgentName {name!r} — must be one of "
            + ", ".join(CONFIGURING_AGENT_NAMES)
        )

    acceptance: list[str] = []
    context: list[dict[str, Any]] = []
    carried_streams: dict[str, str] = {}
    for entry in plan.context:
        if entry.get("group") == ACCEPTANCE_GROUP:
            acceptance.append(entry.get("value"))
            continue
        # Stream carriers are re-derived from the tasks below, so never echo a
        # stale one back (keeps the round-trip idempotent).
        if entry.get("group") == STREAM_GROUP:
            continue
        if entry.get("group") == STREAM_MAP_GROUP:
            _merge_streams(
                carried_streams,
                _decode_stream_map(entry.get("key", ""), entry.get("value")),
            )
            continue
        item: dict[str, Any] = {"key": entry.get("key"), "value": entry.get("value")}
        group = entry.get("group")
        if group:
            item["group"] = group
        description = entry.get("description")
        if description:
            item["description"] = description
        context.append(item)

    # Carry each task's local-only ``stream`` label through the service as Context
    # (the task schema has no field for it) so the grouped task view is preserved
    # after a publish/pull round-trip. Reattached and stripped by import.
    #
    # The carrier joins back to its task by title (the local id isn't sent — the
    # service assigns its own), and titles are not required to be unique. A streamed
    # task sharing a title with another task would collide on one carrier and
    # silently regroup on pull, so refuse to export that rather than corrupt the
    # plan — the maker gives the tasks distinct titles first.
    title_counts: dict[str, int] = {}
    for task in plan.tasks:
        title = (task.get("title") or "").strip()
        if title:
            title_counts[title] = title_counts.get(title, 0) + 1
    streams: dict[str, str] = {}
    for task in plan.tasks:
        title = (task.get("title") or "").strip()
        stream = (task.get("stream", carried_streams.get(title)) or "").strip()
        if not stream or not title:
            continue
        if title_counts[title] > 1:
            raise ValueError(
                f"cannot export plan: task title {title!r} is shared by "
                f"{title_counts[title]} tasks but carries a workstream label that "
                "round-trips by title; give these tasks distinct titles before "
                "pushing so their grouping can't be silently merged"
            )
        streams[title] = stream

    body: dict[str, Any] = {"configuringAgentName": name}
    if acceptance:
        body["acceptanceCriteria"] = acceptance
    ordinary_context = context
    context = ordinary_context + [
        {"key": f"{_STREAM_KEY_PREFIX}{title}", "value": stream, "group": STREAM_GROUP}
        for title, stream in streams.items()
    ]
    if context:
        body["context"] = context
    if streams and (
        len(context) > Limits.MAX_CONTEXT_ENTRIES
        or any(
            isinstance(entry.get("key"), str) and len(entry["key"]) > Limits.MAX_KEY_LEN
            for entry in context
        )
        or measure_plan_payload(body).estimated_bytes > PLAN_STORAGE_LIMIT_BYTES
    ):
        context = ordinary_context + _packed_stream_context(streams)
        body["context"] = context
    _validate_export_context(context)
    ensure_plan_payload_fits(body)
    tasks = [to_remote_task_body(task) for task in plan.tasks]
    if tasks:
        body["tasks"] = tasks
    return body


# --------------------------------------------------------------------------- #
# Import — service entities  ->  local plan document.
# --------------------------------------------------------------------------- #

def _scalar(entity: Any, *names: str, default: Any = "") -> Any:
    """Read the first present, non-null field from ``entity`` by any of ``names``.

    The SDK declares camelCase, but the live OData endpoint may render PascalCase,
    so callers pass every plausible spelling and this also falls back to a
    case-insensitive match.
    """
    if not isinstance(entity, dict):
        return default
    for name in names:
        if entity.get(name) is not None:
            return entity[name]
    lowered = {str(k).lower(): v for k, v in entity.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return default


def _obj(entity: Any, *names: str) -> dict[str, Any]:
    value = _scalar(entity, *names, default=None)
    return value if isinstance(value, dict) else {}


def _list(entity: Any, *names: str) -> list[Any]:
    value = _scalar(entity, *names, default=None)
    return value if isinstance(value, list) else []


def _as_entities(payload: Any) -> list[dict[str, Any]]:
    """Normalise a task payload into a plain list of entities.

    Tolerates ``None``, a bare list, or an OData collection wrapper
    (``{"value": [...]}``).
    """
    if payload is None:
        return []
    if isinstance(payload, dict):
        payload = payload.get("value")
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    raise ValueError("task payload must be a list of task objects or an OData value collection")


def _principal_from_remote(task: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a local ``assignedTo`` Principal from a service task.

    Prefers the expanded ``assignedTo`` object, falling back to the flat
    ``assignedToId`` / ``assignedToRoleId`` fields. A role without a person is an
    open pool; a person (optionally carrying a grounding role) is an owner.
    """
    principal = _obj(task, "assignedTo", "AssignedTo")
    ptype = _scalar(principal, "type", "Type", default="") if principal else ""
    # Fall back to the flat assignedToType when the principal isn't expanded (e.g.
    # a create body echoed back before the service hydrates the reference).
    if not ptype:
        ptype = _scalar(task, "assignedToType", "AssignedToType", default="")

    role_id = _scalar(task, "assignedToRoleId", "AssignedToRoleId", default="")
    oid = _scalar(task, "assignedToId", "AssignedToId", default="")
    if principal:
        pid = _scalar(principal, "id", "Id", default="")
        if ptype == "Role" and not role_id:
            role_id = pid
        elif ptype == "User" and not oid:
            oid = pid

    if ptype == "Role":
        # Open pool — the role id may arrive as assignedToRoleId or (since a pool's
        # assignedToId *is* the role id) as assignedToId. The service carries the
        # wire display name; fold it back to the local compact id so local role
        # matching (an exact string compare) stays uniform.
        pool_role = role_id or oid
        return principal_pool(_to_compact_role(pool_role)) if pool_role else {}
    if role_id and not oid:
        return principal_pool(_to_compact_role(role_id))
    if oid:
        return principal_person(oid, _to_compact_role(role_id) or None)
    return {}


def _task_from_remote(task: dict[str, Any]) -> dict[str, Any]:
    """Rebuild one local task dict from a service task entity."""
    remote_id = _scalar(task, "taskId", "TaskId", "id", "Id", default="")
    local = new_task(
        remote_id,
        _scalar(task, "title", "Title", default=""),
        description=_scalar(task, "description", "Description", default=""),
        assigned_to=_principal_from_remote(task),
        produces=_list(task, "produces", "Produces"),
        consumes=_list(task, "consumes", "Consumes"),
        state=remote_task_state(_scalar(task, "state", "State", default="NotStarted")),
    )
    local["remoteId"] = remote_id
    local["etag"] = _scalar(task, "etag", "ETag", "@odata.etag", default="")
    return local


def _output_from_remote(artifact: dict[str, Any]) -> dict[str, Any]:
    """Rebuild one local output artifact from a service ``PlanArtifact``.

    The service models attributes as a typed list; the local model stores them as
    a flat ``{key: value}`` dict, so the description on each entry is dropped.
    """
    attributes: dict[str, Any] = {}
    for attr in _list(artifact, "attributes", "Attributes"):
        if isinstance(attr, dict):
            key = _scalar(attr, "key", "Key", default="")
            if key:
                attributes[key] = _scalar(attr, "value", "Value", default="")

    kind = _scalar(artifact, "kind", "Kind", default="Custom")
    if not isinstance(kind, str):
        kind = "Custom"
    state = _scalar(artifact, "state", "State", default="Active")
    if not isinstance(state, str) or not state:
        state = "Active"
    return plan_artifact(
        _scalar(artifact, "key", "Key", default=""),
        kind,
        attributes,
        produced_by_task_id=_scalar(artifact, "producedByTaskId", "ProducedByTaskId", default=""),
        inventory_ref=_scalar(artifact, "inventoryRef", "InventoryRef", default="") or None,
        source="Agent",
        state=state,
    )


def extract_json_payload(text: str) -> Any:
    """Return the payload JSON from a (possibly enveloped) tool-result dump.

    When a planner tool's result is large, the Copilot CLI spills it to a temp
    file as the structured payload followed by a *second* top-level
    ``{"result": "<stringified payload>"}`` document — both carry identical data.
    A single-document parser (PowerShell's ``ConvertFrom-Json`` or a bare
    ``json.loads``) chokes on that concatenation ("Additional text encountered
    after finished reading JSON content"), which is why the sync flow must not
    hand-stitch the ``{plan, tasks}`` object itself. This reads the first complete
    JSON value and ignores any trailing envelope, so raw tool-output files can be
    fed straight to ``import-remote-plan``.

    If the first document is itself a lone ``{"result": ...}`` envelope (the inner
    payload may be a nested object or a JSON-encoded string), it is unwrapped.
    """
    decoder = json.JSONDecoder()
    index, length = 0, len(text)
    # Tolerate a leading BOM and surrounding whitespace before the first value.
    while index < length and text[index] in " \t\r\n\ufeff":
        index += 1
    if index >= length:
        raise ValueError("tool output contained no JSON")
    try:
        value, _ = decoder.raw_decode(text, index)
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse JSON from tool output: {exc}") from exc
    return _unwrap_result_envelope(value)


def _unwrap_result_envelope(value: Any) -> Any:
    """Unwrap a lone ``{"result": <payload>}`` harness envelope (string or object)."""
    if isinstance(value, dict) and set(value) == {"result"}:
        inner = value["result"]
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return inner
        return inner
    return value


def hydrate_from_remote(
    plan_entity: dict[str, Any],
    task_entities: Any = None,
) -> dict[str, Any]:
    """Rebuild a local ``plan.json`` document from service entities.

    ``plan_entity`` is a single service ``Plan``; ``task_entities`` is the task
    collection (a list, an OData ``{"value": [...]}`` wrapper, or ``None`` to use
    the plan's embedded ``agentPlanTasks`` expansion). The result is a plain dict
    ready to hand to :meth:`Plan.load`/``save_all`` — the service stays the source
    of truth, so this never runs local validation.
    """
    if not isinstance(plan_entity, dict):
        raise ValueError("plan_entity must be a service Plan object")

    # ``None`` means "tasks weren't fetched — use the plan's embedded expansion";
    # an explicit collection (even an empty ``{"value": []}``) is the service
    # authoritatively stating the task set, so it must NOT fall back to the
    # embedded ``agentPlanTasks`` (that would resurrect tasks deleted upstream).
    if task_entities is None:
        tasks_raw = _as_entities(_scalar(plan_entity, "agentPlanTasks", "AgentPlanTasks", default=None))
    else:
        tasks_raw = _as_entities(task_entities)

    context: list[dict[str, Any]] = []
    task_streams: dict[str, str] = {}
    for entry in _list(plan_entity, "context", "Context"):
        if not isinstance(entry, dict):
            continue
        group = _scalar(entry, "group", "Group", default="")
        if group == STREAM_MAP_GROUP:
            _merge_streams(task_streams, _decode_stream_map(
                _scalar(entry, "key", "Key", default=""),
                _scalar(entry, "value", "Value", default=None),
            ))
            continue
        # Stream carriers are an internal round-trip vehicle, not maker context:
        # capture them (title -> stream) to reattach to tasks below, then drop them
        # so the local plan never carries the ``taskStream`` group.
        if group == STREAM_GROUP:
            key = _scalar(entry, "key", "Key", default="")
            title = key[len(_STREAM_KEY_PREFIX):] if key.startswith(_STREAM_KEY_PREFIX) else key
            stream = _scalar(entry, "value", "Value", default="")
            if title and stream:
                _merge_streams(task_streams, {title: stream})
            continue
        context.append(
            context_entry(
                _scalar(entry, "key", "Key", default=""),
                _scalar(entry, "value", "Value", default=""),
                group=group or None,
                description=_scalar(entry, "description", "Description", default="") or None,
                source="Agent",
            )
        )
    # Demote the service's first-class acceptance criteria back into the Context
    # bag under the acceptance group (stable, unique keys).
    for index, criterion in enumerate(_list(plan_entity, "acceptanceCriteria", "AcceptanceCriteria"), start=1):
        context.append(
            context_entry(
                f"acceptance.{index}",
                criterion,
                group=ACCEPTANCE_GROUP,
                description="Acceptance criterion",
                source="Agent",
            )
        )

    tasks = [_task_from_remote(t) for t in tasks_raw if isinstance(t, dict)]
    # Reattach the workstream labels the service can't store natively.
    if task_streams:
        for task in tasks:
            stream = task_streams.get((task.get("title") or "").strip())
            if stream:
                task["stream"] = stream
    outputs = [_output_from_remote(a) for a in _list(plan_entity, "outputs", "Outputs") if isinstance(a, dict)]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "planId": _scalar(plan_entity, "planId", "PlanId", "id", "Id", default=""),
        "projectId": _scalar(plan_entity, "projectId", "ProjectId", default=""),
        "configuringAgentName": _scalar(plan_entity, "configuringAgentName", "ConfiguringAgentName", default=""),
        "status": remote_plan_status(_scalar(plan_entity, "status", "Status", default="Draft")),
        "context": context,
        "tasks": tasks,
        "outputs": outputs,
        "etag": _scalar(plan_entity, "etag", "ETag", "@odata.etag", default=""),
        "syncedAt": now_iso(),
    }


def preserve_local_pending(
    hydrated: dict[str, Any],
    local: dict[str, Any] | None,
    *,
    created_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Carry an unpushed local completion across a pull so the service's stale
    state can't silently revert it.

    ``import-remote-plan`` rebuilds the local cache wholesale from the service (the
    service is the source of truth). But a task completed locally and flagged
    ``pendingSync`` has NOT reached the service yet, so the freshly hydrated copy
    would show it ``NotStarted`` again — clobbering the completion and its outputs.
    For each such local task this re-applies ``Completed`` + ``pendingSync`` onto the
    matching hydrated task (matched by ``remoteId`` then ``id``) and re-pins the
    outputs it produced when the pull didn't carry them, so the completion — and the
    invariant that a Completed task's produces resolve — survives until a push lands.
    Only matching completion state AND the expected output values acknowledge a
    completion. Partial outputs are retained without completing their task.
    A first share must supply its successful ``created_plan`` response, matched
    to the readback identity, before local task titles can be associated with
    server-assigned IDs. An ordinary pull cannot attach an unassociated draft.

    Returns ``hydrated`` (mutated in place); without a create response, a
    missing/empty ``local`` is a no-op.
    """
    first_share = created_plan is not None
    if created_plan is not None:
        if not isinstance(local, dict) or local.get("planId"):
            raise ValueError("a create response can only associate an existing unshared local draft")
        created = hydrate_from_remote(created_plan)
        created_id = created.get("planId")
        if not isinstance(created_id, str) or not created_id.strip() or created_id != hydrated.get("planId"):
            raise ValueError("the successful create response must identify the same plan as the readback")
        if created.get("projectId") and hydrated.get("projectId") and created["projectId"] != hydrated["projectId"]:
            raise ValueError("the successful create response belongs to a different project than the readback")
    if not isinstance(local, dict):
        return hydrated
    local_tasks = [
        t for t in local.get("tasks", [])
        if isinstance(t, dict) and (t.get("pendingSync") or t.get("pendingOutputs"))
    ]
    if not local_tasks:
        return hydrated
    if not local.get("planId") and hydrated.get("planId") and not first_share:
        raise ValueError(
            "this draft's pending work has no shared-plan association; provide its "
            "successful create response with --created-plan-file for the first share, "
            "or reconcile the separate plans before importing"
        )
    if (
        (local.get("planId") and local["planId"] != hydrated.get("planId"))
        or (local.get("projectId") and hydrated.get("projectId") and local["projectId"] != hydrated["projectId"])
    ):
        raise ValueError("pending changes belong to a different shared plan; sync them before switching")

    hydrated_tasks = hydrated.setdefault("tasks", [])
    by_remote = {t.get("remoteId"): t for t in hydrated_tasks if t.get("remoteId")}
    by_id = {t.get("id"): t for t in hydrated_tasks if t.get("id")}
    hydrated_outputs = hydrated.setdefault("outputs", [])
    local_outputs = local.get("outputs", [])
    if not isinstance(local_outputs, list):
        local_outputs = []

    for lt in local_tasks:
        match = by_remote.get(lt.get("remoteId")) or by_id.get(lt.get("id"))
        if match is None and first_share:
            # Only the confirmed first share can associate server-assigned IDs
            # by title; an unrelated shared plan is not a continuation of a draft.
            candidates = [t for t in hydrated_tasks if t.get("title") == lt.get("title")]
            local_candidates = [
                t for t in local.get("tasks", [])
                if isinstance(t, dict) and t.get("title") == lt.get("title")
            ]
            if len(candidates) != 1 or len(local_candidates) != 1:
                raise ValueError(
                    f"first-share task {lt.get('id')!r} has no unique title match; "
                    "reconcile the create response and task readback before importing"
                )
            match = candidates[0]
        expected = [
            a for a in local_outputs
            if a.get("producedByTaskId") == lt.get("id") and a.get("state") == "Active"
        ]
        outputs_confirmed = all(
            any(
                a.get("state") == "Active"
                and a.get("producedByTaskId") == (match or {}).get("id")
                and _output_confirmed(artifact, a)
                for a in hydrated_outputs
            )
            for artifact in expected
        )
        if match is None:
            # The completion was never pushed, so the service doesn't know this
            # task at all — keep the local copy wholesale rather than drop it.
            match = copy.deepcopy(lt)
            match["syncConflict"] = "This task is absent from the shared plan; reconcile it before retrying."
            hydrated_tasks.append(match)
        elif outputs_confirmed and (not lt.get("pendingSync") or match.get("state") == "Completed"):
            match.pop("pendingSync", None)
            match.pop("pendingOutputs", None)
            continue
        else:
            if lt.get("pendingSync"):
                match["state"] = "Completed"
                match["pendingSync"] = True
            if lt.get("pendingOutputs"):
                match["pendingOutputs"] = True
            # Keep the original write precondition: a newer ETag must not turn
            # an offline write into an unconditional overwrite of another edit.
            if lt.get("etag"):
                match["etag"] = lt["etag"]

        if not (match.get("pendingSync") or match.get("pendingOutputs")):
            continue
        # Re-pin the outputs this unpushed completion produced that the pull didn't
        # carry, so the Completed task's declared produces still resolve locally.
        target_id = match.get("id")
        for art in expected:
            existing = [a for a in hydrated_outputs if a.get("key") == art.get("key") and a.get("state") == "Active"]
            if any(_output_confirmed(art, a) and a.get("producedByTaskId") == target_id for a in existing):
                continue
            for a in existing:
                a["state"] = "Superseded"
                match["syncConflict"] = "Shared outputs differ from the local result; review before retrying."
            carried = copy.deepcopy(art)
            carried["producedByTaskId"] = target_id
            hydrated_outputs.append(carried)
    return hydrated


def _output_confirmed(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    wanted, received = to_remote_output(expected), to_remote_output(actual)
    attributes = {a["key"]: a.get("value") for a in received["attributes"]}
    return (
        wanted["key"] == received["key"]
        and wanted["kind"] == received["kind"]
        and (not wanted.get("inventoryRef") or wanted["inventoryRef"] == received.get("inventoryRef"))
        and all(a.get("value") == attributes.get(a["key"]) and a["key"] in attributes for a in wanted["attributes"])
    )


def pending_sync_payload(plan: Plan) -> dict[str, Any]:
    """The exact arguments the agent needs to push each pending-sync completion to
    the shared planner via ``complete_project_plan_task``.

    Read-only. Returns ``{projectId, planId, tasks: [...]}`` where each task carries
    the service ``taskId`` (its ``remoteId``), the ETag to guard the PATCH, and the
    produced ``outputs`` already mapped to the tool's completion shape
    (:func:`to_remote_output`). An empty ``tasks`` list means nothing is pending.
    """
    tasks: list[dict[str, Any]] = []
    for task in plan.ordered_tasks():
        if not task.get("pendingSync"):
            continue
        outputs = [
            to_remote_output(art)
            for art in plan.outputs_of_task(task.get("id", ""))
            if art.get("state") == "Active"
        ]
        tasks.append({
            "taskId": task.get("remoteId") or task.get("id", ""),
            "localId": task.get("id", ""),
            "title": task.get("title", ""),
            "etag": task.get("etag", ""),
            "state": task.get("state", ""),
            "outputs": outputs,
            "operation": "complete_project_plan_task" if outputs else "set_project_plan_task_state",
            "conflict": task.get("syncConflict", ""),
        })
    return {
        "projectId": plan.data.get("projectId", ""),
        "planId": plan.data.get("planId", ""),
        "tasks": tasks,
        "pendingOutputs": [
            {"taskId": t.get("remoteId") or t["id"], "title": t.get("title", "")}
            for t in plan.tasks if t.get("pendingOutputs")
        ],
    }


def stamp_remote_ids(
    plan: Plan,
    *,
    project_id: str,
    plan_id: str,
    plan_etag: str | None = None,
    synced_at: str | None = None,
) -> Plan:
    """Record the service ids/ETag a locally-authored plan now mirrors.

    Used after pushing a plan the maker designed offline, when re-hydrating from
    the service would be wasteful — only the identity needs to be stamped.
    """
    plan.set_remote_identity(
        project_id=project_id,
        plan_id=plan_id,
        etag=plan_etag,
        synced_at=synced_at,
    )
    return plan
