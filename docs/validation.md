# Samples static validation

Static validation for changes under [`samples/`](../samples/). Runs locally,
in PRs (via [`.github/workflows/validate-samples.yml`](../.github/workflows/validate-samples.yml)),
and as a pre-PR step in the
[`validate-sample-topic`](../.github/agents/skills/validate-sample-topic/SKILL.md)
agent skill. All three call the same CLI so results cannot drift.

## What is in scope

The validator enforces, for the diff between the PR branch and `main`:

| Check | What it verifies |
|---|---|
| YAML parse | Every changed `*.yaml` under `samples/` parses (PyYAML safe-load). |
| AdaptiveDialog kind | Every changed `topic.yaml` has top-level `kind: AdaptiveDialog`. |
| XML parse | Every changed `*.xml` under `samples/` is well-formed XML. |
| Filename convention (new) | New XML filenames start with `msdyn_` and have no trailing dot. |
| Folder convention (new) | New topic folders are PascalCase and contain `topic.yaml`, at least one `*.xml`, and `README.md`. |
| Diff scope | Every changed path is under `samples/`; the diff touches at most one topic folder (area-level `README.md` / `AGENTS.md` are allowed). |
| Secrets / internal URLs | Conservative regex sweep of the full current contents of each changed file (AWS keys, JWTs, bearer tokens, private-key blocks, `*.corp.microsoft.com`, etc.). Pre-existing matches in a touched file will fail the check; removed secrets are not reported here. |

Documented exceptions from [`samples/AGENTS.md`](../samples/AGENTS.md) are
codified in [`tools/validate_samples/whitelist.yml`](../tools/validate_samples/whitelist.yml).

## What is out of scope

The validator is **static only**. It does **not** cover:

- Importing the topic into Microsoft Copilot Studio / Power Platform.
- Executing Power Automate flows, Dataverse calls, or external APIs.
- Schema validation of `topic.yaml` against Copilot Studio's internal
  AdaptiveDialog schema (not publicly contracted).
- XSD validation of ESS Template Configuration XML (no published XSD).
- Semantic correctness of trigger phrases, `modelDescription`, or adaptive
  card UX.

**Runtime validation in Power Platform remains a manual follow-up step.**
Importing the topic, exercising the flow, and verifying user-visible
behavior must be done by a human in a target environment before the change
is considered production-ready.

## How to run it

Local, against `main`:

```pwsh
python -m tools.validate_samples --diff-base origin/main
```

Local, against an explicit changed-paths file (each line `<STATUS>\t<path>`):

```pwsh
python -m tools.validate_samples --paths-file changed.txt
```

JSON output for tooling:

```pwsh
python -m tools.validate_samples --diff-base origin/main --json
```

Exit code is non-zero if any check reports FAIL.

## How to read failures

The summary block lists each check as `PASS`, `FAIL`, or `N-A`. Sub-bullets
under a `FAIL` line name the specific path and reason. Common cases:

- **YAML parse FAIL** — usually unquoted special characters (`@`, `:`, tabs).
  Quote the value or escape it.
- **AdaptiveDialog kind FAIL** — `topic.yaml` is missing the top-level
  `kind: AdaptiveDialog`. Add it.
- **XML parse FAIL** — unclosed tag, mismatched element, or an invalid
  XML declaration. Open the file and re-parse with any XML editor.
- **Filename convention FAIL** — a *new* XML file does not start with
  `msdyn_`. Rename it before opening the PR. Existing nonconforming names
  are preserved (whitelist).
- **Folder convention FAIL** — a new topic folder is missing `topic.yaml`,
  any `*.xml`, or `README.md`, or the folder name is not PascalCase.
- **Diff scope FAIL** — the PR touches paths outside `samples/`, or
  touches more than one topic folder. Split the PR.
- **Secrets / internal URLs FAIL** — review the flagged location (path
  and line; the matched value is redacted). The check scans the whole
  current file, so a match may be pre-existing rather than introduced by
  the PR — verify either way before merging. If it is a false positive
  (rare; patterns are conservative), open an issue and do not whitelist
  silently.

## CI integration

[`.github/workflows/validate-samples.yml`](../.github/workflows/validate-samples.yml)
runs on every PR that touches `samples/**`, `tools/validate_samples/**`,
or the workflow file. It posts a sticky PR comment with the same summary
block (header `samples-validation`, so re-runs update in place) and fails
the job on any `FAIL`. Once stable, mark "Validate samples / Static
validation (samples/)" as a required check on `main`.
