<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 3 — Capture ServiceNow Connection Basics

Role: **Maker**, with Entra-admin and ServiceNow-admin confirmation where needed. This skill owns rows **S3.1**, **S3.2**, and **S3.3**. Skills 1 and 2 must already have verified the Power Platform environment, Dataverse, capacity, and base ESS agent.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do not rephrase, add commentary, or tell the user what tools you are calling or what files you are reading.

**Do not show internal variable names, Step IDs, checkpoint IDs, role-template IDs, hidden comments, or file paths to the user.** User-facing output is limited to Message blocks, shared checkpoint-result renders, and question prompts.

**Secrets:** never ask for ServiceNow passwords, client secrets, certificate private keys, or tokens through chat questions. Capture only non-secret identifiers, choices, and attestations.

**Files:** config `.local/connect/servicenow/config.json`; working checklist `.local/setup/servicenow/tasks.md`; template `src/skills/setup/servicenow/tasks.md`.

**Checkpoints this skill drives — run each in isolation:**

```
python scripts/flightcheck/cli.py --checkpoint SN-CONFIG-001
python scripts/flightcheck/cli.py --checkpoint SN-PERM-001
python scripts/flightcheck/cli.py --checkpoint SN-USER-001
```

After every run, immediately render the result per [`../shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a: show the compact table and any Manual / Warning / NotConfigured instructions before any later Message block or attestation question. Never ask the user to attest to a checkpoint whose manual steps have not been shown.

---

## P3.0 — Prepare working state

Read `.local/connect/servicenow/config.json` if it exists; otherwise start with an empty object. Every write in this skill is a merge: preserve unknown fields and other skills' data.

If `.local/setup/servicenow/tasks.md` does not exist, render it from the template: copy groups 1, 2, 3, 6, and 7; omit groups 4 and 5 until `authType` is known, and within group 6 omit both product sub-blocks (6a HR, 6b IT) until `scope` is known — keep only the always-on **6c. Shared connection** sub-block for now; preserve all hidden comments. Do not hand-edit row status markers — row updates go through the shared checklist-updater.

When rendering **group 6**, its two product sub-blocks — **6a. ServiceNow HR** and **6b. ServiceNow IT** — are variant groups, exactly like the mutually-exclusive auth groups 4/5: render **6a only when `scope.hrsd`** is true and **6b only when `scope.itsm`** is true; omit a product's sub-block entirely when it is out of scope. The **6c. Shared connection** sub-block is always rendered. Scope is captured in P3.2, so at the first render (P3.0, before scope is known) keep **both** product sub-blocks out — like the auth groups — and add the in-scope one(s) once P3.2 records `scope`. Never substitute or expand placeholders; the HR and IT rows are authored explicitly in the template.

If the working checklist already exists, leave it alone except for the auth-path insertion (P3.4), the in-scope product sub-block insertion (P3.4), and row updates through the updater.

---

## P3.1 — Apply the V2 scope gate

V2 setup supports exactly two sign-in methods: `entra_user` (Microsoft Entra ID user sign-in) and `entra_certificate` (Microsoft Entra ID OAuth with certificate).

Legacy `oauth2`, `basic`, and `graph` / federated knowledge connector paths are **out of scope** and are not supported by this setup flow (the old `connect/servicenow/` step files were retired).

If the maker requests username/password, dev/test basic auth, or Graph knowledge connector, show this and stop:

**Message:**

This setup path supports Microsoft Entra user sign-in or Microsoft Entra
certificate sign-in for ServiceNow. The older username/password, dev/test, and
Graph connector paths aren't part of this setup flow. Choose one of the Entra
sign-in methods to continue.

**End message.**

---

## P3.2 — Capture instance, products, sign-in, and usage

Ask these non-secret questions together:

```json
[
  { "header": "Instance URL", "question": "What's your ServiceNow instance URL? (e.g. https://yourcompany.service-now.com)" },
  { "header": "Products", "question": "Which ServiceNow products will this agent use?", "options": [{ "label": "ITSM", "description": "IT tickets, requests, incidents, and status" }, { "label": "HRSD", "description": "HR cases, case status, and HR services" }, { "label": "Both", "recommended": true }], "allowFreeformInput": false },
  { "header": "Sign-in method", "question": "How should the agent sign in to ServiceNow?", "options": [{ "label": "Microsoft Entra user sign-in", "description": "Employees use their Microsoft work account", "recommended": true }, { "label": "Microsoft Entra certificate sign-in", "description": "Service-to-service sign-in with an Entra app certificate" }, { "label": "I'm not sure" }], "allowFreeformInput": false }
]
```

Normalize answers:

- Instance accepts `https://dev347212.service-now.com`, `dev347212.service-now.com`, or `dev347212`; strip paths/trailing slashes; write canonical URL `https://{instanceName}.service-now.com`.
- Products set `scope.itsm`, `scope.hrsd`, and `usage` (`itsm`, `hrsd`, or `both`).
- Connector is fixed in V2 and must be stored as `connectorType = "powerplatform"`.
- Sign-in maps to `authType = "entra_user"` or `"entra_certificate"`; "I'm not sure" triggers P3.2a.

---

## P3.2b — HRSD prerequisite: confirm `sn_hr_core` plugin

Run this gate only when `scope.hrsd == true`.

Ask:

```json
[
  { "header": "HRSD plugin", "question": "Is the ServiceNow HR Core plugin (sn_hr_core) installed and active in this instance?", "options": [{ "label": "Yes", "recommended": true }, { "label": "No" }, { "label": "Not sure" }], "allowFreeformInput": false }
]
```

- If **Yes**: continue.
- If **No** or **Not sure**: show this and stop.

**Message:**

Before we continue with HRSD setup, install the ServiceNow HR Core plugin
(`sn_hr_core`) in your ServiceNow instance.

Open:
`https://{instanceName}.service-now.com/now/app-manager/home/plugin/id/com.sn_hr_core/details`

After the plugin is installed and active, tell me and I'll continue.

**End message.**

Do not proceed to P3.3 until this prerequisite is confirmed.

---

## P3.2a — Disambiguate "I'm not sure"

Ask one follow-up only when the maker selected "I'm not sure":

```json
[
  { "header": "Sign-in", "question": "When employees sign in to ServiceNow today, do they go through a Microsoft sign-in page with their work or school account?", "options": [{ "label": "Yes", "recommended": true }, { "label": "No" }, { "label": "Still not sure" }], "allowFreeformInput": false }
]
```

Map **Yes** to `entra_user`. For **No**, show the P3.1 V2-scope message and stop unless the maker chooses a V2 method. For **Still not sure**, set `entra_user` and show:

**Message:**

I'll use Microsoft Entra user sign-in for now. It's the most common ServiceNow
sign-in path, and you can rerun setup later if you need the certificate path
instead.

**End message.**

---

## P3.3 — Save V2 config and verify S3.1

Merge these fields into `.local/connect/servicenow/config.json`:

```json
{
  "instanceName": "{instanceName}",
  "instanceUrl": "https://{instanceName}.service-now.com",
  "connectorType": "powerplatform",
  "scope": { "hrsd": false, "itsm": false },
  "usage": "itsm|hrsd|both",
  "authType": "entra_user|entra_certificate",
  "portalBaseUrl": null,
  "makerPermissions": { "entraAdmin": null, "serviceNowAdmin": null },
  "entra": {},
  "packs": {},
  "connections": {},
  "setupStatus": {},
  "productStatus": {},
  "stepStatus": {}
}
```

**Preserve completed state on a re-run — these are first-run defaults, not
overwrites.** When the config already exists, apply a value from the block above
**only if the target key is absent or still null/empty**; never overwrite a key that
already holds a real value. In particular, do **not** reset `portalBaseUrl`,
`makerPermissions`, `entra`, `connections`, `packs`, `setupStatus`, `productStatus`,
or `stepStatus` back to `null`/`{}`, and do **not** flip an already-`true` `scope`
flag to `false` — only the answers the maker just gave in P3.2 may change `scope`,
`usage`, `instanceName`, `authType`, and `instanceUrl`. To **add a product** to an
already-complete setup, do not run this skill at all: use the **Add a product**
transition in `SKILL.md`, which expands scope without touching completed state.

Set `packs.itsm = "pending"` and/or `packs.hrsd = "pending"` from scope unless a more advanced value already exists. Keep `setupStatus` (shared steps) and `productStatus` (per-product steps: install / portal, keyed by `hrsd` / `itsm`) as the setup source of truth and preserve `stepStatus` for legacy compatibility if already present.

Run:

```
python scripts/flightcheck/cli.py --checkpoint SN-CONFIG-001
```

Render the checkpoint result immediately. If `PASSED`, continue. If `FAILED`, keep S3.1 blocked through P3.5 and return to P3.2 after the maker corrects the inputs. If `WARNING`, `MANUAL`, or indeterminate, keep S3.1 in progress; do not complete it until the checkpoint passes.

---

## P3.4 — Render the selected auth-path group

Once `authType` is set, update `.local/setup/servicenow/tasks.md` from the canonical template before recording S3.1:

- `authType == "entra_user"` → render group 4 exactly; omit group 5.
- `authType == "entra_certificate"` → render group 5 exactly; omit group 4.
- Never render both groups; if a stale wrong group exists, remove it.
- Insert the selected group in template order between groups 3 and 6.
- Preserve existing status markers and hidden comments for all other rows.

This makes the selected path durable even if a later row stops.

Also render the in-scope **group 6 product sub-blocks** here (scope is known once P3.2 recorded it):

- `scope.hrsd == true` → render sub-block **6a. ServiceNow HR** exactly; otherwise omit it.
- `scope.itsm == true` → render sub-block **6b. ServiceNow IT** exactly; otherwise omit it.
- Always keep **6c. Shared connection**. Render sub-blocks in template order (6a, 6b, 6c).
- If a stale out-of-scope product sub-block exists, remove it. Preserve existing status markers and hidden comments for all rows that stay.

This makes the in-scope products durable even if a later row stops.

---

When `SN-CONFIG-001` passed, show:

**Message:**

Your ServiceNow instance, product scope, and sign-in method are saved.
I'll use that sign-in path for the remaining setup steps.

**End message.**

Update S3.1 through [`../shared/checklist-updater.md`](../shared/checklist-updater.md): `STEP_ID = "S3.1"`, `GATE = "prog"`, `CHECKPOINT_RESULT` = the actual `SN-CONFIG-001` result, `ACK = false`. Persist immediately. Do not batch with S3.2 or S3.3.

---

## P3.6 — Confirm maker permissions and verify S3.2

Probe Entra admin capability read-only with Microsoft Graph, for example:

```
az rest --method GET --url "https://graph.microsoft.com/v1.0/me/memberOf/microsoft.graph.directoryRole?%24select=roleTemplateId,displayName" --query "value[]" -o json
```

Count the maker as Entra-admin capable if the result includes a role that can create app registrations and grant admin consent, such as Global Administrator, Application Administrator, or Cloud Application Administrator. If Azure sign-in is missing, follow `src/skills/connect/azure/login.md`, retry once, and treat remaining uncertainty as "not held" rather than assuming success.

Then ask for ServiceNow admin availability:

**Message:**

Next I'll check whether setup can automate the Entra parts and whether a
ServiceNow admin is available for the ServiceNow-side configuration.

**End message.**

```json
[
  { "header": "ServiceNow admin availability", "question": "Is someone available who can administer this ServiceNow instance, register an OIDC provider, and elevate to security_admin when needed?", "options": [{ "label": "Yes — I can do it", "recommended": true }, { "label": "Yes — another ServiceNow admin will do it" }, { "label": "No / not sure" }], "allowFreeformInput": false }
]
```

Persist a makerPermissions summary, merging with existing config:

```json
{
  "makerPermissions": {
    "entraAdmin": true,
    "entraAdminEvidence": "programmatic role probe passed|not held|probe unavailable",
    "serviceNowAdmin": true,
    "serviceNowAdminEvidence": "user attested self|user attested another admin available|not available"
  }
}
```

Do not show raw booleans, role-template IDs, or evidence object names to the user.

Run:

```
python scripts/flightcheck/cli.py --checkpoint SN-PERM-001
```

Render the result immediately. If `PASSED`, S3.2 completes programmatically. If a needed admin is unavailable, apply the stop behavior from [`../shared/permission-gate.md`](../shared/permission-gate.md) for the missing role and leave S3.2 blocked. For `MANUAL`, `WARNING`, or probe-unavailable results, after rendering manual steps ask the checklist-updater §U.2 acknowledgement; only explicit acknowledgement can complete the row manually.

Update S3.2 immediately through the shared checklist-updater: `STEP_ID = "S3.2"`; `GATE = "prog"` when the checkpoint passed, otherwise `"manual"`; `CHECKPOINT_RESULT` = the actual `SN-PERM-001` result; `ACK = true` only after explicit manual acknowledgement.

---

## P3.7 — Optional read-only ServiceNow user lookup helper

S3.3 is an attestation gate, but use read-only tooling when it is already available. Do **not** create a test user.

If a ServiceNow MCP server or equivalent read-only connector is already running, query `sys_user` by the mapped identity field with limit 1, for example:

```
query_table(table="sys_user", query="email={signInValue}^active=true", fields="sys_id,user_name,email,active", limit=1)
query_table(table="sys_user", query="user_name={signInValue}^active=true", fields="sys_id,user_name,email,active", limit=1)
```

Use the planned mapping: user sign-in commonly maps Entra `upn` to ServiceNow `email` or `user_name`; certificate sign-in maps the system identity to the field configured for that system user.

If the MCP helper is not already available, configure it only if the repo provides `src/mcp/servicenow/requirements.txt` and the user wants the helper. Merge any `.vscode/mcp.json` changes without removing existing servers. Credential inputs must be masked by the host UI or supplied out of band; never request secrets in chat.

The lookup provides evidence only. S3.3 still requires operator acknowledgement.

---

## P3.8 — Confirm active ServiceNow user record and verify S3.3

This row remediates a spec gap: the spec defines claim-to-user mapping and lists silent login / empty-result symptoms, but omits verifying that the mapped user exists. Without this check, sign-in may succeed while ServiceNow cannot match the identity, causing queries to return empty.

**Message:**

Before we configure the rest of sign-in, confirm the person who will sign in
already has an active ServiceNow user record. This matters because authentication
can succeed even when ServiceNow can't match the identity to a user; in that case,
the agent's queries may come back empty.

**End message.**

Ask for non-secret mapping evidence:

```json
[
  { "header": "ServiceNow user mapping", "question": "Which ServiceNow field will match the sign-in identity?", "options": [{ "label": "email", "recommended": true }, { "label": "user_name" }, { "label": "Other" }], "allowFreeformInput": true },
  { "header": "Active user record", "question": "Have you confirmed the sign-in person exists as an ACTIVE ServiceNow user using that mapped field?", "options": [{ "label": "Yes — I confirmed the active user record", "recommended": true }, { "label": "Not yet" }], "allowFreeformInput": false }
]
```

If not yet confirmed, show:

**Message:**

Please have a ServiceNow admin look up the person in ServiceNow Users, confirm
the mapped field matches their sign-in identity, and confirm the record is active.
Don't create a test user for this setup check — verify the real person or system
user that will be used.

**End message.**

Persist minimal evidence only:

```json
{
  "userRecord": {
    "mappedField": "email|user_name|other",
    "activeUserConfirmed": true,
    "verifiedBy": "read-only lookup|attested",
    "note": "operator confirmed the mapped active user record exists"
  }
}
```

Run:

```
python scripts/flightcheck/cli.py --checkpoint SN-USER-001
```

Render the result immediately. Because S3.3 is an attestation row, a passing or manual checkpoint never completes it by itself. The row completes only after the operator explicitly confirms the active mapped user record and evidence is captured.

Update S3.3 immediately through the shared checklist-updater: `STEP_ID = "S3.3"`; `GATE = "attest"`; `CHECKPOINT_RESULT` = the actual `SN-USER-001` result; `ACK = true` only after explicit confirmation and evidence capture.

If the active user record cannot be confirmed, keep S3.3 in progress, or blocked on a definitive missing-user failure, and stop. Do not proceed to sign-in provisioning until this row is done.

---

## Done

**Message:**

ServiceNow connection basics are captured: the instance, product scope, sign-in
path, setup permissions, and active user record are ready. Next, we'll configure
the selected ServiceNow sign-in path.

**End message.**

Rows S3.1, S3.2, and S3.3 are recorded in the checklist. Stop here; the router will resume into the selected sign-in skill.
