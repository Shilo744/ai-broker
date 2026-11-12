"""Shortcuts to the program get the window's AppUserModelID, so a pinned taskbar button and the running window are one button (Windows only; works on copies in a temp folder,
never on the owner's real shortcuts).   python tests/test_winshell.py"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if sys.platform != "win32":
    print("winshell test: skipped (not Windows)")
    sys.exit(0)
from aibroker import winshell   # noqa: E402

bad = 0


def check(name, cond):
    global bad
    bad += not cond
    print(("PASS " if cond else "FAIL ") + name, flush=True)


def make(path, target, args):
    ps = "$l=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $l.TargetPath='%s'; $l.Arguments='%s'; $l.Save()" % (path, target, args)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True, creationflags=0x08000000)


d = tempfile.mkdtemp()
ours, other = os.path.join(d, "ours.lnk"), os.path.join(d, "other.lnk")
make(ours, os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe"), "-m aibroker.gui")
make(other, r"C:\Windows\notepad.exe", "")
check("a new shortcut has no AppUserModelID", winshell.shortcut_app_id(ours) == "")
changed = winshell.fix_app_shortcuts(ROOT, [d])
check("the shortcut to this program is fixed", changed == [ours] and winshell.shortcut_app_id(ours) == winshell.APP_ID)
check("a shortcut to another program is left alone", winshell.shortcut_app_id(other) == "")
check("the target and arguments survive", winshell.link_target(ours)[1] == "-m aibroker.gui" and winshell.link_target(ours)[0].lower().endswith("pythonw.exe"))
check("running it again changes nothing", winshell.fix_app_shortcuts(ROOT, [d]) == [])
print("winshell test: %d failed" % bad)
sys.exit(1 if bad else 0)
