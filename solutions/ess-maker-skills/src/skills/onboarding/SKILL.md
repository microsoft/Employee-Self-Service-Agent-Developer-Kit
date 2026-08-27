# Onboarding Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

Follow `src/reference/ui-formatting-guidelines.md` for every user-facing
instruction in this flow. Resolve its examples with the actual environment,
agent, product, and connector names before displaying them.

---

## Start

Run `python scripts/setup_state.py show --view current`. When `connect_ready` is
true, this is workspace bootstrap after foundation setup:

1. Initialize `workspace/onboarding/steps.md` from the template only when it is
   missing.
2. Do not render another setup checklist or repeat foundation prerequisites.
3. Resume from the first unchecked workspace-bootstrap step.
4. Go directly to **Step 1 and Step 2** below.

Only use the legacy standalone onboarding messages below when foundation setup
is not complete.

Read `workspace/onboarding/steps.md`.

If the file does not exist, copy `src/skills/onboarding/steps.md` to
`workspace/onboarding/steps.md` and go to Fresh Start below.

If the file exists but mentions "Copilot Studio extension", "Clone agent", or
"PAC CLI", delete it, re-copy from `src/skills/onboarding/steps.md`, and show:

**Message:**

I noticed your setup checklist is from an older version. I've reset it to the
current flow. Let's start fresh.

**End message.**

Then go to Fresh Start.

If the file contains a `Readiness check` row, delete only that row. Preserve
the completion state of the four remaining onboarding steps. The legacy
optional FlightCheck is no longer part of `/setup`.

If the file exists and all items are checked, show:

**Message:**

Setup is already complete! Type `/menu` to see what you can do.

**End message.**

Stop here.

If the file exists and some items are unchecked, find the first unchecked step
number. Show the checklist table (✅ for checked, ⬜ for unchecked) followed
by "Picking up at Step {N}." Then go to the matching step below.

### Fresh Start

**First run only — check the maker is in the right place.** Because foundation
setup is not complete here, this is a first run. Unless the maker already asked
to connect a deployed agent, ask one question before showing the checklist:

**Message:**

Before we connect your environment — which is closest to what you need?

1. **Plan your ESS rollout** — figure out what to build and who does each part.
   Choose this if you don't have an ESS environment yet or you're not sure where
   to start.
2. **Connect an existing environment** — you already have an ESS agent deployed
   and want to wire this kit to it.

**End message.**

- If the maker chooses **1** (or asks to plan, to learn about ESS, or says they
  have no environment yet), read `src/skills/planner/SKILL.md` and follow it
  instead — do **not** continue below.
- If the maker chooses **2**, continue with the checklist below.

**Message:**

| # | Step | Status |
|---|------|--------|
| 1 | Dataverse configured | ⬜ |
| 2 | Agent discovered | ⬜ |
| 3 | Agent extracted | ⬜ |
| 4 | MCP server started | ⬜ |

Let's get your environment set up. These four steps take about 5 minutes.

**End message.**

Go to Step 1.

---

## Step 1 and Step 2

Read `src/skills/onboarding/step1.md` and follow it.

(Step 1 handles connecting to Dataverse. When it finishes, it tells you to
read step1b.md, which discovers agents. When that finishes, it tells you to
read step2.md, which extracts the agent and starts the MCP server.)

---

## Step 3 or Step 4

Read `src/skills/onboarding/step2.md` and follow it.
