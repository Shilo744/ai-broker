"""The resource strip under the header must never squeeze a gauge below its own minimum width, at any window width the window allows. When it did, the bar ran into
the name next to it (seen in a Hebrew window about 1280 px wide: the strip needs about 1350). Needs no service and no GPU:
  python tests/test_strip.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AIBROKER_LANG"] = "he"
import sandbox                                   # noqa: E402,F401  (first: a throw-away data folder)
from PySide6 import QtWidgets as W               # noqa: E402
from PySide6.QtCore import Qt                    # noqa: E402
from aibroker import theme                       # noqa: E402
from aibroker.kit import ResStrip                # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    bad += not cond
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:300]) if extra and not cond else ""), flush=True)


app = W.QApplication([])
app.setStyle("Fusion")
f = app.font()
f.setPointSize(10)
app.setFont(f)
app.setStyleSheet(theme.QSS)
MIN_WINDOW = 960                                  # gui.Main.setMinimumSize(960, 620)

for direction, label in ((Qt.RightToLeft, "right to left"), (Qt.LeftToRight, "left to right")):
    app.setLayoutDirection(direction)
    root = W.QWidget()                            # like the real window it sets its own minimum size, so Qt does not keep it as wide as the strip would like
    root.setMinimumSize(MIN_WINDOW, 40)
    lay = W.QVBoxLayout(root)
    lay.setContentsMargins(0, 0, 0, 0)
    strip = ResStrip()
    lay.addWidget(strip)
    strip.ram.set(26, 63, "26 / 63 GB", marker=58)
    strip.gpu.set(0.0, 16, "0.0 / 16 GB", marker=16)
    strip.disk.set(1, 100, "1%")
    strip.cpu.set(8, 100, "8%")
    strip.set_summary("עד RAM 58 GB · GPU 16 GB · 8 עבודות במקביל")
    root.show()
    problems, always, inside, order, seen_summary, flicker = [], True, True, [], False, False
    for width in range(MIN_WINDOW, 2601, 20):          # up to a width where even a wide font (another system) has room for everything
        root.resize(width, 40)
        app.processEvents()
        app.processEvents()
        for name in ("ram", "gpu", "disk", "cpu"):
            g = getattr(strip, name)
            if g.isHidden():
                continue
            if g.width() < g.minimumSizeHint().width():
                problems.append("%s squeezed by %d px at window width %d" % (name, g.minimumSizeHint().width() - g.width(), width))
            kids = [g.ic.geometry(), g.cap.geometry(), g.bar.geometry(), g.num.geometry()]
            for i in range(len(kids)):
                for j in range(i + 1, len(kids)):
                    if kids[i].intersects(kids[j]):
                        problems.append("%s: parts %d and %d overlap at window width %d" % (name, i, j, width))
            if not strip.rect().contains(g.geometry()):
                inside = False
                problems.append("%s sticks out of the strip at window width %d" % (name, width))
        always = always and not strip.ram.isHidden() and not strip.gpu.isHidden() and not strip.lim_btn.isHidden()
        if not strip.lim_btn.geometry().isValid() or not strip.rect().contains(strip.lim_btn.geometry()):
            problems.append("the Limits button sticks out at window width %d" % width)
        shown = (not strip.lim_sum.isHidden(), not strip.cpu.isHidden(), not strip.disk.isHidden())
        order.append(shown)
        if seen_summary and not shown[0]:
            flicker = True                        # the summary came back and went away again as the window got wider
        seen_summary = seen_summary or shown[0]
    check("%s: no gauge is squeezed, no parts overlap, nothing sticks out (960..2600 px)" % label, not problems, problems[:3])
    check("%s: RAM, GPU and the Limits button are always there" % label, always)
    check("%s: at the smallest window the summary gives way" % label, order[0][0] is False, order[0])
    check("%s: at a wide window everything is shown" % label, order[-1] == (True, True, True), order[-1])
    check("%s: the summary does not come and go as the window grows" % label, not flicker)
    # (summary, CPU, disk): the summary goes first, then CPU, disk last. So the summary shown means CPU shown, and CPU shown means disk shown
    check("%s: they give way in the order summary, CPU, disk" % label, all((a[1] or not a[0]) and (a[2] or not a[1]) for a in order), order)
    root.close()

print("strip test: %d failed" % bad)
sys.exit(1 if bad else 0)
