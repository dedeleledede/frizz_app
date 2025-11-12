# FRIZZ APP

Bot para o servidor do discord do [FrizzMC](https://discord.gg/UCuU6yUcfb).


## Requisitos

- Python 3.10+
- Dependências em `requirements.txt`.

## Configuração

Crie um arquivo `.env` na raiz do repositório, ou use o arquivo `.env.example` e renomeio para `.env`. Variáveis necessárias:

- TOKEN: Token do bot do Discord.
- GUILD_ID: ID do servidor onde os comandos slash (/) serão adicionados.
- PREFIX: Prefixo de comandos texto (opcional; tem um já pré-definido em `config.py`).

Variáveis relacionadas ao auto-update (opcionais, necessárias apenas se quiser que o bot faça self-update):

- GIT_ADDRESS: URL HTTPS do repositório Git (ex.: `https://github.com/owner/repo.git`).
- ACCESS_TOKEN: Token de acesso (personal access token) para acessar o repositório.
- USERNAME: Nome de usuário para montar a URL autenticada (padrão: `token`).
- BRANCH: Branch a ser rastreada (padrão: `main`).
- DISABLE_SELF_UPDATE: `1` para desabilitar o auto-updater.

## Rodando localmente

1. Instale dependências:
   ```bash
   pip install -r requirements.txt
   ```

2. Crie o `.env` (ou copie o `.env.example`) e preencha as variáveis:
   ```env
   TOKEN=token_do_bot_do_discord
   GUILD_ID=123456789012345678
   PREFIX=!
   # Opcional:
   # GIT_ADDRESS=https://github.com/owner/repo.git
   # ACCESS_TOKEN=seu_token_git
   # USERNAME=token
   # BRANCH=main
   # DISABLE_SELF_UPDATE=0
   ```

3. Inicie o bot:
   ```bash
   python main.py
   ```

## Licença

MIT
