import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

WEBHOOK_NAME = "Frizz"
WEBHOOK_AVATAR = "https://cdn.discordapp.com/attachments/781008768925433876/1410721715264426148/frizz-logo-test.png?ex=68b406ba&is=68b2b53a&hm=540404107d693ca15ee49646794f531e6dd6e7e725fc56fd01408b8fb80912ce&"

class WebhookCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /create_webhook command
    @app_commands.command(name="create_webhook", description="Cria um webhook se um ja nao existir")
    @app_commands.describe(canal="O canal onde o webhook sera criado")
    async def create_webhook(self, interaction: discord.Interaction, canal: discord.TextChannel):

        # checa se existe webhook do bot c/ msm nome
        webhooks = await canal.webhooks()
        existing = discord.utils.get(webhooks, name=WEBHOOK_NAME, user=interaction.client.user)

        if existing:
            await interaction.response.send_message("webhook ja existe nesse canal", ephemeral=True)
            return
        else:
            # baixar avatar
            await interaction.response.defer(ephemeral=True)
            async with aiohttp.ClientSession() as session:
                async with session.get(WEBHOOK_AVATAR) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("Erro ao carregar o avatar", ephemeral=True)
                    avatar_bytes = await resp.read()

            # cria webhook
            webhook = await canal.create_webhook(name=WEBHOOK_NAME, avatar=avatar_bytes)
            await interaction.followup.send(f"webhook criado: {webhook.url}", ephemeral=True)

    # /send_webhook command
    @app_commands.command(name="send_webhook", description="Envia uma mensagem usando o webhook existente")
    @app_commands.describe(canal="O canal onde o webhook sera usado", message="A mensagem a ser enviada")
    async def send_webhook(self, interaction: discord.Interaction, canal: discord.TextChannel, message: str):
        await interaction.response.defer(ephemeral=True)

        # acha o webhook
        webhooks = await canal.webhooks()
        webhook = discord.utils.get(webhooks, name=WEBHOOK_NAME, user=interaction.client.user)

        if not webhook:
            
            # baixar avatar
            await interaction.response.defer(ephemeral=True)
            async with aiohttp.ClientSession() as session:
                async with session.get(WEBHOOK_AVATAR) as resp:
                    if resp.status != 200:
                        await interaction.response.send_message("Erro ao carregar o avatar", ephemeral=True)
                avatar_bytes = await resp.read()
            try:
                # cria webhook
                webhook = await canal.create_webhook(name=WEBHOOK_NAME, avatar=avatar_bytes)
            except Exception as e:
                await interaction.followup.send(f"Erro ao criar webhook: {e}\n Tente criar manualmente (/create_webhook)", ephemeral=True)
                return

        # Send the message
        try:
            await webhook.send(content=message)
            await interaction.followup.send("mensagem enviada via webhook.", ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send(f"Erro ao criar webhook: {e}\n Tente criar manualmente (/create_webhook)", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"Erro ao enviar mensagem via webhook: {e}", ephemeral=True)
            return

async def setup(bot: commands.Bot):
    await bot.add_cog(WebhookCog(bot))
