# validate_samples

Static checks for changes under [`samples/`](../../samples/). Implements the
seven automatable checks specified in
[`.github/agents/skills/validate-sample-topic/SKILL.md`](../../.github/agents/skills/validate-sample-topic/SKILL.md):
YAML parse, AdaptiveDialog kind, XML parse, filename convention (new),
folder convention (new, incl. `README.md`), diff scope (`samples/` only),
and a conservative secrets / internal-URL sweep.

Other items in the skill — notably neighbor-key parity and any runtime
validation in Power Platform — are **not** enforced by this CLI and remain
manual follow-up steps.

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
