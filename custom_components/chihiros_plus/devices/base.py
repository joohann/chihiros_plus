"""Device abstraction: describe a Chihiros model's capabilities.

This layer sits between the Light Controller and the concrete hardware so new
models can be added without touching the engine or the controller. A model is
described by data (channels, friendly name, feature flags), not by bespoke
command code — the shared protocol layer handles the bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChihirosModel:
    """Capabilities of one Chihiros model."""

    key: str                       # internal id, e.g. "wrgb_ii_slim"
    name: str                      # human-facing model name
    channels: tuple[str, ...]      # ordered channel labels; index == protocol channel
    supports_rgb: bool = True
    supports_white: bool = True
    supports_moonlight: bool = True
    name_prefixes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def channel_count(self) -> int:
        return len(self.channels)


_REGISTRY: dict[str, ChihirosModel] = {}


def register(model: ChihirosModel) -> ChihirosModel:
    _REGISTRY[model.key] = model
    return model


def get_model(key: str) -> ChihirosModel | None:
    return _REGISTRY.get(key)


def model_for_name(advertised_name: str) -> ChihirosModel | None:
    """Best-effort model lookup from an advertised BLE name prefix."""
    upper = advertised_name.upper()
    for model in _REGISTRY.values():
        if any(upper.startswith(p) for p in model.name_prefixes):
            return model
    return None


def all_models() -> tuple[ChihirosModel, ...]:
    return tuple(_REGISTRY.values())
