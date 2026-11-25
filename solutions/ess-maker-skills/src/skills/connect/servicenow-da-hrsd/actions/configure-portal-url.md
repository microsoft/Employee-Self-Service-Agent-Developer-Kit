# Configure the ServiceNow employee portal Base URI

Treat the HR employee portal URL as one complete high-level step. The instance
origin is already known from preflight, but only the administrator can confirm
whether the employee portal is that exact root URL or uses a separate path.
Never infer `/sp`, `/esc`, or any other example.

The URL question is plain chat text built by the controller: the current-task
message (shown verbatim by the caller) already asked "What is the full HTTPS
base URL ..." and the turn ended. This document runs after the Maker's typed
reply. Never show the URL question as a question card or form, never reword
or repeat the controller message, and never ask for credentials.

Treat the Maker's reply as the administrator-confirmed value. Accept it as
free-form text: a bare URL, a sentence that contains a URL, or a URL with a
short note.

Run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-portal-url
```

If the exact `ServiceNow HRSD Setup Configurations` topic already contains one
valid administrator-confirmed HTTPS Portal BaseURI on the confirmed ServiceNow
instance and it equals the URL in the Maker's reply (or the reply asks to keep
it), return `ACTION_RESULT = "applied"` without a question or mutation.

If the reply does not contain a URL (for example, the Maker asks to reuse a
saved value or does not know it), discover compatible values saved by other
prepared agents in this workspace. This is local-only and must not call
AgentBuilder or Connectivity:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} portal-reuse-handoff
```

- `none`: ask the plain-text URL question again in your own words, without a
  card, and wait for the reply.
- `already-recorded` with an accepted record: use its exact `portalUrl`
  without asking the Maker again, then run the guarded `set-portal-url` command
  below. A declined record continues to the plain-text URL question.
- `question-required`: send the returned `chatMessage`, then ask the returned
  `pendingCard` (title: "Reuse the saved employee portal URL <URL>?"; options
  are only Yes/No). Several saved URLs are asked one at a time; never show a
  source picker. Translate the answer through `portalDecisionChoices`.
  - **Yes**: run
    `record-portal-reuse --source-key <internal-source-key> --decision accept`,
    then pass the returned `portalUrl` directly to the guarded
    `set-portal-url` command. Never ask the Maker to type it.
  - **No** with a non-null `nextSourceKey`: record nothing and rerun
    `portal-reuse-handoff --source-key <nextSourceKey>` to ask about the next
    saved URL.
  - **No** with `nextSourceKey` null (the last candidate): run
    `record-portal-reuse --source-key <internal-source-key> --decision decline`
    and continue to the plain-text URL question.

Candidate discovery and decision recording do not complete the phase or copy
the source topic ID, binding, phase result, or readback. The current agent must
still perform its own fresh component read. When the current value already
equals the accepted URL, `set-portal-url` must return `already-configured`,
record a current-target confirmation, and make no update call. A different
value follows the existing guarded update/readback/rollback transaction.

Show the guarded update and manual fallback guidance in the ordinary
current-task reply. Keep the topic, node, instance origin, current value, and
classification facts for your own checks.
Use the instance root only when the administrator explicitly confirms that exact root URL; otherwise use the confirmed path. Do not show a sample URL as the answer.

Validate that the answer:

- is HTTPS;
- uses the confirmed `{instance}.service-now.com` host;
- is exactly the administrator-supplied root or path URL, without inference;
- has no credentials, query, or fragment.

Then run the read-only confirmation command, which applies the same
normalization as `set-portal-url` (HTTPS, no trailing slash) and saves nothing:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} portal-url-confirmation --portal-url <typed-url>
```

Send the returned `chatMessage` as plain chat text, then ask the returned
`pendingCard` (title: "Is **{NORMALIZED_PORTAL_URL}** the employee portal
URL?", options "Yes" and "No") with no free-form input and no extra body.
- **No**: save nothing and ask the plain-text URL question again, without a
  card.
- **Yes**: show the returned `savedMessage` verbatim
  ("We'll save that portal URL."). Do not announce topic changes in this step;
  topics were handled in the earlier Topics step. Then run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} set-portal-url --portal-url <returned-portalUrl> --yes
```

Nothing is saved before the Maker selects **Yes**.

On `committed` or `already-configured`, return
`ACTION_RESULT = "applied"`. `already-configured` is successful only because
this explicit Maker-confirmed command performs a fresh readback and records a
bounded non-mutating portal confirmation receipt; it must not call the update
API. A `committed` result must update
exactly one `ServiceNowHRSDSetupConfigurations` DialogComponent and exactly
one `Set ServiceNow Portal BaseURI` / `Global.ServiceNowHRSDPortalBaseURI`
SetVariable node, preserve all unrelated topic fields, use the fresh
`changeToken`, and verify the authored readback.

If the update returns `failed-unchanged` or an explicit permission/unsupported
error and a fresh read proves the topic stayed unchanged, show this manual
fallback in the ordinary current-task reply:

1. Open Copilot Studio for the exact HR agent.
2. Open `Topics` → `ServiceNow HRSD Setup Configurations`.
3. Edit the `Set ServiceNow Portal BaseURI` node.
4. Set `To` to the exact administrator-confirmed URL `{PORTAL_URL}`.
5. Save the topic without publishing.

Then use the compact completion confirmation below:

<!-- visible-handoff-question:v1-manual-fallback -->
```json
[
  {
    "header": "Is `{PORTAL_URL}` now saved in the target topic?",
    "question": "We couldn't update the portal URL automatically, so it needs to be set in Copilot Studio.\n\nYou don't need to publish. Answering Yes triggers one fresh read-only verification.",
    "options": [
      { "label": "Yes" },
      { "label": "No" }
    ],
    "allowFreeformInput": false
  }
]
```

After **Yes**, run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-portal-url --expected-portal-url <full-url>
```

If and only if that read-only result reports an exact expected URL match, run
the explicit confirmed setter with the same URL so it records the durable
same-value confirmation without updating the topic:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} set-portal-url --portal-url <full-url> --yes
```

Require `already-configured` and `readbackVerified: true`, then return
`ACTION_RESULT = "applied"`. The read-only inspect command never writes
confirmation state by itself. Only a fresh readback whose normalized authored
value exactly matches the complete URL supplied by the Maker for this phase
completes the step. A different same-instance HTTPS portal path is not
sufficient. Never convert
HTTP 429, unknown mutation state, readback failure, conflict, or rollback
failure into a manual-success fallback. Stop and report those conditions;
honor Retry-After and do not probe repeatedly.

Do not publish the agent in this phase. Publishing is outside ServiceNow
Connect.
