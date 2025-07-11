# Collector — A Discord Item Drop Game Bot

Collector is a Discord bot designed for community servers. It randomly drops collectible items in your server. Users can click buttons to claim or destroy the item. The bot maintains local and global leaderboards to track the most active collectors.

---

## Features

- Random item drops in designated channels (every 15–60 minutes)
- Click-to-claim or destroy functionality using interactive buttons
- Local and global leaderboard with automatic toggling
- Fully customizable drop message, image, and result texts
- Admin-only configuration commands
- Persistent storage using SQLite (`aiosqlite`)
- Slash command support using `discord.app_commands`

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/collector-bot.git
cd collector-bot
```

### 2. Create a `.env` file

```env
DISCORD_TOKEN=your-bot-token
OWNER_ID=your-discord-user-id
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the bot

```bash
python bot.py
```

---

## Configuration

Administrators can customize the bot using slash commands:

- `/set_item_channel` — Set the drop location for items
- `/set_item_message` — Change the message displayed when an item drops
- `/set_item_image` — Set the image displayed in the item embed
- `/set_claim_text` — Define the text shown when someone claims an item (`{user}` is replaced)
- `/set_destroy_text` — Define the text shown when someone destroys an item

---

## Leaderboard

Users can view the most active collectors with:

```bash
/leaderboard
```

The leaderboard supports both local (server-specific) and global rankings. A toggle button allows switching between views.

---

## Permissions

Only server administrators or the user with the `OWNER_ID` defined in `.env` can execute configuration commands. Additional user permissions can be managed via the `permissions` table in the database.

---

## Database

Collector uses two SQLite tables:

- `item_settings` — Stores per-guild configuration
- `item_stats` — Tracks collection activity for users

---

## Customization

All display strings and item behavior are designed to be customizable via slash commands. You can adjust the frequency for testing purposes in `game_collector.py`.

---

## Author

Developed by [heyimneph](https://github.com/heyimneph)  
For contributions, bug reports, or feature requests, feel free to open an issue or pull request.

---

## License

This project is licensed under the MIT License.
