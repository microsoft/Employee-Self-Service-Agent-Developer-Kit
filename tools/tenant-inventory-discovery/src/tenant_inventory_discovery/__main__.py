"""CLI entry point for the discovery skill.

Runs a single discovery pass against a sample platform surface and the in-memory
Inventory client, so the whole lifecycle can be exercised without the live service.
This entry point is a **development harness**; the kit drives the real thing through
``solutions/ess-maker-skills/scripts/discover_inventory.py``, which wires the live
platform clients and :class:`HttpInventoryClient`.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import DiscoveryConfig
from .discovery_skill import DiscoverySkill
from .in_memory_inventory import InMemoryInventoryClient
from .platform_clients import FakePlatform


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tenant-inventory-discovery",
        description="Admin-run crawler for the WeveNova tenant inventory.",
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant identifier to crawl.")
    parser.add_argument(
        "--environment-id",
        action="append",
        dest="environment_ids",
        help="Restrict to specific environment id(s). Omit for a full/tenant-root crawl.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable info logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    # Sample platform + in-memory Inventory: this CLI is a development harness, not
    # the production entry point (see the module docstring).
    skill = DiscoverySkill(
        platform=FakePlatform(),
        inventory=InMemoryInventoryClient(),
        config=DiscoveryConfig(),
    )
    summary = skill.discover(args.tenant_id, environment_ids=args.environment_ids)

    print(f"correlation_id={summary.correlation_id} aborted={summary.aborted}")
    print(f"completed_scopes={len(summary.completed_scopes)}")
    print(f"retired={summary.retired_counts}")
    return 1 if summary.aborted else 0


if __name__ == "__main__":
    sys.exit(main())
