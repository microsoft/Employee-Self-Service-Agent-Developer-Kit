# Live Agent Instructions + Source-URL Citation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use
> `development/reference/executing-plans-guide.md` to implement this plan
> task-by-task.

**Goal:** Implement the two eval-curator wrapper modifications settled in
`docs/plans/2026-10-04-live-instructions-and-citation-design.md`: (1) resolve
the agent's live instructions from the bound agent instead of prompting for a
file, and (2) cite the source document URL on positive/boundary connected-KB
cases plus conditional graded citation-adherence cases.

**Architecture:** New `scripts/flightcheck/agent_instructions_resolver.py`
(resolution logic) and CLI shim `scripts/resolve_agent_instructions.py` — both
near-clones of the KB connection resolver pair
(`flightcheck/kb_connection_resolver.py` + `scripts/resolve_kb_connection.py`),
reusing `load_connected_kb_context`, `PVAClient`, and the native
`AgentBuilderClient` auth paths. `curate/SKILL.md`'s Step 1 is rewired to call
the shim and gate on maker confirmation; Step 3 gains host params and
instructions for citation surfacing. The vendored `curator/curate-evals.md`
stays byte-identical.

**Tech stack:** Python 3.12, pytest, markdown skill files (CRLF).

**Branch:** continues on `feature/eval-curator-direct-integration` (stacked on
PR #358). CRLF-native repo — every file written programmatically must be CRLF
(`sed -i 's/\r*$/\r/'` after Write).

**Grounded facts** (confirmed by reading source):

- `resolve_kb_connection.py` resolves `bot_id` + auth via
  `load_connected_kb_context(discover_tenant_fn=discover_tenant)`, then either
  constructs `PVAClient(tenant_id, dataverse_endpoint)` + `authenticate()`
  (Island Gateway path) or the native `AgentBuilderClient` path, and calls a
  resolver function with `(client, context.bot_id)`. Clone this exactly.
- `PVAClient.get_knowledge_sources(bot_id)` and `get_dialog_components(bot_id)`
  both POST to the same `.../bots/{bot_id}/content/botcomponents` endpoint and
  filter `data["botComponentChanges"][*]["component"]` by `$kind`. The
  instruction-bearing component is in that same changeset under a different
  `$kind` — **not yet extracted anywhere in the repo.**
- `check_eval_artifacts.py` validates only that required fields are present and
  ignores unknown keys — `extensionData.sourceUrl` and an extra CSV column pass
  without any validator change.
- Test fixtures for the KB resolver live in
  `tests/scripts/test_kb_connection_resolver.py` (fake duck-typed client,
  `_gc_knowledge_source` builder). Mirror this style.
- Attribution: every commit ends with
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

## Task 0: Pin the instruction component shape (SPIKE — no commit)

Before writing the resolver, determine the `$kind` and field path that carries
the agent's instruction text in the `botComponentChanges` changeset. Do **not**
guess.

**Steps:**

1. Search existing flightcheck test fixtures / sample payloads for a captured
   `botComponentChanges` response:
   `grep -rln "botComponentChanges\|GptComponent\|instructions" tests/ scripts/`.
2. If a real payload exists, identify the component whose body holds the system
   prompt / persona text (likely a `GptComponent` or similarly named `$kind`
   with an `instructions`/`description` field — **verify, do not assume**).
3. If no fixture exists, capture one against a configured agent (the maker's
   `.local/config.json`) by extending a throwaway script that calls
   `PVAClient.get_knowledge_sources`'s sibling POST and dumps raw
   `botComponentChanges` `$kind` values, OR document that the resolver filter
   must be confirmed against a live payload during Task 1 before finalizing.
4. Record the confirmed `$kind` + field path in a comment at the top of Task 1's
   module. This is the single fact the rest of the plan depends on.

**No commit** — this is a discovery step feeding Task 1.

---

## Task 1: Resolver module + unit tests (RED → GREEN)

**Files:**

- New: `solutions/ess-maker-skills/scripts/flightcheck/agent_instructions_resolver.py`
- New: `tests/scripts/test_agent_instructions_resolver.py`

**Step 1: Write failing unit tests first.** Using a fake duck-typed client
(mirroring `test_kb_connection_resolver.py`'s `_FakePVA`), cover:

- One instruction component present with non-empty text → `status="ok"`,
  `instructions` equal to that text.
- No instruction component in the changeset → `status="not_found"`, empty
  instructions, a message naming what was looked for.
- Instruction component present but empty/whitespace text → `status="not_found"`
  (an empty prompt is not usable grounding).
- `client.is_configured` is `False` (or client is `None`) → `status="error"`
  with a message naming what's missing.
- The client's component fetch raises → caught, `status="error"` with the
  exception message surfaced (not double-wrapped).
- `bot_id` empty → `status="error"` naming the missing botId.

Run — expect FAIL (module doesn't exist).
`cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_agent_instructions_resolver.py -v`

**Step 2: Implement `agent_instructions_resolver.py`.** Model it on
`kb_connection_resolver.py`:

- `@dataclass ResolutionResult` with `status: str`,
  `instructions: str | None`, `error: str | None = None`, and a `to_dict()`
  that omits `error` when falsy.
- `resolve_agent_instructions(client, bot_id) -> ResolutionResult`:
  - guard `client is None or not getattr(client, "is_configured", False)` →
    `error`.
  - guard empty `bot_id` → `error`.
  - fetch the changeset inside `try/except Exception` → `error` on raise.
  - filter for the instruction component's confirmed `$kind` (from Task 0),
    extract the instruction text; missing or whitespace-only → `not_found`;
    otherwise `ok`.

Use the component `$kind`/field pinned in Task 0 — do not invent field names.

**Step 3: Run tests — expect PASS.** Iterate until green.

**Step 4: Commit.**
`test(evaluations): add agent instructions resolver with unit tests` with the
Sonnet trailer.

---

## Task 2: CLI shim (RED → GREEN)

**Files:**

- New: `solutions/ess-maker-skills/scripts/resolve_agent_instructions.py`
- New: `tests/scripts/test_resolve_agent_instructions_cli.py`

**Step 1: Write failing tests** for the shim's JSON contract, mirroring the KB
shim's test style (subprocess or monkeypatched `main()`):

- No `.local/config.json` / bad context → `{"status":"error","instructions":
  null,"error":"..."}` (mentions `/setup`), exits non-zero.
- Config present, resolves one instruction component →
  `{"status":"ok","instructions":"..."}`, exits 0.
- Config present, no instruction component → `{"status":"not_found",...}`,
  exits 0.
- `authenticate()` / native auth raises → `{"status":"error",...}` surfaced,
  exits non-zero.

Run — expect FAIL.

**Step 2: Implement the shim** as a near-clone of `resolve_kb_connection.py`:
reuse `load_connected_kb_context`, the Island Gateway `PVAClient` branch and the
native `AgentBuilderClient` branch verbatim, swap the final call to
`resolve_agent_instructions(client, context.bot_id)`, print `result.to_dict()`
as JSON, exit `0 if result.status != "error" else 1`. Never call
`auth.load_config()`.

For the native `AgentBuilderClient` branch, the resolver needs the same
`botComponentChanges` changeset — reuse or extend the existing
`_AgentBuilderKnowledgeSourceClient` wrapper so the agent-instructions resolver
reads components through the same contract (do not duplicate the fetch).

**Step 3: Run — expect PASS.**

**Step 4: Commit.** `feat(evaluations): add resolve_agent_instructions CLI shim`
with the Sonnet trailer.

---

## Task 3: Wire resolve+confirm into `curate/SKILL.md` Step 1

**Files:**

- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py`

**Step 1: Add failing doc-assertion tests** asserting Step 1:

- Runs `scripts/resolve_agent_instructions.py` and no longer asks the maker for
  an agent-instructions file.
- On `status="error"`/`"not_found"`, stops and reports the exact reason — the
  wrapper text must **not** offer a file-prompt fallback.
- On `status="ok"`, shows the resolved instructions and requires explicit maker
  confirmation before proceeding.

Run — expect FAIL.

**Step 2: Edit `SKILL.md` Step 1.** Replace bullet 3 ("the agent-instructions
file is required… ask exactly one question") with the resolve+confirm step.
Keep the mode selection (bullets 1–2) and every other wrapper responsibility
unchanged. Mirror the structure and tone of the existing "Resolve and confirm
the connected knowledge base" section in Step 3.

**Step 3: CRLF; run routing tests — expect PASS.** Run the full routing file for
regressions. prettier/markdownlint best-effort.

**Step 4: Commit.**
`feat(evaluations): resolve and confirm live agent instructions in curate wrapper`
with the Sonnet trailer.

---

## Task 4: Citation layer in `curate/SKILL.md`

**Files:**

- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py`

**Step 1: Decide the surfacing mechanism.** Re-read the vendored Step 6. If the
host contract can carry a citation column/field instruction without an edit to
the vendored body, use host params (`hostCitationColumn=Source URL`,
`hostCaseSourceField=sourceUrl`) added to Step 3's parameter block. If Step 6's
"these exact columns" wording is too prescriptive, use a **wrapper
post-processing step** after the curator handoff that annotates the written
`.mcs.yml`/CSV artifacts. Pick whichever keeps `curate-evals.md` byte-identical.
Document the choice in `SKILL.md`.

**Step 2: Add failing doc-assertion tests** asserting:

- `sourceUrl`/`Source URL` populated for **positive and boundary** cases in
  connected-KB mode, from each grounded hit's `sourceUrl`.
- Blank for **negative** cases and for **all local-file** cases.
- Graded citation-adherence cases (2b) are generated **only when** the resolved
  instructions mandate citing sources, drawn from positive/boundary grounding
  only, with `expectedOutput` describing citation as observable behavior and
  **not** naming a backend (preserving the vendored Step 4 rule).

Run — expect FAIL.

**Step 3: Edit `SKILL.md`** to add the citation surfacing and the conditional-
graded-case instructions, per the mechanism chosen in Step 1. Do not weaken any
confirmation/validation gate; do not reinterpret the curator's generation rules.

**Step 4: CRLF; run routing tests — expect PASS.**

**Step 5: Commit.**
`feat(evaluations): cite source URLs and add conditional citation eval cases`
with the Sonnet trailer.

---

## Task 5: Full sweep + push

**Step 1:** Run the curator/eval suite:

```powershell
cd solutions/ess-maker-skills
py -3.12 -m pytest `
  ../../tests/scripts/test_agent_instructions_resolver.py `
  ../../tests/scripts/test_resolve_agent_instructions_cli.py `
  ../../tests/scripts/test_evaluation_curator_routing.py `
  ../../tests/scripts/test_kb_connection_resolver.py `
  ../../tests/scripts/test_resolve_kb_connection_cli.py `
  ../../tests/mcp/evaluations/test_curator_skill_orchestration.py `
  ../../tests/scripts/test_curator_vendored_files.py `
  ../../tests/scripts/test_eval_curator_handoff.py `
  -v
```

Expect all green.

**Step 2:** Confirm the vendored body is byte-identical
(`git diff` shows no change to `curator/curate-evals.md`).

**Step 3:** Confirm all new commits carry the
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer.

**Step 4:** Push to `personal` and let PR #358 update (these commits stack on
the same branch). Report the updated PR.

---

## Notes for the executor

- Vendored `curator/curate-evals.md` must NOT be edited in any task.
- Do not call `auth.load_config()` from the resolver or the CLI shim — it exits
  the process on failure, defeating the JSON-error contract.
- Task 0's confirmed instruction-component `$kind`/field is a hard prerequisite
  for Task 1 — do not finalize the resolver filter against a guessed field name.
- Citation applies to positive/boundary cases only, never negatives. `sourceUrl`
  is blank for negatives and for all local-file cases.
- Graded citation cases (2b) are generated only when the resolved instructions
  require citing sources.
- CRLF on every file. Sonnet trailer on every commit.
