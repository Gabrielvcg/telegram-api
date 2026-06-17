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
- `OPENCLAW_MODEL`: default model, recommended `moonshot/kimi-k2.6` for cheaper day-to-day use.
- `OPENCLAW_IMAGE`: optional image override, default `ghcr.io/openclaw/openclaw:latest`.

Secrets:

- `VPS_SSH_KEY`: private SSH key with VPS access.
- `TELEGRAM_BOT_TOKEN`: BotFather token.
- `ANTHROPIC_API_KEY`: Anthropic provider key.
- `MOONSHOT_API_KEY`: Moonshot provider key for Kimi models.
- `OPENCLAW_GATEWAY_TOKEN`: recommended stable Gateway UI/API token.
- `OPENAI_API_KEY`: optional for OpenAI/Codex runtimes.
- `KIMI_API_KEY`: optional separate Kimi Coding or Kimi search key. It is not interchangeable with the Moonshot provider key.

If `OPENCLAW_GATEWAY_TOKEN` is missing, the deploy workflow generates or preserves one on the VPS. Add the secret later if you want a stable known value from GitHub.

## Deployment Flow

On every push to `main`, or on manual workflow dispatch:

1. The workflow creates `.env.deploy`.
2. The workflow creates `openclaw.json.deploy`.
3. The bundle is copied over SSH.
4. The VPS creates persistent folders and copies the host Docker CLI into `tools/`.
5. `docker compose pull` downloads the OpenClaw image.
6. `docker compose up -d` starts the Gateway.
7. The workflow verifies `/healthz`.

Existing `config/openclaw.json` is backed up under `backups/` and then replaced by the generated config so deploys keep the runtime deterministic.

Anthropic model metadata is left to OpenClaw's bundled provider catalog. Do not add a manual `models.providers.anthropic.models` block unless the runtime schema explicitly requires it, because an incorrect custom model row can make OpenClaw route Claude through the OpenAI Responses API. The generated config also avoids `agents.defaults.models` for Claude aliases because that field acts as a model allowlist and can hide bundled catalog entries.

The deploy workflow maps the older `anthropic/claude-haiku-4-5` setting to `anthropic/claude-sonnet-4-6` because OpenClaw 2026.6.1 does not expose that Haiku slug through the Anthropic API catalog.

Kimi/Moonshot is the default primary model via `moonshot/kimi-k2.6`. Claude Sonnet remains configured as the fallback so the assistant can still answer if the Moonshot key is missing, rate-limited, or invalid.

Moonshot and Kimi Coding are separate OpenClaw providers. Use `MOONSHOT_API_KEY` for `moonshot/kimi-k2.6`; use `KIMI_API_KEY` only for `kimi/kimi-for-coding` or Kimi-specific search/coding features.

## Host And Docker Access

The OpenClaw container intentionally has full VPS access:

- `privileged: true`
- user `0:0`
- Docker socket mounted at `/var/run/docker.sock`
- host root mounted read-write at `/host`
- host Docker CLI copied into `tools/` and mounted at `/opt/host-tools`

This lets the Telegram agent run Docker operations such as:

```bash
docker ps
docker compose ps
ls /host
```

Rollback is a normal repository revert plus redeploy:

```bash
git revert <commit-that-enabled-host-access>
git push origin main
```

Before risky host operations, create a VPS backup:

```bash
cd /opt/openclaw-assistant
tar -czf backups/openclaw-host-access-$(date +%Y%m%d-%H%M%S).tgz config workspace auth .env docker-compose.yml
```

Telegram streaming is disabled in the generated config because progress drafts can occasionally fail to finalize in Telegram. The default delivery mode favors receiving the final answer reliably over live progress labels.

Telegram DM policy is generated as `open` with `allowFrom: ["*"]` to avoid OpenClaw Telegram builds that silently drop normal DM text when `dmPolicy: "allowlist"` is used. Agent routing remains pinned to the numeric Telegram user ID from `OPENCLAW_TELEGRAM_ALLOW_FROM`.

Agent context is capped at `100000` tokens and compaction sets `agents.defaults.compaction.reserveTokensFloor` to `20000` so short Telegram turns do not fail with an auto-compaction recovery error after the session has been mapped.

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
2. Confirm the configured numeric Telegram user ID is routed to the agent.
3. Send a text request.
4. Ask it to create or inspect a file in the workspace.

Voice notes are intentionally disabled in the default generated config. Enable them only after configuring a cheap STT provider such as OpenAI transcription or another dedicated speech-to-text backend.

If Telegram does not respond:

```bash
cd /opt/openclaw-assistant
docker compose logs --tail=200 openclaw-gateway
```

Check for:

- invalid Telegram token,
- Telegram peer ID or routing mismatch,
- model provider auth error,
- auto-compaction reserve too low,
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

Host/Docker access is now enabled deliberately after the Telegram + workspace baseline was proven.

Recommended order:

1. Workspace project work.
2. GitHub auth and PR workflows.
3. Docker commands for specific project folders.
4. Host-level operations with explicit backup for destructive maintenance.
