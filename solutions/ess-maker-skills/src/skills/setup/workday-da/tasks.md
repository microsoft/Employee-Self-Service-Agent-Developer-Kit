<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday Connect (DA) — Checklist (template)

The single, trackable checklist spanning the four Workday connect steps for the
**Declarative Agent (DA)** flavor of Employee Self-Service. This file is the
**canonical row source**: on first run the skill renders it to the working copy
`.local/setup/workday-da/tasks.md` and then updates **only its own items**
through the shared
[`shared/checklist-updater.md`](shared/checklist-updater.md). The durable
mirror of each item's status is `setupStatus` in
`.local/connect/workday-da/config.json` (see
[`shared/config-schema.md`](shared/config-schema.md)).

> Do not hand-edit the working copy's checkboxes — let the checklist-updater
> write them so the **MANUAL / attestation rule** is enforced in one place.

This checklist assumes your DA Employee Self-Service base agent is already
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

- [ ] **Install the Workday extension package** — Add the Workday extension package to your DA agent so it can talk to Workday. If your DA base agent isn't installed yet, this step sends you to `/setup` first.
  <!-- id: DA1.1 | role: Environment Maker | skill: da-1 | automatable: Attempt | checkpoints: WD-DA-PKG-001 | gate: prog, else manual | status: pending -->

### 2. Workday single sign-on (Entra)

- [ ] **Create the Workday single sign-on app** — Set up the Entra SSO application for Workday in SAML mode, with the right sign-on URLs and an active signing certificate.
  <!-- id: DA2.1 | role: App/Cloud App Admin | skill: da-2 | automatable: Yes | checkpoints: WD-CONN-102 | gate: prog instantiate (Graph); WD-CONN-102 healthy-state = MANUAL (Entra cert health auto-checked; Workday certificate parity deferred to DA3.4) | status: pending -->
- [ ] **Expose the Workday API permission** — Publish the sign-in scope, pre-authorize the Workday connector, and request the Microsoft Graph permissions the agent needs.
  <!-- id: DA2.2 | role: App/Cloud App Admin or App Owner | skill: da-2 | automatable: Yes | checkpoints: WD-ENTRA-SCOPE-001 | gate: prog | status: pending -->
- [ ] **Grant admin consent** — Approve the requested Microsoft Graph permissions on behalf of your organization.
  <!-- id: DA2.3 | role: Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA) | skill: da-2 | automatable: Attempt | checkpoints: WD-ENTRA-CONSENT-001 | gate: prog; escalate to manual if blocked | status: pending -->
- [ ] **Assign users to the Workday app** — Give the right people or groups access to the Workday enterprise application, or confirm assignment isn't required.
  <!-- id: DA2.4 | role: App/Cloud App Admin | skill: da-2 | automatable: Yes | checkpoints: WD-ASSIGN-001 | gate: prog | status: pending -->
- [ ] **Map the sign-in identifier** — Configure the NameID claim so Workday recognizes each signed-in employee.
  <!-- id: DA2.5 | role: App/Cloud App Admin | skill: da-2 | automatable: Attempt | checkpoints: WD-ENTRA-NAMEID-001 | gate: prog; degrade to manual portal row if brittle | status: pending -->
- [ ] **Set the SAML signing option** — Turn on "Sign SAML response and assertion" so Workday trusts the sign-in tokens.
  <!-- id: DA2.6 | role: App/Cloud App Admin | skill: da-2 | automatable: No (portal-only) | checkpoints: WD-ENTRA-SIGNOPT-001 | gate: manual | status: pending -->
- [ ] **Confirm a single sign-in tenant** — Verify Workday and Entra are federated to the same single tenant so sign-in lines up.
  <!-- id: DA2.7 | role: App/Cloud App Admin | skill: da-2 | automatable: No | checkpoints: WD-CONN-010 | gate: attest | status: pending -->

### 3. Workday tenant configuration

- [ ] **Register the Workday API client** — In Workday, register the API client for the agent, including the functional areas and Workday-owned scope.
  <!-- id: DA3.1 | role: Workday Administrator | skill: da-3 | automatable: No | checkpoints: WD-API-CLIENT-001 | gate: attest | status: pending -->
- [ ] **Capture your Workday connection details** — Record the client ID, token endpoint, REST and SOAP base URLs, and tenant name needed to connect.
  <!-- id: DA3.2 | role: Workday Administrator | skill: da-3 | automatable: No | checkpoints: WD-TENANT-001 | gate: attest | status: pending -->
- [ ] **Activate the Workday authentication policy** — Scope Workday's authentication policy to the new OAuth client, allow SAML sign-in, and activate it.
  <!-- id: DA3.3 | role: Workday Administrator | skill: da-3 | automatable: No | checkpoints: WD-TENANT-001 | gate: attest | status: pending -->
- [ ] **Match the signing certificate** — Confirm the Workday-side signing certificate matches the one in Entra (validity dates, or an externally-computed SHA-1 — Workday shows no thumbprint).
  <!-- id: DA3.4 | role: Workday Administrator | skill: da-3 | automatable: No (Workday cert field not API-reachable) | checkpoints: WD-CONN-102 | gate: manual/attest (WD-CONN-102 returns MANUAL — operator compares certificate: dates / external SHA-1) | status: pending -->

### 4. Verify your Workday connection

- [ ] **Review your Workday connection** — Confirm the extension package, single sign-on, and tenant configuration are all in place, and see what's left before your agent can use Workday.
  <!-- id: DA4.1 | role: Environment Maker | skill: da-4 | automatable: Yes | checkpoints: WD-DA-PKG-001 (reuse) | gate: advisory | status: pending -->

> An item backed by an **attest** or **manual** gate is **never** auto-completed
> by its checkpoint — it requires an explicit user acknowledgement plus
> captured evidence (see [`shared/checklist-updater.md`](shared/checklist-updater.md)).

## Deferred to a follow-up

This checklist deliberately stops at "the extension package is installed and
your Entra/tenant configuration is in place." It does not yet include DA
checkpoints for binding the Workday connection references (account sign-in,
Dataverse connection, REST address, cloud flows, firewall allowlisting) the
way the CEA `setup/workday/tasks.md` skills 5.2–5.8 do — those checks are keyed
off connection-reference and cloud-flow internals specific to the CEA package
today, and DA-scoped equivalents don't exist yet. DA-4 tells you this
explicitly and points you to the full FlightCheck report so nothing is hidden.
