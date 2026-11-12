"""Windows taskbar identity for the window. When the owner pins a running Python program to the taskbar, Windows pins python.exe with the generic Python icon unless the window says
how to start itself and which icon it has: the window properties RelaunchCommand, RelaunchIconResource and RelaunchDisplayNameResource (and the AppUserModelID, which groups the
window with the pinned button). Only ctypes, no extra package. Every failure is silent: this is cosmetic."""
import ctypes
import sys
from ctypes import wintypes


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


class _KEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort), ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


def _guid(s):
    import uuid
    u = uuid.UUID(s)
    d = u.bytes
    return _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*d[8:]))


_APPUSERMODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
KEYS = {"relaunch_command": 2, "relaunch_icon": 3, "relaunch_name": 4, "id": 5}


def _store(hwnd):
    shell32 = ctypes.windll.shell32
    shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    ps = ctypes.c_void_p()
    iid = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")                       # IPropertyStore
    if shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(ps)) != 0 or not ps.value:
        return None
    vtbl = ctypes.cast(ctypes.cast(ps, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return ps, vtbl


def set_window_identity(hwnd, app_id, command, icon, name):
    """Gives the window its own taskbar identity. Returns True when the properties were stored."""
    if sys.platform != "win32":
        return False
    try:
        got = _store(int(hwnd))
        if not got:
            return False
        ps, vtbl = got
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_KEY), ctypes.POINTER(_PROPVARIANT))(vtbl[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        fmt = _guid(_APPUSERMODEL)
        keep = []
        ok = True
        for k, text in (("id", app_id), ("relaunch_command", command), ("relaunch_icon", icon), ("relaunch_name", name)):
            buf = ctypes.create_unicode_buffer(text)
            keep.append(buf)
            pv = _PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, ctypes.c_void_p).value, 0)           # VT_LPWSTR
            ok = set_value(ps, ctypes.byref(_KEY(fmt, KEYS[k])), ctypes.byref(pv)) == 0 and ok
        ok = commit(ps) == 0 and ok
        release(ps)
        return ok
    except Exception:
        return False


def read_window_property(hwnd, key):
    """For the tests: the string stored under one of KEYS, or None."""
    got = _store(int(hwnd))
    if not got:
        return None
    ps, vtbl = got
    get_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_KEY), ctypes.POINTER(_PROPVARIANT))(vtbl[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    pv = _PROPVARIANT()
    r = get_value(ps, ctypes.byref(_KEY(_guid(_APPUSERMODEL), KEYS[key])), ctypes.byref(pv))
    out = ctypes.wstring_at(pv.p) if r == 0 and pv.vt == 31 and pv.p else None
    release(ps)
    return out


# ---------------------------------------------------------------- shortcuts (.lnk): give them the window's AppUserModelID so a pinned button and the running window are ONE button
_CLSID_SHELLLINK = "{00021401-0000-0000-C000-000000000046}"
_IID_PERSISTFILE = "{0000010B-0000-0000-C000-000000000046}"
_IID_PROPSTORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
APP_ID = "AIBroker.Window"


def _open_link(path):
    """(IPersistFile pointer, its vtable, IPropertyStore pointer, its vtable) of a loaded shortcut, or None."""
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    pf = ctypes.c_void_p()
    clsid, iid = _guid(_CLSID_SHELLLINK), _guid(_IID_PERSISTFILE)
    if ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pf)) != 0 or not pf.value:
        return None
    pf_vt = ctypes.cast(ctypes.cast(pf, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    load = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)(pf_vt[5])
    if load(pf, path, 2) != 0:                                   # STGM_READWRITE
        return None
    qi = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(pf_vt[0])
    ps = ctypes.c_void_p()
    psid = _guid(_IID_PROPSTORE)
    if qi(pf, ctypes.byref(psid), ctypes.byref(ps)) != 0 or not ps.value:
        return None
    ps_vt = ctypes.cast(ctypes.cast(ps, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return pf, pf_vt, ps, ps_vt


def shortcut_app_id(path):
    """The AppUserModelID stored in a shortcut ('' when it has none), or None when it cannot be read."""
    if sys.platform != "win32":
        return None
    try:
        got = _open_link(path)
        if not got:
            return None
        _pf, _pf_vt, ps, ps_vt = got
        get_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_KEY), ctypes.POINTER(_PROPVARIANT))(ps_vt[5])
        pv = _PROPVARIANT()
        r = get_value(ps, ctypes.byref(_KEY(_guid(_APPUSERMODEL), KEYS["id"])), ctypes.byref(pv))
        return ctypes.wstring_at(pv.p) if r == 0 and pv.vt == 31 and pv.p else ""
    except Exception:
        return None


def set_shortcut_app_id(path, app_id=APP_ID):
    """Store the AppUserModelID in a shortcut. True when it was written."""
    if sys.platform != "win32":
        return False
    try:
        got = _open_link(path)
        if not got:
            return False
        pf, pf_vt, ps, ps_vt = got
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_KEY), ctypes.POINTER(_PROPVARIANT))(ps_vt[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(ps_vt[7])
        save = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)(pf_vt[6])
        buf = ctypes.create_unicode_buffer(app_id)
        pv = _PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, ctypes.c_void_p).value, 0)
        ok = set_value(ps, ctypes.byref(_KEY(_guid(_APPUSERMODEL), KEYS["id"])), ctypes.byref(pv)) == 0
        ok = commit(ps) == 0 and ok
        return save(pf, path, 1) == 0 and ok
    except Exception:
        return False


def link_target(path):
    """(target, arguments) of a shortcut, through the system's own scripting object (no parsing of the .lnk format here)."""
    import subprocess
    try:
        script = "$l=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $l.TargetPath; $l.Arguments" % path.replace("'", "''")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=20, creationflags=0x08000000).stdout.splitlines()
        return (out[0] if out else ""), (out[1] if len(out) > 1 else "")
    except Exception:
        return "", ""


def fix_app_shortcuts(root, folders=None):
    """Every shortcut to this program (pinned to the taskbar, on the desktop, in the Start menu, in Startup) that has no AppUserModelID or a different one gets ours, so Windows puts the
    pinned button and the running window together. Returns the list of shortcuts it changed."""
    import os
    changed = []
    if sys.platform != "win32":
        return changed
    appdata = os.environ.get("APPDATA", "")
    folders = folders or [os.path.join(appdata, "Microsoft", "Internet Explorer", "Quick Launch", "User Pinned", "TaskBar"), os.path.join(os.path.expanduser("~"), "Desktop"),
                          os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"), os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")]
    key = str(root).lower().replace("/", "\\")
    for d in folders:
        try:
            names = [n for n in os.listdir(d) if n.lower().endswith(".lnk")]
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if shortcut_app_id(p) == APP_ID:
                continue
            target, args = link_target(p)
            if key in (target + " " + args).lower().replace("/", "\\") and ("aibroker" in args.lower() or target.lower().endswith("ai_broker.bat")):
                if set_shortcut_app_id(p):
                    changed.append(p)
    return changed
