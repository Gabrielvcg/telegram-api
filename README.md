# Telegram AI Assistant

Bot personal por Telegram con Claude, memoria persistente SQLite y una base de agente para planificar trabajo de software de forma controlada.

## Requisitos

- Docker
- Docker Compose
- Token de Telegram
- API key de Anthropic

## Configuración

Crea `.env` a partir de `.env.example` y ajusta los valores reales:

```bash
cp .env.example .env
```

Variables principales:

- `TELEGRAM_BOT_TOKEN`: token del bot creado con BotFather.
- `ANTHROPIC_API_KEY`: API key de Anthropic.
- `MODEL_NAME`: modelo de Claude. Actualmente probado con `claude-sonnet-4-5`.
- `ALLOWED_USER_IDS`: IDs de Telegram autorizados, separados por comas.
- `SYSTEM_PROMPT`: personalidad base del asistente.
- `DATABASE_PATH`: ruta SQLite dentro del contenedor.
- `HISTORY_LIMIT`: número de mensajes recientes enviados al modelo.
- `MAX_TOKENS`: presupuesto de respuesta para conversación normal.
- `PLAN_MAX_TOKENS`: presupuesto de respuesta para `/mode plan` y `/plan`.
- `RATE_LIMIT_MESSAGES` y `RATE_LIMIT_WINDOW_SECONDS`: límite básico anti-spam.
- `WORKSPACE_ROOT`: raíz permitida para herramientas de lectura.
- `WORKSPACE_READ_ENABLED`: activa `/files`, `/read` y `/search`.
- `WORKSPACE_WRITE_ENABLED`: activa escritura controlada dentro del workspace.
- `WORKSPACE_COMMAND_ENABLED`: activa ejecución de comandos dentro del workspace.
- `WORKSPACE_COMMAND_TIMEOUT_SECONDS`: timeout de comandos del workspace.
- `WORKSPACE_MAX_OUTPUT_CHARS`: salida máxima devuelta por comando.

## Arrancar

```bash
docker compose up -d --build
```

SQLite se guarda en `./data`, montado como volumen en `/app/data`.

Las herramientas de workspace usan `./workspace`, montado como `/app/workspace`. No pongas secretos en esa carpeta.

## Ver logs

```bash
docker logs -f telegram-bot
```

## Parar

```bash
docker compose down
```

## CI/CD Y VPS

El proyecto incluye GitHub Actions para:

- validar Python y construir la imagen Docker en cada push o pull request;
- publicar la imagen en GHCR al hacer push a `main`;
- desplegar en un VPS por SSH usando `docker-compose.prod.yml`.

Guia completa:

```text
docs/operations/vps-deploy.md
```

En produccion, el archivo `.env` se crea manualmente en el VPS y nunca se sube a GitHub.

## Comandos Del Bot

- `/start`: muestra estado inicial.
- `/help`: lista comandos.
- `/mode normal`: conversación directa.
- `/mode plan`: conversación con prompt de planificación.
- `/plan <objetivo>`: crea una tarea planificada y revisable.
- `/approve [id]`: aprueba una tarea registrada.
- `/cancel [id]`: cancela una tarea.
- `/status [id]`: muestra el estado de una tarea.
- `/tasks`: lista tareas recientes.
- `/reset`: borra memoria conversacional del usuario.
- `/workspace`: muestra estado y crea `AGENTS.md`, `projects/` y `scratch/` si la escritura está activa.
- `/agent <objetivo>`: pide a Claude que ejecute trabajo dentro del workspace y devuelve resumen de alto nivel.
- `/run <comando>`: ejecuta un comando dentro del workspace.
- `/write <ruta> <contenido>`: escribe un archivo dentro del workspace.
- `/files [ruta]`: lista archivos dentro del workspace permitido.
- `/read <ruta>`: lee un archivo del workspace permitido.
- `/search <texto> [ruta]`: busca texto dentro del workspace permitido.

## Seguridad

El bot falla cerrado si `ALLOWED_USER_IDS` está vacío o mal formado. Las herramientas de workspace solo operan dentro de `WORKSPACE_ROOT`. El proyecto raíz no se monta como workspace para evitar exponer `.env`.

Los comandos de workspace se ejecutan con entorno saneado para no exponer tokens del bot. No hay shell de host ni acceso intencionado fuera de `/app/workspace`.
