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
current-task reply first. The native question carries only the required
evidence summary and completion decision:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "HR Service Delivery Core",
    "question": "Required evidence for the selected ServiceNow instance:\n- Title: `Human Resources Scoped App: Core`\n- Plugin id: `com.sn_hr_core`\n- Version Details: `Installed`\n- Message: `Your application is installed and ready for you to use on your instance`\n\nHas the ServiceNow administrator confirmed that all of this HR Service Delivery Core evidence is present?",
    "options": [
      { "label": "Yes, all listed installed-and-ready evidence is present" },
      { "label": "No, one or more required items are missing" },
      { "label": "Not sure, the administrator still needs to check" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset.

- **Yes, all listed installed-and-ready evidence is present:** record the phase
  handoff with `reused` when it was already valid, or `completed` when the
  administrator completed the installation.
- **No, one or more required items are missing** / **Not sure, the
  administrator still needs to check:** show the direct link and identifiers
  above, return `ACTION_RESULT = "waiting"`, and do not record completion.

After **Yes**, record the single phase handoff:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-admin-phase --phase plugin-prerequisites --status <completed|reused>
```

Return `ACTION_RESULT = "recorded"` after the whole step is recorded.
