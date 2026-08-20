from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from autosurf.domain.models import utc_now


SIGNIN_START_TIME = "09:00"
SIGNIN_INTERVAL_SECONDS = 24 * 60 * 60
SIGNIN_TIMEZONE = timezone(timedelta(hours=8))


def next_signin_run_at(now: datetime | None = None) -> datetime:
    current_utc = (now or utc_now()).replace(tzinfo=timezone.utc)
    current_local = current_utc.astimezone(SIGNIN_TIMEZONE)
    target_local = datetime.combine(
        current_local.date(), time(hour=9), tzinfo=SIGNIN_TIMEZONE,
    )
    if target_local <= current_local:
        target_local += timedelta(days=1)
    return target_local.astimezone(timezone.utc).replace(tzinfo=None)
