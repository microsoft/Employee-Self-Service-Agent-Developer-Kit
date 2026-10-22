# SharePoint library knowledge-picker workaround

## Authentication status

**Use the ADK's existing MSAL Python browser sign-in, not the standalone
MSAL.PS/device-code alternative.** On 2026-10-22, the unchanged ADK
`agentbuilder.authenticate` flow completed fresh sign-in using a new, empty
token cache and successfully read the test agent's native components. No
agent updates or publication were performed. This validates that flow in our
test tenant, not customer-tenant sign-in, consent, or retrieval.

The earlier authentication failures concerned different flows:

- The same ADK client ID failed MSAL.PS device-code
  authentication with `AADSTS7000218` (client assertion or secret required).
  Successful device-code initiation did not establish that sign-in could finish.
  That error did not establish that the ADK's browser flow was unusable.
- The documented Azure PowerShell resource-token flow completed sign-in, but
  the agent API rejected the token with `InsufficientDelegatedPermissions`:
  `CopilotStudio.MinimalBot.ReadWrite` was missing.
- Requesting that scope explicitly through the Microsoft Azure PowerShell
  client failed with `AADSTS65002`, requiring API-owner preauthorization
  between the Microsoft-owned client and resource.

The old MSAL.PS authentication instructions remain on hold.
The ADK uses MSAL Python's `acquire_token_interactive` browser flow with its
existing client and the native delegated scope; it does not use device-code
authentication or the Azure PowerShell client. Do not substitute those flows,
request a secret for a Microsoft-owned application, try arbitrary client IDs,
or weaken tenant policies. If the ADK cannot sign in or read the selected
customer agent, stop and resolve that tenant-specific blocker before applying
the workaround.

The earlier component insertion and authoring retrieval test used an existing
token. The new empty-cache test separately establishes fresh ADK authentication
and a read-only API check, not another insertion or a customer retrieval test.

The new standalone PowerShell option below also uses MSAL Python, not
MSAL.PS. Its complete script passed fresh browser authentication and a live
`-WhatIf` run against the test agent on 2026-10-22. It recognized the already
configured SitePages source and made no changes.

This branch adds `/add-sharepoint-library` for an **existing native ESS DA GA**
agent when a direct SharePoint library URL returns **No results** in Configure.
It is not for DA Preview or CEA agents. It bypasses the picker by adding one
knowledge source through the native authoring API; it does not fix the picker.

## Standalone PowerShell option (no ADK or Copilot license)

This option needs **PowerShell 7, Python 3.12 and MSAL Python**. It does not
need the ADK, VS Code, a GitHub Copilot license, MSAL.PS, Azure PowerShell,
a client secret, or a new application registration. The maker still needs
access to the intended agent and any required tenant consent.

Install Python 3.12, ensure `python --version` selects it, then:

```powershell
python -m pip install msal==1.37.0
Invoke-RestMethod 'https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/users/amilandin/sharepoint-library-workaround/solutions/ess-maker-skills/scripts/Add-EssSitePagesSource.ps1' -OutFile '.\Add-EssSitePagesSource.ps1'
```

Review the saved script. Confirm the target values with the customer, then
set them explicitly; do not copy IDs from a different tenant or environment:

```powershell
$target = @{
    TenantId = '<confirmed tenant GUID>'
    EnvironmentId = '<confirmed environment GUID>'
    AgentId = '<confirmed agent GUID>'
    LibraryUrl = 'https://contoso.sharepoint.com/sites/HR/SitePages/'
}
.\Add-EssSitePagesSource.ps1 @target -WhatIf
```

The script opens browser sign-in using MSAL Python's form-post callback and
a new in-memory token cache. Select the maker account for the confirmed tenant.
It does not save tokens to disk or require the maker to copy a bearer token.
Do not use `-DeviceCode`; the old MSAL.PS authentication path is not used.
If Python is not on PATH, pass `-PythonExecutable '<full path to python.exe>'`
and install MSAL with that same interpreter. `-Account '<maker sign-in>'`
optionally supplies a sign-in hint; the returned tenant is still checked.

Inspect the preview. Only after explicitly approving the target and change:

```powershell
.\Add-EssSitePagesSource.ps1 @target -Confirm
```

The standalone script accepts **SitePages library URLs only**. For other
library types, use the ADK skill below. It backs up the current configuration,
uses a fresh change token, inserts one source, checks its readback, skips
duplicates, and does not publish. The retrieval checks and failure-handling
cautions below also apply. Customer-tenant sign-in and retrieval still need
validation; the successful test-tenant run is not proof of either.

## Customer flow

Use the ADK flow below. Confirm customer-tenant access during setup and preview
before approving any update.

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
