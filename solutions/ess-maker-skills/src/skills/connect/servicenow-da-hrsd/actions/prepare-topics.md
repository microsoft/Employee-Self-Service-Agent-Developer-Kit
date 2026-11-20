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
`question-required` carries two controller-built fields. Show
`replyBeforeQuestion` verbatim as an ordinary agent reply (together with the
current-task link below) before the question, and pass `question` to the shared
lifecycle runner exactly as returned (it is asked as plain chat text via
`adapt-question`). Do not move the topic list into the
question or rebuild either field.
Any failure, unknown decision, malformed question or identity mismatch blocks
the phase before checkpoint or mutation.
Use the shared lifecycle runner's `adapt-question` path for that exact
returned canonical question.

The command-generated `replyBeforeQuestion` is an ordinary reply, not part of
the question:

```text
Current topic inventory: {TOPIC_INVENTORY}

Inactive {PRODUCT_NAME} topics:
{INACTIVE_TOPIC_NAMES}
```

The command-generated question is plain chat text with exactly this wording:

<!-- plain-chat-question:v1 -->
**Message:**

Do you want to turn on all listed inactive ServiceNow topics? Reply No to keep their current states. Only topics in the inventory listed above are in scope; unrelated topics remain unchanged.

Reply **Yes** or **No**.

**End message.**

Send it as ordinary chat text (never a card or input component) and end your
turn.

[Open Employee Self-Service (HR) in Copilot Studio]({COPILOT_STUDIO_AGENT_URL})

Open `Topics`; do not invent a tab-specific URL. This link and action guidance
belong in the ordinary current-task reply, not the question. The
returned question is the wait boundary: while pending, do not return an
`ACTION_RESULT`, emit a completion/remediation message, or return control to
the lifecycle runner.
Absence of an answer is not cancellation.
While the question is pending, preserve the historical action and transaction
state.
- If the maker replies No, to keep the current topic states, run
  `python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-topic-choice --choice keep-current`
  and set `ACTION_RESULT = "applied"`.
- If the maker replies Yes, to enable them, run
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
- Set `ACTION_RESULT = "cancelled"` only if the maker explicitly asks to stop
  or leave the phase incomplete. Do not interpret a pending or
  unanswered question as cancellation.
