# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for shared AgentConfiguration OData and URL helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[3]
CORE_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import _odata  # noqa: E402


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://api.example.test", "https://api.example.test"),
        ("https://api.example.test/v1.1///", "https://api.example.test/v1.1"),
    ],
)
def test_https_base_url_preserves_the_route_and_trims_trailing_slashes(
    url: str, expected: str
) -> None:
    assert _odata._validate_https_base_url(url, "AGENTCONFIG_BASE_URL") == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://api.example.test",
        "https:///v1.1",
        "https://user@api.example.test",
        "https://:password@api.example.test",
        "https://api.example.test/v1.1?tenant=other",
        "https://api.example.test/v1.1#fragment",
    ],
)
def test_https_base_url_rejects_unsafe_components(url: str) -> None:
    with pytest.raises(ValueError, match="AGENTCONFIG_BASE_URL must be an HTTPS URL"):
        _odata._validate_https_base_url(url, "AGENTCONFIG_BASE_URL")


@pytest.mark.parametrize("value", [None, 42, "", " ", " leading", "trailing "])
def test_odata_strings_require_nonempty_trimmed_text(value) -> None:
    with pytest.raises(ValueError, match="titleId must be a non-empty string"):
        _odata._validate_odata_string(value, "titleId")


@pytest.mark.parametrize("control", ["\x00", "\t", "\n", "\r", "\x1f", "\x7f"])
def test_odata_strings_reject_embedded_control_characters(control: str) -> None:
    with pytest.raises(ValueError, match="titleId must not contain control characters"):
        _odata._validate_odata_string(f"before{control}after", "titleId")


@pytest.mark.parametrize(
    "value, literal, key",
    [
        ("agent-123", "agent-123", "agent-123"),
        ("O'Brien", "O''Brien", "O%27%27Brien"),
        ("team / one", "team / one", "team%20%2F%20one"),
        ("a?b#c%&()", "a?b#c%&()", "a%3Fb%23c%25%26%28%29"),
        ("caf\u00e9", "caf\u00e9", "caf%C3%A9"),
    ],
)
def test_odata_literals_and_path_keys_use_context_appropriate_escaping(
    value: str, literal: str, key: str
) -> None:
    assert _odata._validate_odata_string(value, "titleId") == value
    assert _odata._escape_odata_literal(value, "titleId") == literal
    assert _odata._require_odata_id(value, "titleId") == key


@pytest.mark.parametrize(
    "encode", [_odata._escape_odata_literal, _odata._require_odata_id]
)
@pytest.mark.parametrize("value", [" leading", "a\nb"])
def test_odata_encoders_validate_input_before_escaping(encode, value: str) -> None:
    with pytest.raises(ValueError, match="titleId must"):
        encode(value, "titleId")


@pytest.mark.parametrize(
    "etag, idempotency_key, expected",
    [
        (None, None, {}),
        ('W/"3"', None, {"If-Match": 'W/"3"'}),
        (None, "request-123", {"Idempotency-Key": "request-123"}),
        (
            '"3"',
            "request-123",
            {"If-Match": '"3"', "Idempotency-Key": "request-123"},
        ),
    ],
)
def test_mutation_headers_preserve_supplied_wire_values(
    etag: str | None, idempotency_key: str | None, expected: dict[str, str]
) -> None:
    assert _odata._mutation_headers(etag, idempotency_key) == expected


@pytest.mark.parametrize("value", ["", " ", 42])
def test_mutation_headers_reject_invalid_etags(value) -> None:
    with pytest.raises(ValueError, match="etag must be a non-empty string"):
        _odata._mutation_headers(etag=value)


@pytest.mark.parametrize("value", ["", " ", 42])
def test_mutation_headers_reject_invalid_idempotency_keys(value) -> None:
    with pytest.raises(ValueError, match="idempotencyKey must be a non-empty string"):
        _odata._mutation_headers(idempotency_key=value)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (42, None),
        ("3", "3"),
        ('"3"', "3"),
        ('W/"3"', "3"),
        (' w/ "3" ', "3"),
        ('W/"4"', "4"),
    ],
)
def test_etags_normalize_for_version_comparison(value, expected: str | None) -> None:
    assert _odata._normalize_etag(value) == expected


def test_entity_scalar_respects_requested_field_order_case_insensitively() -> None:
    entity = {"ETag": "preferred", "@odata.etag": "fallback"}

    assert _odata._entity_scalar(entity, "etag", "@odata.etag") == "preferred"
    assert _odata._entity_scalar(entity, "@ODATA.ETAG", "etag") == "fallback"


def test_entity_scalar_skips_empty_nonstring_and_missing_fields() -> None:
    entity = {42: "ignored", "ETag": "", "Status": 3, "@odata.etag": '"4"'}

    assert _odata._entity_scalar(
        entity, "missing", "etag", "status", "@odata.etag"
    ) == '"4"'


@pytest.mark.parametrize("entity", [None, [], {}, {"ETag": ""}])
def test_entity_scalar_returns_none_without_a_matching_string(entity) -> None:
    assert _odata._entity_scalar(entity, "etag") is None


def test_query_params_map_supported_options_without_escaping_values() -> None:
    query = {
        "SELECT": "TitleId,Name",
        "expand": "Owner",
        "filter": "Name eq 'O''Brien'",
        "orderby": "Name desc",
        "top": 10,
        "skip": 0,
        "count": True,
        "skiptoken": "page+1/==",
    }

    assert _odata._build_query_params(query) == {
        "$select": "TitleId,Name",
        "$expand": "Owner",
        "$filter": "Name eq 'O''Brien'",
        "$orderby": "Name desc",
        "$top": "10",
        "$skip": "0",
        "$count": "true",
        "$skiptoken": "page+1/==",
    }
    assert query["count"] is True
    assert query["skip"] == 0


def test_query_params_preserve_false_and_omit_none() -> None:
    assert _odata._build_query_params({"count": False, "top": None}) == {
        "$count": "false"
    }


@pytest.mark.parametrize("query", [None, {}])
def test_query_params_allow_an_absent_query(query) -> None:
    assert _odata._build_query_params(query) == {}


@pytest.mark.parametrize("query", [[], "top=10"])
def test_query_params_reject_nonobject_queries(query) -> None:
    with pytest.raises(ValueError, match="query must be an object of OData options"):
        _odata._build_query_params(query)


def test_query_params_reject_unknown_options() -> None:
    with pytest.raises(ValueError, match="Unsupported query option: search"):
        _odata._build_query_params({"search": "agent"})
