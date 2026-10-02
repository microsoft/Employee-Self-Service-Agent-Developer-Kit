# Analytics pointer

The **`/analytics`** slash command jumps a maker directly from VS Code to
the current DA agent's Copilot Studio analytics dashboard. It uses the
shared resolver in `solutions/ess-maker-skills/scripts/analytics_pointer.py`.
The current DA-GA setup flow has no separate CEA installation path, so this
command does not branch between DA and CEA analytics surfaces.

## What the maker sees

**When the association is resolvable and the feature is enabled:**

```
Copilot Studio analytics for your agent:
    https://copilotstudio.{test|preprod|}.microsoft.com/environments/{envId}/copilots/{agentId}/analytics
```

**When the association is missing** (no `.local/config.json`, or the
environment ID / agent ID isn't captured there yet):

> I can't find a linked Copilot Studio agent for this workspace, so I
> can't build an analytics link yet. Run `/setup` to link an agent, then
> run `/analytics` again.

**When the link is explicitly disabled** with
`ADK_ANALYTICS_POINTER=off`:

> Your Copilot Studio analytics link isn't available in this workspace right
> now. Please contact your administrator for help accessing analytics.

## Feature flag

The resolver is ON by default. Set `ADK_ANALYTICS_POINTER=off` only to
disable link construction. The host is selected from the configured service
ring: `test`, `preprod`, or the empty segment for production. There is no
CEA-specific branch in the DA-GA solution.

## Reminder state

Optional local reminder state is one-time per DA workspace association.
State is written by a `ReminderStore` selected via
`ADK_ANALYTICS_STORE`:

| Value | Implementation | Scope | Status |
|---|---|---|---|
| `local` (default) | `LocalFileReminderStore` at `~/.adk/analytics_reminder.json` | Per machine | Shipped for MVP |
| `dataverse` | `DataverseReminderStore` — targets an `adk_makerreminder` table in the ESS Dataverse solution | Per (tenant, maker) — cross-device | Follow-up |

The Dataverse follow-up is tracked as an item on the analytics pointer
workstream. It requires the ESS Dataverse solution package to add the
new table before the ADK-side store can be wired.

## Follow-up items

* **Destination validation.** The resolver currently constructs the
  confirmed DA analytics URL locally. Click-time destination validation
  remains a future enhancement.
* **Click-time destination validation (FR2).** The resolver reserves
  the `validation_failed` reason for a future check that pings the
  destination before showing it. Not implemented in the MVP.
* **Server-side reminder state (Dataverse).** See the table above.
* **Repair UI beyond `/setup`.** The FR7 repair path today just points
  the maker at `/setup`. A richer repair flow (e.g. re-run the
  environment picker) is out of scope for the MVP.

## Telemetry

Each `/analytics` skill invocation emits one `adk.capability.use` event with
`adk_capability=analytics`. This feeds the Capability Usage by Type
dashboard. Rendering the URL from `/push` does not emit this event because it
is not an `/analytics` invocation. No separate pointer shown/clicked/
dismissed events are emitted.
