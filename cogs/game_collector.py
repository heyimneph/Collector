import discord
import aiosqlite
import random
import logging

from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from collections import defaultdict

from core.utils import DB_PATH, get_embed_colour, log_command_usage, check_permissions

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------------------------------------
# Game Buttons
# -----------------------------------------------------------------------------------------------------------------
class ItemView(discord.ui.View):
    def __init__(self, author_id: int, bot: commands.Bot):
        super().__init__(timeout=None)
        self.claimed = False
        self.bot = bot

    async def disable_all(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if self.claimed:
                await interaction.response.send_message("This item has already been collected or destroyed!", ephemeral=True)
                return

            self.claimed = True
            await self.disable_all()

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    INSERT INTO item_stats (guild_id, user_id, items_collected)
                    VALUES (?, ?, 1)
                    ON CONFLICT(guild_id, user_id)
                    DO UPDATE SET items_collected = items_collected + 1
                ''', (interaction.guild.id, interaction.user.id))

                cursor = await conn.execute("SELECT claim_text FROM item_settings WHERE guild_id = ?", (interaction.guild.id,))
                row = await cursor.fetchone()
                claim_text = row[0] if row else "{user} claimed it!"

                await conn.commit()

            embed = interaction.message.embeds[0]
            embed.description = claim_text.replace("{user}", interaction.user.mention)
            embed.color = discord.Color.green()
            embed.set_footer(text="Nice one!")
            embed.timestamp = discord.utils.utcnow()

            await interaction.response.edit_message(embed=embed, view=self)
            logger.info(f"{interaction.user} claimed an item in guild {interaction.guild.id}")

        except Exception as e:
            logger.exception(f"Error while claiming item in guild {interaction.guild.id}")
            await interaction.response.send_message("Something went wrong while claiming the item.", ephemeral=True)

    @discord.ui.button(label="Destroy", style=discord.ButtonStyle.danger)
    async def destroy(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if self.claimed:
                await interaction.response.send_message("This item has already been collected or destroyed!", ephemeral=True)
                return

            self.claimed = True
            await self.disable_all()

            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute("SELECT destroy_text FROM item_settings WHERE guild_id = ?", (interaction.guild.id,))
                row = await cursor.fetchone()
                destroy_text = row[0] if row else "{user} destroyed it!"

            embed = interaction.message.embeds[0]
            embed.description = destroy_text.replace("{user}", interaction.user.mention)
            embed.color = discord.Color.red()
            embed.set_footer(text="...why?")
            embed.timestamp = discord.utils.utcnow()

            await interaction.response.edit_message(embed=embed, view=self)
            logger.info(f"{interaction.user} destroyed an item in guild {interaction.guild.id}")

        except Exception as e:
            logger.exception(f"Error while destroying item in guild {interaction.guild.id}")
            await interaction.response.send_message("Something went wrong while destroying the item.", ephemeral=True)


# -----------------------------------------------------------------------------------------------------------------
# Leaderboard View
# -----------------------------------------------------------------------------------------------------------------
class LeaderboardView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.global_view = False

    async def start(self, interaction: discord.Interaction):
        try:
            embed = await self.build_leaderboard_embed(interaction)
            await interaction.response.send_message(embed=embed, view=self)
            logger.info(f"{interaction.user} opened local leaderboard in guild {interaction.guild.id}")
        except Exception as e:
            logger.exception("Error while sending leaderboard.")
            await interaction.response.send_message("Failed to display leaderboard.", ephemeral=True)

    @discord.ui.button(label="🌐 View Global", style=discord.ButtonStyle.secondary)
    async def toggle_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.global_view = not self.global_view
            button.label = "🏠 View Local" if self.global_view else "🌐 View Global"
            embed = await self.build_leaderboard_embed(interaction)
            await interaction.response.edit_message(embed=embed, view=self)
            logger.info(f"{interaction.user} toggled to {'global' if self.global_view else 'local'} leaderboard in guild {interaction.guild.id}")
        except Exception as e:
            logger.exception("Error toggling leaderboard view.")
            await interaction.response.send_message("Failed to update leaderboard view.", ephemeral=True)

    async def build_leaderboard_embed(self, interaction: discord.Interaction) -> discord.Embed:
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                if self.global_view:
                    query = '''
                        SELECT user_id, SUM(items_collected)
                        FROM item_stats
                        GROUP BY user_id
                        ORDER BY SUM(items_collected) DESC
                        LIMIT 10
                    '''
                    params = ()
                else:
                    query = '''
                        SELECT user_id, items_collected
                        FROM item_stats
                        WHERE guild_id = ?
                        ORDER BY items_collected DESC
                        LIMIT 10
                    '''
                    params = (self.guild_id,)

                cursor = await conn.execute(query, params)
                rows = await cursor.fetchall()

            if not rows:
                desc = "No one has collected anything yet!" if not self.global_view else "No global collections yet!"
            else:
                desc = ""
                for i, (user_id, total) in enumerate(rows, 1):
                    user = interaction.guild.get_member(user_id) or self.bot.get_user(user_id)
                    name = user.display_name if isinstance(user, discord.Member) else (user.name if user else f"<@{user_id}>")
                    desc += f"**{i}.** {name} — `{total}`\n"

            embed = discord.Embed(
                title="🌐 Global Leaderboard" if self.global_view else "🏠 Local Leaderboard",
                description=desc,
                color=await get_embed_colour(self.guild_id)
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.set_footer(text="Top Collectors!")
            embed.timestamp = discord.utils.utcnow()
            return embed

        except Exception as e:
            logger.exception("Error building leaderboard embed.")
            return discord.Embed(description="Failed to load leaderboard.", color=discord.Color.red())

# -----------------------------------------------------------------------------------------------------------------
# Game Class
# -----------------------------------------------------------------------------------------------------------------
class ItemDrop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.next_drop_times = defaultdict(lambda: datetime.utcnow())

    def cog_unload(self):
        try:
            self.item_drop_task.cancel()
            logger.info("ItemDrop cog unloaded and task cancelled.")
        except Exception:
            logger.exception("Error during cog_unload.")

    @commands.Cog.listener()
    async def on_ready(self):
        if hasattr(self.bot, '_itemdrop_started'):
            return

        self.bot._itemdrop_started = True
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                for guild in self.bot.guilds:
                    await conn.execute('''
                        INSERT OR IGNORE INTO item_settings (guild_id, drop_channel_id, message, image_url, claim_text, destroy_text)
                        VALUES (?, NULL, 'An item has appeared! Press a button!',
                        'https://imgur.com/CoVltbo.png', '{user} claimed it!', '{user} destroyed it!')
                    ''', (guild.id,))
                    self.next_drop_times[guild.id] = datetime.utcnow() + timedelta(minutes=random.randint(15, 60))

                await conn.commit()

            logger.info("ItemDrop initialized with randomized drop times for all guilds.")
            self.item_drop_task.start()

        except Exception:
            logger.exception("Error initializing ItemDrop during on_ready.")

    @tasks.loop(seconds=30)
    async def item_drop_task(self):
        logger.info(f"[Tick] item_drop_task at {datetime.utcnow()}")

        for guild in self.bot.guilds:
            try:
                if random.randint(1, 120) != 1:
                    continue

                async with aiosqlite.connect(DB_PATH) as conn:
                    cursor = await conn.execute('''
                        SELECT drop_channel_id, message, image_url
                        FROM item_settings WHERE guild_id = ?
                    ''', (guild.id,))
                    settings = await cursor.fetchone()

                channel_id, message_text, image_url = (None, "An item has appeared!", "")
                if settings:
                    channel_id, msg, img = settings
                    message_text = msg or message_text
                    image_url = img or ""

                bot_member = guild.me or guild.get_member(self.bot.user.id)
                if not bot_member:
                    logger.warning(f"Bot member not found in guild {guild.id}")
                    continue

                if not channel_id:
                    valid = [c for c in guild.text_channels if c.permissions_for(bot_member).send_messages]
                    channel = random.choice(valid) if valid else None
                else:
                    channel = self.bot.get_channel(channel_id)

                if not channel:
                    logger.warning(f"No valid channel found for guild {guild.id} (drop_channel_id: {channel_id})")
                    continue

                if not channel.permissions_for(bot_member).send_messages:
                    logger.warning(f"Missing send permission in channel {channel.id} for guild {guild.id}")
                    continue

                colour = await get_embed_colour(guild.id)
                embed = discord.Embed(description=message_text, color=colour)
                embed.timestamp = discord.utils.utcnow()
                if image_url:
                    embed.set_image(url=image_url)

                await channel.send(embed=embed, view=ItemView(author_id=self.bot.user.id, bot=self.bot))
                logger.info(f"[DROP] Item dropped in guild {guild.id} in channel {channel.id}")

            except Exception:
                logger.exception(f"Error during item drop for guild {guild.id}")

    @item_drop_task.before_loop
    async def before_item_drop_task(self):
        try:
            await self.bot.wait_until_ready()
            logger.info("ItemDrop task is waiting until bot is ready.")
        except Exception:
            logger.exception("Error during before_item_drop_task")

# -----------------------------------------------------------------------------------------------------------------
# Game Commands
# -----------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Admin: Set the channel for item drops.")
    async def set_item_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    INSERT INTO item_settings (guild_id, drop_channel_id)
                    VALUES (?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET drop_channel_id = excluded.drop_channel_id
                ''', (interaction.guild.id, channel.id))
                await conn.commit()

            logger.info(f"Set item drop channel to {channel.id} in guild {interaction.guild.id}")
            await interaction.response.send_message(f"Drop channel set to {channel.mention}.", ephemeral=True)

        except Exception:
            logger.exception("Failed to set item drop channel.")
            await interaction.response.send_message("Failed to set drop channel.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the drop message text.")
    async def set_item_message(self, interaction: discord.Interaction, message: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET message = ? WHERE guild_id = ?', (message, interaction.guild.id))
                await conn.commit()

            logger.info(f"Updated item message in guild {interaction.guild.id}: {message}")
            await interaction.response.send_message("Drop message updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update item message.")
            await interaction.response.send_message("Failed to update message.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the image URL for item drops.")
    async def set_item_image(self, interaction: discord.Interaction, image_url: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET image_url = ? WHERE guild_id = ?', (image_url, interaction.guild.id))
                await conn.commit()

            logger.info(f"Updated item image URL in guild {interaction.guild.id}: {image_url}")
            await interaction.response.send_message("Image URL updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update image URL.")
            await interaction.response.send_message("Failed to update image URL.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the text shown when someone claims the item.")
    async def set_claim_text(self, interaction: discord.Interaction, text: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET claim_text = ? WHERE guild_id = ?', (text, interaction.guild.id))
                await conn.commit()

            logger.info(f"Updated claim text in guild {interaction.guild.id}: {text}")
            await interaction.response.send_message("Claim text updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update claim text.")
            await interaction.response.send_message("Failed to update claim text.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the text shown when someone destroys the item.")
    async def set_destroy_text(self, interaction: discord.Interaction, text: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET destroy_text = ? WHERE guild_id = ?', (text, interaction.guild.id))
                await conn.commit()

            logger.info(f"Updated destroy text in guild {interaction.guild.id}: {text}")
            await interaction.response.send_message("Destroy text updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update destroy text.")
            await interaction.response.send_message("Failed to update destroy text.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="User: Show the top collectors in this server or globally.")
    async def leaderboard(self, interaction: discord.Interaction):
        try:
            view = LeaderboardView(self.bot, interaction.guild.id)
            await view.start(interaction)
            logger.info(f"{interaction.user} used /leaderboard in guild {interaction.guild.id}")
        except Exception:
            logger.exception("Failed to show leaderboard.")
            await interaction.response.send_message("Failed to show leaderboard.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

# -----------------------------------------------------------------------------------------------------------------
# Listeners
# -----------------------------------------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    INSERT OR IGNORE INTO item_settings (guild_id, drop_channel_id, message, image_url, claim_text, destroy_text)
                    VALUES (?, NULL, 'An item has appeared! Press a button!',
                            'https://example.com/item.png', '{user} claimed it!', '{user} destroyed it!')
                ''', (guild.id,))
                await conn.commit()

            logger.info(f"Initialized item_settings for new guild {guild.id}")

        except Exception:
            logger.exception(f"Failed to initialize settings for new guild {guild.id}")


# ---------------------------------------------------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS item_settings (
                guild_id INTEGER PRIMARY KEY,
                drop_channel_id INTEGER,
                message TEXT,
                image_url TEXT,
                claim_text TEXT,
                destroy_text TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS item_stats (
                guild_id INTEGER,
                user_id INTEGER,
                items_collected INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')
        await conn.commit()

    logger.info("ItemDrop setup completed. Tables ensured.")
    await bot.add_cog(ItemDrop(bot))
