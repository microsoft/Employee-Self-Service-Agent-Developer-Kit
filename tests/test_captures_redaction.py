# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the recording-wrapper redaction primitives in tests/captures/_common.py.

These tests don't require network or a real cassette — they exercise the
redaction functions directly with synthetic input. If they pass we have
confidence that real captures will be scrubbed correctly before write.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Make tests/captures importable so we can poke at its internals.
CAPTURES_DIR = Path(__file__).resolve().parent / "captures"
sys.path.insert(0, str(CAPTURES_DIR))

from _common import (  # noqa: E402
    SCRUB_HEADERS,
    _before_record_request,
    _before_record_response,
    _redact_text,
    _scrub_headers,
)


class TestRedactText:
    def test_empty_input_returns_empty(self) -> None:
        assert _redact_text("") == ""
        assert _redact_text(None) is None  # type: ignore[arg-type]

    def test_replaces_real_tenant_guid(self) -> None:
        text = "user_id = 4f24a3e1-9bcd-4f00-aa11-deadbeef0001"
        out = _redact_text(text)
        assert "4f24a3e1-9bcd-4f00-aa11-deadbeef0001" not in out
        assert "00000000-0000-0000-0000-000000001111" in out

    def test_replaces_workday_wid(self) -> None:
        wid = "ab" * 16  # 32 hex chars
        text = f"<wd:ID>{wid}</wd:ID>"
        out = _redact_text(text)
        assert wid not in out
        assert "0" * 32 in out

    def test_replaces_email(self) -> None:
        text = "Contact: alice.smith@contoso.com"
        out = _redact_text(text)
        assert "alice.smith@contoso.com" not in out
        assert "mock.user@contoso.com" in out

    def test_idempotent(self) -> None:
        text = "user 4f24a3e1-9bcd-4f00-aa11-deadbeef0001 wrote alice@example.com"
        once = _redact_text(text)
        twice = _redact_text(once)
        assert once == twice


class TestScrubHeaders:
    def test_strips_authorization(self) -> None:
        out = _scrub_headers({"Authorization": "Bearer abc123"})
        assert out["Authorization"] == "REDACTED"

    def test_strips_cookie(self) -> None:
        out = _scrub_headers({"Cookie": "session=abc"})
        assert out["Cookie"] == "REDACTED"

    def test_case_insensitive(self) -> None:
        out = _scrub_headers({"AUTHORIZATION": "x"})
        assert out["AUTHORIZATION"] == "REDACTED"

    def test_preserves_non_sensitive(self) -> None:
        out = _scrub_headers({"Accept": "application/json"})
        assert out["Accept"] == "application/json"

    def test_handles_list_valued_headers(self) -> None:
        # vcrpy serializes headers as {key: [values]} sometimes.
        out = _scrub_headers({"Set-Cookie": ["s=1", "t=2"]})
        assert out["Set-Cookie"] == ["REDACTED"]

    def test_strips_all_known_sensitive_headers(self) -> None:
        for name in SCRUB_HEADERS:
            out = _scrub_headers({name: "secret"})
            assert out[name] == "REDACTED", f"{name} not scrubbed"


class TestBeforeRecordHooks:
    def test_request_hook_redacts_url(self) -> None:
        class _R:
            uri = "https://orgmocktenant.crm.dynamics.com/api/4f24a3e1-9bcd-4f00-aa11-deadbeef0001"
            headers = {"Authorization": "Bearer x"}
            body = None

        out = _before_record_request(_R())
        assert "4f24a3e1-9bcd-4f00-aa11-deadbeef0001" not in out.uri
        assert out.headers["Authorization"] == "REDACTED"

    def test_request_hook_redacts_string_body(self) -> None:
        class _R:
            uri = "https://example/"
            headers: dict = {}
            body = "user alice@example.com"

        out = _before_record_request(_R())
        assert "alice@example.com" not in out.body

    def test_response_hook_redacts_string_body(self) -> None:
        resp = {
            "headers": {"Authorization": ["x"]},
            "body": {"string": "Hello alice@example.com from tenant abcdef0123456789abcdef0123456789"},
        }
        out = _before_record_response(resp)
        body = out["body"]["string"]
        assert "alice@example.com" not in body
        assert "abcdef0123456789abcdef0123456789" not in body
        assert out["headers"]["Authorization"] == ["REDACTED"]

    def test_response_hook_handles_bytes_body(self) -> None:
        resp = {
            "headers": {},
            "body": {"string": b"<email>bob@example.com</email>"},
        }
        out = _before_record_response(resp)
        # bytes body should be re-encoded after redaction
        assert b"bob@example.com" not in out["body"]["string"]
        assert b"mock.user@contoso.com" in out["body"]["string"]
