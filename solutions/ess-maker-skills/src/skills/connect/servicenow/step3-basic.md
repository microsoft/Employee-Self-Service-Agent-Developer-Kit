# ServiceNow Step 3: Install Extension Pack (Basic Auth)

**This file is ONLY for Basic authentication. Do not use for OAuth2 or Entra.**

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "INSTANCE_NAME = ..." or "PACK_NAME = ..." in chat.

Read `.local/connect/servicenow/config.json` to restore INSTANCE_NAME and
SNOW_USAGE (from `usage`).

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
   | **Authentication Type** | Basic |
   | **Instance Name** | `{INSTANCE_NAME}` |
   | **Username** | Your ServiceNow admin username |
   | **Password** | Your ServiceNow admin password |

6. If it asks for a **Microsoft Dataverse** connection, sign in with your
   Microsoft account
7. Click **Allow** if ServiceNow asks for consent

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
- **Authentication error**: Double-check that your username and password
  are correct. The Instance Name should be just `{INSTANCE_NAME}`
  (not the full URL).

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
