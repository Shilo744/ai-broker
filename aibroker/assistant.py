"""The assistant inside the window: Claude Code run HEADLESS (no terminal anywhere), one process per message, conversation kept with --resume.
Tools it may use without asking are listed in SAFE; anything else is denied by Claude Code and comes back in `permission_denials`, which the window turns into an
in-app approval question (Approve / Decline). An approved action is allowed for the next turn only (exact Bash command or exact tool name).
Session-only flags: nothing in the owner's Claude settings is changed."""
import json
import os
import shutil
import subprocess
import time

from PySide6 import QtCore

from . import paths, winutil

PROMPT = paths.ROOT / "skill" / "ai-broker" / "AGENT_PROMPT.md"
MCP_JSON = paths.ROOT / "mcp.json"
HISTORY = paths.HOME / "assistant_chat.json"

BROKER = "mcp__ai-broker__"
SAFE = [BROKER + n for n in ("queue_status", "resources", "job_status", "job_output", "job_history", "list_job_types", "get_limits", "hardware_profile", "submit_job", "rerun_job")] + [
    "Read", "Glob", "Grep", "WebSearch", "WebFetch",
    "Bash(nvidia-smi:*)", "Bash(dir:*)", "Bash(ls:*)", "Bash(du:*)", "Bash(where:*)",
    "Edit(docs/MODELS.md)", "Write(docs/MODELS.md)", "Edit(DOWNLOADS.md)", "Write(DOWNLOADS.md)"]

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "default": None}

FRIENDLY = {
    BROKER + "queue_status": "בודק את התור", BROKER + "resources": "בודק את המשאבים", BROKER + "job_status": "בודק עבודה", BROKER + "job_output": "קורא את הפלט של עבודה",
    BROKER + "hardware_profile": "בודק את החומרה של המחשב", BROKER + "job_history": "קורא את ההיסטוריה", BROKER + "list_job_types": "בודק אילו סוגי עבודות יש", BROKER + "get_limits": "בודק את המגבלות", BROKER + "submit_job": "שולח עבודה",
    BROKER + "rerun_job": "מריץ עבודה שוב", BROKER + "cancel_job": "מבטל עבודה", BROKER + "move_job": "משנה סדר בתור", BROKER + "set_limits": "משנה מגבלות",
    BROKER + "pause_queue": "עוצר את התור", BROKER + "resume_queue": "ממשיך את התור", BROKER + "set_playing_mode": "משנה מצב ״אני משחק״",
    "Read": "קורא קובץ", "Glob": "מחפש קבצים", "Grep": "מחפש בקבצים", "WebSearch": "מחפש באינטרנט", "WebFetch": "קורא דף אינטרנט", "Bash": "בודק את המחשב", "PowerShell": "בודק את המחשב",
    "Edit": "מעדכן קובץ", "Write": "כותב קובץ"}


def claude_exe():
    return shutil.which("claude") or "claude"


def describe_denial(d):
    """Plain Hebrew description of something Claude asked to do and was not allowed to."""
    name = d.get("tool_name", "")
    inp = d.get("tool_input") or {}
    if name == "Bash":
        return "להריץ בפקודה: " + str(inp.get("command", ""))[:300]
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


def write_mcp_config(requester="claude (עוזר)"):
    """The MCP config for ONE assistant turn: the broker's tools plus its permission handler (AIBROKER_ASSISTANT=1). Other agents never get the handler."""
    try:
        base = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        srv = base["mcpServers"]["ai-broker"]
    except (OSError, ValueError, KeyError):
        base = {"mcpServers": {"ai-broker": {"command": str(paths.VENV_PY), "args": [str(paths.ROOT / "mcp_launch.py")]}}}
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
        cmd = [claude_exe(), "-p", self.message, "--output-format", "stream-json", "--verbose", "--mcp-config", str(write_mcp_config()), "--strict-mcp-config",
               "--permission-prompt-tool", BROKER + "approve",
               "--append-system-prompt-file", str(PROMPT), "--add-dir", str(paths.ROOT / "output"), "--max-turns", "30",
               "--allowedTools", ",".join(SAFE + self.extra_allow)]
        if self.session:
            cmd += ["--resume", self.session]
        mid = MODELS.get(self.model)
        if mid:
            cmd += ["--model", mid]
        result = {"ok": False, "error": "", "session": self.session, "denials": [], "text": ""}
        try:
            env = dict(os.environ, AIJOB_REQUESTER="claude (עוזר)", PYTHONUTF8="1")
            self.proc = subprocess.Popen(cmd, cwd=str(paths.ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                         creationflags=winutil.NO_WINDOW, encoding="utf-8", errors="replace")
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
                    result["error"] = "הלך יותר מדי זמן"
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
