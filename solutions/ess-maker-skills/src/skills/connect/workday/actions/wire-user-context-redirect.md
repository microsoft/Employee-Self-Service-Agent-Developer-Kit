# Action: Wire the User Context redirect to Workday

Called by the lifecycle runner (`src/skills/connect/shared/lifecycle-runner.md`)
for the `agent-wiring` phase of the Workday contract. By the time this file
runs, the role gate has already passed and a rollback checkpoint has already
been saved — this file only performs the edit and pushes it.

Every **Message** block is the exact text to show the user. Copy it verbatim.

---

## A.0 — Role gate (Environment Maker)

The lifecycle runner already applied `permission-gate.md` before reading this
file — see `src/skills/connect/shared/lifecycle-runner.md` section L.4a, which
uses `GATE_MODE = "programmatic"` with the same Dataverse security-role query
`src/skills/setup/workday/install-workday-extension-pack.md` section P5.0
uses for this exact role. This file starts from a passed gate; it does not
re-check it.

## A.1 — Explain what's about to change

**Message:**

I'll wire your agent's **User Context** topic to call Workday on every
conversation. Without this, Workday topics respond with "This feature isn't
available yet."

**End message.**

---

## A.2 — Resolve the installed system topic

Find the installed Workday "Set User Context" system topic's dialog id under
`workspace/agents/{AGENT_SLUG}/topics/`. Use the actual installed topic name — do not
assume a fixed name, since it varies by install path (for example,
`WorkdaySystemGetUserContextV2` on the current extension pack).

---

## A.3 — Edit the redirect

Set the agent's
`workspace/agents/{AGENT_SLUG}/topics/user-context-setup.mcs.yml`
`OnRedirect` to a `BeginDialog` calling that dialog id:

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

---

## A.4 — Scan, dry run, push

Check for errors using the diagnostics tool on the edited file. Fix any
before continuing.

Preview and push:

```
python scripts/push.py --only "topics/user-context-setup.mcs.yml" --dry-run
```

Review the preview. The preview must contain only the `user-context-setup` topic. If any other
file appears, stop and report it instead of publishing unrelated work.

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Publish Workday wiring",
    "question": "Publish this scoped User Context topic change to the active agent?",
    "options": [
      { "label": "Publish", "recommended": true },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

If the user selects **Not now**, stop without pushing and leave the phase
`in-progress`. If the user selects **Publish**, run:

```
python scripts/push.py --only "topics/user-context-setup.mcs.yml" --yes
```

The explicit question above is the approval for this concrete scoped change;
`--yes` prevents the script from attempting a second terminal-only prompt.

---

## A.5 — Return

Return to the lifecycle runner. It re-runs `WD-REST-002` for `AGENT_SLUG`
immediately after this file completes and decides whether to advance or use
the named restore point — this file does not re-run the checkpoint itself.
