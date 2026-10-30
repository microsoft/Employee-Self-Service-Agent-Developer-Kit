# Interview questions

Ask these with `vscode_askQuestions`, at most three per round, in the order the rounds give. Fill `{…}` values from what you found. Drop an option that doesn't apply, and skip a question whose answer you already have. Mark the option the evidence supports as recommended; the recommendations below are defaults.

## Contents

- Round 1: Tool source
- Round 2: Who, Changes, Confirm scenarios
- Round 3: Plan, Partly achievable, Mixed requests
- Round 4: Tool binding, Provider details
- Round 5: Grounding
- Round 6: Confirmation, On behalf of others, Defaults
- Round 7: Review
- Round 8: Try it
- Going deeper

## Round 1

**Tool source**

```json
{
  "header": "Tools",
  "question": "Which tools should the skill use?",
  "options": [
    { "label": "workspace/ess-da-ga-skill-builder-capabilities", "description": "{N} tools from {SERVERS}", "recommended": true },
    { "label": "My agent's app package", "description": "Give me the path; I'll copy what's needed into workspace/ess-da-ga-skill-builder-capabilities" },
    { "label": "Another tool list", "description": "Give me the path to a tools.json or plugin file" }
  ],
  "allowFreeformInput": true
}
```

## Round 2

**Who**

```json
{
  "header": "Who",
  "question": "Who will use this?",
  "options": [
    { "label": "Employees", "description": "For their own requests and records", "recommended": true },
    { "label": "Managers", "description": "For their team" },
    { "label": "Both", "description": "Employees for themselves, managers for their team" }
  ],
  "allowFreeformInput": true
}
```

**Changes**

```json
{
  "header": "Changes",
  "question": "Should the agent create or change anything in these scenarios?",
  "options": [
    { "label": "Creates or changes records", "description": "For example opens a case, updates it or adds a comment" },
    { "label": "Only shows information", "description": "For example a balance, a status or a list" },
    { "label": "Both", "description": "Shows something, then lets the user act on it" }
  ],
  "allowFreeformInput": true
}
```

**Confirm scenarios**

```json
{
  "header": "Scenarios",
  "question": "Did I get the scenarios right?",
  "options": [
    { "label": "Yes, continue", "description": "Check these against your tools", "recommended": true },
    { "label": "Change something", "description": "Tell me what to add, remove or adjust" }
  ],
  "allowFreeformInput": true
}
```

## Round 3

**Plan** (after showing the analysis and any conflict message)

```json
{
  "header": "Plan",
  "question": "How should I package these scenarios?",
  "options": [
    { "label": "{RECOMMENDED_PLAN}", "description": "{WHY, in one line}", "recommended": true },
    { "label": "{ALTERNATIVE_PLAN}", "description": "{TRADE-OFF, in one line}" },
    { "label": "Fewer scenarios first", "description": "Pick which ones to build now" }
  ],
  "allowFreeformInput": true
}
```

Plans are concrete, for example "3 focused skills plus shared rules", "1 skill for HR cases", "Add to hr-cases", or "A few lines in the agent's instructions". Offer the maker's own request as the alternative when it differs from the recommendation.

**Partly achievable** (once per partly achievable scenario)

```json
{
  "header": "Gap",
  "question": "The tools can't {MISSING_CAPABILITY}. What should the skill do?",
  "options": [
    { "label": "Build what works now", "description": "Leave {MISSING_PART} out so the agent never offers it", "recommended": true },
    { "label": "Point users elsewhere", "description": "The skill sends users to a portal or contact for that part" },
    { "label": "Wait", "description": "Don't build this scenario until a tool exists" }
  ],
  "allowFreeformInput": true
}
```

**Mixed requests** (when the plan combines knowledge steps with actions, or has two or more area skills)

```json
{
  "header": "Mixed requests",
  "question": "Do people often combine things in one message, like a policy question and a request, or \"if I'm eligible, apply\"?",
  "options": [
    { "label": "Yes, often", "description": "Add one skill that splits and routes these requests across the others" },
    { "label": "Rarely", "description": "A short routing rule in the agent's instructions is enough", "recommended": true },
    { "label": "Not sure", "description": "Start without it; add it if testing shows mixed requests going wrong" }
  ],
  "allowFreeformInput": true
}
```

Move the recommendation to "Yes, often" when the maker's example requests already mix intents.

## Round 4

**Tool binding**

```json
{
  "header": "Explicitness",
  "question": "How exactly should {SKILL_NAME} spell out which actions to take?",
  "options": [
    { "label": "Exact for changes, flexible for lookups", "description": "Precise steps where a mistake would save wrong data; goals for lookups", "recommended": true },
    { "label": "Exact everywhere", "description": "Most predictable; more to update when the tools change" },
    { "label": "Describe goals only", "description": "Works across systems; less predictable, and the agent may guess names" }
  ],
  "allowFreeformInput": false
}
```

**Provider details** (skills with building-block steps only)

```json
{
  "header": "Details",
  "question": "Where should system details such as table and field names live?",
  "options": [
    { "label": "In the skill's steps", "description": "Simplest when the skill only ever uses this system", "recommended": true },
    { "label": "In a separate reference file", "description": "Easier to switch systems later; the agent reads it only when needed" }
  ],
  "allowFreeformInput": false
}
```

## Round 5

**Grounding**

```json
{
  "header": "Sources",
  "question": "What can I learn from to get the details right?",
  "options": [
    { "label": "The kit's ESS samples", "description": "Existing topics and template configurations for this scenario", "recommended": true },
    { "label": "My own topic or configuration", "description": "Give me the path" },
    { "label": "Example conversations or replies", "description": "Paste them or give me a file" },
    { "label": "Policy or process documents", "description": "Give me the path" }
  ],
  "allowFreeformInput": true
}
```

## Round 6

**Confirmation**

```json
{
  "header": "Confirm",
  "question": "Before the agent creates or changes something, how should the user confirm?",
  "options": [
    { "label": "Review a form and submit it", "description": "Safest; available when a form tool exists", "recommended": true },
    { "label": "Confirm in chat", "description": "The agent lists every value and waits for yes" }
  ],
  "allowFreeformInput": true
}
```

**On behalf of others**

```json
{
  "header": "For others",
  "question": "Can users do this for someone else?",
  "options": [
    { "label": "Only for themselves", "description": "Simplest and safest", "recommended": true },
    { "label": "Managers for their direct reports", "description": "The skill checks the reporting line first" },
    { "label": "Anyone they name", "description": "Only if the system itself enforces who may do this" }
  ],
  "allowFreeformInput": true
}
```

**Defaults**

```json
{
  "header": "Defaults",
  "question": "The previous process set {DEFAULTS}. Keep them?",
  "options": [
    { "label": "Keep them", "description": "Same behavior as today", "recommended": true },
    { "label": "Leave them unset", "description": "The system's own defaults apply" },
    { "label": "Change them", "description": "Tell me the values" }
  ],
  "allowFreeformInput": true
}
```

## Round 7

**Review**

```json
{
  "header": "Review",
  "question": "How does this look?",
  "options": [
    { "label": "Looks good", "description": "Move on to trying it", "recommended": true },
    { "label": "More exact", "description": "Spell out steps and values more precisely" },
    { "label": "More flexible", "description": "Fewer fixed steps; let the agent judge more" },
    { "label": "Split it", "description": "Make smaller skills" },
    { "label": "Add examples or rules", "description": "Tell me what's missing" }
  ],
  "allowFreeformInput": true
}
```

## Round 8

**Try it**

```json
{
  "header": "Try it",
  "question": "Should I run some practice checks before you add the skill?",
  "options": [
    { "label": "Run the checks", "description": "Compare the draft with the previous version on the example requests", "recommended": true },
    { "label": "Skip for now", "description": "Finish; you can test it in your agent" }
  ],
  "allowFreeformInput": false
}
```

## Going deeper

When an answer is vague, or the analysis or a draft shows a gap, ask one free-form follow-up before going further. Good follow-ups:

- "What else do people ask for in this area?" (more scenarios)
- "What would someone type when they need this but don't know the right words?" (trigger phrasings)
- "What does a good answer look like? Paste one if you have it." (reply template)
- "What goes wrong today, or what do employees get confused about?" (gotchas)
- "Is there anything the agent must never do here?" (prohibitions)
- "Which of these values does HR (or IT) set, rather than the employee?" (fields to leave out)
- "Which table or record type holds this?" (a building-block fact no source gave)
- "What should happen if nothing matches?" (fallback)
