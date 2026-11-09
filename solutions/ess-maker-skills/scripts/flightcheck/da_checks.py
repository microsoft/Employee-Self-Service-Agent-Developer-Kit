# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA metadata attached to the shared checkpoint registry, not a second index."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .registry import CheckpointSpec


_DISPOSITIONS = frozenset({"execute", "replaced", "legacy", "excluded", "guard", "detail", "deferred"})


@dataclass(frozen=True)
class DAValidation:
    purpose: str
    strategy: str = "custom"
    feature: str = ""
    disposition: str = "execute"
    reason: str = ""
    replacements: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ("DA-AGENT-001",)
    source: str = ""
    source_revision: str = ""
    historical_purpose: str = ""
    target_scope: str = "selected-agent"
    api_contract: str = ""
    manual_steps: tuple[str, ...] = ()
    if_incorrect: str = ""
    local: bool = False
    documentation: str = ""

    @property
    def executable(self) -> bool:
        return self.disposition == "execute"


def attach_inventory(
    existing: list[CheckpointSpec], spec_type: Callable[..., CheckpointSpec],
) -> list[CheckpointSpec]:
    from .checks.da_validation import run_registered_da_check

    by_id = {spec.key: spec for spec in existing}
    seen: set[str] = set()
    with Path(__file__).with_name("da_inventory.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["checkpoint"]
            if key in seen:
                raise ValueError(f"Duplicate DA inventory identity: {key}.")
            seen.add(key)
            definition = DAValidation(
                purpose=row["purpose"], strategy=row["strategy"],
                feature=row["feature"], disposition=row["disposition"],
                reason=row["reason"], replacements=tuple(row["replacements"].split()),
                prerequisites=tuple(row["prerequisites"].split()),
                source=row["source"], source_revision=row["source_revision"],
                historical_purpose=row["historical_purpose"], target_scope=row["target_scope"],
                api_contract=row["api_contract"],
                manual_steps=tuple(row["manual_steps"].split(" | ")) if row["manual_steps"] else (),
                if_incorrect=row["if_incorrect"], local=row["local"] == "true",
                documentation=row.get("documentation", ""),
            )
            if definition.disposition not in _DISPOSITIONS:
                raise ValueError(f"Invalid DA disposition for {key}.")
            if definition.target_scope not in {"tenant", "environment", "selected-agent", "selected-local"}:
                raise ValueError(f"Invalid DA target scope for {key}.")
            if not definition.purpose or not definition.reason:
                raise ValueError(f"Missing DA purpose/disposition reason for {key}.")
            if definition.executable and not definition.manual_steps:
                raise ValueError(f"Missing manual fallback for {key}.")
            if key in by_id:
                by_id[key] = replace(by_id[key], da=definition)
            else:
                families = [
                    spec for spec in existing
                    if spec.is_family and key.startswith(spec.key + "-")
                ]
                if families:
                    family = max(families, key=lambda spec: len(spec.key))
                    by_id[key] = replace(
                        family, key=key, is_family=False, da=definition,
                        legacy_family=family.key,
                        listable=definition.executable,
                    )
                else:
                    by_id[key] = spec_type(
                        key=key, category_fn=run_registered_da_check,
                        category_label=row["area"], roles=tuple(row["roles"].split(" | ")),
                        da=definition, listable=definition.executable,
                    )
    return list(by_id.values())


def validate_da_definitions(registry: dict[str, CheckpointSpec]) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(key):
        if key in active:
            raise ValueError(f"Cyclic DA prerequisite/replacement at {key}.")
        if key in visited:
            return
        spec = registry.get(key)
        if spec is None or spec.da is None:
            raise ValueError(f"Missing DA prerequisite/replacement definition: {key}.")
        definition = spec.da
        if definition.disposition not in _DISPOSITIONS:
            raise ValueError(f"Invalid DA disposition for {key}.")
        if definition.disposition == "replaced" and not definition.replacements:
            raise ValueError(f"DA replacement {key} has no canonical target.")
        if not definition.purpose:
            raise ValueError(f"DA check {key} has no assertion purpose.")
        if definition.executable and (
            not definition.manual_steps or not definition.if_incorrect or not spec.roles
        ):
            raise ValueError(f"DA check {key} lacks complete fallback steps, missing-setting guidance or ownership.")
        active.add(key)
        for dependency in (*definition.prerequisites, *definition.replacements):
            visit(dependency)
        active.remove(key)
        visited.add(key)

    for key, spec in registry.items():
        if spec.da is not None:
            visit(key)
