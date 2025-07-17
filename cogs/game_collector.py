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
from config import OWNER_ID

logger = logging.getLogger(__name__)


async def patch_null_item_settings():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            UPDATE item_settings
            SET
                message = COALESCE(message, 'Something dropped! Claim it or Destroy it!'),
                image_url = COALESCE(image_url, 'https://imgur.com/VZtZTOm.png'),
                claim_text = COALESCE(claim_text, '{user} claimed it!'),
                destroy_text = COALESCE(destroy_text, '{user} destroyed it!'),
                claim_image_url = COALESCE(claim_image_url, 'https://imgur.com/VZtZTOm.png'),
                destroy_image_url = COALESCE(destroy_image_url, 'https://imgur.com/UtVm1W9.png'),
                rare_message = COALESCE(rare_message, 'A rare item has appeared! Be the first to claim it!'),
                rare_image_url = COALESCE(rare_image_url, 'https://imgur.com/GLszyDB.png'),
                rare_default_text = COALESCE(rare_default_text, 'A rare event occurred!'),
                rare_claim_image = COALESCE(rare_claim_image, NULL),
                rare_destroy_image = COALESCE(rare_destroy_image, NULL),
                rare_claim_text = COALESCE(rare_claim_text, '{user} claimed the rare item!'),
                rare_destroy_text = COALESCE(rare_destroy_text, '{user} destroyed the rare item!'),
                rare_role_id = COALESCE(rare_role_id, NULL),
                drop_expiry_minutes = COALESCE(drop_expiry_minutes, 30)
            WHERE
                message IS NULL OR
                image_url IS NULL OR
                claim_text IS NULL OR
                destroy_text IS NULL
        ''')
        await conn.commit()


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
                    '''SELECT claim_text, claim_image_url, rare_claim_image, rare_role_id,
                              rare_image_url, rare_claim_text
                       FROM item_settings WHERE guild_id = ?''',
                    (interaction.guild.id,)
                )
                row = await cursor.fetchone()
                claim_text = (
                    row[5] if is_rare and row and row[5]
                    else row[0] if row else "{user} claimed it!"
                )
                claim_image = (
                    row[2] if is_rare and row and row[2]
                    else (row[4] if is_rare and row and row[4] else row[1])
                )
                rare_role_id = row[3] if row and len(row) > 3 else None

                await conn.commit()

            embed.description = claim_text.replace("{user}", interaction.user.mention)
            embed.color = discord.Color.green()
            embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            embed.timestamp = discord.utils.utcnow()

            if claim_image:
                embed.set_image(url=claim_image)

            await interaction.response.edit_message(embed=embed, view=self)

            if is_rare and rare_role_id:
                role = interaction.guild.get_role(rare_role_id)
                if role:
                    try:
                        # Remove rare role from all members who currently have it
                        for member in role.members:
                            if member != interaction.user:
                                await member.remove_roles(role, reason="Reassigned rare drop role")

                        # Assign the role to the current user
                        await interaction.user.add_roles(role, reason="Claimed rare drop")
                        logger.info(
                            f"Assigned rare role {role.id} to {interaction.user} in guild {interaction.guild.id}")

                    except discord.Forbidden:
                        logger.warning(f"Missing permission to modify role {role.id} in guild {interaction.guild.id}")
                    except Exception as e:
                        logger.exception(f"Error managing rare role: {e}")

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

            embed = interaction.message.embeds[0]
            is_rare = embed.author and "RARE DROP" in embed.author.name if embed.author else False

            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    INSERT INTO item_stats (guild_id, user_id, items_destroyed)
                    VALUES (?, ?, 1)
                    ON CONFLICT(guild_id, user_id)
                    DO UPDATE SET items_destroyed = items_destroyed + 1
                ''', (interaction.guild.id, interaction.user.id))

                cursor = await conn.execute(
                    '''SELECT destroy_text, destroy_image_url, rare_destroy_image,
                              rare_image_url, rare_destroy_text
                       FROM item_settings WHERE guild_id = ?''',
                    (interaction.guild.id,)
                )
                row = await cursor.fetchone()
                destroy_text = (
                    row[4] if is_rare and row and row[4]
                    else row[0] if row else "{user} destroyed it!"
                )
                destroy_image = (
                    row[2] if is_rare and row and row[2]
                    else (row[3] if is_rare and row and row[3] else row[1])
                )

                await conn.commit()

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

    async def start(self, interaction: discord.Interaction, ephemeral: bool = False):
        try:
            embed = await self.build_leaderboard_embed(interaction)
            await interaction.response.send_message(embed=embed, view=self, ephemeral=ephemeral)
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
                    user = interaction.guild.get_member(user_id)
                    if not user:
                        user = self.bot.get_user(user_id)
                    if not user:
                        try:
                            user = await self.bot.fetch_user(user_id)
                        except Exception:
                            user = None

                    name = user.display_name if isinstance(user, discord.Member) else str(
                        user) if user else f"<@{user_id}>"
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
        self.drop_chance_denominator = 120
        self.drop_interval = 60
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
                self.bot.add_view(ItemView(bot=self.bot, author_id=self.bot.user.id))
                logger.info("ItemView registered for persistent button support.")

                async with aiosqlite.connect(DB_PATH) as conn:
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

                    cursor = await conn.execute("SELECT value FROM item_config WHERE key = 'drop_chance_denominator'")
                    row = await cursor.fetchone()
                    self.drop_chance_denominator = int(row[0]) if row else 120
                    logger.info(f"Loaded drop chance denominator: 1 in {self.drop_chance_denominator}")

                    for guild in self.bot.guilds:
                        await conn.execute('''
                            INSERT OR IGNORE INTO item_settings (
                                guild_id, drop_channel_id, message, image_url,
                                claim_text, destroy_text, claim_image_url, destroy_image_url,
                                rare_message, rare_image_url,
                                rare_default_text, rare_claim_image, rare_destroy_image,
                                rare_claim_text, rare_destroy_text,
                                rare_role_id, drop_expiry_minutes
                            ) VALUES (?, NULL,
                                'Something dropped! Claim it or Destroy it!',
                                'https://imgur.com/VZtZTOm.png',
                                '{user} claimed it!',
                                '{user} destroyed it!',
                                'https://imgur.com/VZtZTOm.png',
                                'https://imgur.com/UtVm1W9.png',
                                'A rare item has appeared! Be the first to claim it!',
                                'https://imgur.com/GLszyDB.png',
                                'A rare event occurred!',
                                NULL,
                                NULL,
                                '{user} claimed the rare item!',
                                '{user} destroyed the rare item!',
                                NULL,
                                30
                            )
                            ''', (guild.id,))

                    await conn.commit()

                self.item_drop_task.change_interval(seconds=self.drop_interval)
                self.item_drop_task.start()
                self.cleanup_expired_drops.start()
                logger.info("ItemDrop and cleanup tasks started.")
                logger.info("ItemDrop initialized for all joined guilds.")

            except Exception:
                logger.exception("Error initializing ItemDrop during on_ready.")

    @tasks.loop(seconds=0)
    async def item_drop_task(self):
        logger.info(f"[Tick] item_drop_task at {datetime.utcnow()}")

        for guild in self.bot.guilds:
            try:
                if random.randint(1, self.drop_chance_denominator) != 1:
                    continue

                drop_type = "normal"
                if random.randint(1, 50) == 1:
                    drop_type = "rare"

                async with aiosqlite.connect(DB_PATH) as conn:
                    cursor = await conn.execute('''
                        SELECT drop_channel_id, message, image_url,
                               rare_message, rare_image_url, rare_default_text
                        FROM item_settings WHERE guild_id = ?
                    ''', (guild.id,))
                    settings = await cursor.fetchone()

                channel_id = None
                if settings:
                    (channel_id, msg, img, rare_msg, rare_img, rare_default_text) = settings
                    if drop_type == "rare":
                        message_text = rare_msg or rare_default_text or "✨ A rare item has appeared!"
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
    @app_commands.command(description="Owner: Set the 1-in-X drop chance (1 - 500)")
    async def set_drop_chance(self, interaction: discord.Interaction, chance: int):
        owner_id = self.bot.owner_id or (await self.bot.application_info()).owner.id
        if interaction.user.id != owner_id:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        if chance < 1 or chance > 500:
            await interaction.response.send_message("Please provide a value between 30 and 500.", ephemeral=True)
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
    @app_commands.describe(minutes="Expiration time in minutes (5 - 1440)")
    async def set_expiry_time(self, interaction: discord.Interaction, minutes: int):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        if minutes < 1 or minutes > 1440:
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

    # -----------------------------------------------------------------------------------------------------------------

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

    @app_commands.command(description="Admin: Set the default text shown for rare drops.")
    async def set_rare_default_text(self, interaction: discord.Interaction, text: str):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET rare_default_text = ? WHERE guild_id = ?',
                                   (text, interaction.guild.id))
                await conn.commit()
            await interaction.response.send_message("Rare default text updated.", ephemeral=True)
            logger.info(f"Updated rare_default_text for {interaction.guild.id}")
        except Exception:
            logger.exception("Failed to update rare_default_text.")
            await interaction.response.send_message("Error updating rare default text.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the text shown when someone claims a rare item.")
    async def set_rare_claim_text(self, interaction: discord.Interaction, text: str):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute(
                    'UPDATE item_settings SET rare_claim_text = ? WHERE guild_id = ?',
                    (text, interaction.guild.id)
                )
                await conn.commit()
            await interaction.response.send_message("Rare claim text updated.", ephemeral=True)
        except Exception:
            logger.exception("Failed to update rare claim text.")
            await interaction.response.send_message("Error updating rare claim text.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the text shown when someone destroys a rare item.")
    async def set_rare_destroy_text(self, interaction: discord.Interaction, text: str):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute(
                    'UPDATE item_settings SET rare_destroy_text = ? WHERE guild_id = ?',
                    (text, interaction.guild.id)
                )
                await conn.commit()
            await interaction.response.send_message("Rare destroy text updated.", ephemeral=True)
        except Exception:
            logger.exception("Failed to update rare destroy text.")
            await interaction.response.send_message("Error updating rare destroy text.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the image URL shown when someone claims a rare item.")
    async def set_rare_claim_image(self, interaction: discord.Interaction, image_url: str):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET rare_claim_image = ? WHERE guild_id = ?',
                                   (image_url, interaction.guild.id))
                await conn.commit()
            await interaction.response.send_message("Rare claim image updated.", ephemeral=True)
            logger.info(f"Updated rare_claim_image for {interaction.guild.id}")
        except Exception:
            logger.exception("Failed to update rare_claim_image.")
            await interaction.response.send_message("Error updating rare claim image.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Set the image URL shown when someone destroys a rare item.")
    async def set_rare_destroy_image(self, interaction: discord.Interaction, image_url: str):
        if not await check_permissions(interaction):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('UPDATE item_settings SET rare_destroy_image = ? WHERE guild_id = ?',
                                   (image_url, interaction.guild.id))
                await conn.commit()
            await interaction.response.send_message("Rare destroy image updated.", ephemeral=True)
            logger.info(f"Updated rare_destroy_image for {interaction.guild.id}")
        except Exception:
            logger.exception("Failed to update rare_destroy_image.")
            await interaction.response.send_message("Error updating rare destroy image.", ephemeral=True)
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
                cursor = await conn.execute('''
                    SELECT drop_channel_id, message, image_url,
                           claim_text, destroy_text,
                           claim_image_url, destroy_image_url,
                           rare_message, rare_image_url,
                           rare_default_text, rare_claim_image, rare_destroy_image,
                           rare_claim_text, rare_destroy_text,
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
                 rare_default_text, rare_claim_image, rare_destroy_image,
                 rare_claim_text, rare_destroy_text,
                 rare_role_id, drop_expiry_minutes) = row

                cursor = await conn.execute('SELECT value FROM item_config WHERE key = "drop_chance_denominator"')
                chance_row = await cursor.fetchone()
                drop_chance = int(chance_row[0]) if chance_row else 120

            drop_interval = getattr(self, "drop_interval", 180)
            attempts_per_hour = round(3600 / drop_interval)
            import math
            approx_hourly_chance = 1 - math.pow((drop_chance - 1) / drop_chance, attempts_per_hour)
            approx_percent = round(approx_hourly_chance * 100, 2)

            embed = discord.Embed(title="Item Drop Settings", color=discord.Color.blurple())

            embed.add_field(name="Drop Channel", value=f"```{channel_id or 'Not set'}```", inline=False)
            embed.add_field(name="Drop Message", value=f"```\n{message}```", inline=False)
            embed.add_field(name="Drop Image", value=f"```{image_url or 'Not set'}```", inline=False)

            embed.add_field(name="Claim Text", value=f"```\n{claim_text}```", inline=False)
            embed.add_field(name="Claim Image", value=f"```{claim_image_url or 'Not set'}```", inline=False)

            embed.add_field(name="Destroy Text", value=f"```\n{destroy_text}```", inline=False)
            embed.add_field(name="Destroy Image", value=f"```{destroy_image_url or 'Not set'}```", inline=False)

            embed.add_field(name="Rare Message", value=f"```\n{rare_message or 'Default message'}```", inline=False)
            embed.add_field(name="Rare Image", value=f"```{rare_image_url or 'Not set'}```", inline=False)
            embed.add_field(name="Rare Default Text", value=f"```\n{rare_default_text or 'Not set'}```", inline=False)
            embed.add_field(name="Rare Claim Text", value=f"```\n{rare_claim_text or 'Not set'}```", inline=False)
            embed.add_field(name="Rare Claim Image", value=f"```{rare_claim_image or 'Not set'}```", inline=False)
            embed.add_field(name="Rare Destroy Text", value=f"```\n{rare_destroy_text or 'Not set'}```", inline=False)
            embed.add_field(name="Rare Destroy Image", value=f"```{rare_destroy_image or 'Not set'}```", inline=False)

            role = interaction.guild.get_role(rare_role_id) if rare_role_id else None
            role_display = role.mention if role else "Not set"
            embed.add_field(name="Rare Role", value=f"```{role_display}```", inline=False)

            expiry_display = f"{drop_expiry_minutes} minutes" if drop_expiry_minutes else "30 minutes (default)"
            embed.add_field(name="Drop Expiry Time", value=f"```{expiry_display}```", inline=False)

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
            await view.start(interaction, ephemeral=True)
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
                        rare_message, rare_image_url,
                        rare_default_text, rare_claim_image, rare_destroy_image,
                        rare_claim_text, rare_destroy_text,
                        rare_role_id, drop_expiry_minutes
                    ) VALUES (?, NULL,
                        'Something dropped! Claim it or Destroy it!',
                        'https://imgur.com/VZtZTOm.png',
                        '{user} claimed it!',
                        '{user} destroyed it!',
                        'https://imgur.com/VZtZTOm.png',
                        'https://imgur.com/UtVm1W9.png',
                        'A rare item has appeared! Be the first to claim it!',
                        'https://imgur.com/GLszyDB.png',
                        'A rare event occurred!',
                        NULL,
                        NULL,
                        '{user} claimed the rare item!',
                        '{user} destroyed the rare item!',
                        NULL,
                        30
                    )
                ''', (guild.id,))

                await conn.commit()

            logger.info(f"Initialized item_settings for new guild {guild.id}")

        except Exception:
            logger.exception(f"Failed to initialize settings for new guild {guild.id}")

# ---------------------------------------------------------------------------------------------------------------------
# Patch Commands
# ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(description="Owner: Patch existing tables with new fields")
    async def patch_item_settings(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                # Attempt to add each new column
                new_columns = [
                    "rare_default_text",
                    "rare_claim_image",
                    "rare_destroy_image",
                    "rare_claim_text",
                    "rare_destroy_text"
                ]

                for column in new_columns:
                    try:
                        await conn.execute(f"ALTER TABLE item_settings ADD COLUMN {column} TEXT")
                    except aiosqlite.OperationalError:
                        pass  # Column already exists

                # Fill defaults where values are still NULL
                await conn.execute('''
                    UPDATE item_settings
                    SET
                        rare_default_text = COALESCE(rare_default_text, 'A rare event occurred!'),
                        rare_claim_image = COALESCE(rare_claim_image, NULL),
                        rare_destroy_image = COALESCE(rare_destroy_image, NULL),
                        rare_claim_text = COALESCE(rare_claim_text, '{user} claimed the rare item!'),
                        rare_destroy_text = COALESCE(rare_destroy_text, '{user} destroyed the rare item!')
                ''')
                await conn.commit()

            await interaction.response.send_message("`item_settings` table successfully patched!", ephemeral=True)
            logger.info(f"{interaction.user} patched item_settings table in guild {interaction.guild.id}")

        except Exception as e:
            logger.exception("Failed to patch item_settings.")
            await interaction.response.send_message(f"Failed to patch table: `{e}`", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)


    @app_commands.command(description="Owner: Patch broken item_settings rows with default values.")
    async def patch_null_rows(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        try:
            await patch_null_item_settings()
            await interaction.response.send_message("Patched null entries in `item_settings`.", ephemeral=True)
        except Exception as e:
            logger.exception("Failed to patch null item_settings row.")
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)


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
                rare_default_text TEXT,
                rare_claim_image TEXT,
                rare_destroy_image TEXT,
                rare_claim_text TEXT,
                rare_destroy_text TEXT,
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


