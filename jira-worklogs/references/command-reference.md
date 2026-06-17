# Command Reference

## Global options

| Option | Description |
|---|---|
| `--json` | Output as JSON (place before subcommand) |
| `-h`, `--help` | Show help |

## `list`

| Option | Required | Default | Description |
|---|---|---|---|
| `--year` | No | current year | Year (YYYY) |
| `--month` | No | current month | Month (MM) |
| `--project` | No | — | Filter by project key (e.g. `PROJ`) |
| `--task` | No | — | Filter by task ID (e.g. `PROJ-123`) |
| `--user` | No | authenticated user | Jira username or email |

## `add`

| Option | Required | Default | Description |
|---|---|---|---|
| `--task-id` | **Yes** | — | Task ID (e.g. `PROJ-123`) |
| `--log-time` | **Yes** | — | Hours to log (decimal, e.g. `2.5`) |
| `--comment` | No | empty | Worklog comment |
| `--year` | No | current year | Year for the worklog date |
| `--month` | No | current month | Month for the worklog date |
| `--date` | No | random workday in month | Specific date (`YYYY-MM-DD`), overrides `--year`/`--month` |

## `edit`

| Option | Required | Default | Description |
|---|---|---|---|
| `--task-id` | **Yes** | — | Task ID |
| `--wl-id` | **Yes** | — | Worklog ID (from `list` output) |
| `--log-time` | **Yes** | — | New time in hours |
| `--comment` | No | unchanged | New comment |

## `delete`

| Option | Required | Default | Description |
|---|---|---|---|
| `--task-id` | **Yes** | — | Task ID |
| `--wl-id` | **Yes** | — | Worklog ID (from `list` output) |

## Time format

`--log-time` accepts decimal hours and converts internally:

| Input | Sent to Jira |
|---|---|
| `1.0` | `1h` |
| `2.5` | `2h 30m` |
| `0.75` | `45m` |
| `0.25` | `15m` |

## JSON output structure

### list
```json
{
  "worklogs": [
    {
      "project_key": "PROJ",
      "project_name": "My Project",
      "task_key": "PROJ-123",
      "task_summary": "Fix login bug",
      "id": "10001",
      "comment": "Investigated issue",
      "hours": 2.5
    }
  ],
  "total_hours": 2.5
}
```

### add
```json
{"action": "add", "new": { ...worklog entry... }}
```

### edit
```json
{"action": "edit", "old": { ...worklog entry... }, "new": { ...worklog entry... }}
```

### delete
```json
{"action": "delete", "deleted": { ...worklog entry... }}
```
