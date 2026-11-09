"""AI Broker window. Dark, calm, Hebrew (right-to-left).
Main window = Models (each with its own OUTPUT folder) | Queue + History + the selected model's OUTPUT browser | Resources + limits.
Jobs are submitted by Claude through MCP/CLI; the owner mostly watches. A small secondary "Submit job" button exists with minimal fields.
The window is only a client of the broker service: closing it never stops the queue.
  python -m aibroker.gui [--screenshot out.png] [--model <output_dir>] [--tab 0|1] [--size 1280x800] [--no-tray]"""
import json
import os
import re
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as W
from PySide6.QtCore import Qt

from . import i18n
from .i18n import T
from . import assistant, catalog, client, paths, permissions, system
from .theme import QSS, SYMBOL_ICON, dot_icon, icon, icon_pixmap, logo_pixmap, make_icon, qss, save_ico, style_titlebar, sym_icon, symbol_pixmap
from .kit import (Bar, Chip, Dot, FlowLayout, Gauge, MessageView, MiniGauge, ModelDelegate, NoticeBar, Palette, ROLE_COUNT, ROLE_KIND, ROLE_RUN, ROLE_WAIT, Seg, TaskWidget, ToolHeader, tool_button)

# look and feel (palette, icons, logo): see theme.py

SYM = {"🖼️": "✎", "🎨": "✦", "🧊": "⬢", "🗿": "◈", "🛠️": "⚒", "🧱": "▦", "🎵": "♪", "🔊": "♬", "🎮": "▷", "📸": "◎", "🎬": "▶", "🐍": "λ", "⚙️": "⚙"}
STATE_HE = {"running": T("רץ"), "paused": T("מוקפא"), "queued": T("ממתין"), "held": T("עצור"), "done": T("הצליח"), "failed": T("נכשל"), "cancelled": T("בוטל"), "lost": T("לא ידוע")}
STATE_COLOR = {"running": "#5fad65", "paused": "#e0a030", "queued": "#868a91", "held": "#e0a030", "done": "#5fad65", "failed": "#db5c5c", "cancelled": "#868a91", "lost": "#e0a030"}
HIDDEN_FILES = {"job.log", "result.json"}
IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
KIND = {".glb": ("⬢", "#2aa198"), ".gltf": ("⬢", "#2aa198"), ".obj": ("⬢", "#2aa198"), ".ogg": ("♪", "#43a047"), ".wav": ("♪", "#43a047"), ".flac": ("♪", "#43a047"),
        ".mp3": ("♪", "#43a047"), ".mp4": ("▶", "#c0392b"), ".json": ("≡", "#868a91"), ".txt": ("≡", "#868a91"), ".log": ("≡", "#868a91"), ".blend": ("⚒", "#e87d0d")}


def ltr(t):
    """keep numbers like '~7 GB' in reading order inside right-to-left text"""
    return "⁦%s⁩" % t         # a bidi ISOLATE: the neighbours cannot reorder it (Terminal Grid does the same with <bdi>)


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
    basis = T("חציון של %d ריצות") % n if n > 1 else T("ריצה קודמת אחת")
    if left > 0:
        return T("נשארו כ-%d שניות (%s)") % (round(left), basis) if left < 120 else T("נשארו כ-%d דקות (%s)") % (round(left / 60), basis)
    return T("לוקח יותר מהרגיל (בדרך כלל %d שניות)") % round(typ)


def fmt_size(n):
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%d KB" % max(1, n // 1000)


def loc(t, field, default=""):
    """A job type's text in the UI language: he_<field> or en_<field>, falling back to the plain English field of the job type file."""
    if i18n.lang() == "he":
        return t.get("he_" + field) or t.get(field) or default
    return t.get("en_" + field) or t.get(field) or default


def he_reason(r):
    if not r:
        return T("מתחיל תיכף")
    table = (("RAM budget", T("אין כרגע מספיק RAM פנוי לעבודה הזו")), ("VRAM budget", T("ה-GPU עסוק, מחכה שיתפנה מקום")), ("free RAM", T("ה-RAM של המחשב נמוך, מחכה")),
             ("free commit", T("ה-RAM של המחשב נמוך, מחכה")), ("paused", T("הכול מושהה")), ("I am playing", T("אתה משחק, עבודות GPU מחכות")), ("held by owner", T("עצרת אותה בעצמך")),
             ("max concurrent", T("כבר רצות הרבה עבודות במקביל")), ("another", T("עבודה מאותו סוג כבר רצה")), ("GPU lock", T("תוכנה אחרת משתמשת ב-GPU")),
             ("a self-locking", T("מצלמים עכשיו את המשחק")), ("visual run", T("עבודת GPU רצה עכשיו")), ("BRAKE", T("המחשב בלחץ, עצרתי הכול")),
             ("disk busy", T("הדיסק עסוק מדי, מחכה שיירגע")), ("starvation", T("העבודה הראשונה ממתינה הרבה זמן, אף אחת לא עוקפת אותה")), ("waiting for the job", T("מחכה לעבודה אחרת")), ("backfill", T("מחכה לעבודה שלפניה")))
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


class QueueTable(W.QTableWidget):
    COLS = ["#", T("סוג"), T("עבודה"), T("ביקש"), T("מצב"), T("זמן"), "RAM", T("פרטים")]
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
        for i, wd in enumerate((34, 124, 150, 80, 84, 52, 70)):
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


HE_FIELD = {"image": T("תמונה"), "image2": T("תמונה שנייה"), "instruction": T("מה לעשות בתמונה"), "out": T("קובץ יעד"), "ref": T("תמונת מקור"), "prompt": T("תיאור"), "scenario": T("שם התרחיש"),
            "script": T("קובץ סקריפט"), "outdir": T("תיקיית יעד"), "raw": T("הדגם הכבד"), "clean": T("הדגם הקל"), "jobs": T("קובץ רשימה (jobs.json)"), "depth": T("רמת פירוט"), "seed": "Seed",
            "steps": "Steps", "secs": T("אורך בשניות"), "args": T("פרמטרים נוספים"), "batch": T("קובץ אצווה"), "w": T("רוחב"), "h": T("גובה"), "megapix": T("מגה-פיקסל"), "threads": "Threads",
            "res": T("רזולוציה"), "names": T("שמות"), "extra": T("פרמטרים")}
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
        self.setWindowTitle(T("עבודה חדשה"))
        self.setMinimumWidth(560)
        self.lay = W.QVBoxLayout(self)
        self.lay.setSpacing(10)
        note = W.QLabel(T("בחר סוג, בחר קובץ (או גרור אותו לשדה), ולחץ הוסף. העבודה נכנסת לאותו תור ש-Claude משתמש בו, והתוצאה נשמרת לבד בתיקיית המודל."))
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.lay.addWidget(note)
        self.combo = W.QComboBox()
        for tid, t in sorted(types.items(), key=lambda kv: (kv[1].get("group", ""), kv[0])):
            if t.get("hidden"):
                continue
            self.combo.addItem(loc(t, "title") or tid, tid)
        if preselect:
            i = self.combo.findData(preselect)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.form = W.QFormLayout()
        self.form.addRow(T("סוג"), self.combo)
        self.name = W.QLineEdit()
        self.name.setPlaceholderText(T("שם קצר (לא חובה)"))
        self.form.addRow(T("שם"), self.name)
        self.lay.addLayout(self.form)
        self.main_box = W.QWidget()
        self.main_form = W.QFormLayout(self.main_box)
        self.main_form.setContentsMargins(0, 0, 0, 0)
        self.lay.addWidget(self.main_box)
        self.adv_btn = W.QPushButton(T("אפשרויות מתקדמות  ▾"))
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
        ok = W.QPushButton(T("הוסף לתור"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        no = W.QPushButton(T("ביטול"))
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
        self.where.setText(T("התוצאה תישמר ב: output\\%s\\<תאריך>_<שם>\\") % (t.get("output_dir") or tid))
        for k, spec in (t.get("params") or {}).items():
            d = spec.get("default") if isinstance(spec, dict) else spec
            req = isinstance(spec, dict) and spec.get("required")
            e = DropEdit("" if d is None else (json.dumps(d) if isinstance(d, (list, dict)) else str(d)))
            e.setLayoutDirection(Qt.LeftToRight)
            if k in FILE_FIELDS and self.prefill and not self.prefilled:
                e.setText(self.prefill)
                self.prefilled = True
            if k in FILE_FIELDS:
                e.setPlaceholderText(T("גרור לכאן קובץ או לחץ ״בחר״"))
            row = W.QHBoxLayout()
            row.addWidget(e, 1)
            if k in FILE_FIELDS:
                b = W.QPushButton(T("בחר…"))
                b.setObjectName("tool")
                b.clicked.connect(lambda _=False, ed=e: self.browse(ed))
                row.addWidget(b)
            (self.main_form if req else self.adv_form).addRow(HE_FIELD.get(k, k) + (" *" if req else ""), row)
            self.edits[k] = e
        if tid == "custom":
            e = W.QLineEdit()
            e.setLayoutDirection(Qt.LeftToRight)
            e.setPlaceholderText("python script.py --x 1")
            self.main_form.addRow(T("פקודה *"), e)
            self.edits["__cmd"] = e
        self.ram = W.QDoubleSpinBox()
        self.ram.setRange(0, 64)
        self.ram.setSuffix(" GB RAM")
        self.ram.setSpecialValueText(T("אוטומטי"))
        self.vram = W.QDoubleSpinBox()
        self.vram.setRange(0, 16)
        self.vram.setSuffix(" GB GPU")
        self.vram.setSpecialValueText(T("אוטומטי"))
        self.adv_form.addRow(T("משאבים"), self.ram)
        self.adv_form.addRow("", self.vram)
        self.first = W.QCheckBox(T("להריץ ראשונה"))
        self.adv_form.addRow("", self.first)

    def browse(self, ed):
        p, _ = W.QFileDialog.getOpenFileName(self, T("בחר קובץ"), ed.text())
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


class SettingsDialog(W.QDialog):
    """Settings (gear icon): language, behaviour, Claude (permission level and the connection to Claude Code), log and folders."""
    def toggle_autostart(self, on):
        ok = system.set_autostart(on)
        if not ok and on:
            W.QMessageBox.warning(self, T("הפעלה עם Windows"), T("לא הצלחתי ליצור את הקיצור בתיקיית ההפעלה."))

    def on_conn(self, state):
        self.connected = state
        self.conn_btn.setEnabled(state is not None)
        if state is None:
            self.conn_lbl.setText(T("לא הצלחתי לבדוק: הפקודה claude לא נמצאה."))
        elif state:
            self.conn_lbl.setText(T("מחובר: כל סשן חדש של Claude Code (גם של המשחק והמעבדה) רואה את הכלים של ה-broker ומריץ עבודות דרך התור."))
            self.conn_btn.setText(T("נתק את Claude Code"))
        else:
            self.conn_lbl.setText(T("לא מחובר. סוכנים של Claude Code עדיין יכולים להריץ עבודות כבדות בלי לעבור בתור."))
            self.conn_btn.setText(T("חבר את Claude Code"))

    def toggle_connection(self):
        if self.connected:
            if W.QMessageBox.question(self, T("ניתוק"), T("להסיר את החיבור של ה-broker מ-Claude Code?")) != W.QMessageBox.Yes:
                return
            ok, msg = system.unregister_claude()
        else:
            if W.QMessageBox.question(self, T("חיבור ל-Claude Code"),
                                      T("זה יוסיף את הכלים של ה-broker להגדרות של Claude Code אצלך (לכל הפרויקטים) ויעתיק קובץ הוראות לסוכנים. אפשר לנתק בכל רגע. להמשיך?")) != W.QMessageBox.Yes:
                return
            ok, msg = system.register_claude()
        self.conn_lbl.setText(msg)
        self.check = ConnCheck()
        self.check.done.connect(self.on_conn)
        self.check.start()

    def change_language(self):
        code = self.lang_box.currentData()
        if code == i18n.lang():
            return
        m = W.QMessageBox(self)
        m.setIcon(W.QMessageBox.Question)
        m.setWindowTitle(T("שפה"))
        m.setText(T("החלון ייפתח מחדש כדי להחליף שפה. העבודות ממשיכות לרוץ. להמשיך?"))
        yes = m.addButton(T("כן, החלף שפה"), W.QMessageBox.AcceptRole)
        m.addButton(T("ביטול"), W.QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is not yes:
            self.lang_box.blockSignals(True)
            self.lang_box.setCurrentIndex(max(0, self.lang_box.findData(i18n.lang())))
            self.lang_box.blockSignals(False)
            return
        self.main.set_language(code)

    def __init__(self, parent, tab=None):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle(T("הגדרות"))
        self.resize(760, 600)
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        tabs = W.QTabWidget()
        tabs.setDocumentMode(True)
        outer.addWidget(tabs, 1)
        self.tabs = tabs

        def page(title):
            w = W.QWidget()
            lay = W.QVBoxLayout(w)
            lay.setContentsMargins(6, 14, 6, 8)
            lay.setSpacing(9)
            tabs.addTab(w, title)
            return lay

        def head(lay, text, top=8):
            h = W.QLabel(text)
            h.setObjectName("h2")
            h.setContentsMargins(0, top, 0, 0)
            lay.addWidget(h)

        # ---- general
        g = page(T("כללי"))
        head(g, T("שפה"), 0)
        row = W.QHBoxLayout()
        self.lang_box = W.QComboBox()
        for code, name in i18n.LANGS:
            self.lang_box.addItem(name, code)
        self.lang_box.setCurrentIndex(max(0, self.lang_box.findData(i18n.lang())))
        self.lang_box.currentIndexChanged.connect(self.change_language)
        self.lang_box.setMinimumWidth(180)
        row.addWidget(self.lang_box)
        row.addStretch(1)
        g.addLayout(row)
        note = W.QLabel(T("שינוי שפה פותח את החלון מחדש. גם Claude בחלון ידבר בשפה שנבחרה."))
        note.setObjectName("muted")
        note.setWordWrap(True)
        g.addWidget(note)
        head(g, T("הפעלה"))
        self.auto = W.QCheckBox(T("להפעיל את התוכנה עם Windows (תעלה בשקט באזור ההודעות)"))
        self.auto.setChecked(system.autostart_enabled())
        self.auto.toggled.connect(self.toggle_autostart)
        g.addWidget(self.auto)
        c = W.QCheckBox(T("הודעה של Windows כשעבודה מסתיימת"))
        c.setChecked(bool(parent.state and parent.state["flags"].get("toast")))
        c.toggled.connect(lambda on: parent.api({"op": "limits", "flags": {"toast": on}}))
        g.addWidget(c)
        head(g, T("מודלים"))
        setup = W.QPushButton(T("התקנת מודלים והתקנה ראשונית…"))
        setup.clicked.connect(lambda: (self.accept(), parent.open_setup()))
        srow = W.QHBoxLayout()
        srow.addWidget(setup)
        srow.addStretch(1)
        g.addLayout(srow)
        head(g, T("תיקיות"))
        frow = W.QHBoxLayout()
        b = W.QPushButton(T("פתח את תיקיית הפלט"))
        b.clicked.connect(lambda: os.startfile(parent.output_root))
        frow.addWidget(b)
        b = W.QPushButton(T("פתח את תיקיית הנתונים"))
        b.clicked.connect(lambda: os.startfile(str(paths.HOME)))
        frow.addWidget(b)
        frow.addStretch(1)
        g.addLayout(frow)
        g.addStretch(1)

        # ---- behaviour
        bh = page(T("התנהגות"))
        for key, label in (("affinity", T("לקבץ עבודות שמשתמשות באותו מודל (חוסך זמן טעינה)")), ("backfill", T("לתת לעבודה קטנה לעקוף עבודה גדולה שמחכה")),
                           ("emergency_suspend", T("כשהמחשב בלחץ: להקפיא את העבודה האחרונה שהתחילה")), ("suspend_on_pause", T("״עצור הכול״ מקפיא גם עבודות שכבר רצות"))):
            cb = W.QCheckBox(label)
            cb.setChecked(bool(parent.state and parent.state["flags"].get(key)))
            cb.toggled.connect(lambda on, k=key: parent.api({"op": "limits", "flags": {k: on}}))
            bh.addWidget(cb)
        bh.addStretch(1)

        # ---- Claude
        cl = page("Claude")
        head(cl, T("רמת ההרשאות של Claude"), 0)
        lvl = W.QPushButton(T("שנה את רמת ההרשאות של Claude"))
        lvl.clicked.connect(lambda: (self.accept(), parent.assistant_panel.choose_level()))
        lrow = W.QHBoxLayout()
        lrow.addWidget(lvl)
        lrow.addStretch(1)
        cl.addLayout(lrow)
        head(cl, T("חיבור ל-Claude Code"))
        self.conn_lbl = W.QLabel(T("בודק…"))
        self.conn_lbl.setObjectName("muted")
        self.conn_lbl.setWordWrap(True)
        cl.addWidget(self.conn_lbl)
        crow = W.QHBoxLayout()
        self.conn_btn = W.QPushButton(T("חבר את Claude Code"))
        self.conn_btn.setEnabled(False)
        self.conn_btn.clicked.connect(self.toggle_connection)
        crow.addWidget(self.conn_btn)
        crow.addStretch(1)
        cl.addLayout(crow)
        cl.addStretch(1)
        self.connected = None
        self.check = ConnCheck()
        self.check.done.connect(self.on_conn)
        self.check.start()

        # ---- log
        lg = page(T("יומן"))
        log = W.QPlainTextEdit()
        log.setReadOnly(True)
        log.setLayoutDirection(Qt.LeftToRight)
        log.setPlainText(parent.log_text)
        lg.addWidget(log, 1)

        if tab == "claude":
            tabs.setCurrentIndex(2)
        close = W.QPushButton(T("סגור"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        brow = W.QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(close)
        outer.addLayout(brow)


class OutputDialog(W.QDialog):
    """The full output of one job (live while it runs)."""
    def __init__(self, parent, jid, title):
        super().__init__(parent)
        self.jid = jid
        self.setWindowTitle(T("פלט: ") + title)
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
            r = client.call({"op": "tail", "id": self.jid, "bytes": 60000}, timeout=3)
            if r.get("ok") and r["text"] != self.ed.toPlainText():
                bar = self.ed.verticalScrollBar()
                end = bar.value() >= bar.maximum() - 4
                self.ed.setPlainText(r["text"])
                if end:
                    bar.setValue(bar.maximum())
        except Exception:
            pass


def fmt_typical(sec):
    sec = float(sec or 0)
    return T("%d שניות") % round(sec) if sec < 90 else T("%.1f דקות") % (sec / 60.0)


def stats_line(tid, t, stats):
    """What this kind of job costs on THIS computer: from earlier runs, or the estimate when it never ran."""
    s_ = (stats or {}).get(tid)
    if s_ and s_.get("n"):
        gpu = (" · " + ltr("GPU %.0f GB" % s_["vram"])) if s_.get("vram", 0) >= 0.5 else ""
        return T("אצלך בדרך כלל: %s · %s%s · לפי %d ריצות") % (fmt_typical(s_["median_s"]), ltr("RAM %.0f GB" % s_["ram"]), gpu, s_["n"])
    est = t.get("est") or {}
    gpu = (" · " + ltr("GPU %.0f GB" % est["vram_gb"])) if est.get("vram_gb") else ""
    return T("עוד לא רץ אצלך. הערכה: %s%s") % (ltr("RAM %.0f GB" % est.get("ram_gb", 0)), gpu)


def kv_row(label, text, mono=False, width=46, key=False):
    h = W.QHBoxLayout()
    h.setSpacing(8)
    k = W.QLabel(label)
    k.setObjectName("muted")
    if key:
        k.setLayoutDirection(Qt.LeftToRight)
        k.setStyleSheet("font-family: Consolas; font-size: 9.5pt; color: #b4b8bf;")
    k.setFixedWidth(width)
    k.setAlignment(Qt.AlignTop | Qt.AlignRight)
    v = W.QLabel(text)
    v.setWordWrap(True)
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if mono:
        v.setLayoutDirection(Qt.LeftToRight)
        v.setStyleSheet("font-family: Consolas; font-size: 9.5pt; color: #b4b8bf; background: #1e1f22; border-radius: 4px; padding: 4px 8px;")
    h.addWidget(k)
    h.addWidget(v, 1)
    return h


def about_widget(g, types, stats):
    """Plain-language page for one model: what it is, what goes in, what comes out, an example, a tip, and what it costs on this machine."""
    w = W.QWidget()
    v = W.QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    many = len(g["tids"]) > 1
    for tid in g["tids"]:
        t = types.get(tid, {})
        ab = loc(t, "about") or None
        if not ab:
            continue
        if many:
            sub = W.QLabel(loc(t, "title") or tid)
            sub.setStyleSheet("font-weight:600; color:#dfe1e5; padding-top:6px;")
            v.addWidget(sub)
        what = W.QLabel(ab["what"])
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(what)
        v.addLayout(kv_row(T("נכנס"), ab["inp"]))
        v.addLayout(kv_row(T("יוצא"), ab["out"]))
        if ab.get("example"):
            v.addLayout(kv_row(T("דוגמה"), ab["example"], mono=ab["example"].isascii()))
        if ab.get("tip"):
            tip = W.QLabel(ab["tip"])
            tip.setObjectName("muted")
            tip.setWordWrap(True)
            v.addWidget(tip)
        st = W.QLabel(stats_line(tid, t, stats))
        st.setObjectName("muted")
        st.setStyleSheet("color:#868a91; font-size:9pt;")
        v.addWidget(st)
    return w


class AboutDialog(W.QDialog):
    def __init__(self, main, g):
        super().__init__(main)
        self.setWindowTitle(g["title"])
        self.setMinimumWidth(560)
        v = W.QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(12)
        top = W.QHBoxLayout()
        ic = W.QLabel()
        ic.setPixmap(symbol_pixmap(g["sym"], g["color"], 44))
        t = W.QLabel(g["title"])
        t.setObjectName("h1")
        top.addWidget(ic)
        top.addWidget(t, 1)
        v.addLayout(top)
        v.addWidget(about_widget(g, main.types, main.type_stats))
        cfg = (main.types.get(g["tids"][0], {}).get("chat") or {})
        if cfg:
            kl = W.QLabel(T("קיצורים בתיבת הכתיבה"))
            kl.setObjectName("h2")
            v.addWidget(kl)
            for key_, what_ in (("Enter", T("שולח")), ("Shift+Enter", T("שורה חדשה")), ("Ctrl+V", T("מדביק תמונה מהלוח")), ("↑", T("מחזיר את ההודעה הקודמת")), (T("גרירה"), T("גרירת קובץ לחלון מצרפת אותו"))):
                v.addLayout(kv_row(key_, what_, width=96, key=key_.isascii()))
        b = W.QPushButton(T("סגור"))
        b.clicked.connect(self.accept)
        v.addWidget(b, 0, Qt.AlignLeft)


class Thumb(W.QLabel):
    """A clickable picture or file tile inside a chat bubble."""
    def __init__(self, pixmap, path, size=150, on_click=None, on_menu=None):
        super().__init__()
        self.path = path
        self.on_click = on_click
        self.on_menu = on_menu
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(path)
        self.setStyleSheet("border-radius:8px;")

    def contextMenuEvent(self, e):
        if self.on_menu:
            self.on_menu(e.globalPos())

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
        hint = W.QLabel(T("גרור עם העכבר כדי לסובב. הדגם מוצג בלי צבע (חומר אפור) כדי לראות את הצורה."))
        hint.setObjectName("muted")
        v.addWidget(hint)
        row = W.QHBoxLayout()
        b = W.QPushButton(T("פתח את הקובץ"))
        b.clicked.connect(lambda: os.startfile(self.glb))
        c = W.QPushButton(T("פתח תיקייה"))
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


def centered(widget):
    row = W.QWidget()
    h = W.QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.addStretch(1)
    h.addWidget(widget)
    h.addStretch(1)
    return row


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


def aligned_start(bubble):
    """Anchor a bubble to the START side of the window (the right edge in Hebrew), whoever speaks: a Hebrew conversation is read from the right.
    Who is speaking is shown by the colour of the bubble and its header, not by the side."""
    row = W.QWidget()
    h = W.QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(bubble)
    h.addStretch(1)
    return row


class Bubble(W.QFrame):
    def __init__(self, who, max_width=640):
        super().__init__()
        self.who = who
        self.setObjectName("bubble_user" if who == "user" else "bubble_model")
        self.lay = W.QVBoxLayout(self)
        self.lay.setContentsMargins(14, 10, 14, 10)
        self.lay.setSpacing(8)
        self.setMinimumWidth(300)
        self.setMaximumWidth(max_width)
        self.max_width = max_width

    def message(self, t, markdown=False, muted=False, bold=False):
        """Message text with a direction per paragraph (majority script): Hebrew with English names and numbers inside reads correctly."""
        v = MessageView(t, markdown=markdown, max_width=self.max_width - 30, muted=muted, bold=bold)
        self.lay.addWidget(v)
        return v

    def header(self, name, icon_name=None, when="", color="#b4b8bf", chip=None):
        """Who is speaking: small icon, name, then the time (and a status chip at the end)."""
        h = W.QHBoxLayout()
        h.setSpacing(6)
        if icon_name:
            ic = W.QLabel()
            ic.setPixmap(icon(icon_name, color, 14).pixmap(14, 14))
            h.addWidget(ic)
        n = W.QLabel(name)
        n.setStyleSheet("font-weight:600; font-size:9pt; color:%s;" % color)
        h.addWidget(n)
        if when:
            w = W.QLabel(when)
            w.setObjectName("muted")
            w.setStyleSheet("font-size:8.5pt;")
            w.setLayoutDirection(Qt.LeftToRight)
            h.addWidget(w)
        h.addStretch(1)
        if chip is not None:
            h.addWidget(chip)
        self.lay.insertLayout(0, h)

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
    """A normal chat with one model: you write (or drop / paste a file), the model answers with its result. Built from the job history of that model."""
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("editor")
        self.attached = None
        self.sig = None
        self.fail_cache = {}
        self.recall, self.recall_i = [], -1
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.th = ToolHeader("", "image")
        self.title, self.path = self.th.title, self.th.sub
        self.th.add_action("folder", T("פתח את תיקיית התוצאות"), main.open_model_folder)
        self.th.add_action("help", T("איך זה עובד?"), lambda: self.explain())
        outer.addWidget(self.th)
        bodyw = W.QWidget()
        v = W.QVBoxLayout(bodyw)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        outer.addWidget(bodyw, 1)
        self.scroll = W.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(W.QFrame.NoFrame)
        self.body = W.QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.col = W.QVBoxLayout(self.body)
        self.col.setContentsMargins(0, 0, 6, 0)
        self.col.setSpacing(12)
        self.scroll.setWidget(self.body)
        v.addWidget(self.scroll, 1)
        self.comp = W.QFrame()
        self.comp.setObjectName("composer")
        cl = W.QVBoxLayout(self.comp)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        self.chips = W.QHBoxLayout()
        cl.addLayout(self.chips)
        self.drop_zone = W.QLabel()
        self.drop_zone.setAlignment(Qt.AlignCenter)
        self.drop_zone.setMinimumHeight(64)
        self.drop_zone.setStyleSheet("border: 1px dashed #4e5157; border-radius: 6px; color: #868a91; padding: 12px;")
        cl.addWidget(self.drop_zone)
        self.edit = W.QPlainTextEdit()
        self.edit.setFixedHeight(58)
        self.edit.setLayoutDirection(Qt.LeftToRight)
        self.edit.setStyleSheet("QPlainTextEdit { background: transparent; border: none; color: #dfe1e5; font-family: 'Segoe UI'; font-size: 10.5pt; }")
        self.edit.setPlaceholderText(T("כתוב כאן מה לעשות…"))
        self.edit.installEventFilter(self)
        cl.addWidget(self.edit)
        row = W.QHBoxLayout()
        row.setSpacing(4)
        self.hint_lbl = W.QLabel(T("Enter לשליחה   ·   Shift+Enter שורה חדשה   ·   Ctrl+V הדבקת תמונה"))
        self.hint_lbl.setObjectName("muted")
        self.attach_btn = tool_button("clip", T("צרף קובץ"), self.pick)
        self.adv_btn = tool_button("gear", T("אפשרויות מתקדמות"), lambda: main.open_submit(main.model_first_type(), self.attached))
        self.send_btn = W.QPushButton(T("שלח"))
        self.send_btn.setObjectName("primary")
        self.send_btn.setIcon(icon("send", "#ffffff", 16))
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.hint_lbl)
        row.addStretch(1)
        row.addWidget(self.adv_btn)
        row.addWidget(self.attach_btn)
        row.addWidget(self.send_btn)
        cl.addLayout(row)
        v.addWidget(self.comp)
        self.setAcceptDrops(True)

    # --- input
    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
            k, mod = ev.key(), ev.modifiers()
            if k in (Qt.Key_Return, Qt.Key_Enter) and not (mod & Qt.ShiftModifier):
                self.send()
                return True
            if ev.matches(QtGui.QKeySequence.Paste) and self.paste_attachment():
                return True
            if k == Qt.Key_Up and self.recall and (not self.edit.toPlainText().strip() or self.recall_i >= 0):
                self.recall_i = min(self.recall_i + 1, len(self.recall) - 1)
                self.edit.setPlainText(self.recall[-1 - self.recall_i])
                return True
            if k == Qt.Key_Down and self.recall_i >= 0:
                self.recall_i -= 1
                self.edit.setPlainText(self.recall[-1 - self.recall_i] if self.recall_i >= 0 else "")
                return True
            if k == Qt.Key_Escape and self.attached:
                self.set_attached(None)
                return True
        return super().eventFilter(obj, ev)

    def paste_attachment(self):
        tid, cfg = self.cfg()
        if not (cfg and cfg.get("file")):
            return False
        cb = W.QApplication.clipboard()
        md = cb.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    self.set_attached(u.toLocalFile().replace("\\", "/"))
                    return True
        if md.hasImage():
            img = cb.image()
            if not img.isNull():
                d = paths.HOME / "pasted"
                d.mkdir(parents=True, exist_ok=True)
                fp = d / ("paste_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
                img.save(str(fp))
                self.set_attached(str(fp).replace("\\", "/"))
                self.main.toast(T("התמונה הודבקה"), "ok")
                return True
        return False

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
        p, _ = W.QFileDialog.getOpenFileName(self, T("בחר קובץ"))
        if p:
            self.set_attached(p)

    def set_attached(self, path):
        self.attached = path
        tid, cfg = self.cfg()
        if cfg and not cfg.get("text"):
            self.drop_zone.setText((T("נבחרה תמונה: ") + Path(path).name + T("   (לחץ ״צור דגם 3D״)")) if path else T("גרור לכאן תמונה, הדבק (Ctrl+V), או לחץ על הסיכה"))
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if path:
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                t = W.QLabel()
                t.setPixmap(pm.scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.chips.addWidget(t)
            lab = W.QLabel(Path(path).name)
            lab.setObjectName("muted")
            lab.setLayoutDirection(Qt.LeftToRight)
            self.chips.addWidget(lab)
            self.chips.addWidget(tool_button("x", T("הסר את הקובץ (Esc)"), lambda: self.set_attached(None), size=13))
            self.chips.addStretch(1)

    def explain(self):
        g = next((x for x in self.main.models if x["dir"] == self.main.sel_model), None)
        if g:
            AboutDialog(self.main, g).exec()

    def cfg(self):
        tid = self.main.model_first_type()
        return tid, (self.main.types.get(tid, {}).get("chat") if tid else None)

    def last_result_image(self):
        best = None
        for j in self.main.model_jobs():
            d = j.get("outdir")
            if j["state"] == "done" and d and os.path.isdir(d):
                for n in sorted(os.listdir(d)):
                    if Path(n).suffix.lower() in IMG and n != "ref_rgba.png":
                        best = os.path.join(d, n).replace("\\", "/")
        return best

    def send_to_assistant(self):
        text = self.edit.toPlainText().strip()
        if not text:
            self.main.toast(T("כתוב מה תרצה שיעשו"), "warn")
            return
        m = self.main
        g = next((x for x in m.models if x["dir"] == m.sel_model), None)
        f = self.attached
        msg = T("המשתמש פתח את דף המודל ״%s״ (סוגי עבודה בתור: %s) ומבקש: %s") % (g["title"] if g else "", ", ".join(g["tids"]) if g else "", text)
        if f:
            msg += chr(10) + T("קובץ מצורף: ") + f
        msg += chr(10) + T("הפעל את זה דרך ה-broker (submit_job). אם חסר מידע, שאל אותי בקצרה. התוצאות נשמרות בתיקיית המודל ומופיעות בדף שלו.")
        self.edit.clear()
        self.set_attached(None)
        m.ask_assistant(text + (("   (+ %s)" % Path(f).name) if f else ""), msg)

    def send(self):
        tid, cfg = self.cfg()
        if not cfg:
            return self.send_to_assistant()
        text = self.edit.toPlainText().strip()
        params = {}
        if cfg.get("text"):
            if not text:
                self.main.toast(T("כתוב מה לעשות"), "warn")
                return
            params[cfg["text"]] = text
        f = self.attached
        if cfg.get("file"):
            if not f and cfg.get("needs_file"):
                f = self.last_result_image()          # keep talking: the next message edits the last result
            if not f and cfg.get("needs_file"):
                self.main.toast(T("צרף קובץ: גרור, הדבק (Ctrl+V) או לחץ על הסיכה"), "warn")
                return
            if f:
                params[cfg["file"]] = f
        name = (text[:28] if text else Path(f or "job").stem[:28])
        r = self.main.api(dict(op="submit", type=tid, params=params, name=name, requester="owner"))
        if r and r.get("ok"):
            self.edit.clear()
            self.recall_i = -1
            self.set_attached(None)
            self.sig = None
            self.main.refresh_chat(force=True)

    # --- render
    def onboarding(self, g, cfg):
        card = W.QFrame()
        card.setObjectName("bubble_model")
        card.setMaximumWidth(760)
        card.setMinimumWidth(520)
        v = W.QVBoxLayout(card)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)
        top = W.QHBoxLayout()
        top.setSpacing(12)
        ic = W.QLabel()
        ic.setPixmap(symbol_pixmap(g["sym"], g["color"], 44))
        top.addWidget(ic)
        tcol = W.QVBoxLayout()
        tcol.setSpacing(0)
        t = W.QLabel(g["title"])
        t.setObjectName("h1")
        sub = W.QLabel(T("עוד לא נשלחו עבודות") if cfg else T("אין לו ממשק משלו: כתוב למטה מה תרצה, ו-Claude יפעיל אותו בשבילך"))
        sub.setObjectName("muted")
        tcol.addWidget(t)
        tcol.addWidget(sub)
        top.addLayout(tcol, 1)
        v.addLayout(top)
        v.addWidget(about_widget(g, self.main.types, self.main.type_stats))
        if cfg and cfg.get("examples"):
            lab = W.QLabel(T("דוגמאות, לחץ כדי להעתיק לתיבה:"))
            lab.setObjectName("muted")
            v.addWidget(lab)
            holder = W.QWidget()
            fl = FlowLayout(holder, 6)
            for ex in cfg["examples"]:
                btn = W.QPushButton(ex if len(ex) < 58 else ex[:56] + "…")
                btn.setObjectName("pill")
                btn.setToolTip(ex)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setLayoutDirection(Qt.LeftToRight)
                btn.clicked.connect(lambda _=False, e=ex: (self.edit.setPlainText(e), self.edit.setFocus()))
                fl.addWidget(btn)
            v.addWidget(holder)
        return card

    def build(self, force=False):
        m = self.main
        tid, cfg = self.cfg()
        g = next((x for x in m.models if x["dir"] == m.sel_model), None)
        if g:
            self.th.title.setText(g["title"])
            self.th.set_icon(SYMBOL_ICON.get(g["sym"], "doc"), g["color"])
        self.path.setText(str(m.model_folder()))
        jobs = m.model_jobs()
        sig = (m.sel_model, tuple((j["id"], j["state"], bool(j.get("held")), int(j.get("elapsed", 0)) // 5, len(self.outfiles(j)),
                                   sum(1 for f in self.outfiles(j) if f.lower().endswith(".glb") and (Path(f).parent / "preview" / "preview.png").exists())) for j in jobs), bool(cfg))
        if sig == self.sig and not force:
            return
        self.sig = sig
        while self.col.count():
            it = self.col.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        proxy = cfg is None            # no interface of its own: the request goes to Claude, who runs the model
        self.comp.setVisible(True)
        has_text = bool(cfg and cfg.get("text")) or proxy
        has_file = bool(cfg and cfg.get("file")) or proxy
        self.edit.setVisible(has_text)
        self.drop_zone.setVisible(bool(cfg) and not has_text)
        if cfg and not has_text and not self.attached:
            self.drop_zone.setText(T("גרור לכאן תמונה, הדבק (Ctrl+V), או לחץ על הסיכה"))
        self.attach_btn.setVisible(has_file)
        if proxy:
            self.send_btn.setText(T("בקש מ-Claude"))
            self.send_btn.setIcon(icon("sparkles", "#ffffff", 16))
            self.edit.setPlaceholderText(T("תאר מה תרצה לעשות עם %s, ו-Claude יפעיל את זה בשבילך…") % (g["title"] if g else T("המודל")))
        else:
            self.send_btn.setText(T("שלח") if has_text and has_file else (T("צייר") if has_text else T("צור דגם 3D")))
            self.send_btn.setIcon(icon("send", "#ffffff", 16))
            self.edit.setPlaceholderText(T("כתוב כאן מה לעשות…"))
        self.hint_lbl.setVisible(has_text)
        self.adv_btn.setVisible(has_text)
        if cfg and cfg.get("text"):
            self.recall = [str((j.get("params") or {}).get(cfg["text"]) or "") for j in jobs if (j.get("params") or {}).get(cfg["text"])]
        empty = not jobs and g
        if empty:
            self.col.addStretch(3)             # the start card floats a little above the middle of the free area, not glued to the top
            self.col.addWidget(centered(self.onboarding(g, cfg)))
        for j in jobs:
            self.add_job(j, cfg)
        self.col.addStretch(4 if empty else 1)
        if jobs:
            QtCore.QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        else:
            QtCore.QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(0))      # the start card is read from its top

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

    def fail_text(self, j):
        """The last meaningful lines of a failed job's output, shown right in the answer (no hunting through logs)."""
        jid = j["id"]
        if jid not in self.fail_cache:
            lines = []
            try:
                r = client.call({"op": "tail", "id": jid, "bytes": 3500}, timeout=3)
                lines = [l.strip() for l in (r.get("text") or "").splitlines() if l.strip() and not l.startswith("[broker]")]
            except Exception:
                pass
            self.fail_cache[jid] = "\n".join(lines[-4:])[-600:]
        return self.fail_cache[jid]

    def act_button(self, icon_name, text, slot, tip=None):
        b = W.QPushButton(text)
        b.setObjectName("flat")
        b.setIcon(icon(icon_name, "#868a91", 14))
        b.setIconSize(QtCore.QSize(14, 14))
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def add_job(self, j, cfg):
        m = self.main
        params = j.get("params") or {}
        sym, color, ttl = m.type_info(j["type"])
        when = time.strftime("%H:%M", time.localtime(j["submitted"])) if j.get("submitted") else ""
        u = Bubble("user")
        u.header(T("אתה") if j["requester"] == "owner" else j["requester"], "user", "#%d   %s" % (j["id"], when))
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
        self.col.addWidget(aligned(u, "user"))
        st = "held" if j["state"] == "queued" and j.get("held") else ("paused" if j.get("suspended") else j["state"])
        dur = (j.get("finished") or 0) - (j.get("started") or j.get("finished") or 0)
        chip = {"done": Chip(T("הושלם  %s") % fmt_dur(dur), "ok"), "failed": Chip(T("נכשל"), "bad"), "cancelled": Chip(T("בוטל"), "muted"), "lost": Chip(T("לא ידוע"), "warn"),
                "running": Chip(T("רץ  %s") % fmt_dur(j.get("elapsed", 0)), "info"), "paused": Chip(T("מוקפא"), "warn"), "queued": Chip(T("ממתין"), "muted"), "held": Chip(T("עצור"), "warn")}.get(st)
        a = Bubble("model")
        a.header(ttl, SYMBOL_ICON.get(sym, "doc"), "", color, chip)
        images = []
        if st in ("queued", "held"):
            a.text(T("עצרת אותה בעצמך") if st == "held" else he_reason(j.get("reason", "")), muted=True)
        elif st in ("running", "paused"):
            a.text(T("RAM %s   •   עברו %d שניות") % (ltr("%.1f GB" % j.get("cur_ws", 0)), j.get("elapsed", 0)), muted=True)
            pb = W.QProgressBar()
            pb.setTextVisible(False)
            pb.setFixedHeight(4)
            typ = j.get("typical_s")
            if typ and st == "running":
                pb.setRange(0, 100)
                pb.setValue(min(95, int(100 * j.get("elapsed", 0) / typ)))
                a.text(eta_text(j), muted=True)
            else:
                pb.setRange(0, 0)
                a.text(T("עדיין אין נתונים על ריצות קודמות, אז אין הערכת זמן"), muted=True)
            a.lay.addWidget(pb)
        elif st == "done":
            tiles = []
            for f in self.outfiles(j)[:8]:
                if Path(f).suffix.lower() in IMG:
                    pm = QtGui.QPixmap(f)
                    if not pm.isNull():
                        images.append(f)
                        tiles.append(Thumb(pm.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation), f, on_menu=lambda pos, p=f: m.send_menu(p, pos)))
                        continue
                if f.lower().endswith(".glb"):
                    tiles.append(m.glb_tile(f))
                    continue
                s2, col = KIND.get(Path(f).suffix.lower(), ("▫", "#868a91"))
                t = Thumb(symbol_pixmap(s2, col, 84), f)
                t.setToolTip(f)
                tiles.append(t)
            if tiles:
                a.row(tiles)
                names = W.QLabel("   ".join(Path(f).name for f in self.outfiles(j)[:4]))
                names.setObjectName("muted")
                names.setLayoutDirection(Qt.LeftToRight)
                a.lay.addWidget(names)
        else:
            if st == "failed":
                ft = self.fail_text(j)
                if ft:
                    box = W.QLabel(ft)
                    box.setWordWrap(True)
                    box.setLayoutDirection(Qt.LeftToRight)
                    box.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    box.setStyleSheet("font-family: Consolas; font-size: 9pt; color: #db5c5c; background: #1e1f22; border-radius: 4px; padding: 6px 8px;")
                    a.lay.addWidget(box)
            elif st == "cancelled":
                a.text(T("העבודה בוטלה."), muted=True)
        row = W.QHBoxLayout()
        row.setSpacing(2)
        if st in ("done", "failed", "cancelled"):
            row.addWidget(self.act_button("refresh", T("הרץ שוב"), lambda _=False, i=j["id"]: m.rerun_job(i), T("אותן הגדרות, תיקייה חדשה")))
            if j.get("outdir"):
                row.addWidget(self.act_button("folder", T("תיקייה"), lambda _=False, d=j["outdir"]: os.startfile(d) if os.path.isdir(d) else None))
            if images:
                row.addWidget(self.act_button("arrow", T("שלח אל…"), lambda _=False, p=images[0]: m.send_menu(p, QtGui.QCursor.pos()), T("המשך עם התמונה במודל אחר")))
            if st == "failed":
                row.addWidget(self.act_button("doc", T("פלט מלא"), lambda _=False, i=j["id"], n=j["name"]: m.show_output(i, n)))
        if st in ("queued", "held", "running", "paused"):
            row.addWidget(self.act_button("x", T("בטל"), lambda _=False, i=j["id"]: m.api({"op": "cancel", "id": i})))
        row.addStretch(1)
        a.lay.addLayout(row)
        self.col.addWidget(aligned(a, "model"))


class AssistantPanel(W.QFrame):
    """Claude inside the window: a normal chat. No terminal is ever shown. Questions about the machine and models, requests to run jobs, and (with in-chat approval) downloads."""
    EXAMPLES = [T("מה מותקן אצלי ומה אפשר להריץ?"), T("איזה מודל תמונות כדאי לי להוריד, ולמה?"), T("למה העבודה האחרונה לקחה כל כך הרבה זיכרון?"), T("כמה מקום פנוי יש לי בדיסק למודלים?")]

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
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        th = ToolHeader(T("עוזר Claude"), "sparkles", "")
        self.model_box = W.QComboBox()
        for key, label in (("haiku", T("מהיר וזול (Haiku)")), ("sonnet", T("חכם יותר (Sonnet)")), ("default", T("ברירת מחדל של החשבון"))):
            self.model_box.addItem(label, key)
        i = self.model_box.findData(self.qs.value("model", "haiku"))
        self.model_box.setCurrentIndex(max(0, i))
        self.model_box.currentIndexChanged.connect(lambda: self.qs.setValue("model", self.model_box.currentData()))
        self.level = permissions.DEFAULT_LEVEL
        self.perm_cards = {}
        self.level_btn = W.QPushButton()
        self.level_btn.setObjectName("tool")
        self.level_btn.setIcon(icon("shield", "#b4b8bf", 15))
        self.level_btn.clicked.connect(self.choose_level)
        self.set_level_label()
        th.h.addWidget(self.level_btn)
        th.h.addWidget(self.model_box)
        th.add_action("refresh", T("שיחה חדשה"), self.reset)
        outer.addWidget(th)
        bodyw = W.QWidget()
        v = W.QVBoxLayout(bodyw)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        outer.addWidget(bodyw, 1)
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
        self.edit.setPlaceholderText(T("כתוב לעוזר…  (Enter לשליחה)"))
        self.edit.setStyleSheet("QPlainTextEdit { background: transparent; border: none; color: #dfe1e5; font-family: 'Segoe UI'; font-size: 10.5pt; }")
        self.edit.installEventFilter(self)
        cl.addWidget(self.edit)
        row = W.QHBoxLayout()
        self.send_btn = W.QPushButton(T("שלח"))
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.on_send_click)
        self.send_btn.setIcon(icon("send", "#ffffff", 16))
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
        b = Bubble("user" if role == "user" else "model", 600 if role == "user" else 860)
        b.header(T("אתה") if role == "user" else "Claude", "user" if role == "user" else "sparkles")
        b.message(text, markdown=md)
        self.col.insertWidget(self.col.count() - 1, aligned_start(b))
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
        w = Bubble("model", 860)
        w.message(T("שלום. אני העוזר של התוכנה. אני רואה את התור, המשאבים והתוצאות, יכול להריץ עבודות בשבילך, ולעזור לבחור ולהוריד מודלים (הורדה רק אחרי שתאשר כאן בצ'אט). שאל אותי משהו, או לחץ על דוגמה:"))
        for ex in self.EXAMPLES:
            b = W.QPushButton(ex)
            b.setObjectName("tool")
            b.clicked.connect(lambda _=False, e=ex: (self.edit.setPlainText(e), self.on_send_click()))
            w.lay.addWidget(b)
        self.col.insertWidget(0, aligned_start(w))
        for m in self.hist.get("messages", []):
            self.add_bubble(m["role"], m["text"], save=False, md=(m["role"] != "user"))

    def reset(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        self.hist = {"session": None, "messages": []}
        assistant.save_history(self.hist)
        self.render_history()

    # --- turns
    def ask_from_page(self, display, message):
        """A request typed on a model page: shown as the user's words, sent with the model context."""
        if self.worker and self.worker.isRunning():
            self.main.toast(T("העוזר עוד עובד על בקשה קודמת, נסה בעוד רגע"), "warn")
            return
        self.add_bubble("user", display)
        self.start_turn(message, [])

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
        self.activity.setText(T("חושב…"))
        self.activity.setVisible(True)
        self.bar.setVisible(True)
        self.send_btn.setText(T("עצור", "btn"))
        self.worker.start()

    def on_event(self, ev):
        if ev.get("type") != "assistant":
            return
        for blk in (ev.get("message") or {}).get("content", []):
            if blk.get("type") == "text" and blk.get("text", "").strip():
                self.turn_text = True
                self.add_bubble("assistant", blk["text"].strip(), md=True)
            elif blk.get("type") == "tool_use":
                self.activity.setText(permissions.analyze(blk.get("name", ""), blk.get("input") or {}).text + "…")

    def on_done(self, res):
        self.activity.setVisible(False)
        self.bar.setVisible(False)
        self.send_btn.setText(T("שלח"))
        if res.get("session"):
            self.hist["session"] = res["session"]
            assistant.save_history(self.hist)
        if not res["ok"] and res["error"] and res["error"] != "בוטל":
            self.add_bubble("assistant", T("משהו השתבש: ") + res["error"])
        elif res["ok"] and not self.turn_text and res.get("text"):
            self.add_bubble("assistant", res["text"], md=True)
        for pid in list(self.perm_cards):                       # a question that was still open when the turn ended can no longer be answered
            if not self.perm_cards[pid]["answered"]:
                self.finish_perm(pid, T("פג תוקף"))

    # --- permission level and approvals inside the chat
    def set_level_label(self):
        label = next((T(l) for k, l, *_ in permissions.LEVELS if k == self.level), "")
        self.level_btn.setText(T("הרשאות: ") + label)
        self.level_btn.setToolTip(next((T(long) for k, _l, _s, long in permissions.LEVELS if k == self.level), "") + T("\n\nלחץ כדי לבחור רמה אחרת."))

    def apply_level(self, key):
        """Called by the dialog at the moment the owner clicks a level: tell the broker, update the button."""
        try:
            r = client.call({"op": "assistant_level", "set": key}, timeout=5)
        except client.BrokerDown:
            r = None
        if r and r.get("ok"):
            self.level = r["level"]
            self.set_level_label()
            self.main.toast(T("רמת ההרשאות של Claude: ") + next(T(l) for k, l, *_ in permissions.LEVELS if k == self.level), "ok")
            return True
        self.main.toast(T("לא הצלחתי לשנות את רמת ההרשאות (השירות לא עונה)"), "bad")
        return False

    def choose_level(self):
        LevelDialog(self.main, self.level, self.qs, self.apply_level).exec()

    def on_perms(self, perms, level=None):
        """Called with every state update: the broker's questions that wait for the owner (and his current permission level)."""
        if level and level != self.level:
            self.level = level
            self.set_level_label()
        live = {p["id"] for p in perms}
        for p in perms:
            if p["id"] not in self.perm_cards:
                self.show_perm(p)
        for pid, c in list(self.perm_cards.items()):
            if pid not in live and not c["answered"]:
                self.finish_perm(pid, T("פג תוקף (Claude הפסיק לחכות)"))
        if live and self.worker and self.worker.isRunning():
            self.activity.setText(T("מחכה לאישור שלך…"))

    def show_perm(self, p):
        danger = p.get("risk") == "danger"
        b = Bubble("model", 860)
        b.header("Claude", "sparkles", T("מבקש אישור"), "#db5c5c" if danger else "#e0a030")
        b.message(p["text"], bold=True)
        why = p.get("why") or ""
        if why:
            b.message(why, muted=True)
        detail = (p.get("detail") or "").strip()
        box = toggle = None
        if detail:
            toggle = W.QPushButton(T("הצג את הפקודה"))
            toggle.setObjectName("tool")
            toggle.setCheckable(True)
            box = W.QPlainTextEdit(detail)
            box.setReadOnly(True)
            box.setLayoutDirection(Qt.LeftToRight)
            box.setFixedHeight(min(190, 26 + 17 * (detail.count("\n") + 1 + len(detail) // 62)))
            box.setStyleSheet("QPlainTextEdit { background: #1e1f22; border: 1px solid #393b40; border-radius: 4px; color: #b4b8bf; font-family: Consolas; font-size: 9.5pt; }")
            box.setVisible(False)
            toggle.toggled.connect(lambda on, bx=box, tg=toggle: (bx.setVisible(on), tg.setText(T("הסתר את הפקודה") if on else T("הצג את הפקודה"))))
            row0 = W.QHBoxLayout()
            row0.addWidget(toggle)
            row0.addStretch(1)
            b.lay.addLayout(row0)
            b.lay.addWidget(box)
        yes = W.QPushButton(T("אשר, אני מבין שזה מסוכן") if danger else T("אשר"))
        yes.setObjectName("danger" if danger else "primary")
        no = W.QPushButton(T("דחה"))
        row = W.QHBoxLayout()
        row.addWidget(yes)
        row.addWidget(no)
        row.addStretch(1)
        b.lay.addLayout(row)
        holder = aligned_start(b)
        self.col.insertWidget(self.col.count() - 1, holder)
        self.perm_cards[p["id"]] = {"bubble": b, "yes": yes, "no": no, "answered": False, "holder": holder}
        yes.clicked.connect(lambda _=False, i=p["id"]: self.answer_perm(i, True))
        no.clicked.connect(lambda _=False, i=p["id"]: self.answer_perm(i, False))
        QtCore.QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        self.main.perm_alert(p)

    def finish_perm(self, pid, note):
        c = self.perm_cards.get(pid)
        if not c or c["answered"]:
            return
        c["answered"] = True
        c["yes"].setEnabled(False)
        c["no"].setEnabled(False)
        c["bubble"].message(note, muted=True)

    def answer_perm(self, pid, ok):
        c = self.perm_cards.get(pid)
        if not c or c["answered"]:
            return
        try:
            r = client.call({"op": "perm_answer", "id": pid, "allow": ok}, timeout=5)
        except client.BrokerDown:
            r = None
        self.finish_perm(pid, (T("אישרת") if ok else T("דחית")) if r and r.get("ok") else T("לא הצלחתי לשלוח את התשובה (Claude כבר לא מחכה)"))


class ClickCard(W.QFrame):
    """A card that is clickable everywhere (not only on its small radio button) and shows a hover state."""
    clicked = QtCore.Signal()
    hovered = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self._down = False

    def mousePressEvent(self, e):
        self._down = e.button() == Qt.LeftButton
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._down and e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        self._down = False
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self.hovered.emit(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered.emit(False)
        super().leaveEvent(e)


class LevelDialog(W.QDialog):
    """How much may Claude do without asking? Three levels, each explained in plain words. A click anywhere on a card chooses it and it applies at once."""
    def __init__(self, parent, current, qs, apply):
        super().__init__(parent)
        self.qs = qs
        self.choice = current
        self.apply = apply                          # callable(key) -> bool: tells the broker at once
        self.hover = {}
        self.setWindowTitle(T("רמת ההרשאות של Claude"))
        self.setMinimumWidth(560)
        v = W.QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(10)
        h = W.QLabel(T("כמה Claude רשאי לעשות בלי לשאול אותך?"))
        h.setStyleSheet("font-size: 13.5pt; font-weight: 600;")
        v.addWidget(h)
        sub = W.QLabel(T("אתה בוחר. אפשר לשנות בכל רגע, והשינוי חל מיד."))
        sub.setObjectName("muted")
        v.addWidget(sub)
        self.cards = {}
        self.group = W.QButtonGroup(self)
        for key, label, short, long in permissions.LEVELS:
            card = ClickCard()
            card.setObjectName("levelcard")
            cl = W.QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 12)
            cl.setSpacing(4)
            rb = W.QRadioButton("%s  -  %s%s" % (T(label), T(short), T("   (מומלץ)") if key == "normal" else ""))
            rb.setStyleSheet("font-weight: 600; font-size: 10.5pt;")
            rb.setAttribute(Qt.WA_TransparentForMouseEvents, True)          # the whole card takes the click
            rb.setChecked(key == current)
            self.group.addButton(rb)
            cl.addWidget(rb)
            desc = MessageView(T(long), max_width=520, muted=True)
            desc.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            desc.viewport().setAttribute(Qt.WA_TransparentForMouseEvents, True)
            cl.addWidget(desc)
            card.clicked.connect(lambda k=key: self.pick(k))
            card.hovered.connect(lambda on, k=key: (self.hover.__setitem__(k, on), self.paint()))
            rb.toggled.connect(lambda on, k=key: on and self.pick(k))        # arrow keys on the focused radio button
            self.cards[key] = (card, rb)
            v.addWidget(card)
        note = MessageView(T("חסום תמיד, בכל רמה: פירמוט דיסקים, שינוי רישום המערכת והגדרות האבטחה, וההגדרות של Claude עצמו."), max_width=520, muted=True)
        v.addWidget(note)
        row = W.QHBoxLayout()
        ok = W.QPushButton(T("סגור"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(ok)
        v.addLayout(row)
        self.paint()

    def sync(self):
        for key, (_card, rb) in self.cards.items():
            rb.blockSignals(True)
            rb.setChecked(key == self.choice)
            rb.blockSignals(False)
        self.paint()

    def pick(self, key):
        if key == self.choice:
            return
        if key == "free" and not self.qs.value("free_confirmed"):
            m = W.QMessageBox(self)
            m.setWindowTitle(T("רמה חופשית"))
            m.setIcon(W.QMessageBox.Warning)
            m.setText(T("ברמה ״חופשי״ Claude יוכל להוריד קבצים, להתקין תוכנות ולכתוב קבצים בלי לשאול אותך."))
            m.setInformativeText(T("מחיקות ועצירת תוכנות עדיין דורשות אישור, ופעולות מסוכנות במיוחד חסומות. להפעיל?"))
            yes = m.addButton(T("כן, חופשי"), W.QMessageBox.AcceptRole)
            m.addButton(T("ביטול"), W.QMessageBox.RejectRole)
            m.exec()
            if m.clickedButton() is not yes:
                self.sync()
                return
            self.qs.setValue("free_confirmed", True)
        if self.apply and not self.apply(key):
            self.sync()
            return
        self.choice = key
        self.sync()

    def paint(self):
        for key, (card, _rb) in self.cards.items():
            on = key == self.choice
            bg = "#233350" if on else ("#34373c" if self.hover.get(key) else "#2b2d30")
            card.setStyleSheet("QFrame#levelcard { background: %s; border: 1px solid %s; border-radius: 6px; }" % (bg, "#3574f0" if on else ("#5a5d63" if self.hover.get(key) else "#393b40")))


class LimitsPopup(W.QFrame):
    """Limits (how much RAM / GPU the AI may take, how many jobs at once) and today's numbers. Set once and rarely changed, so they live in a small popup
    instead of a permanent column."""
    def __init__(self, main):
        super().__init__(main, Qt.Popup)
        self.main = main
        self.setObjectName("limitspop")
        self.setStyleSheet("QFrame#limitspop { background: #2b2d30; border: 1px solid #43454a; border-radius: 6px; }")
        self.setMinimumWidth(380)
        rl = W.QVBoxLayout(self)
        rl.setContentsMargins(16, 12, 16, 14)
        rl.setSpacing(6)
        t = W.QLabel(T("מגבלות"))
        t.setObjectName("h2")
        t.setToolTip(T("מגבלות רכות: המערכת מכניסה כמה שיותר עבודות בתוכן, ואפשר לשנות אותן תוך כדי ריצה"))
        rl.addWidget(t)
        sub = W.QLabel(T("מכניסים כמה שיותר עבודות בתוך המגבלות האלה. אפשר לשנות תוך כדי ריצה."))
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        rl.addWidget(sub)
        self.sl = {}
        for key, label, lo, hi in (("ram_gb", T("RAM ל-AI"), 4, 62), ("vram_gb", T("GPU ל-AI"), 2, 16), ("max_jobs", T("עבודות במקביל"), 1, 8), ("reserve_ram_gb", T("RAM שנשאר פנוי"), 0, 24), ("disk_busy_pct", T("עומס דיסק מרבי"), 50, 100)):
            row = W.QHBoxLayout()
            lab = W.QLabel(label)
            s_ = W.QSlider(Qt.Horizontal)
            s_.setLayoutDirection(Qt.LeftToRight)
            s_.setRange(lo, hi)
            val = W.QLabel("")
            val.setMinimumWidth(52)
            val.setStyleSheet("font-weight:600;")
            val.setLayoutDirection(Qt.LeftToRight)
            s_.valueChanged.connect(lambda x, l=val, k=key: l.setText(fmt_limit(k, x)))
            s_.sliderReleased.connect(lambda k=key, sl=s_: main.set_limit(k, sl.value()))
            row.addWidget(lab, 2)
            row.addWidget(s_, 3)
            row.addWidget(val)
            rl.addLayout(row)
            self.sl[key] = (s_, val)
        t2 = W.QLabel(T("היום"))
        t2.setObjectName("h2")
        t2.setContentsMargins(0, 10, 0, 0)
        rl.addWidget(t2)
        card = W.QFrame()
        card.setObjectName("statcard")
        cv = W.QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(7)
        self.stat = {}
        for key, ic_, label in (("done", "check", T("עבודות שהסתיימו")), ("time", "clock", T("זמן ריצה כולל")), ("ram", "layers", T("שיא RAM של עבודה"))):
            r_ = W.QHBoxLayout()
            il = W.QLabel()
            il.setPixmap(icon_pixmap(ic_, "#868a91", 14))
            ll = W.QLabel(label)
            ll.setObjectName("muted")
            vl = W.QLabel("-")
            vl.setLayoutDirection(Qt.LeftToRight)
            vl.setStyleSheet("font-weight:600;")
            r_.addWidget(il)
            r_.addWidget(ll)
            r_.addStretch(1)
            r_.addWidget(vl)
            cv.addLayout(r_)
            self.stat[key] = vl
        rl.addWidget(card)


class SetupWizard(W.QDialog):
    """First-run setup (also from Settings): 1) what do you want to do, 2) what suits THIS computer, 3) downloads with progress.
    The recommendations come from the model catalog and the hardware profile (deterministic); the files only come from the verified sources of the catalog and run as
    `download` jobs in the broker's queue."""
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(T("התקנה ראשונית"))
        self.resize(900, 700)
        self.cats = set()
        self.data = None
        self.checks = {}
        self.ids = []
        self.rows = {}
        self.page = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        v = W.QVBoxLayout(self)
        v.setContentsMargins(26, 20, 26, 16)
        v.setSpacing(8)
        self.step = W.QLabel("")
        self.step.setObjectName("muted")
        self.title = W.QLabel("")
        self.title.setStyleSheet("font-size: 15pt; font-weight: 600;")
        self.sub = W.QLabel("")
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        v.addWidget(self.step)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        self.stack = W.QStackedWidget()
        v.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_cats())
        self.page2 = W.QWidget()
        self.stack.addWidget(self.page2)
        self.page3 = W.QWidget()
        self.stack.addWidget(self.page3)
        foot = W.QHBoxLayout()
        self.skip_btn = W.QPushButton(T("דלג, אעשה את זה אחר כך"))
        self.skip_btn.setObjectName("flat")
        self.skip_btn.clicked.connect(self.skip)
        self.back_btn = W.QPushButton(T("חזרה"))
        self.back_btn.clicked.connect(self.back)
        self.next_btn = W.QPushButton(T("הבא"))
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.next)
        foot.addWidget(self.skip_btn)
        foot.addStretch(1)
        foot.addWidget(self.back_btn)
        foot.addWidget(self.next_btn)
        v.addLayout(foot)
        self.show_page(0)

    # ---------------------------------------------------------------- page 1: what do you want to do
    def build_cats(self):
        w = W.QWidget()
        g = W.QGridLayout(w)
        g.setContentsMargins(0, 8, 0, 0)
        g.setSpacing(12)
        self.cat_cards = {}
        for i, (key, title, desc, icon_name) in enumerate(catalog.CATEGORIES):
            card = ClickCard()
            card.setObjectName("catcard")
            soon = key == "text"
            h = W.QHBoxLayout(card)
            h.setContentsMargins(16, 14, 16, 14)
            h.setSpacing(14)
            ic = W.QLabel()
            ic.setPixmap(icon_pixmap(icon_name, "#868a91" if soon else "#b4b8bf", 30))
            ic.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            col = W.QVBoxLayout()
            t = W.QLabel(T(title))
            t.setStyleSheet("font-size: 11pt; font-weight: 600;" + (" color: #868a91;" if soon else ""))
            d = W.QLabel(T(desc))
            d.setObjectName("muted")
            d.setWordWrap(True)
            for x in (t, d):
                x.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            col.addWidget(t)
            col.addWidget(d)
            mark = W.QLabel()
            mark.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            h.addWidget(ic, 0, Qt.AlignTop)
            h.addLayout(col, 1)
            h.addWidget(mark, 0, Qt.AlignTop)
            if not soon:
                card.clicked.connect(lambda k=key: self.toggle_cat(k))
            else:
                card.setCursor(Qt.ArrowCursor)
            self.cat_cards[key] = (card, mark, soon)
            g.addWidget(card, i // 2, i % 2)
        g.setRowStretch(len(catalog.CATEGORIES) // 2 + 1, 1)
        self.paint_cats()
        return w

    def toggle_cat(self, key):
        self.cats.symmetric_difference_update({key})
        self.paint_cats()

    def paint_cats(self):
        for key, (card, mark, soon) in self.cat_cards.items():
            on = key in self.cats
            card.setStyleSheet("QFrame#catcard { background: %s; border: 1px solid %s; border-radius: 8px; }" % ("#233350" if on else "#2b2d30", "#3574f0" if on else "#393b40"))
            mark.setPixmap(icon_pixmap("check", "#3574f0", 20) if on else QtGui.QPixmap())
        if hasattr(self, "next_btn"):
            self.next_btn.setEnabled(self.page != 0 or bool(self.cats))

    # ---------------------------------------------------------------- navigation
    def show_page(self, n):
        self.page = n
        self.stack.setCurrentIndex(n)
        self.step.setText(T("שלב %d מתוך 3") % (n + 1))
        self.back_btn.setVisible(n == 1)
        self.skip_btn.setVisible(n == 0)
        if n == 0:
            self.title.setText(T("מה תרצה לעשות עם התוכנה?"))
            self.sub.setText(T("סמן מה מעניין אותך. בשלב הבא נבדוק מה מתאים למחשב שלך."))
            self.next_btn.setText(T("הבא"))
            self.next_btn.setEnabled(bool(self.cats))
        elif n == 1:
            self.title.setText(T("מה מתאים למחשב שלך"))
            self.next_btn.setEnabled(True)
        else:
            self.title.setText(T("מתקין…"))
            self.sub.setText(T("ההורדות רצות בתור, ואפשר לסגור את החלון: הן ממשיכות ברקע."))
            self.back_btn.setVisible(False)
            self.skip_btn.setVisible(False)

    def back(self):
        self.show_page(0)

    def skip(self):
        self.main.settings.setValue("setup_done", True)
        self.reject()

    def next(self):
        if self.page == 0:
            self.build_recs()
        elif self.page == 1:
            self.start_install()
        else:
            self.main.settings.setValue("setup_done", True)
            self.accept()

    # ---------------------------------------------------------------- page 2: what suits this computer
    def build_recs(self):
        self.next_btn.setEnabled(False)
        W.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = client.call({"op": "packs", "categories": sorted(self.cats)}, timeout=30)
        except client.BrokerDown:
            r = None
        finally:
            W.QApplication.restoreOverrideCursor()
        if not r or not r.get("ok"):
            W.QMessageBox.warning(self, T("התקנה ראשונית"), T("השירות לא עונה, אי אפשר לבדוק את המחשב עכשיו."))
            self.next_btn.setEnabled(True)
            return
        self.data = r
        w = self.page2
        if w.layout():
            QtGui.QGuiApplication.processEvents()
            W.QWidget().setLayout(w.layout())                       # drop the old layout (a second visit)
        lay = W.QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)
        prof = r["profile"]
        gpu = prof.get("gpu") or {}
        free = [d for d in prof.get("disks") or []]
        models_drive = os.path.splitdrive(r["roots"].get("comfy_models") or r["roots"].get("models") or "")[0].upper()
        free_gb = next((d["free_gb"] for d in free if d["drive"].upper() == models_drive), (free[0]["free_gb"] if free else 0))
        self.free_gb = float(free_gb or 0)
        hw = W.QLabel(T("המחשב שלך: %s · %s · %s · %s") % (gpu.get("name", T("בלי כרטיס מסך של NVIDIA")), ltr("VRAM %.0f GB" % gpu.get("vram_gb", 0)), ltr("RAM %.0f GB" % (prof.get("ram_gb") or 0)),
                                                         T("פנוי בדיסק: %s") % ltr("%.0f GB" % self.free_gb)))
        hw.setObjectName("statcard")
        hw.setWordWrap(True)
        hw.setContentsMargins(12, 9, 12, 9)
        lay.addWidget(hw)
        self.sub.setText(T("סימנו מראש מה שמתאים למחשב שלך ועוד לא מותקן. אפשר לשנות."))
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.NoFrame)
        inner = W.QWidget()
        inner.setStyleSheet("background: transparent;")
        il = W.QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.setSpacing(10)
        self.checks = {}
        shown = 0
        for p in r["packs"]:
            if p["category"] not in self.cats:
                continue
            shown += 1
            il.addWidget(self.pack_card(p))
        if not shown:
            nl = W.QLabel(T("אין עדיין מודלים בקטגוריות שבחרת."))
            nl.setObjectName("muted")
            il.addWidget(nl)
        il.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        self.total = W.QLabel("")
        self.total.setObjectName("muted")
        lay.addWidget(self.total)
        self.show_page(1)
        self.update_total()

    def pack_card(self, p):
        card = W.QFrame()
        card.setObjectName("statcard")
        h = W.QHBoxLayout(card)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)
        cb = W.QCheckBox()
        can = p["downloadable"] and p["status"] != "installed" and p["fit"] != "no" and not p["tools_missing"]
        cb.setEnabled(bool(can))
        cb.setChecked(bool(can and p["fit"] == "ok"))
        cb.toggled.connect(lambda _=False: self.update_total())
        self.checks[p["id"]] = (cb, p)
        h.addWidget(cb, 0, Qt.AlignTop)
        col = W.QVBoxLayout()
        col.setSpacing(5)
        t = W.QLabel(p["title"])
        t.setStyleSheet("font-weight: 600; font-size: 10.5pt;")
        t.setWordWrap(True)
        d = W.QLabel(p["what"])
        d.setObjectName("muted")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        chips = FlowLayout()
        fit = {"ok": (T("מתאים למחשב שלך"), "ok"), "tight": (T("גבולי: ייתכנו האטות"), "warn"), "no": (T("לא מתאים למחשב שלך"), "bad")}[p["fit"]]
        chips.addWidget(Chip(fit[0], fit[1]))
        st = {"installed": (T("מותקן"), "ok"), "partial": (T("מותקן חלקית"), "warn"), "missing": (T("לא מותקן"), "muted"), "unknown": (T("לא ידוע אם מותקן"), "muted")}[p["status"]]
        chips.addWidget(Chip(st[0], st[1]))
        if p["todo_bytes"]:
            chips.addWidget(Chip(T("להורדה: %s") % ("%.1f GB" % (p["todo_bytes"] / 1e9)), "info"))
        for tool in p["tools_missing"]:
            chips.addWidget(Chip(T("חסר: %s") % tool, "bad"))
        if p.get("license"):
            chips.addWidget(Chip(T("רישיון: %s") % p["license"], "muted"))
        need = p.get("needs") or {}
        if need.get("vram_min_gb") or need.get("ram_gb"):
            chips.addWidget(Chip(ltr("VRAM %s GB · RAM %s GB" % (need.get("vram_min_gb", 0), need.get("ram_gb", 0))), "muted"))
        col.addLayout(chips)
        extra = p.get("manual") if (not p["downloadable"] and p["status"] != "installed") else p.get("note")
        if extra:
            e = W.QLabel(extra)
            e.setObjectName("muted")
            e.setWordWrap(True)
            col.addWidget(e)
        if (not p["downloadable"] and p["status"] != "installed") or p["tools_missing"]:
            ask = W.QPushButton(T("בקש מ-Claude לעזור"))
            ask.setObjectName("tool")
            ask.setIcon(icon("sparkles", "#b4b8bf", 15))
            ask.clicked.connect(lambda _=False, pk=p: self.ask_claude(pk))
            row = W.QHBoxLayout()
            row.addWidget(ask)
            row.addStretch(1)
            col.addLayout(row)
        h.addLayout(col, 1)
        return card

    def update_total(self):
        ids = [i for i, (cb, _p) in self.checks.items() if cb.isChecked()]
        gb = sum(p["todo_bytes"] for i, (cb, p) in self.checks.items() if cb.isChecked()) / 1e9
        enough = gb + 5 <= self.free_gb
        self.total.setText(T("להורדה: %s · פנוי בדיסק: %s") % (ltr("%.1f GB" % gb), ltr("%.0f GB" % self.free_gb)) + ("" if enough else T("   ·   אין מספיק מקום פנוי")))
        self.total.setStyleSheet("" if enough else "color: #db5c5c;")
        self.next_btn.setText(T("התקן את המסומנים") if ids else T("סיום"))
        self.next_btn.setEnabled(enough)

    def ask_claude(self, p):
        msg = T("אני רוצה להתקין את ״%s״ (%s). בדוק מה חסר אצלי ועזור לי להתקין את זה, ובקש אישור לפני כל הורדה.") % (p["title"], p.get("source") or "")
        self.main.settings.setValue("setup_done", True)
        self.accept()
        self.main.ask_assistant(T("עזור לי להתקין: %s") % p["title"], msg)

    # ---------------------------------------------------------------- page 3: downloads
    def start_install(self):
        ids = [i for i, (cb, _p) in self.checks.items() if cb.isChecked()]
        if not ids:
            self.main.settings.setValue("setup_done", True)
            self.accept()
            return
        try:
            r = client.call({"op": "install_packs", "ids": ids, "requester": "setup"}, timeout=60)
        except client.BrokerDown:
            r = None
        if not r or not r.get("ok"):
            W.QMessageBox.warning(self, T("התקנה ראשונית"), (r or {}).get("error") or T("השירות לא עונה."))
            return
        self.ids = r["ids"]
        w = self.page3
        lay = W.QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        self.rows = {}
        for jid, task in zip(self.ids, r["tasks"]):
            row = W.QFrame()
            row.setObjectName("statcard")
            rl = W.QVBoxLayout(row)
            rl.setContentsMargins(12, 9, 12, 9)
            rl.setSpacing(5)
            top = W.QHBoxLayout()
            name = W.QLabel(os.path.basename(task["dest"]))
            name.setLayoutDirection(Qt.LeftToRight)
            name.setStyleSheet("font-weight: 600;")
            size = W.QLabel(ltr("%.2f GB" % (task["size"] / 1e9)) if task["size"] else "")
            size.setObjectName("muted")
            st = W.QLabel(T("ממתין"))
            st.setObjectName("muted")
            top.addWidget(name, 1)
            top.addWidget(size)
            top.addWidget(st)
            bar = W.QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            rl.addLayout(top)
            rl.addWidget(bar)
            lay.addWidget(row)
            self.rows[jid] = (bar, st)
        self.manual = r.get("manual") or []
        if self.manual:
            ml = W.QLabel(T("את אלה אי אפשר להוריד אוטומטית (בקש מ-Claude): %s") % ", ".join(self.manual))
            ml.setObjectName("muted")
            ml.setWordWrap(True)
            lay.addWidget(ml)
        if not self.ids:
            nl = W.QLabel(T("אין מה להוריד: הכול כבר מותקן."))
            lay.addWidget(nl)
        lay.addStretch(1)
        self.done_box = W.QHBoxLayout()
        lay.addLayout(self.done_box)
        self.show_page(2)
        self.next_btn.setText(T("סגור (ההורדות ממשיכות)"))
        self.timer.start(1000)
        self.poll()

    def poll(self):
        if not self.ids:
            self.finish(True)
            return
        finished, failed = 0, 0
        for jid in self.ids:
            bar, st = self.rows[jid]
            try:
                j = client.call({"op": "get", "id": jid}, timeout=4).get("job") or {}
            except client.BrokerDown:
                return
            state = j.get("state")
            if state == "done":
                bar.setValue(1000)
                st.setText(T("הושלם"))
                finished += 1
            elif state in ("failed", "cancelled", "lost"):
                tail = ""
                try:
                    tail = client.call({"op": "tail", "id": jid, "bytes": 3000}, timeout=4).get("text", "")
                except client.BrokerDown:
                    pass
                lines = [l for l in tail.splitlines() if l.strip() and not l.startswith("[broker]")]
                st.setText(T("נכשל: ") + (lines[-1][:110] if lines else state))
                st.setStyleSheet("color: #db5c5c;")
                finished += 1
                failed += 1
            elif state == "running":
                pct = 0.0
                try:
                    tail = client.call({"op": "tail", "id": jid, "bytes": 2000}, timeout=4).get("text", "")
                    m = re.findall(r"PROGRESS ([0-9.]+) (\d+) (\d+) ([0-9.]+)", tail)
                    if m:
                        pct = float(m[-1][0])
                        st.setText("%.0f%%  ·  %s" % (pct, ltr("%.0f MB/s" % float(m[-1][3]))))
                except client.BrokerDown:
                    pass
                bar.setValue(int(pct * 10))
            else:
                st.setText(T("ממתין"))
        if finished == len(self.ids):
            self.finish(failed == 0)

    def finish(self, ok):
        self.timer.stop()
        if getattr(self, "finished_shown", False):
            return
        self.finished_shown = True
        self.title.setText(T("ההתקנה הראשונית הושלמה") if ok else T("ההתקנה הסתיימה, חלק מההורדות נכשלו"))
        self.sub.setText(T("עכשיו אפשר לחבר את Claude Code כדי שהסוכנים שלך ישתמשו בתור, ולבקש מ-Claude בחלון להריץ עבודות.") if ok else T("אפשר לנסות שוב מהגדרות, התקנת מודלים."))
        self.next_btn.setText(T("סיום"))
        self.main.settings.setValue("setup_done", True)
        conn = W.QPushButton(T("חבר את Claude Code"))
        conn.setIcon(icon("sparkles", "#b4b8bf", 15))
        conn.setObjectName("tool")
        conn.clicked.connect(lambda: (self.accept(), self.main.open_settings("claude")))
        self.done_box.addStretch(1)
        self.done_box.addWidget(conn)

    def done(self, r):
        self.timer.stop()
        super().done(r)


class Main(W.QMainWindow):
    def __init__(self, tray=True, model=None):
        super().__init__()
        self.setWindowTitle("AI Broker")
        self.setMinimumSize(960, 620)
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
        self.persist = True
        self.zoom = 1.0
        self.type_dir = {}
        self.type_stats = {}
        self.setAcceptDrops(True)
        self._build()
        self.tray = None
        if tray and W.QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()
        self.settings = QtCore.QSettings("ai-broker", "gui3")
        st = self.settings
        try:
            self.zoom = max(0.8, min(1.5, float(st.value("zoom", 1.0) or 1.0)))
        except (TypeError, ValueError):
            self.zoom = 1.0
        if abs(self.zoom - 1.0) > 0.01:
            W.QApplication.instance().setStyleSheet(qss(self.zoom))
        if st.value("geometry"):
            self.restoreGeometry(st.value("geometry"))
        self.fit_to_screen()
        for name, sp in (("split_main2", self.split_main), ("split_center2", self.split_center)):
            if st.value(name):
                sp.restoreState(st.value(name))
        if self.sel_model is None:
            last = st.value("last_model", None)
            if last == "__assistant__":
                self.assistant_mode = True
            elif last:
                self.sel_model = last
        if not st.value("tip_shown") and self.persist:
            QtCore.QTimer.singleShot(2500, lambda: (self.toast(T("טיפ: Ctrl+K פותח חיפוש מהיר של מודלים ופעולות"), "info", T("הבנתי"), None, 8000), st.setValue("tip_shown", True)))
        for seq, fn in (("Ctrl+K", self.open_palette), ("Ctrl+=", lambda: self.zoom_by(0.1)), ("Ctrl++", lambda: self.zoom_by(0.1)), ("Ctrl+-", lambda: self.zoom_by(-0.1)),
                        ("Ctrl+0", lambda: self.zoom_by(0, True)), ("Ctrl+L", self.focus_composer)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            sc.activated.connect(fn)
        self.poller = Poller()
        self.poller.got.connect(self.on_state)
        self.poller.down.connect(self.on_down)
        self.poller.start()
        self.load_types()
        QtCore.QTimer.singleShot(2500, self.maybe_first_run)
        t = QtCore.QTimer(self)
        t.timeout.connect(self.refresh_files)
        t.start(3000)

    def fit_to_screen(self):
        """Never half off-screen: shrink to the screen the window is on and pull it back inside (also if a saved geometry came from a bigger screen)."""
        scr = (self.screen() or W.QApplication.primaryScreen()).availableGeometry()
        w = min(self.width(), int(scr.width() * 0.96))
        h = min(self.height(), int(scr.height() * 0.94))
        self.resize(max(900, w), max(620, h))
        fg = self.frameGeometry()
        if not scr.contains(fg.topLeft()) or not scr.contains(fg.bottomRight()):
            self.move(scr.left() + (scr.width() - self.width()) // 2, scr.top() + (scr.height() - self.height()) // 2)

    def showEvent(self, e):
        style_titlebar(int(self.winId()))
        super().showEvent(e)

    def toast(self, text, kind="info", action=None, fn=None, ms=4200):
        self.toaster.show_message(text, kind, action, fn, ms)

    def zoom_by(self, d, reset=False):
        self.zoom = 1.0 if reset else max(0.8, min(1.5, round(self.zoom + d, 2)))
        W.QApplication.instance().setStyleSheet(qss(self.zoom))
        self.settings.setValue("zoom", self.zoom)
        self.toast(T("גודל הטקסט: %d%%") % round(self.zoom * 100), "info")

    def focus_composer(self):
        if self.assistant_mode:
            self.assistant_panel.edit.setFocus()
        elif self.sel_model:
            (self.chat.edit if self.chat.edit.isVisible() else self.chat).setFocus()

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
        self.h_title = W.QLabel(T("מתחבר…"))
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
        self.play = tb("gamepad", T("משחק / הקלטה"), T("כשזה דלוק, עבודות GPU מחכות ועבודות GPU שרצות מוקפאות, כדי שהמשחק או ההקלטה לא יגמגמו"), "tbplay", True)
        self.play.clicked.connect(lambda on: self.api({"op": "playing", "on": on}))
        self.pause = tb("pause", T("עצור הכול"), T("שום עבודה חדשה לא מתחילה עד שתמשיך"), "tbpause", True)
        self.pause.clicked.connect(lambda on: self.api({"op": "pause"} if on else {"op": "resume"}))
        adv = tool_button("gear", T("הגדרות"), lambda: self.open_settings(), size=19)
        ask = tb("sparkles", T("עוזר"), T("שיחה עם Claude בתוך התוכנה: שאלות על המחשב והמודלים, הרצת עבודות, והמלצה והורדה של מודלים (באישור שלך)"), "tb")
        ask.clicked.connect(self.open_claude)
        pal = tool_button("search", T("חיפוש פעולות ומודלים (Ctrl+K)"), lambda: self.open_palette(), size=17)
        for b_ in (pal, ask, self.play, self.pause, adv):
            head.addWidget(b_)
        v.addWidget(bar)
        strip = W.QFrame()
        strip.setObjectName("resbar")
        sh = W.QHBoxLayout(strip)
        sh.setContentsMargins(16, 5, 12, 5)
        sh.setSpacing(26)
        self.g_ram, self.g_gpu = MiniGauge("RAM", "layers"), MiniGauge("GPU", "cpu")
        self.g_disk, self.g_cpu = MiniGauge(T("דיסק"), "hdd", 56), MiniGauge("CPU", "chart", 56)
        for g_ in (self.g_ram, self.g_gpu, self.g_disk, self.g_cpu):
            sh.addWidget(g_)
        sh.addStretch(1)
        self.lim_btn = W.QPushButton(T("מגבלות"))
        self.lim_btn.setObjectName("flat")
        self.lim_btn.setIcon(icon("sliders", "#868a91", 14))
        self.lim_btn.setToolTip(T("כמה RAM ו-GPU מותר ל-AI לקחת, כמה עבודות במקביל, ומספרי היום"))
        self.lim_btn.clicked.connect(self.open_limits)
        self.lim_sum = W.QLabel("")
        self.lim_sum.setObjectName("muted")
        sh.addWidget(self.lim_sum)
        sh.addWidget(self.lim_btn)
        v.addWidget(strip)
        split = W.QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        body = W.QWidget()
        bl2 = W.QVBoxLayout(body)
        bl2.setContentsMargins(8, 8, 8, 6)
        bl2.addWidget(split)
        v.addWidget(body, 1)
        self.toaster = NoticeBar()                  # messages sit under the content, above the status bar
        v.addWidget(self.toaster)
        mp = self._panel()
        ml = W.QVBoxLayout(mp)
        ml.setContentsMargins(0, 0, 0, 6)
        ml.setSpacing(0)
        mh = ToolHeader(T("מודלים ותוצאות"), "grid")
        mh.add_action("folder", T("פתח את תיקיית הפלט"), lambda: self.open_folder(None if self.assistant_mode else self.sel_model))
        ml.addWidget(mh)
        self.model_list = W.QListWidget()
        self.model_list.setObjectName("models")
        self.model_list.setItemDelegate(ModelDelegate(self.model_list))
        self.model_list.setMouseTracking(True)
        self.model_list.setVerticalScrollMode(W.QAbstractItemView.ScrollPerPixel)
        self.model_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.model_list.currentRowChanged.connect(self.on_model)
        self.model_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.model_list.customContextMenuRequested.connect(self.model_menu)
        self.model_list.itemDoubleClicked.connect(lambda it: self.open_folder(it.data(Qt.UserRole)) if it.data(ROLE_KIND) == "item" and it.data(Qt.UserRole) != "__assistant__" else None)
        ml.addWidget(self.model_list, 1)
        mp.setMinimumWidth(170)
        mp.setMaximumWidth(250)
        split.addWidget(mp)
        self.split_main = split
        cs = W.QSplitter(Qt.Vertical)
        cs.setChildrenCollapsible(False)
        top = self._panel()
        tl = W.QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.tabs = W.QTabWidget()
        self.tabs.setDocumentMode(True)
        qw = W.QWidget()
        ql = W.QVBoxLayout(qw)
        ql.setContentsMargins(8, 2, 8, 8)
        self.queue = QueueTable()
        self.queue.reorder.connect(lambda ids, pos: self.api({"op": "move", "ids": ids, "to": pos}))
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self.queue_menu)
        self.queue.itemDoubleClicked.connect(lambda it: self.show_job(self.queue.job_ids[it.row()]) if it.row() < len(self.queue.job_ids) else None)
        dsc = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Delete), self.queue)
        dsc.setContext(Qt.WidgetShortcut)
        dsc.activated.connect(lambda: self.queue_action("cancel"))
        empty = W.QWidget()
        ev = W.QVBoxLayout(empty)
        ev.setAlignment(Qt.AlignCenter)
        ei = W.QLabel()
        ei.setPixmap(icon_pixmap("list", "#6f737a", 30))
        ei.setAlignment(Qt.AlignCenter)
        et = W.QLabel(T("אין עבודות בתור"))
        et.setObjectName("big")
        et.setAlignment(Qt.AlignCenter)
        es = W.QLabel(T("עבודות ש-Claude או אתה שולחים יופיעו כאן. אפשר לגרור שורות ממתינות כדי לשנות סדר."))
        es.setObjectName("muted")
        es.setAlignment(Qt.AlignCenter)
        for w_ in (ei, et, es):
            ev.addWidget(w_)
        self.q_stack = W.QStackedWidget()
        self.q_stack.addWidget(empty)
        self.q_stack.addWidget(self.queue)
        ql.addWidget(self.q_stack, 1)
        self.tabs.addTab(qw, T("תור"))
        self.hist = W.QTableWidget(0, 7)
        self.hist.setHorizontalHeaderLabels(["#", T("סוג"), T("עבודה"), T("ביקש"), T("תוצאה"), T("זמן"), T("שיא RAM / GPU")])
        self.hist.verticalHeader().hide()
        self.hist.verticalHeader().setDefaultSectionSize(32)
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
        hl.setContentsMargins(8, 4, 8, 8)
        hb = W.QHBoxLayout()
        hb.setSpacing(2)
        for ic_, tx_, fn_ in (("refresh", T("הרץ שוב עם אותן הגדרות"), self.hist_rerun),
                              ("folder", T("פתח את תיקיית התוצאה"), lambda: self.hist_open(self.hist.currentItem()) if self.hist.currentItem() else None)):
            b_ = W.QPushButton(tx_)
            b_.setObjectName("flat")
            b_.setIcon(icon(ic_, "#868a91", 14))
            b_.clicked.connect(lambda _=False, f=fn_: f())
            hb.addWidget(b_)
        hb.addStretch(1)
        hint = W.QLabel(T("לחיצה כפולה על שורה פותחת את התיקייה"))
        hint.setObjectName("muted")
        hb.addWidget(hint)
        hl.addLayout(hb)
        self.hist.setContextMenuPolicy(Qt.CustomContextMenu)
        self.hist.customContextMenuRequested.connect(self.hist_menu)
        hl.addWidget(self.hist, 1)
        self.tabs.addTab(hw, T("היסטוריה"))
        corner = W.QWidget()
        ch = W.QHBoxLayout(corner)
        ch.setContentsMargins(0, 0, 6, 0)
        ch.setSpacing(2)
        self.btns = {}
        for key, ic_, tip in (("top", "top", T("הרץ ראשונה")), ("up", "up", T("הקדם בתור")), ("down", "down", T("דחה בתור")), ("hold", "pause", T("עצור / שחרר את העבודה")), ("cancel", "x", T("בטל את העבודה"))):
            b_ = tool_button(ic_, tip, lambda _=False, k=key: self.queue_action(k))
            ch.addWidget(b_)
            self.btns[key] = b_
        self.tabs.setCornerWidget(corner, Qt.TopLeftCorner)
        self.q_corner = corner
        self.q_busy = False
        self.tabs.currentChanged.connect(lambda i: self.sync_queue_panel(self.q_busy))
        tl.addWidget(self.tabs)
        self.top_panel = top
        outp = self._panel()
        ol = W.QVBoxLayout(outp)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)
        gh = ToolHeader(T("כל התוצאות"), "grid")
        self.out_title, self.out_path = gh.title, gh.sub
        gh.add_action("folder", T("פתח את תיקיית הפלט"), self.open_model_folder)
        ol.addWidget(gh)
        gb = W.QWidget()
        gl = W.QVBoxLayout(gb)
        gl.setContentsMargins(10, 8, 10, 10)
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
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self.files_menu)
        gl.addWidget(self.files, 1)
        self.files_empty = W.QLabel("")
        self.files_empty.setObjectName("muted")
        self.files_empty.setAlignment(Qt.AlignCenter)
        gl.addWidget(self.files_empty)
        ol.addWidget(gb, 1)
        self.chat = ChatPanel(self)
        self.assistant_panel = AssistantPanel(self)
        self.lower = W.QStackedWidget()
        self.lower.addWidget(outp)
        self.lower.addWidget(self.chat)
        self.lower.addWidget(self.assistant_panel)
        cs.addWidget(self.lower)
        cs.addWidget(top)
        cs.setSizes([600, 170])
        self.split_center = cs
        QtCore.QTimer.singleShot(0, lambda: self.sync_queue_panel(False))
        split.addWidget(cs)
        self.limits_pop = LimitsPopup(self)
        self.sl, self.stat = self.limits_pop.sl, self.limits_pop.stat
        split.setSizes([210, 1100])
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)

        def sep():
            f_ = W.QFrame()
            f_.setFixedSize(1, 14)
            f_.setStyleSheet("background:#43454a;")
            return f_
        w0 = W.QWidget()
        h0 = W.QHBoxLayout(w0)
        h0.setContentsMargins(8, 0, 8, 0)
        h0.setSpacing(6)
        self.sd_dot = Dot(8)
        self.sd_lbl = W.QLabel(T("מתחבר…"))
        h0.addWidget(self.sd_dot)
        h0.addWidget(self.sd_lbl)
        self.s_ram, self.s_commit, self.s_lock = Seg("layers", ""), Seg("hdd", ""), Seg("alert", "")
        self.s_ram.setVisible(False)
        self.s_lock.setVisible(False)
        for w_ in (w0, sep(), self.s_commit, self.s_lock):
            sb.addWidget(w_)
        self.task = TaskWidget()
        self.task.clicked.connect(self.on_task_click)
        sb.addPermanentWidget(self.task)

    def _build_tray(self):
        self.tray = W.QSystemTrayIcon(make_icon(), self)
        m = W.QMenu()
        m.addAction(T("פתח את החלון"), self.show_normal)
        m.addAction(T("עצור / המשך הכול"), lambda: self.pause.click())
        m.addAction(T("אני משחק / מקליט"), lambda: self.play.click())
        m.addSeparator()
        m.addAction(T("סגור את החלון (העבודות ממשיכות)"), self.quit_gui)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (W.QSystemTrayIcon.Trigger, W.QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    # ------------------------------------------------------------ actions
    def api(self, req):
        try:
            r = client.call(req, timeout=5)
            if not r.get("ok"):
                self.toast(T("שגיאה: ") + str(r.get("error"))[:160], "bad")
            return r
        except Exception as e:
            self.toast(T("אין חיבור לשירות"), "bad")

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
            if W.QMessageBox.question(self, T("לבטל?"), T("לבטל %d עבודות? עבודה שרצה תיעצר.") % len(ids)) == W.QMessageBox.Yes:
                for i in ids:
                    self.api({"op": "cancel", "id": i})

    def queue_menu(self, pos):
        if not self.queue.selected_ids():
            return
        m = W.QMenu(self)
        for key, text in (("top", T("הרץ ראשונה")), ("up", T("הקדם")), ("down", T("דחה")), ("hold", T("עצור / שחרר")), ("cancel", T("בטל"))):
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
                t.setToolTip(T("לחץ כדי לסובב את הדגם\n") + glb)
                return t
        self.request_preview(glb)
        t = Thumb(symbol_pixmap("⬢", "#2aa198", 120), glb)
        t.setToolTip(T("יוצר תצוגה מקדימה… (כמה שניות)\n") + glb)
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
        m.addAction(T("פתח את תיקיית הפלט"), lambda: self.open_folder(od))
        if od:
            m.addAction(T("עבודה חדשה במודל הזה"), lambda: self.open_submit(self.model_first_type(od)))
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
            self.toast(T("נוספה עבודה חוזרת #%d") % r["id"], "ok", T("הצג בתור"), lambda: self.tabs.setCurrentIndex(0))

    def open_submit(self, preselect=None, prefill=None):
        if not self.types:
            return
        dlg = SubmitDialog(self, self.types, preselect, prefill)
        if dlg.exec() == W.QDialog.Accepted:
            r = self.api(dlg.request())
            if r and r.get("ok"):
                self.toast(T("נוספה עבודה #%d") % r["id"], "ok", T("הצג בתור"), lambda: self.tabs.setCurrentIndex(0))

    def ask_assistant(self, display, message):
        self.model_list.setCurrentRow(0)          # the assistant is the first entry of the list
        self.assistant_panel.ask_from_page(display, message)
        self.toast(T("הבקשה הועברה לעוזר"), "ok")

    def show_output(self, jid, title):
        OutputDialog(self, jid, title).exec()

    def select_model(self, od):
        for i in range(self.model_list.count()):
            if self.model_list.item(i).data(Qt.UserRole) == od and self.model_list.item(i).data(ROLE_KIND) == "item":
                self.model_list.setCurrentRow(i)
                return True
        return False

    def send_menu(self, path, pos=None):
        """Right-click on a picture: continue with it in another model (edit it, turn it into a 3D model...)."""
        if not path or Path(path).suffix.lower() not in IMG:
            return
        m = W.QMenu(self)
        head = m.addAction(T("שלח את התמונה אל:"))
        head.setEnabled(False)
        for g in self.models:
            cfg = (self.types.get(g["tids"][0], {}).get("chat") or {})
            if cfg.get("file"):
                m.addAction(sym_icon(g["sym"], g["color"], 16), "%s   ·   %s" % (cfg.get("send_label") or g["title"], g["title"]), lambda od=g["dir"], p_=path: self.send_to(od, p_))
        m.addSeparator()
        m.addAction(icon("folder", "#b4b8bf", 16), T("פתח את התמונה"), lambda: os.startfile(path))
        m.addAction(icon("copy", "#b4b8bf", 16), T("העתק נתיב"), lambda: W.QApplication.clipboard().setText(path))
        m.exec(pos or QtGui.QCursor.pos())

    def send_to(self, od, path):
        if self.select_model(od):
            self.chat.set_attached(path)
            self.chat.edit.setFocus()
            self.toast(T("התמונה צורפה. כתוב מה לעשות ושלח"), "ok")

    def open_palette(self):
        items = [(T("עוזר Claude"), "sparkles", T("שיחה"), lambda: self.select_model("__assistant__") or self.model_list.setCurrentRow(0)),
                 (T("כל התוצאות"), "grid", T("גלריה"), lambda: self.select_model(None))]
        for g in self.models:
            items.append((T("מעבר אל: ") + g["title"], SYMBOL_ICON.get(g["sym"], "doc"), T("מודל"), lambda od=g["dir"]: self.select_model(od)))
        paused = bool(self.state and self.state.get("paused"))
        items += [(T("המשך את כל העבודות") if paused else T("עצור את כל העבודות"), "play" if paused else "pause", T("תור"), lambda: self.pause.click()),
                  (T("מצב משחק / הקלטה"), "gamepad", T("מתג"), lambda: self.play.click()),
                  (T("פתח את תיקיית הפלט"), "folder", T("קבצים"), lambda: self.open_folder(None)),
                  (T("הגדרות: שפה, חיבור ל-Claude Code, הפעלה עם Windows"), "gear", T("הגדרות"), self.open_settings),
                  (T("התקנת מודלים והתקנה ראשונית"), "download", T("הגדרות"), self.open_setup),
                  (T("הגדל טקסט"), "zoomin", "Ctrl +", lambda: self.zoom_by(0.1)),
                  (T("הקטן טקסט"), "zoomin", "Ctrl -", lambda: self.zoom_by(-0.1)),
                  (T("גודל טקסט רגיל"), "zoomin", "Ctrl 0", lambda: self.zoom_by(0, True))]
        Palette(self, items).popup()

    def on_task_click(self, job):
        if job:
            od = self.type_dir.get(job["type"])
            if od:
                self.select_model(od)

    def open_claude(self):
        self.model_list.setCurrentRow(0)          # the assistant is the first entry of the list

    def perm_alert(self, p):
        """Claude is waiting for a click. The question itself is in the chat; a Windows balloon is shown only when the window is hidden or minimized, and at most once a minute."""
        hidden = (not self.isVisible()) or self.isMinimized()
        if self.tray and hidden and time.time() - getattr(self, "_perm_balloon", 0) > 60:
            self._perm_balloon = time.time()
            self.tray.showMessage("AI Broker", T("Claude מבקש אישור: ") + p["text"][:120], W.QSystemTrayIcon.Information, 8000)

    def sync_perm_notice(self, pending):
        """One row under the content while Claude waits and the assistant page is not in front (never a pop-up; the row disappears when answered)."""
        if pending and not (self.assistant_mode and self.isActiveWindow()):
            txt = T("Claude מחכה לאישור שלך: ") + pending[0]["text"] + (T(" (ועוד %d)") % (len(pending) - 1) if len(pending) > 1 else "")
            self.toaster.upsert("perm", txt, "warn", T("פתח"), self.open_claude, 0)
        else:
            self.toaster.remove("perm")

    def sync_queue_panel(self, busy):
        """The queue panel shows only its tab bar while there is nothing in it (no jobs): the middle gets the room. It opens by itself when a job
        appears or when the History tab is chosen."""
        self.q_busy = busy
        want_open = busy or self.tabs.currentIndex() == 1
        pages = self.tabs.findChild(W.QStackedWidget)
        top = self.top_panel
        self.q_corner.setVisible(busy and self.tabs.currentIndex() == 0)
        if want_open:
            if pages is not None and not pages.isVisible():
                pages.setVisible(True)
                top.setMaximumHeight(16777215)
                total = self.split_center.height()
                self.split_center.setSizes([max(300, total - 240), 240])
        elif pages is not None and pages.isVisible():
            pages.setVisible(False)
            top.setMaximumHeight(self.tabs.tabBar().sizeHint().height() + 8)

    def open_limits(self):
        """The limits popup opens under its button and always stays inside the screen (it used to run off the edge when the window sat at the left of the screen)."""
        p = self.limits_pop
        p.adjustSize()
        b = self.lim_btn
        rtl = W.QApplication.layoutDirection() == Qt.RightToLeft
        left = b.mapToGlobal(QtCore.QPoint(0, 0))
        x = left.x() if rtl else b.mapToGlobal(QtCore.QPoint(b.width(), 0)).x() - p.width()      # Hebrew: the button is at the left end of the strip, so open towards the right
        y = b.mapToGlobal(QtCore.QPoint(0, b.height() + 4)).y()
        scr = (b.screen() or W.QApplication.primaryScreen()).availableGeometry()
        x = max(scr.left() + 8, min(x, scr.right() - p.width() - 8))
        y = max(scr.top() + 8, min(y, scr.bottom() - p.height() - 8))
        p.move(x, y)
        p.show()

    def open_settings(self, tab=None):
        SettingsDialog(self, tab).exec()

    def open_setup(self):
        SetupWizard(self).exec()

    def maybe_first_run(self):
        """A brand-new installation (no job ever ran) opens the setup once; someone who already works with the program is never interrupted (it is in Settings)."""
        if not self.persist or self.settings.value("setup_done"):
            return
        r = self.api({"op": "history", "limit": 1})
        if r and r.get("ok") and not r.get("jobs"):
            self.open_setup()

    def set_language(self, code):
        """Save the language (in the broker's config, so the window, the broker and Claude agree) and open the window again."""
        try:
            client.call({"op": "lang", "set": code}, timeout=5)
        except client.BrokerDown:
            pass
        args = [a for a in sys.argv[1:] if a != "--hidden"]
        import subprocess
        env = dict(os.environ, AIBROKER_LANG=code)
        subprocess.Popen([sys.executable, "-m", "aibroker.gui"] + args, cwd=str(paths.ROOT), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x08000000 | 0x00000008)
        self.quitting = True
        self.close()
        W.QApplication.quit()

    # ------------------------------------------------------------ models and output
    def load_types(self):
        r = self.api({"op": "types"})
        if not r or not r.get("ok"):
            return
        self.types = r["types"]
        self.output_root = r.get("output_root", self.output_root)
        self.refresh_type_stats()
        groups = {}
        for tid, t in self.types.items():
            if t.get("hidden"):
                continue
            od = t.get("output_dir") or tid
            g = groups.setdefault(od, dict(dir=od, title=loc(t, "title"), sym=SYM.get(t.get("icon"), "•"), color=t.get("color", "#78909c"), tids=[],
                                           group=t.get("group", "Other"), group_he=loc(t, "group") or T("אחר")))
            g["tids"].append(tid)
        names = {"blender": T("עבודות Blender"), "tripo_shape": T("דגם 3D (TripoSG)"), "step1x_shape": T("דגם 3D (Step1X)"), "blender_bake": T("אפיית פרטים"), "qwen_edit": T("עריכת תמונה (Qwen)"), "zimage": T("תמונה מטקסט (Z-Image)"), "music": T("מוזיקה"), "sound": T("צלילים"), "scripts": T("סקריפטים"), "other": T("אחר"), "godot_test": T("בדיקות משחק")}
        self.models = []
        order = ["Images", "3D", "Audio", "Game", "Other"]
        for od, g in sorted(groups.items(), key=lambda kv: (order.index(kv[1]["group"]) if kv[1]["group"] in order else 99, kv[0])):
            g["title"] = names.get(od, g["title"])
            self.models.append(g)
            for tid in g["tids"]:
                self.type_dir[tid] = od
        self.fill_models()

    def refresh_type_stats(self):
        try:
            r = client.call({"op": "type_stats"}, timeout=3)
            if r.get("ok"):
                self.type_stats = r["stats"]
        except Exception:
            pass

    def count_outputs(self, od):
        try:
            return sum(1 for x in (Path(self.output_root) / od).iterdir() if x.is_dir())
        except OSError:
            return 0

    def fill_models(self):
        cur = self.sel_model
        ml = self.model_list
        ml.blockSignals(True)
        ml.clear()

        def add(text, data, kind="item", ic=None):
            it = W.QListWidgetItem(text)
            it.setData(Qt.UserRole, data)
            it.setData(ROLE_KIND, kind)
            if ic:
                it.setIcon(ic)
            if kind != "item":
                it.setFlags(Qt.NoItemFlags)
            ml.addItem(it)
            return it
        add(T("עוזר Claude"), "__assistant__", ic=sym_icon("✧", "#3574f0", 18))
        add(T("כל התוצאות"), None, ic=sym_icon("▤", "#b4b8bf", 18))
        last = None
        for g in self.models:
            if g["group"] != last:
                add(g["group_he"], "__caption__", "caption")
                last = g["group"]
            add(g["title"], g["dir"], ic=sym_icon(g["sym"], g["color"], 18))
        sel = 1
        want = "__assistant__" if self.assistant_mode else cur
        for i in range(ml.count()):
            if ml.item(i).data(ROLE_KIND) == "item" and ml.item(i).data(Qt.UserRole) == want:
                sel = i
        ml.setCurrentRow(sel)
        ml.blockSignals(False)
        self.on_model(sel)
        self.update_counts()

    def update_counts(self):
        for i in range(self.model_list.count()):
            it = self.model_list.item(i)
            if it.data(ROLE_KIND) == "item" and it.data(Qt.UserRole) not in (None, "__assistant__"):
                it.setData(ROLE_COUNT, self.count_outputs(it.data(Qt.UserRole)))
        self.model_list.viewport().update()

    def update_badges(self, s):
        run, wait = {}, {}
        for j in s["running"]:
            od = self.type_dir.get(j["type"])
            run[od] = run.get(od, 0) + 1
        for j in s["queued"]:
            od = self.type_dir.get(j["type"])
            wait[od] = wait.get(od, 0) + 1
        for i in range(self.model_list.count()):
            it = self.model_list.item(i)
            if it.data(ROLE_KIND) == "item":
                od = it.data(Qt.UserRole)
                it.setData(ROLE_RUN, run.get(od, 0))
                it.setData(ROLE_WAIT, wait.get(od, 0))
                gg = next((m for m in self.models if m["dir"] == od), None)
                about = ((loc(self.types.get(gg["tids"][0], {}), "about") or {}).get("what") or "") if gg else ""
                if od not in (None, "__assistant__"):
                    it.setToolTip(about + chr(10) * 2 if about else "")
                    it.setToolTip(it.toolTip() + "%s" % it.text() + chr(10) + T("רצות: %d   ממתינות: %d   תוצאות שמורות: %d") % (run.get(od, 0), wait.get(od, 0), it.data(ROLE_COUNT) or 0))
        self.model_list.viewport().update()

    def on_model(self, row):
        if row < 0:
            return
        item = self.model_list.item(row)
        if item.data(ROLE_KIND) != "item":
            return
        data = item.data(Qt.UserRole)
        self.assistant_mode = data == "__assistant__"
        self.sel_model = None if self.assistant_mode else data
        if getattr(self, "persist", True) and getattr(self, "settings", None):
            self.settings.setValue("last_model", data if data is not None else "")
        self.files_sig = None
        self.lower.setCurrentIndex(2 if self.assistant_mode else (1 if self.sel_model else 0))
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
        self.out_title.setText((T("תוצאות: ") + g["title"]) if g else T("כל התוצאות"))
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
        self.files_empty.setText(T("עוד אין תוצאות. כשעבודה תסתיים, הקבצים יופיעו כאן."))
        self.files_empty.setVisible(not files)
        self.update_counts()

    def files_menu(self, pos):
        it = self.files.itemAt(pos)
        if not it:
            return
        fp = it.data(Qt.UserRole)
        if fp == "__new__":
            return
        m = W.QMenu(self)
        m.addAction(T("פתח"), lambda: os.startfile(fp))
        m.addAction(T("פתח את תיקיית העבודה"), lambda: os.startfile(str(Path(fp).parent)))
        m.addAction(T("העתק נתיב"), lambda: W.QApplication.clipboard().setText(fp))
        if Path(fp).suffix.lower() in IMG:
            m.addAction(icon("arrow", "#b4b8bf", 16), T("שלח אל…"), lambda: self.send_menu(fp, QtGui.QCursor.pos()))
        rj = Path(fp).parent / "result.json"
        if rj.exists():
            try:
                jid = json.loads(rj.read_text(encoding="utf-8"))["job_id"]
                m.addAction(T("הרץ שוב את העבודה שיצרה את הקובץ"), lambda: self.rerun_job(jid))
            except (OSError, ValueError, KeyError):
                pass
        m.exec(self.files.viewport().mapToGlobal(pos))

    def hist_rerun(self):
        rows = sorted({i.row() for i in self.hist.selectedIndexes()})
        if not rows or rows[0] >= len(self.hist_jobs):
            self.toast(T("בחר קודם עבודה בהיסטוריה"), "warn")
            return
        for r in rows:
            self.rerun_job(self.hist_jobs[r]["id"])

    def hist_menu(self, pos):
        if not self.hist.selectedIndexes():
            return
        m = W.QMenu(self)
        m.addAction(T("הרץ שוב עם אותן הגדרות"), self.hist_rerun)
        m.addAction(T("פתח את תיקיית התוצאה"), lambda: self.hist_open(self.hist.currentItem()) if self.hist.currentItem() else None)
        m.exec(self.hist.viewport().mapToGlobal(pos))

    def hist_open(self, item):
        r = item.row()
        if r < len(self.hist_jobs) and self.hist_jobs[r].get("outdir") and os.path.isdir(self.hist_jobs[r]["outdir"]):
            os.startfile(self.hist_jobs[r]["outdir"])

    # ------------------------------------------------------------ state
    def on_down(self, msg):
        self.set_head("#868a91", T("השירות לא רץ"), T("התור והעבודות לא זמינים עד שהשירות יעלה"))
        self.sd_dot.set("#868a91")
        self.sd_lbl.setText(T("השירות כבוי"))
        if not getattr(self, "down_told", False):
            self.down_told = True
            self.toast(T("שירות ה-broker לא רץ"), "bad", T("הפעל"), self.start_service, 9000)

    def start_service(self):
        try:
            client.start_daemon()
            self.down_told = False
            self.toast(T("השירות עלה"), "ok")
        except Exception as e:
            self.toast(T("לא הצלחתי להפעיל את השירות"), "bad")

    def set_head(self, color, title, sub):
        self.dot.setStyleSheet("background:%s; border-radius:4px;" % color)
        self.h_title.setText(title)
        self.h_sub.setText(sub)

    def show_job(self, jid):
        for j in list(self.hist_jobs) + (self.state or {}).get("running", []) + (self.state or {}).get("queued", []):
            if j["id"] == jid:
                od = self.type_dir.get(j["type"])
                if od:
                    self.select_model(od)
                return

    def update_stats(self):
        today = time.strftime("%Y-%m-%d")
        js = [j for j in self.hist_jobs if j.get("finished") and time.strftime("%Y-%m-%d", time.localtime(j["finished"])) == today and j["state"] == "done"]
        total = sum(max(0, (j["finished"] or 0) - (j.get("started") or j["finished"])) for j in js)
        self.stat["done"].setText(str(len(js)))
        self.stat["time"].setText(fmt_dur(total) if js else "-")
        self.stat["ram"].setText("%.1f GB" % max([j.get("peak_ws") or 0 for j in js]) if js else "-")

    def type_info(self, tid):
        t = self.types.get(tid, {})
        return SYM.get(t.get("icon"), "•"), t.get("color", "#78909c"), loc(t, "title") or tid

    def on_state(self, s):
        self.down_told = False
        first = self.state is None
        self.state = s
        sy, lim = s["sys"], s["limits"]
        used = sy["ram_total"] - sy["ram_avail"]
        self.g_ram.set(used, sy["ram_total"], "%.0f / %.0f GB" % (used, sy["ram_total"]), marker=lim["ram_gb"])
        self.g_gpu.set(sy["gpu_used"], sy["gpu_total"], "%.1f / %.0f GB" % (sy["gpu_used"], sy["gpu_total"]), marker=lim["vram_gb"])
        self.g_disk.set(sy["disk"], 100, "%.0f%%" % sy["disk"])
        self.lim_sum.setText(T("עד %s · %s · %s עבודות במקביל") % (ltr("RAM %.0f GB" % lim["ram_gb"]), ltr("GPU %.0f GB" % lim["vram_gb"]), ltr("%d" % lim["max_jobs"])))
        self.g_cpu.set(sy["cpu"], 100, "%.0f%%" % sy["cpu"])
        nrun, nq = len(s["running"]), len(s["queued"])
        counts = T("רצות %d, ממתינות %d") % (nrun, nq) if (nrun or nq) else T("אין עבודות כרגע")
        st = s["status"]
        f = used / sy["ram_total"]
        if st == "BRAKE":
            self.set_head("#db5c5c", T("המחשב בלחץ, עצרתי הכול"), T("מעט RAM פנוי. עבודות חדשות לא יתחילו עד שיירגע. ") + counts)
        elif st == "PLAYING":
            self.set_head("#db5c5c", T("אתה משחק / מקליט"), T("עבודות GPU מחכות. ") + counts)
        elif st == "PAUSED":
            self.set_head("#e0a030", T("הכול מושהה"), T("שום עבודה חדשה לא מתחילה. ") + counts)
        elif f < 0.7:
            self.set_head("#5fad65", T("פעיל"), counts)
        elif f < 0.88:
            self.set_head("#e0a030", T("פעיל"), counts + T("   •   RAM עמוס"))
        else:
            self.set_head("#db5c5c", T("RAM כמעט מלא"), counts)
        self.play.setChecked(s["playing"])
        self.pause.setChecked(s["paused"])
        self.pause.setText(T("המשך") if s["paused"] else T("עצור הכול"))
        self.pause.setIcon(icon("play" if s["paused"] else "pause", "#b4b8bf", 16))
        self.building = True
        for k, (sl, val) in self.sl.items():
            if not sl.isSliderDown():
                sl.setValue(int(round(lim[k])))
                val.setText(fmt_limit(k, lim[k]))
        self.building = False
        self.fill_queue(s)
        self.sync_queue_panel(bool(s["running"] or s["queued"]))
        self.refresh_chat()
        self.update_badges(s)
        self.assistant_panel.on_perms(s.get("perms") or [], s.get("assistant_level"))
        self.sync_perm_notice(s.get("perms") or [])
        dot_col, dot_txt = {"ACTIVE": ("#5fad65", T("פעיל")), "PAUSED": ("#e0a030", T("מושהה")), "PLAYING": ("#db5c5c", T("משחק / הקלטה")), "BRAKE": ("#db5c5c", T("בלם בטיחות"))}[st]
        self.sd_dot.set(dot_col)
        self.sd_lbl.setText(dot_txt)
        self.s_ram.set(T("RAM פנוי %.0f GB") % sy["ram_avail"])
        self.s_commit.set(T("Commit פנוי %.0f GB") % sy["commit_avail"])
        self.s_lock.setVisible(s["lock"] != "none")
        if s["lock"] != "none":
            self.s_lock.set(T("נעילת GPU: ") + {"ours": T("אצל ה-broker"), "foreign": T("אצל תוכנה אחרת")}.get(s["lock"], s["lock"]), "#e0a030" if s["lock"] == "foreign" else None)
        run0 = next((j for j in s["running"] if j["state"] in ("running", "paused")), None)
        self.task.set_job(run0, max(0, nrun - 1))
        self.tabs.setTabText(0, T("תור (%d)") % (nrun + nq) if (nrun + nq) else T("תור"))
        if self.tray and st != self.last_status:
            self.tray.setIcon(make_icon({"ACTIVE": "#5fad65", "PAUSED": "#e0a030", "PLAYING": "#db5c5c", "BRAKE": "#db5c5c"}[st]))
            self.last_status = st
        for n, ts, text in s.get("events", []):
            self.log_text += "%s  %s\n" % (time.strftime("%H:%M:%S", time.localtime(ts)), text)
            mt = re.match(r"^#(\d+) (.+?) -> (done|failed|cancelled)", text)
            if mt and not first:
                jid, name, how = int(mt.group(1)), mt.group(2), mt.group(3)
                if how == "done":
                    self.toast(T("הסתיימה: ") + name, "ok", T("הצג"), lambda j=jid: self.show_job(j))
                elif how == "failed":
                    self.toast(T("נכשלה: ") + name, "bad", T("הצג"), lambda j=jid: self.show_job(j))
                if self.tray and how != "cancelled" and ((not self.isVisible()) or self.isMinimized()):     # the bar under the content already told him when the window is open
                    self.tray.showMessage("AI Broker", text[:150], W.QSystemTrayIcon.Information, 6000)
        self.log_text = self.log_text[-60000:]
        if s["hist_rev"] != self.hist_rev:
            self.hist_rev = s["hist_rev"]
            self.refresh_type_stats()
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
                tm, ram = T("%d שנ'") % j.get("elapsed", 0), ltr("%.1f GB" % j.get("cur_ws", 0))
                det = eta_text(j) or (ltr("GPU %.1f GB" % j["cur_vram"]) if j.get("cur_vram") else "")
            else:
                tm, ram, det = fmt_dur(time.time() - j["submitted"]), ltr("~%.0f GB" % j["est_ram"]), (T("עצרת אותה בעצמך") if j.get("held") else he_reason(j.get("reason", "")))
            vals = [str(j["id"]), ttl, j["name"], j["requester"], STATE_HE.get(st, st), tm, ram, det]
            for c, v in enumerate(vals):
                it = q.item(r, c) or W.QTableWidgetItem()
                it.setText(v)
                it.setToolTip(v if c in (2, 7) else ((T("הערכה: ") + j["est_source"]) if c == 6 else ""))
                if c == 1:
                    it.setIcon(sym_icon(sym, color, 16))
                elif c == 4:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(st, "#b4b8bf")))
                    it.setIcon(dot_icon(STATE_COLOR.get(st, "#b4b8bf"), 10))
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
        self.q_stack.setCurrentIndex(1 if jobs else 0)

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
                    it.setIcon(dot_icon(STATE_COLOR.get(j["state"], "#b4b8bf"), 10))
                h.setItem(i, c, it)
        self.update_stats()

    # ------------------------------------------------------------ window
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_gui(self):
        self.quitting = True
        self.close()

    def save_layout(self):
        if not getattr(self, "persist", True):
            return
        st = self.settings
        st.setValue("geometry", self.saveGeometry())
        st.setValue("split_main2", self.split_main.saveState())
        st.setValue("split_center2", self.split_center.saveState())
        st.setValue("zoom", self.zoom)

    def closeEvent(self, e):
        self.save_layout()
        if self.tray and not self.quitting:
            e.ignore()
            self.hide()
            if not self.settings.value("tray_hint"):
                self.tray.showMessage("AI Broker", T("החלון הוסתר לאזור ההודעות. העבודות ממשיכות לרוץ."), W.QSystemTrayIcon.Information, 6000)
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
    app.setLayoutDirection(Qt.RightToLeft if i18n.rtl() else Qt.LeftToRight)
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)
    app.setStyleSheet(QSS)
    try:
        client.start_daemon()
    except Exception as e:
        print("could not start the broker:", e)
    win = Main(tray=("--no-tray" not in argv and shot is None), model=model)
    win.persist = shot is None
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
