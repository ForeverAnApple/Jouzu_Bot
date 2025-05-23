from .immersion_goals import check_goal_status, check_immersion_goal_status
from .username_fetcher import get_username_db, fetch_username_db
from lib.anilist_autocomplete import CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY, CACHED_ANILIST_THUMBNAIL_QUERY, CACHED_ANILIST_TITLE_QUERY, CREATE_ANILIST_FTS5_TABLE_QUERY, CREATE_ANILIST_TRIGGER_DELETE, CREATE_ANILIST_TRIGGER_INSERT, CREATE_ANILIST_TRIGGER_UPDATE
from lib.bot import JouzuBot
from lib.immersion_helpers import is_valid_channel, get_achievement_reached_info, get_current_and_next_achievement
from lib.media_types import MEDIA_TYPES, LOG_CHOICES
from lib.tmdb_autocomplete import CACHED_TMDB_RESULTS_CREATE_TABLE_QUERY, CACHED_TMDB_THUMBNAIL_QUERY, CACHED_TMDB_TITLE_QUERY, CREATE_TMDB_FTS5_TABLE_QUERY, CREATE_TMDB_TRIGGER_DELETE, CREATE_TMDB_TRIGGER_INSERT, CREATE_TMDB_TRIGGER_UPDATE, CACHED_TMDB_GET_MEDIA_TYPE_QUERY
from lib.vndb_autocomplete import CACHED_VNDB_RESULTS_CREATE_TABLE_QUERY, CACHED_VNDB_THUMBNAIL_QUERY, CACHED_VNDB_TITLE_QUERY, CREATE_VNDB_FTS5_TABLE_QUERY, CREATE_VNDB_TRIGGER_DELETE, CREATE_VNDB_TRIGGER_INSERT, CREATE_VNDB_TRIGGER_UPDATE

import csv
import discord
import humanize
import os
import random

from datetime import timedelta, datetime
from discord.ext import commands
from typing import Optional

EMOTE_SERVER = os.getenv("EMOTE_SERVER")
AUTHORIZED_USER_IDS = [int(id) for id in os.getenv("AUTHORIZED_USERS").split(",")]

CREATE_LOGS_TABLE = """
    CREATE TABLE IF NOT EXISTS logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    media_name TEXT,
    comment TEXT,
    amount_logged INTEGER NOT NULL,
    time_logged REAL NOT NULL,
    log_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    achievement_group TEXT);
"""

CREATE_LOG_QUERY = """
    INSERT INTO logs (user_id, media_type, media_name, comment, amount_logged, time_logged, log_date, achievement_group)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""

GET_CONSECUTIVE_DAYS_QUERY = """
    SELECT DISTINCT(DATE(log_date)) AS log_date
    FROM logs
    WHERE user_id = ?
    GROUP BY DATE(log_date)
    ORDER BY log_date DESC;
"""

GET_TIME_FOR_CURRENT_MONTH_QUERY = """
    SELECT SUM(time_logged) AS total_time
    FROM logs
    WHERE user_id = ? AND strftime('%Y-%m', log_date) = strftime('%Y-%m', 'now');
"""

GET_USER_LOGS_QUERY = """
    SELECT log_id, media_type, media_name, amount_logged, log_date
    FROM logs
    WHERE user_id = ?
    ORDER BY log_date DESC;
"""

GET_TO_BE_DELETED_LOG_QUERY = """
    SELECT log_id, media_type, media_name, amount_logged, log_date
    FROM logs
    WHERE user_id = ? AND log_id = ?;
"""

DELETE_LOG_QUERY = """
    DELETE FROM logs
    WHERE log_id = ? AND user_id = ?;
"""

GET_TOTAL_UNITS_FOR_ACHIEVEMENT_GROUP_QUERY = """
    SELECT SUM(amount_logged) AS total_units
    FROM logs
    WHERE user_id = ? AND achievement_group = ?;
"""

GET_TOTAL_TIME_FOR_USER_QUERY = """
    SELECT SUM(time_logged) AS total_time
    FROM logs
    WHERE user_id = ?;
"""

GET_USER_LOGS_FOR_EXPORT_QUERY = """
    SELECT log_id, media_type, media_name, comment, amount_logged, time_logged, log_date
    FROM logs
    WHERE user_id = ?
    ORDER BY log_date DESC;
"""

GET_MONTHLY_LEADERBOARD_QUERY = """
    SELECT user_id, SUM(time_logged) AS total_time, SUM(amount_logged) AS total_units
    FROM logs l
    JOIN users u
    ON l.user_id = u.discord_user_id
    WHERE (? = 'ALL' OR strftime('%Y-%m', log_date) = ?)
    AND (? IS NULL OR media_type = ?)
    AND u.guild_id = ?
    GROUP BY user_id
    ORDER BY total_time DESC
    LIMIT 25
"""

GET_USER_MONTHLY_POINTS_QUERY = """
    SELECT SUM(time_logged) AS total_time, SUM(amount_logged)
    FROM logs
    WHERE user_id = ? AND (? = 'ALL' OR strftime('%Y-%m', log_date) = ?)
    AND (? IS NULL OR media_type = ?);
"""

GET_USER_MONTHLY_TIME_FOR_GROUP_QUERY = """
    SELECT SUM(time_logged) AS total_time, SUM(amount_logged) AS total_units
    FROM logs
    WHERE user_id = ? AND (? = 'ALL' OR strftime('%Y-%m', log_date) = ?)
    AND (? IS NULL OR media_type = ?);
"""

def is_authorized(user_id: int):
    return user_id in AUTHORIZED_USER_IDS

async def log_undo_autocomplete(interaction: discord.Interaction, current_input: str):
    current_input = current_input.strip()

    jouzu_bot = interaction.client
    jouzu_bot: JouzuBot

    user_logs = await jouzu_bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
    choices = []

    for log_id, media_type, media_name, amount_logged, log_date in user_logs:
        unit_name = MEDIA_TYPES[media_type]['unit_name']
        log_date_str = datetime.strptime(log_date, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
        log_name = f"{media_type}: {media_name or 'N/A'} ({amount_logged} {unit_name}) on {log_date_str}"[:100]
        if current_input.lower() in log_name.lower():
            choices.append(discord.app_commands.Choice(name=log_name, value=str(log_id)))

    return choices[:10]


async def log_name_autocomplete(interaction: discord.Interaction, current_input: str):
    current_input = current_input.strip()
    if not current_input:
        return []
    if len(current_input) <= 1:
        return []
    media_type = interaction.namespace['media_type']
    if MEDIA_TYPES[media_type]['autocomplete']:
        result = await MEDIA_TYPES[media_type]['autocomplete'](interaction, current_input)
        return result
    return []


class ImmersionLog(commands.Cog):
    def __init__(self, bot: JouzuBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_LOGS_TABLE)
        await self.bot.RUN(CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_ANILIST_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_UPDATE)
        await self.bot.RUN(CACHED_VNDB_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_VNDB_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_UPDATE)
        await self.bot.RUN(CACHED_TMDB_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_TMDB_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_UPDATE)

    @discord.app_commands.command(name='log', description='Log your immersion!')
    @discord.app_commands.describe(
        media_type='The type of media you are logging.',
        amount='Pages, Characters, Episodes, etc...',
        time_mins='How long you immersed for (in minutes)',
        name='You can use VNDB ID/Title for VNs, AniList ID/Titlefor Anime/Manga, TMDB titles for Listening or provide free text.',
        comment='Short comment about your log.',
        backfill_date='YYYY-MM-DD You can log no more than 7 days into the past. Not needed for immersion you have completed today.'
    )
    @discord.app_commands.choices(media_type=LOG_CHOICES)
    @discord.app_commands.autocomplete(name=log_name_autocomplete)
    async def log(self, interaction: discord.Interaction, media_type: str, amount: Optional[str], time_mins: Optional[str], name: Optional[str], comment: Optional[str], backfill_date: Optional[str]):
        if not amount and not time_mins:
            return await interaction.response.send_message("Please enter either an amount or a time to log. Or both.", ephemeral=True)
        if amount and not amount.isdigit():
            return await interaction.response.send_message("Amount must be a valid number.", ephemeral=True)
        elif amount:
            amount = int(amount)
            if amount < 0:
                return await interaction.response.send_message("Amount must be a positive number.", ephemeral=True)
        allowed_limit = MEDIA_TYPES[media_type]['max_logged']
        if amount and amount > allowed_limit:
            return await interaction.response.send_message(f"Amount must be less than {allowed_limit} for `{MEDIA_TYPES[media_type]['log_name']}`.", ephemeral=True)

        if name and len(name) > 150:
            return await interaction.response.send_message("Name must be less than 150 characters.", ephemeral=True)
        elif name:
            name = name.strip()
        
        unit_is_time = MEDIA_TYPES[media_type]['unit_is_time']
        if time_mins and not time_mins.isdigit():
            return await interaction.response.send_message("Time tracking must be a valid number.", ephemeral=True)
        elif time_mins:
            time_mins = int(time_mins)
            if time_mins < 1 or time_mins > 1440:
                return await interaction.response.send_message("Time tracking must be between 1 - 1440", ephemeral=True)

        if unit_is_time and time_mins and amount:
            return await interaction.response.send_message("This tracking is pure time based, no need to enter time twice.", ephemeral=True)

        if comment and len(comment) > 200:
            return await interaction.response.send_message("Comment must be less than 200 characters.", ephemeral=True)
        elif comment:
            comment = comment.strip()

        if backfill_date is None:
            log_date = discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        else:
            try:
                log_date = datetime.strptime(backfill_date, '%Y-%m-%d')
                today = discord.utils.utcnow().date()
                if log_date.date() > today:
                    return await interaction.response.send_message("You cannot log a date in the future.", ephemeral=True)
                if (today - log_date.date()).days > 7:
                    return await interaction.response.send_message("You cannot log a date more than 7 days in the past.", ephemeral=True)
                log_date = log_date.strftime('%Y-%m-%d') + " 23:59:00"
            except ValueError:
                return await interaction.response.send_message("Invalid date format. Please use YYYY-MM-DD.", ephemeral=True)

        await interaction.response.defer()

        time_logged = 0
        amount_logged = 0
        if unit_is_time:
            time_logged = time_mins if time_mins else amount
            amount_logged = time_logged
        elif time_mins:
            time_logged = time_mins
        if amount:
            amount_logged = amount
        achievement_group = MEDIA_TYPES[media_type]['Achievement_Group']
        user = interaction.user
        total_achievement_units_before = await self.get_total_units_for_achievement_group(user.id, achievement_group)

        current_month_time_before = await self.get_time_for_current_month(user.id)
        current_total_time_before = await self.get_total_time_for_user(user.id)

        await self.bot.RUN(
            CREATE_LOG_QUERY,
            (user.id, media_type, name, comment, amount_logged,
             time_logged, log_date, achievement_group)
        )

        current_month_time_after = await self.get_time_for_current_month(user.id)
        current_total_time_after = await self.get_total_time_for_user(user.id)

        # Check goals
        goal_statuses = await check_immersion_goal_status(self.bot, user.id)
        goal_statuses += await check_goal_status(self.bot, user.id, media_type)

        # Check achievement for the category
        total_achievement_units_after = total_achievement_units_before + amount_logged
        achievement_reached, current_achievement, next_achievement = await get_achievement_reached_info(achievement_group, total_achievement_units_before, total_achievement_units_after)

        # Check achievement for total immersion time overall
        immersion_achievement_reached, current_immersion_achievement, next_immersion_achievement = await get_achievement_reached_info('Immersion', current_total_time_before, current_total_time_after)

        # lmao emoji gacha
        random_guild_emoji = ''
        if EMOTE_SERVER:
            emote_guild = self.bot.get_guild(int(EMOTE_SERVER))
            if emote_guild:
                random_guild_emoji = random.choice(emote_guild.emojis)
        if not random_guild_emoji and interaction.guild and interaction.guild.emojis:
            random_guild_emoji = random.choice(interaction.guild.emojis)

        consecutive_days = await self.get_consecutive_days_logged(user.id)
        actual_title = await self.get_title(media_type, name)
        thumbnail_url = await self.get_thumbnail_url(media_type, name)
        source_url = await self.get_source_url(media_type, name)
        time_logged_str = f"+{time_logged}min(s)"

        unit_name=MEDIA_TYPES[media_type]['unit_name']
        embed_title = (
            f"Logged {amount_logged} {unit_name}"
            f"{'s' if amount_logged > 1 else ''} of {media_type} {random_guild_emoji}"
        )

        log_embed = discord.Embed(title=embed_title, color=discord.Color.random())
        log_embed.description = f"[{actual_title}]({source_url})" if source_url else actual_title
        log_embed.add_field(name="Comment", value=comment or "No comment", inline=False)
        log_embed.add_field(name="Minutes Received", value=time_logged_str)
        log_embed.add_field(name="Total Minutes/Month",
                            value=f"`{current_month_time_before}` → `{current_month_time_after}`")
        log_embed.add_field(name="Streak", value=f"{consecutive_days} day{'s' if consecutive_days > 1 else ''}")
        log_embed.add_field(name=f"Category: {unit_name}(s) Received", value=amount_logged)
        log_embed.add_field(name=f"Total {unit_name}s",
                            value=f"`{total_achievement_units_before}` → `{total_achievement_units_after}`")

        # Achievement reached for current category
        if achievement_reached and current_achievement:
            log_embed.add_field(name=f"{media_type} Achievement Reached! 🎉", value=current_achievement["title"], inline=False)
        if next_achievement:
            next_achievement_info = f"{next_achievement['title']} (`{int(total_achievement_units_after)}/{next_achievement['points']}` {achievement_group} {unit_name}s)"
            log_embed.add_field(name=f"Next {media_type} Achievement", value=next_achievement_info, inline=False)

        # Immersion achievement reached
        if immersion_achievement_reached and current_immersion_achievement:
            log_embed.add_field(name="Total Immersion Time Achievement Reached! 🎉", value=current_immersion_achievement["title"], inline=False)
        if next_immersion_achievement:
            next_immersion_achievement_info = f"{next_immersion_achievement['title']} (`{int(current_total_time_after)}/{next_immersion_achievement['points']}` Total Immersion minutes)"
            log_embed.add_field(name="Next Total Immersion Time Achievement", value=next_immersion_achievement_info, inline=False)

        for i, goal_status in enumerate(goal_statuses, start=1):
            if len(log_embed.fields) >= 24:
                log_embed.add_field(name="Notice", value="You have reached the maximum number of fields. Please clear some of your goals to view more.", inline=False)
                break
            log_embed.add_field(name=f"Goal {i}", value=goal_status, inline=False)

        if thumbnail_url:
            log_embed.set_thumbnail(url=thumbnail_url)
        log_embed.set_footer(text=f"Logged by {user.display_name} for {log_date.split(' ')[0]}", icon_url=user.display_avatar.url)

        logged_message = await interaction.followup.send(embed=log_embed)

        if name and (name.startswith("http://") or name.startswith("https://")):
            await logged_message.reply(f"> {name}")
        elif comment and (comment.startswith("http://") or comment.startswith("https://")):
            await logged_message.reply(f"> {comment}")

        # Notify immersion achievements
        achievement_notif_str = ''
        if achievement_reached:
            achievement_notif_str += f"🎉 **{media_type} Achievement Reached!** (for {user.display_name}) 🎉\n\n**{current_achievement['title']}**\n\n{current_achievement['description']}\n"
        if immersion_achievement_reached:
            achievement_notif_str += f"🎉 **Total Immersion Achievement Reached!** (for {user.display_name}) 🎉\n\n**{current_immersion_achievement['title']}**\n\n{current_immersion_achievement['description']}"
        if achievement_reached or immersion_achievement_reached:
            await logged_message.reply(achievement_notif_str)

        # Warn user of potential mistracking
        if not unit_is_time:
            if time_mins and not amount:
                return await logged_message.reply(f"<@{user.id}>**WARNING** You have tracked only immersion time and not {unit_name}s for {media_type}. Your tracking will **NOT** be counted towards {media_type} achievements. You can `/log_undo` if this was a mistake.")
            elif amount and not time_mins:
                return await logged_message.reply(f"<@{user.id}>**WARNING** You have tracked only {unit_name}s for {media_type} and not total immersion time. Your tracking will **NOT** be counted towards server-wide immersion goals. Your tracking will also **NOT** be counted towards total immersion achievements. You can `/log_undo` if this was a mistake.")


    async def get_consecutive_days_logged(self, user_id: int) -> int:
        result = await self.bot.GET(GET_CONSECUTIVE_DAYS_QUERY, (user_id,))
        if not result:
            return 0

        consecutive_days = 0
        today = discord.utils.utcnow().date()

        for row in result:
            log_date = datetime.strptime(row[0], '%Y-%m-%d').date()
            if log_date == today - timedelta(days=consecutive_days):
                consecutive_days += 1
            else:
                break

        return consecutive_days

    async def get_time_for_current_month(self, user_id: int) -> float:
        result = await self.bot.GET(GET_TIME_FOR_CURRENT_MONTH_QUERY, (user_id,))
        if result and result[0] and result[0][0]:
            return round(result[0][0], 2)
        return 0.0

    async def get_thumbnail_url(self, media_type: str, name: str) -> Optional[str]:
        if MEDIA_TYPES[media_type]['thumbnail_query']:
            result = await self.bot.GET(MEDIA_TYPES[media_type]['thumbnail_query'], (name,))
            if result:
                return result[0][0]
        return None

    async def get_title(self, media_type: str, name: str) -> str:
        if MEDIA_TYPES[media_type]['title_query']:
            result = await self.bot.GET(MEDIA_TYPES[media_type]['title_query'], (name,))
            if result:
                return result[0][0]
        return name

    async def get_source_url(self, media_type: str, name: str) -> Optional[str]:
        if not MEDIA_TYPES[media_type]['source_url']:
            return None
        exists_in_db = await self.bot.GET(MEDIA_TYPES[media_type]['title_query'], (name,))
        if not exists_in_db:
            return None
        if media_type == "Listening Time":
            tmdb_media_type = await self.bot.GET(CACHED_TMDB_GET_MEDIA_TYPE_QUERY, (name,))
            tmdb_media_type = tmdb_media_type[0][0]
            return MEDIA_TYPES[media_type]['source_url'].format(tmdb_media_type=tmdb_media_type) + name
        return MEDIA_TYPES[media_type]['source_url'] + name

    @discord.app_commands.command(name='log_undo', description='Undo a previous immersion log!')
    @discord.app_commands.describe(log_entry='Select the log entry you want to undo.')
    @discord.app_commands.autocomplete(log_entry=log_undo_autocomplete)
    async def log_undo(self, interaction: discord.Interaction, log_entry: str):
        if not log_entry.isdigit():
            return await interaction.response.send_message("Invalid log entry selected.", ephemeral=True)

        log_id = int(log_entry)
        user_logs = await self.bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
        log_ids = [log[0] for log in user_logs]

        if log_id not in log_ids:
            return await interaction.response.send_message("The selected log entry does not exist or does not belong to you.", ephemeral=True)

        deleted_log_info = await self.bot.GET(GET_TO_BE_DELETED_LOG_QUERY, (interaction.user.id, log_id))
        log_id, media_type, media_name, amount_logged, log_date = deleted_log_info[0]
        log_date = datetime.strptime(log_date, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
        await self.bot.RUN(DELETE_LOG_QUERY, (log_id, interaction.user.id))
        await interaction.response.send_message(
            f"> {interaction.user.mention} Your log for `{amount_logged} {MEDIA_TYPES[media_type]['unit_name']}` "
            f"of `{media_type}` (`{media_name or 'No Name'}`) on `{log_date}` has been deleted."
        )

    async def get_total_units_for_achievement_group(self, user_id: int, achievement_group: str) -> float:
        result = await self.bot.GET(GET_TOTAL_UNITS_FOR_ACHIEVEMENT_GROUP_QUERY, (user_id, achievement_group))
        if result and result[0] and result[0][0] is not None:
            return result[0][0]
        return 0.0

    async def get_total_time_for_user(self, user_id: int) -> float:
        result = await self.bot.GET(GET_TOTAL_TIME_FOR_USER_QUERY, (user_id,))
        if result and result[0] and result[0][0] is not None:
            return result[0][0]
        return 0.0

    @discord.app_commands.command(name='log_achievements', description='Display all your achievements!')
    @discord.app_commands.describe(user='The user to view achievements for (optional)')
    @discord.app_commands.guild_only()
    async def log_achievements(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        member = user or interaction.user
        user_id = member.id
        achievements_list = []
        achievements_dict = {settings_group['Achievement_Group']: settings_group['unit_name'] for settings_group in MEDIA_TYPES.values()}
        achievements_dict['Immersion'] = 'minute'

        for achievement_group, unit_name in achievements_dict.items():
            total_units = await self.get_total_units_for_achievement_group(user_id, achievement_group)
            if achievement_group == 'Immersion':
                total_units = await self.get_total_time_for_user(user_id)
            if total_units <= 0:
                continue
            achievements_list.append(f"\n**-----{achievement_group.upper()}-----**\n")
            current_achievement, next_achievement = await get_current_and_next_achievement(achievement_group, total_units)
            if current_achievement:
                current_achievement_info = f"**Reached {current_achievement['title']} (`{current_achievement['points']}` {unit_name}s)**"
                current_achievement_info += f"`\n{current_achievement['description']}`"
            if next_achievement:
                next_achievement_info = f"\n➤ Next: {next_achievement['title']} (`{int(total_units)}/{next_achievement['points']}` {unit_name}s)"

            if current_achievement:
                achievements_list.append(current_achievement_info)
            if next_achievement:
                achievements_list.append(next_achievement_info)
        if achievements_list:
            achievements_str = "\n".join(achievements_list)
        else:
            achievements_str = "No achievements yet. Keep immersing!"

        embed = discord.Embed(title=f"{member.display_name}'s Achievements",
                              description=achievements_str, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)


    @discord.app_commands.command(name='logs', description='Output your immersion logs as a text file!')
    @discord.app_commands.describe(user='The user to export logs for (optional)')
    @discord.app_commands.guild_only()
    async def logs(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        await interaction.response.defer()
        member = user or interaction.user
        user_id = member.id
        user_logs = await self.bot.GET(GET_USER_LOGS_FOR_EXPORT_QUERY, (user_id,))

        if not user_logs:
            return await interaction.followup.send(f"No logs to export for {member.display_name}.", ephemeral=True)

        log_filename = f"immersion_logs_{user_id}.txt"
        log_filepath = os.path.join("/tmp", log_filename)
        # log_id, media_type, media_name, comment, amount_logged, time_logged, log_date
        with open(log_filepath, mode='w', encoding='utf-8') as log_file:
            for log in user_logs:
                log_date = datetime.strptime(log[6], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
                media_type = log[1]
                media_name = log[2] or 'N/A'
                amount_logged = log[4]
                unit_name = MEDIA_TYPES[media_type]['unit_name'] + 's' if amount_logged > 1 else MEDIA_TYPES[media_type]['unit_name']
                comment = log[3] or 'No comment'

                log_entry = f"{log_date}: {media_type} ({media_name}) -> {amount_logged} {unit_name} | {comment}\n"
                log_file.write(log_entry)

        await interaction.followup.send(f"Here are {member.display_name}'s immersion logs:", file=discord.File(log_filepath))
        os.remove(log_filepath)


    @discord.app_commands.command(name='log_server_report', description='Server wide immersion statistics.')
    @discord.app_commands.describe(media_type='Optionally specify the media type for leaderboard filtering.',
                                   month='Optionally specify the month in YYYY-MM format or select all with "ALL".')
    @discord.app_commands.choices(media_type=LOG_CHOICES)
    @discord.app_commands.guild_only()
    async def log_server_report(self, interaction: discord.Interaction, media_type: Optional[str] = None, month: Optional[str] = None):
        if not is_authorized(interaction.user.id):
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)

        await interaction.response.defer()
        guild_id = interaction.guild_id

        if not month:
            month = discord.utils.utcnow().strftime('%Y-%m')
        elif month != 'ALL':
            try:
                datetime.strptime(month, '%Y-%m').strftime('%Y-%m')
            except ValueError:
                return await interaction.followup.send("Invalid month format. Please use YYYY-MM.", ephemeral=True)

        leaderboard_data = await self.bot.GET(GET_MONTHLY_LEADERBOARD_QUERY, (month, month, media_type, media_type, guild_id))

        def human_readable_number(value):
            # Convert to hour
            value /= 60.0
            return f"{value:.1f}"

        embed = discord.Embed(
            title=f"Immersion Report - {(datetime.strptime(month, '%Y-%m').strftime('%B %Y') if month != 'ALL' else 'All Time')}",
            color=discord.Color.blue()
        )
        if media_type:
            embed.title += f" for {media_type}"
        unit_name = MEDIA_TYPES[media_type]['unit_name'] if media_type else None
        unit_is_time = MEDIA_TYPES[media_type]['unit_is_time'] if media_type else None

        description = ""

        if leaderboard_data:
            for rank, (user_id, total_time, total_units) in enumerate(leaderboard_data, start=1):
                (_, user_name) = await fetch_username_db(self.bot, guild_id, user_id)
                total_time_humanized = human_readable_number(total_time)

                description += f"**{humanize.ordinal(rank)} {user_name}**: {total_time_humanized} hrs \t"
                if unit_name and not unit_is_time:
                    description += f" | {total_units} {unit_name}s"
                description += "\n"
        else:
            description = "No logs available for this month. Start immersing to be on the leaderboard!"

        embed.description = description

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ImmersionLog(bot))
