# Curate Knowledge-Grounded Evaluation Test Sets

Create evaluation test sets grounded in a knowledge source (local files or a
connected knowledge base) and a separate
agent-instructions file. The active GitHub Copilot session is the reasoning
host; the vendored curator skill is the authoritative workflow. This wrapper
only supplies the Maker Kit host contract and lifecycle handoff. Never duplicate
the curator instructions here or reimplement them in the host.

This route is for knowledge-source-grounded creation only. It requires an
agent-instructions file plus a knowledge source, and the knowledge source may
be local files (a folder or files) or a connected knowledge base (for example
ServiceNow or SharePoint) reachable via a search/fetch tool in the session. It
does not replace configured-topic creation or named-scenario catalogue
generation.

The curator content is vendored directly in this repository — there is no Git
submodule to initialize and no version handshake to negotiate. The two vendored
files live at fixed paths under this skill folder:

```text
curator/curate-evals.md          # the curator workflow
curator/check_eval_artifacts.py  # the structural validator
```

## Step 1: Choose a mode, then require both inputs

Collect missing inputs one at a time:

1. First, ask the maker whether to curate from local files/folder or from
   their connected knowledge base (for example ServiceNow or SharePoint), then
   wait.
2. After the mode is chosen, collect the inputs that mode needs, one at a
   time, waiting after each: for local mode, ask for the folder/files path;
   for connected mode, confirm which connected knowledge base or tool to use
   (only ask this if more than one is available in the session).
3. In both modes, the agent instructions are required. Do not ask the maker
   for an agent-instructions file. Instead, resolve them live from the bound
   agent (see "Resolve and confirm the agent instructions" below) and require
   explicit maker confirmation before using them.

Do not infer a path, continue with one input, combine the questions, skip the
mode question, or ask for a scenario instead.

### Resolve and confirm the agent instructions

In both modes, the agent instructions are required. Do not ask the maker for
an agent-instructions file and do not infer a path to one. Before proceeding
into generation, run the resolver CLI shim from `solutions/ess-maker-skills/`
to obtain the instructions from the bound agent:

```powershell
py -3.12 scripts/resolve_agent_instructions.py
```

Parse its single JSON result. Never proceed into the curator body's grounding
before this gate completes.

- `status == "ok"` — show the maker the resolved instructions and require
  explicit confirmation before proceeding. The confirmed instruction text is
  the agent-instructions grounding input the curator body expects; use exactly
  that confirmed text to ground the curator's instruction-adherence cases.
- `status == "not_found"` — stop and report that no agent instructions could
  be resolved from the bound agent. Do not fall back to prompting for an
  agent-instructions file and do not silently continue. The maker fixes setup
  (for example by running `/setup`) and retries.
- `status == "error"` — stop and report the exact reason from the shim's
  `error` field. Do not fall back to prompting for an agent-instructions file
  and do not silently continue. The maker fixes setup and retries.

## Step 2: Confirm the vendored curator is present

Resolve these two paths relative to this skill folder
(`src/skills/evaluations/curate/`):

```text
curator/curate-evals.md
curator/check_eval_artifacts.py
```

Confirm both files exist before taking any curation action. If either file is
missing, show this message and stop — do not attempt a fallback implementation
and do not route to another generator:

> The knowledge-source curator is not available in this workspace. Expected
> these files under `src/skills/evaluations/curate/curator/`:
>
> - `curate-evals.md`
> - `check_eval_artifacts.py`
>
> Re-clone or restore the Maker Kit so the vendored curator files are present,
> then try again.

Only after both files are confirmed present, **read `curator/curate-evals.md` in
full** before taking any curation action. Treat these fixed paths as
authoritative.

## Step 3: Run the hosted curator flow

If the maker chose the connected knowledge base mode, resolve and confirm the
bound connection first (see "Resolve and confirm the connected knowledge base"
below) before proceeding into the curator body's Step 3b. Skip that gate
entirely in local-file mode.

Follow the vendored curator skill (`curator/curate-evals.md`) completely with
these host parameters:

```text
hostOutputRoot=workspace/evaluations
hostLifecycleHandoff=Maker Kit validation, maker review choice, promotion, scoped push, and post-success run/results lifecycle
structuralValidatorPath=src/skills/evaluations/curate/curator/check_eval_artifacts.py
```

Proceed in the mode the maker chose (local-file or connected knowledge base);
the vendored curator skill branches on mode. The active GitHub Copilot session
must perform the curator's source grounding, agent-instructions grounding, topic
confirmation, generation, preview, structural validation, and quality rules.
Run structural validation with the vendored validator at the
`structuralValidatorPath` above.

### Resolve and confirm the connected knowledge base

Only when the maker chose connected knowledge base mode: before proceeding into
the curator body's Step 3b (discovery/grounding), run the resolver CLI shim
from `solutions/ess-maker-skills/`:

```powershell
py -3.12 scripts/resolve_kb_connection.py
```

Parse its single JSON result. Never proceed into Step 3b before this gate
completes.

- `status == "error"` or `status == "none_bound"` — stop and report the exact
  reason from the shim's `error` field (or, for `none_bound`, that no
  Graph-connector knowledge source is bound to this agent) to the maker. Do
  not attempt a fallback implementation and must not silently fall back to
  local-file mode. The maker must explicitly restart mode selection at Step 1
  themselves if they want local-file mode instead.
- `status == "ok"` with exactly one connection — show the maker that
  connection's `connection_name` (and its `state`/`status` when present) and
  require explicit confirmation before proceeding into Step 3b.
- `status == "ok"` with more than one connection — list all of them
  (`connection_name` plus `state`/`status` for each) and require the maker to
  pick one or more before proceeding into Step 3b.

Only after the maker's confirmation or choice, hand off the confirmed
`connection_name`(s) into the curator body's existing Step 3b/3c flow as the
connected-KB source identifier it already expects.

### ServiceNow live-retrieval specialization

After the bound-source resolver and the maker's confirmation or selection
gate, apply this specialization to every confirmed connection before using any
ServiceNow MCP tool. Local-file and non-ServiceNow connected-KB flows remain
unchanged.

For each bounded discovery or targeted query, run the scoped Graph search shim
from `solutions/ess-maker-skills/` exactly through this command shape:

```powershell
py -3.12 scripts/search_connected_kb.py `
  --connection "{CONFIRMED_CONNECTION_REFERENCE}" `
  --query "{BOUNDED_QUERY}" `
  --limit "{BOUNDED_LIMIT}"
```

Parse only the CLI's deterministic JSON. Do not parse console prose or call
Graph through an improvised path. The first bounded CLI response may be used
to classify the connection from `connection.classification`, but classification
must be resolved before identifier mapping or any ServiceNow MCP use:

- If the classification is `servicenow`, continue with the Graph-ranked
  results in that response and enter the rest of this specialization.
- If the classification is `ambiguous`, ask the maker whether the connection
  is ServiceNow. A maker-confirmed ServiceNow connection continues with that
  response's Graph-ranked results. If the maker says it is not ServiceNow,
  treat it exactly like `other`.
- If the classification is `other`, or the maker says an ambiguous connection
  is not ServiceNow, discard the shim response for grounding, exit this
  specialization before identifier mapping, and rerun or continue the
  vendored curator's existing generic Search/Fetch contract unchanged for the
  same bounded operation. Do not map ServiceNow identifiers or invoke
  ServiceNow MCP on this branch.

Use bounded retrieval throughout:

1. For topic discovery, run **3-5 broad queries**, each limited to the
   **top 5-10 results**.
2. After the maker confirms topics, run **one targeted query per confirmed
   topic**, limited to the **top 10-20 results**.
3. For each targeted top-10-20 Graph result subset, map every returned hit
   that has a verified safe `sys_id` or article-number identifier. Every such
   safely mapped hit is selected and must be fetched before generation. Do not
   choose a smaller or more promising subset from titles, snippets, or other
   preview text. Only a disclosed unmapped hit or a disclosed individual fetch
   failure may be omitted. Never infer an identifier from a title, URL,
   snippet, or other text.
4. Before any ServiceNow MCP record fetch, perform a fail-closed source
   identity check. Derive the expected ServiceNow hostname from each mapped
   targeted hit's trusted normalized `sourceUrl` when present. All hostnames
   present across the mapped hits must agree on exactly one ServiceNow
   hostname, and at least one such hostname must establish the expected
   instance. Compare that hostname with the configured ServiceNow MCP instance
   URL whenever the configuration is visible. If the running MCP instance
   cannot be inspected programmatically, explicitly ask the maker to confirm
   that the exact expected hostname matches the ServiceNow instance used by
   the running MCP server. Do not invent or call an MCP identity tool. If the
   Graph hostname is missing or inconsistent, the configured hostname differs,
   or the match cannot be established or confirmed, stop before fetching and
   direct the maker to run `/connect ServiceNow`, then reconfigure or start the
   correct server.
5. Fetch every safely mapped record through ServiceNow MCP. Use exactly one of
   these projections:

```text
get_record(
  table="kb_knowledge",
  sys_id="{MAPPED_SYS_ID}",
  fields="sys_id,number,short_description,text,kb_knowledge_base,workflow_state"
)
```

or, when multiple selected hits have safe article-number mappings, this
bounded batch:

```text
query_table(
  table="kb_knowledge",
  query="numberIN{MAPPED_NUMBERS}",
  fields="sys_id,number,short_description,text,kb_knowledge_base,workflow_state",
  limit={MAPPED_NUMBER_COUNT}
)
```

After each single or batch fetch, verify that every returned `sys_id` and/or
`number` used for grounding exactly matches the mapped identifier requested
for that hit. A missing or mismatched requested identifier is a disclosed
failed fetch; do not use that record's content for grounding.

Ground and generate only after all required canonical MCP content fetches and
returned-identifier checks complete. The Graph results are the bounded ranked
candidate subset; they are not a substitute for the canonical full article
content returned by ServiceNow MCP.

Never issue blank, unscoped, or broad `kb_knowledge` queries. Never use a
title-based lookup or title-based fallback. In particular, never broad-search
ServiceNow as a fallback when Graph search or mapping fails.

Apply these failure boundaries:

- A Graph search, authentication, permission, transport, or malformed-response
  failure stops the connected flow. Report the error and offer the maker the
  option to restart in local-file mode. Never broad-search ServiceNow as a
  fallback.
- Missing, stopped, or unauthenticated ServiceNow MCP stops the flow with
  targeted guidance to run `/connect ServiceNow`, or to start or fix the
  configured server when it already exists.
- If an unmapped Graph hit is returned, skip it and disclose the skipped hit
  while continuing with the safely mapped subset.
- If an individual required record fetch fails, including a returned-identifier
  mismatch, skip it and disclose the failure while continuing with the
  remaining bounded subset. Do not replace it with a title lookup or a broad
  query.

### Cite source URLs on grounded cases

This is an additive host write-responsibility, layered on top of the vendored
Step 6 artifact shape **without editing the curator** body. The vendored Step 6
defines the base CSV columns `Prompt,Expected response,Test Method Type,Passing
Score` and the `.mcs.yml` `extensionData` carrying `displayOrder`; those base
columns and keys stay exactly as the vendored body writes them. The host simply
appends one more CSV column and one more extensionData key during the same
Step 6 write pass.

**2a — record the grounding source URL (connected-KB positive/boundary only).**
While writing each set's `.mcs.yml` and `.csv` in the one Step 6 write pass,
for every positive and boundary case grounded through the connected knowledge
base, record that case's grounding document URL into both artifacts:

- Add a `Source URL` column to the CSV, appended after the vendored
  `Passing Score` column, holding that case's grounding `sourceUrl`.
- Add a `sourceUrl` key under that case's child `.mcs.yml`
  `extensionData.sourceUrl`, alongside the vendored `displayOrder`.

The value is the grounding hit's `sourceUrl` as returned by
`py -3.12 scripts/search_connected_kb.py` (its JSON hits include a `sourceUrl`
field) for the hit that grounded that case. Carry the `sourceUrl` of each
selected hit through grounding so it is available at write time, and record it
in the same write pass so the two artifacts can never drift.

Leave the `Source URL` column and the `sourceUrl` extensionData key **blank**
for negative cases and for **all local-file cases**. Cite on positive and
boundary connected-KB cases only, **never for negative cases** (a negative case
tests the agent declining when no source covers the question — there is no
source to cite) and never for any local-file case regardless of sign.

**2b — conditional citation-adherence cases.** Generate a small pool of graded
citation-adherence cases **only when** the live agent instructions resolved and
confirmed in Step 1 actually require citing sources. If the resolved
instructions do not mandate citation, generate none.

When they do mandate citation, draw these cases only from positive and boundary
grounding — **never** from negative cases. Each such case's `expectedOutput`
describes citation as **observable** user-facing behavior (the response points
the user to the supporting source) **without naming a backend** system,
consistent with the vendored curator's "no backend names" rule. These cases
follow the same vendored Step 6 artifact shape as every other set.

**2c — enforce Compare Meaning-only grading.** This is another additive
host write-responsibility, layered on top of the vendored Step 6 artifact
shape **without editing the curator** body. The vendored curator template
writes both a `GeneralQualityGrader` and a `CompareMeaningGrader` entry
under each generated EvaluationSet's `graders` list. The ADK evaluation
feature now supports Compare Meaning only (see
`solutions/ess-maker-skills/scripts/evaluation_method_policy.py`). During
the same Step 6 write pass, remove the `GeneralQualityGrader` entry from
the `graders` list of every generated EvaluationSet parent `.mcs.yml`,
leaving exactly one `CompareMeaningGrader` entry with its threshold
unchanged. Do this for every set regardless of category — never leave
more than one grader, and never leave `GeneralQualityGrader` as the sole
grader for a single-turn set.

The vendored curator skill's "Host integration contract" section describes
resolving paths relative to a curator-package root that the submodule packaging
once provided. That resolution does not apply here: the curator is vendored
in-repo and this wrapper supplies the fixed `structuralValidatorPath` above
directly. Use the paths this wrapper provides and ignore the vendored body's
package-relative path-resolution instructions.

Do not weaken confirmation or validation gates. Do not reinterpret the
curator's generation rules. After receiving its structured hosted handoff, skip
the curator local-only wrap-up because the Maker Kit owns the remaining
lifecycle.

## Step 4: Validate, then ask for maker review

### Accept only a complete hosted handoff

Accept the curator handoff only when it is well formed, contains one or more
generated set entries and all paths required by the curator flow,
`structuralValidation` is exactly `passed`, and `qualityValidation` is exactly
`passed`. A missing set, missing field, unexpected validation value, or
incomplete curator run is a malformed, failed, or partial handoff.

Before invoking Maker Kit validation or handing any set to the update skill,
serialize the exact structured handoff to JSON and pipe it to this deterministic
check from `solutions/ess-maker-skills/`:

```powershell
$handoffJson | py -3.12 scripts/eval_curator_handoff.py validate --repo-root ../..
```

Use `python` instead of `py -3.12` only when required by the host's portable
Python convention. Parse exactly one JSON result. Continue only when the
command exits successfully and `valid` is exactly `true`; then use only its
normalized `sets[].folder` and `sets[].csv` paths for every later validation
and lifecycle handoff. Stop before Maker Kit validation if any path contains
traversal, resolves outside `workspace/evaluations`, crosses a symlink or
junction escape, is missing, uses `exports/` as a set folder, places a CSV
outside `workspace/evaluations/exports/`, or otherwise has malformed
structure. Never repair, reinterpret, or substitute a rejected path.

For every entry in `sets`, always run the Maker Kit validator in the next step,
even when the curator reports `qualityValidation: passed`. Every generated set
must then have successful Maker Kit quality validation before any lifecycle
handoff.

Any malformed, failed, or partial handoff, structural validation failure, or
Maker Kit quality validation failure must remain local. It must not enter the
update skill or proceed to promotion, push, cleanup, or run.

For each generated set in the curator handoff:

1. Read `src/skills/evaluations/validate/SKILL.md` and invoke its quality
   validation for the exact returned set folder.
2. Follow `src/skills/evaluations/quality-fix-flow.md` for any required or
   user-selected fixes.
3. After validation passes for all generated sets, read
   `src/skills/evaluations/update/SKILL.md`.

Use the available structured choice control to ask:

> What would you like to do with these test sets?

Offer exactly:

1. **Edit the test sets myself**
2. **Send them to a judge or SME for feedback**
3. **Keep them unchanged**

Wait for the maker's response. Do not enter update's **Four maker actions** menu
or Step 7 before this choice.

Route the response through the update skill without implementing any mutation,
synchronization, review metadata, or push behavior in this wrapper:

- **Edit the test sets myself** — hand the exact generated workspace set
  folders to the update skill as explicitly preselected sets. This curator
  gate has already selected the edit path, so update Step 2 must show the
  relevant preview and cases, skip its generic Edit/SME/Keep continuation
  question, and proceed directly to case selection and editing. Complete Steps
  2 through 6, including YAML/CSV synchronization and validation, without
  rediscovery or set reselection. When that path completes, return to this
  maker review gate and wait for another choice.
- **Send them to a judge or SME for feedback** — hand the exact generated
  workspace set folders to update **Flow R1** as explicitly preselected sets.
  After Flow R1 records the local review request, continue through update
  **Step 7 onward**.
- **Keep them unchanged** — hand the exact generated workspace set folders to
  the update skill's **Four maker actions** menu as explicitly preselected
  sets.

The update skill is the one authoritative flow for all post-validation
edit/synchronization/validation, review metadata, keep-local, setup check,
promotion, scoped dry-run and push, cleanup, final status, and successful-push
next actions. It is the sole source of truth for those lifecycle gates. Do not
duplicate any of those commands, questions, or behaviors in this wrapper.

Topic confirmation, generation preview, and the maker review choice are not
push approval. Only explicit push approval inside update Step 7 authorizes the
update skill to continue toward staging and push.

Failed or partial validation stays local and blocks lifecycle handoff,
promotion, push, and run. A missing vendored curator file also stops the flow.
