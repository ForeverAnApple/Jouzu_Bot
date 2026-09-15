import asyncio
import os
import tempfile
import unittest

from datetime import datetime, timedelta, timezone

from cogs.user_preferences import (
    CREATE_USER_PREFERENCES_TABLE,
    NUDGE_INTERVAL,
    log_warnings_enabled,
    record_log_warning,
    toggle_log_warnings,
)
from lib.bot import JouzuBot

USER_A = 1111
USER_B = 2222

BASE_TIME = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


class TestUserPreferences(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.bot = JouzuBot(
            command_prefix="%",
            path_to_db=os.path.join(self._tmpdir.name, "db.sqlite3"),
        )
        await self.bot.RUN(CREATE_USER_PREFERENCES_TABLE)

    async def test_default_is_enabled(self):
        self.assertTrue(await log_warnings_enabled(self.bot, USER_A))

    async def test_toggle_turns_warnings_off_then_back_on(self):
        self.assertFalse(await toggle_log_warnings(self.bot, USER_A))
        self.assertFalse(await log_warnings_enabled(self.bot, USER_A))

        self.assertTrue(await toggle_log_warnings(self.bot, USER_A))
        self.assertTrue(await log_warnings_enabled(self.bot, USER_A))

    async def test_toggle_only_affects_one_user(self):
        await toggle_log_warnings(self.bot, USER_A)

        self.assertFalse(await log_warnings_enabled(self.bot, USER_A))
        self.assertTrue(await log_warnings_enabled(self.bot, USER_B))

    async def test_first_warning_never_nudges(self):
        self.assertFalse(await record_log_warning(self.bot, USER_A, BASE_TIME))

    async def test_second_warning_within_interval_nudges(self):
        await record_log_warning(self.bot, USER_A, BASE_TIME)

        self.assertTrue(
            await record_log_warning(self.bot, USER_A, BASE_TIME + timedelta(hours=1))
        )

    async def test_no_second_nudge_before_interval_elapses(self):
        await record_log_warning(self.bot, USER_A, BASE_TIME)
        await record_log_warning(self.bot, USER_A, BASE_TIME + timedelta(hours=1))

        # Nudged one day ago, so this frequent warning stays quiet.
        self.assertFalse(
            await record_log_warning(
                self.bot, USER_A, BASE_TIME + timedelta(days=1, hours=1)
            )
        )

    async def test_nudges_again_once_interval_elapses(self):
        await record_log_warning(self.bot, USER_A, BASE_TIME)
        nudged_at = BASE_TIME + timedelta(hours=1)
        await record_log_warning(self.bot, USER_A, nudged_at)

        # Previous warning one day before the next one keeps it "frequent".
        await record_log_warning(self.bot, USER_A, nudged_at + timedelta(days=2))

        self.assertTrue(
            await record_log_warning(self.bot, USER_A, nudged_at + timedelta(days=3))
        )

    async def test_rare_warnings_never_nudge(self):
        self.assertFalse(await record_log_warning(self.bot, USER_A, BASE_TIME))
        self.assertFalse(
            await record_log_warning(self.bot, USER_A, BASE_TIME + timedelta(days=4))
        )

    async def test_recording_does_not_clobber_toggle(self):
        await toggle_log_warnings(self.bot, USER_A, BASE_TIME)

        await record_log_warning(self.bot, USER_A, BASE_TIME)
        await record_log_warning(self.bot, USER_A, BASE_TIME + timedelta(hours=1))
        await record_log_warning(self.bot, USER_B, BASE_TIME)

        self.assertFalse(await log_warnings_enabled(self.bot, USER_A))
        self.assertTrue(await log_warnings_enabled(self.bot, USER_B))

    async def test_toggle_resets_nudge_state(self):
        await record_log_warning(self.bot, USER_A, BASE_TIME)
        self.assertTrue(
            await record_log_warning(self.bot, USER_A, BASE_TIME + timedelta(hours=1))
        )

        await toggle_log_warnings(self.bot, USER_A, BASE_TIME + timedelta(hours=2))
        await toggle_log_warnings(self.bot, USER_A, BASE_TIME + timedelta(hours=3))

        # The toggle cleared the warning clock, so this warning is a first one.
        self.assertFalse(
            await record_log_warning(self.bot, USER_A, BASE_TIME + timedelta(hours=4))
        )
        # Frequent now, but the toggle counted as a nudge one hour ago.
        self.assertFalse(
            await record_log_warning(
                self.bot, USER_A, BASE_TIME + timedelta(hours=4, minutes=1)
            )
        )

        due_at = BASE_TIME + timedelta(hours=3) + NUDGE_INTERVAL + timedelta(minutes=1)
        await record_log_warning(self.bot, USER_A, due_at - timedelta(hours=1))

        self.assertTrue(await record_log_warning(self.bot, USER_A, due_at))

    async def test_toggle_is_atomic_flip(self):
        results = await asyncio.gather(
            toggle_log_warnings(self.bot, USER_A, BASE_TIME),
            toggle_log_warnings(self.bot, USER_A, BASE_TIME),
        )

        # Two flips from the default cancel out. The return values are
        # read-backs, so both may report the final state; only the stored state
        # is guaranteed.
        self.assertTrue(await log_warnings_enabled(self.bot, USER_A))
        self.assertTrue(all(isinstance(result, bool) for result in results))
        self.assertTrue(any(results))


if __name__ == "__main__":
    unittest.main()
