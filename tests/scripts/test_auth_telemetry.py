# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import adk_telemetry
import pytest
from auth_telemetry import observe_auth, record_auth_result


@pytest.mark.parametrize(
    "error,outcome,category",
    [
        ("invalid_client", "failure", "authentication"),
        ("consent_required", "failure", "consent"),
        ("access_denied", "failure", "permissions"),
        ("user_cancelled", "cancelled", "unknown"),
        ("timeout", "timeout", "unknown"),
        ("private customer error", "failure", "unknown"),
    ],
)
def test_failed_sign_in_is_one_bounded_terminal_event(
    monkeypatch, error, outcome, category
):
    events = []
    monkeypatch.setattr(
        adk_telemetry, "emit_auth_attempt", lambda **kw: events.append(kw)
    )

    @observe_auth("agentbuilder")
    def authenticate():
        record_auth_result(
            {"error": error, "error_description": "secret token and username"},
            "interactive",
        )
        raise SystemExit(1)

    with pytest.raises(SystemExit):
        authenticate()
    assert len(events) == 1
    assert events[0]["outcome"] == outcome
    assert events[0]["error_category"] == category
    assert "secret" not in str(events)


def test_silent_miss_then_success_is_not_two_attempts(monkeypatch):
    events = []
    monkeypatch.setattr(
        adk_telemetry, "emit_auth_attempt", lambda **kw: events.append(kw)
    )

    @observe_auth("dataverse")
    def authenticate():
        record_auth_result(None, "silent")
        record_auth_result(
            {"access_token": "must not emit", "id_token_claims": {"tid": "tenant"}},
            "interactive",
        )
        return "must not emit"

    assert authenticate() == "must not emit"
    assert len(events) == 1
    assert events[0]["outcome"] == "success"
    assert events[0]["method"] == "interactive"
    assert events[0]["error_category"] == ""
    assert "must not emit" not in str(events)


@pytest.mark.parametrize(
    "failure,outcome", [(KeyboardInterrupt, "cancelled"), (TimeoutError, "timeout")]
)
def test_interrupts_and_timeout_preserve_the_original_exception(
    monkeypatch, failure, outcome
):
    events = []
    monkeypatch.setattr(
        adk_telemetry, "emit_auth_attempt", lambda **kw: events.append(kw)
    )
    error = failure("private details")

    @observe_auth("flow")
    def authenticate():
        record_auth_result(None, "interactive")
        raise error

    with pytest.raises(failure) as raised:
        authenticate()
    assert raised.value is error
    assert events[0]["outcome"] == outcome


def test_telemetry_failure_does_not_change_success_or_failure(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("collector unavailable")

    monkeypatch.setattr(adk_telemetry, "emit_auth_attempt", broken)

    @observe_auth("agentbuilder")
    def successful():
        return ("token", "account")

    assert successful() == ("token", "account")
