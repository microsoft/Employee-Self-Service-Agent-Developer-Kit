# WeveNova MCP server (`weve-plan`)

An in-repo [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes live **WeveNova** AgentConfiguration *project*, *plan*, *task*, and
*role-assignment* operations as MCP tools. It lets the ESS Maker Kit **planner**
persist and query a rollout plan directly in WeveNova instead of a local
`plan.json`.

This is the repo-native Python/[FastMCP](https://github.com/modelcontextprotocol/python-sdk)
port of the standalone `weveOpenMcp` reference server. Behaviour is identical;
only the runtime changed (Node → Python) so the server can live and be tested
alongside the kit's other MCP servers (`adk`, `workday`, `servicenow`).

## Layout

| File | Purpose |
| --- | --- |
| `core.py` | All WeveNova logic: URL building, OData encoding, token/identity resolution, the user cache, lifecycle rules, and the `call_wevenova` tool dispatcher. **No `mcp` dependency** — pure stdlib, so it is unit-testable without the SDK installed. |
| `server.py` | Thin FastMCP shell. One `@mcp.tool()` wrapper per WeveNova tool; each delegates to `core.call_wevenova`. Owns the transport / entry point. |
| `tests/test_core.py` | `unittest` suite driving `core` with a fake upstream sender + temp token dir (no network, no `mcp`). |
| `data/user-cache.example.json` | Example demo-user directory for `find_users_by_name`. Copy to `data/user-cache.json` and edit. |
| `tokens/` · `logs/` · `data/user-cache.json` | Per-environment secrets / runtime state. **Gitignored — never commit.** |

## Install & run

```powershell
# from this directory
python -m pip install -r requirements.txt

# Streamable HTTP (default) — serves MCP at http://127.0.0.1:8081/mcp
python server.py

# stdio transport (MCP CLI / local inspector)
python server.py --transport stdio

# override bind address / port
python server.py --host 0.0.0.0 --port 8081
```

Transport, host, and port also read `WEVE_MCP_TRANSPORT`, `WEVE_MCP_HOST`, and
`WEVE_MCP_PORT` (or `PORT`).

### Point the planner at it

The planner is a generic MCP Streamable-HTTP client that looks up the server
named **`weve-plan`** in `.vscode/mcp.json` (gitignored, per-environment):

```jsonc
{
  "servers": {
    "weve-plan": {
      "type": "http",
      "url": "http://127.0.0.1:8081/mcp"
    }
  }
}
```

Then run the planner as usual; it will discover the tools and forward `userName`
/ `aadId` on every call.

## Authentication & identity

Every tool accepts optional **`userName`** and **`aadId`**:

- `userName` selects the ******: the first non-comment,
  non-empty line of `tokens/<userName>.txt` becomes the `Authorization` header
  (a `Bearer ` prefix is added if absent). Defaults to `default` →
  `tokens/default.txt`.
- Supply `userName` **and** `aadId` together once and the server associates that
  AAD identity with the token profile; later calls may pass either. An `aadId`
  alone is only valid after its profile has been learned.

Create token files yourself (they are gitignored):

```
tokens/
  default.txt      # Bearer eyJ0eXAiOiJKV1Q...   (or just the raw token)
  alice.txt
```

`find_users_by_name` is served entirely from `data/user-cache.json` (no upstream
call). Copy `data/user-cache.example.json` to `data/user-cache.json` and fill in
your demo users. Each entry: `{ aadId, displayName, alias?, emailAddress?,
tenantId?, tokenProfile? }`. A `tokenProfile` links an AAD id to a `tokens/*.txt`
file so callers can pass `aadId` alone after the first paired call.

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `WEVE_PROJECTS_URL` | `https://localhost:444/weveb2/api/beta/me/AgentConfigurationProjects` | OData root for projects/plans/tasks. |
| `WEVE_TENANTS_URL` | `https://localhost:444/weveb2/api/beta/tenants` | OData root for tenant-sharded role assignments. |
| `WEVE_TOKEN_DIRECTORY` | `tokens` | Directory of `<userName>.txt` bearer-token files. |
| `WEVE_DEFAULT_USER` | `default` | Token profile used when no `userName`/`aadId` is supplied. |
| `WEVE_USER_CACHE_FILE` | `data/user-cache.json` | Demo people directory for `find_users_by_name`. |
| `WEVE_LOG_FILE` | `logs/server.log` | Structured request log (best-effort; set `:memory:` to disable). |
| `WEVE_TASKS_RESOURCE` | `agentPlanTasks` | OData navigation segment for a plan's tasks. |
| `UPSTREAM_TIMEOUT_MS` | `120000` | Upstream request timeout in ms. |
| `WEVE_MCP_TRANSPORT` / `WEVE_MCP_HOST` / `WEVE_MCP_PORT` (or `PORT`) | `http` / `127.0.0.1` / `8081` | Transport and HTTP bind settings. |

Relative paths resolve against this directory. TLS verification is skipped **only**
for `localhost` upstreams (self-signed dev certs); all other hosts are verified.

## Tools

Discovery / directory:

- `find_users_by_name` — search the cached demo directory by name/alias/email/profile.
- `get_wevenova_lifecycle_rules` — authoritative project/plan/task capabilities.
- `list_attestable_roles` — provider-owned roles accepted by attestation.
- `list_task_roles` — every role accepted for task grounding or pooled assignment.

Projects:

- `list_agent_configuration_projects`, `create_agent_configuration_project`,
  `get_agent_configuration_project`, `archive_agent_configuration_project`.

Plans:

- `list_project_plans`, `get_project_plan`, `create_project_plan`,
  `update_project_plan`, `archive_project_plan`.

Tasks:

- `list_project_plan_tasks`, `get_project_plan_task`, `create_project_plan_task`,
  `create_role_assigned_project_plan_task`, `list_project_plan_tasks_for_caller`,
  `update_project_plan_task`, `set_project_plan_task_state`,
  `complete_project_plan_task`, `delete_project_plan_task`.

Role assignments (tenant-sharded — require `tenantId`):

- `list_plan_role_assignments`, `get_role_assignment`, `attest_plan_role`,
  `revoke_role_assignment`.

## Lifecycle & concurrency rules (enforced by the tools)

- **No DELETE for projects or plans.** Archive projects with
  `archive_agent_configuration_project` and plans with `archive_project_plan`.
  Only **tasks** have a DELETE route (`delete_project_plan_task`, one at a time).
- **Optimistic concurrency.** Before any PATCH/DELETE, read the exact target
  entity (its `get_*` tool) and pass **that entity's** current ETag as
  `If-Match` — never a parent or list-response ETag. Retry at most once on an
  ETag mismatch. Create operations and a first-time `attest_plan_role` omit the
  ETag; `attest_plan_role`'s optional `etag` is only an existing assignment's
  strong ETag, never a plan's weak `W/"..."` ETag.
- **Task state requires an Active plan.** Transitions fail with
  `Details.Code=PlanNotActive` until the plan owner activates the Draft plan
  (`update_project_plan` with `{ Status: "Active" }`).
- **Claiming a pooled task** = `update_project_plan_task` with a patch containing
  **only** `AssignedToId`. `AssignedToType` / `AssignedToRoleId` are create-only.
- **Completion outputs.** `complete_project_plan_task` atomically sets
  `State=Completed` and persists `outputs`. Each output needs a unique `key` and
  a supported `kind` (`Custom`, `Environment`, `Connection`, `KnowledgeSource`);
  `Environment` outputs require a non-empty `environmentId` attribute.

## Tests

```powershell
python -m unittest discover -s tests
```

The suite is stdlib-only (no `mcp`, no network): it injects a fake upstream
sender and a temporary token directory, then asserts URL shapes, HTTP methods,
`If-Match` / `Idempotency-Key` headers, OData `$filter`/`$select` encoding,
output mapping, and validation errors for every representative tool.

## Security

- `tokens/`, `logs/`, and `data/user-cache.json` are gitignored. Never commit
  bearer tokens or real directory data.
- Tokens are read from disk only to build the `Authorization` header; they are
  never logged (only the selected `userName` is recorded).
