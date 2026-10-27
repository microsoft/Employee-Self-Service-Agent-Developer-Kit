# ServiceNow Live Knowledge Retrieval Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Make connected-KB evaluation curation rank documents through the active agent's bound Microsoft Graph connection and fetch only the selected ServiceNow knowledge articles through ServiceNow MCP.

**Architecture:** Keep bound-source discovery in `resolve_kb_connection.py`, add reusable Graph connection canonicalization plus a dedicated scoped-search CLI, and let the evaluation skill orchestrate safe ServiceNow identifier mapping and MCP fetches. Microsoft Search owns relevance; ServiceNow MCP owns canonical article content.

**Tech Stack:** Python 3.12, `requests`, MSAL, Microsoft Graph v1.0 Search API, ServiceNow MCP, pytest, `responses`, Markdown skill orchestration.

---

### Task 1: Add the Microsoft Search API contract and Graph client method

**Files:**
- Modify: `solutions/ess-maker-skills/scripts/flightcheck/graph_client.py:41-62`
- Modify: `solutions/ess-maker-skills/scripts/flightcheck/graph_client.py:580-650`
- Modify: `tests/mocks/graph.py:1-35`
- Modify: `tests/mocks/graph.py:971-1145`
- Modify: `tests/fixtures/cassettes/INDEX.md:37-50`
- Modify: `tests/flightcheck/test_graph_client.py`

**Step 1: Write failing tests for scope and request shape**

Add tests that build a token-populated `GraphClient`, intercept
`POST https://graph.microsoft.com/v1.0/search/query`, and assert:

```python
def test_search_external_items_scopes_query_to_one_connection(fake_token):
    client = GraphClient(tenant_id="tenant")
    client._token = fake_token

    result = client.search_external_items(
        connection_id="ServiceNowKB63",
        query="parental leave",
        size=12,
        fields=["title", "url", "sys_id", "number"],
    )

    request = json.loads(responses.calls[0].request.body)
    search = request["requests"][0]
    assert search["entityTypes"] == ["externalItem"]
    assert search["contentSources"] == [
        "/external/connections/ServiceNowKB63"
    ]
    assert search["query"] == {"queryString": "parental leave"}
    assert search["from"] == 0
    assert search["size"] == 12
```

Also assert:

```python
assert "https://graph.microsoft.com/ExternalItem.Read.All" in GRAPH_SCOPES
```

Test `size=0`, negative sizes, and values above the supported bound. The
production method should reject invalid sizes rather than silently issue an
unbounded search.

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest tests/flightcheck/test_graph_client.py -k "search_external_items or external_item_scope" -v
```

Expected: FAIL because `search_external_items` and the new scope do not exist.

**Step 3: Add a schema-backed mock builder**

In `tests/mocks/graph.py`, add builders for the documented shape:

```python
def external_item_search_response(
    *,
    hits: list[dict[str, Any]] | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    """Build POST /search/query response for externalItem search.

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              ComplexType searchResponse: hitsContainers
              ComplexType searchHitsContainer: hits, total,
              moreResultsAvailable
              ComplexType searchHit: hitId, rank, summary, resource,
              contentSource
      Docs: https://learn.microsoft.com/graph/api/search-query
            https://learn.microsoft.com/graph/api/resources/searchhit
            https://learn.microsoft.com/graph/api/resources/searchhitscontainer
    """
    hits = list(hits or [])
    return {
        "value": [
            {
                "searchTerms": ["mock"],
                "hitsContainers": [
                    {
                        "hits": hits,
                        "total": len(hits) if total is None else total,
                        "moreResultsAvailable": False,
                    }
                ],
            }
        ]
    }
```

Add a `search_hit()` builder whose `resource` is an external-item-shaped
dictionary with a `properties` object. Do not guess tenant-specific ServiceNow
property names in the shared schema builder; tests can supply them as overrides.

Update the Graph tier notes in `INDEX.md` to explicitly record that
`POST /v1.0/search/query` is covered by the existing `validatable` Microsoft
Graph tier and cite the Search API/resource documentation.

**Step 4: Implement the Graph client method**

Add the delegated read scope:

```python
"https://graph.microsoft.com/ExternalItem.Read.All",
```

Implement:

```python
def search_external_items(
    self,
    connection_id: str,
    query: str,
    *,
    size: int = 20,
    fields: list[str] | None = None,
) -> dict:
    connection_id = connection_id.strip()
    query = query.strip()
    if not connection_id:
        raise ValueError("Connection ID must be non-empty.")
    if not query:
        raise ValueError("Search query must be non-empty.")
    if not 1 <= size <= 100:
        raise ValueError("Search size must be between 1 and 100.")

    request = {
        "entityTypes": ["externalItem"],
        "contentSources": [f"/external/connections/{connection_id}"],
        "query": {"queryString": query},
        "from": 0,
        "size": size,
    }
    if fields:
        request["fields"] = list(fields)

    response = _SESSION.post(
        f"{GRAPH_BASE}/search/query",
        headers={**self.headers, "Content-Type": "application/json"},
        json={"requests": [request]},
        timeout=30,
    )
    if response.status_code in (401, 403):
        return {
            "_error": "insufficient_permissions",
            "_status": response.status_code,
        }
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Microsoft Search returned an invalid response.")
    return body
```

Do not add POST to the module retry policy in this task. The call is read-only,
but changing retry semantics is a separate concern and is not required for the
feature.

**Step 5: Run the targeted tests**

Run:

```powershell
py -3.12 -m pytest tests/flightcheck/test_graph_client.py -k "search_external_items or external_item_scope" -v
```

Expected: PASS.

**Step 6: Commit**

```powershell
git add solutions/ess-maker-skills/scripts/flightcheck/graph_client.py tests/mocks/graph.py tests/fixtures/cassettes/INDEX.md tests/flightcheck/test_graph_client.py
git commit -m "feat(graph): add scoped external item search"
```

Include the repository-required Copilot co-author trailer.

### Task 2: Extract reusable Graph connection canonicalization

**Files:**
- Create: `solutions/ess-maker-skills/scripts/flightcheck/graph_connection_resolver.py`
- Modify: `solutions/ess-maker-skills/scripts/flightcheck/checks/graph_connector_kb.py:140-255`
- Create: `tests/flightcheck/test_graph_connection_resolver.py`
- Modify: `tests/flightcheck/checks/test_graph_connector_kb.py`

**Step 1: Write failing pure-logic tests**

Define expected outcomes:

```python
def test_resolve_matches_connection_id():
    result = resolve_graph_connection(
        fake_graph(connections=[{"id": "ServiceNowKB63", "name": "HR KB"}]),
        "ServiceNowKB63",
    )
    assert result.connection["id"] == "ServiceNowKB63"
    assert result.matched_by == "id"


def test_resolve_matches_connection_name():
    result = resolve_graph_connection(
        fake_graph(connections=[{"id": "snow-hr", "name": "ServiceNowKB63"}]),
        "ServiceNowKB63",
    )
    assert result.connection["id"] == "snow-hr"
    assert result.matched_by == "name"


def test_resolve_rejects_duplicate_names():
    with pytest.raises(GraphConnectionResolutionError, match="ambiguous"):
        resolve_graph_connection(
            fake_graph(
                connections=[
                    {"id": "a", "name": "ServiceNowKB63"},
                    {"id": "b", "name": "ServiceNowKB63"},
                ]
            ),
            "ServiceNowKB63",
        )
```

Also cover targeted GET, not found, permission sentinel, malformed list rows,
and an empty reference.

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest tests/flightcheck/test_graph_connection_resolver.py -v
```

Expected: FAIL because the module does not exist.

**Step 3: Implement the resolver**

Create a small result type:

```python
@dataclass(frozen=True)
class ResolvedGraphConnection:
    reference: str
    connection: dict[str, Any]
    matched_by: str

    @property
    def connection_id(self) -> str:
        return str(self.connection["id"])
```

Implement `resolve_graph_connection(graph, reference)` with the exact order:

1. Load `graph.get_external_connections()`.
2. Collect exact case-insensitive ID matches.
3. If none, collect exact case-insensitive name matches.
4. Reject multiple matches.
5. If no list match, call `graph.get_external_connection(reference)`.
6. Reject Graph permission/not-found sentinels and invalid result shapes.

Do not put ServiceNow classification or Microsoft Search in this helper.

**Step 4: Refactor FlightCheck to reuse it**

Replace the inline ID/name/targeted-GET matching block in
`graph_connector_kb.py` with `resolve_graph_connection`. Preserve existing
FlightCheck result wording and statuses unless the existing behavior is
provably incorrect. Update existing tests only where they assert implementation
details rather than behavior.

**Step 5: Run resolver and FlightCheck regression tests**

Run:

```powershell
py -3.12 -m pytest tests/flightcheck/test_graph_connection_resolver.py tests/flightcheck/checks/test_graph_connector_kb.py -v
```

Expected: PASS.

**Step 6: Commit**

```powershell
git add solutions/ess-maker-skills/scripts/flightcheck/graph_connection_resolver.py solutions/ess-maker-skills/scripts/flightcheck/checks/graph_connector_kb.py tests/flightcheck/test_graph_connection_resolver.py tests/flightcheck/checks/test_graph_connector_kb.py
git commit -m "refactor(graph): share connector resolution"
```

Include the repository-required Copilot co-author trailer.

### Task 3: Add ranked-hit normalization and safe ServiceNow mapping

**Files:**
- Create: `solutions/ess-maker-skills/scripts/flightcheck/connected_kb_search.py`
- Create: `tests/flightcheck/test_connected_kb_search.py`

**Step 1: Write failing normalization tests**

Cover the documented nested response shape:

```python
def test_normalize_search_hits_preserves_ranked_metadata():
    payload = graph.external_item_search_response(
        hits=[
            graph.search_hit(
                hit_id="opaque-hit",
                rank=1,
                summary="Leave policy summary",
                resource={
                    "id": "external-item",
                    "properties": {
                        "title": "Parental leave",
                        "sys_id": "0123456789abcdef0123456789abcdef",
                        "url": "https://example.service-now.com/kb?id=kb_article&sys_id=0123456789abcdef0123456789abcdef",
                    },
                },
            )
        ]
    )
    hits = normalize_external_item_hits(payload)
    assert hits[0].rank == 1
    assert hits[0].title == "Parental leave"
    assert hits[0].service_now_identifier.kind == "sys_id"
```

Add tests for:

- `sys_id` in root or `resource.properties`;
- valid article number such as `KB0012345`;
- `sys_id` parsed from a source URL;
- malformed `sys_id`;
- opaque `hitId` not treated as a ServiceNow identifier;
- duplicate hits deduplicated by canonical identifier;
- missing identifier produces `identifier=None` plus a stable skip reason;
- no title fallback.

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest tests/flightcheck/test_connected_kb_search.py -v
```

Expected: FAIL because the module does not exist.

**Step 3: Implement normalized types**

Use explicit data classes:

```python
@dataclass(frozen=True)
class ServiceNowIdentifier:
    kind: Literal["sys_id", "number"]
    value: str


@dataclass(frozen=True)
class RankedExternalItem:
    rank: int
    hit_id: str
    title: str
    summary: str
    source_url: str
    properties: dict[str, Any]
    service_now_identifier: ServiceNowIdentifier | None
    skip_reason: str | None
```

Implement pure helpers:

```python
normalize_external_item_hits(payload) -> list[RankedExternalItem]
extract_servicenow_identifier(resource) -> ServiceNowIdentifier | None
```

Identifier extraction order:

1. Valid 32-hex `sys_id` from recognized root/property keys.
2. Valid article number from recognized root/property keys.
3. Valid `sys_id` or article number parsed from recognized URL fields.

Use conservative key aliases and case-insensitive lookup. Do not derive an
identifier from title, summary, or opaque Graph `hitId`.

**Step 4: Add connection classification**

Add:

```python
@dataclass(frozen=True)
class ConnectionClassification:
    kind: Literal["servicenow", "other", "ambiguous"]
    evidence: tuple[str, ...]
```

Classify only from verified Graph connection metadata. Do not add guessed
gallery connector IDs. Strong ServiceNow metadata may classify directly;
name/description tokens alone should return `ambiguous` so the evaluation skill
requires maker confirmation.

**Step 5: Run tests**

Run:

```powershell
py -3.12 -m pytest tests/flightcheck/test_connected_kb_search.py -v
```

Expected: PASS.

**Step 6: Commit**

```powershell
git add solutions/ess-maker-skills/scripts/flightcheck/connected_kb_search.py tests/flightcheck/test_connected_kb_search.py
git commit -m "feat(evaluations): normalize connected KB search hits"
```

Include the repository-required Copilot co-author trailer.

### Task 4: Add the connected-KB search CLI

**Files:**
- Create: `solutions/ess-maker-skills/scripts/connected_kb_context.py`
- Modify: `solutions/ess-maker-skills/scripts/resolve_kb_connection.py`
- Create: `solutions/ess-maker-skills/scripts/search_connected_kb.py`
- Create: `tests/scripts/test_connected_kb_context.py`
- Create: `tests/scripts/test_search_connected_kb_cli.py`
- Modify: `tests/scripts/test_resolve_kb_connection_cli.py`

**Step 1: Write failing shared-context tests**

Extract active environment/tenant lookup from `resolve_kb_connection.py` into a
shared helper without changing its JSON contract:

```python
context = load_connected_kb_context()
assert context.bot_id == FAKE_BOT_ID
assert context.tenant_id == FAKE_TENANT_ID
```

Cover both:

- Dataverse-backed config using `discover_tenant(dataverseEndpoint)`;
- native AgentBuilder config using schema-version-4 canonical setup state.

Retain fail-closed active-agent slug and tenant/environment matching.

**Step 2: Run context tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest tests/scripts/test_connected_kb_context.py tests/scripts/test_resolve_kb_connection_cli.py -v
```

Expected: new tests FAIL; existing resolver tests remain green until refactor.

**Step 3: Implement and adopt the shared context**

Move only the reusable config/state identity logic. Do not move PVA or
AgentBuilder connection code into the context module.

Update `resolve_kb_connection.py` to consume the helper and preserve every
existing success/error JSON shape and exit code.

**Step 4: Write failing CLI tests**

Specify:

```powershell
py -3.12 scripts/search_connected_kb.py --connection "ServiceNowKB63" --query "parental leave" --limit 20
```

Expected success JSON:

```json
{
  "status": "ok",
  "connection": {
    "reference": "ServiceNowKB63",
    "id": "ServiceNowKB63",
    "name": "ServiceNow HR KB",
    "classification": "ambiguous",
    "classificationEvidence": ["name contains ServiceNow"]
  },
  "query": "parental leave",
  "total": 2,
  "hits": [
    {
      "rank": 1,
      "title": "Parental leave",
      "summary": "...",
      "sourceUrl": "...",
      "identifier": {
        "kind": "sys_id",
        "value": "0123456789abcdef0123456789abcdef"
      },
      "skipReason": null
    }
  ]
}
```

Error JSON uses:

```json
{"status": "error", "hits": [], "error": "..."}
```

Tests must cover invalid arguments, Graph auth failure, connection ambiguity,
permission sentinel, zero results, malformed search response, and one unmapped
hit.

**Step 5: Implement the CLI**

The CLI should:

1. Parse `--connection`, `--query`, and `--limit`.
2. Load the active tenant from `connected_kb_context`.
3. Instantiate and authenticate `GraphClient`.
4. Canonicalize the connection with `resolve_graph_connection`.
5. Classify the connection.
6. Call `search_external_items`.
7. Normalize hits.
8. Print one deterministic JSON object.
9. Return exit code `0` for `ok`, including zero hits; return `1` for `error`.

Never print tokens, raw Graph responses, or full external-item content.

**Step 6: Run CLI and resolver tests**

Run:

```powershell
py -3.12 -m pytest tests/scripts/test_connected_kb_context.py tests/scripts/test_search_connected_kb_cli.py tests/scripts/test_resolve_kb_connection_cli.py -v
```

Expected: PASS.

**Step 7: Commit**

```powershell
git add solutions/ess-maker-skills/scripts/connected_kb_context.py solutions/ess-maker-skills/scripts/resolve_kb_connection.py solutions/ess-maker-skills/scripts/search_connected_kb.py tests/scripts/test_connected_kb_context.py tests/scripts/test_search_connected_kb_cli.py tests/scripts/test_resolve_kb_connection_cli.py
git commit -m "feat(evaluations): add scoped connected KB search CLI"
```

Include the repository-required Copilot co-author trailer.

### Task 5: Define the ServiceNow live-retrieval sequence in the evaluation skill

**Files:**
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md:65-145`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/curator/curate-evals.md:187-270`
- Modify: `solutions/ess-maker-skills/README.md:100-110`
- Modify: `tests/scripts/test_evaluation_curator_routing.py`
- Modify: `tests/mcp/evaluations/test_curator_skill_orchestration.py`

**Step 1: Write failing documentation-contract tests**

Assert the wrapper requires this ServiceNow sequence:

```text
resolve bound connection
maker confirmation
search_connected_kb.py scoped Graph search
ServiceNow classification/confirmation
safe identifier mapping
get_record/query_table on kb_knowledge
exact field projection
grounding before generation
```

Pin these invariants:

- no blank or broad `kb_knowledge` query;
- no title fallback;
- Graph failure offers restart in local-file mode;
- missing/stopped/unauthenticated ServiceNow MCP stops with `/connect
  ServiceNow` guidance;
- unmapped hits and individual fetch failures are skipped and disclosed.

**Step 2: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest tests/scripts/test_evaluation_curator_routing.py tests/mcp/evaluations/test_curator_skill_orchestration.py -k "connected_kb or servicenow" -v
```

Expected: FAIL because the skill does not define the specialized sequence.

**Step 3: Update the wrapper**

After the existing resolver confirmation gate, add the ServiceNow specialization:

```powershell
py -3.12 scripts/search_connected_kb.py `
  --connection "{CONFIRMED_CONNECTION_REFERENCE}" `
  --query "{BOUNDED_QUERY}" `
  --limit "{BOUNDED_LIMIT}"
```

Require parsing its deterministic JSON. For `classification == "ambiguous"`,
ask the maker to confirm ServiceNow before MCP use.

For discovery, run 3-5 broad searches with top 5-10 results. For each confirmed
topic, run one targeted search with top 10-20 results.

Define the exact MCP operations:

```text
get_record(
  table="kb_knowledge",
  sys_id="{MAPPED_SYS_ID}",
  fields="sys_id,number,short_description,text,kb_knowledge_base,workflow_state"
)
```

or:

```text
query_table(
  table="kb_knowledge",
  query="numberIN{MAPPED_NUMBERS}",
  fields="sys_id,number,short_description,text,kb_knowledge_base,workflow_state",
  limit={MAPPED_NUMBER_COUNT}
)
```

Explicitly prohibit title lookup and unscoped ServiceNow table search.

**Step 4: Update the vendored curator specialization**

Keep the generic search/fetch contract intact. Add a host-provided
ServiceNow specialization that says Graph search results are the bounded topic
subset and MCP-fetched article bodies are the full-content fetches. Do not
duplicate wrapper setup/authentication instructions in the vendored body.

**Step 5: Update README**

Clarify that:

- the kit resolves and searches the active Graph connection for ServiceNow;
- ServiceNow MCP must already be configured through `/connect ServiceNow`;
- foundation `/setup` does not configure vendor MCP credentials.

**Step 6: Run orchestration tests**

Run:

```powershell
py -3.12 -m pytest tests/scripts/test_evaluation_curator_routing.py tests/mcp/evaluations/test_curator_skill_orchestration.py -k "connected_kb or servicenow" -v
```

Expected: PASS.

**Step 7: Commit**

```powershell
git add solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/curate/curator/curate-evals.md solutions/ess-maker-skills/README.md tests/scripts/test_evaluation_curator_routing.py tests/mcp/evaluations/test_curator_skill_orchestration.py
git commit -m "feat(evaluations): ground ServiceNow curation through Graph"
```

Include the repository-required Copilot co-author trailer.

### Task 6: Add end-to-end offline orchestration coverage

**Files:**
- Modify: `tests/mcp/evaluations/skill_eval.py`
- Modify: `tests/mcp/evaluations/test_curator_skill_orchestration.py`

**Step 1: Extend the fake backend contracts**

Add deterministic fake operations for:

- scoped Graph external-item search;
- ServiceNow `get_record`;
- ServiceNow `query_table`.

The fake Graph search must reject a request without exactly one content source.
The fake ServiceNow tools must reject:

- a table other than `kb_knowledge`;
- a blank query;
- fields outside the approved projection;
- title-based queries.

**Step 2: Write failing sequence tests**

Add an offline scenario where:

1. Resolver returns `ServiceNowKB63`.
2. Maker confirms.
3. Broad scoped searches discover topics.
4. Targeted search returns one `sys_id`, one article number, and one unmapped
   hit.
5. MCP fetches only the two mapped articles.
6. The unmapped hit is reported.
7. Eval artifact write happens only after both successful fetches.

Assert call ordering:

```python
assert resolve_index < confirm_index < graph_search_index
assert graph_search_index < servicenow_fetch_index < write_index
```

Add scenarios for Graph permission failure offering local mode, MCP auth
failure stopping without writes, and an individual article fetch failure
continuing with the remaining mapped subset.

**Step 3: Run tests to verify they fail**

Run:

```powershell
py -3.12 -m pytest tests/mcp/evaluations/test_curator_skill_orchestration.py -k "servicenow_live" -v
```

Expected: FAIL until the fake contracts and orchestration assertions exist.

**Step 4: Implement the minimal fake contracts**

Keep the tests offline and synthetic. Do not enable host MCP discovery or real
credentials; `session_options()["mcp_servers"]` must remain `{}`.

**Step 5: Run the tests**

Run:

```powershell
py -3.12 -m pytest tests/mcp/evaluations/test_curator_skill_orchestration.py -k "connected_kb or servicenow_live" -v
```

Expected: PASS.

**Step 6: Commit**

```powershell
git add tests/mcp/evaluations/skill_eval.py tests/mcp/evaluations/test_curator_skill_orchestration.py
git commit -m "test(evaluations): cover ServiceNow live grounding"
```

Include the repository-required Copilot co-author trailer.

### Task 7: Run focused and regression validation

**Files:**
- No production changes expected.

**Step 1: Run focused Graph and search tests**

```powershell
py -3.12 -m pytest tests/flightcheck/test_graph_client.py tests/flightcheck/test_graph_connection_resolver.py tests/flightcheck/test_connected_kb_search.py tests/flightcheck/checks/test_graph_connector_kb.py -v
```

Expected: PASS.

**Step 2: Run CLI tests**

```powershell
py -3.12 -m pytest tests/scripts/test_connected_kb_context.py tests/scripts/test_search_connected_kb_cli.py tests/scripts/test_resolve_kb_connection_cli.py -v
```

Expected: PASS.

**Step 3: Run evaluation orchestration tests**

```powershell
py -3.12 -m pytest tests/scripts/test_evaluation_curator_routing.py tests/mcp/evaluations/test_curator_skill_orchestration.py -v
```

Expected: PASS.

**Step 4: Run the existing connected-KB regression set**

```powershell
py -3.12 -m pytest tests/scripts/test_kb_connection_resolver.py tests/scripts/test_curator_vendored_files.py tests/scripts/test_eval_curator_handoff.py tests/mcp/evaluations -v
```

Expected: PASS.

**Step 5: Run formatting/static checks used by the repository**

Run the existing repository commands that cover modified Python and Markdown
files. Do not introduce new tooling.

**Step 6: Inspect the final diff**

```powershell
git --no-pager diff --check
git --no-pager status --short
```

Expected: no whitespace errors and only intended files changed.

**Step 7: Commit any final test-only corrections**

If validation required corrections, commit them separately:

```powershell
git add <corrected-files>
git commit -m "test(evaluations): complete live KB retrieval coverage"
```

Include the repository-required Copilot co-author trailer.
