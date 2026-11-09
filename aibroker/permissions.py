"""What the in-window assistant (Claude) asks to do, said in plain Hebrew, how risky it is, and what each permission level does about it.

The assistant runs headless (`claude -p`). Claude Code asks the broker's `approve` tool whenever a tool call is not pre-allowed; the broker calls analyze() and
decide() here, and only asks the owner (an in-chat card) when the chosen level says so. The owner picks the level himself in the assistant header.

risk:  safe     only reads information
       change   creates / changes files, downloads, installs, runs a program
       danger   deletes, stops programs, or changes the system (always asks, except in the free level it still asks)
       blocked  never allowed at any level (formatting disks, registry/security changes, the owner's Claude settings, remote code ...)
"""
import json
import re
from dataclasses import dataclass, field

LEVELS = (
    ("careful", "זהיר", "שואל על כל פקודה במחשב",
     "Claude שואל אותך על כל פקודה שהוא מריץ במחשב, גם אם היא רק קוראת מידע. בלי לשאול הוא רשאי: לקרוא קבצים, לחפש באינטרנט ולנהל את התור."),
    ("normal", "רגיל", "קריאה חופשית, שינויים באישור",
     "פקודות שרק קוראות מידע (כמה מקום פנוי בדיסק, כרטיס המסך, רשימת קבצים) רצות בלי לשאול. הורדות, התקנות, יצירה ושינוי של קבצים: שואל אותך."),
    ("free", "חופשי", "עושה מה שצריך, בלי לשאול",
     "Claude יכול להוריד, להתקין ולכתוב קבצים בלי לשאול אותך. מחיקות ועצירת תוכנות עדיין דורשות אישור, ופעולות מסוכנות במיוחד (פירמוט, רישום ומערכת, ההגדרות של Claude עצמו) חסומות תמיד."),
)
DEFAULT_LEVEL = "normal"
LEVEL_KEYS = tuple(k for k, *_ in LEVELS)


@dataclass
class Verdict:
    risk: str                       # safe | change | danger | blocked
    kind: str                       # read | write | download | install | delete | system | run | tool
    text: str                       # plain Hebrew: what it does
    detail: str = ""                # the raw command, file or tool input (shown under "show the command")
    shell: bool = False
    why: str = ""                   # plain Hebrew: why this needs asking
    tags: list = field(default_factory=list)


RISK_LABEL = {"safe": "קריאה בלבד", "change": "שינוי", "danger": "מסוכן", "blocked": "חסום"}
KIND_WHY = {
    "write": "הפעולה יוצרת או משנה קבצים במחשב.",
    "download": "הפעולה מורידה קובץ מהאינטרנט למחשב.",
    "install": "הפעולה מתקינה או מריצה תוכנה.",
    "delete": "הפעולה מוחקת קבצים, ואי אפשר לבטל אותה.",
    "system": "הפעולה משנה משהו במערכת או עוצרת תוכנה.",
    "run": "הפעולה מריצה תוכנה או סקריפט.",
    "tool": "הפעולה משנה משהו (בתור, בהגדרות או בקבצים).",
}

HEB = re.compile("[֐-׿]")


def _flags():
    return re.IGNORECASE


# ---------------------------------------------------------------- shell commands (PowerShell, Bash, cmd)
BLOCKED = (
    (r"\b(format-volume|clear-disk|initialize-disk|remove-partition|new-partition|diskpart|bcdedit|vssadmin|wbadmin|cipher\s+/w)\b", "פירמוט או שינוי של דיסקים"),
    (r"\bformat\s+[a-z]:", "פירמוט דיסק"),
    (r"\b(set-executionpolicy|set-mppreference|add-mppreference|disable-windowsoptionalfeature|disable-computerrestore|uninstall-windowsfeature)\b", "שינוי הגדרות אבטחה"),
    (r"\b(stop-computer|restart-computer|shutdown(\.exe)?\s+/|logoff)\b|\bshutdown\s+-", "כיבוי או הפעלה מחדש של המחשב"),
    (r"\breg(\.exe)?\s+(delete|add|import|load|unload|restore)\b", "שינוי רישום המערכת (registry)"),
    (r"\b(set|new|remove)-itemproperty\b.*\bhk(lm|cu|ey_)", "שינוי רישום המערכת (registry)"),
    (r"\b(net\s+user|net\s+localgroup|netsh\s+advfirewall|schtasks\s+/(create|change|delete)|sc(\.exe)?\s+(delete|config|create)|new-service|set-service)\b", "שינוי משתמשים, חומת אש או שירותים"),
    (r"\b(icacls|takeown)\b", "שינוי הרשאות של קבצים"),
    (r"\.claude(\\|/)(settings|\.credentials|plugins|projects)|\.claude\.json|\bclaude\s+mcp\s+(add|remove)", "ההגדרות של Claude עצמו"),
    (r"\b(iex|invoke-expression)\b.*(iwr|irm|invoke-webrequest|invoke-restmethod|downloadstring|curl|wget)|\bdownloadstring\b|-encodedcommand|\s-enc\s|frombase64string", "הרצת קוד שהורד או מוסתר"),
    (r"\[microsoft\.win32\.registry\]|\bregistrykey\b", "שינוי רישום המערכת (registry)"),
    (r"\brm\s+(-[a-z]+\s+)+(/|/\*|~/?|~/\*|\$home/?|\$home/\*)(\s|$)", "מחיקה של דיסק או תיקיית משתמש שלמה"),
)
SYSTEM_PATH = re.compile(r"(\b[a-z]:\\(windows|program files( \(x86\))?|programdata)\b|%systemroot%|%windir%|\$env:(systemroot|windir|programfiles|programdata)|\bsystem32\b)", re.I)
DRIVE_ROOT = re.compile(r"(?<![\w\\])[a-z]:\\?(?=['\"\s;|)]|$)", re.I)
USER_ROOT = re.compile(r"\b[a-z]:\\users\\[^\\'\"\s]+\\?(?=['\"\s;|)]|$)", re.I)

DELETE = re.compile(r"\b(remove-item|ri|rm|del|erase|rmdir|rd|unlink|clear-content|clear-recyclebin)\b|\s-delete\b|\[(system\.)?io\.(file|directory)\]::delete", re.I)
KILL = re.compile(r"\b(stop-process|taskkill|kill|stop-service|spps|pkill)\b", re.I)
DOWNLOAD = re.compile(r"\b(downloadfile|downloaddata|new-object\s+(system\.)?net\.webclient|invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|start-bitstransfer|bitsadmin|aria2c|yt-dlp|huggingface-cli|hf\s+download|git\s+clone|pip\s+download|certutil.*-urlcache)\b", re.I)
INSTALL = re.compile(r"\b(pip3?\s+install|python3?\s+-m\s+pip\s+install|winget\s+(install|upgrade)|choco\s+(install|upgrade)|scoop\s+install|npm\s+(i|install|ci)|conda\s+install|msiexec|expand-archive|7z|7za|unzip)\b", re.I)
# starting a program is never "reading": no exception, whatever the rest of the command looks like
RUN_HARD = re.compile(r"(\bstart-process\b|\bstart\s+\"?[a-z]|(^|[;|&\s])&\s*['\"$(]|\.bat\b|\.cmd\b|\.msi\b|\.ps1\b|\bpowershell(\.exe)?\s|\bcmd(\.exe)?\s+/c|\binvoke-command\b|\badd-type\b|\[(system\.)?diagnostics\.process\]::start)", re.I)
# running a script or an interpreter: only the known read-only forms ("python --version", "git status") are exempt
RUN = re.compile(r"(\.exe\b|\bpython3?\b|\bpy\b\s|\bnode\b|\bgit\s+(pull|push|checkout|reset|clean|commit|merge|rebase|stash|apply))", re.I)
WRITE = re.compile(r"(\b(set-content|add-content|out-file|tee-object|new-item|ni|copy-item|cp|copy|move-item|mv|move|rename-item|ren|mkdir|md|export-csv|export-clixml|set-itemproperty|new-itemproperty|attrib|touch|tee|sed\s+-i|setenvironmentvariable)\b|\[(system\.)?io\.(file|directory)\]::(write|move|copy|create|append|replace)|(^|[^|>-])>>?\s*[\"'$\w.~/\\])", re.I)

READ_ONLY_FIRST = re.compile(
    r"^(get-[\w-]+|test-path|test-connection|select-[\w-]+|where-object|sort-object|measure-object|group-object|format-[\w-]+|out-string|out-host|out-null|"
    r"write-output|write-host|convertto-[\w-]+|convertfrom-[\w-]+|resolve-path|split-path|join-path|compare-object|foreach-object|%|\?|nvidia-smi|dir|ls|type|cat|gc|gci|gps|gwmi|"
    r"gcim|gm|gcm|whoami|hostname|systeminfo|tasklist|where|where\.exe|echo|ver|vol|cd|set-location|pushd|popd|pwd|head|tail|wc|du|df|free|uname|which|find|grep|rg|"
    r"stat|file|tree|sort|uniq|cut|tr|date|true|false|\[math\]::\w+|\[system\.[\w.]+\]::\w+|\$[\w:]+\s*=|\$[\w:.]+)$", re.I)
READ_ONLY_FULL = (
    re.compile(r"^(python3?|py)\s+(-v|--version|-c\s+['\"]import\s+[\w.]+;?\s*print\([^)]*\)['\"])", re.I),
    re.compile(r"^(pip3?|python3?\s+-m\s+pip)\s+(list|show|freeze|--version|check)\b", re.I),
    re.compile(r"^git\s+(status|log|diff|branch|rev-parse|remote\s+-v|--version|show|ls-files)\b", re.I),
    re.compile(r"^(node|npm|npx|winget|blender|ollama|ffmpeg|7z)\s+(-v|--version|list|version)\b", re.I),
    re.compile(r"^wmic\s+.*\bget\b", re.I),
    re.compile(r"^fsutil\s+volume\s+diskfree", re.I),
    re.compile(r"^nvidia-smi\b", re.I),
)

URL = re.compile(r"https?://[^\s'\"<>)]+", re.I)
QUOTED_PATH = re.compile(r"['\"]([a-z]:\\[^'\"]+|[~/.][^'\"]*[/\\][^'\"]*|\\\\[^'\"]+)['\"]", re.I)


def _strip_blocks(s):
    """Collapse quotes, (...), [...] and {...} (nested too) into the placeholder X: what is inside them is checked by the risk patterns on the original text."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"'[^']*'|\"[^\"]*\"", "X", s)
        s = re.sub(r"\{[^{}]*\}", "X", s)
        s = re.sub(r"\[[^\[\]]*\]", "X", s)
        s = re.sub(r"\([^()]*\)", "X", s)
    return s


def _segments(cmd):
    flat = _strip_blocks(cmd)
    return [x.strip() for x in re.split(r"[;|\n]+|&&|\|\||(?<![&])&(?![&])", flat) if x.strip()]


def _is_read_only(cmd):
    """Every part of the command only reads information."""
    segs = _segments(cmd)
    if not segs:
        return False
    for seg in segs:
        seg = seg.strip().lstrip("(").strip()
        first = re.split(r"\s+", seg, maxsplit=1)[0] if seg else ""
        if READ_ONLY_FIRST.match(first) or seg.startswith(("X", "$")):
            continue
        if any(r.match(seg) for r in READ_ONLY_FULL):
            continue
        return False
    return True


def _target(cmd):
    m = URL.search(cmd)
    if m:
        u = m.group(0).rstrip(".,;")
        host = re.sub(r"^https?://", "", u).split("/")[0]
        name = u.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return host, name
    return None, None


def _first_path(cmd):
    m = QUOTED_PATH.search(cmd)
    return m.group(1) if m else ""


def _describe_shell(cmd, desc, kind):
    """One short plain-Hebrew sentence. Claude's own Hebrew description wins; otherwise it is built from what the command contains."""
    if desc and HEB.search(desc):
        return desc.strip().rstrip(".")[:180]
    low = cmd.lower()
    parts = []
    if re.search(r"get-psdrive|get-volume|logicaldisk|diskfree|freespace|\bdf\b|get-disk|get-partition", low):
        parts.append("בודק כמה מקום פנוי יש בדיסקים")
    if re.search(r"nvidia-smi|videocontroller|get-pnpdevice", low):
        parts.append("בודק את כרטיס המסך והזיכרון שלו")
    if re.search(r"win32_(computersystem|processor|physicalmemory|operatingsystem)|systeminfo|get-computerinfo|get-ciminstance|get-wmiobject|gwmi", low) and not parts:
        parts.append("בודק את החומרה של המחשב")
    if re.search(r"get-process|tasklist|\bgps\b", low):
        parts.append("בודק אילו תוכנות רצות")
    if re.search(r"get-childitem|\bgci\b|\bdir\b|(^|[\s;|])ls\b|\bfind\b|\btree\b|get-item\b", low):
        p = _first_path(cmd)
        parts.append("מציג רשימת קבצים" + (" בתיקייה %s" % p if p else ""))
    if re.search(r"get-content|\btype\b|\bcat\b|\bgc\b|select-string|\bgrep\b|\brg\b|\bhead\b|\btail\b", low):
        parts.append("קורא קובץ")
    if re.search(r"pip3?\s+(list|show|freeze)|python3?\s+(-v|--version)|\bpy\s+-", low):
        parts.append("בודק את סביבת Python")
    if re.search(r"git\s+(status|log|diff|branch|show)", low):
        parts.append("בודק את מצב ה-git")
    if kind == "download":
        host, name = _target(cmd)
        parts.append("מוריד קובץ מהאינטרנט" + (" (%s מ-%s)" % (name, host) if host and name else (" מ-%s" % host if host else "")))
    if kind == "install":
        m = re.search(r"(?:pip3?|python3?\s+-m\s+pip)\s+install\s+([^\s;|&]+)", cmd, re.I) or re.search(r"(?:winget|choco|scoop|conda)\s+install\s+([^\s;|&]+)", cmd, re.I) or re.search(r"npm\s+(?:i|install)\s+([^\s;|&]+)", cmd, re.I)
        parts.append("מתקין תוכנה" + (" (%s)" % m.group(1) if m else ""))
    if kind == "delete":
        p = _first_path(cmd)
        parts.append("מוחק קבצים" + (" (%s)" % p if p else ""))
    if kind == "write" and not parts:
        p = _first_path(cmd)
        parts.append("יוצר או משנה קבצים" + (" (%s)" % p if p else ""))
    if kind == "run" and not parts:
        parts.append("מריץ תוכנה או סקריפט")
    if kind == "system" and not parts:
        parts.append("עוצר תוכנה או משנה משהו במערכת")
    if not parts:
        parts.append("מריץ פקודה במחשב")
    return " ו".join(dict.fromkeys(parts))


def analyze_shell(cmd, desc=""):
    cmd = cmd or ""
    low = cmd.lower()
    for rx, what in BLOCKED:
        if re.search(rx, low, re.I | re.S):
            return Verdict("blocked", "system", "פעולה מסוכנת במיוחד: %s" % what, cmd, True, "הפעולה הזאת חסומה בכל רמות ההרשאה.")
    if DELETE.search(cmd):
        if SYSTEM_PATH.search(cmd) or DRIVE_ROOT.search(cmd) or USER_ROOT.search(cmd):
            return Verdict("blocked", "delete", "מחיקה של תיקיית מערכת, משתמש או דיסק שלם", cmd, True, "הפעולה הזאת חסומה בכל רמות ההרשאה.")
        return Verdict("danger", "delete", _describe_shell(cmd, desc, "delete"), cmd, True, KIND_WHY["delete"])
    if KILL.search(cmd):
        return Verdict("danger", "system", _describe_shell(cmd, desc, "system"), cmd, True, KIND_WHY["system"])
    if DOWNLOAD.search(cmd):
        return Verdict("change", "download", _describe_shell(cmd, desc, "download"), cmd, True, KIND_WHY["download"])
    if INSTALL.search(cmd):
        return Verdict("change", "install", _describe_shell(cmd, desc, "install"), cmd, True, KIND_WHY["install"])
    if WRITE.search(re.sub(r"\d?>>?\s*(\$null|nul|&\d)", " ", cmd, flags=re.I)):
        return Verdict("change", "write", _describe_shell(cmd, desc, "write"), cmd, True, KIND_WHY["write"])
    if RUN_HARD.search(cmd) or (RUN.search(cmd) and not _is_read_only(cmd)):
        return Verdict("change", "run", _describe_shell(cmd, desc, "run"), cmd, True, KIND_WHY["run"])
    if _is_read_only(cmd):
        return Verdict("safe", "read", _describe_shell(cmd, desc, "read"), cmd, True)
    return Verdict("change", "run", _describe_shell(cmd, desc, "run"), cmd, True, KIND_WHY["run"])


# ---------------------------------------------------------------- every other tool
BROKER = "mcp__ai-broker__"
BROKER_READ = {"queue_status", "resources", "job_status", "job_output", "job_history", "list_job_types", "get_limits", "hardware_profile", "wait_for_job", "approve"}
BROKER_RUN = {"submit_job", "rerun_job"}
BROKER_CONTROL = {"cancel_job", "move_job", "hold_job", "release_job", "pause_queue", "resume_queue", "set_playing_mode", "set_limits"}
BROKER_TEXT = {
    "queue_status": "בודק את התור", "resources": "בודק את המשאבים", "job_status": "בודק עבודה", "job_output": "קורא את הפלט של עבודה", "job_history": "קורא את ההיסטוריה",
    "list_job_types": "בודק אילו סוגי עבודות יש", "get_limits": "בודק את המגבלות", "hardware_profile": "בודק את החומרה של המחשב", "wait_for_job": "ממתין לסיום עבודה",
    "submit_job": "מוסיף עבודה לתור", "rerun_job": "מריץ עבודה שוב", "cancel_job": "מבטל עבודה", "move_job": "משנה סדר בתור", "hold_job": "מחזיק עבודה בתור", "release_job": "משחרר עבודה",
    "pause_queue": "עוצר את התור", "resume_queue": "ממשיך את התור", "set_playing_mode": "משנה את מצב ״אני משחק״", "set_limits": "משנה את המגבלות של RAM ו-GPU",
}
PROTECTED_FILE = re.compile(r"(\.claude[\\/]|\.claude\.json|[\\/]windows[\\/]|[\\/]system32[\\/]|[\\/]program files|[\\/]startup[\\/]|\.ssh[\\/]|CLAUDE\.md$)", re.I)


def analyze(tool, tin):
    tin = tin or {}
    if tool in ("Bash", "PowerShell"):
        return analyze_shell(str(tin.get("command", "")), str(tin.get("description", "") or ""))
    if tool in ("Read", "Glob", "Grep", "NotebookRead", "LS"):
        what = {"Read": "קורא קובץ", "Glob": "מחפש קבצים", "Grep": "מחפש בתוך קבצים"}.get(tool, "קורא קבצים")
        p = tin.get("file_path") or tin.get("path") or tin.get("pattern") or ""
        return Verdict("safe", "read", what + (": %s" % p if p else ""), str(p))
    if tool in ("WebSearch", "WebFetch"):
        q = tin.get("query") or tin.get("url") or ""
        return Verdict("safe", "read", ("מחפש באינטרנט" if tool == "WebSearch" else "קורא דף אינטרנט") + (": %s" % q if q else ""), str(q))
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        p = str(tin.get("file_path") or tin.get("notebook_path") or "")
        if PROTECTED_FILE.search(p):
            return Verdict("blocked", "write", "שינוי קובץ מערכת או הגדרות של Claude: %s" % p, p, False, "הפעולה הזאת חסומה בכל רמות ההרשאה.")
        return Verdict("change", "write", "כותב קובץ: %s" % p if p else "כותב קובץ", p, False, KIND_WHY["write"])
    if tool.startswith(BROKER):
        name = tool[len(BROKER):]
        txt = BROKER_TEXT.get(name, name)
        det = json.dumps(tin, ensure_ascii=False)[:300] if tin else ""
        if name in BROKER_READ:
            return Verdict("safe", "read", txt, det)
        if name in BROKER_RUN:
            return Verdict("change", "run", txt, det, False, "")
        return Verdict("change", "tool", txt, det, False, KIND_WHY["tool"])
    det = json.dumps(tin, ensure_ascii=False)[:300] if tin else ""
    return Verdict("change", "tool", "משתמש בכלי ״%s״" % tool, det, False, KIND_WHY["tool"])


def decide(level, v):
    """'allow' (runs silently), 'ask' (an in-chat card) or 'deny' (never)."""
    if v.risk == "blocked":
        return "deny"
    if level not in LEVEL_KEYS:
        level = DEFAULT_LEVEL
    if v.risk == "danger":
        return "ask"
    if level == "careful":
        if v.shell:
            return "ask"
        if v.kind == "tool":
            return "ask"
        if v.kind == "write":
            return "ask"
        return "allow"
    if level == "normal":
        if v.risk == "safe":
            return "allow"
        if v.kind == "run" and not v.shell and v.tags == []:
            return "allow" if v.text in (BROKER_TEXT["submit_job"], BROKER_TEXT["rerun_job"]) else "ask"
        return "ask"
    return "allow"                  # free: everything except danger (above) and blocked
