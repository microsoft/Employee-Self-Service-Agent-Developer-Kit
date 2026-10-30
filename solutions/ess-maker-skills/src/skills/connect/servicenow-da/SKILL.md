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

Before dispatching, check whether this exact selected agent already has a
complete current Dev Connect record:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  validation-realm-handoff
```

For `status: dev-connect-required`, continue the normal provider lifecycle
below without asking an environment question. For `status: choice-required`,
show its exact Dev/Test/Prod question. Run the selected realm:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  validate-realm --realm dev
```

Dev returns to the normal exact-target lifecycle and live re-verification.
For Test or Prod, run the read-only validation immediately. When reliable
target-realm administrator-confirmed ServiceNow instance and Entra application
client ID values are already available, pass both together:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  validate-realm --realm <test|prod> \
  --target-instance "{TARGET_INSTANCE}" \
  --target-client-id "{TARGET_CLIENT_ID}"
```

When neither target value is reliably known, omit both flags. Do not add a new
up-front administrator question: the credential row remains `Manual`, and the
Maker proceeds to the exact target Test pane when no automatic blocker exists.
Supplying only one target metadata flag is an error.

Do not copy Dev values unless the customer confirms the target realm shares
them. Test/Prod is a separate read-only validation path. Report every returned
checkpoint status exactly; `Skipped`, `Manual`, `Warning`, `Blocked`,
`NotConfigured`, `Failed`, and `Error` are not automatic passes. Only
`Failed`, `Error`, `Blocked`, or `NotConfigured` automatic rows block the
initial Test pane handoff. Correctly unobservable items remain `Manual` and do
not block that first functional test. Preserve the raw `status` enum for
machine logic, but never present `Manual` alone as if it meant manually
finished. Render each row's `customerStatus` and `customerExplanation`:
unattested target rows say **Not automatically verified**; only exact
target-scoped Maker/Admin evidence may say who confirmed it.

For `ready-for-test-pane`, state that only automatic prechecks are complete
and functional/end-to-end validation is still pending. Show the returned
`question` exactly; it includes the exact target link and the profile's
`test_prompt` (`List my open HR cases` or `List my open IT tickets`). The
customer enters that read-only prompt in the target Test pane and returns only
Pass or Not pass. The kit never runs the prompt, requires a non-empty result,
or records returned employee/ticket/case data. A generic answer is not an
automatic pass, and an empty list is not an automatic failure; the Maker
judges the expected ServiceNow behavior. For Not pass, record the result
without requiring a failure category and show only the returned Dev handoff.

On `needs-configuration`, render each blocking row's complete `remediation`
unchanged. It is the customer-visible recovery handoff: verified problem,
error category, owner, exact target link or UI location, target values or
their authoritative source, action, success condition, and local rerun point.
Do not collapse it into the generic `next.instruction`. If `validate-realm`
exits with `status: error` and `details.recoveryHandoff`, render its `message`
unchanged and stop. That branch distinguishes target mismatch, permission,
throttling, and read/network failures without changing the target.

If exact target discovery finds no deployed target and the customer confirms
that the requested Test/Prod target has not been created or deployed, record
that bounded fact locally:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-deployment --realm <test|prod> --status not-deployed
```

Show the returned `question` exactly. It is the only deployment question and
contains the source-agent link plus this order: upper-right **Deploy to
Test/Prod**, lower-left **Save**, **Deploy**, wait, then **Open Agent**. The
Maker performs these UI actions; the kit does not deploy, promote, import,
publish, click, sign in, or change permissions. A 404, unreadable environment,
or unknown target is not proof of missing deployment: ask only whether the
target exists, and use this command only after the customer explicitly says
it is not deployed. If they say it exists or are unsure, keep the target
status unknown and do not show deployment-as-required instructions.

When the Maker answers `Completed`, record only their report:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-deployment --realm <test|prod> \
  --status deployment-completed
```

Then run the returned read-only validation command. Maker completion and
**Open Agent** do not pass validation: exact realm/family/environment/agent/
schema proof and the bounded Test pane result are still required. On `Not
yet`, stop; the persisted `not-deployed` record makes the same question
visible when that realm is resumed. If the deployment button is unavailable,
route the returned steps to the actual ALM owner without guessing another
button or elevating the current maker.

After the customer answers, record only the bounded result:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-test --realm <test|prod> --result <pass|fail>
```

A pass leaves every unobserved Manual row Manual. For Not pass, render only
the exact returned sentence and Dev source-agent link:
`Not pass recorded; return to the Dev agent and rerun /connect servicenow to
recheck the connection setup step by step.` Do not ask a second
failure-category question, automatically switch `activeAgent`, reset Dev
phases, delete validation history, or change any Dev/Test/Prod setting.
An older caller may still supply a supported failure category; preserve it in
the record but do not use it to create customer-facing targeted follow-up.

Dispatch by the canonical profile returned for `status: ready`:

- `hrsd` -> read `src/skills/connect/servicenow-da-hrsd/SKILL.md`
- `itsm` -> read `src/skills/connect/servicenow-da-itsm/SKILL.md`

The selected provider then invokes the shared lifecycle with
`AGENT_SLUG = SELECTED_AGENT_SLUG`. Local state may label a choice
`connected-revalidation-required`, but the provider must still perform normal
live lifecycle re-verification before reporting it connected.
