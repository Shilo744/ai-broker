"""Things the window can switch on and off for the owner, so nothing needs a .bat file: start with Windows, and connect Claude Code to the broker.
Both only happen when the owner clicks the button in Advanced and confirms."""
import os
import shutil
import subprocess
from pathlib import Path

from . import paths, winutil

STARTUP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
LINK = STARTUP_DIR / "AI Broker.lnk"
SKILL_SRC = paths.ROOT / "skill" / "ai-broker"
SKILL_DST = Path.home() / ".claude" / "skills" / "ai-broker"


def _ps(script, timeout=30):
    return subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script], capture_output=True, text=True, timeout=timeout,
                          creationflags=winutil.NO_WINDOW)


# ---------------------------------------------------------------- start with Windows
def autostart_enabled():
    return LINK.exists()


def set_autostart(on):
    """A shortcut in the user's Startup folder that opens the broker window hidden in the tray (it starts the background service too)."""
    if not on:
        try:
            LINK.unlink()
        except OSError:
            pass
        return not LINK.exists()
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    exe = str(paths.VENV_PYW if paths.VENV_PYW.exists() else paths.VENV_PY)
    ico = paths.ROOT / "assets" / "ai-broker.ico"
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='-m aibroker.gui --hidden';$s.WorkingDirectory='%s';"
              "$s.IconLocation='%s';$s.Description='AI Broker (starts hidden in the tray)';$s.Save()" % (LINK, exe, paths.ROOT, ico))
    _ps(script)
    return LINK.exists()


# ---------------------------------------------------------------- Claude Code connection
def _claude():
    return shutil.which("claude") or "claude"


def claude_registered():
    """True / False, or None when the claude command could not be run."""
    try:
        r = subprocess.run([_claude(), "mcp", "get", "ai-broker"], capture_output=True, text=True, timeout=40, creationflags=winutil.NO_WINDOW)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


def register_claude():
    """Same as register.bat: add the MCP server for this Windows user (all projects) and copy the skill file. Returns (ok, message)."""
    py = str(paths.VENV_PY)
    launcher = str(paths.ROOT / "mcp_launch.py")
    try:
        r = subprocess.run([_claude(), "mcp", "add", "ai-broker", "--scope", "user", "--env", "AIJOB_REQUESTER=claude", "--", py, launcher],
                           capture_output=True, text=True, timeout=60, creationflags=winutil.NO_WINDOW)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "claude mcp add failed")[-300:]
        SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SKILL_SRC, SKILL_DST, dirs_exist_ok=True)
        return True, "מחובר. סשנים חדשים של Claude Code יראו את הכלים של ה-broker."
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, repr(e)


def unregister_claude():
    try:
        subprocess.run([_claude(), "mcp", "remove", "ai-broker", "--scope", "user"], capture_output=True, text=True, timeout=60, creationflags=winutil.NO_WINDOW)
        if SKILL_DST.exists():
            shutil.rmtree(SKILL_DST, ignore_errors=True)
        return True, "נותק."
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, repr(e)
