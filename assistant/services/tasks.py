from assistant.config import Settings
from assistant.services.claude import ClaudeService
from assistant.services.prompts import PLANNING_COMMAND_PROMPT
from assistant.storage.sqlite import SQLiteStorage


class TaskService:
    def __init__(self, settings: Settings, storage: SQLiteStorage, claude: ClaudeService):
        self.settings = settings
        self.storage = storage
        self.claude = claude

    def create_plan(self, telegram_user_id: int, objective: str) -> dict:
        plan = self.claude.create_message(
            messages=[{"role": "user", "content": objective}],
            extra_system_prompt=PLANNING_COMMAND_PROMPT,
            max_tokens=self.settings.plan_max_tokens,
        )
        title = _make_title(objective)
        task_id = self.storage.create_task(
            telegram_user_id=telegram_user_id,
            kind="plan",
            title=title,
            objective=objective,
            plan=plan,
        )
        return {
            "id": task_id,
            "title": title,
            "status": "pending_approval",
            "plan": plan,
        }

    def approve(self, telegram_user_id: int, task_id: int | None = None) -> dict | None:
        task = self.storage.get_task(telegram_user_id, task_id)
        if not task:
            return None
        self.storage.update_task_status(telegram_user_id, task["id"], "approved")
        task["status"] = "approved"
        return task

    def cancel(self, telegram_user_id: int, task_id: int | None = None) -> dict | None:
        task = self.storage.get_task(telegram_user_id, task_id)
        if not task:
            return None
        self.storage.update_task_status(telegram_user_id, task["id"], "cancelled")
        task["status"] = "cancelled"
        return task

    def get_status(self, telegram_user_id: int, task_id: int | None = None) -> dict | None:
        return self.storage.get_task(telegram_user_id, task_id)

    def list_recent(self, telegram_user_id: int) -> list[dict]:
        return self.storage.list_recent_tasks(telegram_user_id)


def _make_title(objective: str) -> str:
    title = " ".join(objective.strip().split())
    if len(title) <= 80:
        return title
    return f"{title[:77]}..."
