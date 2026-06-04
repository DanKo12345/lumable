#!/usr/bin/env python3
"""
Safe writer for i18n JSON files.

Always writes UTF-8 without BOM.
Run from the project root:
    python tools/write_i18n.py

Use this helper for every i18n JSON rewrite. Do not write app/i18n/*.json
directly from PowerShell because the console code page can corrupt Cyrillic
and Chinese text into question marks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

I18N_DIR = Path(__file__).parent.parent / "app" / "i18n"


def write_json(filename: str, data: dict[str, Any]) -> None:
    path = I18N_DIR / filename
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Written: {path}")


def read_json(filename: str) -> dict[str, Any]:
    path = I18N_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    for lang in ["en.json", "ru.json", "zh.json"]:
        data = read_json(lang)
        write_json(lang, data)
        print(f"Re-saved {lang} as clean UTF-8")
