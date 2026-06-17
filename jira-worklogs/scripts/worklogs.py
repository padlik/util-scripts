#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "click>=8.0",
#     "requests>=2.25",
# ]
# ///
"""Jira worklog management CLI."""

import calendar
import json
import os
import random
import sys
from datetime import datetime, date, timezone
from typing import Optional

import click
import requests


# ---------------------------------------------------------------------------
# Jira API client
# ---------------------------------------------------------------------------

class JiraClient:
    def __init__(self):
        self.base_url = os.environ.get("WL_JIRA_URL", "https://jira.intetics.com").rstrip("/")
        token = os.environ.get("WL_JIRA_TOKEN", "")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict = None) -> dict:
        resp = self.session.get(f"{self.base_url}/rest/api/2{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict) -> dict:
        resp = self.session.post(f"{self.base_url}/rest/api/2{path}", json=json)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, json: dict) -> dict:
        resp = self.session.put(f"{self.base_url}/rest/api/2{path}", json=json)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> None:
        resp = self.session.delete(f"{self.base_url}/rest/api/2{path}")
        resp.raise_for_status()

    def get_current_user(self) -> dict:
        return self._get("/myself")

    def search_issues(self, jql: str, fields: list[str] = None) -> list[dict]:
        """Return all issues matching JQL, handling pagination."""
        if fields is None:
            fields = ["summary", "project"]
        start_at = 0
        page_size = 50
        all_issues = []
        while True:
            data = self._get("/search", params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": page_size,
                "fields": ",".join(fields),
            })
            all_issues.extend(data.get("issues", []))
            total = data.get("total", 0)
            start_at += len(data.get("issues", []))
            if start_at >= total:
                break
        return all_issues

    def get_worklogs(self, issue_key: str) -> list[dict]:
        """Return all worklogs for an issue, handling pagination."""
        start_at = 0
        page_size = 100
        all_logs = []
        while True:
            data = self._get(f"/issue/{issue_key}/worklog", params={
                "startAt": start_at,
                "maxResults": page_size,
            })
            all_logs.extend(data.get("worklogs", []))
            total = data.get("total", 0)
            start_at += len(data.get("worklogs", []))
            if start_at >= total:
                break
        return all_logs

    def get_worklog(self, issue_key: str, worklog_id: str) -> dict:
        return self._get(f"/issue/{issue_key}/worklog/{worklog_id}")

    def add_worklog(self, issue_key: str, time_spent: str, comment: str = "", started: datetime = None) -> dict:
        if started is None:
            started = datetime.now(tz=timezone.utc)
        started_str = started.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        return self._post(f"/issue/{issue_key}/worklog", json={
            "timeSpent": time_spent,
            "comment": comment,
            "started": started_str,
        })

    def update_worklog(self, issue_key: str, worklog_id: str, time_spent: str, comment: str = None) -> dict:
        payload = {"timeSpent": time_spent}
        if comment is not None:
            payload["comment"] = comment
        return self._put(f"/issue/{issue_key}/worklog/{worklog_id}", json=payload)

    def delete_worklog(self, issue_key: str, worklog_id: str) -> None:
        self._delete(f"/issue/{issue_key}/worklog/{worklog_id}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def random_workday(year: int, month: int) -> date:
    """Return a random Monday–Friday within the given month."""
    last_day = calendar.monthrange(year, month)[1]
    workdays = [
        date(year, month, d)
        for d in range(1, last_day + 1)
        if date(year, month, d).weekday() < 5  # 0=Mon … 4=Fri
    ]
    return random.choice(workdays)


def hours_to_jira_duration(hours: float) -> str:
    """Convert decimal hours to Jira timeSpent string (e.g. 2.5 → '2h 30m')."""
    total_minutes = round(hours * 60)
    h, m = divmod(total_minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def seconds_to_hours(seconds: int) -> float:
    return round(seconds / 3600, 2)


def format_entry(project_key: str, project_name: str,
                 task_key: str, task_summary: str,
                 wl_id: str, comment: str, hours: float) -> str:
    comment_text = (comment or "").strip() or "(no comment)"
    return (
        f"[{project_key}] {project_name} , "
        f"[{task_key}] {task_summary} , "
        f"[{wl_id}] {comment_text}, "
        f"{hours} Hrs."
    )


def entry_dict(project_key: str, project_name: str,
               task_key: str, task_summary: str,
               wl_id: str, comment: str, hours: float) -> dict:
    return {
        "project_key": project_key,
        "project_name": project_name,
        "task_key": task_key,
        "task_summary": task_summary,
        "id": wl_id,
        "comment": (comment or "").strip(),
        "hours": hours,
    }


def parse_worklogs_in_range(worklogs: list[dict], start: date, end: date,
                             username: Optional[str]) -> list[dict]:
    """Filter worklogs to those started within [start, end] and optionally by author."""
    result = []
    for wl in worklogs:
        started_str = wl.get("started", "")
        try:
            # Jira format: 2024-01-15T09:00:00.000+0000
            wl_date = datetime.strptime(started_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (start <= wl_date <= end):
            continue
        if username:
            author = wl.get("author", {})
            author_name = author.get("name", "") or author.get("emailAddress", "")
            if author_name.lower() != username.lower():
                continue
        result.append(wl)
    return result


def resolve_username(client: JiraClient, user_opt: Optional[str]) -> str:
    """Return the effective username: provided value or current user's name."""
    if user_opt:
        return user_opt
    me = client.get_current_user()
    return me.get("name") or me.get("emailAddress") or ""


def month_range(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def get_issue_meta(issue: dict) -> tuple[str, str, str, str]:
    """Return (project_key, project_name, task_key, task_summary)."""
    fields = issue.get("fields", {})
    project = fields.get("project", {})
    return (
        project.get("key", ""),
        project.get("name", ""),
        issue.get("key", ""),
        fields.get("summary", ""),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--json", "output_json", is_flag=True, default=False,
              help="Output results as JSON")
@click.pass_context
def cli(ctx, output_json):
    """Jira worklog manager.

    \b
    Environment variables:
      WL_JIRA_URL    Jira server base URL  (default: https://jira.intetics.com)
      WL_JIRA_TOKEN  Bearer token for auth (default: empty)

    Run a subcommand with --help for more details.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = output_json
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command("list")
@click.option("--year", default=lambda: datetime.now().year, show_default="current year",
              type=int, help="Year (YYYY)")
@click.option("--month", default=lambda: datetime.now().month, show_default="current month",
              type=int, help="Month (MM)")
@click.option("--project", default=None, help="Filter by project key")
@click.option("--task", default=None, help="Filter by task ID (e.g. PROJ-123)")
@click.option("--user", default=None, help="User email (default: authenticated user)")
@click.pass_context
def list_cmd(ctx, year, month, project, task, user):
    """List worklogs for a given month."""
    output_json = ctx.obj.get("json", False)
    client = JiraClient()
    username = resolve_username(client, user)
    start, end = month_range(year, month)

    start_str = start.strftime("%Y/%m/%d")
    end_str = end.strftime("%Y/%m/%d")

    jql = f'issue in workedIssues("{start_str}", "{end_str}", "{username}")'
    if project:
        jql += f' AND project = "{project}"'
    if task:
        jql += f' AND issue = "{task}"'

    try:
        issues = client.search_issues(jql, fields=["summary", "project"])
    except Exception as e:
        click.echo(f"Error fetching issues: {e}", err=True)
        sys.exit(1)

    total_hours = 0.0
    entries = []
    for issue in issues:
        proj_key, proj_name, task_key, task_summary = get_issue_meta(issue)
        try:
            worklogs = client.get_worklogs(task_key)
        except Exception as e:
            click.echo(f"  Warning: could not fetch worklogs for {task_key}: {e}", err=True)
            continue
        filtered = parse_worklogs_in_range(worklogs, start, end, username)
        for wl in filtered:
            hours = seconds_to_hours(wl.get("timeSpentSeconds", 0))
            total_hours += hours
            if output_json:
                entries.append(entry_dict(proj_key, proj_name, task_key, task_summary,
                                          wl["id"], wl.get("comment", ""), hours))
            else:
                click.echo(format_entry(proj_key, proj_name, task_key, task_summary,
                                        wl["id"], wl.get("comment", ""), hours))

    if output_json:
        click.echo(json.dumps({"worklogs": entries, "total_hours": round(total_hours, 2)}, indent=2))
    else:
        click.echo(f"\nTOTAL: {round(total_hours, 2)} Hrs.")


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@cli.command("add")
@click.option("--task-id", required=True, help="Task ID (e.g. PROJ-123)")
@click.option("--log-time", required=True, type=float, help="Time to log in hours (e.g. 2.5)")
@click.option("--comment", default="", help="Worklog comment")
@click.option("--year", default=lambda: datetime.now().year, show_default="current year",
              type=int, help="Year (YYYY)")
@click.option("--month", default=lambda: datetime.now().month, show_default="current month",
              type=int, help="Month (MM)")
@click.option("--date", "log_date", default=None,
              help="Specific date (YYYY-MM-DD); overrides --year/--month")
@click.pass_context
def add_cmd(ctx, task_id, log_time, comment, year, month, log_date):
    """Add a worklog entry to a task."""
    output_json = ctx.obj.get("json", False)
    client = JiraClient()

    if log_date:
        work_date = datetime.strptime(log_date, "%Y-%m-%d").date()
    else:
        work_date = random_workday(year, month)

    started = datetime(work_date.year, work_date.month, work_date.day,
                       9, 0, 0, tzinfo=timezone.utc)

    time_spent = hours_to_jira_duration(log_time)

    try:
        wl = client.add_worklog(task_id, time_spent, comment, started)
        issue = client.search_issues(f'issue = "{task_id}"', fields=["summary", "project"])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if issue:
        proj_key, proj_name, task_key, task_summary = get_issue_meta(issue[0])
    else:
        proj_key, proj_name, task_key, task_summary = ("", "", task_id, "")

    hours = seconds_to_hours(wl.get("timeSpentSeconds", 0))
    if output_json:
        click.echo(json.dumps({
            "action": "add",
            "new": entry_dict(proj_key, proj_name, task_key, task_summary,
                              wl["id"], wl.get("comment", ""), hours),
        }, indent=2))
    else:
        click.echo("NEW:")
        click.echo(format_entry(proj_key, proj_name, task_key, task_summary,
                                wl["id"], wl.get("comment", ""), hours))


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------

@cli.command("edit")
@click.option("--task-id", required=True, help="Task ID (e.g. PROJ-123)")
@click.option("--wl-id", required=True, help="Worklog ID")
@click.option("--log-time", required=True, type=float, help="New time in hours")
@click.option("--comment", default=None, help="New worklog comment (optional)")
@click.pass_context
def edit_cmd(ctx, task_id, wl_id, log_time, comment):
    """Edit an existing worklog entry."""
    output_json = ctx.obj.get("json", False)
    client = JiraClient()

    try:
        old_wl = client.get_worklog(task_id, wl_id)
        issue = client.search_issues(f'issue = "{task_id}"', fields=["summary", "project"])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if issue:
        proj_key, proj_name, task_key, task_summary = get_issue_meta(issue[0])
    else:
        proj_key, proj_name, task_key, task_summary = ("", "", task_id, "")

    old_hours = seconds_to_hours(old_wl.get("timeSpentSeconds", 0))
    time_spent = hours_to_jira_duration(log_time)

    try:
        new_wl = client.update_worklog(task_id, wl_id, time_spent, comment)
    except Exception as e:
        click.echo(f"Error updating worklog: {e}", err=True)
        sys.exit(1)

    new_comment = comment if comment is not None else old_wl.get("comment", "")
    new_hours = seconds_to_hours(new_wl.get("timeSpentSeconds", 0))

    if output_json:
        click.echo(json.dumps({
            "action": "edit",
            "old": entry_dict(proj_key, proj_name, task_key, task_summary,
                              wl_id, old_wl.get("comment", ""), old_hours),
            "new": entry_dict(proj_key, proj_name, task_key, task_summary,
                              wl_id, new_comment, new_hours),
        }, indent=2))
    else:
        click.echo("OLD:")
        click.echo(format_entry(proj_key, proj_name, task_key, task_summary,
                                wl_id, old_wl.get("comment", ""), old_hours))
        click.echo("NEW:")
        click.echo(format_entry(proj_key, proj_name, task_key, task_summary,
                                wl_id, new_comment, new_hours))


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@cli.command("delete")
@click.option("--task-id", required=True, help="Task ID (e.g. PROJ-123)")
@click.option("--wl-id", required=True, help="Worklog ID")
@click.pass_context
def delete_cmd(ctx, task_id, wl_id):
    """Delete a worklog entry."""
    output_json = ctx.obj.get("json", False)
    client = JiraClient()

    try:
        wl = client.get_worklog(task_id, wl_id)
        issue = client.search_issues(f'issue = "{task_id}"', fields=["summary", "project"])
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if issue:
        proj_key, proj_name, task_key, task_summary = get_issue_meta(issue[0])
    else:
        proj_key, proj_name, task_key, task_summary = ("", "", task_id, "")

    hours = seconds_to_hours(wl.get("timeSpentSeconds", 0))

    try:
        client.delete_worklog(task_id, wl_id)
    except Exception as e:
        click.echo(f"Error deleting worklog: {e}", err=True)
        sys.exit(1)

    if output_json:
        click.echo(json.dumps({
            "action": "delete",
            "deleted": entry_dict(proj_key, proj_name, task_key, task_summary,
                                  wl_id, wl.get("comment", ""), hours),
        }, indent=2))
    else:
        click.echo("DELETED:")
        click.echo(format_entry(proj_key, proj_name, task_key, task_summary,
                                wl_id, wl.get("comment", ""), hours))


if __name__ == "__main__":
    cli()
