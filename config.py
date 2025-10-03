import os

TOKEN = os.getenv("TOKEN")
PREFIX = os.getenv("PREFIX", "-")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
DEBUG_TOKEN = os.getenv("DEBUG_TOKEN")