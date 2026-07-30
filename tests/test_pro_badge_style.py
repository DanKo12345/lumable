from __future__ import annotations

import pytest

from app.styles import build_theme_stylesheet
from app.theme import DARK, LIGHT, pro_badge_tokens


@pytest.mark.parametrize(("tokens", "is_dark"), [(DARK, True), (LIGHT, False)])
def test_shared_pro_badge_is_a_compact_outlined_status(
    tokens: dict[str, str],
    is_dark: bool,
) -> None:
    stylesheet = build_theme_stylesheet(tokens)
    pro = pro_badge_tokens(is_dark)

    assert "#proBadge {" in stylesheet
    assert f"color: {pro['text']};" in stylesheet
    assert f"background: {pro['background']};" in stylesheet
    assert f"border: 1px solid {pro['border']};" in stylesheet
    assert "padding: 1px 6px;" in stylesheet
    assert "font-size: 10px;" in stylesheet
