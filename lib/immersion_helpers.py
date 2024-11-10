import discord
import os
import yaml

from lib.media_types import MEDIA_TYPES

IMMERSION_LOG_SETTINGS = os.getenv("IMMERSION_LOG_SETTINGS") or "config/immersion_log_settings.yml"
with open(IMMERSION_LOG_SETTINGS, "r", encoding="utf-8") as f:
    immersion_log_settings = yaml.safe_load(f)


async def is_valid_channel(interaction: discord.Interaction) -> bool:
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    if interaction.channel.id in immersion_log_settings['immersion_bot']['allowed_log_channels']:
        return True
    if not interaction.user.dm_channel:
        await interaction.client.create_dm(interaction.user)
    if interaction.channel == interaction.user.dm_channel:
        return True
    return False


async def get_achievement_reached_info(achievement_group: str, points_before: int, points_after: int):
    achievement_group_settings = immersion_log_settings['achievements'][achievement_group]
    current_achievement = None
    next_achievement = None
    achievement_reached = False

    for achievement in achievement_group_settings:
        if achievement['points'] <= points_before:
            current_achievement = achievement
        if points_before < achievement['points'] <= points_after:
            achievement_reached = True
            current_achievement = achievement
        elif points_after < achievement['points']:
            next_achievement = achievement
            break

    return achievement_reached, current_achievement, next_achievement


async def get_current_and_next_achievement(achievement_group: str, points: int):
    achievement_group_settings = immersion_log_settings['achievements'][achievement_group]
    current_achievement = None
    next_achievement = None

    for achievement in achievement_group_settings:
        if achievement['points'] <= points:
            current_achievement = achievement
        if points < achievement['points']:
            next_achievement = achievement
            break

    return current_achievement, next_achievement
