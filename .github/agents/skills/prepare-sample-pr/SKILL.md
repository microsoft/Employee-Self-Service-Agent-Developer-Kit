# Skill: Prepare the PR

**Preconditions:** all `validate-sample-topic` checks PASS.

## Branch

```
agent/samples/issue-<issue-number>-<short-slug>
```

`<short-slug>` is a kebab-case 2–5 word summary derived from the issue title.

## Commit message

```
samples(<Area>/<Topic>): <short summary> (#<issue-number>)
```

Examples:

- `samples(Facilities/EmployeeInviteGuest): tighten modelDescription wording (#123)`
- `samples(WorkdayCustomEngineAgent/Employee/EmployeeGetBenefitsSummary): add new topic (#124)`

## PR title

Same as the commit message.

## PR body template

```markdown
## Summary
<one paragraph tied to the issue>

## Changes
- <bullet list of files added/changed>

## Reference topic used
<path to the neighbor topic used as shape reference>

## Validation
<paste the validation summary block from validate-sample-topic>

## Linked issue
Fixes #<issue-number>
```

## Rules

- One issue → one PR.
- Do not enable auto-merge.
- Do not request reviewers automatically — leave for humans / CODEOWNERS.
- Do not force-push after a human has reviewed.
- Apply labels: `area:samples` and `agent:eligible`.

## Stop conditions

- Stop if the diff is empty.
- Stop if the branch name or PR title cannot be derived from the issue.
