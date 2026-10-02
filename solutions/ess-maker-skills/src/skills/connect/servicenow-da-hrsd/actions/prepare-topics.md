# Prepare ServiceNow HRSD topics

Run `python scripts/connect_servicenow_da.py inspect` and show the current HRSD
topic inventory.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from `inspect`.

Open `Topics` and use the inventory below; do not invent a tab-specific URL.

- If all HRSD topics are active, set `ACTION_RESULT = "applied"` without a
  mutation.
- Otherwise show the inactive topic names and use the `vscode_askQuestions`
  tool:

  <!-- visible-handoff-question:v1 -->
  ```json
  [
    {
      "header": "ServiceNow topics",
      "question": "{CURRENT_PROGRESS}\n\nPurpose: prepare the ServiceNow HRSD topics for this exact HR agent.\n\nOwner: ESS Maker / Agent Developer.\n\nOpen Employee Self-Service (HR): {COPILOT_STUDIO_AGENT_URL}\n\nCurrent topic inventory:\n{TOPIC_INVENTORY}\n\nInactive HRSD topics:\n{INACTIVE_TOPIC_NAMES}\n\nEnable all inactive ServiceNow HRSD topics, or explicitly keep their current states? Only ServiceNow HRSD topics in this inventory are in scope; unrelated topics remain unchanged.",
      "options": [
        { "label": "Enable all topics" },
        { "label": "Keep current states" },
        { "label": "Not now" }
      ],
      "allowFreeformInput": false
    }
  ]
  ```

  Leave the selection unset. The tool call is the wait boundary: while the
  question is pending, do not return an `ACTION_RESULT`, emit a completion or
  remediation message, or return control to the lifecycle runner. Absence of
  an answer is not cancellation.
- If the maker selects **Keep current states**, run
  `python scripts/connect_servicenow_da.py record-topic-choice --choice keep-current`
  and set `ACTION_RESULT = "applied"`.
- If the maker selects **Enable all topics**, run
  `python scripts/connect_servicenow_da.py enable-all-topics --yes`. Set
  `ACTION_RESULT = "applied"` only when the command reports `committed` or
  `already-active`. A safely rolled-back update is still a failed action:
  report its error, keep `actionApplied = false`, and stop so a later
  invocation uses a fresh gate and transaction.
- Set `ACTION_RESULT = "cancelled"` only if the maker explicitly selects
  **Not now** or the host explicitly reports that the question tool is
  unavailable. Do not interpret a pending or unanswered question as
  unavailable.
