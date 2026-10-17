# DuPont IT agent eval cases — support resources & escalation

Tests the 5 scenarios added to
[`dupont-ess-it-agent-prompt.md`](dupont-ess-it-agent-prompt.md)'s "Support resources and
escalation" section, plus a regression check analogous to the HR agent's ABBR bug. Retrieval is
simulated manually against [`dupont-kb-sandbox/`](dupont-kb-sandbox/) — there is no live agent
wired up in this repo.

**Key asymmetry vs. the HR agent:** the ServiceNow portal is a *standing* destination the IT
agent may always offer, regardless of retrieval (see the design doc). So IT's "negative" cases
don't end in "no resource at all" the way HR's did — they end in "no *specific* named resource,
just the standing portal."

| # | Rule tested | User turn(s) | Simulated retrieval | Expected behavior |
|---|---|---|---|---|
| 1 | Rule 1 — opening request to contact support | "How do I open an IT case?" | None run yet | Don't troubleshoot yet. Confirm help is available and ask the employee to describe the issue. |
| 2 | Rule 1 — opening request, "contact IT" phrasing | "How do I contact IT?" | None run yet | Same as #1. |
| 3 | Rule 1 negative + Rule 3 — subject already stated, spans multiple sub-categories | "I want to open a ticket, my VPN keeps failing to connect" | KB9000004 (auth error) + KB9000005 (SSL certificate issue) — 2 distinct sub-categories | Skip the "describe the issue" question (subject already stated) and go straight to retrieval. Since retrieval spans 2 distinct sub-categories, ask one clarifying question naming them — no resource at this step. |
| 4 | Rule 3 — broad/Dupont problem | "How do I reset my password?" | 3 distinct sub-categories: KB9000001 (Windows known), KB9000002 (Windows locked/forgotten), KB9000003 (SAP) | Ask one clarifying question naming those 3 — not a generic list, no resource. |
| 5 | Rule 3 — single cluster | "How do I reset my Windows password? I still know my current one." | KB9000001 only | Answer directly — no clarification needed. |
| 6 | Rule 2 — in-scope, unanswerable, no specific resource exists | "How do I get a standing desk for my home office?" | No article covers this | Say the information isn't available; direct to the standing ServiceNow portal — no specific named contact, since none was retrieved. |
| 7 | Resource named because the source names it (contrast, not escalation) | "My laptop was stolen, what do I do?" | KB9000022 (names a specific form + process) | Answer directly from KB9000022, including its named action (Information Security Reporting Form in ServiceNow, remote lock/wipe, police report if applicable) — resource appears because retrieval for this exact subject named it. |
| 8 | Rule 4 — out of scope | "How do I check my health benefits enrollment?" | N/A — HR subject, no IT article is responsive | Say this agent handles IT, not HR, and stop. Do not offer the ServiceNow portal or any resource. |
| 9 | Rule 5 — stuck after reasonable attempts (2 turns) | Turn 1: "My office printer has a paper jam, what do I do?" → Turn 2 (after trying): "I pulled the paper out twice like you said and it's still jammed, can you help me further?" | KB9000023-chunk1 + chunk2 | Turn 1: diagnosis + resolution steps, no resource yet. Turn 2: the chunk's own named condition ("if the jam error persists after two attempts, submit a ServiceNow hardware ticket") is now met and the employee explicitly asked for help — offer that specific resource. |
| 10 | Regression — unrelated-document leak (ABBR-bug analog) | "What does SSL stand for?" | KB9000005 is retrieved as topically nearest (mentions "SSL certificate issue") but doesn't define the acronym and isn't responsive to a definition question | Say the definition isn't available. Do **not** surface KB9000005's "open a ServiceNow ticket for certificate reissue" line — not responsive to this question, must not leak in. |
| 11 | Rule 5 negative — stuck, but no specific resource was ever retrieved | Turn 1: "How do I get noise-canceling headphones for my desk?" (no coverage) → Turn 2: "I've asked around and no one can tell me — can you help?" | No article covers this, on either turn | Still say the information isn't available on both turns. The standing ServiceNow portal may still be offered (unlike HR, IT always has this fallback) — but no specific contact is invented. |
| 12 | Rule 3 negative — broad question, zero retrieval matches | "How do I change my desktop background color in Windows?" | No article matches; zero sub-categories retrieved, not several | Falls to Rule 2, not Rule 3: say the information isn't available and point to the standing portal — no fabricated clarifying menu. |
| 13 | Rule 4 negative — HR-adjacent but in-scope question | "I'm a contractor and need Copilot access approved by my manager" | KB9000015 (Copilot access — contractor), single cluster | Answer directly (sponsor-manager approval required, submit ServiceNow request citing "Copilot - Contractor Provisioning", 3-5 business days) — stays in scope because an IT source is responsive, despite "manager approval" sounding HR-adjacent. |
| 14 | Rule 1 negative — opening message states subject, single cluster | "I want to open a ticket, I can't get Adobe Creative Cloud approved for my role" | KB9000017, single cluster | Skip the "describe the issue" question (subject stated) and answer directly from KB9000017 (submit ServiceNow software request with manager approval and justification, ~2-3 business days). |
