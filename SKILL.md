---
name: git-worktrees
description: >-
  This skill should be used when the user needs to work on multiple
  branches simultaneously, "create worktree", "worktree status", "merge worktree",
  "cleanup worktree", "worktree done", "parallel branches", "isolated workspace",
  "開 worktree", "平行分支", "獨立工作區", "worktree 狀態", "合併 worktree",
  "清理 worktree", or before starting feature work that needs isolation.
version: 0.2.0
tools: Bash, Read, Glob
argument-hint: "<command> [branch] (e.g. create auth-login, status, done feature/auth, cleanup --all)"
---

# Git Worktrees

Full lifecycle management for git worktrees: create → status → done → cleanup.

## Agent Delegation

Delegate worktree operations to `worker` agent.

## Sub-Commands

| Command | Usage | Purpose |
|---------|-------|---------|
| **create** | `create [name]` | New worktree with smart naming + dependency install + baseline test |
| **status** | `status` | Overview all active worktrees with branch/dirty/ahead-behind info |
| **done** | `done [branch]` | Merge completed worktree back to base branch |
| **cleanup** | `cleanup [branch\|--all]` | Remove worktree(s) with optional backup |

If no sub-command is given or intent is ambiguous, detect from context or ask.

---

## Create

### Step 1 — Smart Naming

When the user provides a description rather than a branch name, auto-generate one:

1. **Detect type** from keywords:

| Type | Signals |
|------|---------|
| `feature/` | add, build, implement, new (default) |
| `hotfix/` | fix, bug, urgent, broken |
| `experiment/` | try, explore, PoC, spike, test-if |
| `refactor/` | refactor, clean, restructure, optimize |

2. **Generate name**: convert description → kebab-case, strip filler words, max 4 segments
3. **Result**: `{type}/{kebab-case}` (e.g. `feature/user-auth-oauth`)

If the user provides a full branch name (e.g. `feature/auth`), use it as-is.

### Step 2 — Determine Directory

Check in priority order:

```bash
ls -d .worktrees 2>/dev/null || ls -d worktrees 2>/dev/null
grep -i "worktree" CLAUDE.md 2>/dev/null
```

If nothing exists, ask the user:
- `.worktrees/` — project-local, hidden (recommended)
- `worktrees/` — project-local, visible
- `~/worktrees/<project>/` — global location

### Step 3 — Safety Verification

Verify the worktree directory is git-ignored:

```bash
git check-ignore -q .worktrees 2>/dev/null
```

If NOT ignored, add to `.gitignore` and commit before proceeding.

### Step 4 — Create Worktree

```bash
BRANCH="feature/user-auth"
git worktree add .worktrees/$BRANCH -b $BRANCH
```

### Step 5 — Project Setup

Auto-detect and install dependencies in the new worktree:

```bash
[ -f package.json ] && npm install
[ -f requirements.txt ] && pip install -r requirements.txt
[ -f pyproject.toml ] && pip install -e .
[ -f Cargo.toml ] && cargo build
[ -f go.mod ] && go mod download
```

### Step 6 — Verify Clean Baseline

Run project-appropriate test command. If tests fail, report and ask whether to proceed.

### Step 7 — Report

```
Worktree created
  Path:   .worktrees/feature/user-auth
  Branch: feature/user-auth
  Tests:  42 passing, 0 failures
  Ready to implement.
```

---

## Status

Display all active worktrees with rich context:

```bash
git worktree list --porcelain
```

For each worktree, collect and display:

| Field | Source |
|-------|--------|
| Branch | `git worktree list` |
| Path | `git worktree list` |
| Last commit | `git -C <path> log -1 --format="%ar — %s"` |
| Dirty | `git -C <path> status --porcelain` (non-empty = dirty) |
| Ahead/Behind | `git -C <path> rev-list --left-right --count <base>...<branch>` |

Output as a formatted table:

```
Worktree Status (3 active)
──────────────────────────────────────────────────────────
  feature/auth     .worktrees/feature/auth     3↑ 0↓  dirty   2h ago — Add JWT validation
  hotfix/login     .worktrees/hotfix/login     1↑ 0↓  clean   15m ago — Fix null check
  experiment/sse   .worktrees/experiment/sse   5↑ 2↓  dirty   1d ago — WIP SSE transport
──────────────────────────────────────────────────────────
```

---

## Done (Merge Back)

### Pre-Merge Checks

Run ALL checks before merging. Stop on any failure:

1. **Worktree exists** — verify branch and path are valid
2. **Clean working tree** — no uncommitted changes (offer stash/commit if dirty)
3. **Tests pass** — run test suite in the worktree
4. **Base branch up-to-date** — `git fetch && git status` on base branch
5. **No conflicts** — dry-run merge to detect conflicts early:
   ```bash
   git merge --no-commit --no-ff <branch> && git merge --abort
   ```

### Merge Strategy

Ask user preference (default: merge commit):

| Strategy | Command | When |
|----------|---------|------|
| **Merge commit** | `git merge --no-ff <branch>` | Default — preserves full history |
| **Squash** | `git merge --squash <branch>` | Clean single commit on base |
| **Rebase** | `git rebase <base>` (in worktree first) | Linear history preference |

### Steps

1. Fetch latest from remote
2. In main worktree, checkout base branch and pull
3. Execute chosen merge strategy
4. Run tests on merged result
5. If tests pass → report success, suggest cleanup
6. If tests fail → abort merge, report failures, keep worktree intact

### Report

```
Merge complete
  Branch:   feature/auth → main
  Strategy: squash
  Commits:  7 squashed into 1
  Tests:    42 passing
  Suggest:  Run `/git-worktrees cleanup feature/auth` to remove worktree
```

---

## Cleanup

### Single Worktree

```bash
# 1. Check if branch is merged
git branch --merged main | grep -q "feature/auth"

# 2. Optional backup (if unmerged or user requests)
git branch backup/feature/auth feature/auth

# 3. Remove worktree
git worktree remove .worktrees/feature/auth

# 4. Delete branch (safe — fails if unmerged)
git branch -d feature/auth
```

**If branch is NOT merged**: warn the user and offer options:
- Create backup branch, then remove
- Force remove (`git branch -D`)
- Cancel

### Bulk Cleanup (`--all`)

1. List all worktrees via `git worktree list`
2. Categorize: merged (safe) vs unmerged (needs confirmation)
3. Show summary and ask confirmation
4. Remove merged worktrees automatically
5. For unmerged: ask per-worktree (backup/force/skip)
6. Run `git worktree prune` to clean stale entries

### Report

```
Cleanup complete
  Removed: feature/auth, hotfix/login (merged)
  Skipped: experiment/sse (unmerged, user chose skip)
  Pruned:  1 stale entry
```

---

## Quick Reference

| Situation | Action |
|-----------|--------|
| `.worktrees/` exists | Use it (verify ignored) |
| `worktrees/` exists | Use it (verify ignored) |
| Neither exists | Ask user preference |
| Directory not ignored | Add to .gitignore + commit |
| Tests fail at baseline | Report + ask user |
| No package manager file | Skip dependency install |
| Dirty worktree before merge | Offer stash/commit |
| Unmerged branch on cleanup | Warn + offer backup/force/skip |
| Merge conflicts detected | Abort + report conflicts + keep worktree |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Worktree dir not gitignored | Always `git check-ignore` first |
| Hardcoding setup commands | Auto-detect from project files |
| Proceeding with failing tests | Report and get permission |
| Forgetting to remove after merge | Done report suggests cleanup |
| Checking out same branch in two worktrees | Git prevents this — use a different branch name |
| Force-deleting unmerged branch | Always offer backup first |
| Merging without pulling base | Always fetch + pull before merge |
| Non-tracked files missing in worktree | .env, config files need manual copy — warn user |

## Integration

- **spec-kit** → create worktree for isolated implementation of a spec
- **team-tasks** → parallel multi-agent work on different branches via worktrees
- **blueprint** → each blueprint phase can execute in its own worktree
- **forge** → Stage 4 (executor) can use worktrees for phase isolation

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
