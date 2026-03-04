### 2026-02-24 — Parallel dev design from Agent Vista project
- **Friction**: Original skill only covered git mechanics (create/status/done/cleanup) but lacked architecture-level guidance for multi-session parallel development
- **Fix**: Added `design` sub-command with 6-step workflow: analyze split → classify ownership → build scaffold → create branches → generate CLAUDE.local.md → report. Created `references/parallel-dev-patterns.md` with templates.
- **Rule**: When a real project reveals a reusable architectural pattern, capture it as a reference file + workflow steps, not just ad-hoc instructions. The scaffold-first + file ownership model is the key insight that makes worktree parallelism conflict-free.
