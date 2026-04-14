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

## A.3 — Sign in with device code

Run in the terminal using **async mode** (do NOT use sync mode — it
will block waiting for the user to authenticate in the browser):

```
az login --tenant {TENANT_ID} --use-device-code
```

Read the terminal output. It will contain a line like:

```
To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code E4YVMPKHB to authenticate.
```

Extract the URL and the code from the terminal output. Use this regex
pattern to find them:

```
open the page (https://\S+) and enter the code (\S+)
```

If the terminal output does not yet contain the URL and code, use
`get_terminal_output` to check again. The output appears within a
few seconds.

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

## A.4 — Verify tenant

Run in the terminal:

```
az account show --query tenantId -o tsv
```

Compare the output to TENANT_ID (case-insensitive).

**If they match**: Azure login is complete. Return TENANT_ID to the
calling file.

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

Go back to A.3 and retry.

**If `az account show` fails** (not logged in):

**Message:**

The sign-in didn't complete. Let's try again.

**End message.**

Go back to A.3 and retry. If this is the second failure, stop and show:

**Message:**

Having trouble signing in. You can try manually:

1. Open a terminal
2. Run: `az login --tenant {TENANT_ID}`
3. Complete the sign-in in your browser
4. Then come back here and type **done**

**End message.**

Wait for the user, then go to A.4 to verify.
