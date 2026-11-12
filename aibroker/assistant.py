"""The assistant inside the window: Claude Code run HEADLESS (no terminal anywhere), one process per message, conversation kept with --resume.
Tools it may use without asking are listed in SAFE; anything else is denied by Claude Code and comes back in `permission_denials`, which the window turns into an
in-app approval question (Approve / Decline). An approved action is allowed for the next turn only (exact Bash command or exact tool name).
Session-only flags: nothing in the owner's Claude settings is changed."""
import json
import os
import shutil
import subprocess
import sys
import time

from PySide6 import QtCore

from .i18n import T
from . import i18n, osutil, paths

PROMPT = paths.ROOT / "skill" / "ai-broker" / "AGENT_PROMPT.md"
MCP_JSON = paths.ROOT / "mcp.json"
HISTORY = paths.HOME / "assistant_chat.json"

BROKER = "mcp__ai-broker__"
SAFE = [BROKER + n for n in ("queue_status", "resources", "job_status", "job_output", "job_history", "list_job_types", "get_limits", "hardware_profile", "list_model_packs", "submit_job", "rerun_job", "run_workflow", "save_workflow", "list_workflows")] + [
    "Read", "Glob", "Grep", "WebSearch", "WebFetch",
    "Bash(nvidia-smi:*)", "Bash(dir:*)", "Bash(ls:*)", "Bash(du:*)", "Bash(where:*)",
    "Edit(docs/MODELS.md)", "Write(docs/MODELS.md)", "Edit(DOWNLOADS.md)", "Write(DOWNLOADS.md)"]

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "default": None}

FRIENDLY = {
    BROKER + "queue_status": T("בודק את התור"), BROKER + "resources": T("בודק את המשאבים"), BROKER + "job_status": T("בודק עבודה"), BROKER + "job_output": T("קורא את הפלט של עבודה"),
    BROKER + "hardware_profile": T("בודק את החומרה של המחשב"), BROKER + "job_history": T("קורא את ההיסטוריה"), BROKER + "list_job_types": T("בודק אילו סוגי עבודות יש"), BROKER + "get_limits": T("בודק את המגבלות"), BROKER + "submit_job": T("שולח עבודה"), BROKER + "run_workflow": T("מריץ שרשרת עבודות שמורה"), BROKER + "save_workflow": T("שומר שרשרת עבודות"), BROKER + "list_workflows": T("בודק אילו שרשראות עבודות שמורות יש"),
    BROKER + "rerun_job": T("מריץ עבודה שוב"), BROKER + "cancel_job": T("מבטל עבודה"), BROKER + "move_job": T("משנה סדר בתור"), BROKER + "set_limits": T("משנה מגבלות"),
    BROKER + "pause_queue": T("עוצר את התור"), BROKER + "resume_queue": T("ממשיך את התור"), BROKER + "set_playing_mode": T("משנה מצב ״אני משחק״"),
    "Read": T("קורא קובץ"), "Glob": T("מחפש קבצים"), "Grep": T("מחפש בקבצים"), "WebSearch": T("מחפש באינטרנט"), "WebFetch": T("קורא דף אינטרנט"), "Bash": T("בודק את המחשב"), "PowerShell": T("בודק את המחשב"),
    "Edit": T("מעדכן קובץ"), "Write": T("כותב קובץ")}


def claude_exe():
    return shutil.which("claude") or "claude"


def describe_denial(d):
    """Plain Hebrew description of something Claude asked to do and was not allowed to."""
    name = d.get("tool_name", "")
    inp = d.get("tool_input") or {}
    if name == "Bash":
        return T("להריץ בפקודה: ") + str(inp.get("command", ""))[:300]
    if name.startswith(BROKER):
        return FRIENDLY.get(name, name) + (" (%s)" % json.dumps(inp, ensure_ascii=False)[:160] if inp else "")
    if name in ("Edit", "Write"):
        return "%s: %s" % (FRIENDLY.get(name, name), inp.get("file_path", ""))
    return "%s %s" % (FRIENDLY.get(name, name), json.dumps(inp, ensure_ascii=False)[:200])


def allow_rule(d):
    name = d.get("tool_name", "")
    inp = d.get("tool_input") or {}
    if name == "Bash" and inp.get("command"):
        return "Bash(%s)" % inp["command"]
    if name in ("Edit", "Write") and inp.get("file_path"):
        return "%s(%s)" % (name, inp["file_path"])
    return name


def write_mcp_config(requester=T("claude (עוזר)")):
    """The MCP config for ONE assistant turn: the broker's tools plus its permission handler (AIBROKER_ASSISTANT=1). Other agents never get the handler."""
    try:
        base = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        srv = base["mcpServers"]["ai-broker"]
    except (OSError, ValueError, KeyError):
        base = {"mcpServers": {"ai-broker": {"command": str(paths.PYTHON), "args": [str(paths.ROOT / "mcp_launch.py")]}}}
        srv = base["mcpServers"]["ai-broker"]
    env = dict(srv.get("env") or {})
    env.update(AIJOB_REQUESTER=requester, AIBROKER_ASSISTANT="1")
    for k in ("AIBROKER_HOME", "AIBROKER_PORT"):              # tests run a separate broker: the handler must talk to the same one
        if os.environ.get(k):
            env[k] = os.environ[k]
    srv["env"] = env
    paths.HOME.mkdir(parents=True, exist_ok=True)
    out = paths.HOME / "assistant_mcp.json"
    out.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    return out


def write_prompt():
    """The assistant's instructions plus the language of the window: the owner reads the answers, so Claude answers in the language he chose."""
    base = PROMPT.read_text(encoding="utf-8")
    if i18n.lang() == "en":
        base = base.replace("Speak to the owner in short, plain Hebrew", "Speak to the owner in short, plain English")
        base += ("\n\nLanguage: the owner chose English for this program. Answer in English. Write the `description` argument of every Bash / PowerShell call "
                 "in plain English (one short sentence), not in Hebrew.\n")
    shell = "PowerShell" if osutil.IS_WIN else "bash / zsh"
    system_name = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")
    base += "\n\nThis computer runs %s. Shell commands you write use %s syntax and this system's paths.\n" % (system_name, shell)
    base += ("\n\nYour own program on this computer (paths are real, use them): program folder %s (the code, `DESIGN.md`, `catalog/packs.json`, shipped `jobtypes/*.json`); "
             "the owner's own job types go in %s (a new `<id>.json` there is picked up at the next `list_job_types` call, no restart, and it survives updates); "
             "saved workflows live in %s; the job outputs are under %s.\n") % (paths.ROOT, paths.USER_TYPES_DIR, paths.HOME / "workflows", paths.load_config().get("output_root", paths.ROOT / "output"))
    paths.HOME.mkdir(parents=True, exist_ok=True)
    out = paths.HOME / "assistant_prompt.md"
    out.write_text(base, encoding="utf-8")
    return out


class Worker(QtCore.QThread):
    """Runs ONE turn: `claude -p <message> --output-format stream-json ...` without any window, emits each stream event."""
    event = QtCore.Signal(dict)
    finished_turn = QtCore.Signal(dict)

    def __init__(self, message, session, model, extra_allow):
        super().__init__()
        self.message, self.session, self.model, self.extra_allow = message, session, model, list(extra_allow or [])
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def run(self):
        cmd = [claude_exe(), "-p", self.message, "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--mcp-config", str(write_mcp_config()), "--strict-mcp-config",
               "--permission-prompt-tool", BROKER + "approve",
               "--append-system-prompt-file", str(write_prompt()), "--add-dir", str(paths.ROOT / "output"), "--max-turns", "30",
               "--allowedTools", ",".join(SAFE + self.extra_allow)]
        if self.session:
            cmd += ["--resume", self.session]
        mid = MODELS.get(self.model)
        if mid:
            cmd += ["--model", mid]
        result = {"ok": False, "error": "", "session": self.session, "denials": [], "text": ""}
        try:
            env = dict(os.environ, AIJOB_REQUESTER=T("claude (עוזר)"), PYTHONUTF8="1")
            self.proc = subprocess.Popen(cmd, cwd=str(paths.ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                         creationflags=osutil.NO_WINDOW, encoding="utf-8", errors="replace")
            t0 = time.time()
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("session_id"):
                    result["session"] = ev["session_id"]
                if ev.get("type") == "result":
                    result.update(ok=not ev.get("is_error"), denials=ev.get("permission_denials") or [], text=ev.get("result") or "")
                    if ev.get("is_error"):
                        result["error"] = str(ev.get("result") or "")[:400]
                self.event.emit(ev)
                if time.time() - t0 > 900:
                    self.proc.kill()
                    result["error"] = T("הלך יותר מדי זמן")
                    break
            self.proc.wait(timeout=10)
            if not result["ok"] and not result["error"]:
                result["error"] = (self.proc.stderr.read() or "")[-400:] if not self.cancelled else "בוטל"
        except Exception as e:
            result["error"] = "%r" % (e,)
        self.finished_turn.emit(result)


def load_history():
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"session": None, "messages": []}


def save_history(h):
    try:
        paths.HOME.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(h, ensure_ascii=False)[-400000:], encoding="utf-8")
    except OSError:
        pass
