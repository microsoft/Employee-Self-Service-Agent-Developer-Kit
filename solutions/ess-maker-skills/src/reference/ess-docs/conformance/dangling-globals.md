# Dangling Global reference check

Analysis guidance for the **cross-topic `Global.*` reference** check used by the `topics/review` skill.
It surfaces `Global.X` references that a topic reads but that are never made available anywhere in the
agent — usually a typo, or a reference to a variable that was renamed or removed.

## How availability works

A `Global.*` variable is available to every topic in the agent once **any** topic writes it
(`variable: Global.X`) or a variable file declares it (`name: X`). Many Globals are populated at runtime
by shared system topics (for example a reference-data topic that fills lookup tables), so a topic can
legitimately read a Global it does not write itself. Availability therefore has to be resolved across the
whole agent, not from the single topic under review.

## Running the check

Run the detector, which aggregates readers, writers, and declarations across the agent and reports the
references that resolve to nothing:

```
python scripts/scan_globals.py --agent {agent-slug} --topic {topic-stem}
```

- `{agent-slug}` is the agent folder name under `workspace/agents/`.
- `{topic-stem}` restricts the reported anomalies to those read by the topic under review; availability
  is still resolved across the whole agent.

The detector prints each dangling reference with the sites that read it. It assigns no severity and makes
no judgement — it only reports references with no writer and no declaration. If the script fails to run,
skip this check and continue with the rest of the review.

## Turning an anomaly into a finding

For each dangling reference the detector reports, decide whether it is a real defect:

- A reference that is a near-miss of a real variable name (extra/missing letter, wrong casing, wrong
  separator) is almost certainly a **typo** — the intended variable exists but this reference will always
  read blank.
- A reference with no plausible intended target may be a variable that was **renamed or removed**, or a
  read that was never wired up.

Apply the precision bar and reachability scoring from the shared
[`finding-contract.md`](finding-contract.md) — a dangling read on a path a normal user hits is
higher severity than one on an unreachable path. This check uses the `BTDG` finding-ID prefix. Report
confirmed findings with the shared output format, locating each by the reading action's node identity
(`id` / `displayName` / `kind`) and naming the intended variable in the suggested fix.
