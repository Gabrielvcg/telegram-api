import logging
from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from assistant.config import Settings
from assistant.services.agent import AgentService
from assistant.services.tasks import TaskService
from assistant.services.workspace_agent import WorkspaceAgentService
from assistant.services.workspace_git import WorkspaceGitService
from assistant.services.workspace_github import WorkspaceGitHubService
from assistant.storage.sqlite import SQLiteStorage
from assistant.telegram_utils import split_telegram_message
from assistant.tools.workspace import CommandResult, WorkspaceTools

logger = logging.getLogger(__name__)

HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def register_handlers(
    application: Application,
    settings: Settings,
    storage: SQLiteStorage,
    agent_service: AgentService,
    task_service: TaskService,
    workspace_agent_service: WorkspaceAgentService,
    workspace_git_service: WorkspaceGitService,
    workspace_github_service: WorkspaceGitHubService,
    workspace_tools: WorkspaceTools,
) -> None:
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        await update.message.reply_text(
            "Listo. Soy tu asistente personal.\n\n"
            "Comandos: /help, /mode, /plan, /approve, /cancel, /status, "
            "/tasks, /reset, /workspace, /agent, /git, /github, /run, /write, /files, /read, /search"
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        await update.message.reply_text(
            "Comandos disponibles:\n"
            "/mode normal|plan - cambia el modo de conversación\n"
            "/plan <objetivo> - crea un plan revisable\n"
            "/approve [id] - aprueba una tarea planificada\n"
            "/cancel [id] - cancela una tarea\n"
            "/status [id] - muestra estado de una tarea\n"
            "/tasks - lista tareas recientes\n"
            "/reset - borra memoria conversacional\n"
            "/workspace - estado y bootstrap del workspace\n"
            "/agent <objetivo> - ejecuta trabajo dentro del workspace\n"
            "/git <proyecto> <acción> - gestiona Git dentro de un proyecto del workspace\n"
            "/github <perfil> <acción> - clone/status/push-pr controlado por perfil GitHub\n"
            "/run <comando> - ejecuta un comando dentro del workspace\n"
            "/write <ruta> <contenido> - escribe un archivo dentro del workspace\n"
            "/files [ruta] - lista archivos del workspace\n"
            "/read <ruta> - lee un archivo del workspace\n"
            "/search <texto> [ruta] - busca texto en el workspace"
        )

    async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        user_id = update.effective_user.id
        storage.clear_messages(user_id)
        logger.info("Memoria conversacional reiniciada para el usuario %s", user_id)
        await update.message.reply_text("Memoria reiniciada.")

    async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        user_id = update.effective_user.id
        if not context.args:
            await update.message.reply_text(f"Modo actual: {storage.get_mode(user_id)}")
            return

        mode = context.args[0].lower()
        if mode not in {"normal", "plan"}:
            await update.message.reply_text("Usa: /mode normal o /mode plan")
            return

        storage.set_mode(user_id, mode)
        logger.info("Modo cambiado a %s para el usuario %s", mode, user_id)
        await update.message.reply_text(f"Modo cambiado a: {mode}")

    async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        objective = " ".join(context.args).strip()
        if not objective:
            await update.message.reply_text("Usa: /plan <objetivo>")
            return

        await _typing(update, context)
        task = task_service.create_plan(update.effective_user.id, objective)
        await _reply_long(
            update,
            settings,
            f"Tarea #{task['id']} creada. Estado: pendiente de aprobación.\n\n{task['plan']}",
        )

    async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        task = task_service.approve(update.effective_user.id, _optional_task_id(context))
        if not task:
            await update.message.reply_text("No he encontrado esa tarea.")
            return
        await update.message.reply_text(
            f"Tarea #{task['id']} aprobada.\n"
            "Aún no ejecuto cambios automáticamente; esta aprobación queda registrada para el siguiente paso."
        )

    async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        task = task_service.cancel(update.effective_user.id, _optional_task_id(context))
        if not task:
            await update.message.reply_text("No he encontrado esa tarea.")
            return
        await update.message.reply_text(f"Tarea #{task['id']} cancelada.")

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        task = task_service.get_status(update.effective_user.id, _optional_task_id(context))
        if not task:
            await update.message.reply_text("No he encontrado tareas todavía.")
            return
        await update.message.reply_text(_format_task(task))

    async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        tasks = task_service.list_recent(update.effective_user.id)
        if not tasks:
            await update.message.reply_text("No hay tareas registradas.")
            return
        await update.message.reply_text("\n\n".join(_format_task(task) for task in tasks))

    async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        relative_path = " ".join(context.args).strip() or "."
        await _tool_reply(update, settings, storage, workspace_tools.list_files, "list_files", relative_path)

    async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        relative_path = " ".join(context.args).strip()
        if not relative_path:
            await update.message.reply_text("Usa: /read <ruta>")
            return
        await _tool_reply(update, settings, storage, workspace_tools.read_file, "read_file", relative_path)

    async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        if not context.args:
            await update.message.reply_text("Usa: /search <texto> [ruta]")
            return
        query = context.args[0]
        relative_path = " ".join(context.args[1:]).strip() or "."
        await _tool_reply(
            update,
            settings,
            storage,
            lambda path: workspace_tools.search_text(query, path),
            "search_text",
            relative_path,
            {"query": query, "path": relative_path},
        )

    async def workspace_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        try:
            status = workspace_tools.status()
            bootstrap = workspace_tools.bootstrap() if settings.workspace_write_enabled else ""
            await _reply_long(update, settings, "\n\n".join(part for part in [status, bootstrap] if part))
        except Exception:
            logger.exception("Error preparando workspace")
            await update.message.reply_text("No he podido preparar el workspace.")

    async def write_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        payload = _command_payload(update, "write")
        if not payload or " " not in payload:
            await update.message.reply_text("Usa: /write <ruta> <contenido>")
            return
        relative_path, content = payload.split(" ", 1)
        try:
            output = workspace_tools.write_file(relative_path, content)
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="write_file",
                status="success",
                input_data={"path": relative_path},
                output=output,
            )
            await update.message.reply_text(output)
        except Exception:
            logger.exception("Error escribiendo archivo en workspace")
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="write_file",
                status="error",
                input_data={"path": relative_path},
                output="",
            )
            await update.message.reply_text("No he podido escribir ese archivo.")

    async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        command = _command_payload(update, "run")
        if not command:
            await update.message.reply_text("Usa: /run <comando>")
            return
        try:
            await _typing(update, context)
            result = workspace_tools.run_command(command)
            output = _format_command_result(result)
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="run_command",
                status="success" if result.exit_code == 0 else "error",
                input_data={"command": command},
                output=output,
            )
            await _reply_long(update, settings, output)
        except Exception:
            logger.exception("Error ejecutando comando en workspace")
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="run_command",
                status="error",
                input_data={"command": command},
                output="",
            )
            await update.message.reply_text("No he podido ejecutar ese comando dentro del workspace.")

    async def agent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        objective = _command_payload(update, "agent")
        if not objective:
            await update.message.reply_text("Usa: /agent <objetivo>")
            return
        try:
            await _typing(update, context)
            output = workspace_agent_service.execute_objective(objective)
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="workspace_agent",
                status="success",
                input_data={"objective": objective},
                output=output,
            )
            await _reply_long(update, settings, output)
        except Exception:
            logger.exception("Error ejecutando agente de workspace")
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="workspace_agent",
                status="error",
                input_data={"objective": objective},
                output="",
            )
            await update.message.reply_text("No he podido completar ese trabajo dentro del workspace.")

    async def git_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usa: /git <proyecto> <init|status|log|diff|branch|commit> [args]"
            )
            return
        project_path = context.args[0]
        action = context.args[1]
        args = context.args[2:]
        try:
            await _typing(update, context)
            output = workspace_git_service.handle(project_path, action, args)
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="workspace_git",
                status="success",
                input_data={"project_path": project_path, "action": action, "args": args},
                output=output,
            )
            await _reply_long(update, settings, output)
        except Exception:
            logger.exception("Error ejecutando Git en workspace")
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="workspace_git",
                status="error",
                input_data={"project_path": project_path, "action": action, "args": args},
                output="",
            )
            await update.message.reply_text("No he podido ejecutar esa operación Git dentro del workspace.")

    async def github_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return
        profile_name = context.args[0] if context.args else None
        action = context.args[1] if len(context.args) >= 2 else ("list" if profile_name == "list" else None)
        args = context.args[2:] if len(context.args) >= 2 else []
        if profile_name == "list":
            profile_name = None
        try:
            await _typing(update, context)
            output = workspace_github_service.handle(profile_name, action, args)
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="workspace_github",
                status="success",
                input_data={"profile": profile_name, "action": action, "args": args},
                output=output,
            )
            await _reply_long(update, settings, output)
        except Exception:
            logger.exception("Error ejecutando GitHub en workspace")
            storage.record_tool_run(
                telegram_user_id=update.effective_user.id,
                tool_name="workspace_github",
                status="error",
                input_data={"profile": profile_name, "action": action, "args": args},
                output="",
            )
            await update.message.reply_text("No he podido ejecutar esa operación GitHub dentro del workspace.")

    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await _ensure_authorized(update, settings):
            return

        try:
            await _typing(update, context)
            answer = agent_service.handle_user_message(
                telegram_user_id=update.effective_user.id,
                text=update.message.text,
            )
            await _reply_long(update, settings, answer)
        except Exception:
            logger.exception("Error procesando mensaje del usuario %s", update.effective_user.id)
            await update.message.reply_text("Ha ocurrido un error procesando tu mensaje.")

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("workspace", workspace_command))
    application.add_handler(CommandHandler("agent", agent_command))
    application.add_handler(CommandHandler("git", git_command))
    application.add_handler(CommandHandler("github", github_command))
    application.add_handler(CommandHandler("run", run_command))
    application.add_handler(CommandHandler("write", write_command))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("read", read_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))


async def _ensure_authorized(update: Update, settings: Settings) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id in settings.allowed_user_ids:
        return True

    logger.warning("Acceso no autorizado del usuario %s", user_id)
    if update.message:
        await update.message.reply_text("No autorizado.")
    return False


async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )


async def _reply_long(update: Update, settings: Settings, text: str) -> None:
    for chunk in split_telegram_message(text, settings.max_telegram_message_length):
        await update.message.reply_text(chunk)


async def _tool_reply(
    update: Update,
    settings: Settings,
    storage: SQLiteStorage,
    tool_func: Callable[[str], str],
    tool_name: str,
    relative_path: str,
    input_data: dict | None = None,
) -> None:
    try:
        output = tool_func(relative_path)
        storage.record_tool_run(
            telegram_user_id=update.effective_user.id,
            tool_name=tool_name,
            status="success",
            input_data=input_data or {"path": relative_path},
            output=output,
        )
        await _reply_long(update, settings, output)
    except Exception:
        logger.exception("Error ejecutando herramienta %s", tool_name)
        storage.record_tool_run(
            telegram_user_id=update.effective_user.id,
            tool_name=tool_name,
            status="error",
            input_data=input_data or {"path": relative_path},
            output="",
        )
        await update.message.reply_text("No he podido ejecutar esa herramienta.")


def _optional_task_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if not context.args:
        return None
    try:
        return int(context.args[0])
    except ValueError:
        return None


def _format_task(task: dict) -> str:
    return (
        f"Tarea #{task['id']} - {task['status']}\n"
        f"{task['title']}\n"
        f"Tipo: {task['kind']}"
    )


def _command_payload(update: Update, command_name: str) -> str:
    text = update.message.text or ""
    prefix = f"/{command_name}"
    if not text.startswith(prefix):
        return ""
    return text[len(prefix) :].strip()


def _format_command_result(result: CommandResult) -> str:
    changed_files = "\n".join(f"- {path}" for path in result.changed_files) or "- Sin cambios detectados"
    output = result.output or "Sin salida relevante."
    return (
        f"Comando ejecutado en workspace.\n\n"
        f"Comando:\n{result.command}\n\n"
        f"Resultado: exit code {result.exit_code}\n\n"
        f"Ficheros tocados:\n{changed_files}\n\n"
        f"Salida relevante:\n{output}"
    )
