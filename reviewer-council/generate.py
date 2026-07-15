#!/usr/bin/env python3
"""Compiles config.yaml + prompts/*.md into OpenCode agent/command definitions.

Source of truth:  config.yaml, prompts/*.md
Compiled output:  .opencode/agent/*.md, .opencode/command/*.md

Re-run this after editing config.yaml or any prompts/*.md file.
"""
import pathlib
import yaml

ROOT = pathlib.Path(__file__).parent
AGENT_DIR = ROOT / ".opencode" / "agent"
COMMAND_DIR = ROOT / ".opencode" / "command"

REVIEWER_META = {
    "alpha": ("Alpha", "Architecture Reviewer",
              "Reviews system design, architecture consistency, scalability, and long-term maintainability."),
    "beta": ("Beta", "Implementation Reviewer",
             "Reviews code correctness, bugs, tests, readability, and idiomatic implementation."),
    "gamma": ("Gamma", "Risk Reviewer",
              "Reviews hidden edge cases, security, failure modes, and adversarial risk."),
}

READ_ONLY_TOOLS = {"write": False, "edit": False, "patch": False}


def load_config():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def write_agent(name, description, model, prompt_path, mode, extra_tools=None):
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    body = (ROOT / prompt_path).read_text().strip()
    tools = dict(READ_ONLY_TOOLS)
    if extra_tools:
        tools.update(extra_tools)
    tools_yaml = "\n".join(f"  {k}: {str(v).lower()}" for k, v in tools.items())
    frontmatter = (
        f"---\n"
        f"description: {description}\n"
        f"mode: {mode}\n"
        f"model: {model}\n"
        f"temperature: 0.1\n"
        f"tools:\n{tools_yaml}\n"
        f"---\n\n"
    )
    (AGENT_DIR / f"{name}.md").write_text(frontmatter + body + "\n")


def write_orchestrator(cfg):
    reviewers = cfg["council"]["reviewers"]
    judge_cfg = cfg["council"]["judge"]
    judge_enabled = judge_cfg.get("enabled", True)
    max_iter = cfg["council"]["review_loop"]["max_iterations"]

    reviewer_lines = "\n".join(
        f"- @{key} ({REVIEWER_META[key][0]}, {REVIEWER_META[key][1]}) — {REVIEWER_META[key][2]}"
        for key in reviewers
    )

    if judge_enabled:
        decision_block = f"""4. Send all three reviews to @judge (final decision maker, model: {judge_cfg['model']}).
   @judge returns:
     DECISION: APPROVE | REQUEST_CHANGES
     REASON: ...
     REQUIRED_FIXES: ...
   Map APPROVE -> PASS and REQUEST_CHANGES -> FAIL for the final report below."""
    else:
        decision_block = """4. No judge is configured (council.judge.enabled: false in config.yaml).
   Decide DECISION yourself using the Decision Rules above — do not fabricate a judge verdict."""

    body = f"""---
description: Multi-model code reviewer to use with OpenCode. Emulates a council review board. Use when a deep code review with different models is requested. E.g. "Do a deep code review", "provide extended review", "Do all aspects code review".
mode: primary
tools:
  write: false
  edit: false
  patch: false
---

# Reviewer Council Orchestrator

You coordinate a council of independent reviewer subagents to validate a completed
implementation before it is considered done. You never edit code yourself — you only
collect context, dispatch reviewers, and synthesize their verdicts.

## Council members

{reviewer_lines}
{'- @judge (Final decision maker, model: ' + judge_cfg['model'] + ')' if judge_enabled else ''}

## When to run this

Invoke after: feature implementation, refactoring, database changes, API changes,
infrastructure changes.

Skip for: documentation-only changes, formatting-only changes, trivial renames.

## Review process

1. Collect the diff to review (`git diff`, or `git diff <base>...HEAD` if a base ref was
   given as an argument). If there is nothing to review, say so and stop.
2. Read the changed files enough to give each reviewer real context (not just the diff
   hunks) — imports, call sites, related tests.
3. Dispatch {', '.join('@' + k for k in reviewers)} in parallel via the task tool. Give each
   the same diff/context. Each returns PASS or FAIL with findings, per its own persona.
{decision_block}

## Decision rules (used directly when the judge is disabled, and to sanity-check the judge)

FAIL if:
- any Critical issue exists
- a security issue exists
- functionality is broken
- an architectural violation exists

PASS if:
- no Critical issues
- all reviewers agree it's acceptable

## Re-review loop

This command may be re-invoked after fixes are applied. Do not silently loop more than
{max_iter} review rounds (council.review_loop.max_iterations in config.yaml) on the same
set of changes — if it still fails after {max_iter} rounds, stop and escalate to the user
instead of continuing automatically.

## Output format

Always end with exactly this structure:

```
DECISION: PASS | FAIL

SUMMARY:
(short explanation)

FINDINGS:

[CRITICAL]
Reviewer:
Issue:
Impact:
Fix:

[WARNING]
Reviewer:
Issue:
Recommendation:
```
"""
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    (AGENT_DIR / "reviewer-council.md").write_text(body)


def write_command():
    COMMAND_DIR.mkdir(parents=True, exist_ok=True)
    body = """---
description: Run the reviewer council (architecture, implementation, risk + judge) over the current diff
agent: reviewer-council
---
Run a full council review of the pending changes. $ARGUMENTS
"""
    (COMMAND_DIR / "review-council.md").write_text(body)


def main():
    cfg = load_config()
    reviewers = cfg["council"]["reviewers"]
    judge_cfg = cfg["council"]["judge"]

    for key, rconf in reviewers.items():
        title, role, _ = REVIEWER_META.get(key, (key.title(), "Reviewer", ""))
        write_agent(
            name=key,
            description=f"{title}, the {role.lower()}. Invoked by @reviewer-council — not for direct use.",
            model=rconf["model"],
            prompt_path=rconf["prompt"],
            mode="subagent",
        )

    if judge_cfg.get("enabled", True):
        write_agent(
            name="judge",
            description="Final review judge. Resolves disagreements between the council reviewers. Invoked by @reviewer-council — not for direct use.",
            model=judge_cfg["model"],
            prompt_path=judge_cfg["prompt"],
            mode="subagent",
            extra_tools={"bash": False},
        )
    else:
        judge_path = AGENT_DIR / "judge.md"
        if judge_path.exists():
            judge_path.unlink()

    write_orchestrator(cfg)
    write_command()
    print(f"Wrote {AGENT_DIR} and {COMMAND_DIR}")


if __name__ == "__main__":
    main()
