## Description
<!-- What does this PR do? Why is it needed? -->

## Related issue
<!-- Use one of: `Fixes #123`, `Closes #123`, or `Refs #123` so the issue closes on merge. -->
Fixes #

## Type of change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactor / cleanup

## Testing
<!-- How was this change tested? -->

## Pre-PR Checklist (REQUIRED)

Tick every box. If something doesn't apply, write "N/A — <reason>" next to it.

- [ ] **Rebased on latest `main`** — ran `git fetch origin && git rebase origin/main`
- [ ] **Files changed tab reviewed** — only files I intended to change are listed; no accidental deletions
- [ ] **Local lint / tests pass** — `pytest tests/ -q` clean and `python solutions/ess-maker-skills/scripts/flightcheck/cli.py --help` parses, OR I noted below why end-to-end testing wasn't possible
- [ ] **No references to files outside the repo** — header comments and docs don't point at internal source-of-truth files
- [ ] **Defaults match repo conventions** — output paths default to `workspace/flightcheck/...`; risky operations (writes, deletions, destructive API calls) are opt-in via explicit flags, not opt-out
- [ ] **FlightCheck integration** — new checks are wired into a scope in `solutions/ess-maker-skills/scripts/flightcheck/cli.py` (`SCOPE_MAP` and `FULL_SCOPE`); new tests added under `tests/flightcheck/checks/`
- [ ] **API tier registry honored** — new external API calls reference the tier in `tests/fixtures/cassettes/INDEX.md`; any new tier rows added there with rationale (see `solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md`)
- [ ] **Docs updated** — relevant `README.md` / `AGENTS.md` reflect the change

> **Why "rebased on latest `main`" matters:** Stale branches can silently
> delete files added after your branch was cut. We've already caught one
> case of this. GitHub branch protection enforces this rule automatically.

## Checklist
- [ ] My code follows the existing style
- [ ] I have added/updated tests where applicable
- [ ] I have updated documentation as needed

<!-- The Microsoft CLA bot will comment automatically if a CLA signature is required. No checkbox needed. -->