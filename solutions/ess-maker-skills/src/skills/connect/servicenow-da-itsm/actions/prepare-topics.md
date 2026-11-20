# Prepare ServiceNow ITSM topics

Run:

```text
python scripts/connect_servicenow_da.py \
  --provider servicenow-da-itsm \
  --agent-slug {SELECTED_AGENT_SLUG} \
  topic-action-handoff
```

Parse the structured result. This read-only command is authoritative:

- `verified-noop` with `actionResult: applied` — set
  `ACTION_RESULT = "applied"` without asking or mutating.
- `question-required` — show the returned `replyBeforeQuestion` verbatim as
  an ordinary agent reply (with the current-task link below) before the card,
  then return the exact `question` object to the shared lifecycle runner; do
  not rebuild or shorten either field or move the topic list into the card;
- any failure, unknown decision, malformed question or identity mismatch —
  fail closed before checkpoint or mutation.

Use the shared lifecycle runner's `adapt-question` path for the returned
canonical question. Only ServiceNow ITSM topics in this inventory are in
scope; unrelated topics remain unchanged.

The command-generated `replyBeforeQuestion` is an ordinary reply, not part of
the card:

```text
Current topic inventory: {TOPIC_INVENTORY}

Inactive {PRODUCT_NAME} topics:
{INACTIVE_TOPIC_NAMES}
```

The command-generated question conforms to the same supported
`visible-handoff-question:v1` shape: the card title is the question "Should we
enable the inactive ServiceNow topics?" with exactly these short labels:
**Enable all**, **Keep current**, and **Not now**. The explanation ("Only
topics in the inventory listed above are in scope; unrelated topics remain
unchanged.") is sent as chat text, not in the card.

[Open Employee Self-Service (IT) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Open `Topics`; do not invent a tab-specific URL. This link and action guidance
belong in the ordinary current-task reply, not the native question. The
returned question is the wait boundary: while pending, do not return an
`ACTION_RESULT`, emit a completion/remediation message, or return control to
the lifecycle runner.
Absence of an answer is not cancellation.
- If the maker selects **Keep current**, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} record-topic-choice --choice keep-current`
  and set `ACTION_RESULT = "applied"`.
- If the maker selects **Enable all**, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} enable-all-topics --yes`. Set
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
  **Not now** or the host explicitly reports that
  the question tool is
  unavailable. Do not interpret a pending or unanswered question as
  unavailable.
