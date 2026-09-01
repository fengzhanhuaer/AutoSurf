from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PeriodicSiteTemplate:
    key: str
    name: str
    domains: tuple[str, ...]


PERIODIC_SITE_TEMPLATES = (
    PeriodicSiteTemplate("nodeseek", "NodeSeek", ("nodeseek.com", "www.nodeseek.com")),
    PeriodicSiteTemplate("invitesfun", "InvitesFun", ("invites.fun", "www.invites.fun")),
)


NODESEEK_TEMPLATE_CONFIG: dict[str, Any] = {
    "template_key": "nodeseek",
    "url": "https://www.nodeseek.com/board",
    "browser_request": {
        "url": "https://www.nodeseek.com/api/attendance?random=false",
        "method": "POST",
        "json": {"random": False},
    },
    "wait_for_selector": None,
    "click_selector": None,
    "click_role": None,
    "click_name": None,
    "click_exact": False,
    "wait_after_click_ms": 0,
    "success_patterns": [r'"success"\s*:\s*true', "签到成功"],
    "already_patterns": [r"今日签到获得鸡腿\d+个", "今日已签到", "已经签到", "重复签到"],
    "auth_expired_patterns": ["请先登录", "未登录", "登录后"],
}


INVITES_FUN_TEMPLATE_CONFIG: dict[str, Any] = {
    "template_key": "invitesfun",
    "url": "https://www.invites.fun/",
    "wait_for_selector": ".item-forum-checkin",
    "click_selector": ".item-forum-checkin .CheckInButton--yellow",
    "click_role": None,
    "click_name": None,
    "click_exact": False,
    "already_selector": ".item-forum-checkin .CheckInButton--green",
    "success_selector": ".checkInResultModal .successTitleText, .Alert--success",
    "wait_after_click_ms": 1500,
    "success_patterns": ["签到成功", r"您已签到\s*\d+\s*天", r"获得\s*\d+.*奖励"],
    "already_patterns": [r"已签到\s*\d+\s*天"],
    "auth_expired_patterns": ["请先登录", "登录后签到"],
}


PERIODIC_TEMPLATE_CONFIGS = {
    "nodeseek": NODESEEK_TEMPLATE_CONFIG,
    "invitesfun": INVITES_FUN_TEMPLATE_CONFIG,
}


def discover_periodic_template(domain: str) -> PeriodicSiteTemplate | None:
    normalized = domain.lower().strip().lstrip(".").rstrip(".")
    return next((item for item in PERIODIC_SITE_TEMPLATES if normalized in item.domains), None)


def apply_periodic_template(
    config: dict[str, Any], handler_type: str | None = None,
) -> tuple[str, dict[str, Any]]:
    template = PERIODIC_TEMPLATE_CONFIGS.get(str(config.get("template_key") or ""))
    if template is None:
        return str(handler_type or config.get("handler_type") or "browser_signin"), config
    updated = dict(config)
    updated.update(template)
    return "browser_signin", updated
