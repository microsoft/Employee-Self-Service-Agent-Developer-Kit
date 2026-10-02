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

Use this exact visible handoff payload after rendering `{CURRENT_PROGRESS}` and
`{COPILOT_STUDIO_AGENT_URL}`. It keeps the privacy acceptance criteria and
bounded failure categories in the question itself:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Test ServiceNow HRSD",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: verify the exact saved draft and selected ServiceNow connection return real live HRSD data in the Copilot Studio authoring Test pane.\n\nOwner: ESS Maker / Agent Developer, signed in as the employee used for this test.\n\nOpen Employee Self-Service (HR): {COPILOT_STUDIO_AGENT_URL}\n\n1. Save the current authored draft; unsaved editor changes are not covered.\n2. Open the Test pane from this exact agent landing.\n3. Run exactly: **List my open HR cases**.\n4. Do not include a person's name, email, employee ID, case number, case title, or other personal data.\n\nPass only if the signed-in employee receives real live ServiceNow HRSD data with no authentication, permission, empty-result, connector, or unexpected error. A demo/sample response or merely conversational success is not a pass.\n\nWhat happened?",
    "options": [
      { "label": "Passed with live HRSD data", "recommended": true },
      { "label": "Failed: authentication" },
      { "label": "Failed: permission" },
      { "label": "Failed: empty result" },
      { "label": "Failed: connector" },
      { "label": "Failed: unexpected" },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

Record only an allowlisted prompt category and pass/fail outcome. For failure,
record one bounded category; never store response text, case data, URLs,
identifiers, or free-form details:

```text
python scripts/connect_servicenow_da.py record-test --prompt-category list-my-open-hr-cases --result <pass-or-fail> [--failure-category <authentication|permission|empty-result|connector|unexpected>]
```

- **Passed with live HRSD data:** record `--result pass`.
- **Failed: ...:** record `--result fail` with the matching bounded
  `--failure-category`.
- **Not yet:** return `ACTION_RESULT = "waiting"` and do not record evidence.

Do not infer success from topic, credential, binding, or publish health.
Return `ACTION_RESULT = "recorded"` after current evidence is recorded. If the
maker is unavailable, return `ACTION_RESULT = "cancelled"`.
