# Configure the ServiceNow employee portal Base URI

Treat the HR employee portal URL as one complete high-level step. The instance
origin is already known from preflight, but the portal path is administrator
configuration and must never be inferred as `/sp`, `/esc`, or any other
example.

Run:

```text
python scripts/connect_servicenow_da.py inspect-portal-url
```

If the exact `ServiceNow HRSD Setup Configurations` topic already contains one
valid HTTPS Portal BaseURI on the confirmed ServiceNow instance and includes a
non-root portal path, return `ACTION_RESULT = "applied"` without a question or
mutation.

Otherwise ask for the administrator-confirmed full employee portal URL. The
question body must show the known instance origin, current value
classification, and the manual fallback. Do not show a sample URL as the
answer and do not ask for credentials.

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow employee portal",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: configure the HR agent's employee portal link in the exact `ServiceNow HRSD Setup Configurations` topic.\n\nOwner: ServiceNow / ESS administrator who knows the real employee portal entry point.\n\nKnown ServiceNow instance origin: `{SERVICENOW_INSTANCE_ORIGIN}`\nCurrent Portal BaseURI: {CURRENT_PORTAL_VALUE_CLASSIFICATION}\n\nProvide the complete HTTPS employee portal URL on this same instance, including the administrator-confirmed portal path. The instance origin alone is not enough, and the skill will not infer `/sp`, `/esc`, or any example path.\n\nThe skill will first try a guarded native component update of only the `Set ServiceNow Portal BaseURI` node. It uses a fresh change token, full topic preimage, readback verification, and conflict-safe rollback. If that API path is unsupported or permission denied without mutating the topic, use the manual fallback: Copilot Studio -> Topics -> ServiceNow HRSD Setup Configurations -> Set ServiceNow Portal BaseURI -> To -> enter this exact URL -> Save.\n\nWhat is the complete ServiceNow employee portal URL?",
    "allowFreeformInput": true
  }
]
```

Validate that the answer:

- is HTTPS;
- uses the confirmed `{instance}.service-now.com` host;
- includes a non-root portal path;
- has no credentials, query, or fragment.

Then run:

```text
python scripts/connect_servicenow_da.py set-portal-url --portal-url <full-url> --yes
```

On `committed`, return `ACTION_RESULT = "applied"`. The command must update
exactly one `ServiceNowHRSDSetupConfigurations` DialogComponent and exactly
one `Set ServiceNow Portal BaseURI` / `Global.ServiceNowHRSDPortalBaseURI`
SetVariable node, preserve all unrelated topic fields, use the fresh
`changeToken`, and verify the authored readback.

If the update returns `failed-unchanged` or an explicit permission/unsupported
error and a fresh read proves the topic stayed unchanged, show the manual
fallback above and use this visible **Completed / Not yet** confirmation:

<!-- visible-handoff-question:v1-manual-fallback -->
```json
[
  {
    "header": "Save portal Base URI manually",
    "question": "{CURRENT_PROGRESS}\n\nThe guarded component API did not change the topic, so complete the manual fallback now:\n1. Open Copilot Studio for the exact HR agent.\n2. Open Topics -> ServiceNow HRSD Setup Configurations.\n3. Edit the `Set ServiceNow Portal BaseURI` node.\n4. Set `To` to the exact administrator-confirmed URL `{PORTAL_URL}`.\n5. Save the topic.\n\nDo not publish yet; Publish remains a later explicit phase. When the exact value is saved, choose Completed so the skill can perform a fresh read-only verification.",
    "options": [
      { "label": "Completed" },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

After Completed, run:

```text
python scripts/connect_servicenow_da.py inspect-portal-url --expected-portal-url <full-url>
```

Only a fresh readback whose normalized authored value exactly matches the
complete URL supplied by the Maker for this phase completes the step. A
different same-instance HTTPS portal path is not sufficient. Never convert
HTTP 429, unknown mutation state, readback failure, conflict, or rollback
failure into a manual-success fallback. Stop and report those conditions;
honor Retry-After and do not probe repeatedly.

Do not publish the agent in this phase. Publishing remains the later explicit
Publish phase.
