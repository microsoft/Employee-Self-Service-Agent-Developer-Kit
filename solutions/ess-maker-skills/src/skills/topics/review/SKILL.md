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
  persist the catalog **without narrating them**. Do not rephrase, add commentary, or tell the maker what
  tools you are calling or what files you are reading. The only thing the maker sees is the final report in
  Step 9.
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

## Coverage mode (ISV docs may be absent)

The **ISV field-conformance** check (Step 6) is the one check that can be *skipped* outright: it depends on a
backend-specific reference doc (`src/reference/ess-docs/isv/isv-<system>.md`) that is synced from an ESS
reference source and may be absent — an external maker won't have it. Whether it can run depends on the
**specific backend** the in-scope topic integrates, not on whether any ISV doc happens to exist.

**Do not decide coverage by reasoning or by an ad-hoc file check — run the coverage probe and read its
verdict.** The probe resolves each in-scope topic's backend and checks its reference doc via a path anchored on
the script location (cwd-immune, `.gitignore`-immune), so the answer is deterministic and does not depend on
you remembering to run a check correctly mid-flow:

```
python scripts/check_isv_coverage.py --agent {agent-slug} --topic {topic-stem}
# scoped:  python scripts/check_isv_coverage.py --agent {agent-slug} --module {module-id}
```

It prints a machine-readable verdict behind `###ISV_COVERAGE_JSON###`:
`{"mode": "full"|"reduced", "missing_backends": [...], "covered_backends": [...], "backends": {...}}`.

- **`mode: full`** → ISV conformance runs (or no in-scope topic calls a backend). Say **nothing** about coverage.
- **`mode: reduced`** → the reference doc for a backend in `missing_backends` is absent; ISV conformance is
  skipped for that backend's topics. The report **must** disclose it (see `report-format.md`), naming the
  backend(s) from `missing_backends`. Do not run — or claim to have run — ISV conformance for a missing backend.

Treat the probe's verdict as authoritative over any impression you form while reading the topic. If the probe
cannot run, fall back to a direct filesystem test of the exact path
(`Test-Path src/reference/ess-docs/isv/isv-<backend>.md`) — never a workspace/indexed search (the `isv/` folder
is gitignored, so an index-respecting search reports a present doc as a false-absent).

A second synced doc, `runtime/confirmed-runtime-heuristics.md`, only *corroborates* Power Fx severity — it is
**not** a check and its absence skips nothing. Without it the Power Fx caps still apply structurally (see
`powerfx-topic-local.md`); score structurally and say nothing to the maker about it. Do **not** report missing
runtime docs as reduced coverage.

**Disclose reduced coverage in the report, not before it** — the report's coverage note carries it
(`report-format.md`: the 9a reduced variant for a clean topic, the 9d coverage line otherwise, or the scoped
roll-up's coverage line). Do not add a separate pre-analysis announcement.

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

Gate this step on the **coverage probe verdict** (see "Coverage mode"): the probe already resolved the topic's
backend and whether its reference doc is present.

- If the topic's backend is in `covered_backends` (`mode: full`, or a covered backend under `mode: reduced`),
  read `src/reference/ess-docs/conformance/isv-conformance.md` and follow it: read that backend's reference doc
  by its exact path and check the topic against the documented field/schema conventions and known pitfalls.
- If the topic's backend is in `missing_backends`, ISV conformance is **skipped** for this topic — do not run
  it and do not guess ISV behavior. The report's coverage note (driven by the same verdict) discloses it.
- If no backend was detected, there is nothing to check here.

Do not re-derive doc presence yourself; the probe's verdict is authoritative.

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

**Finding identity is content, not slug.** Two findings at the **same site** (same topic + node `id`/line)
describing the **same underlying pattern** are the **same finding** — even if different lenses gave them
different rule IDs or you'd have named them with different slugs. Never emit or persist the same
`(site, pattern)` twice under two ids; merge them.

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
   `python scripts/merge_findings.py --solution {topic-stem} --show`. Match by **content, not name**: if a
   prior catalog entry is at the **same site** and describes the **same pattern** as one of this run's
   findings, it **is** that finding — reuse its `id` even if you'd have slugged it differently this run.
   Minting a new slug for an already-cataloged issue double-counts it (the script keys cross-run identity on
   `id`). `files[].path` is relative to `solutions/ess-maker-skills/`.
2. Reconcile: for any prior finding now gone or corrected (especially `evidence_stale` ones), or one the
   maker dismisses, add it to a `--resolve` file per finding-contract's *Recording a resolution*.
3. Persist from `solutions/ess-maker-skills/`. **Pipe the findings on stdin with `--current -`** — do not
   pass a temp-file path (a Unix `/tmp/...` path does not exist on Windows, and a shell heredoc is not
   supported in PowerShell). Any staging file goes **inside the workspace** under `.local\tmp\` (gitignored)
   — never `$env:TEMP`, `C:\temp`, or `/tmp`, which trigger sensitive-file prompts.

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

Present the maker-facing report exactly per
[`report-format.md`](src/reference/ess-docs/conformance/report-format.md): the no-findings message (9a),
verdict line (9b), findings table (9c), and close (9d); and, when the maker asks about a **specific issue**,
the **Issue detail view**. Follow those templates verbatim and apply the **Speak the maker's language** rule.

### Subagent mode

**If invoked as a subagent by a parent flow** (not directly by the maker): skip the maker-facing report and
instead return the **structured** findings — rule IDs, severity, reachability, and sites from the analysis
guidance — so the parent can consume them programmatically. Do not prompt the maker directly.

## Scoped review (a whole module)

If Step 1 resolved to a **module scope** (all topics for a backend), follow
[`scoped-review.md`](src/reference/ess-docs/conformance/scoped-review.md) instead of running Steps 2–9
once: it resolves the in-scope set by prefix, runs the detectors once with `--module`, loops the per-topic
engine (Steps 2–8) persisting each catalog, verifies persistence, and presents the scoped roll-up (per
`report-format.md`). The per-topic engine (Steps 2–8) and the finding contract are unchanged.

## References

Guidance docs under `src/reference/ess-docs/conformance/` (read the one a step cites when you reach it):

- [`finding-contract.md`](src/reference/ess-docs/conformance/finding-contract.md) — shared finding shape,
  precision bar, reachability→severity, finding-ID prefixes, output format, and the persisted catalog/ledger form.
- [`powerfx-topic-local.md`](src/reference/ess-docs/conformance/powerfx-topic-local.md) — Power Fx heuristics (Step 5).
- [`dangling-globals.md`](src/reference/ess-docs/conformance/dangling-globals.md) — `Global.*` integrity (Step 3).
- [`ux-contract.md`](src/reference/ess-docs/conformance/ux-contract.md) — adaptive-card UX contract (Step 4).
- [`isv-conformance.md`](src/reference/ess-docs/conformance/isv-conformance.md) — ISV field/schema conformance (Step 6).
- [`isv-integration-pattern.md`](src/reference/ess-docs/conformance/isv-integration-pattern.md) — shared-orchestrator pattern (Step 6b).
- [`report-format.md`](src/reference/ess-docs/conformance/report-format.md) — maker-facing output templates: single-topic report (Step 9), issue detail view, scoped roll-up.
- [`scoped-review.md`](src/reference/ess-docs/conformance/scoped-review.md) — the module-scope sub-workflow (S-1–S-4).
