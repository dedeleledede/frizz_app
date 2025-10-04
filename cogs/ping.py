import re
import aiohttp
import asyncio
import secrets
import discord
from discord.ext import commands

class PingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command()
    async def ping(self, ctx):
        latency_sec = self.bot.latency
        latency_ms = round(latency_sec *1000)
        await ctx.send(f'**Ping!**\nMeu ping está em {latency_ms} ms.') 
        
async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))