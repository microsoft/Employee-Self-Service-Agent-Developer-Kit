# HR KB sandbox (synthetic)

Curated, synthetic HR knowledge-base articles used to manually test the support-resource and
escalation rules in
[`docs/prompts/2026-10-15-hr-agent-instructions-support-escalation.md`](../../prompts/2026-10-15-hr-agent-instructions-support-escalation.md).
None of this content is real DuPont/Northern Trust policy — it exists only to exercise retrieval
scenarios (single-topic match, multi-topic spread, no match, resource present vs. absent) against
the instructions.

| KB # | Topic | Has an escalation/resource line? |
|---|---|---|
| HRKB9000001 | Benefits - Medical - Enrollment | No |
| HRKB9000002 | Benefits - Retirement - Contribution Changes | No |
| HRKB9000003 | Benefits - FSA - Dependent Care Enrollment | No |
| HRKB9000004 | Leave - LOA - Request Process | Yes (if request doesn't appear within 3 business days) |
| HRKB9000005 | Workday Access - Login Issues | Yes (if still can't sign in after password reset) |
| HRKB9000006 | Handbook - Glossary | Yes, but only for handbook questions — not a general catch-all |
| HRKB9000007 | Support - Case Submission - General | Yes (this *is* the general "how to open a case" answer) |
| HRKB9000008 | Leave - Policy Exceptions | Yes (exception request path) |

For the out-of-scope eval case, we reuse the existing
[`../dupont-kb-sandbox/`](../dupont-kb-sandbox/) (IT) content as-is — a password-reset question
is IT scope, not HR scope, which is exactly what that case needs to test.
