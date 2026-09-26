<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Connect — Checklist (template)

The single, trackable checklist spanning the five Workday connect steps for the
**ESS HR agent**. This file is the
human-readable template for the versioned machine contract in
[`workday-da.definition.json`](workday-da.definition.json). Contract tests keep
the visible rows and hidden metadata synchronized. On first run the skill
renders this template to the working copy
`.local/connect/workday-da/tasks.md` and then updates **only its own items**
through the shared
[`shared/checklist-updater.md`](shared/checklist-updater.md). The durable
mirror of each item's status is `setupStatus` in
`.local/connect/workday-da/config.json` (see
[`shared/config-schema.md`](shared/config-schema.md)).

> Do not hand-edit the working copy's checkboxes — let the checklist-updater
> write them so the **MANUAL / attestation rule** is enforced in one place.

This checklist assumes your Employee Self-Service HR agent is already
installed (via `/setup`). If it isn't, DA-1 below detects that and points you
there first.

## How to read this checklist

Each item is a plain checkbox with a short description of what it achieves —
that is what the user sees:

- `- [ ]` — not done yet.
- `- [x]` — done.

The technical details the tooling needs (the stable **Step ID**, the
flightcheck **checkpoint(s)** that verify the item, and the completion
**gate**) live in the HTML comment directly under each item. Those comments are
invisible in the rendered checklist; only the checklist-updater reads them.
**Never surface a Step ID or checkpoint ID to the user** — show the checkbox
and its description only.

**Gate** — how an item reaches done:

| Gate | Meaning |
|------|---------|
| `prog` | A programmatic flightcheck pass completes the item. |
| `manual` | Explicit user action + re-verify; a flightcheck pass alone never completes it. |
| `attest` | Attestation + captured evidence (no queryable directory); never auto-completed. |
| `advisory` | Informational; completes once its output has been shown, regardless of findings. |

The hidden `status:` field carries the full four-state value
(`pending` \| `in-progress` \| `done` \| `blocked`) that a single checkbox can't
express; all items start `pending`.

## Checklist

### 1. Workday extension package

- [ ] **Install the Workday extension package** — Add the Workday extension package to your ESS HR agent so it can talk to Workday. If the HR base agent isn't installed yet, this step sends you to `/setup` first.
  <!-- id: DA1.1 | role: Environment Maker | skill: da-1 | automatable: Attempt | checkpoints: WD-DA-PKG-001 | gate: prog, else manual | status: pending -->

### 2. Connect Microsoft Entra sign-in to Workday

- [ ] **Set up Workday sign-in** — Create the Microsoft Entra application Workday uses to recognize signed-in employees.
  <!-- id: DA2.1 | role: App/Cloud App Admin | skill: da-2 | automatable: Yes | checkpoints: WD-CONN-102 | gate: manual | status: pending -->
- [ ] **Allow Power Platform to call Workday** — Add the permission used by the Workday connector and the Microsoft Graph permissions needed for sign-in.
  <!-- id: DA2.2 | role: App/Cloud App Admin or App Owner | skill: da-2 | automatable: Yes | checkpoints: WD-ENTRA-SCOPE-001 | gate: prog | status: pending -->
- [ ] **Approve the sign-in permissions** — Grant organization-wide consent for the permissions the Workday connection needs.
  <!-- id: DA2.3 | role: Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA) | skill: da-2 | automatable: Attempt | checkpoints: WD-ENTRA-CONSENT-001 | gate: prog; escalate to manual if blocked | status: pending -->
- [ ] **Choose who can use Workday** — Assign the employees or groups allowed to use the Workday application, or confirm assignment is not required.
  <!-- id: DA2.4 | role: App/Cloud App Admin | skill: da-2 | automatable: Yes | checkpoints: WD-ASSIGN-001 | gate: prog | status: pending -->
- [ ] **Match the signed-in employee** — Configure the sign-in identifier Workday uses to find the current employee.
  <!-- id: DA2.5 | role: App/Cloud App Admin | skill: da-2 | automatable: Attempt | checkpoints: WD-ENTRA-NAMEID-001 | gate: prog; degrade to manual portal row if brittle | status: pending -->
- [ ] **Sign the Workday sign-in response** — Turn on "Sign SAML response and assertion" so Workday trusts the sign-in response.
  <!-- id: DA2.6 | role: App/Cloud App Admin | skill: da-2 | automatable: No (portal-only) | checkpoints: WD-ENTRA-SIGNOPT-001 | gate: manual | status: pending -->
- [ ] **Confirm the correct Microsoft Entra tenant** — Verify Workday is connected to this environment's Microsoft Entra tenant.
  <!-- id: DA2.7 | role: App/Cloud App Admin | skill: da-2 | automatable: No | checkpoints: WD-CONN-010 | gate: attest | status: pending -->

### 3. Workday tenant configuration

- [ ] **Register the Workday API client** — In Workday, register the API client for the agent, including the functional areas and Workday-owned scope.
  <!-- id: DA3.1 | role: Workday Administrator | skill: da-3 | automatable: No | checkpoints: WD-API-CLIENT-001 | gate: attest | status: pending -->
- [ ] **Capture your Workday connection details** — Record the client ID, token endpoint, REST and SOAP base URLs, and tenant name needed to connect.
  <!-- id: DA3.2 | role: Workday Administrator | skill: da-3 | automatable: No | checkpoints: WD-API-CLIENT-001 | gate: attest | status: pending -->
- [ ] **Verify employee SAML sign-in policy** — Confirm an active Workday authentication rule allows SAML for the intended employees, or have the Workday administrator review and activate the required change.
  <!-- id: DA3.3 | role: Workday Administrator | skill: da-3 | automatable: No | checkpoints: WD-TENANT-001 | gate: attest | status: pending -->
- [ ] **Match the signing certificate** — Confirm the Workday-side signing certificate matches the one in Entra (validity dates, or an externally-computed SHA-1 — Workday shows no thumbprint).
  <!-- id: DA3.4 | role: Workday Administrator | skill: da-3 | automatable: No (Workday cert field not API-reachable) | checkpoints: WD-CONN-102 | gate: manual/attest (WD-CONN-102 returns MANUAL — operator compares certificate: dates / external SHA-1) | status: pending -->

### 4. Power Platform and agent integration

- [ ] **Create the Workday connection** — Create the signed-in employee Workday connection with the captured Workday endpoints.
  <!-- id: DA4.1 | role: Environment Maker | skill: da-4 | automatable: No | checkpoints: n/a | gate: manual | status: pending -->
- [ ] **Create the Microsoft Dataverse connection** — Create or select an active Dataverse connection owned by the maker in this environment.
  <!-- id: DA4.2 | role: Environment Maker | skill: da-4 | automatable: No | checkpoints: n/a | gate: manual | status: pending -->
- [ ] **Bind the extension connections** — Attach the Workday and Dataverse connections to the installed Workday runtime references.
  <!-- id: DA4.3 | role: Environment Maker | skill: da-4 | automatable: Yes | checkpoints: post-write reference verification | gate: prog | status: pending -->
- [ ] **Turn on the Workday cloud flows** — Enable every Workday runtime flow after its connections are bound.
  <!-- id: DA4.4 | role: Environment Maker | skill: da-4 | automatable: Attempt | checkpoints: flow state verification | gate: prog, else manual | status: pending -->
- [ ] **Connect Workday to the agent** — Connect each Workday flow in Copilot Studio and allow it to share the connection parameters used for signed-in employee access.
  <!-- id: DA4.5 | role: Environment Maker | skill: da-4 | automatable: No | checkpoints: WD-DA-CONN-001 | gate: prog, else manual | status: pending -->
- [ ] **Authorize the agent to use the Workday flows** — Preview and apply the delegated authorization and workflow sharing required by the ESS HR agent.
  <!-- id: DA4.6 | role: Power Platform Administrator | skill: da-4 | automatable: Yes | checkpoints: authorization script verification | gate: prog | status: pending -->
- [ ] **Configure employee context and topics** — Use the Workday package's V2 signed-in-user context and enable the Workday topics selected for this agent.
  <!-- id: DA4.7 | role: Environment Maker | skill: da-4 | automatable: Attempt | checkpoints: WD-DA-CTX-001 | gate: prog user-context + manual topics | status: pending -->
- [ ] **Review network restrictions** — Review the Workday REST and SOAP hosts only when organizational network controls restrict managed-connector access.
  <!-- id: DA4.8 | role: InfoSec/IT | skill: da-4 | automatable: No | checkpoints: n/a | gate: advisory | status: pending -->

### 5. Validate Workday readiness

- [ ] **Validate a signed-in Workday scenario** — Run a Workday topic as a signed-in employee and confirm the agent returns real data before marking the environment ready.
  <!-- id: DA5.1 | role: Environment Maker + Workday test user | skill: da-5 | automatable: No | checkpoints: n/a | gate: manual | status: pending -->

> An item backed by an **attest** or **manual** gate is **never** auto-completed
> by its checkpoint — it requires an explicit user acknowledgement plus
> captured evidence (see [`shared/checklist-updater.md`](shared/checklist-updater.md)).

DA-scoped APIs are not available for every Power Platform surface. Those rows
remain manual or attested rather than being falsely completed by CEA-specific
checks. The final row requires runtime evidence from a signed-in user.
