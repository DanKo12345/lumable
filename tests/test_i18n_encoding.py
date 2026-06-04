from __future__ import annotations

import json
from pathlib import Path

import pytest

I18N_DIR = Path(__file__).parent.parent / "app" / "i18n"
LANGUAGES = ["en.json", "ru.json", "zh.json"]


def _read_translations(lang: str) -> dict[str, str]:
    data = json.loads((I18N_DIR / lang).read_text(encoding="utf-8"))
    assert isinstance(data.get("translations"), dict)
    return data["translations"]


@pytest.mark.parametrize("lang", LANGUAGES)
def test_no_question_marks_in_values(lang: str) -> None:
    """Checks that i18n files were saved as UTF-8 and not replaced with ???."""
    translations = _read_translations(lang)
    broken = {key: value for key, value in translations.items() if "???" in str(value) or "\ufffd" in str(value)}
    assert not broken, f"{lang} contains broken strings: {broken}"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_all_keys_present_in_all_languages(lang: str) -> None:
    """Checks that every language contains all keys from en.json."""
    en = _read_translations("en.json")
    other = _read_translations(lang)
    missing = set(en.keys()) - set(other.keys())
    assert not missing, f"{lang} is missing keys: {missing}"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_no_translation_keys_outside_translations(lang: str) -> None:
    """Checks that translation keys were not written at the JSON top level."""
    data = json.loads((I18N_DIR / lang).read_text(encoding="utf-8"))
    stray = {key for key in data if "." in key}
    assert not stray, f"{lang} contains translation keys outside translations: {stray}"


@pytest.mark.parametrize("lang", ["ru.json", "zh.json"])
def test_no_english_placeholders(lang: str) -> None:
    """Warns when long strings in ru/zh are still identical to English."""
    en = _read_translations("en.json")
    other = _read_translations(lang)
    same_as_en = {
        key
        for key, value in other.items()
        if value == en.get(key) and len(str(en.get(key, ""))) > 10
    }
    if same_as_en:
        print(f"WARNING {lang}: possible untranslated strings: {same_as_en}")
