"""Settings, read from environment variables or `app/.env`."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Current Sonnet-class model, per the claude-api skill (2026-10). Override with LLM_MODEL.
DEFAULT_LLM_MODEL = "claude-sonnet-5-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Wazuh server API
    wazuh_api_url: str = "https://localhost:55000"
    wazuh_api_user: str = "wazuh-wui"
    wazuh_api_password: SecretStr = SecretStr("")
    wazuh_verify_tls: bool = True
    wazuh_timeout_seconds: float = Field(default=10.0, gt=0)
    wazuh_max_retries: int = Field(default=2, ge=0, le=5)

    # Model
    anthropic_api_key: SecretStr | None = None
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_seconds: float = Field(default=45.0, gt=0)
    llm_max_tokens: int = Field(default=6000, ge=1000, le=16000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
