<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Connect Workday to the ESS HR agent

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
  exception: collect all required administrator values in one response and
  pass the untouched text to the controller's worksheet parser. Accept the
  generated table or a recognizable labeled response without asking the
  customer to reformat it. Accept only the resulting validated structured
  payload. Reject missing, duplicate, or unknown labels; never infer an answer
  or treat the raw text as evidence.
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
  A different environment, agent, or maker account may require current
  confirmation, but it must not make the administrator repeat healthy tenant
  configuration.
- Never reuse foundation evidence across a different Entra tenant, Workday
  tenant, SAML Service Provider ID, Entra application, or signing certificate.
- Preserve the full administrator guide even on the reuse path, but show only
  the affected remediation step instead of making the user repeat healthy
  configuration.

## One-way administrator handoff

Treat the two administrator phases as a one-way relay between different
people:

1. Microsoft Entra sign-off must finish first, including transfer of the
   active Base64 signing certificate through the customer's approved channel.
2. Only then may the Workday administrator phase begin.
3. The Workday handoff consumes the recorded Entra identifiers, certificate
   metadata, and transferred certificate file. It must not ask the maker to
   reopen Entra, re-engage the Entra administrator, or repeat an Entra task.
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

## Start or resume

Before running status, show this readiness briefing on every invocation. A
resumed setup must still make its remaining administrator dependencies clear.

> Here's who may be needed to connect Workday to your ESS HR agent:
>
> | Phase                 | Responsibility                                                                                                                                             | Who is needed                                                                                                        |
> | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
> | Preflight             | Verify the ESS HR agent, environment, maker account, and supported package choice without changing the environment                                         | Power Platform Environment Maker                                                                                     |
> | Microsoft Entra       | Configure the Workday enterprise application, SAML, API permission, consent, assignment, and NameID                                                        | Application Administrator or Cloud Application Administrator; a consent-capable administrator when required          |
> | Workday administrator | Configure tenant SAML and certificate trust, OAuth and the API client, functional-area access, endpoints, and the employee authentication policy           | Workday Administrator                                                                                                |
> | Connections           | Install or verify the supported Workday package, then create the Workday OAuthUser and Dataverse connections and complete connector sign-in                | Power Platform Environment Maker with package installation access                                                    |
> | Runtime configuration | Connect the installed Workday components, activate the required flows, configure runtime permissions and connection sharing, and enable all Workday topics | Power Platform Environment Maker; Dataverse System Administrator access for runtime authorization                    |
> | Maker validation      | Smoke-test an enabled Workday scenario in the Copilot Studio Test pane without publishing; publishing and non-maker validation are post-skill next steps | Environment Maker |
>
> I'll automate checks and supported changes where reliable APIs are available.
> For Workday or portal-only settings, I'll provide the responsible
> administrator with the exact steps and wait for verified evidence. The
> guided lifecycle completes after the maker's Test pane scenario succeeds.

Run:

```powershell
python scripts/workday_connect.py status
```

If this invocation carries an explicit promotion intent, use the returned
target registry before the normal ready-state completion branch:

- For Test, require the DEV target to be `ready`, then run
  `discover-realm-target --realm test`.
- For Production, require the TEST target to be `ready`, then run
  `discover-realm-target --realm prod`.

If the prerequisite realm is not Ready, keep that realm active and explain
that its Maker validation must finish before configuring the next realm. If
discovery succeeds, render the newly active target's status and continue from
its current phase. Do not show the previous realm's completion message and do
not ask the general integration-selection question again.

The controller runs automatic readiness checks at the relevant phase
boundaries. Present only the resulting customer-safe readiness
or remediation state; do not expose internal profile/checkpoint identifiers or
ask the customer to run a second validation workflow.

After the readiness briefing:

1. Render the returned `progressText` as Markdown. It is the visible six-row
   roadmap and must not be collapsed into a one-line phase list.
2. Render the returned `nextPhaseSummary` in this form:

   ```markdown
   ### Current phase: {title}

   What happens in this phase:

   - {whatHappens item 1}
   - {whatHappens item 2}
   - {whatHappens item 3}
   ```

3. Show each non-empty customer-safe `readiness.summary` returned for a phase.
   This confirms which automatic readiness checks passed without exposing
   profile or checkpoint identifiers.
4. Show the current blocker afterward when one is present. Use its `summary`
   and `nextAction`; do not render any other blocker fields.

Do not render internal action IDs, hashes, or the full JSON state. Do not
replace the phase explanation with only `Current phase: {title}`.

If controller status is `ready`, skip the availability question and show the
realm-aware completion message below.

For a non-ready lifecycle, determine the current phase's required participants
from `nextPhaseId`:

| `nextPhaseId`         | People required for the current phase                                                                                                                                                                       |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `preflight`           | Power Platform Environment Maker                                                                                                                                                                            |
| `entra`               | Application Administrator or Cloud Application Administrator to identify or confirm the exact application and return the guided evidence; a consent-capable administrator when the handoff requires consent |
| `workday-admin`       | Workday Administrator                                                                                                                                                                                       |
| `connections`         | Power Platform Environment Maker with package installation access                                                                                                                                           |
| `runtime`             | Power Platform Environment Maker with Dataverse System Administrator access for runtime authorization                                                                                                       |
| `maker-validation`    | Environment Maker                                                                                                                                                                                           |

When `nextPhaseId` is `entra`, dispatch to `provision-entra-app.md` without the
form below. That phase asks whether the maker has looped in the administrator,
presents the guided handoff, and validates the returned non-secret evidence.
It must not authenticate the maker to Graph or perform live Entra API checks.

When `nextPhaseId` is `workday-admin`, show only its row and use this exact
`vscode_askQuestions` form before dispatching that phase:

```json
[
  {
    "header": "Workday administrator",
    "question": "Have you looped in the Workday administrator to complete the next phase?",
    "options": [
      { "label": "Yes, the Workday administrator is engaged" },
      { "label": "No, I still need to engage the Workday administrator" }
    ],
    "allowFreeformInput": false
  }
]
```

For every other returned `nextPhaseId` except `entra`, show only its row and
use this exact `vscode_askQuestions` form before dispatching that phase:

```json
[
  {
    "header": "Required access",
    "question": "Are the people needed for the next phase available to help when that phase begins?",
    "options": [
      { "label": "Yes, required people are available" },
      { "label": "No, someone is unavailable" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. This is an availability self-attestation for
planning, not proof that the signed-in account has a required role. The
phase-specific live checks or structured administrator evidence remain
authoritative.
Do not include people from completed phases or remediation-only roles that are
not currently required. In particular, require the Workday Administrator only
when `nextPhaseId` is `workday-admin`; a healthy reused tenant foundation
continues at Connections without that role.

If the maker selects either negative option, stop before dispatching the next
phase. Explain that no phase progress or target configuration was changed and
ask them to return when the required person can participate. Do not request
the person's name, credentials, or other identifying information, and do not
offer to bypass the role requirement.

If the maker selects either affirmative option, dispatch the next phase below.
Within the same invocation, do not repeat the question while `nextPhaseId`
remains unchanged. After a phase completes and `status` returns a different
`nextPhaseId`, evaluate and ask for that new phase.

Dispatch from `nextPhaseId`:

- `preflight` -> read `install-extension.md`
- `entra` -> read `provision-entra-app.md`
- `workday-admin` -> read `configure-tenant.md`
- `connections` or `runtime` -> read `configure-power-platform.md`
- `maker-validation` -> read `verify-connection.md`

When a phase returns, run `status` again and continue from the controller's
next phase. Never restart completed phases because the user asked a side
question; answer the side question, then resume the same blocker.

## Completion

Only show the following after controller status is `ready`:

> Your ESS HR agent is connected to Workday in **{ACTIVE_REALM}**, and the
> maker smoke test passed in that realm's Copilot Studio Test pane.
>
> **Next steps after this guided setup:**
>
> 1. Publish and deploy the agent when ready.
> 2. If this is Development and the agent has been promoted, return here and
>    say **I promoted the agent to Test**.
> 3. If this is Test and the agent has been promoted, return here and say
>    **I promoted the agent to Production**.
> 4. For the final release realm, have each non-maker employee establish their
>    own Workday connections in Microsoft 365 Chat and validate an enabled
>    Workday scenario with the published agent.
>
> Promotion is performed by the maker outside this skill. Publishing,
> employee-owned connections, and non-maker validation are deployment and
> adoption steps outside the guided realm lifecycle.

Show only the numbered item relevant to the active realm. Do not tell a DEV
maker to perform Production release validation, and do not offer Production
until TEST is Ready.
