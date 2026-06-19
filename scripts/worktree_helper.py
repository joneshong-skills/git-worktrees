#!/usr/bin/env python3
"""worktree_helper.py — Git worktree lifecycle helper

Usage:
  worktree_helper.py create <branch-description> [--base BRANCH]
  worktree_helper.py status
  worktree_helper.py done [WORKTREE_PATH]
  worktree_helper.py cleanup [--dry-run] [--force]
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg):
    print(f"{GREEN}\u2713{RESET}  {msg}")


def warn(msg):
    print(f"{YELLOW}\u26a0{RESET}  {msg}")


def err(msg):
    print(f"{RED}\u2717{RESET}  {msg}", file=sys.stderr)


def info(msg):
    print(f"{CYAN}\u2192{RESET}  {msg}")


def bold(msg):
    print(f"{BOLD}{msg}{RESET}")


# ── Guards ────────────────────────────────────────────────────────────────────


def require_git_repo():
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"], capture_output=True, text=True
    )
    if result.returncode != 0:
        err("Not inside a git repository.")
        sys.exit(1)


# ── Utilities ─────────────────────────────────────────────────────────────────


def description_to_branch(desc: str) -> str:
    """Convert description to kebab-case branch name with type prefix.
    'fix login bug' -> 'fix/login-bug'
    'feat add oauth' -> 'feat/add-oauth'
    default -> 'work/<kebab>'
    """
    lower = desc.lower()
    words = lower.split()
    if not words:
        return "work/branch"

    first_word = words[0]

    type_map = {
        "fix": "fix",
        "bugfix": "fix",
        "hotfix": "fix",
        "bug": "fix",
        "feat": "feat",
        "feature": "feat",
        "add": "feat",
        "new": "feat",
        "refactor": "refactor",
        "clean": "refactor",
        "restructure": "refactor",
        "optimize": "refactor",
        "work": "work",
        "task": "work",
        "chore": "work",
        "wip": "work",
    }

    type_keywords = set(type_map.keys())
    branch_type = type_map.get(first_word, "work")

    # Strip the first word if it matched a type keyword
    if first_word in type_keywords:
        body_words = words[1:]
    else:
        body_words = words

    # Remove filler words
    filler = {
        "a",
        "an",
        "the",
        "for",
        "in",
        "on",
        "of",
        "to",
        "and",
        "or",
        "with",
        "that",
        "this",
        "it",
    }
    body_words = [w for w in body_words if w not in filler]

    # Join and clean: replace non-alphanumeric with dash
    body = "-".join(body_words)
    body = re.sub(r"[^a-z0-9]+", "-", body)
    body = body.strip("-")

    # Max 4 segments
    segments = body.split("-")[:4]
    body = "-".join(segments)

    if not body:
        body = "branch"

    return f"{branch_type}/{body}"


def main_worktree_path() -> str:
    """Get the main worktree root (where .git directory lives)."""
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    git_dir = result.stdout.strip()
    # Strip /.git or /.git/worktrees/...
    path = re.sub(r"(/\.git/worktrees/.*|/\.git)$", "", git_dir)
    return path


def repo_name() -> str:
    return os.path.basename(main_worktree_path())


def default_base() -> str:
    """Get the default base branch (main or master)."""
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().replace("refs/remotes/origin/", "")

    # Fallback: check local branches
    for branch in ("main", "master"):
        r = subprocess.run(
            ["git", "show-ref", "--quiet", f"refs/heads/{branch}"], capture_output=True
        )
        if r.returncode == 0:
            return branch
    return "main"


def current_worktree_path() -> str:
    """Detect which worktree the current directory belongs to."""
    cwd = os.getcwd()
    worktrees = list_worktrees_raw()
    for wt_path, _, _ in worktrees:
        if cwd.startswith(wt_path):
            return wt_path
    return ""


def list_worktrees_raw() -> list:
    """Parse `git worktree list --porcelain` into list of (path, head, branch) tuples."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return []

    worktrees = []
    path = head = branch = ""

    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            head = line[len("HEAD ") :]
        elif line.startswith("branch "):
            branch = line[len("branch ") :]
        elif line in ("bare", "detached"):
            branch = "(detached)"
        elif line == "" and path:
            worktrees.append((path, head, branch))
            path = head = branch = ""

    # Handle last entry without trailing blank line
    if path:
        worktrees.append((path, head, branch))

    return worktrees


def run_git(args: list, cwd: str = None) -> subprocess.CompletedProcess:
    cmd = ["git"]
    if cwd:
        cmd += ["-C", cwd]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True)


# ── Pre-flight + state materialization ─────────────────────────────────────────


def detect_in_progress_op():
    """Detect if the current repo is mid-rebase/merge/cherry-pick/revert/bisect.

    Returns (operation_name, abort_command) when an interruptible op is in
    progress, else None. Creating a worktree while the parent repo sits mid-op
    is a Fail-Loud moment — surface it before the side-effecting `worktree add`.
    NOT a data-loss guard (worktrees isolate HEAD; the parent op is unaffected),
    so this is about error-message quality and timing, not safety.
    """
    # (git-path probe, operation label, abort command) per interruptible op.
    # `git rev-parse --git-path` resolves correctly whether .git is a dir or a
    # worktree gitfile, so we never hand-join a .git path.
    checks = [
        ("rebase-merge", "rebase", "git rebase --abort"),
        ("rebase-apply", "rebase", "git rebase --abort"),
        ("MERGE_HEAD", "merge", "git merge --abort"),
        ("CHERRY_PICK_HEAD", "cherry-pick", "git cherry-pick --abort"),
        ("REVERT_HEAD", "revert", "git revert --abort"),
        ("BISECT_LOG", "bisect", "git bisect reset"),
    ]
    for git_path, op_name, abort_cmd in checks:
        r = subprocess.run(
            ["git", "rev-parse", "--git-path", git_path], capture_output=True, text=True
        )
        if r.returncode != 0:
            continue
        p = r.stdout.strip()
        if p and Path(p).exists():
            return (op_name, abort_cmd)
    return None


def materialize_wip(source_path, dest_path):
    """Copy a repo's uncommitted state into a freshly created worktree.

    Source stays read-only throughout (no stash) — safe even when the source
    pane is actively in use by an agent. Three passes: staged (--cached --index),
    unstaged (working tree), untracked (file copy). Mirrors agent-deck's
    diff-pipe-apply. `--binary` handles binary/CRLF; `-z` handles odd filenames.
    Returns True if anything was carried over.
    # ponytail: submodule WIP not carried; add a `git submodule foreach` pass if needed.
    """
    import shutil

    moved = False

    for label, diff_args, apply_args in (
        ("staged", ["diff", "--binary", "--cached"], ["apply", "--binary", "--index"]),
        ("unstaged", ["diff", "--binary"], ["apply", "--binary"]),
    ):
        d = subprocess.run(["git", "-C", source_path] + diff_args, capture_output=True)
        if d.returncode == 0 and d.stdout.strip():
            a = subprocess.run(
                ["git", "-C", dest_path] + apply_args,
                input=d.stdout,
                capture_output=True,
            )
            if a.returncode == 0:
                moved = True
            else:
                warn(
                    f"Could not apply {label} changes: {a.stderr.decode(errors='replace').strip()}"
                )

    # Untracked files are not covered by diff — copy them explicitly.
    r = subprocess.run(
        ["git", "-C", source_path, "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True,
    )
    if r.returncode == 0 and r.stdout:
        for raw in r.stdout.split(b"\x00"):
            if not raw:
                continue
            rel = raw.decode(errors="replace")
            src = Path(source_path) / rel
            dst = Path(dest_path) / rel
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                moved = True

    return moved


# ── Command: create ───────────────────────────────────────────────────────────


def cmd_create(args):
    require_git_repo()

    # Fail-Loud guard: refuse up-front if the repo is mid-operation, before any
    # banner or side effect. Worktrees isolate HEAD so this is message-quality,
    # not a data-loss guard.
    in_progress = detect_in_progress_op()
    if in_progress:
        op_name, abort_cmd = in_progress
        err(f"Repo is mid-{op_name}. Resolve it before creating a worktree.")
        info(f"To abort the {op_name}:  {abort_cmd}")
        sys.exit(1)

    if not args.description:
        err("Usage: worktree_helper.py create <branch-description> [--base BRANCH]")
        sys.exit(1)

    description = " ".join(args.description)

    if not description.strip():
        err("Branch description cannot be empty.")
        sys.exit(1)

    # If description already looks like a branch (contains / and no spaces), use as-is
    if "/" in description and " " not in description:
        branch = description
    else:
        branch = description_to_branch(description)

    base = args.base or default_base()

    main_path = main_worktree_path()
    repo = repo_name()

    # Build worktree directory path: <parent-of-main>/<repo>-<branch-slug>
    branch_slug = branch.replace("/", "-")
    worktree_dir = str(Path(main_path).parent / f"{repo}-{branch_slug}")
    worktree_dir = str(Path(worktree_dir).resolve())

    info("Creating worktree")
    print(f"  Branch:  {BOLD}{branch}{RESET}")
    print(f"  Base:    {BOLD}{base}{RESET}")
    print(f"  Path:    {BOLD}{worktree_dir}{RESET}")
    print()

    # Check branch doesn't already exist
    r = run_git(["show-ref", "--quiet", f"refs/heads/{branch}"])
    if r.returncode == 0:
        err(
            f"Branch '{branch}' already exists. Use a different description or specify a new name."
        )
        sys.exit(1)

    # Check worktree path doesn't already exist
    if Path(worktree_dir).exists():
        err(f"Directory already exists: {worktree_dir}")
        sys.exit(1)

    # Ensure base branch exists locally or as remote
    r_local = run_git(["show-ref", "--quiet", f"refs/heads/{base}"])
    r_remote = run_git(["show-ref", "--quiet", f"refs/remotes/origin/{base}"])
    if r_local.returncode != 0 and r_remote.returncode != 0:
        err(f"Base branch '{base}' not found locally or in origin.")
        sys.exit(1)

    result = subprocess.run(
        ["git", "worktree", "add", worktree_dir, "-b", branch, base],
        capture_output=False,
    )

    if result.returncode != 0:
        err(f"git worktree add failed (exit {result.returncode}).")
        sys.exit(1)

    ok("Worktree created successfully.")

    if getattr(args, "with_state", False):
        # Carry the current working tree's uncommitted state into the new
        # worktree. Source = current repo top-level (the WIP you're sitting on),
        # read-only throughout — no stash, safe for a parent pane in active use.
        source = run_git(["rev-parse", "--show-toplevel"]).stdout.strip() or main_path
        info("Materializing uncommitted state (--with-state)...")
        if materialize_wip(source, worktree_dir):
            ok("Carried parent WIP into worktree (source left untouched).")
        else:
            info("No uncommitted state to carry over.")

    print()
    bold("Worktree Path:")
    print(f"  {worktree_dir}")
    print()
    info("To switch into this worktree:")
    print(f"  cd {worktree_dir}")


# ── Command: status ───────────────────────────────────────────────────────────


def cmd_status(args):
    require_git_repo()

    main_path = main_worktree_path()
    worktrees = list_worktrees_raw()
    total = len(worktrees)

    bold(f"Worktree Status ({total} total)")
    print("─" * 72)
    print(
        f"{BOLD}  {'Branch':<30} {'Path':<35} {'↑/↓':>8}  {'State':<6}  Last Commit{RESET}"
    )
    print("─" * 72)

    home = str(Path.home())

    for wt_path, head, branch_ref in worktrees:
        branch_short = branch_ref.replace("refs/heads/", "")

        path_display = wt_path
        if wt_path == main_path:
            path_display = f"{wt_path} (main)"
        path_display = path_display.replace(home, "~")

        # Dirty status
        r = run_git(["status", "--porcelain"], cwd=wt_path)
        dirty_count = (
            len([l for l in r.stdout.splitlines() if l.strip()])
            if r.returncode == 0
            else 0
        )
        if dirty_count > 0:
            state_str = f"{YELLOW}dirty{RESET}"
        else:
            state_str = f"{GREEN}clean{RESET}"

        # Ahead/behind
        base = default_base()
        ahead = behind = 0
        r = run_git(
            ["rev-list", "--left-right", "--count", f"origin/{base}...{branch_ref}"],
            cwd=wt_path,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

        ab_str = f"{GREEN}{ahead}\u2191{RESET} {RED}{behind}\u2193{RESET}"

        # Last commit
        r = run_git(["log", "-1", "--format=%ar \u2014 %s"], cwd=wt_path)
        last_commit = (
            r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "no commits"
        )

        print(
            f"  {CYAN}{branch_short:<30}{RESET} "
            f"{path_display:<35} "
            f"{ab_str}  "
            f"{state_str:<6}  "
            f"{last_commit}"
        )

    print("─" * 72)


# ── Command: done ─────────────────────────────────────────────────────────────


def cmd_done(args):
    require_git_repo()

    target_path = args.worktree_path or ""

    if not target_path:
        target_path = current_worktree_path()
        if not target_path:
            # Fallback: use cwd if it's a known worktree
            cwd = os.getcwd()
            r = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--git-dir"], capture_output=True
            )
            if r.returncode == 0:
                r2 = subprocess.run(
                    ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                )
                if r2.returncode == 0:
                    target_path = r2.stdout.strip()

        if not target_path:
            err(
                "Cannot detect current worktree. Run from inside a worktree or provide a path."
            )
            sys.exit(1)

    # Verify the path is a registered worktree
    worktrees = list_worktrees_raw()
    found = False
    branch_ref = ""
    for wt_path, head, branch in worktrees:
        if wt_path == target_path:
            found = True
            branch_ref = branch
            break

    if not found:
        err(f"Path is not a registered git worktree: {target_path}")
        err("Registered worktrees:")
        for wt_path, _, _ in worktrees:
            print(f"  {wt_path}", file=sys.stderr)
        sys.exit(1)

    branch_short = branch_ref.replace("refs/heads/", "")

    bold(f"Worktree Done: {branch_short}")
    print("─" * 42)

    # Pre-check 1: clean working tree
    r = run_git(["status", "--porcelain"], cwd=target_path)
    dirty_lines = [l for l in r.stdout.splitlines() if l.strip()]
    dirty_count = len(dirty_lines)
    if dirty_count > 0:
        err(f"Working tree is dirty ({dirty_count} uncommitted change(s)).")
        err("Please commit or stash changes before marking done.")
        subprocess.run(["git", "-C", target_path, "status", "--short"])
        sys.exit(1)
    ok("Working tree is clean.")

    # Ahead/behind
    base = default_base()
    ahead = 0
    r = run_git(
        ["rev-list", "--left-right", "--count", f"origin/{base}...{branch_ref}"],
        cwd=target_path,
    )
    if r.returncode == 0 and r.stdout.strip():
        parts = r.stdout.strip().split()
        if len(parts) == 2:
            ahead = int(parts[1])

    # Commit count
    r = run_git(["rev-list", "--count", f"{base}..{branch_short}"], cwd=target_path)
    commit_count = (
        int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0
    )

    # Files changed
    r = run_git(["diff", "--name-only", f"{base}..{branch_short}"], cwd=target_path)
    files_changed = (
        len([l for l in r.stdout.splitlines() if l.strip()]) if r.returncode == 0 else 0
    )

    print()
    bold("Summary:")
    print(f"  Branch:         {branch_short}")
    print(f"  Commits ahead:  {commit_count}")
    print(f"  Files changed:  {files_changed}")
    print(f"  Worktree path:  {target_path}")
    print()

    if commit_count == 0:
        warn(f"No commits ahead of base branch '{base}'. Nothing to merge.")

    bold(f"To merge this worktree into {base}, run ONE of:")
    print()
    info("Merge commit (preserves full history):")
    print(f"  git checkout {base} && git merge --no-ff {branch_short}")
    print()
    info("Squash merge (single clean commit):")
    print(f"  git checkout {base} && git merge --squash {branch_short} && git commit")
    print()
    info("Rebase (linear history):")
    print(
        f"  git -C {target_path} rebase {base} && "
        f"git checkout {base} && git merge --ff-only {branch_short}"
    )
    print()
    info("After merging, clean up with:")
    print("  worktree_helper.py cleanup")


# ── Command: cleanup ─────────────────────────────────────────────────────────


def cmd_cleanup(args):
    require_git_repo()

    dry_run = args.dry_run
    force = args.force

    base = default_base()
    main_path = main_worktree_path()

    bold("Scanning worktrees for merged branches...")
    print("─" * 42)

    worktrees = list_worktrees_raw()

    merged_worktrees = []
    unmerged_worktrees = []

    for wt_path, head, branch_ref in worktrees:
        # Skip main worktree
        if wt_path == main_path:
            continue

        branch_short = branch_ref.replace("refs/heads/", "")

        # Check if branch is merged into base
        r = run_git(["branch", "--merged", base], cwd=main_path)
        merged_branches = r.stdout.splitlines() if r.returncode == 0 else []
        is_merged = any(branch_short in b for b in merged_branches)

        if is_merged:
            merged_worktrees.append((wt_path, branch_short))
        else:
            unmerged_worktrees.append((wt_path, branch_short))

    # Report merged
    if not merged_worktrees:
        ok("No merged worktrees to clean up.")
    else:
        bold("Merged (safe to remove):")
        for wt_path, branch_short in merged_worktrees:
            print(f"  {GREEN}\u2713{RESET}  {branch_short:<30}  {wt_path}")
        print()

    # Report unmerged
    if unmerged_worktrees:
        bold("Unmerged (require confirmation):")
        for wt_path, branch_short in unmerged_worktrees:
            print(f"  {YELLOW}\u26a0{RESET}  {branch_short:<30}  {wt_path}")
        print()

    if dry_run:
        info("Dry-run mode: no changes made.")
        sys.exit(0)

    # Remove merged worktrees
    if merged_worktrees:
        if not force:
            try:
                confirm = input(
                    f"Remove {len(merged_worktrees)} merged worktree(s)? [y/N] "
                )
            except (KeyboardInterrupt, EOFError):
                confirm = ""
            if not confirm.lower().startswith("y"):
                info("Skipped merged worktrees.")
                sys.exit(0)

        for wt_path, branch_short in merged_worktrees:
            info(f"Removing worktree: {wt_path}")
            r = subprocess.run(
                ["git", "worktree", "remove", wt_path], capture_output=True
            )
            if r.returncode != 0:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path],
                    capture_output=True,
                )
            info(f"Deleting branch: {branch_short}")
            r = run_git(["branch", "-d", branch_short])
            if r.returncode != 0:
                warn(f"Could not delete branch '{branch_short}' (may already be gone).")

        ok(f"Removed {len(merged_worktrees)} merged worktree(s).")

    # Handle unmerged worktrees interactively
    if unmerged_worktrees and not force:
        bold("Handling unmerged worktrees:")
        import datetime

        for wt_path, branch_short in unmerged_worktrees:
            print()
            warn(f"Unmerged: {branch_short} \u2192 {wt_path}")
            print("  [b] Create backup branch + remove")
            print("  [f] Force remove (lose commits)")
            print("  [s] Skip")
            try:
                choice = input("  Choice [b/f/s]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "s"

            if choice.startswith("b"):
                ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                safe_branch = branch_short.replace("/", "-")
                backup_branch = f"backup/{safe_branch}-{ts}"
                r = run_git(["branch", backup_branch, branch_short])
                if r.returncode == 0:
                    ok(f"Backup created: {backup_branch}")
                r = subprocess.run(
                    ["git", "worktree", "remove", wt_path], capture_output=True
                )
                if r.returncode != 0:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", wt_path],
                        capture_output=True,
                    )
                run_git(["branch", "-D", branch_short])
                ok(f"Removed (backup: {backup_branch}).")
            elif choice.startswith("f"):
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path],
                    capture_output=True,
                )
                run_git(["branch", "-D", branch_short])
                ok(f"Force removed: {branch_short}")
            else:
                info(f"Skipped: {branch_short}")

    # Prune stale worktree entries
    print()
    info("Pruning stale worktree entries...")
    subprocess.run(["git", "worktree", "prune"])
    ok("Prune complete.")

    print()
    bold("Cleanup done.")


# ── Main dispatch ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="worktree_helper.py",
        description="Git worktree lifecycle manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  worktree_helper.py create "fix login bug"
  worktree_helper.py create "add oauth support" --base develop
  worktree_helper.py create feature/custom-name
  worktree_helper.py status
  worktree_helper.py done
  worktree_helper.py done /path/to/worktree
  worktree_helper.py cleanup --dry-run
  worktree_helper.py cleanup --force
""",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # create
    p_create = subparsers.add_parser("create", help="Create a new worktree")
    p_create.add_argument(
        "description", nargs="+", help="Branch description or branch name"
    )
    p_create.add_argument("--base", default="", help="Base branch to create from")
    p_create.add_argument(
        "--with-state",
        action="store_true",
        help="Carry current repo's uncommitted state (staged/unstaged/untracked) into the new worktree",
    )

    # status
    subparsers.add_parser("status", help="Show all worktrees status")

    # done
    p_done = subparsers.add_parser(
        "done", help="Mark worktree as done (show merge commands)"
    )
    p_done.add_argument(
        "worktree_path",
        nargs="?",
        default="",
        help="Path to worktree (default: current)",
    )

    # cleanup
    p_cleanup = subparsers.add_parser("cleanup", help="Cleanup merged worktrees")
    p_cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without doing it",
    )
    p_cleanup.add_argument(
        "--force", action="store_true", help="Skip confirmation prompts"
    )

    if len(sys.argv) == 1:
        bold("worktree_helper.py — Git worktree lifecycle manager")
        print()
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.command == "create":
        cmd_create(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "done":
        cmd_done(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    else:
        err(f"Unknown command: {args.command}")
        err("Valid commands: create, status, done, cleanup")
        sys.exit(1)


if __name__ == "__main__":
    main()
