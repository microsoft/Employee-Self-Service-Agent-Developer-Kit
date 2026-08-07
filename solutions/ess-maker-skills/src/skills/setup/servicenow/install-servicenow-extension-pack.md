<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 6 — Install the ServiceNow Extension Pack
Role: **Environment Maker**. This skill installs the ServiceNow extension pack(s),
binds ServiceNow and Dataverse connections, sets the portal URL used by returned
links, verifies the ServiceNow cloud flows, and records rows **S6.0 through S6.6**.
Depends on skills 1–5 as applicable: the environment, Dataverse, ESS base agent,
ServiceNow connection basics, and the selected ServiceNow sign-in path must already
exist. Read the selected path from `.local/connect/servicenow/config.json` as
`authType`.
Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.
**Do not show internal variable names, Step IDs, checkpoint IDs, hidden checklist
comments, or config file paths to the user.** User-facing text is limited to Message
blocks, checkpoint-result tables rendered by the shared checklist updater, manual
verification details, and question prompts.
**Secrets:** never ask for ServiceNow passwords, client secrets, certificate private
keys, certificate passwords, PFX bytes, or any other secret through chat. For the
certificate path, use only the saved certificate file path and tell the maker to use
the password they received when the certificate was generated. Do not write that
password to any config file.
**Files this skill owns or updates:**
- Config: `.local/connect/servicenow/config.json`
- Working checklist: `.local/setup/servicenow/tasks.md`
- Checklist template: `src/skills/setup/servicenow/tasks.md`
**Files this skill may read, but not own:**
- `.local/config.json` — read-only source for `dataverseEndpoint` and agent details;
  write only the legacy `connections.ServiceNow` summary described in P6.3d.
**Checkpoints this skill drives (run each in isolation):**
| Step | Checkpoint | Gate |
|------|------------|------|
| S6.0 | `SN-CONN-OBJECTS-001` — ServiceNow + Dataverse connection objects exist and are connected | prog (maker creates, checkpoint verifies) |
| S6.1 | `SN-PKG-001` — ServiceNow extension pack(s) installed | prog (maker installs, checkpoint verifies) |
| S6.2 | ServiceNow connection reference bound by the maker (connection health confirmed when the maker connects the flow invoker at S6.4) | prog; auth type may require attestation |
| S6.2 | `SN-DV-CONN-001` — Dataverse connection reference active | prog |
| S6.3 | `SN-FLOW-*` — ServiceNow cloud flows enabled *(per-product: `productStatus.<product>`)* | prog |
| S6.4 | ServiceNow flow invoker connection connected by the maker *(per-product: `productStatus.<product>`)* | attest |
| S6.5 | Connection parameters shared by the maker onto the portal-owned reference *(per-product: `productStatus.<product>`)* | attest |
| S6.6 | `SN-BASEURL-001` — portal base URL matches the confirmed value *(per-product: `productStatus.<product>`)* | prog; attest only if unverifiable (`Skipped`/`Warning`), never on `Failed` |
Run any individually-registered checkpoint by itself:
```
python scripts/flightcheck/cli.py --checkpoint <ID>
```
Only `SN-PKG-001`, `SN-DV-CONN-001`, `SN-BASEURL-001`, and the `SN-ENTRA-*`
checks are registered as standalone `--checkpoint` IDs this skill uses. `SN-FLOW-*`
is emitted **only** by the ServiceNow scope run — get it with
`python scripts/flightcheck/cli.py --scope servicenow --no-open` and read the matching
row(s) from the results. **If a `--checkpoint <ID>` call returns "unknown checkpoint",
that ID is scope-emitted: switch to the scope run and read the row. Never treat an
"unknown checkpoint" message as a setup blocker, and never stop the flow because of
it — the maker still performs the underlying step (install, bind, activate) by hand.**
**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` / `Warning` / `NotConfigured` row, its
full verification steps — before you show any later Message block or ask any
attestation question. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees manual steps; never ask a user to
attest to steps they have not been shown.
`SN-FLOW-*` is a data-driven family. Expand S6.3 into one checkbox per emitted flow
result, using the checkpoint description as the visible flow label, and update each
generated row immediately. Do not batch the flow updates. **S6.3 is per-product:**
each `SN-FLOW-*` row is labelled `HRSD` or `ITSM`, so route each flow update to that
product's row (`PRODUCT="hrsd"` / `"itsm"` → `productStatus.<product>`). A product's
S6.3 is complete only when **all** of that product's flow rows pass; complete each
product independently.
**Build order and resume.** Always run P6.0 first, then P6.1 (restore state) and
P6.1a (ensure the shared ServiceNow + Dataverse connections exist), then run P6.2's
pack lookup before the first incomplete row. These are idempotent and rehydrate
state used by the connection, flow, and portal URL checks. After that, skip any row
whose `setupStatus` state is already `done` — **except P6.3's connection bind, which
you
always re-verify: a pack reinstall can silently unbind a reference, so never trust a
recorded S6.2 without re-confirming the ServiceNow reference is bound to an active
connection.**
The connection/flow chain runs in this order: **create connections (P6.1a) →
install (P6.2) → bind connection references (P6.3) → turn on flows (P6.4) → connect
and share (P6.5) → portal URL (P6.6)**. Connection *creation* needs only the sign-in
method from skill 4/5, so it runs **before** install; but each pack's connection
*references* and cloud flows ship **inside** the pack, so binding and activation
stay after install. A cloud flow can only hold activation once its connection
references are bound, and the flow invoker binding must land on the activated flow
definition, so this order is deliberate — do not reorder it.

**State persistence.** Each step records its confirmed outcome into
`.local/connect/servicenow/config.json` via the shared
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) and the explicit
config merges shown in each step — the factual `packs` / `connections` / `status`
artifacts plus the `setupStatus` / `productStatus` step(s) it owns (S6.0–S6.6).
Persist each row immediately, before continuing to the next step, so a resume
continues from the first incomplete step.
---
## P6.0 — Role gate (Environment Maker)
Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
extension-pack or connection work, with:
- `REQUIRED_ROLE` = `"Environment Maker"`
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S6.1"`
- `ROLE_QUERY` = a Dataverse security-role membership check for the signed-in user.
  Read `dataverseEndpoint` from `.local/config.json`; call it `{ENV_URL}`.
Resolve the caller and roles:
```
az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/WhoAmI" --query "UserId" -o tsv
```
```
az rest --method GET --resource "{ENV_URL}" --url "{ENV_URL}/api/data/v9.2/systemusers%28{USER_ID}%29/systemuserroles_association?%24select=name" --query "value[].name" -o json
```
The role is held if the returned names include **Environment Maker**, **System
Customizer**, or **System Administrator**. Treat insufficient privilege, forbidden,
or authorization-denied responses as "role not held". If the query errors for an
unrelated reason, follow the shared gate's retry-then-attest fallback — never assume
pass. If `GATE_RESULT` is `"stop"`, halt. Otherwise carry `GATE_EVIDENCE` forward
and record it when rows are updated.
---
## P6.1 — Restore setup state and derive product/auth values
Read `.local/connect/servicenow/config.json`. If it is missing, stop and route back
to the ServiceNow connection basics skill; this skill cannot infer the instance,
product scope, or sign-in method.
Restore:
- `instanceName` and `instanceUrl`; derive one from the other if needed.
- `usage` and `scope`. `itsm` means ITSM only, `hrsd` means HRSD only, and `both`
  means ITSM then HRSD. Prefer explicit `scope` when present.
- `authType`, which must be `entra_user` or `entra_certificate`.
- `entra.appClientId` for `entra_user`.
- `certificate.tenantId`, `certificate.appAClientId`, `certificate.appBClientId`,
  and `certificate.certPfxPath` for `entra_certificate`.
- Existing `packs`, `connections`, `portalBaseUrl`, `setupStatus`, and
  `productStatus` (per-product install / portal state, keyed by `hrsd` / `itsm`).
If `authType` is missing or not supported, stop and route back to the selected
sign-in setup skill. Do not offer legacy auth in this playbook.
Build the in-scope pack list in this order: ITSM when `scope.itsm` is true, then
HRSD when `scope.hrsd` is true. Use **ServiceNow IT** and **ServiceNow HR** as the
user-facing names. Ensure each in-scope `packs.<product>` exists with at least
`"pending"`, unless it already records a more advanced state. Merge only; never drop
fields written by earlier setup skills.
Read `.local/config.json` read-only for `dataverseEndpoint` and `agent` details. Do
not write ServiceNow setup fields into that file except for the legacy connection
summary in P6.3d.
---
## P6.1a — Create the ServiceNow and Dataverse connections *(completes S6.0)*
Create the shared Power Platform **ServiceNow** connection (using the sign-in method
from skill 4/5) and the **Dataverse** connection **now, before installing any pack**.
Creating the connections up front does not need the extension pack — the pack only
adds the *connection references* that P6.3 later binds to these connections — and it
means both the install dialog (P6.2) and the reference bind (P6.3) reuse an existing
connection instead of prompting for credentials again.
Skip creation for any connection that already exists: check
[Power Automate → Connections](https://make.powerautomate.com/connections), or
`connections.servicenow.state` / `connections.dataverse.state` already at `created`
or `bound` in config. Re-create only if a connection is missing or unhealthy.
**Message:**

Before we install anything, let's create the two connections your agent will reuse —
one for ServiceNow and one for Microsoft Dataverse — so nothing has to
re-authenticate later.

1. Open [Power Apps → Connections](https://make.powerapps.com/connections), and make
   sure the environment selector shows the environment we're setting up.
2. Select **New connection**, search for **ServiceNow**, and create it using the
   details for your sign-in method that I'll give you next.
3. Select **New connection** again, search for **Microsoft Dataverse**, and create
   it by signing in with your maker account.

**End message.**
Then show the ServiceNow connection values for the selected auth type.
For `authType == "entra_user"`, require `entra.appClientId` (route back to the user
sign-in playbook if missing) and show:
**Message:**

For the **ServiceNow** connection, use:

| Field | Value |
|-------|-------|
| **Authentication Type** | Microsoft Entra ID User Login |
| **Resource URI** | `{APP_CLIENT_ID}` |
| **Instance Name** | `{INSTANCE_NAME}` |

Sign in with your Microsoft work account when prompted.

**End message.**
For `authType == "entra_certificate"`, require `certificate.tenantId`,
`certificate.appAClientId`, `certificate.appBClientId`, and
`certificate.certPfxPath` (route back to the certificate playbook if any are
missing; confirm the PFX exists). Open the certificate for the maker
(`explorer.exe /select,"{CERT_PFX_PATH}"`) and show:
**Message:**

For the **ServiceNow** connection, use:

| Field | Value |
|-------|-------|
| **Authentication Type** | Microsoft Entra ID OAuth using Certificate |
| **Instance Name** | `{INSTANCE_NAME}` |
| **Tenant ID** | `{TENANT_ID}` |
| **Client ID** | `{APP_B_CLIENT_ID}` |
| **Resource URI** | `{APP_A_CLIENT_ID}` |
| **Client Secret** | Upload the `.pfx` certificate file I opened for you |
| **Certificate password** | Use the password shown when the certificate was generated |

**End message.**
Confirm the maker created both connections (ask with the question tool, options
**Yes, both are created** / **Not yet**). Only an explicit **Yes** completes this
action — connection creation is a prerequisite for the P6.3 bind, so if the maker
hasn't done it, leave S6.0 `in-progress` and continue only once they confirm.
On confirmation, merge `.local/connect/servicenow/config.json`:
```json
{
  "connections": {
    "servicenow": { "state": "created", "authType": "{authType}" },
    "dataverse": { "state": "created" }
  }
}
```
Run `python scripts/flightcheck/cli.py --checkpoint SN-CONN-OBJECTS-001` and render
the result immediately. `PASSED` completes S6.0. `FAILED` or `NotConfigured` keeps
the row blocked while the maker creates or re-authenticates the named connection,
then loops until the check passes. `MANUAL` means the inventory could not be read;
after showing the result, explicit maker confirmation may complete the row through
the attestation fallback.

Then update **S6.0** via [`../shared/checklist-updater.md`](../shared/checklist-updater.md)
with `STEP_ID="S6.0"`, `GATE="prog"` and the actual checkpoint result. Use
`GATE="attest"`, `ACK=true` only for the `MANUAL` fallback. Persist
`GATE_EVIDENCE` from P6.0 immediately, then continue to P6.2.
---
## P6.2 — Install the extension pack and verify it landed (SN-PKG-001) *(completes S6.1)*
First check whether the ServiceNow pack content is already installed, so resume does
not ask the maker to reinstall.
**Message:**

First, let me check whether the ServiceNow extension pack is already installed in
your agent.

**End message.**
```
python scripts/flightcheck/cli.py --checkpoint SN-PKG-001 --no-open
```
Read the `SN-PKG-001` row from the results before continuing. It is a real,
standalone checkpoint (emitted by `run_servicenow_pack_checks`) that verifies the
pack **content** landed per product by checking each product's Dataverse
template-config records — so it works even before any flow exists. Its result names
each in-scope product's install state (installed / partial / not installed). Later
steps own the
S6.2–S6.6 rows, so ignore those rows here.
- `PASSED` → the expected pack content is present for every in-scope product (the
  summary lists which products are installed); go to **Record S6.1**.
- `WARNING` (partial install — some template configs missing), `NotConfigured`
  (no pack content), or `FAILED` on a per-product row → install (or reinstall) each
  in-scope pack in Copilot Studio (below), then re-run the checkpoint. Only in-scope
  products matter: a product you are not installing showing `NotConfigured` is fine.

### P6.2-M — Install the pack in Copilot Studio
Guide the maker through installing each in-scope pack in Copilot Studio using the
values for the selected auth type below.
**The ServiceNow and Dataverse connections already exist** (created in P6.1a), so
when the install dialog asks for a connection, have the maker **select the existing
connection** rather than re-entering credentials. The value tables below are the
same values used to create them — use them only as a fallback if the dialog forces
an inline connection.
#### P6.2a — User sign-in install values
Use only when `authType == "entra_user"`. Require `entra.appClientId`; if missing,
route back to the user sign-in playbook.
For each in-scope pack, show this message with `{PACK_NAME}` set to **ServiceNow
IT** or **ServiceNow HR**.
**Message:**

Time to install the ServiceNow integration in Copilot Studio.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/).
2. Open your Employee Self-Service agent.
3. Go to **Settings** → **Customize**.
4. Find **{PACK_NAME}** and select **Install**.
5. When it asks for connection details, it should **automatically pick up the
   ServiceNow and Microsoft Dataverse connections you created in the last step** —
   just select them and continue. You only need to create or change a connection if
   the right one isn't offered.

   If you do need to (re)create the ServiceNow connection, use these values:

   | Field | Value |
   |-------|-------|
   | **Authentication Type** | Microsoft Entra ID User Login |
   | **Resource URI** | `{APP_CLIENT_ID}` |
   | **Instance Name** | `{INSTANCE_NAME}` |

   Sign in with your Microsoft work account when prompted, and use the same maker
   account for the **Microsoft Dataverse** connection if it's requested.

If the sign-in button hangs after authenticating, open
[Power Automate](https://make.powerautomate.com) → **Connections** and check whether
ServiceNow shows as connected. If it does, return to Copilot Studio, close the
install dialog, refresh the page, and select **Install** again so it can pick up the
existing connection.

Tell me when the install finishes, or say **help** if something went wrong.

**End message.**
#### P6.2b — Certificate install values
Use only when `authType == "entra_certificate"`. Require `certificate.tenantId`,
`certificate.appAClientId`, `certificate.appBClientId`, and
`certificate.certPfxPath`; if any are missing, route back to the certificate
playbook. Confirm the PFX file exists. If it does not, route back to regenerate it.
Before showing the install message, open File Explorer with the certificate selected:
```powershell
explorer.exe /select,"{CERT_PFX_PATH}"
```
For HRSD, show:
**Message:**

Time to install the ServiceNow HR integration in Copilot Studio.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/).
2. Open your Employee Self-Service agent.
3. Go to **Settings** → **Customize**.
4. Find **ServiceNow HR** and select **Install**.
5. When it asks for connection details, it should **automatically pick up the
   ServiceNow and Microsoft Dataverse connections you created in the last step** —
   just select them and continue. You only need to create or change a connection if
   the right one isn't offered.

   If you do need to (re)create the ServiceNow connection, use these values:

   | Field | Value |
   |-------|-------|
   | **Authentication Type** | Microsoft Entra ID OAuth using Certificate |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Tenant ID** | `{TENANT_ID}` |
   | **Client ID** | `{APP_B_CLIENT_ID}` |
   | **Resource URI** | `{APP_A_CLIENT_ID}` |
   | **Client Secret** | Upload the `.pfx` certificate file I opened for you |
   | **Certificate password** | Use the password shown when the certificate was generated |

   Use the same maker account for the **Microsoft Dataverse** connection if it's
   requested.

Tell me when the install finishes, or say **help** if something went wrong.

**End message.**
For ITSM, show:
**Message:**

Time to install the ServiceNow IT integration in Copilot Studio.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/).
2. Open your Employee Self-Service agent.
3. Go to **Settings** → **Customize**.
4. Find **ServiceNow IT** and select **Install**.
5. When it asks for connection details, it should **automatically pick up the
   ServiceNow and Microsoft Dataverse connections you created in the last step** —
   just select them and continue. You only need to create or change a connection if
   the right one isn't offered.

   If you do need to (re)create the ServiceNow connection, use these values:

   | Field | Value |
   |-------|-------|
   | **Authentication Type** | Use Oauth2 |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Tenant Type** | `{TENANT_ID}` |
   | **Client Id** | `{APP_B_CLIENT_ID}` |
   | **Resource URI** | `{APP_A_CLIENT_ID}` |
   | **Client certificate secret** | Upload the `.pfx` certificate file I opened for you |
   | **Certificate password** | Use the password shown when the certificate was generated |

   Use the same maker account for the **Microsoft Dataverse** connection if it's
   requested.

Tell me when the install finishes, or say **help** if something went wrong.

**End message.**
If the maker asks for help, mention these checks: confirm they are in the right
agent and **Settings → Customize**; check Power Automate **Connections** if sign-in
hangs; verify Resource URI / Client ID values; use the generated certificate
password or rerun certificate setup if it was lost; grant Entra admin consent if a
consent error appears. Then retry the current pack.
After each product install confirmation, continue to the next product. When all
in-scope products have been attempted, re-run:
```
python scripts/flightcheck/cli.py --checkpoint SN-PKG-001 --no-open
```
Read the `SN-PKG-001` row and loop until it passes for every in-scope product. Keep
S6.1 `in-progress` while the maker is still installing or retrying.
### Record S6.1
When the pack checkpoint passes, merge `.local/connect/servicenow/config.json`:
- Set each in-scope `packs.<product>` to `"installed"`.
- Preserve out-of-scope packs and unknown fields.
Then show:
**Message:**

The ServiceNow extension pack content is installed for the products in scope.

**End message.**
`S6.1` is a **per-product** row: update it **once per in-scope product** (HRSD /
ITSM), passing `PRODUCT` (`"hrsd"` / `"itsm"`) to
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) so each product's
state mirrors under `productStatus.<product>.S6.1` (not the shared `setupStatus`).
The maker performs the install by hand and the checkpoint verifies it, so this is a
programmatic gate: update S6.1 for each in-scope product with `GATE="prog"` and that
product's own pack result — the per-product `SN-PKG-010` (HRSD) / `SN-PKG-020` (ITSM)
row from a `--scope servicenow` run, or the `SN-PKG-001` summary, which names each
product's install state.
Persist immediately before continuing.
---
## P6.3 — Bind the ServiceNow and Dataverse connections (SN-DV-CONN-001) *(completes S6.2)*
Verify the ServiceNow reference first.
**Message:**

Now I'll check that the ServiceNow connection is bound and active.

**End message.**

Binding is a manual step the maker performs in Copilot Studio: each extension pack
ships a **connection reference** that must be wired to an active connection (a single
Dataverse write per reference — no re-authentication when a connection already
exists). The ServiceNow and Dataverse connections were already created in **P6.1a**,
so binding just points each pack reference at those existing connections. Show:
**Message:**

The ServiceNow connection isn't confirmed bound yet. In Copilot Studio, open your
agent's **Connections**, find the ServiceNow connection reference, and point it at
the **ServiceNow connection you created earlier** — select the existing connection,
no need to re-authenticate. Do the same for the **Microsoft Dataverse** connection
reference. Then tell me and I'll re-check.

**End message.**
Wait for the maker to confirm both references are bound before continuing.

There is no standalone `SN-CONN-001` checkpoint in this workspace — do **not** run
`--checkpoint SN-CONN-001` (it returns "unknown checkpoint"); the ServiceNow
connection's health is confirmed later when the maker connects the flow invoker at
P6.5, after the flows are on. Re-confirm the bind on every resume; never skip this
step because state was previously recorded — a pack reinstall can silently unbind the
reference.
### P6.3a — Auth-type evidence
The maker's confirmation that the ServiceNow reference is bound to an active
connection is the S6.2 binding evidence. The Power Platform APIs do not expose a
kit-verifiable auth-type fingerprint, so ask the maker to attest the auth type after
the bind has been confirmed.
For `authType == "entra_user"`, show:
**Message:**

Please confirm the ServiceNow connection uses **Microsoft Entra ID User Login**.
Open the ServiceNow connection in Copilot Studio or Power Automate and check the
authentication type. Is it set that way?

**End message.**
Use the question tool with options **Yes** and **No / not sure**.
For `authType == "entra_certificate"`, show:
**Message:**

Please confirm the ServiceNow connection uses the Microsoft Entra certificate
sign-in method from this setup. Open the ServiceNow connection in Copilot Studio or
Power Automate and check the authentication type. Is it set that way?

**End message.**
Use the question tool with options **Yes** and **No / not sure**. If the maker
chooses **No / not sure**, leave S6.2 `in-progress`; have them re-create or re-bind
the ServiceNow connection with the selected auth type, then re-run this section.
### P6.3b — Verify Dataverse
**Message:**

Now I'll check that the Dataverse connection is bound to an active connection.

**End message.**
```
python scripts/flightcheck/cli.py --checkpoint SN-DV-CONN-001
```
Render the result. This checkpoint matches
**every** Dataverse connection reference by its connector
(`shared_commondataserviceforapps`), so it validates *both* the ServiceNow pack's
own reference (e.g. `new_sharedcommondataserviceforapps_…`) **and** the base
Employee Self-Service agent's reference (`msdyn_Dataverse`, installed back in the
base-agent step). One unbound reference fails the whole step even when the others
are bound — so the failure is often the base agent's `msdyn_Dataverse`, not the
ServiceNow pack. (It is not the Workday pack's `DV-CONN-001`, which keys on a
Workday-specific suffix and reports `NotConfigured` in a ServiceNow-only
environment.)

On `FAILED` / `NotConfigured`, **read the checkpoint's `result` line to see which
reference(s) are unbound** (it lists them by logical name, e.g.
`msdyn_Dataverse`) and name them in the message so the maker binds the right one.
Show:
**Message:**

One or more Microsoft Dataverse connection references still need binding:
**{unbound_reference_names}** (from the checkpoint result). Note this often
includes **`msdyn_Dataverse`** — the base Employee Self-Service agent's own
Dataverse reference — not the ServiceNow pack's, so it's easy to miss even after
you've bound the ServiceNow one. In Copilot Studio, open your agent's
**Connections** (or Power Apps > your solution > **Connection references**), find
each reference listed above, and point it at an active Dataverse connection you
own. Then tell me and I'll re-check.

**End message.**
Re-run until it passes. If the result is `Skipped` because a Dataverse token is
unavailable, re-authenticate and re-run; do not complete the row on a skip.
### P6.3c — Write connection-reference state
When the maker has confirmed the ServiceNow reference is bound, the `SN-DV-CONN-001`
checkpoint passes, and any auth-type attestation is satisfied, merge
`.local/connect/servicenow/config.json` to record this step:
```json
{
  "connections": {
    "servicenow": { "state": "bound", "authType": "{authType}", "verifiedBy": "programmatic-or-attested" },
    "dataverse": { "state": "bound", "verifiedBy": "programmatic" }
  }
}
```
Update S6.2 only after the maker confirms the ServiceNow reference is bound,
`SN-DV-CONN-001` passes, and auth-type evidence is present. Use `GATE="prog"` when the
Dataverse checkpoint is the evidence; if auth type required maker confirmation, record
the auth evidence as attested in the row mirror while keeping the passing
`SN-DV-CONN-001` check.
Persist immediately.
The flow invoker binding (making Copilot Studio show the connection as
**Connected**) happens later in P6.5, after the flows are turned on.
---
## P6.4 — Turn on the ServiceNow flows (SN-FLOW-*) *(completes S6.3)*
Installing an extension pack lands its cloud flows in **Draft**. Copilot Studio will
not invoke a draft flow, so the maker must turn them on. This runs before the flow
invoker binding (P6.5) so the invoker connection lands on the activated flow
definition and does not go stale.
**Message:**

Now I'll check whether the ServiceNow cloud flows are already on.

**End message.**
Verify every ServiceNow cloud flow emitted by the installed packs before asking the
maker to take any manual action.
```
python scripts/flightcheck/cli.py --scope servicenow --no-open
```
Read the `SN-FLOW-*` rows from the results (they are emitted by the ServiceNow scope
run, not standalone `--checkpoint` IDs; ignore rows owned by other steps here). If every emitted flow row passes, expand/update S6.3 as one
checkbox per flow result with `GATE="prog"`, routing each to its pack's product
(`PRODUCT` = the flow's `HRSD`/`ITSM` label → `productStatus.<product>`) and
persisting each generated row immediately. Do not ask the maker to open Power
Platform when every in-scope flow already passes. If any flow row fails, guide the
maker to turn on the failed flows by hand. A flow can only hold activation once its
connection references are bound, so this check must run after P6.3. Show:
**Message:**

One or more ServiceNow cloud flows are turned off. In Power Platform, open the
managed ServiceNow solution, go to **Cloud flows**, and turn on any flow that is
off. Then tell me and I'll re-check.

**End message.**
Re-run the family checkpoint after the maker confirms. Leave each failing generated
row `in-progress` or `blocked` according to the checkpoint result; do not complete
the family until every emitted flow row passes. Do not invent flow names — use the
checkpoint descriptions.
When every flow row passes, merge `.local/connect/servicenow/config.json` to record
this step. Per-product completion is written by the checklist-updater under
`productStatus.<product>.S6.3` (routed by each flow's pack label, above); the flat
`flows` summary below is an aggregate indicator — set `state` to `on` only once
every **in-scope** product's flows are on:
```json
{
  "flows": { "state": "on", "verifiedBy": "programmatic" }
}
```
---
## P6.5 — Connect and share the ServiceNow flow invoker connection *(completes S6.4 connect + S6.5 share)*
Binding the connection *reference* (P6.3) and turning
on the flows (P6.4) is necessary but not sufficient: Copilot Studio still shows the
ServiceNow connection as **Not connected** until the agent's per-flow *invoker
connection* is bound. The maker performs that binding by hand (the **connect** stage,
S6.4) and then shares the connection parameters onto the portal-owned reference (the
**share** stage, S6.5). Do connect before share; because both run after the flows are
on, the binding lands on the final, activated flow definition and will not go stale.

Neither stage has a programmatic checkpoint, so both are **attested by the maker**:
they are separate rows so a resume continues from whichever the maker has not yet
confirmed. **Both S6.4 and S6.5 are per-product rows** (`productStatus.<product>`):
the maker binds and shares each installed pack's flow invoker, so record S6.4 and
S6.5 **once per in-scope product** (`PRODUCT="hrsd"` / `"itsm"`). When a single
maker action covers every installed pack at once, confirm once and mark each in-scope
product's row from that confirmation.
**Message:**

Connect and share the ServiceNow connection so your agent's flows can run for your
users:

1. In Copilot Studio, open your agent's **Settings → Connections**, find the
  ServiceNow connection, and connect it (sign in if prompted) so it shows as
  **Connected**.
2. Open the [Power Apps maker portal](https://make.powerapps.com/).
3. In the left nav, go to **Connections** and open the same **ServiceNow**
  connection.
4. Select **Share**, add the users or security group who will use the agent, and
   give them **Can use** access.
5. Save.

Have you completed both steps?

**End message.**
Use the question tool with these options:
- **Yes, both are complete**
- **Connected, sharing not done**
- **Connection is not connected**

Handle the answer as follows:
- **Yes, both are complete** → record both S6.4 and S6.5 as done.
- **Connected, sharing not done** → record S6.4 as done, leave S6.5
  `in-progress`, and show the same bundled instructions again on resume.
- **Connection is not connected** → leave both rows `in-progress` and show the
  same bundled instructions again after the maker fixes the connection.

Connecting and sharing have no programmatic checkpoints, so only the maker's
explicit bundled response can complete either row.
### P6.5a — Write flow invoker state (S6.4 connect) and share state (S6.5)
Record the two stages separately so a resume stays accurate: S6.4 when the maker
confirms the connection is connected, and S6.5 only when the maker confirms sharing is
done. Derive both confirmations from the single bundled answer above.

**S6.4 (connect).** When the maker confirms the connection shows as **Connected**,
merge `.local/connect/servicenow/config.json` (the reference-level
`servicenow`/`dataverse` state was already written in P6.3c; here we add the flow
binding and overall status):
```json
{
  "connections": {
    "servicenow": { "state": "active", "authType": "{authType}", "flowBinding": "connected", "verifiedBy": "attested" }
  },
  "status": "connected"
}
```
Also merge the legacy summary into `.local/config.json` so older scan/report flows
can discover the ServiceNow connection. Preserve every existing key:
```json
{
  "connections": {
    "ServiceNow": {
      "instanceName": "{INSTANCE_NAME}",
      "instanceUrl": "https://{INSTANCE_NAME}.service-now.com",
      "usage": "{usage}",
      "authType": "{authType}",
      "connectedAt": "{current ISO date}"
    }
  }
}
```
Connecting has no checkpoint, so this is an attested gate: update S6.4 with
`GATE="attest"` and `ACK=true` only when the bundled answer confirms the connection,
passing
`PRODUCT="hrsd"` / `"itsm"` for each in-scope product so the row mirrors under
`productStatus.<product>.S6.4`. The `connections.servicenow` / `status` state above
is connection-level and stays shared in the top-level config. Persist immediately.

**S6.5 (share).** Only when the bundled answer confirms sharing, merge the share
artifact and record the row:
```json
{ "parameterSharing": "shared" }
```
Sharing has no checkpoint, so this is an attested gate: update S6.5 with
`GATE="attest"` and `ACK=true` only when the bundled answer confirms sharing,
passing `PRODUCT` for each in-scope product so the row mirrors under
`productStatus.<product>.S6.5`. If the maker selects **Connected, sharing not done**,
leave S6.5 `in-progress`, keep S6.4 `done`, and show the same bundled question on
resume. Persist immediately.
---
## P6.6 — Set the Portal Base URL (SN-BASEURL-001) *(completes S6.6)*
Derive `{SUGGESTED_PORTAL_BASE_URL}` as `{instanceUrl}/sp`, for example
`https://contoso.service-now.com/sp`. This is only a suggestion: a customer's
ServiceNow portal may use a different path. Do not save or use the suggested URL
until the maker confirms it.

**Message:**

We need your ServiceNow service portal URL. Is this your ServiceNow service portal
URL: **{SUGGESTED_PORTAL_BASE_URL}**?

**End message.**

Use the question tool with options **Yes, that's correct** and **No**.

- On **Yes, that's correct**, set `{PORTAL_BASE_URL}` to
  `{SUGGESTED_PORTAL_BASE_URL}`.
- On **No**, ask for the correct value with the question tool:
  - Header: **Service portal URL**
  - Question: **What is your correct ServiceNow service portal URL?**
  - Allow free-form input and do not offer a default value.
  - Require a complete `https://` URL. If the answer is missing the scheme or is
    not a valid absolute URL, ask again. Do not append `/sp` or any other path.
  - Set `{PORTAL_BASE_URL}` to the URL the maker provides.

Only after `{PORTAL_BASE_URL}` has been confirmed or provided, merge it into
`.local/connect/servicenow/config.json` as `portalBaseUrl`. Use this confirmed URL
in every instruction and value below.
**Message:**

One important setting the packs don't fill in for you: the **ServiceNow Portal
Base URL**. It's what turns case and ticket references into working links for your
employees.

For each ServiceNow pack you installed, do this in Copilot Studio:

1. Go to **...** → **Solutions** → **Managed**.
2. Open the managed solution for the pack:
   - For HR: **ServiceNow HR Solution** → **Objects** → `msdyn_ServiceNowHRSD`
   - For IT: **ServiceNow IT Solution** → **Objects** → `msdyn_ServiceNowITSM`
3. Set this value:

   ```json
   { "ServiceNowPortalBaseURI": "{PORTAL_BASE_URL}" }
   ```

Use the same URL for every ServiceNow pack you installed. Tell me when you've set
it for each pack in scope.

**End message.**
Only mention the HR object when HRSD is in scope and only mention the IT object when
ITSM is in scope. After confirmation, run:
```
python scripts/flightcheck/cli.py --scope servicenow --no-open
```
Read the `SN-BASEURL-001` row from the results. It is emitted by the ServiceNow
scope run and is also a registered checkpoint, so you can verify it directly with
`python scripts/flightcheck/cli.py --checkpoint SN-BASEURL-001 --no-open`.

`S6.6` is a **per-product** row: update it **once per in-scope product** (HRSD /
ITSM), passing `PRODUCT` (`"hrsd"` / `"itsm"`) to
[`../shared/checklist-updater.md`](../shared/checklist-updater.md) so each product's
state mirrors under `productStatus.<product>.S6.6`. The checkpoint verifies every
in-scope product at once. It compares each product's stored `ServiceNowPortalBaseURI`
against the confirmed `portalBaseUrl` you merged into
`.local/connect/servicenow/config.json` (host compared case-insensitively; path,
e.g. `/sp`, compared exactly), so a stale or wrong-but-absolute URL cannot pass. Its
result lists each product it found `set` (matching), `empty`, or mismatched
(reporting expected-vs-actual). Decide **strictly by the checkpoint status** — a
`Failed` gate must stay blocked; attestation may **never** override a value Dataverse
explicitly read:

- `PASSED` → the confirmed URL is set for every in-scope product; update S6.6 for
  each in-scope product with `GATE="prog"` and the checkpoint result. Done.
- `FAILED` (Dataverse read an `empty`, malformed, or mismatched value for at least
  one product) → **do not attest, do not mark those rows done.** Keep every product
  the result reports as `empty` or `mismatched` at S6.6 `in-progress`. Show the maker
  the failing per-product detail (for a mismatch, the expected-vs-actual values so
  they fix the wrong pack), return to the portal-setting instructions above, then
  **re-run the checkpoint and loop until it PASSES**:
  ```
  python scripts/flightcheck/cli.py --checkpoint SN-BASEURL-001 --no-open
  ```
  Only a product the result explicitly lists as `set` (matching the confirmed URL)
  may be recorded `done` (`GATE="prog"`) now; the rest stay blocked until re-run
  passes. **Message:**

  I can see the Portal Base URL isn't right yet for the product(s) above — case and
  ticket links won't resolve until it matches. Please set it to the value shown and
  tell me when it's done so I can re-check.

  **End message.**
  Use the question tool with options **I've set it, re-check** and **I need help**.
  On **re-check**, re-run the checkpoint and repeat this decision. Never accept an
  attestation in place of a passing re-run for a `Failed` value.
- `NotConfigured` (no product config record — the pack isn't installed) → S6.1 is
  not actually complete; return to **P6.2** for that product. Do not attest S6.6.
- `SKIPPED` or `WARNING` (verification genuinely **unavailable** — no Dataverse token,
  or the kit could not read the template configs) → and only then, fall back to
  attestation after the rendered result:
**Message:**

I can't verify the portal setting from the kit right now. Please confirm you set the
ServiceNow Portal Base URL shown above for every ServiceNow pack you installed.

**End message.**
Use the question tool with options **Yes, it's set** and **Not yet**. On **Yes**,
update S6.6 for the pending in-scope product(s) with attested evidence and `ACK=true`.
On **Not yet**, leave those products' S6.6 `in-progress`, return to the portal setting
instructions, and re-check or re-attest after they finish.
Always include this note after S6.6 is recorded:
**Message:**

Remember: the ServiceNow Portal Base URL can reset after an extension-pack update.
If you update either ServiceNow pack later, set this value again so links keep
opening in the portal.

**End message.**
---
## Done
When S6.1 **and** S6.6 are `done` for **every in-scope product** (in
`productStatus.<product>`), the shared S6.0 and S6.2 are `done` (in `setupStatus`),
and every generated S6.3 flow row, S6.4, and S6.5 is `done` for **every in-scope
product** (in `productStatus.<product>` — these carry a `product:` tag, so they are
per-product per [`../shared/checklist-updater.md`](../shared/checklist-updater.md)),
return control to the setup router (`SKILL.md`) to resume at validation and handoff.
Do not run the end-to-end ServiceNow prompt test here; that belongs to the separate
`validate-and-handoff.md` playbook.
**Message:**

Your ServiceNow extension pack is installed and wired — the ServiceNow and
Dataverse connections are bound, the cloud flows are on and connected to your agent,
and the portal link setting is recorded. Next up is validating the setup end to end.

**End message.**
