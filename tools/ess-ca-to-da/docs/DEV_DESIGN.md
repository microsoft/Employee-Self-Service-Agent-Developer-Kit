# Dev Design — ESS Custom Engine Agent → Declarative Agent migration (`ess-ca-to-da`)

**Status:** Working draft, reflects the implemented tool.
**Audience:** Engineers and reviewers who need to understand how the migration works, the decisions behind it, and where the risks are.
**Scope:** The `essmig` CLI under `tools/ess-ca-to-da`. It migrates a customer's **ESS Custom Engine Agent (CA)** customizations onto the current **ESS Declarative Agent (DA)** and delivers an importable ALM package plus a report.

---

## 1. Problem statement

A customer has deployed and customized the ESS **Custom Engine Agent** — a Dataverse-backed managed solution. ESS has since shipped a **Declarative Agent** as the go-forward product. We need to move the customer's *customizations* — not the whole agent — onto the DA, without a human hand-porting every topic.

The two agents are **not the same content in a different wrapper**:

| | Custom Engine Agent (CA) | Declarative Agent (DA) |
| --- | --- | --- |
| Stored in | Dataverse (`botcomponent` rows in a managed solution) | Cosmos, via the Agent Builder Service |
| Shipped as | a managed solution | an ALM *templated package* (`agent.yml` + `app.config.<realm>.json`) |
| Schema prefix | `msdyn_…` | `gptagent_…` |
| Customer edits live as | unmanaged solution layers | overlays governed by `Overlays.json` |

ESS did **not** re-wrap the CA to build the DA; much of the content was rewritten. Across the shipping HR template, of the components that have a CA ancestor only a minority are byte-identical after normalisation, some are 50–90% similar, and a few were rebuilt outright. Roughly half the DA's components have no CA ancestor at all.

That rules out both naive strategies:

- **Copy the customer's topics over the DA** → destroys every ESS improvement.
- **Keep the DA, discard the customer's edits** → destroys the customer's work.

### 1.1 ESS is three agents, not one

ESS ships a **hub-and-spoke** topology, and the tool models it directly:

| `--vertical` (`TARGETS`) | agent | schema (CA → DA) | role |
| --- | --- | --- | --- |
| `core` | Core | `msdyn_copilotforemployeeselfservicecore` → `gptagent_…core` | standalone **hub / router**; delegates to a domain agent |
| `hr` | HR | `…hr` → `gptagent_…hr` | HR domain agent |
| `it` | IT | `…it` → `gptagent_…it` | IT domain agent |

Each target is a **first-class, independent migration**: its own CA source
solution, its own DA template, its own package. The tool is run once per agent —
or with `--vertical` omitted it **auto-detects** which of Core/HR/IT are installed
(the three base solutions have fixed unique names, so their presence in `solutions`
is the signal; see `discovery.installed_targets`) and migrates each into its own
`out/<vertical>/` subfolder. Core is **not** shared plumbing folded into HR/IT — it
is a separate agent whose
instructions route to the domain agents, so its baseline is read on its own and
its references repoint to the Core DA agent, never to HR/IT. (`msdyn_copilotforemployeeselfservice`
with no suffix is a *legacy monolith* bot, distinct from the Core hub; it is not
a DA target.)

The **domain integrations** (ServiceNow, Workday, SuccessFactors, ADP, …) are a
different animal: they are *not* separate agents. They layer into HR/IT, and where
ESS has shipped a DA equivalent (`PORTED_EXTENSION_SOLUTIONS`) their content is
baked into the HR/IT `agent.yml`, so a customization to one merges normally.
Integrations ESS has **not** yet ported (`NON_PORTED_EXTENSION_SOLUTIONS`) have no
DA home; a customization to one is reported **`blocked`** (§7), named, with its
configuration reproduced — never silently dropped or misattached.

## 2. Core decision: a three-way merge

The tool does what the platform's own *Upgrade* does for templated agents — a **three-way merge** — because that is the only strategy that preserves *both* the ESS rewrite *and* the customer's intent.

A three-way merge needs three inputs:

- **base** — the CA component *exactly as ESS shipped it* (the common ancestor).
- **ours** — the customer's live CA component (base + the customer's edits).
- **theirs** — the DA component *as ESS ships it today* (base, rewritten for the DA).

The platform can't run this merge for a CA customer — they have no Git Repository Service repo, no base commit, no `templateBaseVersion`, so there is no merge base. **But all three inputs can be reconstructed from sources ESS owns**, which is the key enabling insight of this design.

```
        base (CA as shipped)                theirs (DA as shipped today)
   reference/ca-baseline.json           reference/<vertical>/agent.yml
                 \                                   /
                  \                                 /
   ours (customer's live CA) ----> THREE-WAY MERGE ----> merged agent.yml
   Dataverse discovery                    |
                                          v
                              ALM package (.zip) + report.md
```

The tool **never writes to Dataverse or the customer's tenant** (the one optional exception is `migrate --import`, §9). The customer's CA keeps running untouched; the deliverable is a package the customer imports themselves.

---

## 3. The three inputs — how each is obtained

### 3.1 `base` and `theirs` — vendored, offline (`reference.py`, `ess.py`)

Two of the three inputs are ESS's own product artifacts, so they are **vendored into the tool** and used offline. A customer run needs no access to the ESS product sources.

- **base** comes from the CA solution sources (`sources/dev/solutions/<Solution>/Solution/botcomponents/<name>/data`) and is stored as `reference/ca-baseline.json`, keyed by vertical (`core`/`hr`/`it`) and by schema-name **suffix**.
- **theirs** comes from the DA template (`sources/dev/AgentTemplates/<Template>/Plugin/Agents/<schema>/agent.yml`) and is stored under `reference/<vertical>/`.

`vendor()` (the maintainer-only `vendor` command) extracts both from a local ESSVivaCopilot clone. `load()` reads that vendored snapshot back at migration time. **Vendoring is a maintainer step run when ESS ships a new template version** — not something a customer does. This is how the tool stays decoupled from the ESS source tree.

### 3.2 `ours` — discovered live from Dataverse (`discovery.py`, `dataverse.py`, `auth.py`)

The third input is the customer's live customization, read directly from their Dataverse environment.

- **Auth (`auth.py`):** MSAL public-client, interactive, against the customer's environment. The token cache is process-local and **in-memory — no token touches disk**. A well-known first-party public client id with Dataverse `user_impersonation` consent is used.
- **Client (`dataverse.py`):** A deliberately **read-only** Web API client — it exposes only `get`, `query_all`, and `call_function`. It handles OData paging, retries `429/5xx` with backoff, and honours `Retry-After`. There is no write path here by construction.

The **shared join key** between the CA and DA worlds is the **schema-name suffix** — everything after the agent prefix (e.g. `topic.Foo`, `gpt.default`). `msdyn_copilotforemployeeselfservicehr.topic.Foo` (CA) and `gptagent_copilotforemployeeselfservicehr.topic.Foo` (DA) are the same logical component. `ess.py::schema_suffix` computes it.

---

## 4. Determining what changed (Discovery)

Discovery answers one question: **which components did the customer actually customize?** It has three phases.

### 4.1 Find candidate components — two sources, unioned

Discovery enumerates candidate components from **two** sources and unions them (deduped by GUID, `_dedupe_targets`):

1. **Uninstall dependencies** — `RetrieveDependenciesForUninstallWithMetadata(SolutionId=<base>)`. This returns components that *depend on* the managed base — i.e. **net-new** customer content (new topics, knowledge sources). This is how a brand-new knowledge source is found.

2. **The agent's own `botcomponent` rows** — queried by schema-name prefix, restricted to migratable component types (`_owned_botcomponents`).

> **Why both?** The uninstall-dependency scan alone has a blind spot: an **in-place edit of an out-of-box component** — e.g. changing the agent *instructions* on `gpt.default` — adds an unmanaged "Active" layer but creates **no uninstall dependency**, so it never appears in source (1). Enumerating the agent's own botcomponents directly (source 2) surfaces those edits; the classification step below then discards the ones that were never actually touched. *(This was a real bug: instruction edits silently migrated nothing until source (2) was added.)*

### 4.2 Read the solution layers for each candidate

For each candidate, discovery reads its **solution layers** from the `msdyn_componentlayers` virtual table. This table has hard constraints the code encodes:

- `$filter` **must** pair `msdyn_componentid` with `msdyn_solutioncomponentname`; one query per component (it will not honour `OR` across several component ids).
- `msdyn_overwritetime` is unreliable (net-new reads `1900-01-01`), so classification keys off `msdyn_solutionname`, **not** timestamps.
- The real attribute values live inside `msdyn_componentjson` — a JSON string with an `Attributes` list of `{Key, Value}` pairs; `componenttype` is itself wrapped as `{Value: int}`.

**Effective attribute values** are computed by merging the layers, topmost layer winning (`_component_attributes`).

> **Layer ordering is made deterministic, not trusted.** The virtual table does **not** honour `$orderby` and its row order is undocumented. Relying on "the last row Dataverse returned wins" is a latent bug: if the environment returns the unmanaged **Active** overlay *before* the managed baseline, the baseline silently overwrites the customer's edit and the tool reads the shipped text. `_ordered_base_first` sorts layers by solution-layer semantics — managed OOB solutions are the base, the customer's unmanaged overlay always wins — so precedence is correct regardless of row order. *(This was the second half of the "instructions don't migrate" bug.)*

### 4.3 Classify: keep every customization the agent owns (`_classify`)

A candidate is kept when it is **customized** and owned by *this* vertical's agent:

- **Customized** — more than one layer (managed OOB base + the customer's overlay), **or** a lone layer that is *not* in an OOB ESS solution (a net-new component in the unmanaged `Active` layer). A lone layer *inside* an OOB managed solution is untouched shipped content and is dropped silently. `OOB_CA_SOLUTIONS` (base + core + extension packs) defines "OOB".
- **Owned by this agent** — the schema name carries this vertical's agent prefix. A component owned by another agent is dropped **with a reason**.

Every customized, agent-owned component is kept regardless of `componenttype`, so the report can account for **all** of it. Whether a component is *carried* in the package or only *re-created by hand* is decided downstream by projection/merge — it is no longer silently dropped at discovery. The owned-component sweep queries `DETECTABLE_COMPONENT_TYPES` (the carriable `MIGRATABLE_COMPONENT_TYPES = {9, 12, 15, 16, 20}` → topic, variable, GPT, knowledge source, metric — plus `REPORT_ONLY_COMPONENT_TYPES = {1, 13, 14, 18, 19}` → skills, file attachments, Copilot settings, evaluations/test cases) so in-place edits of those types are found too; net-new components of any type still arrive via the dependency path.

The agent's own **name and description** are read separately (`_agent_metadata`, from the live `bot` row plus its managed component layer for the shipped baseline) and carried on `DiscoveryResult.agent` as an `AgentMetadata`. This is best-effort: any read failure degrades to `None` (agent metadata simply not assessed) rather than aborting the migration.

`--preferred-solution` optionally narrows discovery to the members of a named unmanaged solution.

The output is a `DiscoveryResult`: the kept `CaComponent`s (hydrated: schema name, type, effective `data`, layers), the skipped list with reasons, and the optional `agent` metadata.

---

## 5. Applying the changes to the new package (Projection + Merge)

### 5.1 Projection — CA shape → DA shape (`projection.py`)

Each CA component is *projected* into the DA `agent.yml` shape before merging. Projection:

- maps `componenttype` → DA kind + payload key (`9→DialogComponent/dialog`, `12→GlobalVariableComponent/variable`, `15→GptComponent/metadata`, `16→KnowledgeSourceComponent/configuration`);
- **rewrites schema-name prefixes** end-to-end (`msdyn_copilotforemployeeselfservice[hr]…` → `gptagent_copilotforemployeeselfservice[hr]…`), longest-prefix-first so cross-topic references (BeginDialog targets, variable scopes, trigger targets) point at the DA agent rather than an agent that no longer exists;
- raises `ManualConfigurationRequired` for types the DA supports only as **agent settings** (not package components) — e.g. custom metrics — so they are reported for hand re-creation instead of being silently lost.

### 5.2 Merge — per component (`merge.py::_merge_one`)

For each discovered component, keyed by suffix against the DA template:

1. **No DA counterpart** → `CARRIED_NEW`: the customer authored it; append it wholesale as a customer-owned component.
2. **Template-locked** (overlay policy) → `LOCKED`: the customer's edit can't be carried; reported.
3. **Customer-owned by overlay policy** → keep the customer's version (`MERGED`).
4. **Otherwise, a real three-way merge** of `base_payload` (from `ca-baseline.json`), `ours` (projected live), `theirs` (DA template):
   - `ours == base` → `UNCHANGED` (customer didn't touch it; nothing to carry).
   - structural `merge_node`: if we didn't change it take theirs; if they didn't take ours; if both changed a node differently → **conflict** at the deepest differing point.
   - clean merge → `MERGED`; unresolved conflicts → `CONFLICTED` (needs a human).

**Interactive conflict resolution (`resolve.py`).** A `CONFLICTED` component is not the end of the road. When `migrate` runs against a terminal (and `--non-interactive` is not passed), each contested spot is offered to the user in place. The tool prints the spot's path, *what* changed, and — crucially — **what you changed relative to the version ESS originally shipped in the CA** (a semantic diff computed from the carried `Conflict.base`, so a customer sees just their edit, not two full blobs to eyeball), alongside ESS's current version. It then asks **keep [E]SS's** (default, on Enter), **keep [M]ine**, or **[O]pen an editor to merge by hand**, with an *apply 'keep …' to the rest of this topic* shortcut so a repetitive rename need only be answered once. The chosen value is written straight into the merged tree, so the component lands `MERGED` (its detail notes "You resolved N spot(s) here — X kept yours, Y kept ESS's, Z merged by hand") and the package ships the resolved content.

- **Hand-merge (`Resolution.MANUAL`).** Choosing *open an editor* writes a temp YAML file — a header, both sides shown as reference comments, and an editable region pre-seeded with ESS's version below a marker line — and launches `$VISUAL`/`$EDITOR` (Notepad on Windows). When the user saves and closes, the text below the marker is parsed back through the *same* ruamel YAML machinery that dumped it (`projection.dump` ⇆ `projection.load_fragment`), so quoting and Power Fx expressions round-trip. The parsed value is placed verbatim at the spot. Unparseable or empty edits re-prompt rather than corrupt the package.
- **How it's wired without polluting the merge:** `merge()` takes a `resolver_factory`; `_merge_one` builds a fresh per-component resolver (so the per-topic "apply to rest" state can't leak across topics) and threads a `resolve(conflict) -> Decision | None` callback through `merge_node`/`_merge_dict`/`_merge_list` at each of the six conflict sites. A `Decision` carries the `Resolution` (OURS / THEIRS / MANUAL) plus, for MANUAL, the hand-merged `value`. `None` (the non-interactive default, or a non-TTY, or `--non-interactive`) preserves the old behavior exactly: keep ESS's and report it. The GPT `.instructions` conflict is deliberately **skipped** by the console resolver (returns `None`) so the LLM reconciler below — not a blunt keep-mine/keep-ESS — handles it.

### 5.3 The instructions special case — reconciled with an LLM (`instructions.py`, `llm.py`)

Agent **instructions** (the `instructions` scalar on the `GptComponent`, type 15) are the one customization a structural merge **cannot** carry. The DA ships the *same* instructions the CA shipped, but **reworded for the DA runtime**, so the scalar differs on every side: `base ≠ theirs` (ESS reworded), and `base ≠ ours` when the customer edits. A three-way merge of that single string therefore *always* conflicts and the customer edit is dropped.

The fix (`_reconcile_gpt_instructions`) extracts the customer's **semantic delta** (`ours` vs `base`) and re-applies it onto the DA's wording with a language model:

- Only fires when the customer actually edited instructions (`ours.strip() != base.strip()`).
- Prompts the model with all three versions (BASE / CUSTOMER / TARGET) and asks it to apply the customer's changes onto TARGET, preserving the DA's wording, structure, and runtime references. On success the `.instructions` conflict is cleared and the outcome is `MERGED` with an explanatory note.
- **LLM access** reuses the **GitHub Copilot API** via `gh auth token` — the same pattern the ADK's eval judge uses (`solutions/ess-maker-skills/scripts/evaluate_evals.py`). Endpoint `https://api.githubcopilot.com/chat/completions`, header `Copilot-Integration-Id: copilot-chat`, no model named (uses the plan default to avoid Business/Enterprise model restrictions). **Zero extra setup and no secrets shipped.**
- **Graceful degradation:** if the model is unreachable, `LlmUnavailable` is raised (never `sys.exit`); the migration still produces a package, keeps the DA's instructions, and reports the edit as a conflict for hand re-application. `--keep-instructions` forces this offline path deterministically; `inspect` always uses it to stay fast and network-free.

### 5.4 Unsupported constructs — disable but preserve (`rules.py`, `_apply_unsupported_rules`)

After the merge (so it sees the *final* content), any carried topic that uses a construct the DA lacks (unsupported triggers/nodes) is **deprecated in place** — preserved but disabled — and the report records what was unsupported, the guidance, and **who must act** (`Owner`: maker vs platform). Running post-merge matters: a customer edit may have introduced the unsupported node, or an ESS rewrite may have removed it.

`_ensure_knowledge_search` mirrors the platform: once at least one knowledge source is present, the GPT gets `knowledgeSources: {kind: SearchAllKnowledgeSources}` so carried sources are actually searched.

---

## 6. Building the new package (`packaging.py`)

The deliverable is an ALM package that mirrors the ESS template's layout, with the `Plugin` folder as the archive's top-level entry (the import API requires a `Plugin/Agents/<schema>/agent.yml` entry):

```
Plugin/package.json
Plugin/Overlays.json
Plugin/Agents/<agent schema name>/agent.yml
Plugin/Agents/<agent schema name>/app.config.dev.json
```

Design points that are load-bearing for a successful import:

- **`agent.yml` is emitted byte-faithfully.** YAML is dumped with quotes preserved, block-sequence indentation matching the template (`indent(mapping=2, sequence=4, offset=2)`), and **effectively unlimited width** — a wrapped long scalar folds newlines to spaces on re-parse, which silently corrupts the base64 agent icon, and the strict import binder rejects a package whose `agent.yml` differs structurally from what the platform emits. Timestamps are kept verbatim (`keep_timestamps_verbatim`) so a round-trip doesn't rewrite every component's `auditInfo`.
- **Environment-specific values never travel** (`scrub_config`). Connection ids are set to `null` (the key must remain present — deleting it makes the package fail to bind into a valid Dev agent), and only key-vault *references* (`kv://…`) are allowed through in `secrets`; a literal secret is dropped.
- **Package identity is carried forward** (`_package_metadata`): `packageType`, `publisher`, and `templateVersion` stay exactly as ESS shipped them — they mark the agent as a *templated* agent eligible for future platform upgrades — while authorship/timestamp are restamped.
- **Unbound-pointer check** (`check_pointers`): config keys referenced by `${config.values["…"]}` in `agent.yml` but not defined are surfaced *before* the customer hits a publish failure (connection ids/secrets are expected to be unbound and are not reported).

---

## 7. Reporting & assessment (`report.py`, `assessment.py`, `rules.py`)

The package is only half the deliverable; the **report is the primary human-facing output**. Because a meaningful share of edits to OOB topics will conflict (ESS rewrote much of the content), the honest product is an accurate classification plus a precise worklist.

Every component lands in exactly one `Outcome` — `MERGED`, `CARRIED_NEW`, `CONFLICTED`, `LOCKED`, `UNCHANGED`, `NO_TARGET`, `BLOCKED`, `MANUAL`, `FAILED` — and the report groups them, most-urgent first. `BLOCKED` is reserved for a customization that belongs to a domain integration ESS has not ported to a DA: there is no agent for it to attach to, so it is named (with the pack labelled, e.g. *HR Success Factors*) and its configuration reproduced for hand re-creation, and it counts as a verdict blocker in `assess()`. `assess()` turns the merge result into a go/no-go verdict with blockers and a worklist, so `inspect` can answer "is this customer ready to migrate, and if not, why not?" without producing a package.

---

## 8. Command surface (`cli.py`)

- **`vendor --ess-root <clone>`** — maintainer-only. Refresh `base`/`theirs` reference data when ESS ships a new template version.
- **`inspect --environment-url … [--vertical hr]`** — read-only. Discover customizations, write `out/customizations.json` (per-component snapshot incl. `data` and layer solution order — the diagnostic for "what did the tool actually read?") and `out/customizations.md` (a per-component unified diff of what changed from the ESS baseline, each row tagged **✅ migratable now / ⚠️ migratable but needs you / ⛔ not supported yet** by running the same merge the report uses), and print an eligibility verdict. Uses the **offline** instructions path.
- **`migrate --environment-url … [--vertical hr]`** — the full job: discover → merge onto the DA template → emit `out/gptagent_<schema>.zip` + `out/migration-report.md`. Uses the **model-backed** instructions reconciler by default; `--keep-instructions` forces offline; `--snapshot` reuses a prior `inspect` snapshot instead of hitting Dataverse (its agent is recovered from the snapshot's `vertical` field); `--import` (§9) additionally delivers into a target. **Interactive by default at a terminal**: it prompts to resolve each conflict (§5.2) and bakes the choice into the package; `--non-interactive` (also the automatic behavior when stdout is not a TTY, e.g. CI) skips prompting and leaves conflicts for the report.

**`--vertical` is optional.** When it is omitted, both `inspect` and `migrate` call `discovery.installed_targets` to detect every ESS agent installed in the environment and run the per-agent job for each, writing to `out/<vertical>/` subfolders (an explicit `--vertical` keeps the flat `out/` layout, unchanged). Detection is a cheap `uniquename eq …` probe of `solutions` per target and needs no extra permissions. In auto mode, `--import` delivers each detected agent under its own default DA schema name into the shared target environment; combining it with `--target-schema-name` across multiple detected agents is refused (it would name them all the same), so override a single agent's schema by naming it with `--vertical`.

---

## 9. Delivery / import — the one write path (`deliver.py`)

Optional, off by default. `migrate --import --target-environment-id <guid>` imports the built zip into a **specified** target DA, replacing that agent's content in the target environment's **Dev ring only** (Test/Prod untouched until promoted):

```
POST {api_base}/copilotstudio/tenants/{tenant}/environments/{environment}/minimalBots/alm/import?schemaName={schemaName}
```

`schemaName` must name the agent that already exists in the target, so the import takes the *overwrite* path (without it the API returns 409). HTTP failures are captured into an `ImportResult` (never raised) so a failed delivery still produces a report.

> **Draft-design caveat:** the import host, request/response shape, and token audience are from a draft ALM design and have **not** been exercised against a live environment. The base URL (`--target-api-base` / `ESSMIG_TARGET_API_BASE`) and token scope (`ESSMIG_TARGET_SCOPE`) are runtime-overridable so the endpoint can be corrected without a code change. Re-confirm both before a customer run.

---

## 10. How the DA package is expected to be *updated* over time

Two distinct "update" flows:

1. **ESS ships a new DA template version.** The maintainer re-runs `vendor` against an updated ESSVivaCopilot clone to refresh `base` and `theirs`. Because the merge base and target are both re-derived from ESS sources, a subsequent customer `migrate` re-applies the customer's *same* delta onto the *new* template — this is exactly the templated-agent upgrade behaviour, run on the customer's behalf.

2. **The customer re-runs the migration.** `migrate` is **idempotent with respect to discovery**: it always reads the customer's *current* CA state and rebuilds the package from scratch — it never diffs against a prior run's output. Re-running after further CA edits produces an updated package that reflects those edits. Import is a **clean replace** into Dev, so re-import is safe; connections are re-bound in the destination each time (they never travel in the package).

There is deliberately **no** persistent migration state and **no** incremental/patch update model. The full pipeline (discover → merge → package) is cheap enough to run wholesale, and a stateless rebuild is far easier to reason about and to trust than a patch stream against a live agent.

---

## 11. Testing & quality gates

- `python -m ruff check .`, `python -m mypy`, `python -m pytest tests -q`, run from `tools/ess-ca-to-da`.
- Dataverse, MSAL, the Copilot API, and the import endpoint are all injected as dependencies (a `FakeClient`, a stub `complete`, an injected `httpx.Client`), so the full pipeline is unit-tested offline. Discovery tests cover layer classification, the in-place-edit (botcomponent) source, and the deterministic layer-ordering fix.

---

## 12. Known limitations & open questions

- **Import endpoint is unverified** against a live environment (see §9). Highest-risk area for a real customer run.
- **Discovery assumptions** validated against one HR environment: the `botcomponents` entity set name and `componenttype eq N` filter, and the assumption that a Copilot Studio UI instruction edit creates an `Active` layer on `gpt.default`. Confirmed working for the instructions case; other verticals/edit types warrant a live pass.
- **LLM reconciliation is non-deterministic** by nature. `--keep-instructions` exists for runs that need reproducible output or where `gh` Copilot access is unavailable; the reconciled instructions should be reviewed like any other conflict resolution.
- **Only `agent.yml` component types in `MIGRATABLE_COMPONENT_TYPES` are *carried* into the package.** Everything else the customer owns is still **detected and reported** (Copilot settings, file attachments, evaluations/test cases, skills, custom metrics) — routed to `MANUAL` (re-create in the agent's settings, configuration reproduced) or `NO_TARGET` (no DA equivalent yet) rather than silently dropped. Carrying more types structurally is future work; reporting them is not.
- **Agent name/description migration reads the live `bot` entity.** `_agent_metadata` is best-effort: the `bots` entity-set name, its `name`/`description` fields, and the `bot` component-layer baseline are validated against one HR environment; a schema difference degrades to "not assessed" rather than a crash. When the shipped baseline cannot be read the tool will not overwrite the DA's own name/description — it reports the difference for review instead.

---

## 13. Module map

| Module | Responsibility |
| --- | --- |
| `cli.py` | Command surface: `vendor`, `inspect`, `migrate` (+ `--import`). |
| `auth.py` | MSAL public-client tokens (in-memory only). |
| `dataverse.py` | Read-only Dataverse Web API client (paging, retries). |
| `discovery.py` | Determine what the customer customized (`ours`): layer classification + deterministic ordering; every agent-owned customization is kept and reported; reads the agent's own name/description (`AgentMetadata`). |
| `ess.py` | ESS constants: solution names, schema prefixes, component types, the OOB baseline set. |
| `reference.py` | Vendored `base` (`ca-baseline.json`) and `theirs` (DA template); `vendor()`/`load()`. |
| `projection.py` | CA component → DA `agent.yml` shape; schema-prefix rewriting. |
| `merge.py` | Three-way merge; per-component `Outcome`; unsupported-construct handling; conflict-resolver threading. |
| `resolve.py` | Interactive console conflict resolver (keep ESS's / keep mine, per-topic shortcut). |
| `instructions.py` | Reconcile the `instructions` scalar (LLM) + offline no-op. |
| `llm.py` | Minimal GitHub Copilot API client (`gh auth token`), graceful `LlmUnavailable`. |
| `rules.py` | Unsupported constructs, ownership of the resulting gaps. |
| `assessment.py` | Go/no-go verdict, blockers, worklist. |
| `packaging.py` | Emit the ALM package (byte-faithful `agent.yml`, config scrub, pointer check). |
| `deliver.py` | Optional import into a target DA's Dev ring (the one write path). |
| `report.py` | The human-facing migration report. |
