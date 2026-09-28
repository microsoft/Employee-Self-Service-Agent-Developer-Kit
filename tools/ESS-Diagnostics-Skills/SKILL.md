# Diagnose an ESS Transcript

Read-only diagnostic skill that walks a Field Engineer (FDE) turn-by-turn
through a Copilot Studio / PVA transcript (a JSON payload exported as a `.txt`
file), running a 5-check diagnostic on each turn with evidence quoted straight
from the transcript. It produces an evidence-cited markdown Debug Report plus a
normalized-transcript JSON artifact. This skill replaces the earlier standalone
Python diagnostics tool.

## Rules

- This skill is **read-only**. The ONLY writes it may make are the three output
  files written in Step 4: the markdown Debug Report, the normalized-transcript
  JSON, and the faithful full-transcript JSON. Never modify the transcript, agent
  files, or anything else.
- Do NOT narrate your internal process. Say "Let me walk you through this
  transcript" not "Let me read the parse map." Speak directly to the FDE.
- **Do not proceed past Step 0 until the FDE has stated the problem and you
  have confirmed the transcript file path.** This is a hard stop: ask even if a
  problem statement was already supplied in the invocation — echo the supplied
  statement back and have the FDE confirm or refine it. Never parse the
  transcript before the problem is established.
- Every check verdict MUST quote the specific transcript field value it rests
  on (the actual query string, result names, and so on). Make no claim the
  transcript does not support.
- Walk the transcript one turn at a time. After presenting a turn's checks,
  pause and ask the FDE to confirm or add context before advancing to the next
  turn.
- Track progress with todos if the transcript has many turns.

## Step 0: Establish the Problem

On invocation, STOP before doing anything else. Do not read or parse the
transcript yet — the problem must be established first.

Confirm the transcript **file path** with the FDE, stating the path you were
given. Then ask explicitly: "What specific problem are you investigating in this
transcript?"

If a problem statement was supplied in the invocation arguments, echo it back
verbatim and ask the FDE to confirm it as-is or refine it — do NOT silently
accept it.

Only once the FDE has given or confirmed the problem statement AND the file path
is confirmed may you proceed to Step 1. Keep the confirmed problem statement — it
is cited in the final report.

## Step 1: Read and Parse the Transcript

Read the transcript file (a JSON payload stored in a `.txt`) and extract the
events you will need for the checks.

**Iterate events by their array position in the transcript, NOT by `seq`.**
`seq` is unreliable — some event kinds (e.g. `TranscriptTrace`) repeat
`seq: -1` many times. The array/list order is canonical; walk it in order.

Top-level events are objects with `t` (the event kind) and `p` (its payload).
All diagnostic signals are `t = "Trace"` events discriminated by `p.data.kind`.
Extract events using this parse map:

| Concept | Where it lives | Fields |
| --- | --- | --- |
| User utterance | `t = SynchronousIncomingActivity` (only `p.activity.type = "message"`) | `p.activity.text` |
| Bot message | `t = OutgoingActivity` (only `p.activity.type = "message"`) | `p.activity.text` |
| Intent recognized | `t = Trace`, `p.data.kind = LlmIntentRecognized` | `intentId`, `intentMessage`, `userUtterance` |
| Search issued | `t = Trace`, `p.data.kind = PluginStart` | `p.data.input.search_query`, `p.data.input.search_keywords`, `pluginName` |
| Search results | `t = Trace`, `p.data.kind = PluginResponse` | `citableContent[]` (`source`, `chunks`), `output` |
| Grounding / answer signal | `t = Trace`, `p.data.kind = AnalyticsAiMetricsSignalTraceData` | `completionState`, `triggeredGptFallback`, `rewrittenMessage`, `rewrittenMessageKeywords`, `verifiedSearchResults[]` (`url`, `rankScore`, `snippet`), `citedKnowledgeSources`, `textCitations` |
| Knowledge search state | `t = Trace`, `p.data.kind = KnowledgeTraceData` | `isKnowledgeSearched`, `completionState`, `citedKnowledgeSources`, `failedKnowledgeSourcesTypes` |

Only activities with `p.activity.type = "message"` are real user or bot turns;
activities with `p.activity.type = "event"` are system plumbing and must be
skipped for turn segmentation. Result shapes differ by trace:
`PluginResponse.citableContent[]` items have `source` + `chunks`, while
`AnalyticsAiMetricsSignalTraceData.verifiedSearchResults[]` items have `url`,
`rankScore`, `snippet`, `searchType` — a `rankScore` DOES exist there.

If a mapped field or event kind is absent in a given transcript, mark the
affected check **N/A** with a note like "field not present in this transcript"
rather than failing or guessing. This map derives from observed real exports;
field names may vary by bot configuration.

Segment the events into turns. A **turn** is a user utterance plus the bot
activity and trace events that follow it, up to (but not including) the next
user utterance. Group events into turns by walking array order.

After parsing, tell the FDE how many turns were found before starting the
per-turn walkthrough.

### Faithful transcript-to-JSON (helper script)

The transcript is a large JSON-in-`.txt` payload. To give the FDE a complete,
readable JSON copy of the WHOLE transcript — every event and field preserved,
not just the diagnostic fields — run the bundled helper rather than hand-parsing
it:

```
python scripts/transcript_to_json.py "<transcript-path>"
```

(On Windows use `python`; on POSIX use `python3`.) Run from the skill directory
`tools/ESS-Diagnostics-Skills/`. It writes a
lossless, pretty-printed `<transcript-name>-transcript.json` into the same OS
temp folder used for the other outputs (see Step 4), annotating each event with
a `_turn` and `_index` but removing nothing, and prints the absolute output path
(or an `Error: ...` line on failure — relay that to the FDE rather than
retrying blindly). This faithful dump is SEPARATE from the compact
normalized-diagnostic JSON written in Step 4; produce both.

## Step 2: Walk Each Turn Through the 5 Checks

Walk the turns in array order from Step 1. For each turn, first present the
user utterance and the bot's response, then run **CHECK-001** through
**CHECK-005** in order. Give each check a verdict of **Pass**, **Fail**, or
**N/A**, and quote the specific transcript field value that the verdict rests
on as evidence.

If an earlier check in the same turn already failed and that failure removes a
later check's precondition (for example, no intent was recognized, so no search
could fire), mark the later check **N/A** rather than **Fail**, and note which
earlier check it depends on — this avoids counting one root cause as several
failures.

### Interactive pause protocol

After running the 5 checks for a turn, do NOT advance on your own. Present a
compact structured summary, then a section menu, and STOP. Wait for the FDE.
You may NOT look at or process the next turn until the FDE responds.

First, present a **structured summary** of the turn — not just the verdicts:

- **Intent** — the recognized intent (`intentId` / `intentMessage`), or, when
  recognition did not land, the failure signal (`triggeredGptFallback`).
- **Search query** — the original user prompt AND the issued / rewritten query
  and keywords.
- **Search response** — a compact one-line-per-result list of EVERY returned
  result (not just the count): for each result show its identifier (e.g. the KB
  number from the source text), its title / short description, and its
  `rankScore`. This makes a mis-ranked but topically correct source visible at a
  glance. Then note the cited sources and what the bot actually answered.
- **Verdict strip** — a one-line summary, e.g.
  `001 Pass · 002 Pass · 003 Pass · 004 Pass · 005 Pass`.

Then present this menu and STOP — wait for the FDE before touching the next turn:

```
Drill into a section, or advance:
  1. Intent          2. Search query     3. Search results
  4. Grounding       5. Final answer
  [continue] next turn   [run all] finish without pausing   [override] a verdict
```

From this first pause onward, if the FDE types `run all`, switch to a batch
pass: auto-advance through all remaining turns without pausing, still collecting
everything the full report needs.

If the FDE picks a **section number (1–5)**, show the FULL raw transcript
evidence for that section — the complete `search_query` + `search_keywords`, the
full `verifiedSearchResults` / `citableContent` list, the full intent object, or
the complete bot answer text, as applies — PLUS the reasoning behind that
section's check verdict (why Pass / Fail / N/A). For **section 3 (Search
results)** specifically, show the **Source Text for EVERY result returned** — for
each result, its full `citableContent[].chunks` source text along with its
`source` / `url`, `rankScore`, and `searchType`. Do not show only the top result
or a snippet; list all of them, in the order returned, so the FDE can see
whether a topically correct source was retrieved but under-ranked or not cited.
Explicitly invite the FDE to OVERRIDE the verdict if their domain knowledge says
it is wrong. After a drill-down, return to the SAME turn's menu; do not
auto-advance.

If the FDE **overrides** a verdict (via `[override]` or during a drill-down),
record it: which check, the skill's original verdict, the FDE's override
verdict, and the FDE's stated reason. Carry the override (with its reason) into
the final Debug Report. An overridden verdict REPLACES the skill's verdict for
divergence and root-cause purposes in Step 3.

`continue` advances to the next turn. The loop repeats — summary, menu, hard
stop — for every turn until all turns are done, unless `run all` was chosen.

- **CHECK-001 — Intent Recognition.** **Pass** if the turn has an
  `LlmIntentRecognized` event (quote its `intentId` / `intentMessage`).
  **Fail** if there is no intent event at all, OR the turn's
  `AnalyticsAiMetricsSignalTraceData` carries `triggeredGptFallback = true`
  (quote the `triggeredGptFallback` flag) — that fallback flag is the real
  signal that intent recognition did not land. (Some exports may instead
  surface an explicit unknown-intent event; the real signal here is
  `triggeredGptFallback`.) This is the first divergence candidate — a fail here
  often explains a downstream decline.

- **CHECK-002 — Search Query Issued.** **Pass** if a `PluginStart` carries a
  non-empty `p.data.input.search_query` or `p.data.input.search_keywords`. When
  reporting this check, ALWAYS show three things:
  1. **Original user prompt** — the turn's user utterance from the
     `SynchronousIncomingActivity` `p.activity.text`. (Prefer this: the
     `userUtterance` field on the `LlmIntentRecognized` event is often empty.)
  2. **Issued search query / keywords** — the actual
     `p.data.input.search_query` and `p.data.input.search_keywords` values.
  3. **Rewrite note** — read this DIRECTLY from `rewrittenMessage` /
     `rewrittenMessageKeywords` on the `AnalyticsAiMetricsSignalTraceData`; do
     NOT infer it. If a rewrite is present and materially different from the
     issued query / original prompt, quote it (e.g. "query was rewritten to
     '<rewrittenMessage>'"); otherwise state "no rewrite." Dropping
     filler/stopwords while keeping the key search term(s) does NOT count as a
     material rewrite — mark that "no rewrite." Treat it as a rewrite only when
     the key term itself changed, was dropped, or was narrowed/broadened in a
     way that could change what gets retrieved. A bad rewrite (dropping the key
     term) can itself be the root cause.

  **Fail** if a knowledge answer was expected but no search fired. **N/A** if
  the turn is not knowledge-seeking (e.g. a greeting).

- **CHECK-003 — Search Result Topical Relevance.** **Pass** if the returned
  results are topically relevant to the query/keywords. Prefer
  `verifiedSearchResults[].rankScore` together with each result's `snippet`
  where present (a `rankScore` DOES exist on
  `AnalyticsAiMetricsSignalTraceData.verifiedSearchResults[]`). Where that is
  absent, fall back to keyword overlap between the query/keywords and the
  result's `snippet` / `source` or the `PluginResponse.citableContent[].chunks`
  — ignore common English stopwords and tokens shorter than 2 chars, and
  require a real shared term. **Fail** if results came back but none are
  relevant. **N/A** if no search was issued. When reporting this check, list
  EVERY returned result with its source text (`citableContent[].chunks`) and
  `rankScore`, not just the top hit — a topically correct source that was
  retrieved but under-ranked or not cited is itself the finding.

- **CHECK-004 — Knowledge Grounding Consistency.** Judge this from the mapped
  fields only: `isKnowledgeSearched`, `completionState`,
  `citedKnowledgeSources`, and the `verifiedSearchResults` count, versus what
  the bot's final `OutgoingActivity` `p.activity.text` does with them. **Pass**
  if the two are consistent — the answer presents substantive knowledge AND
  knowledge was searched / results were returned, OR the answer declines / says
  it lacks information AND nothing usable was retrieved. **Fail** on a
  mismatch — the answer presents specific knowledge as fact but nothing
  (`verifiedSearchResults` / `citedKnowledgeSources`) backed it (ungrounded), or
  results were returned yet the answer ignores them and declines. Quote the
  `verifiedSearchResults` count / `completionState` / `citedKnowledgeSources`
  and the relevant answer text as evidence. **N/A** if the turn is not
  knowledge-seeking.

- **CHECK-005 — Final Answer vs. Retrieved Content / Guardrails.** **Pass** if
  the bot's final `OutgoingActivity` text aligns with what was retrieved
  (`verifiedSearchResults` / `citedKnowledgeSources` / `textCitations`), OR the
  bot appropriately declined / gave a guardrail response when no relevant
  content was found. **Fail** if it answered with unsupported content (not
  backed by retrieved results), or it declined despite having relevant results.

## Step 3: Identify Divergence and Root Cause

After all turns are walked, identify the FIRST failing check across the whole
transcript — the earliest turn, then the lowest check number within that turn.
That check is the **divergence point**.

Compose a **root cause** statement derived from that first failure, citing the
evidence that supports it (the quoted query, result names, search_results count,
or answer text behind the failing check).

If NO check failed anywhere, state that explicitly: there is no divergence and
the transcript looks healthy. Do not invent a problem where the evidence shows
none.

## Step 4: Write the Outputs

After the walkthrough and diagnosis, write **three files** into a per-run
subfolder **outside the repo**, in the OS temporary directory. These outputs may
contain employee PII (utterances, retrieved policy content), so they are written
outside the repo and must NEVER be committed to source control or shared outside
approved channels.

Derive the file basename from the transcript's file name — for a transcript
`foo.txt`, the transcript name is `foo`. Write all three files into a per-run
subfolder named for the transcript:

- On **Windows**: `%TEMP%\ess-diagnostics\<transcript-name>\`
- On **POSIX**: `$TMPDIR` (or `/tmp` when `$TMPDIR` is unset)
  `/ess-diagnostics/<transcript-name>/`

Create the subfolder if it does not exist.

**1. Markdown Debug Report** — `<temp-dir>/ess-diagnostics/<transcript-name>/<transcript-name>-debug-report.md`.
This is the human-readable diagnosis. It MUST contain:

- The **confirmed problem statement** (the one confirmed with the FDE in Step 0).
- **Per-turn checklist results** — for each turn, the user utterance and the bot
  response, followed by the 5 check verdicts (**Pass** / **Fail** / **N/A**),
  each with its quoted transcript evidence.
- **FDE verdict overrides** — a section listing every verdict the FDE overrode
  during the walkthrough. For each override, list: which check, the skill's
  original verdict, the FDE's override verdict, and the FDE's stated reason. Note
  that the overridden verdicts are the ones used for the divergence and
  root-cause analysis. If there were no overrides, state that.
- The **divergence point** (from Step 3).
- The **root cause** (from Step 3).

**2. Normalized-transcript JSON** — `<temp-dir>/ess-diagnostics/<transcript-name>/<transcript-name>-normalized.json`.
This is a **normalized transcript ONLY** — a clean, flattened, reusable parsed
artifact. It carries NO diagnostic verdicts, checks, divergence, or root cause;
those live only in the markdown report. It is an array of turn objects in array
order. Each turn object contains:

- `user_utterance` — the user's prompt text, from
  `SynchronousIncomingActivity.p.activity.text`.
- `intent` — an object:
  `{ "kind": "LlmIntentRecognized" | null, "intentId": ..., "intentMessage": ..., "userUtterance": ..., "triggeredGptFallback": <true|false> }`.
  Populate `intentId` / `intentMessage` / `userUtterance` from the
  `LlmIntentRecognized` event; use `null` for any field that is absent, and
  `null` for `kind` when no intent event fired. Represent intent-recognition
  failure via `triggeredGptFallback` (read from the
  `AnalyticsAiMetricsSignalTraceData`).
- `search` — an object:
  `{ "original_prompt": ..., "query": <search_query>, "keywords": <search_keywords>, "rewritten_message": <rewrittenMessage|null>, "rewritten_keywords": <rewrittenMessageKeywords|null>, "rewritten": <true|false>, "rewrite_note": ... }`.
  `query` / `keywords` come from `PluginStart.p.data.input.search_query` /
  `search_keywords`; `rewritten_message` / `rewritten_keywords` come from
  `rewrittenMessage` / `rewrittenMessageKeywords` on the
  `AnalyticsAiMetricsSignalTraceData`. Set `rewritten` / `rewrite_note` by
  comparing the original prompt to the issued query: dropping filler/stopwords
  while the key search term(s) stay the same => `false` / `"no rewrite"`; a
  change to the key term itself (changed, dropped, or narrowed/broadened so
  retrieval could differ) => `true` with a note of what changed. Use `null` /
  empty values when no search occurred.
- `search_results` — an array of the real result objects returned. From
  `AnalyticsAiMetricsSignalTraceData.verifiedSearchResults[]` use keys `url`,
  `rankScore`, `snippet`, `searchType`; and/or from
  `PluginResponse.citableContent[]` use items with `source`, `chunks`. Emit them
  exactly as returned; an empty array if none.
- `grounding` — an object:
  `{ "isKnowledgeSearched": <bool>, "completionState": ..., "citedKnowledgeSources": [...], "triggeredGptFallback": <bool> }`,
  from the `KnowledgeTraceData` / `AnalyticsAiMetricsSignalTraceData` fields.
- `bot_text` — the bot's `OutgoingActivity.p.activity.text` for the turn.

Emit each turn object in this shape. Example of ONE populated turn object:

```json
{
  "user_utterance": "How much parental leave do I get?",
  "intent": {
    "kind": "LlmIntentRecognized",
    "intentId": "KnowledgeSearch",
    "intentMessage": "User is asking about parental leave policy",
    "userUtterance": "How much parental leave do I get?",
    "triggeredGptFallback": false
  },
  "search": {
    "original_prompt": "How much parental leave do I get?",
    "query": "parental leave entitlement",
    "keywords": "parental leave",
    "rewritten_message": null,
    "rewritten_keywords": null,
    "rewritten": false,
    "rewrite_note": "no rewrite"
  },
  "search_results": [
    {
      "url": "https://contoso.example/policies/parental-leave-2025",
      "rankScore": 0.87,
      "snippet": "Eligible employees receive up to 16 weeks of paid parental leave.",
      "searchType": "Semantic"
    }
  ],
  "grounding": {
    "isKnowledgeSearched": true,
    "completionState": "Answered",
    "citedKnowledgeSources": [
      "https://contoso.example/policies/parental-leave-2025"
    ],
    "triggeredGptFallback": false
  },
  "bot_text": "Eligible employees receive up to 16 weeks of paid parental leave."
}
```

Remember: the normalized JSON contains NO verdicts, checks, divergence, or root
cause — those belong only in the markdown Debug Report.

**3. Faithful transcript JSON** — `<temp-dir>/ess-diagnostics/<transcript-name>/<transcript-name>-transcript.json`.
This is the COMPLETE original transcript converted to readable JSON — every
event and every field preserved, nothing dropped (unlike the compact normalized
JSON above, which keeps only the diagnostic fields). Produce it with the bundled
helper introduced in Step 1:

```
python scripts/transcript_to_json.py "<transcript-path>"
```

The helper writes this file into the same per-run temp folder and prints its
absolute path. Do not hand-build this file; use the helper so the dump stays
lossless.

After writing all three files, tell the FDE the three **absolute** output file
paths in the temp directory: the markdown Debug Report, the normalized-diagnostic
JSON, and the faithful transcript JSON.
