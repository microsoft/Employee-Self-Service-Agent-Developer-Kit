# UX contract check

Analysis guidance for the **adaptive-card UX contract** checks used by the `topics/review` skill. These
cover two concerns: whether a card's data bindings resolve, and whether the card handles its own empty,
error, and confirmation states.

## Part 1 — Card / topic binding integrity (run the detector)

An adaptive card renders `Topic.*` values. If a card references a value the topic never populates, that
field renders blank at runtime with no error. Run this from the `solutions/ess-maker-skills/` directory:

```
python scripts/scan_bindings.py --agent {agent-slug} --topic {topic-stem}
```

The detector's output is **authoritative** on whether a card reference resolves. It reconciles what each
card consumes against everything the topic populates — declared inputs, `ParseValue` targets (expanded
through their record schema), `SetVariable` / `SetTextVariable` targets, and `BeginDialog` output
bindings. It reports two anomaly classes:

- **unpopulated variable** — the card reads `Topic.X` whose root variable is never populated anywhere in
  the topic. This value will always render blank.
- **unknown field** — the card reads `Topic.X.Y` where `Topic.X` comes from a `ParseValue` record schema
  that does not declare `Y` (usually a field-name typo). This value will always render blank.

Every reference the detector reports **will always be blank at runtime** — do not reason about whether it
"might" be populated. Turn each into a finding, applying the precision bar and reachability scoring from
the shared [`finding-contract.md`](finding-contract.md) to set severity, and name the intended field in the
suggested fix when there is an obvious near-match. If the script cannot run, say so in the report.

## Part 2 — Empty, error, and confirmation states (read the card)

Read each adaptive card body (`AdaptiveCardTemplate.cardContent` / `AdaptiveCardPrompt.card`) and the
surrounding actions, and assess:

- **Required-field visibility** — an input marked `isRequired: true` that is also `visible: false` cannot
  be satisfied by the user; the card can never be submitted.
- **Empty data sets** — a choice set or repeated section bound to a collection that can be empty renders a
  blank control with no explanation. Check whether an empty result is handled.
- **Parse-driven empty UI** — when a card renders data from a `ParseValue`/`ParseJSON` that can fail or
  return empty, the card shows blank fields with no message unless an empty/error branch handles it.
- **Missing confirmation** — an action that creates or changes something (a flow call that returns an id
  or ticket number) but ends without telling the user it succeeded, or without surfacing the returned
  identifier.
- **Blank / null field rendering** — fields shown directly (e.g. in a `FactSet`) with no `N/A` fallback or
  conditional hide, so a null value renders as an empty row.
- **Links with empty components** — a URL built by concatenating a base and an id where either part can be
  empty, producing a broken link.

Apply the same precision bar and severity mapping from the shared
[`finding-contract.md`](finding-contract.md). A gap on a path a normal user reaches is higher
severity than one behind an unreachable branch. This check uses the `BTUX` finding-ID prefix.
