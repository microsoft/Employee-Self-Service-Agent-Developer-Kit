# Workday connection status

This is a read-only menu status lookup, not live sign-off or lifecycle
completion. Do not authenticate, mutate state, or run connection checks here.

Resolve the active agent's slug and BotId from `.local/config.json`.
Return `CONNECTED = true` only if `.local/connect/workday-da/config.json` has
`schemaVersion: 12`, and one `targets.dev`, `targets.test`, or `targets.prod`
snapshot has `deploymentStatus: "ready"` with an identity whose agent slug
and BotId exactly match the active native DA agent.

Saved CEA lifecycle state and provider state without an exact active-agent
match must not make an agent appear connected. Do not read
`.local/connect/workday/agents/` as connection evidence.

If the agent or Workday state has not been configured, or no matching ready
snapshot exists, return `CONNECTED = false`. If required
state is malformed or unreadable, report that status could not be determined;
do not overwrite or reset it. The selected Workday lifecycle re-verifies live
evidence on entry even when this menu lookup reports a saved ready snapshot.
