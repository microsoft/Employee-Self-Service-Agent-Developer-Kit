# Provision Step 4: Validate Readiness

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This step reviews the provision tasks.md checklist to confirm all prior
steps completed successfully. Each step already validates its own work
(solutions installed, connections active, refs bound, topic patched),
so a separate FlightCheck run is not needed here — FlightCheck's
BAP/PowerApps Admin APIs are unreachable from external networks in preprod
and would produce only false warnings.

> **Future:** A Dataverse-only provision health check (solutions, workflows,
> connectionreferences queried directly) can be added in a follow-up PR
> to provide automated post-provision validation without the BAP dependency.

Read `my/provision/{ENV_NAME}/config.json` for ENV_URL, ENV_NAME, PERSONA.

---

## 4.1 — Skip if already complete

Read `my/provision/{ENV_NAME}/tasks.md`. If "Health check passed" is `- [x]`,
this step is already done from a previous run. Continue back to SKILL.md
**Step 6** (summary + mark complete) without doing anything else.

---

## 4.2 — Review checklist

Read `my/provision/{ENV_NAME}/tasks.md`. Every line should be `- [x]`
except "Health check passed" (which this step will mark).

If any earlier task is still `- [ ]`:

**Message:**

The following provision tasks are not yet complete:

{list unchecked items}

These must be resolved before the environment can be marked ready.
Would you like to go back and complete them, or mark this provision
as incomplete and stop here?

**End message.**

If the user wants to go back, return to the appropriate step.
If the user wants to stop, leave tasks.md as-is and stop.

---

## 4.3 — Mark complete

If all tasks (except "Health check passed") are checked:

Update `my/provision/{ENV_NAME}/tasks.md` — change "Health check passed"
to `- [x]`.

**Message:**

All provision tasks verified. The environment is ready.

**End message.**

Continue back to SKILL.md Step 6 (summary + mark complete).
