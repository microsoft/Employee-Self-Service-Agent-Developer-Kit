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

## Workday GA and Preview layouts

Both Workday areas use `Employee/<Scenario>/` and `Manager/<Scenario>/`.
Subgroup READMEs and GA area screenshots are not topic folders.

New GA scenarios require `topic.yaml` and `README.md`, plus the area-level
`WorkdayOSSTemplateConfigurationSetup.yaml` instead of a per-scenario XML/JSON
file. The shared configuration must be an `AdaptiveDialog` with an `OnRedirect`
trigger. New Preview scenarios retain the local connector-config requirement.
Historical folder-name exceptions exempt spelling only, not required files.

The normal single-topic scope rule remains. For the initial Workday split,
`--diff-base` permits the legacy/GA/Preview batch only when **every** original
legacy file has moved to Preview with identical Git-normalized contents, no
Preview file is missing or added, and the old tree has no remaining files.
This preserves inherited Preview conventions without exempting future additions.
An altered/incomplete copy does not qualify; unrelated sample topics remain
out of scope. `--paths-file` cannot establish that migration evidence and does
not grant the exception.

Validator maintenance can include `tools/validate_samples/`,
`tests/test_validate_samples.py` and `.github/workflows/validate-samples.yml`
alongside samples. Those specific paths are allowed by the scope check, not a
skip switch. CI still runs all sample checks and updates its validation comment
when the validator itself changes; unrelated paths remain rejected.

## Whitelist

Documented inconsistencies from
[`samples/AGENTS.md`](../../samples/AGENTS.md) are listed in
[`whitelist.yml`](whitelist.yml). Additions require a citation in
`samples/AGENTS.md` or a follow-up issue.
