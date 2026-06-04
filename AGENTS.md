# AGENTS.md - OpenClaw VPS Assistant Wrapper

Reference date: 2026-06-04

## Project Identity

This repository deploys OpenClaw to Gabriel's VPS.

It is not a custom Telegram bot anymore. Telegram routing, audio handling, memory, tools, agent execution, and model/provider routing are delegated to OpenClaw.

## Stack

- Docker Compose
- GitHub Actions
- OpenClaw Gateway
- Telegram channel
- Anthropic Claude as the initial provider
- Optional OpenAI/Codex runtime later

## Repository Layout

- `docker-compose.yml`: local OpenClaw runtime.
- `docker-compose.prod.yml`: production OpenClaw runtime copied to the VPS.
- `.github/workflows/deploy.yml`: SSH deploy workflow.
- `.github/workflows/ci.yml`: static verification.
- `.env.example`: local template.
- `README.md`: setup and usage entry point.
- `docs/operations/vps-deploy.md`: operations runbook.

## Change Discipline

- Do not reintroduce the old Python bot runtime.
- Do not add Python assistant services, Anthropic API wrappers, Telegram handlers, or custom workspace-agent code.
- Keep this repo focused on deploy, config, docs, and operations.
- Keep secrets out of Git.
- Keep OpenClaw config and Compose reproducible.
- Preserve existing GitHub environment compatibility where practical.

## Deployment Defaults

- Recommended deploy path: `/opt/openclaw-assistant`.
- Gateway port: `127.0.0.1:18789`.
- Persistent folders: `config/`, `workspace/`, `auth/`, `backups/`.
- Telegram access must be allowlisted.
- The Gateway port must not be exposed publicly without authentication and a deliberate network plan.

## Access Policy

Gabriel wants a useful agent, not a command toy. OpenClaw should be allowed to work on real projects in the workspace.

Do not mount the entire host filesystem or Docker socket by default. Add host-level access in a later explicit change with:

- scope,
- rollback,
- backups,
- command policy,
- logging,
- and a concrete test task.

## Documentation

Update `README.md` and `docs/operations/vps-deploy.md` when changing:

- deployment behavior,
- required GitHub variables/secrets,
- Compose volumes/ports,
- OpenClaw config generation,
- Telegram setup,
- model/provider defaults,
- or host access policy.
