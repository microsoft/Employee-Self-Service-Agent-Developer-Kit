# Choose an ESS Agent for ServiceNow

This is a thin chooser and dispatcher. It never runs a second lifecycle,
changes `.local/config.json.activeAgent`, or reads provider state before the
maker selects one exact agent.

Run the state-free local chooser:

```text
python scripts/connect_servicenow_da.py agent-chooser
```

Show the exact returned `question`: a Yes/No card ("Connect {agent} to
ServiceNow?") for the first prepared agent, never a list of agents. Its
prepared-agent candidates come only from canonical HR/IT setup entries for the
current bound workspace environment. The card title carries the agent's recorded
Copilot Studio display name only (no product suffix, ID, link, or slug); a
product name or ordinal is added only when two candidates would otherwise read
the same. They are prepared in this workspace, not every agent in the
environment. This command must not run a remote collection listing.

**Skip the chooser when the agent is already known.** If the maker already gave
a Copilot Studio agent link, or the agent was already selected, set up, or
discussed earlier in the same conversation, do not show the question. Reuse
that agent silently with the selection-key commands below (link form when a
link is known, `prepared:{AGENT_ID}` otherwise) and continue only on
`status: ready`. Follow the rules in `src/skills/connect/servicenow/entry.md`
(**Choose the agent**); when the conversation names no agent or several agents,
show the chooser as usual. When the maker names an agent only by name (for
example "my Benefits agent"), run
`agent-chooser --agent-name "{NAME_AS_TYPED}"`: an agent that is not an ESS HR
or IT agent returns `unsupported-agent`; show its `message` verbatim, never ask
for a link, and do not start Setup for it. When the maker also names a
destination (for example "test the IT agent in Prod"), pass the words as typed:
continue with `selectedAgent`, then run
`discover-realm-target --realm {realmHint}` at once. It finds the promoted
agent and its link by itself through the API even when its name differs from
Dev; never ask the maker for a link or write your own question.
When the named HR or IT agent is not prepared in this workspace, the controller
returns `agent-link-required` with `requestedProduct`: show its `chatMessage`
verbatim and follow its `afterReply`; never offer the other product's agent.
Never match an agent by display name yourself.

When the maker answers **Yes**, rerun with the returned `prepared:{ID}`
selection key. When the maker answers **No**, rerun with the returned
`next-agent:{N}` key (the last candidate's **No** key is `another-agent`):

```text
python scripts/connect_servicenow_da.py agent-chooser \
  --selection-key "{SELECTION_KEY}"
```

For `status: ready`, retain the returned `selectedAgent` only for this
invocation and continue to its normal provider lifecycle. Fresh supported
identity and lifecycle checks still apply; local preparation is not remote
success evidence.

After the last **No**, or when no agent is prepared, the controller returns
`status: agent-link-required` with one focused freeform question (plain chat,
no options). Show it exactly. After the maker pastes the full
Copilot Studio link, run:

```text
python scripts/connect_servicenow_da.py agent-chooser \
  --selection-key "another-agent" \
  --agent-link "{PASTED_AGENT_LINK}"
```

Do not ask for an environment ID, agent ID, account, or multiple values in the
same field. A malformed, non-Copilot, or different-ring link returns an
actionable no-write error. A link to a different environment hands off to
Setup's existing conflicting-environment choice (see the entry doc). A link
matching a prepared agent
returns `ready` without duplicate setup. `setup-required` means the exact
existing agent is new to this workspace: follow the automatic Setup handoff in
`src/skills/connect/servicenow/entry.md` (**Choose the agent**) for that exact
link, then rerun this command with the same link. `setup-incomplete` means the
agent is in the workspace but its Setup steps are still pending; it is not an
"agent no longer available" error. Follow the same entry doc: Setup's remaining
steps run (at most one resume per invocation), then rerun this command. The
chooser itself never
runs setup, creates an agent, switches environment/account, or mutates local
state.

When `agent-chooser` returns `setup-required` with branch
`workspace-not-prepared`, the workspace has no prepared setup state yet. Follow
the same automatic handoff; a supplied link is carried into Setup, otherwise
Setup asks its normal questions. If Setup is cancelled or blocked, use the
cancel/blocked Messages in the entry doc (blocker: say what to fix, ask the
maker to fix it, then to tell me to finish setup and connect again; cancel:
nothing to fix); never tell the maker to type `/setup`.

After selection, keep only invocation-local values:

- `SELECTED_AGENT_ID`
- `SELECTED_AGENT_SLUG`
- `SELECTED_PROFILE`
- `SELECTED_PROVIDER`

Never persist the choice to `.local/config.json` or change `activeAgent`.

After selection, dispatch the exact selected provider to its normal Dev lifecycle.
Do not change `.local/config.json.activeAgent`; the selected provider uses only
the invocation-local agent values returned by the chooser.

Dispatch by the canonical profile returned for `status: ready`:

- `hrsd` -> read `src/skills/connect/servicenow-da-hrsd/SKILL.md`
- `itsm` -> read `src/skills/connect/servicenow-da-itsm/SKILL.md`

`unsupported-agent` means the pasted link points to an agent already in this
workspace that is neither an HR nor an IT ESS agent. Show the Unsupported agent
Message in the entry doc and offer **Choose a different agent**; do not hand
off to Setup.

The selected provider then invokes the shared lifecycle with
`AGENT_SLUG = SELECTED_AGENT_SLUG`. When the maker said the organization
already uses ServiceNow Knowledge, single sign-on, or the Microsoft Graph
connector, carry that through the chooser and add `--existing knowledge` (or
`sso`, `graph`) to the first `resume-handoff`; never skip it, never write the
opening yourself, and never inspect existing Entra or OIDC configuration (see
**Existing sign-in setup disclosed in the request** in
`src/skills/connect/servicenow/entry.md`). Local state may label a choice
`connected-revalidation-required`, but the provider must still perform normal
live lifecycle re-verification before reporting it connected.

**More than one agent in one request.** When one request names both ESS agents
or all of them (for example "Check HR and IT in Prod"), first run
`validation-notice --situation multi-agent`, send `chatMessage` verbatim with
no preamble or trailer, and end the turn before any chooser, status, preflight,
or checklist step (see **More than one agent in one request** in
`src/skills/connect/servicenow/entry.md`). The controller's fixed text is the
whole reply; no run starts.

**A step failed with no controller message.** Controller messages always win.
Only after a command returned an explicit failure (never after a confirmed or
successful step), and when none covers the failure, run
`redo-step-notice --step {connection|portal-url|topics|test}` and send
`renderBlock.text` verbatim; it repeats the step with its non-secret values and
never asks for or echoes a secret (see **A step failed and no controller
message covers it** in `src/skills/connect/servicenow/entry.md`).

When a destination check is paused, the checklist `renderBlock.text` already
carries the controller's pause text followed by the repair steps for that
blocker (connection, topics, missing sign-in values). Send it verbatim with the
steps; never shorten it or leave out the steps.
