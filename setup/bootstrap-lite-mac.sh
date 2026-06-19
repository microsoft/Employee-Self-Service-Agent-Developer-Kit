#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ESS ADK — macOS Bootstrap (Lite Mode)
#
# One-liner entry point:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite-mac.sh)"
#
# Installs the full maker kit with the ESS Maker Profile extension enabled,
# giving users a chat-first, big-button experience.
# ---------------------------------------------------------------------------
set -euo pipefail

# Lite mode: do NOT set SKIP_MAKER_PROFILE so the chat-first profile installs.

SOURCE_BASE_URL="${ESS_ADK_SOURCE_URL:-https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup}"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Fetching ESS ADK installer to $TEMP_DIR"
INSTALLER_URL="$SOURCE_BASE_URL/install-ess-adk.sh"
echo "  $INSTALLER_URL"

if ! curl -fsSL "$INSTALLER_URL" -o "$TEMP_DIR/install-ess-adk.sh"; then
    echo "  [ERR] Failed to download: $INSTALLER_URL" >&2
    echo "  If raw.githubusercontent.com is blocked by your firewall/proxy," >&2
    echo "  clone the repo manually and run: setup/install-ess-adk.sh" >&2
    exit 1
fi

# Verify the downloaded file looks like a valid script
if [[ ! -s "$TEMP_DIR/install-ess-adk.sh" ]] || ! head -1 "$TEMP_DIR/install-ess-adk.sh" | grep -q '^#!/'; then
    echo "  [ERR] Downloaded file appears invalid (empty or not a shell script)" >&2
    echo "  A corporate proxy may be intercepting the request." >&2
    exit 1
fi

# Run the downloaded installer in a subshell to avoid issues if it calls exit
bash "$TEMP_DIR/install-ess-adk.sh"
