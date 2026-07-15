---
name: reviewer-council
description: Multi-model code reviewer to use with OpenCode. Emulates council review board. Use when deep code review with different models is requested. E.g. "Do a deep code review", "provide extended review", "Do all aspects code review"
license: MIT
compatibility: Requires OpenCode.
  metadata:
  author: Paul A.
  version: "1.0"
---

# Reviewer Council Skill

## Purpose

Perform multi-agent review of completed implementation before task completion.

The council validates:
- correctness
- architecture
- security
- maintainability
- test coverage


## When to use

Invoke after:
- feature implementation
- refactoring
- database changes
- API changes
- infrastructure changes

Skip for:
- documentation-only changes
- formatting-only changes
- trivial renames


## Council Structure

The council consists of three reviewers:

### Alpha — Architecture Reviewer

Focus:
- system design
- architecture consistency
- scalability
- long-term maintainability


### Beta — Implementation Reviewer

Focus:
- code correctness
- bugs
- tests
- readability
- idiomatic implementation


### Gamma — Risk Reviewer

Focus:
- hidden edge cases
- security
- failure modes
- complex reasoning


## Review Process

1. Collect git diff
2. Analyze changed files
3. Run independent reviews
4. Aggregate findings
5. Decide PASS/FAIL


## Decision Rules

FAIL if:

- any Critical issue exists
- security issue exists
- functionality is broken
- architectural violation exists


PASS if:

- no Critical issues
- all reviewers agree acceptable


## Output Format

Return:

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


## Implementation

This spec is compiled into runnable OpenCode agents by `generate.py`.

- `config.yaml` — per-reviewer model + prompt assignment, judge on/off, `review_loop.max_iterations`
- `prompts/*.md` — the persona instructions for each reviewer/judge (source text)
- `.opencode/agent/*.md` — compiled output: `alpha`, `beta`, `gamma`, `judge` (subagents) and
  `reviewer-council` (the primary orchestrator that dispatches them and applies the Decision Rules above)
- `.opencode/command/review-council.md` — the `/review-council` entry point

After editing `config.yaml` or any `prompts/*.md` file, re-run:

```
python3 generate.py
```

to regenerate `.opencode/agent/` and `.opencode/command/`. Do not hand-edit files under
`.opencode/` — they're generated and will be overwritten.
