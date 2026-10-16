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
| 11a (turn 1) | "I couldn't find information on bonus targets in the available HR resources." | **PASS** | No resource retrieved for this subject on turn 1. |
| 11b (turn 2) | "I'm sorry, I still don't have information on bonus targets — that's not something I can find in the available HR resources." | **PASS** | Negative Rule 5: "stuck + asks for help" is necessary but not sufficient — a resource may only be offered if retrieval for *that subject* ever surfaced one. None did on either turn, so none is named, even though the user is visibly stuck. Confirms Rule 5 doesn't override the grounding rule in the section header. |
| 12 | "I couldn't find information on perks in the available HR resources." | **PASS** | Zero sub-categories were retrieved (not "multiple distinct" ones), so this falls to Rule 2, not Rule 3 — no clarifying menu is fabricated from nothing, and no resource is named. |
| 13 | "Reset your network password through the IT self-service password reset portal, since Workday uses the same credentials. If you still can't sign in after that, contact HR Shared Services so they can check your Workday account." | **PASS** | HRKB9000005 is an approved **HR** source and is directly responsive, so this stays in scope and is answered fully — including its named resource, since that resource is conditioned on "still can't sign in," matching the user's stated problem. Confirms scope is determined by which approved source answers the question, not by surface keywords like "login" or "password" that might *look* IT-flavored. |
| 14 | "Sure, I can help — could you briefly describe the issue?" | **FAIL (instruction gap)** | The user already stated the subject ("LOA request not showing up in Workday") in the opening message. Rule 1 is written unconditionally — "if the first message asks to open a case or how to contact HR, don't answer ... ask them to describe the issue" — with no carve-out for when the issue is already described. Applied literally, the agent re-asks for information it already has, which is redundant and works against the "user-centric," "conversational and crisp" core-identity principles, and against the general clarification rule elsewhere in the same document ("ask a clarifying question only when a missing detail is necessary"). This is a real tension in the instructions, not a one-off misread — see **Finding** below. |

## Outcome

13/14 cases pass; case 14 surfaces a genuine instruction gap (see Finding). All 5 required
scenarios are covered (cases 1–2, 3–5, 6–7, 8, 9a–9b respectively), plus the original regression
(case 10) and 4 additional negative/edge cases (11–14) targeting branches the first pass didn't
exercise: a stuck user with no retrievable resource (11), a broad question with zero retrieval
rather than several (12), an HR/IT boundary question that stays in scope because an HR source
answers it (13), and an opening message that already states its subject (14).

## Finding: Rule 1 has no carve-out for a self-describing opening message

Case 14 shows Rule 1's current wording — "if the first message asks to open a case or how to
contact HR, don't answer or name a resource yet — confirm you can help and ask them to describe
the issue" — triggers on the *form* of the message (an opening ask-for-support) regardless of
whether the subject is already present in that same message. That produces a response that
ignores information the user already gave, which cuts against this document's own emphasis on
conversational, non-redundant answers.

**Suggested fix (not applied — pending approval):** add a condition to Rule 1, e.g. "...ask them
to describe the issue, unless the opening message already states it, in which case proceed to
Rules 2–5 using that subject." This keeps Rule 1's purpose (don't let a bare "how do I open a
case" jump straight to naming a resource) while not discarding a subject the user already gave.

## Known limitation

This is a manual simulation, not an automated or live-agent test. It validates that the
instructions *as written* produce the right decision when a human applies them literally and
faithfully — it does not prove a deployed Copilot Studio agent (with real retrieval, real
ranking, and its own instruction-following behavior) will behave identically. Re-validate against
the live agent and real retrieval before relying on this for production sign-off.
