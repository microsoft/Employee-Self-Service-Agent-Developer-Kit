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

For every Dev lifecycle entry, render `transport.ordinaryReply.text`. It shows
the applicable collaboration groups and nested internal-step statuses.
Preflight/instance input proceeds without availability. Ask
`transport.businessGroupAvailability.question` only when its `gateRequired`
field is true, and pass the returned group ID/context hash back with the
answer. On **No**, show the group-specific loop-in reply and re-ask the exact
same question; do not advance state or infer permission/evidence.

For `status: dev-connect-required`, continue the normal provider lifecycle
below without asking an environment question. For `status: choice-required`,
show its exact realm question. Production is absent until the exact Test realm
has completed all three target stages. Run the selected realm:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  validate-realm --realm dev
```

Dev returns to the normal exact-target lifecycle and live re-verification.
For Test or Prod, keep the realm explicit. When the user says this ServiceNow
ESS agent was already promoted, use the existing Test/Prod picker and add
`--already-promoted`; this authorizes one read-only exact-target discovery
before a local deployment record exists. It does not accept the user's claim
as evidence, infer an agent ID from a name, or route a literal Workday request.
The exact target-realm ServiceNow instance and Entra application client ID are
both required:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  validate-realm --realm <test|prod> \
  --target-instance "{TARGET_INSTANCE}" \
  --target-client-id "{TARGET_CLIENT_ID}" \
  --already-promoted
```

On verified discovery, the controller records backend deployment proof from
the exact target identity and continues this validation invocation. If every
candidate environment proves the target absent, show the returned Copilot
Studio deployment/approval question. Permission, throttling, network,
unreadable, ambiguous, or identity/schema/family/tenant/commit failures remain
their typed recovery handoffs; do not describe them as not deployed.

Test/Production returns its structured target-stage ordinary reply. It does
not create Dev collaboration-group availability prompts; target checks and
mutation confirmations remain separate.

If either target value is unknown, stop with the returned recoverable handoff.
Do not copy Dev, another realm, agent, or connection values. Validation must
prove the exact target realm, tenant, environment, Dataverse URL, agent ID,
schema, ALM family, and deployed commit. Missing, ambiguous, or mismatched
identity blocks before configuration.

Render the returned `realmStages` exactly: **Connections**, **Runtime
configuration**, and **Maker validation**. For
`runtime-approval-required`, show the exact `runtimePlan`, then call
`vscode_askQuestions` with a one-element array containing the exact returned
`question` object. Preserve its complete target-scoped body and full option
labels; never substitute its header for the body. Translate approval/rejection
to the command below:

Report every returned checkpoint status exactly. Render `Manual` rows as
**Not automatically verified** and never present `Manual` alone as if it
meant the Maker or administrator finished the step.

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-runtime-plan --realm <test|prod> \
  --plan-sha256 "{PLAN_SHA256}" --decision <approve|reject>
```

Approval performs no remote mutation. For `manual-binding-required`, show the
returned Maker UI question. The Maker binds the approved exact connection to
the exact target agent in Copilot Studio; there is no supported direct binding
API. Then record the target-scoped evidence:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-binding --realm <test|prod> \
  --plan-sha256 "{PLAN_SHA256}" \
  --connection-id "{TARGET_CONNECTION_ID}"
```

The controller revalidates the target, plan, connection, and promoted-content
hashes before accepting the binding and rereads afterward. Promoted topics,
topic states, and the Setup Configurations portal value are read-only. Never
enable topics, push local topic files, PUT components, or silently change the
portal URL in Test/Prod; return wrong content to Dev and re-promote.

For `ready-for-test-pane`, show the returned question exactly. It includes the
exact target link and the profile prompt (`List my open HR cases` or
`List my open IT tickets`).
The Maker returns only Pass or Not pass. A generic answer is not an automatic
pass and an empty list is not an automatic failure. The kit never runs the
prompt, records returned employee/ticket/case data, publishes, or claims an
API-proven Test result. After Not pass, record exactly one bounded category:
authentication, permission, connection, binding, identity-mapping,
promoted-content, or unexpected. Do not paste the response or ask for
personal data. Only confirmed promoted-content defects return to Dev and
re-promotion; other categories stay scoped to the exact target.

On `needs-configuration`, render each blocking row's complete `remediation`
unchanged. It is the customer-visible recovery handoff: verified problem,
error category, owner, exact target link or UI location, target values or
their authoritative source, action, success condition, and local rerun point.
Do not collapse it into the generic `next.instruction`. If `validate-realm`
exits with `status: error` and `details.recoveryHandoff`, render its `message`
unchanged and stop. That branch distinguishes target mismatch, permission,
throttling, and read/network failures without changing the target.

When the user has not asked for already-promoted discovery, preserve the
manual deployment-report path. Before target reads, record whether the Maker
reports the organization promotion incomplete or completed:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-deployment --realm <test|prod> --status not-deployed
```

Show the returned question exactly. It directs the ALM owner to use the
organization's normal promotion process outside Connect and asks the Maker to
choose Completed only after that process finishes. The kit does not deploy, promote, import, publish, click, sign in, or change
permissions. Only the controller's conclusive all-candidate not-found result
proves absence; one candidate 404, an unreadable environment, or an unknown
target does not.

When the Maker answers `Completed`, record only their report:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-deployment --realm <test|prod> \
  --status deployment-completed
```

Then run the returned read-only validation command. Maker completion does not
pass validation. On `Not yet`, stop; the persisted record makes the same
question visible when resumed. Production confirmation remains blocked until
Test configuration and Maker validation complete.

After the customer answers, record only the bounded result:

```text
python scripts/connect_servicenow_da.py \
  --provider "{SELECTED_PROVIDER}" \
  --agent-slug "{SELECTED_AGENT_SLUG}" \
  record-realm-test --realm <test|prod> --result <pass|fail>
```

A pass leaves every unobserved Manual row Manual. For Not pass, render the
returned target-scoped recovery handoff unchanged. Do not automatically switch
`activeAgent`, reset Dev phases, delete validation history, publish, or change
any Dev/Test/Prod setting.

Dispatch by the canonical profile returned for `status: ready`:

- `hrsd` -> read `src/skills/connect/servicenow-da-hrsd/SKILL.md`
- `itsm` -> read `src/skills/connect/servicenow-da-itsm/SKILL.md`

The selected provider then invokes the shared lifecycle with
`AGENT_SLUG = SELECTED_AGENT_SLUG`. Local state may label a choice
`connected-revalidation-required`, but the provider must still perform normal
live lifecycle re-verification before reporting it connected.
