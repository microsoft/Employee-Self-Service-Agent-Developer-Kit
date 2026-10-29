# Update Topic from Evaluation Context

This is a provisional compatibility alias. It does not own a separate scenario, materialization, approval, deployment, or testing lifecycle.

1. Carry the exact selected topic, user intent, supplied evaluation files or cases, valid thresholds, and approved source content.
2. Read `src/skills/topics/update/SKILL.md` and use it as the sole topic-update owner.
3. Preserve user evaluation data. A topic-only save may leave disclosed case mismatches.
4. When separate evaluation editing is requested, hand the exact selected sources and thresholds to the applicable evaluation skill through `src/skills/evaluations/dispatcher/SKILL.md`.
5. Do not create or refresh a scenario document, runtime manifest, or custom materialized evaluation folder.

Reassess this alias during later authorized runtime acceptance.
