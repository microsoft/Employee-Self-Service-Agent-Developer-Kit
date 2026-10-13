# Analytics Skill

Print a direct link to the current DA agent's Copilot Studio analytics
dashboard, so the maker can jump straight from VS Code to its usage metrics.

Every **Message** block is the exact text to show the user. Copy it
verbatim. Do not rephrase, add commentary, or tell the user what tools
you are calling or files you are reading.

The behavior is intentionally a thin wrapper over the
`scripts/analytics_pointer.py` CLI: this skill file only decides which
message block to show; the pointer resolution and URL construction happen
inside the script. The skill records one `adk.capability.use` event for the
`analytics` capability when it starts.

---

## Start

First run `python scripts/analytics_pointer.py --record-invocation` to emit
one capability-usage event for this `/analytics` invocation. This is
best-effort and must not block the skill.

Run `python scripts/analytics_pointer.py --status` in the terminal and
capture its stdout as JSON. The JSON has the shape:

```json
{
  "flag": "on" | "off",
  "association": null | { "env_id": "...", "agent_id": "..." },
  "url": "https://...",
  "reason": "" | "feature_flag_off" | "missing_association" | "validation_failed",
  "completed": true | false
}
```

Then branch on that JSON exactly as follows. Do not compose your own
message. If a branch has no Message block, stay silent and stop.

---

## Case 1: explicit opt-out (`flag == "off"`)

The analytics link was explicitly disabled with
`ADK_ANALYTICS_POINTER=off`. Do not substitute the Copilot Studio homepage.

**Message:**

Your Copilot Studio analytics link isn't available in this workspace right
now. Please contact your administrator for help accessing analytics.

**End message.**

Stop here.

---

## Case 2: flag ON, association missing (`flag == "on"` AND `association == null`)

This is the FR7 repair state. Either `.local/config.json` doesn't have
an active DA agent linked, or one of `env_id` / `agent_id` is missing. The
fix is `/setup`.

**Message:**

I can't find a linked DA Copilot Studio agent for this workspace, so I
can't build an analytics link yet. Run `/setup` to link an agent, then
run `/analytics` again.

**End message.**

Stop here.

---

## Case 3: flag ON, association present, URL resolved (`url` is non-empty)

Show the link exactly as returned by the script — do NOT shorten it,
wrap it in a tracker, or reformat the URL. Then run
`python scripts/analytics_pointer.py --show` in the terminal. That
command prints the same maker-facing line the pointer would print. Show the
script's stdout verbatim to the maker —
that is the ONLY output the maker sees.

Do not add any additional Message block after the script output in this
case. The script's output IS the message.

---

## Case 4: flag ON, association present, resolution failed (`url` empty AND `reason` is `validation_failed`)

Reserved for the click-time destination-validation stub (FR2). Today
the resolver never returns this; when the FR2 check lands, this branch
will fire on transient failures.

**Message:**

I couldn't validate the Copilot Studio analytics link right now. Try
running `/analytics` again in a moment.

**End message.**

Stop here.

---

## Optional: dismissing the reminder

If the maker explicitly asks to "stop showing the analytics reminder"
or similar, run `python scripts/analytics_pointer.py --dismiss` in the
terminal. That marks the one-time post-deployment reminder complete for the
current local DA workspace association. Then:

**Message:**

Got it — I won't show the post-deployment analytics reminder again.
You can still run `/analytics` any time to jump to the dashboard.

**End message.**

Stop here. Do NOT run `--dismiss` unless the maker explicitly asked.
