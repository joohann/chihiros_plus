"""Push-notification policy: which unreachable thresholds push, and to where."""
from __future__ import annotations

from chihiros_plus.notify_policy import (
    normalize_after,
    push_due,
    reconnected_message,
    split_service,
    unreachable_message,
)


def test_push_follows_chosen_first_threshold():
    thresholds = (120, 600, 1800)   # watchdog: 2 / 10 / 30 min
    assert [push_due(t, 2) for t in thresholds] == [True, True, True]
    assert [push_due(t, 10) for t in thresholds] == [False, True, True]
    assert [push_due(t, 30) for t in thresholds] == [False, False, True]


def test_normalize_after_only_allows_watchdog_thresholds():
    assert normalize_after(10) == 10
    assert normalize_after("30") == 30
    assert normalize_after(5) == 2
    assert normalize_after(None) == 2
    assert normalize_after("x") == 2


def test_split_service_accepts_only_notify_services():
    assert split_service("notify.mobile_app_iphone") == ("notify", "mobile_app_iphone")
    assert split_service("light.turn_on") is None
    assert split_service("notify.") is None
    assert split_service("") is None
    assert split_service(None) is None


def test_messages():
    assert unreachable_message("Tank", 30, "critical").startswith("CRITICAL: Tank")
    assert "10 min" in unreachable_message("Tank", 10, "warning")
    assert reconnected_message("Tank") == "Tank is reachable again."
