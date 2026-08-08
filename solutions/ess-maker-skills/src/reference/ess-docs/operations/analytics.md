# Analytics pointer

The **`/analytics`** slash command jumps a maker directly from VS Code to
their Copilot Studio agent's analytics dashboard. It is one of the two
surfaces of the *ADK Copilot Studio Analytics Pointer* MVP (September
2026). The other surface is a one-time reminder printed by
`install_ess_agent.py` right after a successful ESS install.

Both surfaces call the same resolver
(`solutions/ess-maker-skills/scripts/analytics_pointer.py`) and produce
the same maker-facing line so the two experiences stay consistent.

## What the maker sees

**When the association is resolvable and the feature is enabled:**

```
Copilot Studio analytics for your agent:
    https://copilotstudio.microsoft.com/environments/{envId}/bots/{agentId}/analytics
```

**When the association is missing** (no `.local/config.json`, or the
maker AAD / env ID / agent ID isn't captured there yet):

> I can't find a linked Copilot Studio agent for this workspace, so I
> can't build an analytics link yet. Run `/setup` to link an agent, then
> run `/analytics` again.

**When the feature flag is off** (the default for this MVP build):

> Analytics pointer is not yet enabled in this build of the ADK. It is
> behind a feature flag while the Copilot Studio deep-link contract is
> being finalized.

## Feature flag

`ADK_ANALYTICS_POINTER=on` turns the resolver on. It is OFF by default.

The flag exists because the direct-link URL contract for Copilot Studio
analytics has not yet been confirmed by the Copilot Studio partner team.
The PM spec (ADO PR 5465946) forbids shipping against a
reverse-engineered URL, so the default-off state ensures nothing that
depends on the unconfirmed contract can accidentally reach production.

When the flag turns on for real, both the `/analytics` slash command and
the post-deploy reminder become active for that install. There is no
per-surface flag — one switch controls both.

## Reminder state

The post-deploy reminder is one-time per `(maker_aad, env_id, agent_id)`
triplet. State is written by a `ReminderStore` selected via
`ADK_ANALYTICS_STORE`:

| Value | Implementation | Scope | Status |
|---|---|---|---|
| `local` (default) | `LocalFileReminderStore` at `~/.adk/analytics_reminder.json` | Per machine | Shipped for MVP |
| `dataverse` | `DataverseReminderStore` — targets an `adk_makerreminder` table in the ESS Dataverse solution | Per (tenant, maker) — cross-device | Follow-up |

The Dataverse follow-up is tracked as an item on the analytics pointer
workstream. It requires the ESS Dataverse solution package to add the
new table before the ADK-side store can be wired.

## Follow-up items

* **Partner contract for the deep-link URL.** ADO PR 5465946 tracks the
  decision. Until it lands, the resolver stays behind the feature flag
  and the URL shape must be treated as placeholder.
* **Click-time destination validation (FR2).** The resolver reserves
  the `validation_failed` reason for a future check that pings the
  destination before showing it. Not implemented in the MVP.
* **Server-side reminder state (Dataverse).** See the table above.
* **Repair UI beyond `/setup`.** The FR7 repair path today just points
  the maker at `/setup`. A richer repair flow (e.g. re-run the
  environment picker) is out of scope for the MVP.

## Telemetry

The pointer emits five events, all in the `adk.analytics.pointer.*`
family (see `scripts/adk_telemetry.py`):

| Event | When it fires |
|---|---|
| `adk.analytics.pointer.shown` | Any time the pointer line is rendered — carries `outcome` (`resolved` / `unresolved`) and, when unresolved, an `unresolved_reason`. |
| `adk.analytics.pointer.clicked` | Reserved for a future click-tracking wrapper. |
| `adk.analytics.pointer.dismissed` | Maker explicitly ran `/analytics --dismiss`. |
| `adk.analytics.pointer.resolution_failed` | Resolver returned unresolved (also included on the `.shown` event; this exists for FR2 destination-validation retries). |
| `adk.analytics.pointer.repair_attempted` | Maker followed the FR7 repair path and re-ran `/setup`. |

All events carry `env_id` and `agent_id` (opaque GUIDs already emitted
on `adk.agent.deploy`) alongside the common dimensions. No new PII is
introduced by this surface.
