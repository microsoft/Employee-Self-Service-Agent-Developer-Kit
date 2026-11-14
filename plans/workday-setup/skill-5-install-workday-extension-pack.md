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
  - `OAuthUser` (`new_sharedworkdaysoap_ff0df`) — the **Workday** connection.
  - Dataverse (`msviess_sharedcommondataserviceforapps_92b66`) — **not** a Workday ref; it's
    the Common Data Service connector and is verified under a separate (non-`WD`) checkpoint.
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

- **Reuse existing simplified-aware checkpoints — do NOT re-mint them.** `WD-PKG-001` already
  detects the **simplified** flavor (exact `ff0df` match), `WD-CONN-012` already checks
  simplified connection-reference **binding completeness**, and `WD-FLOW-*` is already emitted by
  `checks/workday.py`'s `_check_flow_status` (one `WD-FLOW-{n}` per cloud flow, **not** flavor-gated);
  reuse all three. Only mint the genuinely-new IDs below. Also **do not** reuse the legacy
  `WD-ENV-*` / `WD-WF-*` ISU/RaaS checks (skipped on simplified). Run each individually:
  - `WD-PKG-001` *(existing)* — extension pack present, package flavor = **simplified**.
  - `WD-CONN-012` *(existing)* — the **Workday** connection ref (`ff0df`) bound, own account.
    **Note:** the simplified Workday family fingerprints a **single** `ff0df` ref — `92b66` is
    the **Dataverse** connector, verified separately (see below), **not** a `WD-CONN` ref.
  - `WD-FLOW-*` *(existing — reuse `checks/workday.py`'s `_check_flow_status`)* — both cloud flows on
    (one emitted `WD-FLOW-{n}` per flow; do **not** add a second emitter).
  - `WD-CONN-AUTH-001` *(new)* — Workday connection auth type = **Entra ID Integrated**.
  - `DV-CONN-001` *(new, **non-`WD`-family**)* — Dataverse connection (`92b66`) bound, own account.
  - `WD-REST-001` *(new)* — REST base URL present and **ends at `/api`** (guard silent failure).
  - `WD-REST-002` *(new)* — **user-context redirect pushed** so REST resolves **`/workers/me`**;
    skip if already present; take the rollback checkpoint first. Distinct concern from
    `WD-REST-001` (base-URL shape) — verified by its own `--checkpoint` so a failure is
    unambiguous.
  - `WD-NET-001` *(new)* — Workday REST + SOAP reachability **from the Power Platform connector
    runtime**; on failure report **"network unreachable (firewall)"** distinctly from **"config
    invalid"**.
- **`WD-NET-001` default = MANUAL / InfoSec attestation (build this first).** A local HTTP probe
  only proves the developer's machine can reach Workday — not that the managed-connector outbound
  IPs (the ones InfoSec allowlists) can — so a local-only probe must **never** be presented as a
  gate. The deterministic, junior-safe v1 is an **attestation checkpoint** tied to InfoSec
  evidence (allowlist confirmation). **Optional enhancement (only if explicitly scoped later):** a
  minimal connector/cloud-flow test triggered **in the target environment** that classifies the
  connector response — treat this as a follow-up, not part of the initial skill.
- Updates master checklist rows.

## Acceptance criteria

- Extension pack present (simplified flavor, via existing `WD-PKG-001`); the Workday connection
  (`ff0df`, via existing `WD-CONN-012`) and the Dataverse connection (`92b66`, separate ID) are
  each bound with their own account; both flows on; user-context redirect pushed (with a
  rollback checkpoint) when required — each independently verifiable by a single checkpoint.
- REST base URL stored trimmed to `/api` (guard against the silent failure).
- `WD-NET-001` reflects **Power-Platform-runtime** reachability (or is a MANUAL/InfoSec
  attestation), distinguishing network-unreachable (firewall) from config-invalid.
