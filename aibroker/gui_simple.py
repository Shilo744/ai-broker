"""AI Broker window: simple, big, friendly (Hebrew, right-to-left). Cards with pictures instead of tables.
Pages: Now (what runs, what waits, how the computer feels) / Add a job (big picture tiles) / History / Advanced (limits, log).
The window is only a client of the broker service: closing it never stops the queue.
  python -m aibroker.gui [--screenshot out.png] [--page 0..3] [--size 1280x860] [--no-tray]"""
import json
import os
import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets as W
from PySide6.QtCore import Qt

from . import client, paths

QSS = """
* { font-family: 'Segoe UI'; font-size: 11.5pt; color: #e6e8ee; }
QMainWindow, QDialog, QWidget#page { background: #0f1115; }
QScrollArea { border: none; background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }
QFrame#card { background: #171a21; border: 1px solid #262b36; border-radius: 10px; }
QFrame#tile { background: #171a21; border: 1px solid #262b36; border-radius: 10px; }
QFrame#tile:hover { border-color: #4f8cff; background: #1a1f29; }
QLabel { background: transparent; }
QLabel#h1 { font-size: 18pt; font-weight: 600; } QLabel#h2 { font-size: 13pt; font-weight: 600; padding-top: 10px; color: #aeb6c7; }
QLabel#muted { color: #8b93a5; font-size: 10.5pt; } QLabel#big { font-size: 12.5pt; font-weight: 600; }
QLabel#chip { border: 1px solid #343b4a; border-radius: 8px; padding: 0px 8px; font-size: 9.5pt; color: #8b93a5; }
QPushButton { background: #1c212b; border: 1px solid #2c3340; border-radius: 8px; padding: 8px 16px; font-weight: 500; }
QPushButton:hover { border-color: #4f8cff; background: #212836; }
QPushButton#nav { border: none; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; font-size: 12.5pt; padding: 10px 22px; color: #8b93a5; }
QPushButton#nav:hover { color: #e6e8ee; background: transparent; } QPushButton#nav:checked { color: #ffffff; border-bottom: 2px solid #4f8cff; }
QPushButton#primary { background: #4f8cff; border-color: #4f8cff; color: white; } QPushButton#primary:hover { background: #3f7bef; }
QPushButton#round { border-radius: 6px; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; font-size: 11pt; }
QPushButton#bigplay, QPushButton#bigpause { padding: 10px 22px; font-size: 12pt; font-weight: 600; }
QPushButton#bigplay:checked { background: #f0506e; border-color: #f0506e; color: white; }
QPushButton#bigpause:checked { background: #f5a524; border-color: #f5a524; color: #1a1300; }
QProgressBar { border: none; border-radius: 3px; background: #262b36; max-height: 5px; min-height: 5px; } QProgressBar::chunk { background: #4f8cff; border-radius: 3px; }
QLineEdit, QSpinBox, QDoubleSpinBox { background: #12151b; border: 1px solid #2c3340; border-radius: 8px; padding: 7px 10px; selection-background-color: #4f8cff; }
QLineEdit:focus { border-color: #4f8cff; }
QPlainTextEdit { background: #0b0d11; color: #c5cad6; border: 1px solid #262b36; border-radius: 8px; font-family: Consolas; font-size: 10pt; padding: 8px; }
QSlider::groove:horizontal { height: 4px; background: #2c3340; border-radius: 2px; } QSlider::sub-page:horizontal { background: #4f8cff; border-radius: 2px; }
QSlider::handle:horizontal { background: #e6e8ee; width: 14px; margin: -5px 0; border-radius: 7px; }
QCheckBox { spacing: 10px; padding: 4px 0; } QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #3a4252; border-radius: 5px; background: #12151b; }
QCheckBox::indicator:checked { background: #4f8cff; border-color: #4f8cff; }
QStatusBar { background: #0f1115; border-top: 1px solid #262b36; } QStatusBar QLabel { padding: 0 14px; font-size: 10pt; color: #8b93a5; }
QScrollBar:vertical { background: transparent; width: 10px; } QScrollBar::handle:vertical { background: #2c3340; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QMessageBox { background: #171a21; }
QToolTip { background: #232a37; color: #e6e8ee; border: 1px solid #343b4a; padding: 5px; }
"""

EMOJI = "Segoe UI Emoji"


def fmt_dur(s):
    s = int(s or 0)
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def he_reason(r):
    if not r:
        return "מתחילה תיכף"
    table = (("RAM budget", "אין כרגע מספיק זיכרון פנוי לעבודה הזו"), ("VRAM budget", "כרטיס המסך עסוק, מחכה שיתפנה מקום"),
             ("free RAM", "הזיכרון של המחשב נמוך, מחכה שיתפנה"), ("free commit", "הזיכרון של המחשב נמוך, מחכה שיתפנה"),
             ("paused", "הכול מושהה"), ("I am playing", "אתה משחק, אז עבודות כרטיס המסך מחכות"), ("held", "עצרת אותה בעצמך"),
             ("max concurrent", "כבר רצות הרבה עבודות במקביל"), ("another", "עבודה מאותו סוג כבר רצה"), ("GPU lock", "תוכנה אחרת משתמשת בכרטיס המסך"),
             ("a self-locking", "מצלמים עכשיו את המשחק, מחכה שיסתיים"), ("visual run", "עבודה של כרטיס המסך רצה עכשיו, מחכה לתור"),
             ("BRAKE", "המחשב בלחץ, עצרתי הכול לבטיחות"), ("starvation", "העבודה הראשונה מחכה הרבה זמן, אף אחד לא עוקף אותה"),
             ("waiting for the job", "מחכה לעבודה אחרת שתסתיים"), ("backfill", "מחכה לעבודה שלפניה"))
    for k, v in table:
        if r.startswith(k) or k in r[:24]:
            return v
    return r


SYM = {"🖼️": "✎", "🎨": "✦", "🧊": "⬢", "🗿": "◈", "🛠️": "⚒", "🧱": "▦", "🎵": "♪", "🔊": "♬", "🎮": "▷", "📸": "◎", "🎬": "▶", "🐍": "λ", "⚙️": "⚙"}


def icon_badge(emoji, color, size=64):
    """Flat tinted rounded square with one monochrome symbol (professional, no emoji)."""
    c = QtGui.QColor(color)
    lab = W.QLabel(SYM.get(emoji, "•"))
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet("background: rgba(%d,%d,%d,0.16); border: 1px solid rgba(%d,%d,%d,0.45); border-radius:%dpx; font-family:'Segoe UI Symbol'; font-size:%dpt; color:%s;"
                      % (c.red(), c.green(), c.blue(), c.red(), c.green(), c.blue(), max(8, size // 4), max(10, size // 2 - 4), color))
    return lab


def make_icon(color="#3b82f6"):
    pm = QtGui.QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 18, 18)
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


def chip(text, bg, fg="white"):
    c = W.QLabel(text)
    c.setObjectName("chip")
    c.setStyleSheet("color:%s; border-color:%s;" % (fg, fg))
    c.setAlignment(Qt.AlignCenter)
    return c


def weight_chip(ram):
    if ram >= 20:
        return chip("כבד מאוד", "", "#f0506e")
    if ram >= 8:
        return chip("בינוני", "", "#f5a524")
    return chip("קל", "", "#34c38f")


class Bar(W.QFrame):
    def __init__(self):
        super().__init__()
        self.f, self.color = 0.0, "#34c38f"

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#262b36"))
        p.drawRoundedRect(0, 0, w, h, 4, 4)
        if self.f > 0:
            p.setBrush(QtGui.QColor(self.color))
            fw = max(h, w * self.f)
            x = w - fw if self.layoutDirection() == Qt.RightToLeft else 0
            p.drawRoundedRect(QtCore.QRectF(x, 0, fw, h), 4, 4)


class Gauge(W.QFrame):
    """Compact meter: caption + numbers in one row, a thin bar, one status word."""
    def __init__(self, emoji, caption):
        super().__init__()
        self.setObjectName("card")
        self.setMinimumHeight(86)
        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
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
        lay.addLayout(row)
        lay.addWidget(self.bar)
        lay.addWidget(self.num)

    def set(self, used, total, num_text):
        f = max(0.0, min(1.0, used / total if total else 0))
        self.num.setText(num_text)
        color, word = ("#34c38f", "רגוע") if f < 0.6 else ("#f5a524", "עמוס") if f < 0.85 else ("#f0506e", "כמעט מלא")
        self.word.setText(word)
        self.word.setStyleSheet("font-weight:600; color:%s;" % color)
        self.bar.f, self.bar.color = f, color
        self.bar.update()


class JobCard(W.QFrame):
    """A job as a card: picture, plain name, who asked, what it is doing / why it waits, buttons."""
    def __init__(self, kind, act, types):
        super().__init__()
        self.kind, self.act, self.types = kind, act, types
        self.setObjectName("card")
        self.jid = None
        self.badge = None
        lay = W.QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(16)
        self.num = W.QLabel("")
        self.num.setStyleSheet("font-size:16pt; font-weight:600; color:#5b6578;")
        self.num.setFixedWidth(44)
        self.num.setAlignment(Qt.AlignCenter)
        if kind == "queued":
            lay.addWidget(self.num)
        self.badge_holder = W.QVBoxLayout()
        lay.addLayout(self.badge_holder)
        col = W.QVBoxLayout()
        col.setSpacing(3)
        top = W.QHBoxLayout()
        self.title = W.QLabel("")
        self.title.setObjectName("big")
        self.chipbox = W.QHBoxLayout()
        top.addWidget(self.title)
        top.addLayout(self.chipbox)
        top.addStretch(1)
        self.sub = W.QLabel("")
        self.sub.setObjectName("muted")
        self.line = W.QLabel("")
        self.line.setWordWrap(True)
        col.addLayout(top)
        col.addWidget(self.sub)
        col.addWidget(self.line)
        self.pb = W.QProgressBar()
        self.pb.setRange(0, 0)
        self.pb.setTextVisible(False)
        if kind == "running":
            col.addWidget(self.pb)
        lay.addLayout(col, 1)
        self.btns = W.QHBoxLayout()
        lay.addLayout(self.btns)
        self.b = {}

    def _btn(self, key, text, tip, slot, style="round"):
        b = W.QPushButton(text)
        b.setObjectName(style)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        self.btns.addWidget(b)
        self.b[key] = b
        return b

    def build_buttons(self):
        if self.kind == "queued":
            self._btn("top", "⇈", "להריץ ראשונה", lambda: self.act({"op": "move", "ids": [self.jid], "to": "top"}))
            self._btn("up", "▲", "להקדים בתור", lambda: self.act({"op": "move", "ids": [self.jid], "to": "up"}))
            self._btn("down", "▼", "לדחות בתור", lambda: self.act({"op": "move", "ids": [self.jid], "to": "down"}))
            self._btn("hold", "❚❚", "לעצור עבודה זו", lambda: self.act({"op": "job_resume" if self.held else "job_pause", "id": self.jid}))
        else:
            self._btn("hold", "❚❚", "להשהות עבודה זו", lambda: self.act({"op": "job_resume" if self.susp else "job_pause", "id": self.jid}))
        self._btn("cancel", "✕", "לבטל", lambda: self.act({"op": "cancel", "id": self.jid, "confirm": True}), "round")
        self.b["cancel"].setStyleSheet("color:#f0506e;")

    def update_job(self, j, pos=None):
        first = self.jid is None
        self.jid = j["id"]
        t = self.types.get(j["type"], {})
        self.held = bool(j.get("held"))
        self.susp = bool(j.get("suspended"))
        if first:
            self.badge = icon_badge(t.get("icon", "⚙️"), t.get("color", "#78909c"), 44)
            self.badge_holder.addWidget(self.badge)
            self.build_buttons()
        self.title.setText(t.get("he_title") or j["name"])
        if not self.chipbox.count():
            self.chipbox.addWidget(weight_chip(j["est_ram"]))
        who = "ביקש: %s" % j["requester"]
        self.sub.setText("%s   •   %s" % (j["name"], who) if t.get("he_title") and j["name"] != t.get("title") else who)
        if self.kind == "queued":
            self.num.setText(str(pos))
            self.line.setText(("" + "עצרת אותה בעצמך (לחץ ▶ כדי לשחרר)" if self.held else he_reason(j.get("reason", ""))))
            self.line.setStyleSheet("color:#f5a524;" if j.get("reason") else "color:#34c38f;")
            self.b["hold"].setText("▶" if self.held else "❚❚")
            self.b["hold"].setToolTip("לשחרר עבודה זו" if self.held else "לעצור עבודה זו")
        else:
            state = "מושהית" if self.susp else "עובדת"
            self.line.setText("%s   •   RAM %.1f GB%s" % (state + " " + fmt_dur(j.get("elapsed", 0)), j.get("cur_ws", 0),
                                                                    ("  •  GPU %.1f GB" % j["cur_vram"]) if j.get("cur_vram") else ""))
            self.line.setStyleSheet("color:#c5cad6;")
            self.pb.setVisible(not self.susp)
            self.b["hold"].setText("▶" if self.susp else "❚❚")


class CardList(W.QWidget):
    def __init__(self, make):
        super().__init__()
        self.make = make
        self.lay = W.QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(10)
        self.cards = {}

    def sync(self, items, update):
        ids = [j["id"] for j in items]
        for i in list(self.cards):
            if i not in ids:
                w = self.cards.pop(i)
                self.lay.removeWidget(w)
                w.deleteLater()
        for idx, j in enumerate(items):
            w = self.cards.get(j["id"])
            if w is None:
                w = self.cards[j["id"]] = self.make()
            update(w, j, idx + 1)
            if self.lay.indexOf(w) != idx:
                self.lay.insertWidget(idx, w)


class Tile(W.QFrame):
    clicked = QtCore.Signal()

    def __init__(self, tid, t):
        super().__init__()
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(240, 130)
        self.setToolTip((t.get("notes") or t.get("he_desc") or "") + "\n(%s)" % t.get("title", tid))
        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 14)
        top = W.QHBoxLayout()
        top.addWidget(icon_badge(t.get("icon", "⚙️"), t.get("color", "#78909c"), 44))
        top.addStretch(1)
        top.addWidget(weight_chip(t.get("est", {}).get("ram_gb", 0)), 0, Qt.AlignTop)
        lay.addLayout(top)
        n = W.QLabel(t.get("he_title") or t.get("title", tid))
        n.setObjectName("big")
        n.setWordWrap(True)
        d = W.QLabel(t.get("he_desc") or "")
        d.setObjectName("muted")
        d.setWordWrap(True)
        lay.addWidget(n)
        lay.addWidget(d)
        lay.addStretch(1)
        for c in self.findChildren(W.QLabel):
            c.setAttribute(Qt.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


FILE_FIELDS = {"image", "image2", "ref", "jobs", "script", "raw", "clean", "batch"}
SAVE_FIELDS = {"out", "outdir"}
HE_FIELD = {"image": "תמונה", "image2": "תמונה שנייה (לא חובה)", "instruction": "מה לעשות בתמונה", "out": "איפה לשמור את התוצאה", "ref": "תמונת מקור", "prompt": "תיאור במילים",
            "scenario": "שם התרחיש", "script": "קובץ הסקריפט", "outdir": "תיקיית פלט", "raw": "הדגם הכבד", "clean": "הדגם הקל", "jobs": "קובץ הרשימה (jobs.json)",
            "depth": "רמת פירוט (8 או 9)", "seed": "מספר אקראי", "steps": "צעדים", "secs": "אורך בשניות", "args": "פרמטרים נוספים", "batch": "קובץ אצווה (לא חובה)"}


class JobDialog(W.QDialog):
    def __init__(self, parent, tid, t):
        super().__init__(parent)
        self.t, self.tid, self.edits = t, tid, {}
        self.setWindowTitle(t.get("he_title") or t.get("title", tid))
        self.setMinimumWidth(680)
        self.setLayoutDirection(Qt.RightToLeft)
        lay = W.QVBoxLayout(self)
        lay.setSpacing(12)
        head = W.QHBoxLayout()
        head.addWidget(icon_badge(t.get("icon", "⚙️"), t.get("color", "#78909c"), 48))
        c = W.QVBoxLayout()
        h = W.QLabel(t.get("he_title") or t.get("title", tid))
        h.setObjectName("h1")
        d = W.QLabel(t.get("he_desc") or "")
        d.setObjectName("muted")
        c.addWidget(h)
        c.addWidget(d)
        head.addLayout(c, 1)
        lay.addLayout(head)
        form = W.QFormLayout()
        form.setVerticalSpacing(10)
        self.name = W.QLineEdit()
        self.name.setPlaceholderText("שם לעבודה (לא חובה)")
        form.addRow("שם", self.name)
        for k, spec in (t.get("params") or {}).items():
            d = spec.get("default") if isinstance(spec, dict) else spec
            req = isinstance(spec, dict) and spec.get("required")
            e = W.QLineEdit("" if d is None else (json.dumps(d) if isinstance(d, (list, dict)) else str(d)))
            e.setLayoutDirection(Qt.LeftToRight)
            row = W.QHBoxLayout()
            row.addWidget(e, 1)
            if k in FILE_FIELDS or k in SAVE_FIELDS:
                b = W.QPushButton("בחר…")
                b.clicked.connect(lambda _=False, ed=e, kk=k: self.browse(ed, kk))
                row.addWidget(b)
            form.addRow(HE_FIELD.get(k, k) + (" *" if req else ""), row)
            self.edits[k] = e
        if tid == "custom":
            self.cmd = W.QLineEdit()
            self.cmd.setLayoutDirection(Qt.LeftToRight)
            self.cmd.setPlaceholderText("python script.py --x 1")
            form.addRow("הפקודה *", self.cmd)
        lay.addLayout(form)
        self.more = W.QCheckBox("לקבוע בעצמי כמה משאבים העבודה צריכה (בדרך כלל לא צריך, המערכת לומדת לבד)")
        lay.addWidget(self.more)
        self.est = W.QWidget()
        el = W.QHBoxLayout(self.est)
        self.ram = W.QDoubleSpinBox()
        self.ram.setRange(0, 64)
        self.ram.setSuffix(" GB זיכרון")
        self.vram = W.QDoubleSpinBox()
        self.vram.setRange(0, 16)
        self.vram.setSuffix(" GB כרטיס מסך")
        el.addWidget(self.ram)
        el.addWidget(self.vram)
        self.est.setVisible(False)
        self.more.toggled.connect(self.est.setVisible)
        lay.addWidget(self.est)
        self.first = W.QCheckBox("להריץ אותה ראשונה")
        lay.addWidget(self.first)
        row = W.QHBoxLayout()
        ok = W.QPushButton("הוסף לתור")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        no = W.QPushButton("ביטול")
        no.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(no)
        row.addStretch(1)
        lay.addLayout(row)

    def browse(self, ed, key):
        if key in SAVE_FIELDS:
            p, _ = W.QFileDialog.getSaveFileName(self, "איפה לשמור", ed.text())
        else:
            p, _ = W.QFileDialog.getOpenFileName(self, "בחר קובץ", ed.text())
        if p:
            ed.setText(p)

    def request(self):
        params = {}
        for k, e in self.edits.items():
            v = e.text().strip()
            if v:
                try:
                    params[k] = json.loads(v) if v[:1] in "[{" or v.lstrip("-").replace(".", "", 1).isdigit() else v
                except ValueError:
                    params[k] = v
        est = {}
        if self.more.isChecked():
            if self.ram.value() > 0:
                est["ram_gb"] = self.ram.value()
            if self.vram.value() > 0:
                est["vram_gb"] = self.vram.value()
        req = dict(op="submit", type=self.tid, params=params, name=self.name.text().strip() or None, requester="owner", est=est or None, next=self.first.isChecked())
        if self.tid == "custom":
            import shlex
            req["cmd"] = shlex.split(self.cmd.text(), posix=False)
        return req


class OutputDialog(W.QDialog):
    def __init__(self, parent, jid, title):
        super().__init__(parent)
        self.jid = jid
        self.setWindowTitle("מה העבודה כתבה: " + title)
        self.resize(900, 560)
        lay = W.QVBoxLayout(self)
        self.ed = W.QPlainTextEdit()
        self.ed.setReadOnly(True)
        self.ed.setLayoutDirection(Qt.LeftToRight)
        lay.addWidget(self.ed)
        self.t = QtCore.QTimer(self)
        self.t.timeout.connect(self.refresh)
        self.t.start(1500)
        self.refresh()

    def refresh(self):
        try:
            r = client.call({"op": "tail", "id": self.jid, "bytes": 40000}, timeout=3)
            if r.get("ok") and r["text"] != self.ed.toPlainText():
                bar = self.ed.verticalScrollBar()
                end = bar.value() >= bar.maximum() - 4
                self.ed.setPlainText(r["text"])
                if end:
                    bar.setValue(bar.maximum())
        except Exception:
            pass


class Main(W.QMainWindow):
    def __init__(self, tray=True):
        super().__init__()
        self.setWindowTitle("מנהל העבודות של ה-AI")
        self.setWindowIcon(make_icon())
        self.resize(1180, 780)
        self.state = None
        self.types = {}
        self.hist_rev = -1
        self.quitting = False
        self.building = False
        self.last_status = None
        self._build()
        self.tray = None
        if tray and W.QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()
        self.settings = QtCore.QSettings("ai-broker", "gui2")
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        self.poller = Poller()
        self.poller.got.connect(self.on_state)
        self.poller.down.connect(self.on_down)
        self.poller.start()
        self.load_types()

    # ------------------------------------------------------------ build
    def _scroll(self, inner):
        sa = W.QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(inner)
        return sa

    def _build(self):
        root = W.QWidget()
        root.setObjectName("page")
        self.setCentralWidget(root)
        v = W.QVBoxLayout(root)
        v.setContentsMargins(24, 18, 24, 12)
        v.setSpacing(14)
        # banner
        self.banner = W.QFrame()
        self.banner.setObjectName("card")
        bl = W.QHBoxLayout(self.banner)
        bl.setContentsMargins(22, 16, 22, 16)
        self.b_icon = W.QLabel("")
        self.b_icon.setFixedSize(14, 14)
        bc = W.QVBoxLayout()
        self.b_title = W.QLabel("מתחבר…")
        self.b_title.setObjectName("h1")
        self.b_sub = W.QLabel("")
        self.b_sub.setObjectName("muted")
        self.b_sub.setWordWrap(True)
        bc.addWidget(self.b_title)
        bc.addWidget(self.b_sub)
        bl.addWidget(self.b_icon, 0, Qt.AlignTop)
        self.b_icon.setContentsMargins(0, 0, 0, 0)
        bl.addLayout(bc, 1)
        self.play = W.QPushButton("אני משחק / מקליט")
        self.play.setObjectName("bigplay")
        self.play.setCheckable(True)
        self.play.setCursor(Qt.PointingHandCursor)
        self.play.setToolTip("כשזה דלוק, עבודות שמשתמשות בכרטיס המסך מחכות, כדי שהמשחק או ההקלטה לא יגמגמו")
        self.play.clicked.connect(lambda on: self.api({"op": "playing", "on": on}))
        self.pause = W.QPushButton("עצור הכול")
        self.pause.setObjectName("bigpause")
        self.pause.setCheckable(True)
        self.pause.setCursor(Qt.PointingHandCursor)
        self.pause.setToolTip("שום עבודה חדשה לא תתחיל עד שתמשיך")
        self.pause.clicked.connect(lambda on: self.api({"op": "pause"} if on else {"op": "resume"}))
        bl.addWidget(self.play)
        bl.addWidget(self.pause)
        v.addWidget(self.banner)
        # nav
        nav = W.QHBoxLayout()
        self.navs = []
        self.stack = W.QStackedWidget()
        for i, label in enumerate(("מה קורה עכשיו", "הוסף עבודה", "מה כבר נעשה", "מתקדם")):
            b = W.QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=i: self.go(k))
            nav.addWidget(b)
            self.navs.append(b)
        nav.addStretch(1)
        sw = W.QPushButton("תצוגה מתקדמת")
        sw.setToolTip("לעבור לתצוגה הכהה והמקצועית")
        sw.setCursor(Qt.PointingHandCursor)
        sw.clicked.connect(self.switch_view)
        nav.addWidget(sw)
        v.addLayout(nav)
        v.addWidget(self.stack, 1)
        self.stack.addWidget(self._now_page())
        self.stack.addWidget(self._add_page())
        self.stack.addWidget(self._hist_page())
        self.stack.addWidget(self._adv_page())
        self.go(0)
        sb = self.statusBar()
        self.sb = W.QLabel("")
        sb.addWidget(self.sb, 1)

    def go(self, k):
        self.stack.setCurrentIndex(k)
        sa = self.stack.currentWidget()
        if isinstance(sa, W.QScrollArea):
            sa.verticalScrollBar().setValue(0)
        for i, b in enumerate(self.navs):
            b.setChecked(i == k)

    def _now_page(self):
        inner = W.QWidget()
        lay = W.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        h = W.QLabel("מצב המחשב")
        h.setObjectName("h2")
        lay.addWidget(h)
        row = W.QHBoxLayout()
        self.g_ram = Gauge("", "RAM")
        self.g_vram = Gauge("", "GPU (כרטיס מסך)")
        self.g_disk = Gauge("", "דיסק")
        for g in (self.g_ram, self.g_vram, self.g_disk):
            row.addWidget(g)
        lay.addLayout(row)
        h = W.QLabel("רץ עכשיו")
        h.setObjectName("h2")
        lay.addWidget(h)
        self.run_list = CardList(lambda: JobCard("running", self.act, self.types))
        lay.addWidget(self.run_list)
        self.run_empty = W.QLabel("שום דבר לא רץ כרגע")
        self.run_empty.setObjectName("muted")
        lay.addWidget(self.run_empty)
        h = W.QLabel("ממתין בתור")
        h.setObjectName("h2")
        lay.addWidget(h)
        hint = W.QLabel("אפשר לשנות את הסדר עם החצים בכל כרטיס. ⇈ = להריץ ראשונה.")
        hint.setObjectName("muted")
        lay.addWidget(hint)
        self.q_list = CardList(lambda: JobCard("queued", self.act, self.types))
        lay.addWidget(self.q_list)
        self.q_empty = W.QLabel("התור ריק")
        self.q_empty.setObjectName("muted")
        lay.addWidget(self.q_empty)
        lay.addStretch(1)
        return self._scroll(inner)

    def _add_page(self):
        self.add_inner = W.QWidget()
        self.add_lay = W.QVBoxLayout(self.add_inner)
        self.add_lay.setContentsMargins(0, 0, 8, 0)
        return self._scroll(self.add_inner)

    def _hist_page(self):
        inner = W.QWidget()
        lay = W.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        self.hist_list = CardList(self._make_hist)
        lay.addWidget(self.hist_list)
        self.hist_empty = W.QLabel("עוד לא הסתיימה אף עבודה")
        self.hist_empty.setObjectName("muted")
        lay.addWidget(self.hist_empty)
        lay.addStretch(1)
        return self._scroll(inner)

    def _make_hist(self):
        f = W.QFrame()
        f.setObjectName("card")
        l = W.QHBoxLayout(f)
        l.setContentsMargins(16, 12, 16, 12)
        f.badge = W.QVBoxLayout()
        l.addLayout(f.badge)
        c = W.QVBoxLayout()
        f.t1 = W.QLabel()
        f.t1.setObjectName("big")
        f.t2 = W.QLabel()
        f.t2.setObjectName("muted")
        c.addWidget(f.t1)
        c.addWidget(f.t2)
        l.addLayout(c, 1)
        f.res = W.QLabel()
        f.res.setStyleSheet("font-weight:700;")
        l.addWidget(f.res)
        f.btn = W.QPushButton("מה נכתב")
        l.addWidget(f.btn)
        f.jid = None
        f.made = False
        return f

    def _adv_page(self):
        inner = W.QWidget()
        lay = W.QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        h = W.QLabel("כמה מותר ל-AI לקחת מהמחשב")
        h.setObjectName("h2")
        lay.addWidget(h)
        note = W.QLabel("אלה מגבלות רכות: המערכת מכניסה כמה שיותר עבודות בתוכן. אפשר לשנות בזמן שהכול רץ.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.sl = {}
        for key, label, lo, hi in (("ram_gb", "זיכרון (RAM) לכל עבודות ה-AI יחד", 4, 62), ("vram_gb", "כרטיס מסך (VRAM) לכל עבודות ה-AI יחד", 2, 16),
                                   ("max_jobs", "כמה עבודות במקביל לכל היותר", 1, 8), ("reserve_ram_gb", "כמה זיכרון חייב להישאר חופשי למחשב", 0, 24)):
            card = W.QFrame()
            card.setObjectName("card")
            cl = W.QHBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            t = W.QLabel(label)
            t.setObjectName("big")
            s = W.QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            val = W.QLabel("")
            val.setMinimumWidth(80)
            val.setStyleSheet("font-size:17pt; font-weight:800;")
            s.valueChanged.connect(lambda v, l=val, k=key: l.setText(("%d GB" % v) if k != "max_jobs" else str(v)))
            s.sliderReleased.connect(lambda k=key, sl=s: self.set_limit(k, sl.value()))
            cl.addWidget(t, 2)
            cl.addWidget(s, 3)
            cl.addWidget(val)
            lay.addWidget(card)
            self.sl[key] = (s, val)
        h = W.QLabel("התנהגות")
        h.setObjectName("h2")
        lay.addWidget(h)
        self.flag_boxes = {}
        for key, label in (("affinity", "לקבץ עבודות שמשתמשות באותו מודל (חוסך זמן טעינה)"), ("backfill", "לתת לעבודה קטנה לעקוף עבודה גדולה שמחכה לזיכרון"),
                           ("emergency_suspend", "אם המחשב נכנס ללחץ: להקפיא את העבודה האחרונה שהתחילה"), ("suspend_on_pause", "כשלוחצים ״עצור הכול״ להקפיא גם את מה שרץ"),
                           ("toast", "הודעה של Windows כשעבודה מסתיימת")):
            c = W.QCheckBox(label)
            c.toggled.connect(lambda on, k=key: self.set_flag(k, on))
            lay.addWidget(c)
            self.flag_boxes[key] = c
        h = W.QLabel("יומן")
        h.setObjectName("h2")
        lay.addWidget(h)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLayoutDirection(Qt.LeftToRight)
        self.log.setMaximumBlockCount(1500)
        self.log.setMinimumHeight(220)
        lay.addWidget(self.log)
        row = W.QHBoxLayout()
        b = W.QPushButton("פתח את תיקיית הנתונים")
        b.clicked.connect(lambda: os.startfile(str(paths.HOME)))
        row.addWidget(b)
        b2 = W.QPushButton("עבור לתצוגה המתקדמת")
        b2.clicked.connect(self.switch_view)
        row.addWidget(b2)
        row.addStretch(1)
        lay.addLayout(row)
        return self._scroll(inner)

    def switch_view(self):
        import subprocess
        subprocess.Popen([str(paths.VENV_PYW), "-m", "aibroker.gui"], cwd=str(paths.ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.quitting = True
        self.close()

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

    def act(self, req):
        if req.pop("confirm", False):
            if W.QMessageBox.question(self, "לבטל?", "לבטל את העבודה? אם היא רצה, היא תיעצר.") != W.QMessageBox.Yes:
                return
        self.api(req)

    def set_limit(self, key, v):
        if not self.building:
            self.api({"op": "limits", "set": {key: v}})

    def set_flag(self, key, on):
        if not self.building:
            self.api({"op": "limits", "flags": {key: on}})

    def load_types(self):
        r = self.api({"op": "types"})
        if not r or not r.get("ok"):
            return
        self.types = r["types"]
        while self.add_lay.count():
            it = self.add_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        h = W.QLabel("מה תרצה לעשות?")
        h.setObjectName("h1")
        self.add_lay.addWidget(h)
        sub = W.QLabel("לחץ על תמונה כדי להוסיף עבודה לתור. המערכת תתחיל אותה כשיהיה מקום.")
        sub.setObjectName("muted")
        self.add_lay.addWidget(sub)
        groups = {}
        order = ["Images", "3D", "Audio", "Game", "Other"]
        for tid, t in sorted(self.types.items()):
            groups.setdefault(t.get("group", "Other"), []).append((tid, t))
        for g in sorted(groups, key=lambda x: order.index(x) if x in order else 99):
            hh = W.QLabel(next((t.get("he_group") for _, t in groups[g] if t.get("he_group")), g))
            hh.setObjectName("h2")
            self.add_lay.addWidget(hh)
            grid = W.QGridLayout()
            grid.setSpacing(14)
            for i, (tid, t) in enumerate(groups[g]):
                tile = Tile(tid, t)
                tile.clicked.connect(lambda k=tid: self.open_new(k))
                grid.addWidget(tile, i // 3, i % 3)
            for c in range(3):
                grid.setColumnStretch(c, 1)
            self.add_lay.addLayout(grid)
        self.add_lay.addStretch(1)

    def open_new(self, tid):
        t = self.types.get(tid)
        if not t:
            return
        dlg = JobDialog(self, tid, t)
        if dlg.exec() == W.QDialog.Accepted:
            r = self.api(dlg.request())
            if r and r.get("ok"):
                self.statusBar().showMessage("נוספה עבודה מספר %d" % r["id"], 5000)
                self.go(0)

    def show_output(self, jid, title):
        OutputDialog(self, jid, title).exec()

    # ------------------------------------------------------------ state
    def on_down(self, msg):
        self.set_banner("🔌", "#8b93a5", "השירות לא רץ", "הפעל מחדש מהתפריט ״מתקדם״ או מהקובץ AI_Broker.bat")

    def set_banner(self, emoji, color, title, sub):
        self.b_icon.setStyleSheet("background:%s; border-radius:7px;" % color)
        self.b_title.setText(title)
        self.b_sub.setText(sub)

    def on_state(self, s):
        first = self.state is None
        self.state = s
        sy, lim = s["sys"], s["limits"]
        used = sy["ram_total"] - sy["ram_avail"]
        self.g_ram.set(used, sy["ram_total"], "%.0f מתוך %.0f GB בשימוש" % (used, sy["ram_total"]))
        self.g_vram.set(sy["gpu_used"], sy["gpu_total"], "%.1f מתוך %.0f GB בשימוש" % (sy["gpu_used"], sy["gpu_total"]))
        self.g_disk.set(sy["disk"], 100, "%.0f%% עסוק" % sy["disk"])
        nrun, nq = len(s["running"]), len(s["queued"])
        counts = "רצות %d עבודות, ממתינות %d." % (nrun, nq) if (nrun or nq) else "אין עבודות כרגע."
        st = s["status"]
        if st == "BRAKE":
            self.set_banner("🛑", "#f0506e", "המחשב בלחץ, עצרתי הכול", "אין מספיק זיכרון פנוי. הקפאתי עבודה אחת והעבודות החדשות לא יתחילו עד שיירגע. " + counts)
        elif st == "PLAYING":
            self.set_banner("🎮", "#f0506e", "אתה משחק / מקליט", "עבודות של כרטיס המסך מחכות, כדי שלא יהיו גמגומים. עבודות קלות ממשיכות. " + counts)
        elif st == "PAUSED":
            self.set_banner("❚❚", "#f5a524", "הכול מושהה", "שום עבודה חדשה לא מתחילה עד שתלחץ ״המשך״. " + counts)
        else:
            f = used / sy["ram_total"]
            if f < 0.7:
                self.set_banner("🟢", "#34c38f", "הכול רגוע", "המחשב מרגיש טוב. " + counts)
            elif f < 0.88:
                self.set_banner("🟠", "#f5a524", "המחשב עמוס, אבל בשליטה", "אני מוודא שלא יתווספו עבודות מעבר למה שהוא מחזיק. " + counts)
            else:
                self.set_banner("🔴", "#f0506e", "המחשב כמעט מלא", "עבודות חדשות לא יתחילו עד שיתפנה מקום. " + counts)
        self.play.setChecked(s["playing"])
        self.pause.setChecked(s["paused"])
        self.pause.setText("המשך" if s["paused"] else "עצור הכול")
        self.building = True
        for k, (sl, val) in self.sl.items():
            if not sl.isSliderDown():
                sl.setValue(int(round(lim[k])))
                val.setText(("%d GB" % lim[k]) if k != "max_jobs" else str(int(lim[k])))
        for k, c in self.flag_boxes.items():
            c.setChecked(bool(s["flags"].get(k)))
        self.building = False
        self.run_list.sync(s["running"], lambda w, j, i: w.update_job(j))
        self.q_list.sync(s["queued"], lambda w, j, i: w.update_job(j, i))
        self.run_empty.setVisible(not nrun)
        self.q_empty.setVisible(not nq)
        self.sb.setText("זיכרון פנוי: %.0f GB     כרטיס מסך: %.1f/%.0f GB     %s" % (sy["ram_avail"], sy["gpu_used"], sy["gpu_total"],
                                                                                    ("נעילת כרטיס מסך: " + s["lock"]) if s["lock"] != "none" else ""))
        if self.tray and st != self.last_status:
            self.tray.setIcon(make_icon({"ACTIVE": "#34c38f", "PAUSED": "#f5a524", "PLAYING": "#f0506e", "BRAKE": "#f0506e"}[st]))
            self.last_status = st
        for n, ts, text in s.get("events", []):
            self.log.appendPlainText("%s  %s" % (time.strftime("%H:%M:%S", time.localtime(ts)), text))
            if self.tray and not first and " -> " in text and text.startswith("#"):
                self.tray.showMessage("AI Broker", text[:150], W.QSystemTrayIcon.Information, 6000)
        if s["hist_rev"] != self.hist_rev:
            self.hist_rev = s["hist_rev"]
            self.fill_history()

    def fill_history(self):
        r = self.api({"op": "history", "limit": 60})
        if not r or not r.get("ok"):
            return
        jobs = r["jobs"]
        self.hist_empty.setVisible(not jobs)

        def upd(w, j, i):
            t = self.types.get(j["type"], {})
            if not w.made:
                w.badge.addWidget(icon_badge(t.get("icon", "⚙️"), t.get("color", "#78909c"), 40))
                w.made = True
            w.jid = j["id"]
            w.t1.setText(t.get("he_title") or j["name"])
            dur = (j.get("finished") or 0) - (j.get("started") or j.get("finished") or 0)
            w.t2.setText("%s  •  ביקש: %s  •  %s  •  זיכרון שיא %.1f GB" % (j["name"], j["requester"], fmt_dur(dur), j.get("peak_ws") or 0))
            ok = {"done": ("הצליחה", "#34c38f"), "failed": ("נכשלה", "#f0506e"), "cancelled": ("בוטלה", "#8b93a5"), "lost": ("לא ידוע", "#f5a524")}[j["state"]]
            w.res.setText(ok[0])
            w.res.setStyleSheet("font-weight:700; color:%s;" % ok[1])
            if getattr(w, "wired", False):
                w.btn.clicked.disconnect()
            w.wired = True
            w.btn.clicked.connect(lambda _=False, jid=j["id"], nm=j["name"]: self.show_output(jid, nm))
        self.hist_list.sync(jobs, upd)

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
    shot, page, size = arg("--screenshot"), int(arg("--page", 0)), arg("--size")
    app = W.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.RightToLeft)
    f = app.font()
    f.setPointSize(12)
    app.setFont(f)
    app.setStyleSheet(QSS)
    try:
        client.start_daemon()
    except Exception as e:
        print("could not start the broker:", e)
    win = Main(tray=("--no-tray" not in argv and shot is None))
    if size:
        win.resize(*[int(x) for x in size.lower().split("x")])
    win.go(page)
    win.show()
    if "--auto-switch" in argv:
        QtCore.QTimer.singleShot(3000, win.switch_view)
    if shot:
        def grab():
            win.grab().save(shot)
            print("saved", shot)
            win.quitting = True
            win.close()
        QtCore.QTimer.singleShot(3500, grab)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
