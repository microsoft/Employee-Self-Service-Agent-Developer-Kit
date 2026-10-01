# Discover existing admin setup before creating anything

Preflight is state/API driven. It does not ask the Maker to classify setup
progress.

- **Goal:** discover remote setup first, automatically reuse each valid
  existing item, and send only missing or unhealthy items to their owning
  setup phase.
- **Owner role:** the skill reads canonical `/setup` state, lifecycle state,
  and supported read-only discovery.
- **Completion evidence:** a trusted or explicitly supplied public ServiceNow
  instance URL plus current read-only resource discovery.

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
python scripts/connect_servicenow_da.py migrate-state
```

Run read-only discovery:

```text
python scripts/connect_servicenow_da.py inspect-admin-setup
```

Show the discovery exactly as evidence:

- every connector-scoped `entraIDUserLogin` connection candidate and its
  current status, Instance Name, and Resource URI;
- the App/OIDC/plugin evidence that is known;
- every item that cannot be verified through a supported read-only API.

Local state absence is not evidence that a remote app, OIDC provider, plugin,
or connection is absent. Never create, patch, or recreate a remote object from
this action.

If `instanceInputRequired` is `false`, briefly summarize what was found and do
not ask a progress/scenario question.

Only when `instanceInputRequired` is `true`, use one standalone
`vscode_askQuestions` free-form question for the public ServiceNow HTTPS
instance URL. Never ask for credentials, tokens, secrets, or a portal URL.
While that question is pending, do not return an action result. If the Maker
is not ready to provide the URL, return `ACTION_RESULT = "waiting"`. After the
answer, persist the normalized instance and refresh discovery:

```text
python scripts/connect_servicenow_da.py record-preflight --instance-url <https://instance.service-now.com>
python scripts/connect_servicenow_da.py inspect-admin-setup
```

Return `ACTION_RESULT = "recorded"` after discovery is persisted. The
subsequent plugin, Entra, OIDC, and credential phases independently reverify
their own evidence and automatically skip only the valid item they own.
A Connected physical connection does not prove that the Entra app, consent,
HR Core, OIDC provider, or user mapping are complete.
