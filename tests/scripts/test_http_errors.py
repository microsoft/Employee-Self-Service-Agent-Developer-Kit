# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/http_errors.py.

http_errors.py is pure logic that translates a ``requests.Response`` into a
``requests.HTTPError`` subclass (``APIError``) with a friendly message, a
troubleshooting tip, and structured fields for terminal display. These tests
exercise:

* per-status-code messages and tips (400/401/403/404/429/5xx/unknown)
* the entity-set-name → friendly-label mapping (and the unmapped fallback)
* ``format_for_terminal`` output structure (ERROR / Tip / Detail / Request ID)
* the ``response.request.method`` source for the HTTP verb in Detail
* backward compatibility with ``except HTTPError``
* ``raise_api_error`` no-op on 2xx and raise on 4xx/5xx
* ``AuthExpiredError`` is catchable as ``APIError`` (PR #135 review fix)
  and round-trips through ``format_for_terminal`` when given a response

The module never makes HTTP calls itself — it inspects a response object
passed in by auth.py — so tests build small fake response objects rather
than relying on the ``responses`` library.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from http_errors import (
    APIError,
    _ENTITY_DISPLAY_NAMES,
    _friendly_name,
    raise_api_error,
)


# ---------------------------------------------------------------------------
# Fake response helpers
# ---------------------------------------------------------------------------
#
# APIError reads exactly four things off the response: ``status_code``,
# ``request.url``, ``request.method``, and ``headers.get("x-ms-request-id")``.
# A lightweight SimpleNamespace keeps tests honest — a loose MagicMock would
# make every nested attribute truthy and silently change format_for_terminal
# output.


def _fake_response(
    status_code: int,
    *,
    method: str = "GET",
    url: str = "https://orgmock.crm.dynamics.com/api/data/v9.2/bots",
    request_id: str | None = None,
):
    headers = {}
    if request_id:
        headers["x-ms-request-id"] = request_id
    request = SimpleNamespace(method=method, url=url)
    return SimpleNamespace(
        status_code=status_code,
        request=request,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Friendly name mapping
# ---------------------------------------------------------------------------


class TestFriendlyName:
    def test_maps_known_entity_sets(self) -> None:
        assert _friendly_name("bots") == "agents"
        assert _friendly_name("botcomponents") == "agent components"
        assert _friendly_name("workflows") == "cloud flows"

    def test_falls_back_to_raw_name_when_unknown(self) -> None:
        # Unmapped entity sets stay verbatim — better to leak a Dataverse-y
        # name than to pretend we know what it is.
        assert _friendly_name("solutions") == "solutions"

    def test_returns_generic_placeholder_when_missing(self) -> None:
        assert _friendly_name(None) == "this resource"
        assert _friendly_name("") == "this resource"

    def test_mapping_covers_entity_sets_used_in_auth_py(self) -> None:
        # Pin the contract: these are the entity sets auth.py passes today.
        # Adding a new caller without extending the map is fine — the
        # fallback shows the raw name — but removing one of these should be
        # an intentional choice, not an accident.
        for name in ("bots", "botcomponents", "workflows",
                     "msdyn_employeeselfservicetemplateconfigs"):
            assert name in _ENTITY_DISPLAY_NAMES


# ---------------------------------------------------------------------------
# APIError message + tip per status code
# ---------------------------------------------------------------------------


class TestApiErrorMessages:
    def test_400_message_and_tip(self) -> None:
        err = APIError(_fake_response(400), resource_name="bots",
                       operation="read")
        assert err.status_code == 400
        assert "Bad request" in err._friendly_message
        assert "agents" in err._friendly_message  # entity name translated
        assert "version" in err._tip.lower()

    def test_401_message_includes_http_401(self) -> None:
        # test_preferred_solution.py asserts ``"401" in r.result`` where
        # r.result is ``str(AuthExpiredError)``. Pin that "401" stays in
        # the friendly message so the assertion keeps holding.
        err = APIError(_fake_response(401))
        assert "401" in err._friendly_message
        assert "expired" in err._friendly_message.lower()
        assert "sign in" in err._tip.lower()

    def test_403_message_includes_operation_and_friendly_name(self) -> None:
        err = APIError(
            _fake_response(403),
            resource_name="botcomponents",
            operation="update",
        )
        assert "permission" in err._friendly_message.lower()
        assert "update" in err._friendly_message
        assert "agent components" in err._friendly_message

    def test_403_tip_mentions_custom_required_role(self) -> None:
        err = APIError(
            _fake_response(403),
            resource_name="bots",
            operation="create",
            required_role="Bot Author",
        )
        assert "Bot Author" in err._tip

    def test_403_tip_defaults_when_no_role_supplied(self) -> None:
        err = APIError(_fake_response(403), resource_name="bots",
                       operation="read")
        assert "System Administrator" in err._tip

    def test_404_message_suggests_missing_solution(self) -> None:
        err = APIError(
            _fake_response(404),
            resource_name="msdyn_employeeselfservicetemplateconfigs",
            operation="read",
        )
        assert "Could not find" in err._friendly_message
        assert "ESS template configurations" in err._friendly_message
        assert "solution" in err._tip.lower()

    def test_429_message_and_tip(self) -> None:
        err = APIError(_fake_response(429))
        assert "Too many requests" in err._friendly_message
        assert "Wait" in err._tip

    @pytest.mark.parametrize("code", [500, 502, 503, 504])
    def test_5xx_messages_are_transient(self, code: int) -> None:
        err = APIError(_fake_response(code), resource_name="bots",
                       operation="read")
        assert str(code) in err._friendly_message
        assert "temporary" in err._friendly_message.lower()
        assert "again" in err._tip.lower()

    def test_unknown_status_falls_back_to_generic_message(self) -> None:
        # 418 isn't in the mapping. The message should still be sensible:
        # it includes the operation and the friendly name, and the tip
        # tells the user to look at the technical detail.
        err = APIError(_fake_response(418), resource_name="bots",
                       operation="read")
        assert "418" in err._friendly_message
        assert "agents" in err._friendly_message
        assert err._tip  # non-empty fallback

    def test_caller_provided_message_and_tip_win(self) -> None:
        err = APIError(
            _fake_response(403),
            resource_name="bots",
            operation="read",
            message="custom message",
            tip="custom tip",
        )
        assert err._friendly_message == "custom message"
        assert err._tip == "custom tip"


# ---------------------------------------------------------------------------
# format_for_terminal
# ---------------------------------------------------------------------------


class TestFormatForTerminal:
    def test_includes_error_tip_detail_and_request_id_lines(self) -> None:
        err = APIError(
            _fake_response(
                403,
                method="PATCH",
                url="https://orgmock.crm.dynamics.com/api/data/v9.2/bots(123)",
                request_id="req-abc-123",
            ),
            resource_name="bots",
            operation="update",
        )
        out = err.format_for_terminal()
        assert "ERROR:" in out
        assert "Tip:" in out
        assert "Detail: HTTP 403" in out
        assert "PATCH" in out                  # method from response.request
        assert "Request ID: req-abc-123" in out

    def test_detail_uses_request_method_not_operation(self) -> None:
        # The whole point of PR #135 review comment #3 — don't reverse-
        # engineer the verb from the operation string. ``operation="read"``
        # combined with ``method="POST"`` (e.g. an OData $batch read) must
        # display POST in the Detail line.
        err = APIError(
            _fake_response(429, method="POST"),
            resource_name="bots",
            operation="read",
        )
        assert "POST" in err.format_for_terminal()

    def test_method_is_uppercased(self) -> None:
        err = APIError(
            _fake_response(500, method="get"),
            resource_name="bots",
            operation="read",
        )
        assert "HTTP 500 — GET" in err.format_for_terminal()

    def test_detail_strips_url_query_string(self) -> None:
        # Query strings can hold $filter values that include user-typed
        # text. Strip them from terminal output so we don't echo sensitive
        # input back into the terminal scrollback.
        err = APIError(
            _fake_response(
                404,
                url=("https://orgmock.crm.dynamics.com/api/data/v9.2/bots"
                     "?$filter=name eq 'secret'&$select=name"),
            ),
            resource_name="bots",
            operation="read",
        )
        out = err.format_for_terminal()
        assert "bots" in out
        assert "secret" not in out
        assert "$filter" not in out

    def test_omits_detail_line_when_no_response(self) -> None:
        # AuthExpiredError() with no response shouldn't render a
        # ``Detail: HTTP 401 — GET None`` line.
        err = APIError(response=None, status_code=401)
        out = err.format_for_terminal()
        assert "ERROR:" in out
        assert "Detail:" not in out
        assert "Request ID:" not in out

    def test_omits_request_id_line_when_header_missing(self) -> None:
        err = APIError(_fake_response(500))
        assert "Request ID" not in err.format_for_terminal()


# ---------------------------------------------------------------------------
# raise_api_error
# ---------------------------------------------------------------------------


class TestRaiseApiError:
    @pytest.mark.parametrize("code", [200, 201, 204, 304])
    def test_no_raise_on_2xx_or_3xx(self, code: int) -> None:
        # raise_api_error is gated on status_code >= 400 — anything below
        # that is the caller's responsibility (it's a Dataverse choice
        # whether 304 means "use cached" or "this is fine").
        raise_api_error(
            _fake_response(code),
            resource_name="bots",
            operation="read",
        )

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 503])
    def test_raises_apierror_on_4xx_5xx(self, code: int) -> None:
        with pytest.raises(APIError) as excinfo:
            raise_api_error(
                _fake_response(code),
                resource_name="bots",
                operation="read",
            )
        assert excinfo.value.status_code == code

    def test_raised_apierror_is_also_an_http_error(self) -> None:
        # Backward compat: existing ``except requests.HTTPError`` handlers
        # in callers we haven't migrated yet must still catch this.
        with pytest.raises(requests.HTTPError):
            raise_api_error(
                _fake_response(500),
                resource_name="bots",
                operation="read",
            )

    def test_passes_resource_name_and_operation_through(self) -> None:
        with pytest.raises(APIError) as excinfo:
            raise_api_error(
                _fake_response(403),
                resource_name="workflows",
                operation="delete",
                required_role="Custom Role",
            )
        err = excinfo.value
        assert err.resource_name == "workflows"
        assert err.operation == "delete"
        assert "cloud flows" in err._friendly_message
        assert "Custom Role" in err._tip


# ---------------------------------------------------------------------------
# AuthExpiredError ↔ APIError subclassing (PR #135 review comment #1)
# ---------------------------------------------------------------------------


class TestAuthExpiredErrorSubclassing:
    """Regression tests for PR #135 review comment 1: 401s used to escape
    the friendly handler because callers only caught APIError. Now
    AuthExpiredError inherits from APIError, so ``except APIError`` in
    discover.py / fetch_and_setup.py picks up 401s too while
    ``except AuthExpiredError`` in push.py / FlightCheck still works.
    """

    def test_is_catchable_as_apierror(self) -> None:
        # The fix that closes the reviewer's loop.
        from auth import AuthExpiredError
        with pytest.raises(APIError):
            raise AuthExpiredError()

    def test_is_catchable_as_authexpirederror(self) -> None:
        # push.py and FlightCheck do ``except AuthExpiredError`` for re-
        # auth-and-retry. That contract must still hold.
        from auth import AuthExpiredError
        with pytest.raises(AuthExpiredError):
            raise AuthExpiredError()

    def test_default_message_includes_http_401(self) -> None:
        # test_preferred_solution.py:369 asserts ``"401" in r.result``.
        from auth import AuthExpiredError
        err = AuthExpiredError()
        assert "401" in str(err)
        assert err.status_code == 401

    def test_legacy_string_message_argument_is_preserved(self) -> None:
        # FlightCheck test_licensing.py constructs
        # ``AuthExpiredError("401")`` directly. That positional-message
        # signature must keep working — the supplied text must appear in
        # the str output (APIError still appends its tip line, which is
        # fine since neither existing test asserts an exact string).
        from auth import AuthExpiredError
        err = AuthExpiredError("custom 401 message")
        assert "custom 401 message" in str(err)
        assert err.status_code == 401

    def test_round_trips_response_diagnostics_through_format(self) -> None:
        # When auth.py raises ``AuthExpiredError(response=resp)`` (the
        # common path now), format_for_terminal should include the HTTP
        # method and URL just like other APIErrors do.
        from auth import AuthExpiredError
        resp = _fake_response(
            401,
            method="PATCH",
            url="https://orgmock.crm.dynamics.com/api/data/v9.2/bots(123)",
            request_id="req-xyz-789",
        )
        err = AuthExpiredError(response=resp)
        out = err.format_for_terminal()
        assert "HTTP 401" in out
        assert "PATCH" in out
        assert "bots(123)" in out
        assert "Request ID: req-xyz-789" in out
