# Flightcheck Implementation — New Checkpoints (Workday Setup)

Implementation spec for **every flightcheck we are minting** for the simplified Workday setup —
**15 checkpoints (13 fixed IDs + 2 dynamic families)** plus the `--checkpoint` registry infra.
Grounded in the per-skill sub-plans, [`master-checklist`](./master-checklist.md), the authoring
conventions in `scripts/flightcheck/AGENTS.md`, and the existing check code.

> **`WD-ASSIGN-001` is deliberately excluded** — it is **not** new. It is already shipped as
> **`AUTH-005`** (`_check_workday_app_user_assignment`, `checks/authentication.py:198-500`). Reuse
> it; keep its emitted ID `AUTH-005` (don't alias to `WD-ASSIGN-001`). The master-checklist "mint"
> column for skill-3 should be corrected to **reuse** for this row.

**Source plans:** [`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md),
[`shared-building-blocks`](./shared-building-blocks.md),
[`skill-1`](./skill-1-provision-power-platform-environment.md),
[`skill-2`](./skill-2-install-ess.md),
[`skill-3`](./skill-3-provision-workday-entra-app.md),
[`skill-4`](./skill-4-configure-workday-tenant.md),
[`skill-5`](./skill-5-install-workday-extension-pack.md),
[`skill-6`](./skill-6-create-new-topic.md). Gap traceability:
[`step-1-gaps`](./step-1-gaps.md) · [`step-2-gaps`](./step-2-gaps.md) ·
[`step-3-gaps`](./step-3-gaps.md) · [`step-4-gaps`](./step-4-gaps.md).

## Legend

- **Clients:** `graph` (Microsoft Graph), `dataverse`, `pp_admin` (BAP Admin API), `none`.
- **Status model** — the runner's seven statuses (`AGENTS.md` §2): `PASSED`, `FAILED`, `WARNING`,
  `SKIPPED`, `NOT_CONFIGURED`, `MANUAL`, `ERROR`. **`MANUAL` does not fail readiness** — it carries
  the observed value verbatim in `result` and tells the operator which external screen to compare
  against; a `MANUAL`/attest row is **never** auto-completed.
- **Roles:** `ENTRA_ADMIN`, `WORKDAY_ADMIN`, `ESS_MAKER`, `POWER_PLATFORM_ADMIN`.
- **prog→manual** = attempt programmatically (Graph), escalate to a manual portal row if the
  identity lacks rights or the API route is brittle.
- Every new ID must be added to its category function, registered in `registry.py`, and documented
  in `src/reference/ess-docs/flightcheck/validation-matrix.md`.

---

## skill-1 — `provision-power-platform-environment`

### 1. `ENV-CAPACITY-001` — Copilot Studio capacity available
- **Closes:** Gap 1.1 (capacity prerequisite).
- **Module · owner:** `checks/environment.py` · `run_environment_checks`.
- **Clients:** `pp_admin` / licensing API. **Prereqs:** `ENV-001` (environment exists).
- **Implementation:** Query the environment's Copilot Studio / message-capacity entitlement; assert
  a non-zero allocation is present. If the capacity API isn't reachable, degrade to an attestation
  (operator confirms capacity).
- **Status:** `PASSED` if capacity present; `FAILED` / `NOT_CONFIGURED` if absent; `MANUAL` / attest
  fallback when the API can't be read. **Role:** `POWER_PLATFORM_ADMIN`.

## skill-2 — `install-ess`

### 2. `ESS-SOLN-001` — base ESS solution installed
- **Closes:** Gap 1.1 ("agent verifies the ESS solution exists").
- **Module · owner:** `checks/environment.py` · `run_environment_checks`.
- **Clients:** `dataverse`. **Prereqs:** `ENV-002` (Dataverse provisioned).
- **Implementation:** Dataverse query for the managed solution `msdyn_copilotforemployeeselfservice*`;
  assert present (and, ideally, version readable). This is the explicit gate that the implicit
  `.local/config.json` check replaces.
- **Status:** `PASSED` if found; `FAILED` if missing (blocks the extension pack). **Role:** `ESS_MAKER`.

---

## skill-3 — `provision-workday-entra-app`  *(Graph-first; consent-capable role)*

### 3. `WD-ENTRA-SCOPE-001` — scope exposed + connector pre-authorized + Graph perms  *(composite)*
- **Closes:** Gaps 1.3, 1.4, 1.5-perms.
- **Module · owner:** `checks/workday.py` · `run_workday_checks`.
- **Clients:** `graph` only (declares **no** Dataverse — relies on the registry to run it
  Entra-only). **Prereqs:** none.
- **Implementation:** Read the app registration via Graph and assert three things: (a)
  `api.oauth2PermissionScopes` contains `user_impersonation` (+ Application ID URI set); (b)
  `api.preAuthorizedApplications` contains `4e4707ca-5f53-46a6-a819-f7765446e6ff` mapped to
  `user_impersonation`; (c) `requiredResourceAccess` includes Graph `openid`, `profile`, `User.Read`.
- **Status:** `PASSED` / `FAILED`, status-bucketed by which of the three is missing.
  **Role:** `ENTRA_ADMIN`.
- **Note:** bundles 3 concerns — in tension with "one check, one concern" (`AGENTS.md` §4). Split
  into `-SCOPE` / `-PREAUTH` / `-PERMS` only if they must fail independently in the report.

### 4. `WD-ENTRA-CONSENT-001` — admin consent granted
- **Closes:** Gap 1.5 (admin consent).
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `graph`.
  **Prereqs:** `WD-ENTRA-SCOPE-001` (perms must exist before consent).
- **Implementation:** Graph query for the `oauth2PermissionGrant` covering the three delegated
  scopes; assert a tenant-wide grant exists ("green checkmarks").
- **Status:** `PASSED` if granted; `FAILED` if not; **prog→manual** — if the running identity lacks
  a consent-capable role, emit a named-role remediation and report `NOT_CONFIGURED` / `MANUAL`
  (don't hard-fail). **Role:** `ENTRA_ADMIN`.

### 5. `WD-ENTRA-NAMEID-001` — NameID claim mapping
- **Closes:** SSO hardening (beyond the pasted gaps; SAML NameID).
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `graph`.
  **Prereqs:** `WD-CONN-102` family / SSO-app instantiation.
- **Implementation:** Read the service principal's assigned `claimsMappingPolicy`; assert NameID
  maps to `user.mail` / UPN.
- **Status:** `PASSED` / `FAILED`; **prog→manual** — the `claimsMappingPolicy` route is brittle / has
  no in-repo precedent, so degrade to `MANUAL` (fetch the Entra side, operator confirms) if the
  policy can't be read reliably. **Role:** `ENTRA_ADMIN`.

### 6. `WD-ENTRA-SIGNOPT-001` — "Sign SAML response and assertion" option
- **Closes:** SSO hardening (beyond the pasted gaps; signature validation).
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `graph` (best-effort).
  **Prereqs:** SSO-app instantiation.
- **Implementation:** **Portal-only** — no GA Graph property (beta `samlSingleSignOnSettings`
  exposes only `relayState`). Report what's observable and direct the operator to the portal toggle.
  A Workday SP that validates signatures rejects the assertion if this is wrong, so it must never be
  silently skipped.
- **Status:** `MANUAL` / `NOT_CONFIGURED` (never `PASSED` from an unverifiable read).
  **Role:** `ENTRA_ADMIN`.

---

## skill-4 — `configure-workday-tenant`  *(attestation-heavy; no Workday admin API)*

### 7. `WD-TENANT-001` — tenant security / auth-policy config captured
- **Closes:** Gaps 2.2, 2.4 (SP-ID match, redirect URL, auth-policy scope, captured URLs).
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `none` (reads
  persisted config). **Prereqs:** none.
- **Implementation:** Confirm the observable artifacts skill-4 persisted: redirect URL set,
  **Service Provider ID == Entra Identifier / Entity ID**, auth policy scoped to the OAuth client,
  REST + SOAP base URLs captured. **Cannot** detect "pending changes not activated" (no Workday API)
  — that piece is an operator attestation.
- **Status:** `MANUAL` — carries the observed values verbatim in `result`, points the operator at
  Workday **Tenant Setup – Security**; **does not fail readiness**. **Role:** `WORKDAY_ADMIN`
  (role gate via the shared attestation helper).

### 8. `WD-API-CLIENT-001` — API client registered (functional areas + Workday Owned Scope)
- **Closes:** Gap 2.3.
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `none` (attest).
  **Prereqs:** none.
- **Implementation:** Confirm the API client exists and that Client ID / Token Endpoint / REST base
  URL were captured, and **Include Workday Owned Scope = Yes**. **Functional-area completeness is
  not auto-detectable on simplified** (legacy SOAP probes `WD-WF-001…017` are skipped) → the
  required areas (Core Payroll, Organizations and Roles, Staffing, Time Off and Leave) plus
  **Client Grant Type = SAML Bearer Grant** are enumerated for operator attestation.
- **Status:** `MANUAL` / attest. **Role:** `WORKDAY_ADMIN`.
- **Grant type:** **SAML Bearer Grant** — the ADK and the golden set are aligned, so the check
  asserts SAML Bearer Grant (no JWT path).

---

## skill-5 — `install-workday-extension-pack`

### 9. `WD-CONN-AUTH-001` — connection auth type = Entra ID Integrated
- **Closes:** Gap 3.2.
- **Module · owner:** `checks/workday.py` · `run_workday_checks` (uses `pp_admin`).
  **Clients:** `pp_admin`. **Prereqs:** `WD-PKG-001` (hydrates `_workday_connection_refs`).
- **Implementation:** Extend the `connections.py` helper pattern — locate the `ff0df` Workday
  connection, read its connection-parameter / auth metadata, and **assert the auth-type label =
  "Microsoft Entra ID Integrated"** (the generic helper only checks `Connected`, so this adds the
  label assertion that the gap said was missing).
- **Status:** `PASSED` if the label matches; `FAILED` if OAuth2 / Basic.
  **Role:** `ESS_MAKER` / `POWER_PLATFORM_ADMIN`.

### 10. `DV-CONN-001` — Dataverse connection bound  *(non-`WD` family)*
- **Closes:** Gap 3.3 (Dataverse `92b66` is the Common Data Service connector, **not** a Workday ref).
- **Module · owner:** `checks/connections.py` ·
  `check_connector_connections(connector_keyword=<dataverse/commondataservice>,
  checkpoint_prefix="DV-CONN", category=...)`. **Clients:** `pp_admin`. **Prereqs:** none.
- **Implementation:** Reuse the generic helper directly; assert the `92b66` connection is bound and
  `Connected` with its own account. Emits `DV-CONN-001` summary (+ `DV-CONN-002+` detail via the
  family). Explicitly outside the `WD-CONN` Workday-ref family.
- **Status:** `PASSED` / `FAILED` from `get_connection_status`.
  **Role:** `ESS_MAKER` / `POWER_PLATFORM_ADMIN`.

### 11. `WD-REST-001` — REST base URL present and trimmed to `/api`
- **Closes:** Gaps 2.4, 3.3 (the documented silent-failure gotcha).
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `pp_admin`
  (connection params). **Prereqs:** `WD-PKG-001`, `WD-CONN-012`.
- **Implementation:** Read the Workday connection's REST base URL parameter; assert it's present and
  **ends exactly at `/api`** (no trailing `/`, no `/v1/<tenant>`). Pure string / format validation.
- **Status:** `PASSED` if the shape is correct; `FAILED` if it retains `/v1` / tenant / a trailing
  slash. **Role:** `ESS_MAKER`.

### 12. `WD-REST-002` — user-context redirect pushed (V2, not legacy V1)
- **Closes:** Gap 3.4 (silent V1 drift; `TOPIC-001` only checks existence).
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `pp_admin` +
  `dataverse` (topic definition). **Prereqs:** `WD-PKG-001`, `TOPIC-001`.
- **Implementation:** Inspect the `[Admin] - User Context - Setup` topic's redirect target; assert it
  points at `WorkdaySystemGetUserContextV2` so REST resolves `/workers/me` (not the legacy ISU/RaaS
  V1 flow). **Distinct concern from `WD-REST-001`** → verified by its own `--checkpoint` so a failure
  is unambiguous.
- **Status:** `PASSED` if V2; `FAILED` if V1; `SKIPPED` if the redirect isn't required on this
  flavor. **Role:** `ESS_MAKER`.

### 13. `WD-NET-001` — Workday REST + SOAP reachability (firewall)
- **Closes:** Gaps 1.2, 3.5.
- **Module · owner:** `checks/workday.py` · `run_workday_checks`. **Clients:** `none` (attest
  default). **Prereqs:** none.
- **Implementation:** **Default = MANUAL / InfoSec attestation** tied to allowlist evidence (REST
  **and** SOAP), because a local CLI probe only proves the dev machine — not the managed-connector
  outbound IPs that InfoSec allowlists. **Optional later enhancement (only if scoped):** an
  in-environment connector probe that classifies **"network-unreachable (firewall)" vs
  "config-invalid"** — never a local probe presented as a gate.
- **Status:** `MANUAL` / attest. **Role:** InfoSec / IT — *may need a new `Role` enum value* (the
  current enum has no InfoSec role; flag for [`shared-building-blocks`](./shared-building-blocks.md)).

---

## skill-6 — `create-new-topic`  *(per-topic families)*

### 14. `TOPIC-TRIGGER-*` — new topic exists + trigger phrases wired
- **Closes:** Gap 4.3.
- **Module · owner:** `checks/local_files.py` (builds on the `REQUIRED_TOPICS` / `TOPIC-011`
  structure logic). **Clients:** `none` (local agent files on disk). **Prereqs:** none.
  **Family / prefix** registry entry — one `TOPIC-TRIGGER-{n}` per created topic.
- **Implementation:** For each newly created topic, assert the topic file exists and its
  `triggerQueries` / recognition are populated (routing works).
- **Status:** `PASSED` / `FAILED` per topic, status-bucketed (one result per distinct status).
  **Role:** `ESS_MAKER`.

### 15. `TOPIC-INTEGRATION-*` — Workday action wiring resolves + tenant IDs populated
- **Closes:** Gaps 4.2, 4.4, 4.5-wiring.
- **Module · owner:** `checks/workday.py` (reuses the dialog-ref + template-config resolution logic
  at `workday.py:3519/3677`). **Clients:** `dataverse`. **Prereqs:** the template-config catalog
  resolution (shared with `WD-WF-CAT-001`). **Family / prefix** entry — one per created topic.
- **Implementation:** For each topic, assert the `dialog:` / `scenarioName` / `flowId` reference
  **resolves** to a `msdyn_employeeselfservicetemplateconfigs` row and that tenant reference IDs are
  **populated** in the integration nodes. **Cannot** validate the IDs are *correct in the tenant*
  (no Workday reference-data API) — that is runtime-only (surfaces at the 4.5 test).
- **Status:** `PASSED` / `FAILED` (resolves / populated).
  **Role:** `ESS_MAKER` (+ Workday SME loop-back for tenant-ID gaps).

---

## Foundation infra (prerequisite for all of the above)

### `--checkpoint` registry — `registry.py` + `cli.py` / `runner.py`
- **What:** a static registry mapping each checkpoint ID → owning category function → required
  clients → config → prerequisite IDs; supports **family / prefix** entries (`WD-FLOW-*`,
  `WD-CONN-*`, `TOPIC-TRIGGER-*`, `TOPIC-INTEGRATION-*`) with **exact-match-first** resolution;
  resolves prereqs **transitively**; **hydrate-then-filter** execution.
- **CLI:** add `--checkpoint <ID>` and `--list-checkpoints`; initialize **only** the clients the
  target declares (Entra-only IDs run with **no Dataverse**); mutually exclusive with `--scope`.
- **Tests:** `tests/flightcheck/test_registry.py` (acyclic DAG + every prereq resolves) and
  `tests/flightcheck/test_registry_drift.py` (setup-owned-prefix allow-list). The drift allow-list
  has **no `AUTH` prefix**, so keep `AUTH-005` reachable via `--scope authentication` and **do not**
  alias it to `WD-ASSIGN-001`.

---

## Summary

| # | Checkpoint | Skill | Module · owner | Clients | Status model | Role | Closes |
|---|-----------|-------|----------------|---------|--------------|------|--------|
| 1 | `ENV-CAPACITY-001` | 1 | `environment.py` · `run_environment_checks` | pp_admin | auto → attest | POWER_PLATFORM_ADMIN | 1.1 |
| 2 | `ESS-SOLN-001` | 2 | `environment.py` · `run_environment_checks` | dataverse | automated | ESS_MAKER | 1.1 |
| 3 | `WD-ENTRA-SCOPE-001` *(composite)* | 3 | `workday.py` · `run_workday_checks` | graph | automated | ENTRA_ADMIN | 1.3/1.4/1.5 |
| 4 | `WD-ENTRA-CONSENT-001` | 3 | `workday.py` · `run_workday_checks` | graph | prog→manual | ENTRA_ADMIN | 1.5 |
| 5 | `WD-ENTRA-NAMEID-001` | 3 | `workday.py` · `run_workday_checks` | graph | prog→manual | ENTRA_ADMIN | SSO (beyond) |
| 6 | `WD-ENTRA-SIGNOPT-001` | 3 | `workday.py` · `run_workday_checks` | graph | **manual** | ENTRA_ADMIN | SSO (beyond) |
| 7 | `WD-TENANT-001` | 4 | `workday.py` · `run_workday_checks` | none | **manual/attest** | WORKDAY_ADMIN | 2.2/2.4 |
| 8 | `WD-API-CLIENT-001` | 4 | `workday.py` · `run_workday_checks` | none | **manual/attest** | WORKDAY_ADMIN | 2.3 |
| 9 | `WD-CONN-AUTH-001` | 5 | `workday.py` · `run_workday_checks` | pp_admin | automated | ESS_MAKER | 3.2 |
| 10 | `DV-CONN-001` *(non-`WD`)* | 5 | `connections.py` · `check_connector_connections` | pp_admin | automated | ESS_MAKER | 3.3 |
| 11 | `WD-REST-001` | 5 | `workday.py` · `run_workday_checks` | pp_admin | automated | ESS_MAKER | 2.4/3.3 |
| 12 | `WD-REST-002` | 5 | `workday.py` · `run_workday_checks` | pp_admin + dataverse | automated | ESS_MAKER | 3.4 |
| 13 | `WD-NET-001` | 5 | `workday.py` · `run_workday_checks` | none | **manual/attest** | InfoSec* | 1.2/3.5 |
| 14 | `TOPIC-TRIGGER-*` *(family)* | 6 | `local_files.py` | none | automated | ESS_MAKER | 4.3 |
| 15 | `TOPIC-INTEGRATION-*` *(family)* | 6 | `workday.py` (dialog-ref/template-config) | dataverse | automated | ESS_MAKER | 4.2/4.4/4.5 |

**Totals:** 13 fixed IDs + 2 dynamic families = **15 new checkpoints** (≈ **11 automated, 4
manual/attest**, with `WD-ENTRA-CONSENT-001` / `WD-ENTRA-NAMEID-001` as prog→manual hybrids), plus
the **`--checkpoint` registry** infra. `WD-ASSIGN-001` is **excluded** (reuse `AUTH-005`).

> **\*InfoSec role:** `WD-NET-001`'s owner role has no enum value today — add one in
> [`shared-building-blocks`](./shared-building-blocks.md) or document the attestation owner.

## Open decisions (resolve before coding)

1. **InfoSec `Role` enum** for `WD-NET-001` — add a value or document the attestation owner.
2. **`WD-ENTRA-SCOPE-001` composite vs split** — keep as one composite ID, or split into
   `-SCOPE` / `-PREAUTH` / `-PERMS` so 1.3 / 1.4 / 1.5-perms fail independently.
3. **Master-checklist correction** — relabel the `WD-ASSIGN-001` row from "mint" to **reuse**
   (`AUTH-005`) and register `AUTH-005` accordingly.
