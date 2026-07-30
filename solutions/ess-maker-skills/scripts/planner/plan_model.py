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
  * A Task's ``action`` says HOW it is performed — usually a kit skill,
    sometimes a manual / portal / external step.
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
SUMMARY_PATH = os.path.join(PLAN_DIR, "summary.md")
RESEARCH_PATH = os.path.join(PLAN_DIR, "research-context.json")

# Controlled vocabularies. Kept as plain tuples (not Enums) because the values
# are serialized verbatim to JSON and read back by an agent — the string IS the
# contract.
TASK_STATES = ("NotStarted", "InProgress", "Completed", "Blocked")
ARTIFACT_STATES = ("Active", "Superseded")
PRINCIPAL_TYPES = ("User", "Role")
CONTEXT_SOURCES = ("User", "Agent", "Discovered")
ARTIFACT_KINDS = ("Environment", "Connection", "EntraApp", "KnowledgeSource", "Custom")
ACTION_KINDS = ("kitSkill", "manual", "portal", "external")


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
    MAX_NOTES = 50


def now_iso() -> str:
    """UTC timestamp in the ``2026-07-30T18:00:00Z`` shape used across the kit."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Value-object builders (return plain dicts — JSON is the wire format).
# --------------------------------------------------------------------------- #

def role_ref(role_id: str, directory_ref: str | None = None) -> dict[str, Any]:
    ref: dict[str, Any] = {"roleId": role_id}
    if directory_ref:
        ref["directoryRef"] = directory_ref
    return ref


def user_ref(oid: str, directory_ref: str | None = None) -> dict[str, Any]:
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


def action_kit_skill(skill: str) -> dict[str, Any]:
    return {"kind": "kitSkill", "skill": skill}


def action_portal(ref: str) -> dict[str, Any]:
    return {"kind": "portal", "ref": ref}


def action_manual(ref: str | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {"kind": "manual"}
    if ref:
        a["ref"] = ref
    return a


def action_external(ref: str | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {"kind": "external"}
    if ref:
        a["ref"] = ref
    return a


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
    action: dict[str, Any] | None = None,
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
        "action": action or action_manual(),
        "assignedTo": assigned_to or {},
        "state": state,
        "produces": list(produces or []),
        "consumes": list(consumes or []),
    }
    if checklist:
        task["checklist"] = list(checklist)
    return task


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
            "generatedAt": now_iso(),
            "planId": "",
            "projectId": "",
            "status": "Draft",
            "context": [],
            "tasks": [],
            "outputs": [],
            "notes": [],
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
        for key in ("context", "tasks", "outputs", "notes"):
            data.setdefault(key, [])
        for key in ("planId", "projectId"):
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
        """Write plan.json and regenerate summary.md alongside it."""
        self.save(plan_path)
        summary = os.path.join(os.path.dirname(os.fspath(plan_path)) or ".", "summary.md")
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
        is retained so the task still groups under it in Flow 2."""
        task = self._require_task(task_id)
        role = assignee_role_id(task.get("assignedTo"))
        task["assignedTo"] = principal_person(person_oid, role_id=role)
        return task

    def set_task_state(self, task_id: str, state: str) -> dict[str, Any]:
        if state not in TASK_STATES:
            raise ValueError(f"invalid task state: {state!r}")
        task = self._require_task(task_id)
        task["state"] = state
        return task

    def set_checklist(self, task_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace a task's read-back-only step checklist (display state)."""
        task = self._require_task(task_id)
        task["checklist"] = list(items)
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

    def outputs_of_task(self, task_id: str) -> list[dict[str, Any]]:
        """"This task's outputs" = the ledger filtered by producing id (no copy)."""
        return [a for a in self.outputs if a.get("producedByTaskId") == task_id]

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
        for task in self.tasks:
            assigned = task.get("assignedTo") or {}
            role = assignee_role_id(assigned) or "(no role)"
            owner = assignee_user_oid(assigned)
            if assigned.get("type") == "User" and owner == person_oid:
                grouped.setdefault(role, []).append({"task": task, "relation": "assigned"})
            elif assigned.get("type") == "Role" and assignee_role_id(assigned) in role_set:
                grouped.setdefault(role, []).append({"task": task, "relation": "pool"})
        return grouped

    # ---- validation ------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty == valid)."""
        errors: list[str] = []
        d = self.data

        if d.get("schemaVersion") != SCHEMA_VERSION:
            errors.append(f"schemaVersion should be {SCHEMA_VERSION}")

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
            errors.extend(self._validate_action(tid, task.get("action")))
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
    def _validate_action(tid: str, action: Any) -> list[str]:
        errors: list[str] = []
        if not action:
            return errors  # action optional on a draft task
        kind = action.get("kind")
        if kind not in ACTION_KINDS:
            errors.append(f"task {tid!r} invalid action kind: {kind!r}")
        if kind == "kitSkill" and not action.get("skill"):
            errors.append(f"task {tid!r} kitSkill action missing 'skill'")
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

    def render_summary(self) -> str:
        """A human-readable Markdown view of the Plan (never hand-edited)."""
        d = self.data
        lines: list[str] = []
        objective = self.output_value_or_context("objective") or "(objective not set)"
        lines.append(f"# Scenario plan — {objective}")
        lines.append("")
        planid = d.get("planId") or "(local, not synced)"
        lines.append(f"Generated: {d.get('generatedAt', '')}  |  Status: {d.get('status', '')}  |  Plan: {planid}")
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

        # Tasks.
        lines.append("## Tasks")
        lines.append("")
        if self.tasks:
            lines.append("| # | Task | Action | Assigned to | State |")
            lines.append("|---|------|--------|-------------|-------|")
            for task in self.tasks:
                lines.append(
                    f"| {task.get('id')} | {task.get('title')} | "
                    f"{_render_action(task.get('action'))} | "
                    f"{_render_assignee(task.get('assignedTo'))} | {task.get('state')} |"
                )
        else:
            lines.append("_No tasks yet._")
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


def _render_action(action: dict[str, Any] | None) -> str:
    if not action:
        return "—"
    kind = action.get("kind", "?")
    if kind == "kitSkill":
        return f"kit: {action.get('skill', '?')}"
    return kind


def _render_assignee(assigned: dict[str, Any] | None) -> str:
    if not assigned:
        return "unassigned"
    role = assignee_role_id(assigned)
    if assigned.get("type") == "Role":
        return f"{role} (pool)"
    oid = assignee_user_oid(assigned) or "?"
    return f"{oid} (as {role})" if role else oid
