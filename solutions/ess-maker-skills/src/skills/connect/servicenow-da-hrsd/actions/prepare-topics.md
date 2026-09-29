# Prepare ServiceNow HRSD topics

Run `python scripts/connect_servicenow_da.py inspect` and show the current HRSD
topic inventory.

- If all HRSD topics are active, set `ACTION_RESULT = "applied"` without a
  mutation.
- Otherwise show the inactive topic names and use the `vscode_askQuestions`
  tool:

  ```json
  [
    {
      "header": "ServiceNow topics",
      "question": "Enable all inactive ServiceNow HRSD topics?",
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
