# Workday ISU Authentication Debugging Guide

Systematic guide for diagnosing Workday Integration System User (ISU) failures in the ESS agent. Covers the complete authentication chain: Workday → Entra ID → Power Platform → Copilot Studio, plus Okta-federated environments.

**When to use this guide:** The ESS agent's Workday integration works for makers (developers) testing in Power Automate or Copilot Studio but fails for end users, or ISU-based SOAP/OAuth calls return errors.

---

## Quick Reference: Error → Config Lookup

Use this table first. Match the error message or symptom to the configs that most likely cause it, then jump to the corresponding config section.

### Error String → Config Mapping

| Error String | Auth Leg | Configs to Check | One-Line Root Cause |
|-------------|----------|-----------------|---------------------|
| `invalid_client` | First (OAuth) | 1, 2, 3, 8 | OAuth client ID/secret wrong, ISU not granted access, or wrong grant type |
| `invalid username or password` | Second (SOAP) | 4, 9, 10 | ISU credentials wrong, locked, expired, or auth policy blocks password login |
| `Response is not in JSON format` | First (OAuth) | 3, 5, 11 | Token endpoint returned HTML — wrong URL, issuer mismatch, or firewall block |
| `executeUserSOAPFailure` | Second (SOAP) | 4, 9, 10 | User ISU lacks permissions or credentials are invalid |
| `executeGenericSOAPFailure` | Second (SOAP) | 9, 12 | Generic ISU missing domain permissions or report misconfigured |
| `executeContextSOAPFailure` | Second (SOAP) | 9, 12 | Context ISU missing domain permissions or report misconfigured |
| `TemplateRetrievalFailure` | N/A | Dataverse | Template config record missing or Dataverse connection broken |
| `XmlTemplateToJsonFailed` | N/A | Dataverse | Template config XML is malformed |
| `generateXMLFailure` | N/A | Template | SOAP XML body generation failed — check template config content |
| `extractManagerDataFailure` | Second (SOAP) | 9, 12 | ISU cannot read manager data — domain permission or report issue |

### Symptom → Config Mapping

| Symptom | Configs to Check | Start Here |
|---------|-----------------|------------|
| Maker works, end users don't | 1, 4, 5, 9 | Config 1 (OAuth grants) then Config 4 (ISU status) |
| Worked yesterday, broken today | 4, 7 | Config 4 (password expiry) then Config 7 (secret expiry) |
| New environment, nothing works | 1, 2, 3, 4, 5, 6 | Start at Config 1 and work through sequentially |
| Changed password, still failing | Auth Reset Guide | Go to "Authentication Reset Guide" section |
| Works in Copilot Studio test, fails in BizChat | 1, 4, 9 | Config 1 — maker uses different auth path than ISU |
| Okta environment, first-time setup | 5, 14, 15 | Config 14 (dual IdP) is the #1 Okta root cause |
| Intermittent failures | 4, 7, 11 | Config 4 (account locking) then Config 7 (secret rotation) |

### Diagnostic Decision Tree

1. **Is Okta involved?** → Yes: also check Configs 13–17. No: continue below.
2. **Can the maker connect successfully?**
   - YES → Issue is ISU-specific. Go to step 3.
   - NO → Check Configs 5 (SAML/Issuer), 6 (Connector Auth), 7 (Secret Expiry), 11 (Network).
3. **What error do you see?** → Match against the Error String table above.
4. **Test outside Power Platform** (Postman OAuth + SOAP tests — see Section 7.4).
   - Both pass → Issue is Power Platform specific (connection reference, connector version).
   - OAuth fails → First leg issue: Configs 1, 2, 3, 5, 8.
   - SOAP fails → Second leg issue: Configs 4, 9, 10, 12.
5. **If all external tests pass** → Collect full trace package (Section 7) and follow Auth Reset Guide.

---

## Background: Why Maker Works but ISU Doesn't

| Aspect | Maker (Works) | ISU (Fails) |
|--------|---------------|-------------|
| Auth method | Interactive OAuth via browser | Client Credentials (automated) |
| Credentials used | Maker's Entra AD identity | ISU username + password |
| Token issued by | Entra AD (on behalf of maker) | Entra AD (on behalf of app) |
| What Workday validates | OAuth token + ISU credentials via SOAP | OAuth token + ISU credentials via SOAP |

The maker's interactive login bypasses several ISU-specific configurations. When the flow runs unattended (as ISU), ALL configurations must be perfect — there is no interactive fallback.

### Connection References

| Connection Reference | Auth Type | Used For | Affected Configs |
|---------------------|-----------|----------|-----------------|
| OAuthUser | OAuth 2.0 (user) | Token exchange with Workday | 2, 3, 5, 6, 7, 8 |
| Context Generic User | Basic Auth | SOAP calls as context ISU | 1, 4, 9, 10, 12 |
| Generic User | Basic Auth | SOAP calls as generic ISU | 1, 4, 9, 10, 12 |
| Dataverse | Entra AD | Read/write Dataverse tables | N/A (rarely fails) |

### The Two-Leg Authentication Flow

| | First Leg: OAuth Token Exchange | Second Leg: SOAP API Call |
|-|--------------------------------|--------------------------|
| Protocol | OAuth 2.0 Client Credentials | SOAP over HTTPS with Basic Auth |
| Credentials | Client ID + Secret → Token endpoint | ISU username + password in HTTP header |

---

## Configuration Checklist

All configurations that must be correct for ISU-based Workday connectivity, ordered by likelihood.

### Config 1: OAuth Grants on ISU Accounts

**Likelihood:** HIGH | **Platform:** Workday
**Symptoms:** `invalid_client`

**What:** Each ISU account must have an explicit OAuth 2.0 grant for the API Client used by the connector.

**Why it fails:** Admins create the ISU and API Client but forget to link them. The maker authenticates interactively, bypassing the ISU grant requirement.

**Check:**
1. In Workday, search View Integration System User for each ISU
2. Scroll to the OAuth 2.0 Clients section
3. The API Client (e.g., ESS_Copilot_Client) must be listed AND the status must be Active
4. If the section is empty or the client is missing, the grant has not been created

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| OAuth grants on ISU | Workday > View ISU > OAuth 2.0 Clients section | API Client listed and Active |
| API Client to grant | Workday > View API Client > Client Name | Must match the one used in PP connection |
| To add the grant | Workday > Edit ISU > OAuth 2.0 Clients > Add | Select the API Client from the list |
| To activate the grant | After adding, check the Active checkbox | Must be checked (active) |

> **Common Mistake:** Adding the API Client to the ISU but forgetting to check the 'Active' checkbox. The grant appears configured but is actually inactive.

**Fix:**
1. Edit ISU → scroll to OAuth 2.0 Clients → Add
2. Select the API Client → check Active → Save

---

### Config 2: API Client ID and Secret

**Likelihood:** HIGH | **Platform:** Workday + Power Platform
**Symptoms:** `invalid_client`

**What:** The Client ID and Client Secret in the Power Platform connection reference must exactly match the values in the Workday API Client definition.

**Why it fails:** Copy-paste errors, extra whitespace, or using values from the wrong API Client (e.g., sandbox vs production). Client IDs are case-sensitive.

**Check:**
1. Open the Workday API Client (View API Client for the ESS connector)
2. Copy the Client ID exactly
3. In Power Platform, open the connection reference → compare Client ID character by character
4. For Client Secret: regenerate in Workday if uncertain, then update in PP

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Client ID in Workday | Workday > View API Client > Client ID field | Copy this value exactly |
| Client Secret | Workday > Edit API Client > Regenerate Secret | Update in PP after regenerating |
| Client ID in PP | PP > Solutions > Connection References > Edit > Client ID | Must match Workday exactly |

**Fix:**
1. Copy Client ID from Workday
2. Paste into PP connection reference
3. If secret is uncertain, regenerate in Workday and update both PP and any other consumers

---

### Config 3: Token Endpoint URL

**Likelihood:** HIGH | **Platform:** Workday + Power Platform
**Symptoms:** `invalid_client`, `Response is not in JSON format`

**What:** The OAuth token endpoint URL must follow the exact format: `https://{host}/ccx/oauth2/{tenant}/token`.

**Why it fails:** Wrong Workday data center host (e.g., wd2 vs wd5), omitted tenant name, or implementation-specific URL that doesn't support OAuth.

**Check:**
1. Verify URL format: `https://{host}/ccx/oauth2/{tenant}/token`
2. Host must match your Workday data center (e.g., `wd2-impl-services1.workday.com` for implementation)
3. Tenant must match your exact Workday tenant name (case-sensitive)
4. Test with Postman: POST to the URL with client credentials

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Workday token endpoint | Workday > View API Client > Token Endpoint field | Must show correct host and tenant |
| PP token endpoint | PP > Connection References > Edit > Token URL | Must match Workday exactly |
| Verification | POST to URL with valid credentials | Should return JSON with access_token |

**Fix:**
1. Copy exact token endpoint URL from Workday View API Client page
2. Paste into Power Platform connection reference
3. Test with Postman to verify before saving

---

### Config 4: ISU Account Status

**Likelihood:** HIGH | **Platform:** Workday
**Symptoms:** `invalid username or password`, `executeUserSOAPFailure`

**What:** Both ISU accounts (`ISU_WQL_COPILOT` and `ISU_CONTEXT_COPILOT`) must be active, unlocked, with valid (non-expired) passwords, and 'Do Not Allow UI Sessions' = Yes.

**Why it fails:** ISU passwords expire based on Workday security policy (often 90 days). Accounts lock after failed login attempts.

**Check:**

| Check | ISU_WQL_COPILOT | ISU_CONTEXT_COPILOT |
|-------|-----------------|---------------------|
| Account Status | Must be Active | Must be Active |
| Locked? | Must not be locked | Must not be locked |
| Password Expired? | Check expiry date | Check expiry date |
| Do Not Allow UI Sessions | Must be Yes | Must be Yes |

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Account status | Workday > View ISU > Status field | Active |
| Lock status | Workday > View ISU > Account Locked field | No (unlocked) |
| Password expiry | Workday > View ISU > Password Expiry | Future date |
| To unlock | Workday > Edit ISU > Uncheck Account Locked > Save | Unlocked |
| To reset password | Workday > Edit ISU > Change Password | Use alphanumeric-only password |

> **Tip:** Use alphanumeric-only passwords for ISUs. Special characters (`&`, `%`, `#`) cause encoding issues in Basic Auth headers and SOAP calls.

**Fix:**
1. Edit ISU → reset password (alphanumeric only, no special characters)
2. Uncheck Account Locked
3. Verify Do Not Allow UI Sessions = Yes → Save
4. Update the password in Power Platform connection references

---

### Config 5: SAML IdP Issuer and Token Version

**Likelihood:** MED-HIGH | **Platform:** Entra + Workday
**Symptoms:** `Response is not in JSON format`

**What:** The `accessTokenAcceptedVersion` in the Entra app manifest determines the token issuer claim. Workday's SAML IdP must have the matching issuer URL.

**Why it fails:** Entra manifest has `accessTokenAcceptedVersion` = null/1 (issuer = `sts.windows.net`) but Workday expects v2 (issuer = `login.microsoftonline.com`), or vice versa.

**Check:**
1. Open Entra app registration → Manifest → find `accessTokenAcceptedVersion`
2. Map the version to the issuer:

| accessTokenAcceptedVersion | Issuer URL |
|---------------------------|------------|
| null or 1 (v1) | `https://sts.windows.net/{tenant-id}/` |
| 2 (v2) | `https://login.microsoftonline.com/{tenant-id}/v2.0` |

3. In Workday, go to SAML IdP configuration and check the Issuer field
4. The Issuer in Workday MUST match the issuer from the token version above

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Manifest token version | Entra > App Registrations > Manifest > accessTokenAcceptedVersion | null, 1, or 2 |
| Workday SAML Issuer | Workday > Edit Tenant Setup – Security > SAML IdP > Issuer | Must match token version |
| SAML Tracer verification | Browser extension > Issuer in assertion | Must match Workday config |

> 🛑 **DANGER — Safe Migration Sequence:**
> 1. Check CURRENT Entra token version and note the corresponding issuer URL
> 2. Update Workday SAML IdP Issuer to match the NEW issuer URL
> 3. Only AFTER Workday is updated, change the Entra manifest
>
> Do NOT change the Entra manifest first — this breaks ALL authentication immediately.

**Fix:**
1. Update Workday SAML IdP Issuer to match the target issuer URL
2. Then update the Entra manifest `accessTokenAcceptedVersion`
3. Verify with SAML Tracer

---

### Config 6: Workday Connector Auth in Entra

**Likelihood:** MEDIUM | **Platform:** Entra
**Symptoms:** `invalid_client` (when maker also fails)

**What:** The Workday connector in Power Platform uses app ID `4e4707ca-5f53-46a6-a819-f7765446e6ff`. This must be listed as an authorized client application in Entra.

**Why it fails:** The connector app ID isn't in the Authorized client applications list in Entra, so the token exchange is rejected.

**Check:**
1. Open Entra > App Registrations > your Workday app > Expose an API
2. Check Authorized client applications for: `4e4707ca-5f53-46a6-a819-f7765446e6ff`
3. If not listed, the connector cannot obtain tokens on behalf of users

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Authorized clients | Entra > Expose an API > Authorized client applications | Must include `4e4707ca-5f53-46a6-a819-f7765446e6ff` |

**Fix:**
1. Entra > App Registrations > Expose an API > Add a client application
2. Paste `4e4707ca-5f53-46a6-a819-f7765446e6ff`
3. Select all exposed scopes → Save

---

### Config 7: Entra Client Secret Expiry

**Likelihood:** MEDIUM | **Platform:** Entra
**Symptoms:** `invalid_client` (intermittent or sudden onset)

**What:** The client secret in the Entra app registration has an expiry date. When it expires, the OAuth token exchange fails.

**Why it fails:** Client secrets expire silently. The maker may still work using cached credentials or delegated permissions.

**Check:**
1. Entra > App Registrations > your app > Certificates & secrets
2. Check the expiry date of all client secrets
3. If expired, generate a new one and update all consumers

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Secret expiry | Entra > Certificates & secrets > Expiration | Future date |
| Where to update | PP connection references and any other OAuth consumers | Update all consumers |

**Fix:**
1. Generate a new client secret in Entra (copy immediately — it won't be shown again)
2. Update the Power Platform connection reference
3. Update any other systems using this secret

---

### Config 8: API Client Grant Type and Scope

**Likelihood:** MEDIUM | **Platform:** Workday
**Symptoms:** `invalid_client`

**What:** The Workday API Client must have Client Credentials grant type and functional scope including HR data domains.

**Why it fails:** API Client was created with Authorization Code grant type instead of Client Credentials, or scope doesn't include required HR domains.

**Check:**
1. Workday > View API Client > check Grant Types — Client Credentials must be listed
2. Check Scope (Functional Areas) — must include HR-related domains

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Grant types | Workday > View API Client > Grant Types | Client Credentials (required) |
| Scope | Workday > View API Client > Scope | Must include HR domains |

**Fix:**
1. Edit API Client → add Client Credentials to Grant Types
2. Ensure Scope includes all required HR functional areas → Save

---

### Config 9: ISU Security Group and Domain Permissions

**Likelihood:** MEDIUM | **Platform:** Workday
**Symptoms:** `invalid username or password`, `executeGenericSOAPFailure`, `executeContextSOAPFailure`, `executeUserSOAPFailure`

**What:** ISUs must belong to a security group with Get/Put access to the specific Workday domains used by the ESS agent.

**Why it fails:** ISU is in a security group that lacks permissions for required domains, or ISU was removed from the group.

**Check:**
1. Check which security group the ISU belongs to
2. Verify the group has Get access to all required domains

**Required Domain Permissions:**

| Domain | Permission | Used For |
|--------|-----------|----------|
| Worker Data: Public Worker Reports | Get | Reading worker profile data |
| Compensation | Get | Accessing compensation/pay information |
| Personal Data | Get | Employee personal information |
| Current Staffing Information | Get | Current position and job details |
| Reports: WQL | Get | Executing WQL-based custom reports |

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| ISU's security group | Workday > View ISU > Security Groups section | Group listed and active |
| Group permissions | Workday > View Security Group > Domain Security Policies | All required domains with Get |

**Fix:**
1. Add the ISU's security group to each missing domain security policy with Get access
2. **Activate pending security policy changes** (changes don't take effect until activated)

---

### Config 10: Workday Authentication Policy

**Likelihood:** LOW-MEDIUM | **Platform:** Workday
**Symptoms:** `invalid username or password`

**What:** The authentication policy must allow username/password authentication for the ISU security group. SAML-only policies block ISU Basic Auth.

**Why it fails:** Admin changed policy to SAML-only or MFA-required for all users, including ISU service accounts.

**Check:**
1. Workday > Authentication Policies > find policy for ISU's security group
2. Verify User Name Password authentication is allowed (not SAML-only)
3. Check no conditional rules block non-interactive logins

**Fix:**
1. Edit authentication policy → allow password auth for ISU security group
2. Save and activate pending security policy changes

---

### Config 11: Network Allowlisting

**Likelihood:** LOW-MEDIUM | **Platform:** Network
**Symptoms:** `Response is not in JSON format`, timeouts

**What:** Power Platform outbound IP ranges must be allowlisted in your firewall/WAF to reach Workday.

**Why it fails:** Maker's browser is inside corporate network and can reach Workday directly. Power Platform cloud connectors use external IPs that may be blocked.

**Check:**
1. Verify Power Platform outbound IP ranges are allowlisted in your firewall/WAF
2. Check if a proxy is required and properly configured
3. Test from outside the network (e.g., Postman from a cloud VM) to reproduce
4. Common symptom: `Response is not in JSON format` (HTML firewall block page returned)

**Fix:**
1. Work with network team to allowlist Power Platform outbound IPs for your region
2. Ensure Workday endpoint is reachable from these IPs without proxy interference

---

### Config 12: Custom Report Configuration

**Likelihood:** LOW | **Platform:** Workday
**Symptoms:** `executeGenericSOAPFailure`, `executeContextSOAPFailure`, `extractManagerDataFailure`

**What:** Custom reports must be owned by the correct ISU (`ISU_WQL_COPILOT`), enabled as web services, use API v43.0+, and have correct XML aliases.

**Why it fails:** Report ownership not transferred, web service checkbox unchecked, API version too old, or XML aliases don't match flow expectations.

**Check:**
1. Open each custom report in Workday
2. Verify Owner = `ISU_WQL_COPILOT`
3. Verify Enable As Web Service = Yes
4. Verify API version ≥ v43.0
5. Verify XML aliases match flow expectations

**Values:**

| What to Check | Where to Find It | Expected Value |
|--------------|-----------------|----------------|
| Report owner | Workday > View Custom Report > Owner field | ISU_WQL_COPILOT |
| Web service enabled | Advanced tab > Enable As Web Service | Yes |
| API version | Web Service tab > API Version | v43.0 or later |
| XML aliases | Columns > XML Alias for each column | Must match flow expectations |

**Fix:**
1. Transfer report ownership to `ISU_WQL_COPILOT`
2. Enable as web service, set API version to v43.0+
3. Verify all XML aliases match flow configuration

---

## Okta-Federated Environments (Configs 13–17)

These configs only apply when Okta is in the authentication chain (Okta → Entra → Workday). Skip this section if your organization does not use Okta.

### Config 13: Okta → Entra Federation Trust

**Likelihood:** MEDIUM | **Platform:** Okta + Entra
**Symptoms:** First-leg OAuth failures in Okta environments

**What:** Okta-to-Entra SAML federation must have correct attribute statements (UPN, ImmutableID), proper NameID format, and user must be assigned to Okta application.

**Check:**
1. Verify user is assigned to Okta app for Entra federation
2. Check SAML attribute statements map correctly to Entra expectations
3. Verify NameID format (typically emailAddress or persistent)
4. Use SAML Tracer to capture actual assertion and verify values

**Fix:** Update Okta SAML attribute statements to correctly map UPN and ImmutableID. Ensure NameID format matches Entra configuration. Assign user to Okta application.

---

### Config 14: Workday Dual IdP Configuration

**Likelihood:** HIGH | **Platform:** Workday + Okta + Entra
**Symptoms:** All ISU calls fail in Okta-federated environments

> 🛑 **#1 Okta-Specific Root Cause.** This is the most common cause of ISU failures in Okta-federated environments.

**What:** Workday must have a SEPARATE Entra AD SAML trust configured alongside the Okta trust. Power Platform authenticates via Entra (not Okta), so Workday must accept Entra SAML assertions directly.

**Why it fails:** Workday only has Okta SAML IdP configured. Entra-issued SAML assertions are rejected because Workday doesn't recognize the issuer.

**Check:**
1. Workday > Edit Tenant Setup – Security > SAML Setup
2. Count SAML Identity Providers — should be at least 2 (Okta + Entra)
3. Verify Entra entry has correct Issuer URL (see Config 5)

**Fix:**
1. Add a new SAML Identity Provider entry for Entra AD
2. Use Entra federation metadata URL to populate configuration
3. Ensure both Okta and Entra IdP entries coexist

---

### Config 15: Claim Chain (Okta → Entra → Workday)

**Likelihood:** MEDIUM | **Platform:** All three
**Symptoms:** User lookup or identity mismatch errors

**What:** User identity attributes (UPN, ImmutableID, email) must be consistent across Okta, Entra, and Workday.

**Check:**
1. Trace UPN from Okta → Entra → Workday login
2. Verify ImmutableID consistency between Okta and Entra
3. Check email addresses match across all three systems

**Fix:** Align UPN, ImmutableID, and email values across all three systems. Start from Okta (source of truth), verify Entra matches, then verify Workday login matches.

---

### Config 16: Okta MFA/Session/Network Policies

**Likelihood:** LOW-MEDIUM | **Platform:** Okta
**Symptoms:** First-leg OAuth failures, intermittent auth failures in Okta environments

**What:** Okta's sign-on policies, network zones, and session lifetime settings can block Power Platform connector authentication.

**Why it fails:** Okta requires MFA for sign-on (Power Platform cannot do MFA), network zones block cloud IPs, or short session lifetimes cause frequent re-auth failures.

> These policies affect the FIRST leg only. If the second leg (SOAP) fails, check Configs 4, 9, 10, 12 instead.

**Fix:**
1. Create Okta sign-on policy rule excluding service accounts from MFA
2. Add Power Platform IPs to trusted network zones
3. Ensure session lifetime is sufficient for automated flows

---

### Config 17: Okta → Entra Provisioning Sync

**Likelihood:** LOW | **Platform:** Okta + Entra
**Symptoms:** User exists in Okta but auth fails in Entra

**What:** If Okta provisions users to Entra (SCIM or JIT), sync failures can cause missing or stale user attributes in Entra.

**Check:**
1. Check Okta provisioning status for the Entra app
2. Look for provisioning errors in Okta system log
3. Verify user exists in both Okta and Entra with matching attributes

**Fix:** Resolve provisioning errors in Okta. Force sync for affected users.

---

## Authentication Reset Guide

Use this after making configuration changes to clear all stale caches across every layer.

**When to use:** After updating any authentication configuration (ISU password, client secret, SAML settings, domain permissions, etc.) and the change doesn't seem to take effect.

### Layer-by-Layer Reset Checklist

**Step 1: Workday**
1. **Activate Pending Security Policy Changes** — changes don't take effect until activated
2. If ISU password was changed, update it in API Client configs, Power Platform connections, and all integration endpoints
3. Verify ISU account is not locked or expired (test with Postman)

**Step 2: Entra ID**
1. Wait at least 5 minutes for Entra ID propagation after any app registration or SAML changes
2. Clear Conditional Access policy caches — test user signs out completely and back in
3. Check Entra Sign-in logs for failed auth attempts after the change
4. If SAML certificates were rotated, keep both old and new temporarily active

**Step 3: Power Platform Connections**
1. Power Automate → Connections → find Workday SOAP connector
2. **Delete and recreate** the connection with updated credentials (do NOT trust the green checkmark)
3. Test the new connection and verify successful response

**Step 4: Connection References**
1. Power Automate → Solutions → ESS Solution → Connection References
2. Re-map each reference to the newly created connection:
   - **OAuthUser** — delegated user authentication
   - **ISU_WQL** — Workday Query Language operations
   - **ISU_Generic** — generic SOAP API calls
   - **Dataverse** — template configuration storage

**Step 5: Power Automate Cloud Flows**
1. Turn off each Workday-related cloud flow, wait 30 seconds, turn back on
2. Run a manual test of the primary Workday flow
3. Inspect flow run history for successful completion

**Step 6: Copilot Studio Bot**
1. Open ESS Agent in Copilot Studio
2. Type `/debug clearstate` in test chat (clears bot variables only — NOT OAuth tokens)
3. Publish the bot (even if no topic changes — forces new connection reference bindings)
4. Test in Copilot Studio test pane

**Step 7: End-User Validation**
1. Have a **non-maker user** test in Microsoft 365 Copilot BizChat (maker uses different auth path)
2. Test with 2–3 users across different departments
3. Test the specific question that was failing + at least one other question
4. Check Power Automate flow run history for these test runs

### Cache Lifetimes

| Layer | Duration | How to Clear |
|-------|----------|-------------|
| Entra ID access tokens | 60–90 min | Wait for expiry or force re-auth |
| Entra ID refresh tokens | Up to 90 days | Revoke in Azure Portal or change password |
| Power Platform connector OAuth | Until revoked | Delete and recreate connection |
| Copilot Studio global variables | 30 min idle timeout | `/debug clearstate` |
| Workday security policy changes | Indefinite (staged) | Activate Pending Security Policy Changes |
| Published bot configuration | Until next publish | Publish in Copilot Studio |

### Common Pitfalls

- **Testing only in Copilot Studio test pane** — uses maker credentials, not ISU. Fix appears to work but fails for end users.
- **Not activating pending security policy changes in Workday** — changes are staged, not live.
- **Trusting the green checkmark** on Power Platform connections — status can be stale.
- **Updating only one connection reference** — ESS uses OAuthUser, ISU_WQL, ISU_Generic, and Dataverse. Missing any one causes failures.
- **Forgetting to publish the bot** — unpublished bots use old connection reference bindings.
- **Not cycling flows off and on** — flows hold stale bindings in memory.

---

## Diagnostic Data Sources

| Tool | What It Shows | How to Access |
|------|--------------|--------------|
| Power Automate Flow Runs | Step-by-step execution with inputs/outputs | make.powerautomate.com > Flow > Run History |
| Application Insights | Copilot Studio telemetry and connector traces | Azure Portal > App Insights resource |
| Entra Sign-in Logs | OAuth token requests, success/failure, error codes | Entra > Monitoring > Sign-in logs |
| Entra Audit Logs | App registration changes, secret rotations | Entra > Monitoring > Audit logs |
| Workday Login Activity | ISU login attempts, success/failure | Workday > View Login Activity |
| Workday Integration Events | API call logs, SOAP request/response | Workday > Integration Events |
| Workday API Client Activity | OAuth token grants, client usage | Workday > View API Client Activity |
| Copilot Studio Test Pane | End-to-end conversation testing | Copilot Studio > Test your agent |
| SAML Tracer | SAML assertions, claims, issuer details | Browser extension (Chrome/Edge) |

---

## Collecting Traces for Escalation

### HAR Trace

1. Open Chrome/Edge → navigate to Power Automate flow or Copilot Studio test pane
2. Open DevTools (F12) → Network tab → check 'Preserve log' → clear existing
3. Reproduce the failure
4. Right-click in Network tab → Save all as HAR with content

**Look for:** HTTP 401/403 to token/SOAP endpoints, HTML where JSON expected, redirect chains, missing Authorization headers.

> **Warning:** HAR files contain tokens, cookies, and potentially passwords. Sanitize before sharing.

### Power Automate Flow Run Details

1. make.powerautomate.com → open failing flow → Run History → select failed run
2. Expand each failed action — capture:

| Field | What to Capture |
|-------|----------------|
| Action Name | Name of the failed step |
| Status Code | HTTP status (401, 403, 500, etc.) |
| Request URL | Full URL being called |
| Request Headers | Authorization header (redact token) |
| Request/Response Body | SOAP envelope, OAuth params, error message |
| Duration | Timeout vs immediate rejection |

### SAML Assertion Capture

1. Install SAML Tracer browser extension → clear entries
2. Trigger the auth flow → look for SAML requests/responses
3. Verify: Issuer matches Workday config, NameID maps to valid login, Audience includes Workday SP URI, certificate matches, time window is valid.

### Postman Verification Tests

**Test 1 — OAuth Token Exchange:**
- POST `https://{host}/ccx/oauth2/{tenant}/token`
- Body: `grant_type=client_credentials&client_id={id}&client_secret={secret}`
- 200 = OAuth works (test SOAP next) | 401 = Configs 1,2,8 | 400 = Config 8 | Timeout = Config 11

**Test 2 — Basic Auth SOAP Call:**
- POST `https://{host}/ccx/service/{tenant}/{report_name}`
- Auth: Basic (ISU username + password) | Content-Type: application/xml
- 200 = ISU works (issue is PP-specific) | 401 = Config 4 | 403 = Configs 9,10,12

### Escalation Package Checklist

Before contacting Microsoft or Workday support, compile ALL of these:

| # | Item |
|---|------|
| 1 | HAR trace from browser session |
| 2 | Power Automate flow run details (screenshots + raw JSON) |
| 3 | SAML assertion capture (from SAML Tracer) |
| 4 | Postman test results (both OAuth and SOAP) |
| 5 | Workday connector extension version |
| 6 | Power Platform connector version |
| 7 | Power Platform environment ID |
| 8 | Entra tenant ID |
| 9 | Activity/Correlation ID from failed request |
| 10 | Config checklist results (which configs pass/fail) |
| 11 | Timestamp of failure (with timezone) |
| 12 | Power Platform region (e.g., US, EU, APAC) |

> A complete package with all 12 items typically reduces resolution time from weeks to days.

---

## Additional Considerations

### Multiple Workday Tenants

If your organization has multiple tenants (production, sandbox, implementation), verify ALL configurations for the specific tenant being used. A common mistake is testing in sandbox (works) and deploying to production (fails) because the production tenant has different ISU accounts, API Clients, or security policies.

### Connection Credential Caching

Power Platform caches connection credentials. After updating credentials, delete and recreate the connection reference to force fresh values. Coordinating with your team before deleting shared connection references.

### Third-Party IdP Federation (non-Okta)

The Okta section (Configs 13–17) principles apply to other IdPs (Ping, ADFS, etc.) — verify dual SAML trust, claim chains, and MFA/network policies.

---

## References

- [Workday REST API Documentation](https://doc.workday.com/)
- [Workday Community - Integration System Users](https://community.workday.com/)
- [Microsoft Power Platform Connectors - Workday](https://learn.microsoft.com/en-us/connectors/workday/)
- [Microsoft Entra App Registration](https://learn.microsoft.com/en-us/entra/identity-platform/)
- [Power Platform IP Ranges](https://learn.microsoft.com/en-us/power-platform/admin/online-requirements)
- [Okta SAML Configuration](https://help.okta.com/en-us/content/topics/apps/apps_app_integration_wizard_saml.htm)
- [SAML Tracer Browser Extension](https://chromewebstore.google.com/detail/saml-tracer/)
