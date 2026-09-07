"""Parse notification frames coming back from the lamp.

Only the status/runtime response is documented well enough to parse with
confidence. Everything else is surfaced as a ``RawResponse`` so callers can
log it without us pretending to understand bytes we don't. We never fabricate
a "confirmed state" from an ambiguous frame.
"""
from __future__ import annotations

from dataclasses import dataclass

from .checksum import xor_checksum

# Response frames use command id 0x5b as their header (docs/protocol.md).
RESPONSE_HEADER = 0x5B


@dataclass(frozen=True, slots=True)
class RawResponse:
    """A response frame we received but do not (fully) interpret."""

    data: bytes
    checksum_ok: bool


@dataclass(frozen=True, slots=True)
class StatusResponse:
    """Parsed reply to a STATUS_QUERY (0x5a/0x04)."""

    runtime_minutes: int | None
    checksum_ok: bool
    raw: bytes


def _checksum_ok(frame: bytes) -> bool:
    if len(frame) < 3:
        return False
    return xor_checksum(frame[:-1]) == frame[-1]


def parse_notification(data: bytes) -> StatusResponse | RawResponse:
    """Best-effort parse of a notify payload.

    Returns a ``StatusResponse`` for a recognised status frame, otherwise a
    ``RawResponse`` carrying the bytes and whether the checksum validated.
    """
    if not data:
        return RawResponse(data=data, checksum_ok=False)

    ok = _checksum_ok(data)

    # Runtime response: header 0x5b, runtime (minutes) big-endian in bytes 6-7.
    if data[0] == RESPONSE_HEADER and len(data) >= 8:
        runtime = (data[6] << 8) | data[7]
        return StatusResponse(runtime_minutes=runtime, checksum_ok=ok, raw=data)

    return RawResponse(data=data, checksum_ok=ok)
