import os
import sys
import asyncio
import discord
from pathlib import Path
from dotenv import load_dotenv
from discord import app_commands
from discord.ext import commands

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    print('not in')
    sys.path.insert(0, str(ROOT))

import config
from updater import self_update

class Restart(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(name="restart", description="Atualize o bot, reiniciando o mesmo.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self_update)
            await interaction.followup.send("Atualizado com sucesso.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Atualização falhou: {e}", ephemeral=True)

        loop.call_later(1.0, lambda: os.execv(sys.executable, [sys.executable] + sys.argv))

async def setup(bot: commands.Bot):
    await bot.add_cog(Restart(bot), guild=discord.Object(config.GUILD_ID))