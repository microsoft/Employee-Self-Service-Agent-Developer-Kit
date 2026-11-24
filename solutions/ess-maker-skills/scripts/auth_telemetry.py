# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded, fail-open outcomes for shared Setup/Connect authentication paths."""

from __future__ import annotations

import time
from contextvars import ContextVar
from functools import wraps

_ATTEMPT: ContextVar[dict | None] = ContextVar("adk_auth_attempt", default=None)
_ERROR_CATEGORIES = {
    "invalid_grant": "authentication",
    "invalid_client": "authentication",
    "interaction_required": "authentication",
    "login_required": "authentication",
    "consent_required": "consent",
    "access_denied": "permissions",
    "authorization_declined": "permissions",
}


def record_auth_result(result, method: str, *, tenant_id: str = "") -> None:
    """Observe MSAL results without retaining credentials or descriptions."""
    attempt = _ATTEMPT.get()
    if attempt is None:
        return
    attempt["method"] = method
    claims = (result.get("id_token_claims") or {}) if isinstance(result, dict) else {}
    attempt["tenant_id"] = tenant_id or claims.get("tid") or attempt["tenant_id"]
    error = result.get("error") if isinstance(result, dict) else ""
    attempt["error_category"] = _ERROR_CATEGORIES.get(error, "unknown")
    attempt["outcome"] = (
        "cancelled"
        if error in {"user_cancelled", "authentication_canceled"}
        else "timeout" if error in {"timeout", "expired_token"} else "failure"
    )


def observe_auth(service: str):
    """Count the whole acquisition once, not silent-cache misses as failures."""

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            attempt = {
                "method": "",
                "tenant_id": str(kwargs.get("authority") or "").rsplit("/", 1)[-1],
                "error_category": "unknown",
                "outcome": "failure",
            }
            token = _ATTEMPT.set(attempt)
            started = time.monotonic()
            try:
                result = function(*args, **kwargs)
                attempt.update(outcome="success", error_category="")
                return result
            except KeyboardInterrupt:
                attempt.update(outcome="cancelled", error_category="")
                raise
            except BaseException as exc:
                if isinstance(exc, TimeoutError) or type(exc).__name__ in {
                    "ReadTimeout",
                    "ConnectTimeout",
                }:
                    attempt.update(outcome="timeout", error_category="network")
                elif type(exc).__name__ == "AgentBuilderAccountMismatch":
                    attempt["error_category"] = "account_mismatch"
                raise
            finally:
                _ATTEMPT.reset(token)
                try:
                    import adk_telemetry

                    adk_telemetry.emit_auth_attempt(
                        service=service,
                        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                        **attempt,
                    )
                except Exception:  # noqa: BLE001 - auth must not depend on telemetry
                    pass

        return wrapped

    return decorate
