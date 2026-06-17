---
name: jira-worklogs
description: Manages Jira worklogs via a Python CLI. Use when user asks to log time, list worklogs, add a worklog, edit hours, delete a worklog entry, or view time logged in Jira. Triggers on phrases like "log time to Jira", "show my worklogs", "add worklog", "how many hours did I log", "edit my worklog", or "delete a worklog entry".
metadata:
  author: paulpronko
  version: 1.0.0
---

# Jira Worklogs

A single-file Python CLI (`worklogs.py`) for managing Jira worklogs. Uses Jira REST API V2 with Bearer token auth.

## Setup

Before running any command, ensure:

1. Activate the environment:
```sh
source /home/paul/.config/wl_jira/.env
```
2. Required environment variables:
   - `WL_JIRA_URL` — Jira server base URL (default: `https://jira.intetics.com`)
   - `WL_JIRA_TOKEN` — Bearer token for authentication

If the token is missing or invalid, commands will fail with an HTTP error. Ask the user to set `WL_JIRA_TOKEN`.

---

## Instructions

### General recomendations
- Use `--json` before the subcommand for machine-readable output.

### Step 1: Identify the action

Determine what the user wants to do:

| Goal | Command |
|---|---|
| View logged time for a month | `list` |
| Add a new worklog to a task | `add` |
| Change hours/comment on a worklog | `edit` |
| Remove a worklog entry | `delete` |

### Step 2: Run the command

#### List worklogs
```bash
uv run ./scripts/worklogs.py --json list [--year YYYY] [--month MM] [--project KEY] [--task PROJ-123] [--user email]
```
- Defaults to current month and authenticated user.
- Use `--project` or `--task` to filter.
- Use `--json` before the subcommand for machine-readable output.

#### Add a worklog
```bash
uv run ./scripts/worklogs.py --json add --task-id PROJ-123 --log-time HOURS [--comment "text"] [--year YYYY] [--month MM] [--date YYYY-MM-DD]
```
- `--log-time` is in decimal hours (e.g. `2.5` = 2h 30m).
- Without `--date`, picks a random working day (Mon–Fri) in the specified month.
- Without `--year`/`--month`, defaults to the current month.

#### Edit a worklog
```bash
uv run ./scripts/worklogs.py --json edit --task-id PROJ-123 --wl-id WORKLOG_ID --log-time HOURS [--comment "new text"]
```
- `--wl-id` is the worklog ID shown in brackets in `list` output: `[10045]`.
- Prints the old and new values.

#### Delete a worklog
```bash
uv run ./scripts/worklogs.py --json delete --task-id PROJ-123 --wl-id WORKLOG_ID
```

#### JSON output (any command)
```bash
uv run ./scripts/worklogs.py --json -- list --year 2026 --month 4
```

### Step 3: Interpret output

**list** (human format):
```
[PROJ] Project Name , [PROJ-123] Task Summary , [10001] comment, 2.5 Hrs.

TOTAL: 10.0 Hrs.
```

**list** (JSON):
```json
{"worklogs": [{"project_key": "PROJ", "task_key": "PROJ-123", "id": "10001", "comment": "...", "hours": 2.5}], "total_hours": 10.0}
```

**add**: prints `NEW:` line with the created entry.
**edit**: prints `OLD:` then `NEW:` lines.
**delete**: prints `DELETED:` line.

---

## Common Issues

### HTTP 401 / 403
Cause: Invalid or missing `WL_JIRA_TOKEN`.
Solution: Set `export WL_JIRA_TOKEN=your_token` and re-run.

### HTTP 404 on task ID
Cause: Task ID doesn't exist or user lacks access.
Solution: Verify the task ID format (e.g. `PROJ-123`) and permissions.

### "workedIssues" returns no results
Cause: No worklogs logged in that month for the user.
Solution: Try a different month, or check `--user` matches the Jira account name.

### Wrong worklog edited/deleted
Cause: Wrong `--wl-id`. Use `list` first to find the worklog ID in `[brackets]`.

---

## Examples

**Example 1: List April 2026 worklogs**
```bash
uv run ./scripts/worklogs.py --json list --year 2026 --month 4
```

**Example 2: Log 3 hours to a task in the current month**
```bash
uv run ./scripts/worklogs.py --json add --task-id PROJ-42 --log-time 3 --comment "Implemented feature X"
```

**Example 3: Fix a wrong time entry**
First, find the worklog ID:
```bash
uv run ./scripts/worklogs.py --json list --task PROJ-42
```
Then edit it:
```bash
uv run ./scripts/worklogs.py --json edit --task-id PROJ-42 --wl-id 10045 --log-time 2.5
```

**Example 4: Get JSON output for scripting**
```bash
uv run ./scripts/worklogs.py --json list --year 2026 --month 4 | jq '.total_hours'
```

See `references/command-reference.md` for full option reference.
