import re
import aiohttp
import asyncio
import random
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

WEBHOOK_NAME = "Frizz"

ZW_START = "\u2063\u2063"
ZW_END = "\u2063\u2063"

# -------- utilidades --------

DUR_RX = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.I)  # 10m, 2h, 1d, 45s
MARK_RX = re.compile(r'\u2063gaw:count:([^\u2063]+)\u2063')  # marcador invisivel no texto

def parse_duration(s: str) -> timedelta | None:
    m = DUR_RX.match(s or "")
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    return {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }.get(unit)

# -------- dados de sorteio --------

@dataclass
class Giveaway:
    id: str
    guild_id: int
    channel_id: int
    winners: int
    ends_at: datetime
    participants: set[int] = field(default_factory=set)

# -------- Cog --------

class GiveawayManager(commands.Cog):
    """
    Gerencia sorteios com botao.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[str, Giveaway] = {}           # gid
        self.pending_clicks: dict[str, set[int]] = {}   # gid -> cliques antes do gaw_set
        # bindings: onde atualizar contadores na mensagem
        # gid -> [ { "webhook_url": str, "message_id": int, "base_labels": {path->label} } ]
        self.bindings: dict[str, list[dict]] = {}

    def _zw_find_and_decode(self, s: str):
        i = s.find(ZW_START)
        if i == -1:
            return None
        j = s.find(ZW_END, i + len(ZW_START))
        if j == -1:
            return None
        payload = s[i + len(ZW_START): j]
        if any(ch not in ("\u200b", "\u200c") for ch in payload):
            return None
        bits = "".join("0" if ch == "\u200b" else "1" for ch in payload)
        if len(bits) % 8 != 0:
            return None
        decoded = "".join(chr(int(bits[k:k+8], 2)) for k in range(0, len(bits), 8))
        return decoded, s[i:j + len(ZW_END)]

    async def _write_time_once(self, gid: str):
        g = self.active.get(gid)
        if not g or not g.ends_at:
            return

        ts = int(g.ends_at.timestamp())

        for b in self.bindings.get(gid, []):
            url = b.get("webhook_url")
            ch_id = b.get("channel_id")
            mid = b.get("message_id")
            base_labels = b.setdefault("base_labels", {})

            if not url:
                ch = self.bot.get_channel(ch_id or 0)
                if not isinstance(ch, discord.TextChannel):
                    continue
                try:
                    webhooks = await ch.webhooks()
                except discord.HTTPException:
                    continue
                me = self.bot.user
                wh = discord.utils.find(lambda w: w.user == me and w.name == WEBHOOK_NAME, webhooks)
                if not wh:
                    continue
                url = wh.url
                b["webhook_url"] = url

            # GET da mensagem atual
            get_url = url + f"/messages/{mid}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(get_url) as r:
                    if r.status != 200:
                        continue
                    msg_json = await r.json()

            comps = msg_json.get("components") or []
            changed, base_labels = self._set_time_texts(comps, gid, g.ends_at, base_labels)
            if not changed:
                continue

            patch_url = url + f"/messages/{mid}"
            async with aiohttp.ClientSession() as sess:
                await sess.patch(patch_url, json={"components": comps}, timeout=30)
            b["base_labels"] = base_labels
            

    def _set_time_texts(self, comps: list, gid: str, ends_at: datetime | None, base_labels: dict[str, str]) -> tuple[bool, dict[str, str]]:
        """
        Procura TextDisplay (type 10) com marcador invisível 'gaw:time:<gid>'
        e escreve 'Label: <t:UNIX:R>' mantendo o marcador
        """
        changed = False
        if ends_at is None:
            return changed, base_labels

        ts = int(ends_at.timestamp())

        def walk(lst: list, path: str = ""):
            nonlocal changed
            for i, c in enumerate(lst):
                if not isinstance(c, dict):
                    continue
                cur = f"{path}/{i}"
                t = c.get("type")

                if t == 10:
                    content = c.get("content")
                    if isinstance(content, str):
                        found = self._zw_find_and_decode(content)  # precisa existir na classe
                        if found:
                            decoded, token_span = found
                            if decoded.startswith("gaw:time:"):
                                gid_in = decoded.split(":", 2)[2]
                                if gid_in == gid:
                                    # remove contagem/tempo anterior visível, preserva marcador
                                    visible = content.replace(token_span, "")
                                    base = base_labels.get(cur) or re.sub(r'\s*:\s*<?t:\d+:R>?\s*$', '', visible).rstrip()
                                    c["content"] = f"{base}: <t:{ts}:R>{token_span}"
                                    base_labels[cur] = base
                                    changed = True

                inner = c.get("components")
                if isinstance(inner, list):
                    walk(inner, cur)

        walk(comps, "")
        return changed, base_labels

    # -------------------- interacao de botao (entrar/sair) --------------------

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        try:
            data = interaction.data or {}
            cid = data.get("custom_id")
            if not cid or not isinstance(cid, str):
                return
            if not cid.startswith("gaw:join:"):
                return

            gid = cid.split(":", 2)[2]

            # escolhe conjunto de participantes
            g = self.active.get(gid)
            if g:
                part_set = g.participants
            else:
                part_set = self.pending_clicks.setdefault(gid, set())

            uid = interaction.user.id
            if uid in part_set:
                part_set.discard(uid)
                out_msg = "Removido da participação."
                reply = out_msg
            else:
                part_set.add(uid)
                in_msg = "Participação registrada."
                reply = in_msg

            try:
                await interaction.response.send_message(reply, ephemeral=True)
            except discord.InteractionResponded:
                pass

            # atualiza contador
            await self._update_counters(gid)

        except Exception:
            pass

    # --------------------------- comandos de controle --------------------------

    @commands.command(name="gaw_set")
    @commands.guild_only()
    async def gaw_set(self, ctx: commands.Context, giveaway_id: str, channel: discord.TextChannel, duration: str, winners: int):
        """
        Configura um sorteio:
        - giveaway_id: GID mostrado pelo GIVEAWAY_COUNT no builder
        - channel: onde anunciar o sorteio
        - duration: 10m, 2h, 1d, etc.
        - winners: quantidade de vencedores
        """
        td = parse_duration(duration)
        if not td or td.total_seconds() < 5:
            await ctx.reply("Duracao invalida. Use 10m, 2h, 1d, etc.")
            return
        if winners < 1:
            await ctx.reply("Vencedores deve ser >= 1 retard")
            return

        ends_at = datetime.now(timezone.utc) + td
        g = Giveaway(
            id=giveaway_id,
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            winners=winners,
            ends_at=ends_at,
        )

        # funde cliques anteriores
        early = self.pending_clicks.pop(giveaway_id, set())
        g.participants |= early

        self.active[giveaway_id] = g
        # dispara a tarefa de conclusao
        asyncio.create_task(self._run_giveaway(giveaway_id))
        await ctx.reply(f"Sorteio configurado. Termina em {duration}. Vencedores: {winners}.")

        await self._write_time_once(giveaway_id)

        # atualiza contadores ja vinculados
        await self._update_counters(giveaway_id)

    @commands.command(name="gaw_participants")
    @commands.guild_only()
    async def gaw_participants(self, ctx: commands.Context, giveaway_id: str):
        """Lista participantes atuais."""
        g = self.active.get(giveaway_id)
        ids: list[int]
        if g:
            ids = list(g.participants)
        else:
            ids = list(self.pending_clicks.get(giveaway_id, set()))
        if not ids:
            await ctx.reply("Sem participantes no momento.")
            return
        # limita visual para não estourar
        names = [f"<@{i}>" for i in ids][:30]
        more = max(0, len(ids) - 30)
        extra = f" e mais {more}" if more else ""
        await ctx.reply(f"Participantes: {', '.join(names)}{extra}")

    @commands.command(name="gaw_end")
    @commands.guild_only()
    async def gaw_end(self, ctx: commands.Context, giveaway_id: str):
        """Encerra antecipadamente e sorteia agora."""
        if giveaway_id not in self.active:
            await ctx.reply("Sorteio não encontrado ou já encerrado.")
            return
        await self._finish_and_announce(giveaway_id)

    @commands.command(name="gaw_bind")
    @commands.guild_only()
    async def gaw_bind(self, ctx: commands.Context, giveaway_id: str, channel: discord.TextChannel, message: str):
        """
        Vincula uma mensagem publicada para atualizar o contador automaticamente.

        Exemplos:
        -gaw_bind <gid> #canal 123456789012345678
        -gaw_bind <gid> #canal https://discord.com/channels/G/C/M
        """
        # obter message_id a partir do argumento
        if message.isdigit():
            message_id = int(message)
            channel_id_from_link = None
        else:
            _, channel_id_from_link, message_id = self._parse_message_link(message)
            if not message_id:
                await ctx.reply("Mensagem invalida. Envie ID ou link de mensagem.")
                return

        # se veio link e o canal não bate, avisa
        if channel_id_from_link and channel.id != channel_id_from_link:
            await ctx.reply("O canal do link não corresponde ao canal informado.")
            return

        # armazena apenas canal_id e message_id; o webhook será descoberto na hora do update
        self.bindings.setdefault(giveaway_id, []).append({
            "channel_id": channel.id,
            "message_id": message_id,
            "base_labels": {}  # mantém compatibilidade com o contador em texto
        })
        await ctx.reply("Vinculado. Atualizando contador.")

        await self._write_time_once(giveaway_id)

        await self._update_counters(giveaway_id)

    @commands.command(name="gaw_unbind")
    @commands.guild_only()
    async def gaw_unbind(self, ctx: commands.Context, giveaway_id: str, message_id: int):
        """Remove o vinculo de atualizacao de uma mensagem especifica."""
        lst = self.bindings.get(giveaway_id, [])
        before = len(lst)
        lst[:] = [b for b in lst if b.get("message_id") != message_id]
        removed = before - len(lst)
        await ctx.reply("Removido." if removed else "Nada removido.")

    # ----------------------------- internos -----------------------------------

    async def _run_giveaway(self, giveaway_id: str):
        g = self.active.get(giveaway_id)
        if not g:
            return
        delay = max(0, int((g.ends_at - datetime.now(timezone.utc)).total_seconds()))
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        await self._finish_and_announce(giveaway_id)

    async def _finish_and_announce(self, giveaway_id: str):
        g = self.active.pop(giveaway_id, None)
        if not g:
            return

        ch = self.bot.get_channel(g.channel_id)
        if not isinstance(ch, discord.TextChannel):
            return

        pool = list(g.participants)
        if not pool:
            await ch.send(f"Sorteio {giveaway_id} encerrado. Sem participantes.")
            return

        k = min(g.winners, len(pool))
        winners = random.sample(pool, k)
        mentions = " ".join(f"<@{i}>" for i in winners)
        await ch.send(f"Sorteio {giveaway_id} encerrado. Vencedores: {mentions}")

        # atualiza contadores pela ultima vez
        await self._update_counters(giveaway_id)

    # ---- atualizacao do contador ----

    def _parse_message_link(self, link: str) -> tuple[int | None, int | None, int | None]:
        # https://discord.com/channels/<guild>/<channel>/<message>
        try:
            parts = link.rstrip("/").split("/")
            guild_id = int(parts[-3])
            channel_id = int(parts[-2])
            message_id = int(parts[-1])
            return guild_id, channel_id, message_id
        except Exception:
            return None, None, None

    def _set_counter_texts(self, comps: list, gid: str, count: int, base_labels: dict[str, str]) -> tuple[bool, dict[str,str]]:
        """
        Procura TextDisplay (type 10) contendo o marcador invisivel '\u2063gaw:count:<gid>\u2063'
        e substitui o conteudo visivel para 'Label: <count>' mantendo o marcador.
        """
        changed = False

        def walk(lst: list, path: str = ""):
            nonlocal changed
            for i, c in enumerate(lst):
                if not isinstance(c, dict):
                    continue
                t = c.get("type")
                cur = f"{path}/{i}"

                if t == 10:
                    content = c.get("content")
                    if isinstance(content, str):
                        found = self._zw_find_and_decode(content)
                        if found:
                            decoded, token_span = found           # token_span = o trecho invisível já codificado
                            if decoded.startswith("gaw:count:"):
                                gid_in = decoded.split(":", 2)[2]
                                if gid_in == gid:
                                    visible = content.replace(token_span, "")
                                    base = base_labels.get(cur) or re.sub(r"\s*:\s*\d+\s*$", "", visible).rstrip()
                                    c["content"] = f"{base}: {count}{token_span}"  # mantém o marcador invisível
                                    base_labels[cur] = base
                                    changed = True

                inner = c.get("components")
                if isinstance(inner, list):
                    walk(inner, cur)

        walk(comps, "")
        return changed, base_labels

    async def _update_counters(self, gid: str):
        """
        Busca a mensagem via endpoint de webhook, atualiza os componentes (somente textos com marcador)
        e envia PATCH. Requer vínculo previo via gaw_bind.
        """
        # contagem atual
        if gid in self.active:
            count = len(self.active[gid].participants)
        else:
            count = len(self.pending_clicks.get(gid, set()))

        for b in self.bindings.get(gid, []):
            base_labels = b.setdefault("base_labels", {})

            # descobrir webhook_url automaticamente
            webhook_url = b.get("webhook_url")
            if not webhook_url:
                ch = self.bot.get_channel(b.get("channel_id", 0))
                if not isinstance(ch, discord.TextChannel):
                    continue
                try:
                    webhooks = await ch.webhooks()
                except discord.HTTPException:
                    continue

                # procura webhook app-owned com o mesmo nome e dono
                me = self.bot.user
                wh = discord.utils.find(lambda w: w.user == me and w.name == WEBHOOK_NAME, webhooks)
                if not wh:
                    wh = await ch.create_webhook(name=WEBHOOK_NAME)
                    webhook_url = wh.url
                    b["webhook_url"] = webhook_url

                webhook_url = wh.url
                b["webhook_url"] = webhook_url  # cache para as proximas atualizacoes

            url = webhook_url
            mid = b.get("message_id")
            if not mid:
                continue

            # GET da mensagem via endpoint do webhook
            get_url = url + f"/messages/{mid}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(get_url) as r:
                    if r.status != 200:
                        continue
                    msg_json = await r.json()

            comps = msg_json.get("components") or []

            changed_count, base_labels = self._set_counter_texts(comps, gid, count, base_labels)
            if not changed_count:
                continue

            patch_url = url + f"/messages/{mid}"
            async with aiohttp.ClientSession() as sess:
                await sess.patch(patch_url, json={"components": comps}, timeout=30)
            b["base_labels"] = base_labels

# entrypoint da extensão
async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayManager(bot))
