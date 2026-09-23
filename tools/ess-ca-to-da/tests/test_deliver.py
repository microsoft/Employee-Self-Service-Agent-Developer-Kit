"""Tests for the target Declarative Agent import — the tool's one write path."""

from __future__ import annotations

import httpx
import pytest

from essmig.deliver import (
    DEFAULT_API_BASE,
    DeliveryError,
    ImportTarget,
    import_package,
)

_TENANT = "11111111-1111-1111-1111-111111111111"
_ENV = "22222222-2222-2222-2222-222222222222"
_SCHEMA = "gptagent_copilotforemployeeselfservicehr"


class _StaticToken:
    def __init__(self, token: str = "token-abc") -> None:
        self._token = token

    def get_token(self, scopes: object = None) -> str:
        return self._token


class _FailingToken:
    def get_token(self, scopes: object = None) -> str:
        raise RuntimeError("no account")


def _target(**overrides: str) -> ImportTarget:
    values = {"tenant_id": _TENANT, "environment_id": _ENV, "schema_name": _SCHEMA}
    values.update(overrides)
    return ImportTarget(**values)  # type: ignore[arg-type]


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_endpoint_is_built_from_the_documented_path() -> None:
    target = _target()
    assert target.endpoint == (
        f"{DEFAULT_API_BASE}/copilotstudio/tenants/{_TENANT}"
        f"/environments/{_ENV}/minimalBots/alm/import"
    )


def test_api_base_is_overridable_without_a_trailing_slash_problem() -> None:
    target = _target(api_base="https://example.crm.dynamics.com/")
    assert target.endpoint.startswith("https://example.crm.dynamics.com/copilotstudio/")
    assert "//copilotstudio" not in target.endpoint.replace("https://", "")


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": "not-a-guid"},
        {"environment_id": "nope"},
        {"schema_name": ""},
        {"api_base": "http://insecure.example.com"},
    ],
)
def test_a_malformed_target_is_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(DeliveryError):
        _target(**overrides)


def test_a_successful_import_sends_the_zip_and_the_schema_name() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["schema"] = request.url.params.get("schemaName")
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.content
        return httpx.Response(200)

    result = import_package(
        _target(), b"PK-zip-bytes", _StaticToken(), client=_client(httpx.MockTransport(handler))
    )

    assert result.ok
    assert result.status == 200
    assert seen["schema"] == _SCHEMA
    assert seen["auth"] == "Bearer token-abc"
    assert seen["body"] == b"PK-zip-bytes"
    assert "minimalBots/alm/import" in str(seen["url"])


def test_an_async_accept_captures_the_operation_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, headers={"Location": "https://track.example/op/1"})

    result = import_package(
        _target(), b"zip", _StaticToken(), client=_client(httpx.MockTransport(handler))
    )

    assert result.ok
    assert result.operation_url == "https://track.example/op/1"


def test_a_rejected_import_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"message": "agent already exists"}})

    result = import_package(
        _target(), b"zip", _StaticToken(), client=_client(httpx.MockTransport(handler))
    )

    assert not result.ok
    assert result.status == 409
    assert "already exists" in result.detail


def test_a_transport_failure_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    result = import_package(
        _target(), b"zip", _StaticToken(), client=_client(httpx.MockTransport(handler))
    )

    assert not result.ok
    assert result.status is None
    assert "failed" in result.detail


def test_a_token_failure_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not reached
        return httpx.Response(200)

    result = import_package(
        _target(), b"zip", _FailingToken(), client=_client(httpx.MockTransport(handler))
    )

    assert not result.ok
    assert "token" in result.detail


def _empty_inputs() -> tuple[object, object]:
    from essmig.discovery import DiscoveryResult
    from essmig.merge import MergeResult

    discovery = DiscoveryResult(
        vertical="hr",
        solution_unique_name="msdyn_CopilotForEmployeeSelfServiceHR",
        solution_id="",
        components={},
        skipped=[],
    )
    merged = MergeResult(vertical="hr", agent={"entity": {"schemaName": _SCHEMA}}, results=[])
    return discovery, merged


def test_a_successful_delivery_shows_in_the_report() -> None:
    from essmig.deliver import ImportResult
    from essmig.report import render_json, render_markdown

    discovery, merged = _empty_inputs()
    result = ImportResult(ok=True, endpoint="https://x/import", schema_name=_SCHEMA, status=200)

    markdown = render_markdown(discovery, merged, None, result)  # type: ignore[arg-type]
    assert "## Delivery to the target Declarative Agent" in markdown
    assert "development" in markdown

    payload = render_json(discovery, merged, result)  # type: ignore[arg-type]
    assert payload["delivery"]["ok"] is True


def test_a_failed_delivery_is_reported_and_does_not_claim_success() -> None:
    from essmig.deliver import ImportResult
    from essmig.report import render_markdown

    discovery, merged = _empty_inputs()
    result = ImportResult(
        ok=False, endpoint="https://x/import", schema_name=_SCHEMA, status=409, detail="exists"
    )

    markdown = render_markdown(discovery, merged, None, result)  # type: ignore[arg-type]
    assert "**failed**" in markdown
    assert "was not changed" in markdown


def test_no_delivery_argument_keeps_the_report_unchanged() -> None:
    from essmig.report import render_json, render_markdown

    discovery, merged = _empty_inputs()
    markdown = render_markdown(discovery, merged, None)  # type: ignore[arg-type]
    assert "## Delivery to the target Declarative Agent" not in markdown
    assert render_json(discovery, merged)["delivery"] is None  # type: ignore[arg-type]

