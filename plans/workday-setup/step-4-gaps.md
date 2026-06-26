# Step 4 Gaps — Custom Topic & Template Configuration (Extensibility)

Gap analysis and resolution for **Step 4 (4.1–4.5)** of the simplified Workday setup. Part of
[Workday Setup](./README.md). Each gap is closed by a **two-part fix**: a **skill** performs the
configuration action, and a **flightcheck** verifies it held.

**Source plans:** [`master-checklist`](./master-checklist.md) (canonical checkpoint registry),
[`skill-4-configure-workday-tenant`](./skill-4-configure-workday-tenant.md),
[`skill-6-create-new-topic`](./skill-6-create-new-topic.md),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md),
[`evals`](./evals.md).

> **Ownership note (clean, single skill).** The gap source's "Step 4" is the official
> **extensibility / new-topic** stage. In the new decomposition this maps **entirely to
> [`skill-6 create-new-topic`](./skill-6-create-new-topic.md)** (Environment Maker + Workday SME for
> tenant IDs/permissions) — master-checklist rows **S6.1–S6.2**. skill-6 is a Workday-specialized
> refactor of the existing `src/skills/topics/create` skill (Template Config + Shared Flow pattern —
> reuse, not reinvention).

> **Where Step 4 lands.** The Power-Platform/Dataverse half is automatable (template-config rows,
> topic structure, scenario catalog), but the two **Workday-tenant-facing** concerns —
> **tenant reference-ID validity** (4.4) and **per-scenario write permission** (4.5) — have **no
> simplified Workday API** to probe, so they degrade to **runtime test + SME loop-back**.

---

## Step 4.1 — Source the XML Template Configuration

**The gap**
- *Skill side (COVERED):* `topics/create` reads OOTB Workday samples; `workday-extensibility.md`
  covers the open-source-sample and Copilot-generated-XML paths, with an explicit **expert-review
  warning** for generated XML.
- *Flightcheck side (PARTIAL):* **no XML-schema validation** of template configs; `WD-WF-CAT-001`
  flags custom scenarios as **Manual**.

**Skill (the fix)**
- **skill-6 `create-new-topic`** — Workday-specialized refactor of `topics/create` using the
  **Template Config + Shared Flow** pattern. Sources the template config (OOTB sample or
  Copilot-generated starting point) and carries forward the **expert-review warning**: AI-generated
  definitions are a starting point that an integration specialist must review against the tenant's
  data schema / custom fields.

**Flightcheck (the proof)**
- **`WD-WF-CAT-001`** (reuse) — cross-checks topic scenario/flow references against the **live
  Dataverse template-config catalog** (`msdyn_employeeselfservicetemplateconfigs`) and flags
  **unknown / custom** scenarios as **MANUAL**.

**Status:** skill covered; flightcheck **PARTIAL — not fully closed**. `WD-WF-CAT-001` validates the
scenario against the catalog, but **no automated XML-schema validator** is added. The "Copilot
generates XML with syntax / schema errors" alternative is handled by the skill's **expert-review
warning** plus the **diagnostics scan in 4.3** (author-time), **not** by a flightcheck schema check.
*(See Open items #1.)*

---

## Step 4.2 — Create the Template Configuration in Copilot Studio

**The gap**
- *Skill side (COVERED):* `topics/create` automates Dataverse creation into
  `msdyn_employeeselfservicetemplateconfigs`, with a **Maker-portal fallback**; **ScenarioName
  wiring** handles the unique-name mismatch risk.
- *Flightcheck side (COVERED / PARTIAL):* `WD-WF-CAT-001` cross-checks topic references against the
  live Dataverse catalog.

**Skill (the fix)**
- **skill-6** automates the Dataverse template-config row creation (Maker-portal fallback) and wires
  **ScenarioName** so the topic's reference matches the saved config exactly (the unique-name guard).

**Flightcheck (the proof)**
- **`TOPIC-INTEGRATION-*`** (new family, per-topic) — verifies the topic's `scenarioName` / `flowId`
  **resolves** to a template-config row in Dataverse and that tenant reference IDs are populated
  (the precise per-topic integration check; builds on the `WD-SEC-003` / template-config resolution
  logic).
- **`WD-WF-CAT-001`** (reuse) — catalog cross-check (catches scenarios that don't resolve).

**Status:** **covered both sides.** The "template saves but the later topic can't find it
(unique-name mismatch)" alternative is closed by **ScenarioName wiring** (skill) verified by
**`TOPIC-INTEGRATION-*`** (the scenarioName actually resolves to a row).

---

## Step 4.3 — Create the Topic via Code Editor

**The gap**
- *Skill side (COVERED / better than manual):* the skill generates YAML in VS Code, **scans
  diagnostics, dry-runs, and pushes**, catching undefined variables / missing references via the
  scan + cleanup.
- *Flightcheck side (PARTIAL):* `local_files.py` validates topic structure.

**Skill (the fix)**
- **skill-6** generates the topic YAML and runs the existing `topics/create` **scan → dry-run →
  push** pipeline. The diagnostics scan catches **"undefined variables" / "missing references"** at
  author time (before push), then cleans up.

**Flightcheck (the proof)**
- **`TOPIC-TRIGGER-*`** (new family, per-topic) — the new topic exists and its **trigger phrases /
  recognition** are wired (builds on the existing required-topic logic, `TOPIC-011`).
- **`local_files.py`** (reuse) — validates topic file structure.

**Status:** **covered both sides.** The "Copilot Studio throws undefined-variables / missing-
references on save" alternative is caught by the **author-time diagnostics scan** (which routes the
user to the Variables tab); `TOPIC-TRIGGER-*` + `local_files.py` verify the result post-create.

---

## Step 4.4 — Customize the UI and Workday Identifiers

**The gap**
- *Skill side (PARTIAL / GAP):* `workday-extensibility.md` documents replacing `Time_Off_Type_Id`
  by exporting Workday Time Off Types, **but** `topics/create` does **not** discover tenant-specific
  reference IDs via Workday MCP or inject them into topic choice nodes.
- *Flightcheck side (GAP):* **nothing validates that IDs hard-coded in a topic actually exist in the
  tenant.**

**Skill (the fix)**
- **skill-6** **wires tenant-specific reference IDs** into the topic (acceptance criterion: *"New
  topic + template config created and wired with tenant reference IDs"*). When a tenant-ID gap is
  detected, the skill surfaces the **Workday SME / `configure-workday-tenant` loop-back** rather than
  failing silently, and carries the guidance to **export the Workday reference-data report** (e.g.
  Time Off Types) for the alphanumeric IDs.

**Flightcheck (the proof)**
- **`TOPIC-INTEGRATION-*`** (new family) — verifies tenant reference IDs are **populated / wired**
  in the topic's integration nodes.

**Status:** skill **PARTIAL → addressed** by ID wiring + the Workday-SME loop-back — **but
auto-discovery via Workday MCP and injection into choice nodes is an open design question** the plan
does not commit to (it wires + loops back, it does not promise MCP discovery). Flightcheck:
`TOPIC-INTEGRATION-*` confirms IDs are **present/wired**, but **cannot confirm they are correct in
the Workday tenant** (no simplified Workday reference-data API) — a **wrong-but-present ID surfaces
only at the 4.5 runtime test.** The "doesn't know where to find the IDs" alternative is handled by
the export-report guidance + SME loop-back. *(See Open items #2.)*

---

## Step 4.5 — Configure Workday Permissions & Execute Final Test

**The gap**
- *Skill side (DOCUMENTED-MANUAL):* `workday-extensibility.md` documents granting **business-process
  domain security** to the API client; Unauthorized errors are routed to the Workday admin.
- *Flightcheck side (GAP, debug):* `WD-SEC-003` probes **only Personal Data write** and is **manual
  on simplified**. **No proactive per-scenario permission probe** exists for arbitrary new **write**
  business processes (e.g. *Enter Time Off*).

**Skill (the fix)**
- **skill-6** documents granting the **business-process domain security** to the API client for the
  specific process being automated, then runs the **final test** in the Copilot Studio test pane.
  A new scenario that needs **additional API-client functional areas** triggers an explicit
  **loop-back to [`skill-4`](./skill-4-configure-workday-tenant.md) (Register API Client)** —
  missing scopes produce a clear loop-back, not a silent failure. Unauthorized → Workday
  Security/Integration admin.

**Flightcheck (the proof)**
- **`WD-SEC-003`** (reuse, **MANUAL** on simplified) — Workday **Personal Data** domain
  write-permission probe (the only existing write probe).
- **`TOPIC-INTEGRATION-*`** (new) — confirms the action **wiring resolves**, not runtime permission.

**Status:** skill documents the manual permission grant + loop-back; flightcheck **GAP — not fully
closed**. `WD-SEC-003` covers only **Personal Data**; **arbitrary new write business processes**
(*Enter Time Off*) have **no proactive per-scenario probe** on simplified (no Workday security API).
The "card submits but returns Unauthorized / Action Failed" alternative degrades to the **manual
final test** + routing to the Workday Security admin / skill-4 scope loop-back. *(See Open items
#3.)*

---

## Summary

| Step | Gap type | Skill fix (action) | Skill | Flightcheck (proof) | FC type |
|------|----------|--------------------|-------|---------------------|---------|
| 4.1 | Covered / Partial | skill-6 sources template config (+ expert-review warning) | skill-6 | `WD-WF-CAT-001` (reuse) | **manual** (catalog) |
| 4.2 | Covered / Covered | skill-6 creates Dataverse template-config; ScenarioName wiring | skill-6 | `TOPIC-INTEGRATION-*` (+ reuse `WD-WF-CAT-001`) | **automated** |
| 4.3 | Covered / Partial | skill-6 generates YAML; scan → dry-run → push | skill-6 | `TOPIC-TRIGGER-*` (+ reuse `local_files.py`) | **automated** |
| 4.4 | Partial / Gap | skill-6 wires tenant IDs + Workday-SME loop-back | skill-6 | `TOPIC-INTEGRATION-*` (populated, not tenant-valid) | **automated** (partial) |
| 4.5 | Doc-manual / Gap | skill-6 documents domain security grant + skill-4 scope loop-back | skill-6 | `WD-SEC-003` (reuse, Personal-Data only) | **manual** (per-scenario gap) |

### Skills referenced

| Skill | Role | Type for Step 4 |
|-------|------|-----------------|
| skill-6 `create-new-topic` | Environment Maker (+ Workday SME) | **owns all of Step 4** (refactor of `topics/create`) |
| skill-4 `configure-workday-tenant` | Workday Administrator | loop-back target — adds API-client functional areas / scopes for new scenarios (4.5) |

### Checkpoints referenced

| Checkpoint | New / Reuse | Verification |
|------------|-------------|--------------|
| `WD-WF-CAT-001` | reuse | **manual** — scenario refs cross-checked vs. live Dataverse catalog; custom flagged MANUAL |
| `TOPIC-TRIGGER-*` | new (per-topic) | **automated** — topic exists + trigger phrases wired |
| `TOPIC-INTEGRATION-*` | new (per-topic) | **automated** — scenarioName/flowId resolves + tenant ref IDs populated |
| `WD-SEC-003` | reuse | **manual** (simplified) — Personal Data domain write probe only |
| `local_files.py` (`TOPIC-011`) | reuse | automated — topic file structure |

> **Automated vs manual for Step 4:** automated — `TOPIC-TRIGGER-*`, `TOPIC-INTEGRATION-*`, and the
> reused `local_files.py` structure check. Manual — `WD-WF-CAT-001` (custom-scenario checklist) and
> `WD-SEC-003` (Personal-Data-only, manual on simplified). The genuinely Workday-tenant-facing
> validations (tenant-ID validity, per-scenario write permission) **have no API** and degrade to the
> **runtime final test** + **Workday-SME / skill-4 loop-back**.

## Open items & reduced coverage (Step 4)

1. **No automated XML-schema validation of template configs (4.1).** `WD-WF-CAT-001` checks the
   scenario against the Dataverse catalog, not the **XML schema**. AI-generated XML relies on the
   skill's **expert-review warning** + the **4.3 diagnostics scan** — a malformed schema is not
   caught by a dedicated flightcheck. *(Optional later: a template-config XML-schema validator.)*
2. **Tenant reference-ID validity is not auto-verifiable on simplified (4.4).** `TOPIC-INTEGRATION-*`
   confirms IDs are **populated / wired**, not that they are **correct in the Workday tenant** (no
   simplified Workday reference-data API). A **wrong-but-present ID** surfaces only at the **4.5
   runtime test**. Whether skill-6 should **auto-discover IDs via Workday MCP** and inject them into
   choice nodes is an **open design question** — today it wires + loops back to the Workday SME.
3. **No proactive per-scenario write-permission probe on simplified (4.5).** `WD-SEC-003` covers
   only **Personal Data** write; arbitrary new **write** business processes (*Enter Time Off*) have
   no automated probe (no Workday security API on simplified). Replaced by the **manual final test**
   + **skill-4 scope loop-back** + routing to the Workday Security admin. *(Optional later:
   generalize `WD-SEC-003` into a per-scenario domain-security probe.)*
4. **New-scenario scope loop-back (4.4 / 4.5).** A new scenario may require **additional API-client
   functional areas**; skill-6 **loops back to skill-4 (Register API Client)** so a missing scope is
   surfaced explicitly rather than failing silently at runtime — keep this loop-back wired when
   implementing.
