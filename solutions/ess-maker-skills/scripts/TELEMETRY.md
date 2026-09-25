# ESS ADK / FlightCheck Telemetry — Investigation Guide

This document is the entry point for **investigations** that involve ESS ADK
or FlightCheck telemetry — for example, "was the event from tenant X emitted
by an up-to-date clone of the ADK, and if not, how far behind was it?"

It is written for AI agents (Copilot, Agency, …) and humans troubleshooting
a specific tenant or event. It is **not** documentation for building
dashboards or aggregate reporting.

> **Position on toolkit version dimensions:**
> The `toolkit_git_sha` and `toolkit_git_branch` dimensions added in PR #335
> (and their `agent_type` derivation in PRs #336 / #337) are intended
> **only for reactive per-tenant / per-event investigations** of the kind
> described below. They are **not** meant to back an Aria dashboard tile.
> The ADK is a source-only repo: makers pull `main` / `main-ca` whenever
> they choose, so the SHA has effectively unbounded cardinality and any
> donut split-by SHA would degenerate to a mess of single-count wedges
> within days. Dashboards continue to use `adk_version` (bounded, release-
> cadence) for coarse cohorting; SHA + branch exist here for the
> investigation workflow only.

---

## Where events go

ESS ADK and FlightCheck emit to the 1DS OneCollector pipeline. Every event
lands in two places:

- **Aria RTA cubes** — powers the portal dashboards. Cube-side dimension
  registration is required for tiles to query a field, and RTA has a
  ~30-day hot window. Good for aggregate charts, poor for per-event drill-
  down.
- **Kusto (Asimov)** — every field on every event, stored raw as columns.
  No cube-side dim registration needed; retention is longer than RTA's
  hot window. **This is the surface for investigations.**

Prod project id: `311254257bbc417e860c76781d4863c8`.
Dev project id:  `08e397b2c6c243eeaeb341e111c36167`.

## How to connect to Kusto

- Cluster: `https://kusto.aria.microsoft.com`
- Database: the Aria project id (see above)
- Auth: your corp AAD identity
- Access: requires Aria **Event reader** role on the project (the Metric
  reader role for dashboard viewing is not enough).

See [`telemetry_queries.kql`](telemetry_queries.kql) — the self-serve query
pack — for full connection instructions and a canonical set of KQL queries
covering usage, verdicts, categories, per-tenant breakdown, run duration,
Vorpal client events, and (**§9**) toolkit version coverage.

## Column naming reminder

Column casing differs by table family:

| Table family | Casing | Example fields |
|---|---|---|
| `essmakerkit_flightcheck_run` / `_check` | camelCase | `tenantId`, `tenantName`, `instanceId`, `toolkitGitSha`, `toolkitGitBranch` |
| `adk_session_start`, `adk_capability_use`, `adk_agent_create`, `adk_agent_deploy`, `adk_build_complete`, `adk_api_call` | snake_case | `tenant_id`, `tenant_name`, `instance_id`, `toolkit_git_sha`, `toolkit_git_branch` |

Time column on every table: `EventInfo_Time` (UTC).

## What each identifier means

| Field | Meaning |
|---|---|
| `tenant_id` / `tenantId` | Raw Microsoft Entra tenant GUID of the maker (OII per approved Data Profile) |
| `tenant_name` / `tenantName` | Best-effort org display name (OII; may be empty on older events) |
| `instance_id` / `instanceId` | Random GUID pinned per install (`.adk/config`); a single tenant may have many. **This is the unit of "one maker's clone."** |
| `session_id` / `sessionId` | 30-minute session grouping of events from one install |
| `adk_version` / `adkVersion` | The shipped VS Code extension's `package.json` version — coarse, only bumps on manual maintainer commits |
| `toolkit_git_sha` / `toolkitGitSha` | 7-char hex SHA of the clone's local `HEAD` — the precise upgrade posture signal |
| `toolkit_git_branch` / `toolkitGitBranch` | Bounded classification: `main`, `main-ca`, `detached`, `other`, `unknown` |
| `agent_type` / `agentType` | Derived from branch: `custom_agent` (`main-ca`) / `declarative_agent` (`main`) / `unknown`. Present once PR #336 / #337 are merged. |

---

## Investigation workflow: "was tenant X on an up-to-date ADK when this happened?"

1. **Fetch the (install, SHA, branch) triple for the tenant / event of interest.**
   Use `telemetry_queries.kql` §9a (FlightCheck) or §9b (ADK platform tables).
   The result is one row per install with the SHA it was emitting from and
   the branch classification (`main` = DA, `main-ca` = CA, `other` /
   `detached` / `unknown` = anything else).

2. **Determine "how far behind" via GitHub compare API.** Kusto cannot
   call GitHub, so this step is out-of-band (script, agent, or manual
   `curl`):

   ```
   GET https://api.github.com/repos/microsoft/Employee-Self-Service-Agent-Developer-Kit/compare/{tenant_sha}...{branch_head}
   ```

   where `{branch_head}` is `main` when `toolkitGitBranch == "main"` (DA)
   or `main-ca` when `toolkitGitBranch == "main-ca"` (CA). Response fields
   you care about:

   | Field | Interpretation |
   |---|---|
   | `behind_by` | Exact commits-behind count |
   | `ahead_by` | Non-zero if the maker has local / topic-branch commits not on the shipping branch |
   | `commits[].commit.author.date` | Age of each commit between the emitter and head |
   | `files[]` | Files that changed — useful for "does the delta include the fix I care about?" |

3. **Interpret the answer for the tenant.** A single tenant can have
   many installs on different SHAs simultaneously (each maker on that
   tenant has their own clone). §9d in `telemetry_queries.kql` surfaces
   this case explicitly. If it applies, report per-install rather than
   per-tenant.

## Edge cases and gotchas

- **`toolkit_git_branch == "other"`** — maker is on a topic/fork branch.
  GitHub compare still works, but "behind" is meaningful only relative
  to a chosen base; note the branch is non-standard in the report.
- **`toolkit_git_branch == "detached"`** — SHA is directly a commit;
  compare against `main` or `main-ca` per `agent_type`. Same workflow.
- **`toolkit_git_sha == "unknown"` or `toolkit_git_branch == "unknown"`** —
  the install's `.git` was missing or malformed (e.g., ZIP download,
  not a `git clone`). Nothing to compare; report "version not
  determinable" for those events.
- **Short-SHA ambiguity.** 7 hex chars against a repo with a few
  thousand reachable commits per branch → collision probability is
  vanishingly small. If GitHub returns 422 "ambiguous", the SHA
  transport truncated something legitimately unique; investigate the
  emitter rather than assuming ambiguity.
- **Force-pushed / GC'd SHAs.** A topic branch that was squash-merged
  and deleted may leave the maker's SHA unreachable from any current
  branch. Rare for `main` / `main-ca` (which are protected). If it
  happens, GitHub compare returns 404.

## Why not just build a dashboard?

Because SHA cardinality grows every time anyone merges to `main` or
`main-ca`. Within a 30-day window there can easily be dozens of distinct
SHAs across a modest install base — a donut becomes unreadable, and the
"tenants by SHA" measure double-counts any tenant with multiple installs
on different versions.

The right dashboard-side aggregation of "upgrade posture" would need an
emit-time age signal (e.g., a `toolkit_git_commit_date` dimension), which
is a follow-up ADO task, not part of PRs #335 / #336 / #337. Until that
lands, this document + `telemetry_queries.kql` §9 is the sanctioned way
to consume the SHA and branch dimensions.

## Related files

- [`telemetry_queries.kql`](telemetry_queries.kql) — PM self-serve KQL
  pack. §9 covers toolkit version coverage investigations.
- [`adk_telemetry.py`](adk_telemetry.py) — the emitter for ADK platform
  events. `common_dimensions()` is where `toolkit_git_sha` /
  `toolkit_git_branch` / `agent_type` are stamped onto every event.
- [`flightcheck/telemetry.py`](flightcheck/telemetry.py) — the emitter
  for FlightCheck run / check events. `_run_data()` and the selftest
  event stamp the camelCase `toolkitGitSha` / `toolkitGitBranch` /
  `agentType` fields.
