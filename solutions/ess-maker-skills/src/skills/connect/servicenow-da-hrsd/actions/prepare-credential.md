# Prepare the ServiceNow credential

Run `python scripts/connect_servicenow_da.py inspect`.

- If exactly one Connected `entraIDUserLogin` ServiceNow credential exists,
  run `python scripts/connect_servicenow_da.py record-credential --connection-id <id>`.
- If several exist, ask the maker to select one by display name and ID, then
  run `record-credential`.
- If none exists, run `python scripts/connect_servicenow_da.py create`, guide
  the maker through credential creation and Entra sign-in, then inspect again
  and record the selected healthy credential.

Physical credential creation and sign-in are maker actions. Do not call a
connection-create API or persist secrets. Return `ACTION_RESULT = "applied"`
only after a currently healthy credential is selected; otherwise return
`ACTION_RESULT = "cancelled"`.
