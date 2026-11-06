<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday rollout planning reference

This is the planner's role map for a Workday rollout. Only
`python scripts/planner/cli.py setup-tasks --system workday` reads it, and it
turns the steps below into one plan task per role boundary (see
[`model.md`](../model.md) → *Split on role boundaries*).

It is a planning reference, not a progress checklist. `/connect-workday` owns
the Workday connection lifecycle and its state in
`.local/connect/workday-da/config.json`. Never track progress here, and never
copy lifecycle state into this file. The procedure, handoffs, and evidence for
each phase live in [`connect/workday/SKILL.md`](../../connect/workday/SKILL.md).
The role and evidence rules live in
[`role-gating.md`](../../../reference/ess-docs/setup/role-gating.md).

## How to read this reference

Each numbered group is one stretch of work. Each step is a bold title and a
short summary, followed by a hidden metadata comment:

| Field | Meaning |
|-------|---------|
| `id` | Stable step ID, `S<group>.<step>`. |
| `role` | Who does the step, worded as the owning skill or Microsoft Learn words it. `setup-tasks` maps it to an attestable plan role. |
| `phase` | The `/connect-workday` phase the step belongs to. Groups 1 and 2 are `/setup` foundation work and have no phase. |
| `gate` | How the step is confirmed: `prog` (the kit checks it), `manual` (the person acts in a portal, then the kit verifies the result), or `attest` (the person confirms the work and returns evidence the kit validates but cannot check directly). |

The phases must appear in the order of `PHASE_DEFINITIONS` in
`scripts/workday_connect_model.py`. A planner test enforces this.

The Microsoft Entra and Workday administrator groups are a reusable tenant
foundation. A promoted Test or Prod environment in the same tenant continues at
Connections and repeats only the maker work in group 6. Group 4 must finish,
including the certificate handoff, before group 5 starts.

## Steps

### 1. Power Platform environment

- **Create or choose the environment** — Create the Power Platform environment for the ESS HR agent in the Power Platform admin center, or choose an existing one, and make sure Copilot Studio capacity is available. `/setup` shows these steps but does not create the environment or allocate capacity.
  <!-- id: S1.1 | role: Power Platform Administrator | gate: manual -->
- **Give the maker Environment Maker** — Assign the Environment Maker security role in that environment to the maker who will create the agent.
  <!-- id: S1.2 | role: Power Platform Administrator | gate: manual -->

### 2. ESS HR agent

- **Set up the ESS HR agent** — Run `/setup` with the maker's own Microsoft login to create a fresh ESS HR agent or select an existing one, and bring its local copy into the workspace.
  <!-- id: S2.1 | role: Environment Maker | gate: prog -->

### 3. Preflight

- **Confirm Workday readiness** — Start `/connect-workday` to confirm the ESS HR agent, environment, and maker account, verify Dataverse access, and choose the supported Workday package. Nothing changes yet.
  <!-- id: S3.1 | role: Environment Maker | phase: preflight | gate: prog -->

### 4. Microsoft Entra

- **Identify the Workday app and configure SAML** — Use the existing Workday enterprise application or add it from the gallery, then set the SAML identifier, signing certificate, and signing option.
  <!-- id: S4.1 | role: Application Administrator or Cloud Application Administrator | phase: entra | gate: attest -->
- **Expose the connector scope and grant consent** — Expose the `user_impersonation` scope to the Workday connector, add the delegated Microsoft Graph permissions, and grant admin consent.
  <!-- id: S4.2 | role: Application Administrator or Cloud Application Administrator (a separate consent-capable administrator only if tenant policy blocks consent) | phase: entra | gate: attest -->
- **Configure assignment and NameID** — Assign the intended ESS employee group when assignment is required, and map NameID to the Workday user name.
  <!-- id: S4.3 | role: Application Administrator or Cloud Application Administrator | phase: entra | gate: attest -->
- **Hand off the signing certificate** — Transfer the Base64 public signing certificate to the Workday administrator through an approved channel. The Entra phase is not complete until the transfer is confirmed.
  <!-- id: S4.4 | role: Application Administrator or Cloud Application Administrator | phase: entra | gate: attest -->

### 5. Workday administrator

- **Trust the Microsoft Entra sign-in** — Install the transferred certificate, add or confirm the Entra SAML identity-provider row without replacing another federation, and enable OAuth 2.0 clients and SAML.
  <!-- id: S5.1 | role: Workday Administrator | phase: workday-admin | gate: attest -->
- **Set up the employee API client** — Reuse or register the employee API client with SAML Bearer, the required functional areas, and Workday-owned scope, grant the employee domain security, and confirm the client ID, token endpoint, and REST and SOAP base URLs.
  <!-- id: S5.2 | role: Workday Administrator | phase: workday-admin | gate: attest -->
- **Activate the employee authentication policy** — Confirm that an active rule scoped to the ESS OAuth client allows SAML for the intended employees, and activate any pending policy changes.
  <!-- id: S5.3 | role: Workday Administrator | phase: workday-admin | gate: attest -->

### 6. Connections, runtime, and maker validation

- **Install the package and create the connections** — Install or verify the supported Workday package, then create or find the Workday and Microsoft Dataverse connections and confirm both are live.
  <!-- id: S6.1 | role: Environment Maker (+ package installation access) | phase: connections | gate: manual -->
- **Configure the Workday runtime** — Preview and approve the runtime changes, then bind the connections, activate the required flows, configure permissions and employee context, connect the agent's Workday entries with parameter sharing allowed, and enable the Workday topics.
  <!-- id: S6.2 | role: Environment Maker (+ Dataverse System Administrator access for runtime authorization) | phase: runtime | gate: prog -->
- **Validate as the maker** — Test an enabled read-only Workday scenario in the Copilot Studio Test pane without publishing the agent.
  <!-- id: S6.3 | role: Environment Maker | phase: maker-validation | gate: attest -->

Publishing, deployment, employee-owned connections, and validation beyond the
maker's Test pane come after `/connect-workday`. Plan them as their own tasks.
