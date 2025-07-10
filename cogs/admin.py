import discord
import aiosqlite
import logging

from discord import app_commands
from discord.ext import commands
from config import client, perform_sync, OWNER_ID
from core.utils import log_command_usage, check_permissions, get_embed_colour, DB_PATH


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

    async def owner_check(self, interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Reset a specific table in the database")
    async def reset_table(self, interaction: discord.Interaction, table_name: str):
        await interaction.response.defer()
        try:
            if not await self.owner_check(interaction):
                await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
                return

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
            await interaction.followup.send(f'`Error: Failed to reset {table_name} table. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Delete a specific table from the database")
    async def delete_table(self, interaction: discord.Interaction, table_name: str):
        await interaction.response.defer()
        try:
            if not await self.owner_check(interaction):
                await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
                return

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
            await interaction.followup.send(f'`Error: Failed to delete {table_name} table. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Load a Cog")
    async def load(self, interaction: discord.Interaction, extension: str):
        await interaction.response.defer()
        try:
            if not await self.owner_check(interaction):
                await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
                return

            await client.load_extension(f'cogs.{extension}')
            await interaction.followup.send(f'`Success: Loaded {extension}`')
            await perform_sync()
        except Exception as e:
            await interaction.followup.send(f'`Error: Failed to load {extension}. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Unload a Cog")
    async def unload(self, interaction: discord.Interaction, extension: str):
        await interaction.response.defer()
        try:
            if not await self.owner_check(interaction):
                await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
                return

            await client.unload_extension(f'cogs.{extension}')
            await interaction.followup.send(f'`Success: Unloaded {extension}`')
        except Exception as e:
            await interaction.followup.send(f'`Error: Failed to unload {extension}. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Reload a Cog")
    async def reload(self, interaction: discord.Interaction, extension: str):
        await interaction.response.defer()
        try:
            if not await self.owner_check(interaction):
                await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
                return

            await client.unload_extension(f'cogs.{extension}')
            await client.load_extension(f'cogs.{extension}')
            await interaction.followup.send(f'Reloaded {extension}.')
            await perform_sync()
        except Exception as e:
            await interaction.followup.send(f'`Error: Failed to reload {extension}. {str(e)}`')
        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(AdminCog(bot))