---
name: connect-workday-da
description: >-
  Connect Workday to an Employee Self-Service Declarative Agent HR deployment.
  Use for package installation, Entra SSO, Workday tenant setup, Power Platform
  connections and flows, authorization, resume, drift repair, and readiness validation.
---

<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Connect (DA) — Orchestrator

Every **Message** block is the exact text to show the user.

## Playbook map

- Package: [`install-extension.md`](install-extension.md)
- Microsoft Entra: [`provision-entra-app.md`](provision-entra-app.md)
- Workday tenant: [`configure-tenant.md`](configure-tenant.md)
- Power Platform and agent: [`configure-power-platform.md`](configure-power-platform.md)
- Readiness: [`verify-connection.md`](verify-connection.md)
- State transitions: [`shared/checklist-updater.md`](shared/checklist-updater.md)
- Permission gates: [`shared/permission-gate.md`](shared/permission-gate.md)
- Persisted state: [`shared/config-schema.md`](shared/config-schema.md)
- Executable definition: [`workday-da.definition.json`](workday-da.definition.json) Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading.

These checked-in playbooks and the executable definition are the controlled
sources for this flow. Do not browse for, merge in, or improvise setup steps
from unrelated web pages, LMC articles, prior chat transcripts, or another
Workday architecture. If a required detail is absent or conflicts with these
files, stop at that step and report the missing decision instead of inventing
instructions.

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

## V1 identity boundary

This release supports only the Workday connection option named **Microsoft
Entra ID Integrated**. Do not present an identity-provider decision tree and do
not configure direct Workday federation through Okta, Ping, or another
identity provider.

If the user says their Workday tenant is directly federated to a provider other
than Microsoft Entra ID, show:

**Message:**

This version of Workday setup supports **Microsoft Entra ID Integrated**
authentication only. Direct Workday federation through Okta, Ping, or another
identity provider is outside the V1 scope, so I won't change this environment.
Contact your Workday and identity administrators before continuing.

**End message.**

Stop without creating or updating Workday state.

When this file is invoked directly instead of through `/connect workday`, show
the same customer-facing routing confirmation defined by the Workday branch in
`src/skills/connect/step1.md` before the readiness briefing. Resolve and enforce
the architecture, authentication mode, and canonical state path internally,
but do not expose Git revisions or local file-system paths in the customer
conversation.

Use the same five-phase lifecycle and the same completion gates for
Development, Sandbox, and Production Power Platform environments. Environment
type never skips, reorders, or relaxes a Workday step. Only discovered
environment identifiers, tenant-specific values, and the ring-specific
Power Platform host may differ.

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

Whenever a command starts device-code authentication, read the command output
and repeat the sign-in URL and one-time code as plain, copyable chat text.
Never require the user to copy them from an inline terminal. Do not repeat
access tokens, refresh tokens, passwords, or cookies.

---

## Start

1. **Initialize the durable state.** The canonical internal checklist is
   `.local/connect/workday-da/tasks.md`, next to the provider config it
   represents. Initialize and validate both through the deterministic helper:

   ```powershell
   python scripts/workday_da_state.py --root . initialize
   ```

   When the legacy `.local/setup/workday-da/tasks.md` exists, the helper will
   move that exact file to the canonical path while preserving its contents and
   timestamps. It refuses conflicting dual copies, migrates version fields, and
   creates canonical config/checklist state when absent. Do not hand-edit
   status markers or provider state. After a successful legacy move, the old
   path is no longer used.

2. **Revalidate saved completion.** Before selecting a resume row, create the
   deterministic live-revalidation plan:

   ```powershell
   python scripts/workday_da_state.py --root . revalidation-plan
   ```

   Complete every returned action before claiming readiness:
   - `checkpoint` — rerun the listed checkpoint and persist its current result
     through the checklist updater.
   - `external-verification` — dispatch to the owning playbook's existing
     read-only/post-write verification and persist that current result.
   - `manual-evidence-stale` — the helper already regressed that row and its
     dependents because the selected agent, tenant, endpoint, app, or
     environment scope changed. Resume normally and request fresh evidence
     when that row is reached.

   Do not show internal IDs from the plan. While programmatic revalidation is
   outstanding, provider status remains `in-progress` even when saved rows are
   still checked.

3. **Show the concise customer journey.** Run:

   ```powershell
   python scripts/workday_da_state.py --root . customer-status
   ```

   Map milestone states to markers: ✅ = `done`, 🔄 = `in-progress`, ⛔ =
   `blocked`, and ⬜ = `pending`. Show only the seven customer milestones, not
   the 21 internal rows, their IDs, checkpoint IDs, implementation files, or
   completed-row evidence.

   On a completely fresh setup, precede the status with one sentence:

   **Message:**

   Connecting Workday requires an Environment Maker, a Microsoft Entra
   administrator, and a Workday administrator. I will save progress and tell
   you when each person is needed.

   **End message.**

   Do not repeat that sentence after any internal row has moved out of
   `pending`.

   **Message:**

   Workday connection progress:

   | Milestone | Status |
   | --- | --- |
   | Preflight | {marker} |
   | Microsoft Entra | {marker} |
   | Workday administrator | {marker} |
   | Connections | {marker} |
   | Runtime configuration | {marker} |
   | Network readiness | {marker} |
   | Employee validation | {marker} |

   Next: **{title of `nextMilestoneId`}**.

   **End message.**

   If `nextMilestoneId` is null, omit the **Next** line. Do not render the
   longer technical checklist unless the user explicitly asks for diagnostic
   details.

4. **Resume internally.** Read `setupStatus` in
   `.local/connect/workday-da/config.json` (the durable source of truth; the
   tasks file is only an internal compatibility view). Walk the technical rows
   in Step order (DA1.1, DA2.1 … DA5.1), pick the first whose state is not
   `done`, and dispatch by that Step in **Dispatch** below. A step's playbook may
   re-run its own idempotent foundation steps to rehydrate in-memory state.
   Follow that playbook's build order without showing those internal rows to the
   customer.

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

**Failure and retry policy.** Classify failures using the categories in
`workday-da.definition.json`. Only `transient` failures from read-only or
explicitly idempotent operations may retry, using the definition's bounded
attempt count and backoff. Authentication, permission, validation,
unsupported-state, conflict, manual-action, and verification failures stop
with remediation. An `ambiguous-mutation` always stops for reconciliation;
never repeat a mutation when the prior outcome is unknown. Persist the safe
category, retryability, and attempt count in row evidence without raw service
responses or secrets.

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
signing option, and confirms single-tenant federation. It obtains one scoped
approval for the remaining Entra changes, then verifies each
outcome (`WD-CONN-102`, `WD-ENTRA-SCOPE-001`, `WD-ENTRA-CONSENT-001`,
`WD-ASSIGN-001`, `WD-ENTRA-NAMEID-001`, `WD-ENTRA-SIGNOPT-001`, `WD-CONN-010`)
and updates rows **DA2.1**–**DA2.7** through the shared checklist-updater
(DA2.1/DA2.6 manual and DA2.7 attest rows need acknowledgement). On resume it
re-runs the role gate, scoped approval, and DA2.1 app lookup before the first
incomplete row, since DA2.2–DA2.4 depend on the in-memory app object id that
DA2.1 populates.

When it returns, go back to **Start** to resume at the next unverified row.

### DA3.1 through DA3.4 — Configure the Workday tenant (DA-3)

Read `src/skills/setup/workday-da/configure-tenant.md` and follow it. That
playbook confirms a Workday Administrator is available, protects the existing
single-tenant SAML federation, and presents one administrator work packet for
the X.509 signing certificate, Tenant Setup – Security, API client, connection
fields, and employee SAML policy. It captures one structured response and
updates rows **DA3.1**–**DA3.4** through the shared checklist-updater. Manual
outcomes remain individually evidenced internally, but manual-only
FlightChecks are not presented as customer verification. A different or
unknown active federation pauses the standard flow for the organization's
formal identity change process.

When it returns, go back to **Start** to resume at the next unverified row.

### DA4.1 through DA4.8 — Configure Power Platform and agent integration (DA-4)

Read `src/skills/setup/workday-da/configure-power-platform.md` and follow it.
That playbook guides creation of the Workday and Dataverse connections, binds
the installed solution references, activates the runtime flows, connects the
flows to the agent with parameter sharing, applies checked-in script
authorization, configures DA V2 employee context and topic selection, and
shows a conditional network advisory. It obtains one scoped approval for the
remaining supported runtime helpers and updates rows **DA4.1**–**DA4.8**
through the shared checklist-updater. Manual rows require explicit evidence;
DA4.3, supported DA4.4 activation, and DA4.6 are programmatic, while DA4.8 is
non-blocking.

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
