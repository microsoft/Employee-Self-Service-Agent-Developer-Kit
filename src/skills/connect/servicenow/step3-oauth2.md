# ServiceNow Step 3: Install Extension Pack (OAuth2)

**This file is ONLY for OAuth2 authentication. Do not use for Basic or Entra.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "CLIENT_ID = ..." or "PACK_NAME = ..." in chat.

Read `my/connect/servicenow/config.json` to restore INSTANCE_NAME,
SNOW_USAGE (from `usage`), CLIENT_ID (from `oauth.clientId`).

The CLIENT_SECRET should still be in memory from step 2. If the agent
restarted since step 2, the user must re-enter the secret — show:
"I need the Client Secret from when we set up OAuth. You can find it in
ServiceNow → System OAuth → Application Registry → ESS Copilot → click
the lock icon next to Client Secret."

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
   | **Authentication Type** | OAuth2 |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Client ID** | `{CLIENT_ID}` |
   | **Client Secret** | `{CLIENT_SECRET}` |

6. Sign in with your ServiceNow admin account when prompted
7. Click **Allow** when asked for consent
8. If it asks for a **Microsoft Dataverse** connection, sign in with your
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

## 3.3 — Handle redirect URL error

If the user mentions "Invalid redirect_uri", "redirect" error, or a URL
mismatch:

**Message:**

That's a redirect URL mismatch — easy fix. Look at the **browser address
bar** on the error page and find `redirect_uri=` in the URL.

Copy the full URL after `redirect_uri=` (up to the next `&`), decode it
(replace `%3a` with `:` and `%2f` with `/`), and paste it here.

**End message.**

Wait for the user to paste the URL. Save it as CORRECT_REDIRECT.

Call the ServiceNow MCP `update_record` tool to fix the redirect URL:

- `table`: `"oauth_entity"`
- `sys_id`: read from `my/connect/servicenow/config.json` at `oauth.sysId`
- `data`: `"{\"redirect_url\": \"{CORRECT_REDIRECT}\"}"`

Update `my/connect/servicenow/config.json` — set `oauth.redirectUrl` to
CORRECT_REDIRECT.

**Message:**

✅ Redirect URL updated. Go back to Copilot Studio and retry the install —
it should work now.

**End message.**

Wait for the user to complete the install.

---

## 3.4 — Handle other help requests

If the user says "help" with a non-redirect issue:

**Message:**

Here are some things to check:

- **Can't find the extension pack**: Make sure you're in the right agent.
  Go to **Settings** → **Customize** and look for "ServiceNow".
- **Sign In button hangs**: Open
  [Power Automate](https://make.powerautomate.com) → **Connections** — if
  ServiceNow shows as **Connected**, go back to Copilot Studio, cancel,
  refresh, and click **Install** again.
- **Authentication error**: Double-check Client ID and Client Secret match
  what was generated. The Instance Name should be just `{INSTANCE_NAME}`
  (not the full URL).

Type **retry** once you've fixed the issue, or describe what you're seeing
and I'll help troubleshoot.

**End message.**

Wait for the user.

---

## 3.5 — Handle "done"

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

Now I'll pull your updated agent from Dataverse to bring in all the new
ServiceNow topics, flows, and template configurations. Type **go** to
continue.

**End message.**

Wait for the user. Then read `src/skills/connect/servicenow/step4.md`
and follow it.
