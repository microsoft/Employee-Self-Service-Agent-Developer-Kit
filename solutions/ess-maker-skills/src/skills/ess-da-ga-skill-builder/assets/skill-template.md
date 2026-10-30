---
name: <skill-name>
description: <What the skill does, in third person, with the user-visible outcome and scope.> Use when <the intents and the phrasings users actually type, including requests that don't name the area>. <Boundary with the closest neighbouring skill, if any.>
---

# <Title in sentence case>

<One or two sentences: what this skill covers and what it leaves to other skills. If the agent has a shared rules skill, say which of its rules apply.>

## Step 1: <Understand the request>

<What to extract from the user's message, and the one question to ask if something essential is missing.>

## Step 2: <Look up what the change needs>

<Exact tool and arguments for each lookup, or the goal and a default tool, per the maker's choice. Decision rules: one match, several matches, none.>

## Step 3: Confirm

<Open the form and stop; the user submits it. Or: one message with every value the change will use; skip it when the user already said "go ahead" with all values.>

## Step 4: <Make the change>

```text
<tool_name>(
  <argument>="<value or where it comes from>",
  ...)
```

<Defaults and value codes, with the source of each default.>

## Step 5: Verify and report

<Read the record back with the exact call. Reply in one sentence with the record number. Map errors to plain next steps.>

## Gotchas

- <A fact that defies a reasonable assumption, and what to do instead.>

## Don'ts

- <A mistake the model would plausibly make, and why it's wrong.>

<If needed:> Read [references/<subject>.md](references/<subject>.md) when <the moment it's needed>.
