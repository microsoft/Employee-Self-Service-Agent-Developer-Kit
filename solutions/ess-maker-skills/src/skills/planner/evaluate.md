# Planner - Phase 5: Generate evaluations in the guided flow

> **Planner session entry:** Follow `src/skills/planner/SKILL.md` -> **Intent gate**,
> then **Gate** for the workspace bootstrap on first Planner use. Reuse its successful result
> in the same chat and workspace before continuing this flow.
> Apply its **Communication rules** to every reply and next-step handoff.

The planner orchestrates the existing evaluation skills; it does not invent a
second YAML format, grader, or runtime. The maker must not have to discover and
invoke a separate `/evaluate` command.

## During planning: generate and save scenario cases

Once goals and scenarios are captured, read the plan's `scenario`,
`scenarioCapability`, `objective`, `businessGoals`, and explicit out-of-scope
boundaries. Reuse the selected HR/IT target and systems. A pending system is not
a reason to stop; describe system-independent observable behavior until it is known.

Generate a small, nonredundant set of employee prompts and expected behaviors:
a success case, a boundary/missing-information case, and a negative/out-of-scope
case for each selected scenario area. Cover the named capabilities without
inventing company policy, personal records, or unsupported integrations.

Persist each case as a scalar context entry so it survives closing chat, sharing,
and resuming:

```text
python scripts/planner/cli.py set-context --key "eval.hr-profile-read.direct" --group evaluationCase --value "Prompt: Show my profile. Expected: Display only the signed-in employee's supported profile fields." --description "Draft scenario evaluation; not yet executed" --source Agent
```

Use stable `eval.<scenario>.<case>` keys. Update the same keys on refinement and
remove cases that are explicitly out of scope. Do not append another full set on
every resume. Stay within the model's context-entry and value-size limits; group
related named capabilities into a representative case rather than exceeding them.
Also respect the aggregate shared-record budget in `sync.md`: field-by-field
validity does not account for server-added metadata. Avoid repeated boilerplate
descriptions, but never remove distinct expected behavior, authorization, or
write-confirmation requirements merely to fit.
If a large scope exceeds the budget, report it and retain the detailed cases in the
approved scenario contracts when authoring begins; never silently drop coverage.

Show two or three representative **prompt + expected behavior** pairs with the
plan, not a separate wall of prompts or a new mandatory interview turn. Label them
**Draft evaluation cases - not run**. Acknowledge that actual tests will be generated
as topics become available. Draft cases do not mean the maker approved a topic
mutation or that any runtime test passed.

## While executing the selected authoring/evaluation work

Check the plan's dependency brief and the actual active agent/topic files:

1. **No connected workspace or built topics yet:** keep the cases saved and name
   the specific prerequisite. Planning and unrelated work continue; no native
   generation or runtime success is claimed.
2. **New non-integration topic:** use
   `src/skills/topics/create-eval-driven/SKILL.md`. Supply the saved cases and
   scope as the starting contract. Preserve its explicit contract approval,
   checkpoint, topic review, materialization, static validation, dry run, push
   approval, and verification. Its materializer generates native tests alongside
   the topic; do not generate a second duplicate suite.
3. **Built topics, including integration topics:** continue directly to
   `src/skills/evaluations/create/SKILL.md` with the plan's selected topics,
   scenario cases, knowledge-source facts, and out-of-scope boundaries. That
   skill reads the real topics, generates the native evaluation files, validates
   them, and preserves review/dry-run/push/verify gates. Do not route an integration
   topic through the Phase-1-only eval-driven topic wrapper.
4. **Existing tests:** inspect and reuse them. Generate only missing coverage
   for changed/new topics; do not overwrite or delete reviewed tests without
   confirmation. Do not re-ask HR/IT, systems, or scope already supplied by the plan.

This continuation belongs to the selected build/evaluation task, not permission
to execute the entire rollout after merely showing a draft plan. When access or
source facts are missing, state the blocker and leave the relevant task pending.

## Capture facts, not claims

Keep these stages distinct:

| Stage | Evidence | Maker-facing label |
|-------|----------|-------------------|
| Draft cases | Saved plan context with prompts and expected behavior | Draft evaluation cases - not run |
| Generated tests | Actual native files and successful static checks | Tests generated and validated - not run |
| Published tests | Successful approved push and readback | Tests available in Copilot Studio - not run |
| Runtime results | Actual execution results from the supported runtime | Passed/failed with the observed results |

Capture the verified suite reference as `evalSuite` on the generation task and
sync it through `capture.md`. Runtime execution is a separate milestone producing
`evaluationResults`; do not complete that task from file generation or static
validation. Never fabricate runtime pass rates or mark publishing ready merely
because draft prompts exist.

Planning cases need no Copilot Studio access. Native generation needs the connected
workspace; publishing and runtime operations retain the existing role and consent
requirements. A plan nomination alone is not proof of those permissions.
