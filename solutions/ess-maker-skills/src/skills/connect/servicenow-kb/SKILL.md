---
name: connect-servicenow-kb
description: Walk native ESS HR or IT Development through every required ServiceNow Knowledge Simple or Advanced configuration and acceptance step.
---

# ServiceNow Knowledge guided lifecycle

Run commands from the maker workspace root; do not change another agent's state.
Use structured questions for scope choices, change approval and actual
observations. Report `SERVICENOW_KB_ERROR_JSON`, `stepError` and nonzero exits
explicitly. Never interpret a failed or skipped operation as successful setup.
Do not add an optional "Non-secret findings or blocker" question or a separate
notes field. Ask only for the current step's required observation; if it fails
or is blocked, report that explicitly and guide correction in the same step.
Do not generate, share or request Excel handoffs. Stay with the user through
the entire [configuration walkthrough](configuration.md).

## Customer-facing guidance before questions

Follow Workday's instruction-first presentation, not its Excel handoff.
Render the applicable numbered walkthrough as a visible chat message before
showing the existence, confirmation or retry question. Include the saved instance
or target link, exact portal navigation and required field values. Show only the
current branch; do not bury the walkthrough inside a long question detail.
If the user asks how to perform the step, show the affected instructions again
before another question. A broad "review everything" or "confirm all settings"
request is not a substitute for executable instructions.

Describe the current phase, responsible administrator, concrete action, expected
result and concise correction. Keep Act / Verify labels, checkpoint IDs, state
keys, commands and execution-only cautions internal unless diagnostics are asked
for. Show necessary security guidance only at the affected action. Do not repeat
it around the walkthrough or suggest the assistant performed a manual change.
Ask one concise result question after the walkthrough; never infer completion
from approval, existence or an incomplete review.
Collect the test article number and its Knowledge Base sys_id in one form with
two fields when both are pending, after showing both lookup instructions.
Record `test-article` then `test-kb` separately, refreshing status between them;
keep their existing validation and connection/scope guards. On resume ask only
for missing or corrected details, not valid saved answers.
Present the source/indexed denied-reader comparison as one **Optional,
recommended** action with **Run recommended access check** and **Skip**.
Guide finding a source-denied ordinary user and using their mapped Entra identifier
privately in Check user access. Do not store that identifier. One combined result
uses `confirm --step denied-reader` with `confirmed`, `skipped` or `unverified`;
this records both internal outcomes atomically. Skip is not a pass and cannot
clear a reported failure. Do not require a denied reader when selecting the article.

## Target and scope

After [entry prerequisites](entry.md), run:

```powershell
python scripts\servicenow_kb_connect.py status
```

Resume the recorded `nextStep`; do not repeat completed healthy work.
For a new journey, confirm the instance HTTPS origin, all KBs or explicit KB
sys_ids, and the selected Simple/Advanced flow. The permission-flow question
must show exactly two explicit choices:

- **Simple** - supported non-scripted criteria.
- **Advanced** - applicable scripted criteria.

Do not offer "Unknown" or "administrator assessment needed" as a third choice.
If the maker cannot select a flow, pause for the administrator to assess it using
[shared guidance](shared.md); do not guess Simple from one global query.
Guide the authorized administrator through the scoped assessment in this journey.

Do not ask the maker whether the scope includes HRSD content, either upfront or
as a replacement question later. HRSD applicability and required access checks
belong to the ServiceNow administrator's **HR scoped reads** guided check.
An omitted upfront classification is unassessed, not "No"; do not infer it from
the agent being HR or IT. No new sign-in is required by this local controller.

```powershell
python scripts\servicenow_kb_connect.py start --instance "<HTTPS origin>" --query "active=true^workflow_state=published" --flow simple
```

Use `--flow advanced` for Advanced. A KB restriction is
`^kb_knowledge_base=<32-character sys_id>` or
`^kb_knowledge_baseIN<comma-separated sys_ids>`. Arbitrary scripted queries,
article selection/classification and cross-machine progress sync are outside
this MVP. Explain these limits rather than silently changing scope.
Leave `--hr-content` omitted during normal entry. The optional flag remains
compatible with previously administrator-established classifications. Resuming
unchanged content scope retains an existing classification and its valid evidence.

If the target, instance, tenant, query or flow changes, rerun `start` with the
new approved scope. It invalidates dependent evidence and rejects confirmations
for earlier scope fingerprints. Changing the instance/tenant resets administrator evidence; changing
content/flow retains healthy shared identity/auth/read confirmations; changing
only the native target retains source setup but clears maker acceptance.

## One continuous guided journey

For each `nextStep`, read its exact section in [configuration.md](configuration.md)
and the applicable [shared prerequisites](shared.md).

For the selected **Simple** flow, present a standalone Microsoft-documented
Simple journey. Do not import our Advanced run's role names, scripts, endpoint
ACLs or completion claims. Do not require `copilot_connector` or another custom
role as a Simple prerequisite. Show the published Federated Auth roles and the
saved role assignments during setup. Show the mandatory Simple read surface
only in the later access-validation steps, with feature-dependent access only
when included. Do not ask for a vague table-grant review or untested READ confirmation.
Additional custom grants are conditional, not a mandatory Advanced-setup replay.
Keep Advanced support separate and do not delete or change its existing resources.

Treat first-time integration-user setup as configuration work, not an immediate
read-access examination. Guide documented role assignments and the
`permission-setup` first; default Simple confirms saved roles, while specifically
identified, approved corrections and applicable HR grants use inline instructions.
Reuse existing approved grants without duplicating ACLs. Guide each required
action in chat with navigation and field values, never an external table-access
procedure handoff. Reuse the saved current-scope role confirmation without
repeating the question.
Confirm saved configuration only at this checkpoint: **Permissions configured;
access tests pending**. It does not record Common table reads or other read
results as passed. Do not start Access Analyzer or a read-test questionnaire here.
After identity/API setup, guide the separate common/HR and flow-specific
source-permission preflights. These must pass before opening the connector wizard.
The `property-reads` step first guides Name/Value checks on both actual property
records, using the integration-user display name and exact User ID. Ask for the
result; record `confirmed` for verified reads, `unreadable` for reported blocked
access or `unverified` for inconclusive checks. For unresolved access, show
Microsoft's restrictive-default warning, recommend contacting the ServiceNow
administrator, then ask whether to continue without this access. Only an explicit
Yes records `proceed-without-access`; No, silence or cancellation pauses setup.
Do not start inline ACL troubleshooting or mistake a read result for consent.
Then complete authentication settings, content/mappings, source permissions,
audience, schedules and the approved Create action in one continuous wizard session.
Do not keep an unsaved form open while sending the user to Access Analyzer.
For a new draft, choose **Custom setup**, select **Authorize** with the saved
Federated Auth settings and verify the actual successful result before Create.
Failed or unavailable authorization pauses setup for correction/screen inspection.
Do not assume sample-fetch success unless separately displayed. Authorization
success is not completed ingestion or reader-permission evidence; a legacy
settings-only confirmation does not establish authorization for an unfinished draft.
After explicit creation approval and recording the connection name, verify actual
operation in **connection-ready** with that saved `--connection-name`. This fresh
checkpoint is required even when old grouped Ready evidence or reader observations
exist; preserve them without upgrading their provenance. Still-processing or
failed operation is not Ready and must not lead to another Create.

Before requesting the `service-principal` Object ID, introduce the Federated
Auth phase using that step's opening explanation in `configuration.md`. On resume,
explain how the current authentication step fits this phase without repeating
healthy checks. Present the current step, not the whole runbook or an
administrator questionnaire:

For a configuration item that may already exist, first establish existence
separately from configuration and verification. Show only where to check and
the exact identifier, then ask **Does this <item> exist?** with **Yes**, **No**,
and **I can't check**, all initially unset. Do not mix creation instructions or
an "all settings match" question into this existence check.

- **Yes:** guide inspection of the existing item; reuse correct settings and
  guide targeted correction where needed.
- **No:** give the documented creation steps directly, without another permission
  questionnaire for manual work within the approved setup.
- **I can't check:** pause for the relevant administrator/access prerequisite;
  do not infer absence or completion.

Use an explicit current-scope answer already supplied instead of asking again.
Do not add this question to read-only diagnostics or completed healthy steps.
First-party Entra application absence remains a blocker, not a creation branch.
An existence answer is not verified configuration: do not pass Yes/No to `confirm`
or advance a checkpoint before its required Verify observation.

1. Explain the purpose and required administration identity. Use a task-oriented
   heading such as **Create or verify the ServiceNow integration user**, not
   "Match the integration identity."
2. **Act:** after the applicable existence branch is known, provide the exact
   portal navigation and concrete settings for the
   recorded tenant/instance/flow. Inspect existing configuration first and reuse
   it when correct. If missing or incorrect, explain the necessary create/update
   action and its impact, then guide the authorized user directly through the
   documented manual action within the approved setup. Do not ask a separate
   "Do you want to add it?" or "Approve assigning the documented roles" question.
   Honor required administrator authorization; if it is unavailable, pause.
   Obtain explicit approval for actions outside the approved scope or executing
   scripts. A missing-item report does not authorize assistant-made remote writes.
   Do not begin with a matching questionnaire or treat approval as completion.
   The user performs portal actions or approved scripts; missing privileges pause
   the step, not send a workbook or mark it complete on somebody's behalf.
3. **Verify:** after the action, provide the specific saved-setting inspection or
   observed test and ask only for its required result or non-secret value.
   If reuse is already verified, do not repeat writes. For read-only steps, Act
   means inspect, retrieve or run the described test, not invent a remote change.
   Failed verification leads to targeted correction and re-verification.
4. Record only the user's observed result using the current scope fingerprint:

```powershell
python scripts\servicenow_kb_connect.py confirm --step "<nextStep.id>" --value "<observed value>" --target-reference "<targetReference from current status>"
```

Use `confirmed` only for the passing check defined by that step. Connection name,
required source IDs, audience and tested article/KB use actual values.
Do not ask for an acceptance observation time or timezone: the controller
automatically records UTC when required acceptance checks finish. Existing
observation times remain unchanged; `start` finalizes older completed checks
missing only the time from their recorded evidence, not the current resume time.
Do not ask for an
assessment completion date after the current review: confirming `scope-assessment`
automatically records its UTC date. Existing historical assessment dates remain
unchanged; the date step is only for an explicit legacy-date correction.
For **connection-ready** and every reader-validation step, also pass
`--connection-name "<saved connection name>"`
from the connection being tested. This must match the saved connection; do not
substitute another name into an observation made against another source.
Use the actual name shown in ESS Knowledge, reusing a name already supplied;
do not ask for a technical Connection ID. Disambiguate duplicate names using
the instance, flow and approved scope rather than guessing.
Reviewed HRSD non-applicability uses `not-applicable`; an unanswered maker
question does not establish it. Keep the fingerprint internal, not another
question for the user. Do not run confirmations in a prefilled "all confirmed"
batch. The user need not edit JSON or execute the local bookkeeping commands.

On failure, record the nonpassing result (for example `unverified`) to block
progress and invalidate dependent checks, then guide the targeted correction.
Never copy credentials, article bodies, employee identities, membership exports,
sensitive prompts or authenticated captures into step values or committed files.
Refresh status after each record; it returns the next eligible step.

## Required coverage

The shared setup path covers the scoped permission assessment and date, Entra
service principal, release-specific ServiceNow OIDC provider, machine integration
user, approved roles/ACL configuration, identity mapping and applicable HRSD
role assignment. Simple configures its four attribute-table grants. Advanced
adds approved V2 API installation/reuse, resource security and namespace.

Use supported ServiceNow-side diagnostics for common row/field reads,
HR-scoped reads and the Simple attribute reads or Advanced resource/ACL tests;
do not assume an authenticated gallery session exists before Create.
For permission properties, check first, then show the warning and administrator
referral if access is unresolved. Ask a separate Yes/No continuation question;
never continue automatically. Historical `deferred-to-admin` results require
fresh consent, while verified reads and explicit approved continuation are reused.
Surface returned
`warnings` on resume and final summaries, even after representative maker tests;
guided validation is not proof that deferred property access was resolved.
Only after these preflights, open the gallery wizard or inspect the exact existing
connection. For a new draft, review Federated Auth settings and verify Custom
setup's Authorize success. Continue directly through content and identity mapping, source
permissions, audience, schedules, creation and crawl/error review.
Do not restart the wizard or create a duplicate on resume.
After creation, verify actual operation against the recorded connection name;
only then continue to indexed-content and reader acceptance.

The Microsoft 365 AI administrator creates or reuses the **ServiceNow Knowledge
gallery connection**, confirms its actual connection name, instance,
Federated Auth, query and selected flow. Advanced uses the assessed API namespace.

Explain both rollout options and ask the user to choose: **organization-wide**
(limited-audience toggle off) or **selected users/groups** (toggle on).
Neither is a forced default; reuse an explicit choice for this deployment.
Both preserve source permissions: Users remains
**Only people with access to this data source**.
**Everyone** in Users grants source access and is not the
organization-wide rollout setting. Copilot Chat/Search visibility is not a
completion requirement for an ESS-only deployment. Network escalation is
conditional on an observed block. Optional Advanced `user_changes` and auditing
remain outside this MVP; do not enable incremental identity sync without them.

## Native source attachment and acceptance

Finish connector/index verification before opening ESS: review processing/errors,
select the test article/KB, confirm Indexed and compare native ServiceNow access
with indexed allowed permissions. Offer the grouped optional denied-reader
comparison or Skip. Missing, failed or pending required checks pause
here; ESS attachment is not an indexing workaround.

The maker opens the exact selected native HR/IT Dev agent, confirms its current
identity/environment/realm, attaches the exact Knowledge connection through
the supported authoring interface and checks its Knowledge source entry.
Do not invent an attachment API or claim local metadata verifies deployed
freshness. Current FlightCheck `EXT-002`, `EXT-002-ACL` and `CONFIG-013` remain
manual at their indexing/ACL boundaries; a Manual result is not Passed.

Use the already verified article, KB and allowed/denied readers for the
**same article and exact connection**. The allowed reader must
also obtain a relevant ESS answer and matching article citation. Isolate this
source so an overlapping connector cannot supply the result. Guide a detailed,
article-specific question describing the topic, scenario and requested steps,
then inspect the answer and open supporting citations to the correct article/KB.
A bare article number or a returned link alone is not an answer/citation test.
A citation URL
alone cannot distinguish two connections indexing the same article.

The walkthrough saves the tested article and KB, attachment, indexing, isolated
source, four native/indexed reader outcomes, answer/citation and actual observation
time as individual steps. No manually prepared acceptance file is required.
Each `confirmed` attests the described observation: denied readers **were
denied**, not granted. Do not derive these from API existence or schema creation.
Only completing all required observations and confirming or explicitly skipping
the optional denied-reader comparison records maker acceptance.
Skipped outcomes remain `skipped`, never fabricated `confirmed` results.
`guided-complete-with-warnings` reports completion with denied-user parity untested;
show the persistent warning on resume and completion.

`guided-validated` means recorded administrator confirmations and the tested
reader/article cases only. It does not prove universal ACL parity, all-KB
coverage, a revocation SLA or published employee readiness. This controller
makes no remote reads/writes and produces no API-verified remote evidence;
absence of a check remains unverified, never a success-shaped fallback.

## Recovery

After an observed change or failure, reopen the affected owner/field, then
correct and reconfirm the affected configuration. Source failures invalidate
Microsoft 365 and maker evidence; Microsoft 365 failures invalidate maker
evidence. Reopening validation preserves both administrator milestones.

```powershell
python scripts\servicenow_kb_connect.py reopen --owner m365 --field "Connection ready"
python scripts\servicenow_kb_connect.py reopen --owner validation --field validation
```

Progress is atomically saved in `.local/connect/servicenow-kb/config.json`.
Concurrent writes fail explicitly with a lock error. For a stale lock, confirm
the owning process is no longer running and obtain approval to remove only
`.local/connect/servicenow-kb/config.lock`; never delete progress or broad
workspace directories. Do not mutate canonical Setup readiness.

Version 1 progress remains readable and migrates to version 2 on the next saved
operation, retaining its scope, confirmations and acceptance. Prior grouped
administrator confirmations can satisfy their group, but do not claim newly
observed fine-grained checks. New partial steps have their own provenance.
Legacy workbook commands remain compatibility-only; never route this journey
through them or change Workday's workbook workflow.
