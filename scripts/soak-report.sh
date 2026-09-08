#!/usr/bin/env bash
#
# Nightly soak report — stage B of docs/autonomous-build.md.
#
# Summarises what the sensors actually reported, so the moisture thresholds in
# config/plants.toml can be set from data instead of guessed. Read-only: it
# touches nothing but the database, and writes a dated markdown file.
#
# Wants layer 04a running with automation_enabled = false.
#
# The queries below assume the table and column names layer 02 is expected to
# create (reading, channel, node, sensor, plant, event). If layer 02 lands on
# different names, update this script in the same commit — it is the first
# consumer of that schema and a useful check that the narrow-row shape (DATA-1)
# and the role column (DATA-3) actually work.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

DB="${SMARTGARDEN_DB:-$REPO/data/smartgarden.db}"
OUT_DIR="$REPO/.autobuild/soak"
OUT="$OUT_DIR/$(date -u +%Y-%m-%d).md"
mkdir -p "$OUT_DIR"

if [[ ! -f "$DB" ]]; then
    echo "No database at $DB — is the control loop running?" >&2
    exit 69
fi

# Read-only connection, so a long query can never block a control-loop write.
q() { sqlite3 -readonly -noheader -separator ' | ' "$DB" "$1" 2>/dev/null; }

{
    echo "# Soak report — $(date -u +'%Y-%m-%d %H:%M UTC')"
    echo
    echo "Database: \`$DB\`"
    echo

    echo '## Automation'
    echo
    if grep -Eq '^\s*automation_enabled\s*=\s*true' config/app.toml; then
        echo '**automation_enabled = true** — this is no longer a soak.'
    else
        echo 'automation_enabled = false. Observing only, as intended.'
    fi
    echo

    echo '## Coverage, last 24h'
    echo
    echo '```'
    q "SELECT c.role,
              COUNT(*)                        AS samples,
              ROUND(MIN(r.value), 1)          AS min,
              ROUND(AVG(r.value), 1)          AS mean,
              ROUND(MAX(r.value), 1)          AS max,
              SUM(CASE WHEN r.quality != 'ok' THEN 1 ELSE 0 END) AS flagged
         FROM reading r
         JOIN channel c ON c.id = r.channel_id
        WHERE r.ts >= datetime('now', '-1 day')
        GROUP BY c.role
        ORDER BY c.role;"
    echo '```'
    echo

    echo '## Soil moisture by day'
    echo
    echo 'The plateau in the days after a watering is your `moisture_high`.'
    echo 'The level at which the plant started to look thirsty is `moisture_low`.'
    echo 'A Seesaw reads roughly 200 in open air and 2000 in water.'
    echo
    echo '```'
    q "SELECT date(r.ts)                AS day,
              COALESCE(p.slug, c.role)  AS plant,
              ROUND(MIN(r.value))       AS min,
              ROUND(AVG(r.value))       AS mean,
              ROUND(MAX(r.value))       AS max
         FROM reading r
         JOIN channel c ON c.id = r.channel_id
    LEFT JOIN plant   p ON p.id = c.plant_id
        WHERE c.role = 'soil_moisture'
          AND r.ts >= datetime('now', '-14 days')
        GROUP BY day, plant
        ORDER BY day DESC, plant;"
    echo '```'
    echo

    echo '## Node health'
    echo
    echo '```'
    q "SELECT slug,
              last_seen_at,
              CASE WHEN last_seen_at < datetime('now', '-' || stale_after_s || ' seconds')
                   THEN 'OFFLINE' ELSE 'ok' END AS state
         FROM node ORDER BY slug;"
    echo '```'
    echo

    echo '## Read failures, last 24h'
    echo
    echo '```'
    q "SELECT s.slug, COUNT(*) AS failures, MAX(e.ts) AS latest
         FROM event e JOIN sensor s ON s.id = e.sensor_id
        WHERE e.kind = 'read_failure'
          AND e.ts >= datetime('now', '-1 day')
        GROUP BY s.slug ORDER BY failures DESC;"
    echo '```'
    echo

    echo '## Days of data so far'
    echo
    echo '```'
    q "SELECT ROUND(julianday('now') - julianday(MIN(ts)), 1) || ' days'
         FROM reading;"
    echo '```'
    echo
    echo 'Seven days minimum, across varied weather, before setting thresholds.'
} >"$OUT"

echo "$OUT"
