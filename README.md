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
- Default model: Claude Haiku 4.5 with thinking off and no automatic fallback to a more expensive model.
- Anthropic model metadata is resolved through OpenClaw's bundled provider catalog, and the generated config does not set an agent model allowlist.
- Host access is intentionally enabled: OpenClaw runs privileged, can use the Docker socket, and can inspect the host filesystem through `/host`.
- The host Docker CLI is mounted into the container as `docker` and `docker-compose`.
- Telegram direct-message routing is pinned to `OPENCLAW_TELEGRAM_ALLOW_FROM`.
- Voice notes are handled by OpenClaw media audio understanding.
- Telegram streaming is disabled by default so the chat receives final answers reliably instead of progress drafts.
- Telegram table markdown and edit/delete actions are disabled to favor plain text replies in Telegram Web.
- Routine Telegram runs expose only the direct `exec` tool so VPS status questions use the real shell instead of a JavaScript code-mode bridge.
- Agent context is capped at 40k tokens, bootstrap context is trimmed, and compaction reserves 8k tokens to keep routine Telegram turns cheap while leaving enough room for shell-tool turns.

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
- `OPENCLAW_MODEL` (default: `anthropic/claude-haiku-4-5`)

Required secrets:

- `VPS_SSH_KEY`
- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEY`

Recommended secret:

- `OPENCLAW_GATEWAY_TOKEN`

Optional secret:

- `OPENAI_API_KEY` if you later enable OpenAI/Codex runtimes.
- `MOONSHOT_API_KEY` if you later enable Kimi/Moonshot models.
- `KIMI_API_KEY` if you later use Kimi Coding or Kimi search features that require that separate provider key.

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

Inside the OpenClaw container, the agent should also be able to run:

```bash
docker ps
ls /host
```

If your `VPS_DEPLOY_PATH` still points to the old path, use that path instead.

## Telegram Smoke Test

After deploy:

1. Send a DM to your Telegram bot.
2. Ask: `que puedes hacer ahora mismo en este servidor?`
3. Ask it to create a tiny file in the workspace.
4. Check progress and final response in Telegram.

Voice notes are disabled by default to avoid expensive accidental transcription/model calls. Add a cheap STT provider before enabling audio again.

## Security Notes

- The Gateway port is bound to `127.0.0.1`, not public internet.
- Telegram DM policy uses `open` as an OpenClaw Telegram workaround, but agent routing is pinned to the numeric user ID in `OPENCLAW_TELEGRAM_ALLOW_FROM`.
- The OpenClaw workspace is persistent and private. Treat it as sensitive.
- The container has full host-level access by design. Anyone who can control the Telegram allowlisted agent can effectively control Docker and inspect or modify the VPS through `/host`.
