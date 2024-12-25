from lib.bot import JouzuBot
import discord
import os
from discord.ext import commands

AUTHORIZED_USER_IDS = [int(id) for id in os.getenv("AUTHORIZED_USERS").split(",")]


def is_authorized():
    async def predicate(ctx: commands.Context):
        return ctx.author.id in AUTHORIZED_USER_IDS
    return commands.check(predicate)


class Sync(commands.Cog):
    def __init__(self, bot: JouzuBot):
        self.bot = bot

    async def cog_load(self):
        pass

    @commands.command()
    @is_authorized()
    async def sync_guild(self, ctx: discord.ext.commands.Context):
        """Sync commands to current guild."""
        await ctx.send(f"Syncing commands to guild with id {ctx.guild.id}...")
        self.bot.tree.copy_global_to(guild=discord.Object(id=ctx.guild.id))
        self.bot.tree.clear_commands(guild=None)
        await self.bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
        await ctx.send(f"Synced commands to guild with id {ctx.guild.id}.")

    @commands.command()
    @is_authorized()
    async def sync_global(self, ctx: discord.ext.commands.Context):
        """Sync commands to global."""
        await ctx.send("Syncing commands to global...")
        await self.bot.tree.sync()
        await ctx.send("Synced commands to global.")

    @commands.command()
    @is_authorized()
    async def clear_global_commands(self, ctx):
        """Clear all global commands."""
        self.bot.tree.clear_commands(guild=None)
        await self.bot.tree.sync()
        await ctx.send("Cleared global commands.")

    @commands.command()
    @is_authorized()
    async def clear_guild_commands(self, ctx):
        """Clear all guild commands."""
        self.bot.tree.clear_commands(guild=discord.Object(id=ctx.guild.id))
        await self.bot.tree.sync(guild=discord.Object(id=ctx.guild.id))
        await ctx.send(f"Cleared guild commands for guild with id {ctx.guild.id}.")


async def setup(bot):
    await bot.add_cog(Sync(bot))
