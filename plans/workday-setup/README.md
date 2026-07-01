# Workday Setup — Primary Plan

Automate configuration of **Workday for the ESS Agent** by re-decomposing the
`/connect workday` monolith into atomic, role-scoped skills for the **simplified** Workday
integration, grounded in the official docs (authoritative):

- [Workday simplified setup](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/workday-simplified-setup)
- [Configure Workday for SSO with Microsoft Entra ID](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial)

This is the **primary plan** (the folder's `README`). The detailed work is broken into
focused **sub-plans** beside it in this folder, each reviewable and shippable on its own cadence.

## Sub-plans

### Foundation (no Workday dependency)

| Sub-plan | Scope | Depends on |
| --- | --- | --- |
| [`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md) | Add `--checkpoint <ID>` single-checkpoint invocation to flightcheck, via a **checkpoint registry + prerequisite hydration**. **Integration-agnostic.** | — |
| [`shared-building-blocks`](./shared-building-blocks.md) | Parameterized Entra-app helper (de-dups connector authorization across Workday + ServiceNow), role-gate (programmatic + attestation), connection-field helper, config schema, checklist updater. | — |

### The 6 atomic skills (numbered in dependency order — the **Depends on** column is authoritative)

| Sub-plan | Role | Depends on |
| --- | --- | --- |
| [`skill-1-provision-power-platform-environment`](./skill-1-provision-power-platform-environment.md) | Power Platform Admin | foundation |
| [`skill-2-install-ess`](./skill-2-install-ess.md) | Environment Maker | skill-1 |
| [`skill-3-provision-workday-entra-app`](./skill-3-provision-workday-entra-app.md) | App / Cloud App Admin (consent-capable role) | foundation |
| [`skill-4-configure-workday-tenant`](./skill-4-configure-workday-tenant.md) | Workday Administrator | skill-3 |
| [`skill-5-install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md) | Environment Maker | skill-2, skill-4 (+ firewall gate) |
| [`skill-6-create-new-topic`](./skill-6-create-new-topic.md) | Environment Maker + Workday SME | skill-5 |

> **Cross-skill data & manual gates:** skill-4 captures the **SOAP + REST base URLs** and the
> **OAuth client identity** that skill-5 consumes. skill-5's *functional* verification is gated
> on **firewall allowlisting (REST + SOAP)** — without it, connection auth fails for network
> reasons indistinguishable from a config error, so skill-5 must report "unreachable" vs
> "misconfigured" distinctly.

### Orchestration & verification

| Sub-plan | Scope | Depends on |
| --- | --- | --- |
| [`master-checklist`](./master-checklist.md) | One trackable checklist spanning all 6 skills + manual rows; defines the new Workday flightcheck checkpoints + role-gating. | foundation |
| [`command-wiring`](./command-wiring.md) | Retire the `connect/workday` monolith; route `/connect workday` to the new orchestrator. | skills 1–6 |
| [`evals`](./evals.md) | Per-skill eval sets (OOTB baseline + auto-gen per new topic). | skill-5, skill-6 |

## Confirmed decisions (apply across all sub-plans)

| # | Decision | Choice |
| --- | --- | --- |
| 1 | Relationship to existing `connect/workday` | **Full re-decomposition** — 6 skills replace the monolith |
| 2 | Install-path scope | **Simplified only** — drop legacy |
| 3 | Net-new skills | **Build all fully**, incl. provision-env + install-ess |
| 4 | Entra app design | **Per official docs** — SSO gallery app first, then connector config; no generic `c26b24aa` reuse |
| 5 | Workday-tenant tasks | **New 6th skill `configure-workday-tenant`** (Workday Admin) |
| 6 | Evals coverage | **Per-skill** — OOTB baseline + auto-gen per new topic |
| 7 | Atomic flightcheck | **Single-checkpoint invocation** (`--checkpoint <ID>`); keep existing scopes |
| 8 | Checklist structure | **One master checklist**, each row linked to a flightcheck checkpoint |
| 9 | Plan location | **`plans/workday-setup/` only** — this `README` (primary) + the sub-plans beside it; session `plan.md` is a pointer |

## Official simplified-setup sequence → skill mapping

| Official step | Role | Skill |
| --- | --- | --- |
| Deploy env + Dataverse + Copilot Studio capacity | Power Platform Admin | **1. provision-power-platform-environment** |
| Deploy base ESS agent (AppSource) | Environment Maker | **2. install-ess** |
| SSO gallery app (SAML, cert) — **Graph-first + portal fallback** | App / Cloud App Admin | **3. provision-workday-entra-app** (prereq) |
| Workday connector in Entra (scope, authorize `4e4707ca`, Graph, consent, enterprise-app assignment) | App / Cloud App Admin (consent-capable) | **3. provision-workday-entra-app** (core) |
| Configure Workday tenant (X.509, security, auth policies, API client) | Workday Administrator | **4. configure-workday-tenant** |
| Install extension pack + connections + flows | Environment Maker | **5. install-workday-extension-pack** |
| Customizations / new scenarios | Environment Maker + Workday SME | **6. create-new-topic** |
| Firewall/network allowlisting (**REST + SOAP**) | InfoSec/IT | *Manual row in master checklist; gates skill-5 functional check* |

## Recommended delivery order

1. **flightcheck-single-checkpoint** (unblocks atomic verification for every skill)
2. **shared-building-blocks** (foundation; parameterizes the connector for Workday + ServiceNow)
3. **master-checklist** (the spine the skills update + the new Workday checkpoints)
4. **skills 1→6** (in dependency order)
5. **command-wiring** (retire monolith once the skills exist)
6. **evals** (after extension-pack + create-topic skills exist)

## Review hardening (applied — multi-model rubber-duck, rounds 1–2)

Folded in after critique by Claude Opus 4.8, GPT-5.5, and GPT-5.3-Codex (round 1) and a
round-2 re-review (Opus 4.8 + GPT-5.5) that pressure-tested the Graph-automation claim against
the repo source of truth:

- **Flightcheck needs a checkpoint registry + prerequisite hydration**, not naive per-check
  isolation — checks share state within category functions, and `cli.py` must stop requiring
  Dataverse for Entra-only checkpoints. *(highest-priority change)*
- **skill-5 reuses existing simplified-aware checkpoints** `WD-PKG-001` + `WD-CONN-012` +
  `WD-FLOW-*` (`checks/workday.py`'s `_check_flow_status` already emits one `WD-FLOW-{n}` per cloud flow —
  don't re-mint) and mints only `WD-CONN-AUTH-001`, `DV-CONN-001`, `WD-REST-001`, `WD-REST-002`,
  `WD-NET-001`;
  **never reuse legacy `WD-ENV-*`/`WD-WF-*`** (ISU/RaaS, skipped on simplified).
- **Admin consent is not GA-only** — any consent-capable role (App Admin / Cloud App Admin /
  Priv Role Admin / GA); attempt programmatically, escalate to manual if blocked.
- **The connector refactor is parameterization/de-dup, not a ServiceNow bug fix** —
  `c26b24aa` is the *correct* ServiceNow connector; only a misleading comment is wrong.
- **MCP stays out of verification** because standing up a Workday MCP connection needs the
  *same* setup as the ESS connection (circular), regardless of credentials.
- **skill-4 registers the API client before scoping auth policies**; it captures **both** SOAP
  and REST base URLs for skill-5.
- **Firewall (REST + SOAP) gates skill-5's functional check**; skill-5 reports
  network-unreachable vs config-invalid distinctly.
- **`MANUAL` ≠ done** — manual/attestation rows need explicit acknowledgement; the orchestrator
  won't advance on a flightcheck pass alone.
- **skill-3 is Graph-first with a mandatory per-step portal fallback.** This *extends* the
  existing mixed pattern in `connect/workday/step2.md` (which uses `az rest` Graph calls and
  already falls back to the portal for the not-authorized / portal-only cases) to a fallback on
  **every** step. \~9 of 11 Entra sub-steps are Graph-GA (instantiate, SAML mode,
  identifier/reply/sign-on/logout URLs, cert add **and activate** via
  `preferredTokenSigningKeyThumbprint`, scope, pre-authorize `4e4707ca`, Graph perms, admin
  consent, enterprise-app assignment). **Two are not one-liners and are explicit gates:** the
  **"Sign SAML response and assertion" signing option is portal-only** (no Graph property), and
  **NameID requires a `claimsMappingPolicy` create+assign** (GA but finicky, no repo precedent).
- **Reuse existing simplified-aware checkpoints; don't re-mint.** `WD-PKG-001`, `WD-CONN-012`,
  `WD-CONN-102`, `WD-CONN-010` already exist and are simplified-aware — skills 3/4/5 reuse them
  and mint new IDs only for genuinely-uncovered outputs (see [`master-checklist`](./master-checklist.md)).
- **`92b66` is the Dataverse connector, not a Workday ref** — simplified fingerprints a single
  `ff0df` Workday ref; verify `92b66` under a separate non-`WD` checkpoint.
- **skill-4 captures REST and SOAP base URLs from different sources** — REST from "View API
  Client", SOAP derived from the Workday **web host** pattern (per `step1.md`, user-prompt
  fallback) — and runs a single-tenant SAML IdP pre-gate (a second Entra tenant silently breaks
  the first federation).
- **`WD-NET-001` defaults to a MANUAL/InfoSec attestation** (allowlist evidence) because a local
  CLI probe only proves the dev machine — not the managed-connector outbound IPs — can reach
  Workday; an in-environment connector probe is an optional later enhancement, never a local
  probe presented as a gate.
- \*\*The flightcheck registry resolves prerequisites transitively, validates an acyclic DAG, and
  has a **setup-scoped** drift test\*\* (it asserts the registry covers every *setup-owned* emitted
  checkpoint ID; other integrations' checkpoints stay out of scope, validated via `--scope`).
- **Added:** enterprise-app user/group assignment gate (skill-3), live-agent rollback before
  the redirect push (skill-5), attestation-based gating for Workday/InfoSec roles, and evals
  derived from the installed topic inventory (not a hand list).

## Implementation conventions (read before executing any sub-plan)

- **Base directory:** every repo-relative path in these plans (e.g. `scripts/flightcheck/cli.py`,
  `src/skills/setup/workday/…`, `src/reference/ess-docs/…`) is relative to
  **`solutions/ess-maker-skills/`** unless it explicitly says "repo root". The `plans/` folder
  and `.gitignore` are the only repo-root paths referenced.
- **Skills are markdown playbooks**, not application code — each new skill is authored under
  `src/skills/setup/workday/` (the canonical home introduced by command-wiring) and invoked by
  the orchestrator (see
  [`command-wiring`](./command-wiring.md)); the only Python touched is `scripts/flightcheck/`
  and the shared helpers in [`shared-building-blocks`](./shared-building-blocks.md).
- **Definition of done for a sub-plan** = its own *Acceptance criteria* section is fully met and
  every checkpoint it owns is registered in [`master-checklist`](./master-checklist.md) and runs
  in isolation via `--checkpoint <ID>`.

## Resolved judgment calls (no open questions)

These were the four items flagged during review; all are now decided in-plan:

1. **skill-4 task ordering** — register API client **before** scoping auth policies. \*Confirmed
   correct by both models\* (the policy must reference the OAuth client identity).
2. **User-context redirect push under simplified (skill-5)** — **keep it**, but first confirm
   it's still required (V2 REST `/workers/me`) and **skip if already present**; always create a
   rollback checkpoint before mutating the live agent.
3. **Workday Admin / InfoSec role gating** — **attestation + captured evidence** (no queryable
   directory), never a silent pass.
4. **Evals data-correctness** — OOTB integration tests are **shape checks by default**; true
   data-correctness requires a **sanitized golden test user** the operator supplies (see
   [`evals`](./evals.md)). Absent that fixture, the eval stays shape-only — not a blocker.

## Out of scope

- Legacy ISU / security-group / RaaS path in the new skills (existing legacy installs keep working via the old reference docs).
- New flightcheck *scopes* (single-checkpoint invocation only).

## Housekeeping

- The `plans/` folder is tracked via a repo-root `.gitignore` `!plans/` allowlist (committed).