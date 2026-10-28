# Create Topic from Evaluation Context

This is a provisional compatibility alias. It does not own a separate scenario, materialization, approval, deployment, or testing lifecycle.

1. Carry the user's intent, supplied evaluation files or cases, valid thresholds, and approved source content.
2. Read `src/skills/topics/create/SKILL.md` and use it as the sole topic-authoring owner.
3. Use the supplied cases as authoring context without rewriting user evaluation data or claiming unsupported cases are runnable.
4. When separate evaluation generation or editing is requested, hand the exact selected sources and thresholds to `src/skills/evaluations/dispatcher/SKILL.md`.
5. Do not create a scenario document, runtime manifest, or custom materialized evaluation folder.

Reassess this alias during later authorized runtime acceptance.
