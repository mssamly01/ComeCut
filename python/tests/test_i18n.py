from __future__ import annotations

import pytest

from comecut_py import i18n


def test_available_locales_has_en_vi_zh():
    locs = i18n.available_locales()
    assert "en" in locs and "vi" in locs and "zh" in locs


def test_set_locale_and_translate():
    i18n.set_locale("vi")
    assert i18n.t("menu.file") == "Tệp"
    i18n.set_locale("en")
    assert i18n.t("menu.file") == "File"


def test_unknown_locale_raises():
    with pytest.raises(ValueError):
        i18n.set_locale("xx")


def test_unknown_key_falls_back():
    i18n.set_locale("en")
    assert i18n.t("nonexistent.key", default="fallback") == "fallback"
    assert i18n.t("nonexistent.key") == "nonexistent.key"
