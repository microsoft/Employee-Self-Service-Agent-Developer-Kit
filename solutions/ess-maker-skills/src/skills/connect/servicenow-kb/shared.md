# Shared prerequisites and flow-specific work

Use these once for both flows. ServiceNow administrators own ServiceNow changes;
Microsoft 365 AI administrators own gallery connection setup. This is an indexed
Knowledge connector, not the transactional ServiceNow provider or a live-query
connector.

## Common to Simple and Advanced

1. Assess all **included** KB/article read and deny criteria, contributor paths,
   custom behavior and HR scopes. Preserve source policy. Microsoft documents
   Simple for supported non-scripted criteria and Advanced for applicable
   scripted criteria; a global `advanced=true` query alone cannot classify scope.
   Unknown/custom dependencies require owner review before proceeding.
2. Configure/reuse the published **Federated Auth** recipe. The Microsoft app ID
   is `933838e2-bec1-440f-a634-9363c82e5b6d`; its tenant-local enterprise
   application object ID is different. Match that object ID to the ServiceNow
   machine user's User ID, map the `oid` claim, use `useraccount` scope and
   follow Microsoft's metadata/cache/JTI guidance. Do not return any credential.
3. Assign the documented roles and configure the required read grants through
   **permission-setup** before asking for read-test results. For default Simple,
   confirm saved roles, not table coverage. Guide specifically identified,
   approved corrections and applicable HRSD role assignments inline in chat.
   Reuse approved grants; avoid duplicate or blanket field ACLs.
   Saved configuration is not proof of effective crawler access.
4. Configure ServiceNow-to-Entra end-user identity mapping. Before opening the
   connector wizard, use supported ServiceNow-side diagnostics to assess common
   rows/fields, HR-scoped reads and flow-specific access.
   For the two knowledge permission properties, guide Name/Value checks and ask
   for their result. Verified reads record `confirmed`. Missing/blocked access
   records `unreadable`; inconclusive checks record `unverified`, not failure.
   For unresolved access, explain that unreadable settings default to `true` for
   both, blocking articles without explicit user criteria without an admin-center
   error. Recommend consulting the ServiceNow administrator, then explicitly ask
   whether to continue without this access. Only Yes records
   `proceed-without-access`; No pauses. Do not start inline ACL troubleshooting.
   Reuse verified reads and explicit consent; old automatic `deferred-to-admin`
   results are not consent. Display unresolved-access warnings on resume and
   completion; approval to continue is not a successful read.
   Preserve property values and existing security. The ServiceNow administrator
   assesses HR applicability, not through a separate maker question.
   An absent upfront classification is not evidence of non-applicability.
   Integration-account access is not an allowed employee's permission evidence.
5. In Microsoft 365, retain source-trimmed permissions, approved content query
   and flow, actual schedules/error review, and an explicit rollout audience.
   Complete source access validation before opening the connector wizard. Then
   configure Federated Auth and the remaining gallery settings through the
   approved Create action without detouring back to source diagnostics.
   For a new draft, use **Custom setup > Authorize** before Create and confirm the
   displayed success for the selected Federated Auth settings. Failed authorization
   pauses setup; if the action is absent, inspect the actual screen rather than
   silently continuing. Claim sample-fetch success only if separately displayed.
   Authorization does not prove ingestion or reader permissions.
   Record/reuse the connection name shown in ESS Knowledge, not a technical ID.
   Verify actual operation after Create against that named connection and its settings;
   previous draft confirmations or grouped Ready flags do not complete that gate.
   Ready, Indexed, reader permission and an ESS answer/citation are independent
   observations. Schedules are not guaranteed revocation times.
6. Finish indexed-article verification and native/indexed allowed/denied access
   checks before opening ESS. The denied-reader comparison is one optional,
   recommended action: Run or explicitly Skip both outcomes, with a persistent
   not-tested warning. Finding a denied user is not an article-selection gate.
   Observed access failures still block and cannot be cleared with Skip.
   Pending or failed required index checks pause setup.
   Then attach/reuse the named connection in the selected ESS Dev agent, isolate
   that source and verify the answer/citation using a detailed article-specific
   prompt. Review the response and open supporting citations to the same article/KB.

## Simple branch

Use the published Simple/Federated Auth instructions independently of our prior
Advanced setup. Assign `knowledge_admin`, `user_criteria_admin` and `user_admin`
as directed by that authentication recipe; do not require a custom connector
role, the Advanced ACL script or Advanced endpoint permissions. Additional ACLs
are conditional on required grants not already provided by the assigned roles.
Keep the table matrix in the later validation phase, not the role-saving step.
Never replace required chat instructions with an external table-access procedure.

Validate actual crawler reads of `sys_user_grmember`, `cmn_location`,
`cmn_department` and `core_company` in the later validation phase; guide approved
corrections only when specific gaps are established.
Use the Simple gallery flow only after the scoped criteria assessment confirms
eligibility; prior Advanced script execution is not Simple verification evidence.

## Advanced branch

Review/install the approved `microsoft_copilot` **POST `user_criteria_v2`**
Scripted REST API and capture its actual namespace. Configure its authentication
and resource ACLs during setup. In the later validation phase, confirm authenticated caller,
resource-security settings, ACL enforcement and intended caller access. Evaluate
per-user errors inside HTTP 200 responses, not just the response status.
Use the Advanced gallery flow with that namespace.

The V2 API is not a public unauthenticated endpoint. Scripts can alter existing
records: review the actual vendor version, diffs and change approval before
execution. Optional `user_changes` auditing/incremental identity customization
is not part of this MVP.

## Authoritative references

- [ServiceNow prerequisites](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup)
- [Flows, Federated Auth, gallery deployment and sync](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-deployment)
- [Setup scripts and execution guidance](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-setup-scripts)
- [Connector troubleshooting](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-troubleshooting)

Check source-instance policy and the current vendor recipe rather than treating
recorded confirmations as proof of every ServiceNow customization's compatibility.
