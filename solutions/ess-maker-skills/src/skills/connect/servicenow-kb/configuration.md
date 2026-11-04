# ServiceNow Knowledge: configuration walkthrough

Use this as the executable conversation guide, one current step at a time.
Exceptions: collect `test-article` and `test-kb` together; present both denied-reader
checks as one optional, recommended action as described below.
Step IDs match the controller's `nextStep.id`. Refer to the saved target, tenant,
instance, query, flow and previously recorded values instead of asking again.
The user performs privileged actions; the assistant records their observed
checks. No Excel handoff and no user-authored evidence JSON are required.

At every change: inspect/reuse first, explain impact and guide the authorized user
within the approved setup. Once a required item is reported missing, give its
documented manual addition steps directly, not another approval questionnaire.
Required administrator authorization still applies; pause if unavailable.
Approval instructions below must not become repeated permission questions for
manual actions already covered by the approved setup. Obtain explicit approval
for new scope or script execution; never infer permission for assistant-made
remote writes from a missing-item report.
If the needed role, supported UI, feature entitlement or
cloud/release support is absent, pause explicitly. Never switch tenants, weaken
source policy or create a replacement application to continue.

Present every user-facing step as **Act**, then **Verify**, under a task-oriented
heading. Act means configure after approval, or inspect/retrieve/test for a
read-only step. Reuse correct existing setup; guide approved creation or targeted
correction when needed. Ask for the required observation after the action, not
an upfront matching questionnaire. Approval or execution alone never passes
verification. Automatic assessment-date and acceptance-time bookkeeping are not
user-facing steps.

When a configurable item may already exist, precede Act / Verify with a short
existence check: exact navigation, identifying value and **Yes / No / I can't
check**. Present only that check until answered; do not show creation instructions
or ask whether saved settings match yet. If the current-scope answer is already
known, take its branch without another question. Yes leads to inspection/reuse or
correction; No leads directly to documented creation; inability to check pauses.
Existence is not configuration evidence and must not complete a checkpoint.
This does not add questions to completed steps or read-only diagnostics, nor
authorize creating a replacement first-party Entra application.

Act / Verify and Check existence labels below are internal conversation structure,
not boilerplate headings to repeat to the user. Show the current branch as a
concrete numbered walkthrough in visible chat, including the saved instance link
and required values, then ask its short result question separately.

For a first-time integration user, guide role and ACL configuration first.
The `permission-setup` checkpoint records saved configuration only, not tested
access. Do not start Access Analyzer or a read-test questionnaire during that
step. After identity/API setup, perform the separate ServiceNow-side permission
preflights before opening the connector wizard. The permission-property step
checks access first; unresolved access requires a warning, administrator referral
and explicit user consent before continuing.
Only then complete the wizard
through Create in one continuous session; do not hold an unsaved form open
while performing source diagnostics.

## scope-assessment

**Owner:** ServiceNow knowledge/security administrator. **Record:** `confirmed`.

**Act:** assess the selected Knowledge permission scope.

Render the following numbered walkthrough for the saved instance and content
scope; do not replace it with "inspect applicable criteria":

1. Open the saved ServiceNow instance, then **All > Knowledge > Administration >
   Knowledge Bases**. Identify the KBs containing articles selected by the saved
   active/published query and any KB restriction. Review only that approved scope;
   all-KB scope means every KB containing included articles, not one sample KB.
2. Open each included KB. In its **Can Read**, **Cannot Read**, **Can Contribute**
   and **Cannot Contribute** related lists, open each referenced User Criteria
   record. Inspect all pages of each list; an empty or inaccessible list is not
   proof the source has no applicable criteria.
3. On each referenced **User Criteria** form, inspect **Advanced**. When selected,
   inspect the **Script** field, which this option displays. When not selected,
   inspect the configured **Users**, **Groups**, **Roles**, **Companies**,
   **Departments**, **Locations** and **Match All** values, where applicable.
   Check custom dimensions or dependencies with the source owner; do not assume
   every non-scripted customization is supported. Do not change the criterion.
   The same records can also be opened through **All > Knowledge > Administration >
   User Criteria** using the exact referenced record, not an unrelated name match.
4. Open the included articles' **Knowledge** forms and inspect their **Can Read**
   and **Cannot Read** fields. Open each referenced criterion and repeat the
   Advanced/Script check. If these fields are hidden, have the authorized
   administrator expose them through the supported form layout; do not interpret
   hidden fields as no restrictions or change/publish article access settings.
5. Include criteria on any included knowledge blocks and HR-scoped content.
   If scope restrictions prevent inspection, involve the relevant source
   administrator and leave the review incomplete rather than assuming no criteria.
   Ask the owner to explain contributor/owner exceptions and custom dependencies
   that affect the included content.
6. Reconcile the full article/KB scope and paginated criteria lists before
   answering. A global advanced-criteria query is only discovery: relate its
   records to the included KBs/articles, and do not use one returned or empty
   page as the completed review.

**Verify:** establish that the selected flow supports the included permission paths.

For Simple, verify every included permission path uses supported non-scripted
dimensions. Scripted allow criteria can overshare and scripted deny criteria can
deny everyone. For Advanced, review scripts in the evaluated user's context,
not the session administrator's context. Do not remove restrictions to qualify.
Confirm only when this actual scope is appropriate for the selected flow.
After this walkthrough, ask **Did the review confirm that the selected
<Simple/Advanced> flow supports this content's permissions?** with unset choices:
**Yes, the review confirmed it**, **No, the selected flow is unsuitable**, and
**The review is incomplete; help me finish it**. An unsuitable or incomplete
review does not pass. Guide only the affected criterion, access problem or
approved flow/scope correction, not a repeat of healthy work. The controller
automatically records the confirmation's UTC date when missing; do not ask for it.

Navigation and fields follow ServiceNow's [KB criteria guide](https://www.servicenow.com/docs/r/servicenow-platform/knowledge-management/t_SelectUserCriteria.html),
[article criteria guide](https://www.servicenow.com/docs/r/servicenow-platform/knowledge-management/t_SelectUCArticle.html)
and [User Criteria form reference](https://www.servicenow.com/docs/r/servicenow-platform/knowledge-management/create-user-criteria-record-in-knowledge-management.html).

## assessment-date

**Automatic bookkeeping, not a normal user question.**

The `scope-assessment` confirmation saves its UTC date and skips this step.
Existing historical dates are preserved during reuse/resume, not overwritten
with today. The explicit date command remains available for correcting an actual
historical date in legacy progress, using `YYYY-MM-DD` and never a future date.
If an older journey is paused here after the review was just completed, reconfirm
`scope-assessment` to record its date automatically. Do not infer the date of an
undated historical assessment without a current confirmation or known actual date.

## service-principal

**Owner:** authorized Entra administrator. **Record:** tenant-local object GUID.

**Act:** identify the Microsoft connector application in the configured tenant.

Start by telling the user: **"Next, we'll configure Federated Auth between
Microsoft and ServiceNow: identify the connector application, configure ServiceNow
to trust its tokens, and map that identity to the integration user."**
This is ServiceNow OIDC and user mapping, not an Entra app registration's
**Federated credentials** entry.

Show the saved `scope.target.tenantId` as the configured ESS tenant, not a new
question. It comes from canonical Setup's `environment.tenant_id` in
`.local\setup\config.json`; do not invent an organization name or imply a live
tenant lookup. Explain that the tenant ID selects the directory, the Application
ID finds the connector app, and its tenant-local Object ID becomes the ServiceNow
integration user's User ID for machine authentication. We need the application's
Object ID, not a "tenant Object ID."

Open Microsoft Entra admin center in the saved tenant:

1. Go to **Entra ID > Enterprise applications > All applications**.
2. Clear the search box and set **Application type** to **All Applications**
   if that filter is present. Do not enter the tenant ID in application search.
3. Choose **Add filters > Application ID > starts with**, enter
   `933838e2-bec1-440f-a634-9363c82e5b6d`, and apply the filter.
4. Open the matching application, select **Overview**, and copy **Object ID**.
   Verify its Application ID matches the full value above.

If portal discovery is inconclusive, Microsoft's deployment recipe documents
an authorized `Get-AzADServicePrincipal -ApplicationId` lookup and Graph query.
Do not install tools or grant consent without approval.

**Verify:** verify the directory and application, then record its Object ID.

Check that the tenant matches the selected ESS environment. Record the
enterprise application's **Object ID**, not its Application ID, a new app
registration ID or a ServiceNow record sys_id. Missing access or no matching
principal is a blocker, not permission to create a replacement application.

## oidc-provider

**Owner:** ServiceNow administrator. **Record:** `confirmed` after inspection.

**Check existence:** show only this check before the Act instructions.

> **Check whether the ServiceNow OIDC registration already exists**
>
> Open **All > System OAuth > Application Registry**. Check for an OIDC
> registration with Client ID `933838e2-bec1-440f-a634-9363c82e5b6d`.
>
> **Does this registration exist?**
> - **Yes**
> - **No**
> - **I can't check**

Leave choices unset. Yes means inspect the existing registration and its linked
provider configuration, not that settings passed. No means guide creation below.
I can't check means pause for the authorized ServiceNow administrator. If there
are multiple candidates, establish the intended registration before changing one.

**Act:** show only the branch established by the existence answer.

For **Yes**, open that registration and its linked provider configuration.
Inspect the required settings below, reuse correct values and guide correction
of only missing/incorrect values. Do not create a duplicate.

For **No**, guide **New**, then the creation path for the user's release:

- Yokohama and earlier: **New > Configure an OIDC provider to verify ID tokens**.
- Zurich and later: **New Inbound Integration Experience > New Integration >
  Third party ID token issued by OIDC supporting identity provider**.

Show these field values explicitly, in form order, rather than asking the user
to invent names. Use these values for a new registration; preserve existing
approved descriptive names when reusing one.

| Details field | Value for a new registration |
| --- | --- |
| Name | `Microsoft Entra ID` |
| Provider name | Select **Microsoft** from the dropdown |
| Client ID | `933838e2-bec1-440f-a634-9363c82e5b6d` |
| Active | Checked |
| Comments | Optional; leave blank unless your organization requires a description |

Under **OAuth OIDC provider configuration**, choose **Select an existing
configuration** only if its saved settings match the connector values below.
Otherwise choose **Create a new configuration** and fill in these fields.
Do not accept an unrelated preselected configuration such as **Sidebar OIDC
config**, or edit that shared configuration for this connector. Read-only fields
in existing-configuration mode are not instructions to leave incorrect defaults:
select the correct configuration or create a dedicated one.

| OIDC configuration field | Required connector value |
| --- | --- |
| OIDC provider / OIDC provider name (older form: OIDC Provider Configuration Name) | `Microsoft Entra ID` for a new configuration; select the verified existing configuration when reusing |
| OIDC metadata URL | `https://login.microsoftonline.com/<saved-tenant-id>/v2.0/.well-known/openid-configuration` |
| OIDC configuration cache lifespan (hours) | `120` |
| User claim | `oid` for the saved service principal Object ID mapping |
| User field | `User ID`, not the default Email |
| Enable JTI verification | Disabled, subject to approved security policy |

Render the metadata URL with the actual saved tenant ID, not the placeholder
or the unrelated `/common/` URL. The registration **Name**, **Provider name**
and linked **OIDC provider name** are distinct form fields. Use `Microsoft Entra ID`
for the new registration/configuration names, but select **Microsoft** in the
Provider name dropdown; do not ask the user to enter a custom provider label.

Set User Claim explicitly: `oid` for the saved service principal object ID
mapping; use `sub` only for an approved matching subject mapping. Do not leave
it blank or confuse it with the scope. Set Scope Restriction / Auth Scope to
**Useraccount scoped** (`useraccount`). Save approved changes.

**Verify:** reopen the actual records and
verify the registration/provider names and linked configuration, active status,
Client ID, metadata, claim/field, cache, JTI
and scope. This checkpoint verifies settings, not successful authentication.

Field defaults follow Microsoft's [OIDC configuration tables](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-deployment#step-2-create-the-oidc-provider-in-servicenow);
the current form structure is also described in ServiceNow's [third-party ID token guide](https://www.servicenow.com/docs/r/platform-security/authentication/configure-a-third-party-id-token.html).

The published `federated_auth_setup.js` is an alternative to manual entry only
after reviewing its current configuration and impact and obtaining approval.
Set `SP_OBJECT_ID` and `TENANT_ID` to the recorded values. Never run it simply
because this local step is incomplete; it may affect existing configuration.

## integration-user

**Owner:** ServiceNow administrator. **Record:** `confirmed`.

**Check existence:** open **All > User Administration > Users** and check for
**User ID = saved tenant-local principal Object ID**. Ask **Does this integration
user exist?** with unset **Yes / No / I can't check** choices, unless already
answered. Show no creation instructions or saved-setting confirmation form yet.
Pause if the administrator cannot check.

**Act:** create or verify the ServiceNow integration user.

For **Yes**, open the existing user and inspect the required fields below;
reuse correct settings. For **No**, guide **New > User ID = saved Object ID >
First name / Last name = approved recognizable integration-user name >
Identity Type = Machine > Active = checked > Save**. If a dedicated integration user needs
correction, explain the authentication impact, update only the
approved fields and save; do not repurpose an ordinary user or create a duplicate.

**Verify:** reopen the saved integration user.

Show the saved user's **Name (display name)** alongside **User ID**, **Identity
Type** and **Active** in the visible verification details. Read the actual saved
First name / Last name and resulting display name; do not infer a name from the
Object ID or rename a healthy existing user. Reuse an already supplied name;
if unavailable, ask the administrator for the name shown on this exact user record.
Check the saved user's User ID, active status and identity type against the
OIDC claim mapping. Do not use the application ID or native record sys_id.

Machine identities can be web-service-only and non-impersonable. Do not enable
interactive access or invent a Basic password to test this Federated Auth path.

## integration-roles

**Owner:** ServiceNow administrator; elevate `security_admin` for ACL work.
**Record:** `confirmed` after role inspection.

**Act:** assign or reuse the approved integration-user roles.

Open the integration user's **Roles** related list. Follow the approved
Federated Auth recipe for `knowledge_admin`, `user_criteria_admin` and `user_admin`;
these are broad roles, not a claim of minimum privilege. Any least-privilege
alternative needs explicit approval and verification, not assumed equivalence.
For **Simple**, guide only these published Federated Auth role assignments first.
A custom connector role is not a mandatory Simple prerequisite. Do not import
the role or ACL script from our previous Advanced setup. Show custom-role
creation only if an additional approved grant actually needs that mechanism.

For **Advanced**, assign the approved dedicated connector read role to this same
machine user. For a new setup, use `copilot_connector` unless another role was
already approved. If it is missing, open **All > User Administration > Roles >
New**, set **Name** to the approved role name, and **Submit**. Then add it through
the integration user's **Roles > Edit** and **Save**.

If the user reports no roles, guide **Roles > Edit**, add `knowledge_admin`,
`user_criteria_admin` and `user_admin` to the selected roles, then **Save**.
Do not insert an "Approval for documented roles" questionnaire. In the Advanced
or conditional custom-grant branch, if the dedicated
connector read role is not yet identified/approved, resolve that actual prerequisite
with the security owner rather than asking permission again for the documented roles.

Do not show ACL-script execution as part of the default Simple role instructions.
In the Advanced or explicitly selected script branch, if using
`row_level_acl_setup.js`, first review the current vendor version and
its existing-record effects. Set `USER_ID` to the recorded principal object ID
and the role name to the approved connector role. In **System Definition >
Scripts - Background**, use the approved server-side execution context; do not
execute it as a scriptlet. Review the summary and reopen user/role assignments.

**Verify:** inspect the saved role assignments on the same integration user.

Verify each approved role is present; script execution alone does not establish it.
A successful role/script checkpoint does not confirm all reads.

## permission-setup

**Owner:** ServiceNow security administrator. **Record:** `confirmed`.

**Act:** save role assignments and any specifically identified, approved corrections.

Expect the integration user to be new unless current-scope history says otherwise.
Guide the administrator through adding the required access, not proving reads
before setup. A new user does not imply all ACLs are absent: reuse approved grants
already supplied by its assigned roles and do not duplicate them.

**Default Simple path:** the action is to save the three published roles, not
review or certify table grants. Show only this walkthrough:

1. Open the saved ServiceNow instance, then **All > User Administration > Users**.
2. Open the integration user whose **User ID** is the recorded principal Object ID.
3. In **Roles > Edit**, add `knowledge_admin`, `user_criteria_admin` and
   `user_admin` if missing, then **Save**.
4. Reopen **Roles** and confirm the three assignments are saved.

Reuse a current-scope confirmation already supplied in **integration-roles**;
do not ask the user to repeat this work or its result question. Say **Role
assignments saved; required READ access not yet verified** and continue to the
next setup step. Do not show a table matrix or ask the user to "review existing
read grants", "ensure coverage" or certify untested READ access here. The table
requirements belong to the later **table-reads** and **simple-reads** validation.
If the current scope already identifies an applicable HR role or a specific
approved correction, guide that action below before continuing. Do not treat
unknown feature applicability as absence.

Show this manual ACL procedure only for an additional required grant being
configured with approval, not automatically to every Simple user. Present the
applicable steps in chat, substituting the actual table and approved role.
Never send the user to an external table-access procedure to complete the action:

1. Use an approved role for that grant. If a custom role is needed, open
   **All > User Administration > Roles > New**, set **Name** to the approved
   role name, then **Submit**. Open the integration user and use
   **Roles > Edit** to add it, then **Save**. Do not assume an Advanced role exists.
   The human security administrator elevates **security_admin**, then opens
   **All > System Security > Access Control (ACL)**.
2. For each required table without an existing approved grant, select **New**.
   Set **Type = record**, **Operation = read**, and **Name = the table** with the
   field selector **--None--** for row access. Add the dedicated connector role
   under **Requires role / Roles**, then **Submit**. Do not modify an unrelated
   ACL or remove its conditions/scripts to make the connector work.
3. Reopen the saved ACL and confirm its table, operation and approved role.
   This confirms configuration only; retest the affected access in the validation
   phase. Do not show the Advanced ACL script as a Simple prerequisite.

For included **Human Resources: Core** (`sn_hr_core`) content identified in the
scope assessment, assign/reuse the approved **sn_hr_core.content_reader** role
on the integration user (or the approved broader **sn_hr_core.admin** alternative)
through **Roles > Edit > Save**. No upfront maker HRSD questionnaire is needed.

Preserve property values and existing row/field/scope/domain protections.
Do not add blanket **table.*** field ACLs. If a specific field-access gap is
already known, guide its approved targeted correction; otherwise defer field
diagnostics and any resulting field ACL changes to the validation phase.

**Verify:** reopen the saved role assignments and any ACL records actually configured.

For Simple, ask **Have the three role assignments been saved?** only if not
already confirmed. For additional approved changes, ask whether those specific
changes were saved, not whether all reads work. Offer an unset completed/incomplete
choice. Record this step only after the actual saved configuration is confirmed.
For default Simple use the role-saving statement above; otherwise say
**Permissions configured; access tests pending**.
Do not record Common table reads, property reads, HR reads or Simple reads as
passed from this answer. Do not apply **snc_read_only**: the authentication path
needs authentication-related writes, including **oauth_credential**, not general
table write access.

Keep the Federated Auth integration user's **User ID** equal to the recorded
principal Object ID; do not substitute a generic `microsoft.copilot` username.
Vendor scripts remain an alternative only after source review and execution
approval and explicit selection, not the default Simple instructions; do not run
them automatically or treat their completion as read proof.

## identity-mapping

**Owner:** authorized ServiceNow/Entra administrators. **Record:** `confirmed`.

**Act:** inspect the ordinary readers' source-to-Entra mapping.

Inspect the known allowed ordinary reader privately in ServiceNow and Entra,
including the approved custom mapping formula if used. A denied reader is not
required here; verify that reader's mapping later if the optional denied-reader
comparison is selected. If incorrect,
explain the targeted correction and obtain approval before changing it.

**Verify:** verify their ServiceNow email resolves to the intended Entra UPN or
Mail through the approved mapping. Do not assume identical
display names, crawler access or an admin bypass proves reader identity.
Record only the check outcome, not employee IDs or membership exports.
The gallery mapping preview must also be checked during connector configuration.

## advanced-api

**Owner:** ServiceNow administrator with approved elevated `security_admin`.
**Advanced only. Record:** `confirmed` for installed/reused V2 resource.

**Check existence:** open **System Web Services > Scripted REST APIs** and check
for API ID `microsoft_copilot` with a **GetAllUserCriteriaV2** POST resource at
`/user_criteria_v2`. Ask **Does this V2 API resource exist?** with unset
**Yes / No / I can't check** choices unless already answered. Do not show script
execution instructions or ask for installation confirmation before this answer.
Pause if the administrator cannot check.

**Act:** install or reuse the approved Advanced V2 API resource.

For **Yes**, inspect and reuse the approved existing resource; guide targeted
correction if needed, not duplicate creation. For **No**, first inspect any existing
API and other resources so a partial setup is preserved, then review Microsoft's
current `scripted_rest_api_setup.js`,
configure `ROLE_NAME` to the actual connector role, explain its record changes,
obtain approval, and guide server-side Scripts - Background execution.
Do not paste an invented evaluator or install the deprecated V1 endpoint.

During this setup, configure the API/resource security from the approved vendor
recipe: **Requires authentication** and **Requires ACL authorization** enabled,
the intended endpoint ACL with the dedicated caller role, and the documented
**Scripted REST External Default** configuration. Inspect saved settings now;
actual authorized/unauthorized caller tests belong to **advanced-security**
before opening the connector wizard, using supported ServiceNow-side diagnostics.

**Verify:** inspect the saved API and resource.

Reopen the actual API/resource and check API ID, POST method, relative path
and approved V2 script. Script success alone does not pass the following
namespace/security checkpoints.

## advanced-namespace

**Owner:** ServiceNow administrator. **Advanced only. Record:** actual namespace.

**Act:** retrieve the installed API's namespace.

Open the existing `microsoft_copilot` API form and read its namespace.

**Verify:** verify the namespace against the actual endpoint.

Check the resulting endpoint:
`/api/<namespace>/microsoft_copilot/user_criteria_v2`.
Record only the namespace, not the full URL, an API token or the API ID.

## table-reads

**Owner:** ServiceNow security administrator. **Record:** `confirmed`.

**Act:** assess configured crawler access with supported ServiceNow-side diagnostics.

Explain that roles/ACLs were configured earlier and this is now the separate
source-permission preflight, before opening the connector wizard. Access Analyzer
is a diagnostic option, not a Microsoft-required connector wizard step.
Use Access Analyzer or other supported record/field
diagnostics for the actual integration user. In **Select user**, use the verified
integration-user display name and confirm the selected record's **User ID**
matches the recorded principal Object ID. Show both identifiers in the instructions;
names need not be unique. If the name is unavailable on resume, reopen the user
by its exact User ID to retrieve it rather than inventing a name.
No authenticated gallery session
is assumed. Use authenticated REST diagnostics only when an approved method is
actually available; do not invent credentials or require a Basic password for
the machine user. If necessary checks cannot be performed, record the blocker
and involve the security owner rather than claiming success.
Use the required tables below.
In the customer-facing list, omit the associated-content rows unless the source
owner established they are included:

| Purpose | Tables |
|---|---|
| Articles/KBs | `kb_knowledge`, `kb_knowledge_base` |
| KB criteria links | `kb_uc_can_read_mtom`, `kb_uc_cannot_read_mtom`, `kb_uc_can_contribute_mtom`, `kb_uc_cannot_contribute_mtom` |
| Users/roles/groups/criteria | `sys_user`, `sys_user_has_role`, `sys_user_group`, `sys_user_role`, `user_criteria` |
| Included templates/attachments/comments | `sys_db_object`, `sys_dictionary`, `sys_attachment`, `kb_feedback` |
| Included knowledge blocks | `kb_knowledge_block`, `m2m_kb_knowledge_to_block` |

Permission-property access is handled separately by the
`property-reads` step. Do not make `sys_properties` record/field verification a
hidden requirement of this common-table confirmation.

Show actual navigation, test inputs and expected observations in chat before
asking for results; the matrix alone is not an executable test. If a specific
missing grant is established, guide the applicable approved correction from
**permission-setup** inline, then retest. Do not substitute an external
table-access procedure link for those instructions. If the applicable ACL or
safe correction is unknown, request the specific diagnostic result needed or
involve the security owner; do not invent an ACL or blanket-grant access.

**Verify:** test the required records and fields under the actual crawler identity.

Use known records and required fields, not HTTP 200, an empty result or table-level
access alone. Keep the source's row, field, application-scope and domain protections.
If rows exist but needed fields are missing, diagnose the actual ACL first.
Target only approved missing access. Do not run `field_level_acl_setup.js`
indiscriminately: first inspect its dry run and existing ACLs; a first `table.*`
ACL can remove other users' field access. Prefer targeted fields on shared
tables, and verify affected ordinary users retain their existing access.
Do not confirm while required reads remain unverified.

## property-reads

**Owner:** ServiceNow administrator; the user decides whether to continue with
unresolved access. **Record:** `confirmed`, `unreadable`, `unverified` or
`proceed-without-access` according to the actual result and explicit decision.

**Act:** guide these read-only checks before asking for the result:

1. Open the saved ServiceNow instance, then **All > Access Analyzer >
   Analyze Permissions > Evaluate access**.
2. Set **Analyze by = User** and **Select user = the verified integration-user
   display name**. Show its actual name and User ID; verify the selected user's
   User ID matches the recorded principal Object ID.
3. Set **Resource = Table (record)** (older forms: **Rule type = Table**), then
   **Select table = System Property (`sys_properties`)**.
4. In **Select record**, select the existing
   `glide.knowman.apply_article_read_criteria` property using the record lookup.
5. Set **Select field = Name (`name`)**, click **Evaluate access**, and inspect the
   **read** result. Repeat with **Select field = Value (`value`)**.
6. Repeat both field checks on the existing
   `glide.knowman.block_access_with_no_user_criteria` record.

**Verify:** ask **Can the integration user read name and value for both
properties?** Offer unset choices **Yes, name and value are readable for both
properties**, **A property or field is missing or unreadable**, and **I couldn't
complete these checks**. These are two fields on each of two property records,
not four distinct fields. A table-only pass is not proof of record/field access.
Reuse actual current-scope results already supplied; do not make the user repeat
a completed check just to answer the form.

- If all reads pass, record `confirmed` and continue. Do not show the missing-access
  warning or ask permission to proceed without access.
- If the user reports a missing/blocked read, record `unreadable`.
- If the result is inconclusive, record `unverified`; do not call it blocked or
  verified. If Access Analyzer is unavailable, consult the ServiceNow administrator
  rather than inventing a pass or alternate credentials.

For either unresolved outcome, show the following warning and administrator
referral before asking whether to proceed:

> **Permission-property access warning (Simple and Advanced):** the connector
> needs to read `glide.knowman.apply_article_read_criteria` and
> `glide.knowman.block_access_with_no_user_criteria` from `sys_properties`.
> If the integration user cannot read them, Microsoft documents that the connector
> silently defaults both settings to `true`. This blocks articles without explicit
> user criteria from appearing in search results, with no error shown in the admin
> center. Consult your ServiceNow administrator to resolve this access.

This impact is documented in [Microsoft's ServiceNow setup guide](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup#create-service-account-and-set-up-permissions-to-index-items).
Do not launch an inline role/ACL or property Read roles troubleshooting detour.
Do not create missing properties or change their values as a workaround.

Then ask **Would you like to continue setup without this access?** with unset
**Yes, continue with this access unresolved / No, pause for my ServiceNow
administrator** choices. Record `proceed-without-access` only after an explicit
Yes to this separate question. Acknowledging the warning, reporting blocked access,
silence, cancellation or No is not consent. No pauses setup at this step, retaining
the reported `unreadable` or `unverified` result; do not advance or record approval.

On resume, preserve existing `confirmed` access or explicit
`proceed-without-access` consent without repeating checks. A historical
`deferred-to-admin` result came from automatic deferral, not consent: obtain the
actual result if unknown, show the warning and ask the continuation question.
Retain previous observations and the existing connection; do not reset progress
or recreate the connection just to record this decision. Keep unresolved-access
warnings visible in status and final summaries after user-approved continuation.
Passing representative reader tests does not resolve or verify property access.

## hr-reads

**Owner:** ServiceNow HR knowledge/security administrator.
**Record:** `confirmed`, or `not-applicable` after actual scope review.

**Act:** validate HR-scoped access configured in permission-setup.

Review the included KB/criteria application scopes within this access check;
do not ask an upfront or replacement maker "Does this include HRSD?" question.
For included Human Resources: Core (`sn_hr_core`) content, inspect the assigned
`sn_hr_core.content_reader` or approved broader `sn_hr_core.admin` role.
Correct only actual approved gaps if setup was incomplete.

**Verify:** inspect expected HR-scoped criteria/content rows under the crawler identity.

The roles grant access through different mechanisms; do not assume one contains
the other. A global table read can silently omit HR-scoped criteria.

Use `not-applicable` only after the administrator established that the actual
included scope has no applicable HRSD content. Unknown is not No. Previously
known HRSD scope cannot pass by claiming non-applicability.

## simple-reads

**Owner:** ServiceNow security administrator. **Simple only. Record:** `confirmed`.

**Act:** validate the Simple-flow reads configured earlier.

The shared 16-table script alone does not establish these four reads. Diagnose
and correct approved gaps when observed; do not repeat healthy role/ACL setup.
Simple needs no V2 API, `user_changes` endpoint or identity auditing.
Do not delete Advanced resources if another existing connection uses them.

**Verify:** test required rows and fields on `sys_user_grmember`, `cmn_location`,
`cmn_department` and `core_company` for the actual crawl identity.

## advanced-security

**Owner:** ServiceNow security administrator. **Advanced only. Record:** `confirmed`.

**Act:** validate the approved API/resource security configured earlier.

Inspect API and resource security following the vendor recipe. Keep
**Requires authentication** and **Requires ACL authorization** enabled; check
the intended endpoint ACL/custom caller role and **Scripted REST External Default**
configuration. Selected ACLs are not an AND restriction: evaluate actual caller
access and do not assume multiple ACL entries restrict access more tightly.

**Verify:** test intended and prohibited caller access and evaluation outcomes.

In a private approved REST diagnostic, test the actual intended caller with
matching and nonmatching native user/criteria record IDs. Inspect per-user
evaluation/errors inside the response, not just HTTP 200. Also verify anonymous
and unauthorized authenticated callers cannot use the endpoint. Do not put
employee record IDs, tokens or full responses into saved evidence.
Unexpected caller access or evaluation errors block this checkpoint.

## federated-auth

**Owner:** Microsoft 365 AI administrator with ServiceNow administrator available.
**Record:** `confirmed` for reviewed settings and successful pre-Create
authorization on a new draft, or verified matching configuration on an existing
connection. This is not completed ingestion or reader-permission evidence.

**Act:** begin the connector wizard after the required ServiceNow-side preflights
pass and property access is verified or continuation without it explicitly approved.

For new setup, show these steps with the actual saved values:

1. Open **Microsoft 365 admin center > Copilot > Connectors > Gallery >
   ServiceNow Knowledge**, choose **Custom setup** and start one connection draft.
2. Enter a recognizable display name, choose the saved **Simple** or **Advanced**
   flow and enter the canonical ServiceNow instance URL.
3. Select **Federated Auth / Federated Credential**. For Advanced, enter the
   saved API namespace.
4. Select **Authorize** in Custom setup and inspect the actual result for these
   settings. If authorization fails, pause, show the reported error and guide the
   specific approved correction before retrying. Do not continue on a failure.
5. After authorization succeeds, continue directly through content/mappings,
   source permissions, audience and schedules to the final creation review.
   Select **Create** only after that review and explicit creation approval.

The required source checks are already complete; property access may remain
unresolved only with explicit continuation approval and its warning visible.
Do not interrupt this wizard for Access
Analyzer or another source preflight, or ask the user to keep an unsaved form
open while switching to ServiceNow diagnostics.

Use Custom setup's **Authorize** action before creation, rather than assuming
the initial setup screen is the only path. If Authorize is unexpectedly absent,
pause and inspect the actual Custom setup screen; do not invent another button,
switch authentication methods or silently continue to Create.
Ask **Did Authorize succeed for these connection settings?** with unset
**Succeeded / Failed / I can't verify** choices. Record `confirmed` only after
reviewing the settings and an actual successful result. Say **Authorization
succeeded; ingestion and reader permissions not yet verified**.
Report sample-fetch success only if the portal separately displays it; do not
ask whether authentication and sample fetch "both succeeded" by assumption.

For reuse, inspect the exact existing gallery connection and its matching
instance, flow, namespace and Federated Auth selection. Do not recreate the
connection or change another working connector to manufacture a pass. If an
earlier walkthrough already opened a draft, finish outstanding source checks
first; reuse entered values if still available or re-enter them afterward.
Do not require the user to keep that unsaved form open. Inspect existing
connections before any Create if creation might already have occurred.

**Verify:** inspect the entered configuration and actual Authorize result for
a new draft; for reuse, inspect the matching existing connection configuration.

Reuse the saved provider, tenant metadata, claim/User ID, scope and JTI setup
without another portal detour. Actual connector operation is verified in
**connection-ready**, after creation and recording the actual connection name.
A previous settings-only confirmation does not establish authorization success
for an unfinished draft. Complete Authorize before Create unless an actual
successful result for the unchanged settings was already supplied. A historical
"Both succeeded" answer is not post-Create ingestion evidence; never copy it
into the connection-ready checkpoint.
Microsoft's Basic/OAuth Checker instructions are not proof of Federated testing.

## connector-config

**Owner:** Microsoft 365 AI administrator. **Record:** `confirmed` after review.

**Act:** configure or reuse the approved connector content and mappings.

Continue the configured draft, or inspect the exact reused connection.
If an earlier unsaved draft is no longer open and no connection was created,
reopen **Copilot > Connectors > Gallery > ServiceNow Knowledge** and re-enter
the saved instance, flow, Federated Auth and Advanced namespace if applicable.
Use a recognizable display name. Do not repeat healthy source checks just to
re-enter the wizard. If creation is uncertain, inspect existing connections first
instead of starting a duplicate.
In Custom setup, check the saved instance, flow, Federated Auth and Advanced
namespace if applicable. In **Content**, enter the saved active/published query
exactly; do not broaden it or replace it with unsupported article classification.
Check the result against the approved source scope.

Review the identity mapping/preview using the intended ordinary readers. Resolve
mapping failures; "validation skipped" is not passed. Review supported schema
property/citation URL mappings against the actual ServiceNow portal:
the default article link uses `kb_view.do?sys_kb_id=<article-sys-id>`.
If custom portal URLs are needed, use the supported mapping editor and check the
resulting link; don't invent transformations or confuse article and KB IDs.

**Verify:** review the saved instance, flow, query, authentication and mappings,
including actual reader mapping previews and citation destinations.

Check parent/article permission support for the actual cloud/tenant. Unsupported
features or unresolved custom dependencies require owner review, not a pass.

## source-permissions

**Owner:** Microsoft 365 AI administrator. **Record:** `confirmed`.

**Act:** configure source-trimmed permissions or reuse the correct saved selection.

In **Custom setup > Users**, select **Only people with access to this data source**.
For reuse, do not repeat the change.

**Verify:** inspect the actual saved selection. **Everyone** here grants source
access; it is not organization-wide rollout. Organization-wide rollout is supported
while preserving ServiceNow permissions. Explain both rollout options next.

## audience

**Owner:** Microsoft 365 AI administrator.
**Record:** `organization-wide` or `selected-users`, as chosen by the user.

**Act:** configure or reuse the approved rollout audience.

Before changing **Setup > Rollout to limited audience**, explain both options:

- **Organization-wide:** leave the toggle off to make the connection available
  across the organization; each person still needs ServiceNow source access.
- **Selected users/groups:** turn the toggle on and select the intended supported
  users/groups for a limited rollout; they still need ServiceNow source access.

Ask which applies to this deployment before configuring it. Do not assume a
default or carry over another deployment's choice. If the user already explicitly
chose for this deployment, reuse that choice without asking again.

**Verify:** reopen/review the actual audience setting.

Either choice retains source-trimmed permissions and the same approved KB query.
Copilot Chat/Search visibility is not required for ESS-only acceptance.

## schedules

**Owner:** Microsoft 365 AI administrator. **Record:** `confirmed`.

**Act:** inspect schedules and configure only approved changes.

In **Sync**, inspect the actual content incremental and full-crawl settings.
Documented defaults are content incremental every 15 minutes and full daily;
review them against approved expectations, not a promised revocation SLA.
Simple identity refresh follows full crawls.

This MVP defers Advanced `user_changes` and auditing. Do not enable or claim
incremental identity refresh without that validated dependency. If a reused
connection already has it, inspect its approved health and ownership without
altering it; do not treat it as newly tested. Keep full crawls.

**Verify:** review the saved content and identity schedules against the approved
expectations; do not infer a revocation SLA or unconfigured incremental identity sync.

## connection-name

**Owner:** Microsoft 365 AI administrator. **Record:** actual connection name
shown when selecting the source in ESS Knowledge.

**Act:** create the approved connection once, or open the exact reused connection.

For a new draft, verify that Custom setup's **Authorize** succeeded for the
current settings; a settings-only confirmation is not proof. Reuse an actual
successful result for unchanged settings, otherwise authorize before continuing.
Review the configured draft, obtain explicit creation approval, then select
**Create** once. For reuse, do not create anything.

**Verify:** inspect the created or reused connection's actual display name and
matching instance/settings. Reuse the name already supplied during the wizard;
do not ask the user to enter it again. If unknown, ask **What connection name
will you select in ESS Knowledge?** Record that name, including spaces and
punctuation. Do not request a technical Connection ID.
If multiple connections have the same name, clarify the intended source using
its instance, flow and approved scope before recording or selecting it.
If Create returns an ambiguous failure, inspect the
existing connections before retrying; never assume nothing was created.

## connection-ready

**Owner:** Microsoft 365 AI administrator. **Record:** `confirmed`.

**Act:** verify actual operation after Create for the recorded connection name.

1. Open **Microsoft 365 admin center > Copilot > Connectors**, select the
   connection whose **name** matches the recorded value, verify its instance
   and approved configuration, and open its
   details. For reuse, inspect that existing connection; do not create another.
2. Inspect **Detail**, **Statistics** and **Error**. Review actual authentication,
   connectivity and crawl errors; do not infer success from the saved auth selection.
3. Wait for the relevant initial content and identity processing. Compare the
   approved eligible scope with indexed counts and known expected records,
   including a known article from that scope. Resolve reported errors.
4. Report whether processing completed and the expected content is present
   without unresolved authentication/connectivity errors. If still processing
   or the observations are unavailable, leave this checkpoint pending.

**Verify:** compare expected eligible scope and actual ingestion, including
known records. Creation/authentication success, zero reported item errors or
one item count alone is insufficient. Neither the old pre-Create "Both succeeded"
answer nor a grouped legacy Ready flag completes this connection-bound checkpoint.
Ask **Has this connection completed initial processing with expected content
present and no unresolved authentication/connectivity errors?** Use unset
verified/still-processing/failed-or-unverified choices. Record `confirmed` only
for the verified outcome and supply the saved `--connection-name` with
the internal confirmation command. Do not ask for a separate authentication
button or claim token/sample-fetch telemetry the portal did not show.
If still processing, stop at this step and resume later; don't record Ready or
spin in an endless polling loop. Indexed item and reader checks follow separately.
Complete those checks before opening ESS: select the article/KB, verify Indexed
and compare allowed access in ServiceNow and the index. Offer the grouped optional
denied-reader comparison or explicit Skip. Only then attach
the named source in ESS and test its answer/citation.
On failure, retain the recorded connection name and saved setup, guide the specific
provider/claim/role/network correction in chat, and recheck this same connection.
Do not reset it to a new draft or automatically retry Create.

## test-article

**Owner:** maker with source owner. **Record:** actual article number, e.g. `KB0000012`.

**Act:** select a representative article and an ordinary allowed reader.

Choose an indexed article in the approved scope with one known allowed ordinary
reader. Finding a denied reader is optional and happens in the later recommended
denied-reader action, not as a prerequisite to choosing an article.
Avoid administrator, KB-owner or contributor
exceptions that would invalidate the permission comparison. No article body,
reader identity or sensitive prompt is stored.

**Verify:** check the article is in the approved scope and record its actual number,
not its sys_id or title.

When both article and KB details are pending, show the selection instructions
above and the KB-reference lookup below together, then ask **one form with two
fields**: **Test article number** and **Knowledge Base sys_id**. Explain that the
second field is the referenced KB's 32-character lowercase sys_id, not the
article's sys_id. Do not submit a separate article-only question first.
After the grouped answer, record `test-article`, refresh status, then record
`test-kb` for that same article using the saved connection name and scope.
Retain the separate validators and prerequisite checks; a missing or invalid
field is not confirmed. On resume, reuse valid saved details and ask only for
the missing or corrected field. If no suitable allowed-reader test article exists,
pause here; absence of a denied reader does not block article selection.

## test-kb

**Owner:** maker/source owner. **Record:** actual 32-character lowercase KB sys_id.

**Act:** retrieve the selected article's Knowledge Base reference.

Open the selected article privately and inspect its Knowledge Base reference.

**Verify:** verify the KB identity against the selected scope.

Record the KB's sys_id, not the article sys_id. It must match any selected-KB
filter. Use this same article/KB for every subsequent test.

## article-indexed

**Owner:** maker/Microsoft 365 administrator. **Record:** `confirmed`.

**Act:** locate the selected article in the exact connection's Index browser.

Open the exact connection's **Index browser**. Locate the selected article using
its `kb_number` and `knowledge_base_sys_id`.

**Verify:** inspect Indexed status and displayed
refresh information. Check relevant Title/content property status; the property
status UI is not a display of the article body. Do not use the article sys_id
in the KB filter or infer indexing from crawl creation.
If the article is missing, still processing or unverified, pause here; do not
move to ESS attachment as a workaround. Resolve the specific indexing issue
against the same connection and recheck.

## allowed-native

**Owner:** ordinary allowed reader with source owner. **Record:** `confirmed`.

**Act:** open the exact article as the intended ordinary allowed reader, using
their actual ServiceNow session or supported native permission diagnostics.

**Verify:** confirm the reader can access the article. Crawler
and administrator visibility are not substitutes.

## allowed-indexed

**Owner:** Microsoft 365 administrator. **Record:** `confirmed`.

**Act:** run the indexed access check for the same allowed reader and article.

For the same article in the exact connection's Index browser, open **Permissions >
Check user access** and check the intended mapped allowed reader.

**Verify:** the result must
be Allowed. A source allow alone doesn't prove indexed identity/permission access.

## denied-native

**Owner:** maker/source owner and Microsoft 365 administrator.
**Record:** grouped `denied-reader` result, `confirmed` or `skipped`.

**Optional, recommended: verify denied-user access**

Present this and `denied-indexed` as one action, not two questionnaires. Explain
that it checks whether a user denied by ServiceNow is also denied by the index.
Offer **Run recommended access check** and **Skip** without a preselected answer.
On Skip, record `confirm --step denied-reader --value skipped` with the saved
connection name and target reference. This atomically skips both internal checks;
continue setup with the returned warning. Do not label skipped checks as passed.

**Act:** for Run, show the complete walkthrough together:

1. Ask the user to find an ordinary employee who cannot access the selected
   article in ServiceNow. Establish that denial using the employee's actual
   session or supported source diagnostics with the source owner; signing in
   alone is not evidence. Do not substitute an administrator or integration user.
2. Use that employee's mapped Microsoft Entra identifier, such as their UPN,
   privately in the indexed **Check user access** lookup below. Do not save the
   employee identifier in progress, an acceptance file or committed records.
3. Check the same article/KB in the saved connection and verify **Denied**.
   Ask for one combined result, not separate native/indexed confirmation forms.
   Record `confirm --step denied-reader --value confirmed` only when both the
   source denial and indexed denial are actually established.

**Verify:** establish both source and indexed denial before recording a pass.
If no suitable denied reader is available, offer Skip for the whole comparison.
If source or indexed access is unexpectedly allowed, report the failed comparison
with grouped value `unverified` and pause for owner review. An observed failure
cannot be cleared by Skip; correct and rerun the comparison.

## denied-indexed

This is the indexed portion of the single optional, recommended action above,
not another user-facing question. Existing verified native results may be reused;
on a partial legacy resume, guide only the missing indexed observation.

**Owner:** Microsoft 365 administrator.

**Act:** use **Check user access** on the same indexed article for that same mapped denied
reader. Confirm the selected article number and KB sys_id in the saved connection
before entering the identifier.

**Verify:** it must be Denied. Unexpected indexed access blocks acceptance; investigate
identity, criteria completeness, HR-scoped rows, property reads and crawl freshness.
Never change Users to Everyone or remove criteria to make the test pass.

## source-attached

**Owner:** maker. **Record:** `confirmed`.

**Act:** after indexed-content and allowed/denied permission verification
(or explicit skip of the optional denied-reader comparison),
attach or reuse the exact Knowledge connection in the selected Dev agent.

Open the exact selected native ESS HR/IT Development agent in the supported
authoring interface and recheck its current identity/environment/realm.
In its Knowledge source management, select/add the exact ServiceNow Knowledge
connection by the saved connection name, reusing it if already attached. Show
that name before asking the user to select it; do not ask for a Connection ID.
If names are duplicated, clarify the matching source/configuration before selection.

**Verify:** inspect the saved source entry and exact connection identity.

Do not attach a similarly named
connection, substitute article uploads, invent an attachment API, or publish/
promote the agent. If this interface doesn't expose a supported attachment
operation, pause explicitly rather than assuming local metadata attached it.

## source-isolated

**Owner:** maker. **Record:** `confirmed`.

**Act:** isolate the selected source using an approved test configuration.

Use a supported, approved test configuration to isolate this exact source for
the selected agent's retrieval test.

**Verify:** check for overlapping indexed connections
that could return the same article. Do not disable shared production connections
or assume a citation URL identifies the supplying connector. If isolation isn't
available, leave this check unverified and explain the limitation.

## answer-citation

**Owner:** allowed ordinary reader and maker. **Record:** `confirmed`.

**Act:** ask the selected native Dev agent a question answered by the test article.

In the selected native ESS Dev test experience, have the same allowed employee
use a detailed, non-sensitive prompt describing the article's topic, the actual
task or problem, and the instructions they need. Do not test only with an article
number or a vague keyword. Show this template with the saved article number;
the user fills the private topic/scenario details in ESS:

> I need help with [specific task/problem covered by the selected article].
> My situation is [relevant non-sensitive context]. Explain the prerequisites,
> detailed steps and any limitations described in ServiceNow article
> [saved article number] about [article topic/title]. Base the answer on that
> article and include citations linking to the supporting article.

**Verify:** verify a relevant answer and matching article
citation from the isolated source. Review the response against the selected
article privately, not just whether an answer appeared. Open its supporting
citations and verify they point to the correct article number, Knowledge Base
and intended ServiceNow portal destination. A relevant answer without a correct
supporting article citation does not pass. Merely returning a link or finding a different connector's
copy doesn't pass. Do not persist sensitive prompts or article text.

## observation-time

**Owner:** controller bookkeeping. **Record:** automatic UTC observation timestamp.

**Automatic bookkeeping, not a normal user question.**

Do not ask the user to enter a date, time or timezone. After the last required
acceptance result is confirmed (with the optional denied-reader comparison
confirmed or explicitly skipped), the controller records the completion time
automatically from the latest recorded acceptance checkpoint and assembles scoped
maker acceptance. This records when the observation was confirmed, not remote
telemetry or an independently measured test-execution time.

Existing observation times remain unchanged on resume. Older completed checks
missing only this timestamp are finalized by `start` using their recorded
completion evidence, not the current resume time. Failed or pending checks do
not receive a completion timestamp. Explicit historical corrections remain
supported; they are not a normal question.
`guided-validated` covers only these recorded representative cases.
`guided-complete-with-warnings` means setup observations are complete but the
denied-reader comparison was skipped; it does not establish denied-user parity.
Current FlightCheck indexing/ACL boundaries remain Manual, not Passed.

## References and execution limits

The configuration guidance was checked against Microsoft's current
[deployment recipe](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-deployment),
[source prerequisites](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-admin-setup),
and [script execution guidance](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-setup-scripts).
Use the original linked vendor scripts after reviewing the actual version,
not a copied/reconstructed evaluator. Script documentation's broad reuse and
non-destructive claims do not replace inspecting existing-record effects.

This controller performs local bookkeeping only. Portal checks and source tests
remain observed administrator/maker attestations, not API-verified evidence.
Other auth methods, optional audit/incremental-identity setup, Test/Prod,
publishing/promotion, and unattended remote provisioning remain out of scope.
