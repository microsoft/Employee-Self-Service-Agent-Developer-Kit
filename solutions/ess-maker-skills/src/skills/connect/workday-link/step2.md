# Workday Link Step 2: Wire Workday Topics to This Agent

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

Workday topics only work once the agent's **User Context** topic redirects to
the Workday system topic that sets it. Without this redirect, every Workday
topic fails at runtime with "This feature isn't available yet."

---

## 2.1 — Check whether the redirect is already wired

**Message:**

Now I'll check whether the Workday user-context redirect is already wired
into this agent.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-REST-002
```

Render the result per `src/skills/setup/shared/checklist-updater.md`
§U.0–U.0a before continuing.

- **`PASSED`** — already wired. Update
  `.local/connect/workday-link/steps.md` step 2 to `- [x]` and continue
  to step 3 (`src/skills/connect/workday-link/step3.md`).
- **`Skipped`** — not applicable to this install. Update step 2 to `- [x]`
  and continue to step 3.
- **`FAILED`** or **`NotConfigured`** — continue to 2.2.

---

## 2.2 — Wire the redirect

**Message:**

I'll wire the **User Context** topic to call the Workday user-context system
topic on every conversation. I'll save a rollback checkpoint first so this
can be undone if anything looks off.

**End message.**

Save a rollback checkpoint:

```
python scripts/checkpoint.py "Add User Context redirect to Workday"
```

Resolve the installed Workday "Set User Context" system topic's dialog id
under `workspace/agents/{slug}/topics/` — use the actual installed topic name
(`WorkdaySystemGetUserContextV2` on the simplified pack; the legacy name on a
full install), do not assume one over the other.

Set the agent's
`workspace/agents/{slug}/topics/user-context-setup.mcs.yml` `OnRedirect` to a
`BeginDialog` calling that dialog id:

```yaml
kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  priority: 0
  actions:
    - kind: BeginDialog
      id: bfT9Kx
      displayName: Redirect to Workday System Get User Context
      dialog: {USER_CONTEXT_DIALOG}
```

Push the change:

```
python scripts/push.py --yes
```

Re-verify:

```
python scripts/flightcheck/cli.py --checkpoint WD-REST-002
```

Render the result per `src/skills/setup/shared/checklist-updater.md`
§U.0–U.0a before continuing.

**If `PASSED`:** update `.local/connect/workday-link/steps.md` step 2 to
`- [x]` and continue to step 3.

**If it still fails:** roll back with the checkpoint saved above, then show:

**Message:**

I wasn't able to wire the redirect automatically. I've rolled back the
change. In Copilot Studio, open the **User Context** topic and set its
redirect to the Workday "Set User Context" system topic, then type
**retry**.

**End message.**

Wait for the user. On retry, go back to 2.1.
