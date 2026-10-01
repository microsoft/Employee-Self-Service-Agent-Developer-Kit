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

Open the instance-specific plugin page returned by preflight discovery:

[Open HR Service Delivery Core]({HR_CORE_PLUGIN_URL})

Use the exact URL from preflight discovery `links.hrCorePlugin.url`.

Confirm **HR Service Delivery Core** is installed and Active:

- Plugin ID: `com.sn_hr_core`
- Scope: `sn_hr_core`

This requirement is derived from the `hrsd` scope. ITSM must not inherit it.
OIDC capability belongs to the later ServiceNow OIDC phase.

## Completion signal and evidence

Use `vscode_askQuestions` with exactly this question:

> Is HR Service Delivery Core installed and Active?

Choices: **Yes**, **No**, **Not sure**. Leave the selection unset.

- **Yes:** record the phase handoff with `reused` when it was already valid,
  or `completed` when the admin installed/activated it.
- **No / Not sure:** show the direct link and identifiers above, return
  `ACTION_RESULT = "waiting"`, and do not record completion.

After **Yes**, record the single phase handoff:

```text
python scripts/connect_servicenow_da.py record-admin-phase --phase plugin-prerequisites --status <completed|reused>
```

Return `ACTION_RESULT = "recorded"` after the whole step is recorded.
