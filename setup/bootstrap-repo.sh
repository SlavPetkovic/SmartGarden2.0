#!/usr/bin/env bash
#
# One-time repository setup. Run this once, from the repository root, on any
# machine that has `gh` authenticated as the account that should own the repo.
#
#   ./setup/bootstrap-repo.sh smartgarden
#   ./setup/bootstrap-repo.sh smartgarden --public
#   ./setup/bootstrap-repo.sh smartgarden --dry-run
#
# It does five things, and says what it is doing at each step:
#
#   1. creates the GitHub repository (private by default)
#   2. makes the initial commit and pushes main
#   3. enables squash-only merges, auto-merge, and branch deletion on merge
#   4. protects main: every CI check required, zero approvals required
#   5. reports what it could not do, rather than pretending it did
#
# Step 4 is the one that can fail. Branch protection on a *private* repository
# needs a paid GitHub plan; on a free account the API returns 403. That is not
# fatal -- the /ship command checks CI before merging regardless -- but you
# should know which of the two you got, so the script says so plainly at the
# end.
#
# Safe to read before running. It does nothing clever.

set -euo pipefail

NAME="${1:-}"
VISIBILITY="--private"
DRY_RUN=0
PROTECT_ONLY=0

shift || true
while (( $# )); do
    case "$1" in
        --public)       VISIBILITY="--public" ;;
        --private)      VISIBILITY="--private" ;;
        --dry-run)      DRY_RUN=1 ;;
        --protect-only) PROTECT_ONLY=1 ;;
        *) echo "unknown option: $1" >&2; exit 64 ;;
    esac
    shift
done

if [[ -z "$NAME" ]]; then
    cat >&2 <<'EOF'
usage: setup/bootstrap-repo.sh <repo-name> [--public|--private] [--dry-run]

Creates the GitHub repository, pushes this directory to it as the initial
commit, and configures main so that CI is the merge gate.
EOF
    exit 64
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m    ! %s\033[0m\n' "$*"; }

run() {
    if (( DRY_RUN )); then
        printf '    [dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

# --- preflight --------------------------------------------------------------

say "Preflight"

command -v gh  >/dev/null || { echo "gh is not installed: https://cli.github.com" >&2; exit 69; }
command -v git >/dev/null || { echo "git is not installed" >&2; exit 69; }

if ! gh auth status >/dev/null 2>&1; then
    echo "gh is not authenticated. Run: gh auth login" >&2
    exit 77
fi

# Checked before anything is created. A missing git identity fails at the
# commit, which is after the repository exists -- the one state this script
# would otherwise leave behind half-finished.
if ! git config user.email >/dev/null || ! git config user.name >/dev/null; then
    cat >&2 <<'EOF'
git has no commit identity on this machine. Set one first:

    git config --global user.name  "Slav Petkovic"
    git config --global user.email "you@example.com"

EOF
    exit 78
fi
note "commit identity: $(git config user.name) <$(git config user.email)>"

OWNER="$(gh api user --jq .login)"
note "authenticated as $OWNER"
note "repository will be $OWNER/$NAME ($( [[ $VISIBILITY == --private ]] && echo private || echo public ))"

# The whole point of this build is that main is protected by CI rather than by
# a person. If the account cannot protect a branch on a private repo, say so
# now rather than after everything is pushed.
if [[ "$VISIBILITY" == "--private" ]]; then
    PLAN="$(gh api user --jq '.plan.name // "unknown"' 2>/dev/null || echo unknown)"
    note "account plan: $PLAN"
    if [[ "$PLAN" == "free" ]]; then
        warn "Branch protection on a private repository needs a paid plan."
        warn "The script will still try; if it fails, see 'What you got' at the end."
    fi
fi

if [[ -d .git ]]; then
    note "this directory is already a git repository -- will push to the new remote"
    ALREADY_GIT=1
else
    ALREADY_GIT=0
fi

# --protect-only: the repository already exists and only step 4 needs redoing,
# which is the case after moving a private repo to a paid plan or to public.
if (( PROTECT_ONLY )); then
    if ! gh repo view "$OWNER/$NAME" >/dev/null 2>&1; then
        echo "REFUSING: $OWNER/$NAME does not exist. Drop --protect-only." >&2
        exit 65
    fi
    note "--protect-only: skipping create, push, settings and labels"
elif gh repo view "$OWNER/$NAME" >/dev/null 2>&1; then
    echo >&2
    echo "REFUSING: $OWNER/$NAME already exists." >&2
    echo "Pick another name, or delete it yourself first. This script will not" >&2
    echo "overwrite a repository that has anything in it." >&2
    exit 65
fi

if (( ! PROTECT_ONLY )); then

# --- 1. create --------------------------------------------------------------

say "Creating $OWNER/$NAME"
run gh repo create "$NAME" "$VISIBILITY" \
    --description "Sensor-driven irrigation and lighting on a Raspberry Pi 5" \
    --disable-wiki

# --- 2. initial commit and push ---------------------------------------------

say "Putting the CI workflows in place"
# They are staged under setup/github/ rather than living in .github/ directly,
# because the OneDrive folder that syncs this repository cannot write into a
# dotted config directory. Same reason setup/claude/ exists.
note ".github/workflows/ci.yml, tripwires.yml, pull_request_template.md"
run mkdir -p .github/workflows
run cp setup/github/workflows/ci.yml         .github/workflows/ci.yml
run cp setup/github/workflows/tripwires.yml  .github/workflows/tripwires.yml
run cp setup/github/pull_request_template.md .github/pull_request_template.md

say "Pushing the initial commit"

if (( ! ALREADY_GIT )); then
    run git init -b main
fi

run git add .

if (( DRY_RUN )) || [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    run git commit -m "Layer 01: foundation, and the repository contract

Configuration loading and validation, core domain types, and the physics
module (VPD, dew point, daily light integral, unit conversion).

The control service has no third-party dependencies by design; web and
hardware libraries are opt-in extras. No hardware required to run the suite.

Also establishes how this repository is governed: CI is the merge gate
(.github/workflows/), the structural invariants CLAUDE.md calls correctness
bugs are checked mechanically (scripts/gate.py), and changes to tuning,
safety constants or the requirements themselves have to be declared in the
pull request body (scripts/diff_gate.py). docs/git-workflow.md is the
contract.

Specification and diagrams in docs/architecture.html."
fi

run git remote remove origin 2>/dev/null || true
run git remote add origin "https://github.com/$OWNER/$NAME.git"
run git push -u origin main

# --- 3. repository settings -------------------------------------------------

say "Configuring merge behaviour"
note "squash only, auto-merge on, delete branch on merge"

run gh api -X PATCH "repos/$OWNER/$NAME" \
    -F allow_squash_merge=true \
    -F allow_merge_commit=false \
    -F allow_rebase_merge=false \
    -F allow_auto_merge=true \
    -F delete_branch_on_merge=true \
    -F has_issues=true \
    --silent

fi   # end: skipped entirely under --protect-only

# --- 4. branch protection ---------------------------------------------------

say "Protecting main"
note "required checks: the four CI jobs plus the tripwires"
note "required approvals: zero -- CI is the reviewer"

PROTECTION_OK=0
if (( DRY_RUN )); then
    note "[dry-run] would PUT repos/$OWNER/$NAME/branches/main/protection"
    PROTECTION_OK=1
elif gh api -X PUT "repos/$OWNER/$NAME/branches/main/protection" \
        --input - --silent <<EOF 2>/dev/null
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "tests (no dependencies)"},
      {"context": "ruff + mypy"},
      {"context": "structural guard rails"},
      {"context": "pytest + coverage"},
      {"context": "change-shape tripwires"}
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true,
  "required_conversation_resolution": true
}
EOF
then
    PROTECTION_OK=1
else
    warn "Could not set branch protection."
    warn "Most likely cause: private repository on a free GitHub plan."
fi

# --- 5. labels --------------------------------------------------------------

if (( ! PROTECT_ONLY )); then
say "Labels"
add_label() {
    run gh label create "$1" --color "$2" --description "$3" --force >/dev/null 2>&1 \
        || true
    note "$1"
}
add_label "layer"        "0e8a16" "One layer of the build plan"
add_label "blocked"      "d93f0b" "Stopped on a gate that cannot be passed honestly"
add_label "soak"         "1d76db" "Depends on data from the seven-day soak"
add_label "hardware"     "5319e7" "Needs something wired, moved or measured"
add_label "gate-change"  "fbca04" "Changes a check, not the code a check judges"
fi

# --- what you got -----------------------------------------------------------

cat <<EOF

────────────────────────────────────────────────────────────────────────
  What you got
────────────────────────────────────────────────────────────────────────

  Repository   https://github.com/$OWNER/$NAME
  Merge style  squash only, branch deleted on merge
EOF

if (( PROTECTION_OK )); then
    cat <<'EOF'
  main         PROTECTED. Five required checks, zero required approvals,
               no force pushes, no deletion, linear history.

               This is the arrangement the build assumes: Claude Code
               merges its own pull requests, and the checks are what
               make that safe. GitHub itself will refuse a red merge.
EOF
else
    cat <<EOF
  main         NOT PROTECTED -- the API refused.

               Everything still works: /ship runs \`gh pr checks --watch\`
               and refuses to merge on red, and docs/git-workflow.md
               forbids merging past a check. But that is a contract Claude
               Code keeps, not a rule the server enforces.

               To get server enforcement, either:
                 - make the repository public (protection is free there):
                     gh repo edit $OWNER/$NAME --visibility public
                 - or upgrade to GitHub Pro.
               Either way, then re-run:
                     setup/bootstrap-repo.sh $NAME --protect-only

               Worth doing before layer 04b, which is the first layer that
               can open a valve.
EOF
fi

cat <<EOF

  Next         On the Pi:

                 git clone https://github.com/$OWNER/$NAME.git ~/SmartGarden
                 cd ~/SmartGarden
                 mkdir -p .claude/commands
                 cp setup/claude/settings.json          .claude/settings.json
                 cp setup/claude/commands/*.md          .claude/commands/
                 python3 -m venv .venv && .venv/bin/pip install -e ".[pi,web,dev]"
                 gh auth login          # Claude Code pushes and merges as you
                 claude

               Then paste START-HERE.md into the session.

EOF
