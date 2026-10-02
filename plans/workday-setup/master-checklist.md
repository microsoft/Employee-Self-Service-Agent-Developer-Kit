# Plan: Master setup checklist + Workday flightcheck checkpoints

The single, trackable checklist spanning all 6 skills, plus the new Workday-specific
flightcheck checkpoints and the role-gating matrix. Part of
[Workday Setup](./README.md).
**Depends on:** [`shared-building-blocks`](./shared-building-blocks.md) (checklist updater),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md) (atomic verification).

## Master checklist

One `tasks.md` spanning all 6 skills + manual prerequisites. Columns:
**Step | Role | Skill | Automatable? | Flightcheck checkpoint | Status**.

- **Concrete file:** working copy at **`my/setup/workday/tasks.md`**, rendered on first run from
  the template **`src/skills/setup/workday/tasks.md`** (the `setup` orchestrator skill folder is
  defined in [`command-wiring`](./command-wiring.md), following the existing
  `my/connect/workday/tasks.md` precedent — state under `my/`, template under `src/skills/`).

- Each skill updates **its own rows** via the shared checklist-updater.
- Each row links to a checkpoint runnable in isolation (`--checkpoint <ID>`).
- Explicit gated/manual rows for:
  - **SSO gallery app — split into three rows** (it is not one atomic action):
    (a) **automated** Graph instantiation + SAML mode + URLs + cert add/activate (Graph-first,
    portal fallback); (b) **manual gate** — the "Sign SAML response and assertion" signing
    option (portal-only); (c) **attestation** — Workday-side confirmation that the SP validates
    against the uploaded cert/SP-ID (verified functionally downstream in skill-4/skill-5).
  - **Admin consent** (consent-capable role; attempt programmatically, escalate to manual if
    blocked).
  - **NameID claim** — attempt programmatically via a `claimsMappingPolicy` create+assign
    (skill-3's `WD-ENTRA-NAMEID-001`); if that route proves brittle in testing, **degrade this to a
    MANUAL portal row** rather than reporting a false pass.
  - All **Workday-admin tenant tasks** (attestation).
  - **AppSource install** (manual gate + re-verify).
  - **Firewall allowlisting** **(REST + SOAP, InfoSec/IT — gates skill-5 functional check)**.

### Canonical checklist rows (render these exact rows into `my/setup/workday/tasks.md`)

The implementer renders **exactly** these rows — stable `Step` IDs, fixed checkpoint IDs, no
invention. `Gate` legend: **prog** = programmatic check; **manual** = explicit user action +
re-verify; **attest** = attestation + captured evidence (no queryable directory).

| Step | Role | Skill | Automatable? | Checkpoint(s) | Gate |
|------|------|-------|--------------|---------------|------|
| S1.1 — Provision Power Platform environment + Dataverse | Power Platform Administrator | skill-1 | Yes | `ENV-001`, `ENV-002` (reuse) | prog |
| S1.2 — Copilot Studio capacity available | Power Platform Administrator | skill-1 | Partial | `ENV-CAPACITY-001` | prog, else attest |
| S2.1 — Install ESS base agent from AppSource | Environment Maker | skill-2 | No | `ESS-SOLN-001` | manual |
| S3.1 — Expose `user_impersonation`, pre-authorize `4e4707ca`, grant Graph perms | App/Cloud App Admin or App Owner | skill-3 | Yes | `WD-ENTRA-SCOPE-001` | prog |
| S3.2 — Admin-consent the Graph delegated perms | Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA) | skill-3 | Attempt | `WD-ENTRA-CONSENT-001` | prog; escalate to manual if blocked |
| S3.3 — Enterprise-app user/group assignment (or confirm not required) | App/Cloud App Admin | skill-3 | Yes | `WD-ASSIGN-001` | prog |
| S3.4 — Instantiate SSO gallery app: SAML mode, URLs, signing cert add+activate | App/Cloud App Admin | skill-3 | Yes | `WD-CONN-102` | prog instantiate (Graph); `WD-CONN-102` healthy-state = `MANUAL` (Entra cert health auto-checked; Workday thumbprint parity deferred to S4.4) |
| S3.5 — NameID claim mapping (`claimsMappingPolicy`) | App/Cloud App Admin | skill-3 | Attempt | `WD-ENTRA-NAMEID-001` | prog; degrade to manual portal row if brittle |
| S3.6 — "Sign SAML response and assertion" signing option | App/Cloud App Admin | skill-3 | No (portal-only) | `WD-ENTRA-SIGNOPT-001` | manual |
| S3.7 — Confirm single-Entra-tenant federation alignment | App/Cloud App Admin | skill-3 | No | `WD-CONN-010` | attest |
| S4.1 — Register Workday API client (functional areas + Include Workday Owned Scope = Yes) | Workday Administrator | skill-4 | No | `WD-API-CLIENT-001` | attest |
| S4.2 — Capture connection fields (client ID, token endpoint, REST + SOAP base URLs, tenant) | Workday Administrator | skill-4 | No | `WD-TENANT-001` | attest |
| S4.3 — Scope authentication policies to the OAuth client, allow SAML, activate | Workday Administrator | skill-4 | No | `WD-TENANT-001` | attest |
| S4.4 — Signing-certificate thumbprint matches Entra (Workday-side `X509 Certificate` row) | Workday Administrator | skill-4 | No (Workday cert field not API-reachable) | `WD-CONN-102` | manual/attest (`WD-CONN-102` returns `MANUAL` — operator compares thumbprints) |
| S5.1 — Install Workday extension pack (simplified) | Environment Maker | skill-5 | No | `WD-PKG-001` | manual |
| S5.2 — Workday connection ref (`ff0df`) bound, own account | Environment Maker | skill-5 | Yes | `WD-CONN-012` | prog |
| S5.3 — Connection auth type = Entra ID Integrated | Environment Maker | skill-5 | Yes | `WD-CONN-AUTH-001` | prog |
| S5.4 — Dataverse connection (`92b66`) bound, own account | Environment Maker | skill-5 | Yes | `DV-CONN-001` | prog |
| S5.5 — REST base URL present and trimmed to `/api` | Environment Maker | skill-5 | Yes | `WD-REST-001` | prog |
| S5.6 — Cloud flows on | Environment Maker | skill-5 | Yes | `WD-FLOW-*` | prog |
| S5.7 — User-context redirect push (skip if `/workers/me` present; rollback checkpoint first) | Environment Maker | skill-5 | Yes | `WD-REST-002` | prog w/ rollback |
| S5.8 — Firewall allowlisting (REST + SOAP) | InfoSec/IT | skill-5 | No | `WD-NET-001` | attest |
| S6.1 — New topic trigger phrases + definition | Environment Maker (+ Workday SME) | skill-6 | Yes | `TOPIC-TRIGGER-*` | prog |
| S6.2 — New topic integration wiring (tenant reference IDs) | Environment Maker (+ Workday SME) | skill-6 | Yes | `TOPIC-INTEGRATION-*` | prog (+ SME for IDs) |

> Rows whose checkpoint is a `*` family (S5.6, S6.1, S6.2) expand to one row **per** emitted /
> created item at run time. A row backed by an **attest** or **manual** gate is **never**
> auto-completed by its checkpoint — see the `MANUAL`/attestation rule below.

## New Workday flightcheck checkpoints

Add the Workday checkpoints to `scripts/flightcheck/checks/workday.py` — the `run_workday_checks`
category function, which is registered into the generic runner by `cli.py` (`runner.register`).
Non-Workday IDs go in their own `checks/*.py` module (e.g. `ENV-CAPACITY-001`/`ESS-SOLN-001` in
`checks/environment.py`), **never** in `runner.py` (that is the integration-agnostic engine). Also
register each new ID in the checkpoint registry from
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md) and document it in
`src/reference/ess-docs/flightcheck/validation-matrix.md`, aligned to the skills.

> **Reuse before minting.** Several simplified-aware checkpoints already exist in `checks/workday.py`
> and **must be reused**, not re-created: `WD-PKG-001` (package-flavor detector, returns
> `simplified` on the exact `ff0df` match), `WD-CONN-012` (connection-reference binding
> completeness, keyed on the simplified `ff0df` suffix), `WD-CONN-102` (SAML signing-certificate
> health), `WD-CONN-010` (Entra↔Workday federation alignment). New IDs are minted **only** for
> outputs no existing checkpoint covers.

> **A trailing `*` denotes a data-driven checkpoint *family*, not a literal ID — and only the
> genuinely count-variable checkpoints keep one.** Setup-scope families: `WD-FLOW-*`
> (`checks/workday.py`'s `_check_flow_status`, one **zero-padded** `WD-FLOW-{n}` per discovered
> flow); `WD-CONN-*` (the generic connection enumerator in `checks/connections.py` emits
> `WD-CONN-001` summary + `WD-CONN-{i+2:03d}` per Workday connection — exact-first keeps reused
> fixed `WD-CONN-010`/`-012`/`-102` and new `WD-CONN-AUTH-001` as literal entries, the family
> absorbs the dynamic detail rows); `WD-WF-*` (per workflow — emitted but skipped on simplified,
> registered for completeness); the legacy `WD-ENV-*` (banned for simplified — listed only so the
> registry knows the family); and the per-topic `TOPIC-TRIGGER-*` / `TOPIC-INTEGRATION-*` (skill-6
> emits one per created topic). **Every other *setup* checkpoint is a single fixed ID** (e.g.
> `ENV-001`, `WD-ENTRA-SCOPE-001`, `WD-CONN-AUTH-001`) — no `*`, nothing for the implementer to
> invent. (Other integrations emit their own dynamic families — `SN-CONN-*`, `SN-FLOW-*`,
> `ENV-004-OR/UR/UC` detail rows, `EXT-002-*` — which are **out of setup-registry scope**; see
> [`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md).) The
> registry registers each family as a **prefix entry** so `--checkpoint WD-FLOW-*` runs the whole
> family and the drift test compares families (normalizing numeric suffixes), **not** exact
> dynamic IDs — see [`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md).

| Skill | Reuse existing | New IDs to mint |
|-------|----------------|-----------------|
| skill-1 | `ENV-001` (environment exists), `ENV-002` (Dataverse provisioned) | `ENV-CAPACITY-001` (Copilot Studio capacity / attestation) |
| skill-2 | — | `ESS-SOLN-001` (ESS solution `msdyn_copilotforemployeeselfservice*` installed) |
| skill-3 | `WD-CONN-102` (cert health), `WD-CONN-010` (federation alignment) | `WD-ENTRA-SCOPE-001` (scope exposed + `4e4707ca` pre-authorized + Graph perms), `WD-ENTRA-CONSENT-001` (admin consent), `WD-ASSIGN-001` (enterprise-app assignment / not-required), `WD-ENTRA-NAMEID-001`, `WD-ENTRA-SIGNOPT-001` (the two at-risk SAML sub-steps) |
| skill-4 | `WD-CONN-102` (cert thumbprint match) | `WD-TENANT-001`, `WD-API-CLIENT-001` (mostly `MANUAL`/attestation) |
| skill-5 | `WD-PKG-001` (flavor=simplified), `WD-CONN-012` (`ff0df` binding), `WD-FLOW-*` (cloud flows on — `checks/workday.py`'s `_check_flow_status` already emits `WD-FLOW-{n}`) | `WD-CONN-AUTH-001` (Entra-Integrated auth), `DV-CONN-001` (Dataverse `92b66`, **non-`WD`-family**), `WD-REST-001` (`/api`-trimmed), `WD-REST-002` (user-context redirect pushed → REST resolves `/workers/me`), `WD-NET-001` (Power-Platform-runtime reachability / InfoSec attestation) |
| skill-6 | — | `TOPIC-TRIGGER-*`, `TOPIC-INTEGRATION-*` |

- **`92b66` is the Dataverse connector, not a Workday ref** — the simplified Workday family
  fingerprints a **single** `ff0df` connection ref. Verify `92b66` under the **non-`WD`** ID
  `DV-CONN-001` (named for the skill, but explicitly outside the `WD-CONN` Workday-ref family),
  never as a second `WD-CONN` ref.
- **Do NOT reuse the legacy `WD-ENV-*` / `WD-WF-*` checkpoints for the simplified path** —
  they test ISU/RaaS artifacts that simplified setup removes and are skipped on simplified
  installs (reusing them yields false failures / N/A noise). Define the new simplified-only IDs
  above instead.
- Preserve `MANUAL` status for non-automatable Workday-admin steps (reports what it can, does
  not fail readiness). **A `MANUAL`/attestation checkpoint never auto-completes its checklist
  row** — the row needs an explicit user acknowledgement (+ captured artifact) to reach *done*.

### Checkpoint ownership (single owner per concern)

To avoid two plans claiming to "define" the same thing:

- **This plan (`master-checklist`) is the single registry owner** — it declares the canonical
  list of new checkpoint IDs (the table above) and their checklist rows.
- **The `flightcheck-single-checkpoint` plan owns the registry *mechanism*** (the
  ID→function→clients→config→prereqs schema and the `--checkpoint`/`--list-checkpoints` CLI).
- **Each `skill-N` plan owns the *verification wiring* for its own IDs** — the actual
  `CheckResult` emission inside the owning `checks/*.py` module (Workday IDs live in
  `checks/workday.py`'s `run_workday_checks`) and the master-checklist row updates. Skills do not
  invent IDs outside the table above without adding them here first.

## Permission / role gating (named error + stop)

Gating mechanism differs: Entra / Power Platform / Dataverse roles are checked
**programmatically**; **Workday Administrator** and **InfoSec/IT** have no queryable directory
here → **attestation + captured evidence**.

| Role | Gated step | How gated |
|------|-----------|-----------|
| Power Platform Administrator | provision-power-platform-environment | programmatic |
| Environment Maker | install-ess, install-workday-extension-pack, create-new-topic | programmatic |
| App / Cloud App Admin or App Owner | SSO gallery app + connector config (entra-app) | programmatic |
| App Admin / Cloud App Admin / Priv Role Admin / Global Admin | admin consent (attempt; escalate to manual if blocked) | programmatic |
| Workday Administrator | configure-workday-tenant | attestation |
| InfoSec/IT | firewall allowlisting (REST + SOAP; manual row) | attestation |

## Acceptance criteria

- The checklist renders every step with its role, skill, automatable flag, checkpoint, and
  live status; skills update only their own rows.
- Every non-manual row maps to a checkpoint that runs in isolation; manual rows are clearly
  marked and never auto-completed.
