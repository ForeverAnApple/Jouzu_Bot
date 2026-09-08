import asyncio
import logging

import aiohttp
import discord

from lib.autocomplete_helpers import build_choice_name
from lib.bot import JouzuBot

_log = logging.getLogger(__name__)

ANILIST_API_URL = "https://graphql.anilist.co"

ANILIST_NAME_QUERY = """
query ($search: String, $type: MediaType) {
  Page(perPage: 10) {
    media(search: $search, type: $type) {
      id
      format
      title {
        english
        romaji
        native
      }
      coverImage {
        medium
      }
    }
  }
}"""

ANILIST_ID_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    id
    format
    title {
      english
      romaji
      native
    }
    coverImage {
      medium
    }
  }
}"""

CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS cached_anilist_results (
    primary_key INTEGER PRIMARY KEY AUTOINCREMENT,
    anilist_id INTEGER UNIQUE,
    title_english TEXT,
    title_native TEXT,
    cover_image_url TEXT,
    media_type TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    media_format TEXT
);
"""

CREATE_ANILIST_FTS5_TABLE_QUERY = """
CREATE VIRTUAL TABLE IF NOT EXISTS anilist_fts USING fts5(
    anilist_id UNINDEXED,
    title_english,
    title_native,
    cover_image_url UNINDEXED,
    media_type UNINDEXED,
    content='cached_anilist_results',
    tokenize = 'porter'
);
"""

CREATE_ANILIST_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS anilist_fts_insert AFTER INSERT ON cached_anilist_results
BEGIN
  INSERT INTO anilist_fts(rowid, anilist_id, title_english, title_native, media_type)
  VALUES (new.rowid, new.anilist_id, new.title_english, new.title_native, new.media_type);
END;
"""

CREATE_ANILIST_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS anilist_fts_update AFTER UPDATE ON cached_anilist_results
BEGIN
  UPDATE anilist_fts SET 
    title_english = new.title_english,
    title_native = new.title_native,
    media_type = new.media_type
  WHERE rowid = old.rowid;
END;
"""

CREATE_ANILIST_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS anilist_fts_delete AFTER DELETE ON cached_anilist_results
BEGIN
  DELETE FROM anilist_fts WHERE rowid = old.rowid;
END;
"""

CACHED_ANILIST_RESULTS_INSERT_QUERY = """
INSERT INTO cached_anilist_results (anilist_id, title_english, title_native, cover_image_url, media_type, media_format) 
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(anilist_id) DO UPDATE SET 
    title_english=excluded.title_english,
    title_native=excluded.title_native,
    cover_image_url=excluded.cover_image_url,
    media_type=excluded.media_type,
    media_format=excluded.media_format,
    timestamp=CURRENT_TIMESTAMP;
"""

# Reads the base table, not anilist_fts: the FTS table lacks media_format and this LIKE search never used FTS anyway.
CACHED_ANILIST_RESULTS_SEARCH_QUERY = """
SELECT anilist_id, title_english, title_native, media_format 
FROM cached_anilist_results 
WHERE (title_english LIKE '%' || ? || '%' OR title_native LIKE '%' || ? || '%')
AND media_type = ? 
LIMIT 10;
"""

CACHED_ANILIST_RESULTS_BY_ID_QUERY = """
SELECT anilist_id, title_english, title_native, media_format FROM cached_anilist_results 
WHERE anilist_id = ? AND media_type = ?;
"""

CACHED_ANILIST_THUMBNAIL_QUERY = """
SELECT cover_image_url FROM cached_anilist_results
WHERE anilist_id = ?;
"""

CACHED_ANILIST_TITLE_QUERY = """
SELECT COALESCE(title_english, title_native) AS title 
FROM cached_anilist_results 
WHERE anilist_id = ?;
"""

ANILIST_ADD_FORMAT_COLUMN_QUERY = (
    "ALTER TABLE cached_anilist_results ADD COLUMN media_format TEXT;"
)

ANILIST_TABLE_INFO_QUERY = "PRAGMA table_info(cached_anilist_results);"

ANILIST_FORMAT_BACKFILL_QUERY = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids) {
      id
      format
    }
  }
}"""

ANILIST_MISSING_FORMAT_IDS_QUERY = """
SELECT anilist_id FROM cached_anilist_results
WHERE media_format IS NULL AND anilist_id IS NOT NULL;
"""

ANILIST_SET_FORMAT_QUERY = """
UPDATE cached_anilist_results SET media_format = ? WHERE anilist_id = ?;
"""

BACKFILL_CHUNK_SIZE = 50
BACKFILL_RETRY_SECONDS = 3600

# AniList MediaFormat enum -> label shown before the title in autocomplete.
FORMAT_LABELS = {
    "MANGA": "Manga",
    "NOVEL": "Light Novel",
    "ONE_SHOT": "One-shot",
    "TV": "TV",
    "TV_SHORT": "TV Short",
    "MOVIE": "Movie",
    "SPECIAL": "Special",
    "OVA": "OVA",
    "ONA": "ONA",
    "MUSIC": "Music",
}


def format_label(media_format):
    """Label for a MediaFormat value; unknown enum members degrade to a readable form."""
    if not media_format:
        return None
    return FORMAT_LABELS.get(media_format) or media_format.replace("_", " ").title()


async def ensure_anilist_schema(bot: JouzuBot):
    """Create the AniList cache tables and add media_format to databases predating it."""
    await bot.RUN(CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY)
    await bot.RUN(CREATE_ANILIST_FTS5_TABLE_QUERY)
    await bot.RUN(CREATE_ANILIST_TRIGGER_INSERT)
    await bot.RUN(CREATE_ANILIST_TRIGGER_UPDATE)
    await bot.RUN(CREATE_ANILIST_TRIGGER_DELETE)

    columns = await bot.GET(ANILIST_TABLE_INFO_QUERY)
    if not any(column[1] == "media_format" for column in columns):
        await bot.RUN(ANILIST_ADD_FORMAT_COLUMN_QUERY)
        _log.info("Added media_format column to cached_anilist_results")


def _anilist_error_message(data) -> str:
    """First message out of an AniList {"errors": [...]} body, or an empty string."""
    errors = (data or {}).get("errors") or []
    if errors and isinstance(errors[0], dict):
        return errors[0].get("message") or ""
    return ""


async def _post_anilist(payload: dict) -> tuple[int, dict | None, int | None]:
    """POST to AniList; returns (status, json body or None, Retry-After seconds or None).

    The body is parsed on failures too: AniList explains itself in "errors" even on 403,
    and callers log that. Success is therefore status == 200, not a truthy body.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(ANILIST_API_URL, json=payload) as response:
            try:
                data = await response.json(content_type=None)
            except (aiohttp.ClientError, ValueError):
                data = None
            if response.status == 200:
                return response.status, data, None
            retry_after = response.headers.get("Retry-After")
            return (
                response.status,
                data,
                int(retry_after) if retry_after else None,
            )


async def query_anilist(
    interaction: discord.Interaction, current_input: str, bot: JouzuBot
):
    media_type = interaction.namespace["media_type"]
    media_type = (
        "MANGA"
        if media_type == "Reading" or media_type == "Reading Time"
        else media_type.upper()
    )
    if current_input.isdigit():
        query = ANILIST_ID_QUERY
        variables = {"id": int(current_input)}
    else:
        query = ANILIST_NAME_QUERY
        variables = {"search": current_input, "type": media_type}

    status, data, retry_after = await _post_anilist(
        {"query": query, "variables": variables}
    )
    if status == 429:
        _log.warning("AniList rate limited; retry after %ss", retry_after or 60)
        return []
    if status != 200:
        _log.warning(
            "AniList query failed: HTTP %s %s", status, _anilist_error_message(data)
        )
        return []

    # AniList can answer 200 with {"data": null, "errors": [...]}.
    payload_data = (data or {}).get("data") or {}
    if not payload_data:
        _log.warning(
            "AniList returned no data for %r: %s",
            current_input,
            _anilist_error_message(data) or "empty response",
        )
        return []
    if current_input.isdigit():
        media_list = [payload_data.get("Media") or {}]
    else:
        media_list = (payload_data.get("Page") or {}).get("media") or []

    choices = []
    for media in media_list:
        media_id = media.get("id")
        title_english = media.get("title", {}).get("english") or media.get(
            "title", {}
        ).get("romaji")
        title_native = media.get("title", {}).get("native")
        cover_image_url = media.get("coverImage", {}).get("medium")
        media_format = media.get("format")
        title = title_english or title_native
        if not title or not media_id:
            continue

        choice_name = build_choice_name(
            title, media_id, "API", label=format_label(media_format)
        )
        choices.append(
            discord.app_commands.Choice(name=choice_name, value=str(media_id))
        )

        await bot.RUN(
            CACHED_ANILIST_RESULTS_INSERT_QUERY,
            (
                media_id,
                title_english,
                title_native,
                cover_image_url,
                media_type,
                media_format,
            ),
        )

    _log.debug(
        "AniList returned %d result(s) for %r (%s)",
        len(choices),
        current_input,
        media_type,
    )
    return choices[:10]


async def backfill_anilist_formats(bot: JouzuBot):
    """Fill media_format for rows cached before the column existed; cache hits never re-query."""
    # AniList outages last hours, so a deploy during one must self-heal instead of leaving
    # every cached row unlabelled until somebody notices and restarts the bot.
    while True:
        rows = await bot.GET(ANILIST_MISSING_FORMAT_IDS_QUERY)
        ids = [row[0] for row in rows]
        if not ids:
            return
        _log.info("AniList format backfill: %d row(s) missing format", len(ids))

        failure = None
        updated = 0
        for start in range(0, len(ids), BACKFILL_CHUNK_SIZE):
            chunk = ids[start : start + BACKFILL_CHUNK_SIZE]
            try:
                status, data, _ = await _post_anilist(
                    {"query": ANILIST_FORMAT_BACKFILL_QUERY, "variables": {"ids": chunk}}
                )
            except (aiohttp.ClientError, TimeoutError) as error:
                failure = str(error) or type(error).__name__
                break
            if status != 200 or data is None:
                message = _anilist_error_message(data)
                failure = f"HTTP {status}: {message}" if message else f"HTTP {status}"
                break

            media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
            chunk_updated = 0
            for media in media_list:
                media_id = media.get("id")
                media_format = media.get("format")
                if media_id and media_format:
                    await bot.RUN(ANILIST_SET_FORMAT_QUERY, (media_format, media_id))
                    chunk_updated += 1
            updated += chunk_updated
            _log.debug(
                "AniList format backfill: %d of %d row(s) updated in this chunk",
                chunk_updated,
                len(chunk),
            )

        # Rows still NULL after a clean pass have no format on AniList either.
        if failure is None:
            _log.info(
                "AniList format backfill complete; %d row(s) updated, "
                "%d left without a format on AniList",
                updated,
                len(ids) - updated,
            )
            return

        _log.warning(
            "AniList format backfill failed (%s); retrying in %d minutes",
            failure,
            BACKFILL_RETRY_SECONDS // 60,
        )
        await asyncio.sleep(BACKFILL_RETRY_SECONDS)


async def anime_manga_name_autocomplete(
    interaction: discord.Interaction, current_input: str
):
    jouzu_bot = interaction.client
    jouzu_bot: JouzuBot

    media_type = interaction.namespace["media_type"]
    media_type = (
        "MANGA"
        if media_type == "Reading" or media_type == "Reading Time"
        else media_type.upper()
    )

    if current_input.isdigit():
        cached_result = await jouzu_bot.GET_ONE(
            CACHED_ANILIST_RESULTS_BY_ID_QUERY, (int(current_input), media_type)
        )
        if cached_result:
            anilist_id, title_english, title_native, media_format = cached_result
            title = title_english or title_native
            if title:
                choice_name = build_choice_name(
                    title, anilist_id, "Cached", label=format_label(media_format)
                )
                return [
                    discord.app_commands.Choice(name=choice_name, value=str(anilist_id))
                ]
        else:
            return await query_anilist(interaction, current_input, jouzu_bot)
    else:
        cached_results = await jouzu_bot.GET(
            CACHED_ANILIST_RESULTS_SEARCH_QUERY,
            (current_input, current_input, media_type),
        )
        choices = []
        for cached_result in cached_results:
            anilist_id, title_english, title_native, media_format = cached_result
            title = title_english or title_native
            if title:
                choice_name = build_choice_name(
                    title, anilist_id, "Cached", label=format_label(media_format)
                )
                choices.append(
                    discord.app_commands.Choice(name=choice_name, value=str(anilist_id))
                )

        if len(choices) < 1:
            anilist_choices = await query_anilist(interaction, current_input, jouzu_bot)
            choices.extend(anilist_choices)

        return choices[:10]
