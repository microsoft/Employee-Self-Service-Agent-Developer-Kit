# ServiceNow Step 3: Configure Graph Connector in M365 Admin Center

**This file walks the user through creating the ServiceNow Knowledge
connection in the Microsoft 365 Admin Center and adding it as a
knowledge source in Copilot Studio.** There is no API for these steps —
the user must complete them in the browser.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

**Do NOT show internal variable names or assignments to the user.**

Read `.local/connect/servicenow/config.json` for INSTANCE_NAME.

---

## 3.1 — Walk through M365 Admin Center setup

**Message:**

Now let's create the knowledge connection in the Microsoft 365 Admin
Center.

1. Go to the [M365 Admin Center](https://admin.microsoft.com/)
2. In the left pane, navigate to **Copilot** → **Connectors**
3. Go to the **Connectors** tab → **Gallery**
4. Find **ServiceNow Knowledge** and click it
5. Configure the connection:

   | Setting | Value |
   |---------|-------|
   | **Display name** | ServiceNow Knowledge (or your preferred name) |
   | **User criteria** | Simple (default) |
   | **ServiceNow URL** | `https://{INSTANCE_NAME}.service-now.com` |
   | **Authentication type** | Federated Credential (Recommended) |

6. Check the **Notice** checkbox
7. Click **Create**

The connection will start indexing ServiceNow knowledge articles. Wait
for the connection status to show **Ready** — this can take a few
minutes for the initial crawl.

Type **done** when the connection is created and shows as Ready, or
**help** if something went wrong.

**End message.**

Wait for the user.

---

## 3.2 — Handle help requests

If the user says "help" or describes an error:

**Common errors and fixes:**

- **"Connection setup details are not valid"**: The OIDC provider
  configuration has wrong values. Check that `user_claim` is `oid` and
  `user_field` is `user_name` (not `user_id`). Also verify the OIDC
  metadata URL uses the v2.0 endpoint.

- **"Missing access to certain tables"**: The ACL setup didn't complete
  successfully. The integration user needs explicit READ ACLs on the
  required tables. Try re-running the ACL setup or running the scripts
  from https://github.com/microsoft/copilot-servicenow-connector-setup-scripts
  manually in ServiceNow Scripts - Background.

- **"Sample data could not be fetched"**: The integration user is
  missing roles. Verify all 6 roles are assigned: `catalog_admin`,
  `user_criteria_admin`, `user_admin`, `knowledge`, `knowledge_admin`,
  `knowledge_manager`.

- **"Invalid connection credentials"**: Check that the OIDC entity's
  `scope_restriction_status` is `unrestricted`. Do NOT change it to
  `restricted`.

- **Can't find ServiceNow Knowledge in the Gallery**: Make sure you're
  in the [M365 Admin Center](https://admin.microsoft.com/), not the
  Power Platform admin center. Navigate to **Copilot** → **Connectors**
  → **Gallery**.

**Message:**

Here are some things to check:

{Include the relevant troubleshooting item from the list above based
on what the user described.}

For detailed troubleshooting, see the
[ServiceNow Knowledge connector troubleshooting guide](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/servicenow-knowledge-troubleshooting).

Type **retry** once you've fixed the issue, or describe what you're
seeing and I'll help further.

**End message.**

Wait for the user.

---

## 3.3 — Add as knowledge source in Copilot Studio

When the user says "done":

**Message:**

Great — the Knowledge connector is set up. Now let's add it as a
knowledge source in your ESS agent.

1. Open [Copilot Studio](https://copilotstudio.microsoft.com/)
2. Open your ESS agent
3. Go to **Knowledge** in the top navigation
4. Click **+ Add Knowledge**
5. Select **ServiceNow** from the list
6. Select the connection you just created (it should appear under
   **Created by your admin**)
7. Click **Add**

Type **done** when the knowledge source is added.

**End message.**

Wait for the user.

---

## 3.4 — Complete

Update `.local/connect/servicenow/config.json` — set
`"graph"."status"` to `"connected"`.

**Message:**

✅ ServiceNow Knowledge search is configured!

Your agent can now search ServiceNow knowledge base articles to answer
employee questions. The connector will sync articles automatically
(every 15 minutes for changes, daily for full re-index).

**End message.**

Check `.local/connect/servicenow/config.json` for `connectorType`. If it
is `both` AND the Power Platform connector was already set up before
this flow, stop here — everything is done.

If the user came here directly (SNOW_CONNECTOR was `graph` only), also
show:

**Message:**

| Command | What it does |
|---------|-------------|
| `/create` | Create a new topic |
| `/scan` | Check your agent for errors |
| `/menu` | See all available commands |

**End message.**

Stop here.
