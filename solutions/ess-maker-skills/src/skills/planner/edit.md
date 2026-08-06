# Planner — Editing the plan (the Markdown round-trip)

The Plan's human view — `workspace/plan/ESS-scenario-plan.md` — is not just a
read-out. It is the **editable surface** a Plan editor works with. The CLI
regenerates it from `plan.json` after every change, and the editor can revise it
and have those revisions **reconciled back into the plan**. `plan.json` stays the
source of truth; the Markdown is how a human edits it.

## Present it as an editable file

Whenever you've created or changed the plan, show the editor the Markdown plan and
tell them they can edit it. Refer to it as the **"ESS scenario plan"** (its file is
`workspace/plan/ESS-scenario-plan.md`) — a file they can open, read, and edit, or
download and re-upload. Offer the two ways to change it:

1. **Edit the Markdown directly** — open `ESS-scenario-plan.md`, change it (add a
   task, tick one off, retitle, delete), save (or re-upload an edited copy), then
   tell me *"I edited the plan"*.
2. **Just say what to change** in chat — *"add a task to bring in the parental-leave
   knowledge source"*, *"mark Workday SSO done"*, *"drop the veteran-info write"*.

Speak in terms of the plan and its tasks — never mention `plan.json`, the CLI, or
which files you read.

## Reconcile a direct Markdown edit back into the plan

When the editor says they edited the Markdown (or re-uploads it), reconcile it —
**do this before running any command that regenerates the file, so you never
overwrite their edits**:

1. **Read both.** Read the edited `ESS-scenario-plan.md` and the current plan
   (`python scripts/planner/cli.py summary`). The Tasks table is keyed by task
   **id** (the `#` column) — use it to line rows up.
2. **Diff by id.** Work out, per task, what changed:
   - **Added** row (no existing id / a new one) → a new task.
   - **Removed** row → a deletion.
   - **Retitled / re-described** → a content edit.
   - **Role / owner** column changed → a reassignment.
   - **State** column changed (e.g. a ticked checkbox → Completed) → a state change.
   - Changes under **Intent** (scenarios, systems, goals) or **Scenario
     dependencies** → context edits.
3. **Apply each change through the CLI** so writes stay atomic and validated —
   never hand-edit `plan.json`:

   ```
   python scripts/planner/cli.py add-task --id <next T#> --title "..." --description "..." --role <grounded-role> [--produces ...] [--consumes ...]
   python scripts/planner/cli.py update-task --id <T#> [--title "..."] [--description "..."] [--produces a,b] [--consumes a,b]
   python scripts/planner/cli.py remove-task --id <T#>
   python scripts/planner/cli.py assign --task <T#> --role <role> [--person <oid>]
   python scripts/planner/cli.py set-state --task <T#> --state Completed
   python scripts/planner/cli.py add-scenario --id <id> --label "..."
   python scripts/planner/cli.py set-context --key <k> --value "..." --group <group> --description "..." --source User
   ```

4. **Re-render and show it back.** Applying a change regenerates
   `ESS-scenario-plan.md`; run `validate`, then show the refreshed plan — *"I saw
   your changes and updated the plan — here it is again"*, calling out what changed
   (e.g. "added *Add parental-leave knowledge source*").

## Ask where ambiguous — do not guess

Grounding and the plan's rules still hold when reconciling. Stop and ask the editor
a targeted question (rather than inventing) when an edit is unclear, for example:

- A **new task with no clear role** — the role is Learn-grounded, not invented; ask
  which role, or pool it to a role you can ground, but don't fabricate one.
- A **retitled row you can't map** to an existing id — ask whether it's a rename of
  an existing task or a brand-new one.
- A task **marked Completed that still has unmet dependencies**, or whose
  `produces` were never captured — confirm it's really done.
- A **deletion that would orphan** a dependency (something else consumes what it
  produced) — confirm before removing.
- A **new scenario / system** that maps to no ESS category, or a write with
  governance implications — confirm scope, per the interview rules.
- An **Intent line you can't classify** into a group — ask what it means.

Only assign new ids the plan doesn't already use (next `T#`); **reuse the id shown
in the row** for edits so you change the right task. Keep the plan valid after every
reconcile.

## Chat-intent edits

If the editor states the change in chat instead of editing the file, apply it the
same way (the matching CLI command above), confirm, and show the refreshed plan.
Same grounding and same "ask where ambiguous" rule.
