#!/usr/bin/env bash
# Poll the local bot database and log until something changes, then dump state.
#
# usage: watch.sh "<snapshot SQL>" [max_seconds] [db_path] [log_path]
#
# The snapshot SQL should return whatever the next test step is expected to
# change, e.g. "SELECT MAX(log_id) FROM logs". The loop ends when that result
# differs from its starting value or when a new Traceback/ERROR line lands in
# the log. Exit code 0 on change, 2 on timeout, so a caller can tell them apart.

set -u

snapshot_sql="${1:?snapshot SQL required}"
max_seconds="${2:-540}"
db="${3:-data/db.sqlite3}"
log="${4:-/tmp/jouzu_live.log}"

snap() { sqlite3 "$db" "$snapshot_sql"; }
errs() { grep -c -E "Traceback|ERROR" "$log" 2>/dev/null || true; }

base_snap=$(snap)
base_errs=$(errs)
changed=0
waited=0

while [ "$waited" -lt "$max_seconds" ]; do
  if [ "$(snap)" != "$base_snap" ] || [ "$(errs)" != "$base_errs" ]; then
    changed=1
    # The bot writes several rows per command; let it finish before reading.
    sleep 3
    break
  fi
  sleep 5
  waited=$((waited + 5))
done

echo "--- snapshot before: $base_snap"
echo "--- snapshot after:  $(snap)"
echo "--- newest logs:"
sqlite3 -header "$db" "SELECT log_id, user_id, media_type, amount_logged, time_logged, log_date FROM logs ORDER BY log_id DESC LIMIT 3;"
echo "--- user_preferences:"
sqlite3 -header "$db" "SELECT * FROM user_preferences;"
echo "--- new errors:"
if [ "$(errs)" = "$base_errs" ]; then
  echo none
else
  grep -E -A 20 "ERROR" "$log" | tail -n 40
fi

if [ "$changed" = "1" ]; then
  exit 0
fi
echo "--- timed out after ${max_seconds}s with no change"
exit 2
