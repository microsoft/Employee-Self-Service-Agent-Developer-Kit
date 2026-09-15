# Workday Link Step 1: Verify the Extension

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This flow wires the current agent to a Workday extension that is already
installed in this environment. It does not install the extension pack,
configure the Workday tenant, or provision connections — that's the setup
orchestrator's job.

Read `.local/config.json` for the agent details (`dataverseEndpoint`,
`agent.botId`, `agent.name`, `agent.schemaName`, `agent.isManaged`).

---

## 1.1 — Check the extension pack and connections

Run each checkpoint in isolation:

```
python scripts/flightcheck/cli.py --checkpoint WD-PKG-001
python scripts/flightcheck/cli.py --checkpoint WD-CONN-012
python scripts/flightcheck/cli.py --checkpoint DV-CONN-001
```

**If all three report `PASSED`:**

Update `.local/connect/workday-link/steps.md` — change step 1 from
`- [ ]` to `- [x]`.

Continue to step 2 (`src/skills/connect/workday-link/step2.md`).

**If any report `FAILED`, `NotConfigured`, or `Skipped`:**

**Message:**

I couldn't find a working Workday extension in this environment after all.
Switching to full setup instead.

**End message.**

Read `src/skills/setup/SKILL.md` and follow it.
