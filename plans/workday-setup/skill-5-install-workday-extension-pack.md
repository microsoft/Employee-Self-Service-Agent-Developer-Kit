# Plan: Skill 5 — `install-workday-extension-pack`

**Role:** Environment Maker · Part of [Workday Setup](./README.md).
**Depends on:** [`skill-2-install-ess`](./skill-2-install-ess.md),
[`skill-4-configure-workday-tenant`](./skill-4-configure-workday-tenant.md). **Functional
verification is additionally gated on firewall allowlisting (REST + SOAP)** — see the manual
row in [`master-checklist`](./master-checklist.md).

## Purpose

Install the Workday extension pack onto the deployed ESS agent in Copilot Studio
(Settings → Customize → Workday → Install/Update), adding the Workday topics, cloud flows,
and connection references.

## Configuration

- **Connection auth = Microsoft Entra ID Integrated** (recommended).
- Fields (via the shared connection-field helper): **App ID URI**, Workday **OAuth token
  URL** + **Client ID**, **SOAP base URL**, and **REST base URL trimmed to `/api`**
  (documented silent-failure gotcha). **SOAP + REST base URLs and the OAuth client come from
  skill-4's captured config** — don't re-derive them here.
- **Two connections**, each with its own account:
  - `OAuthUser` (`new_sharedworkdaysoap_ff0df`)
  - Dataverse (`msviess_sharedcommondataserviceforapps_92b66`)
- Confirm both cloud flows are **on**; non-UPN identity resolution (usually no action).
- **Auto-push** the user-context topic redirect — but **create a checkpoint/rollback first**
  (preserve the existing `step3.md` checkpoint-before-push pattern), since this mutates the
  live agent. First **confirm the redirect is still required under simplified** (V2 user
  context via REST `/workers/me`); skip the push if it isn't needed.

## Phases

- **Manual (gated):** the in-product Install/Update click + connection sign-in.
- **Automatable:** post-install verification — 2 connection references, 2 flows on, topic
  redirect present.

## Permission gating

- Not an **Environment Maker** → named error + stop.

## Verification

- **Use simplified-only checkpoints — not the legacy `WD-ENV-*` / `WD-WF-*` ISU/RaaS checks,
  which are skipped on simplified installs.** Run individually:
  - `WD-PKG-*` — extension pack present, package flavor = simplified.
  - `WD-CONN-*` — exactly the two connection refs (`ff0df` + `92b66`) bound, each its own account.
  - `WD-CONN-AUTH-*` — connection auth type = **Entra ID Integrated**.
  - `WD-REST-*` — REST base URL present and **ends at `/api`** (guard the silent failure).
  - `WD-FLOW-*` — both cloud flows on.
  - `WD-NET-*` — Workday REST + SOAP endpoints reachable; on failure report **"network
    unreachable (firewall)"** distinctly from **"config invalid"** so the firewall gate is
    diagnosable.
- Updates master checklist rows.

## Acceptance criteria

- Extension pack present (simplified flavor); both connections created (own accounts); both
  flows on; user-context redirect pushed (with a rollback checkpoint) when required — each
  independently verifiable by a single checkpoint.
- REST base URL stored trimmed to `/api` (guard against the silent failure).
- Functional auth failures distinguish network-unreachable (firewall) from config-invalid.
