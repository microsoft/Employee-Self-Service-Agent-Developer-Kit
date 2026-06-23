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

### The 6 atomic skills (build in order 1→6)

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
| SSO gallery app (SAML, cert) — **fully Graph-automated** | App / Cloud App Admin | **3. provision-workday-entra-app** (prereq) |
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

## Review hardening (applied — multi-model rubber-duck)

Folded in after critique by Claude Opus 4.8, GPT-5.5, and GPT-5.3-Codex:

- **Flightcheck needs a checkpoint registry + prerequisite hydration**, not naive per-check
  isolation — checks share state within category functions, and `cli.py` must stop requiring
  Dataverse for Entra-only checkpoints. *(highest-priority change)*
- **skill-5 uses new simplified-only checkpoints** (`WD-PKG/CONN/CONN-AUTH/REST/FLOW/NET-*`);
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
- **skill-3 is fully Graph-automated end-to-end** (gallery app + SAML + cert + connector +
  Graph perms + admin consent + enterprise-app assignment) — no Entra portal step; the only
  escalation is admin consent when the caller lacks a consent-capable role.
- **Added:** enterprise-app user/group assignment gate (skill-3), live-agent rollback before
  the redirect push (skill-5), attestation-based gating for Workday/InfoSec roles, and evals
  derived from the installed topic inventory (not a hand list).

## Out of scope

- Legacy ISU / security-group / RaaS path in the new skills (existing legacy installs keep working via the old reference docs).
- New flightcheck *scopes* (single-checkpoint invocation only).

## Housekeeping

- Pending uncommitted change: `.gitignore` (`!plans/` allowlist) + the `plans/` folder — commit alongside this work.