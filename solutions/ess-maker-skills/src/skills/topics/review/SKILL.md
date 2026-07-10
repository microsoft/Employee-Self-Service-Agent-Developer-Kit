# Review Topic Skill

This skill runs an **authoring-time conformance review** over an authored Copilot Studio topic — or a whole
module's topics at once — and returns an **advisory** report of findings the maker should consider before
publishing.

> **Advisory by construction.** This review has no power to block — it surfaces findings and the maker
> decides. Never present a finding as a hard failure or refuse to proceed.

## Rules

- Do NOT modify the topic. This skill only reads, reports, and writes its findings catalog/ledger under
  `.local/`; it never edits the topic.
- Operate on the authored `.mcs.yml` in the maker's agent folder (`{agent.folder}/topics/`), i.e. the
  topic **before publish**. Do not require the published `samples/` copy.
- **Run the analysis silently.** Steps 3–8 are internal: run the detectors, read the reference docs, and
  persist the catalog **without narrating them**. Do not tell the maker what tools you are calling or what
  files you are reading. The only thing the maker sees is the final report in Step 9.
- **Speak the maker's language.** Hide the *review system's* vocabulary everywhere — "lens", "detector",
  "conformance", "reachability" tags (`REACHABLE_NORMAL_UI`), rule IDs (`BTPF-001`), catalog paths (the list
  is illustrative; the test is whether a maker who never saw this skill's internals would understand it). This
  is **not** a ban on technical content — the maker's own Power Fx, action kinds, field names, step names, and
  `topic.mcs.yml:line` are *their* language, not ours. The roll-up and report table (Step 9c, S-4) stay plain
  and scannable (plain severity, step **display name**, everyday description, no line numbers); the
  **single-issue detail view** shows the maker's own code in full — the exact expression and location.
- **TRACK PROGRESS**: use the todo list tool to track the steps below so the maker can see where you are.

## What this checks

This skill analyzes:

- the topic's **Power Fx expression logic** (guidance:
  `src/reference/ess-docs/conformance/powerfx-topic-local.md`) — decidable from the authored topic file;
- **`Global.*` reference integrity** across the agent (guidance:
  `src/reference/ess-docs/conformance/dangling-globals.md`) — references that resolve to no variable;
- **adaptive-card UX contract** (guidance: `src/reference/ess-docs/conformance/ux-contract.md`) — card
  data bindings that resolve to nothing, and empty/error/confirmation-state gaps;
- **ISV conformance** (guidance: `src/reference/ess-docs/conformance/isv-conformance.md`) — the topic
  against the documented field/schema conventions and known pitfalls of the backend system it integrates
  with, when ISV reference docs are available;
- **ISV integration pattern** (guidance: `src/reference/ess-docs/conformance/isv-integration-pattern.md`) —
  whether a topic for an ESS-orchestrated backend uses the shared template-config pattern rather than a
  standalone flow.
- **ServiceNow response-field integrity** — response fields the topic parses that the scenario's template
  config never returns, and which therefore render blank at runtime.

Other checks (cross-component error-code coverage) are not part of this skill; if the
maker asks about those, say they are not covered rather than guessing.

## Step 1: Identify the scope

Decide whether the maker wants **one topic** or a **module scope** (all topics for a backend), then branch:

- If the maker named a single topic (a path or one topic name) → **single-topic review**: use it and continue
  with Steps 2–9 below.
- If the maker asked to review a **module / backend / "all"** (e.g. "review all the Workday topics", "review
  ServiceNow HRSD", "review everything") → **scoped review**: resolve the module id, then jump to the
  **Scoped review** section at the end of this skill (do not run Steps 2–9 directly).
- If it is ambiguous, read `.local/config.json` for the agent folder, list the module prefixes present in
  `{agent.folder}/topics/` (the leading `servicenow-hrsd`, `servicenow-itsm`, `workday`, … segment), and ask
  the maker whether they want one topic or a whole module.

For a single-topic review, state the full path of the file you are about to review.

## The per-topic review engine (Steps 2–8)

Steps 2–8 are the **unit of review** — everything needed to review one topic and persist its catalog. Both
entry paths run this same engine:

- **Single-topic** (from Step 1) runs it **once**, then presents with Step 9.
- **Scoped** (the Scoped review section) runs it **per topic in a loop**, then presents with S-4.

**Detector steps (3, 4, 6c) share one contract.** Each runs a script from `solutions/ess-maker-skills/`
whose output is **authoritative**: every item it reports is a real defect that will always render blank at
runtime — do **not** second-guess it with "might be blank for some records". Read the step's cited guidance
doc, turn each reported item into a finding, and apply the precision bar + reachability from
`finding-contract.md` to set severity. If a script genuinely cannot run, say so in the report rather than
silently skipping. Sourcing: in a **single-topic** review run each detector with `--topic {topic-stem}`; in
a **scoped** review they already ran **once** across the module with `--module` (S-1) — use this topic's
slice, do **not** re-run them per topic (`scan_globals` re-reads the whole agent on each call).

## Step 2: Read the topic

Read the entire target `.mcs.yml`. Identify every Power Fx expression: any value beginning with `=`, and
the expression bodies inside `AdaptiveCardPrompt.card` and `AdaptiveCardTemplate.cardContent`. For each,
capture the enclosing action's **`id:`**, **`displayName:`** (if present), and **`kind:`** — these are the
stable node locators the fix step keys on. Note the approximate line number as secondary context only.

## Step 3: Check Global reference integrity (run the detector)

`python scripts/scan_globals.py --agent {agent-slug} --topic {topic-stem}` (`{agent-slug}` = the agent
folder under `workspace/agents/`, from `.local/config.json`; `{topic-stem}` = the topic filename without
`.mcs.yml`). Every reference it reports is dangling — it exists nowhere in the agent (no writer, no variable
declaration), so it will **always** read blank. Guidance: `dangling-globals.md`.

## Step 4: Check adaptive-card UX contract

If the topic contains an adaptive card:
`python scripts/scan_bindings.py --agent {agent-slug} --topic {topic-stem}`. Every card `Topic.*` reference
it reports will always render blank. Then read `ux-contract.md` and also assess the card's
empty/error/confirmation states (Part 2).

## Step 5: Analyze Power Fx expression logic (internal reasoning)

Read the analysis guidance at
`src/reference/ess-docs/conformance/powerfx-topic-local.md` and apply every heuristic in it to the
expressions you gathered. Use its precision bar (>=80% confidence), reachability scoring, and severity
mapping to decide which candidates are real findings and how serious each is.

## Step 6: Check ISV conformance (if the topic integrates a backend system)

If the topic calls an ISV scenario, read
`src/reference/ess-docs/conformance/isv-conformance.md` and follow it: determine the target ISV from the
scenario name, read that ISV's reference doc if one is available in the environment, and check the topic
against the documented field/schema conventions and known pitfalls. If the ISV reference docs are not
available, note that ISV conformance was not checked and continue — do not guess ISV behavior.

## Step 6b: Check the ISV integration pattern

Read `src/reference/ess-docs/conformance/isv-integration-pattern.md` and follow it: if the topic
integrates an ESS-orchestrated backend (ServiceNow, Workday, SAP SuccessFactors), confirm it delegates the
backend call to the shared system topic rather than calling its own cloud flow. This check reads only the
authored topic and always applies (no reference docs needed).

## Step 6c: Check ServiceNow response-field integrity (run the detector)

If the topic integrates ServiceNow:
`python scripts/scan_config.py --agent {agent-slug} --topic {topic-stem}`. Every field it reports is one the
topic parses but the scenario's template config never produces, so it will always render blank (uses the
`BTCF` finding-ID prefix per [`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md)).
ServiceNow scenarios only — Workday's config declares just a top-level key, so it contributes nothing there.
**Fix:** remove the field from the topic's parse schema, or add it to the scenario config's
`OutputFieldMapping` if the integration should return it.

Steps 3–6c are **internal reasoning**; every check reports findings in the one shape defined by
[`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md) (precision bar,
reachability→severity, finding-ID prefixes, output format). Carry each finding's node locators (`id` /
`displayName` / `kind`) through internally so consolidation and the report can name the step and a fixer can
act. That structured vocabulary is internal only — see the **Speak the maker's language** rule.

## Step 7: Consolidate findings

Before presenting, dedupe the findings from Steps 3–6c so each fix site is shown once. Different
heuristics — and different lenses — can flag the same node (e.g. a hardcoded `flowId` caught by both the
Power Fx and ISV integration-pattern lenses).

Group findings by **fix-target node id** (fall back to the site `id` / `kind` if a finding has no distinct
fix target). Within a group:

- If **one fix resolves the group**, merge into a single finding: highest severity, one unified fix,
  keeping every contributing rule ID.
- If the node genuinely needs **two independent fixes**, keep both rows and add a short "same step" note.

Carry the consolidated locators, rule IDs, and `Fix targets` to Step 8.

## Step 8: Persist and reconcile across runs

The checks are agentic, so coverage varies run to run — **a finding missing this run is not evidence it was
fixed.** Persist this run and let the script reconcile it against the prior run so the report is consistent
across sessions and `/update` can act precisely. The full shape, `id`-reuse, status/resolution, and
staleness rules live in [`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md)
(Persisted form); this step is the mechanics. The review scope is passed as `--solution` (the topic stem
today; scope-neutral for a wider review later).

1. Assemble this run's consolidated findings as `{"issues": [...]}`, each in the finding-contract shape,
   **reusing the exact prior `id`** for a finding you recognize — read the prior catalog first with
   `python scripts/merge_findings.py --solution {topic-stem} --show`. `files[].path` is relative to
   `solutions/ess-maker-skills/`.
2. Reconcile: for any prior finding now gone or corrected (especially `evidence_stale` ones), or one the
   maker dismisses, add it to a `--resolve` file per finding-contract's *Recording a resolution*.
3. Persist from `solutions/ess-maker-skills/`. **Pipe the findings on stdin with `--current -`** — do not
   pass a temp-file path (a Unix `/tmp/...` path on Windows or a shell heredoc is a known failure). Any
   staging file goes **inside the workspace** under `.local\tmp\` (gitignored) — never `$env:TEMP`,
   `C:\temp`, or `/tmp`, which trigger sensitive-file prompts.

   ```
   New-Item -ItemType Directory -Force .local\tmp | Out-Null
   Set-Content -Path .local\tmp\findings.json -Value $json -Encoding utf8
   Get-Content .local\tmp\findings.json -Raw | python scripts/merge_findings.py --solution {topic-stem} --current -
   ```

   Add `--resolve .local\tmp\resolved.json` to record resolutions. The script's catalog is **authoritative**
   on the cross-run set. If it cannot run, present this run's findings and say the cross-run catalog was
   unavailable.
4. Present (Step 9) the **active** set from the merged catalog — including findings not re-detected this run
   whose files are unchanged; flag `evidence_stale` ones as "previously flagged, code has since changed —
   worth confirming."

## Step 9: Present the report

Follow this format exactly. Do **not** add prose between sections, narrate what you checked, or explain the
process. Use plain words per the **Speak the maker's language** rule; locate each finding by the
**step/action it lives in** (its display name), never a node id or line number.

### 9a — No findings

If the active set is empty, show only this and stop — no table, no disclaimer, nothing to caveat:

**Message:**

I looked over `{TopicName}` and didn't spot anything to flag — you're good to publish.

**End message.**

### 9b — Verdict line

Otherwise show one verdict line, keyed to the highest severity present:

- Any High → `⚠️ **{TopicName}** — I spotted some things that could cause problems; worth a look before you publish.`
- Any Medium (no High) → `**{TopicName}** — a few things that might be worth a look before you publish.`
- Only Low → `**{TopicName}** — looks good; a couple of minor things to double-check before publishing.`

Directly under it, this framing line **verbatim**:

> These are potential issues flagged from common patterns — not confirmed bugs. Some may not apply to your
> scenario; use your judgment.

### 9c — Findings table

Then this table, one row per finding, sorted High → Medium → Low. Put any "no user impact today" items under
a short **Minor / cleanup** heading below the main rows.

| # | Severity | Where (step) | Potential issue | Suggested fix |
|---|----------|--------------|-----------------|---------------|
| 1 | Medium | "{step name/label}" | {what might be wrong — hedged} | {suggested fix} |

The table carries each finding — do not restate rows in prose. Add one short line under the table **only**
when a fix needs a Power Fx snippet or nuance the cell can't hold.

### 9d — Close

End with this **verbatim**:

> Advisory — you can publish as-is. To fix one, type `/update` and name its step; re-run `/review` after
> edits to re-check.

### Issue detail view (when the maker asks about one issue)

When the maker asks to see or fix a **specific issue** — "more details on X", "explain this one", "how do I
fix it" — present that finding in this structured shape, **not flowing prose**. Pull the finding from its
catalog and read the cited `files[].lines` to quote the current expression **verbatim** (a targeted read, not
a re-analysis). One block per issue — a bold header line (`{plain-language title}` · {High/Medium/Low} ·
`{topic-stem}.mcs.yml:{line}` "{step display name}"), then:

- **Current state:** `{the exact offending expression / property, verbatim from the file}`
- **Proposed fix:** `{the concrete replacement, verbatim}`
- **Why fix it this way:** {one or two plain sentences}

This is the one place the maker's own code and `file:line` appear in full. Still keep the review system's
vocabulary out (no rule IDs, reachability tags, "lens").

### Subagent mode

**If invoked as a subagent by a parent flow** (not directly by the maker): skip 9a–9d and instead return the
**structured** findings — rule IDs, severity, reachability, and sites from the analysis guidance — so the
parent can consume them programmatically. Do not prompt the maker directly.

## Scoped review (a whole module)

Reached from Step 1 when the maker asked to review a module rather than one topic. The scope is a **module
id** — a filename prefix shared by a backend's topics (`servicenow-hrsd`, `servicenow-itsm`, `workday`).

**Resolve the in-scope set once, by prefix, and use that exact set for everything.** The in-scope topics are
`{agent.folder}/topics/{module-id}*.mcs.yml` — a **prefix** match (the same `startswith` the detectors'
`--module` uses), never a substring match. List them and let **N = that count**; both the review loop and the
S-4 "N topics" figure must come from this one enumerated set, so the reported count always equals what was
actually reviewed. A broad or non-canonical term can resolve to more than one backend — e.g. `servicenow`
spans `servicenow-hrsd` **and** `servicenow-itsm`, and does **not** include the differently-prefixed
`ess-hr-servicenow-*` persona-bundle copies. If the maker's term is ambiguous or matches zero topics, confirm
the resolved module id and the exact topic list with them before starting.

Run the analysis silently (the no-chatter rule still applies); the maker sees only the roll-up in S-4.

### S-1: Run the detectors once across the scope

From `solutions/ess-maker-skills/`, run each detector **once** with `--module` (not per topic):

```
python scripts/scan_globals.py  --agent {agent-slug} --module {module-id}
python scripts/scan_bindings.py --agent {agent-slug} --module {module-id}
python scripts/scan_config.py   --agent {agent-slug} --module {module-id}
```

Each reports findings for every in-scope topic at once (globals availability is still resolved agent-wide;
`--module` only filters which topics are reported). Their output is authoritative, as in Steps 3/4/6c.

### S-2: Review each topic through the engine (per-topic loop)

Dispatch **one subagent for the whole module** (not one per topic, and not one per lens). That subagent:

1. Reads the shared reference material **once** — the module's ISV reference doc (in full — do not distill
   it) and the conformance guidance (`powerfx-topic-local.md`, `isv-conformance.md`,
   `isv-integration-pattern.md`). A module maps to a single ISV, so its topics share one ISV doc; reading it
   once here is what avoids re-reading it per topic.
2. **Loops each in-scope topic**, giving each its own full attention (per-topic focus is deliberate —
   scanning many topics at once for one lens skims and misses per-topic detail like a single hardcoded
   value). For **each** topic, in order, run the per-topic engine and finish with the mandatory persist:
   1. Read the topic and apply all six lenses (Steps 2–6c), using this topic's slice of the S-1 detector
      output — do not re-run the detectors.
   2. Consolidate (Step 7).
   3. **Persist this topic's catalog — the required last action of the iteration, before moving to the next
      topic.** Pipe this topic's consolidated findings to the script on stdin, from
      `solutions/ess-maker-skills/` (see Step 8 for the exact stdin form and the `.local\tmp\`
      workspace-internal staging rule — never `$env:TEMP` / `/tmp`):

      ```
      Get-Content .local\tmp\findings.json -Raw | python scripts/merge_findings.py --solution {topic-stem} --current -
      ```

      This write is **mandatory and per-topic**: do it once for each topic as you finish it. Do **not**
      defer persistence to the end of the loop, do **not** collect all topics and write them together, and
      do **not** author a helper script to batch-write. `merge_findings.py` is the **only** sanctioned way to
      write a catalog: it validates each finding against the contract (`id`, `title`, `severity`,
      `reachability`, `root_cause`, `concrete_fix`, and a non-empty `files[]`) and **exits non-zero without
      writing** if any is malformed. If it exits non-zero, the finding shape is wrong — correct the field names
      and re-run for this topic; never hand-write a catalog or improvise a scanner to work around it. The
      `{topic-stem}-catalog.json` on disk is the only durable record of this topic's findings — the roll-up and
      drill-down read from it, and skipping the write silently loses the topic's results. Writing as you go also
      keeps findings from accumulating in context, so a long module does not degrade the review.

The subagent returns a compact per-topic summary — per topic: the High/Medium/Low counts and, for each
finding, its severity, plain-language issue type, and id. That summary (already in your context) is what the
roll-up is **tabulated from**; the per-topic catalogs on disk are the durable record and the drill-down
source, **not** re-read to aggregate. (If a module is very large and the loop risks losing focus late,
split it into batches of topics across a few subagents — but read the shared docs once within each batch.)

### S-3: Verify every topic persisted

Before presenting, confirm the loop actually wrote a valid catalog for **each** in-scope topic. For every
topic stem, check that `.local/review-findings/{topic-stem}-catalog.json` exists and parses (has an
`issues` array). A missing or unparseable catalog means that topic's persist was skipped or its findings
were rejected — **re-run the per-topic engine for that one topic** (Steps 2–8, persisting via
`merge_findings.py`), then re-check. Do this only for the missing/invalid topics, not the whole module.
Present the roll-up (S-4) only once every in-scope topic has a valid catalog.

### S-4: Present the roll-up

Show a scope-level summary, then a per-topic table and an issue-type rollup — **not** each topic's full
findings table. **Tabulate it directly from the per-topic summaries the loop returned into your context**
(counts + per-finding severity/issue-type/id) — do **not** re-read the catalogs to aggregate, and do **not**
author a script or write a summary JSON to compute it; the roll-up is a presented table, not a persisted
artifact. Follow the same exact-template discipline as Step 9 (including the **Speak the maker's language**
rule — plain words, step display names, no internal vocabulary): use the verbatim lines below, do not
improvise the verdict, add prose between sections, or narrate the analysis (including todo-list activity).

If **no topic** in the scope has an active finding:

**Message:**

I reviewed all {N} `{module-id}` topics and didn't spot anything to flag — you're good to publish.

**End message.**

Otherwise, one verdict line keyed to the highest severity anywhere in the scope (verbatim):

- Any High → `⚠️ **Review — {module-id}** ({N} topics) — some things across these topics could cause problems; worth a look before you publish.`
- Any Medium (no High) → `**Review — {module-id}** ({N} topics) — a few things across these topics might be worth a look before you publish.`
- Only Low → `**Review — {module-id}** ({N} topics) — looks good; a few minor things to double-check before publishing.`

Directly under it, this framing line **verbatim**:

> These are potential issues flagged from common patterns — not confirmed bugs. Some may not apply to your
> scenario; use your judgment.

Then the **per-topic table** — topics with findings first, worst severity first; omit clean topics but note
the count below:

| Topic | High | Medium | Low |
|-------|------|--------|-----|
| {topic-stem} | {n} | {n} | {n} |

`{k} other topics were clean.`

Then the **issue-type rollup** — the same active findings grouped by their plain-language issue type, so the
maker sees which problems recur across the scope. Order by severity, then count:

| Issue | Topics affected | Severity |
|-------|-----------------|----------|
| {plain-language issue type} | {count} | {High/Medium/Low} |

Close with this **verbatim**:

> To see a topic's details, ask to review it by name (e.g. `review {topic-stem}`) — its findings are saved.
> To fix one, type `/update` and name the topic and step. Re-run to re-check.

**Drill-down:** if the maker asks to see one topic, render that topic's Step-9c table from its
`{topic-stem}-catalog.json` (active set). If they ask about a **specific issue**, use the **Issue detail
view** (Step 9) — no re-analysis, only a targeted read of the cited line to quote the current expression.

## References

Guidance docs under `src/reference/ess-docs/conformance/` (read the one a step cites when you reach it):

- [`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md) — shared finding shape,
  precision bar, reachability→severity, finding-ID prefixes, output format, and the persisted catalog/ledger form.
- [`powerfx-topic-local.md`](src/reference/ess-docs/conformance/powerfx-topic-local.md) — Power Fx heuristics (Step 5).
- [`dangling-globals.md`](src/reference/ess-docs/conformance/dangling-globals.md) — `Global.*` integrity (Step 3).
- [`ux-contract.md`](src/reference/ess-docs/conformance/ux-contract.md) — adaptive-card UX contract (Step 4).
- [`isv-conformance.md`](src/reference/ess-docs/conformance/isv-conformance.md) — ISV field/schema conformance (Step 6).
- [`isv-integration-pattern.md`](src/reference/ess-docs/conformance/isv-integration-pattern.md) — shared-orchestrator pattern (Step 6b).
