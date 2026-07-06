<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Setup — Checklist (template)

The single, trackable checklist spanning all six Workday setup skills plus the
manual prerequisite steps. This file is the **canonical row source**: on first run
each skill renders it to the working copy `.local/setup/workday/tasks.md` and then
updates **only its own items** through the shared
[`checklist-updater.md`](../shared/checklist-updater.md). The durable mirror of
each item's status is `setupStatus` in `.local/connect/workday/config.json` (see
[`config-schema.md`](../shared/config-schema.md)).

> Do not hand-edit the working copy's checkboxes — let the checklist-updater
> write them so the **MANUAL / attestation rule** is enforced in one place.

## How to read this checklist

Each item is a plain checkbox with a short description of what it achieves — that
is what the user sees:

- `- [ ]` — not done yet.
- `- [x]` — done.

The technical details the tooling needs (the stable **Step ID**, the flightcheck
**checkpoint(s)** that verify the item, and the completion **gate**) live in the
HTML comment directly under each item. Those comments are invisible in the
rendered checklist; only the checklist-updater reads them. **Never surface a Step
ID or checkpoint ID to the user** — show the checkbox and its description only.

**Gate** — how an item reaches done:

| Gate | Meaning |
|------|---------|
| `prog` | A programmatic flightcheck pass completes the item. |
| `manual` | Explicit user action + re-verify; a flightcheck pass alone never completes it. |
| `attest` | Attestation + captured evidence (no queryable directory); never auto-completed. |

Full role × gate mapping: [`role-gating.md`](../../../reference/ess-docs/setup/role-gating.md).

A checkpoint ending in `*` is a **data-driven family** (e.g. `WD-FLOW-*`): the item
expands to one checkbox **per** emitted / created item at render time. A `(reuse)`
marker means the checkpoint already existed before this setup flow; all others are
minted by the owning skill.

The hidden `status:` field carries the full four-state value
(`pending` \| `in-progress` \| `done` \| `blocked`) that a single checkbox can't
express; all items start `pending`.

## Checklist

### 1. Power Platform environment

- [ ] **Set up your Power Platform environment** — Create the Power Platform environment with a Dataverse database so your agent and its data have a home.
  <!-- id: S1.1 | role: Power Platform Administrator | skill: skill-1 | automatable: Yes | checkpoints: ENV-001, ENV-002 (reuse) | gate: prog | status: pending -->
- [ ] **Confirm Copilot Studio capacity** — Make sure your tenant has enough Copilot Studio message capacity to run the agent.
  <!-- id: S1.2 | role: Power Platform Administrator | skill: skill-1 | automatable: Partial | checkpoints: ENV-CAPACITY-001 | gate: prog, else attest | status: pending -->

### 2. Employee Self-Service base agent

- [ ] **Install the Employee Self-Service agent** — Add the Microsoft Employee Self-Service base agent to your environment from AppSource.
  <!-- id: S2.1 | role: Environment Maker | skill: skill-2 | automatable: No | checkpoints: ESS-SOLN-001 | gate: manual | status: pending -->

### 3. Workday single sign-on (Entra)

- [ ] **Create the Workday single sign-on app** — Set up the Entra SSO application for Workday in SAML mode, with the right sign-on URLs and an active signing certificate.
  <!-- id: S3.1 | role: App/Cloud App Admin | skill: skill-3 | automatable: Yes | checkpoints: WD-CONN-102 | gate: prog instantiate (Graph); WD-CONN-102 healthy-state = MANUAL (Entra cert health auto-checked; Workday thumbprint parity deferred to S4.4) | status: pending -->
- [ ] **Expose the Workday API permission** — Publish the sign-in scope, pre-authorize the Workday connector, and request the Microsoft Graph permissions the agent needs.
  <!-- id: S3.2 | role: App/Cloud App Admin or App Owner | skill: skill-3 | automatable: Yes | checkpoints: WD-ENTRA-SCOPE-001 | gate: prog | status: pending -->
- [ ] **Grant admin consent** — Approve the requested Microsoft Graph permissions on behalf of your organization.
  <!-- id: S3.3 | role: Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA) | skill: skill-3 | automatable: Attempt | checkpoints: WD-ENTRA-CONSENT-001 | gate: prog; escalate to manual if blocked | status: pending -->
- [ ] **Assign users to the Workday app** — Give the right people or groups access to the Workday enterprise application, or confirm assignment isn't required.
  <!-- id: S3.4 | role: App/Cloud App Admin | skill: skill-3 | automatable: Yes | checkpoints: WD-ASSIGN-001 | gate: prog | status: pending -->
- [ ] **Map the sign-in identifier** — Configure the NameID claim so Workday recognizes each signed-in employee.
  <!-- id: S3.5 | role: App/Cloud App Admin | skill: skill-3 | automatable: Attempt | checkpoints: WD-ENTRA-NAMEID-001 | gate: prog; degrade to manual portal row if brittle | status: pending -->
- [ ] **Set the SAML signing option** — Turn on "Sign SAML response and assertion" so Workday trusts the sign-in tokens.
  <!-- id: S3.6 | role: App/Cloud App Admin | skill: skill-3 | automatable: No (portal-only) | checkpoints: WD-ENTRA-SIGNOPT-001 | gate: manual | status: pending -->
- [ ] **Confirm a single sign-in tenant** — Verify Workday and Entra are federated to the same single tenant so sign-in lines up.
  <!-- id: S3.7 | role: App/Cloud App Admin | skill: skill-3 | automatable: No | checkpoints: WD-CONN-010 | gate: attest | status: pending -->

### 4. Workday tenant configuration

- [ ] **Register the Workday API client** — In Workday, register the API client for the agent, including the functional areas and Workday-owned scope.
  <!-- id: S4.1 | role: Workday Administrator | skill: skill-4 | automatable: No | checkpoints: WD-API-CLIENT-001 | gate: attest | status: pending -->
- [ ] **Capture your Workday connection details** — Record the client ID, token endpoint, REST and SOAP base URLs, and tenant name needed to connect.
  <!-- id: S4.2 | role: Workday Administrator | skill: skill-4 | automatable: No | checkpoints: WD-TENANT-001 | gate: attest | status: pending -->
- [ ] **Activate the Workday authentication policy** — Scope Workday's authentication policy to the new OAuth client, allow SAML sign-in, and activate it.
  <!-- id: S4.3 | role: Workday Administrator | skill: skill-4 | automatable: No | checkpoints: WD-TENANT-001 | gate: attest | status: pending -->
- [ ] **Match the signing certificate** — Confirm the Workday-side signing certificate thumbprint matches the one in Entra.
  <!-- id: S4.4 | role: Workday Administrator | skill: skill-4 | automatable: No (Workday cert field not API-reachable) | checkpoints: WD-CONN-102 | gate: manual/attest (WD-CONN-102 returns MANUAL — operator compares thumbprints) | status: pending -->

### 5. Workday extension pack

- [ ] **Install the Workday extension pack** — Add the Workday extension pack to your agent so it can talk to Workday.
  <!-- id: S5.1 | role: Environment Maker | skill: skill-5 | automatable: No | checkpoints: WD-PKG-001 | gate: manual | status: pending -->
- [ ] **Connect your Workday account** — Bind the Workday connection to your own account so requests run as the signed-in employee.
  <!-- id: S5.2 | role: Environment Maker | skill: skill-5 | automatable: Yes | checkpoints: WD-CONN-012 | gate: prog | status: pending -->
- [ ] **Use Entra ID Integrated sign-in** — Confirm the Workday connection is set to "Microsoft Entra ID Integrated" authentication.
  <!-- id: S5.3 | role: Environment Maker | skill: skill-5 | automatable: Yes | checkpoints: WD-CONN-AUTH-001 | gate: attest (WD-CONN-AUTH-001 returns MANUAL — no kit-verifiable auth-type fingerprint; operator confirms) | status: pending -->
- [ ] **Connect Dataverse** — Bind the Dataverse connection to your own account so the agent can read its configuration.
  <!-- id: S5.4 | role: Environment Maker | skill: skill-5 | automatable: Yes | checkpoints: DV-CONN-001 | gate: prog | status: pending -->
- [ ] **Set the Workday REST address** — Make sure the Workday REST base URL is filled in and trimmed to end with `/api`.
  <!-- id: S5.5 | role: Environment Maker | skill: skill-5 | automatable: Yes | checkpoints: WD-REST-001 | gate: prog | status: pending -->
- [ ] **Turn on the Workday cloud flows** — Switch on the background flows that carry requests between the agent and Workday.
  <!-- id: S5.6 | role: Environment Maker | skill: skill-5 | automatable: Yes | checkpoints: WD-FLOW-* | gate: prog | status: pending -->
- [ ] **Wire up the employee-context lookup** — Publish the redirect that lets the agent look up who the signed-in employee is (skipped if it's already present).
  <!-- id: S5.7 | role: Environment Maker | skill: skill-5 | automatable: Yes | checkpoints: WD-REST-002 | gate: prog w/ rollback | status: pending -->
- [ ] **Allow Workday through your firewall** — Add the Workday REST and SOAP endpoints to your network allowlist so traffic can get through.
  <!-- id: S5.8 | role: InfoSec/IT | skill: skill-5 | automatable: No | checkpoints: WD-NET-001 | gate: attest | status: pending -->

### 6. Your first Workday topic

- [ ] **Give your new topic its trigger phrases** — Define the new topic and the phrases employees will use to start it.
  <!-- id: S6.1 | role: Environment Maker (+ Workday SME) | skill: skill-6 | automatable: Yes | checkpoints: TOPIC-TRIGGER-* | gate: prog | status: pending -->
- [ ] **Wire your new topic to Workday** — Connect the new topic to Workday using your tenant's reference IDs, with no placeholders left behind.
  <!-- id: S6.2 | role: Environment Maker (+ Workday SME) | skill: skill-6 | automatable: Yes | checkpoints: TOPIC-INTEGRATION-* | gate: prog (+ SME for IDs) | status: pending -->

> Items whose checkpoint is a `*` family (the cloud flows, and each new topic)
> expand to one checkbox **per** emitted / created item at run time. An item backed
> by an **attest** or **manual** gate is **never** auto-completed by its checkpoint —
> it requires an explicit user acknowledgement plus captured evidence (see
> [`checklist-updater.md`](../shared/checklist-updater.md)).
