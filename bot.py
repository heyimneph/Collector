import os
import discord
import asyncio
import logging
from config import client, DISCORD_TOKEN, perform_sync, TEST_GUILD_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------------------------
# Sync on Ready
# ---------------------------------------------------------------------------------------------------------------------
@client.event
async def on_ready():
    logger.info(f"Bot logged in as {client.user} (ID: {client.user.id})")

    if TEST_GUILD_ID and not hasattr(client, "synced"):
        try:
            await perform_sync(guild=discord.Object(id=TEST_GUILD_ID))
            client.synced = True
            logger.info(f"Synced slash commands to test guild: {TEST_GUILD_ID}")
        except Exception as e:
            logger.exception(f"Failed to sync commands to test guild {TEST_GUILD_ID}: {e}")


# ---------------------------------------------------------------------------------------------------------------------
# Sync on Guild Join
# ---------------------------------------------------------------------------------------------------------------------
@client.event
async def on_guild_join(guild: discord.Guild):
    try:
        await perform_sync(guild=guild)
        logger.info(f"Auto-synced commands to new guild: {guild.name} ({guild.id})")
    except Exception as e:
        logger.exception(f"Failed to sync on guild join for {guild.id}: {e}")


# ---------------------------------------------------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------------------------------------------------
async def main():
    try:
        await client.load_extension("core.initialisation")
        logger.info("Loaded core.initialisation")

        for filename in os.listdir("cogs"):
            if filename.endswith(".py"):
                await client.load_extension(f"cogs.{filename[:-3]}")
                logger.info(f"Loaded cog: {filename[:-3]}")

        logger.info("Starting bot...")
        await client.start(DISCORD_TOKEN)

    except Exception as e:
        logger.exception(f"Unhandled exception during startup: {e}")


if __name__ == "__main__":
    asyncio.run(main())
