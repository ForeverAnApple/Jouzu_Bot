# Jouzu Gumi Discord Bot

Multi-purpose Discord bot developed for the Jouzu Gumi Discord server. The bot is designed to be modular and easy to extend with new features and is largely based off of [TMW_Bot](https://github.com/friedrich-de/TMW_Bot).


## Features/Commands

#### `immersion_log.py`, `immersion_goals.py`, `immersion_stats.py`

Comprehensive immersion tracking system that allows users to log their Japanese learning activities, set goals, and view statistics.

Commands:
* `/log` `<media_type>` `<amount>` `<name>` `<comment>` `<backfill_date>` - Log immersion activity. Media type can be books, manga, anime, etc. Amount is in units or minutes.
* `/log_undo` `<log_entry>` - Remove a previous log entry.
* `/log_achievements` - Display all your immersion achievements.
* `/log_export` `<user>` - Export immersion logs as CSV file. User parameter is optional.
* `/logs` `<user>` - Output immersion logs as a nicely formatted text file. User parameter is optional.
* `/log_leaderboard` `<media_type>` `<month>` - Display monthly leaderboard. Can filter by media type and month (YYYY-MM or "ALL").

Goal Management:
* `/log_set_goal` `<media_type>` `<goal_type>` `<goal_value>` `<end_date_or_hours>` - Set a new immersion goal.
* `/log_remove_goal` `<goal_entry>` - Remove a specific goal.
* `/log_view_goals` `<member>` - View your goals or another user's goals.
* `/log_clear_goals` - Clear all expired goals.

Statistics:
* `/log_stats` `<user>` `<from_date>` `<to_date>` `<immersion_type>` - Display detailed immersion statistics with graphs. All parameters optional.

---

#### `selfmute.py`

Allows users to temporarily mute themselves for a specified duration. Users can choose from multiple mute roles and their existing roles are automatically restored when the mute expires.

Commands:
* `/selfmute` `<hours>` `<minutes>` - Mute yourself for a specified duration (max 7 days). Presents a selection menu of available mute roles.
* `/check_mute` - Check your current mute status or remove mute if the time has expired.
* `/unmute_user` `<member>` - Admin only. Remove a mute from a specified user.

Note: Requires configuration in `selfmute_settings.yml` to define mute roles and announcement channels.

---

#### `sticky_messages.py`

Allows moderators to make messages "sticky" in channels, meaning they will reappear after new messages, making the message always visible at the bottom of the channel.

Commands:
* `/sticky_last_message` - Make the last message in the channel sticky (ignoring bot commands). Requires manage messages permission by default.
* `/unsticky` - Remove the current sticky message from the channel. Requires manage messages permission by default.

---

#### `sync.py`

Manages command synchronization between the bot and Discord's command system. For authorized users only.

Commands (used with prefix):
* `sync_guild` - Sync commands to the current guild.
* `sync_global` - Sync commands globally across all guilds.
* `clear_global_commands` - Remove all global commands.
* `clear_guild_commands` - Remove all commands from the current guild.

Note: All commands require the user to be listed in the AUTHORIZED_USERS environment variable.

---

#### `username_fetcher.py`

Internal utility module that maintains a database of user IDs and usernames. Used by other modules to efficiently fetch and cache usernames.

Note: No user commands - internal utility module only.

## How to contribute

1. Report bugs and suggest features in the issues tab.

2. Create a PR with your changes. The bot is made to run server indepedently, so you can run it anywhere you want to test your changes.

## How to run

1. Clone the repository
2. Create a virtual environment and install the requirements with `pip install -r requirements.txt`
3. Create a copy of `.env.example` and rename it to `.env` in the root directory and modify the following variables:

    `TOKEN=YOUR_DISCORD_BOT_TOKEN`

    `AUTHORIZED_USERS=960526101833191435,501009840437592074` Comma separated list of user IDs who can use bot management commands.

    `DEBUG_USER=960526101833191435` User ID of the user who gets sent debug messages.

    `COMMAND_PREFIX=%`

    `PATH_TO_DB=data/db.sqlite3`

    `TMDB_API_KEY=YOUR_TMDB_API_KEY`

4. Run the bot with `python main.py`, make sure your bot has [Privledged Message Intents](https://discord.com/developers/docs/events/gateway#privileged-intents)
5. Run `%sync_global` or `%sync_guild` to create application commands within your server

## How to run on Docker

1. Clone the repository
2. Build the docker image with `docker build -t discord-tmw-bot .`
3. Create a copy of `.env.example` and rename it `.env`, modify the variables to fit your environment
4. `docker compose up -d`

## Overwrite Settings

You can link to alternative setting files by setting the path in the corresponding environment variable. 

Each part of the bot can be configured separately. Please look into the cog files for the variable names.

## Acknowledgements
This bot's base code is largely based on TMW_bot, many thanks to the TMW community for their contribution towards the JP learning communities.

This bot contains modifications to fit Jouzu Gumi's server needs and learning philosophies.
- **TMW_Bot** - Licensed under the GPL-3.0 license.
  - Original source: [https://github.com/friedrich-de/TMW_Bot](https://github.com/friedrich-de/TMW_Bot)

TMW_Bot is based on the following projects:

- **DJT-Discord Bot** - Unlicensed (Corresponding code in this project is licensed under the GPL-3.0 license).
  - Original source: [https://github.com/friedrich-de/DJT-Discord-Bot](https://github.com/friedrich-de/DJT-Discord-Bot)
- **gatekeeper** - Licensed under the GPL-3.0 license.
  - Original source: [https://github.com/themoeway/gatekeeper](https://github.com/themoeway/gatekeeper)
- **selfmutebot** - Licensed under the MIT license.
  - Original source: [https://github.com/themoeway/selfmutebot](https://github.com/themoeway/selfmutebot)
- **tmw-utility-bot** - Licensed under the GPL-3.0 license.
  - Original source: [https://github.com/themoeway/tmw-utility-bot](https://github.com/themoeway/tmw-utility-bot)
- **Immersionbot** - Licensed under the MIT license.
  - Original source: [https://github.com/themoeway/Immersionbot](https://github.com/themoeway/Immersionbot)
