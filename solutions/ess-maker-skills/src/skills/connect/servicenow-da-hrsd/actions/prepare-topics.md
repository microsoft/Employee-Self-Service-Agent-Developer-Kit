# Prepare ServiceNow HRSD topics

Run `python scripts/connect_servicenow_da.py inspect` and show the current HRSD
topic inventory.

- If all HRSD topics are active, set `ACTION_RESULT = "applied"` without a
  mutation.
- Otherwise ask whether to enable all topics or keep current states.
- For keep-current, run
  `python scripts/connect_servicenow_da.py record-topic-choice --choice keep-current`
  and set `ACTION_RESULT = "applied"`.
- For enable-all, show the inactive names, obtain explicit confirmation, run
  `python scripts/connect_servicenow_da.py enable-all-topics --yes`, and set
  `ACTION_RESULT = "applied"` only when the command commits or safely rolls
  back its remote transaction.
- If the maker declines or is unavailable, set
  `ACTION_RESULT = "cancelled"`.
