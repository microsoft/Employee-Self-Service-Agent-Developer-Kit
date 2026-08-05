"""Typed Dataverse Web API client.

Owns Dataverse authentication handoff, HTTP execution, retry handling, and
OData serialization concerns. Business and migration logic must never live in
this module.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final, Protocol
from urllib.parse import urljoin, urlparse

import httpx

from core.outbound.exceptions import AuthenticationExpiredError, DataverseApiError

JsonDict = dict[str, Any]
Sleep = Callable[[float], None]

# A GUID-shaped value is an OData ``Edm.Guid`` literal (unquoted) in a Web API
# function call; anything else is a single-quoted ``Edm.String`` literal.
_GUID_LITERAL_RE: Final = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


def _format_function_param(key: str, value: str) -> str:
    """Format one unbound-function parameter as an OData literal."""
    if _GUID_LITERAL_RE.match(value):
        return f"{key}={value}"
    return f"{key}='{value}'"


class TokenProvider(Protocol):
    """Any object that can provide a bearer token."""

    def get_token(self) -> str: ...


_API_PATH: Final[str] = "/api/data/v9.2/"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0
_GET_ATTEMPTS: Final[int] = 3
_MAX_RETRY_DELAY_SECONDS: Final[float] = 60.0
_RETRY_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
_RECORD_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"\(([^()]+)\)")
_O_DATA_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Prefer": "odata.include-annotations=*",
}


class DataverseClient:
    """Execute authenticated Dataverse Web API requests.

    Responsibilities:
    - obtain a fresh bearer token for every HTTP request,
    - apply required OData headers,
    - retry idempotent GET requests on Dataverse throttling/server failures,
    - translate HTTP failures into typed outbound exceptions.
    """

    def __init__(
        self,
        env_url: str,
        token_provider: TokenProvider,
        *,
        client: httpx.Client | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        """Create a Dataverse client for one HTTPS environment.

        Inputs:
        - env_url: Dataverse environment root URL.
        - token_provider: bearer-token provider used immediately before requests.

        Output:
        - initialized client ready for Dataverse Web API calls.
        """
        self.__env_url = _normalize_env_url(env_url)
        self.__token_provider = token_provider
        self.__sleep = sleep if sleep is not None else time.sleep
        self.__client = (
            client
            if client is not None
            else httpx.Client(
                base_url=f"{self.__env_url}{_API_PATH}",
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
        )

    @property
    def environment_url(self) -> str:
        """Return the normalized Dataverse environment URL bound to this client."""
        return self.__env_url

    def query_all(
        self,
        entity_set: str,
        *,
        select: str | None = None,
        filter: str | None = None,
    ) -> list[JsonDict]:
        """Return all records for an entity-set query across all pages.

        ``select`` limits the returned columns. Pass ``None`` (the default) or
        ``"*"`` to return all fields — Dataverse has no ``$select=*``; the
        parameter is simply omitted, which yields the full default projection.
        """
        params: dict[str, str] = {}
        if select is not None and select != "*":
            params["$select"] = select
        if filter is not None:
            params["$filter"] = filter

        payload = self.get(entity_set, params=params or None)
        records = list(_coerce_records(payload, entity_set))
        next_link = _coerce_next_link(payload)

        while next_link is not None:
            _validate_next_link(next_link, self.__env_url)
            payload = self.get(next_link)
            records.extend(_coerce_records(payload, entity_set))
            next_link = _coerce_next_link(payload)

        return records

    def get(self, path: str, *, params: dict[str, str] | None = None) -> JsonDict:
        """Execute one Dataverse GET request and return the JSON payload."""
        response = self.__request(
            "GET",
            path,
            params=params,
            operation="read",
            entity_set=_entity_from_path(path),
        )
        return _json_payload(response)

    def call_function(self, function_name: str, **params: str) -> JsonDict:
        """Invoke an unbound Dataverse Web API function and return the JSON payload.

        Parameters are inlined as OData literals: a GUID value becomes an unquoted
        ``Edm.Guid`` literal (e.g.
        ``RetrieveDependenciesForUninstallWithMetadata(SolutionId=<guid>)``); any
        other value becomes a single-quoted ``Edm.String`` literal. Functions with
        no parameters (e.g. ``GetPreferredSolution()``) pass none.
        """
        inner = ",".join(_format_function_param(key, value) for key, value in params.items())
        path = f"{function_name}({inner})"
        return self.get(path)

    def create(self, entity_set: str, data: JsonDict) -> str:
        """Create one Dataverse record and return its Dataverse record ID."""
        response = self.__request(
            "POST",
            entity_set,
            json=data,
            operation="create",
            entity_set=entity_set,
        )
        record_id = _extract_record_id(response)
        if record_id is None:
            raise DataverseApiError(
                status=response.status_code,
                operation="create",
                entity_set=entity_set,
                message="Dataverse create response did not include a record ID.",
            )
        return record_id

    def update(
        self,
        entity_set: str,
        record_id: str,
        data: JsonDict,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Update one Dataverse record without returning a payload."""
        self.__request(
            "PATCH",
            f"{entity_set}({record_id})",
            json=data,
            operation="update",
            entity_set=entity_set,
            headers=headers,
        )

    def delete(self, entity_set: str, record_id: str) -> None:
        """Delete one Dataverse record without returning a payload."""
        self.__request(
            "DELETE",
            f"{entity_set}({record_id})",
            operation="delete",
            entity_set=entity_set,
        )

    def __request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonDict | None = None,
        operation: str,
        entity_set: str | None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if method == "GET":
            response = self.__request_with_get_retry(
                path,
                params=params,
                headers=headers,
            )
        else:
            response = self.__send_once(method, path, params=params, json=json, headers=headers)

        self.__raise_for_status(response, operation=operation, entity_set=entity_set)
        return response

    def __request_with_get_retry(
        self,
        path: str,
        *,
        params: dict[str, str] | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        response = self.__send_once("GET", path, params=params, headers=headers)
        for attempt in range(1, _GET_ATTEMPTS):
            if response.status_code not in _RETRY_STATUS_CODES:
                return response

            delay_seconds = _retry_delay_seconds(response, attempt)
            if delay_seconds > 0:
                self.__sleep(delay_seconds)
            response = self.__send_once("GET", path, params=params, headers=headers)

        return response

    def __send_once(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonDict | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        token = self.__token_provider.get_token()
        request_headers = {
            **_O_DATA_HEADERS,
            **(headers or {}),
            "Authorization": f"Bearer {token}",
        }
        return self.__client.request(
            method,
            self.__request_url(path),
            headers=request_headers,
            params=params,
            json=json,
        )

    def __request_url(self, path: str) -> str:
        parsed = urlparse(path)
        if parsed.scheme and parsed.netloc:
            return path
        if path.startswith("/"):
            return urljoin(f"{self.__env_url}/", path.lstrip("/"))
        return path

    def __raise_for_status(
        self,
        response: httpx.Response,
        *,
        operation: str,
        entity_set: str | None,
    ) -> None:
        if response.status_code < 400:
            return

        request_id = _request_id(response)
        if response.status_code == 401:
            raise AuthenticationExpiredError(
                operation=operation,
                entity_set=entity_set,
                request_id=request_id,
            )

        raise DataverseApiError(
            status=response.status_code,
            operation=operation,
            entity_set=entity_set,
            request_id=request_id,
        )


def _normalize_env_url(env_url: str) -> str:
    parsed = urlparse(env_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("env_url must be an HTTPS URL.")
    if parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ValueError("env_url must be the Dataverse root (no path, query, or fragment).")
    return f"{parsed.scheme}://{parsed.netloc}"


def _coerce_records(payload: JsonDict, entity_set: str) -> list[JsonDict]:
    if "value" not in payload:
        raise DataverseApiError(
            status=200,
            operation="read",
            entity_set=entity_set,
            message="Dataverse query response is missing the required 'value' key.",
        )
    value = payload["value"]
    if not isinstance(value, list):
        raise DataverseApiError(
            status=200,
            operation="read",
            entity_set=entity_set,
            message="Dataverse query response 'value' is not a list.",
        )
    records: list[JsonDict] = []
    for item in value:
        if isinstance(item, dict):
            records.append(item)
    return records


def _coerce_next_link(payload: JsonDict) -> str | None:
    next_link = payload.get("@odata.nextLink")
    return next_link if isinstance(next_link, str) and next_link else None


def _validate_next_link(next_link: str, env_url: str) -> None:
    """Reject nextLinks that point to a different host (token exfiltration guard)."""
    parsed = urlparse(next_link)
    env_parsed = urlparse(env_url)
    if parsed.scheme and parsed.netloc:
        if parsed.scheme.lower() != "https" or parsed.netloc.lower() != env_parsed.netloc.lower():
            raise DataverseApiError(
                status=0,
                operation="read",
                entity_set=None,
                message=(
                    f"@odata.nextLink points to a different host ({parsed.netloc}) "
                    f"than the configured environment ({env_parsed.netloc}). "
                    "Refusing to follow — possible token exfiltration."
                ),
            )


def _json_payload(response: httpx.Response) -> JsonDict:
    if not response.content:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        raise DataverseApiError(
            status=response.status_code,
            operation="read",
            entity_set=None,
            message="Dataverse response payload must be a JSON object.",
        )
    return payload


def _extract_record_id(response: httpx.Response) -> str | None:
    header_value = response.headers.get("OData-EntityId") or response.headers.get("Location")
    if header_value is not None:
        match = _RECORD_ID_PATTERN.search(header_value)
        if match is not None:
            return match.group(1)
    return None


def _request_id(response: httpx.Response) -> str | None:
    request_id = response.headers.get("x-ms-request-id") or response.headers.get("request-id")
    if request_id is None or isinstance(request_id, str):
        return request_id
    return str(request_id)


def _entity_from_path(path: str) -> str | None:
    parsed = urlparse(path)
    relative_path = parsed.path if parsed.scheme and parsed.netloc else path
    trimmed = relative_path.lstrip("/")
    api_prefix = _API_PATH.lstrip("/")
    if trimmed.startswith(api_prefix):
        trimmed = trimmed[len(api_prefix) :]
    return trimmed.split("?", maxsplit=1)[0] or None


def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
    retry_after_header = response.headers.get("Retry-After")
    retry_after_seconds = _parse_retry_after_seconds(retry_after_header)
    if retry_after_seconds is not None:
        return min(retry_after_seconds, _MAX_RETRY_DELAY_SECONDS)
    return min(float(2 ** (attempt - 1)), _MAX_RETRY_DELAY_SECONDS)


def _parse_retry_after_seconds(header_value: str | None) -> float | None:
    if header_value is None:
        return None
    stripped = header_value.strip()
    if not stripped:
        return None

    try:
        return max(float(stripped), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    delta = retry_at - datetime.now(UTC)
    return max(delta.total_seconds(), 0.0)
