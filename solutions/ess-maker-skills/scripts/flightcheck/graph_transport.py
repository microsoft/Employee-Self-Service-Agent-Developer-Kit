# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded Graph reads with shared retry policy and cancellable OS DNS."""

import asyncio
from dataclasses import dataclass
import json
import socket
import sys
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import requests
from urllib3.exceptions import InvalidHeader
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry


class GraphPermissionError(PermissionError):
    """Graph consent or a directory read was explicitly denied."""


@dataclass(frozen=True)
class CollectionRead:
    items: list[dict]
    complete: bool


def collection_page(data, url: str) -> tuple[list[dict], str | None]:
    if (
        not isinstance(data, dict) or not isinstance(data.get("value"), list)
        or any(not isinstance(row, dict) for row in data["value"])
    ):
        raise ValueError("Graph returned an invalid resource collection.")
    continuation = data.get("@odata.nextLink")
    if continuation is not None:
        expected, actual = urlsplit(url), urlsplit(str(continuation))
        if (
            not isinstance(continuation, str) or not continuation
            or actual.scheme != expected.scheme or actual.netloc != expected.netloc
            or actual.path != expected.path or actual.fragment
        ):
            raise ValueError("Graph returned an invalid collection continuation.")
    return data["value"], continuation


# Cancelling the thread-pool resolver leaves event-loop shutdown waiting on DNS.
# The helper receives only resolver arguments, never tokens or profile data.
_DNS_LOOKUP = """
import json
import socket
import sys

try:
    addresses = socket.getaddrinfo(**json.load(sys.stdin))
except OSError as exc:
    json.dump({"error": exc.errno}, sys.stdout)
else:
    json.dump({"addresses": addresses}, sys.stdout)
"""


async def _bounded_getaddrinfo(host, port, *, family=0, type=0, proto=0, flags=0):
    options = {
        "host": host.decode("ascii") if isinstance(host, bytes) else host,
        "port": port.decode("ascii") if isinstance(port, bytes) else port,
        "family": family, "type": type, "proto": proto, "flags": flags,
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-S", "-c", _DNS_LOOKUP,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await process.communicate(json.dumps(options).encode("utf-8"))
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
    if process.returncode != 0:
        raise RuntimeError("Graph DNS resolver process failed.")
    result = json.loads(output)
    if "error" in result:
        raise socket.gaierror(result["error"], "Graph DNS resolution failed.")
    return [
        (family, kind, proto, canonical, tuple(address))
        for family, kind, proto, canonical, address in result["addresses"]
    ]


def _bounded_event_loop():
    loop = asyncio.new_event_loop()
    loop.getaddrinfo = _bounded_getaddrinfo
    return loop


def _retry_response(retry: Retry, status: int, headers, *, url: str | None = None) -> tuple[Retry, float] | None:
    if not retry.total or not retry.is_retry("GET", status, "Retry-After" in headers):
        return None
    metadata = HTTPResponse(status=status, headers=headers)
    updated = retry.increment(method="GET", url=url, response=metadata)
    delay = updated.get_retry_after(metadata) if updated.respect_retry_after_header else None
    return updated, delay or updated.get_backoff_time()


def _batch_responses(data, expected_ids: set[str]):
    rows = data.get("responses") if isinstance(data, dict) else None
    if (
        not isinstance(rows, list) or len(rows) != len(expected_ids)
        or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows)
        or {row["id"] for row in rows} != expected_ids
    ):
        raise ValueError("Graph returned an incomplete or invalid profile batch.")
    permission_denied = False
    for row in rows:
        status = row.get("status")
        if type(status) is not int:
            raise ValueError("Graph returned an invalid profile response status.")
        headers = row.get("headers", {})
        if not isinstance(headers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()
        ):
            raise ValueError("Graph returned invalid profile response headers.")
        profile = row.get("body")
        if status == 200 and (not isinstance(profile, dict) or not profile or "error" in profile):
            raise ValueError("Graph returned an invalid profile resource.")
        if status == 403:
            permission_denied = True
            continue
        yield row["id"], status, httpx.Headers(headers), profile
    # Permission fallback must not hide another response's authentication or data error.
    if permission_denied:
        raise GraphPermissionError("Graph denied a profile read; no partial coverage is reported.")


class BoundedGraphTransport:
    def __init__(self, base_url: str, headers: dict[str, str], retry: Retry):
        self.base_url, self.headers, self.retry = base_url, headers, retry

    def get_collection(
        self, path: str, *, params: dict, limit: int, time_budget: float,
    ) -> CollectionRead:
        if limit <= 0 or time_budget <= 0:
            raise ValueError("Collection limit and time budget must be positive.")
        return self._run(self._read(path, params, limit, time_budget), time_budget)

    def get_profile(self, *, params: dict, time_budget: float, path: str = "/me") -> dict:
        if time_budget <= 0:
            raise ValueError("Profile time budget must be positive.")
        return self._run(self._read(path, params, None, time_budget), time_budget)

    def get_profiles(self, user_ids: list[str], *, time_budget: float) -> list[dict]:
        if time_budget <= 0 or not user_ids:
            raise ValueError("Profile identities and time budget must be positive.")
        identities = [str(UUID(identity)) for identity in user_ids]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate profile identities; coverage was not calculated.")
        return self._run(self._read_profiles(identities, time_budget), time_budget)

    def _run(self, operation, time_budget):
        try:
            with asyncio.Runner(loop_factory=_bounded_event_loop) as runner:
                return runner.run(asyncio.wait_for(operation, timeout=time_budget))
        except TimeoutError:
            raise TimeoutError(
                f"The {time_budget:g}-second coverage budget expired; no partial coverage is reported."
            ) from None
        except httpx.HTTPStatusError as exc:
            response = requests.Response()
            response.status_code = exc.response.status_code
            raise requests.HTTPError(
                f"Graph read failed (HTTP {response.status_code}).", response=response,
            ) from None
        except httpx.RequestError as exc:
            raise requests.ConnectionError(f"Graph request failed ({type(exc).__name__}).") from None
        except InvalidHeader:
            raise ValueError("Graph returned an invalid Retry-After header.") from None

    async def _get_with_retries(self, session, path, url, params, *, batch=None):
        retry = self.retry
        while True:
            try:
                response = (
                    await session.get(url, headers=self.headers, params=params)
                    if batch is None else
                    await session.post(url, headers=self.headers, json={"requests": batch})
                )
            except (httpx.NetworkError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                if not retry.total:
                    raise
                retry = retry.increment(method="GET", url=url, error=exc)
                await asyncio.sleep(retry.get_backoff_time())
                continue
            scheduled = _retry_response(retry, response.status_code, response.headers, url=url)
            if scheduled is not None:
                retry, delay = scheduled
                await asyncio.sleep(delay)
                continue
            if response.status_code == 403:
                raise GraphPermissionError(f"Graph returned HTTP 403 on {path}.")
            response.raise_for_status()
            return response

    async def _read(self, path, params, limit, time_budget):
        items: list[dict] = []
        seen_urls: set[str] = set()
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=time_budget, follow_redirects=False) as session:
            while url:
                if url in seen_urls:
                    raise ValueError("Graph returned a repeated collection continuation.")
                seen_urls.add(url)
                response = await self._get_with_retries(session, path, url, params)
                data = response.json()
                if limit is None:
                    if not isinstance(data, dict):
                        raise ValueError("Graph returned an invalid user profile.")
                    return data
                page, continuation = collection_page(data, f"{self.base_url}{path}")
                if continuation in seen_urls:
                    raise ValueError("Graph returned a repeated collection continuation.")
                remaining = limit - len(items)
                items.extend(page[:remaining])
                complete = continuation is None and len(page) <= remaining
                if len(items) == limit or complete:
                    return CollectionRead(items, complete)
                url, params = continuation, None
        raise ValueError("Graph collection discovery did not complete.")

    async def _read_profiles(self, identities, time_budget):
        profiles = {}
        async with httpx.AsyncClient(timeout=time_budget, follow_redirects=False) as session:
            for offset in range(0, len(identities), 20):
                pending = {
                    str(index): {
                        "id": str(index), "method": "GET",
                        "url": f"/users/{identity}/profile",
                    }
                    for index, identity in enumerate(identities[offset:offset + 20], start=offset)
                }
                retries = {key: self.retry for key in pending}
                while pending:
                    # Every subrequest is GET; the batch POST is a read-only envelope.
                    response = await self._get_with_retries(
                        session, "/$batch", f"{self.base_url}/$batch", None,
                        batch=list(pending.values()),
                    )
                    retry_requests = {}
                    delays = []
                    for key, status, headers, profile in _batch_responses(response.json(), set(pending)):
                        scheduled = _retry_response(retries[key], status, headers)
                        if scheduled is not None:
                            retries[key], delay = scheduled
                            delays.append(delay)
                            retry_requests[key] = pending[key]
                            continue
                        if status != 200:
                            failed = requests.Response()
                            failed.status_code = status
                            raise requests.HTTPError(
                                f"Graph profile read failed (HTTP {status}); no partial coverage is reported.",
                                response=failed,
                            )
                        profiles[key] = profile
                    pending = retry_requests
                    if pending:
                        await asyncio.sleep(max(delays))
        return [profiles[str(index)] for index in range(len(identities))]
