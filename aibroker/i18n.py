"""UI language. Hebrew is the default and the source language of every string in the code; T() returns the English text when the language is English.

The language lives in config.json ("lang": "he" | "en") so that the window, the broker and the assistant agree; the environment variable AIBROKER_LANG overrides it.
Changing it (Settings, gear icon) restarts the window. Right-to-left layout is used for Hebrew only. Keep the same %s / %d placeholders, in the same order,
in the English text of i18n_en.py (tools/i18n_tool.py check verifies that every T() key has an English text)."""
import json
import os
from pathlib import Path

LANGS = (("he", "עברית"), ("en", "English"))


def _read():
    env = os.environ.get("AIBROKER_LANG")
    if env in ("he", "en"):
        return env
    home = Path(os.environ.get("AIBROKER_HOME") or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ai-broker"))
    try:
        v = json.loads((home / "config.json").read_text(encoding="utf-8")).get("lang")
        if v in ("he", "en"):
            return v
    except (OSError, ValueError, AttributeError):
        pass
    return "he"


LANG = _read()
_EN = None


def en_table():
    global _EN
    if _EN is None:
        from .i18n_en import EN
        _EN = EN
    return _EN


def T(s, ctx=None):
    """The text in the UI language. Unknown strings come back unchanged (Hebrew), so a missing translation never breaks anything.
    ctx: for a Hebrew word that needs a different English word in a specific place (EN_CTX in i18n_en.py)."""
    if LANG != "en":
        return s
    if ctx:
        from .i18n_en import EN_CTX
        hit = EN_CTX.get((ctx, s))
        if hit:
            return hit
    return en_table().get(s, s)


def set_lang(code):
    global LANG
    LANG = code if code in ("he", "en") else "he"


def lang():
    return LANG


def rtl():
    return LANG == "he"
