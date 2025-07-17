import discord
import aiosqlite
import logging

from discord import app_commands
from discord.ext import commands
from config import client, perform_sync

from core.utils import log_command_usage, DB_PATH, only_owner, owner_check
from core.autocomplete import table_name_autocomplete, cog_autocomplete

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Admin Class
# ---------------------------------------------------------------------------------------------------------------------
class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync_all", description="Owner: Sync all slash commands to all guilds.")
    @only_owner()
    async def sync_all(self, interaction: discord.Interaction):
        if not await owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        total_commands = 0
        total_guilds = len(self.bot.guilds)

        for guild in self.bot.guilds:
            count = await perform_sync(guild=guild)
            total_commands += count

        await interaction.followup.send(
            f"Synced commands to {total_guilds} guild(s). Total commands synced: {total_commands}",
            ephemeral=True
        )

        await log_command_usage(self.bot, interaction)
    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Reset a specific table in the database")
    @only_owner()
    @app_commands.autocomplete(table_name=table_name_autocomplete)
    async def reset_table(self, interaction: discord.Interaction, table_name: str):
        if not await owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
                    (table_name,)
                )
                schema = await cursor.fetchone()
                await cursor.close()

                if not schema:
                    await interaction.followup.send(f'`Error: No table found with name {table_name}`')
                    return

                await conn.execute(f'DROP TABLE IF EXISTS {table_name}')
                await conn.execute(schema[0])
                await conn.commit()

            await interaction.followup.send(f'`Success: {table_name} table has been reset`')
        except Exception as e:
            logger.exception("Error in reset_table")
            await interaction.followup.send(f'`Error: Failed to reset {table_name} table. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Delete a specific table from the database")
    @only_owner()
    @app_commands.autocomplete(table_name=table_name_autocomplete)
    async def delete_table(self, interaction: discord.Interaction, table_name: str):
        if not await owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                    (table_name,)
                )
                exists = await cursor.fetchone()
                await cursor.close()

                if not exists:
                    await interaction.followup.send(f'`Error: No table found with name {table_name}`')
                    return

                await conn.execute(f'DROP TABLE IF EXISTS {table_name}')
                await conn.commit()

            await interaction.followup.send(f'`Success: {table_name} table has been deleted`')
        except Exception as e:
            logger.exception("Error in delete_table")
            await interaction.followup.send(f'`Error: Failed to delete {table_name} table. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Load a Cog")
    @only_owner()
    @app_commands.autocomplete(extension=cog_autocomplete)
    async def load(self, interaction: discord.Interaction, extension: str):
        if not await owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            await client.load_extension(f'cogs.{extension}')
            await interaction.followup.send(f'`Success: Loaded {extension}`')
            await perform_sync()
        except Exception as e:
            logger.exception("Error in load")
            await interaction.followup.send(f'`Error: Failed to load {extension}. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Unload a Cog")
    @only_owner()
    @app_commands.autocomplete(extension=cog_autocomplete)
    async def unload(self, interaction: discord.Interaction, extension: str):
        if not await owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            await client.unload_extension(f'cogs.{extension}')
            await interaction.followup.send(f'`Success: Unloaded {extension}`')
        except Exception as e:
            logger.exception("Error in unload")
            await interaction.followup.send(f'`Error: Failed to unload {extension}. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="reload", description="Owner: Reload a Cog")
    @only_owner()
    @app_commands.autocomplete(extension=cog_autocomplete)
    async def reload(self, interaction: discord.Interaction, extension: str):
        if not await owner_check(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            await client.unload_extension(f'cogs.{extension}')
            await client.load_extension(f'cogs.{extension}')
            await interaction.followup.send(f'Reloaded {extension}.')
            await perform_sync()
        except Exception as e:
            logger.exception("Error in reload")
            await interaction.followup.send(f'`Error: Failed to reload {extension}. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(AdminCog(bot))
