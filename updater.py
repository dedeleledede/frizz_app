def self_update():
    import os, subprocess, io, zipfile, urllib.request, shutil, tempfile, glob, time

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    address = os.getenv('GIT_ADDRESS')
    branch = os.getenv('BRANCH', 'main')
    username = os.getenv('USERNAME', 'token')
    token = os.getenv('ACCESS_TOKEN')

    # >>> arquivos/pastas que NÃO devem ser apagados por update
    PRESERVE = ['.env', 'ticket_config.json']  # adicione outros se precisar, ex: 'data', 'config.local.json'

    if os.getenv('DISABLE_SELF_UPDATE') == '1':
        print('[updater] desativado por DISABLE_SELF_UPDATE=1')
        return
    if not address or not token:
        print('[updater] faltando GIT_ADDRESS ou ACCESS_TOKEN; pulando update')
        return

    authed = f"https://{username}:{token}@{address.split('https://', 1)[-1]}"

    # --- helpers de preservação ---
    tmp_keep = None
    def stash_preserve():
        nonlocal tmp_keep
        tmp_keep = tempfile.mkdtemp(prefix='keep_', dir=repo_dir)
        for name in PRESERVE:
            src = os.path.join(repo_dir, name)
            if os.path.exists(src):
                dst = os.path.join(tmp_keep, name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # move para fora do caminho
                shutil.move(src, dst)
                print(f'[updater] preservando {name}')
    def restore_preserve():
        nonlocal tmp_keep
        if not tmp_keep:
            return
        for root, dirs, files in os.walk(tmp_keep):
            rel = os.path.relpath(root, tmp_keep)
            for d in dirs:
                os.makedirs(os.path.join(repo_dir, rel, d), exist_ok=True)
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(repo_dir, rel, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # se o update criou um arquivo com o mesmo nome, mantemos o preservado
                if os.path.exists(dst):
                    try:
                        os.remove(dst)
                    except Exception:
                        pass
                shutil.move(src, dst)
        try:
            shutil.rmtree(tmp_keep, ignore_errors=True)
        except Exception:
            pass
        print('[updater] itens preservados restaurados')

    def git(*args, check=True):
        return subprocess.run(['git', *args], cwd=repo_dir, check=check,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # --- fluxo via git ---
    try:
        stash_preserve()
        if os.path.isdir(os.path.join(repo_dir, '.git')):
            try:
                git('remote', 'set-url', 'origin', authed, check=False)
            except Exception:
                git('remote', 'add', 'origin', authed, check=False)

            git('fetch', 'origin', branch)
            rc = git('checkout', branch, check=False)
            if rc.returncode != 0:
                git('checkout', '-b', branch, '--track', f'origin/{branch}', check=False)
            git('reset', '--hard', f'origin/{branch}')

            # NÃO usar clean -fdx pois apagaria os preservados
            # Se precisar limpar lixo sem remover preservados, limpe seletivamente.

            print('[updater] atualizado via git')
            restore_preserve()
            return
        else:
            git('init')
            git('remote', 'add', 'origin', authed, check=False)
            git('fetch', 'origin', branch)
            rc = git('checkout', '-b', branch, '--track', f'origin/{branch}', check=False)
            if rc.returncode != 0:
                git('checkout', branch, check=False)
            git('reset', '--hard', f'origin/{branch}')
            print('[updater] inicializado e alinhado via git')
            restore_preserve()
            return
    except Exception as e_git:
        print(f'[updater] git falhou: {e_git}. Tentando fallback ZIP...')

    # --- fallback por ZIP (também preservando) ---
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
            src = glob.glob(os.path.join(tmp, '*'))[0]

            # guarda itens preservados, limpa e copia
            stash_preserve()
            # remove tudo exceto .git (se existir) — mas teu dir provavelmente não tem .git nesse fallback
            for name in os.listdir(repo_dir):
                if name == '.git':
                    continue
                path = os.path.join(repo_dir, name)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                except Exception:
                    pass

            # copia conteúdo novo
            for name in os.listdir(src):
                s = os.path.join(src, name)
                d = os.path.join(repo_dir, name)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

            restore_preserve()
        print('[updater] atualizado via ZIP fallback')
    except Exception as e_zip:
        print(f'[updater] fallback ZIP também falhou: {e_zip}')