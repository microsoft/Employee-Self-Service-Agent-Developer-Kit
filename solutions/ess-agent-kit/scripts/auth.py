# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit - Shared Dataverse Authentication

Provides MSAL-based interactive browser auth with token caching and
Dataverse REST API helpers. Used by fetch_and_setup.py and push.py.
"""

import json
import os
import re
import sys

try:
    import msal
except ImportError:
    print("ERROR: 'msal' package not found. Run: pip install msal")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)


# Well-known first-party client ID for Power Platform / Dynamics tools.
CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

HEADERS_BASE = {
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Prefer": "odata.include-annotations=*",
}


def discover_tenant(env_url):
    """Discover the tenant ID from the environment's auth challenge."""
    resp = requests.get(
        f"{env_url}/api/data/v9.2/",
        headers={"Accept": "application/json"},
        allow_redirects=False,
        timeout=10,
    )
    auth_header = resp.headers.get("WWW-Authenticate", "")
    match = re.search(r"login\.microsoftonline\.com/([^/]+)", auth_header)
    if match:
        return match.group(1)
    return "organizations"


def authenticate(env_url):
    """Get a Dataverse access token via MSAL interactive browser auth.

    Uses a token cache so repeat runs within the same session don't re-prompt.
    Discovers the correct tenant from the environment automatically.
    """
    tenant = discover_tenant(env_url)
    authority = f"https://login.microsoftonline.com/{tenant}"
    scope = f"{env_url}/user_impersonation"
    cache = msal.SerializableTokenCache()
    cache_path = os.path.join("my", ".token_cache.bin")

    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            cache.deserialize(f.read())

    app = msal.PublicClientApplication(
        CLIENT_ID, authority=authority, token_cache=cache
    )

    # Try silent first (cached token from previous run)
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent([scope], account=accounts[0])

    if not result or "access_token" not in result:
        print(f"Opening browser for sign-in (tenant: {tenant})...")
        print("Please select the account that has access to this environment.")
        result = app.acquire_token_interactive(
            [scope], prompt="select_account"
        )

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown"))
        print(f"ERROR: Authentication failed: {error}")
        sys.exit(1)

    # Persist cache
    if cache.has_state_changed:
        os.makedirs("my", exist_ok=True)
        with open(cache_path, "w") as f:
            f.write(cache.serialize())

    return result["access_token"]


def query_all(env_url, token, entity_set, select, filter_expr=None):
    """Query a Dataverse table with automatic @odata.nextLink pagination.

    Returns all records across all pages.
    """
    headers = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    url = f"{env_url}/api/data/v9.2/{entity_set}?$select={select}"
    if filter_expr:
        url += f"&$filter={filter_expr}"

    all_records = []
    page = 0
    while url:
        page += 1
        resp = requests.get(url, headers=headers, timeout=120)
        if resp.status_code == 401:
            print("ERROR: Authentication expired or invalid. Run again.")
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json()
        records = data.get("value", [])
        all_records.extend(records)
        url = data.get("@odata.nextLink")
        if page == 1:
            print(f"  Page {page}: {len(records)} records", end="")
        elif records:
            print(f" → Page {page}: {len(records)}", end="")

    print(f" → Total: {len(all_records)}")
    return all_records


def update_record(env_url, token, entity_set, record_id, data):
    """Update a single Dataverse record via PATCH."""
    headers = {
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{env_url}/api/data/v9.2/{entity_set}({record_id})"
    resp = requests.patch(url, headers=headers, json=data, timeout=60)
    if resp.status_code == 401:
        print("ERROR: Authentication expired or invalid. Run again.")
        sys.exit(1)
    resp.raise_for_status()
    return True


def create_record(env_url, token, entity_set, data):
    """Create a new Dataverse record via POST. Returns the new record ID."""
    headers = {
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{env_url}/api/data/v9.2/{entity_set}"
    resp = requests.post(url, headers=headers, json=data, timeout=60)
    if resp.status_code == 401:
        print("ERROR: Authentication expired or invalid. Run again.")
        sys.exit(1)
    resp.raise_for_status()
    result = resp.json()
    return result.get("botcomponentid", result.get("id"))


def delete_record(env_url, token, entity_set, record_id):
    """Delete a single Dataverse record."""
    headers = {
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
    }
    url = f"{env_url}/api/data/v9.2/{entity_set}({record_id})"
    resp = requests.delete(url, headers=headers, timeout=60)
    if resp.status_code == 401:
        print("ERROR: Authentication expired or invalid. Run again.")
        sys.exit(1)
    resp.raise_for_status()
    return True


def load_config():
    """Load my/config.json. Returns the parsed dict or exits on error."""
    config_path = os.path.join("my", "config.json")
    if not os.path.exists(config_path):
        print("ERROR: my/config.json not found. Run /setup first.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
