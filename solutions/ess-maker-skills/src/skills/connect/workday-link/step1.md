# Workday Link Step 1: Verify the Extension

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This flow wires the current agent to a Workday extension that is already
installed in this environment. It does not install the extension pack,
configure the Workday tenant, or provision connections — that's the setup
orchestrator's job.

Read `.local/config.json` for the agent details (`dataverseEndpoint`,
`agent.botId`, `agent.name`, `agent.schemaName`, `agent.isManaged`).

**After every checkpoint run in this flow, show its result in chat first.**
As soon as a `python scripts/flightcheck/cli.py --checkpoint <ID>` run
returns, render the result to the user per
`src/skills/setup/shared/checklist-updater.md` §U.0–U.0a — the compact
result table and, for any `Manual`, `Warning`, or `NotConfigured` row, its
full verification steps — before you show any later **Message** or branch
on the outcome. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees the finding.

---

## 1.0 — Initialize state

If `.local/connect/workday-link/steps.md` does not exist, copy
`src/skills/connect/workday-link/steps.md` to
`.local/connect/workday-link/steps.md`.

**If step 1 is already checked** in that file, skip to the first unchecked
step: read `src/skills/connect/workday-link/step2.md` if step 2 is
unchecked, otherwise read `src/skills/connect/workday-link/step3.md`. Stop
following this file.

---

## 1.1 — Check the extension pack and connections

Run each checkpoint in isolation:

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
python scripts/flightcheck/cli.py --checkpoint WD-CONN-012
python scripts/flightcheck/cli.py --checkpoint DV-CONN-001
```

This does not re-check `WD-CONN-AUTH-001` — that's a manual attestation on
the environment's shared Workday connection, already confirmed when the
extension was first installed. It isn't re-asked per agent that links to it.

Render all three results per the convention above before continuing.

**If all three report `PASSED`:**

Update `.local/connect/workday-link/steps.md` — change step 1 from
`- [ ]` to `- [x]`.

The extension was installed to Dataverse independently of this agent's
local workspace, so its topics (including the Workday system topic step 2
needs to wire) may not exist on disk yet. Refresh the local workspace before
continuing:

**Message:**

Extension confirmed. Refreshing your agent's local files to pick up the
Workday topics...

**End message.**

```
python scripts/fetch_and_setup.py --refresh
```

**If the refresh fails:** show the exact error and stop — step 2 cannot
resolve the Workday system topic without an up-to-date local workspace.

**If it succeeds:** continue to step 2
(`src/skills/connect/workday-link/step2.md`).

**If any report anything other than `PASSED`** (`FAILED`, `WARNING`,
`NotConfigured`, or `Skipped`):

**Message:**

I couldn't find a working Workday extension in this environment after all.
Switching to full setup instead.

**End message.**

Read `src/skills/setup/SKILL.md` and follow it.
