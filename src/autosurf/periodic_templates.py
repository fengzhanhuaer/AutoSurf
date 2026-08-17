from __future__ import annotations

from typing import Any


NODESEEK_TEMPLATE_CONFIG: dict[str, Any] = {
    "template_key": "nodeseek",
    "site_url": "https://www.nodeseek.com/board",
    "url": "https://www.nodeseek.com/api/attendance?random=false",
    "method": "POST",
    "origin": "https://www.nodeseek.com",
    "referer": "https://www.nodeseek.com/board",
    "json": {"random": False},
    "wait_for_selector": None,
    "click_selector": None,
    "click_role": None,
    "click_name": None,
    "click_exact": False,
    "wait_after_click_ms": 0,
    "success_patterns": [r'"success"\s*:\s*true', "签到成功"],
    "already_patterns": ["今日已签到", "已经签到", "重复签到"],
    "auth_expired_patterns": ["请先登录", "未登录", "登录后"],
}


def apply_periodic_template(
    config: dict[str, Any], handler_type: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if config.get("template_key") != "nodeseek":
        return str(handler_type or config.get("handler_type") or "browser_signin"), config
    updated = dict(config)
    updated.update(NODESEEK_TEMPLATE_CONFIG)
    return "http_signin", updated
