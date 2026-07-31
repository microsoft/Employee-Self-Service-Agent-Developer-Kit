# CUSTOMIZATION_DISCOVERY.md

# ESS NextGen Migration Toolkit — Customization Discovery & DA-Compatibility Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document specifies how the toolkit discovers a customer's *customizations*
> on top of the managed ESS base solution, and how the first Transformation step
> makes the agent DA-compatible. It is the architectural companion to the
> `RetrieveAgentConfigurationStep`, `RetrieveCustomizationsStep` (Input stage),
> and `ApplyDaCompatibilityStep` (Transformation stage) implementations.
>
> Field names marked **UNCONFIRMED** below are isolated as module-level
> constants and treated tolerantly (no crash on mismatch). They must be verified
> against a live environment (`./mtk.sh run --dev`) before writeback is trusted.

---

## 1. Why discovery is needed

The ESS Agent ships as a **managed** base solution. When a customer edits the
agent (renames it, edits instructions/starters, adds or changes a Topic), those
edits are stored as **unmanaged customization layers** that *override* the
managed base at runtime. A major-version update of the base solution does **not**
remove those overlays — so an old overlay can keep the effective record pinned to
CA-era values (`PreviewModels`, `default-*` template) even after the base has
moved to DA. The toolkit must therefore:

1. Find exactly which components the customer has customized (the overlays), and
2. Rewrite the agent's core config to DA-compatible values so the CA→DA
   transition is not blocked by a stale overlay.

The two concerns map to two Input steps + one Transformation step.

---

## 2. Solution resolution by vertical

The selected agent's `schemaname` suffix identifies the ESS vertical, which
resolves to the managed base solution's unique name
(`service/utils.py::resolve_ess_solution`, table in `service/constants.py`):

| Agent schemaname                          | Vertical | Base solution unique name             |
| ----------------------------------------- | -------- | ------------------------------------- |
| `msdyn_copilotforemployeeselfservicehr`   | HR       | `msdyn_CopilotForEmployeeSelfServiceHR` |
| `msdyn_copilotforemployeeselfserviceit`   | IT       | `msdyn_CopilotForEmployeeSelfServiceIT` |

An unresolvable schemaname is a hard error — discovery cannot proceed without a
base solution to diff against.

---

## 3. Discovery flow (`RetrieveCustomizationsStep`)

```text
resolve_ess_solution(agent.schemaname)          # -> base solution unique name
        ↓
solutions?$select=solutionid&$filter=uniquename eq '<base>'   # -> solutionid (GUID)
        ↓
call_function RetrieveDependenciesForUninstallWithMetadata(SolutionId=<guid>)
        ↓  DependencyMetadataCollection.DependencyMetadataInfoCollection[]
extract (dependentcomponentobjectid, dependentcomponententitylogicalname) pairs
        ↓  (skip empty GUID + entries missing either field; dedupe by object id)
per-component fetch msdyn_componentlayers      # one query per id, NOT a bulk OR
        ↓  context.component_layers : {componentId -> [layer, …]}
classify + filter + hydrate  → context.customizations : {componentId -> CustomizationComponent}
        ↓
context.customized_dependencies : the raw_dependencies infos for the kept components
```

### 3.1 Dependencies for uninstall

`RetrieveDependenciesForUninstallWithMetadata` takes a **`SolutionId`** (an
`Edm.Guid`, inlined **unquoted** in the URL), not the unique name — so the base
solution's unique name is first resolved to its `solutionid` via a `solutions`
query. (The documented `RetrieveDependenciesForUninstall` variant takes
`SolutionUniqueName`; the `WithMetadata` variant used here takes `SolutionId` and
returns richer per-component metadata.) `DataverseClient.call_function` inlines a
GUID-shaped value as an unquoted `Edm.Guid` literal and any other value as a
single-quoted string. Response shape (verified live):

```jsonc
{
  "DependencyMetadataCollection": {
    "DependencyMetadataInfoCollection": [
      { "dependentcomponentobjectid": "ec1a5183-…",
        "dependentcomponententitylogicalname": "botcomponent", … }
    ]
  }
}
```

The step collects unique
`(dependentcomponentobjectid, dependentcomponententitylogicalname)` pairs,
skipping the all-zero GUID `00000000-0000-0000-0000-000000000000` and any entry
missing either field. The entity logical name is **required** for the
component-layers query below.

### 3.2 Component layers (per-component, virtual table)

`msdyn_componentlayers` is a **virtual** table that resolves **one component at a
time**: the `$filter` must pair `msdyn_componentid eq '<id>'` with
`msdyn_solutioncomponentname eq '<entitylogicalname>'` (from the dependency's
`dependentcomponententitylogicalname`). Without the `solutioncomponentname` the
query returns empty, and OR-ing multiple `msdyn_componentid`s in one query
silently returns only a couple of rows — so the toolkit issues **one query per
component** (not a chunked-OR bulk fetch) and keys the results by component id
(`context.component_layers : {componentId -> [layer, …]}`). Each query selects all
fields (`select=None`) so the full `msdyn_componentjson` payload is available, and
is fully paginated via `query_all`. Reads are sequential; `DataverseClient` retries
each GET on 429 honoring `Retry-After`.

---

## 4. Classification, filtering & hydration

`msdyn_overwritetime` is **not** a reliable signal — a net-new unmanaged topic
reads the same `1900-01-01T00:00:00Z` value as an untouched managed base. The
classifier instead keys off the **solution each layer belongs to**
(`msdyn_solutionname`), then the component's **sub-type** and **schemaname**.

### 4.1 Customized? (per component, keyed by `msdyn_componentid`)

| Case          | Layers                                                   | Verdict |
| ------------- | -------------------------------------------------------- | ------- |
| Customized OOB| more than one layer (managed base + an overlay)          | **keep** |
| Net-new       | a single layer in a **non-OOB** solution (e.g. `Active`) | **keep** |
| Untouched OOB | a single layer in an OOB ESS managed solution            | **drop** |

Rule: keep if `len(layers) > 1`, **or** a lone layer whose `msdyn_solutionname` is
**not** in `OOB_ESS_SOLUTIONS` (`service/constants.py` — the base HR/IT solutions
plus the 11 vertical extension packs, e.g. `msdyn_EssHRServiceNowHRSD`). Every
unmanaged customer change lands in the `Active` (or a custom unmanaged) solution,
so a lone OOB-solution layer is the untouched base.

### 4.2 Migratable? (sub-type + owning agent)

Kept components are then narrowed to the ones the toolkit migrates today. The
component's attributes are parsed **once** from `msdyn_componentjson` (a JSON
string with an `Attributes` list — the `componenttype` value is `{"Value": <int>}`,
while `schemaname` / `name` / `data` are plain strings):

- **componenttype** must be in `ALLOWED_BOT_COMPONENT_TYPES` (`{9}` — Topic V2 for
  now; the full option-set catalog is `BOT_COMPONENT_TYPE_LABELS`). Other types
  (Test Case = 19, Knowledge Source = 16, …) are dropped.
- **schemaname** must contain an ESS HR/IT agent prefix (`ESS_AGENT_SCHEMANAMES`,
  case-insensitive partial match), so components owned by other agents (e.g. the
  shared `…core` agent) are dropped.

### 4.3 Hydration

Each kept component is hydrated into a `CustomizationComponent`
(`modules/transformation/models/customization_component.py`) — top-level
`component_id`, `schemaname`, `name`, `component_type`, `component_type_label`
(e.g. "Topic (V2)"), `data` (the topic YAML), plus its raw `layers` — so the
Transformation/Output modules consume the fields directly without re-parsing
`msdyn_componentjson`.

- `context.component_layers` — `{componentId -> [layer, …]}`, every dependent
  component's raw layers.
- `context.customizations` — `{componentId -> CustomizationComponent}`, the kept
  (customized + migratable) subset, hydrated.
- `context.customized_dependencies` — the `raw_dependencies` infos whose
  `dependentcomponentobjectid` is a kept component.

### 4.4 Preferred-solution scoping (ALM path)

When the customer declares a **preferred solution**
(`context.preferred_solution`, an unmanaged solution they imported and marked
preferred — its topics are customizations layered on the managed ESS base),
discovery is narrowed to the components that *belong to that solution*, so
transformations and writeback touch only that solution's customizations.

Crucially, this membership is **not** read off the component layers: every
unmanaged solution shares the single `Active` layer, so `msdyn_solutionname` reads
`Active` regardless of which unmanaged solution a change was authored in. Instead
`RetrieveCustomizationsStep` resolves the preferred solution's `solutionid` (from
its unique name) and reads its **`solutioncomponents`** (one row per contained
component, filtered `_solutionid_value eq <solutionid>`), collecting each
`objectid`. `context.customizations` is then filtered to components whose id is a
member (ids normalized case/brace-insensitively).

> **Confirmed live** (2026-07, org `orgfe6eb58f`): a topic (Copilot component) is
> listed in `solutioncomponents` as its own row with **`objectid` = the topic's
> `botcomponentid`** and `componenttype` **10213** (the solution-component code for
> `botcomponent`). So matching the discovered topic ids against the solution's
> `objectid`s is valid — topics are not merely implicit subcomponents. Sample:
> `GET /solutioncomponents?$filter=objectid eq <botcomponentid> and _solutionid_value eq <solutionid>`
> → one row (`objectid`, `_solutionid_value`, `componenttype: 10213`).

- With **no** preferred solution (non-ALM path), every discovered customization is
  kept — no `solutioncomponents` query is issued.
- The scoping runs **once per preferred solution**: an ALM customer who owns
  several preferred-solution setups runs the tool once per solution rather than the
  tool consuming an array and waiting on the maker to re-mark each as preferred.
- `context.customized_dependencies` is derived after the narrowing, so it stays
  consistent with the scoped `customizations`.

### 4.5 Pre-writeback snapshot (`customizations.json`)

Right after the scoped `context.customizations` is finalized, the discovery step
writes a **pre-writeback snapshot** to the session bundle
(`output/session-<timestamp>/customizations.json`): a focused, per-topic view of the
**original** definition — `component_id`, `schemaname`, `name`, `component_type`(+label),
`statecode`/`statuscode`, and `data` (the original topic YAML) — excluding the verbose
raw `layers`. Because `CustomizationComponent` is frozen and the transformation stage
stages edits on the `WritebackPlan` (never mutating the component), this captures the
true pre-migration state.

It is written **early** (Input stage, before any transformation/writeback) so it
survives a later partial failure, and it is an internal engineering/recovery aid — if
a run must be reverted manually (e.g. a customer incident), the original topic YAML can
be read back from here. It is **not** a customer-facing "undo" feature; the write is
best-effort and no-ops when no session bundle is available (unit tests). See
`00_META/INVARIANTS.md` DIAG-004.

---

## 5. Agent configuration retrieval (`RetrieveAgentConfigurationStep`)

Runs **before** customization discovery. It fetches the two base artifacts the
Transformation stage rewrites, storing them raw on the context:

- `bots({selected_agent_id})` → `context.agent_bot_record` — carries the
  **UNCONFIRMED** `template` and `configuration` fields.
- `{schemaname}.gpt.default` botcomponent (queried by `schemaname eq …`) →
  `context.agent_gpt_component` — its **UNCONFIRMED** `data` YAML carries the
  model kind. A missing gpt.default is a warning, not a failure.

---

## 6. DA-compatibility transforms (`ApplyDaCompatibilityStep`)

The first Transformation step. All three rewrites are **idempotent** — records
already at DA values are left untouched and produce no write. Each rewrite is
**staged on the `WritebackPlan`** (`context.writeback`, see
`04_EXECUTION/tasks/TASK-017-writeback-plan.md`) rather than appended directly:
the step reads the working value (`target.get(field)`), transforms it, and stages
the result (`target.set(field, …)`). `context.pending_writes`
(`{"entity_set", "record_id", "changes"}`) derives from the plan — coalesced to
one PATCH per record and containing only genuinely-changed fields, so an unchanged
record never stamps a needless overlay.

| # | Target                          | From (CA)                                     | To (DA)                                           |
| - | ------------------------------- | --------------------------------------------- | ------------------------------------------------- |
| 1 | gpt.default botcomponent `data` (YAML) | `kind: PreviewModels` (+ `modelNameHint:` line) | `kind: MicrosoftCopilotModels` (hint line removed) |
| 2 | bot `template`                  | `default-*`                                   | `gptagent-1.0.0`                                  |
| 3 | bot `configuration` (JSON)      | `aISettings` without DA `model`               | add `aISettings.model = {"$kind": "MicrosoftCopilotModels"}` |

Notes:

- Transform 1 is a line-anchored regex that **preserves indentation** and only
  matches a standalone `kind: PreviewModels` line, then strips the now-orphaned
  `modelNameHint` line.
- Transform 3 parses the JSON string, only injects when `aISettings` is a dict
  and its `model` differs from the DA value, and re-serializes. Non-JSON /
  unexpected shapes are left as-is.
- Model *names* are intentionally retained; only the model **kind**/template/
  config nomenclature changes.

---

## 7. Writeback targeting (Output stage — forthcoming)

The Output stage consumes `context.pending_writes` in **WRITEBACK** mode only
(`ExecutionMode.WRITEBACK`). The list is already coalesced (one entry per record)
and no-op-guarded by the `WritebackPlan`, so each entry maps to a single
`client.update(entity_set, record_id, changes)`. When
`context.preferred_solution` is set (ALM customers), the writes target that
solution — verified live in `GatherALMCustomerInputStep` via `GetPreferredSolution`
so a typo cannot silently redirect writeback — and discovery has already been
**scoped to that solution's members** (§4.4), so writeback only ever touches the
preferred solution's own customizations. In READONLY mode the pending writes
are reported but not applied.

> **Future — overlay removal.** The guard suppresses writes equal to the current
> overlay value. If a transformed topic overlay becomes identical to the managed
> base, the ideal is to *delete* the unmanaged overlay (revert to base) rather
> than write a base-equal overlay; that base-equality removal is a future
> enhancement, not yet implemented.

---

## 8. Unconfirmed field inventory

Isolated as constants; confirm against a live record before trusting writeback:

| Constant location                         | Field           | Used for                          |
| ----------------------------------------- | --------------- | --------------------------------- |
| `apply_da_compatibility_step.py`          | bot `template`  | template rewrite                  |
| `apply_da_compatibility_step.py`          | bot `configuration` | config model injection        |
| `apply_da_compatibility_step.py`          | botcomponent `data` | gpt YAML model kind rewrite   |
| `apply_da_compatibility_step.py`          | `botcomponentid`| pending-write record id           |
| `gather_alm_customer_input_step.py`       | `uniquename`    | `GetPreferredSolution` cross-check |
