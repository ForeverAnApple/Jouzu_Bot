import copy
import discord
import os

from datetime import datetime, timezone, timedelta
from discord.ext import commands
from lib.bot import JouzuBot
from lib.immersion_helpers import is_valid_channel
from lib.media_types import LOG_CHOICES, MEDIA_TYPES
from typing import Optional

CREATE_GUILD_GOALS_TABLE = """
    CREATE TABLE IF NOT EXISTS guild_goals (
    goal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    goal_type TEXT NOT NULL CHECK(goal_type IN ('time', 'amount')),
    goal_value INTEGER NOT NULL,
    per_user_scaling INTEGER,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
"""

CREATE_GUILD_GOAL_QUERY = """
    INSERT INTO guild_goals (guild_id, media_type, goal_type, goal_value, per_user_scaling, start_date, end_date)
    VALUES (?, ?, ?, ?, ?, ?, ?);
"""

GET_GUILD_GOALS_QUERY = """
    SELECT goal_id, media_type, goal_type, goal_value, per_user_scaling, start_date, end_date
    FROM guild_goals
    WHERE guild_id = ?;
"""

DELETE_GUILD_GOAL_QUERY = """
    DELETE FROM guild_goals
    WHERE goal_id = ? AND guild_id = ?;
"""

GET_GUILD_GOAL_STATUS_QUERY = """
    SELECT goal_id, goal_type, goal_value, per_user_scaling, start_date, end_date, 
       (SELECT COALESCE(SUM(time_logged), 0) 
        FROM logs 
        AND log_date BETWEEN guild_goals.start_date AND guild_goals.end_date)
        as progress
    FROM guild_goals
    WHERE guild_id = ?
    AND media_type = 'Immersion'
"""

GOAL_CHOICES = [discord.app_commands.Choice(name="General Immersion (mins)",
                                            value="Immersion")]
AUTHORIZED_USER_IDS = [int(id) for id in os.getenv("AUTHORIZED_USERS").split(",")]

def is_authorized():
    async def predicate(ctx: commands.Context):
        return ctx.author.id in AUTHORIZED_USER_IDS
    return commands.check(predicate)

async def goal_undo_autocomplete(interaction: discord.Interaction, current_input: str):
    current_input = current_input.strip()
    jouzu_bot = interaction.client
    jouzu_bot: JouzuBot
    guild_goals = await jouzu_bot.GET(GET_GUILD_GOALS_QUERY, (interaction.guild_id,))
    choices = []

    for goal_id, media_type, goal_type, goal_value, per_user_scaling, start_date, end_date in guild_goals:
        end_date_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        end_date_str = end_date_dt.strftime('%Y-%m-%d %H:%M UTC')
        start_date_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        start_date_str = start_date_dt.strftime('%Y-%m-%d %H:%M UTC')
        goal_entry = f"{goal_type.capitalize()} goal of {goal_value} for {media_type} from {start_date_str} -> {end_date_str}"
        if current_input.lower() in goal_entry.lower():
            choices.append(discord.app_commands.Choice(name=goal_entry, value=str(goal_id)))

    return choices[:10]


class GuildGoalsCog(commands.Cog):
    def __init__(self, bot: JouzuBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_GUILD_GOALS_TABLE)

    
    @discord.app_commands.command(name='log_set_server_goal', description='Set an immersion goal for the server!')
    @discord.app_commands.describe(
        media_type='The type of media for which you want to set a goal.',
        goal_type='The type of goal, either time (mins) or amount.',
        goal_value='The goal value you want to achieve.',
        start_date='The start date for the goal. (YYYY-MM-DD format)',
        end_date='The end date for the goal by (YYYY-MM-DD format)'
    )
    @discord.app_commands.guild_only()
    @discord.app_commands.choices(goal_type=[
        discord.app_commands.Choice(name='Time (mins)', value='time'),
        discord.app_commands.Choice(name='Amount', value='amount')],
        media_type=GOAL_CHOICES)
    @is_authorized()
    async def log_set_server_goal(self, interaction: discord.Interaction, media_type: str, goal_type: str, goal_value: int, start_date: str, end_date: str, per_user_scaling: Optional[str]):
        # Make sure that general immersion time goal is not using amount.
        if media_type == 'Immersion' and goal_type != 'time':
            return await interaction.response.send_message("General Immersion goals MUST be time based.", ephemeral=True)
        if media_type != 'Immersion' and MEDIA_TYPES[media_type]['unit_is_time'] and goal_type == 'amount':
            return await interaction.response.send_message("Time based goals MUST have time as goal_type.", ephemeral=True)

        if goal_value < 1:
            return await interaction.response.send_message("Goal value must be above 0.", ephemeral=True)

        if per_user_scaling and per_user_scaling.isdigit():
            return await interaction.response.send_message("Per user scaling must be a valid number.", ephemeral=True)
        elif per_user_scaling:
            per_user_scaling = int(per_user_scaling)
            if per_user_scaling < 1:
                return await interaction.response.send_message("Per user scaling must be above 0.", ephemeral=True)

        try:
            start_date_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            # if start_date_dt < discord.utils.utcnow().replace(minute=0, second=0, microsecond=0):
            #     return await interaction.response.send_message("The start date must be in the future.", ephemeral=True)
            end_date_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if end_date_dt < discord.utils.utcnow().replace(minute=0, second=0, microsecond=0):
                return await interaction.response.send_message("The end date must be in the future.", ephemeral=True)

            if end_date_dt <= start_date_dt:
                return await interaction.response.send_message("End date must be after start date.", ephemeral=True)
        except ValueError:
            return await interaction.response.send_message("Invalid input. Please use date in YYYY-MM-DD format.", ephemeral=True)

        await self.bot.RUN(CREATE_GUILD_GOAL_QUERY, (interaction.guild_id, media_type, goal_type, goal_value, per_user_scaling, start_date_dt.strftime('%Y-%m-%d %H:%M:%S'), end_date_dt.strftime('%Y-%m-%d %H:%M:%S')))

        unit_name = MEDIA_TYPES[media_type]['unit_name'] if goal_type == 'amount' else 'minute'
        start_timestamp = int(start_date_dt.timestamp())
        end_timestamp = int(end_date_dt.timestamp())
        embed = discord.Embed(title=f"Goal Set for {interaction.guild.name}!", color=discord.Color.green())
        embed.add_field(name="Media Type", value=media_type, inline=True)
        embed.add_field(name="Goal Type", value=goal_type.capitalize(), inline=True)
        embed.add_field(name="Goal Value", value=f"{goal_value} {unit_name}{'s' if goal_value > 1 else ''}", inline=True)
        embed.add_field(name="Start Date", value=f"<t:{start_timestamp}:R>", inline=False)
        embed.add_field(name="End Date", value=f"<t:{end_timestamp}:R>", inline=True)
        embed.add_field(name="Per User Scaling", value=f"{per_user_scaling if per_user_scaling else 'No scaling'}", inline=True)
        embed.set_footer(text=f"Goal set by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)


    @discord.app_commands.command(name='log_remove_server_goal', description='Remove one of the server\'s goals.')
    @discord.app_commands.describe(goal_entry='Select the goal you want to remove.')
    @discord.app_commands.autocomplete(goal_entry=goal_undo_autocomplete)
    @is_authorized()
    async def log_remove_server_goal(self, interaction: discord.Interaction, goal_entry: str):
        if not goal_entry.isdigit():
            return await interaction.response.send_message("Invalid goal entry selected.", ephemeral=True)

        goal_id = int(goal_entry)
        guild_goals = await self.bot.GET(GET_GUILD_GOALS_QUERY, (interaction.guild_id,))
        goal_ids = [goal[0] for goal in guild_goals]

        if goal_id not in goal_ids:
            return await interaction.response.send_message("The selected goal entry does not exist or does not belong to the server.", ephemeral=True)

        goal_to_remove = next(goal for goal in guild_goals if goal[0] == goal_id)
        goal_type, goal_value, media_type = goal_to_remove[2], goal_to_remove[3], goal_to_remove[1]
        unit_name = MEDIA_TYPES[media_type]['unit_name'] if goal_type == 'amount' else 'time'

        await self.bot.RUN(DELETE_GUILD_GOAL_QUERY, (goal_id, interaction.guild_id))
        await interaction.response.send_message(f"{interaction.guild.name}'s `{goal_type}` goal of `{goal_value} {unit_name}{'s' if goal_value > 1 else ''}` for `{media_type}` has been removed.")


async def setup(bot):
    await bot.add_cog(GuildGoalsCog(bot))
