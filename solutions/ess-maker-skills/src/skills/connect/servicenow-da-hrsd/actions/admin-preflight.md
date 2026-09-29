# Discover existing admin setup before creating anything

Treat preflight and reuse approval as one complete high-level step with one
pause boundary.

- **Goal:** discover remote setup first and decide what may be reused without
  rebuilding valid remote objects.
- **Owner role:** Maker coordinating with the ServiceNow/Entra admins who know
  which tenant resources already exist.
- **Completion evidence:** confirmed ServiceNow instance URL, existing-setup
  scenario, and one explicit reuse-versus-configure-missing decision.

Run:

```text
python scripts/connect_servicenow_da.py migrate-state
```

Run read-only discovery before asking the single preflight question:

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

Then use one bundled question form for the complete preflight/reuse step. It
must collect:

1. which situation matches:

- a Connected Microsoft Entra ID User Login connection already exists;
- the Entra app and ServiceNow OIDC setup exist, but no connection exists;
- only the ServiceNow instance/plugins exist;
- start from scratch;
- unsure, discover what is visible.

2. the confirmed ServiceNow public HTTPS instance URL, never credentials,
   tokens, secrets, or a portal URL; and
3. one explicit decision:
   - **Reuse discovered setup and verify each item**; or
   - **Configure only the missing or invalid items**.

An exactly-one candidate is still not approval. While this one bundled form is
pending, do not return an action result. If the Maker is not ready, return
`ACTION_RESULT = "waiting"`.

After the single Maker return, persist the scenario and normalized instance,
refresh discovery, then persist the decision:

```text
python scripts/connect_servicenow_da.py record-preflight --scenario <connected|app-oidc|plugins-only|scratch|unsure> --instance-url <https://instance.service-now.com>
python scripts/connect_servicenow_da.py inspect-admin-setup
python scripts/connect_servicenow_da.py record-reuse-decision --decision <reuse-discovered|configure-missing>
```

Return `ACTION_RESULT = "recorded"` only after the decision is persisted.
