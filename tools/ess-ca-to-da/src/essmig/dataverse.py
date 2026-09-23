"""Read-only Dataverse Web API client.

This tool never writes to Dataverse. The customer's Custom Engine Agent is left
exactly as it is found; the migration output is an ALM package the customer
imports into the Declarative Agent separately. Accordingly this client exposes
only ``get``, ``query_all`` and ``call_function``.
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

from essmig.auth import TokenProvider

JsonDict = dict[str, Any]

_API_PATH: Final = "/api/data/v9.2/"
_DEFAULT_TIMEOUT_SECONDS: Final = 120.0
_GET_ATTEMPTS: Final = 3
_MAX_RETRY_DELAY_SECONDS: Final = 60.0
_RETRY_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})
_ODATA_HEADERS: Final = {
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Prefer": "odata.include-annotations=*",
}

# A GUID-shaped value is an OData ``Edm.Guid`` literal (unquoted) in a Web API
# function call; anything else is a single-quoted ``Edm.String`` literal.
_GUID_RE: Final = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class DataverseError(RuntimeError):
    """A Dataverse Web API call failed."""

    def __init__(self, status: int, path: str, message: str = "") -> None:
        self.status = status
        self.path = path
        super().__init__(f"Dataverse {status} on {path}{f': {message}' if message else ''}")


class DataverseClient:
    """Execute authenticated, read-only Dataverse Web API requests."""

    def __init__(
        self,
        env_url: str,
        token_provider: TokenProvider,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._env_url = _normalize_env_url(env_url)
        self._tokens = token_provider
        self._sleep = sleep
        self._client = client or httpx.Client(
            base_url=f"{self._env_url}{_API_PATH}", timeout=_DEFAULT_TIMEOUT_SECONDS
        )

    @property
    def environment_url(self) -> str:
        return self._env_url

    def query_all(
        self, entity_set: str, *, select: str | None = None, filter: str | None = None
    ) -> list[JsonDict]:
        """Return every record for an entity-set query, following ``@odata.nextLink``.

        Dataverse has no ``$select=*``; pass ``None`` (or ``"*"``) to omit the
        parameter and take the full default projection.
        """
        params: dict[str, str] = {}
        if select and select != "*":
            params["$select"] = select
        if filter:
            params["$filter"] = filter

        payload = self.get(entity_set, params=params or None)
        records = _records(payload, entity_set)
        next_link = _next_link(payload)
        while next_link is not None:
            self._validate_next_link(next_link)
            payload = self.get(next_link)
            records.extend(_records(payload, entity_set))
            next_link = _next_link(payload)
        return records

    def get(self, path: str, *, params: dict[str, str] | None = None) -> JsonDict:
        response = self._send_with_retry(path, params)
        if response.status_code >= 400:
            raise DataverseError(response.status_code, path, _error_message(response))
        return response.json() if response.content else {}

    def call_function(self, function_name: str, **params: str) -> JsonDict:
        """Invoke an unbound Web API function with inlined OData literals.

        A GUID value becomes an unquoted ``Edm.Guid`` literal — which is what
        ``RetrieveDependenciesForUninstallWithMetadata(SolutionId=<guid>)``
        requires; anything else becomes a quoted ``Edm.String``.
        """
        inner = ",".join(
            f"{key}={value}" if _GUID_RE.match(value) else f"{key}='{value}'"
            for key, value in params.items()
        )
        return self.get(f"{function_name}({inner})")

    def _send_with_retry(
        self, path: str, params: dict[str, str] | None
    ) -> httpx.Response:
        response = self._send_once(path, params)
        for attempt in range(1, _GET_ATTEMPTS):
            if response.status_code not in _RETRY_STATUS_CODES:
                return response
            delay = _retry_delay(response, attempt)
            if delay > 0:
                self._sleep(delay)
            response = self._send_once(path, params)
        return response

    def _send_once(self, path: str, params: dict[str, str] | None) -> httpx.Response:
        token = self._tokens.get_token()
        headers = {**_ODATA_HEADERS, "Authorization": "Bearer " + token}
        return self._client.request("GET", self._url(path), headers=headers, params=params)

    def _url(self, path: str) -> str:
        parsed = urlparse(path)
        if parsed.scheme and parsed.netloc:
            return path
        if path.startswith("/"):
            return urljoin(f"{self._env_url}/", path.lstrip("/"))
        return path

    def _validate_next_link(self, next_link: str) -> None:
        """Refuse a nextLink pointing at another host (bearer-token exfiltration guard)."""
        parsed = urlparse(next_link)
        if not (parsed.scheme and parsed.netloc):
            return
        expected = urlparse(self._env_url).netloc.lower()
        if parsed.scheme.lower() != "https" or parsed.netloc.lower() != expected:
            raise DataverseError(
                0,
                next_link,
                f"@odata.nextLink host {parsed.netloc!r} differs from the environment "
                f"host {expected!r}; refusing to follow.",
            )


def _normalize_env_url(env_url: str) -> str:
    parsed = urlparse(env_url.strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("env_url must be an HTTPS URL.")
    if parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ValueError("env_url must be the Dataverse root (no path, query, or fragment).")
    return f"{parsed.scheme}://{parsed.netloc}"


def _records(payload: JsonDict, entity_set: str) -> list[JsonDict]:
    value = payload.get("value")
    if not isinstance(value, list):
        raise DataverseError(200, entity_set, "response has no list-valued 'value' key.")
    return [item for item in value if isinstance(item, dict)]


def _next_link(payload: JsonDict) -> str | None:
    link = payload.get("@odata.nextLink")
    return link if isinstance(link, str) and link else None


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), _MAX_RETRY_DELAY_SECONDS)
        except ValueError:
            try:
                when = parsedate_to_datetime(header)
            except (TypeError, ValueError):
                when = None
            if when is not None:
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                delta = (when - datetime.now(UTC)).total_seconds()
                return min(max(delta, 0.0), _MAX_RETRY_DELAY_SECONDS)
    return min(float(2**attempt), _MAX_RETRY_DELAY_SECONDS)


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return str(body)[:300]
