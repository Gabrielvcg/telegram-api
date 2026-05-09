# VPS Deployment

This project should be deployed through GitHub Actions and GHCR.

## Repository Setup

Create a GitHub repository and push this project to `main`.

Never commit `.env`, `data/`, local databases, SSH keys, API tokens, or Telegram tokens.

## GitHub Environment

Create a GitHub environment named `prod`.

Configure these environment variables:

- `VPS_HOST`: VPS IP or hostname.
- `VPS_PORT`: SSH port, usually `22`.
- `VPS_USER`: SSH user used for deployment.
- `VPS_DEPLOY_PATH`: deployment directory, for example `/opt/telegram-ai-assistant`.
- `GHCR_USERNAME`: GitHub username or organization account allowed to pull the package.
- `ALLOWED_USER_IDS`: Telegram user IDs allowed to use the bot.
- `MODEL_NAME`: Claude model, for example `claude-sonnet-4-5`.
- `SYSTEM_PROMPT`: assistant base prompt.
- `HISTORY_LIMIT`: recent message history limit.
- `MAX_TOKENS`: normal response token budget.
- `PLAN_MAX_TOKENS`: planning response token budget.
- `MAX_TELEGRAM_MESSAGE_LENGTH`: Telegram chunk size.
- `RATE_LIMIT_MESSAGES`: user rate limit count.
- `RATE_LIMIT_WINDOW_SECONDS`: user rate limit window.
- `WORKSPACE_READ_ENABLED`: usually `true`.
- `WORKSPACE_WRITE_ENABLED`: usually `true` for the dedicated workspace.
- `WORKSPACE_COMMAND_ENABLED`: usually `true` for workspace agent execution.
- `WORKSPACE_COMMAND_TIMEOUT_SECONDS`: command timeout, for example `120`.
- `WORKSPACE_MAX_OUTPUT_CHARS`: maximum command output returned to Telegram, for example `6000`.
- `WORKSPACE_AGENT_MAX_ATTEMPTS`: maximum `/agent` attempts including automatic repair, for example `2`.
- `WORKSPACE_GIT_AUTHOR_NAME`: Git author name for local agent commits.
- `WORKSPACE_GIT_AUTHOR_EMAIL`: Git author email for local agent commits.
- `PROJECT_TELEGRAM_PATH`: workspace path for the bot repository, usually `projects/telegram-ai-assistant`.
- `PROJECT_TELEGRAM_REPO`: GitHub repository, usually `Gabrielvcg/telegram-api`.
- `PROJECT_TELEGRAM_BASE_BRANCH`: PR base branch, usually `main`.
- `LOG_LEVEL`: usually `INFO`.

Configure these environment secrets:

- `VPS_SSH_KEY`: private SSH key with access to the VPS.
- `GHCR_TOKEN`: GitHub personal access token with `read:packages`, required if the GHCR package is private.
- `TELEGRAM_BOT_TOKEN`: Telegram bot token.
- `ANTHROPIC_API_KEY`: Anthropic API key.
- `PROJECT_TELEGRAM_TOKEN`: fine-grained GitHub PAT limited to the bot repository with `Contents: Read and write` and `Pull requests: Read and write`.

The workflow uses `GITHUB_TOKEN` to push the Docker image to GHCR.

## VPS Preparation

On the VPS, create the deployment folder:

```bash
sudo mkdir -p /opt/telegram-ai-assistant
sudo chown -R vacaro:vacaro /opt/telegram-ai-assistant
cd /opt/telegram-ai-assistant
mkdir -p data workspace
chmod 755 data workspace
```

The workflow creates `/opt/telegram-ai-assistant/.env` from the GitHub `prod` environment and sets it to mode `600`.

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
