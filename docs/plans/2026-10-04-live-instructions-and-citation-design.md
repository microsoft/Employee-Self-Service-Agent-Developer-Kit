# Live Agent Instructions + Source-URL Citation — Design

## Summary

Two wrapper-only modifications to the ESS Maker Kit eval curator route
(`solutions/ess-maker-skills/src/skills/evaluations/curate/`). Both respect the
standing rules: the vendored curator body (`curator/curate-evals.md`) stays
byte-identical, and the wrapper never reimplements curator generation,
validation, or lifecycle logic.

1. **Live agent instructions.** Replace `SKILL.md` Step 1's "ask for an
   agent-instructions file" prompt with a resolve-from-bound-agent step that
   mirrors the existing KB connection resolver. The wrapper pulls the agent's
   actual instructions from Copilot Studio via the `botcomponents` endpoint,
   using `agent.botId` from `.local/config.json`. On any failure it stops and
   reports — no silent fallback to prompting for a file.

2. **Source-URL citation (two layers).** Each generated test case can cite the
   URL of the document it was grounded in, surfaced as both a new CSV column and
   a `sourceUrl` field in the `.mcs.yml` `extensionData`. A graded citation
   requirement is added conditionally, only when the resolved agent instructions
   actually mandate citing sources.

## Motivation

- Today both the wrapper (`SKILL.md` Step 1) and the vendored curator (Step 2)
  require the maker to supply an agent-instructions **file** by hand. The
  agent's real instructions already live in Copilot Studio and are reachable
  through the same authenticated `botcomponents` endpoint `PVAClient` already
  uses for `get_knowledge_sources`/`get_dialog_components`. Resolving them
  programmatically removes a manual, error-prone step and guarantees the evals
  are grounded in the agent's *actual* configured instructions.
- Generated test cases currently record no provenance. Citing the source
  document's URL gives every case a traceable origin and — when the agent is
  built to cite sources — lets the eval actually test that citation behavior.

## Decisions (settled)

1. **Instructions source:** pull live from the bound agent (`agent.botId` →
   `botcomponents`), no file prompt.
2. **Resolve failure:** stop and report the exact reason, consistent with the KB
   connection resolver. No silent fallback to prompting for a file.
3. **Citation surface:** a new `Source URL` CSV column **and** a `sourceUrl`
   field in each case's `.mcs.yml` `extensionData`.
4. **Local-file mode:** citation is **blank** — local documents have paths, not
   URLs, and the design will not fabricate one.
5. **Vendored body:** stays byte-identical. Citation is layered via the host
   integration contract (or a wrapper post-process), never a body edit.
6. **Citation role:** metadata for all applicable cases, **plus** conditional
   graded citation-adherence cases generated only when the resolved live
   instructions require citing sources. If the agent's instructions do not
   mandate citation, no graded citation cases are generated — never test a
   behavior the agent was not told to exhibit.
7. **Negative cases:** the citation requirement applies to **positive and
   boundary cases only, never negatives.** A negative case tests that the agent
   declines when the knowledge source does not cover something — there is no
   source document to cite, and asserting citation would contradict the expected
   "I don't know" behavior. `sourceUrl` is blank for negatives even in
   connected-KB mode; graded citation cases are drawn only from
   positive/boundary grounding.

## Non-goals

- Editing the vendored curator body or its existing test coverage.
- A file-prompt fallback when live instruction resolution fails.
- Citing a source for local-file mode or for negative cases.
- Grading citation when the agent's instructions do not require it.

## Modification 1 — resolve live agent instructions

**New resolver module + CLI shim**, cloning the KB-connection-resolver pattern:

- `scripts/flightcheck/agent_instructions_resolver.py` —
  `resolve_agent_instructions(client, bot_id) -> ResolutionResult`. Fetches the
  `botComponentChanges` changeset (the same one the KB resolver reads), filters
  for the component carrying the agent's instruction text, and returns
  `{status: "ok"|"not_found"|"error", instructions: "...", error?: "..."}`.
- `scripts/resolve_agent_instructions.py` — thin CLI shim, a near-clone of
  `resolve_kb_connection.py`: reuses `load_connected_kb_context`, both auth
  paths (Island Gateway `PVAClient` and native `AgentBuilderClient`), prints one
  JSON result, exits 0 on `ok`/`not_found` and 1 on `error`. Never calls
  `auth.load_config()` (which `sys.exit`s), so every failure surfaces as JSON.

**Wrapper change — `SKILL.md` Step 1:** replace bullet 3 ("ask exactly one
question for the agent instructions") with: run
`py -3.12 scripts/resolve_agent_instructions.py`, parse the single JSON result.

- `status == "ok"` → use the returned instruction text as the curator's
  agent-instructions input; show it to the maker and require explicit
  confirmation before proceeding (consistent with the KB connection confirmation
  gate).
- `status == "not_found"` / `"error"` → stop and report the exact reason; no
  file-prompt fallback. The maker fixes setup (e.g. `/setup`) and retries.

**Known unknown (for the plan):** the exact `$kind` of the instruction-bearing
component. No existing code extracts it, so the first implementation task must
inspect a real `botComponentChanges` payload (or an existing flightcheck
fixture) to pin the field before finalizing the filter — the same way the KB
resolver's `BoundConnection` fields were verified against real fixtures rather
than guessed.

## Modification 2 — source-URL citation

The CSV columns and `.mcs.yml` shape are defined inside the vendored Step 6,
which stays byte-identical. The sanctioned extension point the vendored body
honors is the **host integration contract** (`hostOutputRoot`,
`hostLifecycleHandoff`). The wrapper adds a new host parameter (e.g.
`hostCitationColumn=Source URL` / `hostCaseSourceField=sourceUrl`) and, through
the host-contract section of `SKILL.md`, instructs the curator to populate:

**Layer 2a — traceability metadata (always written):**

- `extensionData.sourceUrl` per case + a `Source URL` CSV column.
- Populated from each grounded hit's `sourceUrl` for **positive/boundary cases
  in connected-KB mode**.
- **Blank** for negatives and for all local-file cases.
- Pure metadata — `CompareMeaningGrader` only grades `expectedOutput` and never
  reads `extensionData`, so this adds no grading dimension and leaves the
  vendored Step 4 "no backend names in expectedOutput" rule intact.

**Layer 2b — conditional graded citation cases:**

- Generated **only when** modification 1's resolved instructions mandate citing
  sources.
- Drawn from **positive/boundary grounding only, never negatives.**
- `expectedOutput` describes citation as **observable behavior** ("the agent
  should point the user to where the answer came from") — no backend name,
  preserving the vendored Step 4 rule — graded by CompareMeaning like any other
  case.
- If the agent's instructions do not require citation, none are generated.

**Validator:** `check_eval_artifacts.py` needs no change — it only checks
required fields are present and ignores extra keys, so `sourceUrl` and the extra
CSV column pass as-is.

**Constraint to resolve in the plan:** whether the vendored Step 6 can be
*instructed via the host contract* to emit the new column/field, or whether its
"these exact columns" wording is too prescriptive to bend without a body edit.
If it is, the fallback is a **wrapper post-processing step**: after the curator's
hosted handoff, the wrapper annotates the already-written `.mcs.yml`/CSV
artifacts with citations derived from the grounding it observed. Either way the
vendored file stays untouched. The plan evaluates both and picks the one that
does not edit the vendored body.

## Files

**New:**

- `scripts/flightcheck/agent_instructions_resolver.py`
- `scripts/resolve_agent_instructions.py`
- `tests/scripts/test_agent_instructions_resolver.py`
- `tests/scripts/test_resolve_agent_instructions_cli.py`

**Modified:**

- `src/skills/evaluations/curate/SKILL.md` — Step 1 (resolve+confirm
  instructions), Step 3 host params (citation column/field), citation surfacing
  and conditional-case instructions.
- `tests/scripts/test_evaluation_curator_routing.py` — doc-assertion tests for
  the new wrapper branches.

**Never touched:**

- `curator/curate-evals.md` (byte-identical)
- `curator/check_eval_artifacts.py` (no change needed)

## Testing

- **Resolver unit tests** (fake client, no network): `ok` with instruction text;
  `not_found` when no instruction component; `error` when unconfigured;
  exception surfaced, not swallowed. Mirrors `test_kb_connection_resolver.py`.
- **CLI shim tests:** JSON shape + exit code per status; missing config → JSON
  error (not process exit).
- **Routing doc-assertions on `SKILL.md`:** Step 1 runs the resolver before
  proceeding and no longer prompts for a file; `error`/`not_found` stops with no
  file-prompt fallback; `ok` requires confirmation. Citation: `sourceUrl`/CSV
  column populated for positive/boundary connected-KB cases, blank for negatives
  and local-file; 2b graded cases generated only when instructions mandate
  citation.

## Task breakdown (RED→GREEN)

1. Agent-instructions resolver + unit tests — pin the instruction component's
   `$kind` from a real payload/fixture, then TDD the module.
2. CLI shim + tests — clone `resolve_kb_connection.py` structure.
3. Wire resolve+confirm into `SKILL.md` Step 1 + routing tests.
4. Citation layer (2a + 2b) in `SKILL.md` via host contract — decide
   host-param-instruction vs. wrapper post-process (whichever keeps the vendored
   body untouched) + routing tests.
5. Full sweep — curator/eval suite green, `git diff` confirms
   `curate-evals.md` byte-identical, push to `personal`, PR #358 updates.

Continues on `feature/eval-curator-direct-integration` (stacked on PR #358),
CRLF-native. Every commit carries the Sonnet trailer.

## Acceptance criteria

When a maker runs the curate route, the wrapper resolves the agent's live
instructions from the bound agent (stopping with a specific reason if it
cannot), confirms them with the maker, and grounds instruction-adherence cases
in that resolved text instead of a hand-supplied file. Generated positive and
boundary cases in connected-KB mode carry the source document's URL in both the
CSV and the `.mcs.yml` metadata; negatives and local-file cases leave it blank.
When — and only when — the resolved instructions require citing sources, the
eval additionally includes graded citation-adherence cases. The vendored curator
body remains byte-identical throughout.
