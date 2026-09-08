import aiohttp
import discord

from lib.autocomplete_helpers import build_choice_name
from lib.bot import JouzuBot

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


async def _post_anilist(payload: dict) -> tuple[int, dict | None, int | None]:
    """POST to AniList; returns (status, json body or None, Retry-After seconds or None)."""
    async with aiohttp.ClientSession() as session:
        async with session.post(ANILIST_API_URL, json=payload) as response:
            if response.status == 200:
                return response.status, await response.json(), None
            retry_after = response.headers.get("Retry-After")
            return (
                response.status,
                None,
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
        print(
            f"API rate limit exceeded. Please wait {retry_after or 60} seconds before retrying."
        )
        return []
    if status != 200 or not data:
        return []

    # AniList can answer 200 with {"data": null, "errors": [...]}.
    payload_data = data.get("data") or {}
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

    return choices[:10]


async def backfill_anilist_formats(bot: JouzuBot):
    """Fill media_format for rows cached before the column existed; cache hits never re-query."""
    rows = await bot.GET(ANILIST_MISSING_FORMAT_IDS_QUERY)
    ids = [row[0] for row in rows]

    for start in range(0, len(ids), BACKFILL_CHUNK_SIZE):
        chunk = ids[start : start + BACKFILL_CHUNK_SIZE]
        try:
            status, data, _ = await _post_anilist(
                {"query": ANILIST_FORMAT_BACKFILL_QUERY, "variables": {"ids": chunk}}
            )
        except (aiohttp.ClientError, TimeoutError) as error:
            print(f"AniList format backfill stopped: {error}.")
            return
        if status != 200 or not data:
            print(f"AniList format backfill stopped: HTTP {status}.")
            return

        media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
        for media in media_list:
            media_id = media.get("id")
            media_format = media.get("format")
            if media_id and media_format:
                await bot.RUN(ANILIST_SET_FORMAT_QUERY, (media_format, media_id))


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
