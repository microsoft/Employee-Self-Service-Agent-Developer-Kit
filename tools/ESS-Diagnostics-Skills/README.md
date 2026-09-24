# ESS Diagnostics Skills

A read-only Claude skill for diagnosing ESS Custom Engine Agent transcripts. The
full procedure lives in [`SKILL.md`](./SKILL.md).

## What it is

`SKILL.md` is a read-only Claude skill that walks a Field Engineer (FDE)
turn-by-turn through a Copilot Studio / PVA transcript, runs a 5-check
diagnostic on each turn, and produces an evidence-cited Debug Report. It
replaces the earlier standalone Python diagnostics tool.

## How an FDE uses it

Invoke the skill by pointing Claude at this skill directory (there is no wired
slash command yet) — for example, ask Claude to "use the ESS diagnostics skill in
`tools/ESS-Diagnostics-Skills/` on `<path-to-transcript.txt>`", or open
`SKILL.md` and have Claude follow it. Before it parses anything, the
skill **stops at a hard gate (Step 0)**: it asks the FDE to confirm the
transcript **file path** and to state the **specific problem** being
investigated. It will not proceed without a problem statement — even if one was
supplied in the invocation, it echoes that back for the FDE to confirm or refine.

Only then does it read and parse the transcript. It walks each turn and **STOPS
at every turn**, presenting a structured summary (intent, search query +
rewrite, search response, plus a one-line verdict strip) and a section menu. At
each pause the FDE can:

- **Drill into any section (1–5)** — see the full raw transcript evidence for
  that section plus the reasoning behind that check's verdict.
- **Override a verdict** — the FDE's override replaces the skill's verdict for
  divergence and root-cause purposes.
- **`continue`** — advance to the next turn.
- **`run all`** — finish the remaining turns without pausing.

## The 5 checks

- **CHECK-001 — Intent Recognition:** was the user's intent recognized (fails on
  no intent event, or on `triggeredGptFallback = true`).
- **CHECK-002 — Search Query Issued:** shows the original prompt, the issued
  query, and any rewrite.
- **CHECK-003 — Search Result Topical Relevance:** relevance of the returned
  results to the query/keywords (can use `verifiedSearchResults[].rankScore`,
  else keyword overlap).
- **CHECK-004 — Knowledge Grounding Consistency:** did the answer's grounding
  match what was retrieved — judged from `isKnowledgeSearched`,
  `completionState`, `citedKnowledgeSources`, and the `verifiedSearchResults`
  count versus what the final answer does.
- **CHECK-005 — Final Answer vs. Retrieved Content / Guardrails:** did the final
  answer align with what was retrieved (or decline appropriately).

## Outputs

Because transcripts contain employee PII, the outputs are written **outside the
repo**, into a per-run subfolder in the OS temporary directory, named from the
transcript's basename:

- **Windows:** `%TEMP%\ess-diagnostics\<name>\`
- **POSIX:** `$TMPDIR` (or `/tmp` when unset) `/ess-diagnostics/<name>/`

Three files are written there:

- **`<name>-debug-report.md`** — the human-readable Debug Report with per-turn
  verdicts, any FDE verdict overrides, the divergence point, and the root cause.
- **`<name>-normalized.json`** — a clean, normalized parsed transcript artifact
  containing NO verdicts (only the fields the diagnostic checks use).
- **`<name>-transcript.json`** — a faithful, lossless JSON copy of the whole
  transcript (every event and field preserved, `_turn`/`_index` annotated),
  produced by the bundled helper `scripts/transcript_to_json.py`.

## Read-only guarantee

The skill never modifies the transcript or any agent files. Its only writes are
the three output files above, in the OS temp directory — never in the repo.

## Testing / validation

There is no automated test suite — the skill is prose, not code. Validate it
with a manual dry run against a real (redacted) transcript. Outputs are written
outside the repo specifically to avoid committing PII; still, never commit
un-redacted real transcripts, which may contain PII or employee data.
