# Record current Test pane evidence

Ask the maker to run one privacy-safe HRSD request in the Copilot Studio Test
pane: **List my open HR cases**. The prompt must not contain a person's name,
email, employee ID, case number, case title, or other personal data.

Before opening Test, save the current authored draft. The Test evidence binds
the server-saved draft semantic identity and selected ServiceNow connection;
unsaved editor-buffer changes are not covered.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open the `Test` pane from this exact agent landing; do not invent a
tab-specific URL.

A **pass** means the currently signed-in employee receives real live
ServiceNow HRSD data and the response has no authentication, permission,
empty-result, connector, or unexpected error. A sample/demo response or a
successful conversational message without live HRSD data is not a pass.

Record only an allowlisted prompt category and pass/fail outcome. For failure,
record one bounded category; never store response text, case data, URLs,
identifiers, or free-form details:

```text
python scripts/connect_servicenow_da.py record-test --prompt-category list-my-open-hr-cases --result <pass-or-fail> [--failure-category <authentication|permission|empty-result|connector|unexpected>]
```

Do not infer success from topic, credential, binding, or publish health.
Return `ACTION_RESULT = "recorded"` after current evidence is recorded. If the
maker is unavailable, return `ACTION_RESULT = "cancelled"`.
