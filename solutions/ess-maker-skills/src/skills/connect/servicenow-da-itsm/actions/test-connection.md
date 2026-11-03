# Record current Test pane evidence

Ask the maker to run one privacy-safe ITSM request in the Copilot Studio Test
pane: **List my open IT tickets**. The prompt must not contain a person's name,
email, employee ID, case number, case title, or other personal data.

For a Test or Production deployment realm, use only the exact target agent
link returned by the realm controller after Connections and Runtime
configuration are complete. This is target-scoped Manual evidence; never copy
it from Dev, another realm, agent, or connection. It does not publish or
promote the agent.

Before opening Test, save the current authored draft. The Test evidence binds
the server-saved draft semantic identity and selected ServiceNow connection;
unsaved editor-buffer changes are not covered.

[Open Employee Self-Service (IT) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open the `Test` pane from this exact agent landing; do not invent a
tab-specific URL.

The maker decides whether the ServiceNow functionality worked correctly.
Do not require a non-empty ticket result, and do not automatically treat a
sample, empty result, or conversational response as pass or fail. For a
Test/Production realm Not pass, the realm controller also requires one bounded
category without response content: authentication, permission, connection,
binding, identity-mapping, promoted-content, or unexpected.

Render the target link, saved-draft instruction, exact prompt, and privacy
boundary above in the ordinary current-task reply. Then use this compact
result question:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "Test ServiceNow ITSM",
    "question": "Selected agent: Employee Self-Service (IT) (`{SELECTED_AGENT_SLUG}` / `{SELECTED_AGENT_ID}`)\nRequired prompt: **List my open IT tickets**\n\nDid the ServiceNow ITSM capability work correctly for the exact saved draft and selected ServiceNow connection?\n\nReturn only Pass or Not pass. Do not include response content, personal data, ticket identifiers, tokens, or secrets.",
    "options": [
      { "label": "Pass, the ServiceNow ITSM capability worked correctly" },
      { "label": "Not pass, it failed or could not be verified" }
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
