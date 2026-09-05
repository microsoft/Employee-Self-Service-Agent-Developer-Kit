"""Inventory API client: the write/read surface the skill depends on.

Routes (OData containment under the ``tenants`` entity set)::

    GET  {c}                        list non-retired rows ($top/$skip/$orderby)
    GET  {c}('{id}')                read one row by its opaque kind:naturalKey id
    POST {c}/syncInventory          replace the tenant's whole inventory (200)

    where {c} = {base}/api/beta/tenants('{tenantId}')/agentConfigurationInventoryItems

**Sync is whole-inventory, and absence retires.** One call carries every row the
tenant should have, across all kinds mixed together, and the service retires anything
Active that the payload omits. There is no per-row write, no delete call, and no id
list naming what to remove. Three consequences shape the client:

1. **A partial crawl must never be submitted.** Omission is deletion, so posting what
   a half-failed crawl managed to collect retires everything it could not read. The
   service offers no guardrail for this, so the gate lives in
   :meth:`~tenant_inventory_discovery.discovery_skill.DiscoverySkill._sync` and is the
   single most load-bearing safety property in the skill. The failure direction is the
   opposite of the old design's: a partially-authorized crawl used to retire too
   little, and now retires too much.
2. **Nothing is precondition-checked.** ETags, ``If-Match`` and the 412 retry are gone
   -- the response describes a whole-inventory transition, not one row's revision, and
   no ETag comes back at all.
3. **Order is irrelevant.** The service sorts internally, writing parents before
   children and retiring after, so the payload may be assembled in any order.

Payload limits are pre-checked client-side by
:func:`~tenant_inventory_discovery.mapping.validate_sync_payload`, which refuses an
empty list outright: empty is legal on the wire and retires the entire tenant.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from .config import DiscoveryConfig, RetryPolicy
from .errors import (
    InventoryApiError,
    NonRetryableApiError,
    ThrottledError,
)
from .mapping import (
    sync_idempotency_key,
    to_sync_entry,
    validate_sync_payload,
)
from .models import (
    FailedSyncItem,
    InventoryItem,
    Kind,
    SyncResult,
)


@runtime_checkable
class InventoryClient(Protocol):
    """The Inventory surface the runner and skill depend on."""

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List the tenant's non-retired rows, optionally narrowed to a scope."""
        ...

    def sync_inventory(
        self, items: Sequence[InventoryItem], *, run_id: str = ""
    ) -> SyncResult:
        """Submit the tenant's entire inventory; anything Active but omitted is retired.

        ``run_id`` scopes the ``Idempotency-Key`` to the current pass so a timed-out
        resend replays rather than re-running ~400 writes, while a later pass still
        applies.
        """
        ...


def odata_key_literal(item_id: str) -> str:
    """Render an opaque item id as an OData key segment.

    Two layers of escaping, in this order:

    1. **OData string literal** -- a single quote inside the literal is doubled.
    2. **URL path** -- the whole literal is percent-encoded, so the ``%`` in an id
       that already contains percent-encoded natural-key segments survives the
       service's own path decode. Skipping this collapses ``%3A`` back to ``:`` and
       the lookup misses.
    """
    return quote(item_id.replace("'", "''"), safe="")


#: Service payload keys whose camelCase form is not simply "first letter lowered".
_KEY_ALIASES = {"ETag": "etag", "@odata.etag": "etag"}


def _camel(key: str) -> str:
    if key in _KEY_ALIASES:
        return _KEY_ALIASES[key]
    if not key or key[0].islower():
        return key
    return key[0].lower() + key[1:]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a service payload's PascalCase keys to the camelCase used internally.

    The service serializes EDM property names as ``NaturalKey``, ``Source``, ``ETag``,
    ``Attributes: [{Key, Value}]``. Every consumer here -- the local mirror, the
    reporting layer, the in-memory fake -- was written against camelCase. Left
    unnormalized the mismatch is *silent*: ``row.get("source")`` is None rather than
    ``"Discovered"``, and ``list_items(kind=...)`` filters on a key that does not exist
    and returns nothing. Neither raises, so both look like "the tenant is empty".

    Normalizing here, at the one place service JSON enters the process, keeps that
    knowledge out of every caller. Idempotent, so an already-camelCase payload (the
    fake, or a future service version) passes through unchanged.

    Nested dicts inside list values (``Attributes``, and the ``FailedItems`` of a sync
    response) get the same treatment one level down, which is as deep as the wire
    shapes go.
    """
    out: dict[str, Any] = {}
    for key, value in row.items():
        name = _camel(key)
        if isinstance(value, list):
            value = [
                {_camel(k): v for k, v in entry.items()}
                if isinstance(entry, dict)
                else entry
                for entry in value
            ]
        out[name] = value
    return out


def _sleep_backoff(attempt: int, policy: RetryPolicy, retry_after: float | None) -> None:
    """Bounded exponential backoff, honoring an explicit ``Retry-After``."""
    if retry_after is not None:
        delay = min(retry_after, policy.max_delay_seconds)
    else:
        delay = min(
            policy.base_delay_seconds * (policy.backoff_multiplier**attempt),
            policy.max_delay_seconds,
        )
    time.sleep(delay)


def with_retry(func, policy: RetryPolicy):  # type: ignore[no-untyped-def]
    """Run ``func`` with retry on transient failures (5xx / timeout / 429).

    A transient sync failure retries with the **same** ``Idempotency-Key``, so the
    service replays its original response -- including the original ``retiredItemIds``
    -- instead of re-running the whole payload. :class:`NonRetryableApiError` -- every
    4xx other than 429, including a duplicate natural key and the per-kind row cap --
    propagates on the first attempt: the service's answer will not change, and burning
    the backoff budget on it only stalls the rest of the pass.
    """
    last_exc: Exception | None = None
    final_attempt = policy.max_attempts - 1
    for attempt in range(policy.max_attempts):
        try:
            return func()
        except NonRetryableApiError:
            raise
        except ThrottledError as exc:
            last_exc = exc
            retry_after: float | None = exc.retry_after
        except InventoryApiError as exc:
            last_exc = exc
            retry_after = None
        # Never back off after the last attempt: the delay is there to space out the
        # *next* try, and there isn't one. Sleeping anyway just adds dead wait to a
        # call that has already failed -- and on the sync, whose backoff is measured in
        # seconds, that wait is long enough to notice.
        if attempt < final_attempt:
            _sleep_backoff(attempt, policy, retry_after)
    assert last_exc is not None
    raise last_exc


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class HttpInventoryClient:
    """``httpx``-backed Inventory API client.

    ``httpx`` is imported lazily so the package -- and the unit tests, which use the
    in-memory fake -- do not hard-require the dependency.
    """

    def __init__(
        self,
        tenant_id: str,
        *,
        config: DiscoveryConfig | None = None,
        auth_token_provider=None,  # callable -> the admin's delegated bearer token
        timeout: float | None = None,  # flat override; otherwise the tiered config
        transport=None,  # httpx transport override; the tests inject a mock
        verify=True,  # False for a local dev tunnel's self-signed certificate
    ) -> None:
        import httpx  # lazy import -- see class docstring

        self._config = config or DiscoveryConfig()
        self._tenant_id = tenant_id
        self._auth_token_provider = auth_token_provider
        self._retry = self._config.retry
        if timeout is None:
            default_timeout = httpx.Timeout(
                self._config.read_timeout_seconds,
                connect=self._config.connect_timeout_seconds,
            )
            # Only the read leg is stretched: a sync that cannot *connect* in 10s is
            # still a dead endpoint, and saying so quickly is the whole value of a
            # separate connect budget.
            self._sync_timeout = httpx.Timeout(
                self._config.sync_timeout_seconds,
                connect=self._config.connect_timeout_seconds,
            )
        else:
            default_timeout = self._sync_timeout = timeout
        self._client = httpx.Client(
            timeout=default_timeout, transport=transport, verify=verify
        )
        self._httpx = httpx

        base = self._config.require_base_url()
        segment = self._config.api_segment.strip("/")
        tenant_literal = quote(tenant_id.replace("'", "''"), safe="")
        self._collection_url = (
            f"{base}/{segment}/tenants('{tenant_literal}')/{self._config.entity_set}"
        )

    # -- plumbing --------------------------------------------------------------------

    def _headers(
        self, *, idem_key: str | None = None, json_body: bool = False
    ) -> dict[str, str]:
        # The skill runs as the admin end-to-end: a delegated bearer token, never a
        # lower-privilege identity.
        headers = {"Accept": "application/json"}
        if json_body:
            # httpx infers this from ``json=``, but the wire format of a request is
            # the caller's contract with the service, not a detail to leave to a
            # library default that a future transport swap could change.
            headers["Content-Type"] = "application/json"
        if self._auth_token_provider is not None:
            headers["Authorization"] = f"Bearer {self._auth_token_provider()}"
        if idem_key is not None:
            headers["Idempotency-Key"] = idem_key
        return headers

    def _raise_for_status(self, resp, url: str, *, natural_key: str = "") -> None:
        """Translate a non-2xx response into the client's error taxonomy."""
        if resp.status_code == 429:
            raise ThrottledError(_parse_retry_after(resp.headers.get("Retry-After")))
        if resp.status_code >= 500:
            raise InventoryApiError(f"{resp.request.method} {url} -> {resp.status_code}")
        if resp.status_code >= 400:
            # 4xx is a non-retryable client error: a schema violation, a duplicate
            # natural key, a missing role, or a cap the payload blew past. There is no
            # 412 arm any more -- writes carry no precondition.
            raise NonRetryableApiError(
                f"{resp.request.method} {url} -> {resp.status_code}: {resp.text}"
            )

    def _item_url(self, item_id: str) -> str:
        return f"{self._collection_url}('{odata_key_literal(item_id)}')"

    # -- surface ---------------------------------------------------------------------

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Page through the tenant's non-retired rows.

        Narrowing is applied client-side. The service already filters out Retired rows
        and materializes the whole tenant partition per call, so an OData ``$filter``
        would buy nothing while adding enum-literal namespacing that varies by
        metadata version.

        Rows are normalized to camelCase before filtering -- see :func:`normalize_row`.
        Filtering the raw PascalCase payload would match nothing and silently return
        an empty list.
        """
        rows: list[dict[str, Any]] = []
        page_size = max(1, min(self._config.list_page_size, 500))
        skip = 0

        while True:
            url = (
                f"{self._collection_url}"
                f"?$top={page_size}&$skip={skip}&$orderby=naturalKey"
            )

            def _do(url: str = url) -> list[dict[str, Any]]:
                try:
                    resp = self._client.get(url, headers=self._headers())
                except self._httpx.HTTPError as exc:
                    raise InventoryApiError(f"GET {url} failed: {exc}") from exc
                self._raise_for_status(resp, url)
                return [normalize_row(r) for r in resp.json().get("value", [])]

            page = with_retry(_do, self._retry)
            rows.extend(page)
            if len(page) < page_size:
                break
            skip += page_size

        if kind is not None:
            rows = [r for r in rows if r.get("kind") == kind.discriminator]
        if environment_id is not None:
            rows = [r for r in rows if (r.get("environmentId") or "") == environment_id]
        return rows

    def sync_inventory(
        self, items: Sequence[InventoryItem], *, run_id: str = ""
    ) -> SyncResult:
        """Submit the tenant's whole inventory as one desired end state.

        The payload is validated client-side first, so a duplicate key or an over-cap
        kind surfaces as a :class:`~tenant_inventory_discovery.mapping.SyncPayloadError`
        naming the offender rather than an opaque 400 -- and, in the empty case, before
        a request that would retire the tenant's entire inventory.
        """
        payload_items = list(items)
        validate_sync_payload(
            payload_items,
            caps=self._config.caps,
            max_items=self._config.max_items_per_sync,
        )

        url = f"{self._collection_url}/{self._config.sync_action}"
        body = {
            "items": [to_sync_entry(i, self._tenant_id) for i in payload_items]
        }
        idem = sync_idempotency_key(payload_items, run_id)

        def _do() -> SyncResult:
            try:
                resp = self._client.post(
                    url,
                    json=body,
                    headers=self._headers(idem_key=idem, json_body=True),
                    timeout=self._sync_timeout,
                )
            except self._httpx.TimeoutException as exc:
                # Name the budget in the message. The failure looks identical to a dead
                # endpoint otherwise, and the two need opposite responses: raise
                # ``sync_timeout_seconds`` versus go fix the service.
                raise InventoryApiError(
                    f"POST {url} did not complete within "
                    f"{self._config.sync_timeout_seconds:g}s while applying "
                    f"{len(payload_items)} item(s). The service may still be "
                    "processing it; re-running is safe. Raise "
                    "sync_timeout_seconds if this recurs."
                ) from exc
            except self._httpx.HTTPError as exc:
                raise InventoryApiError(f"POST {url} failed: {exc}") from exc
            self._raise_for_status(resp, url)
            # The write response is PascalCase too. Normalizing it here means the
            # counts are read from the same key space as every other service payload;
            # skipping it fails silently as zeros, which reads as "nothing happened".
            data = normalize_row(resp.json()) if resp.content else {}
            failed = [
                FailedSyncItem(
                    item_id=str(f.get("itemId") or ""),
                    reason=str(f.get("reason") or ""),
                )
                for f in (data.get("failedItems") or [])
            ]
            return SyncResult(
                submitted_count=int(
                    data.get("submittedCount", len(payload_items))
                ),
                upserted_count=int(data.get("upsertedCount", 0)),
                retired_count=int(data.get("retiredCount", 0)),
                retired_item_ids=list(data.get("retiredItemIds") or []),
                failed_items=failed,
            )

        return with_retry(_do, self._config.sync_retry)

    def probe(self) -> None:
        """Verify the endpoint is reachable and the token is accepted.

        A single ``$top=1`` GET against the tenant collection. Used as a pre-flight so
        the bridge can report an unusable write path *before* a long crawl, rather than
        discovering it when the sync is submitted. Raises the normal error taxonomy
        (:class:`NonRetryableApiError` for 401/403, :class:`InventoryApiError` for
        transport or 5xx failures); returns ``None`` on success.
        """
        url = f"{self._collection_url}?$top=1"

        def _do() -> None:
            try:
                resp = self._client.get(url, headers=self._headers())
            except self._httpx.HTTPError as exc:
                raise InventoryApiError(f"GET {url} failed: {exc}") from exc
            self._raise_for_status(resp, url)

        with_retry(_do, self._retry)

    def close(self) -> None:
        self._client.close()
