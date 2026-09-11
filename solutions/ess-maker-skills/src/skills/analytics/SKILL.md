# Analytics Skill

Print a direct link to the current agent's Copilot Studio analytics
dashboard, so the maker can jump straight from VS Code to their agent's
usage metrics.

Every **Message** block is the exact text to show the user. Copy it
verbatim. Do not rephrase, add commentary, or tell the user what tools
you are calling or files you are reading.

The behavior is intentionally a thin wrapper over the
`scripts/analytics_pointer.py` CLI: this skill file only decides which
Message block to show; the pointer resolution, URL construction, feature
flag check, and telemetry emission all happen inside the script. That
keeps the "what URL do we point at?" decision in exactly one place — see
the analytics_pointer.py module docstring for the partner-contract
caveat that governs it.

---

## Start

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

## Case 1: feature flag OFF (`flag == "off"`)

The analytics pointer is gated behind a feature flag while the Copilot
Studio direct-link contract is being finalized. Do not attempt to
construct or guess a URL — the script would refuse anyway.

**Message:**

Analytics pointer is not yet enabled in this build of the ADK. It is
behind a feature flag while the Copilot Studio deep-link contract is
being finalized.

If you need your agent's analytics right now, open it manually from the
Copilot Studio homepage: https://copilotstudio.microsoft.com/

**End message.**

Stop here.

---

## Case 2: flag ON, association missing (`flag == "on"` AND `association == null`)

This is the FR7 repair state. Either `.local/config.json` doesn't have
an active agent linked, or one of `maker_aad` / `env_id` / `agent_id` is
missing. The fix is `/setup`.

**Message:**

I can't find a linked Copilot Studio agent for this workspace, so I
can't build an analytics link yet. Run `/setup` to link an agent, then
run `/analytics` again.

**End message.**

Stop here.

---

## Case 3: flag ON, association present, URL resolved (`url` is non-empty)

Show the link exactly as returned by the script — do NOT shorten it,
wrap it in a tracker, or reformat the URL. Then run
`python scripts/analytics_pointer.py --show` in the terminal. That
command prints the same maker-facing line the pointer would print, AND
emits the `adk.analytics.pointer.shown` telemetry event with
`outcome=resolved`. Show the script's stdout verbatim to the maker —
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
running `/analytics` again in a moment, or open Copilot Studio directly
at https://copilotstudio.microsoft.com/ and find your agent from the
homepage.

**End message.**

Stop here.

---

## Optional: dismissing the reminder

If the maker explicitly asks to "stop showing the analytics reminder"
or similar, run `python scripts/analytics_pointer.py --dismiss` in the
terminal. That marks the reminder complete for the current
`(maker, env, agent)` triplet so the post-deploy report won't show it
again. Then:

**Message:**

Got it — I won't show the analytics reminder after future installs.
You can still run `/analytics` any time to jump to the dashboard.

**End message.**

Stop here. Do NOT run `--dismiss` unless the maker explicitly asked.
