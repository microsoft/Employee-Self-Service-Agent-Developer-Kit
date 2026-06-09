# Azure Login (Shared)

This file is integration-agnostic. It logs the user into Azure CLI
against a specific tenant using the device code flow. It is called
by integration-specific step files (e.g., `servicenow/step2-entra.md`).

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.** Never
display text like "TENANT_ID = ..." in chat.

**Inputs from the calling file:**
- None required. This file collects everything it needs.

**Outputs to the calling file:**
- TENANT_ID — the verified Entra tenant ID

---

## A.1 — Check Azure CLI is installed

Run in the terminal (do not show this command to the user):

```
az version -o json
```

**If the command succeeds** (exit code 0): proceed to A.2.

**If the command fails** (exit code non-zero, or `az` not found):

**Message:**

The Azure CLI is required for Entra ID setup but isn't installed on
your machine.

1. Install it from https://aka.ms/installazurecli
2. Restart VS Code after installation
3. Then come back and we'll pick up where we left off

**End message.**

Stop here. Do not proceed.

---

## A.2 — Ask for tenant ID

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Tenant ID",
    "question": "What's your Microsoft Entra tenant ID? Find it in the Azure portal → Microsoft Entra ID → Overview → Tenant ID."
  }
]
```

Save the answer as TENANT_ID. Validate it looks like a GUID
(8-4-4-4-12 hex format). If not, ask again.

---

## A.3 — Check if already logged into the correct tenant

Run in the terminal (do not show this command to the user):

```
az account show --query tenantId -o tsv
```

**If the command succeeds AND the output matches TENANT_ID**
(case-insensitive): skip A.4 entirely. Go straight to A.5.

**If the command fails OR the tenant doesn't match**: proceed to A.4.

---

## A.4 — Sign in with device code

**Track attempts.** Read `.local/.azure-login-attempts.json` if it exists.
If it does not exist, treat the current attempt count as `0`. Increment
the counter and write it back:

```json
{ "tenantId": "{TENANT_ID}", "attempts": <new count> }
```

If the attempt count reaches `3`, do NOT issue another device code.
Stop and show:

**Message:**

Three sign-in attempts have failed for tenant `{TENANT_ID}`. Common causes:

- The account does not have **Application Administrator** or
  **Global Administrator** in this tenant
- A Conditional Access policy is blocking the sign-in
- The wrong tenant ID was entered (double-check it in the Azure portal)

Talk to your tenant admin and then run `/connect` again to retry.

**End message.**

Delete `.local/.azure-login-attempts.json` so the next `/connect` run
starts a fresh count, then stop here. Do not proceed.

Otherwise, run this command in the terminal using `run_in_terminal`
with **`mode=async`**. You MUST use async mode — sync mode will block
forever waiting for the user to authenticate in the browser.

Use `--allow-no-subscriptions` to prevent an interactive subscription
selection prompt that would block the terminal:

```
az login --tenant {TENANT_ID} --use-device-code --allow-no-subscriptions
```

After the async call returns, read the terminal output (use
`get_terminal_output` with the returned terminal ID). The output will
contain a line like:

```
To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code E4YVMPKHB to authenticate.
```

Extract the URL and the code from the terminal output. Use this regex
pattern to find them:

```
open the page (https://\S+) and enter the code (\S+)
```

If the terminal output does not yet contain the URL and code, call
`get_terminal_output` again with the same terminal ID. The output
appears within a few seconds.

Once you have the URL and code, show them to the user **in chat** (NOT
in the terminal). The user must never need to look at the terminal.

**Message:**

Sign in to Azure to set up the Entra ID connection.

1. Open {URL}
2. Enter code **{CODE}**
3. Sign in with an account that has **Application Administrator** or
   **Global Administrator** role in your tenant

Type **done** when you've signed in.

**End message.**

Wait for the user.

---

## A.5 — Verify tenant

Run in the terminal:

```
az account show --query tenantId -o tsv
```

Compare the output to TENANT_ID (case-insensitive).

**If they match**: Azure login is complete. Delete
`.local/.azure-login-attempts.json` (success — clear the counter). Return
TENANT_ID to the calling file.

**If they don't match**:

**Message:**

You're signed into tenant `{actual_tenant_id}` but we expected
`{TENANT_ID}`. This can happen if you signed in with the wrong account.

Let's try again — I'll sign you out first.

**End message.**

Run:

```
az logout
```

Go back to A.4 and retry.

**If `az account show` fails** (not logged in):

Read `.local/.azure-login-attempts.json` to determine the current attempt
count. If `attempts < 2`:

**Message:**

The sign-in didn't complete. Let's try again.

**End message.**

Go back to A.4 and retry.

If `attempts == 2` (the second device-code attempt failed), do NOT
issue a third device code. Fall back to the manual flow:

**Message:**

Having trouble with the device-code sign-in. Let's try it manually:

1. Open a terminal
2. Run: `az login --tenant {TENANT_ID} --allow-no-subscriptions`
3. Complete the sign-in in your browser
4. Then come back here and type **done**

**End message.**

**Bump the counter before waiting on the user.** Write
`.local/.azure-login-attempts.json`:

```
{ "tenantId": "{TENANT_ID}", "attempts": 3 }
```

This is the cap. The manual fallback gets exactly one chance; if it
also fails we stop instead of looping. (Without this bump, the next
A.5 iteration re-reads `attempts == 2` and routes back into the manual
flow forever.)

Wait for the user. Once they reply **done**, return to the top of A.5
to verify (NOT A.4 - A.4 would reissue a fresh device code and
overwrite the manual sign-in).

If A.5 still fails on this iteration, `attempts == 3` and the
"three failed attempts" branch fires:

**Message:**

Three sign-in attempts have failed for tenant `{TENANT_ID}`,
including the manual fallback. Common causes:

- The account doesn't exist in this tenant (Guest vs Member, MSA vs work)
- Conditional Access policy blocks command-line sign-in
- The tenant requires a managed device

Talk to your tenant admin and try `/connect` again once resolved.

**End message.**

Delete `.local/.azure-login-attempts.json` so the next `/connect` run
starts clean. Stop. Do NOT route back into A.4 or the manual flow.
