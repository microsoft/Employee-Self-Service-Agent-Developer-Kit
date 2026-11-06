# ESS Diagnostics — Combined Implementation Plan

This document combines the implementation plans for two related efforts on the
ESS Diagnostics skill, in the order they were done:

- **Part 1 — ESS Diagnostics Skill (v4):** prose edits to `SKILL.md` for the
  interactive walkthrough + real-schema parse map.
- **Part 2 — Transcript helper: Node.js → Python port:** converting the bundled
  helper to `transcript_to_json.py` and removing the Node version.

See the combined design doc `2026-09-17-ess-diagnostics-design.md` for the
rationale behind both.

---

# Part 1 — ESS Diagnostics Skill v4 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Revise `tools/ESS-Diagnostics-Skills/SKILL.md` to (a) make the diagnosis interactive — a hard problem-statement gate and a structured per-turn pause with section drill-down and verdict override — and (b) reconcile the parse map with the real Copilot Studio / PVA export schema, writing PII-bearing outputs to an OS temp dir outside the repo.

**Architecture:** Prose edits to a single `SKILL.md` (read-only Claude skill, no code). Sourced from the v4 design (Part 1 of the combined design doc) and from field paths observed in a real transcript. Validation is a manual dry run.

**Tech Stack:** Markdown. No test framework.

**Line endings:** repo is `core.autocrlf=true` + `core.safecrlf=true`, files are CRLF. After each edit, normalize to exactly one CRLF per line: `sed -i 's/\r$//' <file> && sed -i 's/$/\r/' <file>`; verify `file <file>` says "CRLF line terminators" and `grep -aoP '\r\r' <file> | wc -l` prints 0. Only touch `tools/ESS-Diagnostics-Skills/SKILL.md` unless a task says otherwise.

**Real schema reference (from the observed transcript):**
- User turn: `t = SynchronousIncomingActivity`, `p.activity.type = "message"`, text at `p.activity.text`.
- Bot turn: `t = OutgoingActivity`, `p.activity.type = "message"`, text at `p.activity.text`. (`type = "event"` activities are system plumbing — skip.)
- Diagnostic events: `t = Trace`, discriminated by `p.data.kind` ∈ {`LlmIntentRecognized`, `PluginStart`, `PluginResponse`, `KnowledgeTraceData`, `AnalyticsAiMetricsSignalTraceData`, …}.
- `PluginStart.input`: `search_query`, `search_keywords`, `enable_summarization`.
- `PluginResponse`: `citableContent[]` (`source`, `chunks`), `output`.
- `AnalyticsAiMetricsSignalTraceData`: `completionState`, `triggeredGptFallback`, `rewrittenMessage`, `rewrittenMessageKeywords`, `verifiedSearchResults[]` (`url`, `rankScore`, `snippet`, `searchType`), `citedKnowledgeSources`, `textCitations`.
- `KnowledgeTraceData`: `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `failedKnowledgeSourcesTypes`.

---

### Task 1: Add Step 0 (problem-statement hard gate) and strengthen the Rule

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** In `## Rules`, replace the bullet "Require two inputs up front… If either is missing, ask for it before proceeding." with a hard-stop bullet: the skill must not proceed past Step 0 until the FDE has stated the problem and the file path is confirmed — even if a problem was supplied in the invocation.

**Step 2:** Insert a new `## Step 0: Establish the Problem` section BEFORE `## Step 1`. It must instruct: on invocation, STOP; confirm the transcript file path; explicitly ask "What specific problem are you investigating in this transcript?"; do not read/parse until answered; if a problem statement was supplied in the args, echo it back and ask the FDE to confirm or refine rather than silently accepting.

**Step 3:** CRLF-normalize, verify, `git add`, commit: `feat: add Step 0 problem-statement hard gate to diagnostics skill`.

---

### Task 2: Rewrite the Step 1 parse map to the real schema

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Replace the Step 1 parse-map table with the concept→location→fields table from the v4 design (SynchronousIncomingActivity; OutgoingActivity; Trace/`p.data.kind` for LlmIntentRecognized, PluginStart, PluginResponse, AnalyticsAiMetricsSignalTraceData, KnowledgeTraceData). Keep the array-position ordering rule. Add: only `p.activity.type = "message"` activities are real turns; `type = "event"` are skipped for segmentation. Replace the old "search_results[] with keys FileType/Name/Text/…, no score field" note with the real result shapes (`citableContent[]` source/chunks; `verifiedSearchResults[]` url/rankScore/snippet).

**Step 2:** Add the graceful-missing-field rule: if a mapped field/event is absent, mark the affected check N/A with "field not present in this transcript" rather than failing/guessing; note the map derives from observed exports and may vary by bot config.

**Step 3:** CRLF-normalize, verify, `git add`, commit: `feat: reconcile Step 1 parse map with real transcript schema`.

---

### Task 3: Reconcile the 5 checks with the real fields

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Update each check bullet in Step 2:
- CHECK-001: recognized via `LlmIntentRecognized`; failure = intent absent OR `triggeredGptFallback = true`. Remove `UnknownIntentTriggered` as the failure path (note it's not present in real data; keep a mention that some exports may use it).
- CHECK-002: original prompt from `SynchronousIncomingActivity.p.activity.text`; issued query/keywords from `PluginStart.input`; rewrite read DIRECTLY from `rewrittenMessage` / `rewrittenMessageKeywords` (not inferred).
- CHECK-003: use `verifiedSearchResults[].rankScore` + `snippet` where present; fall back to keyword overlap on `snippet`/`source`/`citableContent.chunks`. (rankScore DOES exist — drop the "no score field" claim.)
- CHECK-004: from `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `verifiedSearchResults` count vs. the answer.
- CHECK-005: answer vs. `verifiedSearchResults` / `citedKnowledgeSources` / `textCitations`.

**Step 2:** Keep the existing "earlier failed check removes a later precondition ⇒ N/A" rule.

**Step 3:** CRLF-normalize, verify, `git add`, commit: `feat: reconcile the 5 checks with real transcript fields`.

---

### Task 4: Make Step 2 an interactive loop with structured pause + drill-down + override

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Rewrite the Step 2 walkthrough framing so that per turn the skill presents a STRUCTURED SUMMARY: Intent (id/message or failure signal); Search query (original prompt + issued/rewritten query & keywords); Search response (result count / cited sources + bot answer); and a one-line verdict strip `001 … · 005 …`.

**Step 2:** Add the section menu + hard stop:
- Menu options 1–5 (Intent, Search query, Search results, Grounding, Final answer) plus `[continue]`, `[run all]`, `[override]`.
- Hard stop: the skill WAITS and may not look at the next turn until the FDE responds.
- `run all` (available from the first pause) switches to a batch pass that auto-advances remaining turns but still produces the full report.

**Step 3:** Add drill-down + override behavior:
- Drill-down (section 1–5): show full raw transcript evidence for that section PLUS the check's reasoning (why Pass/Fail/N/A), and explicitly invite the FDE to override the verdict.
- Override: record (check, original verdict → override, FDE reason); it flows into the final report.

**Step 4:** CRLF-normalize, verify, `git add`, commit: `feat: make per-turn walkthrough interactive with drill-down and override`.

---

### Task 5: Update Step 4 outputs — OS temp dir, overrides, real-schema JSON

**Files:** Modify `tools/ESS-Diagnostics-Skills/SKILL.md`.

**Step 1:** Change output location: write the two files to a per-run subfolder in the OS temp dir (`%TEMP%/ess-diagnostics/<transcript-name>/` on Windows; `$TMPDIR` or `/tmp` on POSIX), NOT under the repo. Remove the `reports/`-under-repo path. Add a one-time PII warning and instruct the skill to report the absolute temp paths.

**Step 2:** Markdown report additions: include the confirmed problem statement (from Step 0) and any FDE verdict overrides (check, original → override, reason).

**Step 3:** Normalized JSON updates: `search.rewritten`/`rewrite_note` from `rewrittenMessage`/`rewrittenMessageKeywords`; `search_results` → real `verifiedSearchResults[]` shape (`url`, `rankScore`, `snippet`, …) and/or `citableContent[]`; add a `grounding` object (`completionState`, `isKnowledgeSearched`, `citedKnowledgeSources`, `triggeredGptFallback`). Update the fenced JSON example to this shape. Keep "NO verdicts in JSON".

**Step 4:** CRLF-normalize, verify, `git add`, commit: `feat: write outputs to OS temp dir and update JSON to real schema`.

---

### Task 6: Update README for v4 behavior

**Files:** Modify `tools/ESS-Diagnostics-Skills/README.md`.

**Step 1:** Update the README to describe: the Step 0 problem gate; the interactive per-turn pause with section drill-down and override; outputs written to an OS temp dir (not the repo) with a PII note; and the CHECK-004 (grounding) / CHECK-003 (rankScore) reconciliations. Keep it concise.

**Step 2:** CRLF-normalize, verify, `git add`, commit: `docs: update README for v4 interactive + real-schema behavior`.

---

### Task 7: Dry-run validation against the real transcript

**Files:** none (validation only).

**Step 1:** Follow the revised SKILL.md against `C:\path\to\Transcript_a9b8b841-6a4f-4675-9e79-92fc6df74be9.txt`. Confirm:
- Step 0 hard gate fires (skill asks for the problem before parsing).
- Parse map extracts the real events: 3 turns; intents `LlmIntentRecognized`; PluginStart queries + `rewrittenMessage`; `verifiedSearchResults` (count 10), `completionState = Answered`.
- The per-turn structured pause shows intent/search/response + verdict strip + section menu; drill-down shows raw evidence + reasoning; an override is accepted and recorded; `run all` works.
- Outputs land in the OS temp dir (NOT the repo); `git status` under the repo stays clean.

**Step 2:** Do NOT commit any generated report/JSON. Confirm nothing was written under `tools/ESS-Diagnostics-Skills/`. Record any gaps found; if SKILL.md needs a fix, apply it and commit `fix: address gaps found during v4 dry run`.

---

# Part 2 — Transcript helper: Node→Python port Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Replace the Node.js helper `scripts/transcript-to-json.js` with a stdlib-only Python drop-in (`scripts/transcript_to_json.py`) of exact behavioral parity, update `SKILL.md` to invoke it, and delete the JS file.

**Architecture:** A single faithful procedural port (design "Approach A"). The Python script mirrors the JS flow one-for-one — BOM strip, JSON-array validation, `_turn`/`_index` annotation as first keys, temp-dir output, absolute-path print, `Error:`/exit-1 failures. No dependencies, no packaging, no CLI framework. Validated manually by diffing its output against the existing JS output for a real transcript (no automated test, per the approved design).

**Tech Stack:** Python 3.11+ stdlib only (`sys`, `json`, `pathlib`, `tempfile`). Repo lint: Ruff (E4/E7/E9/F). Git `core.autocrlf=true` — new text files must be committed with CRLF terminators.

**Design:** Part 2 of the combined design doc `2026-09-17-ess-diagnostics-design.md`.

**Working directory for all paths below:** repo root `Employee-Self-Service-Agent-Developer-Kit/`.

**Note on git & line endings:** `core.autocrlf=true` with no `.gitattributes` caused a "LF would be replaced by CRLF" commit failure on a LF-only file. Before every commit of a NEW text file (`.py`, `.md`), convert to CRLF first: `sed -i 's/$/\r/' <file>` (idempotent-guard: only run on files freshly written LF-only). Existing files edited in place keep their endings.

---

### Task 1: Create the Python helper

**Files:**
- Create: `tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py`

**Step 1: Write the script**

Write exactly this content to `tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py`:

```python
#!/usr/bin/env python3
"""transcript_to_json.py — faithful transcript -> JSON helper for the ESS
Diagnostics skill.

Parses a Copilot Studio / PVA transcript (JSON payload stored in a .txt) and
writes a LOSSLESS, pretty-printed JSON copy: every event and every field is
preserved exactly. The only additions are `_turn` and `_index`, annotated as
the first keys on each event (turn 0 for events before the first user message)
so a reader can navigate by conversation turn. Nothing is removed, so the
output round-trips back to the original once `_turn`/`_index` are dropped.

This is the faithful full dump. It is NOT the compact diagnostic "normalized"
view the skill builds for the 5 checks — it is the whole transcript, just as
real JSON.

Usage:
    python transcript_to_json.py <transcript.txt> [outFile.json]

- <transcript.txt>  path to the raw transcript export (required).
- [outFile.json]    where to write. If omitted, writes
                    `<basename>-transcript.json` into the OS temp dir under
                    `ess-diagnostics/<basename>/` (outside any repo, because
                    transcripts may contain employee PII).

Prints the absolute output path on success. Exits non-zero with an
`Error: ...` message on failure.
"""

import json
import sys
import tempfile
from pathlib import Path


def fail(msg):
    sys.stderr.write("Error: " + msg + "\n")
    sys.exit(1)


def is_user_turn_start(e):
    return (
        isinstance(e, dict)
        and e.get("t") == "SynchronousIncomingActivity"
        and isinstance(e.get("p"), dict)
        and isinstance(e["p"].get("activity"), dict)
        and e["p"]["activity"].get("type") == "message"
    )


def main(argv):
    if len(argv) < 2:
        fail(
            "missing transcript path. Usage: "
            "python transcript_to_json.py <transcript.txt> [outFile.json]"
        )
    src_arg = argv[1]
    src_path = Path(src_arg)
    if not src_path.exists():
        fail("transcript file not found: " + src_arg)

    try:
        raw = src_path.read_text(encoding="utf-8")
    except OSError as e:
        fail("could not read transcript: " + str(e))

    # Strip a leading UTF-8 BOM if present, then parse.
    if raw and raw[0] == "\ufeff":
        raw = raw[1:]

    try:
        events = json.loads(raw)
    except ValueError as e:
        fail("transcript is not valid JSON: " + str(e))

    if not isinstance(events, list):
        fail(
            "expected the transcript to be a JSON array of events; got "
            + type(events).__name__
        )

    # Annotate each event with its conversation turn number, WITHOUT mutating any
    # existing field. A turn starts at each real user message; events before the
    # first user message are turn 0. `_turn`/`_index` are first keys on a shallow
    # copy; every original key/value is copied through untouched.
    annotated = []
    turn = 0
    for i, e in enumerate(events):
        if is_user_turn_start(e):
            turn += 1
        if isinstance(e, dict):
            annotated.append({"_turn": turn, "_index": i, **e})
        else:
            annotated.append({"_turn": turn, "_index": i, "_value": e})

    base = src_path.name
    dot = base.rfind(".")
    if dot > 0:
        base = base[:dot]

    if len(argv) >= 3 and argv[2]:
        out_file = Path(argv[2])
        try:
            out_file.resolve().parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            fail(
                "could not create output directory "
                + str(out_file.resolve().parent)
                + ": "
                + str(e)
            )
    else:
        out_dir = Path(tempfile.gettempdir()) / "ess-diagnostics" / base
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            fail("could not create output directory " + str(out_dir) + ": " + str(e))
        out_file = out_dir / (base + "-transcript.json")

    try:
        out_file.write_text(
            json.dumps(annotated, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        fail("could not write output: " + str(e))

    sys.stdout.write(str(out_file.resolve()) + "\n")


if __name__ == "__main__":
    main(sys.argv)
```

**Step 2: Lint the new file**

Run: `cd tools/ESS-Diagnostics-Skills && python -m ruff check scripts/transcript_to_json.py`
(If Ruff is not installed, skip — it is a dev tool; note the skip.)
Expected: no errors (E4/E7/E9/F clean).

**Step 3: Run against the real transcript**

Run (from `tools/ESS-Diagnostics-Skills`):
`python scripts/transcript_to_json.py "C:\path\to\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229.txt"`
Expected: prints one absolute path ending in
`ess-diagnostics\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229-transcript.json`
and exits 0.

**Step 4: Diff Python output against the existing JS output (parity check)**

The JS dump already exists from this session at the same temp path. Regenerate
it to a side path with the JS helper, then compare:
```
node scripts/transcript-to-json.js "C:\path\to\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229.txt" /tmp/js-out.json
python scripts/transcript_to_json.py "C:\path\to\Transcript_ 4b548465-9be5-4b73-bc96-e3d6bbbe5229.txt" /tmp/py-out.json
diff /tmp/js-out.json /tmp/py-out.json && echo "IDENTICAL"
```
Expected: no content diff. On Windows the Python output uses CRLF where JS uses
LF; that newline-only difference is the accepted deviation — normalize newlines
(`diff <(tr -d '\r' < js) <(tr -d '\r' < py)`) and expect IDENTICAL. Any other
diff (Unicode escaping, key ordering) must be fixed before continuing.

**Step 5: Spot-check a failure case**

Run: `python scripts/transcript_to_json.py /nonexistent/file.txt; echo "exit=$?"`
Expected: stderr line `Error: transcript file not found: /nonexistent/file.txt` and `exit=1`.

**Step 6: Commit**

```bash
cd <repo-root>
sed -i 's/$/\r/' tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py
git add tools/ESS-Diagnostics-Skills/scripts/transcript_to_json.py
git commit -m "ESS Diagnostics: add Python transcript_to_json helper (drop-in for JS)"
```
(Append the `Co-Authored-By: Claude <noreply@anthropic.com>` line per session attribution.)

---

### Task 2: Point SKILL.md at the Python helper

**Files:**
- Modify: `tools/ESS-Diagnostics-Skills/SKILL.md` (Step 1 "Faithful transcript-to-JSON" block; Step 4 file #3 block)

**Step 1: Replace both invocation code blocks**

Both currently read:
```
node scripts/transcript-to-json.js "<transcript-path>"
```
Change each to:
```
python scripts/transcript_to_json.py "<transcript-path>"
```

**Step 2: Add a platform note next to the Step 1 invocation**

Immediately after the Step 1 code block, add a sentence in the existing
Windows/POSIX style:
> On Windows use `python`; on POSIX use `python3`.

**Step 3: Verify no stale JS references remain**

Run: `grep -n "node \|transcript-to-json.js\|\.js" tools/ESS-Diagnostics-Skills/SKILL.md`
Expected: no matches.

**Step 4: Commit**

```bash
git add tools/ESS-Diagnostics-Skills/SKILL.md
git commit -m "ESS Diagnostics: SKILL.md invokes Python transcript helper"
```
(SKILL.md is an existing file; Edit preserves its CRLF endings. If a commit fails on CRLF, re-normalize with `sed -i 's/$/\r/'`.)

---

### Task 3: Remove the Node.js helper

**Files:**
- Delete: `tools/ESS-Diagnostics-Skills/scripts/transcript-to-json.js`

**Step 1: Confirm nothing operational references it**

Run: `grep -rn "transcript-to-json" tools/ESS-Diagnostics-Skills/ --include=*.md --include=*.py --include=*.js`
Expected: matches only inside `docs/plans/` (historical design/plan text) — no
match in SKILL.md, README, or scripts. Fix any operational match before deleting.

**Step 2: Delete the file**

```bash
git rm tools/ESS-Diagnostics-Skills/scripts/transcript-to-json.js
```

**Step 3: Final sanity run**

Run the Python helper once more against the real transcript (Task 1 Step 3) to
confirm the skill's dump path still works with the JS file gone.
Expected: same absolute path printed, exit 0.

**Step 4: Commit**

```bash
git commit -m "ESS Diagnostics: remove Node transcript helper (replaced by Python)"
```

---

### Task 4: Final verification

**Step 1:** `git log --oneline` — confirm the port commits are present.
**Step 2:** `git status` — confirm clean working tree.
**Step 3:** Confirm `scripts/` now contains only `transcript_to_json.py` (no `.js`):
`ls tools/ESS-Diagnostics-Skills/scripts/`
