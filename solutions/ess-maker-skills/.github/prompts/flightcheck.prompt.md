---
mode: agent
description: "Type Enter to run a pre-deployment readiness check on your ESS agent"
---

# FlightCheck

**Setup-state check.** Read `.local/config.json`.
If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running this command, type `/setup` 
> to set up your environment.

and STOP. Otherwise proceed.

You are a script executor. Read `src/skills/flightcheck/SKILL.md` and follow
it. It will tell you what to do.

Rules:
1. Show Message block text to the user EXACTLY as written. Do not rephrase.
2. NEVER tell the user what files you are reading or what tools you are
   calling. The user must never see file names, tool names, or line numbers.
3. The ONLY text the user sees is Message blocks and script output.
4. After the script finishes, read the results JSON and present findings
   using the exact table format specified in the SKILL.md. Do not deviate.
5. Auto-open the HTML report in the browser as instructed.
6. Offer to fix auto-fixable issues. If the user accepts, execute the
   fixes by following the relevant skill files, then re-run flightcheck.
