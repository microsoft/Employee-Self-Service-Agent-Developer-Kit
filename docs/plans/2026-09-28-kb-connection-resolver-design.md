# ServiceNow/Graph-Connector Connection Resolver — Design

## Summary

Add a resolver that, given the active agent (via `.local/config.json`), determines
which Graph-connector knowledge source(s) (e.g. ServiceNow, SharePoint) are
actually bound to that agent in Copilot Studio — and has the maker confirm the
resolved connection before it is used for grounding search. This closes the gap
in the eval curator's connected-KB mode: today the maker must supply a
`connectionName` blind; this resolver derives and confirms it automatically.

## Motivation

The tenant-wide catalog at `df.gcs.office.com/v1.0/admin/knowledge/connectors/v2`
lists every Graph connector available in the tenant, but not which one (if any)
is attached to a specific Copilot Studio agent. The only way to determine that
is the agent-scoped Island Gateway `botcomponents` API, already implemented and
tested in this repo (`scripts/flightcheck/pva_client.py`,
`scripts/flightcheck/checks/graph_connector_kb.py`). This design wraps that
existing, verified capability into a small resolver the eval curator's
connected-KB mode can call, instead of duplicating the join/lookup logic or
asking the maker to guess a connection name.

## Goals

- Programmatically resolve the Graph-connector knowledge source(s) bound to the
  active agent, reusing the existing `PvaClient` + `graph_connector_kb.py`
  helpers — no reimplementation of the `botcomponents` call or the
  `connectionName`/`connectionId` join logic.
- Always confirm the resolved connection(s) with the maker before running any
  Graph search against them.
- When more than one Graph-connector source is bound, list all and let the
  maker choose.
- On any resolution failure (no config, no gateway, zero bound sources), stop
  and report the specific failure — no silent fallback to local-file mode.
- Feed the confirmed `connectionName` into the eval curator's existing
  connected-KB Step 3b/3c flow unchanged.

## Non-goals

- Editing the vendored curator body (`curator/curate-evals.md`).
- Auto-selecting a connection without maker confirmation, even when only one
  is bound.
- Auto-falling back to local-file mode on resolution failure.
- Building or configuring any new connector.
- Caching or persisting resolved connection info beyond the current run.

## Design decisions (settled)

1. **Output scope:** resolver is purpose-built for eval curation's
   connected-KB mode — not a standalone diagnostic skill.
2. **Confirmation UX:** always show the resolved connection(s) and status, and
   require explicit maker confirmation before searching, every run.
3. **Multiple bound sources:** list all bound Graph-connector sources
   (`connectionName` + status) and let the maker pick one or more.
4. **Failure handling:** stop and report the exact failure (missing config,
   unconfigured `PvaClient`, zero bound sources, etc.); never silently switch
   to local-file mode.
5. **Implementation shape:** a new Python resolver module plus a thin CLI
   shim (JSON in/out, matching the `eval_curator_handoff.py` deterministic-check
   pattern), invoked by the curate skill wrapper. No new MCP tool surface, no
   markdown-only prompt-driven resolution.

## Components

| Component | Change |
|---|---|
| `scripts/flightcheck/kb_connection_resolver.py` (new) | `resolve_bound_connections(bot_id) -> list[BoundConnection]`. Calls `PvaClient.get_knowledge_sources()`, filters via existing `_filter_graph_connector_sources()`, extracts `connectionName` via existing `_connector_reference()`. Resolution only — no Graph search. |
| `scripts/resolve_kb_connection.py` (new CLI shim) | Loads `.local/config.json` for env/botId, invokes the resolver, prints JSON: `{status: "ok"|"none_bound"|"error", connections: [{connectionName, status}], error?: "..."}`. |
| `curate/SKILL.md` (wrapper, connected-KB branch) | Before curator Step 3b: run the CLI shim. Branch on `status`: `error`/`none_bound` → stop with the specific message; `ok` with 1 connection → show + confirm; `ok` with N connections → list + maker picks one or more. Pass confirmed `connectionName`(s) into the curator body's existing connected-KB flow. |
| `curator/curate-evals.md` (vendored body) | **No change.** Receives a confirmed `connectionName` as the connected-KB source identifier it already expects. |

## Data flow

```
maker chooses "connected knowledge base" (existing curate wrapper mode-select)
  → CLI shim: .local/config.json → env + botId
  → kb_connection_resolver.resolve_bound_connections(botId)
      → PvaClient.get_knowledge_sources(botId)
      → _filter_graph_connector_sources() → _connector_reference() per source
  → shim prints {status, connections[]}
  → wrapper:
      status == "error"      → stop, report the specific failure
      status == "none_bound" → stop, report no Graph-connector source is bound
      status == "ok", 1 conn → show connectionName + status, ask maker to confirm
      status == "ok", N conn → list all, ask maker to pick one or more
  → confirmed connectionName(s) → curator body Step 3b (discovery)
    → Step 3c (per-topic grounding) → Step 4 (generation)
    → existing Maker Kit lifecycle (validate → review → promotion → push → run), unchanged
```

## Error handling

- No `.local/config.json` / no bound `botId` → stop: "Run `/setup` first to
  bind an agent."
- `PvaClient` not configured (missing gateway/auth) → stop: surface the exact
  `is_configured` reason from the client.
- Zero Graph-connector sources bound → stop: "No ServiceNow/SharePoint
  knowledge source is attached to this agent in Copilot Studio. Attach one
  first, or choose local-file mode instead." No automatic fallback; the maker
  restarts the mode-select step themselves if they want local-file mode.
- Connection resolved but not fully indexed (e.g. item count 0 / provisioning
  status) → surface as a warning at confirmation time, but still let the maker
  proceed if they confirm.

## Security and privacy

The resolver only reads bot-component metadata (which connection is bound) via
the existing authenticated `PvaClient` — it performs no Graph search itself and
persists nothing. It relies on already-established Maker Kit auth
(`.local/config.json` + `PvaClient`), adding no new credentials or scopes.

## Testing

- Unit tests for `kb_connection_resolver.py` (mocked `PvaClient`): zero
  sources, one Graph-connector source, multiple sources, non-Graph-connector
  sources filtered out, `connectionName` vs `connectionId`-dict fallback per
  existing `_connector_reference()` semantics.
- CLI shim test: JSON output shape for each `status` value, matching the
  deterministic-check pattern already used by `eval_curator_handoff.py`.
- Doc-assertion test on `curate/SKILL.md`: connected-KB branch invokes the
  shim before Step 3b, always requires confirmation (single or multiple bound
  connections), and never silently proceeds without one.
- No changes to the vendored curator body or its existing test coverage.

## Acceptance criteria

When a maker chooses connected-KB mode in the eval curator, the wrapper
automatically resolves the agent's bound Graph-connector knowledge source(s)
via the existing `botcomponents` lookup, shows the maker exactly which
connection(s) were found (or the specific reason none could be resolved), and
proceeds into the curator's existing Step 3b/3c grounding flow only after
explicit maker confirmation of the connection to use.
