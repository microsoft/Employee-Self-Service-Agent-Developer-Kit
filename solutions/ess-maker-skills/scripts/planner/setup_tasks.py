# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: deterministic setup-task decomposition.

The ``/planner`` skill's Phase 3 (``src/skills/planner/model.md``) has to turn a
system's rollout into **atomic, role-boundary Tasks**. Doing that from memory is
where the plan drifts: the LLM under-decomposes a rich multi-role rollout into a
couple of coarse tasks and *invents* roles (e.g. tagging Workday sign-in as
"Global Administrator"), losing the fidelity the connect skills were carefully
authored with.

This module removes the guesswork. It reads the system's planning reference
(``src/skills/planner/systems/<system>.md``), groups its steps by the **role
boundary** the reference declares, and emits one grounded Task per
(group, role). After the two ``/setup`` foundation groups, the Workday reference
follows the six ``/connect-workday`` phases in the order of
``PHASE_DEFINITIONS`` (``scripts/workday_connect_model.py``). The reference is a
planning map only; ``/connect-workday`` owns the lifecycle and its state. Two
things make the output correct where the freehand path was wrong:

* **Roles are grounded, then mapped to an *attestable* role.** Each step carries
  a verbatim ``role:`` (``Application Administrator or Cloud Application
  Administrator``, ``Workday Administrator`` …). Those are *display* labels, not
  the closed set of roles the plan backend will accept on a task
  (``src/mcp/agentconfig_planner/roles_surface.py`` → ``ATTESTABLE_ROLES``; a
  non-attestable role can never be attested, so the work stays invisible — see
  ``src/skills/planner/assign.md`` → *Nudge*). We ground the label, then map it
  to the correct attestable role id. Crucially, the Workday Entra work maps to
  ``EntraCloudApplicationAdministrator`` — the least-privileged role that can do
  it — and never to ``EntraGlobalAdministrator``.

* **Every step is accounted for.** All 14 Workday steps across 6 groups are
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
# (solutions/ess-maker-skills), which holds src/skills/planner/systems/<system>.md.
_SOLUTION_ROOT = Path(__file__).resolve().parents[2]

# A step line immediately followed by its hidden metadata comment. The step's
# user-facing text is captured so minority-role tasks can title themselves from
# it. A legacy ``- [ ]`` checkbox before the text is still accepted.
_ITEM_RE = re.compile(
    r"^-\s*(?:\[(?P<box>[ xX])\]\s+)?(?P<text>.*?)\n[ \t]*<!--(?P<meta>.*?)-->\s*$",
    re.MULTILINE,
)
# "### 4. Microsoft Entra" -> number + heading text.
_HEADING_RE = re.compile(r"^###\s+(?P<num>\d+)\.\s+(?P<title>.+?)\s*$", re.MULTILINE)
# The bold lead of an item line is its short title: "**Title** — summary".
_TITLE_RE = re.compile(r"\*\*(?P<title>.+?)\*\*")
_STEP_RE = re.compile(r"S(?P<group>\d+)\.(?P<minor>\d+)")

# The shared foundation groups — a Power Platform environment and the ESS HR
# agent — are produced by the backbone /setup task (model.md). ``--skip-
# foundation`` drops them so the emitted set doesn't duplicate that task.
FOUNDATION_GROUPS = frozenset({1, 2})


# --- role grounding --------------------------------------------------------

# Ordered (substring, canonical display) rules that collapse the reference's
# ``role:`` labels onto a single grounded role. Substring match against the
# lower-cased raw label; first hit wins — so "Application Administrator or Cloud
# Application Administrator (a separate consent-capable administrator …)"
# resolves to the Entra app administrator before the bare fallback strips its
# parenthetical. Grounded in the labels in ``src/skills/planner/systems/*.md``
# and the role table in ``src/reference/ess-docs/setup/role-gating.md``.
_ROLE_ALIASES: tuple[tuple[str, str], ...] = (
    ("cloud application administrator", "Entra app administrator"),
    ("application administrator", "Entra app administrator"),
    ("entra app administrator", "Entra app administrator"),
    ("app/cloud app admin", "Entra app administrator"),
    ("environment maker", "Environment Maker"),
    ("power platform administrator", "Power Platform Administrator"),
    ("workday administrator", "Workday Administrator"),
)

# Grounded role id (``slugify`` of the canonical display) -> attestable compact
# id. Mirrors the closed registry in
# ``src/mcp/agentconfig_planner/roles_surface.py`` (``ATTESTABLE_ROLES``); a task
# whose ``--role`` isn't one of those can never be attested/assigned to a real
# person, so grounding alone isn't enough — the grounded role must be mapped to
# the attestable role that owns that work. The Entra app administrator maps to
# Cloud Application Administrator: either it or Application Administrator can
# configure the Workday enterprise application, and it is the less privileged of
# the two. It is never Global Administrator.
_ATTESTABLE_BY_GROUNDED: dict[str, str] = {
    "power-platform-administrator": "EntraPowerPlatformAdministrator",
    "environment-maker": "PowerPlatformEnvironmentMaker",
    "entra-app-administrator": "EntraCloudApplicationAdministrator",
    "workday-administrator": "WorkdayAdmin",
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
}


def canonical_role(raw_label: str) -> str:
    """Collapse a reference ``role:`` label onto its canonical display name.

    Handles the real Workday labels — ``Application Administrator or Cloud
    Application Administrator (…)``, ``Environment Maker (+ package installation
    access)`` — via the alias table, falling back to stripping any ``(…)``
    parenthetical and ``or …`` alternate so an unknown system still yields a
    stable grounded role.
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
    """A reference role, grounded and mapped to its attestable counterpart."""

    grounded_id: str
    grounded_display: str
    attestable_role: str  # compact id (or the grounded id when unmapped)
    attestable_display: str
    mapped: bool  # True when a real attestable role backs this task


def ground_role(raw_label: str) -> GroundedRole:
    """Ground a raw reference ``role:`` label and map it to an attestable role."""
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


# --- reference parsing -----------------------------------------------------


@dataclass(frozen=True)
class ChecklistItem:
    """One step of a planning reference."""

    step_id: str
    group_index: int
    group_title: str
    title: str
    summary: str
    role_label: str
    gate: str
    phase: str = ""  # owning lifecycle phase; empty for foundation work

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
    """Parse a planning reference into its steps (metadata + heading).

    Each returned item carries its stable Step ID, the numbered group it sits
    under, its user-facing title/summary, the verbatim ``role:`` label, the
    confirmation ``gate``, and the lifecycle ``phase`` (empty for foundation
    work) — everything the decomposition needs.
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
                phase=meta.get("phase", ""),
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


# Workday: one slot per (group_index, grounded role id). The produces/consumes
# keys thread the work in /connect-workday order: the maker's preflight unlocks
# the Entra handoff, the Entra signing certificate unlocks the Workday
# administrator, and both administrator outputs unlock the maker's connection.
# Group 6 spans the Connections, Runtime configuration, and Maker validation
# phases, which the same maker runs in one /connect-workday session.
_WORKDAY_SLOTS: dict[tuple[int, str], _Slot] = {
    (1, "power-platform-administrator"): _Slot(
        task_id="workday-pp-environment",
        title="Set up the Power Platform environment",
        how="Create or choose the Power Platform environment for the ESS HR agent in the Power Platform admin center, confirm Copilot Studio capacity, and give the maker the Environment Maker role in it",
        produces=("primaryEnvironment",),
    ),
    (2, "environment-maker"): _Slot(
        task_id="workday-ess-hr-agent",
        title="Set up the ESS HR agent",
        how="Run /setup with the maker's own login to create a fresh ESS HR agent or select an existing one, and bring its local copy into the workspace",
        produces=("essAgent",),
        consumes=("primaryEnvironment",),
        command="/setup",
    ),
    (3, "environment-maker"): _Slot(
        task_id="workday-preflight",
        title="Confirm Workday readiness for the ESS HR agent",
        how="Start /connect-workday to confirm the agent, environment, and maker account, verify Dataverse access, and choose the supported Workday package before anything changes",
        produces=("workdayPreflight",),
        consumes=("primaryEnvironment", "essAgent"),
        command="/connect-workday",
    ),
    (4, "entra-app-administrator"): _Slot(
        task_id="workday-entra-app",
        title="Set up Workday sign-in in Microsoft Entra",
        how="Follow the /connect-workday handoff to configure the Workday enterprise application — SAML, the connector scope, delegated permissions and admin consent, employee assignment, and NameID — then hand the signing certificate to the Workday administrator. Either an Application Administrator or a Cloud Application Administrator can do this. It is a reusable tenant foundation, so reuse an existing configuration rather than replace it",
        produces=("workdayEntraApp",),
        consumes=("workdayPreflight",),
    ),
    (5, "workday-administrator"): _Slot(
        task_id="workday-tenant-config",
        title="Configure the Workday tenant",
        how="Follow the /connect-workday handoff to trust the Microsoft Entra sign-in with the transferred certificate, set up the employee API client and domain security, activate the employee authentication policy, and return the client ID, token endpoint, and REST and SOAP base URLs",
        produces=("workdayTenantConfig",),
        consumes=("workdayEntraApp",),
    ),
    (6, "environment-maker"): _Slot(
        task_id="workday-connect",
        title="Connect the ESS HR agent to Workday",
        how="Continue /connect-workday to install the Workday package, create the Workday and Dataverse connections, apply the runtime configuration and Workday topics, and smoke-test a read-only scenario in the Test pane without publishing. A promoted Test or Prod environment reuses the Entra and Workday configuration and repeats only this task",
        produces=("workdayConnection",),
        consumes=("primaryEnvironment", "essAgent", "workdayEntraApp", "workdayTenantConfig"),
        command="/connect-workday",
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

# The skill that owns a system's lifecycle phases, named in task descriptions.
_SYSTEM_LIFECYCLE: dict[str, str] = {
    "workday": "/connect-workday",
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
    phases: list[str] = field(default_factory=list)

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
            "phases": list(self.phases),
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
    """Surface grounding nuance carried in the raw labels (a conditional consent
    administrator, extra access the role needs) so it survives into the
    description."""
    notes: list[str] = []
    joined = " ".join(raw_labels).lower()
    if "consent" in joined:
        notes.append(
            "involve a separate consent-capable administrator only if tenant policy prevents admin consent"
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
    phases: list[str] = []
    for it in items:
        if it.phase and it.phase not in phases:
            phases.append(it.phase)
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
        f"Grounded in planner/systems/{system}.md group {group_index} "
        f"({group_title}) steps {_step_range(step_ids)}"
    )
    if phases:
        owner = _SYSTEM_LIFECYCLE.get(system)
        noun = "phase" if len(phases) == 1 else "phases"
        lead = f"{owner} {noun}" if owner else noun.capitalize()
        grounding += f"; {lead}: {', '.join(phases)}"
    grounding += "."
    role_line = (
        f"Reference role: {grounded.grounded_display}{notes}; "
        f"attestable role: {grounded.attestable_display}."
    )
    if not grounded.mapped:
        role_line += " No attestable role fits — assign a person directly."
    # Reference summaries are full sentences; drop their period before joining.
    description = f"{how.rstrip(' .')}. {grounding} {role_line}"

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
        phases=phases,
    )


def decompose(system: str, items: list[ChecklistItem]) -> list[SetupTask]:
    """Group reference steps by (group, grounded role) — the role boundary — and
    emit one grounded, attestable-mapped Task per partition, in reference order."""
    slots = _SYSTEM_SLOTS.get(system, {})
    ordered = sorted(items, key=lambda it: it.step_order)

    # Preserve first-seen order of each (group, grounded-role) partition, and
    # remember which grounded role opened each group (its "primary" role) so a
    # minority role in a mixed group titles itself from its own first step.
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
    """Path of a system's planning reference."""
    return _SOLUTION_ROOT / "src" / "skills" / "planner" / "systems" / f"{system}.md"


def system_setup_tasks(system: str, skip_foundation: bool = False) -> list[SetupTask]:
    """Read ``planner/systems/<system>.md`` and decompose it into grounded Tasks.

    Raises ``FileNotFoundError`` when the system has no planning reference
    (today only ``workday`` ships one under ``src/skills/planner/systems/``).
    """
    path = checklist_path(system)
    if not path.is_file():
        raise FileNotFoundError(
            f"no planning reference for system {system!r} (expected {path})"
        )
    items = parse_setup_checklist(path.read_text(encoding="utf-8"))
    tasks = decompose(system, items)
    if skip_foundation:
        tasks = [t for t in tasks if t.group_index not in FOUNDATION_GROUPS]
    return tasks
