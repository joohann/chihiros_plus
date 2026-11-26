#!/usr/bin/env python3
"""Report missing panel translations, and scaffold a new language file.

    python3 tools/i18n_check.py            # report
    python3 tools/i18n_check.py --new de   # write an empty de.json

English is the source language: every key used in the panel must exist in
en.json, and every other language is measured against it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = ROOT / "frontend" / "chihiros-panel.js"
TRANSLATIONS = ROOT / "frontend" / "translations"
BASE_LANGUAGE = "en"

KEY_PATTERN = re.compile(r"""\bt\(\s*["']([a-z0-9_]+)["']""")
TEMPLATE_PATTERN = re.compile(r"""\bt\(\s*`([a-z0-9_]+)\$\{""")
# Keys picked by a ternary inside t(), e.g. t(cond ? "a" : "b").
TERNARY_PATTERN = re.compile(r"""\bt\(\s*[^()]*\?\s*["']([a-z0-9_]+)["']\s*:\s*["']([a-z0-9_]+)["']""", re.S)
# Problem keys are returned by _sectionProblem() and translated by the caller.
NOTICE_PATTERN = re.compile(r"""["'](problem_[a-z0-9_]+)["']""")


def used_keys() -> set[str]:
    source = PANEL_JS.read_text()
    keys = set(KEY_PATTERN.findall(source))
    keys.update(NOTICE_PATTERN.findall(source))
    for pair in TERNARY_PATTERN.findall(source):
        keys.update(pair)
    # Keys built from a template literal, e.g. t(`status_${status}`): the
    # prefix is checked against the base file by hand below.
    for prefix in TEMPLATE_PATTERN.findall(source):
        keys.update(
            key for key in json.loads((TRANSLATIONS / f"{BASE_LANGUAGE}.json").read_text())
            if key.startswith(prefix)
        )
    return keys


def load(language: str) -> dict[str, str]:
    path = TRANSLATIONS / f"{language}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def languages() -> list[str]:
    return sorted(path.stem for path in TRANSLATIONS.glob("*.json"))


def report() -> int:
    base = load(BASE_LANGUAGE)
    used = used_keys()
    problems = 0

    missing_in_base = sorted(used - base.keys())
    if missing_in_base:
        problems += len(missing_in_base)
        print(f"{BASE_LANGUAGE}.json is missing {len(missing_in_base)} key(s) used by the panel:")
        for key in missing_in_base:
            print(f"  - {key}")

    unused = sorted(base.keys() - used)
    if unused:
        print(f"{BASE_LANGUAGE}.json has {len(unused)} unused key(s):")
        for key in unused:
            print(f"  - {key}")

    for language in languages():
        if language == BASE_LANGUAGE:
            continue
        translated = load(language)
        missing = sorted(base.keys() - translated.keys())
        extra = sorted(translated.keys() - base.keys())
        empty = sorted(key for key, value in translated.items() if not str(value).strip())
        if missing or extra or empty:
            problems += len(missing) + len(extra) + len(empty)
            print(f"{language}.json:")
            for key in missing:
                print(f"  - missing: {key}")
            for key in empty:
                print(f"  - empty: {key}")
            for key in extra:
                print(f"  - not in {BASE_LANGUAGE}: {key}")

    if not problems:
        print(f"All {len(base)} keys present in: {', '.join(languages())}")
    return 1 if problems else 0


def scaffold(language: str) -> int:
    path = TRANSLATIONS / f"{language}.json"
    if path.exists():
        print(f"{path.name} already exists")
        return 1
    base = load(BASE_LANGUAGE)
    path.write_text(
        json.dumps({key: "" for key in base}, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"Wrote {path} with {len(base)} empty key(s); translate those only.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", metavar="LANGUAGE", help="create an empty language file")
    args = parser.parse_args()
    return scaffold(args.new) if args.new else report()


if __name__ == "__main__":
    sys.exit(main())
