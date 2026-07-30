# Planner — Phase 1: Research Microsoft Learn (grounding)

Ground the Plan in **what ESS actually supports today** by researching the live
Microsoft Learn ESS section. This is a primary planning step, not a fallback.
The vendored snapshot under `src/reference/ess-docs/` is a seed hint and an
offline safety net only — the ESS docs have moved before, so read them live.

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
4. **Read the selected pages** with your fetch tool, using the URLs the CLI
   prints. Only follow links that resolve to a TOC `href` — never invent a URL.

## What to extract from each page

For every page you read, pull out (each stamped with its source URL):

- **Capabilities** — the ESS-supported scenarios for the sponsor's systems
  (e.g. Workday read-profile scenarios; ServiceNow HRSD create/view/update
  case). This is what makes a scenario *buildable*.
- **Prerequisites** — what must exist first (environment, licensing, an Entra
  app + SSO, a connection, a knowledge source), and for each: the **responsible
  role** the docs name, **how** it's done (a kit skill, or a portal/manual
  step), and the **output keys** it produces. These become Tasks (Phase 3).
- **Constraints** — e.g. "Workday requires Entra SSO", data-residency notes.
- **Open items** — anything the docs don't answer → interview questions
  (Phase 2).

Cite the file/URL you used so the sponsor can verify. If the vendored snapshot
disagrees with live Learn, live wins for planning; note the drift.

When you have a grounded picture — supported scenarios, their prerequisites,
each prerequisite's role/action/produces — go to Phase 2.
