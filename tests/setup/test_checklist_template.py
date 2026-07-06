# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural consistency guard for the master setup checklist template.

Pure-logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are exempt
from the cassette rule). The template
``src/skills/setup/workday/tasks.md`` is the canonical row source that every
Workday setup skill renders and updates via ``checklist-updater.md``. Each item
is a user-facing checkbox line followed by a hidden HTML-comment carrying the
machine-readable metadata (``id`` / ``role`` / ``skill`` / ``automatable`` /
``checkpoints`` / ``gate`` / ``status``). If that metadata drifts — a
duplicated/renamed Step ID, a typo'd or foreign checkpoint, an invalid gate, a
status that isn't seeded ``pending``, or a checkbox seeded checked — the skills
silently fail to locate their items. This test pins the template's shape so that
drift is caught at CI time rather than at setup time.

It also enforces the cross-document contract: every Step ID referenced by the
shared ``config-schema.md`` / ``checklist-updater.md`` examples must exist in the
template (those docs read the template as the source of truth).
"""

from __future__ import annotations

import re
from pathlib import Path

from flightcheck import registry
from flightcheck.registry import OWNED_PREFIXES

# tests/setup/test_checklist_template.py -> repo root is parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_TEMPLATE = _SOLUTION / "src" / "skills" / "setup" / "workday" / "tasks.md"
_SHARED = _SOLUTION / "src" / "skills" / "setup" / "shared"

# The canonical Step IDs the template MUST declare (master-checklist.md items).
_EXPECTED_STEPS = {
    "S1.1", "S1.2",
    "S2.1",
    "S3.1", "S3.2", "S3.3", "S3.4", "S3.5", "S3.6", "S3.7",
    "S4.1", "S4.2", "S4.3", "S4.4",
    "S5.1", "S5.2", "S5.3", "S5.4", "S5.5", "S5.6", "S5.7", "S5.8",
    "S6.1", "S6.2",
}

_METADATA_KEYS = {
    "id", "role", "skill", "automatable", "checkpoints", "gate", "status",
}
_VALID_GATES = {"prog", "manual", "attest"}
_STEP_RE = re.compile(r"^S\d+\.\d+$")
# Upper-case checkpoint tokens, optionally a "-*" family suffix.
_CKPT_RE = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*(?:-\*)?")
# A checkbox item line immediately followed by its hidden metadata comment.
_ITEM_RE = re.compile(
    r"^-\s*\[(?P<box>[ xX])\]\s+.*\n\s*<!--(?P<meta>.*?)-->\s*$",
    re.MULTILINE,
)


def _parse_items() -> list[dict[str, str]]:
    """Return the checklist items as dicts of their hidden metadata plus a
    ``checkbox`` key holding the raw marker (`` `` unchecked / ``x`` checked)."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    items: list[dict[str, str]] = []
    for match in _ITEM_RE.finditer(text):
        meta: dict[str, str] = {"checkbox": match.group("box").lower()}
        for field in match.group("meta").split("|"):
            key, sep, val = field.partition(":")
            if not sep:
                continue
            meta[key.strip()] = val.strip()
        items.append(meta)
    return items


def _probe(token: str) -> str:
    """Normalise a checkpoint token to a registry probe (drop a ``-*`` family
    suffix)."""
    if token.endswith("-*"):
        return token[:-2]
    return token.rstrip("*")


def _is_owned(probe: str) -> bool:
    return any(
        probe == prefix or probe.startswith(prefix + "-")
        for prefix in OWNED_PREFIXES
    )


class TestChecklistTemplate:
    def test_template_exists(self):
        assert _TEMPLATE.is_file(), f"missing checklist template: {_TEMPLATE}"

    def test_items_carry_full_metadata(self):
        items = _parse_items()
        assert items, "no checklist items parsed — template shape changed?"
        for meta in items:
            missing = _METADATA_KEYS - meta.keys()
            assert not missing, (
                f"item hidden comment missing field(s) {sorted(missing)}: {meta}"
            )
            assert _STEP_RE.match(meta["id"]), (
                f"item id is not a Step ID: {meta['id']!r}"
            )

    def test_step_ids_complete_and_unique(self):
        step_ids = [meta["id"] for meta in _parse_items()]
        assert len(step_ids) == len(set(step_ids)), (
            f"duplicate Step IDs: {sorted({s for s in step_ids if step_ids.count(s) > 1})}"
        )
        assert set(step_ids) == _EXPECTED_STEPS, (
            f"Step ID set drifted. Missing: {_EXPECTED_STEPS - set(step_ids)}; "
            f"unexpected: {set(step_ids) - _EXPECTED_STEPS}"
        )

    def test_every_checkpoint_resolves_or_is_owned_pending(self):
        failures = []
        for meta in _parse_items():
            step = meta["id"]
            checkpoint_cell = meta["checkpoints"]
            tokens = _CKPT_RE.findall(checkpoint_cell)
            assert tokens, f"{step}: no checkpoint token in {checkpoint_cell!r}"
            for tok in tokens:
                probe = _probe(tok)
                if registry.resolve(probe) is not None:
                    continue  # runnable today (reuse / already registered)
                if _is_owned(probe):
                    continue  # minted, pending its skill's emitter+entry
                failures.append((step, tok))
        assert not failures, (
            "checkpoint token(s) neither resolve in the registry nor fall under "
            f"an owned setup prefix (typo or foreign ID?): {failures}"
        )

    def test_gates_are_valid(self):
        for meta in _parse_items():
            step = meta["id"]
            gate_lead = re.match(r"[a-z]+", meta["gate"])
            assert gate_lead, f"{step}: gate has no leading keyword: {meta['gate']!r}"
            assert gate_lead.group(0) in _VALID_GATES, (
                f"{step}: invalid gate {gate_lead.group(0)!r} (value {meta['gate']!r})"
            )

    def test_status_seeded_pending(self):
        for meta in _parse_items():
            step = meta["id"]
            assert meta["status"] == "pending", (
                f"{step}: template status must seed 'pending', got {meta['status']!r}"
            )

    def test_checkboxes_seeded_unchecked(self):
        for meta in _parse_items():
            step = meta["id"]
            assert meta["checkbox"] == " ", (
                f"{step}: template checkbox must seed unchecked '- [ ]', "
                f"got marker {meta['checkbox']!r}"
            )

    def test_family_rows_keep_literal_star(self):
        # The three data-driven items must carry the literal "*" so the
        # checklist-updater knows to expand them per emitted/created item.
        family_steps = {"S5.6", "S6.1", "S6.2"}
        starred = {
            meta["id"] for meta in _parse_items() if "*" in meta["checkpoints"]
        }
        assert starred == family_steps, (
            f"family (*) items drifted. Expected {family_steps}, found {starred}"
        )

    def test_cross_doc_step_ids_subset(self):
        # Every Step ID the shared docs cite in examples must exist in the
        # template (the docs treat the template as the row source of truth).
        template_steps = {meta["id"] for meta in _parse_items()}
        cited: set[str] = set()
        for name in ("config-schema.md", "checklist-updater.md"):
            text = (_SHARED / name).read_text(encoding="utf-8")
            cited.update(re.findall(r"\bS\d+\.\d+\b", text))
        missing = cited - template_steps
        assert not missing, (
            f"shared docs cite Step IDs absent from the template: {sorted(missing)}"
        )
