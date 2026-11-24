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

Return this exact compact canonical payload to the shared lifecycle runner's
`adapt-question` path.
Render the target link and complete instructions above in the ordinary
current-task reply first. After the target lines it has a short plain-text
lead-in, then a Ready-to-send fenced block, which is the message the
Maker forwards to the ServiceNow administrator (instance URL, the Plugins
path, and what to send back); it is already in the controller text, so render
it verbatim. The native question carries only the required
evidence summary and completion decision:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Has your ServiceNow administrator confirmed all of this is present?",
    "question": "Your ServiceNow administrator should see **Human Resources Scoped App: Core** (`com.sn_hr_core`) listed as Installed, with the message `Your application is installed and ready for you to use on your instance`.",
    "options": [
      { "label": "Yes" },
      { "label": "No" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset.

- **Yes:** record the phase
  handoff with `reused` when it was already valid, or `completed` when the
  administrator completed the installation.
- **No:** show only this fixed waiting text verbatim (do not paraphrase it
  and do not repeat the link, plugin title, plugin id, version or message
  details), return `ACTION_RESULT = "waiting"`, and do not record completion:

  ```text
  HR setup is waiting for your ServiceNow administrator to confirm that the HR Service Delivery Core plugin is installed and active.

  Bring back that confirmation when it's ready, and we'll continue with the Entra handoff. You won't need to restart.
  ```

After **Yes**, record the single phase handoff:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-admin-phase --phase plugin-prerequisites --status <completed|reused>
```

Return `ACTION_RESULT = "recorded"` after the whole step is recorded, then run
the `nextCommand` from that record output exactly as given. Do not run a bare
`resume-handoff`; the flags in `nextCommand` tell the controller this action
is already applied.
