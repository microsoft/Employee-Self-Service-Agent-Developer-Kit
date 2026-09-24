# Planner — Phase 1: Research (grounding) — Microsoft Learn *and* the kit's own skills

Ground the Plan in **what ESS actually supports today** by researching the live
Microsoft Learn ESS section. This is a primary planning step, not a fallback.
The vendored snapshot under `src/reference/ess-docs/` is a seed hint and an
offline safety net only — the ESS docs have moved before, so read them live.

Research runs on **two grounding axes — do both before you model tasks (Phase 3):**

1. **Microsoft Learn — *what* ESS supports** (the TOC crawl below): capabilities,
   prerequisites, the responsible role each names, and the outputs each produces.
2. **The kit's own skills — *how this kit builds each piece*** (*Also research
   across the kit's own skills*, below): the exact command an assignee runs, the
   role boundaries a setup splits on, and the deterministic step→task
   decomposition a shipped setup checklist encodes.

Neither axis alone is enough: Learn tells you a Workday connection is a
prerequisite; the kit's Workday setup skill tells you that one prerequisite is
**25 steps across 6 role boundaries**, decomposed deterministically. Fold both
into one research context.

## How the crawl works (Table-of-Contents first)

Learn publishes each section's tree as a machine-readable **Table of Contents**
(`toc.json`) — the authoritative parent/child/sibling map. Use it as the spine
instead of scraping links.

1. **Resolve the section base.** Start from the URL recorded in
   `src/reference/ess-docs/README.md` and follow any redirect to the current
   base (the section has moved once already). If your fetch tool refuses a
   cross-path redirect, re-fetch the final URL it names.
2. **Fetch the TOC.** Get `{base}/toc.json`. It lists every page as
   `{ href, toc_title, children[] }`.
3. **Select the pages to read.** Preview a bounded, intent-scoped selection:

   ```
   python scripts/planner/cli.py research --tokens "<systems + scenarios>" --toc <saved-toc.json>
   ```

   (Save the fetched TOC to a temp file and pass it with `--toc`, or pass
   `--fetch` to let the CLI fetch it.) The selection always includes the
   backbone (`overview`, `prerequisites`, `install`, `commands-reference`, …)
   plus the pages whose title/path match the sponsor's intent tokens, capped by
   a page budget. Non-matching siblings (e.g. SAP when the sponsor said Workday)
   are read title-only, not fetched.

   Add `--extract` to also fetch each selected page and pull **role/output
   candidates** off it (grounded to the page they came from):

   ```
   python scripts/planner/cli.py research --fetch --extract --tokens "<systems + scenarios>"
   ```

   Use those role candidates as the Learn-grounded role for each prerequisite's
   Task (Phase 3), and keep the page URL in your research notes — it grounds the
   role in the **research context** (§7.6), not as a task field.
4. **Read the selected pages** with your fetch tool, using the URLs the CLI
   prints. Only follow links that resolve to a TOC `href` — never invent a URL.

## What to extract from each page

For every page you read, pull out (each stamped with its source URL):

- **Capabilities** — the ESS-supported scenarios for the sponsor's systems
  (e.g. Workday read-profile scenarios; ServiceNow HRSD create/view/update
  case). This is what makes a scenario *buildable*.
- **Prerequisites** — what must exist first (environment, licensing, an Entra
  app + SSO, a connection, a knowledge source), and for each: the **responsible
  role** the docs name (and the **page URL** it came from — kept in the research
  context, not on the Task), **how** it's done (a kit command, or a
  portal/manual step — this goes in the Task **description**), and the **output
  keys** it produces (the Task's `--produces`). These become Tasks
  (Phase 3).
- **Constraints** — e.g. "Workday requires Entra SSO", data-residency notes.
- **Open items** — anything the docs don't answer → interview questions
  (Phase 2).

Cite the file/URL you used so the sponsor can verify. If the vendored snapshot
disagrees with live Learn, live wins for planning; note the drift.

## Also research across the kit's own skills (grounding axis 2)

Microsoft Learn says *what* to build; the **kit's own skills** say *how this kit
does it* — the command to run, the role boundaries, and the exact task
decomposition. Research these too, and record the findings next to the Learn
findings in the research context.

1. **Inventory the commands an assignee will run.** The kit ships one skill per
   verb — `/setup`, `/connect`, `/create`, `/evaluate`, `/flightcheck`, `/push`
   (routing table: `.github/copilot-instructions.md`). Every prerequisite you
   found on Learn maps to **one** of these, or to a portal/manual step. Name that
   command in the Task **description** (Phase 3) — it's what Flow 2 hands off to.

2. **Read the setup checklist for every captured system, and decompose it
   deterministically.** A system with a `src/skills/setup/<system>/tasks.md`
   ships a canonical, role-gated checklist — the information-complete source the
   setup orchestrator (`src/skills/setup/SKILL.md`) and `/connect` sequence.
   **Discover them** by listing `src/skills/setup/*/tasks.md` (today: `workday`).
   For each captured system that has one, **do not hand-write the tasks** — run
   the extractor, which groups every step by its role boundary and maps each
   grounded role to its attestable id:

   ```
   python scripts/planner/cli.py setup-tasks --system <system> --commands
   ```

   For `workday` that yields **25 steps / 6 groups → 7 role-boundary Tasks across
   5 roles** (PP Admin, Env Maker, Cloud App Admin, Workday Admin, Network Admin),
   each with its `--produces`/`--consumes` already set. Emit those lines verbatim
   (Phase 3, `model.md` → *Don't hand-decompose a system that ships a setup
   checklist*).

3. **Read the role gating.** `src/reference/ess-docs/setup/role-gating.md` is the
   role × gate matrix every checklist item cites — use it to confirm the
   attestable role each Task pools to (the grounded→attestable map lives in
   `model.md`).

4. **Note the produces/consumes each skill implies.** A setup checklist's outputs
   (an Entra app, a tenant config, a connection, a network allowlist, a topic) are
   the `--produces` keys of its Tasks; a downstream skill that needs one declares
   it as `--consumes`. This ledger is what sequences the plan (`model.md` →
   *Sequence the tasks*).

A captured system with **no** native kit skill (no extension pack — ADP, Jira, a
custom HTTP API) has no `setup-tasks` decomposition: model it as a `/create`
custom-flow Task instead (`model.md` → *Native connector vs. custom flow*).

When you have a grounded picture from **both axes** — supported scenarios, their
prerequisites, each prerequisite's role/how/produces, and the deterministic setup
decomposition for every system that ships a checklist — go to Phase 2.

> **Where the research context lives (today).** It is held in your working notes
> for this planning session — there is **no** persisted `research-context.json`
> sidecar yet (a design follow-up, §18). Task briefs (Phase 6, `mytasks.md`)
> therefore re-read the grounding Learn page **live** at brief time rather than
> replaying a stored anchor, so a manual task is still enriched from its source.
