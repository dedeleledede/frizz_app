import os, sys, discord
from discord.ext import commands

BASE_DIR = os.path.dirname(os.path.abspath(__file__))     
PARENT_DIR = os.path.dirname(BASE_DIR)                    
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import config

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned_or('-', config.PREFIX), intents=intents)

    async def setup_hook(self):
        # load cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('_'):
                await self.load_extension(f'cogs.{filename[:-3]}')  # remove .py

        # sync slash commands to test guild
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

bot = MyBot()

@bot.event
async def on_ready():
    print(f'logado como {bot.user} (ID: {bot.user.id})\n')


# run the bot
bot.run(config.TOKEN)