---
name: good-case-create
description: Opens a new HR case for the employee in the HR service that matches their issue, and confirms it with its case number. Use when someone wants to open, raise or report an HR case, or says something like "my payslip is wrong".
---

# Open an HR case

## Step 1: Find the service

`list_records(table="hr_service", query="active=true^nameLIKE<word>", fields="sys_id,name")`

Read [references/services.md](references/services.md) when no service matches.

## Step 2: Confirm

Confirm the service and the summary with the user before creating anything.

## Step 3: Create

```text
create_record(table="hr_case", body={"hr_service": "<sys_id>", "short_description": "<summary>"})
```

## Step 4: Verify

`get_record(table="hr_case", sys_id="<new sys_id>", fields="number,state")`, then reply with the case number.
