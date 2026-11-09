"""Small design-system widgets used by the window: tool-window headers, resource gauges with a history graph, status chips, toasts, the model-list row painter,
the status-bar background-task indicator, a wrapping layout for pills, and the command palette (Ctrl+K)."""
import time
from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets as W
from PySide6.QtCore import Qt

from .theme import ACCENT, BAD, BG, BORDER, LINE, MUTED, OK, PANEL, SELECT, SUB, TEXT, WARN, icon, icon_pixmap

ROLE_KIND = Qt.UserRole + 1       # "item" | "caption" | "sep"
ROLE_COUNT = Qt.UserRole + 2      # number of saved results
ROLE_RUN = Qt.UserRole + 3        # running jobs
ROLE_WAIT = Qt.UserRole + 4       # waiting jobs
ROLE_COLOR = Qt.UserRole + 5


def tool_button(icon_name, tip, slot=None, size=16, checkable=False, color=SUB):
    b = W.QToolButton()
    b.setIcon(icon(icon_name, color, size))
    b.setIconSize(QtCore.QSize(size, size))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    if slot:
        b.clicked.connect(slot)
    return b


class ToolHeader(W.QFrame):
    """Title strip of a tool window: icon, title, then small action buttons at the end."""
    def __init__(self, title, icon_name=None, sub=None):
        super().__init__()
        self.setObjectName("toolheader")
        self.setFixedHeight(34)
        self.h = W.QHBoxLayout(self)
        self.h.setContentsMargins(12, 0, 6, 0)
        self.h.setSpacing(7)
        self.icon_lbl = W.QLabel()
        if icon_name:
            self.icon_lbl.setPixmap(icon_pixmap(icon_name, MUTED, 15))
            self.h.addWidget(self.icon_lbl)
        self.title = W.QLabel(title)
        self.title.setObjectName("h2")
        self.h.addWidget(self.title)
        self.sub = W.QLabel(sub or "")
        self.sub.setObjectName("muted")
        self.sub.setLayoutDirection(Qt.LeftToRight)
        self.h.addWidget(self.sub, 1)

    def set_icon(self, name, color=MUTED):
        self.icon_lbl.setPixmap(icon_pixmap(name, color, 15))
        if self.h.indexOf(self.icon_lbl) < 0:
            self.h.insertWidget(0, self.icon_lbl)

    def add_action(self, icon_name, tip, slot):
        b = tool_button(icon_name, tip, slot)
        self.h.addWidget(b)
        return b


# ------------------------------------------------------------------ gauges
class Bar(W.QFrame):
    def __init__(self):
        super().__init__()
        self.f, self.color, self.marker = 0.0, OK, None
        self.setFixedHeight(6)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rtl = self.layoutDirection() == Qt.RightToLeft
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(LINE))
        p.drawRoundedRect(0, 0, w, h, 3, 3)
        if self.f > 0:
            p.setBrush(QtGui.QColor(self.color))
            fw = max(h, w * self.f)
            p.drawRoundedRect(QtCore.QRectF(w - fw if rtl else 0, 0, fw, h), 3, 3)
        if self.marker is not None:
            x = w * self.marker
            x = w - x if rtl else x
            p.setPen(QtGui.QPen(QtGui.QColor(ACCENT), 2))
            p.drawLine(QtCore.QPointF(x, -2), QtCore.QPointF(x, h + 2))


class Spark(W.QWidget):
    """A tiny history graph (about two minutes), drawn left to right like any graph."""
    def __init__(self, n=120):
        super().__init__()
        self.setFixedHeight(22)
        self.setLayoutDirection(Qt.LeftToRight)
        self.vals = deque(maxlen=n)
        self.color = ACCENT

    def push(self, v, color):
        self.vals.append(max(0.0, min(1.0, v)))
        self.color = color
        self.update()

    def paintEvent(self, e):
        if len(self.vals) < 2:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height() - 2
        n = self.vals.maxlen
        step = w / float(n - 1)
        pts = [QtCore.QPointF(w - (len(self.vals) - 1 - i) * step, h - v * (h - 3) + 1) for i, v in enumerate(self.vals)]
        path = QtGui.QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        fill = QtGui.QPainterPath(path)
        fill.lineTo(pts[-1].x(), h + 1)
        fill.lineTo(pts[0].x(), h + 1)
        fill.closeSubpath()
        c = QtGui.QColor(self.color)
        g = QtGui.QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QtGui.QColor(c.red(), c.green(), c.blue(), 70))
        g.setColorAt(1, QtGui.QColor(c.red(), c.green(), c.blue(), 0))
        p.fillPath(fill, g)
        p.setPen(QtGui.QPen(c, 1.3))
        p.drawPath(path)


class Gauge(W.QWidget):
    """One resource: name, value, bar (blue tick = the limit you set) and a short history graph."""
    def __init__(self, caption, icon_name="cpu"):
        super().__init__()
        lay = W.QVBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(4)
        row = W.QHBoxLayout()
        row.setSpacing(6)
        ic = W.QLabel()
        ic.setPixmap(icon_pixmap(icon_name, MUTED, 14))
        self.cap = W.QLabel(caption)
        self.cap.setObjectName("big")
        self.word = W.QLabel("")
        self.num = W.QLabel("")
        self.num.setObjectName("muted")
        self.num.setLayoutDirection(Qt.LeftToRight)
        row.addWidget(ic)
        row.addWidget(self.cap)
        row.addWidget(self.word)
        row.addStretch(1)
        row.addWidget(self.num)
        self.bar = Bar()
        self.spark = Spark()
        lay.addLayout(row)
        lay.addWidget(self.bar)
        lay.addWidget(self.spark)

    def set(self, used, total, num_text, marker=None):
        f = max(0.0, min(1.0, used / total if total else 0))
        color, word = (OK, "") if f < 0.6 else (WARN, "עמוס") if f < 0.85 else (BAD, "כמעט מלא")
        self.word.setText(word)
        self.word.setStyleSheet("font-weight:600; font-size:9pt; color:%s;" % color)
        self.num.setText(num_text)
        self.bar.f, self.bar.color = f, color
        self.bar.marker = (marker / total) if (marker and total) else None
        self.bar.update()
        self.spark.push(f, color)


# ------------------------------------------------------------------ chips and pills
CHIP_COLORS = {"ok": (OK, "#1f3524"), "bad": (BAD, "#3b2325"), "warn": (WARN, "#3a2f18"), "info": (ACCENT, "#233350"), "muted": (MUTED, "#2f3135")}


class Chip(W.QLabel):
    """A small status pill: 'הושלם 1:32', 'נכשל', 'ממתין'."""
    def __init__(self, text, kind="muted", icon_name=None):
        super().__init__(text)
        fg, bg = CHIP_COLORS.get(kind, CHIP_COLORS["muted"])
        self.setStyleSheet("background:%s; color:%s; border-radius:9px; padding:1px 9px; font-size:9pt; font-weight:600;" % (bg, fg))
        self.setAlignment(Qt.AlignCenter)


class FlowLayout(W.QLayout):
    """Wraps its items onto several lines (used for the example pills). Respects right-to-left."""
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self._sp = spacing

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QtCore.QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QtCore.QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        rtl = self.parentWidget() is not None and self.parentWidget().layoutDirection() == Qt.RightToLeft
        x, y, line_h = rect.x(), rect.y(), 0
        rows = [[]]
        for it in self.items:
            w = it.sizeHint().width()
            if x + w > rect.right() + 1 and rows[-1]:
                x = rect.x()
                y += line_h + self._sp
                line_h = 0
                rows.append([])
            rows[-1].append((it, x, y))
            x += w + self._sp
            line_h = max(line_h, it.sizeHint().height())
        if not test:
            for row in rows:
                for it, rx, ry in row:
                    sz = it.sizeHint()
                    px = rect.right() - (rx - rect.x()) - sz.width() + 1 if rtl else rx
                    it.setGeometry(QtCore.QRect(QtCore.QPoint(px, ry), sz))
        return y + line_h - rect.y()


# ------------------------------------------------------------------ toast
class Toast(W.QFrame):
    """A small message that appears at the bottom of the window and fades away (feedback without dialogs)."""
    KINDS = {"ok": ("check", OK), "bad": ("alert", BAD), "info": ("info", ACCENT), "warn": ("alert", WARN)}

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        h = W.QHBoxLayout(self)
        h.setContentsMargins(12, 8, 10, 8)
        h.setSpacing(8)
        self.ic = W.QLabel()
        self.msg = W.QLabel()
        self.act = W.QPushButton()
        self.act.setObjectName("flat")
        self.act.setCursor(Qt.PointingHandCursor)
        h.addWidget(self.ic)
        h.addWidget(self.msg)
        h.addWidget(self.act)
        self.fx = W.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.anim = QtCore.QPropertyAnimation(self.fx, b"opacity", self)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade)
        self.anim.finished.connect(self._done)
        self._act_fn = None
        self.act.clicked.connect(self._on_act)
        self.hide()

    def show_message(self, text, kind="info", action=None, fn=None, ms=4200):
        name, color = self.KINDS.get(kind, self.KINDS["info"])
        self.ic.setPixmap(icon_pixmap(name, color, 16))
        self.msg.setText(text)
        self.act.setVisible(bool(action))
        self.act.setText(action or "")
        self._act_fn = fn
        self.adjustSize()
        self.place()
        self.anim.stop()
        self.fx.setOpacity(1.0)
        self.show()
        self.raise_()
        self.timer.start(ms)

    def place(self):
        p = self.parentWidget()
        if p:
            self.move((p.width() - self.width()) // 2, p.height() - self.height() - 44)

    def fade(self):
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()

    def _done(self):
        if self.fx.opacity() < 0.05:
            self.hide()

    def _on_act(self):
        self.timer.stop()
        self.hide()
        if self._act_fn:
            self._act_fn()


# ------------------------------------------------------------------ model list rows
class ModelDelegate(W.QStyledItemDelegate):
    """Draws the left list like an IDE project tree: caption rows, icon + name, a running dot and a count pill."""
    def sizeHint(self, option, index):
        kind = index.data(ROLE_KIND)
        return QtCore.QSize(option.rect.width(), 26 if kind == "caption" else 30)

    def paint(self, p, option, index):
        kind = index.data(ROLE_KIND) or "item"
        rtl = option.direction == Qt.RightToLeft
        r = option.rect.adjusted(4, 1, -4, -1)
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        align = Qt.AlignVCenter | (Qt.AlignRight if rtl else Qt.AlignLeft)
        if kind == "caption":
            f = p.font()
            f.setPointSizeF(8.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(r.adjusted(8, 8, -8, 0), align, index.data(Qt.DisplayRole))
            p.restore()
            return
        if kind == "sep":
            p.setPen(QtGui.QColor(LINE))
            y = r.center().y()
            p.drawLine(r.left() + 6, y, r.right() - 6, y)
            p.restore()
            return
        sel = bool(option.state & W.QStyle.State_Selected)
        hov = bool(option.state & W.QStyle.State_MouseOver)
        if sel or hov:
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(SELECT if sel else LINE))
            p.drawRoundedRect(r, 4, 4)
        ic = index.data(Qt.DecorationRole)
        x_start = r.right() - 8 if rtl else r.left() + 8
        if isinstance(ic, QtGui.QIcon):
            pm = ic.pixmap(QtCore.QSize(18, 18), QtGui.QIcon.Normal)
            ix = x_start - 18 if rtl else x_start
            p.drawPixmap(ix, r.center().y() - 9, pm)
            x_start = ix - 9 if rtl else ix + 18 + 9
        # end side: running dot + count pill
        end = r.left() + 8 if rtl else r.right() - 8
        run, wait, cnt = index.data(ROLE_RUN) or 0, index.data(ROLE_WAIT) or 0, index.data(ROLE_COUNT) or 0
        pills = []
        if run:
            pills.append((str(run), OK, "#1f3524"))
        if wait:
            pills.append((str(wait), MUTED, "#393b40"))
        if cnt and not run and not wait:
            pills.append((str(cnt), MUTED, "#35373b"))
        f = p.font()
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        fm = QtGui.QFontMetrics(f)
        for text, fg, bg in pills:
            wpx = max(20, fm.horizontalAdvance(text) + 12)
            rect = QtCore.QRect(end if rtl else end - wpx, r.center().y() - 9, wpx, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(bg))
            p.drawRoundedRect(rect, 9, 9)
            p.setPen(QtGui.QColor(fg))
            p.drawText(rect, Qt.AlignCenter, text)
            end = end + wpx + 4 if rtl else end - wpx - 4
        f.setPointSizeF(10)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QtGui.QColor("#ffffff" if sel else TEXT))
        if rtl:
            tr = QtCore.QRect(end, r.top(), x_start - end, r.height())
        else:
            tr = QtCore.QRect(x_start, r.top(), end - x_start, r.height())
        txt = QtGui.QFontMetrics(f).elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, max(10, tr.width()))
        p.drawText(tr, align, txt)
        p.restore()


# ------------------------------------------------------------------ status bar pieces
class Seg(W.QWidget):
    """A status-bar segment: small icon + text."""
    def __init__(self, icon_name=None, text=""):
        super().__init__()
        h = W.QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(5)
        self.ic = W.QLabel()
        self.lbl = W.QLabel(text)
        self.lbl.setLayoutDirection(Qt.LeftToRight)
        if icon_name:
            self.ic.setPixmap(icon_pixmap(icon_name, MUTED, 13))
            h.addWidget(self.ic)
        h.addWidget(self.lbl)

    def set(self, text, color=None):
        self.lbl.setText(text)
        self.lbl.setStyleSheet("color:%s;" % color if color else "")


class Dot(W.QLabel):
    def __init__(self, size=9):
        super().__init__()
        self.setFixedSize(size, size)
        self.size_ = size

    def set(self, color):
        self.setStyleSheet("background:%s; border-radius:%dpx;" % (color, self.size_ // 2))


class TaskWidget(W.QFrame):
    """Background task indicator (like an IDE): what is running, a progress bar from the typical duration, click to open it."""
    clicked = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        h = W.QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(8)
        self.lbl = W.QLabel("אין עבודות פעילות")
        self.lbl.setObjectName("muted")
        self.bar = W.QProgressBar()
        self.bar.setFixedWidth(96)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        h.addWidget(self.lbl)
        h.addWidget(self.bar)
        self.job = None

    def set_job(self, j, extra=0):
        self.job = j
        if not j:
            self.lbl.setText("אין עבודות פעילות")
            self.bar.setVisible(False)
            return
        name = j["name"] if len(j["name"]) < 26 else j["name"][:24] + "…"
        more = "  (+%d)" % extra if extra else ""
        typ = j.get("typical_s")
        el = j.get("elapsed", 0)
        if typ and j.get("state") == "running":
            left = max(0, typ - el)
            self.lbl.setText("%s%s  •  נשארו כ-%d שנ'" % (name, more, round(left)))
            self.bar.setRange(0, 100)
            self.bar.setValue(min(95, int(100 * el / typ)))
        else:
            self.lbl.setText("%s%s  •  %d שנ'" % (name, more, el))
            self.bar.setRange(0, 0)
        self.bar.setVisible(True)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.job)


# ------------------------------------------------------------------ command palette
class Palette(W.QDialog):
    """Ctrl+K: type to jump to a model or run an action. Items are (label, icon_name, hint, callable)."""
    def __init__(self, parent, items):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.items = items
        self.setLayoutDirection(Qt.RightToLeft)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = W.QFrame()
        box.setObjectName("palette")
        outer.addWidget(box)
        v = W.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 6)
        v.setSpacing(0)
        self.edit = W.QLineEdit()
        self.edit.setPlaceholderText("חפש מודל או פעולה…")
        self.edit.textChanged.connect(self.refilter)
        self.edit.installEventFilter(self)
        v.addWidget(self.edit)
        self.list = W.QListWidget()
        self.list.setIconSize(QtCore.QSize(18, 18))
        self.list.itemActivated.connect(self.run_item)
        self.list.itemClicked.connect(self.run_item)
        v.addWidget(self.list)
        foot = W.QLabel("↑↓ לבחירה   Enter להפעלה   Esc לסגירה")
        foot.setObjectName("muted")
        foot.setContentsMargins(12, 6, 12, 0)
        v.addWidget(foot)
        self.resize(520, 380)
        self.refilter("")

    def refilter(self, text):
        t = (text or "").strip().lower()
        self.list.clear()
        for label, ic, hint, fn in self.items:
            if t and t not in label.lower() and t not in (hint or "").lower():
                continue
            it = W.QListWidgetItem(icon(ic, SUB, 18), "  " + label + (("      " + hint) if hint else ""))
            it.setData(Qt.UserRole, fn)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if self.list.currentItem():
                    self.run_item(self.list.currentItem())
                return True
        return super().eventFilter(obj, ev)

    def run_item(self, it):
        fn = it.data(Qt.UserRole)
        self.close()
        if fn:
            QtCore.QTimer.singleShot(0, fn)

    def popup(self):
        p = self.parentWidget()
        g = p.geometry()
        self.move(p.mapToGlobal(QtCore.QPoint((g.width() - self.width()) // 2, 70)))
        self.show()
        self.edit.setFocus()


class MessageView(W.QTextBrowser):
    """Chat message text, Markdown or plain. Every paragraph gets its direction from the majority script (see rtltext.py), so a Hebrew sentence that
    starts with an English product name is still laid out right-to-left. Height follows the content; no scrollbars; text stays selectable."""

    def __init__(self, text="", markdown=False, max_width=720, muted=False, bold=False):
        super().__init__()
        self._max = max_width
        if bold:
            f = self.document().defaultFont()
            f.setBold(True)
            self.document().setDefaultFont(f)
        self.setFrameShape(W.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(True)
        self.setSizePolicy(W.QSizePolicy.Preferred, W.QSizePolicy.Minimum)
        self.document().setDocumentMargin(0)
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Link, QtGui.QColor("#6ea0ff"))
        self.setPalette(pal)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; color: %s; selection-background-color: %s; }" % (SUB if muted else TEXT, SELECT))
        self.viewport().setCursor(Qt.IBeamCursor)
        self.set_content(text, markdown)

    def set_content(self, text, markdown=False):
        from .rtltext import apply_directions
        doc = self.document()
        if markdown:
            doc.setMarkdown(text)
        else:
            doc.setPlainText(text)
        apply_directions(doc)
        self._fit(max(60, self.width()))
        self.updateGeometry()

    def _natural_width(self):
        """Width of the longest paragraph without wrapping. Measured on a copy, so the visible document keeps its wrapping width."""
        probe = self.document().clone()
        probe.setTextWidth(-1)
        return int(probe.idealWidth()) + 3

    def _fit(self, width):
        doc = self.document()
        if abs(doc.textWidth() - width) > 0.5:
            doc.setTextWidth(width)
        h = int(doc.size().height() + 1.5)
        if h != self.height() or self.minimumHeight() != h:
            self.setFixedHeight(h)

    def sizeHint(self):
        w = min(self._max, self._natural_width())
        probe = self.document().clone()
        probe.setTextWidth(w)
        return QtCore.QSize(w, int(probe.size().height() + 1.5))

    def showEvent(self, e):
        super().showEvent(e)
        self._fit(max(60, self.viewport().width()))

    def minimumSizeHint(self):
        return QtCore.QSize(60, self.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit(max(60, self.viewport().width()))
