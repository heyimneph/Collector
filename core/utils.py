import discord
import os
import logging
import aiosqlite
from functools import wraps
from discord.ui import View, Button

# ---------------------------------------------------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------------------------------------------------
DB_DIR = os.path.join('data', 'databases')
DB_PATH = os.path.join(DB_DIR, 'collector.db')
os.makedirs(DB_DIR, exist_ok=True)

def get_db_path() -> str:
    """Return the location of the bot's SQLite database."""
    return DB_PATH

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Get Embed Colour
# ---------------------------------------------------------------------------------------------------------------------
async def get_embed_colour(guild_id):
    try:
        guild_id = int(guild_id)
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute(
                'SELECT value FROM customisation WHERE type = ? AND guild_id = ?',
                ("embed_color", guild_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return int(row[0], 16)
    except Exception as e:
        logger.error(f"Failed to retrieve custom embed color: {e}")

    return 0xc4a7ec  # fallback default (light purple)


# ---------------------------------------------------------------------------------------------------------------------
# Command Logging
# ---------------------------------------------------------------------------------------------------------------------
async def log_command_usage(bot, interaction):
    try:
        # Check if interaction.command is None
        if interaction.command is None:
            logger.error("Interaction does not have a valid command associated with it.")
            return

        # Extract command options
        command_options = ""
        if 'options' in interaction.data:
            for option in interaction.data['options']:
                command_options += f"{option['name']}: {option.get('value', 'Not provided')}\n"

        user = interaction.user
        guild = interaction.guild
        channel = interaction.channel

        log_channel = None

        if guild:
            async with aiosqlite.connect(DB_PATH) as conn:
                logger.info(f"Connected to the database at {DB_PATH}")
                async with conn.execute(
                    'SELECT log_channel_id FROM config WHERE guild_id = ?', (guild.id,)
                ) as cursor:
                    row = await cursor.fetchone()

                    if row and row[0]:
                        try:
                            log_channel = bot.get_channel(int(row[0]))
                        except (TypeError, ValueError):
                            logger.warning(f"Invalid log_channel_id for guild {guild.id}: {row[0]}")

                if not log_channel:
                    logger.info(f"Checking for fallback channel 'collector_logs' in guild {guild.id}")
                    log_channel = discord.utils.get(guild.text_channels, name='collector_logs')

        # Construct and send embed if we have a destination
        if log_channel:
            embed = discord.Embed(
                description=f"Command: `{interaction.command.name}`",
                color=discord.Color.blue()
            )
            embed.add_field(name="User", value=user.mention if user else "Unknown", inline=True)
            embed.add_field(name="Guild ID", value=guild.id if guild else "DM", inline=True)
            embed.add_field(name="Channel", value=channel.mention if channel else "DM", inline=True)
            if command_options:
                embed.add_field(name="Command Options", value=command_options.strip(), inline=False)

            embed.set_footer(text=f"User ID: {user.id if user else 'Unknown'}")
            embed.set_author(name=str(user), icon_url=user.display_avatar.url if user else discord.Embed.Empty)
            embed.timestamp = discord.utils.utcnow()

            await log_channel.send(embed=embed)
        else:
            logger.info(f"No log channel found for command '{interaction.command.name}' in guild {guild.id if guild else 'DM'}.")

    except aiosqlite.Error as e:
        logger.error(f"SQLite error while logging command: {e}")
    except Exception as e:
        command_name = interaction.command.name if interaction.command else "Unknown"
        logger.error(f"Unexpected error logging command usage for '{command_name}': {e}")
        logger.error(f"Interaction data: {interaction.data}")

# ---------------------------------------------------------------------------------------------------------------------
# Permissions Check
# ---------------------------------------------------------------------------------------------------------------------
async def check_permissions(interaction):
    if interaction.user.guild_permissions.administrator:
        return True

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute('''
            SELECT can_use_commands FROM permissions WHERE guild_id = ? AND user_id = ?
        ''', (interaction.guild_id, interaction.user.id))
        permission = await cursor.fetchone()
        return permission and permission[0]





