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

# 5. Session Folder Structure

Each execution creates a timestamped folder.

```
logs/

    2026-07-18_14-32-05/

        session.log

        readiness_report.txt

        preview_report.txt

        migration_report.txt

        diagnostics_summary.txt
```

The timestamp format shall be:

```
YYYY-MM-DD_HH-MM-SS
```

---

# 6. Logger

The Logger is the only approved mechanism for runtime output.

The Logger writes simultaneously to:

* Console
* Session Log

Direct use of:

```
print()
```

is prohibited.

---

# 7. Log Levels

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

Migration

UpdateRuntimeProviderStep

Updated runtime provider.
```

---

# 9. Reporter

The Reporter generates customer-facing artifacts.

Reports include:

* Migration Readiness Report
* Preview Report
* Migration Report
* Diagnostics Summary

Reports are generated from the MigrationContext.

---

# 10. Migration Readiness Report

Generated during:

```
DISCOVER
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
PREVIEW
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
MIGRATE
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
