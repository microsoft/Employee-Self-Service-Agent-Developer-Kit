# Skill: Validate a sample topic

**Preconditions:** `create-or-update-sample-topic` has produced a working-tree diff.

This skill is now **executable**. The authoritative implementation lives at
[`tools/validate_samples/`](../../../../tools/validate_samples/) and is run
the same way locally, in CI, and by this skill — so results cannot drift.

## Procedure

1. From the repo root, run:

   ```bash
   python -m tools.validate_samples --diff-base origin/main
   ```

2. Read its stdout — it is the summary block defined below.
3. If the process exit code is non-zero (any `FAIL`), **stop**. Either fix the
   diff and re-run, or post a comment on the issue explaining the blocker. Do
   not open a PR.
4. If all checks are `PASS` or `N-A`, paste the stdout block verbatim into the
   PR body's "Validation" section. The `validate-samples` GitHub Action will
   post the same block as a sticky PR comment; the agent-pasted copy is a
   courtesy for reviewers.

## Checks (enforced by the CLI)

1. **YAML well-formedness** — every changed `*.yaml` under `samples/` parses.
2. **AdaptiveDialog kind** — every changed `topic.yaml` has top-level
   `kind: AdaptiveDialog`.
3. **XML well-formedness** — every changed `*.xml` parses.
4. **Filename convention (new files only)** — new XML filenames start with
   `msdyn_` and have no trailing dot. Documented inconsistencies in
   [`samples/AGENTS.md`](../../../../samples/AGENTS.md) are whitelisted in
   [`tools/validate_samples/whitelist.yml`](../../../../tools/validate_samples/whitelist.yml).
5. **Folder convention (new folders only)** — new topic folder is PascalCase
   and contains `topic.yaml`, at least one `*.xml`, and `README.md`.
6. **Diff scope** — every changed path is under `samples/`; the diff touches
   at most one topic folder (area-level `README.md` / `AGENTS.md` are allowed).
7. **Secrets / internal URLs** — conservative regex sweep of the *full current contents* of each changed file (not just the added hunks).

**Neighbor-key parity** against the sibling reference is *not* a CLI check —
it is part of step 1 of [`create-or-update-sample-topic`](../create-or-update-sample-topic/SKILL.md).
Record the neighbor path in the PR body as instructed there.

## Output: validation summary (paste into PR body)

The CLI emits exactly this block. Do not hand-craft it.

```text
Validation
- YAML parse: PASS|FAIL|N-A
- AdaptiveDialog kind: PASS|FAIL|N-A
- XML parse: PASS|FAIL|N-A
- Filename convention (new): PASS|FAIL|N-A
- Folder convention (new, incl. README.md): PASS|FAIL|N-A
- Diff scope (samples/ only): PASS|FAIL|N-A
- Secrets / internal URLs: PASS|FAIL|N-A
```

## Out of scope (manual follow-up)

Runtime validation in Microsoft Copilot Studio / Power Platform is **not**
covered by this skill or the CLI. Importing the topic, exercising the flow,
and verifying user-visible behavior remain manual steps. See
[`docs/validation.md`](../../../../docs/validation.md).

## Stop conditions

- Any `FAIL` → do not open a PR. Fix and re-run, or stop and post a comment
  explaining the blocker.
- CLI cannot run (missing PyYAML, no git history) → stop and surface the
  underlying error; do not approximate the checks by hand.
