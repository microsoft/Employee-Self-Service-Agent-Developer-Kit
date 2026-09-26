<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Connect Workday to the ESS HR agent

This skill is a thin conversational client for
`scripts/workday_connect.py`. The controller and
`.local/connect/workday-da/config.json` own lifecycle state. Do not create,
copy, update, or infer status from a Markdown checklist.

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

## Capability contract

Describe each action according to who actually performs it:

| Phase | What the skill can do | What remains a user or administrator action |
| --- | --- | --- |
| Preflight | Verify the selected agent, environment, account, and package; install the reviewed package through PAC when needed | Complete Microsoft sign-in and choose an environment when no exact URL is known |
| Microsoft Entra | Discover exact applications, validate roles, generate one administrator handoff, reread Graph, and record verified evidence | Create or change the Entra application in the portal |
| Workday administrator | Generate the handoff, validate returned non-secret values, derive endpoints, and record evidence | Change SAML, OAuth, API-client, certificate, or authentication-policy settings in Workday |
| Connections | Discover connected physical connections, verify agent parameter sharing, and record the maker's flow-attachment confirmation | Create connector connections, complete connector OAuth, connect flows to the agent, and enable parameter sharing in Copilot Studio |
| Runtime | After approval, bind reviewed solution connection references, activate reviewed package flows, configure delegated authorization, redirect an empty User Context scaffold, and reread every write | Resolve custom topic content or a package without a reviewed runtime catalog |
| Employee validation | Record safe validation evidence and retain the current blocker | Publish the agent, sign in as an employee, and run the real employee scenario |

Never say "I changed," "I configured," "I enabled," or "I updated" for a
manual action. Say what the administrator or maker must do, then say what the
skill can verify or record afterward. Claim an automated change only after its
command succeeded and the target was reread.

## Start or resume

Run:

```powershell
python scripts/workday_connect.py status
```

Show only the returned `progressText`, current blocker when present, and the
next phase. Do not render internal action IDs, hashes, or the full JSON state.

The six customer-facing phases are:

1. Preflight
2. Microsoft Entra
3. Workday administrator
4. Connections
5. Runtime configuration
6. Employee validation

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
