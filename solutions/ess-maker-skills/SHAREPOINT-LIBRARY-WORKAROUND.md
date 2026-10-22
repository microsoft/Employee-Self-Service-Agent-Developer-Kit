# SharePoint library knowledge-picker workaround

## Authentication status

**Blocked pending an approved authentication route. Do not distribute this
branch as a ready-to-run customer workaround.** Fresh sign-in validation on
2026-10-22 found:

- The shared client copied from existing ADK code failed MSAL.PS device-code
  authentication with `AADSTS7000218` (client assertion or secret required).
  Successful device-code initiation did not establish that sign-in could finish.
- The documented Azure PowerShell resource-token flow completed sign-in, but
  the agent API rejected the token with `InsufficientDelegatedPermissions`:
  `CopilotStudio.MinimalBot.ReadWrite` was missing.
- Requesting that scope explicitly through the Microsoft Azure PowerShell
  client failed with `AADSTS65002`, requiring API-owner preauthorization
  between the Microsoft-owned client and resource.

Changing to device-code authentication alone is therefore not a verified fix.
Do not request a secret for a Microsoft-owned application, try arbitrary client
IDs, or weaken tenant policies. Obtain the API owner's approved client and
authentication flow, or confirmation that a properly consented tenant-owned
public-client registration is supported. Then validate fresh sign-in and the
agent API read before resuming the customer procedure below.

The earlier component insertion and authoring retrieval test remain valid;
they used an existing token and did not establish a fresh customer sign-in flow.

This branch adds `/add-sharepoint-library` for an **existing native ESS DA GA**
agent when a direct SharePoint library URL returns **No results** in Configure.
It is not for DA Preview or CEA agents. It bypasses the picker by adding one
knowledge source through the native authoring API; it does not fix the picker.

## Customer flow

**On hold until the authentication blocker above is resolved.**

### 1. Install this branch

Windows PowerShell:

```powershell
& ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/users/amilandin/sharepoint-library-workaround/setup/bootstrap.ps1'))) -Branch 'users/amilandin/sharepoint-library-workaround' -InstallMode maker
```

The installer opens the Maker Kit workspace in VS Code. Use the branch above,
not the normal `main` installer; this workaround is not part of the general
release. The normal installer prerequisites, sign-in, permissions and any
administrator consent requirements still apply.

### 2. Run `/setup`

In Copilot Chat, run `/setup` and choose your **existing agent**. Use the maker
account that can edit it. Confirm the tenant, environment and agent, and finish
local workspace preparation. This workaround does not require unrelated
Workday/ServiceNow connections to be ready. If setup cannot access or
materialize the agent, resolve that blocker before proceeding; do not create
another agent instead.

### 3. Run `/add-sharepoint-library`

For example:

```text
/add-sharepoint-library https://contoso.sharepoint.com/sites/HR/SitePages/
```

Or supply your document-library URL ending in `/Shared%20Documents/`.
The skill shows the target and library, then asks before adding it.
Use a direct library-root URL, not a sharing link or `Forms/AllItems.aspx`.
This targeted workaround accepts tenant-root libraries or libraries directly
under `/sites/<site>/` or `/teams/<site>/`; subwebs and subfolders are out of scope.

It uses the ADK's existing authentication and native component transport,
saves a backup under `.local/backups/sharepoint-library/`, inserts one source
with optimistic concurrency, and checks that existing components are unchanged.
A rerun detects the same library rather than inserting another copy.
Treat local backups as sensitive agent configuration; do not upload them or
commit them to source control.

## Verify before publishing

Refresh Copilot Studio and test a question about a known document or page in
the library. Confirm the answer and citation. The command **does not publish**:
use the existing `/publish` flow only after reviewing any other pending changes.
Retrieval and strict library scoping must be validated in your own tenant.

If the command reports a conflict, timeout, or verification failure, keep the
backup and inspect the current sources. A write may have committed even if the
response was lost. Run the read-only preview again before retrying; do not
replay the backup or delete other sources.
