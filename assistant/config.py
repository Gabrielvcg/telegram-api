import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_SYSTEM_PROMPT = (
    "Eres el asistente personal de Gabriel. Responde siempre en español salvo "
    "que te hablen en otro idioma. Sé técnico, útil y conciso."
)


@dataclass(frozen=True)
class GitHubProjectSettings:
    name: str
    path: str
    repo: str
    token: str = field(repr=False)
    base_branch: str = "main"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    anthropic_api_key: str
    model_name: str
    system_prompt: str
    allowed_user_ids: set[int]
    database_path: Path
    history_limit: int
    max_tokens: int
    plan_max_tokens: int
    max_telegram_message_length: int
    rate_limit_messages: int
    rate_limit_window_seconds: int
    workspace_root: Path
    workspace_read_enabled: bool
    workspace_write_enabled: bool
    workspace_command_enabled: bool
    workspace_command_timeout_seconds: int
    workspace_max_output_chars: int
    workspace_agent_max_attempts: int
    workspace_git_author_name: str
    workspace_git_author_email: str
    github_projects: dict[str, GitHubProjectSettings]
    log_level: str


def load_settings() -> Settings:
    load_dotenv()

    telegram_bot_token = _required_env("TELEGRAM_BOT_TOKEN")
    anthropic_api_key = _required_env("ANTHROPIC_API_KEY")
    allowed_user_ids = _parse_allowed_user_ids(os.getenv("ALLOWED_USER_IDS", ""))

    return Settings(
        telegram_bot_token=telegram_bot_token,
        anthropic_api_key=anthropic_api_key,
        model_name=os.getenv("MODEL_NAME", "claude-sonnet-4-5"),
        system_prompt=os.getenv("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        allowed_user_ids=allowed_user_ids,
        database_path=Path(os.getenv("DATABASE_PATH", "/app/data/assistant.db")),
        history_limit=_int_env("HISTORY_LIMIT", 12),
        max_tokens=_int_env("MAX_TOKENS", 1200),
        plan_max_tokens=_int_env("PLAN_MAX_TOKENS", 2200),
        max_telegram_message_length=_int_env("MAX_TELEGRAM_MESSAGE_LENGTH", 3900),
        rate_limit_messages=_int_env("RATE_LIMIT_MESSAGES", 20),
        rate_limit_window_seconds=_int_env("RATE_LIMIT_WINDOW_SECONDS", 60),
        workspace_root=Path(os.getenv("WORKSPACE_ROOT", "/app/workspace")),
        workspace_read_enabled=_bool_env("WORKSPACE_READ_ENABLED", True),
        workspace_write_enabled=_bool_env("WORKSPACE_WRITE_ENABLED", False),
        workspace_command_enabled=_bool_env("WORKSPACE_COMMAND_ENABLED", False),
        workspace_command_timeout_seconds=_int_env("WORKSPACE_COMMAND_TIMEOUT_SECONDS", 120),
        workspace_max_output_chars=_int_env("WORKSPACE_MAX_OUTPUT_CHARS", 6000),
        workspace_agent_max_attempts=_bounded_int_env("WORKSPACE_AGENT_MAX_ATTEMPTS", 2, 1, 5),
        workspace_git_author_name=os.getenv("WORKSPACE_GIT_AUTHOR_NAME", "Telegram AI Assistant"),
        workspace_git_author_email=os.getenv("WORKSPACE_GIT_AUTHOR_EMAIL", "telegram-ai-assistant@users.noreply.github.com"),
        github_projects=_parse_github_projects(),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_allowed_user_ids(raw_value: str) -> set[int]:
    allowed_user_ids = set()
    for value in raw_value.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            allowed_user_ids.add(int(value))
        except ValueError as exc:
            raise RuntimeError(f"Invalid ALLOWED_USER_IDS value: {value}") from exc

    if not allowed_user_ids:
        raise RuntimeError("ALLOWED_USER_IDS must contain at least one Telegram user ID")

    return allowed_user_ids


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    value = _int_env(name, default)
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _parse_github_projects() -> dict[str, GitHubProjectSettings]:
    projects = {}
    for env_name, token in os.environ.items():
        if not env_name.startswith("PROJECT_") or not env_name.endswith("_TOKEN"):
            continue
        if _is_placeholder_secret(token):
            continue

        raw_name = env_name[len("PROJECT_") : -len("_TOKEN")]
        project_name = raw_name.lower()
        prefix = f"PROJECT_{raw_name}"
        path = os.getenv(f"{prefix}_PATH", "").strip()
        repo = os.getenv(f"{prefix}_REPO", "").strip()

        if project_name == "telegram":
            path = path or "projects/telegram-ai-assistant"
            repo = repo or "Gabrielvcg/telegram-api"

        if not path or not repo:
            raise RuntimeError(
                f"{prefix}_PATH and {prefix}_REPO are required when {prefix}_TOKEN is configured"
            )

        projects[project_name] = GitHubProjectSettings(
            name=project_name,
            path=path,
            repo=repo,
            token=token,
            base_branch=os.getenv(f"{prefix}_BASE_BRANCH", "main").strip() or "main",
        )
    return projects


def _is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    return value.strip().lower() in {"replace-me", "changeme", "change-me", "todo"}


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
