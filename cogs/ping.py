import re
import aiohttp
import asyncio
import secrets
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='-', intents=intents)

@bot.command()
async def ping(ctx):
    latency_sec = bot.latency
    latency_ms = round(latency_sec * 1000)
    await ctx.send(f'**Ping!**\nMeu ping está em {latency_ms} ms')