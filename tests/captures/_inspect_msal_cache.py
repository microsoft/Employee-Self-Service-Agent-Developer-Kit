"""One-shot helper: print the MSAL accounts cached at the kit's standard
token-cache location. Used to identify which account a recording session
will use BEFORE re-running a recorder, so you can decide whether to wipe
the cache and switch accounts.

Run from the kit root:
    python tests\\captures\\_inspect_msal_cache.py

Reads:  solutions/ess-maker-skills/.local/.token_cache.bin
Writes: nothing — read-only inspection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import msal

CACHE_PATH = Path("solutions/ess-maker-skills/.local/.token_cache.bin")


def main() -> int:
    if not CACHE_PATH.exists():
        print(f"NO CACHE at {CACHE_PATH}")
        print("Either you've never authenticated yet, or you're running from")
        print("a directory that isn't the kit root.")
        return 1

    cache = msal.SerializableTokenCache()
    cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
    # Client ID doesn't matter for inspecting accounts; MSAL just needs ANY
    # PublicClientApplication to expose its cached accounts. Use the
    # well-known Azure CLI client.
    app = msal.PublicClientApplication(
        "04b07795-8ddb-461a-bbee-02f9e1bf7b46",
        token_cache=cache,
    )
    accounts = app.get_accounts()
    if not accounts:
        print(f"Cache exists at {CACHE_PATH} but contains no accounts.")
        return 1
    print(f"MSAL cache: {CACHE_PATH}")
    print(f"Cached accounts ({len(accounts)}):")
    for i, a in enumerate(accounts):
        marker = ">>" if i == 0 else "  "
        print(f"  {marker} [{i}] username:        {a.get('username')}")
        print(f"        home_account_id: {a.get('home_account_id')}")
        print(f"        environment:     {a.get('environment')}")
        print(f"        local_account_id:{a.get('local_account_id')}")
        print()
    print("The first account (>>) is the one MSAL will use silently.")
    print("To switch: delete the cache file and re-run the recorder; the")
    print("account picker will appear on next sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
