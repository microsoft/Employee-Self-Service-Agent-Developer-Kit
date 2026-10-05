# Publish the ServiceNow HRSD agent revision

Run `python scripts/connect_servicenow_da.py inspect` and show the exact active
agent and current component revision.

Publishing is allowed only when the exact current saved draft and selected
ServiceNow connection still match the passing privacy-safe Test evidence. If
either changed, stop and return to the Test phase before asking for publish
confirmation.

If `inspect` reports `progress.publish.status = done`, the current full
component receipt and fresh Test evidence already establish the semantic
identity bridge. Return `ACTION_RESULT = "recorded"` without another publish
question or remote mutation.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Use `links.copilotStudioAgent.url` from `inspect`.

Use `Publish` from this exact agent landing; do not invent a tab-specific URL.

If the publish checkpoint is stale because a legacy receipt lacks
`publishedComponentHash`, first run:

```text
python scripts/connect_servicenow_da.py inspect-publish
```

When `reconciliationEligible` is true, show the exact `componentHash` and
`serverLastPublishedAt`. Ask the Maker one explicit evidence question with
this visible payload after rendering `{CURRENT_PROGRESS}`,
`{COPILOT_STUDIO_AGENT_URL}`, `{COMPONENT_HASH}`, and
`{SERVER_LAST_PUBLISHED_AT}`:

<!-- visible-handoff-question:v1-reconcile -->
```json
[
  {
    "header": "Reconcile publish receipt",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: reconcile a legacy local receipt without publishing or mutating the agent.\n\nOwner: ESS Maker / Agent Developer.\n\nOpen Employee Self-Service (HR): {COPILOT_STUDIO_AGENT_URL}\n\nCurrent component hash: `{COMPONENT_HASH}`\nServer lastPublishedAt: `{SERVER_LAST_PUBLISHED_AT}`\n\nConfirm Copilot Studio currently shows this exact agent and current revision as Published and that no edits were made after that publish. The reconciliation command performs a second read and stops if either value changed; it never publishes or unpublishes.\n\nDoes the exact agent and revision still show Published with no later edits?",
    "options": [
      { "label": "Yes, reconcile local receipt", "recommended": true },
      { "label": "No / not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

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
explicit confirmation to publish the current revision using this visible
payload after rendering `{CURRENT_PROGRESS}`, `{COPILOT_STUDIO_AGENT_URL}`,
`{AGENT_ID}`, `{DRAFT_SEMANTIC_HASH}`, and `{CONNECTION_ID}`:

<!-- visible-handoff-question:v1-publish -->
```json
[
  {
    "header": "Publish tested HR agent",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: publish the exact ServiceNow HRSD draft that passed the privacy-safe Test pane check.\n\nOwner: ESS Maker / Agent Developer.\n\nOpen Employee Self-Service (HR): {COPILOT_STUDIO_AGENT_URL}\n\nExact agent ID: `{AGENT_ID}`\nTested saved-draft semantic hash: `{DRAFT_SEMANTIC_HASH}`\nSelected connection ID: `{CONNECTION_ID}`\n\nPublish is allowed only because this exact saved draft and connection still match the passing Test evidence. Publishing applies the current authored content to channels. The command records and refetches the publish receipt; if it reports `needs_remediation`, do not retry blindly and do not claim automatic unpublish or rollback.\n\nPublish this exact tested revision now?",
    "options": [
      { "label": "Yes, publish now", "recommended": true },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

After confirmation run:

```text
python scripts/connect_servicenow_da.py publish --yes
```

Return `ACTION_RESULT = "applied"` only for a definitive success or a
sanitized receipt that the publish checkpoint can verify. If the command
reports `needs_remediation`, stop: do not retry blindly and do not claim an
automatic unpublish or rollback. If the maker declines or is unavailable,
return `ACTION_RESULT = "cancelled"`.
