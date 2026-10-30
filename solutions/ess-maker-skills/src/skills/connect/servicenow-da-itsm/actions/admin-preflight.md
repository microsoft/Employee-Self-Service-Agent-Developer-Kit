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

Run read-only discovery:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} inspect-admin-setup
```

Before running discovery, tell the Maker:

> Preparing read-only ServiceNow connection discovery. If Microsoft sign-in
> opens, complete it; while the browser is waiting, setup is waiting for
> authorization, not processing the ServiceNow API. After authorization, the
> connection inventory request uses a 60-second HTTP connect/read timeout.
> That is not a 60-second limit for the whole invocation, and a server that
> continues returning bytes may keep a read active.

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

Show the discovery exactly as evidence:

- every connector-scoped `entraIDUserLogin` connection candidate and its
  current status, Instance Name, and Resource URI;
- the App/OIDC evidence that is known;
- every item that cannot be verified through a supported read-only API.

Local state absence is not evidence that a remote app, OIDC provider, or
connection is absent. Never create, patch, or recreate a remote object from
this action.

If `instanceInputRequired` is `false`, reuse the valid prior confirmation,
briefly summarize discovery, and do not ask again. A newly visible connection
never changes the confirmed instance automatically.

When `instanceInputRequired` is `true`, send the exact returned
`instanceQuestion` through `vscode_askQuestions`:

- With candidates, every normalized URL is a separate **Use <URL>** choice,
  even when there is only one, plus **Provide another ServiceNow instance
  URL**. Translate the selected label through `instanceChoices`; never ask the
  Maker to copy an internal key.
- **Provide another ServiceNow instance URL** opens the exact returned
  `manualInstanceQuestion`. Do not construct or shorten another free-form
  question.
- With no candidates, the returned question is already that free-form URL
  question.
- Discovery errors remain visible in the question. Manual target confirmation
  does not prove connection health, select/reuse a credential, create an
  instance, or bind the agent.

The no-candidate/manual-URL form uses this supported visible shape. The
runtime-rendered question may add the bounded discovery error:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow instance",
    "question": "{CURRENT_PROGRESS}\n\nFor {AGENT_DISPLAY_NAME} (`{SELECTED_AGENT_SLUG}`) in environment `{ENVIRONMENT_ID}` and {REALM} realm, enter the intended public ServiceNow HTTPS root URL.\n\nExample: `https://dev184242.service-now.com`\n\nUse only the instance root (`https://<instance>.service-now.com`). Do not enter a portal or module path such as `/sp`, `/esc`, or `/now/...`. Do not enter a username, password, credential, token, secret, or certificate. If you do not know the URL, ask your ServiceNow administrator for the public instance root.\n\n{DISCOVERY_ERROR_IF_ANY}",
    "allowFreeformInput": true
  }
]
```

While that question is pending, do not return an action result. If the Maker
is not ready to provide the URL, return `ACTION_RESULT = "waiting"`. After the
selected or entered URL is confirmed, persist it and refresh discovery:

Do not call `next-step`, `resume-handoff`, or the preflight checkpoint between
showing the question and recording its answer. If a redundant provider
`resume-handoff` call occurs, its top-level `pendingInput` is authoritative:
show that exact question and stop without running a checkpoint.

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} record-preflight --instance-url <https://instance.service-now.com>
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} inspect-admin-setup
```

If the refreshed result contains `links.serviceNowInstance`, preserve it for
later phases and do not display an action link before the Entra step.

Return `ACTION_RESULT = "recorded"` after discovery is persisted. The
subsequent Entra, OIDC, and credential phases independently reverify
their own evidence.
A Connected physical connection does not prove that the Entra app, connector
authorization, OIDC provider, or user mapping are complete.
