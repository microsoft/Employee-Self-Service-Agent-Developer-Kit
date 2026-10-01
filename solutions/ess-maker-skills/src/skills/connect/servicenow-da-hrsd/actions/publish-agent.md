# Publish the ServiceNow HRSD agent revision

Run `python scripts/connect_servicenow_da.py inspect` and show the exact active
agent and current component revision.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from `inspect`.

Use `Publish` from this exact agent landing; do not invent a tab-specific URL.

If the publish checkpoint is stale because a legacy receipt lacks
`publishedComponentHash`, first run:

```text
python scripts/connect_servicenow_da.py inspect-publish
```

When `reconciliationEligible` is true, show the exact `componentHash` and
`serverLastPublishedAt`. Ask the Maker one explicit evidence question:

> Does Copilot Studio currently show this exact agent and current revision as
> Published, and have you made no edits since that publish completed?

If confirmed, run the local-only guarded reconciliation using the exact values
from `inspect-publish`:

```text
python scripts/connect_servicenow_da.py reconcile-publish-receipt --expected-component-hash <hash> --expected-last-published-at <timestamp> --yes
```

The reconciliation command performs a second read and stops if either value
changed. It never publishes or mutates the remote agent. Return
`ACTION_RESULT = "recorded"` after it succeeds; the publish checkpoint remains
`Manual` until the Maker acknowledges this evidence.

If reconciliation is not eligible or the Maker cannot confirm it, ask for
explicit confirmation to publish the current revision. After confirmation run:

```text
python scripts/connect_servicenow_da.py publish --yes
```

Return `ACTION_RESULT = "applied"` only for a definitive success or a
sanitized receipt that the publish checkpoint can verify. If the command
reports `needs_remediation`, stop: do not retry blindly and do not claim an
automatic unpublish or rollback. If the maker declines or is unavailable,
return `ACTION_RESULT = "cancelled"`.
