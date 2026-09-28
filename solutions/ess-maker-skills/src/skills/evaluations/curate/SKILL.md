# Curate Knowledge-Grounded Evaluation Test Sets

Create evaluation test sets grounded in a local knowledge source and a separate
agent-instructions file. The active GitHub Copilot session is the reasoning
host; the curator submodule is the authoritative workflow. This wrapper only
supplies the Maker Kit host contract and lifecycle handoff. Never duplicate the
curator instructions here or reimplement them in the host.

This route is for knowledge-source-grounded creation only. Use local-file mode
only for v1: require both a local knowledge source (files or a folder) and an
agent-instructions file. It does not replace configured-topic creation or
named-scenario catalogue generation.

## Step 1: Require both inputs

Collect missing inputs one at a time:

1. If the local knowledge source is missing, ask exactly one question for it,
   then wait.
2. After the knowledge source is available, if the agent-instructions file is
   missing, ask exactly one question for the agent instructions, then wait.

Do not infer a path, continue with one input, combine the questions, or ask for
a scenario instead.

## Step 2: Run the curator preflight

From `solutions/ess-maker-skills/` on a Windows-compatible host, run:

```powershell
py -3.12 scripts/eval_curator_submodule.py status --repo-root ../..
```

The command path is `scripts/eval_curator_submodule.py status`; use `python`
instead of `py -3.12` only when required by the host's portable Python
convention.

Parse exactly one JSON result from standard output. If the command fails, the
JSON is invalid, `available` is not `true`, or the contract is missing or
incompatible, show the returned error message and stop. Do not attempt a
fallback implementation.

Require `supportsHostOutputOverride` and `supportsHostLifecycleHandoff`; both
capability flags are exactly `true`. If either capability flag is false or
missing, explain that this is an incompatible curator contract and stop before
reading or invoking `skillPath`.

Only after all preflight checks pass, read `skillPath` and
`structuralValidatorPath` from the successful result. **Read the returned curator skill in full**
before taking any curation action. Treat the returned paths as authoritative
and do not guess submodule paths.

## Step 3: Run the hosted curator flow

Follow the returned curator skill completely with these host parameters:

```text
hostOutputRoot=workspace/evaluations
hostLifecycleHandoff=Maker Kit validation, maker review choice, promotion, scoped push, and post-success run/results lifecycle
```

Keep version 1 in local-file mode only. The active GitHub Copilot session must
perform the curator's source grounding, agent-instructions grounding, topic
confirmation, generation, preview, structural validation, and quality rules.
Run structural validation with the returned `structuralValidatorPath`.

Do not weaken confirmation or validation gates. Do not reinterpret the
curator's generation rules. After receiving its structured hosted handoff, skip
the curator local-only wrap-up because the Maker Kit owns the remaining
lifecycle.

## Step 4: Validate, then ask for maker review

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
next actions. Do not duplicate any of those commands, questions, or behaviors
in this wrapper.

Failed or partial validation stays local and blocks lifecycle handoff,
promotion, push, and run. A missing or incompatible curator submodule also
stops the flow.
