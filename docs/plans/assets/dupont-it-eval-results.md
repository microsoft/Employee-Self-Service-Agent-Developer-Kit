# DuPont IT agent eval results — support resources & escalation

Manual walkthrough of [`dupont-it-eval-cases.md`](dupont-it-eval-cases.md) against
[`dupont-ess-it-agent-prompt.md`](dupont-ess-it-agent-prompt.md) as it stands after the escalation
section was added and the redundant clarify-first restatements were removed. No live agent is
wired up in this repo, so each case is resolved by hand: simulate what retrieval would return from
the cited KB sandbox article(s), then apply the instructions literally.

| # | Simulated response | Verdict | Notes |
|---|---|---|---|
| 1 | "Sure, I can help — could you briefly describe the issue?" | **PASS** | Rule 1: no troubleshooting, no resource yet. |
| 2 | "Sure, I can help — what do you need from IT?" | **PASS** | Same as #1 for "contact IT" phrasing. |
| 3 | "Is this a sign-in/credentials error, or a certificate error message?" | **PASS** | Rule 1's "unless they already stated it" carve-out skips straight to retrieval since the subject (VPN) was given; retrieval then spans 2 distinct sub-categories (KB9000004 vs KB9000005), triggering Rule 3's clarification — no resource at this step. Confirms the two rules compose correctly. |
| 4 | "Are you trying to reset your Windows password, or your SAP password?" | **PASS** | 3 sub-categories retrieved (2 Windows variants collapse to one "Windows password" option plus SAP) — clarifies using only retrieved categories, no resource. |
| 5 | "Press Ctrl+Alt+Delete, select 'Change a password', enter your old password, then your new password twice. It must meet DuPont's complexity requirements (12+ characters, mixed case, number, symbol)." | **PASS** | Single cluster (KB9000001) — answered directly. |
| 6 | "I couldn't find information on standing desks in our IT resources. You can submit a request through the ServiceNow portal." | **PASS** | No article retrieved — says so, offers only the standing portal (no specific contact, since none was retrieved for this subject). |
| 7 | "Submit the Information Security Reporting Form for Lost or Stolen Device(s) in ServiceNow immediately — IT Security will remotely lock and wipe the device. File a police report if it was stolen outside a DuPont facility." | **PASS** | KB9000022 is fully responsive and names its own resource/process — answered directly, resource included because retrieval for *this* subject named it. |
| 8 | "That's a question about your health benefits, which is outside what I can help with — I handle IT questions, not HR. You'll want to check with HR for that." | **PASS** | Rule 4: out of scope, stops there — importantly, does **not** also suggest the ServiceNow (IT) portal, since that's an IT destination and the rule explicitly forbids offering any resource here. |
| 9a (turn 1) | "Check the display panel for the jam location code (tray, fuser, or output area) — don't force the printer to continue. Then open the indicated tray or rear panel gently and pull the jammed paper in the direction of the paper path, never against it. Close the panels and press Resume." | **PASS** | Diagnosis + resolution steps from KB9000023, no resource yet. |
| 9b (turn 2) | "Since it's still jammed after two attempts, please submit a ServiceNow hardware ticket so IT can take a closer look." | **PASS** | Rule 5: the source's own named condition ("if the jam error persists after two attempts, submit a ServiceNow hardware ticket") is met, and the employee made a reasonable attempt and explicitly asked for more help — resource offered. |
| 10 | "I couldn't find a definition for 'SSL' in our IT resources." | **PASS** | Regression check: KB9000005 is retrieved as topically nearest but doesn't define the acronym and isn't responsive to this specific question, so its "open a ServiceNow ticket for certificate reissue" line (which answers a different problem — certificate errors, not acronym definitions) must not leak in — and it doesn't. This is the exact mechanism the new section's opening grounding sentence was written to enforce. |
| 11a (turn 1) | "I couldn't find information on noise-canceling headphones in our IT resources. You can submit a request through the ServiceNow portal." | **PASS** | No resource retrieved for this subject. |
| 11b (turn 2) | "I'm sorry, I still don't have specific guidance on that — you're welcome to submit a request through the ServiceNow portal and a specialist can look into it." | **PASS** | Negative Rule 5: no specific contact is invented even though the employee is stuck and asking for help — but unlike HR, the standing ServiceNow portal remains a legitimate thing to point to, since it never required retrieval. Confirms the designed asymmetry holds in practice. |
| 12 | "I couldn't find information on changing your desktop background color in our IT resources. You can submit a request through the ServiceNow portal." | **PASS** | Zero sub-categories retrieved (not "multiple distinct" ones) — falls to Rule 2, not Rule 3; no clarifying menu fabricated from nothing. |
| 13 | "As a contractor, you'll need sponsor-manager approval before Copilot access can be granted. Submit a ServiceNow request citing 'Copilot - Contractor Provisioning' with your sponsor's name — provisioning takes about 3-5 business days after approval." | **PASS** | KB9000015 is an approved IT source and is directly responsive, so this stays in scope and is answered fully — confirms scope is determined by which source answers the question, not by surface wording like "manager approval" that might look HR-adjacent. |
| 14 | "Submit a ServiceNow software request citing 'Adobe Creative Cloud' with manager approval and business justification — provisioning takes about 2-3 business days after approval." | **PASS** | Rule 1's carve-out skips the "describe the issue" question since the subject was already stated; single-cluster retrieval (KB9000017) answers directly. |

## Results — UAT-sourced cases (Gold Prompt validation)

These check whether this repo's revised prompt — not the pre-update Gold Prompt the UAT actually
tested — would have avoided each real failure.

| # | Simulated response | Verdict | Notes |
|---|---|---|---|
| 15a (turn 1) | "To make sure I guide you to the right steps, could you let me know which account or system you need to reset the password for? For example, is it your Windows login or SAP?" | **PASS** | 3 categories retrieved (Windows-known, Windows-locked, SAP) — clarifies first. |
| 15b (turn 2) | "Do you know your current Windows password, or is your account locked or forgotten?" | **PREDICTED PASS** | Retrieval narrowed to "Windows password reset" still spans 2 distinct sub-categories (KB9000001 vs. KB9000002). Applying the Core principle and the Authoritative knowledge source bullet literally — both of which fire per retrieval event, not just once per conversation — this *should* trigger a second clarifying question. This directly addresses what the Gold Prompt missed in row 1. Marked "predicted" rather than a flat pass: it depends on the live model re-applying the rule on a second, narrower retrieval, which is exactly the kind of multi-step condition that didn't hold reliably in the Copilot Studio trigger-description testing earlier in this project — worth confirming against the live agent, not just this manual walkthrough. |
| 16 | "Is this a sign-in/authentication error, or a certificate error message?" | **PREDICTED PASS** | 2 distinct sub-categories retrieved (KB9000004, KB9000005) — the rule as written should produce one clarifying question here, not the long combined script the Gold Prompt actually gave. Flagged "predicted" for the same reason as 15b: this is precisely the failure mode observed in production, so it's worth live re-verification rather than assuming the rule holds just because it reads correctly on paper. |
| 17 | "Are you trying to access P23 (Production - Americas) or P80 (Production - EMEA)?" | **PASS** | 2 distinct sub-categories (KB9000008, KB9000009) — clarifies, matching what the Gold Prompt failed to do in row 7. |
| 18 | "Are you looking for self-paced training or a live session?" | **PASS** | 2 distinct sub-categories (KB9000012, KB9000013) — clarifies instead of describing both tracks, matching what the Gold Prompt failed to do in row 14 (confirmed by the transcript showing a combined answer). |
| 19 | "I can help — which region are you in (Americas, EMEA, or APAC)? That determines the approved models and delivery timeline." | **PASS, with a caveat** | Only one article (KB9000018) is retrieved — there's no second competing article, so this isn't the "multiple distinct sub-categories" trigger the other cases rely on. The correct behavior here comes from a different source: KB9000018's own content instructs selecting a region as part of the catalog item, so the agent should surface that as part of answering, not withhold an answer pending a separate clarification turn. The *outcome* the tester wants (region gets asked) is still achieved, but through "answer faithfully from the one retrieved article" rather than through Rule 3's clustering logic — worth knowing these are different mechanisms producing the same visible behavior. |
| 20 | "Is this for a managed DuPont device, or an unmanaged/BYOD device?" | **PASS** | 2 distinct sub-categories (KB9000010, KB9000011) — clarifies, matching what the Gold Prompt failed to do in row 21. |
| 21 | "Are you looking for Adobe Reader, or Adobe Creative Cloud?" | **PASS** | 2 distinct sub-categories (KB9000016, KB9000017) — clarifies, matching what the Gold Prompt failed to do in row 27. |
| 22 | "Are you requesting this as a full-time employee, or as a contractor?" | **PASS** | 2 distinct sub-categories (KB9000014, KB9000015) — clarifies, matching what the Gold Prompt failed to do in row 29. |
| 23 | N/A | **SANDBOX GAP — not evaluable** | Our sandbox has only one peripherals article (KB9000018, keyboard-specific). Row 30's expectation (ask which peripheral) needs a richer sandbox with separate articles per peripheral category to test meaningfully. Recommend expanding `dupont-kb-sandbox/` if this case matters for sign-off. |
| 24 | "Which method would you like to use — the Microsoft Authenticator app, a Deepnet hardware token, or something else?" | **PASS** | Both retrieved methods are named exactly as they appear in KB9000019/KB9000020, with a generic "something else" catch-all per the existing clarifying-question format — and critically, "OKTA" is never mentioned, since it appears in no retrieved content. This is a direct, concrete test of the "Accuracy and safety" rule ("use only terms that appear in retrieved KB content") against the exact hallucination the Gold Prompt produced in row 28. |
| 25 | N/A | **SANDBOX GAP — not evaluable** | Our sandbox has only one home-printer article (KB9000007), with no OS-version variant. Row 5's expectation (ask Windows 10 vs. 11) needs that variant modeled before this can be tested. |
| 26 | N/A | **OUT OF SCOPE — platform bug, not prompt-evaluable** | Row 2's citation complaint (missing KB number, SharePoint icon instead of ServiceNow) is about connector/indexing behavior, not response text. No manual text walkthrough can validate or refute this — it needs to be checked against the live ServiceNow Knowledge connector configuration directly. |

### Outcome — UAT-sourced cases

8 of 12 cases are clean passes under literal application of the current prompt; 2 are marked
"predicted pass" rather than a flat pass because they're the exact failure modes observed live,
and the existing project history (the Copilot Studio trigger-description saga) is a reminder that
a correct-on-paper rule doesn't always hold under a real orchestrator — these specifically warrant
live re-verification, not just this manual walkthrough. 2 are sandbox-fidelity gaps needing a
richer KB before they can be tested at all, and 1 (citations) is a platform bug outside what any
prompt wording can fix.


## Outcome

14/14 cases pass on the first pass — no instruction gap found, unlike the HR agent's first pass
(which needed the rule 1 carve-out added after testing). That fix was incorporated into this
prompt proactively from the start ("unless they already stated it" is already in rule 1's text),
and the grounding sentence at the top of "Support resources and escalation" already guards against
the unrelated-document-leak pattern case 10 checks for. All 5 required scenarios are covered
(cases 1-2, 3-5, 6-7, 8, 9a-9b respectively), plus the regression check (case 10) and 4
negative/edge cases (11-14) mirroring the ones added to the HR eval suite.

## Known limitation

This is a manual simulation, not an automated or live-agent test. It validates that the
instructions *as written* produce the right decision when applied literally and faithfully — it
does not prove a deployed agent (with real retrieval, real ranking, and its own
instruction-following behavior) will behave identically. Re-validate against the live agent and
real retrieval before relying on this for production sign-off.
