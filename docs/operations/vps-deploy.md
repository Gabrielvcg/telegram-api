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
- `OPENCLAW_MODEL`: default model, recommended `anthropic/claude-haiku-4-5` for cheaper day-to-day use.
- `OPENCLAW_IMAGE`: optional image override, default `ghcr.io/openclaw/openclaw:latest`.

Secrets:

- `VPS_SSH_KEY`: private SSH key with VPS access.
- `TELEGRAM_BOT_TOKEN`: BotFather token.
- `ANTHROPIC_API_KEY`: Anthropic provider key.
- `OPENCLAW_GATEWAY_TOKEN`: recommended stable Gateway UI/API token.
- `OPENAI_API_KEY`: optional for OpenAI/Codex runtimes.
- `MOONSHOT_API_KEY`: optional Moonshot provider key for Kimi models.
- `KIMI_API_KEY`: optional separate Kimi Coding or Kimi search key. It is not interchangeable with the Moonshot provider key.

If `OPENCLAW_GATEWAY_TOKEN` is missing, the deploy workflow generates or preserves one on the VPS. Add the secret later if you want a stable known value from GitHub.

## Deployment Flow

On every push to `main`, or on manual workflow dispatch:

1. The workflow creates `.env.deploy`.
2. The workflow creates `openclaw.json.deploy`.
3. The bundle is copied over SSH.
4. The VPS creates persistent folders and copies the host Docker CLI into `tools/`.
5. `docker compose pull` downloads the OpenClaw image.
6. `docker compose up -d --force-recreate` starts the Gateway and reruns the startup patch.
7. The workflow verifies `/healthz`.

Existing `config/openclaw.json` is backed up under `backups/` and then replaced by the generated config so deploys keep the runtime deterministic.

Anthropic model metadata is left to OpenClaw's bundled provider catalog. Do not add a manual `models.providers.anthropic.models` block unless the runtime schema explicitly requires it, because an incorrect custom model row can make OpenClaw route Claude through the OpenAI Responses API. The generated config also avoids `agents.defaults.models` for Claude aliases because that field acts as a model allowlist and can hide bundled catalog entries.

The default model is `anthropic/claude-haiku-4-5` with `thinkingDefault: "off"`. Haiku 4.5 is the low-cost Claude default for routine Telegram and VPS operations.

The generated config intentionally sets no automatic fallback to Claude Sonnet. This prevents routine failures or provider auth issues from silently escalating to a more expensive model.

Moonshot and Kimi Coding are separate OpenClaw providers. Use `MOONSHOT_API_KEY` for `moonshot/kimi-k2.6`; use `KIMI_API_KEY` only for `kimi/kimi-for-coding` or Kimi-specific search/coding features.

## Host And Docker Access

The OpenClaw container intentionally has full VPS access:

- `privileged: true`
- user `0:0`
- Docker socket mounted at `/var/run/docker.sock`
- host root mounted read-write at `/host`
- host Docker CLI copied into `tools/` and mounted as `/usr/local/bin/docker`
- Docker Compose plugin copied into `tools/cli-plugins/` and mounted in Docker's standard plugin directory

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

Telegram table markdown and message edit/delete actions are disabled in the generated config to favor plain text replies in Telegram Web. If Telegram mobile works but Telegram Web shows unsupported-message placeholders, keep these settings conservative before enabling richer output again.

The container runs `openclaw-patches/patch-telegram-plain-send.mjs` before starting the Gateway. This compatibility patch changes OpenClaw text delivery from Telegram's experimental rich-message API to the normal Bot API `sendMessage`, which Telegram Web can render. It is idempotent and leaves `.orig` backups inside the container filesystem.

Telegram DM policy is generated as `open` with `allowFrom: ["*"]` to avoid OpenClaw Telegram builds that silently drop normal DM text when `dmPolicy: "allowlist"` is used. Agent routing remains pinned to the numeric Telegram user ID from `OPENCLAW_TELEGRAM_ALLOW_FROM`.

Routine Telegram runs expose only the direct `exec` tool. This keeps Docker and VPS work available without the JavaScript code-mode bridge that can make small models answer from memory instead of calling the real shell.

Deployment also copies `openclaw-workspace/IDENTITY.md` and `openclaw-workspace/USER.md` into the persistent workspace root. Keep `USER.md` extremely short: current Telegram turns may inject only a tiny bootstrap budget, and the first line must fit while telling the model to inspect the live VPS with `exec` before answering operational questions.

Agent context is capped at `40000` tokens, bootstrap context is trimmed to `8000` total characters, startup context is disabled, and compaction sets `agents.defaults.compaction.reserveTokensFloor` to `8000`. OpenClaw may apply a larger internal reserve for some providers; keep enough headroom for shell-tool turns while avoiding long-context costs.

The generated `messages.messagePrefix` reminds the agent that it has root shell and Docker access. This is intentional because routine VPS questions should inspect the live system instead of telling Gabriel to run commands manually.

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
