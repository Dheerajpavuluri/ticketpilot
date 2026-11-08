import os
from dataclasses import dataclass, field
from datetime import date


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _default_provider() -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "offline"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./ticketpilot.db"))

    # LLM
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER") or _default_provider())
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "60")))
    max_agent_steps: int = field(default_factory=lambda: int(_env("MAX_AGENT_STEPS", "8")))

    # optional cost tracking, USD per million tokens (left at 0 = don't report cost)
    price_input_per_mtok: float = field(default_factory=lambda: float(_env("PRICE_INPUT_PER_MTOK", "0")))
    price_output_per_mtok: float = field(default_factory=lambda: float(_env("PRICE_OUTPUT_PER_MTOK", "0")))

    # policy
    auto_send_confidence: float = field(default_factory=lambda: float(_env("AUTO_SEND_CONFIDENCE", "0.8")))
    refund_review_limit: float = field(default_factory=lambda: float(_env("REFUND_REVIEW_LIMIT", "100")))

    # processing: "inline" runs triage in the API process, "queue" hands it to taskforge workers
    processing_mode: str = field(default_factory=lambda: _env("PROCESSING_MODE", "inline"))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))

    # pin "today" for reproducible evals; empty = real date
    today_override: str = field(default_factory=lambda: _env("TODAY", ""))

    def today(self) -> date:
        return date.fromisoformat(self.today_override) if self.today_override else date.today()


settings = Settings()
