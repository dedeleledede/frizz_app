import os, sys, discord
from discord.ext import commands
from dotenv import load_dotenv

cogs_path = os.path.join(os.path.dirname(__file__), 'cogs')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))     
PARENT_DIR = os.path.dirname(BASE_DIR)                  
load_dotenv(os.path.join(BASE_DIR, '.env'))  
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import config

# --- SELF UPDATE (Orihost sem console/sem startup editável) ---
def self_update():
    import os, subprocess, io, zipfile, urllib.request, shutil, tempfile, glob

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    address = os.getenv('GIT_ADDRESS')
    branch = os.getenv('BRANCH', 'main')
    username = os.getenv('USERNAME', 'token')
    token = os.getenv('ACCESS_TOKEN')

    if os.getenv('DISABLE_SELF_UPDATE') == '1':
        print('[updater] desativado por DISABLE_SELF_UPDATE=1')
        return
    if not address or not token:
        print('[updater] faltando GIT_ADDRESS ou ACCESS_TOKEN; pulando update')
        return

    authed = f"https://{username}:{token}@{address.split('https://', 1)[-1]}"

    def git(*args, check=True):
        return subprocess.run(['git', *args], cwd=repo_dir, check=check,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        # Tenta via git (se houver CLI disponível no container)
        if os.path.isdir(os.path.join(repo_dir, '.git')):
            try:
                git('remote', 'set-url', 'origin', authed, check=False)
            except Exception:
                git('remote', 'add', 'origin', authed, check=False)

            git('fetch', 'origin', branch)
            # checkout pode falhar se o branch local não existir ainda; tente criar/track
            rc = git('checkout', branch, check=False)
            if rc.returncode != 0:
                git('checkout', '-b', branch, '--track', f'origin/{branch}', check=False)
            git('reset', '--hard', f'origin/{branch}')
            git('clean', '-fdx')
            print('[updater] atualizado via git')
            return
        else:
            # Diretório sem .git (mas com arquivos) → inicializa e alinha com remoto
            git('init')
            git('remote', 'add', 'origin', authed, check=False)
            git('fetch', 'origin', branch)
            rc = git('checkout', '-b', branch, '--track', f'origin/{branch}', check=False)
            if rc.returncode != 0:
                git('checkout', branch, check=False)
            git('reset', '--hard', f'origin/{branch}')
            git('clean', '-fdx')
            print('[updater] inicializado e alinhado via git')
            return
    except Exception as e_git:
        print(f'[updater] git falhou: {e_git}. Tentando fallback ZIP...')

    # Fallback: baixa o ZIP do branch pelo GitHub/forge (sem dependências externas)
    try:
        zip_url = address.rstrip('.git') + f'/archive/refs/heads/{branch}.zip'
        req = urllib.request.Request(
            zip_url,
            headers={'Authorization': f'token {token}', 'User-Agent': 'orihost-self-updater'}
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(tmp)
            src = glob.glob(os.path.join(tmp, '*'))[0]  # pasta do repo dentro do zip

            # Copia conteúdo por cima (apaga antes pra evitar lixo)
            for name in os.listdir(src):
                if name == '.git':
                    continue
                s = os.path.join(src, name)
                d = os.path.join(repo_dir, name)
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
                else:
                    try:
                        os.remove(d)
                    except FileNotFoundError:
                        pass
                shutil.move(s, d)
        print('[updater] atualizado via ZIP fallback')
    except Exception as e_zip:
        print(f'[updater] fallback ZIP também falhou: {e_zip}')

# Chame isso logo no início do programa:
self_update()
# --- FIM SELF UPDATE ---

token = config.DEBUG_TOKEN

if not token:
    raise RuntimeError("Token ausente. Verifique o .env e o carregamento com load_dotenv().")

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned_or('-', config.PREFIX), intents=intents)

    async def setup_hook(self):
        # load cogs
        for filename in os.listdir(cogs_path):
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
bot.run(token)