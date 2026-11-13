# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Search registered FlightCheck checks by what they verify.

Run from ``solutions/ess-maker-skills/scripts``::

    python -m flightcheck.catalog workday connection
    python -m flightcheck.catalog --release da --json servicenow

Use it before adding a check: a close match means you should reuse or update
that check instead of adding another one. Every term must match (AND), case
insensitively, against the ID, category, provider, owning module, purpose and
tags.

Limit: only Declarative Agent (DA) checks carry a recorded purpose
(``da_inventory.csv``). Legacy checks are matched on ID, category, provider and
module name only, so search those by area rather than by behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable

from . import registry


def _release_line(spec: registry.CheckpointSpec) -> str:
    return "da" if spec.da is not None else "legacy"


def build_catalog() -> list[dict[str, Any]]:
    """One row per listable checkpoint or checkpoint family."""
    rows = []
    for spec in registry.list_checkpoints():
        rows.append({
            "id": f"{spec.key}-*" if spec.is_family else spec.key,
            "family": spec.is_family,
            "release_line": _release_line(spec),
            "category": spec.category_label,
            "provider": spec.provider,
            "module": spec.category_fn.__module__.removeprefix("flightcheck."),
            "purpose": spec.da.purpose if spec.da else "",
            "documentation": spec.da.documentation if spec.da else "",
            "priority": spec.priority,
            "tags": list(spec.custom_tags),
        })
    return rows


def _haystack(row: dict[str, Any]) -> str:
    parts = [
        row["id"], row["category"], row["provider"], row["module"],
        row["purpose"], *row["tags"],
    ]
    return " ".join(str(part) for part in parts).casefold()


def search(
    rows: Iterable[dict[str, Any]], terms: list[str], release: str = "any",
) -> list[dict[str, Any]]:
    needles = [term.casefold() for term in terms if term.strip()]
    return [
        row for row in rows
        if release in ("any", row["release_line"])
        and all(needle in _haystack(row) for needle in needles)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("terms", nargs="*", help="Words that must all match.")
    parser.add_argument("--release", choices=("any", "da", "legacy"), default="any")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)

    matches = search(build_catalog(), args.terms, args.release)
    if args.json:
        print(json.dumps(matches, indent=2))
        return 0
    if not matches:
        print("No matching checks. Safe to add a new one; re-check with broader terms first.")
        return 0
    for row in matches:
        line = f"{row['id']:<18} [{row['release_line']}] {row['category']} ({row['module']})"
        print(line)
        if row["purpose"]:
            print(f"    {row['purpose']}")
    print(f"{len(matches)} match(es).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
