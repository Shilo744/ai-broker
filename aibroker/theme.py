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
QSplitter::handle { background: transparent; } QSplitter::handle:horizontal { width: 6px; } QSplitter::handle:vertical { height: 6px; }
QSplitter::handle:hover { background: #393b40; }
QMenu { background: #2b2d30; border: 1px solid #43454a; padding: 3px; } QMenu::item { padding: 5px 20px; border-radius: 3px; } QMenu::item:selected { background: #2e436e; }
QToolTip { background: #393b40; color: #dfe1e5; border: 1px solid #4e5157; padding: 4px; }
QFrame#toolheader { background: transparent; border: none; border-bottom: 1px solid #393b40; }
QToolButton { background: transparent; border: none; border-radius: 4px; padding: 4px; } QToolButton:hover { background: #393b40; }
QToolButton:pressed { background: #43454a; } QToolButton:checked { background: #2e436e; }
QFrame#toast { background: #393b40; border: 1px solid #4e5157; border-radius: 6px; }
QFrame#statcard { background: #1e1f22; border: 1px solid #393b40; border-radius: 6px; }
QFrame#palette { background: #2b2d30; border: 1px solid #4e5157; border-radius: 8px; }
QFrame#palette QLineEdit { border: none; border-bottom: 1px solid #393b40; border-radius: 0; background: transparent; padding: 10px 12px; font-size: 11.5pt; }
QFrame#palette QListWidget { background: transparent; border: none; outline: none; padding: 4px; }
QFrame#palette QListWidget::item { padding: 7px 10px; border-radius: 4px; }
QFrame#palette QListWidget::item:selected { background: #2e436e; color: white; }
QPushButton#pill { background: transparent; border: 1px solid #4e5157; border-radius: 11px; padding: 3px 12px; font-size: 9.5pt; color: #b4b8bf; }
QPushButton#pill:hover { border-color: #3574f0; color: #ffffff; background: #233350; }
QPushButton#flat { background: transparent; border: 1px solid transparent; color: #868a91; padding: 2px 8px; font-size: 9.5pt; }
QPushButton#flat:hover { color: #dfe1e5; background: #393b40; }
"""

def qss(scale=1.0):
    """The stylesheet with every font size multiplied by `scale` (Ctrl +/- zoom)."""
    import re
    if abs(scale - 1.0) < 0.01:
        return QSS
    return re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: "%.1fpt" % (float(m.group(1)) * scale), QSS)


def style_titlebar(hwnd):
    """Dark title bar in the app colours (Windows 11; silently ignored elsewhere)."""
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi

        def put(attr, val):
            v = ctypes.c_int(val)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(int(hwnd)), attr, ctypes.byref(v), 4)
        put(20, 1)               # immersive dark mode
        put(35, 0x00221F1E)      # caption colour  #1e1f22  (COLORREF is BGR)
        put(36, 0x00E5E1DF)      # caption text    #dfe1e5
        put(34, 0x00403B39)      # border          #393b40
    except Exception:
        pass


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
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "hdd": '<rect x="3" y="14" width="18" height="6" rx="2"/><path d="M3 14l3-9h12l3 9M7 17h.01M11 17h.01"/>',
    "zoomin": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4M11 8v6M8 11h6"/>',
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


def dot_icon(color, size=10):
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QtCore.QRectF(size * 0.5, size * 0.5, size, size))
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QtGui.QIcon(pm)


def symbol_pixmap(symbol, color, size=96):
    """A tinted rounded square with the line icon of that type (model list, result tiles, start cards)."""
    dpr = 2.0
    px = int(size * dpr)
    pm = QtGui.QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = QtGui.QColor(color)
    p.setBrush(QtGui.QColor(c.red(), c.green(), c.blue(), 36))
    p.setPen(QtGui.QPen(QtGui.QColor(c.red(), c.green(), c.blue(), 100), 1.2))
    p.drawRoundedRect(QtCore.QRectF(1, 1, px - 2, px - 2), px / 8, px / 8)
    inner = icon_pixmap(SYMBOL_ICON.get(symbol, "doc"), color, int(px * 0.56), 1.0)     # device pixels: the target pixmap is still at ratio 1 while painting
    off = (px - inner.width()) // 2
    p.drawPixmap(off, off, inner)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


# ------------------------------------------------------------------ logo
# Three requests (three colours) converge into one ring (the machine) and leave as a single line: that is what the broker does.
INPUTS = (("#35d0c4", "#6ee7f9"), ("#4c8dff", "#7ee7ff"), ("#9a6bff", "#7ee7ff"))


def _grad(x0, x1, c1, c2):
    g = QtGui.QLinearGradient(x0, 0, x1, 0)
    g.setColorAt(0, QtGui.QColor(c1))
    g.setColorAt(1, QtGui.QColor(c2))
    return g


def paint_logo(p, status=None, detail=True):
    """Draws the logo into a 100x100 coordinate space: dark graphite tile, three converging lines, a ring, one line out."""
    tile = QtGui.QLinearGradient(0, 0, 0, 100)
    tile.setColorAt(0, QtGui.QColor("#272b33"))
    tile.setColorAt(1, QtGui.QColor("#121418"))
    p.setPen(Qt.NoPen)
    p.setBrush(tile)
    p.drawRoundedRect(QtCore.QRectF(0, 0, 100, 100), 23, 23)
    if detail:
        glow = QtGui.QRadialGradient(28, 18, 70)
        glow.setColorAt(0, QtGui.QColor(255, 255, 255, 26))
        glow.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(glow)
        p.drawRoundedRect(QtCore.QRectF(0, 0, 100, 100), 23, 23)
    p.setBrush(Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 80 if detail else 110), 1.4))
    p.drawRoundedRect(QtCore.QRectF(0.8, 0.8, 98.4, 98.4), 22.4, 22.4)
    cx, cy = 55, 50
    w_in = 5.6 if detail else 7.4
    for y, (c1, c2) in zip((27, 50, 73), INPUTS):
        path = QtGui.QPainterPath(QtCore.QPointF(13, y))
        path.cubicTo(QtCore.QPointF(36, y), QtCore.QPointF(38, cy), QtCore.QPointF(cx, cy))
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QBrush(_grad(13, cx, c1, c2)), w_in, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
    if detail:
        halo = QtGui.QRadialGradient(cx, cy, 20)
        halo.setColorAt(0, QtGui.QColor(126, 231, 255, 120))
        halo.setColorAt(1, QtGui.QColor(126, 231, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QtCore.QPointF(cx, cy), 20, 20)
    p.setPen(QtGui.QPen(QtGui.QBrush(_grad(cx, 90, "#ffffff", "#7ee7ff")), 8 if detail else 10, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(87, cy))
    p.setBrush(QtGui.QColor("#14161a"))
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 4.4 if detail else 5.6))
    p.drawEllipse(QtCore.QPointF(cx, cy), 9 if detail else 10, 9 if detail else 10)
    if detail:
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(QtCore.QPointF(cx, cy), 3.2, 3.2)
    if status:                                           # tray: a status dot in the corner
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#1e1f22"))
        p.drawEllipse(QtCore.QPointF(80, 80), 19, 19)
        p.setBrush(QtGui.QColor(status))
        p.drawEllipse(QtCore.QPointF(80, 80), 13, 13)


def logo_pixmap(size=64, status=None, dpr=2.0):
    px = max(8, int(size * dpr))
    pm = QtGui.QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(px / 100.0, px / 100.0)
    paint_logo(p, status, detail=px >= 36)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def make_icon(status=None):
    ic = QtGui.QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(sz, status))
    return ic


def save_ico(path):
    """Multi-size Windows icon (PNG-compressed entries, 16..256) so the desktop, taskbar and Start menu all get a sharp logo."""
    import struct
    sizes = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    blobs = []
    for sz in sizes:
        pm = logo_pixmap(sz, None, 1.0)
        ba = QtCore.QByteArray()
        buf = QtCore.QBuffer(ba)
        buf.open(QtCore.QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        blobs.append(bytes(ba))
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for sz, b in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", 0 if sz >= 256 else sz, 0 if sz >= 256 else sz, 0, 0, 1, 32, len(b), offset)
        offset += len(b)
    with open(str(path), "wb") as f:
        f.write(head + entries + b"".join(blobs))
    return True
