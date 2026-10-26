<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Connect Workday to the ESS HR agent

This branch is DA-only. CEA Workday Connect is maintained on `main-ca`; do not
run a CEA lifecycle or use CEA progress as evidence here.

Guide the customer through one resumable Workday connection lifecycle per
DEV, TEST, and PROD target. Use
`scripts/workday_connect.py` and
`.local/connect/workday-da/config.json` internally; do not create, copy,
update, or infer status from a Markdown checklist.
Use `shared/config-schema.md` as the internal state and migration reference;
it is not a customer-executed phase and must not be shown as an extra step.

## Safety contract

- Support only the active native ESS HR agent recorded by `/setup`. Classic DA
  and ESS IT agents are outside this lifecycle. The controller verifies the
  exact agent, workspace materialization, architecture, and Dataverse
  environment during preflight.
- Never ask for a Workday password, client secret, access token, refresh token,
  cookie, certificate private key, or certificate body in chat.
- Explain an authentication prompt before launching it. PAC, Dataverse,
  connector OAuth, and Agent Builder are separate credential stores; a prompt
  for a different store is expected, but a valid store must not be prompted
  twice for the same account and session. The guided Microsoft Entra phase
  must not authenticate the maker to Graph.
- Preview the exact target and actions before approval. After approval, verify
  the plan hash immediately before every mutation. If discovery or scope
  changes, discard the approval and show the new plan.
- After every mutation, reread the target and persist evidence only after the
  verified result matches the approved plan.
- Never diagnose a permission problem from a guess. Show the API, CLI, or
  checked-in script evidence that produced the diagnosis.
- Use structured `vscode_askQuestions` forms for choices and short customer
  evidence. The Entra and Workday administrator handoffs are the only
  exception: share the checked-in workbook, collect the administrator's
  full local path to the completed `.xlsx` file, and pass that file to the
  controller's worksheet parser. Accept only the resulting validated structured payload.
  Reject missing, duplicate, or unknown labels, formulas, and unsafe workbook
  content; never infer an answer or treat a supplied path as evidence before
  validation.
- Leave every option initially unset. Do not add `recommended`, `default`,
  “recommended” label text, or any equivalent preselection to approvals,
  factual observations, connection choices, or validation outcomes. Continue
  only after the customer explicitly submits a choice.
- Reuse the exact recorded account through the shared credential cache. Run
  only the narrow verification required for the current phase; do not launch
  broader checks that request unrelated API audiences.

## Customer-facing language contract

Commands, file paths, JSON payloads, state keys, plan hashes, checkpoint IDs,
schema names, component maps, API names, and implementation terms in this skill
are internal execution instructions. Never show or narrate them unless the
customer explicitly asks for technical diagnostics.

Customer-facing messages must describe only:

- the customer-visible target and current phase;
- who needs to perform a portal or Workday action;
- the exact portal navigation and field value needed for that action;
- whether a supported change or verification succeeded;
- the concise remediation needed when it did not.

Keep execution-only notes and action markers such as `A.1` and `B.2` internal.
Do not turn later-phase sequencing rules into warnings about pages the maker
has not been asked to use. Show necessary safety guidance at the step where
it applies, without repeating it in surrounding prose.

Translate internal outcomes into plain language. For example, say **all
Workday topics are enabled**, not that component `state` and `status` are
`Active`. Topic metadata diagnostics are support context and must not be
translated into a missing-package, missing-flow, or runtime-failure claim by
themselves. Never show `CloudFlow NotFound`, `MinimalBot`, component-map,
native-definition terminology, raw command output, tracebacks, encoding
errors, or internal identifiers in a customer message.

Read `WORKDAY_CONNECT_RESULT_JSON` directly. Do not create an ad hoc Python or
PowerShell formatter merely to render controller status. If an internal
formatting command fails, correct or retry it internally and show only the
validated customer-facing result.

## Capability contract

This table is an internal reference, not an opening customer plan. Never
render it automatically on invocation; choose the applicable presentation
under **Start or resume** only after resolving the target realm and status.

Describe each action according to who actually performs it:

| Phase                 | What the skill can do                                                                                                                                                                                                         | What remains a user or administrator action                                                                             |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Preflight             | Verify the selected agent, environment, account, and supported Workday package choice without installing it                                                                                                                   | Complete Microsoft sign-in and choose an environment when no exact URL is known                                         |
| Microsoft Entra       | Generate one guided administrator handoff, validate the returned non-secret target and configuration evidence, and record it                                                                                                  | Identify the exact application, create or change it in the portal, and return the requested evidence                    |
| Workday administrator | Generate the handoff, validate returned non-secret values, derive endpoints, and record evidence                                                                                                                              | Change SAML, OAuth, API-client, certificate, or authentication-policy settings in Workday                               |
| Connections           | After approval, install or verify the Workday package, then record the reviewed physical-connection readiness evidence                                                                                                        | Approve package installation, create connector connections, and complete connector OAuth                                |
| Runtime               | After approval, bind the Workday connections, activate the package flows, configure required runtime permissions, connect employee context routing, enable every Workday topic included with the agent, and verify the result | Connect flows to the agent and enable parameter sharing in Copilot Studio when those settings require maker interaction |
| Maker validation      | Guide and record one successful pre-publish maker smoke test, then close the guided lifecycle                                                                                                                                    | Test once in the Copilot Studio Test pane without publishing                                                                                                         |

Never say "I changed," "I configured," "I enabled," or "I updated" for a
manual action. Say what the administrator or maker must do, then say what the
skill can verify or record afterward. Claim an automated change only after its
command succeeded and the target was reread.

## Tenant foundation and deployment scope

Treat the Entra and Workday configuration as a reusable tenant foundation.
Treat package installation, physical connections, runtime flow wiring, native
topics, and maker validation as environment-and-agent-specific deployment
work. Publishing and non-maker validation happen after this guided lifecycle.

- A different Power Platform environment, ESS HR agent, or maker account must
  not by itself require the Entra or Workday administrators to repeat setup.
- For a controller-verified Test or Production promotion in the same
  AgentBuilder ALM family and Microsoft Entra tenant, reuse the recorded tenant
  foundation and continue at Connections. The promoted target discovery is the
  fresh target proof; do not repeat the Entra or Workday administrator handoff.
- For an unrelated environment or any target that cannot be proven as the
  promoted sibling, do not silently trust stored Entra evidence or perform a
  maker-authenticated Graph reread. Keep setup blocked until the exact target
  and tenant relationship can be verified.
- Ask the administrator to repeat only missing, changed, or unhealthy settings.
  Outside the verified promotion path, every fresh Entra sign-off must be
  followed by fresh Workday administrator confirmation and a completed
  workbook. Matching a saved tenant foundation does not complete that phase.
  Healthy settings may be confirmed without repeating configuration changes.
- Never reuse foundation evidence across a different Entra tenant, Workday
  tenant, SAML Service Provider ID, Entra application, or signing certificate.
- Keep the detailed administrator instructions in the workbook and internal
  guide. In chat, show only the concise handoff, target values, workbook link,
  and essential handoff notes. Do not repeat administrator task lists. On a
  question or validation failure, show only the affected help or correction
  instead of making the user repeat healthy configuration.

## One-way administrator handoff

Treat the two administrator phases as a one-way relay between different
people:

1. Microsoft Entra sign-off must finish first, including transfer of the
   active Base64 signing certificate through the customer's approved channel.
2. Only then may the Workday administrator phase begin.
3. The Workday handoff consumes the recorded Entra identifiers, certificate
   metadata, and transferred certificate file. It must not ask the maker to
   reopen Entra, re-engage the Entra app administrator, or repeat an Entra task.
4. A Workday-side mismatch or uncertainty remains blocked in the Workday phase
   and is resolved through the customer's Workday governance path. The only
   exception is an explicit controller-detected change to the selected Entra
   target, which invalidates downstream evidence before a new phase continues.

Do not combine both administrator guides into one conversation handoff. Each
administrator receives only the standalone section for their phase.

## DEV, TEST, and PROD journey

Use `/connect-workday` or `/connect` with Workday selected for every realm.
Natural-language statements such as **I promoted the agent to Test** or **the
agent is now in Production** enter this same lifecycle. Do not introduce or
suggest realm-specific slash commands such as `/connect-workday-test` or
`/connect-workday-prod`.

On every invocation, use the controller's `activeTargetRealm` and `targets`
status. Never infer the active realm from conversation text alone.

Distinguish a completed promotion from a request to perform promotion.
**Promote the agent to Test** or **How do I promote?** is not evidence that
promotion happened. Explain that Connect Workday configures Workday after
promotion but does not promote or publish an agent. Open the source agent's
known Copilot Studio link, identify its current realm, and direct the maker
responsible for agent deployment to complete the organization's approved
promotion process. Use documented native DA instructions when available;
never invent portal controls or substitute Dataverse solution export/import
or publishing for realm promotion.

If promotion completion is unknown, ask with `vscode_askQuestions`:

```json
[
  {
    "header": "Promotion",
    "question": "Has the agent already been promoted to the requested realm?",
    "options": [
      { "label": "Yes, promotion is complete - check again" },
      { "label": "No, I need to complete promotion first" },
      { "label": "Not now" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. On **Yes**, run the discovery below. On **No**,
provide the source-agent link and deployment-owner handoff above, then ask
the maker to return here after promotion. **Not now** preserves all progress.
An explicit statement that promotion completed already answers this question;
do not ask it again. Always finish with an actionable result or this decision,
not an empty response or internal-process narration.

1. Complete DEV through the maker's successful Copilot Studio Test pane
   scenario.
2. After DEV is Ready, if the maker says the agent was promoted to Test or
   chooses to configure Test, run automatic promoted-target discovery:

   ```powershell
   python scripts/workday_connect.py discover-realm-target --realm test
   ```

3. If automatic discovery cannot prove one environment, show the safe
   environment names or URLs returned by the controller and ask the maker to
   select one. Leave the choice unset, then rerun with the selected friendly
   value:

   ```powershell
   python scripts/workday_connect.py discover-realm-target --realm test --environment "{ENVIRONMENT_NAME_OR_URL}"
   ```

4. After TEST is Ready, use the same flow for Production:

   ```powershell
   python scripts/workday_connect.py discover-realm-target --realm prod
   ```

   Use `--environment` only when automatic discovery requests a selection.

Do not ask the maker for an environment ID, BotId, flow ID, authorization team
name, ALM family ID, or deployed commit. The controller obtains and verifies
those values. A URL is acceptable only as the maker's friendly environment
selection when automatic proof is insufficient.

Promoted-target discovery must prove the exact sibling realm, direct agent
identity, ALM family, supported schema, deployed commit, tenant, environment,
and Dataverse URL. It then activates an independent realm snapshot and reuses
the verified tenant foundation. Package readiness, physical connections,
runtime wiring, topics, and Maker validation remain target-specific and must
be completed separately in that active realm.

If discovery reports `foundationReused: true`, continue at Connections without
showing either administrator phase. If it is false, do not claim the
foundation was reused; follow the controller's current phase and blocker.

Discovery may find the sibling in the same Power Platform environment as
Dev. Do not ask the maker to create a separate environment just because its
realm is Test or Production. The controller still verifies the exact sibling,
realm, tenant, and ALM family.

If discovery fails, preserve the active realm and all completed administrator
work. Show the observed failure and the returned remediation. Offer **Check
again**, **Choose another environment**, and **Not now** in an unset
`vscode_askQuestions` form. Reuse a supplied valid environment selection on
**Check again**; ask for a friendly name or Dataverse URL only on **Choose
another environment** or when no selection exists. A malformed unrelated
inventory entry is not evidence that the maker supplied an invalid GUID.
Do not send the maker to reinstall tooling, repeat administrator handoffs,
or contact support without first offering the applicable retry/access steps.

## Start or resume

Run status before showing any plan, role table, progress table, phase
explanation, or participant question:

```powershell
python scripts/workday_connect.py status
```

### Resolve the realm and completion before presenting a plan

If this invocation carries an explicit promotion intent, use the returned
target registry before the normal ready-state completion branch or any
briefing:

If promotion completion is unknown, use the **Promotion** decision above
before proceeding. Do not show an opening plan while that decision or
promoted-target verification is outstanding.

- For a confirmed completed Test promotion, require the DEV target to be `ready`, then run
  `discover-realm-target --realm test`.
- For a confirmed completed Production promotion, require the TEST target to be `ready`, then run
  `discover-realm-target --realm prod`.

If the prerequisite realm is not Ready, keep that realm active and explain
that its Maker validation must finish before configuring the next realm.
Show only its current unfinished phase, not a new opening plan. If discovery
succeeds, run `status` again and use the newly verified `activeTargetRealm`,
`targets`, `phases`, and `nextPhaseId` for every subsequent message. Do not
render the previous realm's progress or completion first. If discovery fails
or requires a target selection, use the recovery or selection in **DEV, TEST,
and PROD journey** and do not show a speculative Test or Production plan.

If controller status is `ready` after resolving any explicit promotion intent,
go directly to **Completion** and finish this invocation. Do not show the
opening role table, `progressText`, a phase plan, or a participant question.
A bare Connect request after Development is Ready does not restart Development
or establish that promotion occurred. Do not discover or activate the next
realm without the maker's explicit intent.

For a non-ready lifecycle, require a resolved `activeTargetRealm` from the
controller before choosing a plan. Do not infer Test or Production solely
from the maker's wording, or fall back to a Development plan when the target
cannot be verified. Show the actual target blocker and supported recovery.

### Choose the presentation for the verified realm

- **First Development start:** Only when `activeTargetRealm` is `dev`, the
  lifecycle is not ready, all phases are still pending, and no administrator
  evidence has been captured, use the first-start briefing below. Any
  completed, in-progress, or blocked phase makes this a resume. Do not repeat
  the briefing within the same conversation even if all phases remain pending.
- **Development resume:** On resume, show the current phase and only its
  remaining participants, with the current six-phase progress table as
  described below; do not repeat the full role table or completed
  administrator handoffs.
- **Verified Test or Production:** Show a concise **Workday connection plan -
  Test** or **Workday connection plan - Production** only after that realm
  has been resolved by the controller. Build a short list from that active
  realm's `phases`, including only phases whose `status` is not `complete`.
  Never show the Development opening briefing, capability table, or six-row
  `progressText`, even on the first invocation for that promoted target.
  On a later invocation, narrow this list to the still-unfinished work.

For a verified promotion with `foundationReused: true`, explain once that the
existing tenant foundation is reused. The remaining plan contains only
unfinished **Connections**, **Runtime configuration**, and **Maker validation**
for this Test or Production agent. Describe target-specific package and
connection readiness, runtime authorization and sharing, and the maker Test
pane validation. Do not include completed Preflight or administrator phases,
ask administrators to repeat their handoffs, or imply Development is being
configured again. Development's completed connection remains unchanged.

If the controller instead reports a foundation blocker or an unfinished
administrator phase, show that exact phase and required remediation for the
verified realm. Do not claim reuse or promise the three-phase promoted plan
until the controller confirms it. Do not replace a real blocker with the
generic six-phase Development plan.

### First Development start only

On the first start of a non-ready Development lifecycle, show this readiness
briefing only after the realm and completion decisions above:

> Here's who may be needed to connect Workday to your ESS HR agent:
>
> | Phase                 | Responsibility                                                                                                                                             | Who is needed                                                                                                        |
> | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
> | Preflight             | Verify the ESS HR agent, environment, maker account, and supported package choice without changing the environment                                         | Power Platform Environment Maker                                                                                     |
> | Microsoft Entra       | Configure the Workday enterprise application, SAML, API permission, consent, assignment, and NameID                                                        | One Microsoft Entra app administrator with either the Application Administrator or Cloud Application Administrator role; involve a separate consent-capable administrator only if tenant policy prevents that administrator from granting consent |
> | Workday administrator | Configure tenant SAML and certificate trust, OAuth and the API client, functional-area access, endpoints, and the employee authentication policy           | Workday Administrator                                                                                                |
> | Connections           | Install or verify the Workday package, then connect Microsoft Dataverse and Workday                                                                         | Power Platform Environment Maker with package installation access                                                    |
> | Runtime configuration | Connect the installed Workday components, activate the required flows, configure runtime permissions and connection sharing, and enable all Workday topics | Power Platform Environment Maker; Dataverse System Administrator access for runtime authorization                    |
> | Maker validation      | Test a read-only Workday request in the Copilot Studio Test pane                                                                                            | Environment Maker |
>
> I'll run the available checks and automate supported changes. Each
> administrator gets a workbook with the required steps. Workday setup
> finishes after your Workday test succeeds in the Copilot Studio Test pane.

### Continue the current unfinished phase

The controller runs automatic readiness checks at the relevant phase
boundaries. Present only the resulting customer-safe readiness
or remediation state; do not expose internal profile/checkpoint identifiers or
ask the customer to run a second validation workflow.

For a resolved, non-ready lifecycle, after the applicable presentation:

1. **Development progress rule:** For a verified, non-ready
   `activeTargetRealm: dev`, render the returned `progressText` as Markdown
   on entry or resume and whenever `nextPhaseId` changes, before the current
   phase explanation or participant questions. This includes transitions to
   `entra` and `workday-admin`, not only Preflight. After completing a phase,
   run `status` again before presenting the next phase; do not reuse the
   previous phase's progress snapshot. It is the visible six-row roadmap and
   must not be collapsed into a one-line phase list. Do not repeat it for
   every question, file-path request, or workbook correction within an
   unchanged phase unless the maker asks for progress. Omit it for a ready
   lifecycle and Test or Production plans.
2. Render the returned `nextPhaseSummary` in this form:

   ```markdown
   ### Current phase: {title}

   What happens in this phase:

   - {whatHappens item 1}
   - {whatHappens item 2}
   - {whatHappens item 3}
   ```

3. Show new customer-safe `readiness.summary` results as they occur. On resume,
   show only evidence relevant to the current unfinished phase or its blocker,
   not a recap of every completed phase. Do not expose profile or checkpoint
   identifiers.
4. Show the current blocker afterward when one is present. Use its `summary`
   and `nextAction`; do not render any other blocker fields.

Do not render internal action IDs, hashes, or the full JSON state. Do not
replace the phase explanation with only `Current phase: {title}`.

For a non-ready lifecycle, determine the current phase's required participants
from `nextPhaseId`:

| `nextPhaseId`         | People required for the current phase                                                                                                                                                                       |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `preflight`           | Power Platform Environment Maker                                                                                                                                                                            |
| `entra`               | One Microsoft Entra app administrator with either the Application Administrator or Cloud Application Administrator role to complete the handoff; involve a separate consent-capable administrator only if tenant policy prevents that administrator from granting consent |
| `workday-admin`       | Workday Administrator                                                                                                                                                                                       |
| `connections`         | Power Platform Environment Maker with package installation access                                                                                                                                           |
| `runtime`             | Power Platform Environment Maker with Dataverse System Administrator access for runtime authorization                                                                                                       |
| `maker-validation`    | Environment Maker                                                                                                                                                                                           |

When `nextPhaseId` is `entra`, dispatch to `provision-entra-app.md` without the
form below. That phase asks whether the maker has engaged the administrator,
presents a concise handoff and checked-in detailed workbook, asks whether the
administrator completed the task, and validates the workbook at the supplied
path. It must not authenticate the maker to Graph or perform live Entra API checks.

When `nextPhaseId` is `workday-admin`, show only its row and use this exact
`vscode_askQuestions` form before dispatching that phase:

```json
[
  {
    "header": "Workday administrator",
    "question": "Have you arranged for a Workday administrator to complete this step?",
    "options": [
      { "label": "Yes, the Workday administrator is engaged" },
      { "label": "No, I still need to engage the Workday administrator" }
    ],
    "allowFreeformInput": false
  }
]
```

When `nextPhaseId` is `preflight` or `runtime`, show only its row and use this
exact `vscode_askQuestions` form before dispatching that phase:

```json
[
  {
    "header": "Required access",
    "question": "Are the people listed for this step available to help?",
    "options": [
      { "label": "Yes, required people are available" },
      { "label": "No, someone is unavailable" }
    ],
    "allowFreeformInput": false
  }
]
```

When `nextPhaseId` is `connections`, show only its row and use this exact
`vscode_askQuestions` form before dispatching that phase:

```json
[
  {
    "header": "Connections access",
    "question": "Do you have Power Platform Environment Maker access and permission to install the Workday package in this environment?",
    "options": [
      { "label": "Yes, I have the required privilege and access" },
      { "label": "No, I do not have the required privilege or access" }
    ],
    "allowFreeformInput": false
  }
]
```

When `nextPhaseId` is `maker-validation`, show only its row and use this exact
`vscode_askQuestions` form before dispatching that phase:

```json
[
  {
    "header": "Test access",
    "question": "Do you have Environment Maker access to test this agent in the Copilot Studio Test pane?",
    "options": [
      { "label": "Yes, I have the required privilege and access" },
      { "label": "No, I do not have the required privilege or access" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave every selection unset. The Connections and Maker validation answers are
privilege self-attestations for routing; the Preflight and Runtime answer is an
availability self-attestation. None is proof that the signed-in account has
the required role. The phase-specific live checks or structured administrator
evidence remain authoritative.

After the maker confirms the Workday administrator is engaged, the Workday
phase shares the checked-in detailed workbook with concise target values and
the applicable federation safety note, not another administrator task list.
It tells the maker to have the administrator follow and complete the workbook,
asks whether the task is complete, then requests the full local path to the
completed `.xlsx` file. It must not require an upload or ask the maker to paste
the worksheet table or retype the administrator values.
Do not include people from completed phases or remediation-only roles that are
not currently required. In particular, require the Workday Administrator only
when `nextPhaseId` is `workday-admin`; a healthy reused tenant foundation
on a controller-verified Test or Production promotion continues at Connections
without that role. A regular Entra workbook return must not take this shortcut.

If the maker selects a negative administrator-engagement option, stop before
dispatching the next phase and ask them to return when that administrator can
participate. If the maker selects a negative maker-privilege option, stop and
ask them to return after the required privilege or access is granted, or to
rerun the skill using the authorized maker account. If the maker selects the
negative generic availability option, ask them to return when the required
people are available. In every case, explain that no phase progress or target
configuration was changed. Do not request a person's name, credentials, or
other identifying information, and do not offer to bypass the role
requirement.

If the maker selects either affirmative option, dispatch the next phase below.
Within the same invocation, do not repeat the question while `nextPhaseId`
remains unchanged. After a phase completes and `status` returns a different
`nextPhaseId`, evaluate and ask for that new phase.

Dispatch from `nextPhaseId`:

Preflight dispatch is foundation-only: use the Preflight guide only for Setup's
initial Development target. For an active Test or Production target, do not
run `preflight` as a general prerequisite repair or recheck. Preserve its active
realm, scope, and phase evidence; use promoted-target discovery or the current
phase's supported recovery. If no target-preserving recovery is available,
show the exact blocker and stop rather than resetting the target.

- `preflight` -> read `install-extension.md`
- `entra` -> read `provision-entra-app.md`
- `workday-admin` -> read `configure-tenant.md`
- `connections` or `runtime` -> read `configure-power-platform.md`
- `maker-validation` -> read `verify-connection.md`

When a phase returns, run `status` again and continue from the controller's
next phase. Never restart completed phases because the user asked a side
question; answer the side question, then resume the same blocker.

## Completion

Only after controller status is `ready`, render the returned
`completionMessage`. Status and maker-validation completion return the same
realm-specific completion: all six steps are finished, the maker Test pane
validation passed, and no further Workday Connect action is required in that
realm.

Finish using **Finish the current Workday connection** in
`verify-connection.md`. Do not invoke Setup between phases or at completion;
its prerequisite handoff belongs only to `entry.md`, before this lifecycle
starts. Do not ask the maker to run Connect again for this completed realm.

Render `postSkillNextSteps`
under **Optional next steps**. These are
future deployment choices, not continued actions or another required phase.
Link to the known source agent in Copilot Studio for manual promotion, and
make the deployment-owner responsibility explicit. Do not start promotion or
another realm without an explicit maker request.

Do not tell a DEV maker to perform Production release validation, and do not
offer Production until TEST is Ready. Do not claim that a maker Test pane
success independently verifies published employee scenarios.
