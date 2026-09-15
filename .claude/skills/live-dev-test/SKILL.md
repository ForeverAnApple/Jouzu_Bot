---
name: live-dev-test
description: Bring up the local dev Discord bot (Slime) and monitor it while the user drives slash commands in Discord, then confirm each step from the SQLite database and the bot log. Use this whenever the user wants to test, try, or verify a bot change live, says "bring up the test bot", "let me test it", "I'll test now, you monitor", "start the bot", or when a change to a cog, slash command, embed, or /log behaviour needs end-to-end proof beyond unit tests. Unit tests passing is not done in this repo; watched working in Discord is.
---

# Live dev test

The bot cannot be driven from here. The user clicks in Discord; you run the bot, watch what it writes, and confirm each step from evidence. Your job is to make their clicks cheap and your verification independent of their word.

## What you are working with

- `python main.py` from the repo root starts the bot with every cog in `cogs/`. The local `.env` token is the dev bot Slime, not prod. It DMs `DEBUG_USER` "Bot is ready" on login.
- `data/db.sqlite3` is the local database. Every slash command that matters writes to it. Tables: `logs`, `user_preferences`, `user_goals`, `users`, plus caches.
- The bot logs cog loads, login, and tracebacks. It does not log successful slash commands. So the database is your only signal that a command ran, and the log is your only signal that it crashed.
- The tester's Discord id is `DEBUG_USER` in `.env`. Read it with `grep ^DEBUG_USER= .env`.
- `scripts/watch.sh` in this skill polls the database and the log for you. Details below.

## Procedure

### 1. Preflight

Run the unit tests. If they fail, fix that first. A live test on broken code wastes the user's clicks.

Check nothing is already running: `pgrep -fl "python main.py"`. Kill a stale instance with `pkill -f "python main.py"`; two bots on one token fight over the gateway.

### 2. Start and confirm

```bash
nohup python main.py > /tmp/jouzu_live.log 2>&1 &
sleep 8
grep -E "Loaded cogs\.|Logged in as|Traceback|ERROR" /tmp/jouzu_live.log
```

You need three things in that output: the cog you changed loaded, `Logged in as Slime`, and no traceback. A cog that fails to load logs a traceback and the bot still comes up, so do not stop reading at the login line.

If your change touched schema, check the migration ran: `sqlite3 data/db.sqlite3 "PRAGMA table_info(<table>);"`.

### 3. Sync only when the command surface changed

Discord caches slash command definitions. Sync is needed when a command was added, renamed, or had its parameters or description changed. Behaviour changes inside an existing command need no sync.

When sync is needed, tell the user to run `%sync_guild` **in a server channel**. In a DM the command crashes because `ctx.guild` is None. Watch the log for that traceback and tell them if it happens.

### 4. Hand the user a script

Write a numbered list, one action per step, with the exact visible outcome to expect. The user should never have to guess whether a step passed. Example:

```
1. /log media_type:Reading time_mins:12 name:test. Expect the embed and an ephemeral WARNING, no tip.
2. Same again. Expect WARNING plus an ephemeral tip mentioning /toggle_log_warning.
3. /toggle_log_warning. Expect the ephemeral "now off" reply.
4. Same /log. Expect the embed and nothing else.
```

Order steps so each one changes database state you can check. Ephemeral messages show "Only you can see this" in Discord; say so when that is the expected outcome, because that is the one thing the database cannot tell you.

### 5. Watch

Start the watcher in the background before the user begins:

```bash
bash .claude/skills/live-dev-test/scripts/watch.sh "<snapshot SQL>" [max_seconds]
```

The snapshot SQL is whatever should change on the next step. Good snapshots:

- `SELECT MAX(log_id) FROM logs` for anything that creates a log.
- `SELECT log_warnings, last_log_warning_at, last_nudge_at FROM user_preferences WHERE user_id=<DEBUG_USER>` for preference changes.
- `SELECT COUNT(*) FROM user_goals WHERE user_id=<DEBUG_USER>` for goal commands.

The script polls every 5 seconds until the snapshot changes or a new traceback appears, then prints the before and after snapshot, the newest log rows, and any new errors. Run it with `run_in_background` so you get pinged. Keep `max_seconds` under 600; the Bash tool caps there. When it fires, read the output, confirm or refute the step, and re-arm for the next one.

If the watcher fires on a timeout with nothing changed, the user has not acted yet. Say so briefly and re-arm.

### 6. Confirm from evidence, not from the user

After each step, state what the database shows and whether it matches the expected outcome. The user's "perfect" tells you what they saw on screen. The row tells you what the code did. You need both, and only the second one is yours to report.

A step passes when the visible outcome the user reports and the database evidence both match the script. A mismatch is a bug, even if the user is happy.

### 7. Changing code mid-test

Edit, rerun the unit tests, then restart:

```bash
pkill -f "python main.py"; sleep 2
nohup python main.py > /tmp/jouzu_live.log 2>&1 &
sleep 8; grep -E "Loaded cogs\.|Logged in as|Traceback" /tmp/jouzu_live.log
```

Restarting replaces the log file, which resets the watcher's error baseline. A watcher started before the restart will fire spuriously. Stop it and start a fresh one.

### 8. Teardown and report

`pkill -f "python main.py"`. Stop any running watcher. Then report:

- A table of steps and what the database showed for each.
- Error count from the log.
- Loose ends the test left behind: test rows in `logs`, toggled preferences, expired goals. These live in the local database only. The user decides whether to clean them.
- Whether anything is committed. Do not commit unless asked.

## Discord facts that decide how commands behave

These were confirmed live, not from memory. Use them when a change involves message visibility.

- After `interaction.response.defer()`, the first `followup.send` replaces the "thinking" message and inherits the defer's visibility. The `ephemeral` flag on that first followup is ignored.
- Every followup after the first creates a new message, and `ephemeral=True` on it is honoured. This is why `/log` can send a public embed and then an ephemeral warning.
- Followups only work for 15 minutes after the interaction.
- A message's ephemeral state cannot be changed after it is sent.
