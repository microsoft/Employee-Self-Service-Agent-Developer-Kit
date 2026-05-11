# ServiceNow Step 3: Install Extension Pack (Certificate Auth)

**This file is ONLY for Certificate (service-to-service) authentication.
Do not use for Entra ID User Login, OAuth2, or Basic.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "INSTANCE_NAME = ..." or "PACK_NAME = ..." in chat.

Read `.local/connect/servicenow/config.json` to restore INSTANCE_NAME,
SNOW_USAGE (from `usage`), TENANT_ID (from `certificate.tenantId`),
APP_A_CLIENT_ID (from `certificate.appAClientId`),
APP_B_CLIENT_ID (from `certificate.appBClientId`), and
CERT_PFX_PATH (from `certificate.certPfxPath`).

**CERT_PASSWORD is not stored on disk.** If you already have it from
the same session that ran step2-certificate.md, use that value.
Otherwise (this is a resumed session), prompt for it now via
`vscode_askQuestions`:

```json
[
  {
    "header": "PFX password",
    "question": "What's the password for `{CERT_PFX_PATH}`? It was shown to you when the certificate was generated and is not saved by this kit."
  }
]
```

Save the answer as CERT_PASSWORD (session memory only — do not write
to `.local/connect/servicenow/config.json`).

---

## 3.1 — Determine which packs to install

Based on SNOW_USAGE:
- `itsm` → install ITSM only
- `hrsd` → install HRSD only
- `both` → install ITSM first, then HRSD

Set CURRENT_PACK to the first pack to install.

If CURRENT_PACK is `itsm`, set PACK_NAME to `ServiceNow IT`.
If CURRENT_PACK is `hrsd`, set PACK_NAME to `ServiceNow HR`.

---

## 3.2 — Walk through extension pack install

### If CURRENT_PACK is `hrsd`:

**Message:**

Time to install the ServiceNow integration in Copilot Studio.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Open your ESS agent
3. Go to **Settings** → **Customize**
4. Find **{PACK_NAME}** and click **Install**
5. When it asks for connection details, enter:

   | Field | Value |
   |-------|-------|
   | **Authentication Type** | Microsoft Entra ID OAuth using Certificate |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Tenant ID** | `{TENANT_ID}` |
   | **Client ID** | `{APP_B_CLIENT_ID}` |
   | **Resource URI** | `{APP_A_CLIENT_ID}` |
   | **Client Secret** | Upload the `.pfx` file (I'll open the folder) |
   | **Certificate password** | `{CERT_PASSWORD}` |

6. If it asks for a **Microsoft Dataverse** connection, sign in with your
   Microsoft account

I've opened File Explorer with the certificate file selected — drag it
into the upload dialog or use **Browse** to navigate to it.

> **If the Sign In button hangs** after authenticating: the connection was
> likely created but Copilot Studio didn't detect it. Open
> [Power Automate](https://make.powerautomate.com) → **Connections** and
> check if ServiceNow shows as **Connected**. If it does, go back to
> Copilot Studio, close the install dialog, refresh the page, and click
> **Install** again — it should pick up the existing connection.

Type **done** when the install finishes, or **help** if something went wrong.

**End message.**

After showing the message, run in the terminal (do not show to the user):

```powershell
explorer.exe /select,"{CERT_PFX_PATH}"
```

Replace `{CERT_PFX_PATH}` with the actual path. This opens File Explorer
with the .pfx file pre-selected so the user can drag it into the upload
dialog.

Wait for the user.

### If CURRENT_PACK is `itsm`:

> **Note for maintainers:** The ITSM extension pack uses different field
> labels in Copilot Studio than the HRSD pack. The labels below
> ("Use Oauth2", "Tenant Type", "Client Id", "Client certificate secret")
> are what the ITSM install dialog actually shows. Do not "normalize"
> them to match the HRSD labels — they are intentionally different.

**Message:**

Time to install the ServiceNow integration in Copilot Studio.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Open your ESS agent
3. Go to **Settings** → **Customize**
4. Find **{PACK_NAME}** and click **Install**
5. When it asks for connection details, enter:

   | Field | Value |
   |-------|-------|
   | **Authentication Type** | Use Oauth2 |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Tenant Type** | `{TENANT_ID}` |
   | **Client Id** | `{APP_B_CLIENT_ID}` |
   | **Resource URI** | `{APP_A_CLIENT_ID}` |
   | **Client certificate secret** | Upload the `.pfx` file (I'll open the folder) |
   | **Certificate password** | `{CERT_PASSWORD}` |

6. If it asks for a **Microsoft Dataverse** connection, sign in with your
   Microsoft account

I've opened File Explorer with the certificate file selected — drag it
into the upload dialog or use **Browse** to navigate to it.

> **If the Sign In button hangs** after authenticating: the connection was
> likely created but Copilot Studio didn't detect it. Open
> [Power Automate](https://make.powerautomate.com) → **Connections** and
> check if ServiceNow shows as **Connected**. If it does, go back to
> Copilot Studio, close the install dialog, refresh the page, and click
> **Install** again — it should pick up the existing connection.

Type **done** when the install finishes, or **help** if something went wrong.

**End message.**

After showing the message, run in the terminal (do not show to the user):

```powershell
explorer.exe /select,"{CERT_PFX_PATH}"
```

Replace `{CERT_PFX_PATH}` with the actual path. This opens File Explorer
with the .pfx file pre-selected so the user can drag it into the upload
dialog.

Wait for the user.

---

## 3.3 — Handle help requests

If the user says "help":

**Message:**

Here are some things to check:

- **Can't find the extension pack**: Make sure you're in the right agent.
  Go to **Settings** → **Customize** and look for "ServiceNow".
- **Sign In button hangs**: Open
  [Power Automate](https://make.powerautomate.com) → **Connections** — if
  ServiceNow shows as **Connected**, go back to Copilot Studio, cancel,
  refresh, and click **Install** again.
- **"Resource not found" or "Invalid resource"**: The Resource URI must
  be the Application (client) ID from the first app registration
  (the OIDC resource app). It should be:
  `{APP_A_CLIENT_ID}`
- **"Invalid client" error**: The Client ID must be the Application
  (client) ID from the second app registration (the service account
  app). It should be:
  `{APP_B_CLIENT_ID}`
- **Certificate error**: Verify you browsed to the correct `.pfx` file
  and that the password matches. The file should be at:
  `{CERT_PFX_PATH}`
- **"AADSTS65001" consent error**: An admin in your tenant needs to grant
  consent. Open https://entra.microsoft.com → **App registrations** →
  find your app → **API permissions** → **Grant admin consent**.

Type **retry** once you've fixed the issue, or describe what you're seeing
and I'll help troubleshoot.

**End message.**

Wait for the user.

---

## 3.4 — Handle "done"

**If SNOW_USAGE is `both` AND this was the first pack (ITSM):**

Set CURRENT_PACK to `hrsd` and PACK_NAME to `ServiceNow HR`.

**Message:**

Great — IT tickets are connected. Now let's add HR cases too.

**End message.**

Go back to section 3.2 with CURRENT_PACK set to `hrsd`.

**Otherwise (single pack, or second pack just finished):**

Update `.local/connect/servicenow/tasks.md` — change step 3 from
`- [ ]` to `- [x]`.

Update `.local/connect/servicenow/config.json` — set the status of each
installed pack from `"pending"` to `"installed"` in the `packs` object.

**Message:**

✅ Extension installed.

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ✅ |
| 3 | Extension installed | ✅ |
| 4 | Connection verified | ⬜ |

Now I'll pull your updated agent from Dataverse to bring in all the new
ServiceNow topics, flows, and template configurations. Type **go** to
continue.

**End message.**

Wait for the user. Then read `src/skills/connect/servicenow/step4.md`
and follow it.
