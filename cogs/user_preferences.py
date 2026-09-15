from datetime import datetime, timedelta, timezone

import discord

from discord.ext import commands
from lib.bot import JouzuBot

# Remind a user about /toggle_log_warning at most this often.
NUDGE_INTERVAL = timedelta(days=3)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

CREATE_USER_PREFERENCES_TABLE = """
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    log_warnings INTEGER NOT NULL DEFAULT 1,
    last_log_warning_at TIMESTAMP,
    last_nudge_at TIMESTAMP
);"""

GET_LOG_WARNINGS_QUERY = """
SELECT log_warnings
FROM user_preferences
WHERE user_id = ?;"""

# The flip happens inside the statement, so two concurrent toggles cannot read
# the same value and write the same result. Clearing last_log_warning_at and
# stamping last_nudge_at is not bookkeeping: using the toggle proves the user
# already knows the command, so the warning clock restarts and they count as
# nudged right now. Without it, turning warnings off and straight back on would
# tip them about the very command they just used.
TOGGLE_LOG_WARNINGS_QUERY = """
INSERT INTO user_preferences (user_id, log_warnings, last_log_warning_at, last_nudge_at)
VALUES (?, 0, NULL, ?)
ON CONFLICT(user_id) DO UPDATE SET
    log_warnings = 1 - user_preferences.log_warnings,
    last_log_warning_at = NULL,
    last_nudge_at = excluded.last_nudge_at;
"""

GET_WARNING_TIMESTAMPS_QUERY = """
SELECT last_log_warning_at, last_nudge_at
FROM user_preferences
WHERE user_id = ?;"""

# log_warnings is left out of the DO UPDATE so recording a warning never
# resets the user's own toggle. COALESCE keeps the old nudge time when we
# pass None, i.e. when this warning does not earn a nudge.
RECORD_LOG_WARNING_QUERY = """
INSERT INTO user_preferences (user_id, last_log_warning_at, last_nudge_at)
VALUES (?, ?, ?)
ON CONFLICT(user_id)
DO UPDATE SET
    last_log_warning_at = excluded.last_log_warning_at,
    last_nudge_at = COALESCE(excluded.last_nudge_at, user_preferences.last_nudge_at);
"""


def _parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


async def record_log_warning(
    bot: JouzuBot, user_id: int, now: datetime | None = None
) -> bool:
    """Record that a /log warning was just sent.

    Returns True when the user should also be nudged about /toggle_log_warning:
    this is at least the second warning inside NUDGE_INTERVAL, and we have not
    nudged them within NUDGE_INTERVAL.
    """
    if now is None:
        now = discord.utils.utcnow()

    row = await bot.GET_ONE(GET_WARNING_TIMESTAMPS_QUERY, (user_id,))
    last_warning = _parse_timestamp(row[0]) if row else None
    last_nudge = _parse_timestamp(row[1]) if row else None

    frequent = last_warning is not None and now - last_warning < NUDGE_INTERVAL
    due = last_nudge is None or now - last_nudge >= NUDGE_INTERVAL
    nudge = frequent and due

    now_text = now.strftime(TIMESTAMP_FORMAT)
    await bot.RUN(
        RECORD_LOG_WARNING_QUERY, (user_id, now_text, now_text if nudge else None)
    )
    return nudge


async def log_warnings_enabled(bot: JouzuBot, user_id: int) -> bool:
    """Missing row means the user never opted out, so warnings stay on."""
    row = await bot.GET_ONE(GET_LOG_WARNINGS_QUERY, (user_id,))
    if not row:
        return True
    return bool(row[0])


async def toggle_log_warnings(
    bot: JouzuBot, user_id: int, now: datetime | None = None
) -> bool:
    if now is None:
        now = discord.utils.utcnow()

    await bot.RUN(TOGGLE_LOG_WARNINGS_QUERY, (user_id, now.strftime(TIMESTAMP_FORMAT)))
    return await log_warnings_enabled(bot, user_id)


class UserPreferences(commands.Cog):
    def __init__(self, bot: JouzuBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_USER_PREFERENCES_TABLE)

    @discord.app_commands.command(
        name="toggle_log_warning",
        description="Turn the /log missing-field warnings on or off for yourself.",
    )
    async def toggle_log_warning(self, interaction: discord.Interaction):
        enabled = await toggle_log_warnings(self.bot, interaction.user.id)
        if enabled:
            message = "Log warnings are now **on**. You'll be warned when a `/log` is missing time or units."
        else:
            message = "Log warnings are now **off**. You won't be warned when a `/log` is missing time or units."

        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserPreferences(bot))
