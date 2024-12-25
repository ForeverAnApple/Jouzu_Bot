import asyncio
from lib.bot import JouzuBot
import discord
from discord.ext import commands

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    discord_user_id INTEGER,
    guild_id INTEGER,
    nick_name TEXT,
    user_name TEXT,
    PRIMARY KEY (discord_user_id, guild_id)
);"""

UPDATE_USERNAME_QUERY = """
UPDATE users
SET user_name = ?
WHERE discord_user_id = ? and guild_id = ?;"""

INSERT_USER_QUERY = """
INSERT INTO users (discord_user_id, guild_id, nick_name, user_name)
VALUES (?, ?, ?, ?) 
ON CONFLICT(discord_user_id, guild_id) 
DO UPDATE SET 
    user_name = excluded.user_name,
    nick_name = excluded.nick_name;
"""

FETCH_USER_QUERY = """
SELECT nick_name, user_name
FROM users
WHERE discord_user_id = ?, guild_id = ?;"""

FETCH_LOCK = asyncio.Lock()


async def get_username_db(bot: JouzuBot, guild_id: int, user: discord.User) -> (str, str):
    if user:
        await bot.RUN(INSERT_USER_QUERY, (user.id, guild_id, user.nick, user.display_name))
        return (user.nick, user.display_name)
    user_name = await bot.GET_ONE(FETCH_USER_QUERY, (user_id, guild_id))
    if user_name:
        return (user_name[0], user_name[1])
    async with FETCH_LOCK:
        await asyncio.sleep(1)
        user = await bot.fetch_user(user_id)
        if user:
            await bot.RUN(INSERT_USER_QUERY, (user.id, guild_id, user.nick, user.display_name))
            return (user.nick, user.display_name)
        else:
            return 'Unknown User'


class UsernameFetcher(commands.Cog):
    def __init__(self, bot: JouzuBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_USERS_TABLE)


async def setup(bot):
    await bot.add_cog(UsernameFetcher(bot))
