# Discover existing admin setup before creating anything

Preflight is state/API driven. It does not ask the Maker to classify setup
progress.

- **Goal:** confirm the exact prepared ESS agent, environment, realm, and one
  Maker-selected public ServiceNow instance before configuration begins.
- **Owner role:** the skill reads canonical `/setup` state, lifecycle state,
  and supported read-only discovery.
- **Completion evidence:** a valid prior confirmation for the same target or
  one explicit Maker-confirmed public ServiceNow instance URL.

Read `adminSetup.phaseHandoffs.preflight` first. If it is already
`completed`, refresh `inspect-admin-setup`. If the stored instance is still
present and stored phase checkpoint results are empty or
all in this phase's `completionStatuses`, do not ask again; return
`ACTION_RESULT = "recorded"` so the runner can reverify. Discovery changes do
not require a global reuse decision: later phases own verification and repair
for their individual resources.

Any prior result outside `completionStatuses` requires a fresh read-only
discovery. Missing instance evidence requires only the standalone URL question
below.

Run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} migrate-state
```

Run migration and discovery as two separate terminal invocations. Never chain
them into one command: migration is local, while discovery can authenticate
and call a remote read API.

Run read-only discovery:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-admin-setup
```

Before running discovery, tell the Maker:

> We're checking your ServiceNow connections, read-only. If a Microsoft
> sign-in window opens, please complete it, and we'll continue once you're
> signed in.

Parse the first `DA_ADMIN_PREFLIGHT_PROGRESS_JSON:` marker with
`stage: authentication` as client/auth preparation. Do not say that the HTTP
inventory read has started at that marker. Parse the later marker with
`stage: connection-inventory` as proof that authentication completed and the
HTTP read is starting.

When optional connection discovery returns an error:

- preserve and show the exact error and its details; never describe it as an
  empty inventory;
- do not automatically select a cached or discovered instance;
- allow the Maker to provide one public HTTPS root URL for target
  confirmation; later credential discovery and health checks still fail
  closed if their required reads fail;
- for `category: timeout`, say that the configured HTTP connect/read timeout
  was reached, not that the whole invocation lasted exactly 60 seconds. State
  that no remote write was attempted and the Maker can retry
  `/connect servicenow` after checking network access;
- for `category: throttled`, show `retryAfter`, wait at least that long, and do
  not automatically retry;
- for another HTTP/transport error, preserve its status, error code, request
  ID, and supported retry instruction.

Do not describe authorization waiting as API processing. Do not start another
discovery while the first command is running. A read-only discovery failure
does not authorize continuing with cached connection evidence.

Keep the discovery evidence agent-facing. Do not show a candidate list, a
status table, a Resource URI, a connection ID, or the App/OIDC/plugin evidence
to the Maker; those values are technical. Say only what the Maker needs: the
one plain question below. Items that cannot be verified through a supported
read-only API stay internal and are re-checked by the later phases.

Local state absence is not evidence that a remote app, OIDC provider, plugin,
or connection is absent. Never create, patch, or recreate a remote object from
this action.

If `instanceInputRequired` is `false`, reuse the valid prior confirmation and
do not ask again. A newly visible connection never changes the confirmed
instance automatically.

When `instanceInputRequired` is `true`, the returned `instanceQuestion` is
already plain chat text (`servicenow.plain-question.v1`). Send its `plainText`
verbatim as an ordinary assistant message, never through `ask_user` or any
input or selection card, and wait for the Maker's typed reply. Never write your
own version of this question or add the connection details to it.

- With one candidate the question asks "Yes" or "No" to use the found
  instance. With several, it lists them by number plus an option to use
  another. Map the typed reply with `match-reply`, passing the returned
  `instanceQuestion` on stdin, then translate the matched label through
  `instanceChoices`; never ask the Maker to copy an internal key. A pasted
  ServiceNow URL in any reply is the manually provided instance.
- When the reply means "use another instance", send the `plainText` of
  `manualInstanceQuestion` verbatim. Do not construct or shorten another
  free-form question.
- With no candidates, the returned question is already that free-form URL
  question.
- Discovery errors remain visible in the question. Manual target confirmation
  does not prove connection health, select/reuse a credential, create an
  instance, or bind the agent.

The no-candidate/manual-URL form uses the text below. The controller adds any
bounded discovery error and returns the final text as `plainText`; send that
`plainText` verbatim as ordinary chat text and end your turn. Never call
`ask_user` or any card tool.

<!-- plain-chat-question:v1 -->
**Message:**

Which ServiceNow instance should {AGENT_DISPLAY_NAME} use? Reply here in chat with its public HTTPS URL, not credentials.

Example: `https://<your-instance>.service-now.com`

Use only the instance address, without a portal path such as `/sp` or `/esc`. If you don't know it, ask your ServiceNow administrator.

{DISCOVERY_ERROR_IF_ANY}

**End message.**

While that question is pending, do not return an action result. If the Maker
is not ready to provide the URL, return `ACTION_RESULT = "waiting"`. After the
selected or entered URL is confirmed, persist it and refresh discovery:

Do not call `next-step`, `resume-handoff`, or the preflight checkpoint between
showing the question and recording its answer. If a redundant provider
`resume-handoff` call occurs, its top-level `pendingInput` is authoritative:
send its `question.plainText` verbatim and stop without running a checkpoint.

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-preflight --instance-url <https://instance.service-now.com>
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} inspect-admin-setup
```

If the refreshed result contains `links.serviceNowInstance`, preserve it for
later phases and do not display an action link before the Entra step.

Return `ACTION_RESULT = "recorded"` after discovery is persisted. The
subsequent plugin, Entra, OIDC, and credential phases independently reverify
their own evidence.
A Connected physical connection does not prove that the Entra app, connector
authorization, HR Core, OIDC provider, or user mapping are complete.
