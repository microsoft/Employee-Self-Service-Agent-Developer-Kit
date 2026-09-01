# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: the local Plan data model.

This module owns the structured, on-disk Plan that the ``/planner`` skill
authors (``workspace/plan/plan.json``). It is deliberately shaped like the
WeveNova ``Plan`` / ``AgentConfigurationTask`` entities described in the
"Plan Enrichment & Persistence" (Step 2) design so a future sync is a field
copy, not a re-model:

  * All sponsor/agent intent lives in ONE open ``context`` bag of
    ``ContextEntry`` records (key + scalar value + group + description +
    provenance).
  * Each Task carries one extended ``assignedTo`` Principal that can name a
    role, a person, or a person acting as a role (the pool / claimed /
    direct-for-role states).
  * A Task is described by its ``title`` + ``description`` — the "how" (which
    kit command, or a portal/manual step) lives in the ``description``; there is
    deliberately **no** separate ``action`` field.
  * Produced artifacts land in a single ``outputs`` ledger, keyed and
    supersede-on-rewrite, each stamped with the producing task id.
  * An optional, read-back-only ``checklist`` on a Task carries step-level
    display state a skill fills at runtime (steps are never first-class).

The Plan is authoritative on disk and works with WeveNova, tenant inventory,
and the roles source all absent. Writes are atomic (temp file + ``os.replace``
+ ``fsync``), mirroring ``scripts/setup.py`` so a crash mid-write cannot
corrupt the file that drives the whole experience.

Nothing here reaches the network; it is pure data + local file IO.
"""

from __future__ import annotations

import heapq
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

# Default on-disk locations (relative to the kit root — the cwd the skill runs
# from, same convention as .local/config.json and workspace/agents/).
PLAN_DIR = os.path.join("workspace", "plan")
PLAN_PATH = os.path.join(PLAN_DIR, "plan.json")
# The plan's human-readable Markdown view. It is an *editable* surface — a Plan
# editor can revise it directly and the planner reconciles the changes back into
# plan.json (see src/skills/planner/edit.md) — regenerated from plan.json after
# every mutation. Named for the editor ("ESS scenario plan"), not "summary".
SUMMARY_FILENAME = "ESS-scenario-plan.md"
SUMMARY_PATH = os.path.join(PLAN_DIR, SUMMARY_FILENAME)
RESEARCH_PATH = os.path.join(PLAN_DIR, "research-context.json")

# Controlled vocabularies. Kept as plain tuples (not Enums) because the values
# are serialized verbatim to JSON and read back by an agent — the string IS the
# contract.
TASK_STATES = ("NotStarted", "InProgress", "Completed", "Blocked")
ARTIFACT_STATES = ("Active", "Superseded")
PRINCIPAL_TYPES = ("User", "Role")
CONTEXT_SOURCES = ("User", "Agent", "Discovered")
ARTIFACT_KINDS = ("Environment", "Connection", "EntraApp", "KnowledgeSource", "Agent", "Custom")
# Plan lifecycle vocab (mirrors the WeveNova PlanStatus enum). A local plan lives
# in Draft until the sync seam pushes and activates it server-side.
PLAN_STATES = ("Draft", "Active", "Completed", "Archived")
# The ESS agent a plan configures (mirrors the WeveNova ConfiguringAgentName enum).
# Required on the create body, so a plan must name one before it can be pushed.
CONFIGURING_AGENT_NAMES = (
    "EmployeeSelfServiceHRCEA",
    "EmployeeSelfServiceHRDA",
    "EmployeeSelfServiceITCEA",
    "EmployeeSelfServiceITDA",
)
# The ledger key the /setup task produces and downstream tasks consume — the
# grounded signal used to identify the setup task and env-dependent tasks. A Task
# is described only by its title + description (matching the WeveNova Task
# entity); there is no execution-hint/action field.
PRIMARY_ENVIRONMENT_KEY = "primaryEnvironment"
DEPENDENCY_KINDS = ("requires", "recommends")
# Scenario dependency lives in the open Context bag (no new typed collection),
# consistent with the "one Context bag" model. A scenario in scope is a Context
# entry in SCENARIO_GROUP; a dependency edge is an entry in DEPENDS_ON_GROUP whose
# key encodes "<dependent> -> <prerequisite>" and whose scalar value is the kind.
SCENARIO_GROUP = "scenario"
DEPENDS_ON_GROUP = "scenarioDependsOn"
_DEP_SEP = " -> "
# Acceptance criteria (definition-of-done) live in the open Context bag under this
# group so the local model stays a single bag; the sync seam promotes them to the
# WeveNova Plan's first-class acceptanceCriteria list on export and back on import.
ACCEPTANCE_GROUP = "acceptanceCriteria"


class Limits:
    """Writer-enforced caps, following the Step-2 §8 / ``Project.Metadata`` caps."""

    MAX_TASKS = 50
    MAX_OUTPUTS = 50
    MAX_CONTEXT_ENTRIES = 64
    MAX_PRODUCES = 20
    MAX_CHECKLIST = 40
    MAX_KEY_LEN = 128
    MAX_VALUE_LEN = 2000
    MAX_DESCRIPTION_LEN = 1000
    MAX_ATTRIBUTES = 32


def now_iso() -> str:
    """UTC timestamp in the ``2026-07-30T18:00:00Z`` shape used across the kit."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Value-object builders (return plain dicts — JSON is the wire format).
# --------------------------------------------------------------------------- #

def role_ref(role_id: str, directory_ref: str | None = None) -> dict[str, Any]:
    # Step-2 §7.4: Principal.Role = { roleId, directoryRef? }.
    ref: dict[str, Any] = {"roleId": role_id}
    if directory_ref:
        ref["directoryRef"] = directory_ref
    return ref


def user_ref(oid: str, directory_ref: str | None = None) -> dict[str, Any]:
    # Step-2 §7.4: Principal.User = { oid, directoryRef? }.
    ref: dict[str, Any] = {"oid": oid}
    if directory_ref:
        ref["directoryRef"] = directory_ref
    return ref


def principal_pool(role_id: str, directory_ref: str | None = None) -> dict[str, Any]:
    """State 1 — open to a role: nobody owns it yet, any holder of R can claim."""
    return {"type": "Role", "id": role_id, "role": role_ref(role_id, directory_ref)}


def principal_person(
    oid: str, role_id: str | None = None, directory_ref: str | None = None
) -> dict[str, Any]:
    """A person owns it. With ``role_id`` this is the claimed / direct-for-role
    state (role retained); without, a plain person assignment."""
    p: dict[str, Any] = {"type": "User", "id": oid, "user": user_ref(oid, directory_ref)}
    if role_id:
        p["role"] = role_ref(role_id)
    return p


def assignee_role_id(assigned_to: dict[str, Any] | None) -> str | None:
    """The grounded role a task is attached to, whether pooled or owned."""
    if not assigned_to:
        return None
    role = assigned_to.get("role")
    if isinstance(role, dict):
        return role.get("roleId")
    return None


def assignee_user_oid(assigned_to: dict[str, Any] | None) -> str | None:
    """The individual who owns a task, or None while it is an open pool."""
    if not assigned_to or assigned_to.get("type") != "User":
        return None
    user = assigned_to.get("user")
    if isinstance(user, dict):
        return user.get("oid")
    return assigned_to.get("id")


def provenance(
    source: str,
    added_by: dict[str, Any] | None = None,
    added_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "addedBy": added_by or {},
        "addedAt": added_at or now_iso(),
    }


def context_entry(
    key: str,
    value: Any,
    *,
    group: str | None = None,
    description: str | None = None,
    source: str = "User",
    added_by: dict[str, Any] | None = None,
    added_at: str | None = None,
) -> dict[str, Any]:
    """A single self-describing intent fact. ``value`` is a scalar; related
    facts are separate entries sharing a ``group`` (never a nested object)."""
    return {
        "key": key,
        "value": value,
        "group": group or "",
        "description": description or "",
        "provenance": provenance(source, added_by, added_at),
    }


def plan_artifact(
    key: str,
    kind: str,
    attributes: dict[str, Any],
    *,
    produced_by_task_id: str,
    inventory_ref: str | None = None,
    source: str = "Agent",
    added_by: dict[str, Any] | None = None,
    added_at: str | None = None,
    state: str = "Active",
) -> dict[str, Any]:
    """A pinned, concrete artifact a completed task produced (the forked state)."""
    return {
        "key": key,
        "kind": kind,
        "attributes": dict(attributes),
        "inventoryRef": inventory_ref or "",
        "producedByTaskId": produced_by_task_id,
        "provenance": provenance(source, added_by, added_at),
        "state": state,
    }


def new_task(
    task_id: str,
    title: str,
    *,
    description: str = "",
    assigned_to: dict[str, Any] | None = None,
    produces: Iterable[str] | None = None,
    consumes: Iterable[str] | None = None,
    checklist: list[dict[str, Any]] | None = None,
    state: str = "NotStarted",
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": task_id,
        "title": title,
        "description": description,
        "assignedTo": assigned_to or {},
        "state": state,
        "produces": list(produces or []),
        "consumes": list(consumes or []),
    }
    if checklist:
        task["checklist"] = list(checklist)
    return task


def dependency_key(scenario: str, depends_on: str) -> str:
    """The Context key for a scenario dependency edge: ``"<dep> -> <prereq>"``."""
    return f"{scenario}{_DEP_SEP}{depends_on}"


def parse_dependency_key(key: str) -> tuple[str, str]:
    """Split a dependency key back into ``(scenario, depends_on)``."""
    parts = key.split(_DEP_SEP, 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (key, "")


def known_scenario_dependencies() -> list[dict[str, str]]:
    """The scenario dependencies the planner knows about, read from the vendored
    non-Learn facts file (``planner_facts.json``).

    These are *not* a scenario list — an edge only takes effect when the maker
    independently puts both its scenarios in scope. Each edge carries an explicit
    ``source``; the planner never fabricates a citation. A missing/empty facts
    file simply yields no known dependencies (nothing invented)."""
    try:
        from . import facts

        return facts.scenario_dependency_edges()
    except Exception:  # noqa: BLE001 — facts are best-effort; never fail a read
        return []


# --------------------------------------------------------------------------- #
# The Plan.
# --------------------------------------------------------------------------- #

class Plan:
    """A thin, validated wrapper over the plan.json document.

    The class holds the raw dict (``self.data``) so round-tripping to JSON is
    lossless and the agent-readable shape is never obscured behind typed
    objects. Mutators keep invariants (unique task ids, supersede-by-key
    outputs); ``validate`` reports cap / vocabulary violations without raising.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    # ---- construction / IO ---------------------------------------------- #

    @classmethod
    def new(cls, *, objective: str | None = None) -> "Plan":
        data: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "planId": "",
            "projectId": "",
            "configuringAgentName": "",
            "status": "Draft",
            "context": [],
            "tasks": [],
            "outputs": [],
            "etag": "",
            "syncedAt": "",
        }
        plan = cls(data)
        if objective:
            plan.set_context("objective", objective, group="objective",
                             description="Plain-language goal the sponsor stated",
                             source="User")
        return plan

    @classmethod
    def load(cls, path: str | os.PathLike[str] = PLAN_PATH) -> "Plan":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Old / partial documents deserialize to sensible empties.
        data.setdefault("schemaVersion", SCHEMA_VERSION)
        for key in ("context", "tasks", "outputs"):
            data.setdefault(key, [])
        for key in ("planId", "projectId", "configuringAgentName", "etag", "syncedAt"):
            data.setdefault(key, "")
        data.setdefault("status", "Draft")
        return cls(data)

    @classmethod
    def load_or_new(cls, path: str | os.PathLike[str] = PLAN_PATH) -> "Plan":
        if os.path.exists(path):
            return cls.load(path)
        return cls.new()

    def save(self, path: str | os.PathLike[str] = PLAN_PATH) -> None:
        """Atomically write plan.json (temp + fsync + os.replace).

        Mirrors ``scripts/setup.py`` so a crash mid-write can never leave a
        half-written file that breaks a later read.
        """
        path = os.fspath(path)
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                # Some network filesystems don't support fsync; os.replace is
                # still atomic on POSIX and Windows.
                pass
        os.replace(tmp, path)

    def write_summary(self, path: str | os.PathLike[str] = SUMMARY_PATH) -> None:
        path = os.fspath(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        Path(path).write_text(self.render_summary(), encoding="utf-8")

    def save_all(self, plan_path: str | os.PathLike[str] = PLAN_PATH) -> None:
        """Write plan.json and regenerate the Markdown view alongside it."""
        self.save(plan_path)
        summary = os.path.join(os.path.dirname(os.fspath(plan_path)) or ".", SUMMARY_FILENAME)
        self.write_summary(summary)

    # ---- convenience accessors ------------------------------------------ #

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return self.data["tasks"]

    @property
    def context(self) -> list[dict[str, Any]]:
        return self.data["context"]

    @property
    def outputs(self) -> list[dict[str, Any]]:
        return self.data["outputs"]

    def task(self, task_id: str) -> dict[str, Any] | None:
        for t in self.tasks:
            if t.get("id") == task_id:
                return t
        return None

    # ---- remote identity (sync seam) ------------------------------------ #

    @property
    def configuring_agent_name(self) -> str:
        return self.data.get("configuringAgentName", "")

    def set_configuring_agent_name(self, name: str) -> None:
        """Name the ESS agent this plan configures — required before a sync push.

        Must be one of :data:`CONFIGURING_AGENT_NAMES` (mirrors the WeveNova
        ``ConfiguringAgentName`` enum).
        """
        if name not in CONFIGURING_AGENT_NAMES:
            raise ValueError(
                "configuringAgentName must be one of " + ", ".join(CONFIGURING_AGENT_NAMES)
            )
        self.data["configuringAgentName"] = name

    def set_remote_identity(
        self,
        *,
        project_id: str | None = None,
        plan_id: str | None = None,
        etag: str | None = None,
        synced_at: str | None = None,
    ) -> None:
        """Record the server ids / ETag this local cache now mirrors (sync seam).

        ``syncedAt`` is refreshed to *now* unless an explicit value is given.
        Only the arguments that are not ``None`` are written, so a partial stamp
        (e.g. project id before the plan exists) leaves the rest untouched.
        """
        if project_id is not None:
            self.data["projectId"] = project_id
        if plan_id is not None:
            self.data["planId"] = plan_id
        if etag is not None:
            self.data["etag"] = etag
        self.data["syncedAt"] = synced_at if synced_at is not None else now_iso()

    # ---- context (intent) mutators -------------------------------------- #

    def set_context(
        self,
        key: str,
        value: Any,
        *,
        group: str | None = None,
        description: str | None = None,
        source: str = "User",
        added_by: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add or overwrite-in-place a context entry (latest state only).

        On overwrite the original ``addedBy``/``addedAt`` are preserved and
        ``updatedBy``/``updatedAt`` are refreshed — creator + last editor,
        no per-key history (Step-2 §7.6).
        """
        for entry in self.context:
            if entry.get("key") == key:
                entry["value"] = value
                if group is not None:
                    entry["group"] = group
                if description is not None:
                    entry["description"] = description
                prov = entry.setdefault("provenance", provenance(source, added_by))
                prov["source"] = source
                prov["updatedBy"] = added_by or {}
                prov["updatedAt"] = now_iso()
                return entry
        entry = context_entry(
            key, value, group=group, description=description,
            source=source, added_by=added_by,
        )
        self.context.append(entry)
        return entry

    def set_system(self, area: str, system: str, *, source: str = "User") -> dict[str, Any]:
        """Record the target system for one scenario/area under a scoped key.

        Systems are captured per area (``system.<area>``) so two areas never
        collide on a single reused key: e.g. ``system.hr-knowledge = Workday``
        and ``system.it-ticketing = ServiceNow ITSM`` coexist. ``area`` is a
        scenario id or a short slug; the value is the system name the maker gave.
        """
        slug = area.strip().lower().replace(" ", "-")
        return self.set_context(
            f"system.{slug}", system, group="system",
            description=f"Target system for {area}", source=source,
        )

    # ---- task mutators --------------------------------------------------- #

    def add_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if self.task(task["id"]) is not None:
            raise ValueError(f"duplicate task id: {task['id']!r}")
        self.tasks.append(task)
        return task

    def assign_task(
        self,
        task_id: str,
        *,
        role_id: str | None = None,
        person_oid: str | None = None,
    ) -> dict[str, Any]:
        """Set a task's assignee. Rules realising Flow 1:

          * ``person_oid`` + ``role_id`` -> direct-for-role (person owns it,
            role retained).
          * ``role_id`` only            -> open pool (any holder can claim).
          * ``person_oid`` only         -> plain person (no role).
        """
        task = self._require_task(task_id)
        if person_oid:
            task["assignedTo"] = principal_person(person_oid, role_id=role_id)
        elif role_id:
            task["assignedTo"] = principal_pool(role_id)
        else:
            raise ValueError("assign_task needs role_id and/or person_oid")
        return task

    def claim_task(self, task_id: str, person_oid: str) -> dict[str, Any]:
        """A holder of the task's role picks it up (pool -> claimed). The role
        is retained so the task still groups under it in Flow 2. Only an **open
        role pool** can be claimed — claiming a task already assigned to a person
        (or one with no role) is rejected so an existing owner is never silently
        replaced and the role is never erased."""
        task = self._require_task(task_id)
        assigned = task.get("assignedTo") or {}
        role = assignee_role_id(assigned)
        if assigned.get("type") != "Role" or not role:
            raise ValueError(
                f"task {task_id!r} is not an open role pool "
                f"(assignedTo.type={assigned.get('type')!r}); only pooled tasks can be claimed"
            )
        task["assignedTo"] = principal_person(person_oid, role_id=role)
        return task

    def set_task_state(self, task_id: str, state: str) -> dict[str, Any]:
        if state not in TASK_STATES:
            raise ValueError(f"invalid task state: {state!r}")
        task = self._require_task(task_id)
        # Invariant enforced for EVERY caller (not just the capture CLI): a task
        # cannot be Completed while its declared `produces` have no Active
        # artifact — that would leave a completed producer with blocked consumers.
        if state == "Completed":
            missing = self.unresolved_produces(task_id)
            if missing:
                raise ValueError(
                    f"task {task_id!r} cannot be Completed — unresolved produces {missing}; "
                    "pin those outputs first (capture-setup / pin-output)"
                )
        task["state"] = state
        return task

    def set_checklist(self, task_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace a task's read-back-only step checklist (display state)."""
        task = self._require_task(task_id)
        task["checklist"] = list(items)
        return task

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        produces: list[str] | None = None,
        consumes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing task's content in place — used when reconciling a
        Plan editor's Markdown edit back into plan.json (src/skills/planner/edit.md).

        Only the WeveNova ``Task`` content fields (title, description, produces,
        consumes) are touched here; the assignee/role goes through ``assign_task``
        and state through ``set_task_state``. A ``None`` argument leaves that field
        unchanged."""
        task = self._require_task(task_id)
        if title is not None:
            task["title"] = title
        if description is not None:
            task["description"] = description
        if produces is not None:
            task["produces"] = list(produces)
        if consumes is not None:
            task["consumes"] = list(consumes)
        return task

    def remove_task(self, task_id: str) -> dict[str, Any]:
        """Remove a task (reconciling a deletion from the Markdown view) and return
        it. Raises ``KeyError`` on an unknown id so a mistyped id fails loudly
        rather than silently doing nothing."""
        task = self._require_task(task_id)
        self.tasks.remove(task)
        return task

    # ---- output ledger --------------------------------------------------- #

    def add_output(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Pin an artifact, superseding any Active artifact with the same key
        (append-and-supersede, never delete — Step-2 §8)."""
        key = artifact["key"]
        for existing in self.outputs:
            if existing.get("key") == key and existing.get("state") == "Active":
                existing["state"] = "Superseded"
        self.outputs.append(artifact)
        return artifact

    def output(self, key: str) -> dict[str, Any] | None:
        """The current Active artifact for a ledger key (what downstream reads)."""
        for art in reversed(self.outputs):
            if art.get("key") == key and art.get("state") == "Active":
                return art
        return None

    def unresolved_produces(self, task_id: str) -> list[str]:
        """A task's declared ``produces`` keys that have no Active artifact yet.

        A task should not be marked ``Completed`` while its declared outputs are
        still unresolved — otherwise it becomes a completed producer while
        downstream consumers stay blocked."""
        task = self.task(task_id)
        if not task:
            return []
        return [k for k in (task.get("produces") or []) if self.output(k) is None]

    def outputs_of_task(self, task_id: str) -> list[dict[str, Any]]:
        """"This task's outputs" = the ledger filtered by producing id (no copy)."""
        return [a for a in self.outputs if a.get("producedByTaskId") == task_id]

    def resolved_consumes(self, task_id: str) -> dict[str, Any]:
        """For each key a task consumes, the Active artifact's attributes (or
        ``None`` if not produced yet). This is how a downstream assignee learns,
        e.g., the ``environmentId`` the setup task produced — the back-propagation."""
        task = self._require_task(task_id)
        resolved: dict[str, Any] = {}
        for key in task.get("consumes", []):
            art = self.output(key)
            resolved[key] = art.get("attributes", {}) if art else None
        return resolved

    def blocking_inputs(self, task_id: str) -> dict[str, list[str]]:
        """The task's consumed keys that have **no Active artifact yet**, each
        mapped to the task ids declared to produce them.

        This is the produces/consumes readiness signal: a task cannot truly
        start (nor be legitimately ``Completed``) while it consumes an artifact
        nothing has produced. Returns ``{key: [producerTaskId, ...]}`` for every
        unmet key — the producer list is empty for an external input no task in
        the plan produces. A task with no entry here is ready on the artifact
        model. Pure/read-only: reflects the current ledger, never mutates it."""
        task = self.task(task_id)
        if not task:
            return {}
        unmet: dict[str, list[str]] = {}
        for key in (task.get("consumes") or []):
            if self.output(key) is not None:
                continue  # satisfied by an Active artifact
            producers = [
                t.get("id")
                for t in self.tasks
                if key in (t.get("produces") or []) and t.get("id") != task_id
            ]
            unmet[key] = [p for p in producers if p]
        return unmet

    def waiting_on(self, task_id: str) -> list[str]:
        """Flattened, de-duplicated, sorted list of what a task is blocked on:
        the upstream producer task ids for its unproduced consumed artifacts,
        plus ``needs <key>`` for any consumed key nothing in the plan produces.
        Empty when the task is ready. Drives the task-list dependency marker."""
        tokens: list[str] = []
        for key, producers in self.blocking_inputs(task_id).items():
            if producers:
                tokens.extend(producers)
            else:
                tokens.append(f"needs {key}")
        return sorted(dict.fromkeys(tokens))

    def dependency_marker(self, task_id: str) -> str:
        """Compact task-list marker for artifact readiness: ``""`` when the task
        is ready (all consumed artifacts produced, or it consumes nothing), else
        the comma-joined :meth:`waiting_on` tokens (e.g. ``"T2"`` or
        ``"T1, T2"``). Render-time only — reflects the produces/consumes ledger,
        never mutates it, and never changes stored task sequence or state."""
        return ", ".join(self.waiting_on(task_id))

    def setup_task_id(self) -> str | None:
        """The plan's setup task id — the task that **produces** the primary
        environment (`primaryEnvironment`), i.e. the ``/setup`` task. Prefers the
        first not-yet-Completed such task, else the first one; ``None`` if no task
        produces it. Keyed on the grounded ``produces`` signal, not on any
        execution-hint field."""
        candidates = [
            t for t in self.tasks
            if PRIMARY_ENVIRONMENT_KEY in (t.get("produces") or [])
        ]
        if not candidates:
            return None
        for t in candidates:
            if t.get("state") != "Completed":
                return t["id"]
        return candidates[0]["id"]

    def kit_setup_nudge(self, task_id: str) -> dict[str, Any] | None:
        """Whether this task's assignee should run ``/setup`` to connect their own
        kit to the plan's environment before starting.

        The Power Platform admin's setup task decides or creates the environment
        and pins ``primaryEnvironment``. Every *other* task that **consumes**
        `primaryEnvironment` runs against that same environment, but each
        assignee's local kit must be connected to it first (via ``/setup``) — a
        per-person step the pinned plan value can't do for them. So:

        - Returns ``{environmentId, environmentUrl}`` when the task **consumes**
          `primaryEnvironment` (needs the env), does **not** produce it, and the
          plan already has an environment pinned — nudge this persona to run
          ``/setup`` and connect to that env.
        - Returns ``None`` for the setup task itself (it produces the env), for
          tasks that don't need the env, or when no environment is pinned yet.
        """
        task = self._require_task(task_id)
        produces = task.get("produces") or []
        consumes = task.get("consumes") or []
        if PRIMARY_ENVIRONMENT_KEY in produces:
            return None  # this IS the setup task
        if PRIMARY_ENVIRONMENT_KEY not in consumes:
            return None  # doesn't need the connected environment
        env = self.output(PRIMARY_ENVIRONMENT_KEY)
        if not env:
            return None
        attrs = env.get("attributes", {})
        return {
            "environmentId": attrs.get("environmentId", ""),
            "environmentUrl": attrs.get("environmentUrl", ""),
        }

    def task_brief(self, task_id: str) -> dict[str, Any]:
        """A briefing for a task's assignee: what to do (title + description), the
        role, the resolved values it consumes (e.g. the env id to use), and the
        keys to capture when done."""
        task = self._require_task(task_id)
        return {
            "id": task["id"],
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "role": assignee_role_id(task.get("assignedTo")),
            "assignee": assignee_user_oid(task.get("assignedTo")),
            "state": task.get("state", ""),
            "kitSetup": self.kit_setup_nudge(task_id),
            "consumes": self.resolved_consumes(task_id),
            "blockedBy": self.blocking_inputs(task_id),
            "produces": list(task.get("produces", [])),
        }

    # ---- scenario dependencies (open Context bag, not a typed collection) - #

    def in_scope_scenarios(self) -> dict[str, str]:
        """Scenario id -> label for scenarios in scope (Context group 'scenario')."""
        return {
            e["key"]: e.get("value", "")
            for e in self.context
            if e.get("group") == SCENARIO_GROUP
        }

    def scenario_dependencies(self) -> list[dict[str, Any]]:
        """Dependency edges parsed from the Context bag (group 'scenarioDependsOn').

        Each edge: ``{scenario, dependsOn, kind, rationale, provenance}``. The
        Plan stores these as ordinary Context entries — there is no separate
        typed collection — so they round-trip and read back like any intent.
        """
        edges: list[dict[str, Any]] = []
        for e in self.context:
            if e.get("group") != DEPENDS_ON_GROUP:
                continue
            scenario, depends_on = parse_dependency_key(e.get("key", ""))
            edges.append(
                {
                    "scenario": scenario,
                    "dependsOn": depends_on,
                    "kind": e.get("value", ""),
                    "rationale": e.get("description", ""),
                    "provenance": e.get("provenance", {}),
                }
            )
        return edges

    def add_scenario_dependency(
        self,
        scenario: str,
        depends_on: str,
        *,
        kind: str = "requires",
        rationale: str = "",
        source: str = "Agent",
    ) -> dict[str, Any]:
        """Record that ``scenario`` depends on ``depends_on`` as a Context entry.

        ``source`` is the Context provenance source ("Agent" when the planner
        asserts it from the PM spec / research, "User" when the sponsor states
        it); the PM-spec citation lives in ``rationale``.
        """
        if scenario == depends_on:
            raise ValueError("a scenario cannot depend on itself")
        if kind not in DEPENDENCY_KINDS:
            raise ValueError(f"invalid dependency kind: {kind!r}")
        return self.set_context(
            dependency_key(scenario, depends_on),
            kind,
            group=DEPENDS_ON_GROUP,
            description=rationale,
            source=source,
        )

    def scenario_dependency_status(self) -> list[dict[str, Any]]:
        """Every scenario-dependency edge whose dependent scenario is in scope,
        each tagged ``met`` (prerequisite also in scope) or not.

        Merges edges captured on this plan with the known non-Learn facts, so
        callers can show *both* satisfied and unmet dependencies (not only the
        gaps). De-dupes on ``(scenario, dependsOn)``, plan edges winning.
        """
        in_scope = set(self.in_scope_scenarios())
        edges = self.scenario_dependencies()
        have = {(e["scenario"], e["dependsOn"]) for e in edges}
        for edge in known_scenario_dependencies():
            pair = (edge["scenario"], edge["dependsOn"])
            if edge["scenario"] in in_scope and pair not in have:
                edges.append({**edge, "provenance": {"source": edge.get("source", "")}})
        status: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for edge in edges:
            pair = (edge["scenario"], edge["dependsOn"])
            if edge["scenario"] in in_scope and pair not in seen:
                seen.add(pair)
                status.append({**edge, "met": edge["dependsOn"] in in_scope})
        return status

    def unmet_scenario_dependencies(self, *, include_known: bool = True) -> list[dict[str, Any]]:
        """Edges whose dependent scenario is in scope but whose prerequisite
        scenario is not — what to surface to the sponsor. Merges the PM-spec seed
        (for in-scope scenarios) with edges captured on this plan."""
        in_scope = set(self.in_scope_scenarios())
        edges = self.scenario_dependencies()
        if include_known:
            have = {(e["scenario"], e["dependsOn"]) for e in edges}
            for edge in known_scenario_dependencies():
                pair = (edge["scenario"], edge["dependsOn"])
                if edge["scenario"] in in_scope and pair not in have:
                    edges.append({**edge, "provenance": {"source": "Agent"}})
        unmet: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for edge in edges:
            pair = (edge["scenario"], edge["dependsOn"])
            if edge["scenario"] in in_scope and edge["dependsOn"] not in in_scope and pair not in seen:
                unmet.append(edge)
                seen.add(pair)
        return unmet

    # ---- Flow 2: discovery ---------------------------------------------- #

    def tasks_for_person(
        self, person_oid: str, roles: Iterable[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Group a person's tasks by role for the "what am I assigned?" view.

        Returns ``{roleId: [{"task": <task>, "relation": "assigned"|"pool"}]}``.
        Covers both tasks assigned directly to the person (bucketed by the
        task's retained role) and open pools for any role the person holds —
        which is how a multi-role person sees everything waiting on them.
        """
        role_set = set(roles)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for task in self.ordered_tasks():
            if task.get("state") == "Completed":
                continue  # Flow 2 surfaces work still waiting, not finished tasks
            assigned = task.get("assignedTo") or {}
            role = assignee_role_id(assigned) or "(no role)"
            owner = assignee_user_oid(assigned)
            if assigned.get("type") == "User" and owner == person_oid:
                grouped.setdefault(role, []).append(
                    {"task": task, "relation": "assigned", "waitingOn": self.waiting_on(task.get("id"))}
                )
            elif assigned.get("type") == "Role" and assignee_role_id(assigned) in role_set:
                grouped.setdefault(role, []).append(
                    {"task": task, "relation": "pool", "waitingOn": self.waiting_on(task.get("id"))}
                )
        return grouped

    # ---- validation ------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty == valid)."""
        errors: list[str] = []
        d = self.data

        if d.get("schemaVersion") != SCHEMA_VERSION:
            errors.append(f"schemaVersion should be {SCHEMA_VERSION}")

        agent_name = d.get("configuringAgentName")
        if agent_name and agent_name not in CONFIGURING_AGENT_NAMES:
            errors.append(f"invalid configuringAgentName: {agent_name!r}")

        # Context
        if len(self.context) > Limits.MAX_CONTEXT_ENTRIES:
            errors.append(f"too many context entries (> {Limits.MAX_CONTEXT_ENTRIES})")
        seen_ctx: set[str] = set()
        for i, entry in enumerate(self.context):
            key = entry.get("key", "")
            if not key:
                errors.append(f"context[{i}] missing key")
            if key in seen_ctx:
                errors.append(f"context key not unique: {key!r}")
            seen_ctx.add(key)
            if len(str(key)) > Limits.MAX_KEY_LEN:
                errors.append(f"context key too long: {key!r}")
            if isinstance(entry.get("value"), (dict, list)):
                errors.append(f"context[{key}] value must be scalar, not nested")
            if len(str(entry.get("value", ""))) > Limits.MAX_VALUE_LEN:
                errors.append(f"context[{key}] value too long")
            src = (entry.get("provenance") or {}).get("source")
            if src and src not in CONTEXT_SOURCES:
                errors.append(f"context[{key}] invalid provenance source: {src!r}")
            if entry.get("group") == DEPENDS_ON_GROUP:
                if entry.get("value") not in DEPENDENCY_KINDS:
                    errors.append(f"scenario dependency {key!r} invalid kind: {entry.get('value')!r}")
                dep_from, dep_to = parse_dependency_key(key)
                if not dep_to or dep_from == dep_to:
                    errors.append(f"scenario dependency {key!r} malformed (expected 'A -> B')")

        # Tasks
        if len(self.tasks) > Limits.MAX_TASKS:
            errors.append(f"too many tasks (> {Limits.MAX_TASKS})")
        seen_task: set[str] = set()
        for i, task in enumerate(self.tasks):
            tid = task.get("id", "")
            if not tid:
                errors.append(f"tasks[{i}] missing id")
            if tid in seen_task:
                errors.append(f"task id not unique: {tid!r}")
            seen_task.add(tid)
            if task.get("state") not in TASK_STATES:
                errors.append(f"task {tid!r} invalid state: {task.get('state')!r}")
            errors.extend(self._validate_assignee(tid, task.get("assignedTo")))
            if len(task.get("produces", [])) > Limits.MAX_PRODUCES:
                errors.append(f"task {tid!r} too many produces keys")
            if len(task.get("checklist", [])) > Limits.MAX_CHECKLIST:
                errors.append(f"task {tid!r} too many checklist items")

        # Outputs
        if len(self.outputs) > Limits.MAX_OUTPUTS:
            errors.append(f"too many outputs (> {Limits.MAX_OUTPUTS})")
        for i, art in enumerate(self.outputs):
            if not art.get("key"):
                errors.append(f"outputs[{i}] missing key")
            if art.get("kind") not in ARTIFACT_KINDS:
                errors.append(f"outputs[{art.get('key')!r}] invalid kind: {art.get('kind')!r}")
            if art.get("state") not in ARTIFACT_STATES:
                errors.append(f"outputs[{art.get('key')!r}] invalid state: {art.get('state')!r}")
            if not art.get("producedByTaskId"):
                errors.append(f"outputs[{art.get('key')!r}] missing producedByTaskId")
            elif art.get("producedByTaskId") not in seen_task:
                errors.append(
                    f"outputs[{art.get('key')!r}] references unknown task "
                    f"{art.get('producedByTaskId')!r}"
                )
            if len(art.get("attributes", {})) > Limits.MAX_ATTRIBUTES:
                errors.append(f"outputs[{art.get('key')!r}] too many attributes")

        # At most one Active artifact per key.
        active: dict[str, int] = {}
        for art in self.outputs:
            if art.get("state") == "Active":
                active[art.get("key", "")] = active.get(art.get("key", ""), 0) + 1
        for key, count in active.items():
            if count > 1:
                errors.append(f"output key {key!r} has {count} Active artifacts (max 1)")

        return errors

    @staticmethod
    def _validate_assignee(tid: str, assigned: Any) -> list[str]:
        errors: list[str] = []
        if not assigned:
            return errors  # unassigned draft task is allowed
        ptype = assigned.get("type")
        if ptype not in PRINCIPAL_TYPES:
            errors.append(f"task {tid!r} invalid assignee type: {ptype!r}")
        if ptype == "Role" and not assignee_role_id(assigned):
            errors.append(f"task {tid!r} role-assigned but no role.roleId")
        if ptype == "User" and not assignee_user_oid(assigned):
            errors.append(f"task {tid!r} user-assigned but no user.oid")
        return errors

    def _require_task(self, task_id: str) -> dict[str, Any]:
        task = self.task(task_id)
        if task is None:
            raise KeyError(f"no such task: {task_id!r}")
        return task

    # ---- rendering ------------------------------------------------------- #

    def ordered_tasks(self) -> list[dict[str, Any]]:
        """Tasks in execution order: a task that **produces** an artifact another
        task **consumes** is listed before that consumer.

        A stable topological sort over the ``produces``/``consumes`` ledger.
        Tasks with no dependency between them keep their original order (ties
        break by original position), so the view only reorders where a real
        producer -> consumer edge forces it. A ``produces``/``consumes`` cycle
        degrades gracefully — tasks still tangled in it are appended in original
        order — so rendering never drops or duplicates a task. Pure: it does not
        mutate the stored task order (the shared planner stays authoritative on
        sequence; this is a render-time convenience only)."""
        tasks = self.tasks
        n = len(tasks)
        if n < 2:
            return list(tasks)
        # Map each produced key to the task positions that produce it.
        producer_positions: dict[str, list[int]] = {}
        for i, task in enumerate(tasks):
            for key in (task.get("produces") or []):
                producer_positions.setdefault(key, []).append(i)
        # Edge producer -> consumer for every consumed key; indegree per consumer.
        successors: list[set[int]] = [set() for _ in range(n)]
        indegree = [0] * n
        for i, task in enumerate(tasks):
            producers: set[int] = set()
            for key in (task.get("consumes") or []):
                for p in producer_positions.get(key, []):
                    if p != i:
                        producers.add(p)
            for p in producers:
                if i not in successors[p]:
                    successors[p].add(i)
                    indegree[i] += 1
        # Kahn's algorithm; original position as a stable tie-break so
        # independent tasks never shuffle.
        ready = [i for i in range(n) if indegree[i] == 0]
        heapq.heapify(ready)
        order: list[int] = []
        while ready:
            i = heapq.heappop(ready)
            order.append(i)
            for j in sorted(successors[i]):
                indegree[j] -= 1
                if indegree[j] == 0:
                    heapq.heappush(ready, j)
        if len(order) < n:  # produces/consumes cycle — keep the rest as-is.
            placed = set(order)
            order.extend(i for i in range(n) if i not in placed)
        return [tasks[i] for i in order]

    def render_summary(self) -> str:
        """A human-readable Markdown view of the Plan — the editable surface a Plan
        editor revises directly; edits are reconciled back into plan.json
        (see src/skills/planner/edit.md)."""
        d = self.data
        lines: list[str] = []
        objective = self.output_value_or_context("objective") or "(objective not set)"
        lines.append(f"# Scenario plan — {objective}")
        lines.append("")
        planid = d.get("planId") or "(local, not synced)"
        agent = d.get("configuringAgentName") or "(agent not set)"
        header = f"Status: {d.get('status', '')}  |  Agent: {agent}  |  Plan: {planid}"
        if d.get("syncedAt"):
            header += f"  |  Synced: {d.get('syncedAt')}"
        lines.append(header)
        lines.append("")

        # Intent, grouped.
        if self.context:
            lines.append("## Intent")
            lines.append("")
            by_group: dict[str, list[dict[str, Any]]] = {}
            for entry in self.context:
                by_group.setdefault(entry.get("group") or "other", []).append(entry)
            for group in sorted(by_group):
                lines.append(f"**{group}**")
                for entry in by_group[group]:
                    lines.append(f"- {entry.get('key')}: {entry.get('value')}")
                lines.append("")

        # Tasks — described by title + role; the "how" lives in each task's
        # description (shown in task-brief), keeping the table scannable.
        lines.append("## Tasks")
        lines.append("")
        if self.tasks:
            lines.append("| # | Task | Role / owner | State | Blocked by |")
            lines.append("|---|------|--------------|-------|------------|")
            for task in self.ordered_tasks():
                marker = self.dependency_marker(task.get("id")) or "—"
                lines.append(
                    f"| {task.get('id')} | {task.get('title')} | "
                    f"{_render_assignee(task.get('assignedTo'))} | {task.get('state')} | {marker} |"
                )
        else:
            lines.append("_No tasks yet._")
        lines.append("")

        # Scenario dependencies — show BOTH satisfied and unmet edges (whose
        # dependent scenario is in scope) so a met dependency doesn't silently
        # disappear from the view while `check-deps` still reports it.
        status_edges = self.scenario_dependency_status()
        if status_edges:
            lines.append("## Scenario dependencies")
            lines.append("")
            lines.append("| Scenario | Depends on | Kind | Status |")
            lines.append("|----------|-----------|------|--------|")
            for edge in status_edges:
                status = "met" if edge.get("met") else "MISSING — add it first"
                lines.append(
                    f"| {edge['scenario']} | {edge['dependsOn']} | {edge.get('kind')} | {status} |"
                )
            lines.append("")

        # Outputs ledger.
        active = [a for a in self.outputs if a.get("state") == "Active"]
        if active:
            lines.append("## Produced (pinned outputs)")
            lines.append("")
            lines.append("| Key | Kind | Attributes | By task |")
            lines.append("|-----|------|------------|---------|")
            for art in active:
                attrs = ", ".join(f"{k}={v}" for k, v in art.get("attributes", {}).items())
                lines.append(
                    f"| {art.get('key')} | {art.get('kind')} | {attrs} | "
                    f"{art.get('producedByTaskId')} |"
                )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def output_value_or_context(self, key: str) -> Any:
        for entry in self.context:
            if entry.get("key") == key:
                return entry.get("value")
        return None


def _render_assignee(assigned: dict[str, Any] | None) -> str:
    if not assigned:
        return "unassigned"
    role = assignee_role_id(assigned)
    if assigned.get("type") == "Role":
        return f"{role} (pool)"
    oid = assignee_user_oid(assigned) or "?"
    return f"{oid} (as {role})" if role else oid
