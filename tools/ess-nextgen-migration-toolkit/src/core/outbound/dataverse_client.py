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
from typing import Any, Final
from urllib.parse import urljoin, urlparse

import httpx

from core.auth.token_provider import MsalTokenProvider
from core.outbound.exceptions import AuthenticationExpiredError, DataverseApiError

JsonDict = dict[str, Any]
Sleep = Callable[[float], None]

_API_PATH: Final[str] = "/api/data/v9.2/"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0
_GET_ATTEMPTS: Final[int] = 3
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
        token_provider: MsalTokenProvider,
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

    def query_all(
        self,
        entity_set: str,
        *,
        select: str,
        filter: str | None = None,
    ) -> list[JsonDict]:
        """Return all records for an entity-set query across all pages."""
        params: dict[str, str] = {"$select": select}
        if filter is not None:
            params["$filter"] = filter

        payload = self.get(entity_set, params=params)
        records = list(_coerce_records(payload, entity_set))
        next_link = _coerce_next_link(payload)

        while next_link is not None:
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
            raise RuntimeError("Dataverse create response did not include a record ID.")
        return record_id

    def update(self, entity_set: str, record_id: str, data: JsonDict) -> None:
        """Update one Dataverse record without returning a payload."""
        self.__request(
            "PATCH",
            f"{entity_set}({record_id})",
            json=data,
            operation="update",
            entity_set=entity_set,
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
    ) -> httpx.Response:
        if method == "GET":
            response = self.__request_with_get_retry(
                path,
                params=params,
                operation=operation,
                entity_set=entity_set,
            )
        else:
            response = self.__send_once(method, path, params=params, json=json)

        self.__raise_for_status(response, operation=operation, entity_set=entity_set)
        return response

    def __request_with_get_retry(
        self,
        path: str,
        *,
        params: dict[str, str] | None,
        operation: str,
        entity_set: str | None,
    ) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(1, _GET_ATTEMPTS + 1):
            response = self.__send_once("GET", path, params=params)
            last_response = response
            if response.status_code not in _RETRY_STATUS_CODES or attempt == _GET_ATTEMPTS:
                return response

            delay_seconds = _retry_delay_seconds(response, attempt)
            if delay_seconds > 0:
                self.__sleep(delay_seconds)

        if last_response is None:
            raise RuntimeError("GET retry loop completed without a response.")
        self.__raise_for_status(last_response, operation=operation, entity_set=entity_set)
        return last_response

    def __send_once(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: JsonDict | None = None,
    ) -> httpx.Response:
        token = self.__token_provider.get_token()
        headers = {**_O_DATA_HEADERS, "Authorization": f"Bearer {token}"}
        return self.__client.request(
            method,
            self.__request_url(path),
            headers=headers,
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


def _json_payload(response: httpx.Response) -> JsonDict:
    if not response.content:
        return {}
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Dataverse response payload must be a JSON object.")
    return payload


def _extract_record_id(response: httpx.Response) -> str | None:
    header_value = response.headers.get("OData-EntityId") or response.headers.get("Location")
    if header_value is not None:
        match = _RECORD_ID_PATTERN.search(header_value)
        if match is not None:
            return match.group(1)

    if response.content:
        payload = response.json()
        if isinstance(payload, dict):
            string_ids = [
                value
                for key, value in payload.items()
                if key.lower().endswith("id") and isinstance(value, str)
            ]
            if len(string_ids) == 1:
                return string_ids[0]
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
        return retry_after_seconds
    return float(2 ** (attempt - 1))


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
