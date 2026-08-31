"""Make ``my_chihiros`` importable as a package when running tests directly.

Adds the ``custom_components`` directory (the package's parent) to sys.path so
``import my_chihiros...`` resolves without Home Assistant installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_CUSTOM_COMPONENTS = Path(__file__).resolve().parents[2]
if str(_CUSTOM_COMPONENTS) not in sys.path:
    sys.path.insert(0, str(_CUSTOM_COMPONENTS))
