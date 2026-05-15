# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Shared Power Platform Helpers

Common utilities for /provision scripts: .env loading with alias resolution,
MSAL token acquisition (device-code + browser), per-env host construction,
persona/connector mappings.
"""

import os
import sys

try:
    import msal
except ImportError:
    print("ERROR: 'msal' package not found. Run: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(3)


SCOPES_BY_RING = {
    "preprod": "https://api.preprod.powerplatform.com/.default",
    "prod": "https://api.powerplatform.com/.default",
}

HOST_SUFFIX_BY_RING = {
    "preprod": "environment.api.preprod.powerplatform.com",
    "prod": "environment.api.powerplatform.com",
}

MAKER_HOST_BY_RING = {
    "preprod": "make.preprod.powerapps.com",
    "prod": "make.powerapps.com",
}


# .env key alias table — mirrors SKILL.md Step 0.
ENV_ALIASES = {
    "ESS_DEVKIT_EMPHUB_CLIENT_ID": [
        "ESS_DEVKIT_EMPHUB_CLIENT_ID",
        "ESS_PROVISION_CLIENT_ID",
        "provision_client_id",
        "ess_devkit_client_id",
    ],
    "WORKDAY_BASE_URL": [
        "WORKDAY_BASE_URL",
        "soap_url",
        "wd_soap_url",
        "wd_base_url",
        "workday_soap_url",
        "workday_base_url",
    ],
    "WORKDAY_TENANT": [
        "WORKDAY_TENANT",
        "tenant",
        "wd_tenant",
        "workday_tenant",
        "workday_tenant_name",
    ],
    "WORKDAY_OAUTH_TOKEN_URL": [
        "WORKDAY_OAUTH_TOKEN_URL",
        "oauth_token_url",
        "wd_oauth_token_url",
        "workday_oauth_token_url",
    ],
    "WORKDAY_OAUTH_CLIENT_ID": [
        "WORKDAY_OAUTH_CLIENT_ID",
        "oauth_client_id",
        "wd_oauth_client_id",
        "workday_client_id",
        "workday_oauth_client_id",
    ],
    "WORKDAY_ENTRA_APP_ID_URI": [
        "WORKDAY_ENTRA_APP_ID_URI",
        "microsoft_entra_resource_url",
        "entra_resource_url",
        "wd_entra_app_id_uri",
        "workday_entra_app_id_uri",
    ],
    "WORKDAY_REST_URL": [
        "WORKDAY_REST_URL",
        "workday_rest_correct_endpoint",
        "rest_base_url",
        "workday_rest_url",
    ],
}


# Allowlist — also used for OData filter injection defense.
VALID_PERSONAS = {"hr", "it"}


_CONNECTOR_SHORT_NAMES = {
    "shared_workdaysoap": "workday",
    "shared_commondataserviceforapps": "dataverse",
    "shared_servicenow": "servicenow",
    "shared_servicenowhrservicedelivery": "servicenowhr",
    "shared_sapsuccessfactors": "successfactors",
}


def load_env_file(env_path):
    """Load a .env file into a dict with normalized keys.

    Keys are lowercased with spaces→underscores so `Workday REST correct Endpoint`
    matches alias `workday_rest_correct_endpoint`. Handles UTF-8 BOM and
    surrounding quotes. Returns {} if file doesn't exist.
    """
    if not os.path.exists(env_path):
        return {}
    env = {}
    with open(env_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip().lower().replace(" ", "_")
            env[normalized_key] = value.strip().strip('"').strip("'")
    return env


def lookup_env(env_map, canonical_key):
    """Resolve a canonical setting by trying its aliases in order.

    The lookup is case-insensitive. Returns None if no alias matches.
    """
    for alias in ENV_ALIASES.get(canonical_key, [canonical_key]):
        v = env_map.get(alias.lower())
        if v:
            return v
    return None


def per_env_host(env_id, ring):
    """Build the per-environment API host.

    Format: `{first 31 chars of dashless GUID}.{remaining}.{ring-suffix}`.
    The 31+1 split is empirically required — MS Learn documents 30+2 but
    Preprod DNS doesn't resolve that form.
    """
    if ring not in HOST_SUFFIX_BY_RING:
        raise ValueError(f"Unknown ring {ring!r}. Use one of: {sorted(HOST_SUFFIX_BY_RING)}")
    no_dashes = env_id.replace("-", "")
    return f"{no_dashes[:31]}.{no_dashes[31:]}.{HOST_SUFFIX_BY_RING[ring]}"


def short_connector_name(connector):
    """Friendly short name for a connector unique name (e.g. shared_workdaysoap -> workday)."""
    if connector in _CONNECTOR_SHORT_NAMES:
        return _CONNECTOR_SHORT_NAMES[connector]
    return connector.replace("shared_", "", 1)


def bot_schema_name_for_persona(persona):
    """Return the canonical ESS bot schema name for the given persona.

    Raises ValueError if `persona` is not in VALID_PERSONAS.
    """
    p = persona.lower()
    if p not in VALID_PERSONAS:
        raise ValueError(f"persona must be one of {sorted(VALID_PERSONAS)}, got {persona!r}")
    return f"msdyn_copilotforemployeeselfservice{p}"


def acquire_device_code_token(client_id, tenant, scope, cache_prefix=None):
    """Acquire an MSAL token via device-code flow with on-disk cache.

    Cache at `.local/.token_cache_{prefix}.bin`, written atomically.
    Tries silent first; falls back to device-code. Exits 1 on failure.
    """
    cache_dir = ".local"
    prefix = cache_prefix or client_id[:8]
    cache_path = os.path.join(cache_dir, f".token_cache_{prefix}.bin")

    cache = msal.SerializableTokenCache()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())
        except Exception as e:
            print(f"WARN: failed to load token cache (will re-prompt): {e}", file=sys.stderr)

    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    # Silent first (uses cached refresh token if available).
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent([scope], account=accounts[0])

    if not result or "access_token" not in result:
        print("Device-code sign-in required...", file=sys.stderr)
        flow = app.initiate_device_flow(scopes=[scope])
        if "user_code" not in flow:
            err = flow.get("error", "unknown")
            desc = flow.get("error_description", "")
            print(f"ERROR: device-flow init failed: {err}: {desc}", file=sys.stderr)
            sys.exit(1)
        print(flow["message"], file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        err = result.get("error", "unknown")
        desc = result.get("error_description", "")
        print(f"ERROR: token acquisition failed: {err}: {desc}", file=sys.stderr)
        sys.exit(1)

    if cache.has_state_changed:
        _atomic_write_cache(cache_dir, cache_path, cache.serialize())

    return result["access_token"]


def acquire_browser_token(client_id, tenant, scope, cache_prefix=None):
    """Acquire an MSAL token via interactive browser flow with on-disk cache.

    Shares cache with acquire_device_code_token. Preferred for UX — one
    click instead of copy-paste-code. Exits 1 on failure.
    """
    cache_dir = ".local"
    prefix = cache_prefix or client_id[:8]
    cache_path = os.path.join(cache_dir, f".token_cache_{prefix}.bin")

    cache = msal.SerializableTokenCache()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())
        except Exception as e:
            print(f"WARN: failed to load token cache (will re-prompt): {e}", file=sys.stderr)

    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    # Silent first (uses cached refresh token if available).
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent([scope], account=accounts[0])

    if not result or "access_token" not in result:
        print("Opening browser for Power Platform sign-in...", file=sys.stderr)
        result = app.acquire_token_interactive(
            [scope], prompt="select_account"
        )

    if "access_token" not in result:
        err = result.get("error", "unknown")
        # Don't echo error_description — may contain tenant IDs (CWE-209).
        print(f"ERROR: browser auth failed: {err}", file=sys.stderr)
        sys.exit(1)

    if cache.has_state_changed:
        _atomic_write_cache(cache_dir, cache_path, cache.serialize())

    return result["access_token"]


def _atomic_write_cache(cache_dir, cache_path, payload):
    """Atomic file write: tempfile + os.replace. Best-effort 0o600 perms."""
    os.makedirs(cache_dir, exist_ok=True)
    try:
        os.chmod(cache_dir, 0o700)
    except OSError:
        pass
    tmp_path = cache_path + ".tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp_path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, cache_path)
        try:
            os.chmod(cache_path, 0o600)
        except OSError:
            pass
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
