# Record current Test pane evidence

Ask the maker to run one privacy-safe ITSM request in the Copilot Studio Test
pane: **List my open IT tickets**. The prompt must not contain a person's name,
email, employee ID, case number, case title, or other personal data.

Before opening Test, save the current authored draft. The Test evidence binds
the server-saved draft semantic identity and selected ServiceNow connection;
unsaved editor-buffer changes are not covered.

[Open Employee Self-Service (IT) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open the `Test` pane from this exact agent landing; do not invent a
tab-specific URL.

The maker decides whether the ServiceNow functionality worked correctly. Do
not independently classify authentication, permission, empty-result,
connector, or other failure types. Do not require a non-empty ticket result
and do not automatically treat a sample, empty result, or conversational
response as pass or fail.

Use this exact visible handoff payload after rendering `{CURRENT_PROGRESS}` and
`{COPILOT_STUDIO_AGENT_URL}`:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Test ServiceNow ITSM",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: verify whether ServiceNow functionality works correctly for the exact saved draft and selected ServiceNow connection in the Copilot Studio authoring Test pane.\n\nOwner: ESS Maker / Agent Developer, signed in as the employee used for this test.\n\nOpen Employee Self-Service (IT): {COPILOT_STUDIO_AGENT_URL}\n\n1. Save the current authored draft; unsaved editor changes are not covered.\n2. Open the Test pane from this exact agent landing.\n3. Run exactly: **List my open IT tickets**.\n4. Decide whether the ServiceNow functionality worked correctly.\n5. Do not include or return a person's name, email, employee ID, ticket number, ticket title, ticket/case content, or other personal data.\n\nWhat was the result?",
    "options": [
      { "label": "Pass" },
      { "label": "Not pass" }
    ],
    "allowFreeformInput": false
  }
]
```

Record only an allowlisted prompt category and the maker's pass/fail outcome.
Never store response text, case/ticket data, URLs, identifiers, or free-form
details:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} record-test --prompt-category list-my-open-it-tickets --result <pass-or-fail>
```

- **Pass:** record `--result pass`.
- **Not pass:** record `--result fail` without inventing a failure category.
- While the question is unanswered, the test is not performed or the maker is
  not ready, return `ACTION_RESULT = "waiting"` and do not record evidence.

Do not infer success from topic, credential, binding, or historical publish
health. A current passing result completes the ServiceNow Connect lifecycle;
publishing is a separate user action outside Connect.
Return `ACTION_RESULT = "recorded"` after current evidence is recorded. If the
question tool is unavailable or the maker has not responded, return
`ACTION_RESULT = "waiting"`. Do not ask a second failure-classification
question.
