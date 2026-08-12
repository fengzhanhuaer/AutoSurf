from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_WAIT = "retry_wait"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class RunOutcome(StrEnum):
    SUCCESS = "success"
    ALREADY_DONE = "already_done"
    AUTH_EXPIRED = "auth_expired"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class RunResult:
    outcome: RunOutcome
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class RunContext:
    execution_id: str
    config: dict[str, Any]
    cookies: dict[str, str]


class AutomationHandler(Protocol):
    type: str

    async def run(self, context: RunContext) -> RunResult: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
