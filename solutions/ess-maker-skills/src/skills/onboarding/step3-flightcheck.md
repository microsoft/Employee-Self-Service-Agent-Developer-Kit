# Step 3: FlightCheck (Optional)

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This step runs AFTER Step 2 completes (agent extracted, MCP started).

---

## 3.1 — Offer the readiness check

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "FlightCheck",
    "question": "Want to run a quick readiness check on your environment? (~2-3 min, optional)",
    "options": [
      { "label": "Yes — run readiness check", "recommended": true },
      { "label": "Skip — remind me later" }
    ],
    "allowFreeformInput": false
  }
]
```

**If they choose "Skip":**

Do NOT update `workspace/onboarding/tasks.md`. Step 5 stays unchecked so
`/setup` will offer the readiness check again on the next run.

**Message:**

No problem — I'll keep this on your checklist. You can run
`/flightcheck` any time, or `/setup` will offer it again.

**End message.**

Then go to **3.4** (record on the plan, if one exists).

**If they choose "Yes":**

Proceed to 3.2.

---

## 3.2 — Run FlightCheck

**Message:**

Running readiness checks — this takes 1–3 minutes...

**End message.**

Run in the terminal:

```
python scripts/flightcheck/cli.py --scope full --invocation-source adk
```

Wait for the script to finish.

Update `workspace/onboarding/tasks.md` — change step 5 from `- [ ]` to `- [x]`.

---

## 3.3 — Present results

Read `workspace/flightcheck/results.json`. Present the results using the same
format as `src/skills/flightcheck/SKILL.md` Step 3 (summary banner →
category breakdown table → issues table → next steps). Follow that format
exactly.

After the results, always append the setup completion table:

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse configured | ✅ |
| 2 | Agent discovered | ✅ |
| 3 | Agent extracted | ✅ |
| 4 | MCP server started | ✅ |
| 5 | Readiness check | ✅ |

Then show:

| Command | What it does |
|---------|-------------|
| `/create` | Create a new topic or workflow |
| `/connect` | Set up ServiceNow or Workday integration |
| `/scan` | Scan for compile errors |
| `/flightcheck` | Re-run readiness check after fixes |
| `/menu` | See all commands |

Then go to **3.4** (record on the plan, if one exists).

---

## 3.4 — Record setup on the rollout plan (if one exists)

Setup just connected the kit to the environment and recorded its details. If the
maker is following a **rollout plan**, this completed the plan's setup task and
produced the environment the other tasks depend on — so offer to record it. This
runs at the end of setup whether the readiness check was run or skipped.

Check whether `workspace/plan/plan.json` exists.

**If it does NOT exist:** stop here — there is nothing to record.

**If it exists**, ask (use the `vscode_askQuestions` tool, or just ask in plain
text if that tool isn't available):

- Header: "Update your plan"
- Question: "Setup is done — and it's a task on your rollout plan. Want me to mark
  that task complete and save the environment so the rest of the plan can use it?"
- Options: "Yes, update my plan" (recommended) / "Not now"

**If "Yes, update my plan":** run this (do not narrate the command) — it finds the
plan's `/setup` task, marks it complete, and pins the environment for downstream
tasks:

```
python scripts/planner/cli.py capture-setup --complete
```

Then show:

**Message:**

Done — I've marked the setup task complete on your plan and saved the environment,
so the next tasks can connect to it. Say **"what's next on my plan"** whenever
you're ready to continue.

**End message.**

**If "Not now":** leave the plan unchanged.

Stop here.
