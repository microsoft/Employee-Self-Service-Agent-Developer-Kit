<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Connect (DA) — Orchestrator

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

This router sequences the five Workday connect steps for the **ESS HR agent**,
using the master checklist as a
**resume-aware spine**: it renders the working checklist on first run, resumes at
the first unverified step, and dispatches to the owning step's playbook. It
**never** advances past a `MANUAL` / attestation row on a flightcheck pass alone —
those require explicit user acknowledgement (enforced by
[`shared/checklist-updater.md`](./shared/checklist-updater.md)).

This skill assumes the Employee Self-Service base agent itself is already
installed — that's owned by `/setup`, not by this skill. DA-1 checks for it and
sends you to `/setup` first if it isn't there yet.

This release does not support Workday for the ESS DA IT Agent. Before creating
the working checklist or reading provider state, resolve `activeAgent` from
`.local/config.json` and require an ESS DA HR agent entry with a stable slug,
`botId`, and HR schema name. Then read the canonical
`.local/setup/config.json` `agents` record keyed by that `botId` and require
canonical workspace evidence plus `steps.SETUP-07.state: "done"`. Do not
require `connect_ready: true`; configuring Workday may resolve the remaining
runtime connection blocker. Do not use the retired `selected_products` field
or choose the first agent in a multi-agent workspace. If the target is IT,
Hub, CEA, ambiguous, incomplete, or unresolved, show:

**Message:**

This Workday setup supports the ESS HR agent only. Select the ESS HR agent,
or contact your administrator if it isn't available.

**End message.**

Stop immediately without creating or updating any Workday state. This guard is
required even though the `/connect workday` router performs the same check,
because this file must remain safe if invoked directly.

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

1. **Show the readiness briefing.** After the DA HR agent guard and routing
   FlightChecks have passed, show this before creating or resuming the
   checklist. Show it on every invocation so a resumed setup makes its
   remaining administrator dependencies clear.

   **Message:**

   Here's the plan for connecting Workday to your ESS HR agent. Some steps
   require administrators outside the maker role, so involve them now if you
   don't hold these permissions:

   | Phase | What we'll do | Who is needed |
   | --- | --- | --- |
   | Workday extension | Install or verify the Workday package for the ESS HR agent | Power Platform Environment Maker |
   | Microsoft Entra | Configure Workday SSO, API permission, consent, user assignment, NameID, and SAML signing | Entra Application Administrator or Cloud Application Administrator; a consent-capable administrator if required |
   | Workday tenant | Configure tenant security, the API client, functional areas, endpoints, authentication policy, and certificate trust | Workday Administrator |
   | Power Platform connections | Configure Workday OAuthUser and Dataverse connections, shared parameters, bindings, and cloud flows | Power Platform Environment Maker |
   | Agent authorization | Preview and run the Dataverse bot-to-flow authorization script | Power Platform Administrator with Dataverse System Administrator access |
   | Network readiness | Allow the required Workday REST and SOAP hosts | InfoSec or network administrator |
   | Topics and validation | Select Workday topics and validate a real signed-in employee scenario | Environment Maker, Workday test employee, and Workday Administrator if remediation is needed |

   I'll automate checks and supported changes where reliable APIs are
   available. For Workday or portal-only settings, I'll give the responsible
   administrator the exact steps and wait for confirmation. I won't mark the
   environment ready until the signed-in Workday scenario succeeds.

   **End message.**

2. **Working copy.** The canonical checklist is
   `.local/connect/workday-da/tasks.md`, next to the provider config it
   represents. If it does not exist:
   - When the legacy `.local/setup/workday-da/tasks.md` exists, create
     `.local/connect/workday-da/` if needed and move that exact file to the
     canonical path. Preserve its contents and timestamps; never replace it
     with a fresh template or overwrite an existing canonical checklist.
   - Otherwise render it by copying the template
     `src/skills/setup/workday-da/tasks.md`.

   Do not hand-edit its status markers — the shared checklist-updater writes
   them. After a successful legacy move, the old path is no longer used.

3. **Resume point.** Read `setupStatus` in `.local/connect/workday-da/config.json`
   (the durable source of truth; the tasks file is only the view). If the file or
   the `setupStatus` key is missing, treat every row as `pending`. A row counts as
   complete only when `setupStatus["{Step}"].state` is `"done"`.

4. **Show the checklist, then find where to resume.** Determine each item's state
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

   **2. Connect Microsoft Entra sign-in to Workday**
   - {m} Set up Workday sign-in
   - {m} Allow Power Platform to call Workday
   - {m} Approve the sign-in permissions
   - {m} Choose who can use Workday
   - {m} Match the signed-in employee
   - {m} Sign the Workday sign-in response
   - {m} Confirm the correct Microsoft Entra tenant

   **3. Workday tenant configuration**
   - {m} Register the Workday API client
   - {m} Capture your Workday connection details
   - {m} Verify employee SAML sign-in policy
   - {m} Match the signing certificate

   **4. Power Platform and agent integration**
   - {m} Create the Workday connection
   - {m} Create the Microsoft Dataverse connection
   - {m} Bind the extension connections
   - {m} Turn on the Workday cloud flows
   - {m} Connect Workday to the agent
   - {m} Authorize the agent to use the Workday flows
   - {m} Configure employee context and topics
   - {m} Allow Workday through the firewall

   **5. Validate Workday readiness**
   - {m} Validate a signed-in Workday scenario

   Picking up at: {title of the first item whose state is not `done`}.

   **End message.**

   Then walk the items in Step order (DA1.1, DA2.1 … DA5.1 — these IDs are
   internal only), pick the first whose state is not `done`, and dispatch by that
   Step in **Dispatch** below. A step's playbook may re-run its own idempotent
   foundation steps (role gate, resource lookup) ahead of the resume item to
   rehydrate in-memory state — follow the playbook's stated build order rather
   than jumping straight into it.

5. If **every** item is `done`, also require provider `status` to be `"ready"`
   before showing **All done**. If every row is done but status is not ready,
   treat DA5.1 as `in-progress` and dispatch to DA-5 to reconcile readiness;
   never claim success from checklist state alone.

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
(`WD-API-CLIENT-001`), and verifies the signed-in employee SAML policy
(`WD-TENANT-001`) — updating rows **DA3.1**–**DA3.4** through the shared
checklist-updater. All four are manual Workday-admin tasks (attest / manual
gates) that need acknowledgement; `WD-API-CLIENT-001` and `WD-TENANT-001`
report `MANUAL`. On resume it always re-runs its role gate and the
single-tenant SAML pre-check first — both idempotent — before the first
incomplete row.

When it returns, go back to **Start** to resume at the next unverified row.

### DA4.1 through DA4.8 — Configure Power Platform and agent integration (DA-4)

Read `src/skills/setup/workday-da/configure-power-platform.md` and follow it.
That playbook guides creation of the Workday and Dataverse connections, binds
the installed solution references, activates the runtime flows, connects the
flows to the agent with parameter sharing, applies checked-in script
authorization, configures DA V2 employee context and topic selection, and
records firewall allowlisting. It updates rows **DA4.1**–**DA4.8** through the
shared checklist-updater. Manual and attestation rows require explicit
evidence; DA4.3, supported DA4.4 activation, and DA4.6 are programmatic.

When it returns, go back to **Start** to resume at DA5.1.

### DA5.1 — Validate Workday readiness (DA-5)

Read `src/skills/setup/workday-da/verify-connection.md` and follow it. That
playbook re-runs `WD-DA-PKG-001`, summarizes all setup areas, and requires a
successful signed-in employee Workday scenario. It updates **DA5.1** only after
runtime evidence is captured and sets provider `status` to `"ready"`.

When it returns, go back to **Start** — every row should now be `done`.

## All done

**Message:**

Your ESS HR agent is connected to Workday and the signed-in employee path
has been validated in this environment. The Workday connection is ready; you
do not need to run `/setup` again.

**End message.**
