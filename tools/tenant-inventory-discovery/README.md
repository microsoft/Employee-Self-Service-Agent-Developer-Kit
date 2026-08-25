# Tenant Inventory — Discovery Skill (ADK)

Admin-run crawler that enumerates a tenant's shared agent resources across **eight
kinds** and writes each as one idempotent `InventoryItem` to the **WeveNova Inventory
API**, then triggers a **scoped server-side reconcile** so the tenant picture stays
current on every re-run.

This is the ADK-side implementation of the *Tenant Inventory — Discovery Skill
Implementation Spec*. The schemas, routes, caps, and validation order in this package are
**mirrored from the live WeveNova service** (`AgentConfigurationInventoryItemsController`
and friends), so the wire contract is pinned rather than assumed. The platform surfaces
still ship as Protocols with in-memory fakes for testing.

## Layout

```
src/tenant_inventory_discovery/
  models.py            # Kind enum, ScopeKey, InventoryItem, natural-key composition (§4, §5)
  schemas.py           # per-kind attribute schemas + caps, mirrored from the server
  mapping.py           # resource -> InventoryItem -> wire body (§4.1, §8)
  config.py            # tunable page size, concurrency, retry, endpoints, lock TTL (§8)
  inventory_client.py  # WeveNova client Protocol + HttpInventoryClient (real routes)
  in_memory_inventory.py # in-memory InventoryClient: --local-only dry-runs + tests
  recording.py         # decorator that captures applied items so the mirror works live
  local_store.py       # durable local inventory mirror: cross-run merge (server-faithful reconcile)
  platform_clients.py  # BAP/Dataverse/Graph/Copilot Studio surfaces + FakePlatform
  crawlers/            # the eight per-kind crawlers, declarative (§4)
  runner.py            # enumerate -> map -> upsert -> completeness gate (§5-§7)
  progress.py          # live run narration + heartbeat (keeps a long crawl visibly alive)
  discovery_skill.py   # lifecycle facade: correlation id, lock, run, reconcile, telemetry (§5.1)
  lock.py              # per-tenant single-flight run lock (interim D6 mitigation, §7)
  telemetry.py         # structured run-summary event (§8)
  mcp_inventory.py     # InventoryClient over the local WeveNova MCP server (stdio JSON-RPC)
  __main__.py          # CLI (uses fakes by default)
tests/                 # the §10 test matrix + HTTP-level contract tests
```

## Run the demo / tests

```bash
cd tools/tenant-inventory-discovery
python -m pip install -e ".[dev]"      # or: pip install pytest ruff
python -m pytest                        # runs the §10 matrix against the in-memory fakes
python -m tenant_inventory_discovery --tenant-id contoso --verbose
```

The tests never touch the network: lifecycle tests run against `InMemoryInventoryClient`
(via the `SpyInventoryClient` subclass in `tests/spies.py`, which adds call counters),
and `tests/test_http_client.py` drives the real `HttpInventoryClient` through an `httpx`
mock transport.

### Three implementations of one Protocol

`InventoryClient` has three real implementations, and none is a throwaway stub:

| | `HttpInventoryClient` | `McpInventoryClient` | `InMemoryInventoryClient` |
|---|---|---|---|
| Storage | the live WeveNova service | the live service, via a local MCP server | a dict |
| Auth | caller supplies a token | the server resolves its own | none |
| Used by | `--direct` | the **default** write path | `--local-only` opt-out, degraded runs, `__main__`, tests |

The in-memory one reproduces the service's *observable* semantics — watermark reconcile,
tenant-root rejection, soft delete, the 50-row cap, 24h idempotency replay. That fidelity
is the point: it is what let the suite catch a cross-run idempotency replay silently
defeating watermark reconcile. A laxer stub would have passed.

Call counters used only by assertions live in `tests/spies.py`, not in the shipped class.

### The MCP write path (the default)

`McpInventoryClient` does not speak HTTP. It spawns
`solutions/ess-maker-skills/src/mcp/wevenova/server.py` and talks JSON-RPC to it over
stdio, and *that* server holds the `HttpInventoryClient`. Two reasons this indirection
earns its keep, and why it is the default:

- **The token never enters the crawler.** The server resolves one itself, in order:
  `WEVENOVA_ACCESS_TOKEN`, then the gitignored `.local/wevenova_token` file, then a
  Windows PowerShell 5.1 `New-WeveTeamsClientToken` mint. It caches the result in memory
  and re-resolves once on a 401. Nothing to paste, and no token in a shell history or a
  `.env`. **This is the only path that reads the token file** — `--direct` does not.
- **The self-signed dev certificate is handled in one place.** The server defaults to
  not verifying TLS because the tunnel's certificate is self-signed; the crawler keeps
  its safe default of verifying.

HTTP correctness is not duplicated — the server delegates to the same
`HttpInventoryClient` the direct path uses, so URL shape, idempotency keys, ETag
handling, and the retry policy have exactly one implementation.

The `{"ok": …}` envelope every tool returns carries the exception *type* plus
`naturalKey` / `retryAfter`, and the client rebuilds the real exception from it. That is
what keeps the runner's retry, drift, and abort behaviour identical on both paths.

```bash
pip install -r solutions/ess-maker-skills/src/mcp/wevenova/requirements.txt

python solutions/ess-maker-skills/scripts/discover_inventory.py \
  --tenant-id {TENANT_ID} \
  --json-out workspace/discover/results.json
```

`--via-mcp` predates this becoming the default and is now a no-op, still accepted so
existing commands keep working. `--direct` opts out and calls the API from the crawler
process, which then needs its own token: `WEVENOVA_ACCESS_TOKEN`, else an interactive
MSAL sign-in. Because the app id that flow can obtain is not admitted by
`ManageAgentConfigurationFromAuthorizedApp`, `--direct` generally degrades — which is
exactly why it is not the default. If the server cannot start or cannot reach the API,
the run degrades to the local mirror and exits `2`, same as the direct path.

The server can also be pointed elsewhere, or handed a token directly, through its
environment: `WEVENOVA_BASE_URL`, `WEVENOVA_ACCESS_TOKEN`, `WEVENOVA_VERIFY_TLS`. The
bridge only forwards a base URL you asked for explicitly — never its own production
default, which would otherwise silently redirect an MCP run at production.

#### If your machine is not TDS-paired

`New-WeveTeamsClientToken` needs a paired machine (`Test-TdsMachinePair` must return
`True`). Insomnia works without pairing because it *replays* a token rather than minting
one, so a working Insomnia setup does not imply minting works.

The server resolves a token in this order:

1. `WEVENOVA_ACCESS_TOKEN`
2. the token file — `solutions/ess-maker-skills/.local/.wevenova_token`, overridable
   with `WEVENOVA_TOKEN_FILE`
3. `New-WeveTeamsClientToken` via Windows PowerShell 5.1

So the unblock is to paste the same token you use in Insomnia into that file:

```powershell
# .local/ is gitignored. A leading "Bearer " and a UTF-8 BOM are both tolerated.
Set-Content solutions/ess-maker-skills/.local/.wevenova_token '<token>'
```

The file is re-read on every mint, not cached at startup, so refreshing it mid-crawl is
picked up by the automatic 401 retry instead of failing the rest of the run. `Set-TdsMachinePair`
remains the permanent fix — once paired, no file is needed.

## The Inventory API surface

All five routes are implemented in `HttpInventoryClient`, rooted on the tenant shard
(`{base}/api/beta/tenants('{tenantId}')/agentConfigurationInventoryItems`):

| Op | Route | Notes |
|---|---|---|
| List | `GET {collection}` | `$top` capped at 500; Retired rows already excluded |
| Read | `GET {collection}('{id}')` | id = `{Kind}:{escaped naturalKey}` |
| Upsert | `POST {collection}` | 201 + `ETag`; `Idempotency-Key` cached 24h; `If-Match` |
| Retire | `DELETE {collection}('{id}')` | 204; soft delete; idempotent |
| Reconcile | `POST {collection}/reconcile` | collection-bound OData action |

Three details are easy to get wrong and are pinned by tests in `tests/test_http_client.py`:

- **`attributes` is an array of `{key, value}` entries**, never a JSON object — a plain
  dictionary binds to a list of empty objects on an OData entity type. Every value is a
  string; Boolean/Integer-typed keys are coerce-validated server-side.
- **No top-level `connectorId`.** An unknown top-level field binds the whole body to
  `null` and yields a 400. The connector edge travels as an *attribute*.
- **The item id is percent-encoded twice.** The id already contains encoded natural-key
  segments, so the route segment must re-encode it (`odata_key_literal`) or `%3A`
  collapses back to `:` and the lookup misses.

## Reconcile is watermark-based

The service does **not** accept a set of observed keys. The caller supplies
`passStartedAt`, and the service retires every Active, `Source = Discovered` row in the
`(kind, environmentId)` scope whose `UpdatedAt` predates it. Two consequences shape this
package:

1. **Every observed row must be re-upserted each pass**, even when unchanged, so its
   `UpdatedAt` moves past the watermark. This is why `idempotency_key()` mixes in the
   `run_id`: a run-independent key would let the 24h idempotency cache *replay* the write
   for an unchanged resource, leaving `UpdatedAt` behind the watermark and getting a live
   row retired.
2. **Tenant-rooted kinds cannot use it.** The service rejects `Environment`, `EntraApp`,
   `Connector`, and `SharePointSite` because a tenant-wide crawl has no provable
   completeness boundary. `DiscoverySkill._sweep_tenant_root` handles their drift
   client-side: list, diff against what the pass observed, `DELETE` the remainder.

The watermark is also backdated by `clock_skew_allowance_seconds` (default 300), because
it is a *client* timestamp compared against *server*-stamped values — a fast client clock
would otherwise retire rows the crawl just wrote.

## Service behaviours the client absorbs

These were all found by running against the live service; every one of them had passed
mock-based tests, because the in-memory fake did not model them.

| Behaviour | What the client does |
|---|---|
| Responses are **PascalCase** (`NaturalKey`, `Source`, `ETag`), not camelCase | `normalize_row()` rewrites keys once at the HTTP boundary. This one never raised — it silently emptied every `kind=` filter and made the drift sweep skip every row, so nothing was ever retired. `test_wire_shape.py` pins a verbatim captured payload. |
| A write over an **existing** row is rejected `400 {"Target": "If-Match"}` | The upsert posts blind, and on that specific 400 re-posts once with the row's current ETag. Without it a first crawl succeeded (all creates) and every later crawl updated nothing. `If-Match: *` is *not* accepted — the service answers 412. |
| **GET/DELETE by key 404s** for any id containing percent-escapes (`SharePointSite:https%3A%2F%2F…`) | No client-side encoding reaches it, so ETags are read from the collection listing instead, indexed once per pass. |
| Ids are **rewritten** on the way out: `%3A` decoded to `:`, `/` encoded to `%2F` | A submitted id never equals the returned id for those keys, so the ETag index is keyed on `(kind, naturalKey)` — which round-trips verbatim and is unique (`Environment` and `ExtensionPack` both key on `env-prod`). |

Because of the key-routing limit, `retire()` cannot treat a 404 as "already gone" on
faith: it confirms the row is absent from the listing first, and otherwise raises so the
sweep logs it and does *not* count the row as retired. Env-scoped kinds are retired by
the server's `reconcile` action and are unaffected.

## Known limits (server-side, not fixable here)

| Item | Impact |
|---|---|
| `ManageAgentConfigurationFromAuthorizedApp` admits only the Sydney app id | This CLI cannot mint its own token for the live service. Supply one instead — see [Local development against the dev tunnel](#local-development-against-the-dev-tunnel). |
| `MaxItemsPerTenantAndKind = 50` | The runner guards client-side: it stops at 50 rows per kind, marks the scope `capped` + incomplete, and skips reconcile so nothing is wrongly retired. |
| No batch upsert; the service counts rows per create | Upsert concurrency is deliberately low (`max_concurrency = 4`). |
| `flowCount` needs the BAP admin surface | Omitted from `ExtensionPack` rather than guessed. |

`ExtensionPack` has no pack identity in the server schema, so its natural key is the
`environmentId` alone — one row per environment describing what is installed.

## Concurrency and progress

A crawl is one POST per discovered row behind a token mint and a retry budget, so it
runs for minutes and is almost entirely I/O. Two things follow from that.

**The upsert pool shares one MCP connection.** `runner._upsert_all` writes through a
`ThreadPoolExecutor`, so several threads issue JSON-RPC requests over the same stdio
pipe at once. `_StdioJsonRpc` therefore **multiplexes**: a single reader thread owns
stdout and routes each reply to the waiter that asked for it, by id. A transport that
instead scans the pipe for its own id and discards the rest will consume another
thread's reply and hang that thread forever — which is exactly the bug that made
`/discover` stop mid-run. `tests/test_mcp_inventory.py::TestConcurrentCalls` pins this
against a server that deliberately answers out of order. Requests are also bounded by
`DEFAULT_REQUEST_TIMEOUT`, so a server that never answers fails loudly instead of
hanging.

The MCP server side matters too: FastMCP runs a **sync** tool inline on its event loop,
so a blocking HTTP call there stalls every other in-flight request. The WeveNova tools
are `async` and offload their blocking work with `anyio.to_thread.run_sync`.

**The run narrates itself.** `progress.py` turns run events into human-readable lines,
and a background heartbeat prints an elapsed-time line whenever nothing has been written
for `DEFAULT_HEARTBEAT_SECONDS`. Silence is what makes a long run look wedged, so this
is a behaviour, not a nicety — reporters must also never raise into the crawl, and
`ConsoleProgressReporter` swallows its own write errors. `NullProgressReporter` is the
default, so library and test behaviour is unchanged.

Narration goes to **stderr**. Stdout stays reserved for the single result JSON object
the `/discover` skill parses.

## Local development against the dev tunnel

The API is not deployed anywhere yet — the controller lives on an unmerged branch — so
the default production origin has no such route. To exercise it against a local service
through the `HttpTunnel`:

```powershell
# 1. Supply a token. Easiest: drop a bearer token (no "Bearer " prefix) into
#    solutions/ess-maker-skills/.local/wevenova_token -- gitignored, and read on
#    every call, so refreshing it mid-crawl is picked up. WEVENOVA_ACCESS_TOKEN
#    takes precedence if set.
#
#    Alternatively mint one, if this machine is paired. Must be Windows PowerShell
#    5.1: the Dev.* modules use System.Net.ICertificatePolicy, which does not exist
#    on .NET Core. The AppId is Apps.Sydney -- the only app id admitted by
#    ManageAgentConfigurationFromAuthorizedApp. The extra wid is Global Administrator.
$env:WEVENOVA_ACCESS_TOKEN = & powershell.exe -NoProfile -Command {
  Import-Module Dev.Weve
  New-WeveTeamsClientToken -UserName default `
    -AppId 'fb8d773d-7ef8-4ec0-a117-179f88add510' `
    -Permissions 'Analytics.Read','Analytics.ReadWrite' `
    -AdditionalWids '62e90394-69f5-4237-9190-012177145e10'
}

# 2. Crawl and persist through the tunnel.
python scripts/discover_inventory.py --tenant-id <tenantId> `
  --base-url https://localhost:444/weveb2
```

Prerequisites: the TDS VPN is connected and `https://localhost:444/sts` returns 200.
Minting additionally needs the machine to be paired — check with `Test-TdsMachinePair`,
which returns `False` until `Set-TdsMachinePair` has been run. Note that a working
Insomnia setup does **not** imply minting works: Insomnia *replays* a token, it does not
mint one.

**TLS against the tunnel.** The tunnel serves a self-signed certificate. PowerShell and
Insomnia validate against the Windows certificate store and accept it; `httpx` validates
against `certifi` and rejects it with `CERTIFICATE_VERIFY_FAILED`. That failure happens
before any request is sent, so it looks like the service is unreachable when it is only
a trust-store difference.

Verification therefore follows the *target*, not a flag: a loopback host
(`localhost`, `127.0.0.1`, `::1`) is not verified, and every other host is. Traffic to
this machine never reaches a network, so there is no position from which to intercept
it — while a real host still gets a full certificate check. `--insecure-skip-tls-verify`
remains available to force verification off against a non-local host, and warns when
used that way. `WEVENOVA_VERIFY_TLS` overrides the rule in either direction.

Reading the pre-flight result:

| Pre-flight | Meaning |
| --- | --- |
| `CERTIFICATE_VERIFY_FAILED` | The target is not loopback and its certificate is untrusted. Check the base URL first; `--insecure-skip-tls-verify` forces past it. |
| `401` | Route resolved and the service is running; the token is missing or invalid. |
| `403` | Token is valid but the app id is not admitted by the authorization policy. |
| `404` | Wrong base URL, or the branch with the controller is not running. |

## Wiring for production

1. Replace `FakePlatform` with bindings to the ADK's existing tenant-platform client
   layer (BAP, Dataverse, Microsoft Graph, Copilot Studio). **Do not add new SDKs if a
   client already exists** (spec §2). Each enumerator must **page to completion**.
2. Construct `HttpInventoryClient` with the default origin (or `--base-url` /
   `WEVENOVA_BASE_URL`) and an `auth_token_provider` that yields the **admin's
   delegated** bearer token (spec §8) — the skill runs as admin end-to-end and never
   writes with a lower-privilege identity. Done, and verified end to end against the dev
   tunnel: a full crawl upserts every row and re-runs are idempotent.
3. Provide a durable `RunLock` (the file lock is a single-host interim; use a
   distributed lock for multi-host).

## Core invariants enforced here (spec §3, §5-§7)

- **Idempotent by `(kind, naturalKey)`** — re-asserting a resource overwrites in place;
  env-scoped kinds compose `environmentId` so cross-environment names never collide.
- **Completeness gates reconcile** — a scope reconciles only if it enumerated fully with
  no fatal error and did not hit the row cap; a partial or crashed run never triggers
  reconcile (recrawl instead).
- **Tenant-root exemption** — a subset-of-environments run never marks tenant-root kinds
  complete, so their client-side sweep stays inert.
- **Non-retryable failures fail fast** — a 4xx other than 429 (schema violation, missing
  role, row cap, stale `If-Match`) raises `NonRetryableApiError` and skips the backoff
  budget entirely.

## Local inventory mirror (`local_store.py`)

The server (WeveNova) is authoritative, but each run also merges its results into a durable
local mirror (the kit writes it to `.local/inventory.json`). `build_document()` is pure and
applies the **same per-scope reconcile the server would**, keyed off
`RunSummary.completed_scopes` (which already encodes the tenant-root exemption):
- **Reconciled scope** (in `completed_scopes`) — observed items are refreshed and drift
  (prior keys not observed) is retired. Retired rows are kept for **one** run
  (`state:"Retired"` + `retiredAt`), then pruned.
- **Complete-but-exempt scope** (fully enumerated, no error, but tenant-root during a subset
  crawl) — observed items are refreshed; prior items are **kept**, never retired.
- **Incomplete / not-crawled scope** — prior items are preserved untouched, so a partial
  crawl never wipes the mirror.

Each record carries `firstSeenAt` (carried forward across runs) and `lastSeenAt`. All file
I/O and the `.local/config.json` pointer live in the kit bridge, not in this module.

