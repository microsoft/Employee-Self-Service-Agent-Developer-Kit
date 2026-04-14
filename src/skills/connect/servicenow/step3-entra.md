# ServiceNow Step 3: Install Extension Pack (Entra ID)

**This file is ONLY for Entra ID authentication. Do not use for OAuth2 or Basic.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "INSTANCE_NAME = ..." or "PACK_NAME = ..." in chat.

Read `my/connect/servicenow/config.json` to restore INSTANCE_NAME,
SNOW_USAGE (from `usage`), and APP_CLIENT_ID (from `entra.appClientId`).

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

**Message:**

Time to install the ServiceNow integration in Copilot Studio.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Open your ESS agent
3. Go to **Settings** → **Customize**
4. Find **{PACK_NAME}** and click **Install**
5. When it asks for connection details, enter:

   | Field | Value |
   |-------|-------|
   | **Authentication Type** | Microsoft Entra ID User Login |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Resource URI** | `{APP_CLIENT_ID}` |

6. Sign in with your Microsoft account when prompted
7. If it asks for a **Microsoft Dataverse** connection, sign in with your
   Microsoft account

> **If the Sign In button hangs** after authenticating: the connection was
> likely created but Copilot Studio didn't detect it. Open
> [Power Automate](https://make.powerautomate.com) → **Connections** and
> check if ServiceNow shows as **Connected**. If it does, go back to
> Copilot Studio, close the install dialog, refresh the page, and click
> **Install** again — it should pick up the existing connection.

Type **done** when the install finishes, or **help** if something went wrong.

**End message.**

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
- **"Resource not found" or "Invalid resource"**: Verify the Resource URI
  matches the App (Client) ID from Entra. It should be:
  `{APP_CLIENT_ID}`
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

Update `my/connect/servicenow/tasks.md` — change step 3 from
`- [ ]` to `- [x]`.

Update `my/connect/servicenow/config.json` — set the status of each
installed pack from `"pending"` to `"installed"` in the `packs` object.

**Message:**

✅ Extension installed.

| # | Task | Status |
|---|------|--------|
| 1 | Instance configured | ✅ |
| 2 | Connection secured | ✅ |
| 3 | Extension installed | ✅ |
| 4 | Connection verified | ⬜ |

One more step — let's verify everything is working. Type **go** to continue.

**End message.**

Wait for the user. Then read `src/skills/connect/servicenow/step4.md`
and follow it.
