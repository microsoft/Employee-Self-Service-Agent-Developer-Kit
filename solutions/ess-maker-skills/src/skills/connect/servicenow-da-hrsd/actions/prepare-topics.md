# Prepare ServiceNow HRSD topics

Run:

```text
python scripts/connect_servicenow_da.py \
  --provider servicenow-da-hrsd \
  --agent-slug {SELECTED_AGENT_SLUG} \
  topic-action-handoff
```

Parse the structured result. `verified-noop` with `actionResult: applied`
returns `ACTION_RESULT = "applied"` without asking or mutating.
`question-required` must be passed to the question tool exactly as returned.
Any failure, unknown decision, malformed question or identity mismatch blocks
the phase before checkpoint or mutation.
Use `vscode_askQuestions` for that exact returned question.

The command-generated question conforms to this visible contract:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow topics",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: prepare the ServiceNow HRSD topics for this exact HR agent.\n\nOwner: ESS Maker / Agent Developer.\n\nCurrent topic inventory: {TOPIC_INVENTORY}\n\nInactive HRSD topics:\n{INACTIVE_TOPIC_NAMES}\n\nEnable all inactive ServiceNow HRSD topics, or explicitly keep their current states? Only ServiceNow HRSD topics in this inventory are in scope; unrelated topics remain unchanged.",
    "options": [
      { "label": "Enable all topics" },
      { "label": "Keep current states" },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Open `Topics`; do not invent a tab-specific URL. The returned question is the
wait boundary: while pending, do not return an `ACTION_RESULT`, emit a
completion/remediation message, or return control to the lifecycle runner.
Absence of an answer is not cancellation.
The tool call is the wait boundary: while the
  question is pending, preserve the historical action and transaction state.
Absence of
  an answer is not cancellation.
- If the maker selects **Keep current states**, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-topic-choice --choice keep-current`
  and set `ACTION_RESULT = "applied"`.
- If the maker selects **Enable all topics**, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} enable-all-topics --yes`. Set
  `ACTION_RESULT = "applied"` only when the command reports
  `transactionStatus: "committed"` or `status: "already-active"`.
  A successful update whose fresh readback proves every in-scope topic exists
  and is `Active` is committed even when non-target component content differs
  from the locally constructed postimage. Preserve the returned
  `unattributedPostimageTopics` as diagnostic evidence. The difference may
  come from service normalization or a concurrent edit; do not attribute it to
  either source, claim full postimage ownership, or roll back content the
  transaction does not own.

  An update with an exception or unknown response, a missing target topic, or
  any in-scope topic still not `Active` is not success. Preserve the current
  transaction and rollback protections for those cases. A safely rolled-back
  update is still a failed action: report its error, keep
  `actionApplied = false`, and stop so a later invocation uses a fresh gate and
  transaction. A later invocation that freshly observes all topics Active
  follows the no-mutation path above and must not repeat the confirmed update.
- Set `ACTION_RESULT = "cancelled"` only if the maker explicitly selects
  **Not now** or the host explicitly reports that the question tool is
  unavailable. Do not interpret a pending or unanswered question as
  unavailable.
