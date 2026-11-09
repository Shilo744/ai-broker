"""Look of the AI Broker window: an IDE-style dark theme (neutral grey, one blue accent, small radii, thin line icons) and the product logo.
All icons are drawn from the small SVG set below (own drawings, 24x24 grid, stroke only), recoloured on the fly."""
from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt
from PySide6.QtSvg import QSvgRenderer

# ------------------------------------------------------------------ palette
BG = "#1e1f22"          # editor area, toolbar, inputs
PANEL = "#2b2d30"       # tool windows
LINE = "#393b40"        # separators, hover
BORDER = "#43454a"      # control borders
TEXT = "#dfe1e5"
SUB = "#b4b8bf"
MUTED = "#868a91"
ACCENT = "#3574f0"
SELECT = "#2e436e"
OK = "#5fad65"
WARN = "#e0a030"
BAD = "#db5c5c"

QSS = """
* { font-family: 'Segoe UI'; font-size: 10.5pt; color: #dfe1e5; }
QMainWindow, QDialog, QWidget#page { background: #1e1f22; }
QFrame#topbar { background: #1e1f22; border-bottom: 1px solid #393b40; }
QFrame#panel { background: #2b2d30; border: 1px solid #393b40; border-radius: 6px; }
QFrame#editor { background: #1e1f22; border: 1px solid #393b40; border-radius: 6px; }
QFrame#bubble_user { background: #233350; border: 1px solid #2e436e; border-radius: 6px; }
QFrame#bubble_model { background: #2b2d30; border: 1px solid #393b40; border-radius: 6px; }
QFrame#composer { background: #2b2d30; border: 1px solid #43454a; border-radius: 6px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 11.5pt; font-weight: 600; letter-spacing: 0.3px; }
QLabel#h1 { font-size: 14pt; font-weight: 600; } QLabel#h2 { font-size: 10pt; font-weight: 600; color: #b4b8bf; }
QLabel#muted { color: #868a91; font-size: 9.5pt; } QLabel#big { font-size: 10.5pt; font-weight: 600; }
QPushButton { background: #2b2d30; border: 1px solid #4e5157; border-radius: 4px; padding: 5px 14px; }
QPushButton:hover { background: #393b40; } QPushButton:pressed { background: #43454a; } QPushButton:disabled { color: #6f737a; border-color: #393b40; }
QPushButton#primary { background: #3574f0; border-color: #3574f0; color: white; } QPushButton#primary:hover { background: #4682fa; border-color: #4682fa; }
QPushButton#tool { padding: 3px 9px; font-size: 9.5pt; }
QPushButton#tb, QPushButton#tbplay, QPushButton#tbpause { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 5px 11px; }
QPushButton#tb:hover, QPushButton#tbplay:hover, QPushButton#tbpause:hover { background: #393b40; }
QPushButton#tb:checked { background: #2e436e; border-color: #3574f0; }
QPushButton#tbplay:checked { background: #4a2b2e; border-color: #db5c5c; }
QPushButton#tbpause:checked { background: #4a3b1c; border-color: #e0a030; }
QListWidget, QTableWidget { background: transparent; border: none; outline: none; gridline-color: #393b40; alternate-background-color: #2f3135; }
QListWidget#models::item { padding: 6px 8px; border-radius: 4px; margin: 1px 4px; } QListWidget#models::item:selected { background: #2e436e; color: white; }
QListWidget#models::item:hover { background: #393b40; } QListWidget#models::item:selected:hover { background: #2e436e; }
QListWidget#files::item { border-radius: 4px; padding: 4px; } QListWidget#files::item:selected { background: #2e436e; } QListWidget#files::item:hover { background: #393b40; }
QTableWidget { selection-background-color: #2e436e; selection-color: white; }
QHeaderView::section { background: transparent; color: #868a91; border: none; border-bottom: 1px solid #393b40; padding: 4px 8px; font-weight: 500; }
QTabWidget::pane { border: none; } QTabBar::tab { background: transparent; color: #868a91; padding: 6px 14px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #3574f0; } QTabBar::tab:hover:!selected { color: #dfe1e5; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #1e1f22; border: 1px solid #43454a; border-radius: 4px; padding: 5px 8px; selection-background-color: #3574f0; }
QLineEdit:focus, QComboBox:focus { border-color: #3574f0; }
QComboBox QAbstractItemView { background: #2b2d30; selection-background-color: #2e436e; border: 1px solid #43454a; }
QPlainTextEdit { background: #17181a; color: #bcbec4; border: 1px solid #393b40; border-radius: 4px; font-family: Consolas; font-size: 10pt; padding: 8px; }
QSlider::groove:horizontal { height: 3px; background: #43454a; border-radius: 1px; } QSlider::sub-page:horizontal { background: #3574f0; border-radius: 1px; }
QSlider::handle:horizontal { background: #dfe1e5; width: 12px; margin: -5px 0; border-radius: 6px; }
QCheckBox { spacing: 8px; padding: 2px 0; } QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #4e5157; border-radius: 3px; background: #1e1f22; }
QCheckBox::indicator:checked { background: #3574f0; border-color: #3574f0; }
QStatusBar { background: #2b2d30; border-top: 1px solid #393b40; } QStatusBar QLabel { padding: 0 10px; font-size: 9.5pt; color: #868a91; }
QProgressBar { border: none; border-radius: 1px; background: #393b40; max-height: 3px; min-height: 3px; } QProgressBar::chunk { background: #3574f0; border-radius: 1px; }
QScrollBar:vertical { background: transparent; width: 9px; } QScrollBar::handle:vertical { background: #4e5157; border-radius: 3px; min-height: 30px; margin: 1px; }
QScrollBar:horizontal { background: transparent; height: 9px; } QScrollBar::handle:horizontal { background: #4e5157; border-radius: 3px; min-width: 30px; margin: 1px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QSplitter::handle { background: transparent; }
QMenu { background: #2b2d30; border: 1px solid #43454a; padding: 3px; } QMenu::item { padding: 5px 20px; border-radius: 3px; } QMenu::item:selected { background: #2e436e; }
QToolTip { background: #393b40; color: #dfe1e5; border: 1px solid #4e5157; padding: 4px; }
"""

# ------------------------------------------------------------------ line icons (24x24, stroke only unless noted)
_SVG = {
    "sparkles": '<path d="M11 3l2 5.5L18.5 10.5 13 12.5 11 18l-2-5.5L3.5 10.5 9 8.5z"/><path d="M19 3v4M17 5h4M19 17v4M17 19h4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 8"/>',
    "wand": '<path d="M4 20L16 8"/><path d="M14 6l4 4"/><path d="M19 3v3M17.5 4.5h3"/><path d="M5 5v2M4 6h2"/>',
    "cube": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3.5 17.5l3 3 5.8-5.8a4 4 0 0 0 5.4-5.4l-2.4 2.4-2.4-.6-.6-2.4z"/>',
    "music": '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    "speaker": '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11"/>',
    "gamepad": '<rect x="2.5" y="7" width="19" height="11" rx="5"/><path d="M7 10.5v4M5 12.5h4"/><circle cx="15" cy="11.5" r=".8"/><circle cx="17.5" cy="13.5" r=".8"/>',
    "camera": '<path d="M4 8h3l1.5-2h7L17 8h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M16 4v16M3 9h5M3 15h5M16 9h5M16 15h5"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "play": '<path d="M7 4.5l12 7.5-12 7.5z"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "up": '<path d="M6 15l6-6 6 6"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "top": '<path d="M5 5h14M12 20V9M7 14l5-5 5 5"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.5-5.8"/><path d="M20 4v5h-5"/>',
    "send": '<path d="M4 12l16-8-6 16-3-7z"/>',
    "clip": '<path d="M20 11l-8 8a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8"/>',
    "doc": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/>',
}
_FILLED = {"pause", "play"}
SYMBOL_ICON = {"✎": "image", "✦": "wand", "⬢": "cube", "◈": "layers", "⚒": "wrench", "▦": "layers", "♪": "music", "♬": "speaker", "▷": "gamepad", "◎": "camera",
               "▶": "film", "λ": "code", "⚙": "gear", "▤": "grid", "+": "plus", "≡": "doc", "▫": "doc", "✧": "sparkles", "•": "doc"}
_cache = {}


def icon_pixmap(name, color=SUB, size=16, dpr=2.0):
    key = (name, color, size, dpr)
    pm = _cache.get(key)
    if pm is None:
        body = _SVG.get(name, _SVG["doc"])
        fill = color if name in _FILLED else "none"
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%s" stroke="%s" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
               % (fill, color, body))
        r = QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
        px = int(size * dpr)
        pm = QtGui.QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r.render(p)
        p.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def icon(name, color=SUB, size=16):
    return QtGui.QIcon(icon_pixmap(name, color, size))


def sym_icon(symbol, color=SUB, size=18):
    return icon(SYMBOL_ICON.get(symbol, "doc"), color, size)


def symbol_pixmap(symbol, color, size=96):
    """A tinted rounded square with the line icon of that type (model list, result tiles)."""
    dpr = 2.0
    px = int(size * dpr)
    pm = QtGui.QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = QtGui.QColor(color)
    p.setBrush(QtGui.QColor(c.red(), c.green(), c.blue(), 36))
    p.setPen(QtGui.QPen(QtGui.QColor(c.red(), c.green(), c.blue(), 100), 1.2))
    r = size * dpr
    p.drawRoundedRect(QtCore.QRectF(1, 1, r - 2, r - 2), r / 8, r / 8)
    inner = icon_pixmap(SYMBOL_ICON.get(symbol, "doc"), color, int(size * 0.52), dpr)
    off = (r - inner.width()) / 2
    p.drawPixmap(int(off), int(off), inner)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


# ------------------------------------------------------------------ logo
def logo_pixmap(size=64, status=None):
    """Product mark: gradient tile with a black square carrying 'AB' and a small bar (queue), in the layout language of IDE product icons."""
    dpr = 2.0
    s = size * dpr
    pm = QtGui.QPixmap(int(s), int(s))
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    g = QtGui.QLinearGradient(0, 0, s, s)
    g.setColorAt(0.0, QtGui.QColor("#20c5ff"))
    g.setColorAt(0.5, QtGui.QColor("#3574f0"))
    g.setColorAt(1.0, QtGui.QColor("#8a4cf0"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QtCore.QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    p.setBrush(QtGui.QColor("#000000"))
    p.drawRect(QtCore.QRectF(s * 0.13, s * 0.30, s * 0.57, s * 0.57))
    p.setPen(QtGui.QColor("#ffffff"))
    f = QtGui.QFont("Segoe UI", 1)
    f.setBold(True)
    f.setPixelSize(max(6, int(s * 0.27)))
    p.setFont(f)
    p.drawText(QtCore.QRectF(s * 0.13, s * 0.33, s * 0.57, s * 0.34), Qt.AlignCenter, "AB")
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRect(QtCore.QRectF(s * 0.20, s * 0.76, s * 0.22, s * 0.045))
    if status:
        r = s * 0.17
        p.setBrush(QtGui.QColor("#1e1f22"))
        p.drawEllipse(QtCore.QPointF(s - r * 1.05, s - r * 1.05), r * 1.25, r * 1.25)
        p.setBrush(QtGui.QColor(status))
        p.drawEllipse(QtCore.QPointF(s - r * 1.05, s - r * 1.05), r * 0.85, r * 0.85)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def make_icon(status=None):
    ic = QtGui.QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(sz, status))
    return ic


def save_ico(path):
    pm = logo_pixmap(256)
    pm.setDevicePixelRatio(1.0)
    return pm.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(path), "ICO")
