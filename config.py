import os

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("COMMAND_PREFIX", "-")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
