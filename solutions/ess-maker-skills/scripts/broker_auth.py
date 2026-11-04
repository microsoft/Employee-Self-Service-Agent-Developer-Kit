# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Windows broker authentication shared by the ESS public-client sign-ins."""

from __future__ import annotations

import sys
from typing import Any

import msal
import requests


class BrokerAuthenticationError(RuntimeError):
    """Raised when the required Windows broker cannot be used."""


class _BrokerOnlyHttpClient(requests.Session):
    def post(self, url: str, **kwargs: Any) -> Any:
        raise BrokerAuthenticationError(
            "Windows token acquisition must use WAM, not an HTTP token request."
        )


def is_windows() -> bool:
    return sys.platform == "win32"


def create_public_client_application(client_id: str, **kwargs: Any) -> Any:
    if not is_windows():
        return msal.PublicClientApplication(client_id, **kwargs)
    try:
        app = msal.PublicClientApplication(
            client_id,
            enable_broker_on_windows=True,
            http_client=_BrokerOnlyHttpClient(),
            **kwargs,
        )
    except ImportError as exc:
        raise BrokerAuthenticationError(
            "Windows sign-in requires the MSAL broker dependencies. "
            "Install the updated ADK requirements and retry."
        ) from exc
    # MSAL can deactivate an opted-in broker when initialization fails.
    if not getattr(app, "_enable_broker", False):
        raise BrokerAuthenticationError(
            "Windows Web Account Manager (WAM) could not be initialized. "
            "Use a supported Windows desktop session and verify the broker "
            "dependencies. Browser fallback is not used."
        )
    return app


def _parent_window_handle() -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetConsoleWindow.argtypes = []
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    handle = kernel32.GetConsoleWindow()
    if not handle:
        # VS Code's stdio MCP host may not have a console window.
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        handle = user32.GetForegroundWindow()
    if not handle:
        raise BrokerAuthenticationError(
            "Windows sign-in requires an interactive desktop window. "
            "Retry from VS Code or a Windows terminal."
        )
    return int(handle)


def _require_broker_ui(ui: str, **kwargs: Any) -> None:
    if ui != "broker":
        raise BrokerAuthenticationError(
            "Windows sign-in did not select WAM. Browser fallback is not used."
        )


def acquire_token_silent(
    app: Any, scopes: list[str], *, account: dict[str, Any], **kwargs: Any
) -> Any:
    # MSAL can refresh browser-created accounts without broker even when opted in.
    # Establish a broker account interactively instead of reusing those credentials.
    if is_windows() and account.get("account_source") != "broker":
        return None
    try:
        return app.acquire_token_silent(scopes, account=account, **kwargs)
    except BrokerAuthenticationError:
        # A broker account can disappear while a legacy refresh token remains.
        # Treat blocked HTTP fallback as a cache miss, not a credential to reuse.
        return None


def acquire_token_interactive(app: Any, scopes: list[str], **kwargs: Any) -> Any:
    if is_windows():
        kwargs["parent_window_handle"] = _parent_window_handle()
        kwargs["on_before_launching_ui"] = _require_broker_ui
    return app.acquire_token_interactive(scopes=scopes, **kwargs)
