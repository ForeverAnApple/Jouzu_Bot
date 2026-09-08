import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import aiosqlite

from lib import anilist_autocomplete
from lib.anilist_autocomplete import ensure_anilist_schema, query_anilist

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

        self.assertEqual(len(choices), 2)
        self.assertEqual(self.rows(), [(1, "MANGA"), (2, "NOVEL")])

    async def test_null_data_with_errors(self):
        post = mock.AsyncMock(
            return_value=(200, {"data": None, "errors": [{"message": "boom"}]}, None)
        )
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post):
            choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(choices, [])

    async def test_rate_limited(self):
        post = mock.AsyncMock(return_value=(429, None, 30))
        with mock.patch.object(anilist_autocomplete, "_post_anilist", post), mock.patch(
            "builtins.print"
        ):
            choices = await query_anilist(self.interaction, "Happy", self.bot)

        self.assertEqual(choices, [])


if __name__ == "__main__":
    unittest.main()
