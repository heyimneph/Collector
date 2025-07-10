import discord
import datetime
import aiosqlite
import logging

from discord import app_commands
from discord.ext import commands

from config import client
from core.utils import DB_PATH

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)


class TheMachineBotCore(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

#  ---------------------------------------------------------------------------------------------------------
#  ---------------------------------------------------------------------------------------------------------
#  ---------------------------------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'Logged on as {self.bot.user}...')
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute('SELECT value FROM customisation WHERE type = ?', ("activity_type",)) as cursor:
                activity_type_doc = await cursor.fetchone()
            async with conn.execute('SELECT value FROM customisation WHERE type = ?', ("bio",)) as cursor:
                bio_doc = await cursor.fetchone()

        if activity_type_doc and bio_doc:
            activity_type = activity_type_doc[0]
            bio = bio_doc[0]

            if activity_type.lower() == "playing":
                activity = discord.Game(name=bio)
            elif activity_type.lower() == "listening":
                activity = discord.Activity(type=discord.ActivityType.listening, name=bio)
            elif activity_type.lower() == "watching":
                activity = discord.Activity(type=discord.ActivityType.watching, name=bio)
            else:
                print("Invalid activity type in database")
                return

            await client.change_presence(activity=activity)


#  ---------------------------------------------------------------------------------------------------------------------
#  ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    await bot.add_cog(TheMachineBotCore(bot))