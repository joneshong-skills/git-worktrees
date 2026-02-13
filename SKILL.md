---
name: git-worktrees
description: >-
  This skill should be used when the user needs to work on multiple
  branches simultaneously, "create worktree", "worktree", "parallel branches",
  "isolated workspace", "開 worktree", "平行分支", "獨立工作區",
  or before starting feature work that needs isolation from the current workspace.
version: 0.1.0
tools: Bash, Read, Glob
argument-hint: "branch name (e.g. feature/auth)"
---

# Git Worktrees

Create isolated workspaces sharing the same repository for parallel branch work.

## Overview

Git worktrees allow working on multiple branches simultaneously without switching.
Each worktree is a separate directory with its own working tree, sharing the same
`.git` data. Changes in one worktree don't affect others.

## Workflow

### Step 1 — Determine Directory

Check in priority order:

```bash
# 1. Check existing directories
ls -d .worktrees 2>/dev/null || ls -d worktrees 2>/dev/null

# 2. Check project docs for preference
grep -i "worktree" CLAUDE.md 2>/dev/null
```

If nothing exists, ask the user:
- `.worktrees/` — project-local, hidden (recommended)
- `worktrees/` — project-local, visible
- `~/worktrees/<project>/` — global location

### Step 2 — Safety Verification

For project-local directories, verify they're git-ignored:

```bash
git check-ignore -q .worktrees 2>/dev/null
```

If NOT ignored, add to `.gitignore` before proceeding:

```bash
echo ".worktrees/" >> .gitignore
git add .gitignore && git commit -m "Add .worktrees to gitignore"
```

### Step 3 — Create Worktree

```bash
BRANCH="feature/auth"
PROJECT=$(basename "$(git rev-parse --show-toplevel)")

# Create worktree with new branch
git worktree add .worktrees/$BRANCH -b $BRANCH

cd .worktrees/$BRANCH
```

### Step 4 — Project Setup

Auto-detect and run appropriate setup:

```bash
# Node.js
[ -f package.json ] && npm install

# Python
[ -f requirements.txt ] && pip install -r requirements.txt
[ -f pyproject.toml ] && pip install -e .

# Rust
[ -f Cargo.toml ] && cargo build

# Go
[ -f go.mod ] && go mod download
```

### Step 5 — Verify Clean Baseline

Run tests to ensure the worktree starts clean:

```bash
# Use project-appropriate command
npm test / pytest / cargo test / go test ./...
```

If tests fail, report failures and ask whether to proceed or investigate.

### Step 6 — Report

```
Worktree ready at <full-path>
Branch: <branch-name>
Tests: <N> passing, 0 failures
Ready to implement <feature>
```

## Managing Worktrees

```bash
# List all worktrees
git worktree list

# Remove a worktree (after merging)
git worktree remove .worktrees/feature/auth

# Prune stale worktrees
git worktree prune
```

## Quick Reference

| Situation | Action |
|-----------|--------|
| `.worktrees/` exists | Use it (verify ignored) |
| `worktrees/` exists | Use it (verify ignored) |
| Neither exists | Ask user preference |
| Directory not ignored | Add to .gitignore + commit |
| Tests fail at baseline | Report + ask user |
| No package manager file | Skip dependency install |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Worktree dir not gitignored | Always `git check-ignore` first |
| Hardcoding setup commands | Auto-detect from project files |
| Proceeding with failing tests | Report and get permission |
| Forgetting to remove after merge | `git worktree remove` + `git branch -d` |
| Checking out same branch in two worktrees | Git prevents this — use a different branch name |

## Integration

- Useful before **spec-kit** plan execution for isolated implementation
- Pairs with **team-tasks** for parallel multi-agent work on different branches

## Continuous Improvement

This skill evolves with each use. After every invocation:

1. **Reflect** — Identify what worked, what caused friction, and any unexpected issues
2. **Record** — Append a concise lesson to `lessons.md` in this skill's directory
3. **Refine** — When a pattern recurs (2+ times), update SKILL.md directly

### lessons.md Entry Format

```
### YYYY-MM-DD — Brief title
- **Friction**: What went wrong or was suboptimal
- **Fix**: How it was resolved
- **Rule**: Generalizable takeaway for future invocations
```

Accumulated lessons signal when to run `/skill-optimizer` for a deeper structural review.
