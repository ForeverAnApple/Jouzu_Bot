import asyncio
import logging
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import aiohttp
import aiosqlite

from lib import anilist_autocomplete
from lib.anilist_autocomplete import (
    BACKFILL_CHUNK_DELAY_SECONDS,
    BACKFILL_MAX_RATE_LIMIT_RETRIES,
    BACKFILL_RETRY_SECONDS,
    CACHED_ANILIST_RESULTS_INSERT_QUERY,
    anime_manga_name_autocomplete,
    backfill_anilist_formats,
    ensure_anilist_schema,
    format_label,
    query_anilist,
)

LOGGER = "lib.anilist_autocomplete"

OLD_CACHE_TABLE = """
CREATE TABLE cached_anilist_results (
    primary_key INTEGER PRIMARY KEY AUTOINCREMENT,
    anilist_id INTEGER UNIQUE,
    title_english TEXT,
    title_native TEXT,
    cover_image_url TEXT,
    media_type TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


class FakeBot:
    """Stands in for JouzuBot: same aiosqlite helpers, no discord client."""

    def __init__(self, path_to_db):
        self.path_to_db = path_to_db

    async def RUN(self, query: str, params: tuple = ()):
        async with aiosqlite.connect(self.path_to_db) as db:
            await db.execute(query, params)
            await db.commit()

    async def GET(self, query: str, params: tuple = ()):
        async with aiosqlite.connect(self.path_to_db) as db:
            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()

    async def GET_ONE(self, query: str, params: tuple = ()):
        async with aiosqlite.connect(self.path_to_db) as db:
            async with db.execute(query, params) as cursor:
                return await cursor.fetchone()


class FakeInteraction:
    def __init__(self, bot, media_type="Reading"):
        self.namespace = {"media_type": media_type}
        self.client = bot


def media(media_id, media_format, title="My Happy Marriage"):
    return {
        "id": media_id,
        "format": media_format,
        "title": {"english": title, "romaji": title, "native": "わたしの幸せな結婚"},
        "coverImage": {"medium": f"https://example.invalid/{media_id}.jpg"},
    }


class AniListTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        os.remove(self.db_path)
        self.bot = FakeBot(self.db_path)
        self.interaction = FakeInteraction(self.bot)

        # Tests assert on logs explicitly; a handler keeps the rest off stderr.
        logger = logging.getLogger(LOGGER)
        handler = logging.NullHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def columns(self):
        with sqlite3.connect(self.db_path) as db:
            return [row[1] for row in db.execute("PRAGMA table_info(cached_anilist_results);")]

    def rows(self):
        with sqlite3.connect(self.db_path) as db:
            return db.execute(
                "SELECT anilist_id, media_format FROM cached_anilist_results ORDER BY anilist_id;"
            ).fetchall()


class TestEnsureAnilistSchema(AniListTestCase):
    async def test_fresh_database_has_format_column(self):
        await ensure_anilist_schema(self.bot)
        self.assertIn("media_format", self.columns())

    async def test_migrates_old_schema(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute(OLD_CACHE_TABLE)
        self.assertNotIn("media_format", self.columns())

        await ensure_anilist_schema(self.bot)
        self.assertIn("media_format", self.columns())

    async def test_is_idempotent(self):
        await ensure_anilist_schema(self.bot)
        await ensure_anilist_schema(self.bot)
        self.assertEqual(self.columns().count("media_format"), 1)


class TestQueryAnilist(AniListTestCase):
    async def asyncSetUp(self):
        await ensure_anilist_schema(self.bot)

    async def test_stores_media_format(self):
        post = mock.AsyncMock(
            return_value=(
                200,
                {"data": {"Page": {"media": [media(1, "MANGA"), media(2, "NOVEL")]}}},
                None,
            )
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(self.rows(), [(1, "MANGA"), (2, "NOVEL")])
        self.assertEqual(
            [choice.name for choice in choices],
            [
                "[Manga] My Happy Marriage (ID: 1) (API)",
                "[Light Novel] My Happy Marriage (ID: 2) (API)",
            ],
        )

    async def test_null_data_with_errors(self):
        post = mock.AsyncMock(
            return_value=(200, {"data": None, "errors": [{"message": "boom"}]}, None)
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(choices, [])
        self.assertIn("boom", logs.output[0])

    async def test_rate_limited(self):
        post = mock.AsyncMock(return_value=(429, None, 30))
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(choices, [])
        self.assertIn("rate limited", logs.output[0])
        self.assertIn("30", logs.output[0])

    async def test_logs_api_error_body(self):
        """A 403 outage must name itself in the logs, not vanish into an empty list."""
        post = mock.AsyncMock(
            return_value=(
                403,
                {"errors": [{"message": "The AniList API has been temporarily disabled"}]},
                None,
            )
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(choices, [])
        self.assertIn("HTTP 403", logs.output[0])
        self.assertIn("The AniList API has been temporarily disabled", logs.output[0])

    async def test_success_logs_no_warning(self):
        post = mock.AsyncMock(
            return_value=(200, {"data": {"Page": {"media": [media(1, "MANGA")]}}}, None)
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            with self.assertNoLogs(LOGGER, level="WARNING"):
                choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(len(choices), 1)


class TestFormatLabel(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(format_label("ONE_SHOT"), "One-shot")
        self.assertEqual(format_label("NOVEL"), "Light Novel")

    def test_missing_format(self):
        self.assertIsNone(format_label(None))

    def test_unknown_enum_member(self):
        self.assertEqual(format_label("WEIRD_NEW"), "Weird New")


class TestCachedChoices(AniListTestCase):
    async def asyncSetUp(self):
        await ensure_anilist_schema(self.bot)
        post = mock.AsyncMock(
            return_value=(
                200,
                {"data": {"Page": {"media": [media(1, "MANGA"), media(2, "NOVEL")]}}},
                None,
            )
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            await query_anilist(self.interaction, "Happy", self.bot)

    async def test_search_uses_cache_and_labels(self):
        post = mock.AsyncMock()
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            choices = await anime_manga_name_autocomplete(self.interaction, "Happy")

        post.assert_not_called()
        self.assertEqual(
            [choice.name for choice in choices],
            [
                "[Manga] My Happy Marriage (ID: 1) (Cached)",
                "[Light Novel] My Happy Marriage (ID: 2) (Cached)",
            ],
        )

    async def test_by_id_labels(self):
        post = mock.AsyncMock()
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            choices = await anime_manga_name_autocomplete(self.interaction, "2")

        post.assert_not_called()
        self.assertEqual(
            [choice.name for choice in choices],
            ["[Light Novel] My Happy Marriage (ID: 2) (Cached)"],
        )

    async def test_null_format_has_no_prefix(self):
        await self.bot.RUN(
            "UPDATE cached_anilist_results SET media_format = NULL WHERE anilist_id = 1;"
        )
        choices = await anime_manga_name_autocomplete(self.interaction, "1")
        self.assertEqual(
            [choice.name for choice in choices],
            ["My Happy Marriage (ID: 1) (Cached)"],
        )


class TestBackfillAnilistFormats(AniListTestCase):
    async def asyncSetUp(self):
        await ensure_anilist_schema(self.bot)
        for anilist_id in (1, 2, 3):
            await self.bot.RUN(
                CACHED_ANILIST_RESULTS_INSERT_QUERY,
                (anilist_id, "My Happy Marriage", None, None, "MANGA", None),
            )

    async def test_updates_returned_ids_only(self):
        post = mock.AsyncMock(
            return_value=(
                200,
                {
                    "data": {
                        "Page": {
                            "media": [
                                {"id": 1, "format": "MANGA"},
                                {"id": 2, "format": "NOVEL"},
                            ]
                        }
                    }
                },
                None,
            )
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            await backfill_anilist_formats(self.bot)

        self.assertEqual(self.rows(), [(1, "MANGA"), (2, "NOVEL"), (3, None)])
        payload = post.await_args.args[0]
        self.assertEqual(sorted(payload["variables"]["ids"]), [1, 2, 3])

    async def run_backfill(self, post, sleep):
        """Run the backfill with the network and the retry delay stubbed out."""
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post), mock.patch(
            "lib.anilist_autocomplete.asyncio.sleep", sleep
        ):
            await backfill_anilist_formats(self.bot)

    @staticmethod
    def slept(sleep):
        """Every delay the backfill waited on, in order."""
        return [call.args[0] for call in sleep.await_args_list]

    async def seed_rows(self, anilist_ids):
        for anilist_id in anilist_ids:
            await self.bot.RUN(
                CACHED_ANILIST_RESULTS_INSERT_QUERY,
                (anilist_id, "My Happy Marriage", None, None, "MANGA", None),
            )

    async def test_persistent_api_failure_changes_nothing(self):
        post = mock.AsyncMock(return_value=(403, None, None))
        # A cancelled sleep stands in for shutdown; without it the retry loop never ends.
        sleep = mock.AsyncMock(side_effect=asyncio.CancelledError)

        with self.assertRaises(asyncio.CancelledError):
            await self.run_backfill(post, sleep)

        self.assertEqual(self.rows(), [(1, None), (2, None), (3, None)])
        post.assert_awaited_once()
        sleep.assert_awaited_once_with(BACKFILL_RETRY_SECONDS)

    async def test_retries_after_http_failure(self):
        post = mock.AsyncMock(
            side_effect=[
                (403, None, None),
                (
                    200,
                    {"data": {"Page": {"media": [{"id": 1, "format": "MANGA"}]}}},
                    None,
                ),
            ]
        )
        sleep = mock.AsyncMock()

        await self.run_backfill(post, sleep)

        self.assertEqual(self.rows(), [(1, "MANGA"), (2, None), (3, None)])
        sleep.assert_awaited_once_with(BACKFILL_RETRY_SECONDS)

    async def test_retries_after_client_error(self):
        post = mock.AsyncMock(
            side_effect=[
                aiohttp.ClientError("connection reset"),
                (
                    200,
                    {"data": {"Page": {"media": [{"id": 2, "format": "NOVEL"}]}}},
                    None,
                ),
            ]
        )
        sleep = mock.AsyncMock()

        await self.run_backfill(post, sleep)

        self.assertEqual(self.rows(), [(1, None), (2, "NOVEL"), (3, None)])
        sleep.assert_awaited_once_with(BACKFILL_RETRY_SECONDS)

    async def test_logs_failure_and_retry_delay(self):
        post = mock.AsyncMock(
            return_value=(
                403,
                {"errors": [{"message": "The AniList API has been temporarily disabled"}]},
                None,
            )
        )
        sleep = mock.AsyncMock(side_effect=asyncio.CancelledError)

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            with self.assertRaises(asyncio.CancelledError):
                await self.run_backfill(post, sleep)

        warning = logs.output[0]
        self.assertIn("HTTP 403", warning)
        self.assertIn("The AniList API has been temporarily disabled", warning)
        self.assertIn("retrying in 60 minutes", warning)

    async def test_logs_completion(self):
        post = mock.AsyncMock(
            return_value=(
                200,
                {"data": {"Page": {"media": [{"id": 1, "format": "MANGA"}]}}},
                None,
            )
        )
        sleep = mock.AsyncMock()

        with self.assertLogs(LOGGER, level="INFO") as logs:
            await self.run_backfill(post, sleep)

        self.assertTrue(
            any(
                "backfill complete; 1 row(s) updated, 2 left" in line
                for line in logs.output
            ),
            logs.output,
        )

    async def test_does_not_retry_when_anilist_has_no_format(self):
        post = mock.AsyncMock(
            return_value=(
                200,
                {
                    "data": {
                        "Page": {
                            "media": [
                                {"id": 1, "format": "MANGA"},
                                {"id": 2, "format": "NOVEL"},
                                {"id": 3, "format": None},
                            ]
                        }
                    }
                },
                None,
            )
        )
        sleep = mock.AsyncMock()

        await self.run_backfill(post, sleep)

        self.assertEqual(self.rows(), [(1, "MANGA"), (2, "NOVEL"), (3, None)])
        post.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_rate_limit_pauses_and_retries_same_chunk(self):
        """A 429 is a pause, not a failure: same chunk again after Retry-After."""
        post = mock.AsyncMock(
            side_effect=[
                (429, {"errors": [{"message": "Too Many Requests."}]}, 7),
                (
                    200,
                    {"data": {"Page": {"media": [{"id": 1, "format": "MANGA"}]}}},
                    None,
                ),
            ]
        )
        sleep = mock.AsyncMock()

        await self.run_backfill(post, sleep)

        self.assertEqual(self.rows(), [(1, "MANGA"), (2, None), (3, None)])
        self.assertEqual(post.await_count, 2)
        first, second = post.await_args_list
        self.assertEqual(
            first.args[0]["variables"]["ids"], second.args[0]["variables"]["ids"]
        )
        self.assertEqual(self.slept(sleep), [7])

    async def test_rate_limit_without_retry_after_pauses_a_minute(self):
        post = mock.AsyncMock(
            side_effect=[
                (429, {"errors": [{"message": "Too Many Requests."}]}, None),
                (
                    200,
                    {"data": {"Page": {"media": [{"id": 1, "format": "MANGA"}]}}},
                    None,
                ),
            ]
        )
        sleep = mock.AsyncMock()

        await self.run_backfill(post, sleep)

        self.assertEqual(self.slept(sleep), [60])

    async def test_paces_between_chunks(self):
        await self.seed_rows(range(4, 61))

        def respond(payload):
            ids = payload["variables"]["ids"]
            media_list = [{"id": anilist_id, "format": "MANGA"} for anilist_id in ids]
            return 200, {"data": {"Page": {"media": media_list}}}, None

        post = mock.AsyncMock(side_effect=respond)
        sleep = mock.AsyncMock()

        await self.run_backfill(post, sleep)

        self.assertEqual(post.await_count, 2)
        self.assertEqual([len(call.args[0]["variables"]["ids"]) for call in post.await_args_list], [50, 10])
        # One delay between the two chunks, none after the last.
        self.assertEqual(self.slept(sleep), [BACKFILL_CHUNK_DELAY_SECONDS])

    async def test_gives_up_after_repeated_rate_limits(self):
        post = mock.AsyncMock(
            return_value=(429, {"errors": [{"message": "Too Many Requests."}]}, 1)
        )

        def wait(seconds):
            # Only the hourly retry stands in for shutdown; the pauses must go through.
            if seconds == BACKFILL_RETRY_SECONDS:
                raise asyncio.CancelledError

        sleep = mock.AsyncMock(side_effect=wait)

        with self.assertLogs(LOGGER, level="WARNING") as logs:
            with self.assertRaises(asyncio.CancelledError):
                await self.run_backfill(post, sleep)

        self.assertEqual(post.await_count, BACKFILL_MAX_RATE_LIMIT_RETRIES + 1)
        self.assertEqual(
            self.slept(sleep),
            [1] * BACKFILL_MAX_RATE_LIMIT_RETRIES + [BACKFILL_RETRY_SECONDS],
        )
        self.assertEqual(self.rows(), [(1, None), (2, None), (3, None)])
        warning = logs.output[0]
        self.assertIn("HTTP 429", warning)
        self.assertIn("retrying in 60 minutes", warning)


if __name__ == "__main__":
    unittest.main()
