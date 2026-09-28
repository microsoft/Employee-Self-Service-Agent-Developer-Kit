# ESS Diagnostics — Combined Design

This document combines the design for two related efforts on the ESS Diagnostics
skill, in the order they were done:

- **Part 1 — ESS Diagnostics Skill (v4):** the interactive-walkthrough +
  real-schema parse-map revision of `SKILL.md`.
- **Part 2 — Transcript helper: Node.js → Python port:** converting the bundled
  faithful-dump helper from `transcript-to-json.js` to `transcript_to_json.py`.

---

# Part 1 — ESS Diagnostics Skill (v4): Interactive Walkthrough + Real-Schema Parse Map

## Purpose

Fix two problems found when dry-running the v3 skill against a real transcript
(`Transcript_a9b8b841-...txt`):

1. **The skill was not interactive.** It ran the whole diagnosis in one shot:
   it never stopped to ask the FDE for the specific problem, and it never paused
   turn-by-turn for FDE input. The v3 rules *said* to do both, but they were soft
   guidance ("ask if missing", "pause") with no hard stop, so the model flowed
   straight through.
2. **The parse map did not match real data.** Real Copilot Studio / PVA exports
   carry diagnostic events as `Trace` events discriminated by `p.data.kind`, use
   `SynchronousIncomingActivity` for user turns, and expose grounding/rewrite via
   `AnalyticsAiMetricsSignalTraceData` / `KnowledgeTraceData`. The v3 map's
   `IncomingActivity` / `search_results[]`-with-`Name`/`Text` shape does not exist
   in the observed transcript.

This is a v4 revision of `tools/ESS-Diagnostics-Skills/SKILL.md`. Scope: both the
interaction model AND the parse-map reconciliation.

## 1. Problem-statement hard gate (new Step 0)

Add **Step 0: Establish the Problem**, run before any parsing:

- On invocation the skill STOPS, confirms the transcript **file path**, and
  explicitly asks: **"What specific problem are you investigating in this
  transcript?"**
- It may NOT read/parse the transcript until the FDE answers.
- If a problem statement was supplied in the invocation args, the skill echoes it
  back and asks the FDE to confirm or refine it — never silently accepts it.
- Rules bullet changes from "ask if missing" to a firm hard stop: "Do not proceed
  past Step 0 until the FDE has stated the problem and you have confirmed the file
  path — even if a problem was supplied in the invocation."

## 2. Interactive per-turn walkthrough with structured pause

Step 2 becomes a real interactive loop with a hard stop after each turn.

At each turn's pause, the skill presents a **structured summary** (explicit, not
just verdicts):

- **Intent** — recognized intent (id/message) or the failure signal.
- **Search query** — original user prompt + issued/rewritten query & keywords.
- **Search response** — result count / cited sources, and what the bot answered.
- A one-line **verdict strip**: `001 Pass · 002 Pass · 003 Pass · 004 Pass · 005 Pass`.

Then a **section menu**:

```
Drill into a section, or advance:
  1. Intent          2. Search query     3. Search results
  4. Grounding       5. Final answer
  [continue] next turn   [run all] finish without pausing   [override] a verdict
```

- **Hard stop:** the skill WAITS here; it may not look at the next turn until the
  FDE responds. Default is per-turn stops.
- **Escape hatch:** at the first pause the FDE may type `run all` to switch to a
  batch pass (auto-advance through remaining turns, still producing the full
  report).
- **Drill-down (sections 1–5):** show the full raw transcript evidence for that
  section (complete query/keywords, full result list, full intent object, full
  answer text) PLUS the check's reasoning (why Pass/Fail/N/A), and explicitly
  invite the FDE to **override** the verdict with their domain knowledge.
- **Override:** recorded (check, original verdict → override, FDE reason) and
  carried into the final report.

## 3. Parse-map reconciliation (real schema)

Rewrite Step 1's parse map to the observed real export. Ordering by array
position is unchanged (that rule was correct). Structural change: most diagnostic
events are `Trace` events keyed by `p.data.kind`.

| Concept | Where it lives | Fields |
|---|---|---|
| User utterance | `t = SynchronousIncomingActivity`, `p.activity.type = "message"` | `p.activity.text` |
| Bot message | `t = OutgoingActivity`, `p.activity.type = "message"` | `p.activity.text` |
| Intent recognized | `t = Trace`, `p.data.kind = LlmIntentRecognized` | `intentId`, `intentMessage`, `userUtterance` |
| Search issued | `t = Trace`, `p.data.kind = PluginStart` | `input.search_query`, `input.search_keywords`, `pluginName` |
| Search results | `t = Trace`, `p.data.kind = PluginResponse` | `citableContent[]` (`source`, `chunks`), `output` |
| Grounding/answer signal | `t = Trace`, `p.data.kind = AnalyticsAiMetricsSignalTraceData` | `completionState`, `triggeredGptFallback`, `rewrittenMessage`, `rewrittenMessageKeywords`, `verifiedSearchResults[]` (`url`, `rankScore`, `snippet`, `searchType`), `citedKnowledgeSources`, `textCitations` |
| Knowledge search state | `t = Trace`, `p.data.kind = KnowledgeTraceData` | `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `failedKnowledgeSourcesTypes` |

Only `p.activity.type = "message"` activities are real user/bot turns;
`type = "event"` activities are system/plumbing and are skipped for turn
segmentation.

Check reconciliation:

- **CHECK-001 Intent Recognition** — recognized via `LlmIntentRecognized`. The
  failure signal is `triggeredGptFallback = true` on
  `AnalyticsAiMetricsSignalTraceData` (there is no `UnknownIntentTriggered` in
  real data). Fail if intent is absent or GPT fallback was triggered.
- **CHECK-002 Search Query Issued** — original prompt from
  `SynchronousIncomingActivity.p.activity.text` (the intent's `userUtterance` is
  often empty). Issued query/keywords from `PluginStart.input`. **Rewrite is read
  directly** from `rewrittenMessage` / `rewrittenMessageKeywords`, not inferred.
- **CHECK-003 Search Result Topical Relevance** — use
  `verifiedSearchResults[].rankScore` and `snippet` where present (rankScore does
  exist in this schema); fall back to keyword overlap on `snippet` / `source` /
  `citableContent.chunks`.
- **CHECK-004 Knowledge Grounding Consistency** — from `isKnowledgeSearched`,
  `completionState`, `citedKnowledgeSources`, and `verifiedSearchResults` count
  vs. what the answer does with them.
- **CHECK-005 Final Answer vs. Retrieved Content / Guardrails** — answer text vs.
  `verifiedSearchResults` / `citedKnowledgeSources` / `textCitations`.

**Graceful missing-field handling:** if a mapped field/event is absent in a given
transcript, mark the affected check **N/A** with "field not present in this
transcript" rather than failing or guessing. Note that the map derives from
observed exports and field names may vary by bot configuration.

## 4. Outputs, PII handling, testing

**Outputs written OUTSIDE the repo (PII safety):** the markdown Debug Report and
normalized JSON are written to a per-run subfolder in the OS temp directory
(`%TEMP%/ess-diagnostics/<transcript-name>/` on Windows; `$TMPDIR` or `/tmp` on
POSIX), NOT under `tools/ESS-Diagnostics-Skills/`. Nothing is written into the
repo, so commits can never capture employee PII. The skill tells the FDE the
absolute temp paths when done and warns once that outputs may contain PII and
should not be shared outside approved channels.

**Report additions:** the confirmed problem statement (from Step 0) and any FDE
verdict overrides (check, original → override, reason). Per-turn results surface
intent / search query + rewrite / search response explicitly.

**Normalized JSON updates:** `search.rewritten` / `rewrite_note` sourced from
`rewrittenMessage` / `rewrittenMessageKeywords`; `search_results` becomes the real
`verifiedSearchResults[]` shape (`url`, `rankScore`, `snippet`, …) and/or
`citableContent[]`; add a `grounding` object (`completionState`,
`isKnowledgeSearched`, `citedKnowledgeSources`, `triggeredGptFallback`). Still NO
verdicts in the JSON.

**Testing:** re-run the dry run against the same real transcript and confirm:
Step 0 gate fires; the structured per-turn pause + section menu + drill-down +
override work; the new parse map extracts intent/search/grounding correctly; and
outputs land in the OS temp dir, not the repo. No automated suite (prose skill).

## Note on prior v3 decisions this revisits

- v3's final review removed reliance on a "completion state" field because it was
  unmapped. Real data DOES carry `completionState` / `isKnowledgeSearched`, so v4
  re-introduces it as a mapped field for CHECK-004.
- v3 asserted there is "no rank/score field" on results. Real
  `verifiedSearchResults[]` objects DO have `rankScore`, so CHECK-003 may use it.
- These are corrections grounded in one real export; the graceful-missing-field
  rule guards against over-fitting to a single transcript.

---

# Part 2 — Transcript helper: Node.js → Python port

**Date:** 2026-09-17
**Status:** Approved design
**Scope:** `tools/ESS-Diagnostics-Skills/`

## Problem

The ESS Diagnostics skill ships a helper, `scripts/transcript-to-json.js`, that
produces a faithful (lossless) JSON dump of a Copilot Studio / PVA transcript.
The rest of the repo is Python (3.11+, Ruff-linted, pytest suite). A lone
Node.js dependency in an otherwise Python toolkit is an avoidable footgun for
FDEs and maintainers. Convert the helper to Python and remove the Node version.

## Goals

- Replace the JS helper with a stdlib-only Python script that is an **exact
  behavioral drop-in** (same CLI contract, same output, same error/exit
  behavior).
- Update `SKILL.md` to invoke the Python helper.
- Remove the JS file. No Node dependency remains.

## Non-goals

- No automated test (matches the JS helper's current no-test status; validate
  manually).
- No CLI enhancements (`argparse`, `--help`), no packaging (`__main__.py`), no
  refactor of the diagnostic flow. Faithful port only.

## Decisions

| Question | Decision |
| --- | --- |
| Fate of the JS file | **Delete** — Python fully replaces it. |
| Invocation | `python scripts/transcript_to_json.py "<path>"` (plain script, not `-m`). |
| Interpreter in docs | Document both: `python` (Windows) / `python3` (POSIX), matching SKILL.md's existing Windows/POSIX split. |
| Fidelity | **Exact behavioral parity** — true drop-in. |
| Test | **None** — manual validation. |
| Internal structure | **Approach A** — faithful procedural port, stdlib only, no unused abstraction. |
| Filename | `transcript_to_json.py` (PEP 8 underscores). |

## Files

- **Add:** `tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py`
- **Delete:** `tools/ESS-Diagnostics-Skills/scripts/transcript-to-json.js`
- **Edit:** `tools/ESS-Diagnostics-Skills/SKILL.md` (invocation commands, ~2 spots, + platform note)
- **README.md:** no change (verified — no `node`/`.js`/`transcript-to-json` references)

No new dependencies. Stdlib only: `sys`, `json`, `pathlib`, `tempfile`.
Target: Python 3.11+.

## The Python script (behavioral parity)

CLI: `python transcript_to_json.py <transcript.txt> [outFile.json]` — arg 1
required (source), arg 2 optional (output path).

Flow, identical to the JS original:

1. `fail(msg)` → write `Error: <msg>\n` to stderr, `sys.exit(1)`.
2. Missing arg 1 → fail with the usage message. Source file not found → fail.
3. Read source as UTF-8. Strip a leading BOM (`﻿`) if present.
4. `json.loads`; on error → `fail("transcript is not valid JSON: ...")`.
5. Not a `list` → `fail("expected the transcript to be a JSON array of events; got <type>")`.
6. Annotate: walk events in array order, increment `turn` at each user-turn
   start (`t == "SynchronousIncomingActivity"` and `p.activity.type ==
   "message"`); emit each as `{"_turn": turn, "_index": i, **event}` so
   `_turn`/`_index` are the first keys and every original field is preserved
   untouched. Nested access is guarded (`isinstance` / `.get()` chains) so a
   malformed event never raises — mirrors the JS `e && e.p && e.p.activity`
   guard.
7. Resolve output path: if arg 2 is given, use it (create its parent dir);
   otherwise `tempfile.gettempdir()/ess-diagnostics/<basename>/<basename>-transcript.json`,
   creating directories. Basename = source filename minus its final extension.
8. Write with `json.dumps(annotated, indent=2, ensure_ascii=False)`.
   **`ensure_ascii=False` is required** for byte-parity with JS
   `JSON.stringify`, which emits raw (non-escaped) Unicode.
9. Print the absolute output path to stdout.

Wrapped in a `main()` called under `if __name__ == "__main__":`.

Parity guarantees preserved: identical `Error:` prefix (SKILL.md instructs the
FDE to relay it), exit codes (0 success / 1 failure), temp-path shape, printed
absolute path, and round-trippable output (drop `_turn`/`_index` → original).

**Accepted platform deviation:** on Windows, Python's `Path.write_text`
translates `\n` to `\r\n`, so the dump uses CRLF while the JS output used LF.
This was reviewed and accepted — the file is valid JSON consumed by re-parsing
(newline-agnostic), CRLF is native on Windows, and the content is byte-identical
after newline normalization.

## SKILL.md edits

Each `node scripts/transcript-to-json.js "<transcript-path>"` (Step 1 "Faithful
transcript-to-JSON" and Step 4, file #3) becomes:

```
python scripts/transcript_to_json.py "<transcript-path>"
```

Add a one-line platform note in the existing Windows/POSIX style: use `python`
on Windows, `python3` on POSIX. Surrounding prose (writes into the same temp
folder, prints the absolute path, relay `Error:` on failure, produce both dumps)
stays valid unchanged.

## Error handling

All failure modes route through `fail()`: missing/absent source, invalid JSON,
non-array top level, and unwritable output directory each print a single
`Error: ...` line to stderr and exit non-zero. No Python traceback leaks to the
FDE. Identical to the JS behavior.

## Validation (manual)

1. Run the new script against the real transcript
   (`Transcript_ 4b548465-...txt`); confirm it prints the same absolute path and
   writes a valid file.
2. Diff the Python output against the existing JS output for that transcript;
   expect identical content (the annotation + round-trip guarantee).
3. Spot-check a failure case (non-existent path); confirm the `Error:` line and
   non-zero exit.
