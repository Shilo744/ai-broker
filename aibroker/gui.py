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

from . import assistant, client, paths, system
from .theme import QSS, icon, logo_pixmap, make_icon, save_ico, sym_icon, symbol_pixmap

# look and feel (palette, icons, logo): see theme.py

SYM = {"🖼️": "✎", "🎨": "✦", "🧊": "⬢", "🗿": "◈", "🛠️": "⚒", "🧱": "▦", "🎵": "♪", "🔊": "♬", "🎮": "▷", "📸": "◎", "🎬": "▶", "🐍": "λ", "⚙️": "⚙"}
STATE_HE = {"running": "רץ", "paused": "מוקפא", "queued": "ממתין", "held": "עצור", "done": "הצליח", "failed": "נכשל", "cancelled": "בוטל", "lost": "לא ידוע"}
STATE_COLOR = {"running": "#5fad65", "paused": "#e0a030", "queued": "#868a91", "held": "#e0a030", "done": "#5fad65", "failed": "#db5c5c", "cancelled": "#868a91", "lost": "#e0a030"}
HIDDEN_FILES = {"job.log", "result.json"}
IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
KIND = {".glb": ("⬢", "#2aa198"), ".gltf": ("⬢", "#2aa198"), ".obj": ("⬢", "#2aa198"), ".ogg": ("♪", "#43a047"), ".wav": ("♪", "#43a047"), ".flac": ("♪", "#43a047"),
        ".mp3": ("♪", "#43a047"), ".mp4": ("▶", "#c0392b"), ".json": ("≡", "#868a91"), ".txt": ("≡", "#868a91"), ".log": ("≡", "#868a91"), ".blend": ("⚒", "#e87d0d")}


def ltr(t):
    """keep numbers like '~7 GB' in reading order inside right-to-left text"""
    return "‪%s‬" % t


def fmt_dur(s):
    s = int(s or 0)
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def fmt_limit(key, v):
    v = int(round(v))
    return str(v) if key == "max_jobs" else ("%d%%" % v if key == "disk_busy_pct" else "%d GB" % v)


def eta_text(j):
    """Plain-Hebrew estimate for a running job from the MEDIAN of earlier identical runs: seconds left, or 'longer than usual'."""
    typ, n = j.get("typical_s"), j.get("typical_n", 0)
    if not typ or j.get("state") not in ("running", "paused"):
        return ""
    left = typ - j.get("elapsed", 0)
    basis = "חציון של %d ריצות" % n if n > 1 else "ריצה קודמת אחת"
    if left > 0:
        return "נשארו כ-%d שניות (%s)" % (round(left), basis) if left < 120 else "נשארו כ-%d דקות (%s)" % (round(left / 60), basis)
    return "לוקח יותר מהרגיל (בדרך כלל %d שניות)" % round(typ)


def fmt_size(n):
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % max(1, n // 1000)


def he_reason(r):
    if not r:
        return "מתחיל תיכף"
    table = (("RAM budget", "אין כרגע מספיק RAM פנוי לעבודה הזו"), ("VRAM budget", "ה-GPU עסוק, מחכה שיתפנה מקום"), ("free RAM", "ה-RAM של המחשב נמוך, מחכה"),
             ("free commit", "ה-RAM של המחשב נמוך, מחכה"), ("paused", "הכול מושהה"), ("I am playing", "אתה משחק, עבודות GPU מחכות"), ("held by owner", "עצרת אותה בעצמך"),
             ("max concurrent", "כבר רצות הרבה עבודות במקביל"), ("another", "עבודה מאותו סוג כבר רצה"), ("GPU lock", "תוכנה אחרת משתמשת ב-GPU"),
             ("a self-locking", "מצלמים עכשיו את המשחק"), ("visual run", "עבודת GPU רצה עכשיו"), ("BRAKE", "המחשב בלחץ, עצרתי הכול"),
             ("disk busy", "הדיסק עסוק מדי, מחכה שיירגע"), ("starvation", "העבודה הראשונה ממתינה הרבה זמן, אף אחת לא עוקפת אותה"), ("waiting for the job", "מחכה לעבודה אחרת"), ("backfill", "מחכה לעבודה שלפניה"))
    for k, v in table:
        if r.startswith(k):
            return v
    return r


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
        self.f, self.color = 0.0, "#5fad65"
        self.marker = None

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rtl = self.layoutDirection() == Qt.RightToLeft
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#393b40"))
        p.drawRoundedRect(0, 0, w, h, 4, 4)
        if self.f > 0:
            p.setBrush(QtGui.QColor(self.color))
            fw = max(h, w * self.f)
            p.drawRoundedRect(QtCore.QRectF(w - fw if rtl else 0, 0, fw, h), 4, 4)
        if self.marker is not None:
            x = w * self.marker
            x = w - x if rtl else x
            p.setPen(QtGui.QPen(QtGui.QColor("#3574f0"), 2))
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
        color, word = ("#5fad65", "") if f < 0.6 else ("#e0a030", "עמוס") if f < 0.85 else ("#db5c5c", "כמעט מלא")
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


class DropEdit(W.QLineEdit):
    """A path field that also accepts a file dropped from Explorer."""
    def __init__(self, text=""):
        super().__init__(text)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.setText(u.toLocalFile().replace("\\", "/"))
                break


class SubmitDialog(W.QDialog):
    """Secondary and minimal: model type, input file, name. Everything else is defaulted from the job-type file and hidden under 'Advanced'."""
    def __init__(self, parent, types, preselect=None, prefill=None):
        super().__init__(parent)
        self.types = types
        self.prefill = prefill
        self.setWindowTitle("עבודה חדשה")
        self.setMinimumWidth(560)
        self.setLayoutDirection(Qt.RightToLeft)
        self.lay = W.QVBoxLayout(self)
        self.lay.setSpacing(10)
        note = W.QLabel("בחר סוג, בחר קובץ (או גרור אותו לשדה), ולחץ הוסף. העבודה נכנסת לאותו תור ש-Claude משתמש בו, והתוצאה נשמרת לבד בתיקיית המודל.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.combo = W.QComboBox()
        for tid, t in sorted(types.items(), key=lambda kv: (kv[1].get("group", ""), kv[0])):
            if t.get("hidden"):
                continue
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
        self.prefilled = False
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
        self.prefilled = False
        tid = self.combo.currentData()
        t = self.types[tid]
        self.where.setText("התוצאה תישמר ב: output\\%s\\<תאריך>_<שם>\\" % (t.get("output_dir") or tid))
        for k, spec in (t.get("params") or {}).items():
            d = spec.get("default") if isinstance(spec, dict) else spec
            req = isinstance(spec, dict) and spec.get("required")
            e = DropEdit("" if d is None else (json.dumps(d) if isinstance(d, (list, dict)) else str(d)))
            e.setLayoutDirection(Qt.LeftToRight)
            if k in FILE_FIELDS and self.prefill and not self.prefilled:
                e.setText(self.prefill)
                self.prefilled = True
            if k in FILE_FIELDS:
                e.setPlaceholderText("גרור לכאן קובץ או לחץ ״בחר״")
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


class ConnCheck(QtCore.QThread):
    done = QtCore.Signal(object)

    def run(self):
        self.done.emit(system.claude_registered())


class AdvancedDialog(W.QDialog):
    def toggle_autostart(self, on):
        ok = system.set_autostart(on)
        if not ok and on:
            W.QMessageBox.warning(self, "הפעלה עם Windows", "לא הצלחתי ליצור את הקיצור בתיקיית ההפעלה.")

    def on_conn(self, state):
        self.connected = state
        self.conn_btn.setEnabled(state is not None)
        if state is None:
            self.conn_lbl.setText("לא הצלחתי לבדוק: הפקודה claude לא נמצאה.")
        elif state:
            self.conn_lbl.setText("מחובר: כל סשן חדש של Claude Code (גם של המשחק והמעבדה) רואה את הכלים של ה-broker ומריץ עבודות דרך התור.")
            self.conn_btn.setText("נתק את Claude Code")
        else:
            self.conn_lbl.setText("לא מחובר. סוכנים של Claude Code עדיין יכולים להריץ עבודות כבדות בלי לעבור בתור.")
            self.conn_btn.setText("חבר את Claude Code")

    def toggle_connection(self):
        if self.connected:
            if W.QMessageBox.question(self, "ניתוק", "להסיר את החיבור של ה-broker מ-Claude Code?") != W.QMessageBox.Yes:
                return
            ok, msg = system.unregister_claude()
        else:
            if W.QMessageBox.question(self, "חיבור ל-Claude Code",
                                      "זה יוסיף את הכלים של ה-broker להגדרות של Claude Code אצלך (לכל הפרויקטים) ויעתיק קובץ הוראות לסוכנים. אפשר לנתק בכל רגע. להמשיך?") != W.QMessageBox.Yes:
                return
            ok, msg = system.register_claude()
        self.conn_lbl.setText(msg)
        self.check = ConnCheck()
        self.check.done.connect(self.on_conn)
        self.check.start()

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
        self.auto = W.QCheckBox("להפעיל את התוכנה עם Windows (תעלה בשקט באזור ההודעות)")
        self.auto.setChecked(system.autostart_enabled())
        self.auto.toggled.connect(self.toggle_autostart)
        lay.addWidget(self.auto)
        h = W.QLabel("חיבור ל-Claude Code")
        h.setObjectName("h2")
        lay.addWidget(h)
        self.conn_lbl = W.QLabel("בודק…")
        self.conn_lbl.setObjectName("muted")
        self.conn_lbl.setWordWrap(True)
        lay.addWidget(self.conn_lbl)
        crow = W.QHBoxLayout()
        self.conn_btn = W.QPushButton("חבר את Claude Code")
        self.conn_btn.setEnabled(False)
        self.conn_btn.clicked.connect(self.toggle_connection)
        crow.addWidget(self.conn_btn)
        crow.addStretch(1)
        lay.addLayout(crow)
        self.connected = None
        self.check = ConnCheck()
        self.check.done.connect(self.on_conn)
        self.check.start()
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



class Thumb(W.QLabel):
    """A clickable picture or file tile inside a chat bubble."""
    def __init__(self, pixmap, path, size=150, on_click=None):
        super().__init__()
        self.path = path
        self.on_click = on_click
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(path)
        self.setStyleSheet("border-radius:8px;")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and os.path.exists(self.path):
            if self.on_click:
                self.on_click()
            else:
                os.startfile(self.path)



def glb_frames(path):
    d = Path(path).parent / "preview"
    return sorted(str(x) for x in d.glob("frame_*.png")) if d.is_dir() else []


class TurntableDialog(W.QDialog):
    """Spin a 3D model with the mouse. The frames come from the broker's Blender preview job (36 views around the model)."""
    def __init__(self, parent, glb):
        super().__init__(parent)
        self.glb = glb
        self.setWindowTitle(Path(glb).name)
        self.setLayoutDirection(Qt.RightToLeft)
        self.frames = [QtGui.QPixmap(f) for f in glb_frames(glb)]
        self.i = 0
        self.drag = None
        v = W.QVBoxLayout(self)
        self.view = W.QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(520, 520)
        self.view.setStyleSheet("background:#17181a; border-radius:10px;")
        self.view.setCursor(Qt.OpenHandCursor)
        v.addWidget(self.view)
        hint = W.QLabel("גרור עם העכבר כדי לסובב. הדגם מוצג בלי צבע (חומר אפור) כדי לראות את הצורה.")
        hint.setObjectName("muted")
        v.addWidget(hint)
        row = W.QHBoxLayout()
        b = W.QPushButton("פתח את הקובץ")
        b.clicked.connect(lambda: os.startfile(self.glb))
        c = W.QPushButton("פתח תיקייה")
        c.clicked.connect(lambda: os.startfile(str(Path(self.glb).parent)))
        row.addWidget(b)
        row.addWidget(c)
        row.addStretch(1)
        v.addLayout(row)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(lambda: self.show_frame(self.i + 1))
        self.timer.start(90)
        self.show_frame(0)

    def show_frame(self, i):
        if self.frames:
            self.i = i % len(self.frames)
            self.view.setPixmap(self.frames[self.i].scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def mousePressEvent(self, e):
        if self.view.geometry().contains(e.position().toPoint()):
            self.drag = (e.position().x(), self.i)
            self.timer.stop()
            self.view.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.drag:
            self.show_frame(self.drag[1] - int((e.position().x() - self.drag[0]) / 9))

    def mouseReleaseEvent(self, e):
        self.drag = None
        self.view.setCursor(Qt.OpenHandCursor)

    def resizeEvent(self, e):
        self.show_frame(self.i)
        super().resizeEvent(e)


def aligned(bubble, who):
    """Place a chat bubble on the right (user) or left (model) side of an RTL window. A stretch is used instead of an alignment flag, because alignment breaks wrapped-label heights."""
    row = W.QWidget()
    h = W.QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    if who == "user":
        h.addWidget(bubble)
        h.addStretch(1)
    else:
        h.addStretch(1)
        h.addWidget(bubble)
    return row


class Bubble(W.QFrame):
    def __init__(self, who):
        super().__init__()
        self.who = who
        self.setObjectName("bubble_user" if who == "user" else "bubble_model")
        self.lay = W.QVBoxLayout(self)
        self.lay.setContentsMargins(14, 10, 14, 10)
        self.lay.setSpacing(8)
        self.setMinimumWidth(300)
        self.setMaximumWidth(620)

    def text(self, t, muted=False, selectable=True):
        l = W.QLabel(t)
        l.setWordWrap(True)
        if muted:
            l.setObjectName("muted")
        if selectable:
            l.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.lay.addWidget(l)
        return l

    def row(self, widgets):
        h = W.QHBoxLayout()
        h.setSpacing(8)
        for w in widgets:
            h.addWidget(w)
        h.addStretch(1)
        self.lay.addLayout(h)


class ChatPanel(W.QFrame):
    """A normal chat with one model: you write (and drop a file), the model answers with its result. Built from the job history of that model."""
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("editor")
        self.attached = None
        self.sig = None
        v = W.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        head = W.QHBoxLayout()
        self.title = W.QLabel("")
        self.title.setObjectName("h2")
        self.path = W.QLabel("")
        self.path.setObjectName("muted")
        self.path.setLayoutDirection(Qt.LeftToRight)
        b = W.QPushButton("פתח תיקייה")
        b.setObjectName("tool")
        b.clicked.connect(main.open_model_folder)
        head.addWidget(self.title)
        head.addWidget(self.path, 1)
        head.addWidget(b)
        v.addLayout(head)
        self.scroll = W.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(W.QFrame.NoFrame)
        self.body = W.QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.col = W.QVBoxLayout(self.body)
        self.col.setContentsMargins(0, 0, 6, 0)
        self.col.setSpacing(10)
        self.scroll.setWidget(self.body)
        v.addWidget(self.scroll, 1)
        # composer
        self.comp = W.QFrame()
        self.comp.setObjectName("composer")
        cl = W.QVBoxLayout(self.comp)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        self.chips = W.QHBoxLayout()
        cl.addLayout(self.chips)
        self.drop_zone = W.QLabel("גרור לכאן תמונה, או לחץ ״בחר תמונה״ ואז ״צור דגם 3D״")
        self.drop_zone.setAlignment(Qt.AlignCenter)
        self.drop_zone.setMinimumHeight(70)
        self.drop_zone.setStyleSheet("border: 2px dashed #4e5157; border-radius: 12px; color: #868a91; padding: 14px;")
        cl.addWidget(self.drop_zone)
        self.edit = W.QPlainTextEdit()
        self.edit.setFixedHeight(62)
        self.edit.setLayoutDirection(Qt.LeftToRight)
        self.edit.setStyleSheet("QPlainTextEdit { background: transparent; border: none; color: #dfe1e5; font-family: 'Segoe UI'; font-size: 10.5pt; }")
        self.edit.setPlaceholderText("כתוב כאן מה לעשות…  (Enter לשליחה)")
        self.edit.installEventFilter(self)
        cl.addWidget(self.edit)
        row = W.QHBoxLayout()
        self.attach_btn = W.QPushButton("צרף קובץ")
        self.attach_btn.setObjectName("tool")
        self.attach_btn.clicked.connect(self.pick)
        self.adv_btn = W.QPushButton("מתקדם…")
        self.adv_btn.setObjectName("tool")
        self.adv_btn.clicked.connect(lambda: main.open_submit(main.model_first_type(), self.attached))
        self.send_btn = W.QPushButton("שלח")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        self.hint_lbl = W.QPushButton("איך זה עובד?")
        self.hint_lbl.setObjectName("tool")
        self.hint_lbl.clicked.connect(self.explain)
        row.addWidget(self.send_btn)
        row.addWidget(self.attach_btn)
        row.addWidget(self.adv_btn)
        row.addStretch(1)
        row.addWidget(self.hint_lbl)
        cl.addLayout(row)
        v.addWidget(self.comp)
        self.setAcceptDrops(True)

    # --- input
    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
            self.send()
            return True
        return super().eventFilter(obj, ev)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.set_attached(u.toLocalFile().replace("\\", "/"))
                e.acceptProposedAction()
                break

    def pick(self):
        p, _ = W.QFileDialog.getOpenFileName(self, "בחר קובץ")
        if p:
            self.set_attached(p)

    def set_attached(self, path):
        self.attached = path
        tid, cfg = self.cfg()
        if cfg and not cfg.get("text"):
            self.drop_zone.setText(("נבחרה תמונה: " + Path(path).name + "   (לחץ ״צור דגם 3D״)") if path else "גרור לכאן תמונה, או לחץ ״בחר תמונה״ ואז ״צור דגם 3D״")
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if path:
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                t = W.QLabel()
                t.setPixmap(pm.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.chips.addWidget(t)
            lab = W.QLabel(Path(path).name)
            lab.setObjectName("muted")
            x = W.QPushButton("הסר")
            x.setObjectName("tool")
            x.clicked.connect(lambda: self.set_attached(None))
            self.chips.addWidget(lab)
            self.chips.addWidget(x)
            self.chips.addStretch(1)

    def explain(self):
        tid, cfg = self.cfg()
        if cfg:
            nl = chr(10)
            txt = cfg["hint"]
            if cfg.get("examples"):
                txt += nl + nl + "דוגמאות:" + nl + nl.join(cfg["examples"])
            W.QMessageBox.information(self, "איך זה עובד", txt + nl + nl + "Enter שולח. Shift+Enter שורה חדשה.")

    def cfg(self):
        tid = self.main.model_first_type()
        return tid, (self.main.types.get(tid, {}).get("chat") if tid else None)

    def last_result_image(self):
        for j in self.main.model_jobs():
            pass
        best = None
        for j in self.main.model_jobs():
            d = j.get("outdir")
            if j["state"] == "done" and d and os.path.isdir(d):
                for n in sorted(os.listdir(d)):
                    if Path(n).suffix.lower() in IMG and n != "ref_rgba.png":
                        best = os.path.join(d, n).replace("\\", "/")
        return best

    def send(self):
        tid, cfg = self.cfg()
        if not cfg:
            return
        text = self.edit.toPlainText().strip()
        params = {}
        if cfg.get("text"):
            if not text:
                self.main.statusBar().showMessage("כתוב מה לעשות", 4000)
                return
            params[cfg["text"]] = text
        f = self.attached
        if cfg.get("file"):
            if not f and cfg.get("needs_file"):
                f = self.last_result_image()          # keep talking: the next message edits the last result
            if not f and cfg.get("needs_file"):
                self.main.statusBar().showMessage("צרף קובץ (גרור לכאן או ״צרף קובץ״)", 4000)
                return
            if f:
                params[cfg["file"]] = f
        name = (text[:28] if text else Path(f or "job").stem[:28])
        r = self.main.api(dict(op="submit", type=tid, params=params, name=name, requester="owner"))
        if r and r.get("ok"):
            self.edit.clear()
            self.set_attached(None)
            self.sig = None
            self.main.refresh_chat(force=True)

    # --- render
    def build(self, force=False):
        m = self.main
        tid, cfg = self.cfg()
        g = next((x for x in m.models if x["dir"] == m.sel_model), None)
        self.title.setText(("שיחה עם: " + g["title"]) if g else "")
        self.path.setText(str(m.model_folder()))
        jobs = m.model_jobs()
        sig = (m.sel_model, tuple((j["id"], j["state"], bool(j.get("held")), int(j.get("elapsed", 0)) // 5, len(self.outfiles(j)), sum(1 for f in self.outfiles(j) if f.lower().endswith(".glb") and (Path(f).parent / "preview" / "preview.png").exists())) for j in jobs), bool(cfg))
        if sig == self.sig and not force:
            return
        self.sig = sig
        while self.col.count():
            it = self.col.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        can = bool(cfg)
        self.comp.setVisible(can)
        has_text = bool(cfg and cfg.get("text"))
        has_file = bool(cfg and cfg.get("file"))
        self.edit.setVisible(has_text)
        self.drop_zone.setVisible(bool(cfg) and not has_text)
        self.attach_btn.setVisible(has_file)
        self.attach_btn.setText("בחר תמונה" if not has_text else "צרף קובץ")
        self.send_btn.setText("שלח" if has_text and has_file else ("צייר" if has_text else "צור דגם 3D"))
        self.hint_lbl.setVisible(bool(cfg))
        self.adv_btn.setVisible(has_text)
        # explanation bubble (always first)
        b = Bubble("model")
        if cfg:
            b.text(cfg["hint"])
            if cfg.get("examples"):
                b.text("דוגמאות (לחץ כדי להעתיק לתיבה):", muted=True)
                for ex in cfg["examples"]:
                    btn = W.QPushButton(ex)
                    btn.setObjectName("tool")
                    btn.setLayoutDirection(Qt.LeftToRight)
                    btn.clicked.connect(lambda _=False, e=ex: self.edit.setPlainText(e))
                    b.lay.addWidget(btn)
        else:
            b.text("לסוג הזה עדיין אין שיחה. הוא משמש בעיקר את Claude. אפשר לשלוח עבודה ידנית דרך הכפתור למטה, והתוצאות יופיעו כאן.")
            btn = W.QPushButton("שלח עבודה ידנית…")
            btn.clicked.connect(lambda: m.open_submit(m.model_first_type()))
            b.lay.addWidget(btn, 0, Qt.AlignRight)
        self.col.addWidget(aligned(b, "model"))
        for j in jobs:
            self.add_job(j, cfg)
        self.col.addStretch(1)
        QtCore.QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    @staticmethod
    def outfiles(j):
        d = j.get("outdir")
        out = []
        if d and os.path.isdir(d):
            for root, _x, names in os.walk(d):
                if os.path.basename(root) == "preview":
                    continue
                for n in sorted(names):
                    if n not in HIDDEN_FILES:
                        out.append(os.path.join(root, n))
        return out

    def add_job(self, j, cfg):
        params = j.get("params") or {}
        u = Bubble("user")
        txt = params.get((cfg or {}).get("text") or "") if cfg else None
        if txt:
            u.text(str(txt))
        fp = params.get((cfg or {}).get("file") or "") if cfg else None
        if fp and os.path.exists(str(fp)):
            pm = QtGui.QPixmap(str(fp))
            if not pm.isNull():
                u.row([Thumb(pm.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation), str(fp))])
        if not txt and not (fp and os.path.exists(str(fp))):
            u.text(j["name"])
        u.text("#%d  •  %s" % (j["id"], j["requester"]), muted=True)
        self.col.addWidget(aligned(u, "user"))
        a = Bubble("model")
        st = "held" if j["state"] == "queued" and j.get("held") else ("paused" if j.get("suspended") else j["state"])
        if st in ("queued", "held"):
            a.text("ממתין בתור: " + ("עצרת אותה בעצמך" if st == "held" else he_reason(j.get("reason", ""))), muted=True)
        elif st in ("running", "paused"):
            a.text("%s   •   עברו %d שניות   •   RAM %s" % ("עובד על זה" if st == "running" else "מוקפא", j.get("elapsed", 0), ltr("%.1f GB" % j.get("cur_ws", 0))))
            pb = W.QProgressBar()
            pb.setTextVisible(False)
            pb.setFixedHeight(5)
            typ = j.get("typical_s")
            if typ and st == "running":
                pb.setRange(0, 100)
                pb.setValue(min(95, int(100 * j.get("elapsed", 0) / typ)))
                a.text(eta_text(j), muted=True)
            else:
                pb.setRange(0, 0)
                a.text("עדיין אין נתונים על ריצות קודמות, אז אין הערכת זמן", muted=True)
            a.lay.addWidget(pb)
        elif st == "done":
            dur = (j.get("finished") or 0) - (j.get("started") or j.get("finished") or 0)
            a.text("מוכן (%s)" % fmt_dur(dur), muted=True)
            tiles = []
            for f in self.outfiles(j)[:8]:
                if Path(f).suffix.lower() in IMG:
                    pm = QtGui.QPixmap(f)
                    if not pm.isNull():
                        tiles.append(Thumb(pm.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation), f))
                        continue
                if f.lower().endswith(".glb"):
                    tiles.append(self.main.glb_tile(f))
                    continue
                sym, col = KIND.get(Path(f).suffix.lower(), ("▫", "#868a91"))
                t = Thumb(symbol_pixmap(sym, col, 84), f)
                t.setToolTip(f)
                tiles.append(t)
            if tiles:
                a.row(tiles)
                names = W.QLabel("  ".join(Path(f).name for f in self.outfiles(j)[:4]))
                names.setObjectName("muted")
                names.setLayoutDirection(Qt.LeftToRight)
                a.lay.addWidget(names)
        else:
            a.text("%s (קוד %s). ראה פירוט בהיסטוריה." % ("נכשל" if st == "failed" else {"cancelled": "בוטל", "lost": "לא ידוע"}.get(st, st), j.get("rc")), muted=True)
        row = W.QHBoxLayout()
        if st in ("done", "failed", "cancelled"):
            rb = W.QPushButton("הרץ שוב")
            rb.setObjectName("tool")
            rb.clicked.connect(lambda _=False, i=j["id"]: self.main.rerun_job(i))
            row.addWidget(rb)
            if j.get("outdir"):
                ob = W.QPushButton("פתח תיקייה")
                ob.setObjectName("tool")
                ob.clicked.connect(lambda _=False, d=j["outdir"]: os.startfile(d) if os.path.isdir(d) else None)
                row.addWidget(ob)
        if st in ("queued", "held", "running", "paused"):
            cb = W.QPushButton("בטל")
            cb.setObjectName("tool")
            cb.clicked.connect(lambda _=False, i=j["id"]: self.main.api({"op": "cancel", "id": i}))
            row.addWidget(cb)
        row.addStretch(1)
        a.lay.addLayout(row)
        self.col.addWidget(aligned(a, "model"))



class AssistantPanel(W.QFrame):
    """Claude inside the window: a normal chat. No terminal is ever shown. Questions about the machine and models, requests to run jobs, and (with in-chat approval) downloads."""
    EXAMPLES = ["מה מותקן אצלי ומה אפשר להריץ?", "איזה מודל תמונות כדאי לי להוריד, ולמה?", "למה העבודה האחרונה לקחה כל כך הרבה זיכרון?", "כמה מקום פנוי יש לי בדיסק למודלים?"]

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("editor")
        self.hist = assistant.load_history()
        self.worker = None
        self.pending = []
        self.denial_ui = []
        self.turn_text = False
        self.qs = QtCore.QSettings("ai-broker", "assistant")
        v = W.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        head = W.QHBoxLayout()
        t = W.QLabel("עוזר Claude")
        t.setObjectName("h2")
        sub = W.QLabel("שאל על המחשב והמודלים, בקש להריץ עבודות, או להמליץ ולהוריד (רק באישור שלך)")
        sub.setObjectName("muted")
        self.model_box = W.QComboBox()
        for key, label in (("haiku", "מהיר וזול (Haiku)"), ("sonnet", "חכם יותר (Sonnet)"), ("default", "ברירת מחדל של החשבון")):
            self.model_box.addItem(label, key)
        i = self.model_box.findData(self.qs.value("model", "haiku"))
        self.model_box.setCurrentIndex(max(0, i))
        self.model_box.currentIndexChanged.connect(lambda: self.qs.setValue("model", self.model_box.currentData()))
        new = W.QPushButton("שיחה חדשה")
        new.setObjectName("tool")
        new.clicked.connect(self.reset)
        head.addWidget(t)
        head.addWidget(sub, 1)
        head.addWidget(self.model_box)
        head.addWidget(new)
        v.addLayout(head)
        self.scroll = W.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(W.QFrame.NoFrame)
        self.body = W.QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.col = W.QVBoxLayout(self.body)
        self.col.setContentsMargins(0, 0, 6, 0)
        self.col.setSpacing(10)
        self.scroll.setWidget(self.body)
        v.addWidget(self.scroll, 1)
        self.activity = W.QLabel("")
        self.activity.setObjectName("muted")
        self.bar = W.QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.activity.setVisible(False)
        self.bar.setVisible(False)
        v.addWidget(self.activity)
        v.addWidget(self.bar)
        comp = W.QFrame()
        comp.setObjectName("composer")
        cl = W.QVBoxLayout(comp)
        cl.setContentsMargins(10, 8, 10, 8)
        self.edit = W.QPlainTextEdit()
        self.edit.setFixedHeight(62)
        self.edit.setPlaceholderText("כתוב לעוזר…  (Enter לשליחה)")
        self.edit.setStyleSheet("QPlainTextEdit { background: transparent; border: none; color: #dfe1e5; font-family: 'Segoe UI'; font-size: 10.5pt; }")
        self.edit.installEventFilter(self)
        cl.addWidget(self.edit)
        row = W.QHBoxLayout()
        self.send_btn = W.QPushButton("שלח")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.on_send_click)
        row.addWidget(self.send_btn)
        row.addStretch(1)
        cl.addLayout(row)
        v.addWidget(comp)
        self.render_history()

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ev.modifiers() & Qt.ShiftModifier):
            self.on_send_click()
            return True
        return super().eventFilter(obj, ev)

    # --- bubbles
    def add_bubble(self, role, text, save=True, md=False):
        b = Bubble("user" if role == "user" else "model")
        l = b.text(text)
        if md:
            l.setTextFormat(Qt.MarkdownText)
            l.setOpenExternalLinks(True)
        self.col.insertWidget(self.col.count() - 1, aligned(b, "user" if role == "user" else "model"))
        if save:
            self.hist["messages"].append({"role": role, "text": text})
            assistant.save_history(self.hist)
        QtCore.QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        return b

    def render_history(self):
        while self.col.count():
            it = self.col.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.col.addStretch(1)
        w = Bubble("model")
        w.text("שלום. אני העוזר של התוכנה. אני רואה את התור, המשאבים והתוצאות, יכול להריץ עבודות בשבילך, ולעזור לבחור ולהוריד מודלים (הורדה רק אחרי שתאשר כאן בצ'אט). שאל אותי משהו, או לחץ על דוגמה:")
        for ex in self.EXAMPLES:
            b = W.QPushButton(ex)
            b.setObjectName("tool")
            b.clicked.connect(lambda _=False, e=ex: (self.edit.setPlainText(e), self.on_send_click()))
            w.lay.addWidget(b)
        self.col.insertWidget(0, aligned(w, "model"))
        for m in self.hist.get("messages", []):
            self.add_bubble(m["role"], m["text"], save=False, md=(m["role"] != "user"))

    def reset(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        self.hist = {"session": None, "messages": []}
        assistant.save_history(self.hist)
        self.render_history()

    # --- turns
    def on_send_click(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            return
        text = self.edit.toPlainText().strip()
        if not text:
            return
        self.edit.clear()
        self.add_bubble("user", text)
        self.start_turn(text, [])

    def start_turn(self, message, extra):
        self.turn_text = False
        self.worker = assistant.Worker(message, self.hist.get("session"), self.model_box.currentData(), extra)
        self.worker.event.connect(self.on_event)
        self.worker.finished_turn.connect(self.on_done)
        self.activity.setText("חושב…")
        self.activity.setVisible(True)
        self.bar.setVisible(True)
        self.send_btn.setText("עצור")
        self.worker.start()

    def on_event(self, ev):
        if ev.get("type") != "assistant":
            return
        for blk in (ev.get("message") or {}).get("content", []):
            if blk.get("type") == "text" and blk.get("text", "").strip():
                self.turn_text = True
                self.add_bubble("assistant", blk["text"].strip(), md=True)
            elif blk.get("type") == "tool_use":
                self.activity.setText(assistant.FRIENDLY.get(blk.get("name", ""), "עובד על זה") + "…")

    def on_done(self, res):
        self.activity.setVisible(False)
        self.bar.setVisible(False)
        self.send_btn.setText("שלח")
        if res.get("session"):
            self.hist["session"] = res["session"]
            assistant.save_history(self.hist)
        if not res["ok"] and res["error"] and res["error"] != "בוטל":
            self.add_bubble("assistant", "משהו השתבש: " + res["error"])
        elif res["ok"] and not self.turn_text and res.get("text"):
            self.add_bubble("assistant", res["text"], md=True)
        if res.get("denials"):
            self.ask(res["denials"])

    # --- approvals inside the chat
    def ask(self, denials):
        seen, items = set(), []
        for d in denials:
            key = (d.get("tool_name"), json.dumps(d.get("tool_input"), sort_keys=True))
            if key not in seen:
                seen.add(key)
                items.append(d)
        self.pending = []
        for d in items:
            b = Bubble("model")
            b.text("Claude מבקש רשות " + assistant.describe_denial(d))
            row = W.QHBoxLayout()
            yes = W.QPushButton("אשר")
            yes.setObjectName("primary")
            no = W.QPushButton("דחה")
            row.addWidget(yes)
            row.addWidget(no)
            row.addStretch(1)
            b.lay.addLayout(row)
            self.col.insertWidget(self.col.count() - 1, aligned(b, "model"))
            entry = {"d": d, "answer": None, "bubble": b, "yes": yes, "no": no}
            self.pending.append(entry)
            yes.clicked.connect(lambda _=False, e=entry: self.answer(e, True))
            no.clicked.connect(lambda _=False, e=entry: self.answer(e, False))
        QtCore.QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def answer(self, entry, ok):
        entry["answer"] = ok
        entry["yes"].setEnabled(False)
        entry["no"].setEnabled(False)
        entry["bubble"].text("אישרת" if ok else "דחית", muted=True)
        if all(e["answer"] is not None for e in self.pending):
            approved = [e for e in self.pending if e["answer"]]
            rules = [assistant.allow_rule(e["d"]) for e in approved]
            msg = ("אישרתי: " + "; ".join(assistant.describe_denial(e["d"]) for e in approved) + ". תמשיך.") if approved else "לא אישרתי. תמשיך בלי זה, או תציע חלופה."
            self.pending = []
            self.add_bubble("user", "אישרתי" if approved else "לא אישרתי")
            self.start_turn(msg, rules)


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
        self.assistant_mode = False
        self.preview_asked = set()
        self.setAcceptDrops(True)
        self._build()
        self.tray = None
        if tray and W.QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()
        self.settings = QtCore.QSettings("ai-broker", "gui3")
        self.fit_to_screen()
        self.poller = Poller()
        self.poller.got.connect(self.on_state)
        self.poller.down.connect(self.on_down)
        self.poller.start()
        self.load_types()
        t = QtCore.QTimer(self)
        t.timeout.connect(self.refresh_files)
        t.start(3000)

    def fit_to_screen(self):
        """Open at a size that fits the screen the window is on, centred; never half off-screen (also if a saved geometry came from a bigger screen)."""
        scr = (self.screen() or W.QApplication.primaryScreen()).availableGeometry()
        w = min(self.width(), int(scr.width() * 0.92))
        h = min(self.height(), int(scr.height() * 0.92))
        self.resize(max(900, w), max(620, h))
        self.move(scr.left() + (scr.width() - self.width()) // 2, scr.top() + (scr.height() - self.height()) // 2)

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
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = W.QFrame()
        bar.setObjectName("topbar")
        head = W.QHBoxLayout(bar)
        head.setContentsMargins(12, 7, 12, 7)
        head.setSpacing(6)
        logo = W.QLabel()
        logo.setPixmap(logo_pixmap(30))
        brand = W.QLabel("AI Broker")
        brand.setObjectName("brand")
        sep = W.QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet("background:#393b40;")
        self.dot = W.QLabel("")
        self.dot.setFixedSize(9, 9)
        self.h_title = W.QLabel("מתחבר…")
        self.h_title.setObjectName("big")
        self.h_sub = W.QLabel("")
        self.h_sub.setObjectName("muted")
        for w in (logo, brand):
            head.addWidget(w)
        head.addSpacing(8)
        head.addWidget(sep)
        head.addSpacing(8)
        head.addWidget(self.dot, 0, Qt.AlignVCenter)
        head.addWidget(self.h_title)
        head.addWidget(self.h_sub)
        head.addStretch(1)

        def tb(name, text, tip, obj="tb", checkable=False):
            btn = W.QPushButton(text)
            btn.setObjectName(obj)
            btn.setIcon(icon(name, "#b4b8bf", 16))
            btn.setIconSize(QtCore.QSize(16, 16))
            btn.setToolTip(tip)
            btn.setCheckable(checkable)
            btn.setCursor(Qt.PointingHandCursor)
            return btn
        self.play = tb("gamepad", "משחק / הקלטה", "כשזה דלוק, עבודות GPU מחכות ועבודות GPU שרצות מוקפאות, כדי שהמשחק או ההקלטה לא יגמגמו", "tbplay", True)
        self.play.clicked.connect(lambda on: self.api({"op": "playing", "on": on}))
        self.pause = tb("pause", "עצור הכול", "שום עבודה חדשה לא מתחילה עד שתמשיך", "tbpause", True)
        self.pause.clicked.connect(lambda on: self.api({"op": "pause"} if on else {"op": "resume"}))
        adv = tb("gear", "מתקדם", "מגבלות, הפעלה עם Windows, חיבור ל-Claude Code, יומן")
        adv.clicked.connect(self.open_advanced)
        ask = tb("sparkles", "עוזר", "שיחה עם Claude בתוך התוכנה: שאלות על המחשב והמודלים, הרצת עבודות, והמלצה והורדה של מודלים (באישור שלך)", "tb")
        ask.clicked.connect(self.open_claude)
        for b_ in (ask, self.play, self.pause, adv):
            head.addWidget(b_)
        v.addWidget(bar)
        split = W.QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        body = W.QWidget()
        bl2 = W.QVBoxLayout(body)
        bl2.setContentsMargins(8, 8, 8, 6)
        bl2.addWidget(split)
        v.addWidget(body, 1)
        mp = self._panel()
        ml = W.QVBoxLayout(mp)
        ml.setContentsMargins(8, 12, 8, 8)
        t = W.QLabel("  מודלים ותוצאות")
        t.setObjectName("h2")
        ml.addWidget(t)
        self.model_list = W.QListWidget()
        self.model_list.setObjectName("models")
        self.model_list.setIconSize(QtCore.QSize(20, 20))
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.model_list.currentRowChanged.connect(self.on_model)
        self.model_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.model_list.customContextMenuRequested.connect(self.model_menu)
        self.model_list.itemDoubleClicked.connect(lambda it: self.open_folder(it.data(Qt.UserRole)))
        ml.addWidget(self.model_list, 1)
        mp.setMinimumWidth(250)
        mp.setMaximumWidth(290)
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
        hw = W.QWidget()
        hl = W.QVBoxLayout(hw)
        hl.setContentsMargins(0, 6, 0, 0)
        hb = W.QHBoxLayout()
        rb = W.QPushButton("הרץ שוב עם אותן הגדרות")
        rb.setObjectName("tool")
        rb.clicked.connect(self.hist_rerun)
        ob = W.QPushButton("פתח את תיקיית התוצאה")
        ob.setObjectName("tool")
        ob.clicked.connect(lambda: self.hist_open(self.hist.currentItem()) if self.hist.currentItem() else None)
        hb.addWidget(rb)
        hb.addWidget(ob)
        hb.addStretch(1)
        hint = W.QLabel("לחיצה כפולה על שורה פותחת את התיקייה")
        hint.setObjectName("muted")
        hb.addWidget(hint)
        hl.addLayout(hb)
        self.hist.setContextMenuPolicy(Qt.CustomContextMenu)
        self.hist.customContextMenuRequested.connect(self.hist_menu)
        hl.addWidget(self.hist, 1)
        self.tabs.addTab(hw, "היסטוריה")
        tl.addWidget(self.tabs)
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
        self.files.itemDoubleClicked.connect(lambda it: self.open_file(it.data(Qt.UserRole)))
        self.files.itemClicked.connect(lambda it: self.open_submit(self.model_first_type()) if it.data(Qt.UserRole) == "__new__" else None)
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        ol.addWidget(self.files, 1)
        self.files_empty = W.QLabel("")
        self.files_empty.setObjectName("muted")
        self.files_empty.setAlignment(Qt.AlignCenter)
        ol.addWidget(self.files_empty)
        self.chat = ChatPanel(self)
        self.assistant_panel = AssistantPanel(self)
        self.lower = W.QStackedWidget()
        self.lower.addWidget(outp)
        self.lower.addWidget(self.chat)
        self.lower.addWidget(self.assistant_panel)
        cs.addWidget(self.lower)
        cs.addWidget(top)
        cs.setSizes([600, 170])
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
        for key, label, lo, hi in (("ram_gb", "RAM ל-AI", 4, 62), ("vram_gb", "GPU ל-AI", 2, 16), ("max_jobs", "עבודות במקביל", 1, 8), ("reserve_ram_gb", "RAM שנשאר פנוי", 0, 24), ("disk_busy_pct", "עומס דיסק מרבי", 50, 100)):
            row = W.QHBoxLayout()
            lab = W.QLabel(label)
            s = W.QSlider(Qt.Horizontal)
            s.setLayoutDirection(Qt.LeftToRight)
            s.setRange(lo, hi)
            val = W.QLabel("")
            val.setMinimumWidth(52)
            val.setStyleSheet("font-weight:600;")
            s.valueChanged.connect(lambda x, l=val, k=key: l.setText(fmt_limit(k, x)))
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
        split.setSizes([260, 720, 280])
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

    def open_file(self, path):
        """Open a result: a 3D model opens the in-app turntable (never an external program); everything else opens normally."""
        if not path or path == "__new__":
            return
        if path.lower().endswith(".glb") and glb_frames(path):
            TurntableDialog(self, path).exec()
        else:
            os.startfile(path)

    def request_preview(self, glb):
        if glb in self.preview_asked:
            return
        self.preview_asked.add(glb)
        self.api({"op": "preview", "path": glb})

    def glb_tile(self, glb):
        """A 3D model in a chat bubble: its preview picture (click = spin it), or a placeholder while the preview is being made."""
        pv = Path(glb).parent / "preview" / "preview.png"
        if pv.exists():
            pm = QtGui.QPixmap(str(pv))
            if not pm.isNull():
                t = Thumb(pm.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation), glb, on_click=lambda: self.open_file(glb))
                t.setToolTip("לחץ כדי לסובב את הדגם\n" + glb)
                return t
        self.request_preview(glb)
        t = Thumb(symbol_pixmap("⬢", "#2aa198", 120), glb)
        t.setToolTip("יוצר תצוגה מקדימה… (כמה שניות)\n" + glb)
        return t

    def model_first_type(self, od=None):
        od = od if od is not None else self.sel_model
        g = next((m for m in self.models if m["dir"] == od), None)
        return g["tids"][0] if g else None

    def model_menu(self, pos):
        it = self.model_list.itemAt(pos)
        if not it:
            return
        od = it.data(Qt.UserRole)
        m = W.QMenu(self)
        m.addAction("פתח את תיקיית הפלט", lambda: self.open_folder(od))
        if od:
            m.addAction("עבודה חדשה במודל הזה", lambda: self.open_submit(self.model_first_type(od)))
        m.exec(self.model_list.viewport().mapToGlobal(pos))

    def open_folder(self, od):
        d = Path(self.output_root) / od if od else Path(self.output_root)
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        """Drop a file anywhere on the window: opens the new-job dialog with that file filled in."""
        for u in e.mimeData().urls():
            if u.isLocalFile():
                path = u.toLocalFile().replace("\\", "/")
                pre = self.model_first_type()
                if pre and (self.types.get(pre, {}).get("chat") or {}).get("file"):
                    self.chat.set_attached(path)
                    return
                if not pre:
                    pre = "qwen_image_edit" if Path(path).suffix.lower() in IMG else None
                self.open_submit(pre, path)
                break

    def rerun_job(self, jid):
        r = self.api({"op": "rerun", "id": jid})
        if r and r.get("ok"):
            self.statusBar().showMessage("נוספה עבודה חוזרת מספר %d" % r["id"], 5000)
            self.tabs.setCurrentIndex(0)

    def open_submit(self, preselect=None, prefill=None):
        if not self.types:
            return
        dlg = SubmitDialog(self, self.types, preselect, prefill)
        if dlg.exec() == W.QDialog.Accepted:
            r = self.api(dlg.request())
            if r and r.get("ok"):
                self.statusBar().showMessage("נוספה עבודה מספר %d" % r["id"], 5000)
                self.tabs.setCurrentIndex(0)

    def open_claude(self):
        self.model_list.setCurrentRow(0)          # the assistant is the first entry of the list

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
            if t.get("hidden"):
                continue
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
        it = W.QListWidgetItem("  עוזר Claude")
        it.setData(Qt.UserRole, "__assistant__")
        it.setIcon(sym_icon("✧", "#3574f0", 20))
        self.model_list.addItem(it)
        it = W.QListWidgetItem("  הכול")
        it.setData(Qt.UserRole, None)
        it.setIcon(sym_icon("▤", "#b4b8bf", 20))
        self.model_list.addItem(it)
        for g in self.models:
            n = self.count_outputs(g["dir"])
            it = W.QListWidgetItem("  %s%s" % (g["title"], ("   (%d)" % n) if n else ""))
            it.setData(Qt.UserRole, g["dir"])
            it.setIcon(sym_icon(g["sym"], g["color"], 20))
            self.model_list.addItem(it)
        sel = 1
        want = "__assistant__" if self.assistant_mode else cur
        for i in range(self.model_list.count()):
            if self.model_list.item(i).data(Qt.UserRole) == want:
                sel = i
        self.model_list.setCurrentRow(sel)
        self.model_list.blockSignals(False)
        self.on_model(sel)

    def on_model(self, row):
        if row < 0:
            return
        data = self.model_list.item(row).data(Qt.UserRole)
        self.assistant_mode = data == "__assistant__"
        self.sel_model = None if self.assistant_mode else data
        self.files_sig = None
        self.lower.setCurrentIndex(2 if self.assistant_mode else (1 if self.sel_model else 0))
        sp = self.lower.parent()
        if isinstance(sp, W.QSplitter):
            sp.setSizes([640, 120] if self.assistant_mode else ([600, 150] if self.sel_model else [400, 300]))
        self.chat.set_attached(None)
        self.refresh_files()
        self.refresh_chat(force=True)

    def model_jobs(self):
        """Every job of the selected model, oldest first (running + waiting + finished)."""
        g = next((m for m in self.models if m["dir"] == self.sel_model), None)
        if not g:
            return []
        tids = set(g["tids"])
        seen, out = set(), []
        s = self.state or {}
        for j in list(self.hist_jobs) + s.get("running", []) + s.get("queued", []):
            if j["type"] in tids and j["id"] not in seen:
                seen.add(j["id"])
                out.append(j)
        return sorted(out, key=lambda j: j["id"])

    def refresh_chat(self, force=False):
        if self.sel_model and self.models:
            self.chat.build(force)

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
                if os.path.basename(root) == "preview":
                    continue
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
        if ext == ".glb":
            pv = fp.parent / "preview" / "preview.png"
            if pv.exists():
                img = QtGui.QImage(str(pv))
                if not img.isNull():
                    icon = QtGui.QIcon(QtGui.QPixmap.fromImage(img.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                    self.thumb_cache[key] = icon
                    return icon
            self.request_preview(str(fp))
        if icon is None and ext in IMG and fp.stat().st_size < 25e6:
            img = QtGui.QImage(str(fp))
            if not img.isNull():
                icon = QtGui.QIcon(QtGui.QPixmap.fromImage(img.scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        if icon is None:
            sym, col = KIND.get(ext, ("▫", "#868a91"))
            icon = QtGui.QIcon(symbol_pixmap(sym, col, 110))
        if len(self.thumb_cache) > 400:
            self.thumb_cache.clear()
        self.thumb_cache[key] = icon
        return icon

    def refresh_files(self):
        if not self.models:
            return
        if self.sel_model:
            self.refresh_chat()
            self.out_path.setText(str(self.model_folder()))
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
        self.files_empty.setText("עוד אין תוצאות. כשעבודה תסתיים, הקבצים יופיעו כאן.")
        self.files_empty.setVisible(not files)
        for i in range(2, self.model_list.count()):
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
        if fp == "__new__":
            return
        m = W.QMenu(self)
        m.addAction("פתח", lambda: os.startfile(fp))
        m.addAction("פתח את תיקיית העבודה", lambda: os.startfile(str(Path(fp).parent)))
        m.addAction("העתק נתיב", lambda: W.QApplication.clipboard().setText(fp))
        rj = Path(fp).parent / "result.json"
        if rj.exists():
            try:
                jid = json.loads(rj.read_text(encoding="utf-8"))["job_id"]
                m.addAction("הרץ שוב את העבודה שיצרה את הקובץ", lambda: self.rerun_job(jid))
            except (OSError, ValueError, KeyError):
                pass
        m.exec(self.files.viewport().mapToGlobal(pos))

    def hist_rerun(self):
        rows = sorted({i.row() for i in self.hist.selectedIndexes()})
        if not rows or rows[0] >= len(self.hist_jobs):
            self.statusBar().showMessage("בחר קודם עבודה בהיסטוריה", 4000)
            return
        for r in rows:
            self.rerun_job(self.hist_jobs[r]["id"])

    def hist_menu(self, pos):
        if not self.hist.selectedIndexes():
            return
        m = W.QMenu(self)
        m.addAction("הרץ שוב עם אותן הגדרות", self.hist_rerun)
        m.addAction("פתח את תיקיית התוצאה", lambda: self.hist_open(self.hist.currentItem()) if self.hist.currentItem() else None)
        m.exec(self.hist.viewport().mapToGlobal(pos))

    def hist_open(self, item):
        r = item.row()
        if r < len(self.hist_jobs) and self.hist_jobs[r].get("outdir") and os.path.isdir(self.hist_jobs[r]["outdir"]):
            os.startfile(self.hist_jobs[r]["outdir"])

    # ------------------------------------------------------------ state
    def on_down(self, msg):
        self.set_head("#868a91", "השירות לא רץ", "הפעל מחדש עם AI_Broker.bat")

    def set_head(self, color, title, sub):
        self.dot.setStyleSheet("background:%s; border-radius:4px;" % color)
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
            self.set_head("#db5c5c", "המחשב בלחץ, עצרתי הכול", "מעט RAM פנוי. עבודות חדשות לא יתחילו עד שיירגע. " + counts)
        elif st == "PLAYING":
            self.set_head("#db5c5c", "אתה משחק / מקליט", "עבודות GPU מחכות. " + counts)
        elif st == "PAUSED":
            self.set_head("#e0a030", "הכול מושהה", "שום עבודה חדשה לא מתחילה. " + counts)
        elif f < 0.7:
            self.set_head("#5fad65", "פעיל", counts)
        elif f < 0.88:
            self.set_head("#e0a030", "פעיל", counts + "   •   RAM עמוס")
        else:
            self.set_head("#db5c5c", "RAM כמעט מלא", counts)
        self.play.setChecked(s["playing"])
        self.pause.setChecked(s["paused"])
        self.pause.setText("המשך" if s["paused"] else "עצור הכול")
        self.pause.setIcon(icon("play" if s["paused"] else "pause", "#b4b8bf", 16))
        self.building = True
        for k, (sl, val) in self.sl.items():
            if not sl.isSliderDown():
                sl.setValue(int(round(lim[k])))
                val.setText(fmt_limit(k, lim[k]))
        self.building = False
        self.fill_queue(s)
        self.refresh_chat()
        self.sb.setText("RAM פנוי: %.0f GB      Commit פנוי: %.0f GB%s" % (sy["ram_avail"], sy["commit_avail"], ("      נעילת GPU: " + {"ours": "אצל ה-broker", "foreign": "אצל תוכנה אחרת"}.get(s["lock"], s["lock"])) if s["lock"] != "none" else ""))
        if self.tray and st != self.last_status:
            self.tray.setIcon(make_icon({"ACTIVE": "#5fad65", "PAUSED": "#e0a030", "PLAYING": "#db5c5c", "BRAKE": "#db5c5c"}[st]))
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
                tm, ram = "%d שנ'" % j.get("elapsed", 0), ltr("%.1f GB" % j.get("cur_ws", 0))
                det = eta_text(j) or (ltr("GPU %.1f GB" % j["cur_vram"]) if j.get("cur_vram") else "")
            else:
                tm, ram, det = fmt_dur(time.time() - j["submitted"]), ltr("~%.0f GB" % j["est_ram"]), ("עצרת אותה בעצמך" if j.get("held") else he_reason(j.get("reason", "")))
            vals = [str(j["id"]), ttl, j["name"], j["requester"], STATE_HE.get(st, st), tm, ram, det]
            for c, v in enumerate(vals):
                it = q.item(r, c) or W.QTableWidgetItem()
                it.setText(v)
                it.setToolTip(v if c in (2, 7) else (("הערכה: " + j["est_source"]) if c == 6 else ""))
                if c == 1:
                    it.setIcon(sym_icon(sym, color, 16))
                elif c == 4:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(st, "#b4b8bf")))
                elif c == 7:
                    it.setForeground(QtGui.QColor("#e0a030" if j["state"] == "queued" and j.get("reason") else "#b4b8bf"))
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
            vals = [str(j["id"]), ttl, j["name"], j["requester"], STATE_HE.get(j["state"], j["state"]), fmt_dur(dur),
                    ltr("RAM %.1f GB   GPU %.1f GB" % (j.get("peak_ws") or 0, j.get("peak_vram") or 0))]
            for c, v in enumerate(vals):
                it = W.QTableWidgetItem(v)
                if c == 1:
                    it.setIcon(sym_icon(sym, color, 16))
                if c == 4:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(j["state"], "#b4b8bf")))
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
    try:                                         # own taskbar identity: the window icon (our logo) instead of the generic Python icon
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AIBroker.Window")
    except Exception:
        pass
    app = W.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.RightToLeft)
    f = app.font()
    f.setPointSize(10)
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
    if "--hidden" in argv and win.tray:
        pass                                    # started with Windows: stay in the tray, the service is running
    else:
        win.show()
    if "--assistant" in argv:
        QtCore.QTimer.singleShot(1200, win.open_claude)
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
