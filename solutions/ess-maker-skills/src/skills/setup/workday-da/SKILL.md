<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Connect (DA) — Orchestrator

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

This router sequences the four Workday connect steps for the **Declarative Agent
(DA)** flavor of Employee Self-Service, using the master checklist as a
**resume-aware spine**: it renders the working checklist on first run, resumes at
the first unverified step, and dispatches to the owning step's playbook. It
**never** advances past a `MANUAL` / attestation row on a flightcheck pass alone —
those require explicit user acknowledgement (enforced by
[`shared/checklist-updater.md`](./shared/checklist-updater.md)).

This skill assumes the DA Employee Self-Service base agent itself is already
installed — that's owned by `/setup`, not by this skill. DA-1 checks for it and
sends you to `/setup` first if it isn't there yet.

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
  `python scripts/flightcheck/cli.py --scope workdayda` in the terminal.

Non-secret connection identifiers (tenant, SOAP/REST/token URLs, OAuth client
ID, App ID URI) are safe to capture in chat — see
[`shared/connection-fields.md`](./shared/connection-fields.md). The Workday
**username** is likewise not masked (`"password": false`); only the password is.

---

## Start

1. **Working copy.** If `.local/setup/workday-da/tasks.md` does not exist, render
   it by copying the template `src/skills/setup/workday-da/tasks.md`. Do not
   hand-edit its status markers — the shared checklist-updater writes them.

2. **Resume point.** Read `setupStatus` in `.local/connect/workday-da/config.json`
   (the durable source of truth; the tasks file is only the view). If the file or
   the `setupStatus` key is missing, treat every row as `pending`. A row counts as
   complete only when `setupStatus["{Step}"].state` is `"done"`.

3. **Show the checklist, then find where to resume.** Determine each item's state
   from `setupStatus`: ✅ = `done`, 🔄 = `in-progress`, ⛔ = `blocked`, ⬜ =
   `pending` or unset. Show the checklist **grouped exactly as in the template** —
   the group headings and item titles below are verbatim from
   `src/skills/setup/workday-da/tasks.md`; render every group and every item,
   replacing each `{m}` with that item's marker. **Never show Step IDs or
   checkpoint IDs.**

   **Message:**

   Here's the checklist for connecting Workday to your agent:

   **1. Workday extension package**
   - {m} Install the Workday extension package

   **2. Workday single sign-on (Entra)**
   - {m} Create the Workday single sign-on app
   - {m} Expose the Workday API permission
   - {m} Grant admin consent
   - {m} Assign users to the Workday app
   - {m} Map the sign-in identifier
   - {m} Set the SAML signing option
   - {m} Confirm a single sign-in tenant

   **3. Workday tenant configuration**
   - {m} Register the Workday API client
   - {m} Capture your Workday connection details
   - {m} Activate the Workday authentication policy
   - {m} Match the signing certificate

   **4. Review your Workday configuration**
   - {m} Review your Workday configuration

   Picking up at: {title of the first item whose state is not `done`}.

   **End message.**

   Then walk the items in Step order (DA1.1, DA2.1 … DA4.1 — these IDs are
   internal only), pick the first whose state is not `done`, and dispatch by that
   Step in **Dispatch** below. A step's playbook may re-run its own idempotent
   foundation steps (role gate, resource lookup) ahead of the resume item to
   rehydrate in-memory state — follow the playbook's stated build order rather
   than jumping straight into it.

4. If **every** item is `done`, show the **All done** message and stop.

---

## Dispatch

**Persist each row the moment its checkpoint passes.** Every step calls
[`shared/checklist-updater.md`](./shared/checklist-updater.md) per row, inline —
updating both the working checklist and the durable `setupStatus` mirror
immediately — and **must not** batch those writes to the end of its run. This
keeps progress crash-safe: if a step errors midway, the rows already verified
stay complete and this router resumes at the first row that isn't.

### DA1.1 — Install the Workday extension package (DA-1)

Read `src/skills/setup/workday-da/install-extension.md` and follow it. That
playbook checks the DA base agent is installed and sends the user to `/setup`
if it isn't, attempts an automated install of the Workday extension package,
falls back to a guided manual AppSource install if automation isn't available
in this tenant, verifies the package landed (`WD-DA-PKG-001`), and updates row
**DA1.1** through the shared checklist-updater.

When it returns, go back to **Start** to resume at the next unverified row.

### DA2.1 through DA2.7 — Provision the Workday Entra app (DA-2)

Read `src/skills/setup/workday-da/provision-entra-app.md` and follow it. That
playbook role-gates (App / Cloud Application Administrator), instantiates and
configures the Workday SSO gallery app, exposes the API scope and
pre-authorizes the Workday connector, grants and consents the Graph
permissions, assigns the enterprise app, sets the NameID mapping and SAML
signing option, and confirms single-tenant federation. It verifies each
outcome (`WD-CONN-102`, `WD-ENTRA-SCOPE-001`, `WD-ENTRA-CONSENT-001`,
`WD-ASSIGN-001`, `WD-ENTRA-NAMEID-001`, `WD-ENTRA-SIGNOPT-001`, `WD-CONN-010`)
and updates rows **DA2.1**–**DA2.7** through the shared checklist-updater
(DA2.1/DA2.6 manual and DA2.7 attest rows need acknowledgement). On resume it
always re-runs its role gate and DA2.1 (create the SSO app) first — both
idempotent — before the first incomplete row, since DA2.2–DA2.4 depend on the
in-memory app object id that only DA2.1 populates.

When it returns, go back to **Start** to resume at the next unverified row.

### DA3.1 through DA3.4 — Configure the Workday tenant (DA-3)

Read `src/skills/setup/workday-da/configure-tenant.md` and follow it. That
playbook role-gates (Workday Administrator, by attestation), records the
current single-tenant SAML federation before any change, uploads and verifies
the X.509 signing certificate (`WD-CONN-102`), edits Tenant Setup – Security,
registers the Workday API client and captures the connection fields
(`WD-API-CLIENT-001`), and scopes and activates the authentication policy
(`WD-TENANT-001`) — updating rows **DA3.1**–**DA3.4** through the shared
checklist-updater. All four are manual Workday-admin tasks (attest / manual
gates) that need acknowledgement; `WD-API-CLIENT-001` and `WD-TENANT-001`
report `MANUAL`. On resume it always re-runs its role gate and the
single-tenant SAML pre-check first — both idempotent — before the first
incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

### DA4.1 — Review your Workday configuration (DA-4)

Read `src/skills/setup/workday-da/verify-connection.md` and follow it. That
playbook re-runs `WD-DA-PKG-001` to reconfirm the extension package, summarizes
the Entra and tenant configuration recorded in
`.local/connect/workday-da/config.json`, and clearly states what this skill
does — and does not yet — verify about the live connection (see the "Deferred
to a follow-up" note in `tasks.md`), pointing to a full FlightCheck run for
anything beyond that. It updates row **DA4.1** through the shared
checklist-updater (`prog` gate — completes only when the live package recheck
passes).

When it returns, go back to **Start** — every row should now be `done`.

## All done

**Message:**

Your Workday installation and configuration checklist is complete. The final
review explains the remaining live connection and agent-path checks. Type
`/menu` to see what you can do next.

**End message.**
