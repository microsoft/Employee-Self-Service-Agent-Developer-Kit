# Skill: Validate a sample topic

**Preconditions:** `create-or-update-sample-topic` has produced a working-tree diff.

Run every check below. Record PASS / FAIL / N-A for each. Block the PR on any FAIL except where noted.

## Checks

1. **YAML well-formedness** — every changed `topic.yaml` parses without error.
2. **AdaptiveDialog kind** — `topic.yaml` has top-level `kind: AdaptiveDialog`.
3. **Neighbor-key parity** — a new `topic.yaml` includes the top-level keys present in its sibling reference (e.g., `inputs`, `modelDescription`, `beginDialog`). Missing keys are FAIL.
4. **XML well-formedness** — every changed `*.xml` parses.
5. **Filename convention (new files only)** — new XML filenames start with `msdyn_`. Existing non-conforming names are **not** flagged.
<<<<<<< HEAD
6. **Folder convention (new folders only)** — new topic folder is PascalCase and contains at least `topic.yaml` and one `*.xml`.
=======
6. **Folder convention (new folders only)** — new topic folder is PascalCase and contains at least `topic.yaml`, one `*.xml`, and a `README.md` (see README expectations in `samples/AGENTS.md`).
>>>>>>> main
7. **Diff scope** — `git diff --name-only` shows only paths under a single `samples/<Area>/.../<TopicFolder>/`. Anything outside `samples/` is FAIL.
8. **No secrets / no internal URLs** — scan the diff for tokens, keys, and non-public hostnames.

## Output: validation summary (paste into PR body)

```text
Validation
- YAML parse: PASS|FAIL
- AdaptiveDialog kind: PASS|FAIL|N-A
- Neighbor-key parity: PASS|FAIL|N-A (reference: <path>)
- XML parse: PASS|FAIL
- Filename convention (new): PASS|FAIL|N-A
<<<<<<< HEAD
- Folder convention (new): PASS|FAIL|N-A
=======
- Folder convention (new, incl. README.md): PASS|FAIL|N-A
>>>>>>> main
- Diff scope (samples/ only): PASS|FAIL
- Secrets / internal URLs: PASS|FAIL
```

## Stop conditions

- Any FAIL → do not open a PR. Fix and re-run, or stop and post a comment explaining the blocker.
