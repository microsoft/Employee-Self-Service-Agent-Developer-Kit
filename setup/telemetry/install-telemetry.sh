#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Installer telemetry emitter (Aria / 1DS OneCollector) for the ESS ADK
# installers — macOS / Linux (bash).
#
# Dependency-light, self-contained mirror of the Python telemetry SDK
# (solutions/ess-maker-skills/scripts/flightcheck/telemetry.py) and of the
# PowerShell emitter (setup/telemetry/install-telemetry.ps1). The installers
# run bash BEFORE Python is guaranteed to exist, so we reproduce the
# OneCollector envelope + POST here with curl.
#
# Design rules (deliberate — read before changing):
#   * Fail-open, NEVER break the install. Every function returns 0 and
#     swallows its own errors; telemetry never changes the installer's exit.
#   * Same privacy model: no developer/user identity; random per-install
#     instance_id for dedup; raw tenant GUID (OII) only where available;
#     enums + scrubbed errors only (paths/URLs/emails/GUIDs stripped).
#   * Same unified opt-out: ESS_ADK_TELEMETRY=off or ~/.adk/config
#     {"telemetry":"disabled"}; one-time notice on first install.
#
# The iKeys are 1DS ingestion keys: write-only, safe to embed.
#
# Source this file, then call: ess_tel_init <adk|lite|flightcheck> [tenant_id]
#   ess_tel_step <step>; ess_tel_complete <success|failure|cancelled> [msg]
# ---------------------------------------------------------------------------

ESS_TEL_IKEY_DEV='08e397b2c6c243eeaeb341e111c36167-294d89f6-c806-4c65-adf3-dea3bb44f949-7206'
ESS_TEL_IKEY_PROD='311254257bbc417e860c76781d4863c8-8cff75a4-47b7-4675-9646-45a4ca9bc138-7062'
ESS_TEL_COLLECTOR='https://mobile.events.data.microsoft.com/OneCollector/1.0/?cors=true&content-type=application/x-json-stream'
ESS_TEL_SCHEMA='1.0'
# Microsoft corporate Entra tenant — the only internal tenancy by default.
ESS_TEL_CORP_TENANT='72f988bf-86f1-41af-91ab-2d7cd011db47'
ESS_TEL_CONFIG_DIR="$HOME/.adk"
ESS_TEL_CONFIG="$ESS_TEL_CONFIG_DIR/config"

ESS_TEL_READY=0
ESS_TEL_INSTALLER='adk'
ESS_TEL_ENV='prod'
ESS_TEL_IKEY=''
ESS_TEL_INSTANCE=''
ESS_TEL_TENANT=''
ESS_TEL_FIRSTRUN='true'
ESS_TEL_PLATFORM='macOS'
ESS_TEL_OS=''
ESS_TEL_ADKVER='unknown'
ESS_TEL_START=0
ESS_TEL_STEP=''
ESS_TEL_STEPIDX=0
ESS_TEL_COMPLETED=0

# --- consent / opt-out -----------------------------------------------------
ess_tel_enabled() {
    local v
    v="$(printf '%s' "${ESS_ADK_TELEMETRY:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$v" in
        0|off|false|no|disabled) return 1 ;;
        1|on|true|yes|enabled)   return 0 ;;
    esac
    if [[ -f "$ESS_TEL_CONFIG" ]] && grep -Eq '"telemetry"[[:space:]]*:[[:space:]]*"disabled"' "$ESS_TEL_CONFIG" 2>/dev/null; then
        return 1
    fi
    return 0
}

ess_tel_notice() {
    # One-time notice, idempotent via config noticeShown (best-effort).
    if [[ -f "$ESS_TEL_CONFIG" ]] && grep -Eq '"noticeShown"[[:space:]]*:[[:space:]]*true' "$ESS_TEL_CONFIG" 2>/dev/null; then
        return 0
    fi
    cat >&2 <<'EOF'

------------------------------------------------------------------------
ESS Agent Developer Kit collects pseudonymous installation telemetry
(install success/failure, which step failed, scrubbed error categories,
duration, platform) to help us improve setup reliability. It does NOT
collect your identity, credentials, file contents, or agent content.
Opt out any time:  python scripts/adk_telemetry.py off   (or set
ESS_ADK_TELEMETRY=off). Details: https://aka.ms/adk-telemetry
------------------------------------------------------------------------

EOF
    mkdir -p "$ESS_TEL_CONFIG_DIR" 2>/dev/null || true
    if [[ -f "$ESS_TEL_CONFIG" ]] && grep -q '"telemetry"' "$ESS_TEL_CONFIG" 2>/dev/null; then
        # append noticeShown without clobbering (best-effort minimal edit)
        if ! grep -q '"noticeShown"' "$ESS_TEL_CONFIG" 2>/dev/null; then
            # insert before the closing brace
            local tmp="$ESS_TEL_CONFIG.tmp.$$"
            sed 's/}[[:space:]]*$/, "noticeShown": true }/' "$ESS_TEL_CONFIG" > "$tmp" 2>/dev/null && mv "$tmp" "$ESS_TEL_CONFIG" 2>/dev/null || true
        fi
    else
        printf '{ "telemetry": "enabled", "noticeShown": true }\n' > "$ESS_TEL_CONFIG" 2>/dev/null || true
    fi
    return 0
}

# --- identity --------------------------------------------------------------
ess_tel_instance_info() {
    # Sets ESS_TEL_INSTANCE + ESS_TEL_FIRSTRUN.
    local candidates=() p existing
    if [[ -n "${ESS_ADK_INSTALL_ROOT:-}" ]]; then
        candidates+=("$ESS_ADK_INSTALL_ROOT/Employee-Self-Service-Agent-Developer-Kit/.local/.instance_id")
    fi
    candidates+=("$ESS_TEL_CONFIG_DIR/.instance_id")
    for p in "${candidates[@]}"; do
        if [[ -f "$p" ]]; then
            existing="$(tr -d '[:space:]' < "$p" 2>/dev/null)"
            if [[ -n "$existing" ]]; then
                ESS_TEL_INSTANCE="$existing"; ESS_TEL_FIRSTRUN='false'; return 0
            fi
        fi
    done
    local newid
    if command -v uuidgen >/dev/null 2>&1; then
        newid="$(uuidgen | tr '[:upper:]' '[:lower:]')"
    else
        newid="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s%N)"
    fi
    ESS_TEL_INSTANCE="$newid"; ESS_TEL_FIRSTRUN='true'
    mkdir -p "$ESS_TEL_CONFIG_DIR" 2>/dev/null || true
    printf '%s' "$newid" > "$ESS_TEL_CONFIG_DIR/.instance_id" 2>/dev/null || true
    return 0
}

ess_tel_tenant_class() {
    local t="$1"
    if [[ -z "$t" ]]; then printf 'unknown'; return 0; fi
    t="$(printf '%s' "$t" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    local corp; corp="$(printf '%s' "$ESS_TEL_CORP_TENANT" | tr '[:upper:]' '[:lower:]')"
    local internal=",$corp,"
    if [[ -n "${ESS_ADK_INTERNAL_TENANTS:-}" ]]; then
        local extra; extra="$(printf '%s' "$ESS_ADK_INTERNAL_TENANTS" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
        internal="$internal$extra,"
    fi
    if [[ "$internal" == *",$t,"* ]]; then printf 'internal'; else printf 'customer'; fi
    return 0
}

# --- scrub (mirrors adk_telemetry._scrub) ----------------------------------
ess_tel_scrub() {
    local s="$1"
    s="${s//$'\n'/ }"; s="${s//$'\r'/ }"
    s="$(printf '%s' "$s" \
        | sed -E 's#[A-Za-z]:\\[^[:space:]]+#<path>#g' \
        | sed -E 's#https?://[^[:space:]]+#<url>#g' \
        | sed -E 's#(^|[^A-Za-z0-9_])/[^[:space:]]+#\1<path>#g' \
        | sed -E 's#[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}#<email>#g' \
        | sed -E 's#[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}#<guid>#g')"
    printf '%s' "${s:0:200}"
}

# --- json helper -----------------------------------------------------------
_ess_tel_jesc() {
    # Escape a string for embedding in JSON.
    local s="$1"
    s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
    s="${s//$'\n'/ }"; s="${s//$'\r'/ }"; s="${s//$'\t'/ }"
    printf '%s' "$s"
}

# --- transport -------------------------------------------------------------
ess_tel_send() {
    # $1 = event name, $2 = extra JSON fields (already ",key:val,..." or empty)
    [[ "$ESS_TEL_READY" == "1" ]] || return 0
    local name="$1" extra="$2"
    local envtoken="o:${ESS_TEL_IKEY%%-*}"
    local ts ns ms
    ns="$(date +%N 2>/dev/null || echo 0)"; ns="${ns//[!0-9]/}"; [[ -n "$ns" ]] || ns=0
    ms=$(( (10#$ns / 1000000) % 1000 ))
    ts="$(date -u +%Y-%m-%dT%H:%M:%S).$(printf '%03d' "$ms")Z"
    local tclass; tclass="$(ess_tel_tenant_class "$ESS_TEL_TENANT")"
    local data
    data="{\"schemaVersion\":\"$ESS_TEL_SCHEMA\",\"env\":\"$ESS_TEL_ENV\",\"installer\":\"$ESS_TEL_INSTALLER\",\"invocationSource\":\"installer\",\"platform\":\"$ESS_TEL_PLATFORM\",\"os\":\"$(_ess_tel_jesc "$ESS_TEL_OS")\",\"instanceId\":\"$ESS_TEL_INSTANCE\",\"tenantId\":\"$(_ess_tel_jesc "$ESS_TEL_TENANT")\",\"tenantClass\":\"$tclass\",\"adkVersion\":\"$(_ess_tel_jesc "$ESS_TEL_ADKVER")\",\"firstRun\":$ESS_TEL_FIRSTRUN$extra}"
    local body="{\"ver\":\"4.0\",\"name\":\"$name\",\"time\":\"$ts\",\"iKey\":\"$envtoken\",\"data\":$data}"
    local uploadms; uploadms="$(( $(date +%s) * 1000 ))"
    curl -fsS -m 5 -X POST "$ESS_TEL_COLLECTOR" \
        -H "apikey: $ESS_TEL_IKEY" \
        -H 'Client-Id: NO_AUTH' \
        -H "client-version: ess-maker-installer-$ESS_TEL_ADKVER" \
        -H "upload-time: $uploadms" \
        -H 'cache-control: no-cache, no-store' \
        -H 'NoResponseBody: true' \
        -H 'Content-Type: application/x-json-stream' \
        --data-binary "$body"$'\n' >/dev/null 2>&1 || true
    return 0
}

# --- public API ------------------------------------------------------------
ess_tel_init() {
    # $1 = installer (adk|lite|flightcheck), $2 = tenant_id (optional)
    ESS_TEL_INSTALLER="${1:-adk}"
    ESS_TEL_TENANT="${2:-}"
    ess_tel_enabled || { ESS_TEL_READY=0; return 0; }
    # The Lite-mode installer is being merged into the standard ADK installer
    # (mode will become an onboarding prompt), so it is no longer instrumented.
    [[ "$ESS_TEL_INSTALLER" == "lite" ]] && { ESS_TEL_READY=0; return 0; }
    ess_tel_notice
    local envname
    envname="$(printf '%s' "${ESS_ADK_ARIA_ENV:-${ESS_FLIGHTCHECK_ARIA_ENV:-}}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    if [[ "$envname" == "dev" ]]; then ESS_TEL_ENV='dev'; ESS_TEL_IKEY="$ESS_TEL_IKEY_DEV"; else ESS_TEL_ENV='prod'; ESS_TEL_IKEY="$ESS_TEL_IKEY_PROD"; fi
    ess_tel_instance_info
    case "$(uname -s 2>/dev/null)" in
        Darwin) ESS_TEL_PLATFORM='macOS' ;;
        Linux)  ESS_TEL_PLATFORM='Linux' ;;
        *)      ESS_TEL_PLATFORM='Unix' ;;
    esac
    ESS_TEL_OS="$(uname -sr 2>/dev/null || echo unknown)"
    ESS_TEL_ADKVER="${ESS_ADK_VERSION:-unknown}"
    ESS_TEL_START="$(date +%s)"
    ESS_TEL_STEPIDX=0
    ESS_TEL_STEP='start'
    ESS_TEL_COMPLETED=0
    ESS_TEL_READY=1
    ess_tel_send 'ESSMakerKit.Installer.Start' ''
    return 0
}

ess_tel_step() {
    [[ "$ESS_TEL_READY" == "1" ]] || return 0
    ESS_TEL_STEPIDX=$((ESS_TEL_STEPIDX + 1))
    ESS_TEL_STEP="$1"
    ess_tel_send 'ESSMakerKit.Installer.Step' ",\"step\":\"$(_ess_tel_jesc "$1")\",\"stepIndex\":$ESS_TEL_STEPIDX,\"outcome\":\"reached\""
    return 0
}

ess_tel_complete() {
    # $1 = outcome (success|failure|cancelled), $2 = error message (optional)
    [[ "$ESS_TEL_READY" == "1" ]] || return 0
    [[ "$ESS_TEL_COMPLETED" == "0" ]] || return 0
    ESS_TEL_COMPLETED=1
    local outcome="${1:-success}" msg="${2:-}"
    local dur=0
    if [[ "$ESS_TEL_START" -gt 0 ]]; then dur=$(( $(date +%s) - ESS_TEL_START )); fi
    local failed=''
    [[ "$outcome" == "success" ]] || failed="$ESS_TEL_STEP"
    local extra=",\"outcome\":\"$outcome\",\"failedStep\":\"$(_ess_tel_jesc "$failed")\",\"durationSecs\":$dur"
    if [[ -n "$msg" ]]; then
        extra="$extra,\"errorMessage\":\"$(_ess_tel_jesc "$(ess_tel_scrub "$msg")")\""
    fi
    ess_tel_send 'ESSMakerKit.Installer.Complete' "$extra"
    return 0
}
