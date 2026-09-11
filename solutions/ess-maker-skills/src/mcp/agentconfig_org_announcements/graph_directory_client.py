# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Microsoft Graph directory client for audience discovery and metadata.

Graph is a *discovery and metadata* source only. WeveNova remains authoritative
for tenant-local existence and save validity; this client decides which group
categories the kit is willing to author against, which is deliberately narrower
than everything the backend might accept.

Authentication is delegated MSAL using the established Graph Command Line Tools
public client and the ADK ``.local/.token_cache.bin`` cache, anchored to the
solution root so it is the *same* cache `/setup` populates. It is a separate
delegated resource from the AgentConfiguration/WeveNova token: no Graph scope is
added to that token, and no Azure CLI credential is used.

Each instance is bound to the captured authoring tenant and account, not to an
ESS titleId. Resource tokens remain separate; the service owns authorization.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from typing import Any, Iterable, Optional
from uuid import UUID

import httpx
from portalocker.exceptions import LockException

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core"),
)

from base_client import account_for_identity, validate_token_identity  # noqa: E402
from _token_cache import create_token_cache  # noqa: E402


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# The established Microsoft Graph Command Line Tools public client, reused so
# audience discovery needs no new app registration or preauthorization. This is
# the same first-party client the kit's `/setup` and FlightCheck Graph paths
# use, which is what makes a silent (prompt-free) acquisition possible here.
GRAPH_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
GRAPH_SCOPES = ["https://graph.microsoft.com/Directory.Read.All"]

# The one delegated Graph/Dataverse cache the whole ADK shares. It is anchored
# to the *solution root* derived from this module's own location, never to the
# process working directory: this server launches with cwd set to its own MCP
# folder, so a cwd-relative ".local/.token_cache.bin" would mint a third,
# private cache and force a second interactive sign-in for a maker who already
# signed in through `/setup`.
#   .../solutions/ess-maker-skills/src/mcp/agentconfig_org_announcements/<this>
#   parents:                       [3] [2]  [1]     [0]
_SOLUTION_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
_LOCAL_STATE_DIR = os.path.join(_SOLUTION_ROOT, ".local")
GRAPH_TOKEN_CACHE_PATH = os.path.join(_LOCAL_STATE_DIR, ".token_cache.bin")

MAX_ELIGIBLE_RESULTS = 20
MAX_SEARCH_PAGES = 3
GRAPH_PAGE_SIZE = 50
MAX_QUERY_LENGTH = 256

# Graph caps ``$filter`` id lists; batch lookups stay well inside that bound.
_METADATA_BATCH_SIZE = 15

# Every mutation refreshes manager state, which re-resolves the audience of
# every listed bulletin. Without a cache that is one Graph round trip per batch
# per mutation for metadata that changes rarely. The TTL is short so a renamed
# or deleted group self-corrects quickly, and WeveNova — not this cache —
# remains authoritative for save validity.
GROUP_METADATA_TTL_SECONDS = 300.0
GROUP_METADATA_CACHE_MAX_ENTRIES = 512

# Shown when a group carries neither a display name nor a mail address. A raw
# directory ID is never used as a name: it is not human-meaningful and it would
# put a tenant group identifier into the widget's visible surface.
UNNAMED_GROUP_LABEL = "Unnamed group"

_GROUP_SELECT = "id,displayName,mail,mailEnabled,securityEnabled,groupTypes"

# Identifier syntax alone cannot distinguish a provider code from private
# account details. Only these fixed diagnostic categories may reach the log.
_SAFE_MSAL_ERROR_CODES = frozenset(
    {"access_denied", "interaction_required", "consent_required"}
)


class GraphDirectoryError(RuntimeError):
    """Raised when a Graph directory call fails in a way the caller must surface."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool = False,
        http_status: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status


class GraphAuthenticationError(GraphDirectoryError):
    """Raised when no delegated Graph token could be acquired."""

    def __init__(self, message: str):
        super().__init__(message, code="AuthenticationRequired", retryable=False)


def escape_search_value(query: str) -> str:
    """Escape a maker-supplied value for a Graph ``$search`` phrase.

    The value is embedded inside a double-quoted ``displayName:<value>`` phrase,
    so a raw backslash or double quote would terminate or corrupt the phrase.
    Both are backslash-escaped; control characters are rejected outright rather
    than silently stripped, because a stripped query would search for something
    the maker did not type.
    """
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must be a non-empty string")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError(f"query must not exceed {MAX_QUERY_LENGTH} characters")
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in normalized
    ):
        raise ValueError("query must not contain control characters")
    return normalized.replace("\\", "\\\\").replace('"', '\\"')


def is_eligible_group(group: Any) -> bool:
    """Apply the MVP audience eligibility policy.

    Included: non-dynamic security groups, mail-enabled security groups, and
    classic distribution groups. Excluded: Microsoft 365/Unified groups and any
    group whose ``groupTypes`` contains ``DynamicMembership``. Exchange dynamic
    distribution lists are not returned by the Graph groups collection at all,
    so they need no predicate branch.

    This is the single eligibility decision in the server; hydration and search
    both call it so a stored group and a searched group are judged identically.
    """
    if not isinstance(group, dict):
        return False
    if not isinstance(group.get("id"), str) or not group["id"]:
        return False

    group_types = group.get("groupTypes")
    if not isinstance(group_types, list):
        return False
    lowered = {value.lower() for value in group_types if isinstance(value, str)}
    if "unified" in lowered or "dynamicmembership" in lowered:
        return False

    security_enabled = group.get("securityEnabled") is True
    mail_enabled = group.get("mailEnabled") is True
    # Security group (with or without mail), or a classic distribution group.
    return security_enabled or mail_enabled


def to_audience_group(group: dict[str, Any]) -> dict[str, Any]:
    """Project a Graph group into the widget's audience metadata shape.

    The display name falls back through ``displayName`` → ``mail`` →
    :data:`UNNAMED_GROUP_LABEL`. The raw directory ID is deliberately *not* a
    fallback: rendering it as a name shows an opaque GUID where the maker
    expects a group, and it surfaces a tenant directory identifier in the
    widget and in anything that copies the label.
    """
    mail = group.get("mail")
    mail = mail.strip() if isinstance(mail, str) else ""
    display_name = group.get("displayName")
    display_name = display_name.strip() if isinstance(display_name, str) else ""
    return {
        "id": group["id"],
        "displayName": display_name or mail or UNNAMED_GROUP_LABEL,
        "mail": mail or None,
        "isValid": True,
    }


def _validate_graph_token(token: str, tenant_id: str, object_id: Optional[str]) -> str:
    try:
        return validate_token_identity(token, tenant_id, object_id)
    except ValueError as error:
        raise GraphAuthenticationError(
            "Microsoft Graph sign-in must identify the current authoring tenant "
            "and account. Use matching delegated credentials with tid and oid claims."
        ) from error


def acquire_graph_token(tenant_id: str, object_id: Optional[str]) -> str:
    """Acquire a delegated Graph token from the shared ADK cache.

    Silent first, so a maker who already signed in for `/setup` is not prompted
    again; the Graph CLI public client is first-party and FOCI, so a prior
    Dataverse sign-in usually redeems silently. Only when that fails does this
    fall back to MSAL's interactive browser flow.

    Device code is deliberately *not* used. An MCP server speaks JSON-RPC over
    stdio, so printing a device code to stdout corrupts the protocol stream, and
    the maker is already in a desktop session where a browser can open.

    This is blocking (MSAL is synchronous and the interactive flow waits on a
    human). Callers must run it off the event loop.
    """
    tenant_id = str(UUID(tenant_id))
    if not object_id:
        raise GraphAuthenticationError(
            "The authoring account cannot be identified. Audience lookup requires "
            "an AgentConfiguration delegated token with an oid claim."
        )
    token = os.environ.get("GRAPH_ACCESS_TOKEN", "").strip()
    if token:
        return _validate_graph_token(token, tenant_id, object_id)

    import msal

    cache = create_token_cache(GRAPH_TOKEN_CACHE_PATH)
    app = msal.PublicClientApplication(
        GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )

    account = account_for_identity(app, tenant_id, object_id)
    result = (
        app.acquire_token_silent(GRAPH_SCOPES, account=account)
        if account is not None
        else None
    )
    if not result or "access_token" not in result:
        # Logged, never printed: stdout is the MCP transport.
        logging.getLogger("ess-org-announcements.graph").info(
            "Opening a browser for Microsoft Graph sign-in (audience discovery)."
        )
        result = app.acquire_token_interactive(
            GRAPH_SCOPES, prompt="select_account"
        )

    if not isinstance(result, dict) or "access_token" not in result:
        error_code = result.get("error") if isinstance(result, dict) else None
        if not isinstance(error_code, str) or error_code not in _SAFE_MSAL_ERROR_CODES:
            error_code = "unknown_error"
        logging.getLogger("ess-org-announcements.graph").warning(
            "Microsoft Graph sign-in failed (%s).", error_code
        )
        raise GraphAuthenticationError(
            "Microsoft Graph sign-in failed. Sign in with the authoring account."
        )
    return _validate_graph_token(result["access_token"], tenant_id, object_id)


class _GroupMetadataCache:
    """A bounded, TTL'd in-process cache of resolved group metadata.

    Only *successful* resolutions are cached. A negative entry would pin a group
    that was just created, just consented to, or just made eligible as invalid
    for the whole TTL, which the maker would experience as an audience they
    cannot add; re-querying the small set of unresolved IDs is the cheaper
    mistake.

    Insertion-ordered with FIFO eviction so a long-running server cannot grow
    without bound. Guarded by a lock because ``resolve_groups`` may be awaited
    concurrently.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = GROUP_METADATA_TTL_SECONDS,
        max_entries: int = GROUP_METADATA_CACHE_MAX_ENTRIES,
    ):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        # Monotonic: a wall-clock adjustment must not resurrect or expire
        # entries early.
        return time.monotonic()

    def get(self, group_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            entry = self._entries.get(group_id)
            if entry is None:
                return None
            expires_at, metadata = entry
            if expires_at <= self._now():
                del self._entries[group_id]
                return None
            return dict(metadata)

    def put(self, group_id: str, metadata: dict[str, Any]) -> None:
        with self._lock:
            expires_at = self._now() + self._ttl
            # Re-insert so a refreshed entry moves to the newest position and
            # FIFO eviction stays meaningful.
            self._entries.pop(group_id, None)
            self._entries[group_id] = (expires_at, dict(metadata))
            while len(self._entries) > self._max_entries:
                self._entries.pop(next(iter(self._entries)))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class GraphDirectoryClient:
    """Bounded, deterministic Graph group search and metadata hydration."""

    def __init__(
        self,
        *,
        tenant_id: str,
        object_id: Optional[str],
        transport: Optional[httpx.AsyncBaseTransport] = None,
        access_token: Optional[str] = None,
        metadata_cache: Optional["_GroupMetadataCache"] = None,
    ):
        self._logger = logging.getLogger("ess-org-announcements.graph")
        self._tenant_id = str(UUID(tenant_id))
        self._object_id = object_id
        # Deliberately NOT acquired here. Constructing the client must stay a
        # pure, non-blocking operation: the server builds it lazily from a tool
        # call, and acquiring a token in __init__ would run a blocking MSAL
        # sign-in (and possibly open a browser) inside the asyncio event loop,
        # stalling every other in-flight request and the MCP stdio transport.
        self._token = (
            _validate_graph_token(access_token.strip(), self._tenant_id, self.object_id)
            if access_token else ""
        )
        self._token_lock = asyncio.Lock()
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._metadata_cache = (
            metadata_cache if metadata_cache is not None else _GroupMetadataCache()
        )
        self.timeout = 30.0

    def __repr__(self) -> str:
        return f"<{type(self).__name__} base_url={GRAPH_BASE_URL!r}>"

    @property
    def tenant_id(self) -> str:
        """The captured authoring tenant; a tenant change requires a new instance."""
        return self._tenant_id

    @property
    def object_id(self) -> Optional[str]:
        """The captured account; changing identity requires a separate cache/client."""
        return self._object_id

    async def _access_token(self) -> str:
        """Return the delegated token, acquiring it once, off the event loop.

        ``acquire_graph_token`` is synchronous and can block for as long as a
        human takes to complete an interactive sign-in, so it runs in a worker
        thread. The lock makes concurrent first calls share one sign-in instead
        of racing two browser prompts.
        """
        if self._token:
            return self._token
        async with self._token_lock:
            if not self._token:
                try:
                    token = await asyncio.to_thread(
                        acquire_graph_token, self.tenant_id, self.object_id
                    )
                except (LockException, OSError) as error:
                    # Keep persistence failures inside the feature's normal error
                    # contract, especially when hydration follows a committed write.
                    raise GraphAuthenticationError(
                        "Microsoft Graph sign-in could not be completed. Try again."
                    ) from error
                self._token = _validate_graph_token(token, self.tenant_id, self.object_id)
        return self._token

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            token = await self._access_token()
            # Another first caller may have constructed it while we awaited auth.
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=GRAPH_BASE_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "ConsistencyLevel": "eventual",
                    },
                    timeout=self.timeout,
                    verify=True,
                    transport=self._transport,
                    follow_redirects=False,
                )
        return self._client

    async def aclose(self) -> None:
        async with self._token_lock:
            client = self._discard_credentials()
        if client is not None and not client.is_closed:
            await client.aclose()

    def _discard_credentials(self) -> Optional[httpx.AsyncClient]:
        self._token = ""
        client, self._client = self._client, None
        # A late request may still hold this old cache. Replace, rather than
        # merely clear it, so its completion cannot populate fresh credentials.
        self._metadata_cache.clear()
        self._metadata_cache = _GroupMetadataCache()
        return client

    async def _invalidate_credentials(self, failed_token: str) -> None:
        """Drop an access token Graph has rejected, and the client holding it.

        A cached access token eventually expires. The MCP server keeps one
        process-global Graph client, so without this a single 401 would poison
        every later audience lookup until the server was restarted — the maker's
        only recovery would be reloading the whole MCP host.

        The clear is a compare-and-swap against ``failed_token``: a concurrent
        caller may already have completed a fresh acquisition between the
        request going out and the 401 coming back, and wiping *that* token would
        throw away a good credential and force a needless second sign-in.

        The ``httpx.AsyncClient`` is dropped too, not just the token, because
        the bearer is baked into its default headers at construction: keeping it
        would keep sending the dead token no matter what ``_token`` says.
        """
        async with self._token_lock:
            if failed_token and self._token != failed_token:
                # Someone already refreshed; their token is still good.
                return
            client = self._discard_credentials()

        # Closed outside the lock: aclose() awaits connection teardown and must
        # not hold up a concurrent re-acquisition.
        if client is not None and not client.is_closed:
            await client.aclose()

    async def _get(
        self, url: str, params: Optional[dict[str, Any]] = None,
        *, client: Optional[httpx.AsyncClient] = None,
    ) -> dict[str, Any]:
        if client is None:
            client = await self._ensure_client()
        if client.is_closed:
            raise GraphAuthenticationError(
                "Microsoft Graph sign-in was reset. Try the request again to sign in."
            )
        request_token = client.headers["Authorization"].removeprefix("Bearer ")
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 401:
                # Expired or revoked credential. Invalidate so the *next* call
                # re-runs silent-first acquisition, which usually refreshes from
                # the shared cache with no prompt at all.
                #
                # The failed request is deliberately NOT replayed here. These
                # are idempotent GETs so a replay would be safe, but
                # re-acquisition can fall through to an interactive browser
                # sign-in, and blocking an in-flight tool call on a surprise
                # prompt is worse than returning a clear, actionable
                # AuthenticationRequired the maker can act on. The next call
                # succeeds silently in the common case.
                await self._invalidate_credentials(request_token)
                raise GraphDirectoryError(
                    "Microsoft Graph rejected the cached sign-in. Try the "
                    "request again to sign in.",
                    code="AuthenticationRequired",
                    retryable=False,
                    http_status=status,
                ) from error
            if status == 403:
                raise GraphDirectoryError(
                    "Microsoft Graph denied the directory request. "
                    "Directory.Read.All requires tenant consent and may be "
                    "blocked by Conditional Access.",
                    code="AuthorizationDenied",
                    retryable=False,
                    http_status=status,
                ) from error
            raise GraphDirectoryError(
                f"Microsoft Graph returned HTTP {status}.",
                code="SearchUnavailable",
                retryable=status in (429, 502, 503, 504),
                http_status=status,
            ) from error
        except httpx.RequestError as error:
            raise GraphDirectoryError(
                "Microsoft Graph could not be reached.",
                code="NetworkError",
                retryable=True,
            ) from error

        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise GraphDirectoryError(
                "Microsoft Graph returned an unexpected directory response.",
                code="SearchUnavailable",
                retryable=False,
            )
        return payload

    async def search_groups(self, query: str) -> dict[str, Any]:
        """Search groups, returning at most 20 eligible, deduplicated results.

        Paging stops at 20 eligible results, at result-set exhaustion, or after
        three pages, whichever comes first. ``exhausted`` distinguishes an
        exhausted result set from a search that stopped at the page cap, so the
        caller never reports "no more matches" for a capped search.
        """
        escaped = escape_search_value(query)
        client = await self._ensure_client()
        params: Optional[dict[str, Any]] = {
            "$search": f'"displayName:{escaped}" OR "mail:{escaped}"',
            "$select": _GROUP_SELECT,
            "$count": "true",
            "$top": str(GRAPH_PAGE_SIZE),
        }
        url = "/groups"

        groups: list[dict[str, Any]] = []
        seen: set[str] = set()
        pages = 0
        exhausted = False

        while pages < MAX_SEARCH_PAGES:
            payload = await self._get(url, params, client=client)
            pages += 1
            for item in payload["value"]:
                if not is_eligible_group(item):
                    continue
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                # Graph's relevance order is preserved; dedupe keeps the first
                # occurrence so repeated runs return the same ordering.
                groups.append(to_audience_group(item))
                if len(groups) >= MAX_ELIGIBLE_RESULTS:
                    return {
                        "groups": groups,
                        "exhausted": False,
                        "pagesExamined": pages,
                    }

            next_link = payload.get("@odata.nextLink")
            if not isinstance(next_link, str) or not next_link:
                exhausted = True
                break
            # The nextLink already carries every query option; re-sending params
            # would duplicate them.
            url = next_link
            params = None

        return {
            "groups": groups,
            "exhausted": exhausted,
            "pagesExamined": pages,
        }

    async def resolve_groups(
        self, group_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        """Resolve display metadata for a deduplicated set of group IDs.

        Deduplication applies only to the lookup batch. The caller re-expands
        the result against each bulletin's canonical audience list so per-item
        order and multiplicity stay exact.

        Results already held in the bounded TTL cache are served without a Graph
        round trip; only the remaining IDs are batched. A Graph failure
        propagates and leaves the cache untouched, so a transient outage cannot
        poison later lookups.

        Any ID that Graph does not return, or that resolves to an ineligible
        group category, is omitted from the result. The caller marks it
        ``isValid: false`` and keeps the ID.
        """
        unique = [
            group_id
            for group_id in dict.fromkeys(group_ids)
            if isinstance(group_id, str) and group_id
        ]
        if not unique:
            return {}

        client = await self._ensure_client()
        metadata_cache = self._metadata_cache

        resolved: dict[str, dict[str, Any]] = {}
        pending: list[str] = []
        for group_id in unique:
            cached = metadata_cache.get(group_id)
            if cached is None:
                pending.append(group_id)
            else:
                resolved[group_id] = cached

        for start in range(0, len(pending), _METADATA_BATCH_SIZE):
            batch = pending[start : start + _METADATA_BATCH_SIZE]
            clause = " or ".join(
                f"id eq '{group_id}'"
                for group_id in batch
                if _is_safe_filter_id(group_id)
            )
            if not clause:
                continue
            payload = await self._get(
                "/groups",
                {"$filter": clause, "$select": _GROUP_SELECT, "$top": str(len(batch))},
                client=client,
            )
            for item in payload["value"]:
                if is_eligible_group(item):
                    metadata = to_audience_group(item)
                    resolved[item["id"]] = metadata
                    metadata_cache.put(item["id"], metadata)

        return resolved


def _is_safe_filter_id(group_id: str) -> bool:
    """Reject any ID that could break out of an OData string literal.

    Directory object IDs are GUIDs, so a value containing a quote, a control
    character, or a backslash is not a real ID; skipping it keeps the filter
    well-formed and the ID is still reported as invalid downstream.
    """
    if "'" in group_id or "\\" in group_id:
        return False
    return not any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in group_id
    )


def build_audience_metadata(
    audience_ids: list[str], resolved: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expand canonical audience IDs into order-preserving display metadata.

    The output is one-to-one with ``audience_ids`` and in the same order, which
    the widget's schema enforces. An unresolved or ineligible ID keeps its
    position and is marked invalid; its display name falls back to a neutral
    placeholder so a raw group ID is never rendered as a name.
    """
    metadata: list[dict[str, Any]] = []
    for group_id in audience_ids:
        group = resolved.get(group_id)
        if group is None:
            metadata.append(
                {
                    "id": group_id,
                    "displayName": "Unavailable group",
                    "mail": None,
                    "isValid": False,
                }
            )
        else:
            metadata.append(dict(group))
    return metadata
