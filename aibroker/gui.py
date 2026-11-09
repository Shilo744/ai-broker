"""AI Broker desktop window (PySide6 / Qt 6): dark IDE-style main window with dockable tool windows.
Left: Job Library.  Centre: Queue.  Right: Resources (+ limits).  Bottom tabs: Log / Output / History.  Status bar, tray icon, toolbar.
The window is only a client of the broker service: closing it never stops the queue.
  python -m aibroker.gui [--screenshot out.png] [--size 1500x900] [--no-tray]"""
import collections
import json
import os
import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets as W
from PySide6.QtCore import Qt

from . import client, paths

QSS = """
* { font-family: 'Segoe UI'; font-size: 11pt; color: #cfd3d6; }
QMainWindow, QDialog { background: #2b2b2b; }
QMainWindow::separator { background: #3c3f41; width: 3px; height: 3px; }
QMenuBar { background: #3c3f41; } QMenuBar::item:selected { background: #4b6eaf; }
QMenu { background: #3c3f41; border: 1px solid #515151; } QMenu::item:selected { background: #4b6eaf; } QMenu::separator { height: 1px; background: #515151; margin: 3px 6px; }
QToolBar { background: #3c3f41; border: none; border-bottom: 1px solid #323232; spacing: 4px; padding: 3px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 3px; padding: 4px 9px; }
QToolButton:hover { background: #4c5052; border-color: #5e6060; } QToolButton:checked { background: #4b6eaf; color: white; }
QToolButton#play:checked { background: #a8321f; color: white; font-weight: bold; }
QToolButton#play { font-weight: bold; padding: 4px 14px; border: 1px solid #5e6060; }
QDockWidget { titlebar-close-icon: none; color: #bbbbbb; }
QDockWidget::title { background: #3c3f41; padding: 5px 8px; border-bottom: 1px solid #323232; font-weight: bold; }
QTabBar::tab { background: #3c3f41; padding: 5px 14px; border: 1px solid #323232; border-bottom: none; }
QTabBar::tab:selected { background: #2b2b2b; border-top: 2px solid #4b6eaf; color: #ffffff; }
QTableWidget, QTreeWidget, QPlainTextEdit, QListWidget, QTextEdit { background: #2b2b2b; alternate-background-color: #313335; border: none; gridline-color: #323232;
    selection-background-color: #2f65ca; selection-color: white; }
QPlainTextEdit, QTextEdit { font-family: Consolas; font-size: 10.5pt; color: #a9b7c6; }
QHeaderView::section { background: #3c3f41; color: #bbbbbb; border: none; border-right: 1px solid #323232; border-bottom: 1px solid #323232; padding: 4px 6px; }
QPushButton { background: #4c5052; border: 1px solid #5e6060; border-radius: 3px; padding: 4px 12px; } QPushButton:hover { background: #5a5e60; }
QPushButton:default { background: #365880; border-color: #4b6eaf; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #45494a; border: 1px solid #646464; border-radius: 2px; padding: 2px 4px; color: #dddddd; selection-background-color: #2f65ca; }
QSlider::groove:horizontal { height: 4px; background: #515151; border-radius: 2px; } QSlider::sub-page:horizontal { background: #4b6eaf; border-radius: 2px; }
QSlider::handle:horizontal { background: #bbbbbb; width: 12px; margin: -5px 0; border-radius: 6px; }
QStatusBar { background: #3c3f41; border-top: 1px solid #323232; } QStatusBar::item { border: none; }
QStatusBar QLabel { padding: 0 8px; }
QGroupBox { border: 1px solid #4a4a4a; border-radius: 3px; margin-top: 10px; padding-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #8c8c8c; }
QCheckBox::indicator { width: 13px; height: 13px; background: #45494a; border: 1px solid #646464; border-radius: 2px; } QCheckBox::indicator:checked { background: #4b6eaf; border-color: #6b8ecf; } QScrollBar:vertical { background: #2b2b2b; width: 11px; } QScrollBar::handle:vertical { background: #4a4d4f; min-height: 24px; border-radius: 4px; }
QScrollBar:horizontal { background: #2b2b2b; height: 11px; } QScrollBar::handle:horizontal { background: #4a4d4f; min-width: 24px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QToolTip { background: #3c3f41; color: #dddddd; border: 1px solid #646464; }
"""

STATE_COLOR = {"running": "#6a9955", "paused": "#d7ba7d", "queued": "#9aa5b1", "done": "#6a9955", "failed": "#e06c75", "cancelled": "#8c8c8c", "lost": "#d19a66"}


def fmt_dur(s):
    s = int(s or 0)
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def make_icon(color="#4b6eaf"):
    pm = QtGui.QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    p.setPen(QtGui.QColor("white"))
    f = QtGui.QFont("Segoe UI", 24, QtGui.QFont.Bold)
    p.setFont(f)
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


class Gauge(W.QWidget):
    """Horizontal bar with caption, optional limit marker and a sparkline of the last 2 minutes."""
    def __init__(self, title, unit="GB", limit_marker=True):
        super().__init__()
        self.title, self.unit = title, unit
        self.value = self.maximum = 0.0
        self.marker = None
        self.hist = collections.deque(maxlen=120)
        self.text = ""
        self.setMinimumHeight(58)

    def set(self, value, maximum, marker=None, text=None):
        self.value, self.maximum, self.marker = value, max(maximum, 1e-9), marker
        self.text = text if text is not None else "%.1f / %.0f %s" % (value, maximum, self.unit)
        self.hist.append(value / self.maximum)
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QtGui.QColor("#bbbbbb"))
        f0 = p.font()
        f0.setPointSize(11)
        p.setFont(f0)
        p.drawText(0, 15, self.title)
        p.drawText(QtCore.QRect(0, 0, w, 18), Qt.AlignRight, self.text)
        bar = QtCore.QRectF(0, 24, w, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#3c3f41"))
        p.drawRoundedRect(bar, 3, 3)
        f = max(0.0, min(1.0, self.value / self.maximum))
        col = "#6a9955" if f < 0.7 else "#d7ba7d" if f < 0.88 else "#e06c75"
        p.setBrush(QtGui.QColor(col))
        p.drawRoundedRect(QtCore.QRectF(0, 24, w * f, 14), 3, 3)
        if self.marker is not None:
            x = w * min(1.0, self.marker / self.maximum)
            p.setPen(QtGui.QPen(QtGui.QColor("#4b9fff"), 2))
            p.drawLine(QtCore.QPointF(x, 21), QtCore.QPointF(x, 41))
        if len(self.hist) > 1:
            pts = [QtCore.QPointF(i * w / 119.0, h - 2 - min(1.0, v) * 12) for i, v in enumerate(self.hist)]
            p.setPen(QtGui.QPen(QtGui.QColor("#5c7fb8"), 1))
            p.drawPolyline(pts)


class QueueTable(W.QTableWidget):
    COLS = ["#", "Job", "Requester", "Model", "Est RAM", "Est VRAM", "State", "Time", "Live / why waiting"]
    reorder = QtCore.Signal(list, int)

    def __init__(self):
        super().__init__(0, len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(34)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(W.QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)            # we move jobs ourselves; Qt must not move/clear the cells
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)
        for i, wd in enumerate((40, 250, 100, 170, 80, 80, 100, 70)):
            self.setColumnWidth(i, wd)
        self.job_ids = []
        self.queued_ids = []

    def dropEvent(self, e):
        pos = e.position().toPoint()
        row = self.rowAt(pos.y())
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
            if tid in rest:
                at = rest.index(tid) + (1 if self.dropIndicatorPosition() == W.QAbstractItemView.BelowItem else 0)
            else:                                           # dropped on a running row: top of the queue
                at = 0
        e.setDropAction(Qt.CopyAction)
        e.accept()
        self.reorder.emit(moved, at + 1)

    def selected_ids(self):
        return [self.job_ids[r] for r in sorted({i.row() for i in self.selectedIndexes()}) if r < len(self.job_ids)]


class NewJobDialog(W.QDialog):
    def __init__(self, parent, tid, t, requester):
        super().__init__(parent)
        self.t, self.edits = t, {}
        self.setWindowTitle("New job: " + t.get("title", tid))
        self.setMinimumWidth(560)
        lay = W.QVBoxLayout(self)
        if t.get("notes"):
            n = W.QLabel(t["notes"])
            n.setWordWrap(True)
            n.setStyleSheet("color:#8c8c8c")
            lay.addWidget(n)
        form = W.QFormLayout()
        self.name = W.QLineEdit()
        self.name.setPlaceholderText(t.get("title", tid))
        self.req = W.QLineEdit(requester)
        form.addRow("Name", self.name)
        form.addRow("Requester", self.req)
        for k, spec in (t.get("params") or {}).items():
            d = spec.get("default") if isinstance(spec, dict) else spec
            e = W.QLineEdit("" if d is None else (json.dumps(d) if isinstance(d, (list, dict)) else str(d)))
            if isinstance(spec, dict) and spec.get("help"):
                e.setToolTip(spec["help"])
                e.setPlaceholderText(spec["help"])
            lbl = k + (" *" if isinstance(spec, dict) and spec.get("required") else "")
            form.addRow(lbl, e)
            self.edits[k] = e
        if tid == "custom":
            self.cmd = W.QLineEdit()
            self.cmd.setPlaceholderText("command line, e.g. python script.py --x 1")
            form.addRow("Command *", self.cmd)
        self.ram = W.QDoubleSpinBox()
        self.ram.setRange(0, 64)
        self.ram.setSpecialValueText("auto (learned)")
        self.vram = W.QDoubleSpinBox()
        self.vram.setRange(0, 16)
        self.vram.setSpecialValueText("auto (learned)")
        form.addRow("Est RAM GB", self.ram)
        form.addRow("Est VRAM GB", self.vram)
        self.next = W.QCheckBox("Run next (top of the queue)")
        form.addRow("", self.next)
        lay.addLayout(form)
        bb = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def request(self, tid):
        params = {}
        for k, e in self.edits.items():
            v = e.text().strip()
            if v == "":
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
        req = dict(op="submit", type=tid, params=params, name=self.name.text().strip() or None, requester=self.req.text().strip() or "owner", est=est or None, next=self.next.isChecked())
        if tid == "custom":
            import shlex
            req["cmd"] = shlex.split(self.cmd.text(), posix=False)
        return req


class Main(W.QMainWindow):
    def __init__(self, tray=True):
        super().__init__()
        self.setWindowTitle("AI Broker")
        self.setWindowIcon(make_icon())
        self.resize(1500, 900)
        self.state = None
        self.types = {}
        self.hist_rev = -1
        self.sel_job = None
        self.quitting = False
        self.last_tray_status = None
        self.building_limits = False
        self._build_center()
        self._build_docks()
        self._build_toolbar()
        self._build_menu()
        self._build_status()
        self.tray = None
        if tray and QtWidgets_tray_ok():
            self._build_tray()
        self.settings = QtCore.QSettings("ai-broker", "gui")
        self._default_state = self.saveState()
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
            self.restoreState(self.settings.value("state"))
        self.poller = Poller()
        self.poller.got.connect(self.on_state)
        self.poller.down.connect(self.on_down)
        self.poller.start()
        self.load_types()
        t = QtCore.QTimer(self)
        t.timeout.connect(self.refresh_output)
        t.start(1000)

    # ---------------------------------------------------------------- layout
    def _build_center(self):
        self.queue = QueueTable()
        self.queue.reorder.connect(self.on_reorder)
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self.queue_menu)
        self.queue.itemSelectionChanged.connect(self.on_select)
        self.queue.doubleClicked.connect(lambda *_: self.show_output_tab())
        box = W.QWidget()
        lay = W.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        head = W.QLabel("  Queue   running jobs first, then waiting jobs in order. Drag waiting rows to reorder; right-click for more.")
        head.setStyleSheet("background:#3c3f41; padding:5px; color:#8c8c8c")
        lay.addWidget(head)
        lay.addWidget(self.queue)
        self.setCentralWidget(box)

    def dock(self, title, widget, area, name):
        d = W.QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setFeatures(W.QDockWidget.DockWidgetMovable | W.QDockWidget.DockWidgetFloatable | W.QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        # Job Library
        self.lib = W.QTreeWidget()
        self.lib.setHeaderLabels(["Job type", "RAM", "VRAM"])
        self.lib.setColumnWidth(0, 230)
        self.lib.setColumnWidth(1, 36)
        self.lib.setColumnWidth(2, 44)
        self.lib.setIndentation(14)
        self.lib.itemDoubleClicked.connect(self.on_lib_double)
        self.d_lib = self.dock("Job Library  (double-click to create a job)", self.lib, Qt.LeftDockWidgetArea, "lib")
        # Resources
        res = W.QWidget()
        rl = W.QVBoxLayout(res)
        self.g_ram = Gauge("Memory (RAM) in use")
        self.g_commit = Gauge("Commit (RAM + pagefile)")
        self.g_vram = Gauge("GPU memory (VRAM)")
        self.g_cpu = Gauge("CPU", "%")
        self.g_disk = Gauge("Disk busy", "%")
        self.g_airam = Gauge("AI jobs: RAM budget")
        self.g_aivram = Gauge("AI jobs: VRAM budget")
        for g in (self.g_ram, self.g_commit, self.g_vram, self.g_cpu, self.g_disk, self.g_airam, self.g_aivram):
            rl.addWidget(g)
        gb = W.QGroupBox("Limits (soft; change while running)")
        fl = W.QFormLayout(gb)
        self.sl = {}
        for key, label, lo, hi, step in (("ram_gb", "AI RAM budget GB", 4, 62, 1), ("vram_gb", "AI VRAM budget GB", 2, 16, 1), ("max_jobs", "Max concurrent jobs", 1, 8, 1),
                                         ("reserve_ram_gb", "Keep free RAM GB", 0, 24, 1)):
            row = W.QWidget()
            hl = W.QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            s = W.QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setSingleStep(step)
            lab = W.QLabel("0")
            lab.setMinimumWidth(26)
            s.valueChanged.connect(lambda v, l=lab: l.setText(str(v)))
            s.sliderReleased.connect(lambda k=key, sl=s: self.set_limit(k, sl.value()))
            s.actionTriggered.connect(lambda act, k=key, sl=s: QtCore.QTimer.singleShot(0, lambda: self.set_limit(k, sl.value()) if not sl.isSliderDown() else None))
            hl.addWidget(s)
            hl.addWidget(lab)
            fl.addRow(label, row)
            self.sl[key] = (s, lab)
        self.flag_boxes = {}
        for key, label in (("affinity", "Group jobs on the same model (affinity)"), ("backfill", "Let small jobs overtake a waiting big one"),
                           ("emergency_suspend", "Safety brake suspends the youngest job"), ("suspend_on_pause", "Pause all also freezes running jobs"),
                           ("toast", "Windows toast when a job ends")):
            c = W.QCheckBox(label)
            c.toggled.connect(lambda on, k=key: self.set_flag(k, on))
            fl.addRow(c)
            self.flag_boxes[key] = c
        rl.addWidget(gb)
        rl.addStretch(1)
        self.d_res = self.dock("Resources", res, Qt.RightDockWidgetArea, "res")
        self.d_res.setMinimumWidth(330)
        # Log / Output / History
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.out = W.QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(4000)
        ow = W.QWidget()
        ol = W.QVBoxLayout(ow)
        ol.setContentsMargins(0, 0, 0, 0)
        self.out_title = W.QLabel("  Select a job in the queue or in History to see its output")
        self.out_title.setStyleSheet("background:#3c3f41; padding:3px; color:#8c8c8c")
        ol.addWidget(self.out_title)
        ol.addWidget(self.out)
        self.hist = W.QTableWidget(0, 10)
        self.hist.setHorizontalHeaderLabels(["#", "Job", "Requester", "State", "Started", "Duration", "Peak RAM GB", "Peak commit GB", "Peak VRAM GB", "Exit"])
        self.hist.verticalHeader().hide()
        self.hist.verticalHeader().setDefaultSectionSize(30)
        self.hist.setAlternatingRowColors(True)
        self.hist.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.hist.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.hist.setShowGrid(False)
        self.hist.horizontalHeader().setStretchLastSection(True)
        self.hist.setColumnWidth(1, 240)
        self.hist.itemSelectionChanged.connect(self.on_hist_select)
        self.hist_ids = []
        self.d_log = self.dock("Log", self.log, Qt.BottomDockWidgetArea, "log")
        self.d_out = self.dock("Output", ow, Qt.BottomDockWidgetArea, "out")
        self.d_hist = self.dock("History", self.hist, Qt.BottomDockWidgetArea, "hist")
        self.tabifyDockWidget(self.d_log, self.d_out)
        self.tabifyDockWidget(self.d_out, self.d_hist)
        self.d_log.raise_()
        self.resizeDocks([self.d_lib, self.d_res], [330, 350], Qt.Horizontal)
        self.resizeDocks([self.d_log], [250], Qt.Vertical)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("toolbar")
        tb.setMovable(False)
        self.a_new = tb.addAction("＋ New job…")
        self.a_new.triggered.connect(self.new_custom)
        tb.addSeparator()
        self.a_pause = tb.addAction("⏸ Pause all")
        self.a_pause.triggered.connect(self.toggle_pause)
        tb.addSeparator()
        self.play_btn = W.QToolButton()
        self.play_btn.setObjectName("play")
        self.play_btn.setCheckable(True)
        self.play_btn.setText("🎮  I am playing / recording")
        self.play_btn.setToolTip("GPU jobs wait and running GPU jobs are suspended while this is on")
        self.play_btn.clicked.connect(lambda on: self.api({"op": "playing", "on": on}))
        tb.addWidget(self.play_btn)
        tb.addSeparator()
        self.a_cancel = tb.addAction("✕ Cancel selected")
        self.a_cancel.triggered.connect(lambda: [self.api({"op": "cancel", "id": i}) for i in self.queue.selected_ids()])
        self.a_next = tb.addAction("⏫ Run next")
        self.a_next.triggered.connect(lambda: self.api({"op": "move", "ids": self.queued_sel(), "to": "top"}) if self.queued_sel() else None)
        sp = W.QWidget()
        sp.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Preferred)
        tb.addWidget(sp)
        self.state_lbl = W.QLabel("connecting…")
        self.state_lbl.setStyleSheet("font-weight:bold; padding:0 10px")
        tb.addWidget(self.state_lbl)

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction("New custom job…", self.new_custom, "Ctrl+N")
        m.addSeparator()
        m.addAction("Open data folder", lambda: os.startfile(str(paths.HOME)))
        m.addAction("Open broker log file", lambda: os.startfile(str(paths.HOME / "broker.log")) if (paths.HOME / "broker.log").exists() else None)
        m.addSeparator()
        m.addAction("Quit window (the broker keeps running)", self.quit_gui, "Ctrl+Q")
        m = mb.addMenu("&Queue")
        m.addAction("Pause / resume all", self.toggle_pause, "Ctrl+P")
        m.addAction("Toggle 'I am playing'", lambda: self.play_btn.click(), "Ctrl+G")
        m.addSeparator()
        m.addAction("Run next", lambda: self.api({"op": "move", "ids": self.queued_sel(), "to": "top"}) if self.queued_sel() else None)
        m.addAction("Move up", lambda: self.api({"op": "move", "ids": self.queued_sel(), "to": "up"}) if self.queued_sel() else None, "Alt+Up")
        m.addAction("Move down", lambda: self.api({"op": "move", "ids": self.queued_sel(), "to": "down"}) if self.queued_sel() else None, "Alt+Down")
        m = mb.addMenu("&View")
        for d in (self.d_lib, self.d_res, self.d_log, self.d_out, self.d_hist):
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        m.addAction("Reset layout", lambda: self.restoreState(self._default_state))
        m = mb.addMenu("&Broker")
        m.addAction("Start broker service", lambda: self.run_safe(client.start_daemon))
        m.addAction("Stop broker service (running jobs keep running)", self.stop_broker)
        m = mb.addMenu("&Help")
        m.addAction("Switch to the SIMPLE view (big cards, Hebrew)", self.switch_view)
        m.addAction("About", lambda: W.QMessageBox.about(self, "AI Broker", "AI Broker 1.0\nOne queue for all local AI/GPU jobs.\nPySide6 (Qt, LGPL-3) + psutil."))

    def switch_view(self):
        import subprocess
        subprocess.Popen([str(paths.VENV_PYW), "-m", "aibroker.gui_simple"], cwd=str(paths.ROOT))
        self.quitting = True
        self.close()

    def _build_status(self):
        sb = self.statusBar()
        self.sb = {k: W.QLabel("") for k in ("run", "queue", "ram", "commit", "vram", "state")}
        for k in ("run", "queue", "ram", "commit", "vram"):
            sb.addWidget(self.sb[k])
        sb.addPermanentWidget(self.sb["state"])

    def _build_tray(self):
        self.tray = W.QSystemTrayIcon(make_icon(), self)
        menu = W.QMenu()
        menu.addAction("Show window", self.show_normal)
        menu.addAction("Pause / resume all", self.toggle_pause)
        menu.addAction("Toggle 'I am playing'", lambda: self.play_btn.click())
        menu.addSeparator()
        menu.addAction("Quit window", self.quit_gui)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (W.QSystemTrayIcon.Trigger, W.QSystemTrayIcon.DoubleClick) else None)
        self.tray.setToolTip("AI Broker")
        self.tray.show()

    # ---------------------------------------------------------------- actions
    def api(self, req):
        try:
            r = client.call(req, timeout=5)
            if not r.get("ok"):
                self.statusBar().showMessage("broker: " + str(r.get("error")), 6000)
            return r
        except Exception as e:
            self.statusBar().showMessage("broker not reachable: %s" % e, 6000)

    def run_safe(self, f):
        try:
            f()
        except Exception as e:
            self.statusBar().showMessage(str(e), 6000)

    def stop_broker(self):
        if W.QMessageBox.question(self, "Stop broker", "Stop the broker service? Running jobs keep running but the queue stops and exit codes get lost.") == W.QMessageBox.Yes:
            self.api({"op": "shutdown"})

    def toggle_pause(self):
        self.api({"op": "resume"} if self.state and self.state.get("paused") else {"op": "pause"})

    def queued_sel(self):
        return [i for i in self.queue.selected_ids() if i in self.queue.queued_ids]

    def on_reorder(self, ids, pos):
        self.api({"op": "move", "ids": ids, "to": pos})

    def set_limit(self, key, v):
        if not self.building_limits:
            self.api({"op": "limits", "set": {key: v}})

    def set_flag(self, key, on):
        if not self.building_limits:
            self.api({"op": "limits", "flags": {key: on}})

    def new_custom(self):
        self.open_new("custom")

    def on_lib_double(self, item, _col):
        tid = item.data(0, Qt.UserRole)
        if tid:
            self.open_new(tid)

    def open_new(self, tid):
        t = self.types.get(tid)
        if not t:
            return
        dlg = NewJobDialog(self, tid, t, "owner")
        if dlg.exec() == W.QDialog.Accepted:
            r = self.api(dlg.request(tid))
            if r and r.get("ok"):
                self.statusBar().showMessage("queued job #%d" % r["id"], 5000)

    def load_types(self):
        r = self.api({"op": "types"})
        if not r or not r.get("ok"):
            return
        self.types = r["types"]
        self.lib.clear()
        groups = {}
        for tid, t in sorted(self.types.items(), key=lambda kv: (kv[1].get("group", "Other"), kv[0])):
            g = groups.get(t.get("group", "Other"))
            if g is None:
                g = W.QTreeWidgetItem([{"Images": "🖼️  Images", "3D": "🧊  3D models", "Audio": "🎵  Audio", "Game": "🎮  Game tests", "Other": "⚙️  Other"}.get(t.get("group", "Other"), t.get("group", "Other"))])
                g.setFlags(Qt.ItemIsEnabled)
                g.setForeground(0, QtGui.QBrush(QtGui.QColor('#e8c36a')))
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                self.lib.addTopLevelItem(g)
                groups[t.get("group", "Other")] = g
            e = t.get("est", {})
            it = W.QTreeWidgetItem([t.get("icon", "⚙️") + "  " + t.get("title", tid), "%.0f" % e.get("ram_gb", 0), "%.0f" % e.get("vram_gb", 0) if e.get("vram_gb") else "-"])
            it.setData(0, Qt.UserRole, tid)
            it.setToolTip(0, (t.get("notes") or t.get("title", tid)) + "\ntype id: " + tid + "\nclass: " + t.get("klass", "cpu"))
            g.addChild(it)
        self.lib.expandAll()

    def queue_menu(self, pos):
        ids = self.queue.selected_ids()
        if not ids:
            return
        m = W.QMenu(self)
        q = [i for i in ids if i in self.queue.queued_ids]
        run = [i for i in ids if i not in self.queue.queued_ids]
        jobs = {j["id"]: j for j in (self.state or {}).get("running", []) + (self.state or {}).get("queued", [])}
        if q:
            m.addAction("⏫ Run next", lambda: self.api({"op": "move", "ids": q, "to": "top"}))
            m.addAction("▲ Move up", lambda: self.api({"op": "move", "ids": q, "to": "up"}))
            m.addAction("▼ Move down", lambda: self.api({"op": "move", "ids": q, "to": "down"}))
            m.addAction("⏬ Move to bottom", lambda: self.api({"op": "move", "ids": q, "to": "bottom"}))
            m.addSeparator()
        for i in ids:
            j = jobs.get(i)
            if not j:
                continue
            if j["state"] == "queued":
                m.addAction(("▶ Release #%d" if j["held"] else "⏸ Hold #%d") % i, lambda i=i, h=j["held"]: self.api({"op": "job_resume" if h else "job_pause", "id": i}))
            elif j["state"] in ("running", "paused"):
                m.addAction(("▶ Resume #%d" if j.get("suspended") else "⏸ Suspend #%d") % i, lambda i=i, s=j.get("suspended"): self.api({"op": "job_resume" if s else "job_pause", "id": i}))
        m.addSeparator()
        m.addAction("✕ Cancel (%d)" % len(ids), lambda: [self.api({"op": "cancel", "id": i}) for i in ids])
        m.addAction("Show output", self.show_output_tab)
        m.exec(self.queue.viewport().mapToGlobal(pos))

    def show_output_tab(self):
        self.d_out.show()
        self.d_out.raise_()

    def on_select(self):
        ids = self.queue.selected_ids()
        if ids:
            self.sel_job = ids[0]
            self.refresh_output()

    def on_hist_select(self):
        rows = sorted({i.row() for i in self.hist.selectedIndexes()})
        if rows and rows[0] < len(self.hist_ids):
            self.sel_job = self.hist_ids[rows[0]]
            self.refresh_output()

    def refresh_output(self):
        if self.sel_job is None or not self.d_out.isVisible():
            return
        r = None
        try:
            r = client.call({"op": "tail", "id": self.sel_job, "bytes": 30000}, timeout=3)
        except Exception:
            return
        if r and r.get("ok"):
            bar = self.out.verticalScrollBar()
            at_end = bar.value() >= bar.maximum() - 4
            txt = r["text"]
            if txt != getattr(self, "_out_txt", None):
                self._out_txt = txt
                self.out.setPlainText(txt)
                if at_end:
                    bar.setValue(bar.maximum())
            self.out_title.setText("  Output of job #%d (last 30 KB)" % self.sel_job)

    # ---------------------------------------------------------------- state
    def on_down(self, msg):
        self.state_lbl.setText("● broker not running")
        self.state_lbl.setStyleSheet("font-weight:bold; padding:0 10px; color:#e06c75")
        self.sb["state"].setText("broker offline")

    def on_state(self, s):
        first = self.state is None
        self.state = s
        sy = s["sys"]
        lim = s["limits"]
        self.g_ram.set(sy["ram_total"] - sy["ram_avail"], sy["ram_total"], marker=None, text="%.1f / %.0f GB (free %.1f)" % (sy["ram_total"] - sy["ram_avail"], sy["ram_total"], sy["ram_avail"]))
        self.g_commit.set(sy["commit_limit"] - sy["commit_avail"], sy["commit_limit"], text="%.0f / %.0f GB (free %.0f)" % (sy["commit_limit"] - sy["commit_avail"], sy["commit_limit"], sy["commit_avail"]))
        self.g_vram.set(sy["gpu_used"], sy["gpu_total"], marker=lim["vram_gb"], text="%.1f / %.1f GB" % (sy["gpu_used"], sy["gpu_total"]))
        self.g_cpu.set(sy["cpu"], 100, text="%.0f %%" % sy["cpu"])
        self.g_disk.set(sy["disk"], 100, text="%.0f %%" % sy["disk"])
        self.g_airam.set(s["budget"]["ram"], lim["ram_gb"], text="%.1f / %.0f GB (limit)" % (s["budget"]["ram"], lim["ram_gb"]))
        self.g_aivram.set(s["budget"]["vram"], lim["vram_gb"], text="%.1f / %.0f GB (limit)" % (s["budget"]["vram"], lim["vram_gb"]))
        self.building_limits = True
        for k, (sl, lab) in self.sl.items():
            if not sl.isSliderDown():
                sl.setValue(int(round(lim[k])))
                lab.setText(str(int(round(lim[k]))))
        for k, c in self.flag_boxes.items():
            c.setChecked(bool(s["flags"].get(k)))
        self.play_btn.setChecked(s["playing"])
        self.building_limits = False
        self.a_pause.setText("▶ Resume" if s["paused"] else "⏸ Pause all")
        status = s["status"]
        col = {"ACTIVE": "#6a9955", "PAUSED": "#d7ba7d", "PLAYING": "#e06c75", "BRAKE": "#e06c75"}[status]
        self.state_lbl.setText("● " + status)
        self.state_lbl.setStyleSheet("font-weight:bold; padding:0 10px; color:" + col)
        self.sb["state"].setText(status + (" - " + s["brake"] if s["brake"] else "") + ("   GPU lock: " + s["lock"] if s["lock"] != "none" else ""))
        self.sb["run"].setText("Running %d" % len(s["running"]))
        self.sb["queue"].setText("Queued %d" % len(s["queued"]))
        self.sb["ram"].setText("Free RAM %.1f GB" % sy["ram_avail"])
        self.sb["commit"].setText("Commit free %.0f GB" % sy["commit_avail"])
        self.sb["vram"].setText("VRAM %.1f/%.1f GB" % (sy["gpu_used"], sy["gpu_total"]))
        if self.tray and status != self.last_tray_status:
            self.tray.setIcon(make_icon({"ACTIVE": "#3d7a3d", "PAUSED": "#b08d2f", "PLAYING": "#a8321f", "BRAKE": "#a8321f"}[status]))
            self.tray.setToolTip("AI Broker: %s, %d running, %d queued" % (status, len(s["running"]), len(s["queued"])))
            self.last_tray_status = status
        for n, ts, text in s.get("events", []):
            self.log.appendPlainText("%s  %s" % (time.strftime("%H:%M:%S", time.localtime(ts)), text))
            if self.tray and not first and " -> " in text and text.startswith("#"):
                self.tray.showMessage("AI Broker", text[:150], W.QSystemTrayIcon.Information, 6000)
        self.fill_queue(s)
        if s["hist_rev"] != self.hist_rev:
            self.hist_rev = s["hist_rev"]
            self.fill_history()
        if first:
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def fill_queue(self, s):
        if QtWidgets_mouse_down():
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
            st = "held" if j["state"] == "queued" and j.get("held") else ("suspended" if j.get("suspended") else j["state"])
            live = ""
            if j["state"] in ("running", "paused"):
                live = "RAM %.1f GB  VRAM %.1f GB" % (j.get("cur_ws", 0), j.get("cur_vram", 0))
            else:
                live = j.get("reason") or ("starts next tick" if not j.get("held") else "held by owner")
            tm = fmt_dur(j.get("elapsed", 0)) if j["state"] in ("running", "paused") else fmt_dur(time.time() - j["submitted"])
            ic = (self.types.get(j["type"], {}).get("icon", "⚙️") + "  ")
            vals = [str(j["id"]), ic + j["name"], j["requester"], self.types.get(j["type"], {}).get("title", j["model"]).split("(")[0].strip(), "%.1f" % j["est_ram"], "%.1f" % j["est_vram"] if j["est_vram"] else "-", st, tm, live]
            for c, v in enumerate(vals):
                it = q.item(r, c) or W.QTableWidgetItem()
                it.setText(v)
                if c == 6:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(j["state"], "#bbbbbb") if st != "suspended" and st != "held" else "#d7ba7d"))
                elif c == 8:
                    it.setForeground(QtGui.QColor("#e0a070" if j["state"] == "queued" and j.get("reason") else "#a9b7c6"))
                elif c in (4, 5):
                    it.setToolTip(j["est_source"])
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if j["state"] == "queued":
                    flags |= Qt.ItemIsDragEnabled
                it.setFlags(flags)
                if c == 1 and j["manual"]:
                    it.setToolTip("moved by the owner: affinity will not jump over it")
                q.setItem(r, c, it)
            if j["id"] in sel:
                q.selectRow(r)
        q.verticalScrollBar().setValue(vs)
        q.setUpdatesEnabled(True)

    def fill_history(self):
        r = self.api({"op": "history", "limit": 200})
        if not r or not r.get("ok"):
            return
        h = self.hist
        jobs = r["jobs"]
        h.setRowCount(len(jobs))
        self.hist_ids = [j["id"] for j in jobs]
        for i, j in enumerate(jobs):
            dur = (j.get("finished") or 0) - (j.get("started") or j.get("finished") or 0)
            vals = [str(j["id"]), j["name"], j["requester"], j["state"], time.strftime("%m-%d %H:%M:%S", time.localtime(j["started"])) if j.get("started") else "-", fmt_dur(dur),
                    "%.1f" % (j.get("peak_ws") or 0), "%.1f" % (j.get("peak_commit") or 0), "%.1f" % (j.get("peak_vram") or 0), str(j.get("rc"))]
            for c, v in enumerate(vals):
                it = W.QTableWidgetItem(v)
                if c == 3:
                    it.setForeground(QtGui.QColor(STATE_COLOR.get(j["state"], "#bbbbbb")))
                if c >= 6 and c <= 8:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                h.setItem(i, c, it)

    # ---------------------------------------------------------------- window
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_gui(self):
        self.quitting = True
        self.close()

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        if self.tray and not self.quitting:
            e.ignore()
            self.hide()
            if not self.settings.value("tray_hint_shown"):
                self.tray.showMessage("AI Broker", "The window is hidden in the tray. The broker keeps running. Use the tray icon to bring it back or to quit the window.", W.QSystemTrayIcon.Information, 6000)
                self.settings.setValue("tray_hint_shown", True)
            return
        self.poller.alive = False
        self.poller.wait(2000)
        W.QApplication.quit()


def QtWidgets_tray_ok():
    return W.QSystemTrayIcon.isSystemTrayAvailable()


def QtWidgets_mouse_down():
    return bool(W.QApplication.mouseButtons() & Qt.LeftButton)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    shot = None
    size = None
    if "--screenshot" in argv:
        shot = argv[argv.index("--screenshot") + 1]
    if "--size" in argv:
        size = [int(x) for x in argv[argv.index("--size") + 1].lower().split("x")]
    app = W.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setApplicationName("AI Broker")
    try:
        client.start_daemon()
    except Exception as e:
        print("could not start the broker:", e)
    win = Main(tray=("--no-tray" not in argv and shot is None))
    if size:
        win.resize(*size)
    if shot:
        win.restoreState(win._default_state)
        win.show()

        def grab():
            win.grab().save(shot)
            print("saved", shot)
            win.quitting = True
            win.close()
        QtCore.QTimer.singleShot(3500, grab)
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
