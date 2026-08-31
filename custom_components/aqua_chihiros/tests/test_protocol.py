"""Protocol-layer tests: checksum, frame building, message-id quirk, round-trip."""
from __future__ import annotations

import pytest

from aqua_chihiros.fake_device import FakeChihirosDevice, FrameError
from aqua_chihiros.protocol import (
    RGBW,
    MessageIdCounter,
    enter_auto_mode,
    enter_manual_mode,
    parse_notification,
    query_status,
    set_channel_brightness,
    set_rgbw,
    set_time,
    xor_checksum,
)
from aqua_chihiros.protocol.parser import StatusResponse


def test_checksum_matches_documented_example():
    # 5a 01 07 00 20 07 00 64 -> checksum 0x45 (docs/protocol.md example)
    head = bytes([0x5A, 0x01, 0x07, 0x00, 0x20, 0x07, 0x00, 0x64])
    assert xor_checksum(head) == 0x45


def test_frame_structure_and_length():
    mid = MessageIdCounter()
    frame = set_channel_brightness(0, 100, mid)
    assert frame[0] == 0x5A
    assert frame[1] == 0x01
    assert frame[2] == len([0, 100]) + 5  # length field = params + 5
    assert frame[5] == 0x07               # manual channel mode
    assert list(frame[6:8]) == [0, 100]
    assert xor_checksum(frame[:-1]) == frame[-1]
    assert len(frame) == 2 + 7            # params(2) + 7


def test_checksum_never_reserved_0x5a():
    mid = MessageIdCounter()
    for ch in range(4):
        for level in range(0, 101):
            frame = set_channel_brightness(ch, level, mid)
            assert frame[-1] != 0x5A


def test_message_id_bytes_skip_reserved():
    mid = MessageIdCounter(start=0x59)  # next few ids would hit 0x5a in low byte
    for _ in range(300):
        hi, lo = mid.next_id()
        assert hi != 0x5A and lo != 0x5A


def test_set_rgbw_produces_four_channel_frames():
    mid = MessageIdCounter()
    frames = set_rgbw(RGBW(10, 20, 30, 40), mid)
    assert len(frames) == 4
    dev = FakeChihirosDevice()
    for f in frames:
        dev.write(f)
    assert dev.channels == [10, 20, 30, 40]
    assert dev.mode == "manual"


def test_mode_switches_round_trip():
    mid = MessageIdCounter()
    dev = FakeChihirosDevice()
    dev.write(enter_auto_mode(mid))
    assert dev.mode == "auto"
    dev.write(enter_manual_mode(mid))
    assert dev.mode == "manual"


def test_set_time_round_trip():
    mid = MessageIdCounter()
    dev = FakeChihirosDevice()
    dev.write(set_time(year=2026, month=8, weekday=7, hour=14, minute=32, second=5, msg_id=mid))
    assert dev.device_time == (26, 8, 7, 14, 32, 5)


def test_status_query_and_parse():
    mid = MessageIdCounter()
    dev = FakeChihirosDevice(runtime_minutes=1234)
    dev.write(query_status(mid))
    resp = parse_notification(dev.status_response())
    assert isinstance(resp, StatusResponse)
    assert resp.checksum_ok
    assert resp.runtime_minutes == 1234


def test_fake_device_rejects_bad_checksum():
    dev = FakeChihirosDevice()
    good = set_channel_brightness(1, 50, MessageIdCounter())
    corrupt = good[:-1] + bytes([good[-1] ^ 0xFF])
    with pytest.raises(FrameError):
        dev.write(corrupt)


def test_invalid_channel_and_brightness_rejected():
    mid = MessageIdCounter()
    with pytest.raises(ValueError):
        set_channel_brightness(4, 10, mid)
    with pytest.raises(ValueError):
        set_channel_brightness(0, 101, mid)
