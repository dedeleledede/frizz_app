import asyncio, os, json
import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# guardar em um txt externo com o config para nao perder ao reiniciar bot
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'configs', 'ticket_config.json')

config_dir = os.path.dirname(CONFIG_FILE)
if not os.path.exists(config_dir):
    os.makedirs(config_dir)

if not CONFIG_FILE or not os.path.isfile(CONFIG_FILE):
    with open(CONFIG_FILE, 'w') as f:
        print("Creating default config file...")
        json.dump({
            "CONFIG": {
                "last_ticket_message_id": 0,
                "ticket_category_id": 0,
                "panel_channel_id": 0,
                "staff_role_id": 0,
                "admin_role_id": 0,
                "logs_channel_id": 0,
                "one_ticket_per_user": True,
                "enable_anonymous_reports": True,
                "rating_timeout_sec": 20,
                "sla_warn_hours": 24,
                "sla_autoclose_hours": 48
            }
        }, f, indent=4)
# load config e pegar dps com CONFIG.get("key")
with open(CONFIG_FILE, 'r') as f:
    CONFIG = json.load(f).get("CONFIG", {})

# ========= Helpers =========
def build_channel_name(category: str, author: discord.Member) -> str:
    short = author.display_name.lower().replace(' ', '-')[:16]
    emoji = {"teste":"🤡"}.get(category, "🤡")
    return f"{emoji}ticket-{short}"

# checar se as configs basicas estao ok
def check_configs():
    missing = []
    required_keys = [
        "ticket_category_id",
        "panel_channel_id",
        "staff_role_id",
        "admin_role_id",
        "logs_channel_id"
    ]
    for key in required_keys:
        if CONFIG.get(key, 0) == 0:
            missing.append(key)
    if missing:
        return True, f"Configuração ausente ou inválida: {', '.join(missing)}\nUtilize /configure para configurar o bot."
    return False, None

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

    # quando o modal for enviado
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        assert guild is not None

        # checar se user ja tem ticket aberto
        if CONFIG.get("one_ticket_per_user", True):
            for ch in guild.text_channels:
                if ch.topic and f"ticket_author_id={interaction.user.id}" in ch.topic and ch.permissions_for(interaction.user).view_channel:
                    return await interaction.followup.send(content=f"Você já possui um ticket aberto: {ch.mention}", ephemeral=True)

        ticket_category_id = CONFIG.get("ticket_category_id")
        print("ticket_category_id:", ticket_category_id)
        parent = guild.get_channel(ticket_category_id) if ticket_category_id and ticket_category_id != 0 else None

        channel = await guild.create_text_channel(
            name=build_channel_name(self.category, interaction.user),
            category=parent,
            topic=f"ticket_category={self.category}; ticket_author_id={interaction.user.id}",
            reason="Novo ticket criado via modal."
        )

        author_label = interaction.user.mention if not self.anonymous else "Anônimo"

        embed = discord.Embed(title=f"Ticket de {self.category.title()}",
        colour=0x2fffeb, timestamp=discord.utils.utcnow())
        embed.add_field(name=interaction.user.display_name, value=author_label, inline=True)
        embed.add_field(name="descricao", value=self.desc.value, inline=False)

        # CONFIGURAR CARGO STAFF DPS
        view = TicketControlsView(opener_id=interaction.user.id)
        await channel.send(content=f"@.staff", embed=embed, view=view)

        await channel.send(f"{interaction.user.mention} criou um ticket na categoria **{self.category}**.")

        await interaction.followup.send(content=f"Ticket criado com sucesso: {channel.mention}", ephemeral=True)

# painel de abertura de tickets
# depois adicionar fail-safe para caso o bot desligue, o botao continuar funcionando (ao criar, salvar id da mensagem de ticket para recuperar)
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Criar teste ticket", style=discord.ButtonStyle.primary, custom_id="create_ticket_button")
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal("teste"))

# controles dentro do ticket para visualizacao e gerenciamento
class TicketControlsView(discord.ui.View):
    def __init__(self, opener_id: int):
        super().__init__(timeout=None)
        self.opener_id = opener_id

    @discord.ui.button(label="assumir", style=discord.ButtonStyle.success, custom_id="ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        #checagem staff (depois fazer verificacao por cargos)
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Você não tem permissão para assumir tickets.", ephemeral=True)
            return
        await interaction.response.defer()
        if interaction.message and interaction.message.embeds:
            emb = interaction.message.embeds[0]
            emb.set_footer(text=f"Assumido por {interaction.user}")
            await interaction.message.edit(embed=emb, view=self)
        else:
            await interaction.followup.send("ticket assumido", ephemeral=True)

    @discord.ui.button(label="fechar", style=discord.ButtonStyle.danger, custom_id="ticket:close")

    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await do_close(interaction, reason="Fechado via botão")

# ===== acoes core ======

async def do_close(interaction: discord.Interaction, reason: str):
    guild = interaction.guild
    channel = interaction.channel
    assert guild and isinstance(channel, discord.TextChannel)

    # checagem staff (depois fazer verificacao por cargos)
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("Você não tem permissão para fechar tickets.", ephemeral=True)
        return

    await interaction.response.defer()
    
    # avaliacao 1-5 botoes

    class RatingView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)  # expira em 60 segundos, dps adc config
            self.value: Optional[int] = None

        @discord.ui.button(label="1", style=discord.ButtonStyle.secondary)
        async def one(self, i: discord.Interaction, b: discord.ui.Button):
            self.value = 1; self.stop(); await i.response.defer()

        @discord.ui.button(label="2", style=discord.ButtonStyle.secondary)
        async def two(self, i: discord.Interaction, b: discord.ui.Button):
            self.value = 2; self.stop(); await i.response.defer()

        @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
        async def three(self, i: discord.Interaction, b: discord.ui.Button):
            self.value = 3; self.stop(); await i.response.defer()

        @discord.ui.button(label="4", style=discord.ButtonStyle.secondary)
        async def four(self, i: discord.Interaction, b: discord.ui.Button):
            self.value = 4; self.stop(); await i.response.defer()

        @discord.ui.button(label="5", style=discord.ButtonStyle.secondary)
        async def five(self, i: discord.Interaction, b: discord.ui.Button):
            self.value = 5; self.stop(); await i.response.defer()

    msg = await channel.send("Por favor, avalie o atendimento de 1 a 5:")
    view = RatingView()
    await msg.edit(view=view)
    try:
        await view.wait()
    except Exception:
        pass
    rating = view.value

    # HTML TRANSCRIPT
    print("obter transcript (futuro)")
    # remover permissao de escrita para todos (exceto staff)
    overwrites = channel.overwrites
    author_id = extract_author_id(channel.topic)
    print(f"author_id extraido: {author_id}")
    if author_id:
        member = guild.get_member(int(author_id))
        if member and member in overwrites:
            overwrites.pop(member, None)
    
        await channel.edit(overwrites=overwrites, reason="Ticket encerrado")

        await channel.send("encerrado")

        print(2)
        # delete provisorio
        wait_time = 5  # segundos
        await channel.send(f"Este canal será excluído em {wait_time} segundos.")

        print(3)

        await asyncio.sleep(wait_time)
        await channel.delete(reason="Ticket encerrado")

def extract_author_id(topic: Optional[str]) -> Optional[int]:
    try:
        if not topic:
            print("NO TOPIC")
            return None
        for part in topic.split(";"):
            print("YES TOPIC")
            if 'ticket_author_id=' in part:
                print("FOUND ID")
                return int(part.split('=')[1].strip())
    except Exception as e:
        print(f"ERROR EXTRACTING ID: {e}")
        return None

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    #publicar painel
    @app_commands.command(name="ticket_panel", description="Publica o painel de abertura de tickets no canal atual.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        # checagem de configs
        #missing, message = check_configs()
        #if missing:
        #    await interaction.response.send_message(message, ephemeral=True)
        #    return False

        await interaction.response.send_message("Painel publicado.", ephemeral=True)
        embed = discord.Embed(title="Abertura de Tickets", description="Escolha uma das categorias abaixo para abrir seu ticket.", colour=discord.Colour.green())
        view = PanelView()
        await interaction.channel.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))