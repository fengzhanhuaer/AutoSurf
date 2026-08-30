from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DATA_DIR = Path(r"C:\Tools\AutoSurf\data") if os.name == "nt" else Path("data")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOSURF_", env_file=".env", extra="ignore")

    data_dir: Path = DEFAULT_DATA_DIR
    secret_key: str = Field(min_length=32)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=1024)
    host: str = "127.0.0.1"
    port: int = 18980
    worker_poll_seconds: float = 1.0
    scheduler_poll_seconds: float = 30.0
    execution_lease_seconds: int = 120

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'autosurf.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
