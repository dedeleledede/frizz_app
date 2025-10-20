import asyncio, os, json
import datetime
from typing import Optional
from zoneinfo import ZoneInfo
import re

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button

# ========= Helpers =========

# guardar em um txt externo com o config para nao perder ao reiniciar bot
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'configs', 'ticket_config.json')

CONFIG_KEY = "CONFIG"

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({CONFIG_KEY: config}, f, indent=4)

def load_config() -> dict:
    if not os.path.isfile(CONFIG_FILE):
        print("Creating default config file...")
        default_config = {
            "last_ticket_message_id": None,
            "last_ticket_channel_id": None,
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
        save_config(default_config)
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f).get(CONFIG_KEY, {})

config_dir = os.path.dirname(CONFIG_FILE)
if not os.path.exists(config_dir):
    os.makedirs(config_dir)

CONFIG = load_config()

# construir nome do canal
def build_channel_name(category: str, author: discord.Member) -> str:
    # normaliza so para comparar
    cat = (category or "ticket").strip().lower()

    # mapeamento minimo
    if cat in ("suporte",):
        emoji, prefix = "🎫", "suporte"
    elif cat in ("denúncia", "denuncia"):
        emoji, prefix = "🚨", "denuncia"
    elif cat in ("loja",):
        emoji, prefix = "🛒", "loja"
    else:
        #basecase
        emoji, prefix = "🎟️", "ticket"

    short = author.display_name.lower().replace(' ', '-')[:16]
    return f"{emoji}{prefix}-{short}"

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
        return True, f"Configuração ausente ou inválida: {', '.join(missing)}\nUtilize /ticket config para configurar o bot."
    return False, None

def clean_ids():
    CONFIG["last_ticket_message_id"] = None
    CONFIG["last_ticket_channel_id"] = None
    save_config(CONFIG)
    pass

# remover caracteres invalidos em arquivos
def safe_filename_part(s: str, maxlen: int = 100) -> str:
    s = re.sub(r'[\\/:"*?<>|]+', '_', s)
    s = re.sub(r'\s+', '_', s).strip('_')
    return s[:maxlen]

async def restore_panel(bot: commands.Bot):
    await bot.wait_until_ready()

    message_id = CONFIG.get("last_ticket_message_id")
    channel_id = CONFIG.get("last_ticket_channel_id")
    if not (message_id and channel_id):
        return  # nothing to restore
    bot.add_view(PanelView())

    # try para resolver canal ou mensagem, ver se e valida
    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(view=PanelView())
        print(f"[tickets] Restored ticket panel on message {msg.id} in channel {channel.id}")
    except discord.NotFound:
        print("[tickets] Could not restore ticket panel: message or channel not found.")
        clean_ids()
    except discord.Forbidden:
        print("[tickets] Could not restore ticket panel: missing permissions to access channel or message.")
        clean_ids()
    except discord.HTTPException as e:
        print(f"[tickets] Could not restore ticket panel: HTTP error {e}")
    except Exception as e:
        print(f"[tickets] Could not restore ticket panel: {e}")

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

        # pingar cargo de staff 
        view = TicketControlsView(opener_id=interaction.user.id)
        await channel.send(content=f"<@&.{CONFIG.get('staff_role_id')}>", embed=embed, view=view)

        await channel.send(f"{interaction.user.mention} criou um ticket na categoria **{self.category}**.")

        await interaction.followup.send(content=f"Ticket criado com sucesso: {channel.mention}", ephemeral=True)
        
# painel de abertura de tickets
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Suporte", style=discord.ButtonStyle.primary, custom_id="create_ticket_suporte", emoji="🎫")
    async def create_ticket_suporte(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal("Suporte"))
        
    @discord.ui.button(label="Denúncia", style=discord.ButtonStyle.danger, custom_id="create_ticket_denuncia", emoji="🚨")
    async def create_ticket_denuncia(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal("Denúncia"))
        
    @discord.ui.button(label="Loja", style=discord.ButtonStyle.success, custom_id="create_ticket_loja", emoji="🛒")
    async def create_ticket_loja(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal("Loja"))

# controles dentro do ticket para visualizacao e gerenciamento
class TicketControlsView(discord.ui.View):
    def __init__(self, opener_id: int):
        super().__init__(timeout=None)
        self.opener_id = opener_id

    @discord.ui.button(label="Assumir", style=discord.ButtonStyle.success, custom_id="ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        #checagem staff (depois fazer verificacao por cargos)
        if not interaction.user.roles == interaction.guild.get_role(CONFIG.get("staff_role_id")):
            await interaction.response.send_message("Você não tem permissão para assumir tickets.", ephemeral=True)
            return
        await interaction.response.defer()
        if interaction.message and interaction.message.embeds:
            emb = interaction.message.embeds[0]
            emb.set_footer(text=f"Assumido por {interaction.user}")
            await interaction.message.edit(embed=emb, view=self)
        else:
            await interaction.followup.send("ticket assumido", ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.danger, custom_id="ticket:close")

    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await do_close(interaction, reason="Fechado via botão")

# ===== acoes core ======

async def do_close(interaction: discord.Interaction, reason: str):
    guild = interaction.guild
    channel = interaction.channel
    assert guild and isinstance(channel, discord.TextChannel)

    # checagem staff (depois fazer verificacao por cargos)
    if not interaction.user.roles == interaction.guild.get_role(CONFIG.get("staff_role_id")):
        await interaction.response.send_message("Você não tem permissão para fechar tickets.", ephemeral=True)
        return

    await interaction.response.defer()
    
    # avaliacao 1-5 botoes

    class RatingView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=config["rating_timeout"])
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

#    transcript_file = None
#    try:
#        import chat_exporter
#        #timezone: gmc -3 arrumar
#        export = await chat_exporter(channel, limit=None, tz_info="America/Sao_Paulo", military_time=True, bot=bot)
        
#        if export is not None:
#            html_bytes = export.encode('utf-8')
#            transcript_file = discord.File(fp=discord.BytesIO(html_bytes)), filename=f"{channel.name}-{discord.utils.format_dt(ts, style="R")}.html"

#        # timezone-aware timestamp in user's timezone (America/Sao_Paulo)
#        now = datetime.now(ZoneInfo("America/Sao_Paulo"))
#        timestamp = now.strftime("%Y%m%d-%H%M%S")  # ex 20251009-142530
#
#        channel_part = safe_filename_part(getattr(channel, "name", f"channel-{channel.id}"))
#        filename = f"{channel_part}-{timestamp}.html"
#    except Exception:
#        pass
        
    
    # remover permissao de escrita para todos (exceto staff)
    overwrites = channel.overwrites
    author_id = extract_author_id(channel.topic)
    if author_id:
        member = guild.get_member(int(author_id))
        if member and member in overwrites:
            overwrites.pop(member, None)
    
        await channel.edit(overwrites=overwrites, reason="Ticket encerrado")

        await channel.send("encerrado")
        # enviar log para canal de logs
        # delete provisorio
        wait_time = 5  # segundos
        await channel.send(f"Este canal será excluído em {wait_time} segundos.")

        await asyncio.sleep(wait_time)
        await channel.delete(reason="Ticket encerrado")

def extract_author_id(topic: Optional[str]) -> Optional[int]:
    try:
        if not topic:
            return None
        for part in topic.split(";"):
            if 'ticket_author_id=' in part:
                return int(part.split('=')[1].strip())
    except Exception as e:
        print(f"ERROR EXTRACTING ID: {e}")
        return None
 
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # recuperar painel
    async def cog_load(self):
        try:
            asyncio.create_task(restore_panel(self.bot))
        except Exception as e:
            print(f"[tickets] Startup restore failed to schedule: {e}")

    # grupo de comandos /ticket
    group = app_commands.Group(name="ticket", description="Utilidades e configuracoes de tickets.")

    #publicar painel
    @group.command(name="panel", description="Publica o painel de abertura de tickets no canal atual.")
    @app_commands.checks.has_role(CONFIG.get("staff_role_id"))
    async def panel(self, interaction: discord.Interaction):
        # checagem de configs
        missing, message = check_configs()
        if missing:
            await interaction.response.send_message(message, ephemeral=True)
            return False

        await interaction.response.send_message("Painel publicado.", ephemeral=True)

        embed = discord.Embed(title="Abertura de Tickets", description="Escolha uma das categorias abaixo para abrir seu ticket.", colour=discord.Colour.green())
        view = PanelView()

        msg = await interaction.channel.send(embed=embed, view=view)
        # salvar id da mensagem e canal
        CONFIG["last_ticket_message_id"] = msg.id
        CONFIG["last_ticket_channel_id"] = msg.channel.id
        save_config(CONFIG)

    #debug 
    @group.command(name="debug", description="Comando de debug (apenas admins).")
    @app_commands.checks.has_role(CONFIG.get("admin_role_id"))
    async def debug(self, interaction: discord.Interaction):
        # format message to ping roles and channels within the config
        message = f"Current CONFIG: {CONFIG}"
        message += "\n\n**Roles:**"
        for role_id in [CONFIG.get("staff_role_id"), CONFIG.get("admin_role_id")]:
            role = interaction.guild.get_role(role_id)
            if role:
                message += f"\n- {role.mention} ({role.name})"
        message += "\n\n**Channels:**"
        for channel_id in [CONFIG.get("panel_channel_id"), CONFIG.get("logs_channel_id"), CONFIG.get("ticket_category_id")]:
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                message += f"\n- {channel.mention} ({channel.name})"

        # get last ticket message and channel (example #tickets->message reference)
        message += "\n\n**Messages:**"
        last_ticket_channel = interaction.guild.get_channel(CONFIG.get("last_ticket_channel_id"))
        last_ticket_message = CONFIG.get("last_ticket_message_id")

        if last_ticket_channel and last_ticket_message:
            try:
                msg = await last_ticket_channel.fetch_message(last_ticket_message)
                message += f"\n- Last ticket message found in {last_ticket_channel.mention}: {msg.jump_url}"
            except Exception as e:
                message += f"\n- Could not fetch last ticket message: {e}"
        else:
            message += "\n- No last ticket message or channel saved."

        await interaction.response.send_message(message, ephemeral=True)

    # configurar tickets
    @group.command(name="config", description="Configura IDs de canais e cargos")
    @app_commands.describe(panel_channel_id="Canal onde o painel de tickets sera postado", logs_channel_id="Canal onde os logs de tickets serao enviados", ticket_category_id="Categoria onde os tickets serao criados", staff_role_id="Cargo que tera acesso aos tickets", admin_role_id="Cargo com permissoes administrativas no bot", one_ticket_per_user="Permitir apenas um ticket por usuario", enable_anonymous_reports="Permitir tickets anonimos", rating_timeout_sec="Tempo (em segundos) para aguardar avaliacao apos fechamento do ticket (default 20s)", sla_warn_hours="Horas para avisar sobre SLA (0 para desativar, default 24h)", sla_autoclose_hours="Horas para fechar automaticamente o ticket (0 para desativar, default 48h)")
    @app_commands.checks.has_role(CONFIG.get("admin_role_id"))
    async def config_cmd(self, interaction: discord.Interaction,
        panel_channel_id: Optional[discord.TextChannel] = None,
        logs_channel_id: Optional[discord.TextChannel] = None,
        ticket_category_id: Optional[discord.CategoryChannel] = None,
        staff_role_id: Optional[discord.Role] = None,
        admin_role_id: Optional[discord.Role] = None,
        one_ticket_per_user: Optional[bool] = None,
        enable_anonymous_reports: Optional[bool] = None,
        rating_timeout_sec: Optional[int] = None,
        sla_warn_hours: Optional[int] = None,
        sla_autoclose_hours: Optional[int] = None
    ):
        changes = []
        if panel_channel_id is not None:
            CONFIG["panel_channel_id"] = panel_channel_id.id if hasattr(panel_channel_id, "id") else panel_channel_id
            changes.append(f"panel_channel_id definido para <#{CONFIG['panel_channel_id']}>")
        if logs_channel_id is not None:
            CONFIG["logs_channel_id"] = logs_channel_id.id if hasattr(logs_channel_id, "id") else logs_channel_id
            changes.append(f"logs_channel_id definido para <#{CONFIG['logs_channel_id']}>")
        if ticket_category_id is not None:
            CONFIG["ticket_category_id"] = ticket_category_id.id if hasattr(ticket_category_id, "id") else ticket_category_id
            changes.append(f"ticket_category_id definido para <#{CONFIG['ticket_category_id']}>")
        if staff_role_id is not None:
            CONFIG["staff_role_id"] = staff_role_id.id if hasattr(staff_role_id, "id") else staff_role_id
            changes.append(f"staff_role_id definido para <@&{CONFIG['staff_role_id']}>")
        if admin_role_id is not None:
            CONFIG["admin_role_id"] = admin_role_id.id if hasattr(admin_role_id, "id") else admin_role_id
            changes.append(f"admin_role_id definido para <@&{CONFIG['admin_role_id']}>")
        if one_ticket_per_user is not None:
            CONFIG["one_ticket_per_user"] = one_ticket_per_user
            changes.append(f"one_ticket_per_user definido para {one_ticket_per_user}")
        if enable_anonymous_reports is not None:
            CONFIG["enable_anonymous_reports"] = enable_anonymous_reports
            changes.append(f"enable_anonymous_reports definido para {enable_anonymous_reports}")
        if rating_timeout_sec is not None:
            CONFIG["rating_timeout_sec"] = rating_timeout_sec
            changes.append(f"rating_timeout_sec definido para {rating_timeout_sec} segundos")
        if sla_warn_hours is not None:
            CONFIG["sla_warn_hours"] = sla_warn_hours
            changes.append(f"sla_warn_hours definido para {sla_warn_hours} horas")
        if sla_autoclose_hours is not None:
            CONFIG["sla_autoclose_hours"] = sla_autoclose_hours
            changes.append(f"sla_autoclose_hours definido para {sla_autoclose_hours} horas")

        try:
            # Load existing config to avoid overwriting unrelated values
            if os.path.isfile(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    existing = json.load(f)
            else:
                existing = {}
            existing[CONFIG_KEY] = CONFIG
            save_config(existing)
        except Exception as e:
            await interaction.response.send_message(f"Erro ao salvar configurações: {e}", ephemeral=True)
            return
    
        save_config(CONFIG)

        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({"CONFIG": CONFIG}, f, indent=4)
        except Exception as e:
            await interaction.response.send_message(f"Erro ao salvar configurações: {e}", ephemeral=True)
            return

        embed = discord.Embed(title="Configurações de Tickets Atualizadas", description="\n".join(changes), colour=discord.Colour.blue(), timestamp=discord.utils.utcnow())
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))