import re
import aiohttp
import asyncio
import secrets
import discord
from discord.ext import commands

WEBHOOK_NAME = "Frizz"
WEBHOOK_AVATAR = "https://cdn.discordapp.com/attachments/781008768925433876/1410721715264426148/frizz-logo-test.png"

# ---- Components V2 type ids (confirmed in modern API typings)
# TextDisplay=10, Thumbnail=11, MediaGallery=12, File=13, Separator=14, Container=17, ActionRow=1, Button=2
# ref: discord-api-types & discord.js docs. 
# We'll also use Section=9 to attach a Thumbnail as an accessory to text. 
# (Section is the "text + accessory" block in Components V2)
# ---------------------------------------------------------------

COMP_FLAG = 1 << 15  # IS_COMPONENTS_V2

URL_RX = re.compile(r"^https?://", re.I)

# marcador invisível (start/end) e codificador
ZW_START = "\u2063\u2063"
ZW_END = "\u2063\u2063"

def _zw_encode_token(token: str) -> str:
    bits = "".join(f"{ord(c):08b}" for c in token)
    return ZW_START + "".join("\u200b" if b == "0" else "\u200c" for b in bits) + ZW_END

def ensure_with_components(url: str) -> str:
    return url if "with_components=" in url else (url + ("&" if "?" in url else "?") + "with_components=true")

def parse_hex_color(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip()
    if s.startswith("#"):
        s = s[1:]
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return None
    return int(s, 16)

def valid_url(u: str) -> bool:
    return bool(URL_RX.match(u))

class CardSession:
    """Holds the in-progress Components V2 message for one user."""
    __slots__ = ("author_id", "build_channel", "top_components", "container_stack","history")

    def __init__(self, author_id: int, build_channel: discord.TextChannel):
        self.author_id = author_id
        self.build_channel = build_channel
        self.top_components: list[dict] = []           # final message components
        self.container_stack: list[dict] = []           # stack of container dicts
        self.history: list[dict] = []  # pilha de ações para desfazer

    @property
    def target(self) -> list[dict]:
        """Return the list to append into (container inner list or top-level)."""
        if self.container_stack:
            return self.container_stack[-1]["components"]
        return self.top_components

    def open_container(self, accent_color: int | None = None):
        container = {"type": 17, "components": []}
        if accent_color is not None:
            container["accent_color"] = accent_color
        self.top_components.append(container)
        self.container_stack.append(container)
        self.history.append({"t": "open_container", "container": container})

    def close_container(self) -> bool:
        if not self.container_stack:
            return False
        self.container_stack.pop()
        return True

    def add_component(self, comp: dict):
        lst = self.target
        lst.append(comp)
        self.history.append({"t": "append", "lst": lst, "obj": comp})

    def undo(self) -> str:
        if not self.history:
            return "Nada para apagar."
        act = self.history.pop()
        t = act["t"]
        if t == "append":
            lst = act["lst"]
            obj = act["obj"]
            # remove a última ocorrência do mesmo objeto
            if lst and lst[-1] is obj:
                lst.pop()
            else:
                try:
                    lst.remove(obj)
                except ValueError:
                    pass
            return "Última ação desfeita."
        if t == "open_container":
            container = act["container"]
            # se o container ainda está aberto, fecha
            if self.container_stack and self.container_stack[-1] is container:
                self.container_stack.pop()
            # remove do nível raiz
            try:
                self.top_components.remove(container)
            except ValueError:
                pass
            return "Container removido."
        return "Nada para apagar."

class BuilderV2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # active sessions keyed by (guild_id, user_id)
        self.sessions: dict[tuple[int, int], CardSession] = {}

    # --------------- Utilities: ensure webhook & POST raw JSON ----------------

    async def _download_avatar_bytes(self) -> bytes | None:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(WEBHOOK_AVATAR) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()

    async def _get_or_create_app_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        # try to find bot-owned, same name
        webhooks = await channel.webhooks()
        me = self.bot.user
        wh = discord.utils.get(webhooks, name=WEBHOOK_NAME, user=me)
        if wh:
            return wh

        avatar_bytes = await self._download_avatar_bytes()
        wh = await channel.create_webhook(name=WEBHOOK_NAME, avatar=avatar_bytes)
        return wh

    async def _post_components_v2(self, webhook: discord.Webhook, payload: dict) -> tuple[int, str]:
        url = ensure_with_components(webhook.url)
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, timeout=30) as resp:
                text = await resp.text()
                return resp.status, text

    # -------------------------- The builder command ---------------------------

    @commands.command(name="buildcard")
    @commands.guild_only()
    async def buildcard(self, ctx: commands.Context, channel: discord.TextChannel):
        """Start an interactive card build session."""
        # restrict one session per (guild, user)
        key = (ctx.guild.id, ctx.author.id)
        if key in self.sessions:
            return await ctx.reply("Voce ja esta fazendo um CARD. Digite **DONE** ou **CANCEL** para finalizar")

        # create a session
        session = CardSession(author_id=ctx.author.id, build_channel=channel)
        self.sessions[key] = session

        await ctx.reply(
            "**Card builder inicializou** para {0.mention} -> CANAL: {1.mention}\n"
            "Digite os elementos linha por linha. **DONE** para enviar, **CANCEL** para abortar\n"
            "**Comandos:**\n"
            "• `TEXT: <conteudo>`\n"
            "• `CONTAINER [#hex]` (entrar no container; cor de destaque opcional)\n"
            "• `BANNER_IMG <url>`\n"
            "• `THUMBNAIL <url>` (adiciona uma pequena imagem acessória ao lado do texto)\n"
            "• `DIVIDER`\n"
            "• `LINK_BUTTON_ROW <url> <texto...>` (botões na mesma linha)\n"
            "• `LINK_BUTTON <url> <texto...>`\n"
            "• `PREVIEW` (visualizar o cartão)\n"
            "• `EXIT` (sair do container atual)\n".format(ctx.author, channel)
        )

        def check(m: discord.Message) -> bool:
            return (
                m.author.id == session.author_id and
                m.channel.id == ctx.channel.id
            )

        try:
            while True:
                # wait for next line (10 minutes timeout)
                msg: discord.Message = await self.bot.wait_for("message", check=check, timeout=600)
                raw = msg.content.strip()

                if not raw:
                    continue

                upper = raw.upper()

                # control commands
                if upper == "CANCEL":
                    del self.sessions[key]
                    await msg.reply("Build cancelada, nada foi enviado")
                    return

                if upper == "DONE":
                    # auto-close any open containers (so you don't lose work)
                    session.container_stack.clear()

                    # ensure webhook
                    try:
                        webhook = await self._get_or_create_app_webhook(session.build_channel)
                    except discord.HTTPException as e:
                        del self.sessions[key]
                        await msg.reply(f"Falha ao garantir webhook: `{e}`")
                        return

                    payload = {
                        "flags": COMP_FLAG,
                        "username": WEBHOOK_NAME,
                        "avatar_url": WEBHOOK_AVATAR,
                        "allowed_mentions": {"parse": []},
                        "components": session.top_components or [{"type": 10, "content": "*empty card*"}],
                    }

                    status, text = await self._post_components_v2(webhook, payload)
                    del self.sessions[key]

                    if 200 <= status < 300:
                        await msg.reply("**Card criado!**")
                    else:
                        await msg.reply(f"Webhook POST falhou ({status}): `{text[:500]}`")
                    return

                if upper == "EXIT":
                    if session.close_container():
                        await msg.reply("Você está agora **fora** do container.")
                    else:
                        await msg.reply("Você não estava dentro de um container.")
                    continue


                if upper == "PREVIEW":
                    # preview no canal atual (ctx.channel)
                    if not isinstance(ctx.channel, discord.TextChannel):
                        await msg.reply("Não é possível fazer preview neste tipo de canal.")
                        continue
                    try:
                        preview_wh = await self._get_or_create_app_webhook(ctx.channel)
                    except discord.HTTPException as e:
                        await msg.reply(f"Falha ao obter webhook de preview: {e}")
                        continue

                    payload = {
                        "flags": COMP_FLAG,
                        "username": WEBHOOK_NAME,
                        "avatar_url": WEBHOOK_AVATAR,
                        "allowed_mentions": {"parse": []},
                        "components": session.top_components or [{"type": 10, "content": ""}],
                    }
                    status, text = await self._post_components_v2(preview_wh, payload)
                    if not (200 <= status < 300):
                        await msg.reply(f"Falha no preview ({status}): {text[:400]}")
                    continue

                if upper == "APAGAR":
                    res = session.undo()
                    await msg.reply(res)
                    continue
                
                # element parsers
                if upper.startswith("TEXT:") or upper.startswith("TEXT "):
                    content = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip()
                    if not content:
                        await msg.reply("Usagem: `TEXT: seu texto`")
                        continue
                    session.add_component({"type": 10, "content": content})
                    await msg.reply("Texto adicionado.")
                    continue

                if upper.startswith("CONTAINER"):
                    parts = raw.split(maxsplit=1)
                    color = parse_hex_color(parts[1]) if len(parts) > 1 else None
                    session.open_container(color)
                    tip = f"com cor `#{parts[1].lstrip('#')}`" if len(parts) > 1 and color is not None else "sem cor"
                    await msg.reply(f"Container aberto ({tip}). Digite **EXIT** para sair do container.")
                    continue

                if upper.startswith("BANNER_IMG"):
                    parts = raw.split(maxsplit=1)
                    if len(parts) < 2 or not valid_url(parts[1]):
                        await msg.reply("Usagem: `BANNER_IMG https://...`")
                        continue
                    session.add_component({
                        "type": 12,  # MediaGallery
                        "items": [{"media": {"url": parts[1]}, "description": None}]
                    })
                    await msg.reply("Banner adicionado.")
                    continue

                if upper.startswith("THUMBNAIL"):
                    parts = raw.split(maxsplit=1)
                    if len(parts) < 2 or not valid_url(parts[1]):
                        await msg.reply("Usagem: `THUMBNAIL https://...`")
                        continue
                    section = {
                        "type": 9,  # Section
                        "components": [{"type": 10, "content": "\u200b"}],  # zero-width spacer
                        "accessory": {
                            "type": 11,  # Thumbnail
                            "media": {"url": parts[1]},
                            "description": None
                        }
                    }
                    session.add_component(section)
                    await msg.reply("Thumbnail adicionada.")
                    continue

                if upper.startswith("DIVIDER"):
                    session.add_component({"type": 14, "divider": True})
                    await msg.reply("Divisor adicionado.")
                    continue

                if upper.startswith("LINK_BUTTON_ROW"):
                    parts = raw.split(maxsplit=2)
                    if len(parts) < 3 or not valid_url(parts[1]):
                        await msg.reply("Usagem: `LINK_BUTTON_ROW https://... Nome do Botão`")
                        continue
                    url, label = parts[1], parts[2]
                    button = {"type": 2, "style": 5, "label": label, "url": url}

                    # se o último componente já for uma Action Row com <5 botões, reaproveita
                    if session.target and isinstance(session.target[-1], dict) \
                    and session.target[-1].get("type") == 1 \
                    and len(session.target[-1].get("components", [])) < 5:
                        session.target[-1]["components"].append(button)
                    else:
                        session.add_component({"type": 1, "components": [button]})

                    await msg.reply("Botão de link adicionado na mesma linha.")
                    continue

                if upper.startswith("LINK_BUTTON"):
                    # LINK_BUTTON <url> <label...>
                    parts = raw.split(maxsplit=2)
                    if len(parts) < 3 or not valid_url(parts[1]):
                        await msg.reply("Usagem: `LINK_BUTTON https://... Nome do Botão`")
                        continue
                    url, label = parts[1], parts[2]

                    session.add_component({
                        "type": 1,  # Action Row
                        "components": [
                            {"type": 2, "style": 5, "label": label, "url": url}
                        ]
                    })
                    await msg.reply("Botão de link adicionado.")
                    continue

                if upper.startswith("GAW_BUTTON"):
                    parts = raw.split(maxsplit=2)
                    if len(parts) < 3:
                        await msg.reply("usagem giveaway: nome gid")
                        continue

                    gid, label = parts[1].strip(), parts[2].strip()
                    
                    action_row = {
                        "type": 1,
                        "components": [
                            {"type": 2, "style": 1, "label": label, "custom_id": f"gaw:join:{gid}"},
                        ]
                    }
                    session.add_component(action_row)
                    await msg.reply(f"botao adicionado")
                    continue

                if upper.startswith("GAW_COUNT"):
                    parts = raw.split(maxsplit=2)
                    if len(parts) < 3:
                        await msg.reply("Usagem: GIVEAWAY_COUNT <gid> <rotulo>")
                        continue

                    gid, label = parts[1].strip(), parts[2].strip()
                    marker = _zw_encode_token(f"gaw:count:{gid}")

                    session.add_component({
                        "type": 10,
                        "content": f"{label}: 0{marker}"
                    })
                    await msg.reply("contador adicionado")
                    continue

                if upper.startswith("GAW_TEMPO"):
                    parts = raw.split(maxsplit=2)
                    if len(parts) < 3:
                        await msg.reply("Usagem: TEMPO <gid> <rotulo>")
                        continue

                    gid, label = parts[1].strip(), parts[2].strip()
                    marker = _zw_encode_token(f"gaw:time:{gid}")

                    session.add_component({
                        "type": 10,
                        "content": f"{label} {marker}"
                    })
                    await msg.reply("tempo adicionado")
                    continue

                if upper.startswith("GAW"):
                    gid = f"gaw-{ctx.guild.id}-{secrets.token_hex(4)}"
                    await ctx.reply(f"GID: {gid}")
                    continue

                # unknown
                await msg.reply(
                    "Entrada desconhecida. Tente uma das seguintes: `TEXT:`, `CONTAINER [#hex]`, `BANNER_IMG`, "
                    "`THUMBNAIL`, `DIVIDER`, ,`LINK_BUTTON_ROW`, `LINK_BUTTON`, `PREVIEW`, `APAGAR`, `EXIT`, `DONE`."
                )

        except asyncio.TimeoutError:
            # cleanup stale session
            self.sessions.pop(key, None)
            await ctx.reply("O construtor expirou (10 minutos). Sessão encerrada.")

async def setup(bot: commands.Bot):
    await bot.add_cog(BuilderV2Cog(bot))