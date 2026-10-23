#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ESS ADK — macOS Bootstrap (FlightCheck Only)
#
# One-liner entry point:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck-mac.sh)"
# ---------------------------------------------------------------------------
set -euo pipefail

export FLIGHTCHECK_ONLY="true"

# Parse optional --branch / --source-base-url / --ring / --scope arguments
BRANCH="main"
SOURCE_BASE_URL=""
RING_ARG=""
DA_TARGET_URL=""
AGENT_SCHEMA_NAME=""
VALIDATION_REALM=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --branch)       BRANCH="$2"; shift 2 ;;
        --source-base-url) SOURCE_BASE_URL="$2"; shift 2 ;;
        --ring)         RING_ARG="$2"; shift 2 ;;
        --scope)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "ERROR: --scope requires a scope name; Full is never selected by default." >&2
                exit 2
            fi
            FLIGHTCHECK_SCOPE="$2"; shift 2 ;;
        --da-target-url|--agent-schema-name|--validation-realm)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "ERROR: $1 requires a value." >&2
                exit 2
            fi
            case "$1" in
                --da-target-url) DA_TARGET_URL="$2" ;;
                --agent-schema-name) AGENT_SCHEMA_NAME="$2" ;;
                --validation-realm) VALIDATION_REALM="$2" ;;
            esac
            shift 2 ;;
        *) shift ;;
    esac
done

resolve_flightcheck_scope() {
    local interactive="$1"
    local entry name
    # Keep this preflight self-contained: bootstrap runs it before downloading.
    # Scope names mirror cli.py, not its separate litmus profiles.
    local scopes=(
        'full|All applicable validation categories'
        'prerequisites|Prerequisite access and setup'
        'infrastructure|Infrastructure and connectivity'
        'environment|Power Platform environment'
        'solution|Installed solution configuration'
        'authentication|Authentication configuration'
        'entraapp|Microsoft Entra application'
        'workdaytenant|Workday tenant configuration'
        'external|External system configuration'
        'workday|External system and Workday checks'
        'workdayextension|Workday checks and extension'
        'workdayda|Workday declarative-agent package'
        'topics|Workday topics'
        'graphconnector|External system and Graph connector knowledge'
        'handoff|Agent handoff topics'
        'servicenow|External system and ServiceNow checks'
        'local|Local agent files'
        'publishing|Agent publishing'
        'licensing|Licensing'
        'cloudpolicy|Cloud policies'
    )
    local instructions="Specify --scope <scope> or set FLIGHTCHECK_SCOPE. Full requires explicit selection."
    if [[ -z "${FLIGHTCHECK_SCOPE:-}" ]]; then
        if [[ "$interactive" != "true" || -n "${CI:-}" || -n "${TF_BUILD:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
            echo "ERROR: FlightCheck scope is required for unattended installation. $instructions" >&2
            printf '  %s\n' "${scopes[@]//|/ - }" >&2
            return 2
        fi
        echo "Choose a FlightCheck scope (no default):"
        printf '  %s\n' "${scopes[@]//|/ - }"
        printf 'Enter a scope name: '
        if ! read -r FLIGHTCHECK_SCOPE; then
            echo "ERROR: FlightCheck scope input is unavailable. $instructions" >&2
            return 2
        fi
    fi
    FLIGHTCHECK_SCOPE="$(printf '%s' "$FLIGHTCHECK_SCOPE" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    for entry in "${scopes[@]}"; do
        name="${entry%%|*}"
        if [[ "$FLIGHTCHECK_SCOPE" == "$name" ]]; then
            export FLIGHTCHECK_SCOPE
            return 0
        fi
    done
    echo "ERROR: A valid FlightCheck scope is required; empty input does not select Full. $instructions" >&2
    printf '  %s\n' "${scopes[@]//|/ - }" >&2
    return 2
}

if [[ -t 0 ]]; then
    resolve_flightcheck_scope true
else
    resolve_flightcheck_scope false
fi

DA_TARGET_ARGS=()
if [[ -n "$DA_TARGET_URL$AGENT_SCHEMA_NAME$VALIDATION_REALM" ]]; then
    if [[ "$FLIGHTCHECK_SCOPE" != "full" || -z "$DA_TARGET_URL" ||
          -z "${AGENT_SCHEMA_NAME//[[:space:]]/}" ||
          ! "$VALIDATION_REALM" =~ ^(dev|test|prod)$ ]]; then
        echo "ERROR: DA onboarding requires --scope full --da-target-url <url> --agent-schema-name <schema> --validation-realm <dev|test|prod>." >&2
        exit 2
    fi
    DA_TARGET_ARGS=(--da-target-url "$DA_TARGET_URL" --agent-schema-name "$AGENT_SCHEMA_NAME" --validation-realm "$VALIDATION_REALM")
fi

SOURCE_BASE_URL="${SOURCE_BASE_URL:-${ESS_ADK_SOURCE_URL:-https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/$BRANCH/setup}}"
# Forward the ring choice to install-ess-adk.sh via the RING env var. Explicit
# --ring wins over an inherited RING env from the caller so a mistake in the
# shell environment can't silently override the one-liner argument. Validate
# up front so a typo fails fast at the bootstrap step (matches Windows
# `-Ring`'s ValidateSet behavior) instead of exiting mid-install.
if [[ -n "$RING_ARG" ]]; then
    case "$RING_ARG" in
        prod|preprod|test) ;;
        *)
            echo "ERROR: --ring must be prod, preprod, or test (got '$RING_ARG')" >&2
            exit 2
            ;;
    esac
    export RING="$RING_ARG"
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Fetching ESS ADK installer to $TEMP_DIR"
INSTALLER_URL="$SOURCE_BASE_URL/install-ess-adk.sh"
echo "  $INSTALLER_URL"

if ! curl -fsSL "$INSTALLER_URL" -o "$TEMP_DIR/install-ess-adk.sh"; then
    echo "  [ERR] Failed to download: $INSTALLER_URL" >&2
    echo "  If raw.githubusercontent.com is blocked by your firewall/proxy," >&2
    echo "  clone the repo manually and run: FLIGHTCHECK_ONLY=true setup/install-ess-adk.sh" >&2
    exit 1
fi

# Verify the downloaded file looks like a valid script
if [[ ! -s "$TEMP_DIR/install-ess-adk.sh" ]] || ! head -1 "$TEMP_DIR/install-ess-adk.sh" | grep -q '^#!/'; then
    echo "  [ERR] Downloaded file appears invalid (empty or not a shell script)" >&2
    echo "  A corporate proxy may be intercepting the request." >&2
    exit 1
fi

# Best-effort: fetch the installer telemetry emitter (fail-open — a telemetry
# download failure must never block the install).
if curl -fsSL "$SOURCE_BASE_URL/telemetry/install-telemetry.sh" -o "$TEMP_DIR/install-telemetry.sh" 2>/dev/null; then
    export ESS_INSTALL_TELEMETRY_LIB="$TEMP_DIR/install-telemetry.sh"
fi

# Run in-memory (source) to avoid any permission issues
export ESS_ADK_BRANCH="$BRANCH"
bash "$TEMP_DIR/install-ess-adk.sh" --scope "$FLIGHTCHECK_SCOPE" ${DA_TARGET_ARGS[@]+"${DA_TARGET_ARGS[@]}"}
