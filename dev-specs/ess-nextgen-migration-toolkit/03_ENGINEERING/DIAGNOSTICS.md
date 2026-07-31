# DIAGNOSTICS.md

# ESS NextGen Migration Toolkit — Diagnostics & Observability Specification
**Status:** Draft v1.0
**Owner:** Anil Kumar Adepu

> **Purpose**
>
> This document defines the diagnostics, logging, reporting, and observability requirements for the ESS NextGen Migration Toolkit.
>
> Diagnostics exist to provide customers and engineers with sufficient information to understand, troubleshoot, and validate every migration session.
>
> Every execution of the toolkit shall produce a complete diagnostic session.

---

# 1. Objectives

The Diagnostics framework shall provide:

* Real-time execution visibility
* Persistent session logs
* Customer-readable reports
* Engineering diagnostics
* Deterministic troubleshooting

Diagnostics shall never influence migration behavior.

---

# 2. Design Principles

## DIAG-001

Diagnostics are passive.

They observe execution.

They never change execution.

---

## DIAG-002

Every execution creates exactly one diagnostic session.

---

## DIAG-003

Every message is timestamped.

---

## DIAG-004

Every diagnostic belongs to one session.

---

## DIAG-005

Business logic never writes directly to stdout or files.

All output flows through the Diagnostics framework.

---

# 3. Diagnostics Architecture

The generic diagnostics infrastructure (Logger, Session Manager) lives in
`src/core/logging/`. The **Reporter** — which renders the ESS customer-facing
`migration_report.md` — lives in the service layer at `src/service/reporter.py`,
so `core/` stays product-agnostic (see `REPOSITORY_STRUCTURE.md`).

The Session Manager owns the bundle folder and takes the report filename as a
parameter (framework default: the neutral `telemetry_report.md`); the ESS
toolkit supplies `migration_report.md` via `service.constants.REPORT_FILENAME`,
so the customer-facing filename is domain-owned, not baked into `core/`.

```
Pipeline Step

↓

Logger

↓

Session Manager

↓

Session Folder
```

Reports are generated independently.

```
Migration Context

↓

Reporter

↓

Reports
```

---

# 4. Session Lifecycle

Every execution creates a unique session.

```
Session Start

↓

Initialize Logger

↓

Initialize Reports

↓

Pipeline Execution

↓

Generate Summary

↓

Close Session
```

---

# 5. Session Bundle (the product)

Every execution produces exactly **one** timestamped **session bundle** — a
single self-contained folder. After a run, the user is presented with exactly
**two files**:

```
output/

    session-2026-07-18_14-32-05/

        migration_report.md     # customer-facing report (see section 9)
        session.log             # engineering diagnostics log (see section 6)
```

| File                 | Audience        | Purpose                                                    |
| -------------------- | --------------- | ---------------------------------------------------------- |
| `migration_report.md`| **Customer**    | The human-readable outcome: summary, changes, warnings.    |
| `session.log`        | **ESS Engineer**| The full diagnostics log, shared for debugging issues.     |

Especially in **Discover** and **Preview** modes, `migration_report.md` *is* the
deliverable. `session.log` is what the customer forwards (or a support engineer
retrieves) when something needs investigation. Two files, one folder — nothing
scattered across the filesystem.

The session folder name is `session-<timestamp>`, where the timestamp format is:

```
YYYY-MM-DD_HH-MM-SS
```

## 5.1 How the two files are produced (read-only steps)

A Pipeline Step **never** opens, reads, or writes a diagnostics/report file
itself. Instead:

1. When the run starts, the **Logger** installs a stdout/stderr tee (section
   6.1), so **`session.log`** becomes a full live transcript of the CLI for the
   whole run.
2. Throughout execution, each step reports through the framework Logger using two
   channels (section 6.2): the **engineer channel** (`LogDebug`/`LogInfo`/…) goes
   to the CLI and is mirrored into `session.log`; the **customer channel**
   (`LogChange`/`LogAdvisory`) appends structured entries to the report model
   only.
3. Every step also **accumulates** structured outcome data into the shared
   `MigrationContext` — `context.Logs`, `context.Warnings`, `context.Errors`, and
   `context.Changes` (see DOMAIN_MODEL.md → MigrationContext). This is the report
   model the customer channel writes to.
4. A **single terminal step**, `GenerateMigrationReport()`, runs last in the
   Output Pipeline and asks the **Reporter service** to render
   **`migration_report.md`** from those collectors.

This keeps DIAG-005 and PIPE-006 intact — business steps never touch the
filesystem; only the Logger and the Reporter service write, and both write only
into the session bundle.

---

# 6. Logger

The Logger is the only approved mechanism for runtime output. Direct use of
`print()` from business logic is prohibited (DIAG-005). The Logger is
initialized once at the **application entry point** (the composition root, before
the pipeline runs) and is the single I/O boundary for all console and log output.

## 6.1 Transcript capture (session.log is a full CLI replay)

When the Logger initializes, it **installs a stdout/stderr tee** for the process.
From that line onward, **every byte written to the CLI** — Logger output,
incidental third-party library output, and tracebacks alike — is mirrored into
`output/session-<timestamp>/session.log`. The engineer therefore receives a
complete, replayable transcript of the run, not just hand-picked log lines.

> Capture begins at the **Python application entry** (the migration run), not in
> the shell wrapper. Environment provisioning output (`uv sync`, etc.) is **not**
> part of the session bundle — the app owns the session folder and its log.

## 6.2 Two channels

The Logger exposes two semantically distinct channels:

| Channel            | Method (illustrative) | Console (CLI) | `session.log` | `migration_report.md` |
| ------------------ | --------------------- | :-----------: | :-----------: | :-------------------: |
| **Engineer**       | `LogDebug` / `LogInfo` / `LogWarning` / `LogError` | ✅ (via tee) | ✅ | ✗ |
| **Customer**       | `LogChange` / `LogAdvisory` | ✗ | ✗ | ✅ (rendered) |

* **Engineer channel** — ordinary diagnostics. Prints to the CLI as usual; the
  transcript tee (6.1) mirrors it into `session.log`. This is the developer/ESS
  debugging stream and honors the log levels in section 7.
* **Customer channel** — customer-facing narrative. It does **not** print to the
  CLI or `session.log`. Instead it appends **structured entries** to an
  intermediate **report model** (see 6.3) that the Reporter later renders into
  the fancy `migration_report.md`. Example (Discover mode): recording each
  unsupported component in a readable way so the customer can decide whether to
  proceed with writeback.

  The customer channel has **two intent-revealing methods**, each feeding a
  distinct report section (do not conflate them):

  | Method        | Report model collector          | `migration_report.md` section        | Records… |
  | ------------- | ------------------------------- | ------------------------------------ | -------- |
  | `LogChange`   | `context.Changes` (`ChangeEntry`) | `## Changes`                        | **What the toolkit did** — a successful transformation, keyed by `RULE-xxx` (e.g. Runtime Provider CA → DA). |
  | `LogAdvisory` | `context.Warnings` / `Errors` / `Logs` (`DiagnosticEntry`, routed by `severity`) | `## Warnings — Manual Review Required` / Errors | **What the customer must act on** — a manual-review advisory with `severity` + `recommendation`. |

  `LogChange` is the changelog; `LogAdvisory` is the action list. Keeping them
  separate lets the Reporter render Changes and Warnings without re-classifying a
  single blended stream.

## 6.3 Report model (intermediate)

Customer-channel calls accumulate into a structured, in-memory **report model**
(the `MigrationContext` collectors — `Changes`, `Warnings`, `Errors`, plus
summary counters; see DOMAIN_MODEL.md). The Reporter (section 9) renders this
model into `migration_report.md` at the end of the run. Persisting the model as
an intermediate `report.json` is permitted internally as a render input, but it
is **not** a session-bundle artifact — the bundle remains exactly the two files
in section 5.

---

# 7. Log Levels

The log levels below apply to the **engineer channel** (console + `session.log`).

Supported log levels:

* TRACE
* DEBUG
* INFO
* WARNING
* ERROR
* FATAL

Production execution defaults to:

```
INFO
```

---

# 8. Log Format

Every log entry shall include:

* Timestamp
* Severity
* Pipeline Stage
* Pipeline Step
* Message

Example:

```
2026-07-18 14:33:51

INFO

Transformation

ApplyDaCompatibilityStep

Applied DA-compatibility rewrite (template, model kind).
```

---

# 9. Reporter

The Reporter (ESS service layer, `src/service/reporter.py`) renders the single
customer-facing artifact — **`migration_report.md`** — from the
`MigrationContext` collectors. It is the only component (besides the Logger) that
writes files. It reads the base `ExecutionContext` collectors and the generic
`mode` string, so it depends on the framework but is not part of it.

`migration_report.md` is one document composed of sections, so the customer has
a single readable file rather than many:

* **Summary** — one-pager (mode, duration, components, migrated, warnings, errors, writeback)
* **Changes** — human-readable per-rule change log (section 9.1)
* **Warnings** — manual-review items only (section 9.2)

The report is mode-aware: it presents the Readiness view in Discover, the
Preview view in Preview, and the Migration view in Migrate (sections 10–13). The
engineering `session.log` is produced separately by the Logger (section 6).

## 9.1 Changes section

The heart of the report: what changed, grouped by Migration Rule.

```
## Changes

### DA Compatibility — Model & Template
Template           CA → DA
Model Kind         PreviewModels → MicrosoftCopilotModels

### RULE-002 — Replaced EndConversation
Topic              Employee Leave
Replacements       1

### RULE-003 — Deprecated Topics
Trigger            OnActivity
Topic              Employee Context
Reason             Unsupported in DA
```

## 9.2 Warnings section

Manual-review items only.

```
## Warnings — Manual Review Required

Topic            Employee Context
Reason           OnActivity trigger unsupported.
Recommendation   Move logic into OnConversationStart.
```

---

# 10. Migration Readiness Report

Generated during:

```
READONLY (Discover intent)
```

Contains:

* Environment
* Agent
* Candidate Components
* Customized Components
* Net-new Components
* Unsupported Components
* Warnings

---

# 11. Preview Report

Generated during:

```
READONLY (Preview intent)
```

Contains:

* Proposed transformations
* Validation results
* Expected writeback
* Warnings
* Errors

No environment changes occur.

---

# 12. Migration Report

Generated during:

```
WRITEBACK (Migrate intent)
```

Contains:

* Components processed
* Components migrated
* Components skipped
* Validation results
* Writeback summary
* Errors
* Duration

---

# 13. Diagnostics Summary

Provides a concise overview.

Includes:

* Session ID
* Execution Mode
* Duration
* Total Components
* Successful Transformations
* Failures
* Warnings

---

# 14. Session Metadata

Every session records:

* Session ID
* Start Time
* End Time
* Toolkit Version
* Execution Mode
* Environment ID
* Agent Name

This metadata appears in all reports.

---

# 15. Error Reporting

Every error shall include:

* Timestamp
* Pipeline Stage
* Pipeline Step
* Exception Type
* Human-readable Message
* Suggested Remediation (where applicable)

Stack traces should be included only in the session log.

---

# 16. Progress Reporting

Long-running operations should report progress.

Example:

```
Discovering Components...

[#####-----] 52%

128 / 245 Components
```

Progress reporting is informational only.

---

# 17. Performance Metrics

Diagnostics shall record:

* Total execution time
* Time per pipeline stage
* Time per pipeline step

Metrics are intended for troubleshooting and optimization.

---

# 18. Diagnostic Ownership

| Component           | Responsibility    |
| ------------------- | ----------------- |
| Logger              | Runtime output    |
| Reporter            | Customer reports  |
| Session Manager     | Session lifecycle |
| Diagnostics Summary | Session overview  |

---

# 19. Testing

Diagnostics should be verified through:

* Unit Tests
* Golden Tests for report generation
* Integration Tests for session creation

Reports should be deterministic for identical inputs.

---

# 20. Future Evolution

Future enhancements may include:

* Rich HTML reports
* JSON export
* Performance dashboards

Core logging behavior should remain stable.

---

# 21. Traceability

**Consumes**

* DOMAIN_MODEL.md
* PIPELINES.md
* IMPLEMENTATION_GUIDE.md
* CODING_STANDARDS.md

**Referenced By**

* TESTING.md
* TASKS.md

The Diagnostics framework provides complete observability for every migration session. It ensures customers receive clear reports while enabling engineering teams to troubleshoot issues using a single self-contained diagnostic session.
