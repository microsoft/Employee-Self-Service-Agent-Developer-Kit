"""Accumulator that coalesces field edits into de-duplicated, no-op-guarded writes.

Transformation steps stage field changes per Dataverse record here instead of
appending to a flat list. Keying by ``(entity_set, record_id)`` means multiple
steps — and multiple rules editing the same field of the same record — coalesce
into **one** PATCH, and each step reads the *working* value so edits **chain**.

``pending_writes`` is **derived** by diffing the working value against the
original baseline, so only records with a genuine change are written. This avoids
stamping a needless unmanaged (``Active``) overlay over an unchanged managed base
when a transform is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WritebackTarget:
    """The staged edits for a single Dataverse record, with its baseline."""

    entity_set: str
    record_id: str
    # Baseline field values as read from Dataverse (the current/effective values).
    original: dict[str, Any] = field(default_factory=dict)
    # Working field values staged by transformation steps.
    working: dict[str, Any] = field(default_factory=dict)

    def get(self, field_name: str) -> Any:
        """Return the working value if one is staged, else the original baseline.

        Rule steps read through this so that a later rule sees the value produced
        by an earlier rule (chaining) rather than the untouched original.
        """
        if field_name in self.working:
            return self.working[field_name]
        return self.original.get(field_name)

    def set(self, field_name: str, value: Any) -> None:
        """Stage a working value for a field (unconditionally; the diff guards no-ops)."""
        self.working[field_name] = value

    def changes(self) -> dict[str, Any]:
        """Return only the staged fields whose value differs from the original."""
        return {
            name: value for name, value in self.working.items() if value != self.original.get(name)
        }


class WritebackPlan:
    """Coalesces per-record field edits and derives the pending writeback list."""

    def __init__(self) -> None:
        self._targets: dict[tuple[str, str], WritebackTarget] = {}

    def target(
        self, entity_set: str, record_id: str, *, original: dict[str, Any] | None = None
    ) -> WritebackTarget:
        """Return (creating on first touch) the target for a record.

        ``original`` seeds the baseline field values. The first value seen for a
        field wins, so a later step passing the same field cannot clobber the true
        baseline used for the no-op diff.
        """
        key = (entity_set, record_id)
        target = self._targets.get(key)
        if target is None:
            target = WritebackTarget(entity_set, record_id, original=dict(original or {}))
            self._targets[key] = target
        elif original:
            for name, value in original.items():
                target.original.setdefault(name, value)
        return target

    def pending_writes(self) -> list[dict[str, Any]]:
        """Derive coalesced, no-op-guarded writes — one entry per changed record.

        Each entry is ``{"entity_set", "record_id", "changes"}``; records whose
        working values all equal their originals produce no entry. Order follows
        first-touch order of the targets (deterministic).
        """
        writes: list[dict[str, Any]] = []
        for target in self._targets.values():
            changes = target.changes()
            if changes:
                writes.append(
                    {
                        "entity_set": target.entity_set,
                        "record_id": target.record_id,
                        "changes": changes,
                    }
                )
        return writes

    def target_for(self, entity_set: str, record_id: str) -> WritebackTarget | None:
        """Look up a record's staged target without creating one.

        Read-only accessor (returns ``None`` for an untouched record) so callers —
        e.g. reporting — can compare a record's ``original`` (actual copy) against
        its ``working`` (final modified copy) after all transformation steps,
        without a second stored copy of the data.
        """
        return self._targets.get((entity_set, record_id))

    def targets(self) -> list[WritebackTarget]:
        """All touched targets in first-touch order (for before/after reporting)."""
        return list(self._targets.values())
