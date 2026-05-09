# AGENTS.md - Telegram AI Assistant

Reference date: 2026-05-09

## Project Identity

This repository is a Telegram-based personal AI assistant for Gabriel, inspired by Codex, Claude Code, Cursor Agent, and OpenHands.

The current goal is to keep a small, reliable MVP running through Docker while gradually evolving it toward a tool-using, persistent, infrastructure-aware personal agent.

## Current Stack

- Python
- Docker
- Telegram Bot API
- Anthropic Claude API
- Local development on Windows
- Future deployment target: Ubuntu 22.04 VPS

## Current Repository Layout

- `bot.py`: thin application entry point.
- `assistant/`: application package with configuration, handlers, services, storage, and tools.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: Python 3.11 slim container image.
- `docker-compose.yml`: Docker service definition.
- `.env`: local runtime secrets and configuration. Do not commit real secrets.
- `.env.example`: documented environment template.
- `docker-compose.prod.yml`: production Compose file for VPS deployments with a prebuilt image.
- `.github/workflows/ci.yml`: GitHub Actions verification workflow.
- `.github/workflows/deploy.yml`: GHCR build/push and VPS deploy workflow.
- `docs/operations/vps-deploy.md`: VPS deployment runbook.
- `README.md`: project entry point and setup notes.

## Runtime Model

The bot currently uses Telegram polling through `app.run_polling()`. It does not use webhooks.

The Anthropic integration uses:

- `anthropic>=0.51.0`
- `client.messages.create()`
- `MODEL_NAME=claude-sonnet-4-5`

Anthropic model naming has changed recently. Before changing model IDs, check the official Anthropic model list and migration guide:

- https://platform.claude.com/docs/en/api/models/list
- https://platform.claude.com/docs/en/about-claude/models/migration-guide

## Environment Variables

Expected `.env` variables:

- `TELEGRAM_BOT_TOKEN`
- `ANTHROPIC_API_KEY`
- `MODEL_NAME`
- `ALLOWED_USER_IDS`
- `SYSTEM_PROMPT`

Keep the assistant personality configurable through `SYSTEM_PROMPT`. Do not hardcode Gabriel-specific behavior in Python unless explicitly requested.

## Implemented Features

- Telegram polling.
- Claude message generation.
- User allowlist through `ALLOWED_USER_IDS`.
- Configurable system prompt.
- Telegram typing indicator with `ChatAction.TYPING`.
- SQLite conversational persistence by Telegram user ID.
- Context trimming with the latest persisted messages only.
- `/reset` command to clear user memory.
- `/mode normal` and `/mode plan`.
- `/plan`, `/approve`, `/cancel`, `/status`, and `/tasks` for persistent task planning.
- Workspace tools through `/files`, `/read`, `/search`, `/workspace`, `/write`, `/run`, `/agent`, and `/git`.
- Basic rate limiting.
- Docker volume for runtime data.
- GitHub Actions CI workflow.
- GHCR-based VPS deployment workflow.

## Conversation Modes

The bot currently supports:

- `normal`: direct assistant mode.
- `plan`: adds a planning/reasoning instruction for step-by-step analysis, architecture, tradeoffs, and edge cases.

The project does not yet use Anthropic extended thinking. Treat `/mode plan` as prompt-level behavior until real extended thinking is implemented.

## Memory State

Current memory is SQLite-backed:

- Messages are stored in `messages`.
- User mode and profile summary live in `users`.
- Agent plans live in `agent_tasks`.
- Tool audit records live in `tool_runs`.
- Trimmed to avoid unbounded RAM growth and high context costs.

Docker Compose mounts persistent data with:

```yaml
volumes:
  - ./data:/app/data
```

PostgreSQL can be considered later when the assistant needs multi-user state, richer querying, or integration with a larger backend stack.

## Near-Term Roadmap

Prioritize the following in roughly this order:

1. Better summary-based context-window management.
2. Streaming or progressive Telegram message updates.
3. More robust error taxonomy and user-facing fallback messages.
4. Patch-based write tools with explicit approval.
5. Controlled test/build command execution.
6. Anthropic tool calling with strict tool schemas.

## Medium-Term Roadmap

Candidate capabilities:

- Anthropic extended thinking.
- Tool calling.
- RAG over personal/project documents.
- Access to Gabriel's own APIs.
- VPS control from Telegram.
- Vision and image inputs.
- File and PDF handling.
- Integration with existing Java/JHipster stack.
- Agent workflows.

## Coding Guidelines

- Keep code, identifiers, comments, docs, environment variable names, and commit messages in English.
- User-facing Telegram replies should normally be in Spanish unless the user speaks another language.
- Application logs should be in Spanish, clear, operational, and free of jokes.
- Never log secrets, tokens, API keys, authorization headers, personal data, or complete request/response bodies.
- Prefer small focused functions over large procedural handlers.
- Keep Telegram transport logic separate from Claude/request-building logic as the bot grows.
- Use environment variables for runtime behavior instead of hardcoding deployment-specific values.
- Keep `bot.py` thin. New behavior should normally live under `assistant/`.
- Keep Telegram handlers as orchestration only; business behavior belongs in services.

## Docker Guidelines

- Keep the image simple and reproducible.
- Preserve `python:3.11-slim` unless there is a clear reason to change it.
- Use Docker Compose for local and VPS runtime.
- When persistence is added, store mutable runtime data under `/app/data` and mount it from the host.
- Do not bake `.env` contents into the image.
- Keep `.dockerignore` excluding `.env`, `data/`, caches, and `.git/`.
- Production deploys should use `docker-compose.prod.yml` and a GHCR image, not local builds on the VPS.
- Keep production `.env` only on the VPS.

## Security Guidelines

- Preserve the user allowlist. Do not accidentally expose the bot to all Telegram users.
- Fail closed when `ALLOWED_USER_IDS` is missing or malformed unless Gabriel explicitly asks for an open mode.
- Treat Telegram input as untrusted.
- Keep workspace tools scoped to `WORKSPACE_ROOT`.
- Keep workspace writes and commands scoped to `WORKSPACE_ROOT`.
- Telegram responses for code changes should summarize touched files and high-level flow, not paste full patches.
- Workspace projects should live under `projects/<project-name>`.
- Use `scratch/` only for temporary experiments and disposable checks.
- For broad `/agent` requests, the expected behavior is an end-to-end workspace flow: inspect, create/edit, verify, organize Git, and summarize.
- Use one branch per meaningful feature or change, named `agent/<short-task-name>`, for example `agent/jwt-auth` or `agent/demo-fastapi-health`.
- If a workspace project is on `main` and the task changes files, create or switch to a feature branch before editing unless Gabriel explicitly asks otherwise.
- For coherent workspace implementations that pass verification, local commits are acceptable and expected unless Gabriel asks not to commit.
- Git operations must stay inside workspace project paths. Do not push automatically unless Gabriel explicitly asks for push/publish.
- Do not deploy, publish packages, configure external accounts, or use SSH keys from workspace automation unless Gabriel explicitly asks for that specific external action.
- Avoid adding shell/VPS control tools until authorization, logging, confirmation flows, and command allowlists are designed.
- For future tool calling, require explicit boundaries around filesystem, shell, network, and infrastructure actions.

## Testing And Verification

For small changes:

- Run the smallest meaningful local check first.
- Prefer syntax/import checks for narrow Python edits.
- Use Docker Compose validation or container runs when Docker behavior changes.

For behavior changes:

- Add focused tests when a test framework exists or when introducing one is proportionate.
- Verify allowlist, `/reset`, `/mode`, error paths, and history behavior.

## Documentation

- Keep `README.md` focused on setup, environment variables, Docker usage, and operational commands.
- Add longer notes under `docs/` if the project grows.
- Update README when setup, runtime variables, Docker behavior, or commands change.

## Change Discipline

- Keep edits scoped to the current task.
- Preserve unrelated user changes.
- Do not commit `.env`.
- Do not replace the working Anthropic model ID without checking current official docs.
- Document user-visible, operational, security, or developer-workflow changes in README or docs when relevant.
