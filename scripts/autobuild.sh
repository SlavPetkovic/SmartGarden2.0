#!/usr/bin/env bash
#
# Unattended layer build driver.
#
#   scripts/autobuild.sh 02          # build layer 02 until its gate passes
#   scripts/autobuild.sh 03 8        # ...allowing 8 attempts instead of 6
#
# Creates branch auto/layer-NN, hands Claude the layer's gate from
# docs/autonomous-build.md, then re-checks the gate itself. A gate that Claude
# believes it passed is not a gate; this script is the arbiter.
#
# Stops after MAX attempts and writes .autobuild/BLOCKED-NN.md.
#
# On a green gate it pushes the branch and opens a pull request, and CI re-runs
# the same three checks on a clean machine before the pull request merges
# itself. That second run is not redundant: a gate that has only ever run on
# the Pi has only ever been checked against the Pi's installed packages.
#
# Pass --no-ship to stop after the push, leaving the pull request for a person.
# See docs/git-workflow.md for what this script may and may not do.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

LAYER=""
MAX=6
SHIP=1

while (( $# )); do
    case "$1" in
        --no-ship) SHIP=0 ;;
        -*) echo "unknown option: $1" >&2; exit 64 ;;
        *) if [[ -z "$LAYER" ]]; then LAYER="$1"; else MAX="$1"; fi ;;
    esac
    shift
done

if [[ -z "$LAYER" ]]; then
    echo "usage: scripts/autobuild.sh <layer: 02|03|04a|05|06|04b> [max-attempts] [--no-ship]" >&2
    exit 64
fi

BRANCH="auto/layer-${LAYER}"
LOGS="$REPO/.autobuild"
PY="$REPO/.venv/bin/python"
mkdir -p "$LOGS"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

if [[ ! -x "$PY" ]]; then
    echo "No virtualenv at .venv — see docs/pi-setup.md §3." >&2
    exit 69
fi

# --- guard rails ------------------------------------------------------------
# Refuse to run if automation is live. An unattended build must never be
# iterating against a system that can open a valve.
if grep -Eq '^\s*automation_enabled\s*=\s*true' config/app.toml; then
    echo "REFUSING: automation_enabled = true in config/app.toml." >&2
    echo "Turn automation off before running an unattended build." >&2
    exit 78
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "REFUSING: working tree is dirty. Commit or stash first." >&2
    git status --short >&2
    exit 65
fi

# --- the gate ---------------------------------------------------------------
gate() {
    local ok=0
    log "gate: unittest"
    PYTHONPATH=src "$PY" -m unittest discover -s tests -t . \
        >"$LOGS/gate-tests.log" 2>&1 || ok=1
    log "gate: ruff"
    "$REPO/.venv/bin/ruff" check . >"$LOGS/gate-ruff.log" 2>&1 || ok=1
    log "gate: mypy"
    "$REPO/.venv/bin/mypy" >"$LOGS/gate-mypy.log" 2>&1 || ok=1
    log "gate: structural guard rails"
    "$PY" scripts/gate.py >"$LOGS/gate-rails.log" 2>&1 || ok=1
    return $ok
}

gate_failures() {
    for f in tests ruff mypy rails; do
        if [[ -s "$LOGS/gate-$f.log" ]]; then
            echo "--- $f ---"
            tail -n 40 "$LOGS/gate-$f.log"
        fi
    done
}

# --- branch -----------------------------------------------------------------
git rev-parse --verify --quiet "$BRANCH" >/dev/null \
    && git switch "$BRANCH" \
    || git switch -c "$BRANCH"

log "building layer $LAYER on $BRANCH (max $MAX attempts)"

FEEDBACK=""
for (( attempt = 1; attempt <= MAX; attempt++ )); do
    log "attempt $attempt/$MAX"

    claude -p "Read docs/autonomous-build.md and build layer ${LAYER}.

Its acceptance gate is the section for layer ${LAYER} in §4 of that document.
Every item in that gate must be true and every requirement ID it names must be
satisfied. The operating contract in §2 and the stop conditions in §6 bind you.

docs/git-workflow.md is the contract for what you may do to this repository.

Work only on this branch. Run the test suite, ruff, mypy and scripts/gate.py
yourself and iterate until all four are clean. Commit your work with a message
naming the requirement IDs you satisfied. Do not push or open a pull request
here -- this script does that once the gate is green.

Do not weaken a test, widen a range, or relax a safety constant to pass.
If you cannot pass honestly, write .autobuild/BLOCKED-${LAYER}.md explaining
what is in the way, and stop.${FEEDBACK}" \
        --permission-mode acceptEdits \
        --permission-prompts none \
        --output-format json \
        >"$LOGS/claude-${LAYER}-${attempt}.json" 2>"$LOGS/claude-${LAYER}-${attempt}.err"

    if [[ -f ".autobuild/BLOCKED-${LAYER}.md" ]]; then
        log "BLOCKED — Claude stopped and explained why:"
        cat ".autobuild/BLOCKED-${LAYER}.md"
        exit 75
    fi

    if gate; then
        log "gate passed on attempt $attempt"
        git --no-pager log --oneline main.."$BRANCH" 2>/dev/null || true

        if (( ! SHIP )); then
            cat <<EOF

Layer $LAYER is green on $BRANCH. --no-ship, so stopping here.
Push and open the pull request yourself, or run: claude -p "/ship"

EOF
            exit 0
        fi

        log "pushing $BRANCH"
        if ! git push -u origin "$BRANCH" >"$LOGS/push-${LAYER}.log" 2>&1; then
            log "push failed -- see .autobuild/push-${LAYER}.log"
            tail -n 20 "$LOGS/push-${LAYER}.log"
            exit 74
        fi

        # Claude writes the body: the "what I was unsure about" section is the
        # point of the template and this script has no way to fill it in.
        log "opening the pull request"
        claude -p "The gate for layer ${LAYER} is green and branch ${BRANCH} is pushed.

Run /ship for it. Write the pull request body to the shape in
docs/git-workflow.md section 6, including the 'What I was unsure about'
section honestly. Wait for CI. Merge only on green. If a required check is
red, do not merge and do not work around it -- report what failed.

If the change touches tuning, a safety constant, a contract document or
removes tests, add the matching declaration line with a real reason." \
            --permission-mode acceptEdits \
            --permission-prompts none \
            >"$LOGS/ship-${LAYER}.json" 2>"$LOGS/ship-${LAYER}.err"

        echo
        gh pr view --json url,state,mergedAt 2>/dev/null \
            || log "no pull request found -- see .autobuild/ship-${LAYER}.err"
        echo
        exit 0
    fi

    log "gate failed; feeding failures back"
    FEEDBACK="

The gate was re-checked after your last attempt and still fails. Output:

$(gate_failures)

Fix the cause. Do not adjust the test to match the code unless the test is
provably wrong about a requirement, and say so explicitly if you conclude that."
done

{
    echo "# Layer $LAYER blocked after $MAX attempts"
    echo
    echo "Generated $(date -u +'%Y-%m-%d %H:%M UTC') by scripts/autobuild.sh"
    echo
    echo '## Last gate output'
    echo
    echo '```'
    gate_failures
    echo '```'
} >"$LOGS/BLOCKED-${LAYER}.md"

log "BLOCKED after $MAX attempts — see .autobuild/BLOCKED-${LAYER}.md"
exit 75
