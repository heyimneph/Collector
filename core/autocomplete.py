import os
import aiosqlite
import logging

from discord import app_commands, Interaction
from config import DB_PATH

# ---------------------------------------------------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------------------------
# Autocomplete Functions
# ---------------------------------------------------------------------------------------------------------------------
async def cog_autocomplete(interaction: Interaction, current: str):
    """Suggests Python cog files from the cogs folder."""
    try:
        suggestions = []
        cogs_dir = "cogs"

        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py"):
                cog_name = filename[:-3]
                if current.lower() in cog_name.lower():
                    suggestions.append(app_commands.Choice(name=cog_name, value=cog_name))

        logger.info(f"[Autocomplete] cog_autocomplete: matched {len(suggestions)} result(s) for '{current}'")
        return suggestions

    except Exception as e:
        logger.exception(f"[Autocomplete] Failed cog_autocomplete for input '{current}': {e}")
        return []


async def table_name_autocomplete(interaction: Interaction, current: str):
    """Suggests table names from the SQLite database."""
    try:
        async with aiosqlite.connect(DB_PATH()) as conn:
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in await cursor.fetchall()]

        filtered = [
            app_commands.Choice(name=table, value=table)
            for table in tables if current.lower() in table.lower()
        ]

        logger.info(f"[Autocomplete] table_name_autocomplete: {len(filtered)} matches for '{current}'")
        return filtered

    except Exception as e:
        logger.exception(f"[Autocomplete] Failed table_name_autocomplete for input '{current}': {e}")
        return []
