from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load .env file if present (no extra dependency needed)
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value and key not in os.environ:  # don't override existing env vars
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """Application-wide settings resolved from environment variables."""

    # GitHub
    github_api_base: str = field(
        default_factory=lambda: os.getenv("GITHUB_API_BASE", "https://api.github.com")
    )
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN"))
    github_timeout: int = int(os.getenv("GITHUB_TIMEOUT", "30"))

    # LLM
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_api_base: str = field(
        default_factory=lambda: os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini")
    )
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "60"))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))

    # Context budget (characters, not tokens — conservative 1:4 ratio)
    max_context_chars: int = int(os.getenv("MAX_CONTEXT_CHARS", "100000"))
    prompt_buffer_chars: int = int(os.getenv("PROMPT_BUFFER_CHARS", "4000"))
    per_file_max_chars: int = int(os.getenv("PER_FILE_MAX_CHARS", "15000"))

    # Cache
    cache_max_size: int = int(os.getenv("CACHE_MAX_SIZE", "128"))

    @property
    def content_budget(self) -> int:
        return self.max_context_chars - self.prompt_buffer_chars


def get_settings() -> Settings:
    return Settings()
