# Skill: Triage a samples GitHub issue

**When to use:** any issue labeled `area:samples`, or whose body references `samples/`.

**Preconditions:** you have read [`samples/AGENTS.md`](../../../../samples/AGENTS.md).

## Inputs

- Issue title, body, labels, author, linked items.
- Read access to `samples/`.

## Procedure

1. **Determine request kind.**
   - `new-topic` — issue asks for a topic that does not exist under `samples/`.
   - `fix-topic` — issue references an existing path under `samples/`.
2. **Identify target.** Area (ISV), sub-grouping (`Employee` / `Manager` / `Extended` / flat), topic folder name. Verify the path actually exists for `fix-topic`.
3. **Required-info check.**
   - **New topic** must include:
     - Target area / ISV.
     - Proposed topic folder name (or enough context to derive one).
     - User scenario / expected behavior.
     - At least 2 sample user utterances.
     - Required inputs/outputs or referenced API/system of record.
   - **Fix topic** must include:
     - Target path under `samples/` (folder or file).
     - Current behavior (what is wrong).
     - Expected behavior or example.
4. **Classify** into exactly one of:
   - `actionable-new-topic`
   - `actionable-fix`
   - `needs-clarification` — required info missing.
   - `blocked` — depends on something outside repo control.
   - `duplicate` — another open issue covers it.
   - `out-of-scope` — not about `samples/`, or asks for renames, deletions, cross-area refactors, or changes outside `samples/`.
   - `not-actionable` — spam/empty.
5. **Act on the classification:**
   - `actionable-*` → apply `agent:eligible`, hand off to `create-or-update-sample-topic`.
   - `needs-clarification` → apply `agent:needs-info`, post a comment listing the specific missing fields. Do not modify files.
   - `blocked` / `out-of-scope` / `duplicate` / `not-actionable` → apply the matching label, post a short explanation referencing `samples/AGENTS.md`. Do not modify files.

## Outputs

- Classification label.
- Target path (for actionable cases).
- Either: handoff packet to the next skill, OR a posted comment, OR a labeled stop.

## Stop conditions

- Stop and ask if the area, sub-grouping, or topic folder is ambiguous.
- Stop if the request would touch anything outside `samples/`.
- Stop if the request asks to rename or delete existing files/folders.
