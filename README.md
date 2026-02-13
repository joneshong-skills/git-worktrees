# Git Worktrees

Create isolated workspaces sharing the same repository for parallel branch work.

## Overview

Git worktrees allow working on multiple branches simultaneously without switching. Each worktree is a separate directory with its own working tree, sharing the same `.git` data. Changes in one worktree don't affect others.

## Quick Start

```bash
# Check for existing worktree directory
ls -d .worktrees 2>/dev/null

# Create a new worktree with a branch
git worktree add .worktrees/feature/auth -b feature/auth

# List all worktrees
git worktree list

# Remove a worktree after merging
git worktree remove .worktrees/feature/auth
```

## Key Features

- **Parallel Work**: Develop multiple features simultaneously without branch switching
- **Shared History**: All worktrees share the same `.git` data, keeping history centralized
- **Automatic Setup**: Detects project type (Node.js, Python, Rust, Go) and runs appropriate dependency installation
- **Clean Baseline**: Verifies test suite passes before starting work
- **Safe Cleanup**: Proper removal and pruning to keep repository clean

## Workflow

1. Determine worktree directory (`.worktrees/`, `worktrees/`, or `~/worktrees/<project>/`)
2. Verify directory is git-ignored
3. Create worktree with new branch
4. Auto-run project setup (npm install, pip install, cargo build, etc.)
5. Verify clean baseline by running tests
6. Start developing in isolated workspace

## Managing Worktrees

```bash
# List all active worktrees
git worktree list

# Prune stale worktrees
git worktree prune

# Remove worktree after merging
git worktree remove .worktrees/feature/auth
git branch -d feature/auth
```

## Use Cases

- Feature development in isolation from main work
- Parallel PR reviews on different branches
- Experiment with multiple approaches simultaneously
- Avoid context switching delays during active development

## Integration

- Pairs with **spec-kit** for isolated implementation during planning execution
- Combines with **team-tasks** for multi-agent parallel work on different branches

## License

Included in Claude Code as part of the Skills Collection. See individual skill documentation for licensing details.
