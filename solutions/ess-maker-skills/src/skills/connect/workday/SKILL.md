# Connect Workday (already installed)

Entry point for connecting this agent to a Workday extension that is
**already installed** in this environment and was identified by the caller as
the compatible simplified CEA package. Missing, partial, legacy, or
inconclusive package results stop in `src/skills/connect/step1.md`; this skill
does not fall back to the setup orchestrator.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

## Maker communication profile

Reuse a caller-supplied immutable profile and never own a second entry, count,
invitation, or proposal. If directly invoked, use eligible mode only after
the existing materialization and Workday package/admission gates pass, before
lifecycle mutations; do not infer support from profile state. When called by
Connect, continue its single eligible entry after those gates. Read
`src/skills/shared/user-profile-entry.md` and
`src/skills/shared/user-profile-contract.md`. Follow any claimed optional
onboarding, resume the same lifecycle, and return the actual outcome to the
entry owner for finish (or finish once for direct entry). Preserve the
lifecycle's exact messages and required turns; do not append a style indicator
or automatic proposal.

---

## W.1 — Run the lifecycle

Read `src/skills/connect/shared/lifecycle-runner.md` and follow it with
`PROVIDER = "workday"` and `AGENT_SLUG` resolved from `.local/config.json`
(`activeAgent`, falling back to `agent.slug`).

That file loads `src/skills/connect/workday/contract.json`, resumes any
in-progress state from
`.local/connect/workday/agents/{AGENT_SLUG}/lifecycle.json`, shows the
plan and collects attestation on a first run, live-re-verifies anything
already recorded done, then runs whichever phase is next — confirming the
extension and its connections, wiring the agent's Workday topics, and
validating the end-to-end connection.

---

## W.2 — After completion

Once the lifecycle runner reports Workday connected, return control to the
caller. Do not repeat the runner's completion message or add your own.
