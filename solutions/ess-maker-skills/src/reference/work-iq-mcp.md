# Work IQ MCP — people & directory lookup (developer tool)

**Work IQ is an authoring-time developer tool for the maker, not a runtime part of
the ESS agent.** It is an MCP server that runs on *your* machine and answers to
*your* Microsoft Entra sign-in while you build. It is **never** a connection
reference, extension pack, cloud flow, or any other runtime dependency of the ESS
agent you are configuring, and it is never deployed to Copilot Studio.

Contrast with the `/connect` family:

| | `/connect servicenow \| workday` | **Work IQ MCP** |
|---|---|---|
| Whose capability | The **deployed ESS agent** (runtime) | The **maker's Copilot** (authoring time) |
| Runtime footprint | Power Platform connector + extension pack + Dataverse connection reference the agent calls | **None** — lives only in `.vscode/mcp.json` |
| Who authenticates | The **employee** at runtime (Entra SSO / ISU / OAuth) | **You, the maker**, interactively |
| Deployed to Copilot Studio? | Yes | **No** |

## What it is

Work IQ ([`@microsoft/workiq`](https://github.com/microsoft/work-iq)) is Microsoft's
MCP server for Microsoft 365 intelligence. It exposes a small, fixed set of generic
tools that operate on **relative resource paths mapping to Microsoft Graph**, so an
agent can read people, mail, meetings, files, and Teams data, and invoke Microsoft
365 Copilot — all through one MCP endpoint. See the
[Work IQ MCP overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview)
and the
[tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference).

**Tools (10 total):** `fetch`, `create_entity`, `update_entity`, `delete_entity`,
`do_action`, `call_function`, `ask`, `list_agents`, `get_schema`, `search_paths`.
The tool surface is fixed — new capabilities are new *paths*, not new tools.

## Enable it

Work IQ needs **Node.js** (for `npx`) and a Microsoft Entra sign-in. It requires no
credentials in config — the first call opens an interactive consent/sign-in in the
browser. First-time use also requires accepting the End User License Agreement (the
CLI exposes `workiq accept-eula` and `workiq auth login`; run as an MCP server it
prompts on the first tool call). Some tenants require a tenant administrator to grant
admin consent on first use; see the
[Tenant Administrator Enablement Guide](https://github.com/microsoft/work-iq/blob/main/ADMIN-INSTRUCTIONS.md).

**New setups get this automatically.** `/setup` writes the `workiq` server into
`.vscode/mcp.json` alongside `Dataverse`. The entry is fully static (no tenant values
or secrets), which is why it can ship with the kit even though `.vscode/mcp.json`
itself is machine-local and git-ignored.

If you set up **before** Work IQ was added, add it manually (merge with the existing
`servers`; keep other entries like `Dataverse` intact):

```json
{
  "servers": {
    "workiq": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@microsoft/workiq@latest", "mcp"]
    }
  }
}
```

Reload the VS Code window (or restart the MCP servers) so Copilot picks it up.

## Get a person's Entra (AAD) object id

The `fetch` tool takes an `entityUrls` array of Graph-relative paths and returns
`results[].data` (the Graph JSON) with a `statusCode`. A user's `id` **is** their
Microsoft Entra object id (the value formerly called the AAD object id).

- **By UPN / email (most reliable):**
  ```
  fetch /users/jane@contoso.com
  ```
  → `results[0].data.id` is Jane's Entra object id.

- **By fuzzy name (relevance-ranked people):**
  ```
  fetch /me/people?$search=Jane Doe
  ```
  → each `value[].id` is a person's directory id; pick the intended match.

- **By exact display-name filter:**
  ```
  fetch /users?$filter=startswith(displayName,'Jane')
  ```

In practice you just ask Copilot in natural language — for example *"what's the Entra
object id for jane@contoso.com?"* — and it calls `fetch` under the hood.

## Why it's a useful ESS addition

While authoring, you frequently need a real person's Entra object id — seeding a test
employee, wiring an approver, checking a manager relationship, or populating eval
fixtures. Work IQ resolves people (and other M365 context) on demand from your own
signed-in session, without hand-copying object ids out of the Entra portal. It is
intentionally decoupled from the ESS agent's runtime: enabling or removing it changes
nothing about the deployed agent.

## Boundaries

- **Authoring-time only.** Do not reference Work IQ, its tools, or any id it returns
  as a runtime dependency of the ESS agent. If the agent needs the *signed-in
  employee's* identity at runtime, use the ESS user-context topics / `System.User.*`,
  not Work IQ.
- **Acts as you.** Every call runs under the maker's delegated permissions and returns
  data in the maker's security context — treat results as your own view of M365.
- **Public preview.** Work IQ is in public preview; tools and permissions may change.
