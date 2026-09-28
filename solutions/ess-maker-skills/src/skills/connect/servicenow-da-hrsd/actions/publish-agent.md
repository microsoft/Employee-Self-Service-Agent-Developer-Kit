# Publish the ServiceNow HRSD agent revision

Run `python scripts/connect_servicenow_da.py inspect` and show the exact active
agent and current component revision. Ask for explicit confirmation to publish
that revision. After confirmation run:

```text
python scripts/connect_servicenow_da.py publish --yes
```

Return `ACTION_RESULT = "applied"` only for a definitive success or a
sanitized receipt that the publish checkpoint can verify. If the command
reports `needs_remediation`, stop: do not retry blindly and do not claim an
automatic unpublish or rollback. If the maker declines or is unavailable,
return `ACTION_RESULT = "cancelled"`.
