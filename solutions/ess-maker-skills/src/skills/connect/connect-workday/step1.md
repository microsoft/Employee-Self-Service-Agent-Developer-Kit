# Connect Workday Step 1: Verify the Extension

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This flow wires the current agent to a Workday extension that is already
installed in this environment. It does not install the extension pack,
configure the Workday tenant, or provision connections — those are handled by
`/connect workday`.

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

Update `.local/connect/connect-workday/steps.md` — change step 1 from
`- [ ]` to `- [x]`.

Continue to step 2 (`src/skills/connect/connect-workday/step2.md`).

**If any report `FAILED`, `NotConfigured`, or `Skipped`:**

**Message:**

I couldn't find a working Workday extension in this environment. This flow
wires an agent to a Workday extension that's already installed and
connected — it doesn't set one up.

Run `/connect workday` instead to install the extension pack and configure
Workday from scratch.

**End message.**

Stop here.
