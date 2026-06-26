# Step 3 Gaps — Power Platform Install & Workday Connection

Gap analysis and resolution for **Step 3 (3.1–3.5)** of the simplified Workday setup. Part of
[Workday Setup](./README.md). Each gap is closed by a **two-part fix**: a **skill** performs the
configuration action, and a **flightcheck** verifies it held.

**Source plans:** [`master-checklist`](./master-checklist.md) (canonical checkpoint registry),
[`skill-4-configure-workday-tenant`](./skill-4-configure-workday-tenant.md),
[`skill-5-install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md),
[`skill-6-create-new-topic`](./skill-6-create-new-topic.md),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md).

> **Ownership note (clean, single skill).** The gap source's "Step 3" is the official **Phase-3
> install & connection** stage. In the new decomposition this maps **entirely to
> [`skill-5 install-workday-extension-pack`](./skill-5-install-workday-extension-pack.md)**
> (Environment Maker role) — master-checklist rows **S5.1–S5.8**. Unlike Step 2 (which moved to the
> net-new skill-4), Step 3 has no ownership shift; the gap doc already names
> `install-workday-extension-pack` as the skill.

> **Where Step 3 lands.** Most of Step 3 is **automated** (Power Platform / Dataverse are
> queryable): the only genuinely manual pieces are the in-product **Install click** (3.1) and the
> **network reachability** attestation (3.5). The one deliberate coverage *reduction* is the
> end-to-end **live-data smoke test** (3.5), which is legacy-only on simplified.

---

## Step 3.1 — Install the Workday Extension Pack

**The gap (COVERED / COVERED)**
- *Skill side (COVERED):* `step3.md` guides **Settings → Customize → Workday → Install**.
- *Flightcheck side (COVERED):* `WD-PKG-001` fingerprints the install flavor
  (none / partial / full / **simplified**) via `external_systems.py` detection; a base-ESS
  **missing or partial** install is caught.

**Skill (the fix)**
- **skill-5 `install-workday-extension-pack`, S5.1** — the in-product **Install/Update** click +
  connection sign-in. This is a **manual-gated** in-product action (no API to click Install), so the
  skill gates on the **Environment Maker** role (named error + stop otherwise).

**Flightcheck (the proof)**
- **`WD-PKG-001`** (reuse) — extension pack present, package flavor = **simplified** (exact `ff0df`
  match). Also the guard for the "can't find / install fails immediately" alternative: it relies on
  **core ESS routing**, so a missing base agent surfaces here (and via `ESS-SOLN-001` from Step 1).

**Status:** **fully covered, both sides** — no new work. The "extension pack can't be installed as a
standalone product" failure mode is exactly what `WD-PKG-001` (+ Step 1's `ESS-SOLN-001`) detect.

---

## Step 3.2 — Configure the Workday Connection Authentication Type

**The gap**
- *Skill side (COVERED):* `step3.md` explicitly specifies **Authentication type = Microsoft Entra
  ID Integrated**, mitigating OAuth2 / Basic-auth misselection.
- *Flightcheck side (PARTIAL):* `WD-CONN-012` and `WD-CONN-101` surface a wrong auth type as
  *unhealthy*, but **no checkpoint asserts the auth-type label itself**.

**Skill (the fix)**
- **skill-5 Configuration** — connection auth = **Microsoft Entra ID Integrated** (required). The
  skill firmly instructs that OAuth 2.0 / Basic Auth will break the SSO user-impersonation flow
  (the agent could not query data on behalf of the chatting employee).

**Flightcheck (the proof)**
- **`WD-CONN-AUTH-001`** (new, **automated**) — asserts the Workday connection **auth-type label =
  Entra ID Integrated** directly. **This is the precise piece the gap said was missing** (assert the
  label, don't just observe downstream unhealth).
- **`WD-CONN-012` / `WD-CONN-101`** (reuse) — binding completeness / token-grant health; these catch
  the *consequence* of a wrong auth type but not the label.

**Status:** skill covered; flightcheck **PARTIAL → closed** by the new `WD-CONN-AUTH-001`. The
"selects OAuth 2.0 / Basic because they made an OAuth client in Workday" alternative is caught at the
**label** before it manifests as a `WD-CONN-101` token failure.

> **Upstream ask (not in-skill):** the gap notes the Power Platform team should expose an **API to
> set the auth type** so configuration can be automated. Today it is operator-set in the portal;
> `WD-CONN-AUTH-001` *verifies* it. That platform API is an external dependency, not skill work.

---

## Step 3.3 — Populate Connection Parameters

**The gap**
- *Skill side (COVERED):* `step3.md` auto-populates **App ID URI, OAuth Token URL, Client ID, REST
  base URL, SOAP base URL** from derived config, avoiding trailing-slash and mixed-environment
  errors.
- *Flightcheck side (PARTIAL):* `WD-CONN-101` catches auth failure, **but not field-level URL
  format**.

**Skill (the fix)**
- **skill-5 Configuration** (via the **shared connection-field helper**) sets App ID URI, OAuth
  token URL + Client ID, SOAP base URL, and **REST base URL trimmed to `/api`**. The **SOAP + REST
  base URLs and the OAuth client come from skill-4's captured config** — skill-5 consumes them, it
  does **not** re-derive.

**Flightcheck (the proof)**
- **`WD-REST-001`** (new, **automated**) — REST base URL present and **ends at `/api`**
  (field-level format — **the missing piece**; guards the documented silent failure).
- **`WD-CONN-012`** (reuse) — Workday connection-ref (`ff0df`) binding completeness, own account.
- **`DV-CONN-001`** (new, **non-`WD`-family**) — the **Dataverse** connection (`92b66`) bound, own
  account. `92b66` is the Common Data Service connector, **not** a Workday ref — verified under its
  own (non-`WD`) ID.
- **`WD-CONN-101`** (reuse) — token / grant health (catches the trailing-slash `/api/` or
  mixed-environment URL as an *auth result*).

**Status:** skill covered; flightcheck **PARTIAL → closed** by `WD-REST-001` (field-level URL
format) + `DV-CONN-001` (Dataverse binding). The "trailing slash `/api/` or impl-vs-prod mixed URL"
alternative → `WD-REST-001` (format) plus `WD-CONN-101` (auth result).

---

## Step 3.4 — Switch the User-Context Topic to V2  *(simplified-connector specific)*

**The gap**
- *Skill side (COVERED / better than manual):* `step3.md` **auto-wires** the
  `[Admin] - User Context - Setup` redirect to **`WorkdaySystemGetUserContextV2`** on simplified
  installs and pushes the change.
- *Flightcheck side (GAP, debug):* `TOPIC-001` only checks that a **user-context topic exists**, not
  whether the redirect **targets V2 vs legacy V1** — **silent V1 drift remains unvalidated**.

**Skill (the fix)**
- **skill-5, S5.7** — **auto-push** the user-context topic redirect to V2, but **take a
  checkpoint/rollback first** (preserve the `step3.md` checkpoint-before-push pattern, since this
  mutates the live agent). First **confirm the redirect is still required under simplified** (V2 user
  context via REST `/workers/me`) and **skip the push** if it isn't needed.

**Flightcheck (the proof)**
- **`WD-REST-002`** (new, **automated**) — verifies the user-context redirect was pushed so REST
  resolves **`/workers/me`** (i.e. the **V2 path is active**, not legacy V1). **This is the precise
  V1/V2-drift gap.** It is a **distinct concern** from `WD-REST-001` (base-URL shape) and is verified
  by its **own `--checkpoint`** so a failure is unambiguous.
- **`TOPIC-001`** (reuse, `local_files.py`) — confirms the user-context topic exists at all (the
  existing, weaker check the gap flagged).

**Status:** skill covered (auto-wire + rollback checkpoint); flightcheck **GAP → closed** by
`WD-REST-002`, which validates **V2 targeting** rather than mere existence. The "agent fails to
recognize who they are / times out fetching data" alternative is exactly the **legacy V1 ISU/RaaS
path** `WD-REST-002` guards against.

---

## Step 3.5 — Activate Cloud Flows and Perform a Smoke Test

**The gap**
- *Skill side (COVERED):* `step3.md` verifies and guides flow enablement, then runs an E2E test.
- *Flightcheck side (PARTIAL):* `WD-FLOW-001/002` check cloud-flow **enabled state**; the **live-data
  smoke tests `WD-WF-001…017` are legacy-only**, so simplified lacks **end-to-end data-probe
  coverage**.

**Skill (the fix)**
- **skill-5** confirms both cloud flows are **On** (they often default to Off after install), then
  the operator runs a smoke prompt in the Copilot Studio test pane
  (*"Show me my time off balance"* / *"When is my next payday?"*). On failure the skill's guidance
  cross-checks **Step 2.2 activate-pending-policy** and the **Power Automate run history** for HTTP
  error codes.

**Flightcheck (the proof)**
- **`WD-FLOW-*`** (reuse — `checks/workday.py`'s `_check_flow_status`, one `WD-FLOW-{n}` per flow) —
  both cloud flows **on**. (Not flavor-gated; do **not** add a second emitter.)
- **`WD-NET-001`** (new, **MANUAL / attest**) — Workday **REST + SOAP** reachability from the
  **Power Platform connector runtime**; on failure reports **"network unreachable (firewall)"**
  distinctly from **"config invalid"** (so a firewall miss isn't misdiagnosed as a config error).

**Reduced coverage (deliberate):** there is **no automated end-to-end live-data smoke probe on
simplified**. The legacy live SOAP data probes `WD-WF-001…017` are **skipped** on simplified; the
smoke test is therefore a **manual operator test** in the Copilot Studio test pane (an attestation),
not an automated flightcheck.

**Status:** skill covered (flow enablement + manual smoke test); flightcheck **PARTIAL** — the
flow on/off state is automated (`WD-FLOW-*`), but the **live-data end-to-end probe is a deliberate
coverage reduction** on simplified. The "generic fallback / error when asked for Workday data"
alternative is triaged by the skill's own guidance (flows on? pending policy activated? Power
Automate run-history HTTP codes?).

---

## Summary

| Step | Gap type | Skill fix (action) | Skill | Flightcheck (proof) | FC type |
|------|----------|--------------------|-------|---------------------|---------|
| 3.1 | Covered / Covered | skill-5 in-product Install/Update click (role-gated) | skill-5 (S5.1) | `WD-PKG-001` (reuse) | **automated** (detect) |
| 3.2 | Covered / Partial | skill-5 sets auth = Entra ID Integrated | skill-5 | `WD-CONN-AUTH-001` (+ reuse `WD-CONN-012/101`) | **automated** (label) |
| 3.3 | Covered / Partial | skill-5 populates fields via helper; REST trimmed to `/api` | skill-5 | `WD-REST-001`, `DV-CONN-001` (+ reuse `WD-CONN-012/101`) | **automated** |
| 3.4 | Covered / Gap | skill-5 auto-wires user-context redirect → V2 (rollback first) | skill-5 (S5.7) | `WD-REST-002` (+ reuse `TOPIC-001`) | **automated** |
| 3.5 | Covered / Partial | skill-5 confirms flows on + manual smoke test | skill-5 | `WD-FLOW-*` (reuse) + `WD-NET-001` | **automated** flows / **manual** net + smoke |

### Skills referenced

| Skill | Role | Type for Step 3 |
|-------|------|-----------------|
| skill-5 `install-workday-extension-pack` | Environment Maker (+ InfoSec/IT for 3.5 net) | **owns all of Step 3** |
| skill-4 `configure-workday-tenant` | Workday Administrator | upstream — supplies captured REST/SOAP/OAuth config consumed in 3.3 |

### Checkpoints referenced

| Checkpoint | New / Reuse | Verification |
|------------|-------------|--------------|
| `WD-PKG-001` | reuse | **automated** — extension pack present, flavor = simplified |
| `WD-CONN-AUTH-001` | new | **automated** — auth-type label = Entra ID Integrated |
| `WD-REST-001` | new | **automated** — REST base URL present and trimmed to `/api` |
| `DV-CONN-001` | new (non-`WD`) | **automated** — Dataverse `92b66` bound, own account |
| `WD-REST-002` | new | **automated** — user-context redirect pushed → REST resolves `/workers/me` (V2 not V1) |
| `WD-FLOW-*` | reuse | **automated** — each cloud flow on (one `WD-FLOW-{n}` per flow) |
| `WD-NET-001` | new | **manual / attest** — REST + SOAP reachability (firewall vs config-invalid) |
| `WD-CONN-012` | reuse | automated — `ff0df` binding completeness |
| `WD-CONN-101` | reuse | automated — token / grant health |
| `TOPIC-001` | reuse | automated — user-context topic exists (`local_files.py`) |

> **Automated vs manual for Step 3:** automated — `WD-PKG-001`, `WD-CONN-AUTH-001`, `WD-REST-001`,
> `WD-REST-002`, `DV-CONN-001`, `WD-FLOW-*`, plus reused `WD-CONN-012/101` and `TOPIC-001`. Manual —
> the in-product **Install click** (3.1, no API) and **`WD-NET-001`** (3.5, InfoSec attestation).
> The **live-data smoke test** (3.5) is a manual operator test, not a flightcheck.

## Open items & reduced coverage (Step 3)

1. **End-to-end live-data smoke probe is not automated on simplified (3.5).** The legacy live SOAP
   data probes (`WD-WF-001…017`) that fetched a payslip / time-off balance are **skipped on
   simplified**. The smoke test becomes a **manual** test-pane prompt; a data-fetch failure surfaces
   only at manual test time, not as an automated flightcheck. *(Optional later enhancement: an
   in-environment connector / cloud-flow data probe — the same follow-up noted for `WD-NET-001`.)*
2. **`WD-NET-001` reachability is MANUAL / InfoSec attestation by default (3.5).** A local HTTP probe
   only proves the **developer's machine** can reach Workday, not the **managed-connector outbound
   IPs** that InfoSec allowlists. Same caveat as **Step 1.2** — see [`step-1-gaps`](./step-1-gaps.md).
3. **Confirm the V2 redirect is still required under simplified before pushing (3.4).** skill-5 must
   first verify the redirect is needed (V2 user context via REST `/workers/me`) and **skip the push**
   if not. The gap doc's own follow-up — *"look into why the V2 topic isn't showing up when the
   connection isn't working"* — remains an **open investigation**.
4. **Auth-type label retrievability (3.2).** `WD-CONN-AUTH-001` assumes the auth-type **label** is
   reliably readable from connection metadata; confirm this versus having to infer it from
   `WD-CONN-101` token-grant behavior. The upstream **Power Platform API** to *set* the auth type
   (so configuration itself can be automated) is an **external platform ask**, not skill work.
