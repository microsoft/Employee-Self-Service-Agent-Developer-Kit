# Guide and verify the Entra User Login application

Treat Entra registration as one complete high-level setup step. Render the one
executable protected-workbook question directly. Do not add a separate
Email/UPN/Pay ID routing question or pauses between Create App, claims, scope,
pre-authorization, permissions, and consent.

This is always an admin-owned guided workflow. Never run `az ad app create`,
Graph `POST`/`PATCH`, admin-consent mutation, or any equivalent write
operation. Never request or persist a client secret, certificate, password,
token, or PFX.

Read `adminSetup.phaseHandoffs.entra-registration` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, rerun
`identity-mapping-handoff --stage entra` to validate the current target-bound
evidence and reconcile any older derived reused handoff. Require
`decision: no-action`; do not ask again. Then return
`ACTION_RESULT = "recorded"` and let all four Entra checkpoints reverify the
current app. A prior `Failed`/`Error` or any other result outside
`completionStatuses` requires one new complete Entra handoff so the Maker can
return corrected bundled evidence.

## Shared Identity lookup

Before creating or returning an Entra workbook, run the local-only Shared
Identity lookup:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} shared-reuse-handoff
```

This command reads only the other ESS ServiceNow lifecycle in this workspace.
It makes no API call and considers only compatible administrator-confirmed
Entra application/claim evidence and ServiceNow OIDC/user-mapping evidence.
It does not include instance confirmation, physical connections, topics,
portal URL, agent binding, Test, Publish, lifecycle plan, or consent.

- `none`: continue the normal Entra workbook flow without a reuse question.
- `already-recorded`: continue; the owning Entra and OIDC checkpoints still
  evaluate the current evidence.
- `source-selection-required`: ask one label-only question from the returned
  candidate labels, then rerun with the selected internal `sourceKey`. Do not
  expose the key.
- `question-required`: pass the returned `question` object unchanged through
  the question tool. Its body contains the exact target, source agent, and
  eligible identity items; its `options` are label-only. Translate the
  selected label through `reuseDecisionChoices`.
  - **Reuse shared identity**: run
    `record-shared-reuse --source-key <internal-source-key> --decision accept`.
    This rechecks only local source hash/scope/bindings and imports only the
    listed identity evidence. It does not call Connectivity or mark the owning
    checkpoints Passed.
  - **Configure separately**: run
    `record-shared-reuse --source-key <internal-source-key> --decision decline`
    and continue normally.
  - **Not now**: record nothing and return `ACTION_RESULT = "waiting"`.

After an accepted reuse, rerun `identity-mapping-handoff --stage entra`.
If it returns `decision: no-action`, immediately return
`ACTION_RESULT = "recorded"`. Do not render or generate a workbook, call the
question tool, rerun `record-identity-mapping`, or replace the reused admin
handoff with `record-admin-phase`; the runner-owned Entra checkpoints still
run next. Only `decision: question-required` enters the missing administrator
work below. Partial reuse continues with only the missing administrator work.
Never infer physical-connection readiness from Shared Identity.

## Goal and owner

- **Goal:** register or verify one Entra app and configure the
  access-token identity claim names needed for ServiceNow user matching.
- **Owner role:** Application Administrator or Cloud Application
  Administrator. A Global Administrator may complete the task but is not
  required. An application owner may collaborate on app settings, but an
  appropriately authorized administrator must review any permission
  confirmation shown by the Task 1 claim flow.

## Complete admin instructions

The workbook includes one standalone
[Task 1 setup instruction](https://review.learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/declarative-agent-servicenow-hr-it?branch=main#task-1-register-an-application-in-microsoft-entra-id-for-oidc-integration-with-servicenow)
reference. Its numbered sign-in action links directly to
https://entra.microsoft.com/.

Generate the current protected Entra workbook before the handoff:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} identity-mapping-handoff --stage entra
```

Give the admin the returned `workbookPath`. The workbook opens on `Steps`,
which contains one fixed universal if/go-to flow covering existing healthy,
existing repair, and new-app paths plus standard and custom identity branches.
Runtime does not delete or splice Steps by scenario. `Worksheet` remains the
two-column administrator form. Current-stage editable
Token Claim Name cells are yellow and locked ServiceNow User Field cells are
gray. Administrator context remains visible; no ownership legend is needed.
The locked hidden `_metadata` sheet supports import integrity but is not
user-facing or authorization. Sheet protection prevents accidental edits;
import validation remains authoritative.

The command returns `instructionTitle`, `instruction`, and one short
`question` object. First render `instructionTitle` and `instruction` exactly as
the visible Step 1 explanation. The instruction contains `Purpose`, `Owner`,
`Known target`, and `Action`, with the dynamic workbook link paired with its
plain absolute path. Then send the returned `question` object unchanged
through the question tool. Both its `header` and `question` are exactly
`Please enter the returned Entra admin handoff workbook URL.` Do not use the
Step title as the question header, reconstruct the payload, or add an
unsupported placeholder field. This is the admin phase's only visible
high-level pause.

When `handoffMode` is `claim-only`, render the same returned Step 1
`instructionTitle`, `instruction`, and exact admin-handoff-workbook URL
question. The protected workbook carries the universal branch graph; the
administrator follows its applicable claim-only branch and verifies
already-healthy settings without changing them.

For every mode, trust only `Passed` checkpoint outcomes. `missingItems` may
control workbook fields and branch guidance, but must never modify the returned
short `question` object, add an identifier question, or crop the workbook
Steps. Unknown, stale, Failed, Error, and NotConfigured items remain
actionable. Passed items stay visible as verify-only branch instructions and
must not be changed when healthy.

The fixed workbook flow is:

- `Setup instructions` is followed by one blank-label quickstart link row.
- Step 1 signs in; Step 2 identifies the exact existing app and fills a yellow
  Application Client ID from Overview or verifies a read-only ID.
- When the existing app and required identity-claim configuration are ready,
  Step 2 goes directly to Step 7. When only the required claim is missing, it
  goes to Step 6. Only no-app + yellow-ID flows go to Step 3.
- Steps 3-5 reproduce the user-supplied new-registration sequence.
- Step 6 retains the user-approved identity dispatcher. Standard details stay
  in `6A.1-6A.5`; non-email attribute/emission details stay in `6B.1-6B.9`.
- Step 7 is the single final actual-issuance verification. Step 8 records the
  actual claim name, then Return saves the same workbook.

1. Open https://entra.microsoft.com/, then go to `Identity` → `Applications`
   → `App registrations`. Resolve the
   single-tenant app by the persisted Application client ID when known.
   When the ID is not yet available, use the current Connect tenant and
   ServiceNow instance to find the candidate app, then verify its Overview
   details before changing it. A display name is a clue, not unique identity.
   - If one exact app exists, reuse it. Fill a yellow client-ID cell from its
     Overview or verify a read-only ID exactly.
   - If multiple candidates exist, the Entra admin resolves the intended app
     inside this same high-level handoff and returns the selected client ID
     only with the final completion response. Do not add an intermediate
     selection pause.
   - Only when no correct app exists and the client-ID cell is yellow, select
     `New registration`; no redirect URI is required.
2. In `Token configuration` -> `Optional claims`, review the configured rows
   whose `Token type` is `Access`, then complete the protected workbook:
   - a claim is the name of employee information sent during sign-in;
   - read the stage-specific `Steps` sheet first;
   - on `Worksheet`, enter one employee-identity candidate claim per yellow
     Token Claim Name cell;
   - candidates may include `email`, `upn`, or a tenant-approved custom claim;
   - never enter `aud`: it is the audience claim, not an employee identity candidate;
   - confirm every returned candidate name is actually issued for the
     representative ServiceNow OIDC resource application, not for Microsoft
     Graph. Use only an organization-approved sign-in/test method. The
     Optional claims screen alone does not prove emission;
   - never copy, upload, paste, or return the issued token;
   - for tenant claims-mapping policy, use `acceptMappedClaims` only when the
     tenant security policy permits it; otherwise use the tenant-approved
     custom signing-key route. Never return signing material;
   - do not add employee values, tokens, secrets, passwords, certificates, ServiceNow fields, or extra worksheets.
   - the Entra admin owns attribute population and claims policy internally; the workbook does not collect an Entra source attribute.
   - for a `Pay ID / employee ID` or another non-email identifier, the Entra
     admin follows the workbook's `6B` branch to:
     1. ensure the approved directory attribute exists and is populated for
        every intended ServiceNow user; only when population is missing, use
        the customer's existing approved HR provisioning, directory sync, or
        direct administration method; and
     2. verify the real ServiceNow resource app already emits that attribute
        as a claim; only when the claim is missing, configure the applicable
        approved claim policy, then verify its actual non-email representation
        and issuance and return only the actual claim name.
     If the customer uses
     [cloud HR provisioning](https://learn.microsoft.com/en-us/entra/identity/app-provisioning/plan-cloud-hr-provision),
     use that approved existing method only when population is missing. If the customer uses
     [directory sync](https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/reference-connect-sync-attributes-synchronized),
     confirm the chosen attribute is synchronized. Do not require both methods.
     Use
     [JWT claims customization](https://learn.microsoft.com/en-us/entra/identity-platform/jwt-claims-customization)
     only for the applicable claim-policy guidance. Do not assume a claim name
     or collect the source attribute/value. If custom signing or
     `acceptMappedClaims` is required, follow tenant security approval and
     confirm the ServiceNow validation metadata/JWKS, issuer, and token version
     are compatible before completing the handoff.
API URI and connector pre-authorization remain separate checks. This Task 1
workbook does not configure them or prove them complete. Keep their existing
checkpoint results and remediation independent.

## Completion signal and evidence

The Maker should answer the executable question once, after its missing
actions are complete, with the local path of:

- the completed protected Entra workbook containing the non-secret
  Application (client) ID when requested and the confirmed candidate claim
  names. This administrator-completed workbook represents their confirmation
  that the Task 1 registration/claim work and actual claim emission are
  complete.

The executable `identity-mapping-handoff --stage entra` question uses
`allowFreeformInput: true`. Its visible wording says “admin handoff workbook
URL” because that is the approved Maker-facing term, but the accepted value
remains the local path (or supported local file URI) of the
administrator-completed template. The generated workbook link and plain
`workbookPath` in
`instruction` identify the blank template to open; they are not the returned
answer. The Maker may return that same local file after the administrator
fills it, or a returned copy saved locally. A VS Code attachment is usable
only through its actual local path. Do not accept an HTTP/SharePoint/OneDrive
URL, workbook contents pasted into chat, or a completion word as a file path.
No answer or cancellation returns `ACTION_RESULT = "waiting"` without
recording completion.

There is no separate client-ID question. When the ID is unknown or the app was
replaced, the workbook shows one yellow Application Client ID cell above the
claim rows. The Entra admin fills that GUID and one or more yellow Token Claim
Name rows, then returns the same workbook. When the ID is already known, that
cell is prefilled, gray, and locked.

The protected workbook is required. If it is missing, malformed, changes the
`Steps` / `Worksheet` / hidden `_metadata` order or visibility, contains
`aud`, duplicate candidates, formulas, changed context, changed editable
markers, a missing/invalid Application client ID, a prefilled ServiceNow
field, or no candidate claims, return
`ACTION_RESULT = "waiting"` with the exact error.

Use the exact local path returned by the question. Validate the protected
structure, target binding, stage, frozen context, Application client ID, and
actual emitted claim names from that file, then import the Entra return.
Supplying a path is not completion; successful validation and import are still
required before the phase can advance. A missing path, missing file,
non-`.xlsx` file, malformed or changed protection/metadata, wrong target or
stage, stale candidate set, invalid client ID, `aud`, or missing actual claim
names returns `ACTION_RESULT = "waiting"` with the exact correction:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-identity-mapping --stage entra --workbook-file "<completed-xlsx-path>" --yes
```

Then record one bundled phase handoff. Use `reused` for a valid existing app
and `completed` for an app that required configuration:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-admin-phase --phase entra-registration --status <completed|reused>
```

Do not call FlightCheck from this action document. Runner-owned checkpoint
target: `SN-DA-HRSD-ENTRA-*`. Return the action result below and let lifecycle
runner L.4b invoke that registered family once.

Do not run the four checkpoint IDs as separate CLI processes. The family
invocation preserves their individual IDs, statuses, results, and remediation
while sharing one category evaluation and one logical set of read-only API
calls. A `Failed` or `Error` result is authoritative and cannot be overridden
by the completion confirmation.

Return `ACTION_RESULT = "recorded"` after the bundled phase handoff is
persisted. Do not decide checkpoint success in this action: lifecycle runner
L.4b invokes the family once, and its four member results are authoritative for
phase completion or blocking.
