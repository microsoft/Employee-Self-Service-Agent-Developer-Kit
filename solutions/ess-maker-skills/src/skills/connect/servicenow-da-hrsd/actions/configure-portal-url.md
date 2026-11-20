# Configure the ServiceNow employee portal Base URI

Treat the HR employee portal URL as one complete high-level step. The instance
origin is already known from preflight, but only the administrator can confirm
whether the employee portal is that exact root URL or uses a separate path.
Never infer `/sp`, `/esc`, or any other example.

Run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-portal-url
```

If the exact `ServiceNow HRSD Setup Configurations` topic already contains one
valid administrator-confirmed HTTPS Portal BaseURI on the confirmed ServiceNow
instance, return `ACTION_RESULT = "applied"` without a question or mutation.

Otherwise discover compatible values saved by other prepared agents in this
workspace. This is local-only and must not call AgentBuilder or Connectivity:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} portal-reuse-handoff
```

- `none`: continue to the manual URL question below.
- `already-recorded` with an accepted record: use its exact `portalUrl`
  without asking the Maker again, then run the guarded `set-portal-url` command
  below. A declined record continues to the manual question.
- `source-selection-required`: send the returned plain question (its
  `plainText`), translate the typed reply through `portalSourceChoices`, and
  rerun `portal-reuse-handoff --source-key <internal-source-key>`.
- `question-required`: send the returned question's `plainText` verbatim as
  ordinary chat text and map the typed reply with `match-reply`. Translate the
  answer through `portalDecisionChoices`.
  - **Yes**: run
    `record-portal-reuse --source-key <internal-source-key> --decision accept`,
    then pass the returned `portalUrl` directly to the guarded
    `set-portal-url` command. Never ask the Maker to type it.
  - **No**: run
    `record-portal-reuse --source-key <internal-source-key> --decision decline`
    and continue to the manual question.
  - No answer yet: record nothing and return `ACTION_RESULT = "waiting"`.

Candidate discovery and decision recording do not complete the phase or copy
the source topic ID, binding, phase result, or readback. The current agent must
still perform its own fresh component read. When the current value already
equals the accepted URL, `set-portal-url` must return `already-configured`,
record a current-target confirmation, and make no update call. A different
value follows the existing guarded update/readback/rollback transaction.

If no accepted saved value applies, ask for the administrator-confirmed full
employee portal URL. Show the guarded update and manual fallback guidance in
the ordinary current-task reply, after its controller-built lead-in, which is shown verbatim. The question body is only the requested-URL question below, with no
target topic, node, instance origin, current value, or classification
lines; keep those facts for your own checks.
Use the instance root only when the administrator explicitly confirms that exact root URL; otherwise ask for the confirmed path. Do not show a sample URL as the answer and do not ask for credentials.

Before the question, always write this as a normal reply to the Maker (not only
inside the question form), exactly as shown:

**Message:**

Next, we'll make sure the agent's HR case links open in the right employee portal.

**End message.**

Send the question below as ordinary chat text and end your turn. Never call
`ask_user` or any card tool: the maker answers by typing in chat, and a hook
blocks card tools during this flow.

<!-- plain-chat-question:v1 -->
**Message:**

What is the full HTTPS base URL of your ServiceNow employee portal? It may differ from the instance URL, so we won't assume `/sp` or `/esc`.

Reply here in chat with the URL.

**End message.**

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

Send the returned question's `plainText` verbatim as chat text and map the
typed reply with `match-reply`; it is a Yes or No question.
The question is "Is **{NORMALIZED_PORTAL_URL}** the employee portal URL?" and
the choices are "Yes" and "No". The question text carries the context.
A pasted new URL in the reply also means "No".
- **No**: save nothing and ask the URL question above
  again.
- **Yes**: show the returned `savedMessage` verbatim
  ("We'll save that portal URL."). Do not announce topic changes in this step;
  topics were handled in the earlier Topics step. Then run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} set-portal-url --portal-url <returned-portalUrl> --yes
```

Nothing is saved before the Maker replies **Yes**.

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

Then use the compact completion confirmation below. Send it as ordinary chat
text (never `ask_user` or any card tool), end your turn, and map the typed
reply: Yes means saved, No means not yet.

<!-- plain-chat-question:v1-manual-fallback -->
**Message:**

We couldn't update the portal URL automatically, so it needs to be set in Copilot Studio. Is `{PORTAL_URL}` now saved in the target topic?

You don't need to publish. A reply that it is saved triggers one fresh read-only verification.

Reply **Yes** or **No**.

**End message.**

After the maker replies **Yes**, run:

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
