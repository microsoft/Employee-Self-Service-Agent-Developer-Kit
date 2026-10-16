# HR agent eval results — support resources & escalation

Manual walkthrough of [`hr-agent-eval-cases.md`](hr-agent-eval-cases.md) against
[`docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md`](../../prompts/2026-10-15-hr-agent-instructions-support-escalation.md).
No live agent is wired up in this repo, so each case is resolved by hand: simulate what
retrieval would return from the cited KB sandbox article(s), then apply the instructions
literally to produce the response a compliant agent would give.

| # | Simulated response | Verdict | Notes |
|---|---|---|---|
| 1 | "Sure, I can help — could you briefly describe the issue so I can point you to the right place?" | **PASS** | No answer given, no resource named yet (Rule 1). |
| 2 | "Sure, I can help — could you briefly describe what you need from HR?" | **PASS** | Same as #1 for the "contact HR" phrasing. |
| 3 | "Submit the leave request through the Time Off & Leave tile in Workday. If it hasn't appeared within 3 business days of submission, contact HR Shared Services at hr-shared-services@northerntrust.com or ext. 4-HRSS." | **PASS** | HRKB9000004 is fully responsive and itself names the resource for this exact condition — answered directly, resource included because retrieval for *this* subject surfaced it. |
| 4 | "I couldn't find information on bonus targets in the available HR resources." | **PASS** | No resource named — none was retrieved for this subject (Rule 2, negative branch). |
| 5 | "LOA policy exceptions, such as extending duration beyond the standard limit, aren't self-service. Open a case with HR Shared Services describing the circumstances; a specialist will respond within 5 business days." | **PASS** | HRKB9000008 documents the exception process as written, including its named escalation path — allowed under role-boundaries ("explain it as written"). |
| 6 | "Are you looking to update your medical coverage, your retirement contributions, or your dependent care FSA?" | **PASS** | Rule 3: clarifies using only the 3 sub-categories actually retrieved (HRKB9000001/2/3); no resource offered at this step. |
| 7 | "FSA enrollment is open during the annual open enrollment period or within 31 days of a qualifying life event, managed through the Benefits tile in Workday." | **PASS** | Single cluster retrieved (HRKB9000003 only) — answered directly without a clarifying detour. |
| 8 | "That's outside what I can help with — I handle HR questions, not IT support." | **PASS** | Rule 4: out of scope, stops there, no resource offered even though the retrieved IT content names an IT Service Desk. |
| 9a (turn 1) | "Leave requests can take up to 3 business days to appear in Workday after submission. If it's been less than that, it should show up soon." | **PASS** | Escalation condition (>3 business days) not yet met — no resource. |
| 9b (turn 2) | "Since it's been more than 3 business days, contact HR Shared Services at ext. 4-HRSS so they can look into it." | **PASS** | Rule 5: reasonable attempt made (waited per guidance), user explicitly asked for help, and the subject's own retrieval names a resource — offered. |
| 10 | "I couldn't find a definition for 'ABBR' in the available HR resources." | **PASS** | Regression check: HRKB9000006 is retrieved as topically nearest but doesn't define "ABBR" and isn't responsive to this specific term, so its unrelated "contact HR Shared Services" line (which answers handbook questions, not acronym lookups) must not leak in — and the walkthrough confirms it doesn't. This is the exact bug the new section was written to fix. |

## Outcome

10/10 cases pass. All 5 required scenarios are covered (cases 1–2, 3–5, 6–7, 8, 9a–9b
respectively), plus the original regression (case 10). No instruction wording changes were
needed as a result of this pass — the grounding rule ("name a resource only when retrieval for
*this* subject returned one") was sufficient to resolve every case, including the two that look
like edge cases of each other (case 3 vs. case 4: same topic area, but only one has a responsive
source).

## Known limitation

This is a manual simulation, not an automated or live-agent test. It validates that the
instructions *as written* produce the right decision when a human applies them literally and
faithfully — it does not prove a deployed Copilot Studio agent (with real retrieval, real
ranking, and its own instruction-following behavior) will behave identically. Re-validate against
the live agent and real retrieval before relying on this for production sign-off.
