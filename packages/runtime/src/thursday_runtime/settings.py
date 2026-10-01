"""Configuration read from the environment and the `.env` file.

Every service reads the same file; each takes only the fields it needs. Secrets are
`SecretStr` so they never appear in reprs or logs. The UI never writes this file.
"""

import os
import pathlib

from pydantic import Field, SecretStr
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

    gateway_localhost_port: int = Field(default=8700, ge=1, le=65535)
    gateway_proxy_port: int = Field(default=8701, ge=1, le=65535)
    voice_agent_port: int = Field(default=8710, ge=1, le=65535)
    main_agent_port: int = Field(default=8711, ge=1, le=65535)
    metrics_collector_port: int = Field(default=8720, ge=1, le=65535)
    speech_port: int = Field(default=8730, ge=1, le=65535)


def load_common_settings() -> CommonSettings:
    return CommonSettings(_env_file=env_file())  # pyright: ignore[reportCallIssue]
