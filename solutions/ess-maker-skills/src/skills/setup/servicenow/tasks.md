<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# ServiceNow Setup — Checklist (template)

The single, trackable checklist spanning the ServiceNow setup skills plus the
manual prerequisite steps. This file is the **canonical row source**: on first run
each skill renders it to the working copy `.local/setup/servicenow/tasks.md` and then
updates **only its own items** through the shared
[`checklist-updater.md`](../shared/checklist-updater.md). The durable mirror of
each item's status is `setupStatus` in `.local/connect/servicenow/config.json` (see
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

A checkpoint ending in `*` is a **data-driven family** (e.g. `SN-FLOW-*`): the item
expands to one checkbox **per** emitted / created item at render time. A `(reuse)`
marker means the checkpoint already existed before this setup flow; all others are
minted by the owning skill.

The hidden `status:` field carries the full four-state value
(`pending` \| `in-progress` \| `done` \| `blocked`) that a single checkbox can't
express; all items start `pending`.

## Auth-path variants — render only the selected path

ServiceNow supports two supported sign-in paths (spec V2): **`entra_user`**
(delegated user sign-in, the default) and **`entra_certificate`** (certificate /
service-account). Group **4** covers the `entra_user` path and group **5** covers
the `entra_certificate` path — they are **mutually exclusive**. The orchestrator
reads `authType` from `.local/connect/servicenow/config.json` (captured in **S3.1**)
and renders **only** the matching group; the other group is omitted from the working
checklist entirely (like a `*` family that expands to zero rows). Legacy paths
(`oauth2`, `basic`, `graph`/federated) are out of scope and are not supported; only
the two Entra sign-in methods are offered.

## Checklist

### 1. Power Platform environment

- [ ] **Set up your Power Platform environment** — Create the Power Platform environment with a Dataverse database so your agent and its data have a home.
  <!-- id: S1.1 | role: Power Platform Administrator | skill: skill-1 | automatable: Yes | checkpoints: ENV-001, ENV-002 (reuse) | gate: prog | status: pending -->
- [ ] **Confirm Copilot Studio capacity** — Make sure your tenant has enough Copilot Studio message capacity to run the agent.
  <!-- id: S1.2 | role: Power Platform Administrator | skill: skill-1 | automatable: Partial | checkpoints: ENV-CAPACITY-001 (reuse) | gate: prog, else attest | status: pending -->

### 2. Employee Self-Service base agent

- [ ] **Install the Employee Self-Service agent** — Add the Microsoft Employee Self-Service base agent to your environment from AppSource.
  <!-- id: S2.1 | role: Environment Maker | skill: skill-2 | automatable: No | checkpoints: ESS-SOLN-001 (reuse) | gate: prog | status: pending -->

### 3. ServiceNow connection basics

- [ ] **Capture your ServiceNow instance and scope** — Record your ServiceNow instance, the products in scope (HRSD / ITSM), the connector, and the sign-in method you'll use.
  <!-- id: S3.1 | role: Maker | skill: skill-3 | automatable: Yes | checkpoints: SN-CONFIG-001 | gate: prog | status: pending -->
- [ ] **Confirm your maker permissions** — Check you have the Entra and ServiceNow permissions the rest of setup needs, so nothing stalls halfway.
  <!-- id: S3.2 | role: Maker (+ Entra admin, ServiceNow admin) | skill: skill-3 | automatable: Partial | checkpoints: SN-PERM-001 | gate: prog; else manual | status: pending -->
- [ ] **Confirm your ServiceNow user record** — Verify the person who'll sign in actually exists as an active user in ServiceNow, so requests return their real data instead of coming back empty.
  <!-- id: S3.3 | role: ServiceNow admin | skill: skill-3 | automatable: Partial | checkpoints: SN-USER-001 | gate: attest | status: pending -->

### 4. ServiceNow single sign-on — user sign-in (Entra)

<!-- variant: authType == "entra_user" — rendered only when the captured authType is entra_user; omitted otherwise -->

- [ ] **Create the ServiceNow sign-in app** — Register the Entra application that lets employees sign in to ServiceNow with their Microsoft identity, and expose the sign-in scope.
  <!-- id: S4.1 | role: App/Cloud App Admin | skill: skill-4 | automatable: Yes | checkpoints: SN-ENTRA-SCOPE-001 | gate: prog | status: pending -->
- [ ] **Grant admin consent** — Approve the Microsoft Graph permissions the sign-in app needs on behalf of your organization.
  <!-- id: S4.2 | role: Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA) | skill: skill-4 | automatable: Attempt | checkpoints: SN-ENTRA-CONSENT-001 | gate: prog; escalate to manual if blocked | status: pending -->
- [ ] **Register the ServiceNow OIDC provider** — In ServiceNow, register Entra as the OIDC identity provider and map the sign-in claims. This is a ServiceNow-admin action the kit never performs for you.
  <!-- id: S4.3 | role: ServiceNow admin | skill: skill-4 | automatable: No (spec: agent must never automate ServiceNow OIDC) | checkpoints: SN-CONN-OIDC-001 | gate: attest | status: pending -->
- [ ] **Map the sign-in identity to a ServiceNow user** — Confirm the signed-in Microsoft identity resolves to the matching ServiceNow user (claim → user field), so each employee sees their own data.
  <!-- id: S4.4 | role: ServiceNow admin | skill: skill-4 | automatable: No | checkpoints: SN-USERMAP-001 | gate: attest | status: pending -->

### 5. ServiceNow single sign-on — certificate (Entra)

<!-- variant: authType == "entra_certificate" — rendered only when the captured authType is entra_certificate; omitted otherwise -->

- [ ] **Create the certificate sign-in apps** — Register the Entra applications for the certificate / service-account sign-in path (the OIDC resource app and the service-account app).
  <!-- id: S5.1 | role: App/Cloud App Admin | skill: skill-5 | automatable: Yes | checkpoints: SN-ENTRA-CERT-001 | gate: prog | status: pending -->
- [ ] **Upload the signing certificate and trust it** — Upload the signing certificate to the app and record the certificate trust (SNI subject) so ServiceNow accepts the tokens.
  <!-- id: S5.2 | role: App/Cloud App Admin | skill: skill-5 | automatable: Yes | checkpoints: SN-ENTRA-CERT-001 | gate: prog; else attest | status: pending -->
- [ ] **Register the ServiceNow OIDC provider and system user** — In ServiceNow, register Entra as the OIDC provider and create the integration system user. Both are ServiceNow-admin actions the kit never performs for you.
  <!-- id: S5.3 | role: ServiceNow admin | skill: skill-5 | automatable: No (spec: agent must never automate ServiceNow OIDC) | checkpoints: SN-CONN-OIDC-001, SN-SYSUSER-001 | gate: attest | status: pending -->

### 6. ServiceNow extension pack and connection

This group has four **sub-blocks**, run in order. The **create-connections**
sub-block (6a) is always rendered and comes **first**: the maker creates the Power
Platform ServiceNow and Dataverse connection objects up front, using the sign-in
method from group 4/5, so nothing needs re-authenticating later. The **install**
sub-block (6b) and the **flows-and-finish** sub-block (6d) are **variant groups** —
*ServiceNow HR* and *ServiceNow IT* — each rendered **only when that product is in
`scope`** (like the mutually-exclusive auth groups 4 and 5): if only ITSM is
selected, the HR rows are omitted entirely, and vice-versa. Their rows carry a
`product:` tag (`hrsd` / `itsm`) and mirror under `productStatus.<product>` in
`.local/connect/servicenow/config.json`, because the extension pack, its cloud
flows, its flow-invoker binding, and its portal URL are all installed **per
product**. The **shared connection** sub-block (6c) is always rendered — its single
step binds the pack's connection references to the connections created in 6a (one
ServiceNow connection is shared by every installed pack) and mirrors under the flat
`setupStatus` block. Routing rule: a row **with** a `product:` tag →
`productStatus.<product>`; a row **without** one → `setupStatus` (see
[`checklist-updater.md`](../shared/checklist-updater.md)).

Connection *creation* (6a) needs only the sign-in method and does **not** depend on
the pack, so it runs before install. The pack install (6b), connection-*reference*
binding (6c), and flow activation / invoker / share / portal (6d) act on artifacts
that ship **inside** the pack, so they stay after the installs. The shared bind (6c)
sits between install (6b) and the per-product flow steps (6d): the references it
binds ship in the pack, and the flows in 6d can only run once those references are
bound.

#### 6a. Create connections

<!-- Always rendered — the ServiceNow and Dataverse connection objects every pack shares are created here, before install. -->

- [ ] **Create the ServiceNow and Dataverse connections** — Create the Power Platform ServiceNow connection (using your chosen sign-in method) and the Dataverse connection now, so the extension pack's references bind to existing connections later without re-authenticating.
  <!-- id: S6.0 | role: Environment Maker | skill: skill-6 | automatable: Partial (maker creates; checkpoint verifies) | checkpoints: SN-CONN-OBJECTS-001 | gate: prog; attest only when inventory is unavailable | status: pending -->

#### 6b. Install the extension pack

<!-- variant: scope.hrsd / scope.itsm — one install row per in-scope product; a product's row is omitted when that product is out of scope. -->

- [ ] **Install the ServiceNow HR extension pack** — Add the ServiceNow HR (HRSD) extension pack to your agent in Copilot Studio.
  <!-- id: S6.1 | product: hrsd | role: Environment Maker | skill: skill-6 | automatable: No (maker installs; checkpoint verifies) | checkpoints: SN-PKG-001 | gate: prog (maker installs, checkpoint verifies) | status: pending -->
- [ ] **Install the ServiceNow IT extension pack** — Add the ServiceNow IT (ITSM) extension pack to your agent in Copilot Studio.
  <!-- id: S6.1 | product: itsm | role: Environment Maker | skill: skill-6 | automatable: No (maker installs; checkpoint verifies) | checkpoints: SN-PKG-001 | gate: prog (maker installs, checkpoint verifies) | status: pending -->

#### 6c. Shared connection

<!-- Always rendered — one ServiceNow connection is shared by every installed pack. -->

- [ ] **Connect ServiceNow and Dataverse** — Bind the ServiceNow and Dataverse connection references (shipped by the pack) to the connections you created in 6a, so the agent can talk to ServiceNow and read its configuration.
  <!-- id: S6.2 | role: Environment Maker | skill: skill-6 | automatable: No (maker binds; checkpoint verifies) | checkpoints: SN-DV-CONN-001; SN connection health confirmed when maker connects the flow invoker at S6.4 | gate: prog; else attest for auth-type | status: pending -->

#### 6d. Turn on flows and finish (per product)

<!-- variant: scope.hrsd / scope.itsm — each product's cloud flows, flow-invoker binding, connection share, and portal URL are installed per pack; a product's rows are omitted when that product is out of scope. -->

- [ ] **Turn on the ServiceNow HR flows** — Switch on the HR (HRSD) background flows that carry requests between the agent and ServiceNow.
  <!-- id: S6.3 | product: hrsd | role: Environment Maker | skill: skill-6 | automatable: No (maker turns on; checkpoint verifies) | checkpoints: SN-FLOW-* | gate: prog | status: pending -->
- [ ] **Connect ServiceNow HR to your agent's flows** — Bind the ServiceNow flow invoker connection for HR (HRSD) so Copilot Studio shows the connection as connected.
  <!-- id: S6.4 | product: hrsd | role: Environment Maker | skill: skill-6 | automatable: No (maker connects; attested) | checkpoints: maker-attested | gate: attest | status: pending -->
- [ ] **Share the ServiceNow HR connection parameters** — Share the HR (HRSD) connection parameters onto the portal-owned reference so end users inherit your connection instead of being prompted to create their own.
  <!-- id: S6.5 | product: hrsd | role: Environment Maker | skill: skill-6 | automatable: No (maker shares; attested) | checkpoints: maker-attested (SN-FLOWCONN-001 confirms connection health) | gate: attest | status: pending -->
- [ ] **Set the HR Portal Base URL** — Point the HR (HRSD) pack at your confirmed ServiceNow Service Portal URL so the links the agent returns open the right pages.
  <!-- id: S6.6 | product: hrsd | role: Environment Maker | skill: skill-6 | automatable: Yes | checkpoints: SN-BASEURL-001 | gate: prog; attest only if unverifiable (Skipped/Warning), never on Failed | status: pending -->
<!-- future: S6.7 | product: hrsd — Install the ServiceNow `sn_hr_core` plugin (HR only). Reserved; render + mint SN-HR-PLUGIN-001 when implemented. -->
<!-- future: S6.8 | product: hrsd — Grant the required ServiceNow HR table access. Reserved; render when implemented. -->
- [ ] **Turn on the ServiceNow IT flows** — Switch on the IT (ITSM) background flows that carry requests between the agent and ServiceNow.
  <!-- id: S6.3 | product: itsm | role: Environment Maker | skill: skill-6 | automatable: No (maker turns on; checkpoint verifies) | checkpoints: SN-FLOW-* | gate: prog | status: pending -->
- [ ] **Connect ServiceNow IT to your agent's flows** — Bind the ServiceNow flow invoker connection for IT (ITSM) so Copilot Studio shows the connection as connected.
  <!-- id: S6.4 | product: itsm | role: Environment Maker | skill: skill-6 | automatable: No (maker connects; attested) | checkpoints: maker-attested | gate: attest | status: pending -->
- [ ] **Share the ServiceNow IT connection parameters** — Share the IT (ITSM) connection parameters onto the portal-owned reference so end users inherit your connection instead of being prompted to create their own.
  <!-- id: S6.5 | product: itsm | role: Environment Maker | skill: skill-6 | automatable: No (maker shares; attested) | checkpoints: maker-attested (SN-FLOWCONN-001 confirms connection health) | gate: attest | status: pending -->
- [ ] **Set the IT Portal Base URL** — Point the IT (ITSM) pack at your confirmed ServiceNow Service Portal URL so the links the agent returns open the right pages.
  <!-- id: S6.6 | product: itsm | role: Environment Maker | skill: skill-6 | automatable: Yes | checkpoints: SN-BASEURL-001 | gate: prog; attest only if unverifiable (Skipped/Warning), never on Failed | status: pending -->
<!-- future: S6.8 | product: itsm — Grant the required ServiceNow IT table access. Reserved; render when implemented. -->
### 7. Validate and hand off

- [ ] **Run an end-to-end validation** — Ask the agent a real ServiceNow question and confirm it returns your live data with working portal links.
  <!-- id: S7.1 | role: Maker | skill: skill-7 | automatable: No | checkpoints: n/a | gate: attest | status: pending -->
- [ ] **Create your first ServiceNow topic** — Hand off to topic creation so you can build your first custom ServiceNow topic on the working connection.
  <!-- id: S7.2 | role: Maker | skill: skill-7 | automatable: No | checkpoints: n/a | gate: manual | status: pending -->

> Items whose checkpoint is a `*` family (the ServiceNow flows) expand to one
> checkbox **per** emitted item at run time. An item backed by an **attest** or
> **manual** gate is **never** auto-completed by its checkpoint — it requires an
> explicit user acknowledgement plus captured evidence (see
> [`checklist-updater.md`](../shared/checklist-updater.md)). The ServiceNow OIDC
> provider, system user, claim mapping, and end-to-end validation are **attest**
> rows by design: the spec forbids the agent from automating ServiceNow-internal
> OIDC, so the operator performs them and attests.
