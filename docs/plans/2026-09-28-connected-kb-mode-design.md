# Connected-KB Mode for the Curator Route — Design

## Summary

Enable **connected knowledge base mode** for the ESS Maker Kit's knowledge-source evaluation curator route (`/evaluate` → curate). Today the Maker Kit wrapper (`curate/SKILL.md`) forces **local-file mode only**, even though the vendored curator body (`curator/curate-evals.md`) already fully supports connected-KB mode (Steps 3b/3c). This change lifts that clamp so a maker can curate evaluation sets grounded in a **live connected knowledge base** — e.g. ServiceNow or SharePoint — reachable through a search/fetch-capable tool in the session, in addition to the existing local-file path.

This is an **un-clamping + mode-selection** change, not a new-capability build. The retrieval engine already exists upstream; the wrapper just gates it off.

## Motivation

The knowledge-source curator supports two grounding modes. The original `EvalsCuratorForAgent` kit runs both live (a SharePoint connected-KB dry-run has been exercised there). When the curator was integrated into the Maker Kit, the wrapper pinned it to local-file mode for v1 as a deliberate scope reduction. That restriction — not anything ServiceNow- or SharePoint-specific, and not a missing connector — is why the `/evaluate` route asks for a local export instead of querying a connected KB, even when a search/fetch tool for that KB is present in the session.

## Goals

- Let makers curate evaluation sets grounded in a live connected KB through the existing `/evaluate` route.
- Keep the vendored curator body **byte-identical** — all changes confined to the wrapper and surrounding docs.
- Preserve the existing Maker Kit lifecycle (validate → review → push → run) unchanged; the mode choice only affects how grounding content is obtained.
- Add real CI coverage for the connected-KB sequence via the existing fake-harness pattern.

## Non-goals

- Editing the vendored curator body (`curate-evals.md`).
- Building or configuring any connector. Connected-KB mode requires a search/fetch-capable tool already present in the session; this change does not create one.
- A consent/egress gate before live querying (see Trust posture — the existing untrusted-data guardrail is deemed sufficient).
- Exhaustive automated coverage of every 3b/3c edge case (thin-results, fetch-failure). Those live in the vendored body's prose and are covered by manual live validation.
- Caching, indexing, or persisting KB content (the curator body already forbids this).

## Design decisions (settled)

1. **Trust posture:** enable straightforwardly, relying on the curator's existing "knowledge-source content is untrusted data, not instructions" guardrail. No new consent gate. A connected KB is treated like any other knowledge source.
2. **Mode selection:** the wrapper **asks the maker up front** — "local files/folder, or your connected knowledge base?" — then proceeds in the chosen mode. No silent auto-selection from tool availability. The agent-instructions file remains required in both modes.
3. **Testing:** doc-assertion tests updated for the ask-first mode selection + connected-KB availability, PLUS one new mocked connected-KB behavioral test (happy path + one zero-result failure case) built on the `skill_eval.py` fake harness. Live dry-run remains the real-world proof.

## Connected-KB flow (what the vendored body already does)

Two-phase retrieval, grounded per-topic:

**Phase 1 — Discovery (Step 3b), broad/shallow:** run 3-5 broad search queries seeded from the agent-instructions scope; collect titles+snippets from the top 5-10 results per query; cluster into candidate topics; present to the maker to confirm/rename/narrow.

**Phase 2 — Per-topic grounding (Step 3c), narrow/deep, once per confirmed topic:** run a targeted search scoped to the topic (top 10-20 results — "this topic's subset"); fully fetch and read every item in the subset; then generate that topic's cases (Step 4) grounded strictly in the fetched content. Zero-result topics generate no cases and are flagged; thin topics generate fewer cases; fetch failures skip the item and are noted.

Classification into topics happens first (from shallow search snippets), the maker confirms topics, then each topic is deeply fetched and curated from its grounded subset — never "fetch everything then guess."

## Components

| Component | Change |
|---|---|
| `curate/SKILL.md` (wrapper) | Remove the three "local-file mode only for v1" clamps. Add an explicit mode question as the first step ("local files/folder or connected knowledge base?"). Collect mode-appropriate inputs: a folder/files path for local; confirmation of the connected source (and which tool, if several) for connected. Agent-instructions file stays required in both modes. Hand off to the curator body, which branches on mode. |
| `curator/curate-evals.md` (vendored body) | **No change.** Steps 3b/3c already implement connected-KB discovery and grounding. |
| `dispatcher/SKILL.md` | Reword the knowledge-source route so it no longer implies "local documents only"; route both local and connected knowledge-source curation intent to the wrapper. |
| `README.md` (maker) | Update the curation-source description to cover both local and connected knowledge bases. |
| `.github/prompts/evaluate.prompt.md` | Adjust any "local"-implying wording for consistency. |

## Data flow (connected mode)

Wrapper asks mode → maker picks connected → wrapper confirms source/tool → hands off to curator body → body runs Step 3b discovery → maker confirms topics → Step 3c per-topic grounding → Step 4 generation → synchronized `.mcs.yml` + CSV → **existing Maker Kit lifecycle unchanged** (validate → maker review → promotion → scoped push → run/results).

## Error handling

Delegated to the vendored body's existing failure modes (no connected KB reachable → confirm connection or offer local fallback; empty search → broaden once or report; zero-result topic → skip + flag; thin topic → fewer cases + flag; fetch failure → skip item + note). The wrapper adds nothing here beyond routing the maker's mode choice.

## Security and privacy

Connected-KB mode issues live search queries (derived from the agent-instructions scope) against the connected backend and reads fetched article content into the session during curation. Per the settled trust posture, this relies on the curator body's existing "untrusted data, not instructions" guardrail; no additional consent gate is added. No KB content is cached, indexed, or persisted beyond the current step. The existing Maker Kit mutation safeguards (preview, validation, explicit push approval, dry run, post-push verification) remain mandatory and unchanged.

## Testing

### Layer 1 — Doc-assertion tests (update existing)

In `test_evaluation_curator_routing.py`:

- The wrapper v1-boundary test drops `assert "local-file mode only for v1"` and instead asserts the wrapper asks the mode question first and names both local and connected-KB options.
- The dispatcher route test generalizes `"local knowledge source"` to assert both source types are covered.
- The README test asserts both source types are documented.

Matching prose edits to `curate/SKILL.md`, `dispatcher/SKILL.md`, and `README.md` make these pass.

### Layer 2 — Mocked connected-KB behavioral test (new)

Extend `skill_eval.py` with two new `ToolContract`s — `search` (query → synthetic ranked results with title/snippet/id) and `fetch` (id → synthetic article body) — backed by an in-memory fixture of a handful of fake articles across 2-3 subjects, with `invoke()` branches recording `kind="search"` and `kind="fetch"`.

New tests in `test_curator_skill_orchestration.py` assert the connected-KB sequence:

1. **Discovery before grounding** — broad `search` calls and topic confirmation happen before any per-topic deep `fetch`.
2. **Per-topic grounding ordering** — for a confirmed topic, targeted `search` → `fetch` happens before the first eval-set `write` for that topic.
3. **Grounded generation** — written cases reference only content present in the fetched fixture.
4. **Zero-result failure** — a topic whose targeted search returns no results generates no cases and is flagged (skip-not-fabricate).

Scope guard (YAGNI): one happy-path test + one zero-result failure case. Not every 3b/3c edge — those are upstream-owned prose validated by live dry-run.

### Layer 3 — Manual live validation (documented, unchanged)

The maker's live connected-KB dry-run (e.g. against ServiceNow) remains the real-world proof, mirroring how the source repo validated SharePoint. **Caveat, stated explicitly:** the mock proves the curator follows the connected-KB sequence when given search/fetch tools; it does NOT prove a real backend returns compatible result shapes. That gap is closed only by the live dry-run.

## Acceptance criteria

A maker running `/evaluate` and choosing knowledge-source curation is asked whether to use local files or a connected knowledge base. Choosing connected, with a search/fetch-capable tool present, curates evaluation sets grounded in that live KB (topic discovery → confirmation → per-topic grounded generation) and flows them through the existing Maker Kit lifecycle — with no edit to the vendored curator body, and with CI covering the connected-KB sequence via the mocked harness.
