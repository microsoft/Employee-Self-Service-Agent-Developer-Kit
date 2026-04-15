# Workday Step 1: Gather Info & Set Up MCP

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "BASE_URL = ..." or "TENANT = ..." in chat.

---

## 1.1 — Get the Workday URL

Use the `vscode_askQuestions` tool with ONE question:

```json
[
  {
    "header": "Workday URL",
    "question": "Paste the URL from your browser when you're logged into Workday (e.g. https://impl.workday.com/yourcompany/d/home.htmld)"
  }
]
```

**Parse the URL to extract tenant and SOAP base URL:**

The Workday web URL follows one of these patterns:
- `https://impl.workday.com/{tenant}/d/...` (implementation)
- `https://wd5.myworkday.com/{tenant}/d/...` (production)
- `https://{host}.workday.com/{tenant}/d/...` (other data centers)

Extract WD_TENANT from the first path segment after the domain.
Example: `https://impl.workday.com/microsoft_dpt6/d/home.htmld`
→ WD_TENANT = `microsoft_dpt6`

Derive the SOAP base URL from the host:
- `impl.workday.com` → `https://wd2-impl-services1.workday.com/ccx/service`
- `wd5.myworkday.com` → `https://wd5-services1.myworkday.com/ccx/service`
- `{dcN}.myworkday.com` → `https://{dcN}-services1.myworkday.com/ccx/service`

If the URL doesn't match any known pattern, fall back to asking:

```json
[
  {
    "header": "SOAP URL",
    "question": "I couldn't determine your Workday services URL from that link. What's the SOAP endpoint? (Ask your Workday admin — it looks like https://wd2-impl-services1.workday.com/ccx/service)"
  }
]
```

Save the derived values as WD_TENANT and WD_BASE_URL.

---

## 1.2 — Install MCP server dependencies

Run in the terminal (do not show this to the user):

```
pip install -r src/mcp/workday/requirements.txt
```

If pip fails, try `python -m pip install -r src/mcp/workday/requirements.txt`.

---

## 1.3 — Save config

Write `my/connect/workday/config.json`:

```json
{
  "baseUrl": "{WD_BASE_URL}",
  "tenant": "{WD_TENANT}",
  "status": "in-progress"
}
```

---

## 1.4 — Set up the Workday MCP server

Read `.vscode/mcp.json`. If it exists, parse it. If it doesn't exist,
start with an empty `{ "servers": {} }` object.

Add a `Workday` entry to the `servers` object. **Keep all existing
entries (like Dataverse, ServiceNow) intact.**

Also ensure the top-level `inputs` array contains the Workday input
definitions. If `inputs` doesn't exist yet, create it. If it exists,
append the Workday inputs (don't overwrite existing inputs).

Write the merged result back to `.vscode/mcp.json`. The Workday section
should look like this (merge with whatever is already there):

```json
{
  "inputs": [
    {
      "id": "workdayUser",
      "type": "promptString",
      "description": "Workday username (the one you use to sign in)",
      "password": false
    },
    {
      "id": "workdayPass",
      "type": "promptString",
      "description": "Workday password",
      "password": true
    }
  ],
  "servers": {
    "Workday": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "${workspaceFolder}/src/mcp/workday",
      "env": {
        "WORKDAY_BASE_URL": "{WD_BASE_URL}",
        "WORKDAY_TENANT": "{WD_TENANT}",
        "WORKDAY_USERNAME": "${input:workdayUser}@{WD_TENANT}",
        "WORKDAY_PASSWORD": "${input:workdayPass}"
      }
    }
  }
}
```

Replace `{WD_BASE_URL}` and `{WD_TENANT}` with the actual values from
step 1.1. These are not secrets so they go directly in the file.

The `WORKDAY_USERNAME` env var appends `@{WD_TENANT}` automatically so
the user only enters their normal username. The client derives the RaaS
username (without @tenant) and reuses the same password internally.

---

## 1.5 — Start the MCP server

**Message:**

Got it — your Workday tenant is **{WD_TENANT}**.

Now let's start the Workday connector:

1. Press **Ctrl+Shift+P** → type **MCP: List Servers** → select it
2. Find **Workday** in the list → click the **Start** button
3. VS Code will prompt for your **Workday username** and **password**
   at the top of the screen — just enter the same credentials you use
   to sign into Workday

Your credentials are only held in memory and never saved to disk. We'll
create dedicated service accounts later so you won't need yours long-term.

Type **done** when the server shows as Running.

**End message.**

Wait for the user.

---

## 1.6 — Verify connectivity

Use the Workday MCP `test_connection` tool.

**If the call succeeds** (returns worker data, not an error):

Update `my/connect/workday/tasks.md` — change step 1 from
`- [ ]` to `- [x]`.

**Message:**

✅ Environment configured — connected to Workday tenant `{WD_TENANT}`.

| # | Task | Status |
|---|------|--------|
| 1 | Environment configured | ✅ |
| 2 | Admin setup complete | ⬜ |
| 3 | Connection verified | ⬜ |

**End message.**

Now read `src/skills/connect/workday/step2.md` and follow it.

---

## 1.7 — Connection failed

**If the test_connection call returns an error:**

Check the error message and provide specific guidance:

**If "invalid username or password":**

**Message:**

Authentication failed. A few things to check:

- **Is your account a Workday admin?** The setup needs an account with
  administrative permissions. A regular employee account won't work.
- **Is the password correct?** Try signing into Workday in your browser
  to confirm.
- **Special characters in password?** Characters like `&`, `%`, `#` can
  cause issues. If your password contains these, try resetting it to one
  with only letters and numbers temporarily.

To retry: press **Ctrl+Shift+P** → **MCP: List Servers** → stop and
restart the **Workday** server. To change credentials, I'll need to
update the config file first.

Type **retry** when ready, or **back** to re-enter your info.

**End message.**

**If "not authorized":**

**Message:**

Good news — your credentials work! The account just doesn't have
permission for the test I ran, which is fine. We'll set up the right
permissions in the next step.

**End message.**

Update `my/connect/workday/tasks.md` — change step 1 from
`- [ ]` to `- [x]`.

Proceed to step2.md. (Auth works; permissions will be configured there.)

**If any other error (connection refused, timeout, etc.):**

**Message:**

I couldn't reach Workday. A few things to check:

- **Are you connected to your corporate network/VPN?** Workday may
  require it.
- **Is the Workday URL correct?** You gave me `{WD_BASE_URL}` — if
  that doesn't look right, type **back** to start over.

Type **retry** to test again, or **back** to re-enter your Workday URL.

**End message.**

Wait for the user. If they say retry, go back to 1.6. If they say back,
go back to 1.1.
