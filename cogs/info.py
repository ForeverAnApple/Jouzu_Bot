import discord
import yaml
from discord.ext import commands

INFO_COMMANDS_PATH = "config/info_commands.yml"
with open(INFO_COMMANDS_PATH, "r", encoding="utf-8") as f:
    info_commands = yaml.safe_load(f)


async def info_autocomplete(interaction: discord.Interaction, current: str):
    if not current:
        return [
            discord.app_commands.Choice(name=key, value=key)
            for key in info_commands.keys()
        ][:25]
    else:
        return [
            discord.app_commands.Choice(name=key, value=key)
            for key in info_commands.keys()
            if current.lower() in key.lower()
        ][:25]


class InfoCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="info", description="Get various pieces of valuable knowledge!"
    )
    @discord.app_commands.describe(info_key="The topic.")
    @discord.app_commands.autocomplete(info_key=info_autocomplete)
    async def info(self, interaction: discord.Interaction, info_key: str):
        if info_key not in info_commands.keys():
            await interaction.response.send_message(
                "Info key not found.", ephemeral=True
            )
            return

        text_info = info_commands.get(info_key)
        embed = discord.Embed(
            title=f"Info for `{info_key}`",
            description=text_info,
            color=discord.Color.random(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(InfoCommand(bot))
