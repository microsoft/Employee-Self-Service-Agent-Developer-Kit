# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - User-Friendly HTTP Error Handling

Provides a central helper that translates raw HTTP status codes into
actionable messages with troubleshooting tips. Used by auth.py and
the installer scripts (discover.py, fetch_and_setup.py) to surface
clear guidance when API calls fail.

FlightCheck clients (graph_client, pp_admin_client, pva_client) have
their own error patterns (returning _error dicts) and are NOT changed.
"""

import requests


# Friendly display names for Dataverse entity sets.
_ENTITY_DISPLAY_NAMES = {
    "bots": "agents",
    "botcomponents": "agent components",
    "workflows": "cloud flows",
    "msdyn_employeeselfservicetemplateconfigs": "ESS template configurations",
    "connections": "connections",
    "connectionreferences": "connection references",
}


def _friendly_name(resource_name):
    """Map an entity set name to a user-friendly label."""
    if not resource_name:
        return "this resource"
    return _ENTITY_DISPLAY_NAMES.get(resource_name, resource_name)


class APIError(requests.exceptions.HTTPError):
    """HTTP error with user-friendly message and troubleshooting tip.

    Subclasses requests.HTTPError so existing `except HTTPError` handlers
    still catch it. Adds structured fields for display formatting.
    """

    def __init__(self, response, resource_name=None, operation=None,
                 required_role=None, message=None, tip=None):
        self.status_code = response.status_code if response is not None else 0
        self.resource_name = resource_name
        self.operation = operation or "access"
        self.required_role = required_role
        self.url = (response.request.url if response is not None
                    and response.request else None)
        self.request_id = (
            response.headers.get("x-ms-request-id")
            if response is not None else None
        )

        # Build user-facing message
        friendly = _friendly_name(resource_name)
        self._friendly_message = message or _build_message(
            self.status_code, friendly, self.operation, self.required_role
        )
        self._tip = tip or _build_tip(
            self.status_code, friendly, self.operation, self.required_role
        )

        # Call parent with the friendly message as the exception string
        super().__init__(str(self), response=response)

    def __str__(self):
        parts = [self._friendly_message]
        if self._tip:
            parts.append(f"  -> {self._tip}")
        return "\n".join(parts)

    def format_for_terminal(self):
        """Format the error for terminal display with technical details."""
        lines = [
            "",
            f"  ERROR: {self._friendly_message}",
        ]
        if self._tip:
            lines.append(f"  Tip:   {self._tip}")
        # Technical detail line (compact, for debugging)
        if self.url:
            # Truncate URL to avoid leaking full query strings
            display_url = self.url.split("?")[0]
            method_verb = (self.operation or "GET").upper()
            if method_verb in ("READ", "ACCESS"):
                method_verb = "GET"
            elif method_verb == "UPDATE":
                method_verb = "PATCH"
            elif method_verb == "CREATE":
                method_verb = "POST"
            elif method_verb == "DELETE":
                method_verb = "DELETE"
            lines.append(
                f"  Detail: HTTP {self.status_code} — {method_verb} {display_url}"
            )
        if self.request_id:
            lines.append(f"  Request ID: {self.request_id}")
        lines.append("")
        return "\n".join(lines)


def _build_message(status_code, friendly_resource, operation, required_role):
    """Build the main error message based on status code."""
    if status_code == 400:
        return (
            f"Bad request while trying to {operation} {friendly_resource}. "
            "The API rejected the query — this may indicate a version mismatch "
            "or unsupported filter."
        )
    if status_code == 401:
        return (
            "Your session has expired or the token is invalid."
        )
    if status_code == 403:
        return (
            f"You signed in successfully, but your account doesn't have "
            f"permission to {operation} {friendly_resource}."
        )
    if status_code == 404:
        return (
            f"Could not find {friendly_resource}. The resource doesn't exist "
            "or the required solution may not be deployed in this environment."
        )
    if status_code == 429:
        return (
            "Too many requests — the API is rate-limiting your account."
        )
    if status_code in (500, 502, 503, 504):
        return (
            f"The server returned an error (HTTP {status_code}) while trying "
            f"to {operation} {friendly_resource}. This is usually temporary."
        )
    return (
        f"Unexpected HTTP {status_code} while trying to {operation} "
        f"{friendly_resource}."
    )


def _build_tip(status_code, friendly_resource, operation, required_role):
    """Build the troubleshooting tip for a given status code."""
    if status_code == 400:
        return (
            "Check that the environment URL is correct and the ESS solution "
            "version matches this kit version."
        )
    if status_code == 401:
        return "Run the command again — you'll be prompted to sign in."
    if status_code == 403:
        role = required_role or "Bot Author, Bot Contributor, or System Administrator"
        return (
            f"Ask your Power Platform admin to assign the {role} security role "
            "to your account in this environment."
        )
    if status_code == 404:
        return (
            "Verify the ESS solution is installed in this environment, or "
            "choose a different environment."
        )
    if status_code == 429:
        return "Wait 1-2 minutes and try again."
    if status_code in (500, 502, 503, 504):
        return (
            "Wait a few minutes and try again. If the problem persists, check "
            "the Power Platform Service Health dashboard."
        )
    return "Check the status code and URL above for clues."


def raise_api_error(response, resource_name=None, operation=None,
                    required_role=None):
    """Inspect a response and raise APIError if it indicates failure.

    Call this AFTER any 401 check (AuthExpiredError) but INSTEAD of
    resp.raise_for_status(). This produces user-friendly errors for
    all non-2xx responses.

    Args:
        response: The requests.Response object.
        resource_name: The Dataverse entity set or API resource being accessed.
        operation: The operation being performed (read/create/update/delete).
        required_role: Role to suggest in 403 messages (optional).
    """
    if response.status_code >= 400:
        raise APIError(
            response,
            resource_name=resource_name,
            operation=operation,
            required_role=required_role,
        )
