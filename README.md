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
- `WORKSPACE_AGENT_MAX_ATTEMPTS`: intentos máximos de `/agent`, incluyendo reparación automática tras fallos.
- `PROJECT_<NAME>_PATH`, `PROJECT_<NAME>_REPO`, `PROJECT_<NAME>_TOKEN`: perfiles GitHub controlados por proyecto.
- `PROJECT_<NAME>_BASE_BRANCH`: rama base del perfil GitHub, por defecto `main`.

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
- `/agent <objetivo>`: pide a Claude que ejecute trabajo dentro del workspace. Si un intento falla, puede hacer una pasada automática de reparación antes de devolver resumen de alto nivel.
- `/git <proyecto> init`: inicializa Git en un proyecto del workspace.
- `/git <proyecto> status`: muestra estado corto.
- `/git <proyecto> diff`: muestra solo resumen estadístico de cambios.
- `/git <proyecto> log`: muestra últimos commits.
- `/git <proyecto> branch <nombre>`: crea una rama.
- `/git <proyecto> commit <mensaje>`: commitea cambios del proyecto.
- `/github list`: lista perfiles GitHub configurados.
- `/github <perfil> clone`: clona el repo configurado en su ruta del workspace.
- `/github <perfil> status`: muestra estado Git del perfil.
- `/github <perfil> push-pr <título>`: pushea la rama actual y crea una PR sin hacer merge.
- `/run <comando>`: ejecuta un comando dentro del workspace.
- `/write <ruta> <contenido>`: escribe un archivo dentro del workspace.
- `/files [ruta]`: lista archivos dentro del workspace permitido.
- `/read <ruta>`: lee un archivo del workspace permitido.
- `/search <texto> [ruta]`: busca texto dentro del workspace permitido.

## Seguridad

El bot falla cerrado si `ALLOWED_USER_IDS` está vacío o mal formado. Las herramientas de workspace solo operan dentro de `WORKSPACE_ROOT`. El proyecto raíz no se monta como workspace para evitar exponer `.env`.

Los comandos de workspace se ejecutan con entorno saneado para no exponer tokens del bot. No hay shell de host ni acceso intencionado fuera de `/app/workspace`.

Los tokens GitHub se usan solo desde herramientas controladas del bot. No se pasan a Claude, no se guardan en `.git/config` y no deben escribirse en archivos del workspace.

### Comando /github

El comando `/github` permite interactuar con repositorios de GitHub directamente desde Telegram.

**Sintaxis:**
```
/github <acción> [argumentos]
```

**Acciones disponibles:**

- **`/github status <repo>`** - Muestra el estado actual del repositorio (rama, commits recientes, issues abiertas)
  - Ejemplo: `/github status owner/repo-name`

- **`/github issues <repo>`** - Lista las issues abiertas del repositorio
  - Ejemplo: `/github issues owner/repo-name`

- **`/github create-issue <repo> <título>`** - Crea una nueva issue
  - Ejemplo: `/github create-issue owner/repo-name "Mejorar documentación"`

- **`/github pr <repo>`** - Lista los pull requests abiertos
  - Ejemplo: `/github pr owner/repo-name`

- **`/github branches <repo>`** - Lista las ramas del repositorio
  - Ejemplo: `/github branches owner/repo-name`

- **`/github commits <repo> [rama]`** - Muestra commits recientes (por defecto main)
  - Ejemplo: `/github commits owner/repo-name`
  - Ejemplo: `/github commits owner/repo-name develop`

**Notas:**
- Requiere configuración previa de token de GitHub
- El formato de repo debe ser `owner/repository-name`
- Algunos comandos pueden requerir permisos específicos en el repositorio

