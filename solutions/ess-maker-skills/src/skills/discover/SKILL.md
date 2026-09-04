# Discover Skill

Tenant inventory discovery — the **admin-run crawler**. Enumerates the tenant's
shared agent resources across **eight kinds** (Environment, EntraApp, Connector,
Connection, SharePointSite, KnowledgeSource, ExtensionPack, ScenarioTemplate),
assembles them into one payload, and submits the tenant's whole inventory in a single
request so the tenant picture stays current on every re-run.

The heavy lifting lives in the standalone crawler package at
`tools/tenant-inventory-discovery/`. This skill drives it via
`scripts/discover_inventory.py` and renders the results JSON.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## Start

Before checking the setup state, show:

**Message:**

First, I'll confirm that setup is complete and identify the Power Platform
environment configured for discovery.

**End message.**

Read `.local/config.json` to confirm setup is complete and get the tenant/agent
context. If setup is not complete, show:

**Message:**

You need to run `/setup` first before discovering your tenant inventory.

**End message.**

Stop here.

If setup is complete, proceed.

---

## Step 1: Run the crawl

Discovery always crawls the **single environment configured during `/setup`**
(`dataverseEndpoint` in `.local/config.json`). There is no scope choice to make and
no full-tenant crawl — do not ask the user which environments to crawl.

Before running the crawl, show:

**Message:**

Setup is ready. Next, I'll verify access to the inventory destination and scan
the configured environment for environments, app registrations, connectors,
connections, SharePoint sites, knowledge sources, extension packs, and scenario
templates. You may be asked to sign in or approve access while this runs.

This usually takes a few minutes, and it prints its progress as it goes, so you
can watch it work.

**End message.**

> **This command is expected to run for minutes, not seconds.** It reads eight resource
> types across several platform APIs. It reports progress continuously (see "Reading the
> live progress output" below), so treat ongoing output as healthy — do not cancel it,
> re-run it, or tell the user it has stalled while progress or heartbeat lines are still
> arriving. Wait for the process to exit and parse the final JSON line on stdout.

> **What runs today.** The default crawl enumerates **all eight kinds** live for the
> configured environment, using your admin sign-in (a browser window may open the first
> time to authenticate; Microsoft Graph and Copilot Studio may each prompt a separate
> consent the first time):
>
> - **Dataverse** — `Connection`, `ExtensionPack`, `ScenarioTemplate` (and the
>   `Environment` identity, from config).
> - **Microsoft Graph** — `EntraApp` (the tenant's app registrations) and `SharePointSite`
>   (only the sites referenced by the agent's SharePoint knowledge sources).
> - **Power Platform (BAP) admin** — `Connector` (the distinct connectors used by the
>   environment's connections).
> - **Copilot Studio** — `KnowledgeSource` (the agent bot's knowledge sources).
>
> If any kind's platform call fails (e.g. a missing role or consent), just that kind's
> scope is reported as **Incomplete**. Its existing rows are re-sent unchanged so nothing
> is removed for it, and the rest of the run still succeeds.
>
> **The write path is wired to the real WeveNova Inventory API and persisting is the
> default** — a discovery pass exists to update the tenant inventory:
>
> - default — persist to WeveNova through the local MCP server, which resolves its own
>   token (`WEVENOVA_ACCESS_TOKEN`, else the saved `.local/wevenova_token` file, else a
>   local mint) and targets `https://substrate.office.com/weveb2`. Override the origin
>   with `--base-url` (or `WEVENOVA_BASE_URL`) for other rings or a dev tunnel.
> - `--direct` — call the Inventory API from this process instead. Acquires its own
>   token and does **not** read the saved token file.
> - `--local-only` — explicit opt-out: crawl, validate, and update the local mirror
>   without contacting WeveNova.
>
> The live path is pre-flighted before the crawl. If the endpoint is unreachable or the
> token is rejected, the run **degrades**: it finishes the crawl, mirrors locally, sets
> `writeDegraded: true` with a reason, and exits `2`. It never silently claims to have
> persisted (see "Writing to WeveNova" below).
>
> Use `--demo` to exercise the full eight-kind lifecycle against representative
> sample data instead of hitting Dataverse.

Run from the `solutions/ess-maker-skills` directory.

- **Python launcher:** Commands below use `python`. If it is unavailable, use
  `py -3` on Windows or `python3` on macOS/Linux with the same arguments.

Live Dataverse crawl of the configured environment (persists to WeveNova by default):

```
python scripts/discover_inventory.py --tenant-id {TENANT_ID} --json-out workspace/discover/results.json
```

Offline demo (no sign-in, sample data, all eight kinds):

```
python scripts/discover_inventory.py --tenant-id {TENANT_ID} --demo --local-only --json-out workspace/discover/results.json
```

### Reading the live progress output

A live crawl reads eight resource types across several platform APIs, so it can run for
several minutes. The command narrates itself on **stderr** as it goes — the phase it is
in, each resource type as it is read (`reading connections...`, `found 12 connections`),
and finally a single save step (`>> Saving the tenant picture: N resource(s) in one
request`). If a single call is slow (token mint, retry backoff), a heartbeat line
(`... still saving 137 resource(s) to the inventory (30s elapsed)`) is emitted so the
output never goes silent for more than ten seconds.

**The save step is one large request and normally takes minutes.** It does all the
writing and all the retiring for the whole run, and it cannot be split — under the
whole-inventory contract each chunk would retire everything not in it. The command says
so itself before it starts waiting. Treat heartbeat lines during this phase as healthy.
Do **not** cancel the run, re-run it, or report it as hung while they are arriving.

If the tenant has not changed since the last run, the command skips the request entirely
and prints `inventory already matches all N resource(s) -- nothing to save, skipping the
request`. That is a success, not a failure.

This narration is progress only. The machine-readable result is still the **single JSON
object on stdout**, which is the only thing to parse. Do not treat a heartbeat or a
progress line as the result, and do not report the run as hung while these lines are
still arriving.

Use `--quiet` to suppress the narration, or `--heartbeat-seconds N` to change the
silence budget (`0` disables the heartbeat).

### Writing to WeveNova

Persisting is the default, so no extra flag is needed. To target a non-production ring
or a dev tunnel:

```
python scripts/discover_inventory.py --tenant-id {TENANT_ID} \
  --base-url https://{wevenova-host} --json-out workspace/discover/results.json
```

Writes go through the local MCP server (`src/mcp/wevenova/server.py`), which resolves
the bearer token in this order:

1. `WEVENOVA_ACCESS_TOKEN`
2. the saved token file — `.local/wevenova_token` or `.local/.wevenova_token`
   (gitignored, both spellings accepted). Paste the same token used in Insomnia there;
   a leading `Bearer ` is tolerated. It is re-read on every attempt, so refreshing an
   expired token mid-crawl is picked up by the 401 retry.
3. a local `New-WeveTeamsClientToken` mint, which needs Windows PowerShell 5.1 and a
   TDS-paired machine (check with `Test-TdsMachinePair`).

On success `writePath` is reported as `mcp:{host}`.

### `--direct`, and why it is not the default

`--direct` calls the Inventory API from the crawler process. It acquires its own token
from `WEVENOVA_ACCESS_TOKEN`, else an interactive MSAL sign-in against the kit's shared
token cache — it does **not** read the saved token file.

**Expect `--direct` to degrade.** The service's
`ManageAgentConfigurationFromAuthorizedApp` policy admits only the Sydney first-party
app id, so a token acquired by this CLI is rejected with 403. The run still completes
and the local mirror is still updated, but it exits `2` and reports the write as failed.
That is precisely why the MCP path is the default. `--direct` conflicts with both
`--via-mcp` and `--local-only`.

`--via-mcp` predates the flip and is now a no-op, still accepted so existing commands
keep working.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Crawl succeeded and the inventory was updated (or `--local-only` was requested). |
| `1` | The run aborted. Nothing was written; the local mirror was left untouched. |
| `2` | The crawl succeeded but the inventory was **not** updated — either the write path failed (`writePathNote`) or the sync was withheld for safety (`syncWithheldNote`). Nothing was deleted either way. |

The script prints a one-line status and writes the full results to
`workspace/discover/results.json`. The JSON always carries a `discovered` block (the
resources read this run, grouped by kind), a `writePath` field, and a `writeDegraded`
boolean. Whenever `writePath` is `local-only` — whether requested via `--local-only` or
forced by a degraded write — a `writePathNote` explains what happened. Say so plainly
when presenting results; **never imply the tenant inventory was updated on the server
unless `writePath` is a host (or `mcp:{host}`) and `writeDegraded` is `false`.**

On a successful (non-aborted) run the script also updates a **durable local inventory
mirror** at `.local/inventory.json` (override with `--inventory-out`). This file is the
persistent picture of the tenant: it is merged across runs using the same whole-inventory
rules the server uses — a successful sync refreshes everything the payload carried and
retires what it omitted (kept one run as `state:"Retired"`, then pruned), while a run that
did not write preserves the prior picture untouched. Each record carries
`firstSeenAt`/`lastSeenAt`.
The server (WeveNova) remains the source of truth; this file is a local cache. An aborted
run never overwrites it. The script also drops a best-effort `inventoryPath` pointer into
`.local/config.json`.

If the status line is `"status": "aborted"`, show:

**Message:**

Discovery didn't finish, so nothing was changed in your inventory. This is safe —
the crawl only updates the inventory when it completes fully. Let's try again.

**End message.**

Then stop and offer to re-run.

---

## Step 2: Present the results

Before reading and presenting the results, show:

**Message:**

The discovery run has finished. I'll now review each resource type, confirm what
was recorded, and identify anything that could not be read or updated safely.

**End message.**

Read `workspace/discover/results.json` with your file-reading tool and format the
summary yourself, directly in the chat reply. Do NOT write or run any script to
parse the JSON.

First show the header line:

**Message:**

Here's what I found in your tenant (run `{correlationId}`):

**End message.**

Then render a table with one row per crawled scope, sorted with tenant-wide
resources first (empty `environmentId`), then grouped by environment. Map each
`kind` to a friendly label:

| Kind (JSON) | Friendly label |
|---|---|
| Environment | Environments |
| EntraApp | App registrations |
| Connector | Connectors |
| Connection | Connections |
| SharePointSite | SharePoint sites |
| KnowledgeSource | Knowledge sources |
| ExtensionPack | Extension packs |
| ScenarioTemplate | Scenario templates |

Table columns — read each from the `scopes[]` entries:

| Scope | Resource | Found | Recorded | Status |
|-------|----------|-------|----------|--------|

- **Scope** = `Tenant-wide` when `environmentId` is empty, otherwise the
  `environmentId`.
- **Resource** = friendly label for `kind`.
- **Found** = `enumerated`.
- **Recorded** = `mapped`.
- **Status** = `Complete` when `complete` is `true`; otherwise
  `Incomplete — kept as-is` (and include the `error` text if present).

After the table, show a one-line summary from `totals`:

**Message:**

Recorded **{totals.mapped}** resources across **{totals.kindsCrawled}** resource types.

**End message.**

If `sync.retired` is greater than zero, add:

**Message:**

I also removed **{sync.retired}** resource(s) that no longer exist in your
tenant since the last discovery.

**End message.**

If `sync.blockedReason` is non-empty, the inventory was **not** updated. Say so plainly
and do not present the run as saved:

**Message:**

⚠️ I read your tenant but did **not** save the results: {sync.blockedReason}

Nothing was changed or deleted. Re-run `/discover` once that is resolved.

**End message.**

If `sync.unchanged` is `true`, the run **succeeded** — the tenant already matched what
was stored, so the write was skipped as redundant. This is not a withhold and not a
failure; never report it with a ⚠️ or alongside `sync.blockedReason`, which is empty in
this case.

**Message:**

✅ Your inventory is already up to date — I checked all **{sync.submitted}**
resource(s) and nothing has changed since the last discovery, so there was nothing
to save.

**End message.**

---

## Step 3: Handle incomplete scopes

If any scope has `complete: false`, show:

**Message:**

I found one or more resource types that need attention. I'll preserve their
existing inventory entries and explain what should be retried.

**End message.**

Then show:

**Message:**

Some resource types couldn't be fully read this time, so I left them untouched
rather than risk removing valid entries. Re-running discovery will pick them up.

**End message.**

Offer to re-run `/discover`.

### `EntraApp` incomplete because the tenant has more app registrations than the cap

`EntraApp` no longer depends on `/connect` having run — discovery enumerates the
tenant's app registrations directly from Microsoft Graph, so a tenant that has only
run `/setup` still gets a real reading.

The usual reason it comes back incomplete now is **volume**: the service caps every
kind at 50 rows per tenant, and directories routinely hold more app registrations
than that. When the read is truncated the scope is marked `capped` and nothing is
retired for it — which is correct, since the crawl never saw the whole directory.

If `EntraApp` is incomplete and `capped: true`, say:

**Message:**

`EntraApp` shows as not updated because this tenant has more app registrations than
the inventory records per resource type, so I only read part of the list. Nothing was
removed for it. The app registration this agent actually uses is always recorded.

**End message.**

If instead the error mentions `Application.Read.All`, the signed-in admin lacks Graph
permission to list applications. Say that consent for `Application.Read.All` is needed
and that nothing was removed for `EntraApp`. Do **not** suggest hand-editing
`entraAppId` into `.local/config.json` — discovery does not need it to enumerate.

### Any resource type can hit the 50-row cap, not just `EntraApp`

The cap is **50 rows per resource type per tenant** (the service's
`MaxItemsPerTenantAndKind`; 8 kinds × 50 is where the 400-item payload ceiling comes
from). `EntraApp` hits it most often because directories are large, but it applies
equally to `Connection`, `KnowledgeSource`, `ExtensionPack` and `ScenarioTemplate` —
and an enterprise tenant can easily hold more than 50 connections in a single
environment.

When a type exceeds the cap, discovery records the first 50 **sorted by natural key**
and marks the scope `capped: true`. Sorting matters: an arbitrary 50 would change
whenever the platform reordered its listing, and because absence retires, that churn
would delete and revive rows on alternating runs.

A capped scope is never authoritative, so **nothing is retired for it** — the rows
beyond the cap are simply never recorded. Do not describe a capped scope as fully
inventoried. If the user asks why a resource is missing from the inventory, this is
the first thing to check:

**Message:**

This tenant has more **{kind}** than the inventory records per resource type
(50), so I recorded the first 50 and left the rest out. Nothing was removed.

**End message.**

---

## Notes for the assistant (do not show the user)

- The crawler is idempotent by `(kind, naturalKey)`: re-running over an unchanged
  tenant produces identical results and removes nothing.
- **Absence is the delete verb.** The client submits the tenant's *entire* inventory in
  one `syncInventory` call and the service retires anything Active that the payload
  omits. There is no diff, no id list, and no server-side guardrail — every safety
  property lives in the client. The failure direction is inverted from the old design:
  a partial crawl used to remove too little, and would now remove too much.
- The guardrail is **carry-forward**. Before syncing, the client reads the current
  inventory and re-sends verbatim every Active row belonging to a scope this run cannot
  vouch for. So a scope that failed to enumerate, was truncated, or was never visited
  keeps its rows and loses nothing.
- A scope may only retire by omission when it is **authoritative**: fully enumerated, no
  fatal error, nothing unmappable, not `capped`, *and* the platform declares tenant-wide
  reach for that kind. The kit crawls only the configured environment, so `EntraApp` is
  the one kind read tenant-wide; `Environment`, `Connector` and `SharePointSite` are
  always carried forward even though they are filed at the tenant root. Env-scoped kinds
  are authoritative only inside the environment that was crawled.
- Two situations withhold the sync entirely (exit code `2`, `sync.blockedReason` set):
  the current inventory could not be read, so carry-forward is impossible; or a row in
  it uses a kind this build does not recognise, so it cannot be re-sent faithfully.
  Withholding writes nothing and deletes nothing.
- The sync is one large request and legitimately takes **minutes** — it does every write
  and every retirement for the run. It cannot be chunked: absence retires, so each chunk
  would delete everything not in it. Heartbeat lines during this phase mean healthy, not
  hung. Never cancel or re-launch a run that is still emitting them.
- The client skips that request when the payload already matches what the service holds
  (`sync.unchanged: true`), which is the common case on a re-run. That is a **success**
  with zero writes, not a withhold — `sync.blockedReason` is empty and the exit code is
  `0`. Report it as up-to-date; never as failed, withheld, or "saved nothing".
- Never present an incomplete scope as updated, and never present a withheld run as
  saved.
- `EntraApp` is read tenant-wide from Microsoft Graph (`GET /applications`) and needs
  no configured id. When `entraAppId` *is* known — resolved from the top-level key in
  `.local/config.json`, then `.local/connect/workday/config.json` (`entraAppId`), then
  `.local/connect/servicenow/config.json` (`entra.appClientId`) — that app is fetched
  separately and **pinned to the front** of the list, so it survives the 50-row
  truncation on a large directory. A tenant with more apps than the cap reports
  `EntraApp` incomplete and therefore retires nothing for it. An empty read is also
  treated as incomplete, never as "every app was deleted".
- Never fabricate counts, environment ids, or resource names — every value comes
  from `workspace/discover/results.json`.
- `workspace/discover/results.json` is the per-run render artifact. The durable
  cross-run picture is `.local/inventory.json` (the local mirror): merged with
  server-faithful whole-inventory semantics, with `firstSeenAt`/`lastSeenAt` and one-run
  `Retired` tombstones. The server (WeveNova) stays authoritative; the mirror is a
  local cache and is only updated on a run that actually synced.
- The default crawl reads all eight kinds live for the configured environment —
  Dataverse (Connection, ExtensionPack, ScenarioTemplate), Microsoft Graph (EntraApp,
  SharePointSite), the BAP admin API (Connector), and Copilot Studio (KnowledgeSource) —
  via the admin's delegated sign-in. `--demo` runs the full eight-kind lifecycle
  against sample data with no network or sign-in.
- Server-side persistence is the default and is fully implemented, and it goes through
  the local MCP server, which supplies the token. When `writePath` is `local-only` for
  any reason, do not claim anything was saved to WeveNova.
- If a run degrades, read `writePathNote` before guessing. The usual causes are a
  missing or expired token file, the dev tunnel being unreachable, or a `--direct` run
  hitting the 403 app-id policy. `--direct` degrading is expected, not a bug in the
  crawl.
