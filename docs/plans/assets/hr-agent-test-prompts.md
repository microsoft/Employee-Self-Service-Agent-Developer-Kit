# HR agent — test prompts for real setup

Copy-paste prompts to validate the support-resource/escalation rules in
`docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md` against a live/real
knowledge base. These mirror the synthetic sandbox cases in `hr-agent-eval-cases.md` — swap in
real subjects if your KB's topics differ (medical/retirement/FSA benefits, leave of absence
request process, Workday access, handbook glossary, exception requests, how-to-open-a-case).

---

## 1 — Opening request (generic "open a case")
> How do I open a support case?

Expected: agent asks what the issue is before naming any resource — no answer, no contact info yet.

## 2 — Opening request ("contact HR" phrasing)
> How do I contact HR?

Expected: same — asks what the issue is first.

## 3 — In-scope, fully answerable (baseline, not an escalation case)
> My leave of absence request isn't showing up in Workday — what do I do?

Expected: direct answer with the wait-time guidance and, since the source itself names it, the
HR Shared Services contact for the "still not showing up" condition.

## 4 — In-scope, genuinely unanswerable, no resource
> What's my annual bonus target supposed to be?

Expected: "couldn't find that" — no resource offered, since none exists for this subject.

## 5 — Exception process (resource named because the source names it)
> I need an exception to extend my leave of absence past the standard limit — how do I ask for that?

Expected: explains the exception-request process and its named contact, as written in the source.

## 6 — Broad/"Dupont problem" question spanning multiple topics
> How do I update my benefits?

Expected: one clarifying question naming the actual sub-topics retrieved (e.g., medical,
retirement, FSA) — no resource offered yet.

## 7 — Broad-sounding but single-topic
> How do I update my FSA enrollment?

Expected: direct answer, no clarification needed (only one topic matched).

## 8 — Out of scope
> How do I reset my Windows password?

Expected: states it's out of scope for an HR agent and stops — no resource offered, even though
an IT contact likely exists somewhere.

## 9 — Stuck after reasonable attempts (2 turns)
> Turn 1: My leave of absence request seems delayed, what should I do?
>
> Turn 2 (after waiting a few days): It's now been over 3 business days and still nothing, I
> don't know what else to do — can someone help me?

Expected: turn 1 gives wait-time guidance, no resource; turn 2 offers the HR Shared Services
contact since the condition is now met and the user explicitly asked for help.

## 10 — Regression check (the original bug)
> What is the definition of ABBR?

Expected: "couldn't find that" — must NOT surface an unrelated HR contact line from a nearby
handbook/glossary article.

## 11 — Negative: stuck but no resource exists anywhere
> Turn 1: What's my bonus target supposed to be?
>
> Turn 2: I've asked around and no one can tell me — can someone help me find out?

Expected: still "couldn't find that" on both turns — no invented contact, even though the user is
stuck and asking for help.

## 12 — Negative: broad question with zero matches (not multiple topics)
> How do I update my perks?

Expected: "couldn't find that" (not a clarifying menu) — nothing was retrieved to clarify between.

## 13 — Negative: HR/IT boundary question that stays in scope
> I can't log into Workday to check my HR self-service, what do I do?

Expected: answered directly (reset network password, then contact HR Shared Services if still
stuck) — NOT rejected as out-of-scope, since an HR source addresses it.

## 14 — Negative: opening message that already states its subject
> I want to open a case about my leave of absence request not showing up in Workday.

Expected: goes straight to the answer/escalation for that subject — should NOT re-ask "what's the
issue?" since it's already stated (this is the fix that was just applied to rule 1).
