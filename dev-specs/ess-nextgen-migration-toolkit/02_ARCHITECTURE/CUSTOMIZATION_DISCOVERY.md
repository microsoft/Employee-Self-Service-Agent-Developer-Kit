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
call_function RetrieveDependenciesForUninstallWithMetadata(SolutionUniqueName=…)
        ↓  DependencyMetadataCollection.DependencyMetadataInfoCollection[]
extract unique dependentcomponentobjectid (skip empty GUID)
        ↓
bulk-fetch msdyn_componentlayers for those ids   # chunked (≤20 ids/$filter) + paginated
        ↓
classify layers by msdyn_componentid group  → customizations[]
```

### 3.1 Dependencies for uninstall

`RetrieveDependenciesForUninstallWithMetadata` returns the components that are
layered on top of the base solution — i.e. the customer's customization
candidates. Response shape (verified from a live sample):

```jsonc
{
  "DependencyMetadataCollection": {
    "DependencyMetadataInfoCollection": [
      { "dependentcomponentobjectid": "ec1a5183-…", "dependentcomponenttype": 10213, … }
    ]
  }
}
```

The step collects the unique, non-empty `dependentcomponentobjectid` values. The
all-zero GUID `00000000-0000-0000-0000-000000000000` is skipped.

### 3.2 Component layers

For each dependent component id, the toolkit reads
`msdyn_componentlayers` (a **virtual** table) filtered by
`msdyn_componentid eq '<id>'`. Because `raw_dependencies` can be large, ids are
**chunked** (≤ 20 per `$filter`, OR-joined) and each query is **fully paginated**
via `query_all` (`@odata.nextLink` followed to exhaustion). All fields are
selected (`select=None`) so the full `msdyn_componentjson` payload is available
downstream.

---

## 4. The ~1900 sentinel classification rule

Each managed base layer carries a **sentinel** `msdyn_overwritetime` of
`1900-01-01T00:00:00Z`; a customer edit/overlay carries a **recent** time. The
classifier groups layers by `msdyn_componentid` and, per group, keeps the
**latest non-sentinel** layer:

| Case          | Layers in the group                          | Verdict                          |
| ------------- | -------------------------------------------- | -------------------------------- |
| Untouched OOB | single ~1900 sentinel layer                  | **drop** (nothing customized)    |
| Customized OOB| ~1900 base **+** one or more recent overlays | **keep** latest non-sentinel overlay |
| Net-new       | single recent (non-1900) layer               | **keep** (customer-authored)     |

These three cases collapse into one rule: *keep the latest non-sentinel layer
per component; if every layer is a ~1900 sentinel, drop the component.* Only the
kept layers (`context.customizations`) propagate to the Transformation/Output
modules.

Sentinel test: a parsed `msdyn_overwritetime` with `year <= 1900`. Unparseable
or missing times sort as the minimum datetime and never win over a real overlay.

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
already at DA values are left untouched and produce no write. Each changed record
appends a payload to `context.pending_writes`
(`{"entity_set", "record_id", "changes"}`) for the Output stage to persist.

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
(`ExecutionMode.WRITEBACK`). When `context.preferred_solution` is set (ALM
customers), the writes target that solution — verified live in
`GatherALMCustomerInputStep` via `GetPreferredSolution` so a typo cannot silently
redirect writeback. In READONLY mode the pending writes are reported but not
applied.

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
