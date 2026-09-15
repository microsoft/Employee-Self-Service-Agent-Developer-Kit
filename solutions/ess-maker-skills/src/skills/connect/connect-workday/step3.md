# Connect Workday Step 3: Verify Connection

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 3.1 — Confirm runtime health

```
python scripts/flightcheck/cli.py --checkpoint WD-RUN-001
```

**If `PASSED` (or `Warning` from an inconclusive live probe backed by recent
run history):** continue to 3.2.

**If `FAILED`:**

**Message:**

The user-context redirect is wired, but the Workday connector isn't
responding right now. This is usually a connection or tenant issue, not
something this flow can fix. Run `/flightcheck` for the full diagnosis.

**End message.**

Stop here.

---

## 3.2 — List available Workday topics

List the Workday-prefixed topics under
`workspace/agents/{slug}/topics/`.

Update `.local/connect/connect-workday/steps.md` step 3 to `- [x]`.

**Message:**

✅ Connection verified!

| # | Step | Status |
|---|------|--------|
| 1 | Extension verified | ✅ |
| 2 | Topics wired | ✅ |
| 3 | Connection verified | ✅ |

This agent can now use these Workday topics:

{list the Workday topics found}

| Command | What it does |
|---------|-------------|
| `/create` | Create a new topic that uses Workday |
| `/flightcheck` | Run the full readiness check |
| `/menu` | See all available commands |

**End message.**
