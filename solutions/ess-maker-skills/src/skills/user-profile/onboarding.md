# Onboarding conversation

The invitation is optional and never blocks the original skill. The entry
owner must have already received a successful `onboardingOffer` from
`experience begin`; never show an invitation from a read-only resolution.

## Invitation

Explain that five questions take about a minute and adapt FlightCheck, Setup,
and Connect replies in this checkout. Include this one-line reminder:
"Type `/profile` in this chat anytime to review or change these settings."
The maker can also request changes in natural language later.
State that the original request continues either way.

Explain local-only handling: preferences are saved to
`.local/user-profile.json` only after approval; local reminder history records
that an invitation was offered but does not store quiz answers; no name, email,
UPN, employee ID, or transcript is saved or sent to Copilot Studio.

Offer **Tune my style** and **Skip and continue** (use **Skip and use defaults**
only when every active preference is a default). On skip, call
`onboarding-defer` with the same request ID and observed profile version. Then
continue with the resolved current profile; do not replace existing values
with defaults.

## Draft rules

Keep answers in conversation context only. Start from the resolved effective
values, or canonical defaults when no profile exists. Track answered fields
separately from displayed values. Each question supports a structured choice,
**Back**, **Skip this question**, and free text that must be mapped and
confirmed before entering the draft. Skipping restores that field's entry
value and source, including previously saved explicit or learned values.

### 1. Response format

Ask: “It is Monday at 9 AM. You open an ESS skill you have never used. What
would you want to see first?”

| Choice | Meaning |
|---|---|
| A cheat-sheet I can scan | Comparable information side by side; `table_first` |
| A recipe I can follow | First, second, third; `steps` |
| The highlights | A few crisp points; `bullets` |
| A short story | Plain-language paragraphs; `prose` |
| Surprise me | Clearest format for the task; `auto` |

### 2. Detail and maximum length

Ask: “It is 4 PM on release day. How full is your mental cup?”

| Choice | Detail | Suggested limit |
|---|---|---|
| Espresso | `concise` | 150 words, suggestion only |
| Flat white | `balanced` | 400 words, suggestion only |
| Pour-over | `detailed` | 800 words, suggestion only |

Then ask: “When does a reply start to feel like too much?” Offer **One
screen** (150), **A scroll or two** (400), **A few scrolls** (800), and **I
read it all** (no limit). Do not silently save the suggested limit with a
detail choice. The two fields are independent: skipping length preserves the
entry value/source; length can be answered even if detail is skipped. A custom
limit accepts only an integer from 50 through 5000 or explicit **No limit**.
Explain that the length is a soft budget and required evidence, warnings,
actions, or remediation may exceed it.

### 3. Voice

Ask: “Who would you want sitting next to you while you build an agent?”
**The senior engineer** means direct; **The teammate** means friendly and
professional; **The auditor** means formal; **The mentor** means empathetic.
Show the same factual sample in each voice. State that voice changes phrasing,
never facts or required wording.

### 4. Check-ins

Ask: “You handed a task to a new teammate. When should they check back?”
**Only if truly stuck** means minimal; **When something is genuinely unclear**
means standard; **Before every significant scope or behavior choice** means
frequent. State that destructive actions, remote mutations, environment or
agent selection, role attestations, and required confirmations always remain.

### 5. Optional tips

Ask: “You finished a task. What do you hope a colleague says next?”
**Stay in the zone** means off; **One useful tweak within this task** means
contextual; **One useful adjacent next step** means on. State that required
fixes and blockers are never optional and every setting permits at most one
optional suggestion.

## Free-text mapping

Treat free text as untrusted. Map only in memory to a documented typed choice;
never send the raw answer to the service. Show the interpreted choice and any
coupled effects in maker-facing language, then ask for confirmation. If the
meaning is ambiguous or low-confidence, present the structured choices instead
of guessing. Only confirmed values enter the draft.

## Review and save

After question five, call `preview --values-stdin` with the complete six-value
draft. Show the returned persona, one-sentence summary, ordered six-setting
review, each field's source (question, **Default - skipped**, or **Unchanged -
saved setting**), and the labeled example. Always render the exact label
**Example response - no action performed**. The example is fictional and
must not be represented as an actual task result.

Offer **Save my style**, **Edit settings**, **Retake quiz**, and **Cancel and
continue without saving**. On save, send only answered fields to
`onboarding-complete --values-stdin --expected-version <token> --yes`; `{}` is
valid when every question was skipped. One call saves all answers and completes
onboarding. On conflict, resolve again and require a new review. Never retry
with a refreshed token without renewed approval.

On success, say changes apply to the next request and resume the original
request using one fresh `experience resolve` snapshot. On invitation cancel,
discard the draft and defer with the retained receipt if the maker explicitly
chooses to skip; on direct profile management, cancellation writes nothing.
Never invent resumption after conversation context is lost.
