from telegram.ext import ApplicationBuilder

from assistant.config import load_settings
from assistant.handlers import register_handlers
from assistant.logging_config import configure_logging
from assistant.services.agent import AgentService
from assistant.services.claude import ClaudeService
from assistant.services.rate_limiter import RateLimiter
from assistant.services.tasks import TaskService
from assistant.services.workspace_agent import WorkspaceAgentService
from assistant.services.workspace_git import WorkspaceGitService
from assistant.storage.sqlite import SQLiteStorage
from assistant.tools.workspace import WorkspaceTools


def create_application():
    settings = load_settings()
    configure_logging(settings.log_level)

    storage = SQLiteStorage(settings.database_path)
    storage.initialize()

    claude = ClaudeService(settings)
    workspace_tools = WorkspaceTools(settings)
    task_service = TaskService(settings, storage, claude)
    rate_limiter = RateLimiter(
        max_events=settings.rate_limit_messages,
        window_seconds=settings.rate_limit_window_seconds,
    )
    agent_service = AgentService(
        settings=settings,
        storage=storage,
        claude=claude,
        rate_limiter=rate_limiter,
    )
    workspace_agent_service = WorkspaceAgentService(claude, workspace_tools)
    workspace_git_service = WorkspaceGitService(workspace_tools)

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    register_handlers(
        application=application,
        settings=settings,
        storage=storage,
        agent_service=agent_service,
        task_service=task_service,
        workspace_agent_service=workspace_agent_service,
        workspace_git_service=workspace_git_service,
        workspace_tools=workspace_tools,
    )
    return application
