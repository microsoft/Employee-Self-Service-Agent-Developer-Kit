# Record current Test pane evidence

Ask the maker to run one privacy-safe ITSM request in the Copilot Studio Test
pane, for example **Show my open IT tickets**. The prompt must not contain a person's name,
email, employee ID, case number, case title, or other personal data.

Before opening Test, save the current authored draft. The Test evidence binds
the server-saved draft semantic identity and selected ServiceNow connection;
unsaved editor-buffer changes are not covered.

[Open Employee Self-Service (IT) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from the provider inspection result.

Open the `Test` pane from this exact agent landing; do not invent a
tab-specific URL.

The maker decides whether the ServiceNow functionality worked correctly.
The maker's answer to the result question decides pass, fail, or untested.
Do not infer the outcome from a sample, an empty result, or a conversational
reply; record only what the maker chose.

Render the target link, saved-draft instruction, and privacy boundary above in the ordinary current-task reply after its controller-built lead-in, which is shown verbatim and already carries the ready message, the example request, and the finish-without-testing option. Do not restate or reword it, and do not add a "Required prompt" line. Then use this compact
result question:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "What did the request return?",
    "question": "No need to share ticket contents.",
    "options": [
      { "label": "Expected results" },
      { "label": "Empty result" },
      { "label": "Error" },
      { "label": "Finish without testing" }
    ],
    "allowFreeformInput": false
  }
]
```

Record only an allowlisted prompt category and the maker's outcome.
Never store response text, case/ticket data, URLs, identifiers, or free-form
details:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} record-test --prompt-category list-my-open-it-tickets --result <pass-fail-untested-or-empty>
```

- **Expected results:** record `--result pass`.
- **Empty result:** run the same command with `--result empty`. Nothing is recorded and the test stays open; show the `message` field of the command output verbatim as an ordinary reply. Never record pass or fail for an empty result. The maker's next answer to the same question can still be pass, fail, or untested, so ask the result question again and return `ACTION_RESULT = "waiting"`.
- **Error:** record `--result fail` without inventing a failure category.
- **Finish without testing:** record `--result untested`, then show the `message` field of the command output verbatim as an ordinary reply. Do not claim the integration is connected or working, do not run final validation, and do not show the final success message. The test stays open, so the next Connect run resumes at the Test-pane request. The Test step is only reached after the earlier setup steps are complete, so no setup blocker is outstanding at this point.
- If the maker replies in chat with only "Done" or an unclear answer instead of using the question, ask the same question again and do not record evidence.
- While the question is unanswered, the test is not performed or the maker is
  not ready, return `ACTION_RESULT = "waiting"` and do not record evidence.

Do not infer success from topic, credential, binding, or historical publish
health. A current passing result completes the ServiceNow Connect lifecycle;
publishing is a separate user action outside Connect.
Return `ACTION_RESULT = "recorded"` after current evidence is recorded. If the
question tool is unavailable or the maker has not responded, return
`ACTION_RESULT = "waiting"`. Do not ask a second failure-classification
question.
