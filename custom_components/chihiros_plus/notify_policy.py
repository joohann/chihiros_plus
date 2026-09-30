"""Push-notification policy for an unreachable lamp (no Home Assistant import).

The watchdog fires escalating unreachable events at 2 / 10 / 30 minutes. The
user picks, in Setup, a notify service (e.g. their phone) and after how many
minutes the first push should go out; every later threshold pushes again.
"""
from __future__ import annotations

NOTIFY_AFTER_CHOICES = (2, 10, 30)   # minutes; match the watchdog thresholds
DEFAULT_NOTIFY_AFTER = 2


def normalize_after(minutes: object) -> int:
    """Clamp a stored/sent value to one of the supported thresholds."""
    try:
        value = int(minutes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_NOTIFY_AFTER
    return value if value in NOTIFY_AFTER_CHOICES else DEFAULT_NOTIFY_AFTER


def push_due(threshold_seconds: float, after_minutes: int) -> bool:
    """True when an unreachable event at this threshold should be pushed."""
    return threshold_seconds >= after_minutes * 60


def split_service(service: str | None) -> tuple[str, str] | None:
    """'notify.mobile_app_x' -> ('notify', 'mobile_app_x'); None if invalid."""
    if not service or "." not in service:
        return None
    domain, name = service.split(".", 1)
    if domain != "notify" or not name:
        return None
    return domain, name


def unreachable_message(name: str, minutes: int, level: str) -> str:
    prefix = "CRITICAL: " if level == "critical" else ""
    return f"{prefix}{name} has been unreachable over Bluetooth for {minutes} min."


def reconnected_message(name: str) -> str:
    return f"{name} is reachable again."
