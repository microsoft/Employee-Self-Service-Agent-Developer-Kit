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

## Step 2: Read the topic

Read the entire target `.mcs.yml`. Identify every Power Fx expression: any value beginning with `=`, and
the expression bodies inside `AdaptiveCardPrompt.card` and `AdaptiveCardTemplate.cardContent`. For each,
capture the enclosing action's **`id:`**, **`displayName:`** (if present), and **`kind:`** — these are the
stable node locators the fix step keys on. Note the approximate line number as secondary context only.

## Step 3: Check Global reference integrity (run the detector)

Run this from the `solutions/ess-maker-skills/` directory:

```
python scripts/scan_globals.py --agent {agent-slug} --topic {topic-stem}
```

- `{agent-slug}` = the agent folder name under `workspace/agents/` (from `.local/config.json`).
- `{topic-stem}` = the reviewed topic's filename without `.mcs.yml`.

The detector's output is **authoritative** on whether a `Global.*` reference resolves. Every reference it
reports as dangling **does not exist** anywhere in this agent — it is neither written by any topic nor
declared as a variable. Do **not** reason about whether such a reference "might be blank" or "might exist
for some records": if the detector reports it, it will **always** read blank. Read
`src/reference/ess-docs/conformance/dangling-globals.md` and turn each reported reference into a finding,
applying the precision bar and reachability scoring to set severity. If the script genuinely cannot be
run, say so in the report rather than silently skipping.

## Step 4: Check adaptive-card UX contract

If the topic contains an adaptive card, run the binding detector from the
`solutions/ess-maker-skills/` directory:

```
python scripts/scan_bindings.py --agent {agent-slug} --topic {topic-stem}
```

Its output is **authoritative** on whether a card's `Topic.*` reference resolves: every reference it
reports **will always render blank at runtime**. Then read
`src/reference/ess-docs/conformance/ux-contract.md` and assess the card's empty/error/confirmation states
(Part 2). Turn each into a finding with the shared precision bar and severity mapping. If the script
cannot run, say so rather than silently skipping.

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

If the topic integrates ServiceNow, run this from the `solutions/ess-maker-skills/` directory:

```
python scripts/scan_config.py --agent {agent-slug} --topic {topic-stem}
```

Its output is **authoritative** on whether a parsed response field is returned by the scenario's template
config: every field it reports is one the topic parses but the config never produces, so it **will always
render blank at runtime**. Turn each reported field into a finding, applying the precision bar and
reachability scoring from the shared [`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md)
(this check uses the `BTCF` finding-ID prefix). The detector covers ServiceNow scenarios only (Workday's
config declares only a top-level key); if it reports nothing, or the topic is not ServiceNow, this check
contributes no findings. If the script cannot run, say so rather than silently skipping. **Fix** for a
reported field: remove it from the topic's parse schema, or add it to the scenario config's
`OutputFieldMapping` if the integration should return it.

Steps 3–6c are **internal reasoning**, and every lens reports findings in the one shared shape defined by
[`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md) — precision bar, severity
via reachability, finding-ID prefixes, and the structured output format. Their rule IDs (e.g. `BTPF-001`),
reachability tags (`REACHABLE_NORMAL_UI`, etc.), and the word "lens" are working vocabulary **for you** —
they are NOT shown to the customer (see Step 9). Carry each finding's node locators (`id` / `displayName` /
`kind`) and `Fix targets` through internally so the consolidation and customer-facing steps can name the
step and a fixer can act.

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

The lenses are agentic, so coverage varies run to run — **a finding missing from this run is not evidence it
was fixed.** Persist this run into the findings catalog and let the script reconcile it against the prior
run, so the report is consistent session to session and `/update` can act on a finding precisely. The
review scope is passed as `--solution` — the topic stem today (scope-neutral: a wider ISV/solution review
would pass a different scope with no other change).

1. Write this run's consolidated findings to a temp JSON file (`{"issues": [...]}`), each in the
   finding-contract shape: `id` (a stable kebab-case behavior-describing slug), `title`, `severity`,
   `reachability`, `root_cause`, `concrete_fix`, `verification` (`static` for all current lenses;
   `needs-runtime-test` only for a finding that can only be confirmed by running the bot), and `files[]`
   (`path` relative to `solutions/ess-maker-skills/` — the topic file, plus the config or other topic a
   finding depends on, so its evidence hash is complete).
   The **`id` is the cross-run identity** — first read the prior catalog
   (`python scripts/merge_findings.py --solution {topic-stem} --show`) and **reuse the exact prior `id`** for a
   finding you recognize, so it is matched as the same finding rather than a new one.
2. Reconcile prior findings. For each prior finding **not** re-detected this run — especially any the
   catalog marks `evidence_stale` (its files changed) — read the current topic: if its node/expression is
   now gone or corrected, add it (at minimum its `id`) to a temp `--resolve` file. Also add a finding here
   if the **maker dismisses it** — set `"resolution": "not-a-bug"` when they judge it a false positive, or
   `"wont-fix"` when they acknowledge it but decline, and set `"resolved_by": "maker"`; the defaults are
   `"resolution": "fixed"` and `"resolved_by": "review-skill"`. A finding merely being absent this run is
   **not** resolution. A dismissed finding stays resolved until its code changes and it is re-detected, which
   reopens it.
3. Run from the `solutions/ess-maker-skills/` directory:

   ```
   python scripts/merge_findings.py --solution {topic-stem} --current {tempCurrent.json} [--resolve {tempResolved.json}]
   ```

   The script writes `.local/review-findings/{topic-stem}-catalog.json` (and appends any resolutions to the
   shared `.local/review-findings/resolved-issue-ledger.jsonl`), reusing stable ids, keeping the higher
   severity on a re-found finding, computing each finding's `evidence_hashes`, and setting `status`
   (`active` / `resolved`) and `evidence_stale`. Its output is **authoritative** on the cross-run set.
4. Present (Step 9) the **active** set from the merged catalog. A finding not re-detected this run whose
   files are unchanged still appears (previously flagged, code unchanged). Flag `evidence_stale` findings as
   "previously flagged, the code has since changed — worth confirming." If the script cannot run, present
   this run's consolidated findings and say the cross-run catalog was unavailable.

## Step 9: Present the report

Follow this format exactly. Do **not** add prose between sections, narrate what you checked, or explain the
process. Use plain words for severity (**High / Medium / Low**); never show internal terms (rule IDs,
"lens", reachability tags, file jargon). Locate each finding by the **step/action it lives in**, never a
line number.

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

### Subagent mode

**If invoked as a subagent by a parent flow** (not directly by the maker): skip 9a–9d and instead return the
**structured** findings — rule IDs, severity, reachability, and sites from the analysis guidance — so the
parent can consume them programmatically. Do not prompt the maker directly.

## Scoped review (a whole module)

Reached from Step 1 when the maker asked to review a module rather than one topic. The scope is a **module
id** — the leading filename segment shared by a backend's topics (`servicenow-hrsd`, `servicenow-itsm`,
`workday`). Confirm the resolved module and the count of topics it matches before starting.

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

### S-2: Review each topic in a read-once, per-topic loop

Dispatch **one subagent for the whole module** (not one per topic, and not one per lens). That subagent:

1. Reads the shared reference material **once** — the module's ISV reference doc (in full — do not distill
   it) and the conformance guidance (`powerfx-topic-local.md`, `isv-conformance.md`,
   `isv-integration-pattern.md`). A module maps to a single ISV, so its topics share one ISV doc; reading it
   once here is what avoids re-reading it per topic.
2. **Loops each in-scope topic**, giving each its own full attention: apply the Power Fx, ISV-conformance,
   and integration-pattern lenses to that one topic (Steps 5, 6, 6b), exactly as the single-topic path does.
   Per-topic focus is deliberate — scanning many topics at once for one lens skims and misses per-topic
   detail (e.g. a single hardcoded value).
3. **Writes each topic's catalog to disk immediately** after finishing that topic (S-3), before moving to
   the next. Offloading as it goes keeps findings from accumulating in context, so a long module does not
   degrade the review. It returns only a compact per-topic summary (counts + finding ids), not full findings.

(If a module is very large and the loop risks losing focus late, split it into batches of topics across a
few subagents — but read the shared docs once within each batch.)

### S-3: Consolidate and persist per topic (inside the loop)

For each topic, combine that topic's detector findings (from S-1) with its lens findings (from S-2), run the
Step 7 consolidation, then persist its catalog with `merge_findings.py --solution {topic-stem}` exactly as
Step 8 does for a single topic. Every topic keeps its own `{topic-stem}-catalog.json`; a topic with no
findings still gets reconciled (so a previously-flagged finding there is correctly carried forward). These
per-topic catalogs are the intermediates the roll-up is built from.

### S-4: Present the roll-up

Show a scope-level summary, then a per-topic table and an issue-type rollup — **not** each topic's full
findings table. Follow the same exact-template discipline as Step 9: use the verbatim lines below, do not
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
`{topic-stem}-catalog.json` (active set) — no re-analysis needed.
