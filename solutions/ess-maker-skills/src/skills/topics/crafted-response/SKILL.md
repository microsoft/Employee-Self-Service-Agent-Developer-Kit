# Create or Update a Crafted-Response Topic

Create or update one response-only topic in the selected editable Dev agent. The topic recognizes one intent, sends the maker's exact approved static response and optional support URL, then ends. Saving is a native Copilot Studio component operation, not a local-file edit or publication.

## Boundaries

- Require canonical setup readiness for the active agent and verify the fresh Dev target through the operation below. Keep the selected account, environment, ring, agent, and native component identity.
- Support only a name, intent, trigger phrases, exact response, and optional maker-approved HTTP(S) support URL. Do not invent employee policy, destinations, or approved wording.
- Do not add questions, cards, conditions, backend calls, handoffs, integration configuration, agent-wide instructions, or multiple intents.
- Update only topics returned by this native crafted-response path. Packaged, system, integration, and other unrecognized topics are unsupported; do not convert or recreate them to bypass this boundary.
- Do not activate, publish, deactivate another topic, use Dataverse, run `push.py`, or invoke the retained legacy/eval-driven topic-authoring skills.
- Respect the maker's intended scope. Do not change unrelated topics or agent settings.

If the requested behavior is outside this shape, explain the specific unsupported part and stop without writing. If the shape is unclear, ask what the topic should answer before choosing a design.

## 1. Resolve the request and selected target

Read `.local/setup/config.json` and `.local/config.json`. Require `schema_version: 4` and the active agent's `connect_ready: true`. Otherwise direct the maker to `/setup` and stop.

Run commands from the Maker Kit workspace root. Use a new, nonexisting path under `.local\topic-authoring\` for every output snapshot:

```powershell
python scripts\topic_authoring.py list --output ".local\topic-authoring\{unique-list}.json"
```

Read the returned target and topic list. For an update, identify the exact topic by its returned native ID; ask the maker to choose if ambiguous. Never select a different agent or update by guessed schema or filename.

```powershell
python scripts\topic_authoring.py read --component-id "{native-id}" --output ".local\topic-authoring\{unique-before}.json"
```

Retain this fresh read for the update baseline. If the requested topic is not supported or is missing, explain that result rather than creating a replacement.

## 2. Collect and preview the exact change

Collect the topic name, one intent, trigger phrases, exact approved answer, and optional support URL. Propose wording only when requested; obtain approval of the actual text. Updates keep the existing name and native identity.

Any topic change is a candidate for a matching agent-instruction change. Assess alignment with current agent instructions across at least:

- Intent and scope.
- Routing and disambiguation.
- Policy and confirmation requirements.
- Response and grounding expectations.
- Fallback behavior.
- Native identity and existence.

Preview any needed instruction change separately and obtain approval before applying it through a supported operation.

Write a request JSON object under `.local\topic-authoring\`:

```json
{
  "name": "Maker-approved topic name",
  "intent": "The single intent this topic answers",
  "triggers": ["An approved trigger phrase"],
  "response": "The exact approved response.",
  "supportLink": "https://approved.example/support"
}
```

Omit `supportLink` when none is approved. It is appended after the response with a blank line. Do not add fields or author arbitrary YAML.

Run the chosen operation without `--yes`:

```powershell
python scripts\topic_authoring.py create --request "{request-path}" --output ".local\topic-authoring\{unique-preview}.json"
python scripts\topic_authoring.py update --request "{request-path}" --expected "{before-path}" --output ".local\topic-authoring\{unique-preview}.json"
```

Run only the applicable command. Read the preview and show the agent/environment, name, intent, trigger phrases, full exact response, and support URL or its absence. For updates show the current and proposed values. Explain that save changes the selected Dev component but does not activate or publish it.

Obtain explicit approval before saving. Offer save, change details, or cancel without preselecting save. Cancellation sends no mutation. A changed proposal requires another preview and approval.

Same-name prevention is a case-insensitive name check within the selected agent, not semantic deduplication. If creation finds that name, stop; do not overwrite or silently switch to update.

## 3. Save once and inspect authoritative readback

After approval, run the same chosen command with the same request, adding `--yes` and a fresh output path. For creation also pass `--expected "{create-preview-path}"` to bind the approved values and target. For updates retain `--expected "{before-path}"` as the native read baseline. The CLI records capability usage; do not emit a duplicate event.

Read the returned result. Claim saved only when `saved` is true and authoritative readback verifies the returned component ID, schema, content, and diagnostics. An update must retain the exact native ID and schema.

Keep creation inactive. Updates preserve the existing native state. Do not claim publication, activation, discoverability in employee chat, or a verified conversation from save/readback.

On failure, retain the exception, service details, request/component identity, and any output path. Report what is known and what remains unverified. Do not blind-retry a create, recreate a missing update target, bypass a concurrent-edit rejection, or add retry/rollback/recovery machinery. Use existing native reads when needed to establish saved state; an uncertain result remains unverified.

Finish with the verified save result, selected agent, and the explicit fact that no publication was performed. Do not offer an employee test as proof of an inactive, unpublished topic.
