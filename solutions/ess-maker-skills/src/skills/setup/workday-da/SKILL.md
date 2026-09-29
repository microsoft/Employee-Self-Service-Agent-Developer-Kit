<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Connect Workday to the ESS HR agent

Guide the customer through one resumable Workday connection lifecycle. Use
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
- Explain an authentication prompt before launching it. Azure CLI/Graph, PAC,
  Dataverse, connector OAuth, and Agent Builder are separate credential stores;
  a prompt for a different store is expected, but a valid store must not be
  prompted twice for the same account and session.
- Preview the exact target and actions before approval. After approval, verify
  the plan hash immediately before every mutation. If discovery or scope
  changes, discard the approval and show the new plan.
- After every mutation, reread the target and persist evidence only after the
  verified result matches the approved plan.
- Never diagnose a permission problem from a guess. Show the API, CLI, or
  checked-in script evidence that produced the diagnosis.
- Use structured `vscode_askQuestions` forms for customer evidence. Never
  replace a multi-field form with one large free-text question or ask the
  customer to edit a prose template.
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

| Phase | What the skill can do | What remains a user or administrator action |
| --- | --- | --- |
| Preflight | Verify the selected agent, environment, account, and supported Workday package; install the package when needed | Complete Microsoft sign-in and choose an environment when no exact URL is known |
| Microsoft Entra | Discover exact applications, validate roles, generate one administrator handoff, reread Graph, and record verified evidence | Create or change the Entra application in the portal |
| Workday administrator | Generate the handoff, validate returned non-secret values, derive endpoints, and record evidence | Change SAML, OAuth, API-client, certificate, or authentication-policy settings in Workday |
| Connections | Record the reviewed physical-connection readiness evidence | Create connector connections and complete connector OAuth |
| Runtime | After approval, bind the Workday connections, activate the package flows, configure required runtime permissions, connect employee context routing, enable every Workday topic included with the agent, and verify the result | Connect flows to the agent and enable parameter sharing in Copilot Studio when those settings require maker interaction |
| Employee validation | Record safe validation evidence and retain the current blocker | Publish the agent, sign in as an employee, and run the real employee scenario |

Never say "I changed," "I configured," "I enabled," or "I updated" for a
manual action. Say what the administrator or maker must do, then say what the
skill can verify or record afterward. Claim an automated change only after its
command succeeded and the target was reread.

## Tenant foundation and deployment scope

Treat the Entra and Workday configuration as a reusable tenant foundation.
Treat package installation, physical connections, runtime flow wiring, native
topics, publishing, and employee validation as environment-and-agent-specific
deployment work.

- A different Power Platform environment, ESS HR agent, or maker account must
  not by itself require the Entra or Workday administrators to repeat setup.
- When the Entra tenant, Workday tenant, and exact Entra application still
  match stored foundation evidence, reread the Entra configuration. If it is
  healthy, reuse the stored Workday administrator evidence and continue at
  Connections.
- Involve an administrator only when foundation evidence is absent, the
  tenant/application identity changed, the Entra reread finds drift, the
  signing certificate changed or is unhealthy, or a later connection/runtime
  test proves the stored Workday configuration no longer works.
- Never reuse foundation evidence across a different Entra tenant, Workday
  tenant, SAML Service Provider ID, Entra application, or signing certificate.
- Preserve the full administrator guide even on the reuse path, but show only
  the affected remediation step instead of making the user repeat healthy
  configuration.

## Start or resume

Before running status, show this readiness briefing on every invocation. A
resumed setup must still make its remaining administrator dependencies clear.

> Here's who may be needed to connect Workday to your ESS HR agent:
>
> | Phase | Responsibility | Who is needed |
> | --- | --- | --- |
> | Preflight | Verify the ESS HR agent and environment, and install or verify the supported Workday package | Power Platform Environment Maker with package installation access |
> | Microsoft Entra | Configure the Workday enterprise application, SAML, API permission, consent, assignment, and NameID | Application Administrator or Cloud Application Administrator; a consent-capable administrator when required |
> | Workday administrator | Configure tenant SAML and certificate trust, OAuth and the API client, functional-area access, endpoints, and the employee authentication policy | Workday Administrator |
> | Connections | Create the Workday OAuthUser and Dataverse connections and complete connector sign-in | Power Platform Environment Maker |
> | Runtime configuration | Connect the installed Workday components, activate the required flows, configure runtime permissions and connection sharing, and enable all Workday topics | Power Platform Environment Maker; Dataverse System Administrator access for runtime authorization |
> | Employee validation | Publish the agent and validate a real signed-in employee scenario | Environment Maker and Workday test employee; Workday Administrator or network administrator if remediation is needed |
>
> I'll automate checks and supported changes where reliable APIs are available.
> For Workday or portal-only settings, I'll provide the responsible
> administrator with the exact steps and wait for verified evidence. The
> environment isn't ready until the signed-in Workday scenario succeeds.

After showing the briefing, use this exact `vscode_askQuestions` form before
running any lifecycle command:

```json
[
  {
    "header": "Required access",
    "question": "Are the people needed for every applicable role above available to help when their phase begins?",
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
phase-specific permission checks and verified evidence remain authoritative.

If the maker selects **No, someone is unavailable**, stop before running
`status` or any phase command. Explain that no setup progress was changed and
ask them to return when the required person can participate. Do not request
the person's name, credentials, or other identifying information, and do not
offer to bypass the role requirement.

If the maker selects **Yes, required people are available**, continue with the
status check below.

Run:

```powershell
python scripts/workday_connect.py status
```

After the readiness briefing:

1. Render the returned `progressText` as Markdown. It is the visible six-row
   roadmap and must not be collapsed into a one-line phase list.
2. Render the returned `nextPhaseSummary` in this form:

   ```markdown
   ### Next phase: {title}

   What happens in this phase:

   - {whatHappens item 1}
   - {whatHappens item 2}
   - {whatHappens item 3}
   ```

3. Show the current blocker afterward when one is present.

Do not render internal action IDs, hashes, or the full JSON state. Do not
replace the phase explanation with only `Next phase: {title}`.

Dispatch from `nextPhaseId`:

- `preflight` -> read `install-extension.md`
- `entra` -> read `provision-entra-app.md`
- `workday-admin` -> read `configure-tenant.md`
- `connections` or `runtime` -> read `configure-power-platform.md`
- `employee-validation` -> read `verify-connection.md`

When a phase returns, run `status` again and continue from the controller's
next phase. Never restart completed phases because the user asked a side
question; answer the side question, then resume the same blocker.

## Completion

Only show the following after controller status is `ready`:

> Your ESS HR agent is connected to Workday, and the signed-in employee path
> has been validated in this environment.
