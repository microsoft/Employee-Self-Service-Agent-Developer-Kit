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
it verbatim. The question carries only the required
evidence summary and completion decision. Send it as ordinary chat text
(its `plainText` from `adapt-question`, never `ask_user`) and map the typed
reply with `match-reply`:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "HR Service Delivery Core",
    "question": "Your ServiceNow administrator should see **Human Resources Scoped App: Core** (`com.sn_hr_core`) listed as Installed, with the message `Your application is installed and ready for you to use on your instance`.\n\nHas the ServiceNow administrator confirmed that all of this HR Service Delivery Core evidence is present?",
    "options": [
      { "label": "Yes, all listed installed-and-ready evidence is present" },
      { "label": "No, one or more required items are missing" },
      { "label": "Not sure, the administrator still needs to check" }
    ],
    "allowFreeformInput": false
  }
]
```

Wait for the Maker's typed reply; do not preselect an answer.

- **Yes, all listed installed-and-ready evidence is present:** record the phase
  handoff with `reused` when it was already valid, or `completed` when the
  administrator completed the installation.
- **No, one or more required items are missing** / **Not sure, the
  administrator still needs to check:** show the direct link and identifiers
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
