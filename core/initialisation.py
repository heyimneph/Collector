import discord
import logging

from discord.ext import commands
from core.utils import get_bio_settings

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------------------------
# BotCore Class
# ---------------------------------------------------------------------------------------------------------------------
class BotCore(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'Logged on as {self.bot.user}...')

        activity_type, bio = await get_bio_settings()
        if not (activity_type and bio):
            logger.warning("No activity type or bio found in database.")
            return

        activity_type = activity_type.lower()
        if activity_type == "playing":
            activity = discord.Game(name=bio)
        elif activity_type == "listening":
            activity = discord.Activity(type=discord.ActivityType.listening, name=bio)
        elif activity_type == "watching":
            activity = discord.Activity(type=discord.ActivityType.watching, name=bio)
        else:
            logger.warning(f"Invalid activity type in DB: {activity_type}")
            return

        await self.bot.change_presence(activity=activity)


# ----------------------------------------------------------------------------------------------------------------------
# Setup Function
# ----------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(BotCore(bot))
