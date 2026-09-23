"""Generate slot: the language model that writes the answer. Gemini and
NVIDIA are both reached through their OpenAI-compatible endpoints."""

from __future__ import annotations

from typing import Any, AsyncIterator, Literal

from ..core.node import Node, NodeConfig, register, ui_field
from ..llm import provider as llm

Reasoning = Literal["default", "none", "low", "medium", "high"]

REASONING_HELP = (
    "How much hidden 'thinking' the model does before answering. Thinking tokens count "
    "against Max answer tokens and delay the first word. 'none' is fastest and suits cited "
    "answers over retrieved sources. 'default' sends nothing — use it if a model rejects this setting."
)


class GenerateConfig(NodeConfig):
    model: str = ui_field("", title="Model",
                          description="Empty = the provider's default model.",
                          json_schema_extra={"options_from": "/api/providers/{type}/models?kind=chat"})
    temperature: float = ui_field(0.2, ge=0, le=2, title="Temperature",
                                  description="Lower = more focused and repeatable; higher = more varied.")
    top_p: float = ui_field(1.0, ge=0.01, le=1, advanced=True, title="Top-p")
    max_tokens: int = ui_field(4096, ge=16, le=32768, title="Max answer tokens",
                               description="Upper limit on the reply, including any hidden reasoning.")
    # Measured 2026-09-23: "none" cut first-token time ~5x on gemini-2.5-flash
    # (1.2s vs 5.9s) and ~3x on nemotron-3-super, with the same cited answers.
    reasoning_effort: Reasoning = ui_field("none", advanced=True, title="Reasoning effort",
                                           description=REASONING_HELP)


class GeminiGenerateConfig(GenerateConfig):
    reasoning_effort: Reasoning = ui_field(
        "none", advanced=True, title="Reasoning effort",
        description=REASONING_HELP + " Gemini Pro models can't turn thinking off — use 'low' or higher with them.",
    )


class ProviderGenerator(Node):
    Config = GenerateConfig
    provider: str = ""

    def __init__(self, config: Any = None) -> None:
        super().__init__(config)
        self.resolved_model: str | None = None

    @property
    def model_name(self) -> str:
        return self.config.model or self.resolved_model or llm.PROVIDERS[self.provider].default_model

    async def stream(self, messages: list[dict[str, str]], usage: dict[str, Any]) -> AsyncIterator[str]:
        """Yield answer text as it arrives; fills `usage` with token counts at the end."""
        c = self.config
        try:
            if not c.model:
                self.resolved_model = await llm.resolve_model(self.provider, "chat")
            extra = {} if c.reasoning_effort == "default" else {"reasoning_effort": c.reasoning_effort}
            resp = await llm.client(self.provider).chat.completions.create(
                model=self.model_name,
                messages=messages,  # type: ignore[arg-type]
                temperature=c.temperature,
                top_p=c.top_p,
                max_tokens=c.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **extra,
            )
            async for chunk in resp:
                if chunk.usage is not None:
                    usage["tokens_in"], usage["tokens_out"] = llm.usage_tokens(chunk.usage)
                    usage["reasoning_tokens"] = llm.reasoning_tokens(chunk.usage)
                for choice in chunk.choices or []:
                    if choice.finish_reason:
                        usage["finish_reason"] = choice.finish_reason
                    delta = choice.delta.content if choice.delta else None
                    if delta:
                        yield delta
        except Exception as e:
            raise llm.friendly_error(self.provider, e) from e


def _register(provider: str, title: str, description: str, config: type[GenerateConfig]) -> None:
    @register("generate", provider, title=title, description=description,
              availability=lambda: llm.availability(provider))
    class Gen(ProviderGenerator):
        Config = config

    Gen.provider = provider
    Gen.__name__ = f"{provider.title()}Generator"


_register("gemini", "Google Gemini", "Free tier via Google AI Studio.", GeminiGenerateConfig)
_register("nvidia", "NVIDIA", "Free tier via build.nvidia.com — Llama, Mistral, Nemotron and more.",
          GenerateConfig)
