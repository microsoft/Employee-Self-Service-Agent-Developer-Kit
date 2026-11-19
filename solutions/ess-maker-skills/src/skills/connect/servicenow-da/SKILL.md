# Choose an ESS Agent for ServiceNow

This is a thin chooser and dispatcher. It never runs a second lifecycle,
changes `.local/config.json.activeAgent`, or reads provider state before the
maker selects one exact agent.

Run the state-free local chooser:

```text
python scripts/connect_servicenow_da.py agent-chooser
```

Show the exact returned `question`. Its prepared-agent choices come only from
canonical HR/IT setup entries for the current bound workspace environment.
They are labeled as prepared in this workspace, not as every agent in the
environment. This command must not run a remote collection listing.

When the maker selects a prepared agent, rerun with its returned internal
selection key:

```text
python scripts/connect_servicenow_da.py agent-chooser \
  --selection-key "{SELECTION_KEY}"
```

For `status: ready`, retain the returned `selectedAgent` only for this
invocation and continue to its normal provider lifecycle. Fresh supported
identity and lifecycle checks still apply; local preparation is not remote
success evidence.

For **Use another agent (paste link)**, the selection-key command returns one
focused freeform question. Show it exactly. After the maker pastes the full
Copilot Studio link, run:

```text
python scripts/connect_servicenow_da.py agent-chooser \
  --selection-key "another-agent" \
  --agent-link "{PASTED_AGENT_LINK}"
```

Do not ask for an environment ID, agent ID, account, or multiple values in the
same field. A malformed, non-Copilot, different-environment, or different-ring
link returns an actionable no-write error. A link matching a prepared agent
returns `ready` without duplicate setup. `setup-required` means the exact
existing agent is new to this workspace: show the returned typed `/setup`
handoff and stop. Do not run setup, create an agent, switch environment/account,
or mutate local state from this chooser.

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

The selected provider then invokes the shared lifecycle with
`AGENT_SLUG = SELECTED_AGENT_SLUG`. Local state may label a choice
`connected-revalidation-required`, but the provider must still perform normal
live lifecycle re-verification before reporting it connected.
