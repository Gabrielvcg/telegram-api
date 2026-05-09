# VPS Deployment

This project should be deployed through GitHub Actions and GHCR.

## Repository Setup

Create a GitHub repository and push this project to `main`.

Never commit `.env`, `data/`, local databases, SSH keys, API tokens, or Telegram tokens.

## GitHub Secrets

Configure these repository secrets:

- `VPS_HOST`: VPS IP or hostname.
- `VPS_PORT`: SSH port, usually `22`.
- `VPS_USER`: SSH user used for deployment.
- `VPS_SSH_KEY`: private SSH key with access to the VPS.
- `VPS_DEPLOY_PATH`: deployment directory, for example `/opt/telegram-ai-assistant`.

The workflow uses `GITHUB_TOKEN` to push the Docker image to GHCR.

If the GHCR package is private, also configure:

- `GHCR_USERNAME`: GitHub username or organization account allowed to pull the package.
- `GHCR_TOKEN`: GitHub personal access token with `read:packages`.

If the GHCR package is public, these two secrets are not needed.

## VPS Preparation

On the VPS, create the deployment folder:

```bash
sudo mkdir -p /opt/telegram-ai-assistant
sudo chown -R "$USER":"$USER" /opt/telegram-ai-assistant
cd /opt/telegram-ai-assistant
mkdir -p data workspace
chmod 755 data workspace
```

Create `/opt/telegram-ai-assistant/.env` manually on the VPS:

```env
TELEGRAM_BOT_TOKEN=replace-me
ANTHROPIC_API_KEY=replace-me
MODEL_NAME=claude-sonnet-4-5
ALLOWED_USER_IDS=8654601585
SYSTEM_PROMPT=Eres el asistente personal de Gabriel. Responde siempre en español salvo que te hablen en otro idioma. Sé técnico, útil y conciso.
DATABASE_PATH=/app/data/assistant.db
HISTORY_LIMIT=12
MAX_TOKENS=1200
PLAN_MAX_TOKENS=2200
MAX_TELEGRAM_MESSAGE_LENGTH=3900
RATE_LIMIT_MESSAGES=20
RATE_LIMIT_WINDOW_SECONDS=60
WORKSPACE_ROOT=/app/workspace
WORKSPACE_READ_ENABLED=true
WORKSPACE_WRITE_ENABLED=false
LOG_LEVEL=INFO
```

Install Docker and Docker Compose on the VPS before the first deploy.

## Deployment Flow

On every push to `main`, GitHub Actions will:

1. Build the Docker image.
2. Push it to GHCR.
3. Copy `docker-compose.prod.yml` to the VPS as `docker-compose.yml`.
4. Pull the latest image on the VPS.
5. Restart the container.

Manual deploys can be triggered from GitHub Actions with `Deploy VPS -> Run workflow`.

## Useful VPS Commands

```bash
cd /opt/telegram-ai-assistant
docker compose ps
docker logs -f telegram-bot
docker compose pull
docker compose up -d
docker compose down
```

The SQLite database is stored in:

```text
/opt/telegram-ai-assistant/data/assistant.db
```
