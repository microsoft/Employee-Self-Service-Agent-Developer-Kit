# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Strip the DBG node(s) a prior ``plant_debug.py`` planted, then publish.

Reads the provenance written by ``plant_debug.py``, removes the planted DBG
SendActivity node(s) from the deployed topic (restoring it byte-identically),
publishes so the removal goes live, and deletes the provenance file.

Idempotent: if the nodes are already gone, it still clears the provenance and
exits cleanly.

Usage:
    python scripts/strip_debug.py [--yes]
"""
from __future__ import annotations

import argparse

from debug_plant import strip_debug_nodes_live
from plant_debug import (
    PROVENANCE_PATH,
    AuthDataverseClient,
    load_provenance,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Strip planted DBG nodes from a deployed topic and publish.")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    if not PROVENANCE_PATH.exists():
        print(f"No provenance at {PROVENANCE_PATH}; nothing to strip.")
        return 0

    provenance = load_provenance()

    from auth import authenticate, load_config

    config = load_config()
    env_url = config["dataverseEndpoint"]
    bot_id = config["agent"]["botId"]

    if not args.yes:
        resp = input(
            f"Strip DBG node(s) {provenance.planted_node_ids} from topic "
            f"{provenance.topic!r} and publish? (yes/no): ").strip().lower()
        if resp not in ("yes", "y"):
            print("Strip cancelled.")
            return 0

    token = authenticate(env_url)
    client = AuthDataverseClient(env_url, token)

    count = strip_debug_nodes_live(client, provenance)
    print(f"  Stripped {count} node(s) from {provenance.topic!r}.")

    print("Publishing...")
    client.publish_bot(bot_id)
    print("  Published. Topic restored to its pre-plant state.")

    PROVENANCE_PATH.unlink()
    print(f"  Cleared {PROVENANCE_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
