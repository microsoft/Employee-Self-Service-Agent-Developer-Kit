"""Inventory API client: the write/read surface the skill depends on.

Routes (OData containment under the ``tenants`` entity set)::

    GET    {c}                        list non-retired rows ($filter/$top/$skip/$orderby)
    GET    {c}('{id}')                read one row by its opaque kind:naturalKey id
    POST   {c}                        upsert (201 + ETag, Idempotency-Key, If-Match)
    DELETE {c}('{id}')                soft-delete: transition the row to Retired
    POST   {c}/reconcile              retire-on-drift for one (kind, environmentId) scope

    where {c} = {base}/api/beta/tenants('{tenantId}')/agentConfigurationInventoryItems

**Reconcile is watermark-based, not set-based.** The caller supplies
``passStartedAt``; the service retires every Active, ``Source = Discovered`` row in the
scope whose ``UpdatedAt`` predates it. Two consequences shape the client:

1. ``passStartedAt`` must be captured *before* the first enumeration, and every
   observed row must be re-upserted during the pass so its ``UpdatedAt`` moves past
   the watermark. An unchanged row still needs its write.
2. The service **rejects tenant-rooted kinds** (Environment, EntraApp, Connector,
   SharePointSite) because a tenant-wide crawl has no provable completeness boundary.
   Drift for those kinds is swept client-side via list + diff + :meth:`retire`.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from .config import DiscoveryConfig, RetryPolicy
from .errors import (
    InventoryApiError,
    NonRetryableApiError,
    PreconditionFailedError,
    ThrottledError,
)
from .mapping import idempotency_key, to_request_body
from .models import InventoryItem, Kind, ReconcileResult, UpsertResult


@runtime_checkable
class InventoryClient(Protocol):
    """The Inventory surface the runner and skill depend on."""

    def upsert(
        self, item: InventoryItem, *, if_match: str | None = None, run_id: str = ""
    ) -> UpsertResult:
        """Idempotent upsert of one row, keyed by ``(kind, naturalKey)``.

        ``run_id`` scopes the ``Idempotency-Key`` to the current pass so retries
        dedupe but a later pass still bumps the row's ``UpdatedAt``.
        """
        ...

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List the tenant's non-retired rows, optionally narrowed to a scope."""
        ...

    def retire(self, item_id: str, *, if_match: str | None = None) -> None:
        """Soft-delete one row by its opaque id. Idempotent for an already-retired row."""
        ...

    def reconcile(
        self, kind: Kind, environment_id: str, pass_started_at: datetime
    ) -> ReconcileResult:
        """Retire drift in one (kind, environmentId) scope, using a start-of-pass watermark."""
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
    ``Attributes: [{Key, Value}]``. Every consumer here -- the drift sweep, the local
    mirror, the in-memory fake -- was written against camelCase. Left unnormalized the
    mismatch is *silent*: ``row.get("source")`` is None rather than ``"Discovered"``,
    so the drift sweep skips every row and nothing is ever retired; and
    ``list_items(kind=...)`` filters on a key that does not exist and returns nothing.
    Neither raises, so both look like "the tenant is empty".

    Normalizing here, at the one place service JSON enters the process, keeps that
    knowledge out of every caller. Idempotent, so an already-camelCase payload (the
    fake, or a future service version) passes through unchanged.
    """
    out: dict[str, Any] = {}
    for key, value in row.items():
        name = _camel(key)
        if name == "attributes" and isinstance(value, list):
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

    Transient upsert failures retry with the **same** ``Idempotency-Key``, so a replay
    is safe. :class:`NonRetryableApiError` -- every 4xx other than 429, including the
    412 stale-ETag case and the per-kind row cap -- propagates on the first attempt:
    the service's answer will not change, and burning the backoff budget on it only
    stalls the rest of the pass.
    """
    last_exc: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return func()
        except NonRetryableApiError:
            raise
        except ThrottledError as exc:
            last_exc = exc
            _sleep_backoff(attempt, policy, exc.retry_after)
        except InventoryApiError as exc:
            last_exc = exc
            _sleep_backoff(attempt, policy, None)
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
        timeout: float = 30.0,
        transport=None,  # httpx transport override; the tests inject a mock
        verify=True,  # False for a local dev tunnel's self-signed certificate
    ) -> None:
        import httpx  # lazy import -- see class docstring

        self._config = config or DiscoveryConfig()
        self._tenant_id = tenant_id
        self._auth_token_provider = auth_token_provider
        self._retry = self._config.retry
        self._client = httpx.Client(
            timeout=timeout, transport=transport, verify=verify
        )
        self._httpx = httpx

        # Populated lazily, the first time the service demands an If-Match. None means
        # "not yet fetched", which is distinct from "fetched and empty".
        self._etag_cache: dict[tuple[str, str], str | None] | None = None
        self._id_index: set[str] = set()
        self._etag_lock = threading.Lock()

        base = self._config.require_base_url()
        segment = self._config.api_segment.strip("/")
        tenant_literal = quote(tenant_id.replace("'", "''"), safe="")
        self._collection_url = (
            f"{base}/{segment}/tenants('{tenant_literal}')/{self._config.entity_set}"
        )

    # -- plumbing --------------------------------------------------------------------

    def _headers(
        self, *, idem_key: str | None = None, if_match: str | None = None
    ) -> dict[str, str]:
        # The skill runs as the admin end-to-end: a delegated bearer token, never a
        # lower-privilege identity.
        headers = {"Accept": "application/json"}
        if self._auth_token_provider is not None:
            headers["Authorization"] = f"Bearer {self._auth_token_provider()}"
        if idem_key is not None:
            headers["Idempotency-Key"] = idem_key
        if if_match is not None:
            headers["If-Match"] = if_match
        return headers

    def _raise_for_status(self, resp, url: str, *, natural_key: str = "") -> None:
        """Translate a non-2xx response into the client's error taxonomy."""
        if resp.status_code == 412:
            raise PreconditionFailedError(natural_key or url)
        if resp.status_code == 429:
            raise ThrottledError(_parse_retry_after(resp.headers.get("Retry-After")))
        if resp.status_code >= 500:
            raise InventoryApiError(f"{resp.request.method} {url} -> {resp.status_code}")
        if resp.status_code >= 400:
            # 4xx other than 412/429 is a non-retryable client error: a schema
            # violation, a missing role, or the per-kind row cap.
            raise NonRetryableApiError(
                f"{resp.request.method} {url} -> {resp.status_code}: {resp.text}"
            )

    def _item_url(self, item_id: str) -> str:
        return f"{self._collection_url}('{odata_key_literal(item_id)}')"

    def _index(self) -> tuple[dict[tuple[str, str], str | None], set[str]]:
        """The tenant's current rows, indexed once per client for writes.

        Returns ``(etags_by_kind_and_natural_key, canonical_item_ids)``.

        Deliberately *not* a GET by key: the service's key routing 404s on any id
        containing percent-escapes, and no client-side encoding reaches it. The
        collection listing carries the same data and needs no key routing.

        ETags are keyed on ``(kind, naturalKey)`` rather than the item id, because the
        service rewrites ids into its own canonical form on the way out -- ``%3A``
        decoded back to ``:``, ``/`` encoded to ``%2F`` -- so a submitted id never
        equals the returned id for those keys. ``naturalKey`` round-trips verbatim, and
        the pair is unique (``Environment`` and ``ExtensionPack`` both key on
        ``env-prod``).
        """
        with self._etag_lock:
            if self._etag_cache is None:
                rows = self.list_items()
                self._etag_cache = {
                    (row["kind"], row["naturalKey"]): row.get("etag")
                    for row in rows
                    if row.get("kind") and row.get("naturalKey")
                }
                self._id_index = {
                    row["agentConfigurationInventoryItemId"]
                    for row in rows
                    if row.get("agentConfigurationInventoryItemId")
                }
            return self._etag_cache, self._id_index

    def _etag_for(self, kind: str, natural_key: str) -> str | None:
        """Current ETag for a row, or None if the service does not have it."""
        etags, _ = self._index()
        return etags.get((kind, natural_key))

    def _remember_etag(self, kind: str, natural_key: str, etag: str | None) -> None:
        """Keep the cache current so a second write to the same row in one pass works."""
        if not etag:
            return
        with self._etag_lock:
            if self._etag_cache is not None:
                self._etag_cache[(kind, natural_key)] = etag

    @staticmethod
    def _demands_if_match(resp) -> bool:
        """Does this 400 mean "the row exists, send its ETag"?

        The service refuses a blind write over an existing row: an upsert without
        ``If-Match`` is answered 400 with ``Target: If-Match``. That is not a schema
        error and must not be reported as one.
        """
        if resp.status_code != 400:
            return False
        return "if-match" in (resp.text or "").lower()

    # -- surface ---------------------------------------------------------------------

    def upsert(
        self, item: InventoryItem, *, if_match: str | None = None, run_id: str = ""
    ) -> UpsertResult:
        url = self._collection_url
        body = to_request_body(item)
        idem = idempotency_key(item, run_id)

        def _post(etag: str | None):
            try:
                return self._client.post(
                    url,
                    json=body,
                    headers=self._headers(idem_key=idem, if_match=etag),
                )
            except self._httpx.HTTPError as exc:  # network/timeout -> transient
                raise InventoryApiError(f"POST {url} failed: {exc}") from exc

        def _do() -> UpsertResult:
            resp = _post(if_match)

            # A discovery pass asserts current truth, so it writes blind and lets the
            # service tell it when a row already exists. Re-reading every row up front
            # would double the request count for the common create case; re-reading
            # only on this 400 costs one extra GET per pre-existing row. Without it a
            # second pass cannot update anything it created in the first.
            if if_match is None and self._demands_if_match(resp):
                current = self._etag_for(item.kind.discriminator, item.natural_key)
                if current is not None:
                    resp = _post(current)

            self._raise_for_status(resp, url, natural_key=item.natural_key)

            payload = normalize_row(resp.json()) if resp.content else {}
            etag = resp.headers.get("ETag") or payload.get("etag")
            self._remember_etag(item.kind.discriminator, item.natural_key, etag)
            return UpsertResult(
                natural_key=item.natural_key,
                kind=item.kind,
                item_id=(
                    payload.get("agentConfigurationInventoryItemId") or item.item_id
                ),
                etag=etag,
                created=resp.status_code == 201,
            )

        return with_retry(_do, self._retry)

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

    def retire(self, item_id: str, *, if_match: str | None = None) -> None:
        url = self._item_url(item_id)

        def _do() -> None:
            try:
                resp = self._client.delete(
                    url, headers=self._headers(if_match=if_match)
                )
            except self._httpx.HTTPError as exc:
                raise InventoryApiError(f"DELETE {url} failed: {exc}") from exc
            if resp.status_code == 404:
                # Retire is a soft delete and idempotent by contract, so an absent row
                # is success -- but a 404 is also what key routing returns for an id
                # containing percent-escapes, and that row is still very much there.
                # Swallowing both would report a retire that never happened, so confirm
                # the row is really gone before claiming so.
                _, current_ids = self._index()
                if item_id not in current_ids:
                    return
                raise InventoryApiError(
                    f"DELETE {url} -> 404 but {item_id!r} is still listed; "
                    "the service could not resolve this key"
                )
            self._raise_for_status(resp, url, natural_key=item_id)

        with_retry(_do, self._retry)

    def reconcile(
        self, kind: Kind, environment_id: str, pass_started_at: datetime
    ) -> ReconcileResult:
        """Invoke the collection-bound ``reconcile`` action for one scope.

        The service accepts only env-scoped kinds and rejects a future watermark, so
        ``pass_started_at`` is normalized to UTC before being sent.
        """
        url = f"{self._collection_url}/{self._config.reconcile_action}"
        if pass_started_at.tzinfo is None:
            pass_started_at = pass_started_at.replace(tzinfo=timezone.utc)
        payload = {
            "kind": kind.discriminator,
            "environmentId": environment_id,
            "passStartedAt": pass_started_at.astimezone(timezone.utc).isoformat(),
        }

        def _do() -> ReconcileResult:
            try:
                resp = self._client.post(url, json=payload, headers=self._headers())
            except self._httpx.HTTPError as exc:
                raise InventoryApiError(f"POST {url} failed: {exc}") from exc
            self._raise_for_status(resp, url)
            data = resp.json() if resp.content else {}
            return ReconcileResult(
                kind=kind,
                environment_id=environment_id,
                evaluated_count=int(data.get("evaluatedCount", 0)),
                retired_count=int(data.get("retiredCount", 0)),
                retired_item_ids=list(data.get("retiredItemIds") or []),
            )

        return with_retry(_do, self._retry)

    def probe(self) -> None:
        """Verify the endpoint is reachable and the token is accepted.

        A single ``$top=1`` GET against the tenant collection. Used as a pre-flight so
        the bridge can report an unusable write path *before* a long crawl, rather than
        discovering it on the first upsert. Raises the normal error taxonomy
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
