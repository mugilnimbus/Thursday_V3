"""Configuration read from the environment and the `.env` file.

Every service reads the same file; each takes only the fields it needs. Secrets are
`SecretStr` so they never appear in reprs or logs. The UI never writes this file. Model API keys are not
here: they live in the operating system's credential store (`secret_store.py`).
"""

import os
import pathlib

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def env_file() -> pathlib.Path:
    """`THURSDAY_ENV_FILE` if set, otherwise `.env` in the working directory (the repository root)."""
    return pathlib.Path(os.environ.get("THURSDAY_ENV_FILE", ".env"))


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=env_file(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    thursday_data_dir: str = ""
    log_level: str = "INFO"
    thursday_service_token: SecretStr = SecretStr("")

    # The built-in llama.cpp. `llamacpp_dir` is only for your own build: `thursday setup` installs the official one
    # in the data folder. The models folder can also be set per agent in Settings.
    llamacpp_dir: str = ""
    llamacpp_models_dir: str = ""
    # A loaded model nobody has used for this many minutes is unloaded to free the hardware; 0 keeps it loaded.
    # Each agent's own value can be set in Settings.
    llm_idle_unload_minutes: float = Field(default=5, ge=0, le=1440)
    # Days that working data is kept (stored events, saved steps of finished tasks, tool-call logs); 0 keeps
    # it until it is deleted by hand. This is the value until one is chosen in Settings. Chats themselves
    # are never removed by age. (`TRACE_RETENTION_DAYS` is the older name and still works.)
    data_retention_days: int = Field(
        default=30, ge=0, le=3650, validation_alias=AliasChoices("data_retention_days", "trace_retention_days")
    )

    gateway_localhost_port: int = Field(default=8700, ge=1, le=65535)
    gateway_proxy_port: int = Field(default=8701, ge=1, le=65535)
    voice_agent_port: int = Field(default=8710, ge=1, le=65535)
    main_agent_port: int = Field(default=8711, ge=1, le=65535)
    metrics_collector_port: int = Field(default=8720, ge=1, le=65535)
    speech_port: int = Field(default=8730, ge=1, le=65535)


def load_common_settings() -> CommonSettings:
    return CommonSettings(_env_file=env_file())  # pyright: ignore[reportCallIssue]
