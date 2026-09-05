# Tenant Inventory — Discovery Skill (ADK)

Admin-run crawler that enumerates a tenant's shared agent resources across **eight
kinds**, assembles them into a single `InventoryItem` payload, and submits that payload
to the **WeveNova Inventory API** as one whole-inventory `syncInventory` call.

This is the ADK-side implementation of the *Tenant Inventory — Discovery Skill
Implementation Spec*. The schemas, routes, caps, and validation order in this package are
**mirrored from the live WeveNova service** (`AgentConfigurationInventoryItemsController`
and friends), so the wire contract is pinned rather than assumed. The platform surfaces
still ship as Protocols with in-memory fakes for testing.

> **The payload is the tenant.** `syncInventory` retires anything Active that the
> payload omits. There is no per-item delete and no server-side guardrail, so every
> safety property lives in this client. Read [Absence is the delete
> verb](#absence-is-the-delete-verb) before changing anything in the write path.

## Layout

```
src/tenant_inventory_discovery/
  models.py            # Kind enum, ScopeKey, InventoryItem, natural-key composition (§4, §5)
  schemas.py           # per-kind attribute schemas + caps, mirrored from the server
  mapping.py           # resource -> InventoryItem -> sync entry + payload validation (§4.1, §8)
  config.py            # tunable page size, retry, endpoints, lock TTL (§8)
  inventory_client.py  # WeveNova client Protocol + HttpInventoryClient (real routes)
  in_memory_inventory.py # in-memory InventoryClient: --local-only dry-runs + tests
  recording.py         # decorator that captures applied items so the mirror works live
  local_store.py       # durable local inventory mirror: cross-run merge (server-faithful)
  platform_clients.py  # BAP/Dataverse/Graph/Copilot Studio surfaces + FakePlatform
  crawlers/            # the eight per-kind crawlers, declarative (§4)
  runner.py            # enumerate -> map -> per-scope coverage verdict (§5-§7)
  progress.py          # live run narration + heartbeat (keeps a long crawl visibly alive)
  discovery_skill.py   # lifecycle facade: correlation id, lock, run, carry-forward, sync (§5.1)
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

The in-memory one reproduces the service's *observable* semantics — whole-inventory sync
(absence retires, parents written before children, the environment/children invariant
surfacing as `failedItems`), soft delete, the 50-row cap, duplicate-key rejection, 24h
idempotency replay. That fidelity is the point: it is what let the suite catch a
cross-run idempotency replay silently suppressing a write. A laxer stub would have
passed.

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

All three routes are implemented in `HttpInventoryClient`, rooted on the tenant shard
(`{base}/api/beta/tenants('{tenantId}')/agentConfigurationInventoryItems`):

| Op | Route | Notes |
|---|---|---|
| List | `GET {collection}` | `$top` capped at 500; Retired rows already excluded |
| Read | `GET {collection}('{id}')` | id = `{Kind}:{escaped naturalKey}` |
| Sync | `POST {collection}/syncInventory` | 200; whole inventory; `Idempotency-Key` cached 24h |

The per-item `POST`, the `DELETE`-by-id retire, and the bulk `reconcile` action are all
**gone**, along with every `ETag` / `If-Match` precondition. There is no per-row revision
to carry, because the request no longer describes a row — it describes the tenant.

Three details are easy to get wrong and are pinned by tests in `tests/test_http_client.py`:

- **`attributes` is an array of `{key, value}` entries**, never a JSON object — a plain
  dictionary binds to a list of empty objects on an OData entity type. Every value is a
  string; Boolean/Integer-typed keys are coerce-validated server-side.
- **No top-level `connectorId`.** An unknown top-level field binds the whole body to
  `null` and yields a 400. The connector edge travels as an *attribute*.
- **`items` is the only accepted body key.** Any other key is a field-targeted
  `ValidationError`, not a warning.

## Absence is the delete verb

The service takes the tenant's entire inventory and reconciles reality to it:

```http
POST .../agentConfigurationInventoryItems/syncInventory
Idempotency-Key: <guid>
{ "items": [ /* every row, all kinds mixed, any order */ ] }
```
```json
{ "submittedCount": 12, "upsertedCount": 12, "retiredCount": 2,
  "retiredItemIds": [...], "failedItems": [{ "itemId": "...", "reason": "..." }] }
```

Server-managed fields (`source`, `submittedById`, `createdAt`, `updatedAt`, `etag`, the
id) are ignored inbound, so **a row from `GET` can be posted straight back**. That single
property is what makes the safety design below possible.

### The failure direction inverted

Under the old reconcile contract the client named what to delete, so a crawl that
under-reported retired **too little** — drift lingered for a pass. Under sync, a crawl
that under-reports retires **too much** — it silently deletes every resource it failed to
mention. The service was asked for a guardrail and declined, so the entire safety story
is client-side.

This matters here more than for most callers, because **the ESS kit deliberately crawls
one environment** — the one bound during `/setup`. A naive payload built from that crawl
would describe one environment and retire every other environment in the tenant.

### The guardrail: complete the payload, don't refuse to send it

`DiscoverySkill._carry_forward` runs between the crawl and the sync. It lists the
service's current rows and appends, verbatim, every Active row this run cannot vouch for.
A scope the crawl did not cover contributes its **existing rows** instead of an absence,
so "I didn't look there" costs nothing.

Refusing to sync would have been the other option, but it would mean the kit could never
write at all. Completing the payload lets a narrow crawl stay useful and safe.

### Which absences count as deletions

`ScopeReport.authoritative` decides, and it is deliberately stricter than "did the scope
finish". A scope may retire by absence only if it is `complete` (read without error,
fully paged, nothing unmappable), `covered` (the platform claims tenant-wide reach for
that kind), and not `capped` (nothing was truncated away — truncated rows were never
sent, so treating them as absent would delete live resources).

`covered` comes from `PlatformSurface.tenant_wide_kinds()`, which **defaults to nothing**:
a surface that has not thought about the question is exactly the one whose absences must
not be trusted. Note this is *not* `Kind.is_tenant_root` — that flag says where a row is
filed, not how much was looked at. In the kit those differ sharply:

| Kind | Source | Tenant-wide? |
|---|---|---|
| `EntraApp` | Graph `/applications` | **yes** — absence is a real deletion |
| `Environment` | the one env in `.local/config.json` | no — carried forward |
| `Connector` | derived from that env's connections | no — carried forward |
| `SharePointSite` | only sites this agent's knowledge sources cite | no — carried forward |
| env-scoped kinds | the crawled environment | yes, **inside that environment only** |

The cost is accepted and one-directional: a resource deleted in an environment the kit
never looks at is never cleaned up. That is the safe failure.

### When the sync is withheld entirely

Two cases leave the tenant untouched rather than risk it. Both exit `2` from the CLI and
report `syncWithheldNote`:

1. **The current inventory could not be read.** Without it there is nothing to carry
   forward, so the payload would be a guess.
2. **The payload is empty.** `{"items": []}` is legal to the service and retires the
   whole tenant.

A third case is self-healing: if the service returns a row whose `kind` this build does
not recognize, the sync is withheld, because a row that cannot be represented cannot be
promised. Upgrading the client clears it.

### Caps, and who loses when they bind

`validate_sync_payload` rejects client-side before sending: **400 items** per call
(`50 × 8 kinds`), **50 per kind**, duplicate `kind:naturalKey` (a hard reject, not
last-one-wins), and the per-field lengths. When a kind overflows after carry-forward,
`_fit_to_caps` drops **observed** rows and keeps **carried** ones. That reads backwards —
the observed rows are fresher — but only one direction is destructive: omitting a carried
row *retires* a resource that exists, while omitting an observed row merely defers
recording it. The service holds at most 50 per kind, so the carried set alone can never
overflow and this always converges.

### Why `run_id` is still in the idempotency key

The service replays a cached response for 24h. Because the payload's *absences* now carry
meaning, replaying a cached response would leave newly-appeared drift unreconciled until
the cache aged out. Keying on the run as well as the payload keeps each pass distinct
while still making a timed-out retry of the *same* pass a no-op.

## Service behaviours the client absorbs

These were all found by running against the live service; every one of them had passed
mock-based tests, because the in-memory fake did not model them.

| Behaviour | What the client does |
|---|---|
| Responses are **PascalCase** (`NaturalKey`, `Source`, `ETag`), not camelCase | `normalize_row()` rewrites keys once at the HTTP boundary — for reads *and* for the sync response, whose counts would otherwise silently read as zero. This one never raised: it emptied every `kind=` filter, so nothing was ever found. `test_wire_shape.py` pins a verbatim captured payload. |
| **GET by key 404s** for any id containing percent-escapes (`SharePointSite:https%3A%2F%2F…`) | Rows are read from the collection listing rather than by key. |
| Ids are **rewritten** on the way out: `%3A` decoded to `:`, `/` encoded to `%2F` | A submitted id never equals the returned id for those keys, so nothing is ever matched on a client-composed id — `(kind, naturalKey)` round-trips verbatim and is unique (`Environment` and `ExtensionPack` both key on `env-prod`). |
| A 200 may carry `failedItems` | Partial success, not failure. Usually a child whose environment the payload omits. Logged and corrected on the next sync. |

## Known limits (server-side, not fixable here)

| Item | Impact |
|---|---|
| `ManageAgentConfigurationFromAuthorizedApp` admits only the Sydney app id | This CLI cannot mint its own token for the live service. Supply one instead — see [Local development against the dev tunnel](#local-development-against-the-dev-tunnel). |
| `MaxItemsPerTenantAndKind = 50` | The runner stops at 50 rows per kind and marks the scope `capped`, which also makes it non-authoritative so the truncated rows are never mistaken for deletions. |
| `flowCount` needs the BAP admin surface | Omitted from `ExtensionPack` rather than guessed. |

`ExtensionPack` has no pack identity in the server schema, so its natural key is the
`environmentId` alone — one row per environment describing what is installed.

## Concurrency and progress

The crawl is eight paged enumerations behind a token mint and a retry budget, followed by
a single large POST, so it runs for minutes and is almost entirely I/O. Two things follow.

**One request, but a shared MCP connection.** Writes go through `_StdioJsonRpc`, which
**multiplexes**: a single reader thread owns stdout and routes each reply to the waiter
that asked for it, by id. A transport that instead scans the pipe for its own id and
discards the rest will consume another caller's reply and hang it forever — which is
exactly the bug that made `/discover` stop mid-run. `tests/test_mcp_inventory.py` pins
this against a server that deliberately answers out of order. Requests are also bounded by
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

### Timeouts are tiered, and the sync is the outlier

One flat timeout cannot serve both a paged `GET` and the whole-inventory `POST`. The
sync drives up to `max_items_per_sync` server-side writes plus the retirement sweep in a
single request, and routinely runs for **minutes**. Holding it to a read-sized budget is
what turns a *working* sync into a timeout, a retry, and a re-POST of the entire payload
onto a service that was already busy applying the first one.

| Budget | Default | Covers |
|---|---|---|
| `connect_timeout_seconds` | 10s | A host that is down should say so in seconds, sync or not. |
| `read_timeout_seconds` | 30s | Ordinary calls — the paged list, the probe. |
| `sync_timeout_seconds` | 600s | The one whole-inventory POST. |
| `DEFAULT_REQUEST_TIMEOUT` (MCP) | `sync_timeout_seconds` + 120s | The RPC that *wraps* the POST. |

The last row is a layering rule, not a number: the MCP budget is **derived** from the
HTTP one so it can never be equal. The server runs the HTTP call inside the RPC, and
whichever budget expires first owns the error the user sees — the inner one names the
payload size and the knob to turn, the outer one can only say the server went quiet.
Equal budgets race, and the race loses the better message.

Retries are tiered for the same reason. `retry` (5 attempts) is right for a cheap
re-read; `sync_retry` (2) is right for a call that re-sends the whole payload, where the
read budget would pile ~50 minutes of duplicated work onto a merely-slow service. One
retry still rides out a dropped connection, and because it reuses the `Idempotency-Key`
a server that *did* finish replays its original answer instead of applying the payload
twice. Neither policy backs off after its final attempt — that delay spaces out a try
that never happens.

### The redundant sync is skipped

The sync is the expensive call, and the overwhelmingly common case is a re-run over a
tenant that has not changed. `_is_unchanged` compares the finished payload against the
inventory **already fetched for carry-forward**, so proving the write redundant costs no
extra request, and skips the POST when they match.

Comparison is on the **wire form** (`to_sync_entry`), not the objects: a locally
observed attribute may be an `int` where the service echoes `"5"`, and the wire form is
exactly what the service will compare. Two payloads that serialize identically are
indistinguishable to it, so posting one over the other is provably a no-op.

It is conservative by construction — anything that does not compare equal, including a
state this build cannot model, falls through to the sync. The failure mode is a
redundant write, never a skipped one. That asymmetry is deliberate: a redundant sync
wastes minutes, while a wrongly-skipped one leaves the tenant wrong *and* makes the next
run compare against the same wrong state and skip again.

A skipped run still reports `synced_ok`, because the guarantee it ends with is the one a
real sync provides: the server's state **is** the payload. That is what lets the local
mirror refresh off it rather than stranding on a stale picture. `RunSummary` distinguishes
the two with `sync_unchanged` (nothing needed doing) versus `sync_blocked_reason`
(something was wrong) — an optimization and a safety stop must never read alike.

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
   tunnel: a full crawl submits every row and re-runs are idempotent.
3. Provide a durable `RunLock` (the file lock is a single-host interim; use a
   distributed lock for multi-host).

## Core invariants enforced here (spec §3, §5-§7)

- **Idempotent by `(kind, naturalKey)`** — re-asserting a resource overwrites in place;
  env-scoped kinds compose `environmentId` so cross-environment names never collide.
- **Only an authoritative scope may retire** — a scope's absences count as deletions only
  if it enumerated fully with no fatal error, nothing unmappable, no truncation, *and*
  the platform declares tenant-wide reach for that kind. Everything else is carried
  forward verbatim.
- **A run only removes what it looked at** — a partial crawl, a crashed run, and an
  unreadable inventory all leave the tenant untouched rather than retire by omission.
- **Never submit an empty payload** — it is legal to the service and means "retire
  everything".
- **Non-retryable failures fail fast** — a 4xx other than 429 (schema violation, missing
  role, row cap, duplicate key) raises `NonRetryableApiError` and skips the backoff
  budget entirely.

## Local inventory mirror (`local_store.py`)

The server (WeveNova) is authoritative, but each run also merges its results into a durable
local mirror (the kit writes it to `.local/inventory.json`). `build_document()` is pure and
mirrors the service's rules, which under whole-inventory sync collapse into one decision
taken **per run** rather than per scope:
- **The sync succeeded** — the payload *was* the tenant, so rows it carried are refreshed
  and rows it omitted are retired. Retired rows are kept for **one** run
  (`state:"Retired"` + `retiredAt`), then pruned. Carried-forward rows are in the payload,
  so they stay Active and the mirror stays whole.
- **The sync did not happen** (withheld, degraded, or aborted) — the tenant did not
  change, so the prior mirror is preserved verbatim and this run's observations are
  **discarded**. Showing them would assert a state that was never written, and the next
  successful sync re-observes them anyway.

Each record carries `firstSeenAt` (carried forward across runs) and `lastSeenAt`. All file
I/O and the `.local/config.json` pointer live in the kit bridge, not in this module.

