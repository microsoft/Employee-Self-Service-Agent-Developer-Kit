# Scoped review (a whole module)

The multi-topic sub-workflow for `topics/review` — reached from Step 1 when the maker asks to review a
**module** (all topics for a backend) rather than one topic. It reuses the per-topic review engine
(Steps 2–8 of the skill) in a loop, then presents a roll-up. Run the analysis silently (the same
no-narration rule as a single-topic review); the maker sees only the roll-up.

## Resolve the scope

The scope is a **module id** — a filename prefix shared by a backend's topics (`servicenow-hrsd`,
`servicenow-itsm`, `workday`).

**Resolve the in-scope set once, by prefix, and use that exact set for everything.** The in-scope topics are
`{agent.folder}/topics/{module-id}*.mcs.yml` — a **prefix** match (the same `startswith` the detectors'
`--module` uses), never a substring match. List them and let **N = that count**; both the review loop and the
S-4 "N topics" figure must come from this one enumerated set, so the reported count always equals what was
actually reviewed. A broad or non-canonical term can resolve to more than one backend — e.g. `servicenow`
spans `servicenow-hrsd` **and** `servicenow-itsm`, and does **not** include the differently-prefixed
`ess-hr-servicenow-*` persona-bundle copies. If the maker's term is ambiguous or matches zero topics, confirm
the resolved module id and the exact topic list with them before starting.

## S-1: Run the detectors once across the scope

From `solutions/ess-maker-skills/`, run each detector **once** with `--module` (not per topic):

```
python scripts/scan_globals.py  --agent {agent-slug} --module {module-id}
python scripts/scan_bindings.py --agent {agent-slug} --module {module-id}
python scripts/scan_config.py   --agent {agent-slug} --module {module-id}
```

Each reports findings for every in-scope topic at once (globals availability is still resolved agent-wide;
`--module` only filters which topics are reported). Their output is authoritative, as in the skill's
Steps 3/4/6c.

## S-2: Review each topic through the engine (per-topic loop)

Dispatch **one subagent for the whole module** (not one per topic, and not one per lens). That subagent:

1. Reads the shared reference material **once** — the module's ISV reference doc (in full — do not distill
   it) and the conformance guidance (`powerfx-topic-local.md`, `isv-conformance.md`,
   `isv-integration-pattern.md`). A module maps to a single ISV, so its topics share one ISV doc; reading it
   once here is what avoids re-reading it per topic.
2. **Loops each in-scope topic**, giving each its own full attention (per-topic focus is deliberate —
   scanning many topics at once for one lens skims and misses per-topic detail like a single hardcoded
   value). For **each** topic, in order, run the per-topic engine and finish with the mandatory persist:
   1. Read the topic and apply all six checks (skill Steps 2–6c), using this topic's slice of the S-1 detector
      output — do not re-run the detectors.
   2. Consolidate (skill Step 7).
   3. **Persist this topic's catalog — the required last action of the iteration, before moving to the next
      topic.** Pipe this topic's consolidated findings to the script on stdin, from
      `solutions/ess-maker-skills/` (see skill Step 8 for the exact stdin form and the `.local\tmp\`
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

## S-3: Verify every topic persisted

Before presenting, confirm the loop actually wrote a valid catalog for **each** in-scope topic. For every
topic stem, check that `.local/review-findings/{topic-stem}-catalog.json` exists and parses (has an
`issues` array). A missing or unparseable catalog means that topic's persist was skipped or its findings
were rejected — **re-run the per-topic engine for that one topic** (skill Steps 2–8, persisting via
`merge_findings.py`), then re-check. Do this only for the missing/invalid topics, not the whole module.
Present the roll-up only once every in-scope topic has a valid catalog.

## S-4: Present the roll-up

Present the **Scoped roll-up** exactly per
[`report-format.md`](report-format.md) — tabulated **directly from the per-topic summaries the loop returned
into your context** (counts + per-finding severity/issue-type/id). Do **not** re-read the catalogs to
aggregate, and do **not** author a script or write a summary JSON to compute it; the roll-up is a presented
table, not a persisted artifact. If the run is in **reduced coverage** (see the skill's "Coverage mode" step —
i.e. an in-scope topic's backend ISV reference doc is absent), include the roll-up's coverage line per
`report-format.md`, naming the backend(s) whose conformance could not be checked.
