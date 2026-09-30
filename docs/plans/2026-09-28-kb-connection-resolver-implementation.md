# KB Connection Resolver — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use
> `development/reference/executing-plans-guide.md` to implement this plan
> task-by-task.

**Goal:** Give the eval curator's connected-KB mode a resolver that
programmatically determines which Graph-connector knowledge source(s) (e.g.
ServiceNow, SharePoint) are bound to the active agent — via the existing,
verified `PVAClient`/`botcomponents` lookup — and always confirms the
resolved connection with the maker before any grounding search runs. See
`docs/plans/2026-09-28-kb-connection-resolver-design.md` for the settled
design.

**Architecture:** New `scripts/flightcheck/kb_connection_resolver.py`
(resolution logic, reusing `PVAClient.get_knowledge_sources()`,
`_filter_graph_connector_sources()`, and `_connector_reference()` from
`scripts/flightcheck/checks/graph_connector_kb.py` — no reimplementation). New
CLI shim `scripts/resolve_kb_connection.py` (JSON in/out, same deterministic-
check pattern as `scripts/eval_curator_handoff.py`). `curate/SKILL.md`'s
connected-KB branch is updated to call the shim before curator Step 3b and
gate on maker confirmation. The vendored `curator/curate-evals.md` stays
byte-identical.

**Tech stack:** Python 3.12, pytest, markdown skill files (CRLF).

**Branch:** continues on `feature/eval-curator-direct-integration` (stacked on
the connected-KB-mode work, PR #358). CRLF-native repo — every file written
programmatically must be CRLF (`sed -i 's/\r*$/\r/'` after Write).

**Grounded facts used below** (confirmed by reading the actual source, not
assumed):

- The client class is `PVAClient` (capital V-A), defined in
  `scripts/flightcheck/pva_client.py`. `is_configured` is a `@property`, not a
  method — call sites use `pva.is_configured`, not `pva.is_configured()`.
- `PVAClient(tenant_id, env_url)` is constructed with `tenant_id` and
  `env_url` sourced from `.local/config.json`'s `dataverseEndpoint` (see
  `scripts/flightcheck/cli.py:433,849,1359`) and `discover_tenant(env_url)`.
  `env_url` must then be authenticated via `pva.authenticate()` before
  `get_knowledge_sources()` will do anything (`is_configured` depends on the
  token/gateway/bap-env-id all being discovered during `authenticate()`).
- `bot_id` comes from `config.get("agent", {}).get("botId")` (see
  `scripts/flightcheck/checks/graph_connector_kb.py:108`).
- `_filter_graph_connector_sources` and `_connector_reference` are module-
  level functions in `scripts/flightcheck/checks/graph_connector_kb.py`
  (lines ~603, ~614), not methods on `PVAClient`.
- `auth.load_config()` calls `sys.exit(1)` on a missing/mismatched config —
  unsuitable to call directly from a library function that must return a
  structured error instead of killing the process. The resolver module reads
  `.local/config.json` itself (mirroring `auth.load_config()`'s path
  handling) rather than calling `load_config()`, so it can convert failures
  into a `status: "error"` result instead of a process exit.

---

## Task 1: Resolver module + unit tests (RED → GREEN)

**Files:**

- New: `solutions/ess-maker-skills/scripts/flightcheck/kb_connection_resolver.py`
- New: `tests/scripts/test_kb_connection_resolver.py`

**Step 1: Write failing unit tests first.** Cover, using a fake/mock
`PVAClient`-shaped object (do not hit the network):

- `resolve_bound_connections`: zero `KnowledgeSourceComponent` entries →
  `status="none_bound"`, empty `connections`.
- One Graph-connector source (`configuration.source.$kind ==
  "GraphConnectorSearchSource"` with a `connectionName`) → `status="ok"`,
  one entry with that `connectionName` and its `state`/`status` fields
  passed through.
- Multiple Graph-connector sources → `status="ok"`, multiple entries,
  order preserved.
- Non-Graph-connector sources (e.g. native SharePoint, no `$kind` match) are
  filtered out and do not appear in `connections`.
- `connectionName` missing but `connectionId` present as a dict
  (`{"$kind": "EnvironmentVariableReference", "schemaName": "..."}`) → falls
  back per existing `_connector_reference()` semantics (call the real
  `_connector_reference` from `graph_connector_kb.py`, don't reimplement).
- `pva.is_configured` is `False` (or `pva` is `None`) → `status="error"`,
  with a message naming what's missing (mirrors the
  `PVAClient.authenticate()` / `is_configured` failure modes documented in
  `scripts/flightcheck/AGENTS.md`).
- `pva.get_knowledge_sources(bot_id)` raises → caught, `status="error"` with
  the exception message surfaced (do not double-wrap/hide it).

Run — expect FAIL (module doesn't exist yet).
`cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_kb_connection_resolver.py -v`

**Step 2: Implement `kb_connection_resolver.py`.**

```python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Resolve which Graph-connector knowledge source(s) are bound to an agent."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from flightcheck.checks.graph_connector_kb import (
    _connector_reference,
    _filter_graph_connector_sources,
)


@dataclass
class BoundConnection:
    connection_name: str
    state: str | None
    status: str | None


@dataclass
class ResolutionResult:
    status: str  # "ok" | "none_bound" | "error"
    connections: list[BoundConnection]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "connections": [asdict(c) for c in self.connections],
            **({"error": self.error} if self.error else {}),
        }


def resolve_bound_connections(pva, bot_id: str) -> ResolutionResult:
    """Resolve Graph-connector knowledge sources bound to ``bot_id``.

    ``pva`` is an authenticated ``PVAClient`` (or a compatible test double).
    Resolution only — never runs a grounding search itself.
    """
    if pva is None or not getattr(pva, "is_configured", False):
        return ResolutionResult(
            status="error",
            connections=[],
            error=(
                "Copilot Studio (Island Gateway) is not authenticated/"
                "configured. Run flightcheck or /setup to establish PVA "
                "access, then retry."
            ),
        )
    if not bot_id:
        return ResolutionResult(
            status="error",
            connections=[],
            error="No agent botId found in .local/config.json. Run /setup first.",
        )

    try:
        knowledge_sources = pva.get_knowledge_sources(bot_id)
    except Exception as exc:  # surfaced, not swallowed
        return ResolutionResult(status="error", connections=[], error=str(exc))

    gc_sources = _filter_graph_connector_sources(knowledge_sources)
    if not gc_sources:
        return ResolutionResult(status="none_bound", connections=[])

    connections = []
    for src in gc_sources:
        name = _connector_reference(src)
        if not name:
            continue
        connections.append(
            BoundConnection(
                connection_name=name,
                state=src.get("state"),
                status=src.get("status"),
            )
        )

    if not connections:
        return ResolutionResult(status="none_bound", connections=[])

    return ResolutionResult(status="ok", connections=connections)
```

Adjust field names (`state`/`status`) to whatever
`KnowledgeSourceComponent` actually exposes once you inspect a real sample in
`graph_connector_kb.py`'s existing test fixtures — use those fixtures'
shape directly rather than guessing new field names.

**Step 3: Run tests — expect PASS.** Iterate until green.

**Step 4: Commit.**
`test(evaluations): add KB connection resolver with unit tests` with the
Sonnet trailer.

---

## Task 2: CLI shim (RED → GREEN)

**Files:**

- New: `solutions/ess-maker-skills/scripts/resolve_kb_connection.py`
- New: `tests/scripts/test_resolve_kb_connection_cli.py`

**Step 1: Write failing tests for the shim's JSON contract**, invoking the
script as a subprocess (matching how `eval_curator_handoff.py` is tested) or
via its internal `main()`/argument-parsed entry point with a monkeypatched
`.local/config.json` path and a fake `PVAClient`:

- No `.local/config.json` present → prints
  `{"status": "error", "connections": [], "error": "..."}` (mentions running
  `/setup`), exits non-zero.
- Config present, agent authenticates, zero bound sources →
  `{"status": "none_bound", "connections": []}`, exits 0.
- Config present, one bound source → `{"status": "ok", "connections": [{...}]}`,
  exits 0.
- Config present, `PVAClient.authenticate()` raises (network/auth failure) →
  `{"status": "error", ...}` with the failure surfaced, exits non-zero.

Run — expect FAIL.

**Step 2: Implement the shim.** Load `.local/config.json` directly (path
`.local/config.json` relative to the solution root, same as `auth.py`'s
`LOCAL_STATE_DIR` convention) without calling `auth.load_config()` (which
`sys.exit`s), so a missing/malformed config becomes a JSON `error` result
instead of an uncaught exit. Steps:

1. Read config; missing/malformed → JSON error result, exit 1.
2. Extract `env_url = config.get("dataverseEndpoint", "")`,
   `bot_id = config.get("agent", {}).get("botId")`.
3. `tenant_id = discover_tenant(env_url)` (reuse `auth.discover_tenant`,
   same call pattern as `cli.py`).
4. Construct `PVAClient(tenant_id, env_url)`, call `pva.authenticate()`
   inside a `try`; on failure → JSON error result, exit 1.
5. Call `resolve_bound_connections(pva, bot_id)`; print `result.to_dict()` as
   JSON; exit 0 if `status != "error"`, else exit 1.

**Step 3: Run — expect PASS.**

**Step 4: Commit.** `feat(evaluations): add resolve_kb_connection CLI shim`
with the Sonnet trailer.

---

## Task 3: Wire the confirmation gate into `curate/SKILL.md` (connected-KB branch)

**Files:**

- Modify:
  `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py`

**Step 1: Add/adjust a doc-assertion test** asserting the connected-KB
branch of the wrapper:

- Runs the `resolve_kb_connection` CLI shim before curator Step 3b.
- On `status="error"` or `status="none_bound"`, stops and reports the exact
  reason — asserts the wrapper text does **not** offer an automatic
  local-file fallback in this case.
- On `status="ok"` with exactly one connection, shows it and requires maker
  confirmation before proceeding.
- On `status="ok"` with multiple connections, lists all and requires the
  maker to pick one or more.

Run — expect FAIL.

**Step 2: Edit `curate/SKILL.md`'s connected-KB mode section** to add this
resolver-and-confirm step between mode selection and the hand-off into the
vendored curator body's Step 3b, per the design's data-flow section. Keep
every existing wrapper responsibility (host params, validator path,
lifecycle handoff) unchanged — this only inserts the resolve+confirm gate
ahead of the existing "hand off to curator body" step.

**Step 3: CRLF; run the routing tests — expect PASS.** Run the full routing
file to confirm no regressions. prettier/markdownlint best-effort.

**Step 4: Commit.**
`feat(evaluations): confirm resolved KB connection before connected-KB curation`
with the Sonnet trailer.

---

## Task 4: Full sweep + push

**Step 1:** Run the whole curator/eval suite:

```powershell
cd solutions/ess-maker-skills
py -3.12 -m pytest `
  ../../tests/scripts/test_kb_connection_resolver.py `
  ../../tests/scripts/test_resolve_kb_connection_cli.py `
  ../../tests/scripts/test_evaluation_curator_routing.py `
  ../../tests/mcp/evaluations/test_curator_skill_orchestration.py `
  ../../tests/scripts/test_curator_vendored_files.py `
  ../../tests/scripts/test_eval_curator_handoff.py `
  -v
```

Expect all green.

**Step 2:** Confirm the vendored body is still byte-identical
(`git diff` shows no change to `curator/curate-evals.md`).

**Step 3:** Confirm all new commits carry the
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer.

**Step 4:** Push to `personal` and let PR #358 update (these commits stack
on the same branch). Report the updated PR.

---

## Notes for the executor

- Vendored `curator/curate-evals.md` must NOT be edited in any task.
- Do not call `auth.load_config()` from the resolver or the CLI shim — it
  exits the process on failure, which defeats the JSON-error contract these
  components need. Read `.local/config.json` directly instead.
- Verify `KnowledgeSourceComponent` field names (`state`, `status`, etc.)
  against `graph_connector_kb.py`'s existing test fixtures before finalizing
  `BoundConnection`'s fields — don't invent field names not present in real
  payloads.
- CRLF on every file. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`
  trailer on every commit.
