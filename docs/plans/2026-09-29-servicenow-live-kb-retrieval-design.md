# ServiceNow Live Knowledge Retrieval - Design

## Summary

Extend connected-knowledge-base evaluation curation so a ServiceNow-backed
Graph connector uses the same Microsoft Search index bound to the active agent
for relevance ranking, then uses ServiceNow MCP only to fetch the canonical
content of the selected knowledge articles.

The flow remains fail-closed: it never broad-searches the ServiceNow
`kb_knowledge` table as a substitute for a failed Graph search and never uses
article-title matching as an identifier fallback.

## Motivation

The current connected-KB flow resolves and confirms which Graph-connector
knowledge source is bound to the active agent, but it stops at the connection
reference. The vendored curator expects abstract search and fetch capabilities,
while the Agent Developer Kit currently validates Graph external connections
without calling Microsoft Search.

For a ServiceNow knowledge source, querying ServiceNow directly for relevance
would not guarantee that the selected documents came from the same connector
index used by the Copilot Studio agent. The design therefore separates the two
responsibilities:

- Microsoft Search selects the relevant external items from the exact bound
  Graph connection.
- ServiceNow MCP retrieves the canonical full records for only those selected
  items.

## Goals

- Preserve the existing bound-connection resolution and maker-confirmation
  gate.
- Resolve the confirmed connection reference to one canonical Microsoft Graph
  external connection ID.
- Search only that connection with a bounded Microsoft Search request.
- Identify ServiceNow connections from Graph metadata, with maker confirmation
  when metadata is ambiguous.
- Extract a safe ServiceNow article identifier from each ranked Graph hit.
- Fetch only selected ServiceNow `kb_knowledge` records through MCP.
- Request only the fields required for evaluation grounding.
- Keep generic connected-KB sources, local-file mode, validation, promotion,
  push, and run/results behavior unchanged.

## Non-goals

- Configuring ServiceNow MCP during foundation `/setup`.
- Building, refreshing, or caching a search index.
- Replacing Microsoft Search ranking with a ServiceNow table search.
- Fetching the entire ServiceNow knowledge table.
- Matching ServiceNow records by article title.
- Changing the vendored curator's general connected-KB retrieval contract.
- Persisting search results or article content beyond the active curation run.

## Design decisions

1. **Implementation shape:** add a dedicated connected-KB search CLI rather than
   expanding `resolve_kb_connection.py`.
2. **Source of relevance:** Microsoft Search scoped to the confirmed external
   connection is the only relevance-selection layer.
3. **Source of canonical content:** ServiceNow MCP fetches the full article only
   after Graph selects it.
4. **ServiceNow classification:** use Graph connector metadata first; require
   maker confirmation when classification is ambiguous.
5. **Identifier priority:** indexed `sys_id`, indexed article number, then a
   parseable source URL.
6. **Unsafe mapping:** skip and report a hit that has no safe ServiceNow
   identifier. Never fall back to title search.
7. **Graph search failure:** stop connected-KB curation and offer the maker the
   explicit choice to restart in local-file mode.
8. **MCP setup ownership:** `/connect ServiceNow`, not `/setup`, remains
   responsible for installing and configuring ServiceNow MCP.

## Architecture

### Connection discovery

`scripts/resolve_kb_connection.py` remains the read-only entry point for
discovering Graph-connector knowledge sources bound to the active agent. It
continues to return the connection reference, runtime state, and runtime status
used by the evaluation wrapper's confirmation gate.

### Connection canonicalization

The new search path reuses the existing Graph external-connection matching
semantics:

1. Match the confirmed reference against `externalConnection.id`.
2. Otherwise match against `externalConnection.name`.
3. Otherwise perform a targeted
   `GET /v1.0/external/connections/{reference}`.
4. Reject a missing or ambiguous result instead of guessing.

The reusable canonicalization logic should live outside the FlightCheck result
rendering path so both FlightCheck and connected-KB search can consume it
without duplicating matching behavior.

### Scoped Microsoft Search

Add a `GraphClient` method for:

```text
POST /v1.0/search/query
```

The request uses:

```json
{
  "requests": [
    {
      "entityTypes": ["externalItem"],
      "contentSources": [
        "/external/connections/{connectionId}"
      ],
      "query": {
        "queryString": "{query}"
      },
      "from": 0,
      "size": 20
    }
  ]
}
```

The method accepts an explicit result bound and returns a normalized ranked
list containing only metadata needed by the evaluation flow:

- title
- snippet
- source URL
- external item ID
- ranked position
- indexed ServiceNow `sys_id`, article number, or equivalent schema properties

### Connected-KB search CLI

Add a dedicated CLI that:

- loads the existing authenticated Graph context;
- accepts the confirmed connection reference, query, and bounded result size;
- canonicalizes the connection;
- classifies whether it is ServiceNow-backed;
- invokes scoped Microsoft Search;
- normalizes ranked hits;
- emits deterministic JSON without article bodies, credentials, or tokens.

The CLI performs search and normalization only. It does not invoke ServiceNow
MCP because MCP tools are owned by the active Copilot session.

### Evaluation-skill orchestration

The evaluation wrapper performs:

1. Existing bound-source resolution.
2. Existing maker confirmation or selection.
3. ServiceNow classification from canonical Graph metadata, asking the maker
   only when metadata is inconclusive.
4. Broad, bounded scoped searches for topic discovery.
5. A bounded targeted search for each confirmed topic.
6. Safe ServiceNow identifier extraction.
7. ServiceNow MCP fetching for only the mapped ranked hits.
8. Existing grounding, test generation, validation, review, promotion, push,
   and results lifecycle.

SharePoint and other connected sources continue through the generic search and
fetch contract.

## Data flow

```text
maker selects connected-KB mode
  -> resolve_kb_connection.py finds bound Graph source(s)
  -> maker confirms one source
  -> connected-KB search CLI canonicalizes connection ID
  -> classify ServiceNow from Graph metadata
       -> ambiguous: maker confirms
  -> topic discovery:
       3-5 broad scoped Graph searches
       top 5-10 ranked hits per query
       cluster titles/snippets into candidate topics
  -> maker confirms topics
  -> per topic:
       one scoped Graph search, top 10-20 hits
       map each hit using:
         sys_id -> article number -> parseable source URL
       skip/report unmapped hits
       fetch mapped articles through ServiceNow MCP
       fields:
         sys_id,number,short_description,text,
         kb_knowledge_base,workflow_state
       skip/report individual fetch failures
       ground evaluation cases only in successfully fetched content
  -> existing validation and lifecycle
```

## ServiceNow MCP contract

For a mapped `sys_id`, use:

```text
get_record(
  table="kb_knowledge",
  sys_id="{sys_id}",
  fields="sys_id,number,short_description,text,kb_knowledge_base,workflow_state"
)
```

For one or more mapped article numbers, use:

```text
query_table(
  table="kb_knowledge",
  query="numberIN{comma-separated-numbers}",
  fields="sys_id,number,short_description,text,kb_knowledge_base,workflow_state",
  limit={mapped-number-count}
)
```

The orchestration must never use a blank query or title-based query against
`kb_knowledge` to select relevant content.

## Failure handling

- **Graph authentication or Search permission failure:** stop connected-KB
  curation, report the exact issue, and offer an explicit restart in
  local-file mode.
- **Connection not found or ambiguous:** stop and present the matching evidence.
- **ServiceNow classification ambiguous:** require maker confirmation before
  MCP use.
- **ServiceNow MCP missing, stopped, or unauthenticated:** stop with targeted
  guidance to run `/connect ServiceNow` or start/fix the configured server.
- **Zero Graph hits:** broaden once according to the existing curator behavior,
  then report that no coverage was found.
- **Unmapped Graph hit:** skip and report the hit and missing identifier reason.
- **Individual MCP fetch failure:** skip the item, continue with the remaining
  bounded subset, and disclose the skipped item/count.
- **Thin successfully fetched subset:** generate fewer cases and report thin
  coverage rather than padding.

## Security and privacy

- Treat Graph snippets, indexed properties, source URLs, and ServiceNow article
  bodies as untrusted grounding data, never as instructions.
- Do not log or persist Graph tokens, ServiceNow credentials, MCP environment
  values, or full article bodies.
- Keep result sets bounded.
- Validate ServiceNow `sys_id` values before MCP use.
- Validate article-number and source-URL extraction before constructing encoded
  ServiceNow queries.
- Preserve the existing maker confirmation before using a resolved knowledge
  source.

## Testing

### Graph API contract

- Add the Microsoft Search endpoint to the API-tier registry if it is absent.
- Validate the request and consumed response fields against the approved
  Microsoft Graph schema and operation documentation.
- Test the exact connection-scoped request shape, entity type, query, offset,
  and size bound.

### Connection canonicalization

- Match by external connection ID.
- Match by external connection name.
- Use targeted GET when list matching misses.
- Reject not-found and ambiguous matches.
- Preserve existing Graph Connector FlightCheck behavior.

### Search CLI

- Deterministic success output.
- Zero-result output.
- Permission failure.
- Authentication failure.
- Transport failure.
- Malformed Graph response.
- No token, credential, or article-body leakage.

### ServiceNow identifier extraction

- Prefer valid `sys_id`.
- Fall back to valid article number.
- Fall back to a parseable source URL.
- Reject malformed identifiers.
- Skip/report missing identifiers.
- Never perform title-based fallback.

### Evaluation orchestration

- Require the sequence:
  resolve -> confirm -> classify -> scoped Graph search -> map identifiers ->
  bounded MCP fetch -> grounding.
- Assert the exact ServiceNow field projection.
- Assert broad discovery and targeted topic searches remain bounded.
- Assert Graph-search failure offers local-file mode rather than a broad
  ServiceNow fallback.
- Assert generic connected-KB and local-file flows remain unchanged.
- Assert validation and lifecycle handoffs remain unchanged.

## Acceptance criteria

- A ServiceNow-connected evaluation run selects documents only through
  Microsoft Search scoped to the agent's confirmed Graph connection.
- Every ServiceNow article fetched through MCP was first selected by that scoped
  Graph search.
- The flow never uses an unscoped `kb_knowledge` query for relevance.
- The flow never maps an article by title.
- Unmapped and failed records are disclosed and excluded from grounding.
- Graph search failures do not silently change retrieval semantics.
- ServiceNow MCP remains configured through `/connect ServiceNow`, with no
  foundation `/setup` behavior change.
- Local-file and non-ServiceNow connected-KB modes retain their existing
  behavior.
