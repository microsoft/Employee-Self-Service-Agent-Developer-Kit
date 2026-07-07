# ISV conformance check

Analysis guidance for the **ISV conformance** check used by the `topics/review` skill. It checks an
authored topic against the reference knowledge for the backend system it integrates with — the
documented field/schema conventions and known integration pitfalls for that ISV.

This check depends on the ESS **ISV reference docs** (`isv-<connector>.md`). Those docs are not part of
this repository; they are read from an ESS reference source when one is available in the environment. When
no reference source is available, skip this check and say so — do not guess ISV behavior.

## Step 1: Determine the target ISV

Find the topic's scenario name — either `scenarioName:` in a `BeginDialog` input binding, or `ScenarioName`
in the system topic the topic calls. Map its prefix to the ISV reference doc:

| Scenario prefix | ISV reference doc |
| --- | --- |
| `HRWorkdayHCM…` | `isv-workday-hcm.md` |
| `ITHelpdeskServiceNowITSM…` | `isv-servicenow-itsm.md` |
| `ServiceNowHRSD…` | `isv-servicenow-hrsd.md` |
| `…SuccessFactorsHCM…` | `isv-successfactors-hcm.md` |

If the topic has no ISV scenario (a simple informational or non-ISV topic), this check does not apply —
skip it.

## Step 2: Locate the ISV reference doc

The ISV reference docs are synced into this workspace at `src/reference/ess-docs/isv/isv-<connector>.md`.
Read the one doc for the ISV determined in Step 1, by its exact path, **in full** — these docs are short,
so load the entire document into context and treat all of it (field tables, schema conventions,
type-coercion notes, and pitfalls) as authoritative reference for the analysis.

If that file is not present, the ISV reference docs have not been synced into this environment. Note in the
report that ISV conformance was not checked and that the docs can be synced by running
`python scripts/sync_isv_docs.py` from `solutions/ess-maker-skills/`, then continue. Do not infer ISV
behavior from general knowledge — the reference docs are authoritative for how these integrations
actually behave.

## Step 3: Apply the ISV reference to the topic

Using the **full** reference doc you loaded in Step 2 as authoritative context — its field/schema tables,
type-coercion notes, and Known Pitfall Areas — check the authored topic against it. The reference doc is
the source of what to look for — each documented convention and pitfall is a lens on the topic. Typical
checks the docs support:

- **Field/schema faithfulness** — the topic references response fields that exist in the ISV's documented
  schema, with the documented names; a field the topic reads that the ISV does not produce will be blank.
- **Config-owned values** — values the topic hardcodes inline (scenario-specific mappings, field or table
  names, constants) that the template config is meant to own and supply, rather than being fixed in the
  topic's logic.
- **Type handling** — the topic handles fields the ISV can return in more than one shape (e.g. a value
  that may be a string or a number/boolean depending on display settings) rather than assuming one type.
- **Identifier/URL construction** — links and identifiers are built the way the ISV requires (e.g. the
  correct record identifier and table parameter, not a display number).
- **Query construction** — user-supplied values placed into the ISV's query language are escaped against
  that language's operators.
- **Naming conventions** — table names, mapping keys, and config unique names follow the ISV's documented
  conventions.

Treat each as a starting question, not a closed rule — the specific conventions come from the reference
doc for the ISV under review. Apply the same precision bar and reachability scoring as the shared
[`finding-contract.md`](finding-contract.md), and report confirmed findings with the shared output
format. This check uses the `BTIC` finding-ID prefix. Locate each by the action's node identity and name
the documented convention it conflicts with.
