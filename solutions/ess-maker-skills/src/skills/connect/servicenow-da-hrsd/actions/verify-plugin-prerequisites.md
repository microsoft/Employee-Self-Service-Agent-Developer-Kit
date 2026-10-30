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

Use `vscode_askQuestions` with this exact visible handoff payload. Render
`{CURRENT_PROGRESS}` and `{HR_CORE_PLUGIN_URL}` first. The question body, not
a preceding message, is the authoritative user-visible copy:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "HR Service Delivery Core",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: confirm this HRSD instance has its HR data foundation.\n\nOwner: ServiceNow Admin.\n\nOpen HR Service Delivery Core: {HR_CORE_PLUGIN_URL}\n\nConfirm the Application Manager page shows:\n- Title: `Human Resources Scoped App: Core`\n- Plugin id: `com.sn_hr_core`\n- Version Details: `Installed`\n- Message: `Your application is installed and ready for you to use on your instance`\n\nDo not select Configure, Repair, or Load demo data for this check. This requirement is HRSD-only and does not prove OIDC or overall connection readiness.\n\n    Does the page show the listed installed-and-ready evidence?",
    "options": [
      { "label": "Yes" },
      { "label": "No" },
      { "label": "Not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset.

- **Yes:** record the phase handoff with `reused` when it was already valid,
  or `completed` when the administrator completed the installation.
- **No / Not sure:** show the direct link and identifiers above, return
  `ACTION_RESULT = "waiting"`, and do not record completion.

After **Yes**, record the single phase handoff:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-admin-phase --phase plugin-prerequisites --status <completed|reused>
```

Return `ACTION_RESULT = "recorded"` after the whole step is recorded.
