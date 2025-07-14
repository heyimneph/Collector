import discord
import aiosqlite
import random
import logging
import math

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

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="item_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if self.claimed:
                await interaction.response.send_message("This item has already been collected or destroyed!",
                                                        ephemeral=True)
                return

            self.claimed = True
            await self.disable_all()

            # Determine if it's a rare drop
            embed = interaction.message.embeds[0]
            is_rare = embed.author and "RARE DROP" in embed.author.name if embed.author else False

            async with aiosqlite.connect(DB_PATH) as conn:
                if is_rare:
                    await conn.execute('''
                        INSERT INTO item_stats (guild_id, user_id, items_collected, rare_drops_claimed)
                        VALUES (?, ?, 1, 1)
                        ON CONFLICT(guild_id, user_id)
                        DO UPDATE SET 
                            items_collected = items_collected + 1,
                            rare_drops_claimed = rare_drops_claimed + 1
                    ''', (interaction.guild.id, interaction.user.id))
                else:
                    await conn.execute('''
                        INSERT INTO item_stats (guild_id, user_id, items_collected)
                        VALUES (?, ?, 1)
                        ON CONFLICT(guild_id, user_id)
                        DO UPDATE SET items_collected = items_collected + 1
                    ''', (interaction.guild.id, interaction.user.id))

                cursor = await conn.execute(
                    "SELECT claim_text, claim_image_url, rare_role_id FROM item_settings WHERE guild_id = ?",
                    (interaction.guild.id,)
                )
                row = await cursor.fetchone()
                claim_text = row[0] if row else "{user} claimed it!"
                claim_image = row[1] if row and row[1] else None
                rare_role_id = row[2] if row and len(row) > 2 else None

                await conn.commit()

            # Update embed
            embed.description = claim_text.replace("{user}", interaction.user.mention)
            embed.color = discord.Color.green()
            embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            embed.timestamp = discord.utils.utcnow()
            if claim_image:
                embed.set_image(url=claim_image)

            await interaction.response.edit_message(embed=embed, view=self)

            # Grant rare role if it's a rare drop and a role is configured
            if is_rare and rare_role_id:
                role = interaction.guild.get_role(rare_role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Claimed rare drop")
                        logger.info(f"Gave rare role {role.id} to {interaction.user} in guild {interaction.guild.id}")
                    except discord.Forbidden:
                        logger.warning(f"Missing permission to assign role {role.id} in guild {interaction.guild.id}")
                    except Exception as e:
                        logger.exception(f"Unexpected error assigning rare role: {e}")

            logger.info(f"{interaction.user} claimed an item in guild {interaction.guild.id}")

        except Exception as e:
            logger.exception(f"Error while claiming item in guild {interaction.guild.id}")
            await interaction.response.send_message("Something went wrong while claiming the item.", ephemeral=True)

    @discord.ui.button(label="Destroy", style=discord.ButtonStyle.danger, custom_id="item_destroy")
    async def destroy(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if self.claimed:
                await interaction.response.send_message("This item has already been collected or destroyed!",
                                                        ephemeral=True)
                return

            self.claimed = True
            await self.disable_all()

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    INSERT INTO item_stats (guild_id, user_id, items_destroyed)
                    VALUES (?, ?, 1)
                    ON CONFLICT(guild_id, user_id)
                    DO UPDATE SET items_destroyed = items_destroyed + 1
                ''', (interaction.guild.id, interaction.user.id))

                cursor = await conn.execute(
                    "SELECT destroy_text, destroy_image_url FROM item_settings WHERE guild_id = ?",
                    (interaction.guild.id,)
                )
                row = await cursor.fetchone()
                destroy_text = row[0] if row else "{user} destroyed it!"
                destroy_image = row[1] if row and row[1] else None

                await conn.commit()

            embed = interaction.message.embeds[0]
            embed.description = destroy_text.replace("{user}", interaction.user.mention)
            embed.color = discord.Color.red()
            embed.set_footer(text=f"Destroyed by {interaction.user.display_name}")
            embed.timestamp = discord.utils.utcnow()

            if destroy_image:
                embed.set_image(url=destroy_image)

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
        self.drop_chance_denominator = 120

        self.bot = bot
        self.next_drop_times = defaultdict(lambda: datetime.utcnow())
        self.start_time = datetime.utcnow()

    def cog_unload(self):
        try:
            self.item_drop_task.cancel()
            logger.info("ItemDrop cog unloaded and task cancelled.")
        except Exception:
            logger.exception("Error during cog_unload.")

    @commands.Cog.listener()
    async def on_ready(self):
        if not hasattr(self.bot, '_itemdrop_started'):
            self.bot._itemdrop_started = True

            try:
                # Register persistent button view (needed across restarts)
                self.bot.add_view(ItemView(bot=self.bot, author_id=self.bot.user.id))
                logger.info("ItemView registered for persistent button support.")

                async with aiosqlite.connect(DB_PATH) as conn:
                    # Ensure config table and default drop chance exist
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS item_config (
                            key TEXT PRIMARY KEY,
                            value TEXT
                        )
                    ''')
                    await conn.execute('''
                        INSERT OR IGNORE INTO item_config (key, value)
                        VALUES ('drop_chance_denominator', '120')
                    ''')

                    # Load current drop chance
                    cursor = await conn.execute("SELECT value FROM item_config WHERE key = 'drop_chance_denominator'")
                    row = await cursor.fetchone()
                    self.drop_chance_denominator = int(row[0]) if row else 120
                    logger.info(f"Loaded drop chance denominator: 1 in {self.drop_chance_denominator}")

                    # Ensure default item_settings for all guilds
                    for guild in self.bot.guilds:
                        await conn.execute('''
                            INSERT OR IGNORE INTO item_settings (
                                guild_id, drop_channel_id, message, image_url,
                                claim_text, destroy_text, claim_image_url, destroy_image_url,
                                rare_message, rare_image_url, rare_role_id, drop_expiry_minutes
                            ) VALUES (?, NULL,
                                'Something dropped! Claim it or Destroy it!',
                                'https://imgur.com/VZtZTOm.png',
                                '{user} claimed it!',
                                '{user} destroyed it!',
                                'https://imgur.com/VZtZTOm.png',
                                'https://imgur.com/UtVm1W9.png',
                                'A rare item has appeared! Be the first to claim it!',
                                'https://imgur.com/GLszyDB.png',
                                NULL,
                                30
                            )
                        ''', (guild.id,))

                    await conn.commit()

                # Start background tasks
                self.item_drop_task.start()
                self.cleanup_expired_drops.start()
                logger.info("ItemDrop and cleanup tasks started.")
                logger.info("ItemDrop initialized for all joined guilds.")

            except Exception:
                logger.exception("Error initializing ItemDrop during on_ready.")

    @tasks.loop(seconds=180)
    async def item_drop_task(self):
        logger.info(f"[Tick] item_drop_task at {datetime.utcnow()}")

        for guild in self.bot.guilds:
            try:
                if random.randint(1, self.drop_chance_denominator) != 1:
                    continue

                # Determine drop type: 1 in 50 chance to make it rare
                drop_type = "normal"
                if random.randint(1, 50) == 1:
                    drop_type = "rare"

                async with aiosqlite.connect(DB_PATH) as conn:
                    cursor = await conn.execute('''
                        SELECT drop_channel_id, message, image_url,
                               rare_message, rare_image_url
                        FROM item_settings WHERE guild_id = ?
                    ''', (guild.id,))
                    settings = await cursor.fetchone()

                channel_id = None
                if settings:
                    (channel_id, msg, img, rare_msg, rare_img) = settings
                    if drop_type == "rare":
                        message_text = rare_msg or "✨ A rare item has appeared! Be the first to claim it!"
                        image_url = rare_img or "https://imgur.com/RgP7g0K.png"
                    else:
                        message_text = msg or "An item has appeared!"
                        image_url = img or ""
                else:
                    message_text = "An item has appeared!"
                    image_url = ""

                bot_member = guild.me or guild.get_member(self.bot.user.id)
                if not bot_member:
                    logger.warning(f"Bot member not found in guild {guild.id}")
                    continue

                if not channel_id:
                    valid = [c for c in guild.text_channels if c.permissions_for(bot_member).send_messages]
                    channel = random.choice(valid) if valid else None
                else:
                    channel = self.bot.get_channel(channel_id)

                if not channel or not channel.permissions_for(bot_member).send_messages:
                    logger.warning(f"Cannot drop item in guild {guild.id}.")
                    continue

                colour = await get_embed_colour(guild.id)
                embed = discord.Embed(description=message_text, color=colour)
                embed.timestamp = discord.utils.utcnow()
                if image_url:
                    embed.set_image(url=image_url)
                if drop_type == "rare":
                    embed.set_author(name="RARE DROP", icon_url="https://imgur.com/RgP7g0K.png")

                view = ItemView(author_id=self.bot.user.id, bot=self.bot)
                message = await channel.send(embed=embed, view=view)

                async with aiosqlite.connect(DB_PATH) as conn:
                    await conn.execute('''
                        INSERT OR IGNORE INTO active_drops (message_id, guild_id, channel_id, drop_time)
                        VALUES (?, ?, ?, ?)
                    ''', (message.id, guild.id, channel.id, datetime.utcnow().isoformat()))
                    await conn.commit()

                logger.info(f"[DROP-{drop_type.upper()}] Item dropped in guild {guild.id} in channel {channel.id}")

            except Exception:
                logger.exception(f"Error during item drop for guild {guild.id}")

    @tasks.loop(minutes=1)
    async def cleanup_expired_drops(self):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                # Load all drop_expiry_minutes settings
                cursor = await conn.execute("SELECT guild_id, drop_expiry_minutes FROM item_settings")
                guild_expiries = {gid: expiry or 30 for gid, expiry in await cursor.fetchall()}

                # Load all active drops
                cursor = await conn.execute("SELECT message_id, guild_id, channel_id, drop_time FROM active_drops")
                rows = await cursor.fetchall()

                expired = []
                now = datetime.utcnow()

                for message_id, guild_id, channel_id, drop_time_str in rows:
                    drop_time = datetime.fromisoformat(drop_time_str)
                    expiry_minutes = guild_expiries.get(guild_id, 30)
                    if drop_time + timedelta(minutes=expiry_minutes) <= now:
                        expired.append((message_id, guild_id, channel_id))

                # Try to delete messages and clean up records
                for message_id, guild_id, channel_id in expired:
                    guild = self.bot.get_guild(guild_id)
                    channel = guild.get_channel(channel_id) if guild else None
                    if not channel:
                        continue
                    try:
                        msg = await channel.fetch_message(message_id)
                        await msg.delete()
                        logger.info(f"[CLEANUP] Deleted expired item in guild {guild_id}, channel {channel_id}")
                    except Exception:
                        logger.warning(f"[CLEANUP] Failed to delete message {message_id} in guild {guild_id}")

                if expired:
                    ids = [msg_id for msg_id, *_ in expired]
                    await conn.executemany("DELETE FROM active_drops WHERE message_id = ?", [(mid,) for mid in ids])
                    await conn.commit()

        except Exception:
            logger.exception("Error during expired item cleanup task.")

    @item_drop_task.before_loop
    async def before_item_drop_task(self):
        try:
            await self.bot.wait_until_ready()
            logger.info("ItemDrop task is waiting until bot is ready.")
        except Exception:
            logger.exception("Error during before_item_drop_task")

    @cleanup_expired_drops.before_loop
    async def before_cleanup_expired_drops(self):
        try:
            await self.bot.wait_until_ready()
            logger.info("Cleanup task is waiting until bot is ready.")
        except Exception:
            logger.exception("Error during before_cleanup_expired_drops")

# -----------------------------------------------------------------------------------------------------------------
# Game Commands
# -----------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Owner: Set the 1-in-X drop chance")
    async def set_drop_chance(self, interaction: discord.Interaction, chance: int):
        owner_id = self.bot.owner_id or (await self.bot.application_info()).owner.id
        if interaction.user.id != owner_id:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        if chance < 1 or chance > 1000:
            await interaction.response.send_message("Please provide a value between 1 and 1000.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('''
                INSERT INTO item_config (key, value)
                VALUES ('drop_chance_denominator', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            ''', (str(chance),))
            await conn.commit()

        self.drop_chance_denominator = chance
        logger.info(f"Drop chance updated to 1 in {chance} by {interaction.user}.")
        await interaction.response.send_message(f"Drop chance updated to `1 in {chance}`.", ephemeral=True)

    @app_commands.command(description="Admin: Set how long (in minutes) item drops last before auto-deletion.")
    @app_commands.describe(minutes="Expiration time in minutes (5–1440)")
    async def set_expiry_time(self, interaction: discord.Interaction, minutes: int):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        if minutes < 5 or minutes > 1440:
            await interaction.response.send_message("Please choose a value between 5 and 1440 (24h).", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute(
                    "UPDATE item_settings SET drop_expiry_minutes = ? WHERE guild_id = ?",
                    (minutes, interaction.guild.id)
                )
                await conn.commit()

            await interaction.response.send_message(f"Drops will now expire after `{minutes}` minutes.", ephemeral=True)
            logger.info(f"Set drop expiry to {minutes} for guild {interaction.guild.id}")
        except Exception:
            logger.exception("Failed to set drop expiry.")
            await interaction.response.send_message("Failed to set drop expiry time.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # -----------------------------------------------------------------------------------------------------------------

    @app_commands.command(description="Admin: Set the channel for item drops.")
    async def set_drop_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
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
    async def set_default_message(self, interaction: discord.Interaction, message: str):
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
    async def set_default_image(self, interaction: discord.Interaction, image_url: str):
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

    # -----------------------------------------------------------------------------------------------------------------

    @app_commands.command(description="Admin: Set image shown when someone claims the item.")
    async def set_claim_image(self, interaction: discord.Interaction, image_url: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET claim_image_url = ? WHERE guild_id = ?',
                                   (image_url, interaction.guild.id))
                await conn.commit()

            logger.info(f"Updated claim image URL in guild {interaction.guild.id}: {image_url}")
            await interaction.response.send_message("Claim image URL updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update claim image URL.")
            await interaction.response.send_message("Failed to update claim image URL.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set image shown when someone destroys the item.")
    async def set_destroy_image(self, interaction: discord.Interaction, image_url: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET destroy_image_url = ? WHERE guild_id = ?',
                                   (image_url, interaction.guild.id))
                await conn.commit()

            logger.info(f"Updated destroy image URL in guild {interaction.guild.id}: {image_url}")
            await interaction.response.send_message("Destroy image URL updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update destroy image URL.")
            await interaction.response.send_message("Failed to update destroy image URL.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # -----------------------------------------------------------------------------------------------------------------

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

    # -----------------------------------------------------------------------------------------------------------------

    @app_commands.command(description="Admin: Set the image URL for rare drops.")
    async def set_rare_image(self, interaction: discord.Interaction, image_url: str):
        try:
            if not await check_permissions(interaction):
                await interaction.response.send_message("You don't have permission.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute(
                    'UPDATE item_settings SET rare_image_url = ? WHERE guild_id = ?',
                    (image_url, interaction.guild.id)
                )
                await conn.commit()

            logger.info(f"Updated rare image URL in guild {interaction.guild.id}: {image_url}")
            await interaction.response.send_message("Rare drop image URL updated.", ephemeral=True)

        except Exception:
            logger.exception("Failed to update rare drop image URL.")
            await interaction.response.send_message("Failed to update rare drop image URL.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the role to give for rare item claims.")
    @app_commands.describe(role="The role to give when a rare drop is claimed.")
    async def set_rare_role(self, interaction: discord.Interaction, role: discord.Role):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute(
                    'UPDATE item_settings SET rare_role_id = ? WHERE guild_id = ?',
                    (role.id, interaction.guild.id)
                )
                await conn.commit()

            await interaction.response.send_message(f"Rare drop role set to {role.mention}.", ephemeral=True)
            logger.info(f"Set rare role to {role.id} in guild {interaction.guild.id}")
        except Exception:
            logger.exception("Failed to set rare role.")
            await interaction.response.send_message("Failed to set rare drop role.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # -----------------------------------------------------------------------------------------------------------------

    @app_commands.command(description="Admin: View current item drop settings.")
    @commands.has_permissions(administrator=True)
    async def view_settings(self, interaction: discord.Interaction):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                # Guild-specific settings
                cursor = await conn.execute('''
                    SELECT drop_channel_id, message, image_url,
                           claim_text, destroy_text,
                           claim_image_url, destroy_image_url,
                           rare_message, rare_image_url,
                           rare_role_id, drop_expiry_minutes
                    FROM item_settings WHERE guild_id = ?
                ''', (interaction.guild.id,))
                row = await cursor.fetchone()

                if not row:
                    await interaction.response.send_message("No settings found for this guild.", ephemeral=True)
                    return

                (channel_id, message, image_url,
                 claim_text, destroy_text,
                 claim_image_url, destroy_image_url,
                 rare_message, rare_image_url,
                 rare_role_id, drop_expiry_minutes) = row

                # Global drop chance from config
                cursor = await conn.execute('SELECT value FROM item_config WHERE key = "drop_chance_denominator"')
                chance_row = await cursor.fetchone()
                drop_chance = int(chance_row[0]) if chance_row else 120

            # Calculate approximate hourly drop chance
            approx_hourly_chance = 1 - math.pow((drop_chance - 1) / drop_chance, 30)
            approx_percent = round(approx_hourly_chance * 100, 2)

            embed = discord.Embed(title="Item Drop Settings", color=discord.Color.blurple())

            embed.add_field(name="Drop Channel", value=f"```{channel_id or 'Not set'}```", inline=False)
            embed.add_field(name="Drop Message", value=f"```\n{message}\n```", inline=False)
            embed.add_field(name="Drop Image", value=f"```{image_url or 'Not set'}```", inline=False)

            embed.add_field(name="Claim Text", value=f"```\n{claim_text}\n```", inline=False)
            embed.add_field(name="Claim Image", value=f"```{claim_image_url or 'Not set'}```", inline=False)

            embed.add_field(name="Destroy Text", value=f"```\n{destroy_text}\n```", inline=False)
            embed.add_field(name="Destroy Image", value=f"```{destroy_image_url or 'Not set'}```", inline=False)

            embed.add_field(name="Rare Message", value=f"```\n{rare_message or 'Default message'}\n```", inline=False)
            embed.add_field(name="Rare Image", value=f"```{rare_image_url or 'Not set'}```", inline=False)

            # Rare Role
            role = interaction.guild.get_role(rare_role_id) if rare_role_id else None
            role_display = role.mention if role else "Not set"
            embed.add_field(name="Rare Role", value=f"```{role_display}```", inline=False)

            # Expiry Time
            expiry_display = f"{drop_expiry_minutes} minutes" if drop_expiry_minutes else "30 minutes (default)"
            embed.add_field(name="Drop Expiry Time", value=f"```{expiry_display}```", inline=False)

            # Drop chance
            embed.add_field(
                name="Drop Chance",
                value=f"```1 in {drop_chance} (~{approx_percent}% per hour)```",
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing item settings for {interaction.guild.id}: {e}")
            await interaction.response.send_message(f"`Error: {e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)
    # -----------------------------------------------------------------------------------------------------------------

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
                    INSERT OR IGNORE INTO item_settings (
                        guild_id, drop_channel_id, message, image_url,
                        claim_text, destroy_text, claim_image_url, destroy_image_url,
                        rare_message, rare_image_url, rare_role_id, drop_expiry_minutes
                    ) VALUES (?, NULL,
                        'Something dropped! Claim it or Destroy it!',
                        'https://imgur.com/VZtZTOm.png',
                        '{user} claimed it!',
                        '{user} destroyed it!',
                        'https://imgur.com/VZtZTOm.png',
                        'https://imgur.com/UtVm1W9.png',
                        'A rare item has appeared! Be the first to claim it!',
                        'https://imgur.com/GLszyDB.png',
                        NULL,
                        30
                    )
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
            CREATE TABLE IF NOT EXISTS item_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS item_settings (
                guild_id INTEGER PRIMARY KEY,
                drop_channel_id INTEGER,
                drop_expiry_minutes INTEGER DEFAULT 30,
                message TEXT,
                image_url TEXT,
                claim_text TEXT,
                destroy_text TEXT,
                claim_image_url TEXT,
                destroy_image_url TEXT,
                rare_message TEXT,
                rare_image_url TEXT,
                rare_role_id INTEGER
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS item_stats (
                guild_id INTEGER,
                user_id INTEGER,
                items_collected INTEGER DEFAULT 0,
                items_destroyed INTEGER DEFAULT 0,
                rare_drops_claimed INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS active_drops (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                drop_time TEXT NOT NULL
            )
        ''')

        await conn.commit()

    logger.info("ItemDrop setup completed. Tables ensured.")
    await bot.add_cog(ItemDrop(bot))


