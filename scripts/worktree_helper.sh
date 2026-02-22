#!/usr/bin/env bash
# worktree_helper.sh — Git worktree lifecycle helper
# Usage:
#   worktree_helper.sh create <branch-description> [--base BRANCH]
#   worktree_helper.sh status
#   worktree_helper.sh done [WORKTREE_PATH]
#   worktree_helper.sh cleanup [--dry-run] [--force]

set -u

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { printf "${GREEN}✓${RESET}  %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${RESET}  %s\n" "$*"; }
err()  { printf "${RED}✗${RESET}  %s\n" "$*" >&2; }
info() { printf "${CYAN}→${RESET}  %s\n" "$*"; }
bold() { printf "${BOLD}%s${RESET}\n" "$*"; }

# ── Guards ────────────────────────────────────────────────────────────────────
require_git_repo() {
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        err "Not inside a git repository."
        exit 1
    fi
}

# ── Utilities ─────────────────────────────────────────────────────────────────

# Convert description to kebab-case branch name with type prefix
# "fix login bug" → "fix/login-bug"
# "feat add oauth" → "feat/add-oauth"
# "refactor auth module" → "refactor/auth-module"
# default → "work/<kebab>"
description_to_branch() {
    local desc="$1"
    local lower
    lower=$(printf '%s' "$desc" | tr '[:upper:]' '[:lower:]')

    # Detect type prefix from first word
    local type="work"
    local first_word
    first_word=$(printf '%s' "$lower" | awk '{print $1}')

    case "$first_word" in
        fix|bugfix|hotfix|bug)   type="fix" ;;
        feat|feature|add|new)    type="feat" ;;
        refactor|clean|restructure|optimize) type="refactor" ;;
        work|task|chore|wip)     type="work" ;;
    esac

    # Strip the first word if it matched a type keyword (avoid "fix/fix-login")
    local body
    case "$first_word" in
        fix|bugfix|hotfix|bug|feat|feature|add|new|refactor|clean|restructure|optimize|work|task|chore|wip)
            body=$(printf '%s' "$lower" | cut -d' ' -f2-)
            ;;
        *)
            body="$lower"
            ;;
    esac

    # Remove filler words
    body=$(printf '%s' "$body" | sed -E 's/\b(a|an|the|for|in|on|of|to|and|or|with|that|this|it)\b//g')

    # Collapse spaces, trim, replace non-alphanumeric with dash, max 4 segments
    body=$(printf '%s' "$body" \
        | sed -E 's/[^a-z0-9]+/-/g' \
        | sed -E 's/^-+|-+$//g' \
        | cut -d'-' -f1-4)

    # Fallback if body is empty
    if [ -z "$body" ]; then
        body="branch"
    fi

    printf '%s/%s' "$type" "$body"
}

# Get the main worktree root (where .git directory lives)
main_worktree_path() {
    git rev-parse --path-format=absolute --git-common-dir 2>/dev/null \
        | sed 's|/\.git$||; s|/\.git/worktrees/.*$||'
}

# Get repo name from directory
repo_name() {
    basename "$(main_worktree_path)"
}

# Get the default base branch (main or master)
default_base() {
    local base
    base=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
    if [ -z "$base" ]; then
        # Fallback: check local branches
        if git show-ref --quiet refs/heads/main; then
            base="main"
        elif git show-ref --quiet refs/heads/master; then
            base="master"
        else
            base="main"
        fi
    fi
    printf '%s' "$base"
}

# Detect which worktree the current directory belongs to
current_worktree_path() {
    local cwd
    cwd=$(pwd)
    git worktree list --porcelain 2>/dev/null | awk '/^worktree /{path=$2} /^HEAD /{head=path; print head}' | while read -r wt_path; do
        case "$cwd" in
            "$wt_path"*) printf '%s' "$wt_path"; return ;;
        esac
    done
}

# Parse `git worktree list --porcelain` into arrays
# Outputs: <path> <head> <branch> per line (tab-separated)
list_worktrees_raw() {
    git worktree list --porcelain 2>/dev/null | awk '
        /^worktree /{ path=$2 }
        /^HEAD /    { head=$2 }
        /^branch /  { branch=$2 }
        /^(bare|detached)$/ { branch="(detached)" }
        /^$/ && path != "" {
            print path "\t" head "\t" branch
            path=""; head=""; branch=""
        }
        END {
            if (path != "") print path "\t" head "\t" branch
        }
    '
}

# ── Command: create ───────────────────────────────────────────────────────────
cmd_create() {
    require_git_repo

    if [ $# -lt 1 ]; then
        err "Usage: worktree_helper.sh create <branch-description> [--base BRANCH]"
        exit 1
    fi

    # Parse args: collect description words until --base
    local desc_parts=()
    local base=""
    local skip_next=0

    for arg in "$@"; do
        if [ "$skip_next" = "1" ]; then
            base="$arg"
            skip_next=0
            continue
        fi
        case "$arg" in
            --base) skip_next=1 ;;
            --base=*) base="${arg#--base=}" ;;
            *) desc_parts+=("$arg") ;;
        esac
    done

    local description="${desc_parts[*]}"

    if [ -z "$description" ]; then
        err "Branch description cannot be empty."
        exit 1
    fi

    # Determine branch name
    local branch
    # If description already looks like a branch (contains / and no spaces), use as-is
    case "$description" in
        */* )
            if ! printf '%s' "$description" | grep -q ' '; then
                branch="$description"
            else
                branch=$(description_to_branch "$description")
            fi
            ;;
        *) branch=$(description_to_branch "$description") ;;
    esac

    if [ -z "$base" ]; then
        base=$(default_base)
    fi

    local main_path
    main_path=$(main_worktree_path)
    local repo
    repo=$(repo_name)

    # Build worktree directory path: <parent-of-main>/<repo>-<branch-slug>
    local branch_slug
    branch_slug=$(printf '%s' "$branch" | sed 's|/|-|g')
    local worktree_dir
    worktree_dir="${main_path}/../${repo}-${branch_slug}"
    worktree_dir=$(realpath -m "$worktree_dir" 2>/dev/null || python3 -c "import os; print(os.path.normpath('$worktree_dir'))")

    info "Creating worktree"
    printf "  Branch:  ${BOLD}%s${RESET}\n" "$branch"
    printf "  Base:    ${BOLD}%s${RESET}\n" "$base"
    printf "  Path:    ${BOLD}%s${RESET}\n" "$worktree_dir"
    printf '\n'

    # Check branch doesn't already exist
    if git show-ref --quiet "refs/heads/$branch"; then
        err "Branch '$branch' already exists. Use a different description or specify a new name."
        exit 1
    fi

    # Check worktree path doesn't already exist
    if [ -e "$worktree_dir" ]; then
        err "Directory already exists: $worktree_dir"
        exit 1
    fi

    # Ensure base branch exists locally or as remote
    if ! git show-ref --quiet "refs/heads/$base" && ! git show-ref --quiet "refs/remotes/origin/$base"; then
        err "Base branch '$base' not found locally or in origin."
        exit 1
    fi

    git worktree add "$worktree_dir" -b "$branch" "$base"
    local exit_code=$?

    if [ "$exit_code" != "0" ]; then
        err "git worktree add failed (exit $exit_code)."
        exit 1
    fi

    ok "Worktree created successfully."
    printf '\n'
    bold "Worktree Path:"
    printf '  %s\n' "$worktree_dir"
    printf '\n'
    info "To switch into this worktree:"
    printf '  cd %s\n' "$worktree_dir"
}

# ── Command: status ───────────────────────────────────────────────────────────
cmd_status() {
    require_git_repo

    local main_path
    main_path=$(main_worktree_path)

    # Count total
    local total
    total=$(list_worktrees_raw | wc -l | tr -d ' ')

    bold "Worktree Status (${total} total)"
    printf '%s\n' "────────────────────────────────────────────────────────────────────────"
    printf "${BOLD}  %-30s %-35s %8s  %-6s  %s${RESET}\n" "Branch" "Path" "↑/↓" "State" "Last Commit"
    printf '%s\n' "────────────────────────────────────────────────────────────────────────"

    list_worktrees_raw | while IFS=$'\t' read -r wt_path head branch_ref; do
        # Short branch name
        local branch_short
        branch_short=$(printf '%s' "$branch_ref" | sed 's|refs/heads/||')

        # Mark main worktree
        local path_display="$wt_path"
        if [ "$wt_path" = "$main_path" ]; then
            path_display="${wt_path} (main)"
        fi

        # Relative path display (shorten home dir)
        local home_dir
        home_dir=$(printf '%s' "$HOME")
        path_display=$(printf '%s' "$path_display" | sed "s|^${home_dir}|~|")

        # Dirty status
        local dirty_count=0
        dirty_count=$(git -C "$wt_path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
        local state_str
        if [ "$dirty_count" -gt 0 ]; then
            state_str="${YELLOW}dirty${RESET}"
        else
            state_str="${GREEN}clean${RESET}"
        fi

        # Ahead/behind relative to default base
        local base
        base=$(default_base)
        local ahead=0 behind=0
        local ab
        ab=$(git -C "$wt_path" rev-list --left-right --count "origin/${base}...${branch_ref}" 2>/dev/null || true)
        if [ -n "$ab" ]; then
            behind=$(printf '%s' "$ab" | awk '{print $1}')
            ahead=$(printf '%s' "$ab" | awk '{print $2}')
        fi
        local ab_str="${GREEN}${ahead}↑${RESET} ${RED}${behind}↓${RESET}"

        # Last commit
        local last_commit
        last_commit=$(git -C "$wt_path" log -1 --format="%ar — %s" 2>/dev/null || printf 'no commits')

        printf "  ${CYAN}%-30s${RESET} %-35s %s  %-6b  %s\n" \
            "$branch_short" \
            "$path_display" \
            "$ab_str" \
            "$state_str" \
            "$last_commit"
    done

    printf '%s\n' "────────────────────────────────────────────────────────────────────────"
}

# ── Command: done ─────────────────────────────────────────────────────────────
cmd_done() {
    require_git_repo

    local target_path=""
    for arg in "$@"; do
        case "$arg" in
            --*) ;;  # skip flags for future use
            *) target_path="$arg" ;;
        esac
    done

    # Default to current worktree
    if [ -z "$target_path" ]; then
        target_path=$(current_worktree_path)
        if [ -z "$target_path" ]; then
            # Fallback: use pwd if it's a known worktree
            local cwd
            cwd=$(pwd)
            if git -C "$cwd" rev-parse --git-dir > /dev/null 2>&1; then
                target_path=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
            fi
        fi
        if [ -z "$target_path" ]; then
            err "Cannot detect current worktree. Run from inside a worktree or provide a path."
            exit 1
        fi
    fi

    # Verify the path is a registered worktree
    local found=0
    local branch_ref=""
    while IFS=$'\t' read -r wt_path head branch; do
        if [ "$wt_path" = "$target_path" ]; then
            found=1
            branch_ref="$branch"
            break
        fi
    done <<EOF
$(list_worktrees_raw)
EOF

    if [ "$found" = "0" ]; then
        err "Path is not a registered git worktree: $target_path"
        err "Registered worktrees:"
        list_worktrees_raw | awk -F'\t' '{print "  " $1}' >&2
        exit 1
    fi

    local branch_short
    branch_short=$(printf '%s' "$branch_ref" | sed 's|refs/heads/||')

    bold "Worktree Done: ${branch_short}"
    printf '%s\n' "──────────────────────────────────────────"

    # Pre-check 1: clean working tree
    local dirty_count
    dirty_count=$(git -C "$target_path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    if [ "$dirty_count" -gt 0 ]; then
        err "Working tree is dirty (${dirty_count} uncommitted change(s))."
        err "Please commit or stash changes before marking done."
        git -C "$target_path" status --short
        exit 1
    fi
    ok "Working tree is clean."

    # Pre-check 2: all changes committed (not just clean, but has commits)
    local base
    base=$(default_base)
    local ahead=0
    local ab
    ab=$(git -C "$target_path" rev-list --left-right --count "origin/${base}...${branch_ref}" 2>/dev/null || true)
    if [ -n "$ab" ]; then
        ahead=$(printf '%s' "$ab" | awk '{print $2}')
    fi

    # Summary
    local commit_count=0
    commit_count=$(git -C "$target_path" rev-list --count "${base}..${branch_short}" 2>/dev/null || printf '0')

    local files_changed=0
    files_changed=$(git -C "$target_path" diff --name-only "${base}..${branch_short}" 2>/dev/null | wc -l | tr -d ' ')

    printf '\n'
    bold "Summary:"
    printf "  Branch:         %s\n" "$branch_short"
    printf "  Commits ahead:  %s\n" "$commit_count"
    printf "  Files changed:  %s\n" "$files_changed"
    printf "  Worktree path:  %s\n" "$target_path"
    printf '\n'

    if [ "$commit_count" -eq 0 ]; then
        warn "No commits ahead of base branch '${base}'. Nothing to merge."
    fi

    bold "To merge this worktree into ${base}, run ONE of:"
    printf '\n'
    info "Merge commit (preserves full history):"
    printf '  git checkout %s && git merge --no-ff %s\n' "$base" "$branch_short"
    printf '\n'
    info "Squash merge (single clean commit):"
    printf '  git checkout %s && git merge --squash %s && git commit\n' "$base" "$branch_short"
    printf '\n'
    info "Rebase (linear history):"
    printf '  git -C %s rebase %s && git checkout %s && git merge --ff-only %s\n' \
        "$target_path" "$base" "$base" "$branch_short"
    printf '\n'
    info "After merging, clean up with:"
    printf '  worktree_helper.sh cleanup\n'
}

# ── Command: cleanup ─────────────────────────────────────────────────────────
cmd_cleanup() {
    require_git_repo

    local dry_run=0
    local force=0

    for arg in "$@"; do
        case "$arg" in
            --dry-run) dry_run=1 ;;
            --force)   force=1 ;;
        esac
    done

    local base
    base=$(default_base)
    local main_path
    main_path=$(main_worktree_path)

    bold "Scanning worktrees for merged branches..."
    printf '%s\n' "──────────────────────────────────────────"

    local merged_worktrees=()
    local merged_branches=()
    local unmerged_worktrees=()
    local unmerged_branches=()

    while IFS=$'\t' read -r wt_path head branch_ref; do
        # Skip main worktree
        if [ "$wt_path" = "$main_path" ]; then
            continue
        fi

        local branch_short
        branch_short=$(printf '%s' "$branch_ref" | sed 's|refs/heads/||')

        # Check if branch is merged into base
        local is_merged=0
        if git -C "$main_path" branch --merged "$base" 2>/dev/null | grep -qF "$branch_short"; then
            is_merged=1
        fi

        if [ "$is_merged" = "1" ]; then
            merged_worktrees+=("$wt_path")
            merged_branches+=("$branch_short")
        else
            unmerged_worktrees+=("$wt_path")
            unmerged_branches+=("$branch_short")
        fi
    done <<EOF
$(list_worktrees_raw)
EOF

    # Report merged
    if [ "${#merged_worktrees[@]}" -eq 0 ]; then
        ok "No merged worktrees to clean up."
    else
        bold "Merged (safe to remove):"
        local i=0
        while [ "$i" -lt "${#merged_worktrees[@]}" ]; do
            printf "  ${GREEN}✓${RESET}  %-30s  %s\n" "${merged_branches[$i]}" "${merged_worktrees[$i]}"
            i=$((i+1))
        done
        printf '\n'
    fi

    # Report unmerged
    if [ "${#unmerged_worktrees[@]}" -gt 0 ]; then
        bold "Unmerged (require confirmation):"
        local j=0
        while [ "$j" -lt "${#unmerged_worktrees[@]}" ]; do
            printf "  ${YELLOW}⚠${RESET}  %-30s  %s\n" "${unmerged_branches[$j]}" "${unmerged_worktrees[$j]}"
            j=$((j+1))
        done
        printf '\n'
    fi

    if [ "$dry_run" = "1" ]; then
        info "Dry-run mode: no changes made."
        exit 0
    fi

    # Remove merged worktrees
    if [ "${#merged_worktrees[@]}" -gt 0 ]; then
        if [ "$force" = "0" ]; then
            printf '%s' "Remove ${#merged_worktrees[@]} merged worktree(s)? [y/N] "
            read -r confirm
            case "$confirm" in
                [Yy]*) ;;
                *) info "Skipped merged worktrees."; exit 0 ;;
            esac
        fi

        local k=0
        while [ "$k" -lt "${#merged_worktrees[@]}" ]; do
            local wt="${merged_worktrees[$k]}"
            local br="${merged_branches[$k]}"
            info "Removing worktree: $wt"
            git worktree remove "$wt" 2>/dev/null || git worktree remove --force "$wt" || true
            info "Deleting branch: $br"
            git branch -d "$br" 2>/dev/null || warn "Could not delete branch '$br' (may already be gone)."
            k=$((k+1))
        done
        ok "Removed ${#merged_worktrees[@]} merged worktree(s)."
    fi

    # Handle unmerged worktrees interactively
    if [ "${#unmerged_worktrees[@]}" -gt 0 ] && [ "$force" = "0" ]; then
        bold "Handling unmerged worktrees:"
        local m=0
        while [ "$m" -lt "${#unmerged_worktrees[@]}" ]; do
            local uwt="${unmerged_worktrees[$m]}"
            local ubr="${unmerged_branches[$m]}"
            printf '\n'
            warn "Unmerged: ${ubr} → ${uwt}"
            printf '  [b] Create backup branch + remove\n'
            printf '  [f] Force remove (lose commits)\n'
            printf '  [s] Skip\n'
            printf '%s' "  Choice [b/f/s]: "
            read -r choice
            case "$choice" in
                [Bb]*)
                    local backup_branch="backup/${ubr//\//-}-$(date +%Y%m%d%H%M%S)"
                    git branch "$backup_branch" "$ubr" && ok "Backup created: $backup_branch"
                    git worktree remove "$uwt" 2>/dev/null || git worktree remove --force "$uwt" || true
                    git branch -D "$ubr" || true
                    ok "Removed (backup: $backup_branch)."
                    ;;
                [Ff]*)
                    git worktree remove --force "$uwt" || true
                    git branch -D "$ubr" || true
                    ok "Force removed: $ubr"
                    ;;
                *)
                    info "Skipped: $ubr"
                    ;;
            esac
            m=$((m+1))
        done
    fi

    # Prune stale worktree entries
    printf '\n'
    info "Pruning stale worktree entries..."
    git worktree prune
    ok "Prune complete."

    printf '\n'
    bold "Cleanup done."
}

# ── Main dispatch ─────────────────────────────────────────────────────────────
main() {
    if [ $# -eq 0 ]; then
        bold "worktree_helper.sh — Git worktree lifecycle manager"
        printf '\n'
        printf 'Usage:\n'
        printf '  worktree_helper.sh create <branch-description> [--base BRANCH]\n'
        printf '  worktree_helper.sh status\n'
        printf '  worktree_helper.sh done [WORKTREE_PATH]\n'
        printf '  worktree_helper.sh cleanup [--dry-run] [--force]\n'
        printf '\n'
        printf 'Examples:\n'
        printf '  worktree_helper.sh create "fix login bug"\n'
        printf '  worktree_helper.sh create "add oauth support" --base develop\n'
        printf '  worktree_helper.sh create feature/custom-name\n'
        printf '  worktree_helper.sh status\n'
        printf '  worktree_helper.sh done\n'
        printf '  worktree_helper.sh done /path/to/worktree\n'
        printf '  worktree_helper.sh cleanup --dry-run\n'
        printf '  worktree_helper.sh cleanup --force\n'
        exit 0
    fi

    local cmd="$1"
    shift

    case "$cmd" in
        create)  cmd_create "$@" ;;
        status)  cmd_status "$@" ;;
        done)    cmd_done "$@" ;;
        cleanup) cmd_cleanup "$@" ;;
        *)
            err "Unknown command: $cmd"
            err "Valid commands: create, status, done, cleanup"
            exit 1
            ;;
    esac
}

main "$@"
