# Curate Knowledge-Grounded Evaluation Test Sets

Create evaluation test sets grounded in a knowledge source (local files or a
connected knowledge base) and a separate
agent-instructions file. The active GitHub Copilot session is the reasoning
host; the vendored curator skill is the authoritative workflow. This wrapper
only supplies the Maker Kit host contract and lifecycle handoff. Never duplicate
the curator instructions here or reimplement them in the host.

This route is for knowledge-source-grounded creation only. It requires an
agent-instructions file plus a knowledge source, and the knowledge source may
be local files (a folder or files) or a connected knowledge base (for example
ServiceNow or SharePoint) reachable via a search/fetch tool in the session. It
does not replace configured-topic creation or named-scenario catalogue
generation.

The curator content is vendored directly in this repository — there is no Git
submodule to initialize and no version handshake to negotiate. The two vendored
files live at fixed paths under this skill folder:

```text
curator/curate-evals.md          # the curator workflow
curator/check_eval_artifacts.py  # the structural validator
```

## Step 1: Choose a mode, then require both inputs

Collect missing inputs one at a time:

1. First, ask the maker whether to curate from local files/folder or from
   their connected knowledge base (for example ServiceNow or SharePoint), then
   wait.
2. After the mode is chosen, collect the inputs that mode needs, one at a
   time, waiting after each: for local mode, ask for the folder/files path;
   for connected mode, confirm which connected knowledge base or tool to use
   (only ask this if more than one is available in the session).
3. In both modes, the agent-instructions file is required. If it is missing,
   ask exactly one question for the agent instructions, then wait.

Do not infer a path, continue with one input, combine the questions, skip the
mode question, or ask for a scenario instead.

## Step 2: Confirm the vendored curator is present

Resolve these two paths relative to this skill folder
(`src/skills/evaluations/curate/`):

```text
curator/curate-evals.md
curator/check_eval_artifacts.py
```

Confirm both files exist before taking any curation action. If either file is
missing, show this message and stop — do not attempt a fallback implementation
and do not route to another generator:

> The knowledge-source curator is not available in this workspace. Expected
> these files under `src/skills/evaluations/curate/curator/`:
>
> - `curate-evals.md`
> - `check_eval_artifacts.py`
>
> Re-clone or restore the Maker Kit so the vendored curator files are present,
> then try again.

Only after both files are confirmed present, **read `curator/curate-evals.md` in
full** before taking any curation action. Treat these fixed paths as
authoritative.

## Step 3: Run the hosted curator flow

If the maker chose the connected knowledge base mode, resolve and confirm the
bound connection first (see "Resolve and confirm the connected knowledge base"
below) before proceeding into the curator body's Step 3b. Skip that gate
entirely in local-file mode.

Follow the vendored curator skill (`curator/curate-evals.md`) completely with
these host parameters:

```text
hostOutputRoot=workspace/evaluations
hostLifecycleHandoff=Maker Kit validation, maker review choice, promotion, scoped push, and post-success run/results lifecycle
structuralValidatorPath=src/skills/evaluations/curate/curator/check_eval_artifacts.py
```

Proceed in the mode the maker chose (local-file or connected knowledge base);
the vendored curator skill branches on mode. The active GitHub Copilot session
must perform the curator's source grounding, agent-instructions grounding, topic
confirmation, generation, preview, structural validation, and quality rules.
Run structural validation with the vendored validator at the
`structuralValidatorPath` above.

### Resolve and confirm the connected knowledge base

Only when the maker chose connected knowledge base mode: before proceeding into
the curator body's Step 3b (discovery/grounding), run the resolver CLI shim
from `solutions/ess-maker-skills/`:

```powershell
py -3.12 scripts/resolve_kb_connection.py
```

Parse its single JSON result. Never proceed into Step 3b before this gate
completes.

- `status == "error"` or `status == "none_bound"` — stop and report the exact
  reason from the shim's `error` field (or, for `none_bound`, that no
  Graph-connector knowledge source is bound to this agent) to the maker. Do
  not attempt a fallback implementation and must not silently fall back to
  local-file mode. The maker must explicitly restart mode selection at Step 1
  themselves if they want local-file mode instead.
- `status == "ok"` with exactly one connection — show the maker that
  connection's `connection_name` (and its `state`/`status` when present) and
  require explicit confirmation before proceeding into Step 3b.
- `status == "ok"` with more than one connection — list all of them
  (`connection_name` plus `state`/`status` for each) and require the maker to
  pick one or more before proceeding into Step 3b.

Only after the maker's confirmation or choice, hand off the confirmed
`connection_name`(s) into the curator body's existing Step 3b/3c flow as the
connected-KB source identifier it already expects.

The vendored curator skill's "Host integration contract" section describes
resolving paths relative to a curator-package root that the submodule packaging
once provided. That resolution does not apply here: the curator is vendored
in-repo and this wrapper supplies the fixed `structuralValidatorPath` above
directly. Use the paths this wrapper provides and ignore the vendored body's
package-relative path-resolution instructions.

Do not weaken confirmation or validation gates. Do not reinterpret the
curator's generation rules. After receiving its structured hosted handoff, skip
the curator local-only wrap-up because the Maker Kit owns the remaining
lifecycle.

## Step 4: Validate, then ask for maker review

### Accept only a complete hosted handoff

Accept the curator handoff only when it is well formed, contains one or more
generated set entries and all paths required by the curator flow,
`structuralValidation` is exactly `passed`, and `qualityValidation` is exactly
`passed`. A missing set, missing field, unexpected validation value, or
incomplete curator run is a malformed, failed, or partial handoff.

Before invoking Maker Kit validation or handing any set to the update skill,
serialize the exact structured handoff to JSON and pipe it to this deterministic
check from `solutions/ess-maker-skills/`:

```powershell
$handoffJson | py -3.12 scripts/eval_curator_handoff.py validate --repo-root ../..
```

Use `python` instead of `py -3.12` only when required by the host's portable
Python convention. Parse exactly one JSON result. Continue only when the
command exits successfully and `valid` is exactly `true`; then use only its
normalized `sets[].folder` and `sets[].csv` paths for every later validation
and lifecycle handoff. Stop before Maker Kit validation if any path contains
traversal, resolves outside `workspace/evaluations`, crosses a symlink or
junction escape, is missing, uses `exports/` as a set folder, places a CSV
outside `workspace/evaluations/exports/`, or otherwise has malformed
structure. Never repair, reinterpret, or substitute a rejected path.

For every entry in `sets`, always run the Maker Kit validator in the next step,
even when the curator reports `qualityValidation: passed`. Every generated set
must then have successful Maker Kit quality validation before any lifecycle
handoff.

Any malformed, failed, or partial handoff, structural validation failure, or
Maker Kit quality validation failure must remain local. It must not enter the
update skill or proceed to promotion, push, cleanup, or run.

For each generated set in the curator handoff:

1. Read `src/skills/evaluations/validate/SKILL.md` and invoke its quality
   validation for the exact returned set folder.
2. Follow `src/skills/evaluations/quality-fix-flow.md` for any required or
   user-selected fixes.
3. After validation passes for all generated sets, read
   `src/skills/evaluations/update/SKILL.md`.

Use the available structured choice control to ask:

> What would you like to do with these test sets?

Offer exactly:

1. **Edit the test sets myself**
2. **Send them to a judge or SME for feedback**
3. **Keep them unchanged**

Wait for the maker's response. Do not enter update Step 7 before this choice.

Route the response through the update skill without implementing any mutation,
synchronization, review metadata, or push behavior in this wrapper:

- **Edit the test sets myself** — hand the exact generated workspace set
  folders to the update skill as explicitly preselected sets. This curator
  gate has already selected the edit path, so update Step 2 must show the
  relevant preview and cases, skip its generic Edit/SME/Keep continuation
  question, and proceed directly to case selection and editing. Complete Steps
  2 through 6, including YAML/CSV synchronization and validation, without
  rediscovery or set reselection. When that path completes, return to this
  maker review gate and wait for another choice.
- **Send them to a judge or SME for feedback** — hand the exact generated
  workspace set folders to update **Flow R1** as explicitly preselected sets.
  After Flow R1 records the local review request, continue through update
  **Step 7 onward**.
- **Keep them unchanged** — hand the exact generated workspace set folders to
  update **Step 7 onward** as explicitly preselected sets.

The update skill is the one authoritative flow for all post-validation
edit/synchronization/validation, review metadata, keep-local, setup check,
promotion, scoped dry-run and push, cleanup, final status, and successful-push
next actions. It is the sole source of truth for those lifecycle gates. Do not
duplicate any of those commands, questions, or behaviors in this wrapper.

Topic confirmation, generation preview, and the maker review choice are not
push approval. Only explicit push approval inside update Step 7 authorizes the
update skill to continue toward staging and push.

Failed or partial validation stays local and blocks lifecycle handoff,
promotion, push, and run. A missing vendored curator file also stops the flow.
