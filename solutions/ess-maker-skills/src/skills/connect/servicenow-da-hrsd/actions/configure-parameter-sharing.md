# Confirm ServiceNow parameter sharing

Guide the maker to the ServiceNow connection's **Connection parameters** UI.
Ask every invocation whether **Allow permission to share parameters** is
currently exposed.

- If exposed, ask the maker to enable it, choose the required parameters, and
  save. Then run
  `python scripts/connect_servicenow_da.py record-parameter-sharing --status enabled`.
- If not exposed, run
  `python scripts/connect_servicenow_da.py record-parameter-sharing --status not-exposed`.

Run only the command matching the maker's current observation. Return
`ACTION_RESULT = "applied"` after recording it; if the maker is unavailable,
return `ACTION_RESULT = "cancelled"`.
