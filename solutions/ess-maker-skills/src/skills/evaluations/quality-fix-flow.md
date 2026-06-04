# Eval Quality Fix Flow

This file is the single source of truth for the quality gate + fix flow.
Both `create/SKILL.md` and `update/SKILL.md` reference it. Do not duplicate
this logic in either file.

---

**If the gate returns Review (3/5) or Fail (1–2/5)**, the subagent's report
will include the flagged cases table. Show the user this prompt and wait for
their response:

> What would you like to do?
> - **A** — Fix all flagged cases
> - **B** — Pick which ones to fix
> - **C** — Push as-is and fix later

When the user responds:

- **A (fix all)**: Run the fix flow below for all flagged cases.
- **B (pick some)**: Ask the user which case numbers to fix (e.g. `1, 3, 5`).
  Run the fix flow below for only those cases.
- **C (push as-is)**: Proceed to the review step.

**Fix flow (A or B)**:
1. For each selected case, read the current file and note the existing `input`
   and `expectedOutput` values (these become the **Before** values in the summary).
2. Devise a fix based on the issue description from the flagged cases table.
   Edit the file with the new values.
3. After all edits are done, show a summary of what changed:

   > **Fixed {n} case(s):**
   >
   > | # | File | Dimension | Field | Before | After |
   > |---|------|-----------|-------|--------|-------|
   > | 1 | `{filename}.mcs.yml` | {dimension} | input | `{old input}` | `{new input}` |
   > | 2 | `{filename}.mcs.yml` | {dimension} | expectedOutput | `{old output}` | `{new output}` |

4. Re-invoke the validate subagent, passing the agent slug, category, and the
   list of edited file paths. The subagent will determine the appropriate
   scoring scope and path (script or fallback). Display the updated scores
   before proceeding.

**If the gate passes (4–5/5)** with some dimensions at 3/5 or below, the
subagent will note them as optional improvements but will not block. Proceed
to the review step without running the fix flow.

**Do not proceed to the review step until quality validation has returned
results and any fixes are complete.**
