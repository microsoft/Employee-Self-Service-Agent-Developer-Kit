# Test / Debug Topic Skill

Guides a maker through debugging a topic they just created or updated — driving it, confirming the reply is real, checking the fix doesn't break the intent the eval cases encode, and localizing a fault to either the flow it calls or the topic's own internal state.

**Eval cases are the read-only intent guardrail.** A topic's **evaluation cases** (authored upstream via the `evaluations/create` skill, stored as `EvaluationData` under `{agent.folder}/evaluations/`) encode the intended customer-facing behaviour — especially failure handling (backend down, record missing, connection unauthorized). This skill treats them as a **guardrail: a fix must not break the intent they encode.** It reads that intent; it does not grade the topic against the cases and it never edits them. If a topic has no eval cases yet, that is a signal to author them with `evaluations/create` — not work this skill does. Absent evals, drive a representative trigger phrase instead.

## The debug-and-validate loop

Debugging a topic is one loop, repeated per probe until the behaviour is right. It is not a heavyweight process — it is the loop you already run naturally — but the moves are:

1. **Build the probe set** — the inputs you will drive, and you drive a *set*, not one prompt. It always includes **failure-triggering probes** (missing record, unauthorized / needs-consent, malformed or out-of-range input) alongside the **happy path**, because error handling is the behaviour most likely to be wrong and least likely to be exercised by hand. Derive the set from the topic's trigger phrases, its backend calls, and any eval cases — you do not wait for the maker to invent the failure prompts. Two kinds feed the set: **eval-case inputs** (the `input` of an `EvaluationData` case, driven to check a fix still preserves the intent that case encodes) and **exploratory probes** (ad-hoc prompts for behaviour no case covers yet). Drive the failure probes **first** — they are the hardest and the highest-value.
2. **Drive and capture** the full reply.
3. **Confirm the reply is real** — classify it (`ok` vs consent gate / timeout / empty) so you never diagnose a phantom reply.
4. **Check the behaviour against intent** — by the kind of probe: where an eval case covers this behaviour, confirm the fix doesn't break the intent it encodes; on an exploratory probe, judge against your own intent for the behaviour you are building. Use deterministic substring checks (`--expect` / `--reject`) as a quick sanity signal, and — where a substring match can't tell whether the reply matches the intent — a **best-effort LLM judge over the capture** (a semantic "does this reply satisfy what this probe is checking for?"). This is a guardrail on your fix, not a grade of the topic — both signals are advisory and inform your diagnosis.
5. **If it diverges, localize the fault** — flow run history, the Topic checker, or a planted DBG node — and **fix the topic, or its flow / template config.**
6. **Re-drive the same probe** until the behaviour holds, then move to the next.

Both kinds run in the **same loop** and usually coexist — the common state is a topic with some eval cases plus behaviour still being built. Existing eval cases are a **standing regression guardrail** the whole time: even while you drive exploratory probes on new ground, a fix must not break the intent the existing cases encode. When an exploratory probe's behaviour stabilizes, capture it as a case with `evaluations/create` so the new ground becomes guardrail too.

**The one invariant:** every fix lands on the **topic** (or its flow / template config) — never on the eval cases. The eval cases are the fixed intent you check against; changing them to make a topic behave defeats the guardrail.

This skill **drives the topic automatically** — it launches (or attaches to) an InPrivate browser on the agent's test pane, sends the probe, and captures the reply — then runs deterministic tools over that reply so you are not debugging on a phantom reply or guessing at hidden state:

- **`scripts/drive_topic.py`** — drive a probe against the already-open, signed-in test pane and classify the reply in one step. Attach with `--no-launch --cdp <endpoint>`; the browser is launched and signed into as a separate chat-driven step (see "Get the browser ready" below), not by surfacing the tool's own sign-in prompt. InPrivate is deliberate: it signs in as a *test* account, not the ambient corp account.
- **`scripts/reply_signal.py`** — the classifier `drive_topic` uses (also runnable standalone on a pasted reply): real answer vs consent gate / timeout / empty.
- **`scripts/flow_run_inspect.py`** — for flow-backed topics, read the flow's per-action run history (did the connector run, which action failed, why is the reply generic). Interpret it with `src/reference/ess-docs/operations/flow-run-inspection.md`.
- **`scripts/plant_debug.py`** / **`scripts/strip_debug.py`** — for topic-internal silent-state bugs, plant a temporary DBG node that projects a topic variable into the transcript, re-drive, read it, then strip it.
- **`scripts/topic_checker_capture.py`** — for an **unexplained** "something went wrong" reply, surface the Copilot Studio authoring-canvas **Topic checker** (PowerFx / card errors that local diagnostics and a runtime drive both miss). Read-only; escalates command bar → 'More' overflow → tells you to check manually if the panel can't be surfaced.

## Rules

- **Always strip.** A DBG node planted with `plant_debug.py` is a live mutation of the deployed topic. It MUST be removed with `strip_debug.py` before you finish — never leave debug noise in a shipped topic. If you plant, you strip, even if the diagnosis fails.
- **Classify before you trust a reply.** Do not diagnose topic logic on a reply until `reply_signal.py` says it is `ok`. A consent gate or empty reply will make any conclusion vacuous.
- **Drive is automated; the sign-in is a human turn.** Getting a browser ready is two phases — the agent launches an InPrivate Edge (CDP port open) and ends its turn so the user signs in as a test account, then attaches with `--no-launch` and drives. Never block a subprocess waiting for sign-in. Once attached, `drive_topic.py` sends the turn and captures the full reply (all bubbles — a card plus a separate DBG bubble is one reply). If it can't reach a signed-in test pane, it **warns and tells you how to fix it** rather than failing silently; only then paste the reply into `reply_signal.py` by hand.
- **Never mutate the eval cases.** They are the read-only guardrail.
- **`python` may be the `py` launcher.** The commands below are written `python scripts/...`; if `python` is not on PATH (common on Windows), use the `py` launcher (`py scripts/...`, or `py -3 scripts/...`) or `python3` — same arguments.
- **Check, don't assume.** An `ok` reply is a real turn, not a correct one — a `400` error reply is also `ok`. Check the content against intent: deterministic `--expect` / `--reject` substrings as a sanity signal, plus a best-effort LLM judge over the capture when a literal substring match can't confirm the reply matches intent. The eval cases are the intent you check against and are **read-only here** — a fix must not break them, and you never edit them to make a topic behave.
- **TRACK PROGRESS.** Use the todo list tool to track the loop so the maker can see where you are.

## Classify the topic — which fault surface?

Read the topic file and decide which fault surface applies — it drives which tool you reach for:

- **Flow-backed** — the topic calls a shared system topic (`BeginDialog` to `...System...`) or an `InvokeFlowAction`. Faults here are usually in the flow / connector path → **Inspect the flow run**.
- **Topic-only** — the topic branches on its own variables (a `ConditionGroup`, a parsed table, a count) with no backend call, or the backend call succeeded but a downstream branch/variable is wrong → **Plant a DBG node**.

Most real topics are both; work outward — confirm the drive, then the flow, then the topic's internal state.

## Get the browser ready (launch → sign in → attach)

The drive is automated, but the **sign-in is not** — a test account has to sign in once in a real browser window, and that is a human step across a turn boundary. Handle it as a **chat** interaction, never by surfacing a terminal prompt: do **not** use `drive_topic.py`'s own launch path here (it prints a "press Enter here" prompt and blocks on `input()` — that presents the CLI as the UX, which we avoid). Instead, two phases:

1. **Launch** an InPrivate Edge with the CDP debug port open (non-blocking), pointed at the agent's test pane, then **end the turn with a chat message**: tell the maker to sign in as their test account in the window that opened, and to reply here when they're ready to test.

   ```
   msedge --inprivate --user-data-dir="<fresh temp dir>" --no-first-run --remote-debugging-port=9222 "<test-pane-url>"
   ```

   - **The dedicated `--user-data-dir` is mandatory.** Without a fresh profile dir, a second `msedge` invocation just opens a tab in an already-running Edge and **silently ignores** `--remote-debugging-port`, so nothing is attachable.
   - **InPrivate is mandatory, not cosmetic.** A normal-profile launch (`--user-data-dir` alone) lets Windows WAM / sync silently sign in the **ambient corp account** — and can flip-flop between identities across launches. InPrivate disables that SSO so the user gets a clean account picker and signs in as the **test** account.
   - The **test-pane URL** is the agent overview page; `drive_topic.py` builds it from `--env`/`--bot` (or `.local/config.json`) — read it from there.
   - **Port** defaults to **9222**. If another session already holds it, pick another (e.g. `9224`) and use it in both the launch and the attach below.

2. **When the maker replies in chat that they're signed in / ready**, attach and drive. Because the browser is already up, use `--no-launch` so the tool attaches without re-launching (and without any interactive prompt of its own):

   ```
   python scripts/drive_topic.py --prompt "<probe input>" --no-launch --cdp http://localhost:9222
   ```

   Subsequent drives in the same session reuse that window — no re-launch, no re-sign-in.

## Build the probe set (failure paths first)

Before driving, assemble the **set** of prompts you will exercise — and drive the set by default, don't wait for the maker to think of test inputs. Every set has two halves:

- **Happy path** — the normal request the topic exists to serve, built from its trigger phrases (e.g. "create a ticket for a broken laptop").
- **Failure paths** — the error conditions the topic must handle. Derive these from what the topic actually does:
  - **backend-call topics** (a `BeginDialog` to a `...System...` topic or an `InvokeFlowAction`) → a **missing record** ("get details for ticket ZZZ0000"), an **unauthorized / needs-consent** call, and a **backend error** (bad request the connector rejects).
  - **input-collecting topics** (cards, prompts, parsed values) → **malformed / out-of-range input**, an **empty required field**, and a value that trips the topic's own validation.

Present the set to the maker so they can adjust it, but the default is to **exercise it** — the failure prompts are the point, and they are the ones a maker skips when testing by hand. Prefer real eval-case `input`s where they exist; fill the gaps with exploratory prompts you generate. Then drive each through the loop below, **failure probes first**.

## Drive, confirm, and validate the reply

Work through the probe set (failure first). For each probe:

1. Drive it and classify the reply in one step (the browser is already up and signed in from the step above):

   ```
   python scripts/drive_topic.py --prompt "<probe input>" --no-launch --cdp http://localhost:9222
   ```

   - **If no browser is ready yet**, `drive_topic.py` *can* launch one itself (omit `--no-launch`, pass `--env`/`--bot` or run from the workspace) — but that path blocks on an interactive sign-in prompt and only suits a human running it at a terminal. When the **agent** drives, do the two-phase launch above instead, so the sign-in is a chat turn, not a blocked subprocess.
   - **The CDP port and concurrent sessions.** The tool attaches to `http://localhost:9222` by default. **If a CDP browser is already up on that port, it attaches to it** — if that browser belongs to another debug session or a different agent, you would drive the **wrong** pane. The tool prints what it attached to; verify it is *your* agent. To run a **second, concurrent session** (or dodge a port another session holds), pass `--cdp http://localhost:<other-port>` and launch on that same port — the two sessions stay isolated.
   - It prints the `signal`, a one-line remediation, and the captured reply.
   - **If it can't reach a signed-in test pane**, it warns and tells you exactly what to do (launch / sign in) — it does **not** fail silently. Fix that and re-run, or fall back to a manual drive: send the prompt in the Test pane, copy the full reply, and run `python scripts/reply_signal.py "<pasted reply>"`.
   - **After a publish** (e.g. you just planted a DBG node or edited the topic), add `--new-session` so the drive starts a fresh test conversation — otherwise stale routing from the pre-publish session can answer the turn.
   - **Sanity-check the content** with `--expect "<text the reply must contain>"` and/or `--reject "<text it must not>"` (both repeatable). A failed assertion returns a non-zero exit — this is the axis that separates a real success from a `400`/runtime error, since **both are `ok` turns** (a real error reply is a real turn). Where an eval case names expected content, use its `expectedOutput` substrings here as the intent to hold to.
   - **Capture blind spot — adaptive card dropdowns.** The transcript capture reads the rendered card **text**, but the **options inside an `Input.ChoiceSet` (a dropdown) are not in the scrapeable DOM** — a populated dropdown reads as empty/absent in the capture. Do **not** conclude a dropdown is empty from the reply alone. To verify a dropdown's contents, plant a DBG node (below) that projects the choice table — e.g. `CountRows(Topic.CategoryChoices)` and `First(Topic.CategoryChoices).title` — and read the values from the DBG bubble. The Power Fx table is the oracle; the rendered dropdown is a lossy view of it.

2. Act on the signal:
   - **`consent_gate`** — the backend never ran; the reply is a "Connect to continue" / connection-manager prompt. Authorize the connection in the test pane, then re-drive. Do NOT diagnose logic on this reply.
   - **`timeout`** — re-drive; a hibernating backend may need a warm-up call first.
   - **`empty`** — confirm the topic actually triggered (right trigger phrase, no conflicting topic), then re-drive.
   - **`ok`** — a real reply. Note that a genuine backend error reply (e.g. `Error code: 400`) is also `ok` — it is a real turn, so the tool prints an **`advisory: reply is error-shaped`** line and you must check it, not assume success. Check the behaviour against intent — the eval case's where one covers this probe, your own for an exploratory probe: use `--expect` / `--reject` for the substrings, and — where a substring match can't tell whether the reply matches the intent — apply a best-effort LLM judge over the capture (a semantic "does this reply satisfy what this probe is checking for?"). If the behaviour holds, move to the next probe; if it diverges, localize the fault (below) and fix the topic / flow / config.

Only proceed past this step on an `ok` reply.

## Inspect the flow run (flow-backed topics)

When the reply is a real answer but wrong (generic error, missing data), read the flow's run history — the decisive "why" surface.

1. Get the **flow id** (GUID) of the flow the topic calls. The **environment id** is resolved automatically from the active agent's Dataverse org URL — pass `--environment <env-guid>` only to override. The tool acquires a Flow-scoped token automatically via the kit's sign-in (set `FLOW_API_TOKEN` only to override with your own).
2. Dump the latest run's action cascade:

   ```
   python scripts/flow_run_inspect.py --flow <flow-guid>
   ```

   Add `--environment <env-guid>` to target a specific environment, or `--run <run-guid>` to inspect a specific run.

3. Interpret the cascade using `src/reference/ess-docs/operations/flow-run-inspection.md`. The key trap: a `runAfter:[Failed]` handler that shows **Succeeded** does NOT mean the flow succeeded — the containing scope can still be **Failed** and a catch-all Response can discard its output, masking (say) a connector **400** as a generic **500**. The **first `Failed` action + its statusCode** is usually the real fault.

If the run history localizes the fault to the flow, fix the flow (see the `workflows/update` skill) — not the topic. To exercise the flow **in isolation** (Power Automate manual Test, no topic) or to dig into the request-body / template-config layer the orchestrator builds, use the `workflows/test` skill (`src/skills/workflows/test/SKILL.md`) — this section covers the flow as reached *through the conversation*; `workflows/test` covers it flow-first. If the flow ran clean but the topic still behaves wrong, the fault is topic-internal → **Plant a DBG node**. If the flow ran clean (or the topic isn't flow-backed) **and the error is generic and unexplained** — "something went wrong" with no status code, table, or field named — the surface may be a publish-time authoring defect the runtime never articulates → **Surface the Topic checker**.

## Surface the Topic checker (unexplained authoring-canvas errors)

A generic, unexplained error reply — no status code, no named table/field — is frequently the runtime surface of a **publish-time authoring defect** (an invalid Adaptive Card JSON, a broken PowerFx expression) that a runtime drive and flow inspection both miss, because the defect never runs cleanly enough to produce a specific fault. `reply_signal.py`'s error-shaped advisory tells you the reply is an error; when it carries **no actionable detail**, reach for the Topic checker.

```powershell
python scripts/topic_checker_capture.py --topic-id <GUID> --json
```

The tool follows an escalation ladder against the authoring canvas and reports exactly which rung it reached:

1. **Command bar** — clicks the Topic checker button when it's directly visible, captures each error (message + linked node/field where available).
2. **'More' overflow** — when the button is hidden, opens the '…' overflow menu and clicks it there.
3. **Manual fallback** — the panel has additional rendering conditions that can't be automated. If neither rung surfaces it, the tool reports `not run` (NOT `clean`) and advises you to **open the Topic checker manually in Copilot Studio and read the errors yourself** — a run that never happened is never reported as a passing check.

Each captured error names a `componentId` (a GUID) rather than the topic's display name — resolve it via `.component-map.json`. Fix the named card/expression, republish, and re-drive. If the tool reports `not run`, do not conclude the topic is clean — surface the checker manually before moving on.

## Plant a DBG node (topic-internal silent state)

When the reply looks plausible and the flow run shows nothing wrong, but a branch fired wrong or a field came back blank, make the deciding topic state visible.

1. Pick the **action id** to instrument (the action that *populates* the variable you doubt) and the variable(s) to print. The DBG node must land **after** the populating action, or it reads a not-yet-set value. **If the DBG message never renders, execution isn't reaching it** — an error-valued inferred input can fail evaluation *before* your instrumentation point. Move the DBG node **one boundary earlier** (before the `Split`/`First`/parse/card that consumes the input) until it renders; the first boundary where it stops rendering is where the value is failing.
2. Plant and publish. Pass `--yes` — the script otherwise prompts on `input()`, which a non-interactive subprocess cannot answer and which reads as a hang. This is a **live but reversible** change to the deployed topic: it is byte-reversible and you always strip it (step 5), and it targets the maker's own dev topic — so you do **not** need a separate approval turn. Just tell the user you're planting a temporary debug node, then plant.

   ```
   python scripts/plant_debug.py --topic <topic> --after <action-id> --activity "DBG branch={Topic.SomeVar} count={Topic.SomeCount}" --yes
   ```

   `--topic` accepts the friendly file stem (e.g. `servicenow-hrsd-get-cases-by-status`), the display name, or the full schemaname — it resolves to the immutable schemaname via `.component-map.json`. This PATCHes the topic, records provenance to `.local/.dbg_provenance.json`, and publishes (retrying transient publish throttling automatically). It refuses to double-plant.

3. **Re-drive** the topic with a fresh session so the just-published change is what answers (`python scripts/drive_topic.py --prompt "<same probe>" --new-session`). The DBG line renders as its own bubble and is captured with the rest of the reply; read the `DBG ...` values from the output.
4. Interpret: an empty value where you expected data, or a branch tag that does not match the path you thought fired, is your fault.
5. **Strip — always:**

   ```
   python scripts/strip_debug.py --yes
   ```

   This restores the topic byte-identically, publishes, and clears the provenance. Run it even if the diagnosis was inconclusive. (`--yes` for the same reason as the plant — the bare command prompts on `input()` and would hang as a subprocess.)

**Recovering a stranded plant (crash / walk-away).** A plant is durable, not tied to this session: `plant_debug.py` records the node to `.local/.dbg_provenance.json` on disk before you strip. So if the tool crashes, the chat closes, or you simply walk away after planting, the DBG node is **still live in the deployed topic** — it is not auto-removed. To recover, run `python scripts/strip_debug.py --yes` from the same workspace at any later time: it reads the persisted provenance, removes the node, republishes, and clears the file (a no-op if the node is already gone). A leftover `.local/.dbg_provenance.json` is the signal that a plant is outstanding; `plant_debug.py` also refuses to plant again while one exists, so a stranded plant can't be silently double-planted.

## Report

Summarize for the maker:

- The drive-outcome signal and, if it was not `ok`, what unblocked it.
- If flow-inspected: the first failing action + statusCode and whether the fault is in the flow or the topic.
- If DBG-planted: the decisive variable/branch value and what it revealed — and confirm the plant was stripped.
- The concrete fix and where it belongs (topic YAML, flow, template config).

If you planted a DBG node at any point, confirm `strip_debug.py` ran and `.local/.dbg_provenance.json` is gone before you finish.
