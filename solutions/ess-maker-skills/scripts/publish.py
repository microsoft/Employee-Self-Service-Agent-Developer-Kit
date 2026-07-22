# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Publish Script

Publishes the active Copilot Studio agent so pushed topic (botcomponent)
changes go live in the test pane and runtime. Dataverse writes alone do not
take effect until the bot is published; flow ``clientdata`` edits are the
exception (live immediately, no publish needed).

This is a standalone capability — it is NOT run automatically by push.py. A
maker (or the agent, on the maker's behalf) invokes it explicitly when they
want their pushed topic changes to go live.

Usage:
    python scripts/publish.py           — Publish the active agent (interactive)
    python scripts/publish.py --yes     — Publish without the confirmation prompt
"""

import os
import sys

try:
    import sys as _sys
    if _sys.stdout.encoding and _sys.stdout.encoding.lower() != "utf-8" \
            and hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 — console reconfig is best-effort
    pass

# Add scripts/ to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import authenticate, publish_bot, load_config  # noqa: E402


def main():
    auto_yes = "--yes" in sys.argv

    config = load_config()
    env_url = config["dataverseEndpoint"]
    agent = config["agent"]
    bot_id = agent["botId"]
    agent_name = agent.get("name", bot_id)

    print(f"Agent:       {agent_name}")
    print(f"Environment: {env_url}")

    if not auto_yes:
        response = input(
            "\nPublish this agent so pushed topic changes go live? (yes/no): "
        ).strip().lower()
        if response not in ("yes", "y"):
            print("Publish cancelled.")
            return

    print("\nAuthenticating to Dataverse...")
    token = authenticate(env_url)
    print("Authenticated.\n")

    print("Publishing... (this can take a minute)")
    try:
        publish_bot(env_url, token, bot_id)
    except Exception as e:  # noqa: BLE001 — surface a clean message + exit code
        print(f"  ❌ Publish failed: {e}")
        sys.exit(1)

    print("  ✅ Published. Pushed topic changes are now live.")

    # Best-effort usage telemetry — never fails the command.
    try:
        import subprocess
        subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "emit_capability.py"),
             "publish"],
            check=False, capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
