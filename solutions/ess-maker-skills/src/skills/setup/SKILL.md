<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Setup Orchestrator

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

This router sequences the six Workday setup skills using the master checklist as a
**resume-aware spine**: it renders the working checklist on first run, resumes at
the first unverified step, and dispatches to the owning skill's playbook. It
**never** advances past a `MANUAL` / attestation row on a flightcheck pass alone —
those require explicit user acknowledgement (enforced by
[`shared/checklist-updater.md`](./shared/checklist-updater.md)).

---

## Handling Workday credentials — never put secrets in chat

The Workday **password is a secret**. **Never** ask for it with a chat question
(`vscode_askQuestions`, or a plain "paste your Workday password" message) — the
chat question tool has no masked-input option, so anything typed is recorded
verbatim in the transcript.

When a Workday secret is genuinely required (only the FlightCheck Workday SOAP
workflow tests need one), it is collected **exclusively** through a masked
input that keeps the value out of chat history:

- the `.vscode/mcp.json` `workdayPass` input — a `promptString` with
  `"password": true`, which VS Code masks and substitutes directly into the
  check environment, or
- the FlightCheck CLI's own `getpass` prompt when you run
  `python scripts/flightcheck/cli.py --scope workday` in the terminal.

Non-secret connection identifiers (tenant, SOAP/REST/token URLs, OAuth client
ID, App ID URI) are safe to capture in chat — see
[`shared/connection-fields.md`](./shared/connection-fields.md). The Workday
**username** is likewise not masked (`"password": false`); only the password is.

---

## Start

1. **Working copy.** If `.local/setup/workday/tasks.md` does not exist, render it by
   copying the template `src/skills/setup/workday/tasks.md`. Do not hand-edit its
   status markers — the shared checklist-updater writes them.

2. **Resume point.** Read `setupStatus` in `.local/connect/workday/config.json` (the
   durable source of truth; the tasks file is only the view). If the file or the
   `setupStatus` key is missing, treat every row as `pending`. A row counts as
   complete only when `setupStatus["{Step}"].state` is `"done"`.

3. **Show the checklist, then find where to resume.** Determine each item's state
   from `setupStatus`: ✅ = `done`, 🔄 = `in-progress`, ⛔ = `blocked`, ⬜ =
   `pending` or unset. Show the checklist **grouped exactly as in the template** —
   the group headings and item titles below are verbatim from
   `src/skills/setup/workday/tasks.md`; render every group and every item, replacing
   each `{m}` with that item's marker. **Never show Step IDs or checkpoint IDs.**

   **Message:**

   Here's where your Workday setup stands:

   **1. Power Platform environment**
   - {m} Set up your Power Platform environment
   - {m} Confirm Copilot Studio capacity

   **2. Employee Self-Service base agent**
   - {m} Install the Employee Self-Service agent

   **3. Workday single sign-on (Entra)**
   - {m} Create the Workday single sign-on app
   - {m} Expose the Workday API permission
   - {m} Grant admin consent
   - {m} Assign users to the Workday app
   - {m} Map the sign-in identifier
   - {m} Set the SAML signing option
   - {m} Confirm a single sign-in tenant

   **4. Workday tenant configuration**
   - {m} Register the Workday API client
   - {m} Capture your Workday connection details
   - {m} Activate the Workday authentication policy
   - {m} Match the signing certificate

   **5. Workday extension pack**
   - {m} Install the Workday extension pack
   - {m} Connect your Workday account
   - {m} Use Entra ID Integrated sign-in
   - {m} Connect Dataverse
   - {m} Set the Workday REST address
   - {m} Turn on the Workday cloud flows
   - {m} Wire up the employee-context lookup
   - {m} Allow Workday through your firewall

   **6. Your first custom Workday topic**
   - {m} Give your new topic its trigger phrases
   - {m} Wire your new topic to Workday

   Picking up at: {title of the first item whose state is not `done`}.

   **End message.**

   Then walk the items in Step order (S1.1, S1.2, S2.1, S3.1 … S6.2 — these IDs are
   internal only), pick the first whose state is not `done`, and dispatch by that
   Step in **Dispatch** below. A skill's playbook may re-run its own idempotent
   foundation steps (role gate, resource creation) ahead of the resume item to
   rehydrate in-memory state — follow the playbook's stated build order rather than
   jumping straight into it.

4. If **every** item is `done`, show the **All done** message and stop.

---

## Dispatch

**Persist each row the moment its checkpoint passes.** Every skill calls
[`shared/checklist-updater.md`](./shared/checklist-updater.md) per row, inline —
updating both the working checklist and the durable `setupStatus` mirror
immediately — and **must not** batch those writes to the end of its run. This keeps
progress crash-safe: if a skill errors midway, the rows already verified stay
complete and this router resumes at the first row that isn't.

### S1.1 or S1.2 — Provision Power Platform environment (skill-1)

Read `src/skills/setup/workday/provision-power-platform-environment.md` and follow
it. That playbook role-gates (Power Platform Administrator), verifies or creates the
environment + Dataverse (`ENV-001`, `ENV-002`), verifies Copilot Studio message
capacity (`ENV-CAPACITY-001`), and updates rows **S1.1** and **S1.2** through the
shared checklist-updater.

When it returns, go back to **Start** to resume at the next unverified row.

### S2.1 — Install the ESS base agent (skill-2)

Read `src/skills/setup/workday/install-ess.md` and follow it. That playbook
role-gates (Environment Maker), guides the manual AppSource install of the base
Employee Self Service agent, verifies the solution landed (`ESS-SOLN-001`), and
updates row **S2.1** through the shared checklist-updater (prog gate —
auto-completes on a passing `ESS-SOLN-001`).

When it returns, go back to **Start** to resume at the next unverified row.

### S3.1 through S3.7 — Provision the Workday Entra app (skill-3)

Read `src/skills/setup/workday/provision-workday-entra-app.md` and follow it. That
playbook role-gates (App / Cloud Application Administrator), instantiates and
configures the Workday SSO gallery app, exposes the API scope and pre-authorizes
the Workday connector, grants and consents the Graph permissions, assigns the
enterprise app, sets the NameID mapping and SAML signing option, and confirms
single-tenant federation. It verifies each outcome (`WD-CONN-102`,
`WD-ENTRA-SCOPE-001`, `WD-ENTRA-CONSENT-001`, `WD-ASSIGN-001`,
`WD-ENTRA-NAMEID-001`, `WD-ENTRA-SIGNOPT-001`, `WD-CONN-010`) and updates rows
**S3.1**–**S3.7** through the shared checklist-updater (S3.1/S3.6 manual and S3.7
attest rows need acknowledgement). On resume it always re-runs **S3.0** (role gate)
and **S3.1** (create the SSO app) first — both idempotent — before the first
incomplete row, since S3.2–S3.4 depend on the in-memory app object id that only
S3.1 populates.

When it returns, go back to **Start** to resume at the next unverified row.

### S4.1 through S4.4 — Configure the Workday tenant (skill-4)

Read `src/skills/setup/workday/configure-workday-tenant.md` and follow it. That
playbook role-gates (Workday Administrator, by attestation), records the current
single-tenant SAML federation before any change, uploads and verifies the X.509
signing certificate (`WD-CONN-102`), edits Tenant Setup – Security, registers the
Workday API client and captures the connection fields (`WD-API-CLIENT-001`), and
scopes and activates the authentication policy (`WD-TENANT-001`) — updating rows
**S4.1**–**S4.4** through the shared checklist-updater. All four are manual
Workday-admin tasks (attest / manual gates) that need acknowledgement;
`WD-API-CLIENT-001` and `WD-TENANT-001` report `MANUAL`. On resume it always
re-runs P4.0 (role gate) and P4.0b (single-tenant SAML pre-gate) first — both
idempotent — before the first incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

### S5.1 through S5.8 — Install the Workday extension pack (skill-5)

Read `src/skills/setup/workday/install-workday-extension-pack.md` and follow it.
That playbook role-gates (Environment Maker, programmatically), verifies the
extension pack installed (`WD-PKG-001`), confirms the Workday connection reference
is bound (`WD-CONN-012`) and uses Microsoft Entra ID Integrated authentication
(`WD-CONN-AUTH-001`), verifies the Dataverse connection (`DV-CONN-001`) and the
trimmed REST base URL (`WD-REST-001`), confirms the cloud flows are on
(`WD-FLOW-*`), wires the user-context redirect topic (`WD-REST-002`, with a
rollback checkpoint), and records the firewall allowlisting (`WD-NET-001`) —
updating rows **S5.1**–**S5.8** through the shared checklist-updater. Most rows are
programmatic gates that complete on a checkpoint pass; S5.1 (manual), S5.3 and S5.8
(`WD-CONN-AUTH-001` / `WD-NET-001` report `MANUAL`, attest) need acknowledgement.
On resume it always re-runs P5.0 (role gate) and P5.1 (`WD-PKG-001`, which hydrates
the cached connection references the later checks depend on) first — both
idempotent/read-only — before the first incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

### S6.1 through S6.2 — Create a new Workday topic (skill-6)

Read `src/skills/setup/workday/create-new-topic.md` and follow it. That playbook
role-gates (Environment Maker, programmatically), then delegates the topic and
template-config authoring to the general create-topic skill (`topics/create`,
Template Config + Shared Flow pattern), wires the tenant-specific reference IDs
(looping back to skill 4's Register-API-Client step if the new scenario needs an
API scope the tenant doesn't grant yet), verifies each new topic is a well-formed
triggerable definition (`TOPIC-TRIGGER-*`) and that its integration wiring
resolves with no unresolved tenant reference-ID placeholders
(`TOPIC-INTEGRATION-*`), and auto-generates a matching evaluation set — updating
rows **S6.1**–**S6.2** through the shared checklist-updater. Both checkpoints are
`*` families that expand to one row **per new/custom topic**. S6.1 is a
programmatic gate that completes on a checkpoint pass; S6.2 is `prog (+ SME for
IDs)` — the checkpoint proves the placeholders were resolved, but the row also
needs a Workday SME's attestation that the wired reference-ID values are correct.
On resume it always re-runs P6.0 (role gate) first — read-only — before the first
incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

## All done

**Message:**

Your Workday setup checklist is complete. Type `/menu` to see what you can do next.

**End message.**
