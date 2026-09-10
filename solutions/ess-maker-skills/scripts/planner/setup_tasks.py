# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: deterministic setup-task decomposition.

The ``/planner`` skill's Phase 3 (``src/skills/planner/model.md``) has to turn a
system's setup into **atomic, role-boundary Tasks**. Doing that from memory is
where the plan drifts: the LLM under-decomposes a rich multi-role setup into a
couple of coarse tasks and *invents* roles (e.g. tagging Workday SSO as "Global
Administrator" or the firewall step as a bare "Network Administrator"), losing
the fidelity the setup skills were carefully authored with.

This module removes the guesswork. It reads the canonical, information-complete
setup checklist that every setup skill already renders and updates
(``src/skills/setup/<system>/tasks.md`` — the same file
``tests/setup/test_checklist_template.py`` pins), groups its steps by the
**role boundary** the checklist itself declares, and emits one grounded Task per
(group, role). Two things make the output correct where the freehand path was
wrong:

* **Roles are grounded, then mapped to an *attestable* role.** Each checklist
  item carries a verbatim ``role:`` (``App/Cloud App Admin``, ``InfoSec/IT`` …).
  Those are *display* labels, not the closed set of roles the plan backend will
  accept on a task (``src/mcp/agentconfig_planner/roles_surface.py`` →
  ``ATTESTABLE_ROLES``; a non-attestable role can never be attested, so the work
  stays invisible — see ``src/skills/planner/assign.md`` → *Nudge*). We ground
  the label, then map it to the correct attestable role id. Crucially, Workday
  SSO maps to ``EntraCloudApplicationAdministrator`` (App/Cloud App Admin) — NOT
  ``EntraGlobalAdministrator`` — and the firewall step to
  ``EntraNetworkAdministrator`` as the closest attestable proxy for InfoSec/IT.

* **Every step is accounted for.** All 25 Workday steps across 6 groups are
  covered, so no group silently disappears.

Pure logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are exempt
from the FlightCheck cassette rule). The ``setup-tasks`` CLI subcommand
(``scripts/planner/cli.py``) is the thin wrapper the skill actually invokes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from planner.roles import slugify_role_id

# scripts/planner/setup_tasks.py -> parents[2] is the solution root
# (solutions/ess-maker-skills), which holds src/skills/setup/<system>/tasks.md.
_SOLUTION_ROOT = Path(__file__).resolve().parents[2]

# A checkbox item line immediately followed by its hidden metadata comment —
# the same shape ``tests/setup/test_checklist_template.py`` parses. The item's
# user-facing text is captured so we can title minority-role tasks from it.
_ITEM_RE = re.compile(
    r"^-\s*\[(?P<box>[ xX])\]\s+(?P<text>.*?)\n\s*<!--(?P<meta>.*?)-->\s*$",
    re.MULTILINE,
)
# "### 3. Workday single sign-on (Entra)" -> number + heading text.
_HEADING_RE = re.compile(r"^###\s+(?P<num>\d+)\.\s+(?P<title>.+?)\s*$", re.MULTILINE)
# The bold lead of an item line is its short title: "**Title** — summary".
_TITLE_RE = re.compile(r"\*\*(?P<title>.+?)\*\*")
_STEP_RE = re.compile(r"S(?P<group>\d+)\.(?P<minor>\d+)")

# The shared foundation groups — a Power Platform environment and the ESS base
# agent — are produced by the backbone "Run setup" task (model.md). ``--skip-
# foundation`` drops them so the emitted set doesn't duplicate that task.
FOUNDATION_GROUPS = frozenset({1, 2})


# --- role grounding --------------------------------------------------------

# Ordered (substring, canonical display) rules that collapse the checklist's
# messy ``role:`` labels onto a single grounded role. Substring match against the
# lower-cased raw label; first hit wins — so the consent step's "Consent-capable
# role (App/Cloud App Admin, …)" resolves to App/Cloud App Admin before the bare
# fallback strips its parenthetical. Grounded in the labels in
# ``src/skills/setup/workday/tasks.md`` and the role matrix in
# ``src/reference/ess-docs/setup/role-gating.md``.
_ROLE_ALIASES: tuple[tuple[str, str], ...] = (
    ("consent-capable", "App/Cloud App Admin"),
    ("app/cloud app admin", "App/Cloud App Admin"),
    ("environment maker", "Environment Maker"),
    ("power platform administrator", "Power Platform Administrator"),
    ("workday administrator", "Workday Administrator"),
    ("infosec", "InfoSec/IT"),
)

# Grounded role id (``slugify`` of the canonical display) -> attestable compact
# id. Mirrors the closed registry in
# ``src/mcp/agentconfig_planner/roles_surface.py`` (``ATTESTABLE_ROLES``); a task
# whose ``--role`` isn't one of those can never be attested/assigned to a real
# person, so grounding alone isn't enough — the grounded role must be mapped to
# the attestable role that owns that work:
#   * App/Cloud App Admin -> Cloud Application Administrator (the least-privilege
#     Entra role for enterprise-app/SSO config) — NOT Global Administrator.
#   * InfoSec/IT -> Network Administrator (no InfoSec attestable role exists; the
#     network-allowlist change is closest to the Entra Network Administrator).
_ATTESTABLE_BY_GROUNDED: dict[str, str] = {
    "power-platform-administrator": "EntraPowerPlatformAdministrator",
    "environment-maker": "PowerPlatformEnvironmentMaker",
    "app-cloud-app-admin": "EntraCloudApplicationAdministrator",
    "workday-administrator": "WorkdayAdmin",
    "infosec-it": "EntraNetworkAdministrator",
}

# Attestable compact id -> wire display name, mirrored from
# ``roles_surface.py::ATTESTABLE_ROLE_WIRE_NAMES`` for the ids we map to (the
# lockstep test asserts these agree with the registry). Kept local so this
# scripts-tree module needs no cross-tree import of the MCP package.
_ATTESTABLE_DISPLAY: dict[str, str] = {
    "EntraPowerPlatformAdministrator": "Power Platform Administrator",
    "PowerPlatformEnvironmentMaker": "Environment Maker",
    "EntraCloudApplicationAdministrator": "Cloud Application Administrator",
    "WorkdayAdmin": "Workday administrator",
    "EntraNetworkAdministrator": "Network Administrator",
}


def canonical_role(raw_label: str) -> str:
    """Collapse a checklist ``role:`` label onto its canonical display name.

    Handles the real Workday labels — ``App/Cloud App Admin or App Owner``,
    ``Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA)``,
    ``Environment Maker (+ Workday SME)`` — via the alias table, falling back to
    stripping any ``(…)`` parenthetical and ``or …`` alternate so an unknown
    system still yields a stable grounded role.
    """
    low = (raw_label or "").lower()
    for needle, display in _ROLE_ALIASES:
        if needle in low:
            return display
    cleaned = re.sub(r"\(.*?\)", "", raw_label or "")
    cleaned = re.split(r"\bor\b", cleaned, maxsplit=1)[0]
    cleaned = cleaned.strip(" ,;/-\u2014")
    return cleaned or (raw_label or "").strip()


@dataclass(frozen=True)
class GroundedRole:
    """A checklist role, grounded and mapped to its attestable counterpart."""

    grounded_id: str
    grounded_display: str
    attestable_role: str  # compact id (or the grounded id when unmapped)
    attestable_display: str
    mapped: bool  # True when a real attestable role backs this task


def ground_role(raw_label: str) -> GroundedRole:
    """Ground a raw checklist ``role:`` label and map it to an attestable role."""
    display = canonical_role(raw_label)
    grounded_id = slugify_role_id(display)
    attestable = _ATTESTABLE_BY_GROUNDED.get(grounded_id)
    if attestable is not None:
        return GroundedRole(
            grounded_id=grounded_id,
            grounded_display=display,
            attestable_role=attestable,
            attestable_display=_ATTESTABLE_DISPLAY[attestable],
            mapped=True,
        )
    # No attestable role fits (a future system's role) — fall back to the
    # grounded id so the task is still emitted; the description flags it so a
    # person is assigned directly rather than pooled to a non-attestable role.
    return GroundedRole(
        grounded_id=grounded_id,
        grounded_display=display,
        attestable_role=grounded_id,
        attestable_display=display,
        mapped=False,
    )


# --- checklist parsing -----------------------------------------------------


@dataclass(frozen=True)
class ChecklistItem:
    step_id: str
    group_index: int
    group_title: str
    title: str
    summary: str
    role_label: str
    gate: str

    @property
    def step_order(self) -> tuple[int, int]:
        m = _STEP_RE.match(self.step_id)
        return (int(m.group("group")), int(m.group("minor"))) if m else (0, 0)


def _metadata(raw: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for field_text in raw.split("|"):
        key, sep, val = field_text.partition(":")
        if sep:
            meta[key.strip()] = val.strip()
    return meta


def parse_setup_checklist(md_text: str) -> list[ChecklistItem]:
    """Parse a setup ``tasks.md`` into its checklist items (metadata + heading).

    Each returned item carries its stable Step ID, the numbered group it sits
    under, its user-facing title/summary, the verbatim ``role:`` label, and the
    completion ``gate`` — everything the decomposition needs.
    """
    headings = [
        (m.start(), int(m.group("num")), m.group("title").strip())
        for m in _HEADING_RE.finditer(md_text)
    ]

    def _group_for(pos: int) -> tuple[int, str]:
        current = (0, "")
        for start, num, title in headings:
            if start < pos:
                current = (num, title)
            else:
                break
        return current

    items: list[ChecklistItem] = []
    for match in _ITEM_RE.finditer(md_text):
        meta = _metadata(match.group("meta"))
        step_id = meta.get("id", "")
        if not step_id:
            continue
        text = match.group("text").strip()
        title_m = _TITLE_RE.search(text)
        title = title_m.group("title").strip() if title_m else text
        summary = ""
        if title_m:
            rest = text[title_m.end():]
            summary = rest.lstrip(" \u2014-").strip()
        group_index, group_title = _group_for(match.start())
        items.append(
            ChecklistItem(
                step_id=step_id,
                group_index=group_index,
                group_title=group_title,
                title=title,
                summary=summary,
                role_label=meta.get("role", ""),
                gate=meta.get("gate", ""),
            )
        )
    return items


# --- per-system annotation ledger -----------------------------------------


@dataclass(frozen=True)
class _Slot:
    """Human-authored annotation for one (group, grounded-role) partition: the
    task id/title, the 'what & how' description lead, its produces/consumes
    ledger keys (used for ordering, see model.md), and the kit command to run."""

    task_id: str
    title: str
    how: str
    produces: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    command: str | None = None


# Workday: one slot per (group_index, grounded role id). produces/consumes keys
# and the backbone they thread through are grounded in model.md's "Typical
# greenfield backbone". Group 5 splits across two roles (Environment Maker for
# the pack + connect, InfoSec/IT for the firewall allowlist), so it carries two
# slots.
_WORKDAY_SLOTS: dict[tuple[int, str], _Slot] = {
    (1, "power-platform-administrator"): _Slot(
        task_id="workday-pp-environment",
        title="Set up the Power Platform environment",
        how="Create the Power Platform environment with a Dataverse database so the ESS agent and its data have a home, and confirm Copilot Studio capacity",
        produces=("primaryEnvironment",),
    ),
    (2, "environment-maker"): _Slot(
        task_id="workday-ess-base-agent",
        title="Install the Employee Self-Service base agent",
        how="Add the Microsoft Employee Self-Service base agent to the environment from AppSource",
        produces=("essAgent",),
        consumes=("primaryEnvironment",),
    ),
    (3, "app-cloud-app-admin"): _Slot(
        task_id="workday-sso-entra",
        title="Set up Workday single sign-on (Entra)",
        how="Register and configure the Workday enterprise SSO app in Entra — SAML app, exposed API permission, admin consent, user assignment, NameID mapping, SAML signing options, and single-tenant federation",
        produces=("workdayEntraApp",),
        consumes=("primaryEnvironment",),
    ),
    (4, "workday-administrator"): _Slot(
        task_id="workday-tenant-config",
        title="Configure the Workday tenant",
        how="In Workday, register the API client, capture the connection details (client id, endpoints, tenant), activate the OAuth/SAML authentication policy, and match the signing certificate to Entra",
        produces=("workdayTenantConfig",),
        consumes=("primaryEnvironment",),
    ),
    (5, "environment-maker"): _Slot(
        task_id="workday-pack-connect",
        title="Install the Workday extension pack and connect",
        how="Run /connect to install the Workday extension pack, bind the Workday and Dataverse connections to your account, set the Workday REST address, turn on the cloud flows, and wire up the employee-context lookup",
        produces=("workdayConnection",),
        consumes=("workdayEntraApp", "workdayTenantConfig"),
        command="/connect",
    ),
    (5, "infosec-it"): _Slot(
        task_id="workday-firewall-allowlist",
        title="Allow Workday through your firewall",
        how="Add the Workday REST and SOAP endpoints to your network allowlist so agent traffic can reach Workday",
        produces=("workdayNetworkAllowlist",),
    ),
    (6, "environment-maker"): _Slot(
        task_id="workday-first-topic",
        title="Author your first custom Workday topic",
        how="Run /create to author your first custom Workday topic — define its trigger phrases, wire it to Workday with your tenant's reference IDs, and review it for issues",
        produces=("topic:workday",),
        consumes=("workdayConnection",),
        command="/create",
    ),
}

_SYSTEM_SLOTS: dict[str, dict[tuple[int, str], _Slot]] = {
    "workday": _WORKDAY_SLOTS,
}


# Workstream/theme label a system's tasks group under in the plan view
# (plan_model._render_tasks). Falls back to a title-cased form of the system id.
_SYSTEM_STREAM: dict[str, str] = {
    "workday": "Workday",
}


# --- decomposition ---------------------------------------------------------


@dataclass
class SetupTask:
    task_id: str
    title: str
    description: str
    role: str  # attestable compact id the task is pooled to
    role_display: str
    grounded_role_id: str
    grounded_role_display: str
    attestable: bool
    group_index: int
    group_title: str
    step_ids: list[str]
    gates: list[str]
    raw_role_labels: list[str]
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    command: str | None = None
    stream: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.task_id,
            "title": self.title,
            "description": self.description,
            "role": self.role,
            "roleDisplay": self.role_display,
            "groundedRole": self.grounded_role_id,
            "groundedRoleDisplay": self.grounded_role_display,
            "attestable": self.attestable,
            "groupIndex": self.group_index,
            "groupTitle": self.group_title,
            "stepIds": list(self.step_ids),
            "gates": list(self.gates),
            "rawRoleLabels": list(self.raw_role_labels),
            "produces": list(self.produces),
            "consumes": list(self.consumes),
            "command": self.command,
            "stream": self.stream,
        }

    def add_task_command(self) -> str:
        """Render the copy-paste ``add-task`` line the skill runs (model.md)."""
        parts = [
            "python scripts/planner/cli.py add-task",
            f'--id {self.task_id}',
        ]
        if self.stream:
            parts.append(f'--stream "{self.stream}"')
        parts += [
            f'--title "{self.title}"',
            f'--description "{self.description}"',
            f"--role {self.role}",
        ]
        if self.produces:
            parts.append(f'--produces "{",".join(self.produces)}"')
        if self.consumes:
            parts.append(f'--consumes "{",".join(self.consumes)}"')
        return " ".join(parts)


def _step_range(step_ids: list[str]) -> str:
    if not step_ids:
        return ""
    if len(step_ids) == 1:
        return step_ids[0]
    return f"{step_ids[0]}-{step_ids[-1]}"


def _role_notes(raw_labels: list[str]) -> str:
    """Surface grounding nuance carried in the raw labels (consent escalation,
    an SME collaborator) so it survives into the description."""
    notes: list[str] = []
    joined = " ".join(raw_labels).lower()
    if "consent-capable" in joined:
        notes.append(
            "admin consent may also need Privileged Role Administrator or Global Administrator"
        )
    for label in raw_labels:
        m = re.search(r"\(\+\s*(?P<who>[^)]+?)\)", label)
        if m:
            notes.append(f"with {m.group('who').strip()}")
    return f" ({'; '.join(notes)})" if notes else ""


def _build_task(
    system: str,
    group_index: int,
    group_title: str,
    grounded: GroundedRole,
    items: list[ChecklistItem],
    slot: _Slot | None,
    is_primary: bool,
) -> SetupTask:
    step_ids = [it.step_id for it in items]
    gates = sorted(
        {
            m.group(0)
            for it in items
            if (m := re.match(r"[a-z]+", it.gate.strip().lower()))
        }
    )
    raw_labels: list[str] = []
    for it in items:
        if it.role_label and it.role_label not in raw_labels:
            raw_labels.append(it.role_label)

    if slot is not None:
        task_id = slot.task_id
        title = slot.title
        how = slot.how
        produces = list(slot.produces)
        consumes = list(slot.consumes)
        command = slot.command
    else:
        # Unannotated system/partition: title from the group heading for the
        # primary role, else from this partition's first item; no ledger keys.
        task_id = f"{system}-g{group_index}-{grounded.grounded_id}"
        title = group_title if is_primary else items[0].title
        how = items[0].summary or items[0].title
        produces = []
        consumes = []
        command = None

    notes = _role_notes(raw_labels)
    grounding = (
        f"Grounded in setup/{system}/tasks.md group {group_index} "
        f"({group_title}) steps {_step_range(step_ids)}."
    )
    role_line = (
        f"Checklist role: {grounded.grounded_display}{notes}; "
        f"attestable role: {grounded.attestable_display}."
    )
    if not grounded.mapped:
        role_line += " No attestable role fits — assign a person directly."
    description = f"{how}. {grounding} {role_line}"

    stream_display = _SYSTEM_STREAM.get(system, system.replace("-", " ").title())

    return SetupTask(
        task_id=task_id,
        title=title,
        description=description,
        role=grounded.attestable_role,
        role_display=grounded.attestable_display,
        grounded_role_id=grounded.grounded_id,
        grounded_role_display=grounded.grounded_display,
        attestable=grounded.mapped,
        group_index=group_index,
        group_title=group_title,
        step_ids=step_ids,
        gates=gates,
        raw_role_labels=raw_labels,
        produces=produces,
        consumes=consumes,
        command=command,
        stream=stream_display,
    )


def decompose(system: str, items: list[ChecklistItem]) -> list[SetupTask]:
    """Group checklist items by (group, grounded role) — the role boundary — and
    emit one grounded, attestable-mapped Task per partition, in checklist order."""
    slots = _SYSTEM_SLOTS.get(system, {})
    ordered = sorted(items, key=lambda it: it.step_order)

    # Preserve first-seen order of each (group, grounded-role) partition, and
    # remember which grounded role opened each group (its "primary" role) so a
    # minority role (e.g. the firewall step) titles itself from its own item.
    partitions: dict[tuple[int, str], list[ChecklistItem]] = {}
    group_primary: dict[int, str] = {}
    order: list[tuple[int, str]] = []
    for it in ordered:
        grounded_id = ground_role(it.role_label).grounded_id
        key = (it.group_index, grounded_id)
        if key not in partitions:
            partitions[key] = []
            order.append(key)
            group_primary.setdefault(it.group_index, grounded_id)
        partitions[key].append(it)

    tasks: list[SetupTask] = []
    for group_index, grounded_id in order:
        part_items = partitions[(group_index, grounded_id)]
        grounded = ground_role(part_items[0].role_label)
        slot = slots.get((group_index, grounded_id))
        is_primary = group_primary.get(group_index) == grounded_id
        tasks.append(
            _build_task(
                system,
                group_index,
                part_items[0].group_title,
                grounded,
                part_items,
                slot,
                is_primary,
            )
        )
    return tasks


def checklist_path(system: str) -> Path:
    return _SOLUTION_ROOT / "src" / "skills" / "setup" / system / "tasks.md"


def system_setup_tasks(system: str, skip_foundation: bool = False) -> list[SetupTask]:
    """Read ``setup/<system>/tasks.md`` and decompose it into grounded Tasks.

    Raises ``FileNotFoundError`` when the system has no setup checklist (today
    only ``workday`` ships one under ``src/skills/setup/``).
    """
    path = checklist_path(system)
    if not path.is_file():
        raise FileNotFoundError(
            f"no setup checklist for system {system!r} (expected {path})"
        )
    items = parse_setup_checklist(path.read_text(encoding="utf-8"))
    tasks = decompose(system, items)
    if skip_foundation:
        tasks = [t for t in tasks if t.group_index not in FOUNDATION_GROUPS]
    return tasks
