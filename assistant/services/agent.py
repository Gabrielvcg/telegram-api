import logging

from assistant.config import Settings
from assistant.services.claude import ClaudeService
from assistant.services.prompts import PLAN_MODE_PROMPT
from assistant.services.rate_limiter import RateLimiter
from assistant.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(
        self,
        settings: Settings,
        storage: SQLiteStorage,
        claude: ClaudeService,
        rate_limiter: RateLimiter,
    ):
        self.settings = settings
        self.storage = storage
        self.claude = claude
        self.rate_limiter = rate_limiter

    def handle_user_message(self, telegram_user_id: int, text: str) -> str:
        if not self.rate_limiter.allow(telegram_user_id):
            logger.warning("Límite de frecuencia alcanzado para el usuario %s", telegram_user_id)
            return "Has enviado demasiados mensajes seguidos. Espera un momento y vuelve a intentarlo."

        mode = self.storage.get_mode(telegram_user_id)
        extra_prompt = PLAN_MODE_PROMPT if mode == "plan" else ""

        self.storage.add_message(telegram_user_id, "user", text)
        history = self.storage.get_recent_messages(
            telegram_user_id=telegram_user_id,
            limit=self.settings.history_limit,
        )

        answer = self.claude.create_message(
            messages=history,
            extra_system_prompt=extra_prompt,
            max_tokens=self._max_tokens_for_mode(mode),
        )
        self.storage.add_message(telegram_user_id, "assistant", answer)
        return answer

    def _max_tokens_for_mode(self, mode: str) -> int:
        if mode == "plan":
            return self.settings.plan_max_tokens
        return self.settings.max_tokens
