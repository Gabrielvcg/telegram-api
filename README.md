# OpenClaw VPS Assistant

This repository deploys a self-hosted OpenClaw assistant to a VPS.

The old Python Telegram bot has been removed. Telegram, audio handling, agent runtime, tools, memory, and model routing now belong to OpenClaw. This repo is only the deployment wrapper: Docker Compose, GitHub Actions, environment documentation, and operations notes.

## Target Architecture

```text
Telegram text/audio
  -> OpenClaw Gateway on VPS
  -> Gabriel agent
  -> Claude/Codex/OpenAI/OpenClaw tools
  -> VPS workspace, GitHub, shell, projects
  -> Telegram progress and final reply
```

## Runtime

- OpenClaw Gateway Docker image: `ghcr.io/openclaw/openclaw:latest`
- Gateway UI/API: `127.0.0.1:18789`
- Health: `http://127.0.0.1:18789/healthz`
- Readiness: `http://127.0.0.1:18789/readyz`
- Telegram is configured with direct-message allowlist access.
- Voice notes are handled by OpenClaw media audio understanding.

## Local Files

- `docker-compose.yml`: local OpenClaw Compose runtime.
- `docker-compose.prod.yml`: production Compose runtime copied to the VPS.
- `.github/workflows/deploy.yml`: GitHub Actions VPS deploy.
- `.env.example`: local environment template.
- `docs/operations/vps-deploy.md`: deployment and operations runbook.

## Required GitHub Environment

Use the existing GitHub environment named `prod`.

Required variables:

- `VPS_HOST`
- `VPS_PORT`
- `VPS_USER`
- `VPS_DEPLOY_PATH` (recommended: `/opt/openclaw-assistant`)
- `OPENCLAW_TELEGRAM_ALLOW_FROM` (your numeric Telegram user ID)
- `OPENCLAW_MODEL` (default: `anthropic/claude-sonnet-4-5`)

Required secrets:

- `VPS_SSH_KEY`
- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEY`

Recommended secret:

- `OPENCLAW_GATEWAY_TOKEN`

Optional secret:

- `OPENAI_API_KEY` if you later enable OpenAI/Codex runtimes.

Legacy variables from the old Python bot can stay in the GitHub environment; the new workflow ignores them.

## Deploy

Push to `main` or run the `Deploy OpenClaw VPS` workflow manually.

The workflow:

1. Generates `.env` and an initial `openclaw.json`.
2. Copies the deploy bundle to the VPS.
3. Creates persistent folders.
4. Runs `docker compose pull`.
5. Runs `docker compose up -d`.
6. Checks `/healthz`.

## VPS Commands

```bash
cd /opt/openclaw-assistant
docker compose ps
docker compose logs -f openclaw-gateway
curl -fsS http://127.0.0.1:18789/healthz
curl -fsS http://127.0.0.1:18789/readyz
```

If your `VPS_DEPLOY_PATH` still points to the old path, use that path instead.

## Telegram Smoke Test

After deploy:

1. Send a DM to your Telegram bot.
2. Ask: `que puedes hacer ahora mismo en este servidor?`
3. Send a short voice note.
4. Ask it to create a tiny file in the workspace.
5. Check progress and final response in Telegram.

## Security Notes

- The Gateway port is bound to `127.0.0.1`, not public internet.
- Telegram access is allowlisted by numeric user ID.
- The OpenClaw workspace is persistent and private. Treat it as sensitive.
- Do not mount the whole host filesystem until the basic Telegram + workspace flow is proven.
- Host/Docker access should be added deliberately with a specific policy and rollback plan.
