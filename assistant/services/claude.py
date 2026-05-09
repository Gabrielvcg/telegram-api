from anthropic import Anthropic

from assistant.config import Settings


class ClaudeService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = Anthropic(api_key=settings.anthropic_api_key)

    def create_message(
        self,
        messages: list[dict[str, str]],
        extra_system_prompt: str = "",
        max_tokens: int | None = None,
    ) -> str:
        system_prompt = self.settings.system_prompt
        if extra_system_prompt:
            system_prompt = f"{system_prompt}\n\n{extra_system_prompt}"

        response = self.client.messages.create(
            model=self.settings.model_name,
            max_tokens=max_tokens or self.settings.max_tokens,
            system=system_prompt,
            messages=messages,
        )

        return "\n".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
