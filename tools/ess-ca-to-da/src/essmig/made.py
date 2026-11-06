"""The ``customizationsMade.md`` diff — what the migration wrote onto the DA.

``customizations.md`` answers *"what did the customer change from the original ESS
agent?"* by diffing the discovered Custom Engine Agent components against the CA
baseline. This module answers the mirror-image question an auditor asks after the
package is built: *"what did this tool change on the Declarative Agent, relative to
what ESS shipped?"*

It diffs the Declarative Agent **as ESS shipped it** (the vendored ``agent.yml``
template) against the **package this tool produced** (that same document after the
merge), component by component, in the same layout as ``customizations.md``:

* **Changed** — a component present in both, whose serialized body differs. A unified
  diff (shipped -> produced) shows the exact lines the migration wrote.
* **Added** — a component the produced package has that the template did not (the
  customer's own net-new topics, a carried knowledge source). Shown in full.
* **Removed** — a component the template shipped that the produced package dropped.
  Migration does not normally remove components, so this is listed for completeness.

The agent's own display name and description (which live in the config and in
``entity.description`` rather than in a component) are surfaced as a leading *Agent
settings* section when the migration changed either.

Because :func:`essmig.merge.merge` edits the reference document *in place*, callers
take a :func:`snapshot` **before** merging (the shipped side) and another **after**
merging the same reference (the produced side), then pass both here.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from essmig.projection import dump
from essmig.reference import ReferenceSet

_BODY_LIMIT = 400
"""Max lines of an Added component's body (or of a single diff) before truncation."""


class Change(StrEnum):
    CHANGED = "changed"
    ADDED = "added"
    REMOVED = "removed"


_HEADLINE = {
    Change.CHANGED: "Changed (differs from the shipped template)",
    Change.ADDED: "Added (new in the produced package)",
    Change.REMOVED: "Removed (dropped from the produced package)",
}

# Most noteworthy first: a removal is the surprising one to audit, then edits, then
# purely additive content.
_ORDER = (Change.REMOVED, Change.CHANGED, Change.ADDED)


@dataclass(frozen=True)
class ComponentText:
    """One Declarative Agent component's identity and serialized body."""

    suffix: str
    schemaname: str
    kind: str
    text: str


@dataclass(frozen=True)
class Snapshot:
    """The auditable surface of one agent.yml + config, captured at a point in time."""

    components: dict[str, ComponentText] = field(default_factory=dict)
    display_name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ComponentChange:
    """One component classified by how the migration changed it."""

    suffix: str
    schemaname: str
    kind: str
    change: Change
    diff: str
    """Unified diff (CHANGED), the body (ADDED), or the dropped body (REMOVED)."""


def snapshot(reference: ReferenceSet) -> Snapshot:
    """Capture the auditable state of a reference's Declarative Agent.

    Call once **before** :func:`essmig.merge.merge` for the shipped side and once
    **after** merging the same reference for the produced side. Only serialized text
    and two scalars are captured, so the two snapshots stay independent even though
    merge mutates the reference in place.
    """
    components: dict[str, ComponentText] = {}
    for suffix, component in reference.da_components.items():
        # da_components only yields dicts, so the reads below are always defined.
        components[suffix] = ComponentText(
            suffix=suffix,
            schemaname=str(component.get("schemaName") or ""),
            kind=str(component.get("kind") or ""),
            text=dump(component),
        )

    entity = reference.agent.get("entity") if isinstance(reference.agent, dict) else None
    description = entity.get("description") if isinstance(entity, dict) else None
    values = reference.config.get("values") if isinstance(reference.config, dict) else None
    display_name = values.get("botName") if isinstance(values, dict) else None

    return Snapshot(
        components=components,
        display_name=display_name if isinstance(display_name, str) else None,
        description=description if isinstance(description, str) else None,
    )


def changes(before: Snapshot, after: Snapshot) -> list[ComponentChange]:
    """Classify every component by how the migration changed it, most-notable first."""
    entries: list[ComponentChange] = []
    for suffix in sorted(set(before.components) | set(after.components)):
        old = before.components.get(suffix)
        new = after.components.get(suffix)
        if old is not None and new is not None:
            if old.text.splitlines() == new.text.splitlines():
                continue
            entries.append(
                ComponentChange(
                    suffix=suffix,
                    schemaname=new.schemaname or old.schemaname,
                    kind=new.kind or old.kind,
                    change=Change.CHANGED,
                    diff=_unified(old.text, new.text),
                )
            )
        elif new is not None:
            entries.append(
                ComponentChange(
                    suffix=suffix,
                    schemaname=new.schemaname,
                    kind=new.kind,
                    change=Change.ADDED,
                    diff=_truncate(new.text.splitlines()),
                )
            )
        elif old is not None:
            entries.append(
                ComponentChange(
                    suffix=suffix,
                    schemaname=old.schemaname,
                    kind=old.kind,
                    change=Change.REMOVED,
                    diff=_truncate(old.text.splitlines()),
                )
            )
    return sorted(entries, key=lambda entry: (_ORDER.index(entry.change), entry.suffix))


def render_markdown(
    vertical: str,
    before: Snapshot,
    after: Snapshot,
    *,
    source_solution: str,
    da_schemaname: str,
    template_version: str | None = None,
    package_path: Path | None = None,
) -> str:
    """The ``customizationsMade.md`` body: a per-component diff of shipped vs produced."""
    entries = changes(before, after)
    counts = {change: sum(entry.change is change for entry in entries) for change in _ORDER}
    agent_lines = _agent_section(before, after)

    lines: list[str] = [
        f"# ESS migration changes — {vertical.upper()}",
        "",
        f"- Source (Custom Engine Agent): `{source_solution}`",
        f"- Target template: `{da_schemaname}`"
        + (f" (version {template_version})" if template_version else ""),
        f"- Components changed: **{len(entries)}**",
    ]
    if package_path is not None:
        lines.append(f"- Package: `{package_path}`")
    lines += [
        "",
        "This diffs the Declarative Agent **as ESS shipped it** against the **package "
        "this tool produced**, component by component, so you can audit exactly what the "
        "migration wrote. **Changed** shows a unified diff of just the lines that moved; "
        "**Added** are components the produced package has and the template did not; "
        "**Removed** are template components the package dropped. Components the migration "
        "left byte-for-byte identical are omitted.",
        "",
        "## Summary",
        "",
        "| Change | Count |",
        "| --- | ---: |",
    ]
    for change in _ORDER:
        lines.append(f"| {_HEADLINE[change]} | {counts[change]} |")

    lines += agent_lines

    for change in _ORDER:
        section = [entry for entry in entries if entry.change is change]
        if not section:
            continue
        lines += ["", f"## {_HEADLINE[change]}", ""]
        for entry in section:
            lines += _component_section(entry)

    if not entries and not agent_lines:
        lines += ["", "_The migration made no changes to the shipped template._"]

    return "\n".join(lines) + "\n"


def write(
    destination: Path,
    vertical: str,
    before: Snapshot,
    after: Snapshot,
    *,
    source_solution: str,
    da_schemaname: str,
    template_version: str | None = None,
    package_path: Path | None = None,
) -> Path:
    """Write ``customizationsMade.md`` into ``destination`` and return its path."""
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "customizationsMade.md"
    path.write_text(
        render_markdown(
            vertical,
            before,
            after,
            source_solution=source_solution,
            da_schemaname=da_schemaname,
            template_version=template_version,
            package_path=package_path,
        ),
        encoding="utf-8",
    )
    return path


def _agent_section(before: Snapshot, after: Snapshot) -> list[str]:
    """The agent's own name/description change — applied to config and entity, not a
    component — surfaced only when the migration actually changed either."""
    name_changed = before.display_name != after.display_name
    description_changed = before.description != after.description
    if not name_changed and not description_changed:
        return []
    lines = ["", "## Agent settings", ""]
    if name_changed:
        lines += [
            "**Display name**",
            "",
            f"- Shipped template: `{before.display_name}`",
            f"- Produced package: `{after.display_name}`",
            "",
        ]
    if description_changed:
        lines += ["**Description**", ""]
        lines += _text_diff(before.description or "", after.description or "")
        lines.append("")
    return lines


def _text_diff(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="shipped template",
        tofile="produced package",
        lineterm="",
    )
    body = list(diff)
    if not body:
        return ["_(no textual change)_"]
    return ["```diff", *body, "```"]


def _component_section(entry: ComponentChange) -> list[str]:
    lines = [
        f"### {entry.suffix}",
        "",
        f"- Kind: `{entry.kind or 'component'}`",
        f"- Schema name: `{entry.schemaname}`",
        "",
    ]
    if entry.change is Change.CHANGED:
        lines += ["```diff", entry.diff, "```", ""]
    elif entry.change is Change.ADDED:
        lines += [
            "New in the produced package; shown in full (no shipped version to diff "
            "against).",
            "",
            "```yaml",
            entry.diff,
            "```",
            "",
        ]
    else:
        lines += [
            "Present in the shipped template but not in the produced package.",
            "",
            "```yaml",
            entry.diff,
            "```",
            "",
        ]
    return lines


def _unified(before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile="shipped template",
        tofile="produced package",
        lineterm="",
    )
    return _truncate(list(diff))


def _truncate(body: list[str]) -> str:
    if len(body) <= _BODY_LIMIT:
        return "\n".join(body)
    kept = body[:_BODY_LIMIT]
    return "\n".join([*kept, f"# ... truncated {len(body) - _BODY_LIMIT} more line(s)"])


__all__ = [
    "Change",
    "ComponentChange",
    "ComponentText",
    "Snapshot",
    "changes",
    "render_markdown",
    "snapshot",
    "write",
]
