"""AI Broker window. Dark, calm, Hebrew (right-to-left).
Main window = Models (each with its own OUTPUT folder) | Queue + History + the selected model's OUTPUT browser | Resources + limits.
Jobs are submitted by Claude through MCP/CLI; the owner mostly watches. A small secondary "Submit job" button exists with minimal fields.
The window is only a client of the broker service: closing it never stops the queue.
  python -m aibroker.gui [--screenshot out.png] [--model <output_dir>] [--tab 0|1] [--size 1280x800] [--no-tray]"""
import json
import os
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as W
from PySide6.QtCore import Qt

from . import client, paths

QSS = """
* { font-family: 'Segoe UI'; font-size: 11.5pt; color: #e6e8ee; }
QMainWindow, QDialog, QWidget#page { background: #0f1115; }
QFrame#panel { background: #14171d; border: 1px solid #262b36; border-radius: 10px; }
QLabel { background: transparent; }
QLabel#h1 { font-size: 17pt; font-weight: 600; } QLabel#h2 { font-size: 12.5pt; font-weight: 600; color: #aeb6c7; }
QLabel#muted { color: #8b93a5; font-size: 10.5pt; } QLabel#big { font-size: 12.5pt; font-weight: 600; }
QPushButton { background: #1c212b; border: 1px solid #2c3340; border-radius: 8px; padding: 7px 16px; font-weight: 500; }
QPushButton:hover { border-color: #4f8cff; background: #212836; } QPushButton:disabled { color: #5b6578; }
QPushButton#primary { background: #4f8cff; border-color: #4f8cff; color: white; } QPushButton#primary:hover { background: #3f7bef; }
QPushButton#tool { padding: 5px 10px; font-size: 10.5pt; }
QPushButton#bigplay, QPushButton#bigpause { padding: 9px 20px; font-size: 12pt; font-weight: 600; }
QPushButton#bigplay:checked { background: #f0506e; border-color: #f0506e; color: white; }
QPushButton#bigpause:checked { background: #f5a524; border-color: #f5a524; color: #1a1300; }
QListWidget, QTableWidget { background: transparent; border: none; outline: none; gridline-color: #262b36; alternate-background-color: #151920; }
QListWidget#models::item { padding: 8px 10px; border-radius: 8px; margin: 1px 4px; } QListWidget#models::item:selected { background: #212a3d; color: white; }
QListWidget#models::item:hover { background: #1a2030; }
QListWidget#files::item { border-radius: 8px; padding: 4px; } QListWidget#files::item:selected { background: #212a3d; } QListWidget#files::item:hover { background: #1a2030; }
QTableWidget { selection-background-color: #212a3d; selection-color: white; }
QHeaderView::section { background: transparent; color: #8b93a5; border: none; border-bottom: 1px solid #262b36; padding: 6px 8px; font-weight: 500; }
QTabWidget::pane { border: none; } QTabBar::tab { background: transparent; color: #8b93a5; padding: 8px 18px; border-bottom: 2px solid transparent; font-size: 12pt; }
QTabBar::tab:selected { color: white; border-bottom: 2px solid #4f8cff; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #12151b; border: 1px solid #2c3340; border-radius: 8px; padding: 7px 10px; selection-background-color: #4f8cff; }
QComboBox QAbstractItemView { background: #171a21; selection-background-color: #212a3d; border: 1px solid #2c3340; }
QPlainTextEdit { background: #0b0d11; color: #c5cad6; border: 1px solid #262b36; border-radius: 8px; font-family: Consolas; font-size: 10pt; padding: 8px; }
QSlider::groove:horizontal { height: 4px; background: #2c3340; border-radius: 2px; } QSlider::sub-page:horizontal { background: #4f8cff; border-radius: 2px; }
QSlider::handle:horizontal { background: #e6e8ee; width: 14px; margin: -5px 0; border-radius: 7px; }
QCheckBox { spacing: 10px; padding: 3px 0; } QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #3a4252; border-radius: 5px; background: #12151b; }
QCheckBox::indicator:checked { background: #4f8cff; border-color: #4f8cff; }
QStatusBar { background: #0f1115; border-top: 1px solid #262b36; } QStatusBar QLabel { padding: 0 12px; font-size: 10pt; color: #8b93a5; }
QScrollBar:vertical { background: transparent; width: 10px; } QScrollBar::handle:vertical { background: #2c3340; border-radius: 5px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; } QScrollBar::handle:horizontal { background: #2c3340; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QSplitter::handle { background: transparent; }
QMenu { background: #171a21; border: 1px solid #2c3340; padding: 4px; } QMenu::item { padding: 6px 22px; border-radius: 6px; } QMenu::item:selected { background: #212a3d; }
QToolTip { background: #232a37; color: #e6e8ee; border: 1px solid #343b4a; padding: 5px; }
"""

SYM = {"🖼️": "✎", "🎨": "✦", "🧊": "⬢", "🗿": "◈", "🛠️": "⚒", "🧱": "▦", "🎵": "♪", "🔊": "♬", "🎮": "▷", "📸": "◎", "🎬": "▶", "🐍": "λ", "⚙️": "⚙"}
STATE_HE = {"running": "רץ", "paused": "מוקפא", "queued": "ממתין", "held": "עצור", "done": "הצליח", "failed": "נכשל", "cancelled": "בוטל", "lost": "לא ידוע"}
STATE_COLOR = {"running": "#34c38f", "paused": "#f5a524", "queued": "#8b93a5", "held": "#f5a524", "done": "#34c38f", "failed": "#f0506e", "cancelled": "#8b93a5", "lost": "#f5a524"}
HIDDEN_FILES = {"job.log", "result.json"}
IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
KIND = {".glb": ("⬢", "#2aa198"), ".gltf": ("⬢", "#2aa198"), ".obj": ("⬢", "#2aa198"), ".ogg": ("♪", "#43a047"), ".wav": ("♪", "#43a047"), ".flac": ("♪", "#43a047"),
        ".mp3": ("♪", "#43a047"), ".mp4": ("▶", "#c0392b"), ".json": ("≡", "#8b93a5"), ".txt": ("≡", "#8b93a5"), ".log": ("≡", "#8b93a5"), ".blend": ("⚒", "#e87d0d")}


def ltr(t):
    """keep numbers like '~7 GB' in reading order inside right-to-left text"""
    return "‪%s‬" % t


def fmt_dur(s):
    s = int(s or 0)
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def fmt_size(n):
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % max(1, n // 1000)


def he_reason(r):
    if not r:
        return "מתחיל תיכף"
    table = (("RAM budget", "אין כרגע מספיק RAM פנוי לעבודה הזו"), ("VRAM budget", "ה-GPU עסוק, מחכה שיתפנה מקום"), ("free RAM", "ה-RAM של המחשב נמוך, מחכה"),
             ("free commit", "ה-RAM של המחשב נמוך, מחכה"), ("paused", "הכול מושהה"), ("I am playing", "אתה משחק, עבודות GPU מחכות"), ("held", "עצרת אותה בעצמך"),
             ("max concurrent", "כבר רצות הרבה עבודות במקביל"), ("another", "עבודה מאותו סוג כבר רצה"), ("GPU lock", "תוכנה אחרת משתמשת ב-GPU"),
             ("a self-locking", "מצלמים עכשיו את המשחק"), ("visual run", "עבודת GPU רצה עכשיו"), ("BRAKE", "המחשב בלחץ, עצרתי הכול"),
             ("starvation", "העבודה הראשונה ממתינה הרבה זמן, אף אחת לא עוקפת אותה"), ("waiting for the job", "מחכה לעבודה אחרת"), ("backfill", "מחכה לעבודה שלפניה"))
    for k, v in table:
        if r.startswith(k) or k in r[:24]:
            return v
    return r


def symbol_pixmap(symbol, color, size=96):
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = QtGui.QColor(color)
    p.setBrush(QtGui.QColor(c.red(), c.green(), c.blue(), 40))
    p.setPen(QtGui.QPen(QtGui.QColor(c.red(), c.green(), c.blue(), 110), 1))
    p.drawRoundedRect(2, 2, size - 4, size - 4, size // 7, size // 7)
    p.setPen(c)
    p.setFont(QtGui.QFont("Segoe UI Symbol", size // 3))
    p.drawText(pm.rect(), Qt.AlignCenter, symbol)
    p.end()
    return pm


def make_icon(color="#4f8cff"):
    pm = QtGui.QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 16, 16)
    p.setPen(QtGui.QColor("white"))
    p.setFont(QtGui.QFont("Segoe UI", 26, QtGui.QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "AI")
    p.end()
    return QtGui.QIcon(pm)


class Poller(QtCore.QThread):
    got = QtCore.Signal(dict)
    down = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.ev = 0
        self.alive = True

    def run(self):
        while self.alive:
            try:
                r = client.call({"op": "state", "ev_since": self.ev}, timeout=4)
                self.ev = r.get("ev_n", self.ev)
                self.got.emit(r)
            except Exception as e:
                self.down.emit(str(e))
            for _ in range(10):
                if not self.alive:
                    return
                self.msleep(100)


class Bar(W.QFrame):
    def __init__(self):
        super().__init__()
        self.f, self.color = 0.0, "#34c38f"
        self.marker = None

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rtl = self.layoutDirection() == Qt.RightToLeft
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#262b36"))
        p.drawRoundedRect(0, 0, w, h, 4, 4)
        if self.f > 0:
            p.setBrush(QtGui.QColor(self.color))
            fw = max(h, w * self.f)
            p.drawRoundedRect(QtCore.QRectF(w - fw if rtl else 0, 0, fw, h), 4, 4)
        if self.marker is not None:
            x = w * self.marker
            x = w - x if rtl else x
            p.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 2))
            p.drawLine(QtCore.QPointF(x, -1), QtCore.QPointF(x, h + 1))


class Gauge(W.QWidget):
    """caption + status word, a thin bar (blue tick = the limit you set), numbers."""
    def __init__(self, caption):
        super().__init__()
        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(4)
        row = W.QHBoxLayout()
        self.cap = W.QLabel(caption)
        self.cap.setObjectName("big")
        self.word = W.QLabel("")
        row.addWidget(self.cap)
        row.addStretch(1)
        row.addWidget(self.word)
        self.bar = Bar()
        self.bar.setFixedHeight(8)
        self.num = W.QLabel("")
        self.num.setObjectName("muted")
        self.num.setLayoutDirection(Qt.LeftToRight)
        self.num.setAlignment(Qt.AlignRight)
        lay.addLayout(row)
        lay.addWidget(self.bar)
        lay.addWidget(self.num)

    def set(self, used, total, num_text, marker=None):
        f = max(0.0, min(1.0, used / total if total else 0))
        color, word = ("#34c38f", "") if f < 0.6 else ("#f5a524", "עמוס") if f < 0.85 else ("#f0506e", "כמעט מלא")
        self.word.setText(word)
        self.word.setStyleSheet("font-weight:600; color:%s;" % color)
        self.num.setText(num_text)
        self.bar.f, self.bar.color = f, color
        self.bar.marker = (marker / total) if (marker and total) else None
        self.bar.update()


class QueueTable(W.QTableWidget):
    COLS = ["#", "סוג", "עבודה", "ביקש", "מצב", "זמן", "RAM", "פרטים"]
    reorder = QtCore.Signal(list, int)

    def __init__(self):
        super().__init__(0, len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(36)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(W.QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)
        for i, wd in enumerate((34, 104, 128, 66, 58, 50, 66)):
            self.setColumnWidth(i, wd)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.job_ids, self.queued_ids = [], []

    def selected_ids(self):
        return [self.job_ids[r] for r in sorted({i.row() for i in self.selectedIndexes()}) if r < len(self.job_ids)]

    def dropEvent(self, e):
        row = self.rowAt(e.position().toPoint().y())
        moved = [i for i in self.selected_ids() if i in self.queued_ids]
        if not moved or e.source() is not self:
            e.ignore()
            return
        rest = [i for i in self.queued_ids if i not in moved]
        if row < 0 or row >= len(self.job_ids):
            at = len(rest)
        else:
            tid = self.job_ids[row]
            if tid in moved:
                e.ignore()
                return
            at = (rest.index(tid) + (1 if self.dropIndicatorPosition() == W.QAbstractItemView.BelowItem else 0)) if tid in rest else 0
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.reorder.emit(moved, at + 1)


HE_FIELD = {"image": "תמונה", "image2": "תמונה שנייה", "instruction": "מה לעשות בתמונה", "out": "קובץ יעד", "ref": "תמונת מקור", "prompt": "תיאור", "scenario": "שם התרחיש",
            "script": "קובץ סקריפט", "outdir": "תיקיית יעד", "raw": "הדגם הכבד", "clean": "הדגם הקל", "jobs": "קובץ רשימה (jobs.json)", "depth": "רמת פירוט", "seed": "Seed",
            "steps": "Steps", "secs": "אורך בשניות", "args": "פרמטרים נוספים", "batch": "קובץ אצווה", "w": "רוחב", "h": "גובה", "megapix": "מגה-פיקסל", "threads": "Threads",
            "res": "רזולוציה", "names": "שמות", "extra": "פרמטרים"}
FILE_FIELDS = {"image", "image2", "ref", "jobs", "script", "raw", "clean", "batch"}


class SubmitDialog(W.QDialog):
    """Secondary and minimal: model type, input file, name. Everything else is defaulted from the job-type file and hidden under 'Advanced'."""
    def __init__(self, parent, types, preselect=None):
        super().__init__(parent)
        self.types = types
        self.setWindowTitle("שליחת עבודה")
        self.setMinimumWidth(560)
        self.setLayoutDirection(Qt.RightToLeft)
        self.lay = W.QVBoxLayout(self)
        self.lay.setSpacing(10)
        note = W.QLabel("בדרך כלל Claude שולח עבודות בעצמו. כאן אפשר לשלוח עבודה ידנית. התוצאה תישמר אוטומטית בתיקיית המודל.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.combo = W.QComboBox()
        for tid, t in sorted(types.items(), key=lambda kv: (kv[1].get("group", ""), kv[0])):
            self.combo.addItem(t.get("he_title") or t.get("title", tid), tid)
        if preselect:
            i = self.combo.findData(preselect)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.form = W.QFormLayout()
        self.form.addRow("סוג", self.combo)
        self.name = W.QLineEdit()
        self.name.setPlaceholderText("שם קצר (לא חובה)")
        self.form.addRow("שם", self.name)
        self.lay.addLayout(self.form)
        self.main_box = W.QWidget()
        self.main_form = W.QFormLayout(self.main_box)
        self.main_form.setContentsMargins(0, 0, 0, 0)
        self.lay.addWidget(self.main_box)
        self.adv_btn = W.QPushButton("אפשרויות מתקדמות  ▾")
        self.adv_btn.setObjectName("tool")
        self.adv_btn.setCheckable(True)
        self.lay.addWidget(self.adv_btn, 0, Qt.AlignRight)
        self.adv_box = W.QWidget()
        self.adv_form = W.QFormLayout(self.adv_box)
        self.adv_form.setContentsMargins(0, 0, 0, 0)
        self.adv_box.setVisible(False)
        self.adv_btn.toggled.connect(self.adv_box.setVisible)
        self.lay.addWidget(self.adv_box)
        self.where = W.QLabel("")
        self.where.setObjectName("muted")
        self.where.setWordWrap(True)
        self.lay.addWidget(self.where)
        row = W.QHBoxLayout()
        ok = W.QPushButton("הוסף לתור")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        no = W.QPushButton("ביטול")
        no.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(no)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.edits = {}
        self.combo.currentIndexChanged.connect(self.rebuild)
        self.rebuild()

    @staticmethod
    def _clear(form):
        while form.rowCount():
            form.removeRow(0)

    def rebuild(self):
        self._clear(self.main_form)
        self._clear(self.adv_form)
        self.edits = {}
        tid = self.combo.currentData()
        t = self.types[tid]
        self.where.setText("התוצאה תישמר ב: output\\%s\\<תאריך>_<שם>\\" % (t.get("output_dir") or tid))
        for k, spec in (t.get("params") or {}).items():
            d = spec.get("default") if isinstance(spec, dict) else spec
            req = isinstance(spec, dict) and spec.get("required")
            e = W.QLineEdit("" if d is None else (json.dumps(d) if isinstance(d, (list, dict)) else str(d)))
            e.setLayoutDirection(Qt.LeftToRight)
            row = W.QHBoxLayout()
            row.addWidget(e, 1)
            if k in FILE_FIELDS:
                b = W.QPushButton("בחר…")
                b.setObjectName("tool")
                b.clicked.connect(lambda _=False, ed=e: self.browse(ed))
                row.addWidget(b)
            (self.main_form if req else self.adv_form).addRow(HE_FIELD.get(k, k) + (" *" if req else ""), row)
            self.edits[k] = e
        if tid == "custom":
            e = W.QLineEdit()
            e.setLayoutDirection(Qt.LeftToRight)
            e.setPlaceholderText("python script.py --x 1")
            self.main_form.addRow("פקודה *", e)
            self.edits["__cmd"] = e
        self.ram = W.QDoubleSpinBox()
        self.ram.setRange(0, 64)
        self.ram.setSuffix(" GB RAM")
        self.ram.setSpecialValueText("אוטומטי")
        self.vram = W.QDoubleSpinBox()
        self.vram.setRange(0, 16)
        self.vram.setSuffix(" GB GPU")
        self.vram.setSpecialValueText("אוטומטי")
        self.adv_form.addRow("משאבים", self.ram)
        self.adv_form.addRow("", self.vram)
        self.first = W.QCheckBox("להריץ ראשונה")
        self.adv_form.addRow("", self.first)

    def browse(self, ed):
        p, _ = W.QFileDialog.getOpenFileName(self, "בחר קובץ", ed.text())
        if p:
            ed.setText(p)

    def request(self):
        tid = self.combo.currentData()
        params = {}
        for k, e in self.edits.items():
            v = e.text().strip()
            if k == "__cmd" or not v:
                continue
            try:
                params[k] = json.loads(v) if v[:1] in "[{" or v.lstrip("-").replace(".", "", 1).isdigit() else v
            except ValueError:
                params[k] = v
        est = {}
        if self.ram.value() > 0:
            est["ram_gb"] = self.ram.value()
        if self.vram.value() > 0:
            est["vram_gb"] = self.vram.value()
        req = dict(op="submit", type=tid, params=params, name=self.name.text().strip() or None, requester="owner", est=est or None, next=self.first.isChecked())
        if tid == "custom":
            import shlex
            req["cmd"] = shlex.split(self.edits["__cmd"].text(), posix=False)
        return req


class AdvancedDialog(W.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("מתקדם")
        self.resize(760, 560)
        self.setLayoutDirection(Qt.RightToLeft)
        lay = W.QVBoxLayout(self)
        for key, label in (("affinity", "לקבץ עבודות שמשתמשות באותו מודל (חוסך זמן טעינה)"), ("backfill", "לתת לעבודה קטנה לעקוף עבודה גדולה שמחכה"),
                           ("emergency_suspend", "כשהמחשב בלחץ: להקפיא את העבודה האחרונה שהתחילה"), ("suspend_on_pause", "״עצור הכול״ מקפיא גם עבודות שכבר רצות"),
                           ("toast", "הודעה של Windows כשעבודה מסתיימת")):
            c = W.QCheckBox(label)
            c.setChecked(bool(parent.state and parent.state["flags"].get(key)))
            c.toggled.connect(lambda on, k=key: parent.api({"op": "limits", "flags": {k: on}}))
            lay.addWidget(c)
        h = W.QLabel("יומן")
        h.setObjectName("h2")
        lay.addWidget(h)
        log = W.QPlainTextEdit()
        log.setReadOnly(True)
        log.setLayoutDirection(Qt.LeftToRight)
        log.setPlainText(parent.log_text)
        lay.addWidget(log, 1)
        row = W.QHBoxLayout()
        b = W.QPushButton("פתח את תיקיית הפלט")
        b.clicked.connect(lambda: os.startfile(parent.output_root))
        row.addWidget(b)
        b = W.QPushButton("פתח את תיקיית הנתונים")
        b.clicked.connect(lambda: os.startfile(str(paths.HOME)))
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)


class Main(W.QMainWindow):
    def __init__(self, tray=True, model=None):
        super().__init__()
        self.setWindowTitle("מנהל העבודות של ה-AI")
        self.setWindowIcon(make_icon())
        self.resize(1280, 800)
        self.state = None
        self.types = {}
        self.output_root = str(paths.ROOT / "output")
        self.models = []
        self.sel_model = model
        self.hist_rev = -1
        self.quitting = False
        self.building = False
        self.last_status = None
        self.files_sig = None
        self.log_text = ""
        self.thumb_cache = {}
        self.hist_jobs = []
        self._build()
        self.tray = None
        if tray and W.QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()
        self.settings = QtCore.QSettings("ai-broker", "gui3")
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        self.poller = Poller()
        self.poller.got.connect(self.on_state)
        self.poller.down.connect(self.on_down)
        self.poller.start()
        self.load_types()
        t = QtCore.QTimer(self)
        t.timeout.connect(self.refresh_files)
        t.start(3000)

    # ------------------------------------------------------------ build
    def _panel(self):
        f = W.QFrame()
        f.setObjectName("panel")
        return f

    def _build(self):
        root = W.QWidget()
        root.setObjectName("page")
        self.setCentralWidget(root)
        v = W.QVBoxLayout(root)
        v.setContentsMargins(18, 14, 18, 8)
        v.setSpacing(12)
        head = W.QHBoxLayout()
        self.dot = W.QLabel("")
        self.dot.setFixedSize(14, 14)
        col = W.QVBoxLayout()
        col.setSpacing(0)
        self.h_title = W.QLabel("מתחבר…")
        self.h_title.setObjectName("h1")
        self.h_sub = W.QLabel("")
        self.h_sub.setObjectName("muted")
        col.addWidget(self.h_title)
        col.addWidget(self.h_sub)
        head.addWidget(self.dot, 0, Qt.AlignVCenter)
        head.addLayout(col)
        head.addStretch(1)
        self.play = W.QPushButton("אני משחק / מקליט")
        self.play.setObjectName("bigplay")
        self.play.setCheckable(True)
        self.play.setToolTip("כשזה דלוק, עבודות GPU מחכות ועבודות GPU שרצות מוקפאות, כדי שהמשחק או ההקלטה לא יגמגמו")
        self.play.clicked.connect(lambda on: self.api({"op": "playing", "on": on}))
        self.pause = W.QPushButton("עצור הכול")
        self.pause.setObjectName("bigpause")
        self.pause.setCheckable(True)
        self.pause.setToolTip("שום עבודה חדשה לא מתחילה עד שתמשיך")
        self.pause.clicked.connect(lambda on: self.api({"op": "pause"} if on else {"op": "resume"}))
        sub = W.QPushButton("שליחת עבודה…")
        sub.clicked.connect(lambda: self.open_submit())
        adv = W.QPushButton("מתקדם")
        adv.clicked.connect(self.open_advanced)
        for b in (self.play, self.pause, sub, adv):
            head.addWidget(b)
        v.addLayout(head)
        split = W.QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        v.addWidget(split, 1)
        mp = self._panel()
        ml = W.QVBoxLayout(mp)
        ml.setContentsMargins(8, 12, 8, 8)
        t = W.QLabel("  מודלים ותוצאות")
        t.setObjectName("h2")
        ml.addWidget(t)
        self.model_list = W.QListWidget()
        self.model_list.setObjectName("models")
        self.model_list.setIconSize(QtCore.QSize(26, 26))
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.model_list.currentRowChanged.connect(self.on_model)
        ml.addWidget(self.model_list, 1)
        mp.setMinimumWidth(200)
        mp.setMaximumWidth(250)
        split.addWidget(mp)
        cs = W.QSplitter(Qt.Vertical)
        cs.setChildrenCollapsible(False)
        top = self._panel()
        tl = W.QVBoxLayout(top)
        tl.setContentsMargins(8, 4, 8, 8)
        self.tabs = W.QTabWidget()
        qw = W.QWidget()
        ql = W.QVBoxLayout(qw)
        ql.setContentsMargins(0, 6, 0, 0)
        tb = W.QHBoxLayout()
        self.btns = {}
        for key, text, tip in (("top", "⇈  הרץ ראשונה", "להקדים לראש התור"), ("up", "▲", "להקדים"), ("down", "▼", "לדחות"), ("hold", "עצור / שחרר", "לעצור או לשחרר את העבודה"),
                               ("cancel", "בטל", "לבטל (אם רצה, תיעצר)")):
            b = W.QPushButton(text)
            b.setObjectName("tool")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.queue_action(k))
            tb.addWidget(b)
            self.btns[key] = b
        tb.addStretch(1)
        hint = W.QLabel("אפשר גם לגרור שורות ממתינות")
        hint.setObjectName("muted")
        tb.addWidget(hint)
        ql.addLayout(tb)
        self.queue = QueueTable()
        self.queue.reorder.connect(lambda ids, pos: self.api({"op": "move", "ids": ids, "to": pos}))
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self.queue_menu)
        ql.addWidget(self.queue, 1)
        self.q_empty = W.QLabel("אין עבודות ברגע זה")
        self.q_empty.setObjectName("muted")
        self.q_empty.setAlignment(Qt.AlignCenter)
        ql.addWidget(self.q_empty)
        self.tabs.addTab(qw, "תור")
        self.hist = W.QTableWidget(0, 7)
        self.hist.setHorizontalHeaderLabels(["#", "סוג", "עבודה", "ביקש", "תוצאה", "זמן", "שיא RAM / GPU"])
        self.hist.verticalHeader().hide()
        self.hist.verticalHeader().setDefaultSectionSize(34)
        self.hist.setAlternatingRowColors(True)
        self.hist.setShowGrid(False)
        self.hist.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.hist.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.hist.horizontalHeader().setStretchLastSection(True)
        for i, wd in enumerate((38, 120, 210, 90, 80, 62)):
            self.hist.setColumnWidth(i, wd)
        self.hist.itemDoubleClicked.connect(self.hist_open)
        self.tabs.addTab(self.hist, "היסטוריה")
        tl.addWidget(self.tabs)
        cs.addWidget(top)
        outp = self._panel()
        ol = W.QVBoxLayout(outp)
        ol.setContentsMargins(12, 10, 12, 10)
        oh = W.QHBoxLayout()
        self.out_title = W.QLabel("תוצאות")
        self.out_title.setObjectName("h2")
        self.out_path = W.QLabel("")
        self.out_path.setObjectName("muted")
        self.out_path.setLayoutDirection(Qt.LeftToRight)
        self.open_btn = W.QPushButton("פתח תיקייה")
        self.open_btn.setObjectName("tool")
        self.open_btn.clicked.connect(self.open_model_folder)
        oh.addWidget(self.out_title)
        oh.addWidget(self.out_path, 1)
        oh.addWidget(self.open_btn)
        ol.addLayout(oh)
        self.files = W.QListWidget()
        self.files.setObjectName("files")
        self.files.setViewMode(W.QListView.IconMode)
        self.files.setIconSize(QtCore.QSize(110, 110))
        self.files.setGridSize(QtCore.QSize(160, 168))
        self.files.setResizeMode(W.QListView.Adjust)
        self.files.setMovement(W.QListView.Static)
        self.files.setWordWrap(True)
        self.files.setUniformItemSizes(True)
        self.files.itemDoubleClicked.connect(lambda it: os.startfile(it.data(Qt.UserRole)))
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        ol.addWidget(self.files, 1)
        self.files_empty = W.QLabel("")
        self.files_empty.setObjectName("muted")
        self.files_empty.setAlignment(Qt.AlignCenter)
        ol.addWidget(self.files_empty)
        cs.addWidget(outp)
        cs.setSizes([300, 400])
        split.addWidget(cs)
        rp = self._panel()
        rl = W.QVBoxLayout(rp)
        rl.setContentsMargins(16, 12, 16, 12)
        t = W.QLabel("משאבים")
        t.setObjectName("h2")
        rl.addWidget(t)
        self.g_ram, self.g_gpu, self.g_disk, self.g_cpu = Gauge("RAM"), Gauge("GPU (VRAM)"), Gauge("דיסק"), Gauge("CPU")
        for g in (self.g_ram, self.g_gpu, self.g_disk, self.g_cpu):
            rl.addWidget(g)
        t = W.QLabel("מגבלות (רכות, אפשר לשנות תוך כדי)")
        t.setObjectName("h2")
        t.setContentsMargins(0, 8, 0, 0)
        rl.addWidget(t)
        self.sl = {}
        for key, label, lo, hi in (("ram_gb", "RAM ל-AI", 4, 62), ("vram_gb", "GPU ל-AI", 2, 16), ("max_jobs", "עבודות במקביל", 1, 8), ("reserve_ram_gb", "RAM שנשאר פנוי", 0, 24)):
            row = W.QHBoxLayout()
            lab = W.QLabel(label)
            s = W.QSlider(Qt.Horizontal)
            s.setLayoutDirection(Qt.LeftToRight)
            s.setRange(lo, hi)
            val = W.QLabel("")
            val.setMinimumWidth(52)
            val.setStyleSheet("font-weight:600;")
            s.valueChanged.connect(lambda x, l=val, k=key: l.setText(("%d GB" % x) if k != "max_jobs" else str(x)))
            s.sliderReleased.connect(lambda k=key, sl=s: self.set_limit(k, sl.value()))
            row.addWidget(lab, 2)
            row.addWidget(s, 3)
            row.addWidget(val)
            rl.addLayout(row)
            self.sl[key] = (s, val)
        rl.addStretch(1)
        rp.setMinimumWidth(270)
        rp.setMaximumWidth(320)
        split.addWidget(rp)
        split.setSizes([220, 760, 290])
        self.sb = W.QLabel("")
        self.statusBar().addWidget(self.sb, 1)

    def _build_tray(self):
        self.tray = W.QSystemTrayIcon(make_icon(), self)
        m = W.QMenu()
        m.addAction("פתח את החלון", self.show_normal)
        m.addAction("עצור / המשך הכול", lambda: self.pause.click())
        m.addAction("אני משחק / מקליט", lambda: self.play.click())
        m.addSeparator()
        m.addAction("סגור את החלון (העבודות ממשיכות)", self.quit_gui)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (W.QSystemTrayIcon.Trigger, W.QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    # ------------------------------------------------------------ actions
    def api(self, req):
        try:
            r = client.call(req, timeout=5)
            if not r.get("ok"):
                self.statusBar().showMessage("שגיאה: " + str(r.get("error")), 6000)
            return r
        except Exception as e:
            self.statusBar().showMessage("אין חיבור לשירות: %s" % e, 6000)

    def set_limit(self, key, v):
        if not self.building:
            self.api({"op": "limits", "set": {key: v}})

    def queue_action(self, key):
        ids = self.queue.selected_ids()
        jobs = {j["id"]: j for j in (self.state or {}).get("running", []) + (self.state or {}).get("queued", [])}
        qs = [i for i in ids if i in self.queue.queued_ids]
        if key in ("top", "up", "down"):
            if qs:
                self.api({"op": "move", "ids": qs, "to": key})
        elif key == "hold":
            for i in ids:
                j = jobs.get(i)
                if not j:
                    continue
                paused = j.get("held") if j["state"] == "queued" else j.get("suspended")
                self.api({"op": "job_resume" if paused else "job_pause", "id": i})
        elif key == "cancel" and ids:
            if W.QMessageBox.question(self, "לבטל?", "לבטל %d עבודות? עבודה שרצה תיעצר." % len(ids)) == W.QMessageBox.Yes:
                for i in ids:
                    self.api({"op": "cancel", "id": i})

    def queue_menu(self, pos):
        if not self.queue.selected_ids():
            return
        m = W.QMenu(self)
        for key, text in (("top", "הרץ ראשונה"), ("up", "הקדם"), ("down", "דחה"), ("hold", "עצור / שחרר"), ("cancel", "בטל")):
            m.addAction(text, lambda k=key: self.queue_action(k))
        m.exec(self.queue.viewport().mapToGlobal(pos))

    def open_submit(self, preselect=None):
        if not self.types:
            return
        dlg = SubmitDialog(self, self.types, preselect)
        if dlg.exec() == W.QDialog.Accepted:
            r = self.api(dlg.request())
            if r and r.get("ok"):
                self.statusBar().showMessage("נוספה עבודה מספר %d" % r["id"], 5000)

    def open_advanced(self):
        AdvancedDialog(self).exec()

    # ------------------------------------------------------------ models and output
    def load_types(self):
        r = self.api({"op": "types"})
        if not r or not r.get("ok"):
            return
        self.types = r["types"]
        self.output_root = r.get("output_root", self.output_root)
        groups = {}
        for tid, t in self.types.items():
            od = t.get("output_dir") or tid
            g = groups.setdefault(od, dict(dir=od, title=t.get("he_title") or t.get("title"), sym=SYM.get(t.get("icon"), "•"), color=t.get("color", "#78909c"), tids=[]))
            g["tids"].append(tid)
        names = {"blender": "עבודות Blender", "tripo_shape": "דגם 3D (TripoSG)", "step1x_shape": "דגם 3D (Step1X)", "blender_bake": "אפיית פרטים", "qwen_edit": "עריכת תמונה (Qwen)", "zimage": "תמונה מטקסט (Z-Image)", "music": "מוזיקה", "sound": "צלילים", "scripts": "סקריפטים", "other": "אחר", "godot_test": "בדיקות משחק"}
        self.models = []
        for od, g in sorted(groups.items(), key=lambda kv: (self.types[kv[1]["tids"][0]].get("group", ""), kv[0])):
            g["title"] = names.get(od, g["title"])
            self.models.append(g)
        self.fill_models()

    def count_outputs(self, od):
        try:
            return sum(1 for x in (Path(self.output_root) / od).iterdir() if x.is_dir())
        except OSError:
            return 0

    def fill_models(self):
        cur = self.sel_model
        self.model_list.blockSignals(True)
        self.model_list.clear()
        it = W.QListWidgetItem("  הכול")
        it.setData(Qt.UserRole, None)
        it.setIcon(QtGui.QIcon(symbol_pixmap("▤", "#aeb6c7", 52)))
        self.model_list.addItem(it)
        for g in self.models:
            n = self.count_outputs(g["dir"])
            it = W.QListWidgetItem("  %s%s" % (g["title"], ("   (%d)" % n) if n else ""))
            it.setData(Qt.UserRole, g["dir"])
            it.setIcon(QtGui.QIcon(symbol_pixmap(g["sym"], g["color"], 52)))
            self.model_list.addItem(it)
        sel = 0
        for i in range(self.model_list.count()):
            if self.model_list.item(i).data(Qt.UserRole) == cur:
                sel = i
        self.model_list.setCurrentRow(sel)
        self.model_list.blockSignals(False)
        self.on_model(sel)

    def on_model(self, row):
        if row < 0:
            return
        self.sel_model = self.model_list.item(row).data(Qt.UserRole)
        self.files_sig = None
        self.refresh_files()

    def model_folder(self):
        return Path(self.output_root) / self.sel_model if self.sel_model else Path(self.output_root)

    def open_model_folder(self):
        d = self.model_folder()
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    def scan_files(self, limit=150):
        out = []
        base = self.model_folder()
        if base.is_dir():
            for root, _dirs, names in os.walk(base):
                for n in names:
                    if n in HIDDEN_FILES:
                        continue
                    fp = Path(root) / n
                    try:
                        st = fp.stat()
                    except OSError:
                        continue
                    out.append((st.st_mtime, st.st_size, fp))
        out.sort(key=lambda x: -x[0])
        return out[:limit]

    def thumb(self, fp, mtime):
        key = (str(fp), mtime)
        if key in self.thumb_cache:
            return self.thumb_cache[key]
        ext = fp.suffix.lower()
        icon = None
        if ext in IMG and fp.stat().st_size < 25e6:
            img = QtGui.QImage(str(fp))
            if not img.isNull():
                icon = QtGui.QIcon(QtGui.QPixmap.fromImage(img.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        if icon is None:
            sym, col = KIND.get(ext, ("▫", "#8b93a5"))
            icon = QtGui.QIcon(symbol_pixmap(sym, col, 110))
        if len(self.thumb_cache) > 400:
            self.thumb_cache.clear()
        self.thumb_cache[key] = icon
        return icon

    def refresh_files(self):
        if not self.models:
            return
        g = next((m for m in self.models if m["dir"] == self.sel_model), None)
        self.out_title.setText(("תוצאות: " + g["title"]) if g else "כל התוצאות")
        self.out_path.setText(str(self.model_folder()))
        files = self.scan_files()
        sig = tuple((str(f[2]), f[0]) for f in files)
        if sig == self.files_sig:
            return
        self.files_sig = sig
        self.files.setUpdatesEnabled(False)
        self.files.clear()
        for mt, size, fp in files:
            when = time.strftime("%d/%m %H:%M", time.localtime(mt))
            name = fp.name if len(fp.name) < 22 else fp.name[:19] + "…"
            it = W.QListWidgetItem(self.thumb(fp, mt), "%s\n%s  •  %s" % (name, when, fmt_size(size)))
            it.setData(Qt.UserRole, str(fp))
            it.setToolTip("%s\n%s" % (fp, fp.parent.name))
            self.files.addItem(it)
        self.files.setUpdatesEnabled(True)
        self.files_empty.setText("עוד אין תוצאות לסוג הזה. כשעבודה תסתיים, הקבצים יופיעו כאן.")
        self.files_empty.setVisible(not files)
        for i in range(1, self.model_list.count()):
            od = self.model_list.item(i).data(Qt.UserRole)
            gm = next((m for m in self.models if m["dir"] == od), None)
            if gm:
                n = self.count_outputs(od)
                self.model_list.item(i).setText("  %s%s" % (gm["title"], ("   (%d)" % n) if n else ""))

    def files_menu(self, pos):
        it = self.files.itemAt(pos)
        if not it:
            return
        fp = it.data(Qt.UserRole)
        m = W.QMenu(self)
        m.addAction("פתח", lambda: os.startfile(fp))
        m.addAction("פתח את תיקיית העבודה", lambda: os.startfile(str(Path(fp).parent)))
        m.addAction("העתק נתיב", lambda: W.QApplication.clipboard().setText(fp))
        m.exec(self.files.viewport().mapToGlobal(pos))

    def hist_open(self, item):
        r = item.row()
        if r < len(self.hist_jobs) and self.hist_jobs[r].get("outdir") and os.path.isdir(self.hist_jobs[r]["outdir"]):
            os.startfile(self.hist_jobs[r]["outdir"])

    # ------------------------------------------------------------ state
    def on_down(self, msg):
        self.set_head("#8b93a5", "השירות לא רץ", "הפעל מחדש עם AI_Broker.bat")

    def set_head(self, color, title, sub):
        self.dot.setStyleSheet("background:%s; border-radius:7px;" % color)
        self.h_title.setText(title)
        self.h_sub.setText(sub)

    def type_info(self, tid):
        t = self.types.get(tid, {})
        return SYM.get(t.get("icon"), "•"), t.get("color", "#78909c"), t.get("he_title") or t.get("title") or tid

    def on_state(self, s):
        first = self.state is None
        self.state = s
        sy, lim = s["sys"], s["limits"]
        used = sy["ram_total"] - sy["ram_avail"]
        self.g_ram.set(used, sy["ram_total"], "%.0f / %.0f GB" % (used, sy["ram_total"]), marker=lim["ram_gb"])
        self.g_gpu.set(sy["gpu_used"], sy["gpu_total"], "%.1f / %.0f GB" % (sy["gpu_used"], sy["gpu_total"]), marker=lim["vram_gb"])
        self.g_disk.set(sy["disk"], 100, "%.0f%% עסוק" % sy["disk"])
        self.g_cpu.set(sy["cpu"], 100, "%.0f%%" % sy["cpu"])
        nrun, nq = len(s["running"]), len(s["queued"])
        counts = "רצות %d, ממתינות %d" % (nrun, nq) if (nrun or nq) else "אין עבודות כרגע"
        st = s["status"]
        f = used / sy["ram_total"]
        if st == "BRAKE":
            self.set_head("#f0506e", "המחשב בלחץ, עצרתי הכול", "מעט RAM פנוי. עבודות חדשות לא יתחילו עד שיירגע. " + counts)
        elif st == "PLAYING":
            self.set_head("#f0506e", "אתה משחק / מקליט", "עבודות GPU מחכות. " + counts)
        elif st == "PAUSED":
            self.set_head("#f5a524", "הכול מושהה", "שום עבודה חדשה לא מתחילה. " + counts)
        elif f < 0.7:
            self.set_head("#34c38f", "מנהל העבודות", counts)
        elif f < 0.88:
            self.set_head("#f5a524", "מנהל העבודות", counts + "   •   RAM עמוס")
        else:
            self.set_head("#f0506e", "מנהל העבודות", counts + "   •   RAM כמעט מלא")
        self.play.setChecked(s["playing"])
        self.pause.setChecked(s["paused"])
        self.pause.setText("המשך" if s["paused"] else "עצור הכול")
        self.building = True
        for k, (sl, val) in self.sl.items():
            if not sl.isSliderDown():
                sl.setValue(int(round(lim[k])))
                val.setText(("%d GB" % lim[k]) if k != "max_jobs" else str(int(lim[k])))
        self.building = False
        self.fill_queue(s)
        self.sb.setText("RAM פנוי: %.0f GB      Commit פנוי: %.0f GB%s" % (sy["ram_avail"], sy["commit_avail"], ("      נעילת GPU: " + {"ours": "אצל ה-broker", "foreign": "אצל תוכנה אחרת"}.get(s["lock"], s["lock"])) if s["lock"] != "none" else ""))
        if self.tray and st != self.last_status:
            self.tray.setIcon(make_icon({"ACTIVE": "#34c38f", "PAUSED": "#f5a524", "PLAYING": "#f0506e", "BRAKE": "#f0506e"}[st]))
            self.last_status = st
        for n, ts, text in s.get("events", []):
            self.log_text += "%s  %s\n" % (time.strftime("%H:%M:%S", time.localtime(ts)), text)
            if self.tray and not first and " -> " in text and text.startswith("#"):
                self.tray.showMessage("AI Broker", text[:150], W.QSystemTrayIcon.Information, 6000)
        self.log_text = self.log_text[-60000:]
        if s["hist_rev"] != self.hist_rev:
            self.hist_rev = s["hist_rev"]
            self.fill_history()
            self.files_sig = None
            self.refresh_files()

    def fill_queue(self, s):
        if W.QApplication.mouseButtons() & Qt.LeftButton:
            return
        q = self.queue
        sel = set(q.selected_ids())
        vs = q.verticalScrollBar().value()
        jobs = s["running"] + s["queued"]
        q.setUpdatesEnabled(False)
        q.setRowCount(len(jobs))
        q.job_ids = [j["id"] for j in jobs]
        q.queued_ids = [j["id"] for j in s["queued"]]
        for r, j in enumerate(jobs):
            sym, color, ttl = self.type_info(j["type"])
            st = "held" if j["state"] == "queued" and j.get("held") else ("paused" if j.get("suspended") else j["state"])
            if j["state"] in ("running", "paused"):
                tm, ram, det = fmt_dur(j.get("elapsed", 0)), ltr("%.1f GB" % j.get("cur_ws", 0)), ltr("GPU %.1f GB" % j["cur_vram"]) if j.get("cur_vram") else ""
            else:
                tm, ram, det = fmt_dur(time.time() - j["submitted"]), ltr("~%.0f GB" % j["est_ram"]), ("עצרת אותה בעצמך" if j.get("held") else he_reason(j.get("reason", "")))
            vals = [str(j["id"]), "%s  %s" % (sym, ttl), j["name"], j["requester"], STATE_HE.get(st, st), tm, ram, det]
            for c, v in enumerate(vals):
                it = q.item(r, c) or W.QTableWidgetItem()
                it.setText(v)
                it.setToolTip(v if c in (2, 7) else (("הערכה: " + j["est_source"]) if c == 6 else ""))
                if c == 1:
                    it.setForeground(QtGui.QColor(color))
                elif c == 4:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(st, "#aeb6c7")))
                elif c == 7:
                    it.setForeground(QtGui.QColor("#f5a524" if j["state"] == "queued" and j.get("reason") else "#aeb6c7"))
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if j["state"] == "queued":
                    flags |= Qt.ItemIsDragEnabled
                it.setFlags(flags)
                q.setItem(r, c, it)
            if j["id"] in sel:
                q.selectRow(r)
        q.verticalScrollBar().setValue(vs)
        q.setUpdatesEnabled(True)
        self.q_empty.setVisible(not jobs)
        q.setVisible(bool(jobs))

    def fill_history(self):
        r = self.api({"op": "history", "limit": 60})
        if not r or not r.get("ok"):
            return
        jobs = self.hist_jobs = r["jobs"]
        h = self.hist
        h.setRowCount(len(jobs))
        for i, j in enumerate(jobs):
            sym, color, ttl = self.type_info(j["type"])
            dur = (j.get("finished") or 0) - (j.get("started") or j.get("finished") or 0)
            vals = [str(j["id"]), "%s  %s" % (sym, ttl), j["name"], j["requester"], STATE_HE.get(j["state"], j["state"]), fmt_dur(dur),
                    ltr("RAM %.1f GB   GPU %.1f GB" % (j.get("peak_ws") or 0, j.get("peak_vram") or 0))]
            for c, v in enumerate(vals):
                it = W.QTableWidgetItem(v)
                if c == 1:
                    it.setForeground(QtGui.QColor(color))
                if c == 4:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(j["state"], "#aeb6c7")))
                h.setItem(i, c, it)

    # ------------------------------------------------------------ window
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_gui(self):
        self.quitting = True
        self.close()

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        if self.tray and not self.quitting:
            e.ignore()
            self.hide()
            if not self.settings.value("tray_hint"):
                self.tray.showMessage("AI Broker", "החלון הוסתר לאזור ההודעות. העבודות ממשיכות לרוץ.", W.QSystemTrayIcon.Information, 6000)
                self.settings.setValue("tray_hint", True)
            return
        self.poller.alive = False
        self.poller.wait(2000)
        W.QApplication.quit()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    arg = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
    shot, model, tab, size = arg("--screenshot"), arg("--model"), int(arg("--tab", 0)), arg("--size")
    app = W.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.RightToLeft)
    f = app.font()
    f.setPointSize(11)
    app.setFont(f)
    app.setStyleSheet(QSS)
    try:
        client.start_daemon()
    except Exception as e:
        print("could not start the broker:", e)
    win = Main(tray=("--no-tray" not in argv and shot is None), model=model)
    if size:
        win.resize(*[int(x) for x in size.lower().split("x")])
    win.tabs.setCurrentIndex(tab)
    win.show()
    if shot:
        def grab():
            win.grab().save(shot)
            print("saved", shot)
            win.quitting = True
            win.close()
        QtCore.QTimer.singleShot(4000, grab)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
