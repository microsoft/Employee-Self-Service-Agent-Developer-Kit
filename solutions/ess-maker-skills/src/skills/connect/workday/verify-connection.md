<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 6 - Maker validation

This is the final guided Workday setup phase. It ends after the maker
successfully validates one enabled read-only Workday scenario in the Copilot
Studio Test pane. Publishing, deployment, and non-maker employee validation
are next steps outside this skill lifecycle.

The skill cannot perform the Test pane interaction on the maker's behalf. The
skill cannot publish or deploy the agent; those are post-skill next steps.

## Run the maker smoke test

Ask the maker to:

1. open **Employee Self-Service (HR)** in Classic Copilot Studio;
2. open a new Test pane conversation without publishing the agent;
3. use the maker's configured Workday connection to run one enabled read-only
   scenario, such as checking a vacation balance; and
4. confirm that the agent identifies the maker's Workday user and returns real
   Workday data without an unexpected repeated sign-in.

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Maker smoke test",
    "question": "Did the Workday scenario succeed in the Copilot Studio Test pane?",
    "options": [
      { "label": "Yes, the Test pane scenario passed" },
      { "label": "No, the Test pane scenario needs remediation" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset.
Do not mark the passing option as recommended.

If the maker selects **No**, stop before publishing and ask what failed. For
failures other than the exact Workday response `Task not authorized`, show only
the remediation relevant to that surface and repeat the maker smoke test after
the issue is corrected.

For `Task not authorized`, ask the maker for the name of the scenario that
failed. Ask the Workday administrator to correct the domain security policy
for that scenario, then collect the affected Workday security domain. Write
this safe evidence to
`.local/connect/workday-da/maker-authorization-remediation.json`:

```json
{
  "remediationId": "WD-E2E-006",
  "scenarioName": "{named scenario that failed}",
  "affectedDomain": "{Workday security domain corrected by the administrator}",
  "timestamp": "{timezone-qualified timestamp when the failure was observed}"
}
```

Run:

```powershell
python scripts/workday_connect.py record-validation-failure --evidence-file ".local\connect\workday-da\maker-authorization-remediation.json"
```

Then require the maker to retest that same named scenario. Do not accept a
different scenario as the retest. Do not start an employee evidence window or
ask a non-maker employee to test.

If the maker selects **Yes**, write this safe evidence to
`.local/connect/workday-da/maker-validation.json` using a structured file-write
tool:

```json
{
  "testUserCategory": "maker",
  "scenarioName": "{named scenario, required after Task not authorized remediation}",
  "timestamp": "{timezone-qualified current timestamp}",
  "outcome": "passed"
}
```

Omit `scenarioName` when no authorization remediation was required.

Then run:

```powershell
python scripts/workday_connect.py record-validation --evidence-file ".local\connect\workday-da\maker-validation.json"
```

The controller marks the guided lifecycle complete immediately. Do not wait
for Power Automate run-history evidence, run a separate runtime-correlation
step, or ask the maker or employee to repeat a successful scenario.

## Finish the current Workday connection

After the controller returns `lifecycleComplete: true`, render its
`completionMessage` first. It confirms that all six steps and the maker Test
pane validation are complete in `activeTargetRealm`, with no further Workday
Connect action required in that realm. Use the same finish behavior when
`status` reports an already-ready lifecycle; do not repeat the smoke test.

End this Connect execution after its completion message and optional later
guidance. Setup is an entry prerequisite, not a phase or completion action:
do not invoke `src/skills/foundation-setup/SKILL.md` here, recheck overall setup
readiness to decide whether Connect can finish, or return to Setup. Keep
completed Workday phases and administrator evidence unchanged. Do not set
`connect_ready` or mark unrelated setup steps done based on Workday success.

## Optional later work

Under **Optional later - not part of this completed connection**, render the returned
`postSkillNextSteps` for the completed realm. Do not ask for a next realm,
start promoted-target discovery, or keep this execution open waiting for
promotion. Returning to Connect is necessary only after the maker actually
promotes the agent and explicitly asks to configure that new realm.

Do not add Production employee-adoption steps to a Development or Test completion.

For Development, the optional later guidance is:

> **Optional later - not part of this completed connection**
>
> 1. Promote the agent from Development to Test when ready. Open the source
>    agent in Copilot Studio and use your organization's approved promotion
>    process. Ask the maker responsible for agent deployment if you need
>    access or instructions. Connect Workday does not perform promotion.
> 2. Only after promotion is complete, return to Connect Workday and say that
>    the agent was promoted to Test.

For Test, the optional later guidance is:

> **Optional later - not part of this completed connection**
>
> 1. Promote the agent from Test to Production when ready. Open the source
>    agent in Copilot Studio and use your organization's approved promotion
>    process. Ask the maker responsible for agent deployment if you need
>    access or instructions. Connect Workday does not perform promotion.
> 2. Only after promotion is complete, return to Connect Workday and say that
>    the agent was promoted to Production.

Only for Production, the optional later guidance is:

> **Optional later - not part of this completed connection**
>
> 1. Publish and deploy the Production agent when ready.
> 2. After deployment, have each non-maker employee establish their own Workday connections
>    in Microsoft 365 Chat.
> 3. After deployment, validate an enabled Workday scenario with the published
>    Production agent.

Do not wait for those results, record them as lifecycle evidence, or keep the
Workday skill open. They are deployment and adoption validation outside this
guided setup lifecycle.

Render the manual promotion destination as the known source-agent Copilot
Studio link, not an unlinked portal name. If the maker asks to promote, follow
the promotion decision in `SKILL.md`; do not assume it has already happened or
claim Connect performed the promotion.
