import discord
import logging
import aiosqlite
import psutil
import inspect

from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
from datetime import datetime

from core.utils import log_command_usage, check_permissions, get_embed_colour, DB_PATH
from config import OWNER_ID

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------------------------------
# Help Modals
# ---------------------------------------------------------------------------------------------------------------------
class SuggestionModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title="Submit a Suggestion")
        self.bot = bot

    ticket_name = discord.ui.TextInput(label="Ticket Name", style=discord.TextStyle.short, required=True)
    suggestion = discord.ui.TextInput(label="Describe your suggestion", style=discord.TextStyle.long, required=True)
    additional_info = discord.ui.TextInput(label="Additional information", style=discord.TextStyle.long, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        current_time = discord.utils.utcnow()
        formatted_time = current_time.strftime("%d/%m/%Y")

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute("SELECT 1 FROM blacklist WHERE user_id = ?", (interaction.user.id,))
            if await cursor.fetchone():
                support_url = "https://discord.gg/SXmXmteyZ3"  # Your support server link
                response_message = ("You are blacklisted from making suggestions. "
                                    f"If you believe this is a mistake, please contact us: [Support Server]({support_url}).")
                await interaction.response.send_message(response_message, ephemeral=True)
                return
            colour = await get_embed_colour(interaction.guild.id)

        channel = self.bot.get_channel(1268168019297697914)
        if channel:
            embed = discord.Embed(title=f"Suggestion: {self.ticket_name.value}",
                                  description=f"```{self.suggestion.value}```",
                                  color=colour)
            embed.add_field(name="Additional Information",
                            value=f"```{self.additional_info.value or 'None provided'}```",
                            inline=False)
            embed.set_footer(text=f"Submitted by {user.name} on {formatted_time}")

            view = View()
            view.add_item(BlacklistButton(interaction.user.id))

            await channel.send(embed=embed, view=view)
            await interaction.response.send_message("Your suggestion has been submitted successfully!", ephemeral=True)
        else:
            await interaction.response.send_message("Failed to send suggestion. Support channel not found.", ephemeral=True)

# ---------------------------------------------------------------------------------------------------------------------
# Buttons and Views
# ---------------------------------------------------------------------------------------------------------------------
class BlacklistButton(discord.ui.Button):
    def __init__(self, user_id):
        super().__init__(style=discord.ButtonStyle.danger, label="Blacklist User")
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute("INSERT OR IGNORE INTO blacklist (user_id) VALUES (?)", (self.user_id,))
            await conn.commit()
        await interaction.response.send_message("User has been blacklisted from making suggestions.", ephemeral=True)

# ---------------------------------------------------------------------------------------------------------------------
# Help View
# ---------------------------------------------------------------------------------------------------------------------
class HelpPaginator(View):
    def __init__(self, bot, pages, updates_page):
        super().__init__(timeout=180)
        self.bot = bot
        self.pages = pages
        self.current_page = 0
        self.updates_page = updates_page

        self.prev_button = Button(label="Prev", style=discord.ButtonStyle.primary)
        self.prev_button.callback = self.prev_page
        self.add_item(self.prev_button)

        self.home_button = Button(label="Home", style=discord.ButtonStyle.green)
        self.home_button.callback = self.go_home
        self.add_item(self.home_button)

        self.next_button = Button(label="Next", style=discord.ButtonStyle.primary)
        self.next_button.callback = self.next_page
        self.add_item(self.next_button)

        self.updates_button = Button(label="Updates", style=discord.ButtonStyle.secondary)
        self.updates_button.callback = self.go_to_updates
        self.add_item(self.updates_button)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        if self.current_page >= len(self.pages):
            self.current_page = 0
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        if self.current_page < 0:
            self.current_page = len(self.pages) - 1
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def go_home(self, interaction: discord.Interaction):
        self.current_page = 0
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def go_to_updates(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.updates_page, view=self)

    async def start(self, interaction: discord.Interaction):
        for page in self.pages:
            page.set_thumbnail(url=self.bot.user.display_avatar.url)
            page.set_footer(text="Created by heyimneph")
            page.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embed=self.pages[self.current_page], view=self, ephemeral=True)

# ---------------------------------------------------------------------------------------------------------------------
# Utility Cog Class
# ---------------------------------------------------------------------------------------------------------------------
class UtilityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot_start_time = datetime.utcnow()

    async def has_required_permissions(self, interaction, command):
        if interaction.user.guild_permissions.administrator:
            return True

        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute('''
                SELECT can_use_commands FROM permissions WHERE guild_id = ? AND user_id = ?
            ''', (interaction.guild.id, interaction.user.id))
            permission = await cursor.fetchone()
            if permission and permission[0]:
                return True

        if "Admin" in command.description or "Owner" in command.description:
            return False

        for check in command.checks:
            try:
                if inspect.iscoroutinefunction(check):
                    result = await check(interaction)
                else:
                    result = check(interaction)
                if not result:
                    return False
            except Exception as e:
                logger.error(f"Permission check failed: {e}")
                return False

        return True

    async def owner_check(self, interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID


    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(name="help", description="User: Display help information for all commands.")
    async def help(self, interaction: discord.Interaction):
        try:
            pages = []
            colour = await get_embed_colour(interaction.guild.id)

            # Main help intro page
            help_intro = discord.Embed(
                title="About Eggbot",
                description=(
                    "Welcome to **Eggbot** – a server-wide item drop game!\n\n"
                    "Items will randomly appear in text channels. "
                    "The first person to `Claim` wins a point... or you can be a little evil and "
                    "`Destroy` it instead \n\n"
                ),
                color=colour
            )

            help_intro.add_field(name="",value="",inline=False)
            help_intro.add_field(
                name="Getting Started",
                value=(
                    "1. Run `/set_default_image`\n"
                    "*Choose your item to begin collecting!*\n"
                    "2. Try `/set_drop_channel` \n"
                    "*This will limit where Eggbot posts*\n"
                    "3. Try `/leaderboard` \n"
                    "*See how you compare locally and globally!*\n\n"
                    "I am an open source project - check me out [here](https://github.com/heyimneph/Collector)!"                )
            )
            help_intro.add_field(name="Need Support?",
                                 value="*Sometimes, things don't work as expected. If you need assistance or "
                                       "would like to report an issue you can join our "
                                       "[support server](https://discord.gg/SXmXmteyZ3) and create a ticket. We'd be "
                                       "happy to help!*",
                                 inline=False)

            pages.append(help_intro)

            # Generating command pages
            for cog_name, cog in self.bot.cogs.items():
                if cog_name in {"Core", "TheMachineBotCore", "AdminCog"}:
                    continue
                embed = discord.Embed(title=f"{cog_name.replace('Cog', '')} Commands", description="", color=colour)

                for cmd in cog.get_app_commands():
                    if "Owner" in cmd.description and not await self.owner_check(interaction):
                        continue
                    if not await self.has_required_permissions(interaction, cmd):
                        continue
                    embed.add_field(name=f"/{cmd.name}", value=f"```{cmd.description}```", inline=False)

                if embed.fields:
                    pages.append(embed)

            # Updates page
            updates_page = discord.Embed(
                title="Latest Updates",
                description=(
                    "15/07/2025 \n"
                    "- Added Support server link \n"
                    "- Added `/suggestion` command \n"
                    "- Updated Command texts \n"
                    "- Added more customisation commands (rare options) \n\n"
                    "14/07/2025 \n"
                    "- Massive QoL improvements \n"
                    "- More customisation \n"
                    "- Added a 'rare' drop' \n\n"
                    "11/07/2025\n"
                    "- Eggbot is live \n\n"
                   # "Please leave a review/rating here: https://top.gg/bot/1268589797149118670"
                ),
                color=colour
            )
            updates_page.set_footer(text="Created by heyimneph")
            updates_page.timestamp = discord.utils.utcnow()

            paginator = HelpPaginator(self.bot, pages=pages, updates_page=updates_page)
            await paginator.start(interaction)

        except Exception as e:
            logger.error(f"Error with Help command: {e}")
            await interaction.response.send_message("Failed to fetch help information.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name="suggest", description="User: Make a suggestion for Eggbot")
    async def suggest(self, interaction: discord.Interaction):
        try:
            modal = SuggestionModal(self.bot)
            await interaction.response.send_modal(modal)
            await log_command_usage(self.bot, interaction)
        except Exception as e:
            logger.error(f"Failed to launch suggestion modal: {e}")
            await interaction.response.send_message("Failed to launch the suggestion modal.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------

    @app_commands.command(name="stats", description="User: Show statistics for Eggbot.")
    async def stats(self, interaction: discord.Interaction):
        colour = await get_embed_colour(interaction.guild.id)

        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                cursor = await conn.execute("SELECT SUM(items_collected) FROM item_stats")
                total_collected = (await cursor.fetchone())[0] or 0

                cursor = await conn.execute("SELECT SUM(items_destroyed) FROM item_stats")
                total_destroyed = (await cursor.fetchone())[0] or 0

            total_servers = len(self.bot.guilds)
            total_users = sum(len(guild.members) for guild in self.bot.guilds)

            bot_ping = round(self.bot.latency * 1000)
            bot_uptime = datetime.utcnow() - self.bot_start_time
            days, remainder = divmod(bot_uptime.total_seconds(), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)

            uptime_display = []
            if days > 0:
                uptime_display.append(f"{int(days)} day(s)")
            if hours > 0:
                uptime_display.append(f"{int(hours)} hour(s)")
            if minutes > 0:
                uptime_display.append(f"{int(minutes)} minute(s)")

            if len(uptime_display) > 1:
                uptime_display = ', '.join(uptime_display[:-1]) + ' and ' + uptime_display[-1]
            elif uptime_display:
                uptime_display = uptime_display[0]
            else:
                uptime_display = "0 minute(s)"

            cpu = psutil.cpu_percent()
            memory = psutil.virtual_memory().percent

            embed = discord.Embed(title="", description="",
                                  color=colour)

            embed.add_field(name="🥚 Items", value=f"┕ `{total_collected}`", inline=True)
            embed.add_field(name="💥 Destroyed", value=f"┕ `{total_destroyed}`", inline=True)
            embed.add_field(name="🧑 Users", value=f"┕ `{total_users}`", inline=True)
            embed.add_field(name="🏡 Servers", value=f"┕ `{total_servers}`", inline=True)
            embed.add_field(name="🏓 Ping", value=f"┕ `{bot_ping} ms`", inline=True)
            embed.add_field(name="🌐 Language", value=f"┕ `Python`", inline=True)
            embed.add_field(name="‍💻 CPU", value=f"┕ `{cpu}%`", inline=True)
            embed.add_field(name="💾 Memory", value=f"┕ `{memory}%`", inline=True)
            embed.add_field(name="⏳ Uptime", value=f"┕ `{uptime_display}`", inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"Error generating stats: {e}")
            await interaction.response.send_message("Failed to load stats.", ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)

    # ---------------------------------------------------------------------------------------------------------------------
    @app_commands.command(description="Admin: Authorize a user to use Admin commands.")
    @app_commands.describe(user="The user to authorize")
    @app_commands.checks.has_permissions(administrator=True)
    async def authorise(self, interaction: discord.Interaction, user: discord.User):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    INSERT INTO permissions (guild_id, user_id, can_use_commands) VALUES (?, ?, 1)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET can_use_commands = 1
                ''', (interaction.guild.id, user.id))
                await conn.commit()
            await interaction.response.send_message(f"{user.display_name} has been authorized.", ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to authorise user: {e}")
            await interaction.response.send_message(f"Failed to authorise user: {e}",
                                                    ephemeral=True)


        finally:
            await log_command_usage(self.bot, interaction)

    @app_commands.command(description="Admin: Revoke a user's authorization to use Admin commands.")
    @app_commands.describe(user="The user to unauthorize")
    @app_commands.checks.has_permissions(administrator=True)
    async def unauthorise(self, interaction: discord.Interaction, user: discord.User):
        try:
            async with aiosqlite.connect(DB_PATH) as conn:
                await conn.execute('''
                    UPDATE permissions SET can_use_commands = 0 WHERE guild_id = ? AND user_id = ?
                ''', (interaction.guild.id, user.id))
                await conn.commit()
            await interaction.response.send_message(f"{user.display_name} has been unauthorized.", ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to unauthorise user: {e}")
            await interaction.response.send_message(f"Failed to unauthorise user: {e}",
                                                    ephemeral=True)
        finally:
            await log_command_usage(self.bot, interaction)


# ---------------------------------------------------------------------------------------------------------------------
# Setup Function
# ---------------------------------------------------------------------------------------------------------------------
async def setup(bot):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        await conn.execute('''
                CREATE TABLE IF NOT EXISTS permissions (
                    guild_id INTEGER,
                    user_id INTEGER,
                    can_use_commands BOOLEAN DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')

        await conn.commit()
    await bot.add_cog(UtilityCog(bot))


