# validate_samples

Static checks for changes under [`samples/`](../../samples/). Mirrors the eight
checks specified in
[`.github/agents/skills/validate-sample-topic/SKILL.md`](../../.github/agents/skills/validate-sample-topic/SKILL.md).

Scope: well-formedness, file/folder conventions, diff confinement, and a
conservative secrets/internal-URL sweep. **Runtime validation in Power Platform
is out of scope and remains a manual follow-up step.**

## Run locally

```pwsh
# Against a base branch
python -m tools.validate_samples --diff-base origin/main

# Against an explicit changed-paths file (each line: "<STATUS>\t<path>")
python -m tools.validate_samples --paths-file changed.txt

# JSON output for tooling
python -m tools.validate_samples --diff-base origin/main --json
```

Exit code is non-zero if any check reports FAIL.

## Whitelist

Documented inconsistencies from
[`samples/AGENTS.md`](../../samples/AGENTS.md) are listed in
[`whitelist.yml`](whitelist.yml). Additions require a citation in
`samples/AGENTS.md` or a follow-up issue.
