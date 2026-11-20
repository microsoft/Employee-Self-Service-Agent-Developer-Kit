# Verify HR Service Delivery Core

Treat this as one complete high-level setup step and ask exactly one question.

Read `adminSetup.phaseHandoffs.plugin-prerequisites` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, do not ask again; return
`ACTION_RESULT = "recorded"` and let the phase checkpoint reverify it. A prior
result outside `completionStatuses` requires one new complete phase handoff,
not a checklist-item question.

## Goal and owner

- **Goal:** confirm this HRSD instance has its HR data foundation.
- **Owner role:** ServiceNow Admin.

## Complete admin instructions

Open the instance-specific Application Manager page returned by preflight
discovery:

[Open HR Service Delivery Core]({HR_CORE_PLUGIN_URL})

Use the exact URL from preflight discovery `links.hrCorePlugin.url`.

Confirm the visible Application Manager evidence:

- Title: `Human Resources Scoped App: Core`
- Plugin id: `com.sn_hr_core`
- Version Details: `Installed`
- Message: `Your application is installed and ready for you to use on your instance`

This requirement is derived from the `hrsd` scope. ITSM must not inherit it.
OIDC capability belongs to the later ServiceNow OIDC phase.
`Configure`, `Repair`, and `Load demo data` are not required for this
verification.

## Completion signal and evidence

Render the target link and complete instructions above in the ordinary
current-task reply first. After the target lines it has a short plain-text
lead-in ("First, your ServiceNow administrator needs to confirm that this
instance supports the HR scenarios. Send them this message. When they reply,
paste their confirmation here."), then a Ready-to-send fenced block, which is
the message the Maker forwards to the ServiceNow administrator (instance URL,
the Plugins path, and what to send back); it is already in the controller
text, so render it verbatim. Ask nothing else: there is no yes/no question.
Wait for the Maker's typed reply, never call `ask_user`, and never preselect
an answer. Read the reply as follows:

- **The reply states that the administrator confirmed the plugin is installed
  and active** (a pasted confirmation, or the Maker relaying it explicitly):
  record the phase handoff with `reused` when it was already valid, or
  `completed` when the administrator completed the installation.
- **The reply is only an acknowledgement such as "Done"** with no
  confirmation: send this message verbatim, then wait again:

  ```text
  Ask your ServiceNow administrator to confirm that the HR Service Delivery Core plugin is installed and active so we can continue.

  Paste their reply here or relay their explicit confirmation.
  ```

- **The reply says the plugin is missing, not installed, or the administrator
  is not sure:** show the direct link and identifiers
  above, then show this fixed waiting text verbatim (do not paraphrase it),
  return `ACTION_RESULT = "waiting"`, and do not record completion:

  ```text
  HR setup is waiting for your ServiceNow administrator to confirm that the HR Service Delivery Core plugin is installed and active.

  Bring back that confirmation when it's ready, and we'll continue with the Entra handoff. You won't need to restart.
  ```

After **Yes**, record the single phase handoff:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-admin-phase --phase plugin-prerequisites --status <completed|reused>
```

Return `ACTION_RESULT = "recorded"` after the whole step is recorded.
