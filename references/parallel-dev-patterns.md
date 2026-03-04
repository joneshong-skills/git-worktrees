# Parallel Multi-Agent Development with Git Worktrees

Patterns for running multiple Claude Code sessions in parallel on the same repo,
each in its own git worktree with strict file ownership boundaries.

---

## 1. When to Use Parallel Worktree Design

Use this pattern when:
- The project has a clear backend/frontend split or multiple independent modules.
- Multiple Claude Code sessions will work simultaneously on different parts.
- Files can be cleanly partitioned with no overlap between sessions.
- The goal is zero merge conflicts when integrating both streams of work.

Avoid when modules are tightly coupled and changes routinely span both sides.

---

## 2. Scaffold-First Pattern

Build all shared infrastructure on the **main branch** BEFORE creating worktrees.
Both worktrees inherit the same foundation. Shared artifacts are "frozen" -- read-only
in worktrees, modifiable only on main.

### Scaffold categories

| Category | Examples |
|----------|----------|
| Shared types/interfaces | Data models used by both sides (Go structs + TS mirrors) |
| Protocol definitions | API contracts, WebSocket message enums, JSON schemas |
| Test fixtures | Sample data files for integration testing |
| Build infrastructure | Makefile, package.json, go.mod, docker-compose.yml |
| Project configuration | .gitignore, CLAUDE.md, tsconfig.json |
| Progress tracking | PROGRESS.md with sections for each worktree |

### Workflow

```
main:  scaffold commit ──┬── merge wt/backend ──┬── release
                         │                      │
wt/backend:  ────────────┘── work ──────────────┘
wt/frontend: ────────────┘── work ──────────────┘
```

---

## 3. File Ownership Model

Three categories govern every file in the repo:

**FROZEN** -- Shared types, interfaces, test data. Created during scaffold.
Modified ONLY on the main branch. Both worktrees READ but never WRITE.

**OWNED** -- Directories exclusively belonging to one worktree. Only that
worktree creates or modifies files here.

**SHARED MUTABLE** -- Files like PROGRESS.md that both worktrees update
(each in its own clearly delimited section).

### Ownership table template

| Directory | Owner | Rule |
|-----------|-------|------|
| `internal/protocol/` | FROZEN (main) | Shared types -- do not modify in worktrees |
| `internal/parser/claude/` | wt/backend | Backend-exclusive |
| `internal/server/` | wt/backend | Backend-exclusive |
| `frontend/src/types/` | FROZEN (main) | TypeScript type mirrors -- do not modify |
| `frontend/src/engine/` | wt/frontend | Frontend-exclusive |
| `frontend/src/components/` | wt/frontend | Frontend-exclusive |
| `testdata/` | FROZEN (main) | Shared fixtures -- do not modify |
| `PROGRESS.md` | SHARED | Both update their own section |

---

## 4. CLAUDE.local.md Template

Place this in the root of each worktree to guide the Claude Code session.

```markdown
# Worktree: {worktree-name}

Working in the **{role}** worktree of {project}.

## Mission
{one-line description of what this worktree builds}

## Owned Files (ONLY modify these)
- `path/to/dir1/` -- description
- `path/to/dir2/` -- description

## DO NOT Modify
- `path/to/frozen/` -- shared types, frozen on main
- `path/to/other-worktree-dir/` -- belongs to {other-worktree}

## Progress Tracking
Update YOUR section in `PROGRESS.md` when completing tasks.
Read the other section before starting dependent work.

## Dev Commands
- `make {target}` -- build
- `make test-{role}` -- run tests
- `make lint-{role}` -- lint

## Task Priority
1. [Phase 1] {task}
2. [Phase 1] {task}
3. [Phase 2] {task}
4. [Phase 3] {task}
```

---

## 5. PROGRESS.md Template

Shared file at repo root. Each worktree updates only its own rows.

```markdown
# {Project} -- Shared Progress

Last updated: {date}

## Convention
- Each worktree updates its own rows when completing tasks.
- Read the other worktree's status before starting dependent work.
- Status: `pending` -> `in-progress` -> `done` -> `verified`

## Scaffold (main branch)
| # | Task | Status | Notes |
|---|------|--------|-------|
| S1 | Define shared types | done | |
| S2 | Create test fixtures | done | |
| S3 | Set up build system | done | |

## {Worktree A Name}
| # | Task | Status | Phase | Notes |
|---|------|--------|-------|-------|
| A1 | | pending | 1 | |
| A2 | | pending | 1 | |
| A3 | | pending | 2 | |

## {Worktree B Name}
| # | Task | Status | Phase | Notes |
|---|------|--------|-------|-------|
| B1 | | pending | 1 | |
| B2 | | pending | 1 | |
| B3 | | pending | 2 | |

## Integration Milestones
| Milestone | Depends On | Status |
|-----------|-----------|--------|
| End-to-end data flow | A2, B2 | pending |
| Full integration test | A3, B3 | pending |
```

---

## 6. Conflict-Free Merge Guarantee

Directory-based ownership guarantees zero merge conflicts on integration:

1. Each worktree only modifies files in its OWNED directories.
2. FROZEN files are never modified in worktrees -- both branches see identical copies.
3. PROGRESS.md is the only shared mutable file. Each worktree edits a distinct
   section, making conflicts rare and trivial to resolve.
4. Merging both feature branches back to main produces no conflicts because the
   modified file sets do not overlap.

If a shared type needs updating mid-development:
- Pause both worktrees.
- Switch to main, update the frozen file, commit.
- Rebase (or merge main into) both worktree branches.
- Resume.

---

## 7. Real-World Example: Agent Vista

Project that inspired these patterns -- a real-time visualization tool for
Claude Code multi-agent sessions.

| Aspect | Detail |
|--------|--------|
| Backend (wt/backend) | Go: log parsers, file watcher, event broker, WebSocket server |
| Frontend (wt/frontend) | React + Canvas 2D: rendering engine, sprite system, FSM animations |
| Frozen shared | Protocol types (Go structs + TS mirrors), test fixtures, parser interface |
| Scaffold size | ~35 files committed on main before splitting |
| Worktree creation | `git worktree add ../agent-vista-backend wt/backend` |
| Result | Two independent Claude Code sessions, zero-conflict merge path |

### Key decisions
- Protocol messages defined as Go structs with `json` tags; TypeScript types
  generated/mirrored manually in scaffold and frozen.
- Canvas rendering kept entirely in frontend; no server-side rendering.
- Backend exposes a single WebSocket endpoint; frontend connects and renders.
- Integration tested by running both builds and verifying end-to-end message flow.
