from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOSURF_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    secret_key: str = Field(min_length=32)
    api_token: str = Field(min_length=16)
    host: str = "0.0.0.0"
    port: int = 8080
    worker_poll_seconds: float = 1.0
    scheduler_poll_seconds: float = 30.0
    execution_lease_seconds: int = 120

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'autosurf.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

