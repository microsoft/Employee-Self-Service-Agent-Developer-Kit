# TASK-004 — Dataverse Client

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-004                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | TASK-008                  |

## Description

Implement the Dataverse Web API client (`src/core/outbound/dataverse_client.py`)
— the single layer permitted to communicate with Dataverse. Business logic is
out of scope.

### Design (modelled on `solutions/ess-maker-skills/scripts/auth.py`)

The existing ESS Maker Kit auth.py is a proven reference for Dataverse REST
patterns. The MTK client should replicate these patterns with modern tooling
(`httpx` instead of `requests`, typed returns, no global state):

1. **Per-request token** — accepts `MsalTokenProvider` (TASK-008); calls
   `get_token()` immediately before each HTTP request. Never caches tokens.
2. **OData headers** — `Accept: application/json`, `OData-MaxVersion: 4.0`,
   `OData-Version: 4.0`, `Prefer: odata.include-annotations=*`.
3. **Retry with backoff** — 429/5xx retries (3 attempts, exponential backoff,
   respect `Retry-After`) for **GET only**. Mutating verbs (POST/PATCH/DELETE)
   are NOT auto-retried (unsafe — response-lost scenario).
4. **Pagination** — `@odata.nextLink` auto-follow for `query_all`.
5. **HTTPS-only** — reject non-HTTPS env URLs at construction time.
6. **Typed errors** — 401 → `AuthenticationExpiredError`; 4xx/5xx → typed
   `DataverseApiError` with status, operation, entity, request_id.
7. **Generic entity support** — methods accept entity_set name as a parameter
   (not hardcoded to `botcomponents`). MTK needs bots, botcomponents, solutions,
   msdyn_componentlayers, dependencies, etc.

### API surface

```python
class DataverseClient:
    def __init__(self, env_url: str, token_provider: MsalTokenProvider) -> None: ...

    # Read
    async def query_all(self, entity_set: str, *, select: str, filter: str | None = None) -> list[dict]: ...
    async def get(self, path: str, *, params: dict | None = None) -> dict: ...

    # Write (not auto-retried)
    async def create(self, entity_set: str, data: dict) -> str: ...   # returns record ID
    async def update(self, entity_set: str, record_id: str, data: dict) -> None: ...
    async def delete(self, entity_set: str, record_id: str) -> None: ...
```

**Sync vs async:** Use `httpx.Client` (sync) for now — the MTK is a CLI tool
with sequential pipeline execution. The interface can be made async later
without changing callers (wrap with `asyncio.run` at the orchestrator level).

## Acceptance Criteria

- [ ] `src/core/outbound/dataverse_client.py` implements the typed client.
- [ ] Constructor validates HTTPS-only and stores `env_url` + `token_provider`.
- [ ] `get_token()` called per request (never cached on the client).
- [ ] OData headers set on every request.
- [ ] GET requests retry on 429/5xx (3 attempts, backoff, Retry-After).
- [ ] POST/PATCH/DELETE are NOT auto-retried.
- [ ] `query_all` follows `@odata.nextLink` for full pagination.
- [ ] 401 → `AuthenticationExpiredError` (typed).
- [ ] 4xx/5xx → `DataverseApiError` with status, operation, entity_set.
- [ ] Methods accept entity_set as parameter (generic, not hardcoded).
- [ ] No business or migration logic in this layer.
- [ ] Quality gates pass: `uv run ruff check .`, `uv run mypy src`,
  `uv run pytest -q`.

## Deliverables

- `src/core/outbound/dataverse_client.py` — typed client class
- `src/core/outbound/exceptions.py` — `AuthenticationExpiredError`,
  `DataverseApiError`
- Unit tests under `tests/unit/core/outbound/` with httpx `MockTransport`
  (pagination, retry, error mapping, per-request token)

## References

- 02_ARCHITECTURE/DATAVERSE_CLIENT.md — design spec
- src/core/auth/token_provider.py — MsalTokenProvider (TASK-008)
- solutions/ess-maker-skills/scripts/auth.py — proven Dataverse REST patterns
  (pagination, retry, OData headers, 401 handling, CRUD)
