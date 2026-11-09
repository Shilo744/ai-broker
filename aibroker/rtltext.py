"""Hebrew / English text direction for chat messages (learned from Terminal Grid, docs/design-principles.md rule 10):

* the direction of a paragraph comes from the MAJORITY script, not from the first letter ("T1 הושלם" is right-to-left, and a bullet that starts with a
  product name such as "FLUX.2 klein 4B (תמונה): ..." is still a Hebrew sentence). A paragraph counts as Hebrew when at least 30 percent of its letters are Hebrew;
* a paragraph without letters (numbers, symbols, empty) keeps the direction of the paragraph before it;
* code blocks always stay left-to-right and left-aligned.

Qt's own bidi algorithm then lays out the English words, numbers and paths inside a Hebrew paragraph correctly, and mirrors list bullets."""
import re

from PySide6 import QtGui
from PySide6.QtCore import Qt

HEB = re.compile("[֐-׿]")
LATIN = re.compile("[A-Za-z]")
RTL_SHARE = 0.3


def is_rtl(text, default=None):
    """True: right-to-left paragraph. `default` is returned when the text has no letters at all."""
    heb = len(HEB.findall(text))
    lat = len(LATIN.findall(text))
    if heb + lat == 0:
        return default
    return heb > 0 and heb >= RTL_SHARE * (heb + lat)


def _is_code_block(block):
    """A paragraph that is one single monospace fragment (a fenced code block line)."""
    it = block.begin()
    if it.atEnd():
        return False
    frag = it.fragment()
    return frag.isValid() and frag.charFormat().fontFixedPitch() and len(frag.text()) >= len(block.text())


def apply_directions(doc, default_rtl=True):
    """Gives every paragraph of a QTextDocument its direction (and the matching alignment)."""
    prev = default_rtl
    cur = QtGui.QTextCursor(doc)
    cur.beginEditBlock()
    block = doc.begin()
    while block.isValid():
        text = block.text()
        fmt = block.blockFormat()
        if _is_code_block(block):
            fmt.setLayoutDirection(Qt.LeftToRight)
            fmt.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute)
        else:
            rtl = is_rtl(text, prev)
            prev = rtl
            fmt.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
            fmt.setAlignment(Qt.AlignRight | Qt.AlignAbsolute if rtl else Qt.AlignLeft | Qt.AlignAbsolute)
        cur.setPosition(block.position())
        cur.setBlockFormat(fmt)
        block = block.next()
    cur.endEditBlock()
