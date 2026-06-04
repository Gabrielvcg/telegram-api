# OpenClaw VPS Deployment Runbook

This runbook describes how to deploy and operate OpenClaw on the VPS through GitHub Actions.

## VPS Layout

Recommended deploy path:

```text
/opt/openclaw-assistant
```

Persistent folders:

```text
config/      -> /home/node/.openclaw
workspace/   -> /home/node/.openclaw/workspace
auth/        -> /home/node/.config/openclaw
backups/     -> local backups before risky operations
.env         -> runtime secrets, mode 600
```

Prepare the folder manually if needed:

```bash
sudo mkdir -p /opt/openclaw-assistant
sudo chown -R vacaro:vacaro /opt/openclaw-assistant
cd /opt/openclaw-assistant
mkdir -p config workspace auth backups
chmod 700 config auth
chmod 755 workspace backups
```

## GitHub Environment

Use the existing `prod` environment.

Variables:

- `VPS_HOST`: VPS IP or hostname.
- `VPS_PORT`: SSH port, usually `22`.
- `VPS_USER`: SSH user used for deployment.
- `VPS_DEPLOY_PATH`: recommended `/opt/openclaw-assistant`.
- `OPENCLAW_TELEGRAM_ALLOW_FROM`: Gabriel's numeric Telegram user ID.
- `OPENCLAW_MODEL`: default model, for example `anthropic/claude-sonnet-4-6`.
- `OPENCLAW_IMAGE`: optional image override, default `ghcr.io/openclaw/openclaw:latest`.

Secrets:

- `VPS_SSH_KEY`: private SSH key with VPS access.
- `TELEGRAM_BOT_TOKEN`: BotFather token.
- `ANTHROPIC_API_KEY`: Anthropic provider key.
- `OPENCLAW_GATEWAY_TOKEN`: recommended stable Gateway UI/API token.
- `OPENAI_API_KEY`: optional for OpenAI/Codex runtimes.

If `OPENCLAW_GATEWAY_TOKEN` is missing, the deploy workflow generates or preserves one on the VPS. Add the secret later if you want a stable known value from GitHub.

## Deployment Flow

On every push to `main`, or on manual workflow dispatch:

1. The workflow creates `.env.deploy`.
2. The workflow creates `openclaw.json.deploy`.
3. The bundle is copied over SSH.
4. The VPS creates persistent folders.
5. `docker compose pull` downloads the OpenClaw image.
6. `docker compose up -d` starts the Gateway.
7. The workflow verifies `/healthz`.

Existing `config/openclaw.json` is not overwritten. A fresh generated candidate is stored as `config/openclaw.generated.json` so local runtime customizations survive deploys.

## Health And Logs

```bash
cd /opt/openclaw-assistant
docker compose ps
docker compose logs -f openclaw-gateway
curl -fsS http://127.0.0.1:18789/healthz
curl -fsS http://127.0.0.1:18789/readyz
```

The Gateway UI is bound to localhost:

```text
http://127.0.0.1:18789
```

Use an SSH tunnel from your machine:

```bash
ssh -L 18789:127.0.0.1:18789 vacaro@<VPS_HOST>
```

Then open:

```text
http://127.0.0.1:18789
```

## Telegram Test

1. DM the Telegram bot.
2. Confirm only the allowlisted user can use it.
3. Send a text request.
4. Send a voice note.
5. Ask it to create or inspect a file in the workspace.

If Telegram does not respond:

```bash
cd /opt/openclaw-assistant
docker compose logs --tail=200 openclaw-gateway
```

Check for:

- invalid Telegram token,
- allowlist mismatch,
- model provider auth error,
- OpenClaw config validation error.

## Backup And Rollback

Before risky changes:

```bash
cd /opt/openclaw-assistant
tar -czf backups/openclaw-$(date +%Y%m%d-%H%M%S).tgz config workspace auth .env docker-compose.yml
```

Rollback to a previous repository version:

```bash
git revert <commit>
git push origin main
```

Or on the VPS, stop OpenClaw:

```bash
cd /opt/openclaw-assistant
docker compose down
```

## Expanding Access

Start with Telegram + workspace + GitHub. After that works, add host/Docker access deliberately.

Recommended order:

1. Workspace project work.
2. GitHub auth and PR workflows.
3. Docker commands for specific project folders.
4. Host-level operations only with explicit backup and confirmation policy.

Do not mount `/` or the Docker socket into the Gateway until the baseline system is proven useful.
