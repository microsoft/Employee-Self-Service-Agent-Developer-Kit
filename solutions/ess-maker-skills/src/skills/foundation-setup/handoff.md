<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 7 — Connect Handoff

Load canonical state:

```text
python scripts/setup_state.py show --view report
```

Build the completion report only from that output. Include:

- locked environment name, type, and endpoint;
- verified allocated capacity and governance status;
- preferred solution and publisher prefix, or `Not configured (skipped)`;
- HR and IT installed/ready matrix;
- open issues;
- statement that ISV connection and topic work were not performed.

Ask the maker to confirm the report is accurate.

After the maker confirms the report, persist one consolidated handoff result:

```text
python scripts/setup_state.py record-step-result \
  --step SETUP-07 \
  --mode manual-attested
```

Run the final bundle by invoking:

```text
python scripts/setup_state.py finalize
```

The domain service requires every prior step to be complete with a persisted
step result. On failure it blocks `SETUP-07` with the returned causes and stops.

If it passes, record the final module result in the displayed report. The command
sets setup to done, records the completion timestamp, and marks `/connect` ready.

Read `src/skills/onboarding/foundation-bootstrap.md` and follow it. This routes
directly to installed-agent inventory without rendering another setup
checklist. When it completes, continue below.

## After workspace binding

This section also handles an already-complete setup. Do not finalize, extract,
or repeat setup again just to choose the next action.

If an assigned plan task was retained, or the saved plan tracks this rollout's
foundation work (`python scripts/planner/cli.py setup-status`), return to Planner:

1. For newly completed foundation work, follow `src/skills/planner/capture.md`
   to confirm and capture the verified outputs **only once**, then perform any
   eligible shared sync/readback. Capture can close both environment and agent
   tasks when this run actually satisfied them. Skip capture if already recorded;
   do not reopen completed tasks. Workspace binding alone is not completion of a
   connection, topic, or other task that still has its own work to do.
2. Follow `src/skills/planner/status.md` → **Refresh after progress** to show what
   changed and the same person's next action from the refreshed plan and caller
   assignments. Continue any unfinished work or show their next eligible task;
   if they have none, say their work is complete or name what they are waiting on.
3. **Do not default to `/connect`** for an assigned admin. Another role may own
   integration work. Recommend the owning workflow for this person's actual
   next task, without starting it automatically. Stop here; omit the standalone
   message below.

**Without a plan task or a plan tracking this rollout**, keep the standalone
setup handoff:

**Message:**

Your ESS foundation and local workspace are complete and ready for integrations.

Topic creation remains a separate `/create` workflow.

## Your next step

**Connect your first system.**

Choose the system you want employees to use through ESS.

**Run:** `/connect`

**End message.**
