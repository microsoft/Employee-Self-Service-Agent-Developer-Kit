# Review report format

The maker-facing output templates for the `topics/review` skill — the single-topic report, the single-issue
detail view, and the scoped roll-up. These are the **exact** shapes to present; follow them verbatim. The
**Speak the maker's language** rule (in the skill's Rules) governs all of them: hide the review system's
vocabulary (lens, detector, reachability tags, rule IDs, catalog paths); the maker's own Power Fx, action
kinds, field names, step names, and `topic.mcs.yml:line` are their language and are allowed where noted.

## Single-topic report (Step 9)

Follow this format exactly. Do **not** add prose between sections, narrate what you checked, or explain the
process. Locate each finding by the **step/action it lives in** (its display name), never a node id or line
number.

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

| #   | Severity | Where (step)        | Potential issue                | Suggested fix   |
| --- | -------- | ------------------- | ------------------------------ | --------------- |
| 1   | Medium   | "{step name/label}" | {what might be wrong — hedged} | {suggested fix} |

The table carries each finding — do not restate rows in prose. Add one short line under the table **only**
when a fix needs a Power Fx snippet or nuance the cell can't hold.

### 9d — Close

End with this **verbatim**:

> Advisory — you can publish as-is. To fix one, type `/update` and name its step; re-run `/review` after
> edits to re-check.

## Issue detail view (when the maker asks about one issue)

When the maker asks to see or fix a **specific issue** — "more details on X", "explain this one", "how do I
fix it" — present that finding in this structured shape, **not flowing prose**. Pull the finding from its
catalog (read the cited `files[].lines` if you need the exact expression to reference — a targeted read, not
a re-analysis). One block per issue — a bold header line (`{plain-language title}` · {High/Medium/Low} ·
`{topic-stem}.mcs.yml:{line}` "{step display name}"), then:

- **Proposed fix:** {concise prose; technical language allowed — name the expression/property and the change}
- **Why fix it this way:** {one or two plain sentences}

This is the one place the maker's own code and `file:line` appear. Still keep the review system's vocabulary
out (no rule IDs, reachability tags, "lens").

## Scoped roll-up (S-4)

Show a scope-level summary, then a per-topic table and an issue-type rollup — **not** each topic's full
findings table. Same exact-template discipline as the single-topic report: use the verbatim lines below, do
not improvise the verdict, add prose between sections, or narrate the analysis (including todo-list activity).

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

| Topic        | High | Medium | Low |
| ------------ | ---- | ------ | --- |
| {topic-stem} | {n}  | {n}    | {n} |

`{k} other topics were clean.`

Then the **issue-type rollup** — the same active findings grouped by their plain-language issue type, so the
maker sees which problems recur across the scope. Order by severity, then count:

| Issue                       | Topics affected | Severity          |
| --------------------------- | --------------- | ----------------- |
| {plain-language issue type} | {count}         | {High/Medium/Low} |

Close with this **verbatim**:

> To see a topic's details, ask to review it by name (e.g. `review {topic-stem}`) — its findings are saved.
> To fix one, type `/update` and name the topic and step. Re-run to re-check.

**Drill-down:** if the maker asks to see one topic, render that topic's 9c table from its
`{topic-stem}-catalog.json` (active set). If they ask about a **specific issue**, use the **Issue detail
view** above — no re-analysis, only a targeted read of the cited line to quote the current expression.
