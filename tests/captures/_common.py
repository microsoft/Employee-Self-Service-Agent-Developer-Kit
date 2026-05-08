# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Shared helpers for VCR.py recording wrappers.

Every record_*.py script in this directory uses build_cassette() to get a
pre-configured VCR instance that:

* Strips Authorization, Cookie, Set-Cookie, and ocp-apim-subscription-key
  headers from every recorded request and response.
* Replaces tenant-identifying values (GUIDs, org URL fragment, real names,
  real emails, employee/worker IDs, ISU usernames) in URLs and response
  bodies BEFORE the cassette is written to disk.
* Writes to tests/fixtures/cassettes/{name}.yaml.

The redaction substitutions are read from REDACT_TABLE below. The values on
the left should be **the real values your tenant emits** — edit this file
once per machine to add anything tenant-specific that's not on the default
list.

If a captured cassette still has unredacted PII after this pass, the
fallback is tests/captures/_redact.py which can be run on an existing
cassette file to apply additional substitutions.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Make the production source importable without a package install.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills" / "scripts"
MCP_WORKDAY = REPO_ROOT / "solutions" / "ess-maker-skills" / "src" / "mcp" / "workday"
MCP_SERVICENOW = REPO_ROOT / "solutions" / "ess-maker-skills" / "src" / "mcp" / "servicenow"

for p in (SCRIPTS_ROOT, MCP_WORKDAY, MCP_SERVICENOW):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


CASSETTE_DIR = REPO_ROOT / "tests" / "fixtures" / "cassettes"
RAW_CASSETTE_DIR = CASSETTE_DIR / ".raw"


# ────────────────────────────────────────────────────────────────────────
# Redaction table
#
# These strings get find-and-replaced in URLs, request bodies, response
# bodies, and any other text VCR captures. The mapping is intentionally
# conservative: it only redacts values that are clearly identifying.
#
# To add a tenant-specific value (e.g. your own org URL fragment, your test
# tenant GUID), edit this table on your local machine before running a
# recording wrapper. Don't commit tenant-specific entries here.
# ────────────────────────────────────────────────────────────────────────

REDACT_TABLE: dict[str, str] = {
    # Tokens that may end up in bodies (response error_descriptions sometimes
    # echo bearer tokens back).
    "Bearer ": "Bearer ",  # placeholder; bearer tokens are stripped via header filtering
    # Real org URL fragment (read from .local/config.json at runtime, see
    # _read_real_dataverse_url below). The placeholder here is a sentinel
    # — runtime substitution overwrites it with the real value.
    "__REAL_ORG_FRAGMENT__": "orgmocktenant",
}


# Regex-based substitutions for things that have a stable shape but vary
# per record (employee IDs, worker IDs, tenant GUIDs we don't know in
# advance). Applied AFTER the literal REDACT_TABLE.
REDACT_REGEX: list[tuple[re.Pattern[str], str]] = [
    # Microsoft tenant / object GUIDs in URL paths and bodies.
    # Replaces every GUID with a stable fake. This is aggressive — if you
    # need to keep specific GUIDs for a test, exempt them by editing the
    # cassette by hand after recording.
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "00000000-0000-0000-0000-000000001111",
    ),
    # Workday WIDs: 32-char hex, sometimes prefixed by "WID="
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "0" * 32),
    # Email addresses → mock.user@contoso.com
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "mock.user@contoso.com",
    ),
]


# Headers that get stripped completely (replaced with REDACTED).
SCRUB_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-ms-aadtoken",
    "ocp-apim-subscription-key",
    "x-ms-correlation-id",   # tenant-correlated trace id
    "x-ms-client-request-id",
    "x-ms-request-id",
    "x-ms-routing-request-id",
}


def _read_real_dataverse_url() -> str | None:
    """Pull the real org URL fragment out of .local/config.json so the
    redactor knows what string to substitute. Returns the fragment (e.g.
    "orgb78b4a3b") or None if the kit isn't set up."""
    config_path = REPO_ROOT / "solutions" / "ess-maker-skills" / ".local" / "config.json"
    if not config_path.exists():
        return None
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    endpoint = cfg.get("dataverseEndpoint", "")
    # Extract the leftmost subdomain label — "https://orgb78b4a3b.crm.dynamics.com" → "orgb78b4a3b"
    m = re.match(r"https?://([^.]+)\.", endpoint)
    return m.group(1) if m else None


def _redact_text(text: str) -> str:
    """Apply REDACT_TABLE + REDACT_REGEX to a string."""
    if not text:
        return text
    real_org = _read_real_dataverse_url()
    if real_org and real_org != "orgmocktenant":
        text = text.replace(real_org, "orgmocktenant")
    for src, dst in REDACT_TABLE.items():
        if src.startswith("__"):  # skip sentinels
            continue
        if src and src != dst:
            text = text.replace(src, dst)
    for pat, dst in REDACT_REGEX:
        text = pat.sub(dst, text)
    return text


def _scrub_headers(headers: dict[str, list[str] | str]) -> dict[str, list[str] | str]:
    """Replace sensitive header values with REDACTED."""
    cleaned: dict[str, list[str] | str] = {}
    for k, v in headers.items():
        if k.lower() in SCRUB_HEADERS:
            cleaned[k] = ["REDACTED"] if isinstance(v, list) else "REDACTED"
        else:
            cleaned[k] = v
    return cleaned


def _before_record_request(request: Any) -> Any:
    """vcrpy hook: scrub headers + redact URL + redact request body."""
    request.headers = _scrub_headers(dict(request.headers))
    request.uri = _redact_text(request.uri)
    if getattr(request, "body", None):
        body = request.body
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8")
                request.body = _redact_text(body).encode("utf-8")
            except UnicodeDecodeError:
                pass  # leave binary bodies alone
        elif isinstance(body, str):
            request.body = _redact_text(body)
    return request


def _before_record_response(response: dict[str, Any]) -> dict[str, Any]:
    """vcrpy hook: scrub headers + redact response body."""
    if "headers" in response:
        response["headers"] = _scrub_headers(response["headers"])
    body = response.get("body", {})
    if isinstance(body, dict) and "string" in body:
        raw = body["string"]
        if isinstance(raw, bytes):
            try:
                decoded = raw.decode("utf-8")
                body["string"] = _redact_text(decoded).encode("utf-8")
            except UnicodeDecodeError:
                pass
        elif isinstance(raw, str):
            body["string"] = _redact_text(raw)
    return response


def build_cassette(name: str) -> Any:
    """
    Return a vcrpy.VCR instance configured with our standard redaction +
    cassette path conventions. Use as:

        vcr = build_cassette("dataverse_whoami")
        with vcr.use_cassette():
            # call production code that issues HTTP requests
            ...

    Cassettes write to tests/fixtures/cassettes/{name}.yaml.
    """
    try:
        import vcr
    except ImportError:
        print("ERROR: vcrpy not installed. Run: pip install -r requirements-dev.txt")
        sys.exit(1)

    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    cassette_path = CASSETTE_DIR / f"{name}.yaml"

    return vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        path_transformer=vcr.VCR.ensure_suffix(".yaml"),
        record_mode="new_episodes",
        match_on=("method", "scheme", "host", "port", "path", "query"),
        filter_headers=list(SCRUB_HEADERS),
        before_record_request=_before_record_request,
        before_record_response=_before_record_response,
        decode_compressed_response=True,
    ).use_cassette(str(cassette_path))


def announce(scenario: str) -> None:
    """Standard preamble printed by every record_*.py wrapper."""
    print(f"=== Recording cassette: {scenario} ===")
    print(f"Output: tests/fixtures/cassettes/{scenario}.yaml")
    print()
    print("This script will make REAL network calls to your tenant.")
    print("Authentication uses your existing .local/.token_cache.bin.")
    print("Headers + tokens + tenant GUIDs are scrubbed BEFORE write.")
    print()
    print("After recording, review the cassette by hand for any leftover")
    print("tenant-specific data (real names, real ticket numbers, etc.) and")
    print("commit it to tests/fixtures/cassettes/.")
    print()


def confirm_or_exit() -> None:
    """Prompt the operator to confirm before hitting the network."""
    if os.environ.get("ESS_RECORD_NO_CONFIRM") == "1":
        return
    answer = input("Proceed with recording? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)
