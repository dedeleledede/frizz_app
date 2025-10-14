import asyncio
import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button

CONFIG = {
    "ticket_category_id": 901812309305991188, 
}

def build_channel_name(category: str, author: discord.Member) -> str:
    short = author.display_name.lower().replace(' ', '-')[:16]
    emoji = {"teste":"🤡"}.get(category, "🤡")
    return f"{emoji}ticket-{short}"

class TicketModal(discord.ui.Modal):
    def __init__(self, category: str, *, anonymous: bool = False):
        self.category = category
        self.anonymous = anonymous
        title = {
            "teste": "Abrir Ticket de teste"
            }.get(category, "Abrir Ticket")
        super().__init__(title=title, timeout=None, custom_id=f"ticket_modal:{category}:{int(anonymous)}")

        self.desc = discord.ui.TextInput(label="descricao", style=discord.TextStyle.paragraph, min_length=10, max_length=1500, required=True, placeholder="Breve descrição do problema.")

        self.add_item(self.desc)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        assert guild is not None

        parent = guild.get_channel(CONFIG["ticket_category_id"]) if CONFIG["ticket_category_id"] else None
        channel = await guild.create_text_channel(
            name=build_channel_name(self.category, interaction.user),
            category=parent if isinstance(parent, discord.CategoryChannel) else None,
            topic=f"Ticket criado por {interaction.user} (ID: {interaction.user.id})",
            reason="Novo ticket criado via modal."
        )

        await channel.send(f"{interaction.user.mention} criou um ticket na categoria **{self.category}**.\n\n**Descrição:** {self.desc.value}")

        await interaction.followup.send(content=f"Ticket criado com sucesso: {channel.mention}", ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Criar teste ticket", style=discord.ButtonStyle.primary, custom_id="create_ticket_button")
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal("teste"))


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    #publicar painel
    @app_commands.command(name="ticket_panel", description="Publica o painel de abertura de tickets no canal atual.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.send_message("Painel publicado.", ephemeral=True)
        embed = discord.Embed(title="Abertura de Tickets", description="Escolha uma das categorias abaixo para abrir seu ticket.", colour=discord.Colour.green())
        view = PanelView()
        await interaction.channel.send(embed=embed, view=view)
        
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="Suporte",
                       style=discord.ButtonStyle.primary,
                       emoji="🎫",
                       custom_id="persistent_view:suporte")
    async def suporte_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Você selecionou **Suporte**. Criando seu ticket...", ephemeral=True)
        
    @discord.ui.button(label="Denúncia",
                       style=discord.ButtonStyle.danger,
                       emoji="❌",
                       custom_id="persistent_view:denuncia")
    async def denuncia_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Você selecionou **Denúncia**. Criando seu ticket...", ephemeral=True)
        
    @discord.ui.button(label="Loja",
                       style=discord.ButtonStyle.sucess,
                       emoji="🛒",
                       custom_id="persistent_view:loja")
    async def loja_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Você selecionou **Loja**. Criando seu ticket...", ephemeral=True)  
    
async def setup_hook(self) -> None:
    self.add_view(TicketView())
                 
async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))