import discord
import os
import asyncio
import argparse
from dotenv import load_dotenv

from discord.ext import commands
from lib.bot import JouzuBot

load_dotenv()

COMMAND_PREFIX = os.getenv("COMMAND_PREFIX")
TOKEN = os.getenv("TOKEN")
PATH_TO_DB = os.getenv("PATH_TO_DB")
COG_FOLDER = "cogs"
my_bot = JouzuBot(command_prefix=COMMAND_PREFIX, cog_folder=COG_FOLDER, path_to_db=PATH_TO_DB)


async def main(cogs_to_load):
    discord.utils.setup_logging()
    await my_bot.load_cogs(cogs_to_load)
    await my_bot.start(TOKEN)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jouzu Gumi Discord Bot")
    parser.add_argument("cogs", nargs="*", help="List of cogs to load, without the .py extension")
    args = parser.parse_args()

    cogs_to_load = args.cogs if args.cogs else "*"

    asyncio.run(main(cogs_to_load))
