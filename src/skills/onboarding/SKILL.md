# Onboarding Script

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

---

## Start

Read `my/onboarding/tasks.md`.

If the file does not exist, copy `src/skills/onboarding/tasks.md` to
`my/onboarding/tasks.md` and go to Fresh Start below.

If the file exists but mentions "Copilot Studio extension", "Clone agent", or
"PAC CLI", delete it, re-copy from `src/skills/onboarding/tasks.md`, and show:

**Message:**

I noticed your setup checklist is from an older version. I've reset it to the
current flow. Let's start fresh.

**End message.**

Then go to Fresh Start.

If the file exists and all items are checked, show:

**Message:**

Setup is already complete! Type `/menu` to see what you can do.

**End message.**

Stop here.

If the file exists and some items are unchecked, find the first unchecked step
number. Show the checklist table (✅ for checked, ⬜ for unchecked) followed
by "Picking up at Step {N}." Then go to the matching step below.

### Fresh Start

**Message:**

| # | Task | Status |
|---|------|--------|
| 1 | Dataverse configured | ⬜ |
| 2 | Agent discovered | ⬜ |
| 3 | Agent extracted | ⬜ |
| 4 | MCP server started | ⬜ |

Let's get your environment set up. This takes about 5 minutes.

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

---

## Step 5

Read `src/skills/onboarding/step3-flightcheck.md` and follow it.
